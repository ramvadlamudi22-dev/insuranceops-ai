#!/usr/bin/env python3
"""Migration safety lint.

Scans Alembic migration files for patterns known to cause production issues:
- CREATE INDEX without CONCURRENTLY on existing tables
- ADD COLUMN with NOT NULL and no server_default
- DROP COLUMN / DROP TABLE (should use expand-migrate-contract)
- Data manipulation (INSERT/UPDATE/DELETE) mixed with DDL in upgrade()

Phase 2A: advisory mode only (exits 0 with warnings).
Phase 2B+: can be switched to strict mode (exits 1 on findings).

Usage:
    python scripts/check_migrations.py [--strict] [path/to/migrations/versions/]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Patterns that indicate potential safety issues
# Each pattern has: regex, description, severity

# Matches op.create_index without postgresql_concurrently=True
# BUT only when the index is NOT inside a create_table block
_CREATE_INDEX_RE = re.compile(r"op\.create_index\s*\(", re.MULTILINE)
_CONCURRENTLY_RE = re.compile(r"postgresql_concurrently\s*=\s*True")

# Matches add_column with nullable=False and no server_default
_ADD_COLUMN_RE = re.compile(r"op\.add_column\s*\(", re.MULTILINE)
_NULLABLE_FALSE_RE = re.compile(r"nullable\s*=\s*False")
_SERVER_DEFAULT_RE = re.compile(r"server_default\s*=")

# Matches drop_column or drop_table
_DROP_COLUMN_RE = re.compile(r"op\.drop_column\s*\(", re.MULTILINE)
_DROP_TABLE_RE = re.compile(r"op\.drop_table\s*\(", re.MULTILINE)

# Matches raw SQL data manipulation in upgrade()
_DATA_MANIP_RE = re.compile(
    r"(?:INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM)", re.IGNORECASE | re.MULTILINE
)

# Matches op.execute with DML
_OP_EXECUTE_RE = re.compile(r"op\.execute\s*\(", re.MULTILINE)

# Initial migration marker (these get special treatment)
_INITIAL_MIGRATION_RE = re.compile(r"down_revision\s*[=:]\s*(?:Union\[str,\s*None\]\s*=\s*)?None\b")


@dataclass
class Finding:
    """A single lint finding."""

    file: str
    line: int
    pattern: str
    message: str
    severity: str = "warning"


@dataclass
class CheckResult:
    """Result of checking a single migration file."""

    file: str
    findings: list[Finding] = field(default_factory=list)
    is_initial: bool = False


def _extract_upgrade_body(content: str) -> str | None:
    """Extract the body of the upgrade() function."""
    match = re.search(r"^def upgrade\(\).*?:\n(.*?)(?=^def |\Z)", content, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1)
    return None


def _is_inside_create_table(content: str, match_start: int) -> bool:
    """Check if a position is inside an op.create_table(...) call."""
    # Look backwards from the match position for an unclosed create_table
    before = content[:match_start]
    # Find the last create_table opening
    last_create = before.rfind("op.create_table(")
    if last_create == -1:
        return False
    # Count parens from that point to our position
    segment = content[last_create:match_start]
    depth = 0
    for ch in segment:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
    # If depth > 0, we're still inside the create_table call
    return depth > 0


def _get_line_number(content: str, pos: int) -> int:
    """Get 1-based line number for a character position."""
    return content[:pos].count("\n") + 1


def _check_create_index_without_concurrently(
    content: str, upgrade_body: str, filepath: str, is_initial: bool
) -> list[Finding]:
    """Check for CREATE INDEX without CONCURRENTLY on existing tables."""
    findings: list[Finding] = []

    if is_initial:
        # Initial migration creates all tables fresh; indexes in create_table are safe
        return findings

    # Find all create_index calls in the upgrade body
    offset = content.find(upgrade_body)
    for match in _CREATE_INDEX_RE.finditer(upgrade_body):
        abs_pos = offset + match.start()

        # Skip if inside a create_table block (those are safe)
        if _is_inside_create_table(content, abs_pos):
            continue

        # Check if this specific create_index has postgresql_concurrently=True
        # Look at the full statement (up to the next line with just ')' or next op.)
        stmt_start = match.start()
        # Find the closing of this call - look for balanced parens
        depth = 0
        stmt_end = stmt_start
        for i in range(stmt_start, len(upgrade_body)):
            if upgrade_body[i] == "(":
                depth += 1
            elif upgrade_body[i] == ")":
                depth -= 1
                if depth == 0:
                    stmt_end = i + 1
                    break

        stmt_text = upgrade_body[stmt_start:stmt_end]
        if not _CONCURRENTLY_RE.search(stmt_text):
            line = _get_line_number(content, abs_pos)
            findings.append(
                Finding(
                    file=filepath,
                    line=line,
                    pattern="CREATE_INDEX_WITHOUT_CONCURRENTLY",
                    message=(
                        "op.create_index() on an existing table without "
                        "postgresql_concurrently=True may hold a long lock"
                    ),
                )
            )

    return findings


def _check_add_column_not_null(
    content: str, upgrade_body: str, filepath: str, is_initial: bool
) -> list[Finding]:
    """Check for ADD COLUMN with NOT NULL and no server_default."""
    findings: list[Finding] = []

    if is_initial:
        return findings

    offset = content.find(upgrade_body)
    for match in _ADD_COLUMN_RE.finditer(upgrade_body):
        abs_pos = offset + match.start()

        # Extract the full add_column statement
        stmt_start = match.start()
        depth = 0
        stmt_end = stmt_start
        for i in range(stmt_start, len(upgrade_body)):
            if upgrade_body[i] == "(":
                depth += 1
            elif upgrade_body[i] == ")":
                depth -= 1
                if depth == 0:
                    stmt_end = i + 1
                    break

        stmt_text = upgrade_body[stmt_start:stmt_end]

        if _NULLABLE_FALSE_RE.search(stmt_text) and not _SERVER_DEFAULT_RE.search(stmt_text):
            line = _get_line_number(content, abs_pos)
            findings.append(
                Finding(
                    file=filepath,
                    line=line,
                    pattern="ADD_COLUMN_NOT_NULL_NO_DEFAULT",
                    message=(
                        "op.add_column() with nullable=False and no server_default "
                        "will lock the table for a full rewrite on large tables"
                    ),
                )
            )

    return findings


def _check_drop_operations(
    content: str, upgrade_body: str, filepath: str, is_initial: bool
) -> list[Finding]:
    """Check for DROP COLUMN or DROP TABLE in non-initial migrations."""
    findings: list[Finding] = []

    if is_initial:
        return findings

    offset = content.find(upgrade_body)

    for match in _DROP_COLUMN_RE.finditer(upgrade_body):
        abs_pos = offset + match.start()
        line = _get_line_number(content, abs_pos)
        findings.append(
            Finding(
                file=filepath,
                line=line,
                pattern="DROP_COLUMN",
                message=(
                    "op.drop_column() should follow expand-migrate-contract. "
                    "Ensure this is the 'contract' phase with prior expand and migrate steps."
                ),
            )
        )

    for match in _DROP_TABLE_RE.finditer(upgrade_body):
        # Skip if this is in a downgrade function
        abs_pos = offset + match.start()
        line = _get_line_number(content, abs_pos)
        findings.append(
            Finding(
                file=filepath,
                line=line,
                pattern="DROP_TABLE",
                message=(
                    "op.drop_table() is destructive. Ensure this follows "
                    "expand-migrate-contract discipline."
                ),
            )
        )

    return findings


def _check_data_manipulation(
    content: str, upgrade_body: str, filepath: str, is_initial: bool
) -> list[Finding]:
    """Check for DML mixed with DDL in upgrade()."""
    findings: list[Finding] = []

    if is_initial:
        return findings

    offset = content.find(upgrade_body)

    # Check for op.execute() with DML patterns
    for match in _OP_EXECUTE_RE.finditer(upgrade_body):
        # Get the statement content
        stmt_start = match.start()
        depth = 0
        stmt_end = stmt_start
        for i in range(stmt_start, len(upgrade_body)):
            if upgrade_body[i] == "(":
                depth += 1
            elif upgrade_body[i] == ")":
                depth -= 1
                if depth == 0:
                    stmt_end = i + 1
                    break

        stmt_text = upgrade_body[stmt_start:stmt_end]

        if _DATA_MANIP_RE.search(stmt_text):
            abs_pos = offset + match.start()
            line = _get_line_number(content, abs_pos)
            findings.append(
                Finding(
                    file=filepath,
                    line=line,
                    pattern="DML_IN_MIGRATION",
                    message=(
                        "Data manipulation (INSERT/UPDATE/DELETE) in a DDL migration. "
                        "Consider separating data migrations into their own idempotent script."
                    ),
                )
            )

    return findings


def check_migration_file(filepath: Path) -> CheckResult:
    """Check a single migration file for safety issues.

    Args:
        filepath: Path to the migration .py file.

    Returns:
        CheckResult with any findings.
    """
    content = filepath.read_text(encoding="utf-8")
    result = CheckResult(file=str(filepath))

    # Detect if this is the initial migration (down_revision = None)
    if _INITIAL_MIGRATION_RE.search(content):
        result.is_initial = True

    # Extract upgrade() body
    upgrade_body = _extract_upgrade_body(content)
    if upgrade_body is None:
        return result

    # Run all checks
    result.findings.extend(
        _check_create_index_without_concurrently(
            content, upgrade_body, str(filepath), result.is_initial
        )
    )
    result.findings.extend(
        _check_add_column_not_null(content, upgrade_body, str(filepath), result.is_initial)
    )
    result.findings.extend(
        _check_drop_operations(content, upgrade_body, str(filepath), result.is_initial)
    )
    result.findings.extend(
        _check_data_manipulation(content, upgrade_body, str(filepath), result.is_initial)
    )

    return result


def check_migrations_directory(migrations_dir: Path) -> list[CheckResult]:
    """Check all migration files in a directory.

    Args:
        migrations_dir: Path to the migrations/versions/ directory.

    Returns:
        List of CheckResult, one per file.
    """
    results: list[CheckResult] = []

    if not migrations_dir.exists():
        return results

    for filepath in sorted(migrations_dir.glob("*.py")):
        if filepath.name == "__pycache__":
            continue
        results.append(check_migration_file(filepath))

    return results


def format_findings(results: list[CheckResult]) -> str:
    """Format findings for human-readable output."""
    lines: list[str] = []
    total_findings = 0

    for result in results:
        if result.findings:
            for finding in result.findings:
                total_findings += 1
                lines.append(
                    f"  [{finding.severity.upper()}] {finding.file}:{finding.line} "
                    f"({finding.pattern}): {finding.message}"
                )

    if total_findings == 0:
        return "Migration safety check: no findings."

    header = f"Migration safety check: {total_findings} finding(s):\n"
    return header + "\n".join(lines)


def main() -> int:
    """Run the migration safety check.

    Returns:
        0 in advisory mode (always), 1 in strict mode if findings exist.
    """
    parser = argparse.ArgumentParser(description="Check Alembic migrations for unsafe patterns")
    parser.add_argument(
        "migrations_dir",
        nargs="?",
        default="migrations/versions",
        help="Path to the migrations/versions/ directory (default: migrations/versions)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any findings (Phase 2B+). Default is advisory mode.",
    )
    args = parser.parse_args()

    migrations_dir = Path(args.migrations_dir)
    if not migrations_dir.exists():
        print(f"Migrations directory not found: {migrations_dir}")
        return 1

    results = check_migrations_directory(migrations_dir)
    output = format_findings(results)
    print(output)

    total_findings = sum(len(r.findings) for r in results)

    if args.strict and total_findings > 0:
        print(f"\nStrict mode: failing with {total_findings} finding(s).")
        return 1

    if total_findings > 0:
        print("\nAdvisory mode: findings reported but not blocking.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
