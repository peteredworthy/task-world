"""Integration tests for OrchestratorMCPServer."""

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.api import OrchestratorMCPServer
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.service import WorkflowService


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
def server(service: WorkflowService) -> OrchestratorMCPServer:
    return OrchestratorMCPServer(service)


def test_server_creation(server: OrchestratorMCPServer) -> None:
    """Server creates without error."""
    assert server.mcp is not None
    assert server.mcp.name == "orchestrator"


def test_tool_names(server: OrchestratorMCPServer) -> None:
    """Server registers all tools regardless of phase."""
    names = server.tool_names()
    assert len(names) == 11
    assert "orchestrator_get_requirements" in names
    assert "orchestrator_update_checklist" in names
    assert "orchestrator_submit" in names
    assert "orchestrator_set_grade" in names
    assert "orchestrator_complete_recovery" in names
    assert "orchestrator_request_clarification" in names
    assert "orchestrator_escalate_requirement" in names
    assert "orchestrator_list_repos" in names
    assert "orchestrator_list_branches" in names
    assert "orchestrator_wait_for_run" in names
    assert "orchestrator_get_run_evidence" in names
    assert "orchestrator_create_child_run" not in names
    assert "orchestrator_get_parent_oversight" not in names


async def test_server_lists_tools(server: OrchestratorMCPServer) -> None:
    """Server lists all tools regardless of phase."""
    tools = await server.mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "orchestrator_get_requirements" in tool_names
    assert "orchestrator_update_checklist" in tool_names
    assert "orchestrator_submit" in tool_names
    assert "orchestrator_set_grade" in tool_names


async def test_server_call_tool(server: OrchestratorMCPServer, service: WorkflowService) -> None:
    """Can call a tool through the server's FastMCP instance."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    run = Run(
        id="run-1",
        repo_name="proj-1",
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
                                req_id="R1",
                                desc="Test requirement",
                                priority=Priority.CRITICAL,
                            ),
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )
    await service.create_run(run)

    # Call tool directly through FastMCP
    result = await server.mcp.call_tool(
        "orchestrator_get_requirements",
        {"run_id": "run-1", "task_id": "task-1"},
    )
    # FastMCP returns a list of content blocks
    assert len(result) > 0


def _parse_mcp_result(raw: object) -> dict[str, Any]:
    """Extract JSON from FastMCP call_tool result.

    call_tool returns (content_blocks_list, metadata_dict) or a list of content blocks.
    """
    raw_tuple: Any = raw
    content_blocks: Any = raw_tuple[0]
    text: str = content_blocks[0].text
    return json.loads(text)  # type: ignore[no-any-return]


async def test_full_workflow_through_mcp_server(
    server: OrchestratorMCPServer,
    service: WorkflowService,
) -> None:
    """Full builder→verifier workflow exercised entirely through MCP call_tool."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    run = Run(
        id="run-1",
        repo_name="proj-1",
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
                                req_id="R1",
                                desc="First requirement",
                                priority=Priority.CRITICAL,
                            ),
                            ChecklistItem(
                                req_id="R2",
                                desc="Second requirement",
                                priority=Priority.EXPECTED,
                            ),
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    call = server.mcp.call_tool

    # 1. Get requirements
    raw = await call("orchestrator_get_requirements", {"run_id": "run-1", "task_id": "task-1"})
    data = _parse_mcp_result(raw)
    assert len(data["requirements"]) == 2

    # 2. Mark R1 done
    raw = await call(
        "orchestrator_update_checklist",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R1", "status": "done"},
    )
    data = _parse_mcp_result(raw)
    assert data["status"] == "done"

    # 3. Mark R2 done
    raw = await call(
        "orchestrator_update_checklist",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R2", "status": "done"},
    )
    data = _parse_mcp_result(raw)
    assert data["status"] == "done"

    # 4. Submit — transitions to verifying
    raw = await call(
        "orchestrator_submit",
        {"run_id": "run-1", "task_id": "task-1"},
    )
    data = _parse_mcp_result(raw)
    assert data["success"] is True
    assert data["new_status"] == "verifying"

    # 5. Grade R1 via verifier-phase MCP server
    verifier_server = OrchestratorMCPServer(service, phase="verifying")
    verify_call = verifier_server.mcp.call_tool
    raw = await verify_call(
        "orchestrator_set_grade",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R1", "grade": "A"},
    )
    data = _parse_mcp_result(raw)
    assert data["grade"] == "A"

    # 6. Grade R2
    raw = await verify_call(
        "orchestrator_set_grade",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R2", "grade": "A"},
    )
    data = _parse_mcp_result(raw)
    assert data["grade"] == "A"

    # 7. Complete verification (via service — not an MCP tool)
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.COMPLETED
