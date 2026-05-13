"""Local filesystem payload store implementation."""

from __future__ import annotations

import os
from pathlib import Path


class LocalPayloadStore:
    """Stores and retrieves document payloads on the local filesystem.

    Files are stored using the hex-encoded content_hash as the filename.
    """

    def __init__(self, base_path: str) -> None:
        self._base_path = Path(base_path)

    def _ref_to_path(self, payload_ref: str) -> Path:
        """Convert a payload_ref to an absolute filesystem path."""
        return self._base_path / payload_ref

    def _content_hash_to_ref(self, content_hash: bytes) -> str:
        """Convert a content hash to a payload reference (filename)."""
        return content_hash.hex()

    def write(self, content_hash: bytes, data: bytes) -> str:
        """Write payload bytes to the store.

        Args:
            content_hash: SHA-256 hash of the data (used as filename).
            data: Raw payload bytes.

        Returns:
            The payload_ref string for later retrieval.
        """
        ref = self._content_hash_to_ref(content_hash)
        path = self._ref_to_path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write atomically via temp file + rename
        tmp_path = path.with_suffix(".tmp")
        try:
            tmp_path.write_bytes(data)
            os.replace(str(tmp_path), str(path))
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

        return ref

    def read(self, payload_ref: str) -> bytes:
        """Read payload bytes from the store.

        Args:
            payload_ref: The reference string returned by write().

        Returns:
            The raw payload bytes.

        Raises:
            FileNotFoundError: If the payload does not exist.
        """
        path = self._ref_to_path(payload_ref)
        return path.read_bytes()

    def exists(self, payload_ref: str) -> bool:
        """Check whether a payload exists in the store."""
        path = self._ref_to_path(payload_ref)
        return path.is_file()
