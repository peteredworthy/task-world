"""Integration tests for ClaudeSDKAgent with real WorkflowService.

Uses the _client dependency injection mechanism to stub out the Anthropic API
while exercising the full agent->callback->WorkflowService->DB path with a real
in-memory SQLite database and a real WorkflowService.

No mocking (no patch/MagicMock/monkeypatch) — all stubs are plain inline classes
injected via the ClaudeSDKAgent constructor's _client kwarg.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.agents.claude_sdk import ClaudeSDKAgent
from orchestrator.agents.types import ExecutionContext, ExecutionResult
from orchestrator.config.enums import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.service import WorkflowService


# ---------------------------------------------------------------------------
# Fake Anthropic client stubs (plain classes, no mocking library)
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, input_tokens: int = 120, output_tokens: int = 60) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeToolUseBlock:
    def __init__(self, id: str, name: str, input: dict[str, Any]) -> None:  # noqa: A002
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input


class _FakeResponse:
    def __init__(
        self,
        content: list[Any],
        stop_reason: str = "end_turn",
        input_tokens: int = 120,
        output_tokens: int = 60,
    ) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _FakeUsage(input_tokens, output_tokens)


class _BuilderToolUseClient:
    """Simulates Claude in builder phase: update_checklist for each requirement, then submit.

    The first API call returns tool_use blocks for update_checklist (R-01) and submit.
    Subsequent calls (should not be reached) return end_turn.
    """

    def __init__(self, req_ids: list[str]) -> None:
        self._req_ids = req_ids
        self._call_count = 0

        class _Messages:
            def __init__(self_, client: _BuilderToolUseClient) -> None:
                self_._client = client

            def create(self_, **kwargs: Any) -> _FakeResponse:
                count = self_._client._call_count
                self_._client._call_count += 1
                if count == 0:
                    blocks: list[Any] = []
                    for i, req_id in enumerate(self_._client._req_ids):
                        blocks.append(
                            _FakeToolUseBlock(
                                id=f"tu-cl-{i}",
                                name="update_checklist",
                                input={"req_id": req_id, "status": "done"},
                            )
                        )
                    blocks.append(_FakeToolUseBlock(id="tu-submit", name="submit", input={}))
                    return _FakeResponse(content=blocks, stop_reason="tool_use")
                return _FakeResponse(content=[], stop_reason="end_turn")

        self.messages = _Messages(self)


class _VerifierToolUseClient:
    """Simulates Claude in verifier phase: grade each requirement then submit."""

    def __init__(self, req_ids: list[str], grade: str = "A") -> None:
        self._req_ids = req_ids
        self._grade = grade
        self._call_count = 0

        class _Messages:
            def __init__(self_, client: _VerifierToolUseClient) -> None:
                self_._client = client

            def create(self_, **kwargs: Any) -> _FakeResponse:
                count = self_._client._call_count
                self_._client._call_count += 1
                if count == 0:
                    blocks: list[Any] = []
                    for i, req_id in enumerate(self_._client._req_ids):
                        blocks.append(
                            _FakeToolUseBlock(
                                id=f"tu-grade-{i}",
                                name="grade",
                                input={
                                    "req_id": req_id,
                                    "grade": self_._client._grade,
                                    "grade_reason": "Requirement met",
                                },
                            )
                        )
                    blocks.append(_FakeToolUseBlock(id="tu-submit", name="submit", input={}))
                    return _FakeResponse(content=blocks, stop_reason="tool_use")
                return _FakeResponse(content=[], stop_reason="end_turn")

        self.messages = _Messages(self)


class _EndTurnClient:
    """Returns a single end_turn text response — no tool calls."""

    def __init__(self, text: str = "Work complete.") -> None:
        self._text = text

        class _Messages:
            def __init__(self_, client: _EndTurnClient) -> None:
                self_._client = client

            def create(self_, **kwargs: Any) -> _FakeResponse:
                return _FakeResponse(
                    content=[_FakeTextBlock(self_._client._text)],
                    stop_reason="end_turn",
                )

        self.messages = _Messages(self)


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
# Integration test: builder phase drives task to VERIFYING
# ---------------------------------------------------------------------------


async def test_claude_sdk_builder_phase_completes_task(service: WorkflowService) -> None:
    """ClaudeSDKAgent builder phase: update_checklist + submit drives task to VERIFYING.

    Uses a real WorkflowService backed by an in-memory SQLite database.
    The Anthropic client is replaced by a plain stub injected via _client.
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

    agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _client=_BuilderToolUseClient(req_ids),
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

    Runs the builder phase with MockAgent logic (direct service calls), then
    uses ClaudeSDKAgent in verifier phase to grade and submit.
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

    agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _client=_VerifierToolUseClient(req_ids, grade="A"),
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
# Integration test: end_turn response path (auto-submit)
# ---------------------------------------------------------------------------


async def test_claude_sdk_end_turn_auto_submit(service: WorkflowService) -> None:
    """ClaudeSDKAgent: end_turn response triggers auto-submit callback.

    When Claude returns end_turn without calling submit, the agent automatically
    calls on_submit(). Verifies this auto-submit path flows through to WorkflowService.
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

    agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _client=_EndTurnClient(text="I have completed the work."),
    )
    context = _ctx(
        run_id="run-sdk-3",
        requirements=["R-01: requirement desc"],
    )

    result = await agent.execute(context, on_checklist_update, on_submit)

    assert result.success is True
    # Auto-submit must have been called exactly once.
    assert submit_count[0] == 1
    # Output lines must contain the text.
    assert "I have completed the work." in result.output_lines

    task = await service.get_task("run-sdk-3", "task-1")
    assert task.status == TaskStatus.VERIFYING


# ---------------------------------------------------------------------------
# Integration test: token metrics accumulated across turns
# ---------------------------------------------------------------------------


async def test_claude_sdk_token_metrics_accumulated(service: WorkflowService) -> None:
    """ExecutionResult contains non-zero token metrics after a successful run."""
    req_ids = ["R-01"]
    run = _make_run(req_ids, run_id="run-sdk-4")
    await service.create_run(run)
    await service.start_run("run-sdk-4")
    await service.start_task("run-sdk-4", "task-1")

    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-sdk-4", "task-1", req_id, status, note)

    async def on_submit() -> None:
        await service.submit_for_verification("run-sdk-4", "task-1")

    agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _client=_BuilderToolUseClient(req_ids),
    )
    context = _ctx(
        run_id="run-sdk-4",
        requirements=["R-01: requirement desc"],
    )

    result = await agent.execute(context, on_checklist_update, on_submit)

    assert result.success is True
    assert result.metrics.tokens_read > 0
    assert result.metrics.tokens_write > 0
    assert result.metrics.duration_ms >= 0
    # One update_checklist tool call + one submit tool call = 2 actions.
    assert result.metrics.num_actions == 2


# ---------------------------------------------------------------------------
# Integration test: full builder+verifier lifecycle in one test
# ---------------------------------------------------------------------------


async def test_claude_sdk_full_builder_verifier_lifecycle(service: WorkflowService) -> None:
    """Full lifecycle: ClaudeSDKAgent builder phase then verifier phase via callbacks.

    Demonstrates the complete end-to-end flow:
      builder agent → submit → task VERIFYING
      verifier agent → grade → complete_verification → task COMPLETED
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

    builder_agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _client=_BuilderToolUseClient(req_ids),
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

    verifier_agent = ClaudeSDKAgent(
        api_key="sk-ant-integration-test",  # pragma: allowlist secret
        _client=_VerifierToolUseClient(req_ids, grade="A"),
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
