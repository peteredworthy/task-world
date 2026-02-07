"""Unit tests for artifact registry."""

from datetime import datetime

import pytest

from orchestrator.artifacts import ArtifactRegistry


@pytest.fixture
def registry() -> ArtifactRegistry:
    """Create a fresh artifact registry."""
    return ArtifactRegistry()


def test_register_new_artifact(registry: ArtifactRegistry) -> None:
    """Test registering a new artifact."""
    content = b"Initial content"
    artifact = registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/plan.md",
        content=content,
        metadata={"author": "test"},
    )

    assert artifact.run_id == "run-1"
    assert artifact.step_id == "step-1"
    assert artifact.task_id == "task-1"
    assert artifact.path == "docs/plan.md"
    assert artifact.version == 1
    assert artifact.metadata == {"author": "test"}
    assert artifact.content_hash is not None
    assert isinstance(artifact.created_at, datetime)


def test_update_artifact_creates_new_version(registry: ArtifactRegistry) -> None:
    """Test updating an artifact creates a new version."""
    # Register initial artifact
    content_v1 = b"Version 1 content"
    artifact_v1 = registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/plan.md",
        content=content_v1,
    )

    assert artifact_v1.version == 1

    # Update with new content
    content_v2 = b"Version 2 content"
    artifact_v2 = registry.register(
        run_id="run-1",
        step_id="step-2",
        task_id="task-2",
        path="docs/plan.md",
        content=content_v2,
    )

    assert artifact_v2.version == 2
    assert artifact_v2.content_hash != artifact_v1.content_hash
    assert artifact_v2.step_id == "step-2"
    assert artifact_v2.task_id == "task-2"


def test_content_hash_deduplication(registry: ArtifactRegistry) -> None:
    """Test that same content hash returns existing artifact."""
    content = b"Unchanged content"

    # Register artifact
    artifact_v1 = registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/plan.md",
        content=content,
    )

    # Register again with same content
    artifact_v2 = registry.register(
        run_id="run-1",
        step_id="step-2",
        task_id="task-2",
        path="docs/plan.md",
        content=content,
    )

    # Should return the same artifact (deduplication)
    assert artifact_v1.id == artifact_v2.id
    assert artifact_v1.version == artifact_v2.version
    assert artifact_v1.content_hash == artifact_v2.content_hash


def test_get_latest_artifact(registry: ArtifactRegistry) -> None:
    """Test getting the latest version of an artifact."""
    # Register multiple versions
    registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/plan.md",
        content=b"Version 1",
    )
    registry.register(
        run_id="run-1",
        step_id="step-2",
        task_id="task-2",
        path="docs/plan.md",
        content=b"Version 2",
    )
    artifact_v3 = registry.register(
        run_id="run-1",
        step_id="step-3",
        task_id="task-3",
        path="docs/plan.md",
        content=b"Version 3",
    )

    # Get latest should return version 3
    latest = registry.get_latest("run-1", "docs/plan.md")
    assert latest is not None
    assert latest.id == artifact_v3.id
    assert latest.version == 3


def test_get_latest_nonexistent(registry: ArtifactRegistry) -> None:
    """Test getting artifact that doesn't exist returns None."""
    latest = registry.get_latest("run-1", "docs/nonexistent.md")
    assert latest is None


def test_list_for_step(registry: ArtifactRegistry) -> None:
    """Test listing all artifacts for a step."""
    # Register artifacts for different steps
    artifact_1 = registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/plan.md",
        content=b"Plan content",
    )
    artifact_2 = registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/architecture.md",
        content=b"Architecture content",
    )
    artifact_3 = registry.register(
        run_id="run-1",
        step_id="step-2",
        task_id="task-2",
        path="docs/implementation.md",
        content=b"Implementation content",
    )

    # List for step-1
    step_1_artifacts = registry.list_for_step("run-1", "step-1")
    assert len(step_1_artifacts) == 2
    assert artifact_1 in step_1_artifacts
    assert artifact_2 in step_1_artifacts
    assert artifact_3 not in step_1_artifacts

    # List for step-2
    step_2_artifacts = registry.list_for_step("run-1", "step-2")
    assert len(step_2_artifacts) == 1
    assert artifact_3 in step_2_artifacts


def test_list_for_step_empty(registry: ArtifactRegistry) -> None:
    """Test listing for step with no artifacts returns empty list."""
    artifacts = registry.list_for_step("run-1", "step-nonexistent")
    assert artifacts == []


def test_has_unresolved_true(registry: ArtifactRegistry) -> None:
    """Test has_unresolved returns True when metadata flag is set."""
    registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/CONFLICTS.md",
        content=b"Conflict content",
        metadata={"has_unresolved": True},
    )

    assert registry.has_unresolved("run-1", "docs/CONFLICTS.md") is True


def test_has_unresolved_false(registry: ArtifactRegistry) -> None:
    """Test has_unresolved returns False when metadata flag is False."""
    registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/CONFLICTS.md",
        content=b"Conflict content",
        metadata={"has_unresolved": False},
    )

    assert registry.has_unresolved("run-1", "docs/CONFLICTS.md") is False


def test_has_unresolved_missing_metadata(registry: ArtifactRegistry) -> None:
    """Test has_unresolved returns False when metadata flag not set."""
    registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/plan.md",
        content=b"Plan content",
        metadata={},
    )

    assert registry.has_unresolved("run-1", "docs/plan.md") is False


def test_has_unresolved_nonexistent(registry: ArtifactRegistry) -> None:
    """Test has_unresolved returns False for nonexistent artifact."""
    assert registry.has_unresolved("run-1", "docs/nonexistent.md") is False


def test_multiple_runs_isolated(registry: ArtifactRegistry) -> None:
    """Test that artifacts from different runs are isolated."""
    # Register artifacts for run-1
    artifact_run1 = registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/plan.md",
        content=b"Run 1 content",
    )

    # Register artifacts for run-2
    artifact_run2 = registry.register(
        run_id="run-2",
        step_id="step-1",
        task_id="task-1",
        path="docs/plan.md",
        content=b"Run 2 content",
    )

    # Artifacts should be separate
    assert artifact_run1.id != artifact_run2.id
    assert registry.get_latest("run-1", "docs/plan.md") == artifact_run1
    assert registry.get_latest("run-2", "docs/plan.md") == artifact_run2


def test_version_increment_across_updates(registry: ArtifactRegistry) -> None:
    """Test version increments correctly across multiple updates."""
    path = "docs/evolving.md"

    v1 = registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path=path,
        content=b"Version 1",
    )
    assert v1.version == 1

    v2 = registry.register(
        run_id="run-1",
        step_id="step-2",
        task_id="task-2",
        path=path,
        content=b"Version 2",
    )
    assert v2.version == 2

    v3 = registry.register(
        run_id="run-1",
        step_id="step-3",
        task_id="task-3",
        path=path,
        content=b"Version 3",
    )
    assert v3.version == 3

    # Verify latest is v3
    latest = registry.get_latest("run-1", path)
    assert latest is not None
    assert latest.version == 3


def test_metadata_preserved_on_registration(registry: ArtifactRegistry) -> None:
    """Test metadata is preserved when registering artifacts."""
    metadata = {
        "has_unresolved": True,
        "author": "test-user",
        "custom_field": "value",
    }

    artifact = registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/plan.md",
        content=b"Content",
        metadata=metadata,
    )

    assert artifact.metadata == metadata


def test_resolution_tracking_workflow(registry: ArtifactRegistry) -> None:
    """Test workflow of tracking conflict resolution."""
    # Step 1: Create conflicts file with unresolved items
    registry.register(
        run_id="run-1",
        step_id="step-1",
        task_id="task-1",
        path="docs/CONFLICTS.md",
        content=b"# Conflicts\n- Conflict 1 [UNRESOLVED]\n- Conflict 2 [UNRESOLVED]",
        metadata={"has_unresolved": True},
    )

    assert registry.has_unresolved("run-1", "docs/CONFLICTS.md") is True

    # Step 2: Update conflicts file with resolutions
    registry.register(
        run_id="run-1",
        step_id="step-2",
        task_id="task-2",
        path="docs/CONFLICTS.md",
        content=b"# Conflicts\n- Conflict 1 [RESOLVED]\n- Conflict 2 [RESOLVED]",
        metadata={"has_unresolved": False},
    )

    assert registry.has_unresolved("run-1", "docs/CONFLICTS.md") is False
