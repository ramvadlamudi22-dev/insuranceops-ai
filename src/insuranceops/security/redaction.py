"""Structlog processor for PII field redaction."""

from __future__ import annotations

from typing import Any

REDACTED_FIELDS = frozenset({
    "ssn",
    "social_security",
    "dob",
    "date_of_birth",
    "policy_number",
    "phone",
    "email",
    "address",
})

REDACTED_VALUE = "[REDACTED]"


def redact_sensitive_fields(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that replaces PII field values with [REDACTED]."""
    for key in list(event_dict.keys()):
        if key.lower() in REDACTED_FIELDS:
            event_dict[key] = REDACTED_VALUE
    return event_dict
