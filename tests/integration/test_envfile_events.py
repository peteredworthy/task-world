"""Integration tests for env file lifecycle event emission."""

import pytest
from pathlib import Path

from orchestrator.envfiles.lifecycle import EnvFileLifecycle
from orchestrator.envfiles.models import EnvFileSpec
from orchestrator.envfiles.store import EnvFileStore
from orchestrator.workflow.events import BufferingEmitter


@pytest.fixture
def store(tmp_path: Path) -> EnvFileStore:
    """Create an EnvFileStore with a temp base directory."""
    return EnvFileStore(base_dir=tmp_path / "store")


@pytest.fixture
def emitter() -> BufferingEmitter:
    """Create a BufferingEmitter for capturing events."""
    return BufferingEmitter()


@pytest.fixture
def lifecycle(store: EnvFileStore, emitter: BufferingEmitter) -> EnvFileLifecycle:
    """Create an EnvFileLifecycle instance with event emitter."""
    return EnvFileLifecycle(store=store, event_emitter=emitter)


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """Create a worktree directory."""
    wt = tmp_path / "worktree"
    wt.mkdir(parents=True, exist_ok=True)
    return wt


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    """Create a source directory with env files."""
    src = tmp_path / "source"
    src.mkdir(parents=True, exist_ok=True)
    (src / ".env").write_text("API_KEY=test\n")
    return src


@pytest.fixture
def env_specs() -> list[EnvFileSpec]:
    """Standard env specs."""
    return [EnvFileSpec(relative_path=".env", promote_on_success=True)]


@pytest.mark.asyncio
async def test_on_run_start_emits_event(
    lifecycle: EnvFileLifecycle,
    emitter: BufferingEmitter,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """Verify on_run_start emits an env_file_snapshot event."""
    run_id = "test-run-123"
    project_id = "test-project"

    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    events = emitter.drain()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "env_file_snapshot"
    assert event.run_id == run_id
    assert event.snapshot_id == "run_start"  # type: ignore[attr-defined]
    assert event.point_type == "run_start"  # type: ignore[attr-defined]
    assert event.files == [".env"]  # type: ignore[attr-defined]
    assert event.task_id is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_on_task_start_emits_event(
    lifecycle: EnvFileLifecycle,
    emitter: BufferingEmitter,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """Verify on_task_start emits an env_file_snapshot event."""
    run_id = "test-run-123"
    task_id = "task-456"
    project_id = "test-project"

    # First initialize with on_run_start
    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    # Clear initial event
    emitter.drain()

    # Now capture task_start
    await lifecycle.on_task_start(
        run_id=run_id,
        task_id=task_id,
        worktree_path=worktree,
    )

    events = emitter.drain()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "env_file_snapshot"
    assert event.run_id == run_id
    assert event.snapshot_id == f"task-{task_id}_start"  # type: ignore[attr-defined]
    assert event.point_type == "task_start"  # type: ignore[attr-defined]
    assert event.task_id == task_id  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_on_task_end_emits_event(
    lifecycle: EnvFileLifecycle,
    emitter: BufferingEmitter,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """Verify on_task_end emits an env_file_snapshot event."""
    run_id = "test-run-123"
    task_id = "task-456"
    project_id = "test-project"

    # Initialize with on_run_start
    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    # Clear initial event
    emitter.drain()

    # Capture task_end
    await lifecycle.on_task_end(
        run_id=run_id,
        task_id=task_id,
        worktree_path=worktree,
    )

    events = emitter.drain()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "env_file_snapshot"
    assert event.run_id == run_id
    assert event.snapshot_id == f"task-{task_id}_end"  # type: ignore[attr-defined]
    assert event.point_type == "task_end"  # type: ignore[attr-defined]
    assert event.task_id == task_id  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_on_run_end_emits_event(
    lifecycle: EnvFileLifecycle,
    emitter: BufferingEmitter,
    worktree: Path,
    source_dir: Path,
    env_specs: list[EnvFileSpec],
) -> None:
    """Verify on_run_end emits an env_file_snapshot event."""
    run_id = "test-run-123"
    project_id = "test-project"

    # Initialize with on_run_start
    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=env_specs,
        source_dir=source_dir,
    )

    # Clear initial event
    emitter.drain()

    # Capture run_end
    await lifecycle.on_run_end(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        success=True,
    )

    events = emitter.drain()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "env_file_snapshot"
    assert event.run_id == run_id
    assert event.snapshot_id == "run_end"  # type: ignore[attr-defined]
    assert event.point_type == "run_end"  # type: ignore[attr-defined]
    assert event.task_id is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_no_events_when_no_env_specs(
    lifecycle: EnvFileLifecycle,
    emitter: BufferingEmitter,
    worktree: Path,
) -> None:
    """Verify no events are emitted when env_specs is empty."""
    run_id = "test-run-123"
    project_id = "test-project"

    await lifecycle.on_run_start(
        run_id=run_id,
        project_id=project_id,
        worktree_path=worktree,
        env_specs=[],
        source_dir=None,
    )

    events = emitter.drain()
    assert len(events) == 0
