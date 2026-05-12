"""Workflow definition registry."""

from __future__ import annotations

from dataclasses import dataclass, field

from insuranceops.workflows.retry import RetryPolicy


@dataclass(frozen=True, slots=True)
class StepDefinition:
    """Definition of a single step within a workflow.

    Attributes:
        step_name: Unique name of the step within the workflow.
        handler_name: Name used to look up the handler in the handler registry.
        step_index: 0-based ordering of the step within the workflow.
        max_attempts: Maximum number of attempts before failure.
        escalate_on_failure: Whether to create an EscalationCase on terminal failure.
        retry_policy: Backoff configuration for retries.
        timeout_seconds: Maximum execution time for a single attempt.
    """

    step_name: str
    handler_name: str
    step_index: int
    max_attempts: int = 3
    escalate_on_failure: bool = False
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_seconds: int = 30


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    """A complete workflow definition with ordered steps.

    Attributes:
        workflow_name: Canonical name of the workflow (e.g., "claim_intake").
        workflow_version: Version string (e.g., "v1").
        steps: Ordered list of step definitions.
        deadline_seconds: Maximum wall-clock time for the entire workflow run.
    """

    workflow_name: str
    workflow_version: str
    steps: tuple[StepDefinition, ...] = field(default_factory=tuple)
    deadline_seconds: int = 3600


class WorkflowRegistry:
    """In-memory registry of workflow definitions.

    Workflows are keyed by (workflow_name, workflow_version) tuples.
    Thread-safe for reads after initialization at import time.
    """

    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], WorkflowDefinition] = {}

    def register(self, definition: WorkflowDefinition) -> None:
        """Register a workflow definition.

        Args:
            definition: The workflow definition to register.

        Raises:
            ValueError: If a definition with the same name and version is already registered.
        """
        key = (definition.workflow_name, definition.workflow_version)
        if key in self._definitions:
            raise ValueError(
                f"Workflow already registered: {definition.workflow_name} "
                f"{definition.workflow_version}"
            )
        self._definitions[key] = definition

    def get(self, workflow_name: str, workflow_version: str) -> WorkflowDefinition | None:
        """Look up a workflow definition by name and version.

        Args:
            workflow_name: The workflow name.
            workflow_version: The workflow version.

        Returns:
            The workflow definition, or None if not found.
        """
        return self._definitions.get((workflow_name, workflow_version))

    def get_latest(self, workflow_name: str) -> WorkflowDefinition | None:
        """Get the latest registered version of a workflow by name.

        Returns the definition with the highest lexicographic version string
        among all registered versions for the given workflow name.

        Args:
            workflow_name: The workflow name.

        Returns:
            The latest workflow definition, or None if no versions are registered.
        """
        candidates = [
            defn for (name, _version), defn in self._definitions.items() if name == workflow_name
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda d: d.workflow_version)

    def list_all(self) -> list[WorkflowDefinition]:
        """List all registered workflow definitions.

        Returns:
            List of all workflow definitions.
        """
        return list(self._definitions.values())


# Global registry instance
registry = WorkflowRegistry()
