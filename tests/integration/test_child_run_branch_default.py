"""Regression coverage for child-run source-branch defaults."""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api import ToolHandler
from orchestrator.config.enums import Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow import WorkflowService
from tests.integration.git_helpers import _git, _init_repo


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def service(session: AsyncSession) -> WorkflowService:
    return WorkflowService(session)


@pytest.fixture
def handler(service: WorkflowService) -> ToolHandler:
    return ToolHandler(service)


EMBEDDED_ROUTINE: dict[str, object] = {
    "id": "child-branch-defaults",
    "name": "Child Branch Defaults",
    "steps": [
        {
            "id": "S-01",
            "title": "Default",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Validate branch defaults",
                    "requirements": [{"id": "R1", "desc": "A thing must be true."}],
                }
            ],
        }
    ],
}


def _make_parent_run(*, run_id: str, repo_name: str) -> Run:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id=run_id,
        repo_name=repo_name,
        source_branch="main",
        status=RunStatus.DRAFT,
        routine_id="test-routine",
        routine_source=RoutineSource.LOCAL,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.PENDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1", desc="First requirement", priority=Priority.CRITICAL
                            )
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


async def test_rest_child_run_defaults_to_parent_accumulation_branch(
    _shared_app_fixture: tuple,
    git_repo: Path,
) -> None:
    client, drain, _, _, _ = _shared_app_fixture

    parent_resp = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": git_repo.name,
            "branch": "main",
            "agent_runner_type": "user_managed",
        },
    )
    assert parent_resp.status_code == 201, parent_resp.text
    parent_id = parent_resp.json()["id"]

    start_resp = await client.post(f"/api/runs/{parent_id}/start")
    assert start_resp.status_code == 202, start_resp.text
    await drain(parent_id)

    parent = (await client.get(f"/api/runs/{parent_id}")).json()
    worktree_path = Path(parent["worktree_path"])
    parent_branch = f"orchestrator/run-{parent_id}"

    branches = _git(["branch", "--list"], cwd=worktree_path)
    assert any(
        (line[2:].strip() if line.startswith("* ") else line.strip()) == parent_branch
        for line in branches.splitlines()
    )

    child_resp = await client.post(
        f"/api/runs/{parent_id}/children",
        json={
            "routine_id": "simple-routine",
            "parent_slice_id": "slice-1",
            "next_action_decision": "continue",
            "branch": "main",
        },
    )
    assert child_resp.status_code == 201, child_resp.text
    assert child_resp.json()["source_branch"] == parent_branch


async def test_mcp_child_creation_uses_parent_accumulation_branch_if_present(
    handler: ToolHandler,
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "parent-repo"
    repo.mkdir()
    _init_repo(repo)
    _git(["branch", "orchestrator/run-run-1"], cwd=repo)

    parent = _make_parent_run(run_id="run-1", repo_name=repo.name)
    parent.status = RunStatus.ACTIVE
    parent.worktree_path = str(repo)
    await service.create_run(parent)

    create_result = await handler.handle(
        "orchestrator_create_child_run",
        {
            "parent_run_id": "run-1",
            "parent_slice_id": "slice-1",
            "routine_embedded": EMBEDDED_ROUTINE,
            "branch": "release-candidate",
            "next_action_decision": "continue",
        },
    )
    child = await service.get_run(create_result["child_run_id"])
    assert child.source_branch == "orchestrator/run-run-1"
