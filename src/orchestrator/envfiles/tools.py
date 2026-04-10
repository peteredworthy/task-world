"""Env file tools for agents (MCP, REST, OpenHands)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.envfiles.errors import SnapshotNotFoundError
from orchestrator.envfiles.store import EnvFileStore
from orchestrator.time_utils import format_utc_datetime


# MCP/OpenHands tool definitions
ENV_FILE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "orchestrator_revert_env_file",
        "description": (
            "Revert one or more environment files (non-git managed files like .env, "
            "config.local.yaml) to an earlier state. Use this if you've accidentally "
            "corrupted a config file or need to reset credentials to their original values. "
            "You can revert to the state at the start of this task or the start of the run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "revert_to": {
                    "type": "string",
                    "enum": ["task_start", "run_start"],
                    "description": (
                        "Which point to revert to. "
                        "'task_start' undoes changes made during this task. "
                        "'run_start' resets to the original state from when the run began."
                    ),
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Specific files to revert (relative paths, e.g. ['.env']). "
                        "Omit or pass empty array to revert all managed environment files."
                    ),
                },
            },
            "required": ["revert_to"],
        },
    },
    {
        "name": "orchestrator_list_env_files",
        "description": (
            "List the environment files managed by the orchestrator for this run, "
            "including which snapshot points are available for revert."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


class EnvFileToolExecutor:
    """Handles env file tool calls from any agent type."""

    def __init__(self, store: EnvFileStore) -> None:
        self._store = store

    async def revert_env_file(
        self,
        run_id: str,
        task_id: str,
        worktree_path: Path,
        revert_to: str,
        files: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute an orchestrator_revert_env_file tool call."""
        manifest = self._store.load_manifest(run_id)

        if revert_to == "task_start":
            snapshot_id = f"task-{task_id}_start"
        elif revert_to == "run_start":
            snapshot_id = "run_start"
        else:
            return {"error": f"Invalid revert_to: {revert_to}. Use 'task_start' or 'run_start'."}

        # Validate snapshot exists
        point = next((s for s in manifest.snapshots if s.snapshot_id == snapshot_id), None)
        if point is None:
            return {"error": f"No snapshot found for '{snapshot_id}'."}

        restored = self._store.restore_snapshot(
            run_id,
            snapshot_id,
            worktree_path,
            files=files or None,
        )

        return {
            "reverted_to": snapshot_id,
            "files_restored": restored,
        }

    async def list_env_files(self, run_id: str) -> dict[str, Any]:
        """Execute an orchestrator_list_env_files tool call."""
        try:
            manifest = self._store.load_manifest(run_id)
        except SnapshotNotFoundError:
            return {"managed_files": [], "snapshots": []}

        return {
            "managed_files": [
                {"path": s.relative_path, "promote_on_success": s.promote_on_success}
                for s in manifest.env_file_specs
            ],
            "snapshots": [
                {
                    "snapshot_id": s.snapshot_id,
                    "type": s.point_type.value,
                    "task_id": s.task_id,
                    "timestamp": format_utc_datetime(s.timestamp),
                    "files": s.files,
                }
                for s in manifest.snapshots
            ],
        }
