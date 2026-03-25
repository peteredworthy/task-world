"""Integration tests for ClaudeSDKAgent with real WorkflowService.

Uses the _query_fn dependency injection mechanism to stub out the Claude Agent
SDK while exercising the full agent->callback->WorkflowService->DB path with a
real in-memory SQLite database and a real WorkflowService.

No mocking (no patch/MagicMock/monkeypatch) — all stubs are plain async
generator functions injected via the ClaudeSDKAgent constructor's _query_fn
kwarg.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from claude_agent_sdk import AssistantMessage, ResultMessage
from claude_agent_sdk.types import TextBlock, ToolUseBlock

from orchestrator.runners import ClaudeSDKAgent
from orchestrator.runners.types import ExecutionContext, ExecutionResult
from orchestrator.config.enums import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.service import WorkflowService


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


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


def _make_run(req_ids: list[str], run_id: str = "run-sdk-1") -> Run:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id=run_id,
        repo_name="sdk-test-project",
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
                                req_id=req_id,
                                desc=f"Requirement {req_id}",
                                priority=Priority.CRITICAL,
                            )
                            for req_id in req_ids
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


def _ctx(
    run_id: str = "run-sdk-1",
    task_id: str = "task-1",
    requirements: list[str] | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        run_id=run_id,
        task_id=task_id,
        working_dir="/tmp/sdk-test",
        prompt="Implement the required features.",
        requirements=requirements or ["R-01: implement feature"],
    )


# ---------------------------------------------------------------------------
# Helper: standard ResultMessage for success
# ---------------------------------------------------------------------------


def _success_result(
    input_tokens: int = 120,
    output_tokens: int = 60,
    num_turns: int = 2,
    duration_ms: int = 100,
    cost_usd: float = 0.01,
) -> ResultMessage:
    return ResultMessage(
        subtype="result",
        duration_ms=duration_ms,
        duration_api_ms=80,
        is_error=False,
        num_turns=num_turns,
        session_id="test-session",
        total_cost_usd=cost_usd,
        usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
        result="Done",
    )


# ---------------------------------------------------------------------------
# Integration test: builder phase drives task to VERIFYING
# ---------------------------------------------------------------------------


async def test_claude_sdk_builder_phase_completes_task(service: WorkflowService) -> None:
    """ClaudeSDKAgent builder phase: update_checklist + submit drives task to VERIFYING.

    Uses a real WorkflowService backed by an in-memory SQLite database.
    The SDK query function is replaced by a plain async generator injected via _query_fn.
    """
    req_ids = ["R-01", "R-02"]
    run = _make_run(req_ids)
    await service.create_run(run)
    await service.start_run("run-sdk-1")
    await service.start_task("run-sdk-1", "task-1")

    updates: list[tuple[str, ChecklistStatus]] = []

    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        updates.append((req_id, status))
        await service.update_checklist_item("run-sdk-1", "task-1", req_id, status, note)

    async def on_submit() -> None:
        await service.submit_for_verification("run-sdk-1", "task-1")

    async def builder_query(
        *, prompt: str, options: Any = None, transport: Any = None
    ) -> AsyncIterator[Any]:
        # Simulate Claude calling update_checklist for each req, then submit
        await on_checklist_update("R-01", ChecklistStatus.DONE, None)
        await on_checklist_update("R-02", ChecklistStatus.DONE, None)
        await on_submit()
        yield AssistantMessage(
            content=[TextBlock(text="Work complete.")],
            model="claude-sonnet-4-5",
        )
        yield _success_result()

    agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _query_fn=builder_query,
    )
    context = _ctx(requirements=[f"{rid}: requirement desc" for rid in req_ids])

    result = await agent.execute(context, on_checklist_update, on_submit)

    # Agent must report success.
    assert isinstance(result, ExecutionResult)
    assert result.success is True

    # Both requirements must have been marked done.
    assert ("R-01", ChecklistStatus.DONE) in updates
    assert ("R-02", ChecklistStatus.DONE) in updates

    # WorkflowService must have advanced the task to VERIFYING.
    task = await service.get_task("run-sdk-1", "task-1")
    assert task.status == TaskStatus.VERIFYING
    assert task.checklist[0].status == ChecklistStatus.DONE
    assert task.checklist[1].status == ChecklistStatus.DONE


# ---------------------------------------------------------------------------
# Integration test: verifier phase drives task to COMPLETED
# ---------------------------------------------------------------------------


async def test_claude_sdk_verifier_phase_completes_task(service: WorkflowService) -> None:
    """ClaudeSDKAgent verifier phase: grade + submit drives task to COMPLETED.

    Runs the builder phase with direct service calls, then uses ClaudeSDKAgent
    in verifier phase to grade and submit.
    """
    req_ids = ["R-01"]
    run = _make_run(req_ids, run_id="run-sdk-2")
    await service.create_run(run)
    await service.start_run("run-sdk-2")
    await service.start_task("run-sdk-2", "task-1")

    # Builder phase: directly advance state via service (not testing builder here).
    await service.update_checklist_item("run-sdk-2", "task-1", "R-01", ChecklistStatus.DONE, None)
    await service.submit_for_verification("run-sdk-2", "task-1")

    # Confirm task is now in VERIFYING.
    task = await service.get_task("run-sdk-2", "task-1")
    assert task.status == TaskStatus.VERIFYING

    # Verifier phase callbacks.
    grades_set: list[tuple[str, str]] = []

    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-sdk-2", "task-1", req_id, status, note)

    async def on_submit() -> None:
        await service.complete_verification("run-sdk-2", "task-1")

    async def on_grade(req_id: str, grade: str, reason: str | None) -> None:
        grades_set.append((req_id, grade))
        await service.set_grade("run-sdk-2", "task-1", req_id, grade)

    async def verifier_query(
        *, prompt: str, options: Any = None, transport: Any = None
    ) -> AsyncIterator[Any]:
        # Simulate Claude grading each requirement, then submitting
        await on_grade("R-01", "A", "Requirement met")
        await on_submit()
        yield AssistantMessage(
            content=[TextBlock(text="Verification complete. All requirements pass.")],
            model="claude-sonnet-4-5",
        )
        yield _success_result(num_turns=1)

    agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _query_fn=verifier_query,
    )
    context = _ctx(
        run_id="run-sdk-2",
        requirements=[f"{rid}: requirement desc" for rid in req_ids],
    )

    result = await agent.execute(
        context,
        on_checklist_update=on_checklist_update,
        on_submit=on_submit,
        on_grade=on_grade,
    )

    assert result.success is True
    assert ("R-01", "A") in grades_set

    # Task should now be COMPLETED.
    task = await service.get_task("run-sdk-2", "task-1")
    assert task.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Integration test: end_turn response path (ResultMessage without error)
# ---------------------------------------------------------------------------


async def test_claude_sdk_end_turn_auto_submit(service: WorkflowService) -> None:
    """ClaudeSDKAgent: SDK session completes with ResultMessage, submit called via MCP.

    In the new SDK-based implementation, the SDK handles the full agentic loop.
    The _query_fn simulates a session where Claude calls submit via the MCP tool
    (represented here by calling on_submit directly), then yields a ResultMessage.
    """
    req_ids = ["R-01"]
    run = _make_run(req_ids, run_id="run-sdk-3")
    await service.create_run(run)
    await service.start_run("run-sdk-3")
    await service.start_task("run-sdk-3", "task-1")

    # Mark checklist done manually so gate check passes on submit.
    await service.update_checklist_item("run-sdk-3", "task-1", "R-01", ChecklistStatus.DONE, None)

    submit_count = [0]

    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-sdk-3", "task-1", req_id, status, note)

    async def on_submit() -> None:
        submit_count[0] += 1
        await service.submit_for_verification("run-sdk-3", "task-1")

    async def end_turn_query(
        *, prompt: str, options: Any = None, transport: Any = None
    ) -> AsyncIterator[Any]:
        # Simulate Claude completing work and calling submit via MCP tool
        await on_submit()
        yield AssistantMessage(
            content=[TextBlock(text="I have completed the work.")],
            model="claude-sonnet-4-5",
        )
        yield _success_result(num_turns=1)

    agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _query_fn=end_turn_query,
    )
    context = _ctx(
        run_id="run-sdk-3",
        requirements=["R-01: requirement desc"],
    )

    result = await agent.execute(context, on_checklist_update, on_submit)

    assert result.success is True
    # Submit must have been called exactly once.
    assert submit_count[0] == 1
    # Output lines must contain the text.
    assert "I have completed the work." in result.output_lines

    task = await service.get_task("run-sdk-3", "task-1")
    assert task.status == TaskStatus.VERIFYING


# ---------------------------------------------------------------------------
# Integration test: token metrics from ResultMessage
# ---------------------------------------------------------------------------


async def test_claude_sdk_token_metrics_accumulated(service: WorkflowService) -> None:
    """ExecutionResult contains token metrics extracted from ResultMessage.usage."""
    req_ids = ["R-01"]
    run = _make_run(req_ids, run_id="run-sdk-4")
    await service.create_run(run)
    await service.start_run("run-sdk-4")
    await service.start_task("run-sdk-4", "task-1")

    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-sdk-4", "task-1", req_id, status, note)

    async def on_submit() -> None:
        await service.submit_for_verification("run-sdk-4", "task-1")

    async def metrics_query(
        *, prompt: str, options: Any = None, transport: Any = None
    ) -> AsyncIterator[Any]:
        # Simulate Claude updating checklist and submitting
        await on_checklist_update("R-01", ChecklistStatus.DONE, None)
        await on_submit()
        yield AssistantMessage(
            content=[
                TextBlock(text="Implemented the feature."),
                ToolUseBlock(
                    id="tu-1", name="update_checklist", input={"req_id": "R-01", "status": "done"}
                ),
                ToolUseBlock(id="tu-2", name="submit", input={}),
            ],
            model="claude-sonnet-4-5",
        )
        yield _success_result(
            input_tokens=500,
            output_tokens=250,
            num_turns=3,
            duration_ms=1500,
            cost_usd=0.05,
        )

    agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _query_fn=metrics_query,
    )
    context = _ctx(
        run_id="run-sdk-4",
        requirements=["R-01: requirement desc"],
    )

    result = await agent.execute(context, on_checklist_update, on_submit)

    assert result.success is True
    # Metrics come from ResultMessage.usage
    assert result.metrics.tokens_read == 500
    assert result.metrics.tokens_write == 250
    assert result.metrics.duration_ms >= 0
    # num_actions = max(tool_use_blocks_counted, ResultMessage.num_turns) = max(2, 3) = 3
    assert result.metrics.num_actions == 3


# ---------------------------------------------------------------------------
# Integration test: full builder+verifier lifecycle in one test
# ---------------------------------------------------------------------------


async def test_claude_sdk_full_builder_verifier_lifecycle(service: WorkflowService) -> None:
    """Full lifecycle: ClaudeSDKAgent builder phase then verifier phase via callbacks.

    Demonstrates the complete end-to-end flow:
      builder agent -> submit -> task VERIFYING
      verifier agent -> grade -> complete_verification -> task COMPLETED
    """
    req_ids = ["R-01", "R-02"]
    run = _make_run(req_ids, run_id="run-sdk-5")
    await service.create_run(run)
    await service.start_run("run-sdk-5")
    await service.start_task("run-sdk-5", "task-1")

    # --- Builder phase ---
    async def builder_on_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-sdk-5", "task-1", req_id, status, note)

    async def builder_on_submit() -> None:
        await service.submit_for_verification("run-sdk-5", "task-1")

    async def builder_query(
        *, prompt: str, options: Any = None, transport: Any = None
    ) -> AsyncIterator[Any]:
        # Simulate builder updating all requirements and submitting
        await builder_on_checklist("R-01", ChecklistStatus.DONE, None)
        await builder_on_checklist("R-02", ChecklistStatus.DONE, None)
        await builder_on_submit()
        yield AssistantMessage(
            content=[TextBlock(text="All requirements implemented.")],
            model="claude-sonnet-4-5",
        )
        yield _success_result(num_turns=2)

    builder_agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _query_fn=builder_query,
    )
    builder_ctx = _ctx(
        run_id="run-sdk-5",
        requirements=[f"{rid}: requirement desc" for rid in req_ids],
    )

    builder_result = await builder_agent.execute(
        builder_ctx, builder_on_checklist, builder_on_submit
    )
    assert builder_result.success is True

    task = await service.get_task("run-sdk-5", "task-1")
    assert task.status == TaskStatus.VERIFYING

    # --- Verifier phase ---
    async def verifier_on_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-sdk-5", "task-1", req_id, status, note)

    async def verifier_on_submit() -> None:
        await service.complete_verification("run-sdk-5", "task-1")

    async def verifier_on_grade(req_id: str, grade: str, reason: str | None) -> None:
        await service.set_grade("run-sdk-5", "task-1", req_id, grade)

    async def verifier_query(
        *, prompt: str, options: Any = None, transport: Any = None
    ) -> AsyncIterator[Any]:
        # Simulate verifier grading all requirements and completing
        await verifier_on_grade("R-01", "A", "Excellent implementation")
        await verifier_on_grade("R-02", "A", "Meets all criteria")
        await verifier_on_submit()
        yield AssistantMessage(
            content=[TextBlock(text="All requirements verified with grade A.")],
            model="claude-sonnet-4-5",
        )
        yield _success_result(num_turns=1)

    verifier_agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _query_fn=verifier_query,
    )
    verifier_ctx = _ctx(
        run_id="run-sdk-5",
        requirements=[f"{rid}: requirement desc" for rid in req_ids],
    )

    verifier_result = await verifier_agent.execute(
        verifier_ctx,
        on_checklist_update=verifier_on_checklist,
        on_submit=verifier_on_submit,
        on_grade=verifier_on_grade,
    )
    assert verifier_result.success is True

    task = await service.get_task("run-sdk-5", "task-1")
    assert task.status == TaskStatus.COMPLETED
    # Both requirements should have A grades.
    for item in task.checklist:
        assert item.grade == "A", f"Expected grade A for {item.req_id}, got {item.grade}"
