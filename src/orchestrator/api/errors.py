"""Error handler registration for the API."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.api.auth import AuthError
from orchestrator.envfiles.errors import SnapshotNotFoundError
from orchestrator.git.errors import BranchNotFoundError, MergeConflictError
from orchestrator.repos.errors import RepoNotFoundError
from orchestrator.routines.errors import RoutineNotFoundError, RoutineValidationError
from orchestrator.state.errors import (
    ChecklistItemNotFoundError,
    MissingRequiredInputError,
    RunNotFoundError,
    StepNotFoundError,
    TaskNotFoundError,
)
from orchestrator.workflow.errors import GateBlockedError, InvalidTransitionError
from orchestrator.workflow.locks import TaskLockedError


def register_error_handlers(app: FastAPI) -> None:
    """Register domain exception -> HTTP response mappings."""

    @app.exception_handler(AuthError)
    async def auth_error(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: AuthError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"error": "authentication_failed", "detail": str(exc)},
        )

    @app.exception_handler(RunNotFoundError)
    async def run_not_found(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: RunNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "run_not_found", "run_id": exc.run_id},
        )

    @app.exception_handler(StepNotFoundError)
    async def step_not_found(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: StepNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "step_not_found", "step_id": exc.step_id},
        )

    @app.exception_handler(TaskNotFoundError)
    async def task_not_found(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: TaskNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "task_not_found", "run_id": exc.run_id, "task_id": exc.task_id},
        )

    @app.exception_handler(ChecklistItemNotFoundError)
    async def checklist_not_found(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: ChecklistItemNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": "checklist_item_not_found",
                "run_id": exc.run_id,
                "task_id": exc.task_id,
                "req_id": exc.req_id,
            },
        )

    @app.exception_handler(RoutineNotFoundError)
    async def routine_not_found(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: RoutineNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "routine_not_found", "path": exc.path},
        )

    @app.exception_handler(RoutineValidationError)
    async def routine_validation(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: RoutineValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "routine_validation_failed",
                "path": exc.path,
                "errors": exc.errors,
            },
        )

    @app.exception_handler(MissingRequiredInputError)
    async def missing_required_input(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: MissingRequiredInputError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "missing_required_input",
                "input_name": exc.input_name,
            },
        )

    @app.exception_handler(InvalidTransitionError)
    async def invalid_transition(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: InvalidTransitionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": "invalid_transition",
                "from_status": exc.from_status,
                "to_status": exc.to_status,
            },
        )

    @app.exception_handler(GateBlockedError)
    async def gate_blocked(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: GateBlockedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": "gate_blocked",
                "gate_name": exc.gate_name,
                "blocking_items": exc.blocking_items,
            },
        )

    @app.exception_handler(TaskLockedError)
    async def task_locked(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: TaskLockedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": "task_locked",
                "task_id": exc.task_id,
                "locked_by": exc.locked_by,
            },
        )

    @app.exception_handler(AgentCancelledError)
    async def agent_cancelled(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: AgentCancelledError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=499,
            content={"error": "agent_cancelled", "agent_type": exc.agent_type},
        )

    @app.exception_handler(AgentNotAvailableError)
    async def agent_not_available(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: AgentNotAvailableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": "agent_not_available",
                "agent_type": exc.agent_type,
                "reason": exc.reason,
            },
        )

    @app.exception_handler(AgentExecutionError)
    async def agent_execution_error(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: AgentExecutionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": "agent_execution_error",
                "agent_type": exc.agent_type,
                "message": exc.message,
            },
        )

    @app.exception_handler(SnapshotNotFoundError)
    async def snapshot_not_found(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: SnapshotNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": "snapshot_not_found",
                "run_id": exc.run_id,
                "snapshot_id": exc.snapshot_id,
            },
        )

    @app.exception_handler(BranchNotFoundError)
    async def branch_not_found(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: BranchNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "branch_not_found", "branch": exc.branch},
        )

    @app.exception_handler(MergeConflictError)
    async def merge_conflict(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: MergeConflictError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": "merge_conflict",
                "source": exc.source,
                "target": exc.target,
                "conflicting_files": exc.conflicting_files,
            },
        )

    @app.exception_handler(RepoNotFoundError)
    async def repo_not_found(  # type: ignore[reportUnusedFunction]
        _request: Request, exc: RepoNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "repo_not_found", "name": exc.name},
        )
