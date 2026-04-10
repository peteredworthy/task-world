"""Session state manager with in-memory state and optional file persistence."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from orchestrator.config.enums import ChecklistStatus
from orchestrator.state.errors import (
    ChecklistItemNotFoundError,
    RunNotFoundError,
    TaskNotFoundError,
)
from orchestrator.state.models import ChecklistItem, Run, TaskState


class SessionStateManager:
    """Manages run state in memory with optional file persistence.

    Design: State lives in memory. File is for durability across restarts.
    All mutations happen in memory first, then save() persists.
    """

    def __init__(self, persist_path: Path | None = None) -> None:
        self._persist_path = persist_path
        self._runs: dict[str, Run] = {}

    # --- Read operations ---

    def get_run(self, run_id: str) -> Run:
        """Get a run by ID."""
        if run_id not in self._runs:
            raise RunNotFoundError(run_id)
        return self._runs[run_id]

    def list_runs(self) -> list[Run]:
        """List all runs."""
        return list(self._runs.values())

    def get_task(self, run_id: str, task_id: str) -> TaskState:
        """Get a task by run ID and task ID."""
        run = self.get_run(run_id)
        for step in run.steps:
            for task in step.tasks:
                if task.id == task_id:
                    return task
        raise TaskNotFoundError(run_id, task_id)

    # --- Write operations ---

    def add_run(self, run: Run) -> None:
        """Add a new run to state."""
        self._runs[run.id] = run

    def update_run(self, run: Run) -> None:
        """Update an existing run."""
        if run.id not in self._runs:
            raise RunNotFoundError(run.id)
        run.updated_at = datetime.now(timezone.utc)
        self._runs[run.id] = run

    def delete_run(self, run_id: str) -> None:
        """Delete a run."""
        if run_id not in self._runs:
            raise RunNotFoundError(run_id)
        del self._runs[run_id]

    def update_checklist_item(
        self,
        run_id: str,
        task_id: str,
        req_id: str,
        status: ChecklistStatus,
        note: str | None = None,
    ) -> ChecklistItem:
        """Update a checklist item status."""
        task = self.get_task(run_id, task_id)
        for item in task.checklist:
            if item.req_id == req_id:
                item.status = status
                if note is not None:
                    item.note = note
                return item
        raise ChecklistItemNotFoundError(run_id, task_id, req_id)

    # --- Persistence ---

    async def save(self) -> None:
        """Persist state to file."""
        if self._persist_path is None:
            return

        data: dict[str, Any] = {
            "runs": {run_id: run.model_dump(mode="json") for run_id, run in self._runs.items()}
        }

        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self._persist_path, "w") as f:
            await f.write(json.dumps(data, indent=2, default=str))

    async def load(self) -> None:
        """Load state from file."""
        if self._persist_path is None or not self._persist_path.exists():
            return

        async with aiofiles.open(self._persist_path, "r") as f:
            content = await f.read()

        if not content.strip():
            return

        data: dict[str, Any] = json.loads(content)
        runs_data: dict[str, Any] = data.get("runs", {})
        self._runs = {
            run_id: Run.model_validate(run_data) for run_id, run_data in runs_data.items()
        }
