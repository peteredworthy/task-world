"""Env file lifecycle hooks for workflow engine integration."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator.config.models import EnvFileSpec
from orchestrator.envfiles.models import (
    SnapshotManifest,
    SnapshotPoint,
    SnapshotPointType,
)
from orchestrator.envfiles.store import EnvFileStore


class EnvFileLifecycle:
    """Manages env file snapshots across the run/task lifecycle.

    Called by the workflow engine at key transition points.
    """

    def __init__(
        self,
        store: EnvFileStore,
        event_emitter: Any | None = None,
    ) -> None:
        """Initialize the lifecycle manager.

        Args:
            store: The env file store for snapshot operations.
            event_emitter: Optional event emitter (PersistentEventEmitter or BufferingEmitter)
                for broadcasting env file events.
        """
        self.store = store
        self._event_emitter = event_emitter

    def _emit_event(self, run_id: str, event_type: str, data: dict[str, Any]) -> None:
        """Emit an env file event if an emitter is configured.

        Args:
            run_id: The run ID associated with this event.
            event_type: The type of event (e.g., "env_file_snapshot").
            data: Event-specific data to include.
        """
        if self._event_emitter is not None:
            from dataclasses import dataclass
            from orchestrator.workflow import WorkflowEvent

            @dataclass
            class EnvFileSnapshotEvent(WorkflowEvent):
                """Emitted when an env file snapshot is captured."""

                snapshot_id: str = ""
                point_type: str = ""
                files: list[str] | None = None
                task_id: str | None = None

                def __post_init__(self) -> None:
                    if self.files is None:
                        self.files = []

            event = EnvFileSnapshotEvent(
                timestamp=datetime.now(timezone.utc),
                run_id=run_id,
                event_type=event_type,
                snapshot_id=data.get("snapshot_id", ""),
                point_type=data.get("point_type", ""),
                files=data.get("files", []),
                task_id=data.get("task_id"),
            )
            self._event_emitter.emit(event)

    async def on_run_start(
        self,
        run_id: str,
        repo_name: str,
        worktree_path: Path,
        env_specs: list[EnvFileSpec],
        source_dir: Path | None = None,
    ) -> None:
        """Called when a run transitions to ACTIVE.

        1. If source_dir provided: ingest files from source into run_start snapshot, then inject into worktree
        2. Else: load from canonical store into worktree, then capture run_start snapshot
        3. Save manifest with run_start snapshot point
        """
        if not env_specs:
            return

        if source_dir:
            ingested_files = self.store.ingest_source(run_id, source_dir, env_specs)
            # Create manifest first so inject_into_worktree can load it
            manifest = SnapshotManifest(
                run_id=run_id,
                source_dir=str(source_dir),
                env_file_specs=env_specs,
                snapshots=[
                    SnapshotPoint(
                        snapshot_id="run_start",
                        point_type=SnapshotPointType.RUN_START,
                        run_id=run_id,
                        task_id=None,
                        timestamp=datetime.now(timezone.utc),
                        files=ingested_files,
                    )
                ],
            )
            self.store.save_manifest(manifest)
            self.store.inject_into_worktree(run_id, "run_start", worktree_path)

            # Emit event for snapshot creation
            self._emit_event(
                run_id,
                "env_file_snapshot",
                {
                    "snapshot_id": "run_start",
                    "point_type": SnapshotPointType.RUN_START.value,
                    "files": ingested_files,
                    "task_id": None,
                },
            )
        else:
            self.store.load_canonical(repo_name, env_specs, worktree_path)
            point = self.store.capture_snapshot(
                run_id,
                "run_start",
                SnapshotPointType.RUN_START,
                worktree_path,
                env_specs,
            )
            manifest = SnapshotManifest(
                run_id=run_id,
                source_dir=None,
                env_file_specs=env_specs,
                snapshots=[point],
            )
            self.store.save_manifest(manifest)

            # Emit event for snapshot creation
            self._emit_event(
                run_id,
                "env_file_snapshot",
                {
                    "snapshot_id": "run_start",
                    "point_type": SnapshotPointType.RUN_START.value,
                    "files": point.files,
                    "task_id": None,
                },
            )

    async def on_task_start(
        self,
        run_id: str,
        task_id: str,
        worktree_path: Path,
    ) -> None:
        """Capture task_start snapshot. No-op if no env_specs."""
        try:
            manifest = self.store.load_manifest(run_id)
        except Exception:
            return
        if not manifest.env_file_specs:
            return

        snapshot_id = f"task-{task_id}_start"
        point = self.store.capture_snapshot(
            run_id,
            snapshot_id,
            SnapshotPointType.TASK_START,
            worktree_path,
            manifest.env_file_specs,
            task_id=task_id,
        )
        manifest.snapshots.append(point)
        self.store.save_manifest(manifest)

        # Emit event for snapshot creation
        self._emit_event(
            run_id,
            "env_file_snapshot",
            {
                "snapshot_id": snapshot_id,
                "point_type": SnapshotPointType.TASK_START.value,
                "files": point.files,
                "task_id": task_id,
            },
        )

    async def on_task_end(
        self,
        run_id: str,
        task_id: str,
        worktree_path: Path,
    ) -> None:
        """Capture task_end snapshot. No-op if no env_specs."""
        try:
            manifest = self.store.load_manifest(run_id)
        except Exception:
            return
        if not manifest.env_file_specs:
            return

        snapshot_id = f"task-{task_id}_end"
        point = self.store.capture_snapshot(
            run_id,
            snapshot_id,
            SnapshotPointType.TASK_END,
            worktree_path,
            manifest.env_file_specs,
            task_id=task_id,
        )
        manifest.snapshots.append(point)
        self.store.save_manifest(manifest)

        # Emit event for snapshot creation
        self._emit_event(
            run_id,
            "env_file_snapshot",
            {
                "snapshot_id": snapshot_id,
                "point_type": SnapshotPointType.TASK_END.value,
                "files": point.files,
                "task_id": task_id,
            },
        )

    async def on_run_end(
        self,
        run_id: str,
        repo_name: str,
        worktree_path: Path,
        success: bool,
    ) -> None:
        """Capture run_end snapshot. If success, promote configured files to canonical."""
        try:
            manifest = self.store.load_manifest(run_id)
        except Exception:
            return
        if not manifest.env_file_specs:
            return

        point = self.store.capture_snapshot(
            run_id,
            "run_end",
            SnapshotPointType.RUN_END,
            worktree_path,
            manifest.env_file_specs,
        )
        manifest.snapshots.append(point)
        self.store.save_manifest(manifest)

        # Emit event for snapshot creation
        self._emit_event(
            run_id,
            "env_file_snapshot",
            {
                "snapshot_id": "run_end",
                "point_type": SnapshotPointType.RUN_END.value,
                "files": point.files,
                "task_id": None,
            },
        )

        if success:
            self.store.promote_to_canonical(
                run_id,
                repo_name,
                manifest.env_file_specs,
            )
