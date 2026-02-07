"""Artifact registry for tracking generated files across steps."""

import hashlib
from datetime import UTC, datetime
from typing import Any

from orchestrator.artifacts.models import Artifact


class ArtifactRegistry:
    """Track artifacts produced during a run."""

    def __init__(self) -> None:
        """Initialize in-memory artifact storage."""
        self._artifacts: dict[str, Artifact] = {}  # artifact_id -> Artifact
        self._by_run_and_path: dict[tuple[str, str], str] = {}  # (run_id, path) -> artifact_id

    def register(
        self,
        run_id: str,
        step_id: str,
        task_id: str,
        path: str,
        content: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """
        Register a new or updated artifact.

        If an artifact at the same path already exists:
        - Same content hash: return existing artifact (deduplication)
        - Different content hash: create new version

        Args:
            run_id: Run identifier
            step_id: Step identifier
            task_id: Task identifier
            path: Relative path within worktree
            content: File content as bytes
            metadata: Optional metadata dict

        Returns:
            Artifact: The registered artifact
        """
        content_hash = hashlib.sha256(content).hexdigest()

        # Check for existing artifact at path
        existing_id = self._by_run_and_path.get((run_id, path))
        existing = self._artifacts.get(existing_id) if existing_id else None

        if existing and existing.content_hash == content_hash:
            return existing  # No change, return existing

        version = (existing.version + 1) if existing else 1

        artifact = Artifact(
            id=f"{run_id}-{path}-v{version}",
            run_id=run_id,
            step_id=step_id,
            task_id=task_id,
            path=path,
            content_hash=content_hash,
            created_at=datetime.now(UTC),
            version=version,
            metadata=metadata or {},
        )

        self._artifacts[artifact.id] = artifact
        self._by_run_and_path[(run_id, path)] = artifact.id

        return artifact

    def get_latest(self, run_id: str, path: str) -> Artifact | None:
        """
        Get the latest version of an artifact.

        Args:
            run_id: Run identifier
            path: Relative path within worktree

        Returns:
            Artifact or None if not found
        """
        artifact_id = self._by_run_and_path.get((run_id, path))
        return self._artifacts.get(artifact_id) if artifact_id else None

    def list_for_step(self, run_id: str, step_id: str) -> list[Artifact]:
        """
        List all artifacts produced by a step.

        Args:
            run_id: Run identifier
            step_id: Step identifier

        Returns:
            List of artifacts for the step
        """
        return [
            artifact
            for artifact in self._artifacts.values()
            if artifact.run_id == run_id and artifact.step_id == step_id
        ]

    def has_unresolved(self, run_id: str, path: str) -> bool:
        """
        Check if artifact has unresolved items (for conflict tracking).

        Checks metadata.has_unresolved flag.

        Args:
            run_id: Run identifier
            path: Relative path within worktree

        Returns:
            True if artifact exists and has_unresolved is True
        """
        artifact = self.get_latest(run_id, path)
        if not artifact:
            return False
        return artifact.metadata.get("has_unresolved", False)
