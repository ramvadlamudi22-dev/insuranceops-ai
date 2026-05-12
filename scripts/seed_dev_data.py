#!/usr/bin/env python3
"""Seed local development database with test data.

Creates a test API key and a sample document for local development.
Requires the database to be running (use scripts/dev_up.sh first).
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/insuranceops"
PEPPER = "dev-pepper-not-for-production"

SAMPLE_CLAIM_TEXT = """\
Claim Number: CLM-2025-001234
Policy Number: POL-12345678
Claimant: Jane Smith
Date of Loss: 01/15/2025
Claim Type: auto
Description: Vehicle collision at intersection of Main St and 5th Ave.
"""


async def main() -> None:
    """Create seed data for local development."""
    engine = create_async_engine(DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Run migrations check
        await session.execute(text("SELECT 1"))
        print("Connected to database.")

        # Create API key
        raw_token = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256((PEPPER + raw_token).encode("utf-8")).digest()
        api_key_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await session.execute(
            text(
                "INSERT INTO api_keys (api_key_id, key_hash, role, label, created_at) "
                "VALUES (:id, :hash, :role, :label, :created_at) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "id": api_key_id,
                "hash": key_hash,
                "role": "supervisor",
                "label": "dev-seed-key",
                "created_at": now,
            },
        )

        # Create sample document
        content = SAMPLE_CLAIM_TEXT.encode("utf-8")
        content_hash = hashlib.sha256(content).digest()
        document_id = uuid.uuid4()

        await session.execute(
            text(
                "INSERT INTO documents (document_id, content_hash, content_type, "
                "size_bytes, payload_ref, ingested_at, ingested_by, api_key_id) "
                "VALUES (:doc_id, :hash, :ct, :size, :ref, :at, :by, :key_id) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "doc_id": document_id,
                "hash": content_hash,
                "ct": "text/plain",
                "size": len(content),
                "ref": f"local://{content_hash.hex()}",
                "at": now,
                "by": f"api_key:supervisor:{api_key_id}",
                "key_id": api_key_id,
            },
        )

        await session.commit()

    await engine.dispose()

    print("\n--- Development Seed Data ---")
    print(f"API Key Token (use as Bearer token): {raw_token}")
    print(f"API Key ID: {api_key_id}")
    print(f"API Key Role: supervisor")
    print(f"Document ID: {document_id}")
    print("\n--- Test with ---")
    print(
        f'curl -H "Authorization: Bearer {raw_token}" '
        f"http://localhost:8000/v1/workflow-runs/{document_id}"
    )


if __name__ == "__main__":
    asyncio.run(main())
