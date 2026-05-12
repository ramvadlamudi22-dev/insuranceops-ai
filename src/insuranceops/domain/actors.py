"""Actor domain model.

An Actor is the principal that caused an event.
Format: <kind>:<subkind>:<id> or <kind>:<subkind> for singleton service identities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CANONICAL_KINDS = frozenset({"worker", "api", "user", "api_key", "anonymous"})

WORKER_SUBKINDS = frozenset({"main", "reaper", "scheduler", "outbox_relay", "extractor"})
API_SUBKINDS = frozenset({"control_plane"})
USER_ROLES = frozenset({"operator", "supervisor", "viewer"})
API_KEY_ROLES = frozenset({"operator", "supervisor", "viewer"})


@dataclass(frozen=True, slots=True)
class Actor:
    """Represents a principal that caused an event."""

    kind: str
    subkind: str
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in CANONICAL_KINDS:
            raise ValueError(f"Invalid actor kind: {self.kind!r}. Must be one of {CANONICAL_KINDS}")
        if not self.subkind and self.kind != "anonymous":
            raise ValueError(f"Actor kind {self.kind!r} requires a subkind")

    def __str__(self) -> str:
        """Format as canonical actor string."""
        if self.kind == "anonymous":
            return "anonymous"
        if self.id is not None:
            return f"{self.kind}:{self.subkind}:{self.id}"
        return f"{self.kind}:{self.subkind}"

    @classmethod
    def parse(cls, raw: str) -> Actor:
        """Parse an actor string into an Actor instance.

        Formats:
            - "anonymous"
            - "kind:subkind" (for service identities without an id)
            - "kind:subkind:id" (for user/api_key actors with an id)
        """
        if raw == "anonymous":
            return cls(kind="anonymous", subkind="")

        parts = raw.split(":", maxsplit=2)
        if len(parts) == 2:
            return cls(kind=parts[0], subkind=parts[1])
        elif len(parts) == 3:
            return cls(kind=parts[0], subkind=parts[1], id=parts[2])
        else:
            raise ValueError(
                f"Invalid actor string: {raw!r}. "
                "Expected format 'kind:subkind:id', 'kind:subkind', or 'anonymous'."
            )
