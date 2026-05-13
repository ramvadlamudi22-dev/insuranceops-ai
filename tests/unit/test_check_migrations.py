"""Tests for the migration safety lint script."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

# Import the module under test
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from check_migrations import (  # noqa: E402
    CheckResult,
    check_migration_file,
    format_findings,
)


@pytest.fixture()
def tmp_migration(tmp_path: Path):
    """Factory fixture: write migration content to a temp file and return its path."""

    def _write(content: str, filename: str = "0002_test.py") -> Path:
        filepath = tmp_path / filename
        filepath.write_text(dedent(content), encoding="utf-8")
        return filepath

    return _write


class TestInitialMigrationSkipped:
    """Initial migrations (down_revision = None) should produce no findings."""

    def test_initial_migration_with_create_index_is_safe(self, tmp_migration):
        content = '''\
        """Initial."""
        from alembic import op
        import sqlalchemy as sa

        revision = "0001"
        down_revision = None

        def upgrade() -> None:
            op.create_table("users", sa.Column("id", sa.Integer(), primary_key=True))
            op.create_index("idx_users_name", "users", ["name"])

        def downgrade() -> None:
            op.drop_table("users")
        '''
        result = check_migration_file(tmp_migration(content))
        assert result.is_initial is True
        assert result.findings == []

    def test_initial_migration_with_union_type_annotation(self, tmp_migration):
        """Match the actual project style: Union[str, None] = None."""
        content = '''\
        """Initial."""
        from __future__ import annotations
        from typing import Sequence, Union
        from alembic import op
        import sqlalchemy as sa

        revision: str = "0001"
        down_revision: Union[str, None] = None
        branch_labels: Union[str, Sequence[str], None] = None

        def upgrade() -> None:
            op.create_table("t", sa.Column("id", sa.Integer(), primary_key=True))
            op.create_index("idx_t_col", "t", ["col"])

        def downgrade() -> None:
            op.drop_table("t")
        '''
        result = check_migration_file(tmp_migration(content))
        assert result.is_initial is True
        assert result.findings == []


class TestCreateIndexWithoutConcurrently:
    """Non-initial migrations creating indexes should warn without CONCURRENTLY."""

    def test_create_index_without_concurrently_warns(self, tmp_migration):
        content = '''\
        """Add index."""
        from alembic import op

        revision = "0002"
        down_revision = "0001"

        def upgrade() -> None:
            op.create_index("idx_docs_hash", "documents", ["content_hash"])

        def downgrade() -> None:
            op.drop_index("idx_docs_hash")
        '''
        result = check_migration_file(tmp_migration(content))
        assert result.is_initial is False
        assert len(result.findings) == 1
        assert result.findings[0].pattern == "CREATE_INDEX_WITHOUT_CONCURRENTLY"

    def test_create_index_with_concurrently_passes(self, tmp_migration):
        content = '''\
        """Add index."""
        from alembic import op

        revision = "0002"
        down_revision = "0001"

        def upgrade() -> None:
            op.create_index(
                "idx_docs_hash",
                "documents",
                ["content_hash"],
                postgresql_concurrently=True,
            )

        def downgrade() -> None:
            op.drop_index("idx_docs_hash")
        '''
        result = check_migration_file(tmp_migration(content))
        assert result.findings == []

    def test_create_index_inside_create_table_is_safe(self, tmp_migration):
        """Indexes created inside create_table are on new tables; no lock concern."""
        content = '''\
        """New table with index."""
        from alembic import op
        import sqlalchemy as sa

        revision = "0002"
        down_revision = "0001"

        def upgrade() -> None:
            op.create_table(
                "new_table",
                sa.Column("id", sa.Integer(), primary_key=True),
                sa.Column("name", sa.Text()),
            )
            op.create_index("idx_new_table_name", "new_table", ["name"])

        def downgrade() -> None:
            op.drop_table("new_table")
        '''
        # Note: this index is AFTER the create_table call, not inside it.
        # It's still on a table just created in this migration.
        # Our heuristic catches this as a warning since we can't track table creation
        # context perfectly. This is acceptable as advisory.
        result = check_migration_file(tmp_migration(content))
        # The index is outside the create_table() parentheses, so it triggers
        assert len(result.findings) == 1
        assert result.findings[0].pattern == "CREATE_INDEX_WITHOUT_CONCURRENTLY"


class TestAddColumnNotNull:
    """Non-initial migrations adding NOT NULL columns without defaults should warn."""

    def test_add_column_not_null_no_default_warns(self, tmp_migration):
        content = '''\
        """Add column."""
        from alembic import op
        import sqlalchemy as sa

        revision = "0002"
        down_revision = "0001"

        def upgrade() -> None:
            op.add_column("users", sa.Column("email", sa.Text(), nullable=False))

        def downgrade() -> None:
            op.drop_column("users", "email")
        '''
        result = check_migration_file(tmp_migration(content))
        assert len(result.findings) == 1
        assert result.findings[0].pattern == "ADD_COLUMN_NOT_NULL_NO_DEFAULT"

    def test_add_column_not_null_with_server_default_passes(self, tmp_migration):
        content = '''\
        """Add column."""
        from alembic import op
        import sqlalchemy as sa

        revision = "0002"
        down_revision = "0001"

        def upgrade() -> None:
            op.add_column(
                "users",
                sa.Column("email", sa.Text(), nullable=False, server_default=sa.text("''")),
            )

        def downgrade() -> None:
            op.drop_column("users", "email")
        '''
        result = check_migration_file(tmp_migration(content))
        assert result.findings == []

    def test_add_column_nullable_true_passes(self, tmp_migration):
        content = '''\
        """Add column."""
        from alembic import op
        import sqlalchemy as sa

        revision = "0002"
        down_revision = "0001"

        def upgrade() -> None:
            op.add_column("users", sa.Column("email", sa.Text(), nullable=True))

        def downgrade() -> None:
            op.drop_column("users", "email")
        '''
        result = check_migration_file(tmp_migration(content))
        # drop_column will trigger but add_column should not
        drop_findings = [f for f in result.findings if f.pattern == "ADD_COLUMN_NOT_NULL_NO_DEFAULT"]
        assert drop_findings == []


class TestDropOperations:
    """Non-initial migrations with DROP should warn."""

    def test_drop_column_warns(self, tmp_migration):
        content = '''\
        """Drop column."""
        from alembic import op

        revision = "0002"
        down_revision = "0001"

        def upgrade() -> None:
            op.drop_column("users", "legacy_field")

        def downgrade() -> None:
            pass
        '''
        result = check_migration_file(tmp_migration(content))
        findings = [f for f in result.findings if f.pattern == "DROP_COLUMN"]
        assert len(findings) == 1

    def test_drop_table_warns(self, tmp_migration):
        content = '''\
        """Drop table."""
        from alembic import op

        revision = "0002"
        down_revision = "0001"

        def upgrade() -> None:
            op.drop_table("old_table")

        def downgrade() -> None:
            pass
        '''
        result = check_migration_file(tmp_migration(content))
        findings = [f for f in result.findings if f.pattern == "DROP_TABLE"]
        assert len(findings) == 1


class TestDataManipulation:
    """Non-initial migrations with DML in op.execute should warn."""

    def test_insert_in_execute_warns(self, tmp_migration):
        content = '''\
        """Seed data."""
        from alembic import op

        revision = "0002"
        down_revision = "0001"

        def upgrade() -> None:
            op.execute("INSERT INTO config (key, value) VALUES ('ver', '1')")

        def downgrade() -> None:
            pass
        '''
        result = check_migration_file(tmp_migration(content))
        findings = [f for f in result.findings if f.pattern == "DML_IN_MIGRATION"]
        assert len(findings) == 1

    def test_update_in_execute_warns(self, tmp_migration):
        content = '''\
        """Backfill."""
        from alembic import op

        revision = "0002"
        down_revision = "0001"

        def upgrade() -> None:
            op.execute("UPDATE users SET active = true WHERE disabled_at IS NULL")

        def downgrade() -> None:
            pass
        '''
        result = check_migration_file(tmp_migration(content))
        findings = [f for f in result.findings if f.pattern == "DML_IN_MIGRATION"]
        assert len(findings) == 1

    def test_pure_ddl_execute_passes(self, tmp_migration):
        content = '''\
        """DDL only."""
        from alembic import op

        revision = "0002"
        down_revision = "0001"

        def upgrade() -> None:
            op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

        def downgrade() -> None:
            pass
        '''
        result = check_migration_file(tmp_migration(content))
        findings = [f for f in result.findings if f.pattern == "DML_IN_MIGRATION"]
        assert findings == []


class TestFormatFindings:
    """Test output formatting."""

    def test_no_findings_message(self):
        results = [CheckResult(file="test.py", findings=[])]
        output = format_findings(results)
        assert "no findings" in output

    def test_findings_formatted(self):
        from check_migrations import Finding

        results = [
            CheckResult(
                file="0002.py",
                findings=[
                    Finding(
                        file="0002.py",
                        line=10,
                        pattern="DROP_COLUMN",
                        message="test message",
                    )
                ],
            )
        ]
        output = format_findings(results)
        assert "1 finding" in output
        assert "DROP_COLUMN" in output
        assert "0002.py:10" in output


class TestExistingMigration:
    """Verify the script produces no findings on the actual 0001_initial.py."""

    def test_existing_initial_migration_passes(self):
        """The existing 0001_initial.py should produce zero findings."""
        migration_path = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "versions"
            / "0001_initial.py"
        )
        if not migration_path.exists():
            pytest.skip("Migration file not found (running outside repo)")

        result = check_migration_file(migration_path)
        assert result.is_initial is True
        assert result.findings == [], (
            f"False positive on existing migration: {result.findings}"
        )
