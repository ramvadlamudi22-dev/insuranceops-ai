"""Ingest step handler: verifies all document_ids exist."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.storage.repositories.documents import DocumentRepository
from insuranceops.workflows.steps.base import StepContext, StepResult


class IngestStepHandler:
    """Verifies that all document_ids referenced by the workflow run exist.

    Returns succeeded if all documents exist in the documents table,
    failed_terminal if any are missing.
    """

    async def handle(self, context: StepContext, session: AsyncSession) -> StepResult:
        """Verify all documents exist.

        Args:
            context: Step context with document_ids.
            session: Active database session.

        Returns:
            StepResult with succeeded or failed_terminal status.
        """
        doc_repo = DocumentRepository(session)
        missing_ids: list[str] = []

        for doc_id in context.document_ids:
            doc = await doc_repo.get_by_id(doc_id)
            if doc is None:
                missing_ids.append(str(doc_id))

        if missing_ids:
            return StepResult(
                status="failed_terminal",
                error_code="DOCUMENTS_NOT_FOUND",
                error_detail=(
                    f"Documents not found: {', '.join(missing_ids)}"
                ),
            )

        return StepResult(
            status="succeeded",
            output={"document_count": len(context.document_ids)},
        )
