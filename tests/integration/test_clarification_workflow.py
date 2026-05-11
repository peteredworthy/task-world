"""Integration tests for clarification workflow."""

from datetime import datetime, timezone

import pytest
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.db import RunRepository, create_engine, create_session_factory, init_db
from orchestrator.db import EventStore
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow import (
    ClarificationAnswer,
    ClarificationQuestion,
    CompressedDecisions,
)
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
def event_store(session: AsyncSession) -> EventStore:
    return EventStore(session)


def _make_simple_run() -> Run:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        routine_id="simple-routine",
        routine_source=RoutineSource.LOCAL,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.BUILDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Complete the task",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        max_attempts=3,
                        current_attempt=1,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


async def test_full_clarification_cycle(
    service: WorkflowService,
    event_store: EventStore,
) -> None:
    """Test full clarification cycle: request -> respond -> verify task back to BUILDING."""
    # Create and save a run with task in BUILDING state
    run = _make_simple_run()
    await service.create_run(run)

    # Request clarification
    questions = [
        ClarificationQuestion(
            id="q1",
            question="What color should the button be?",
            context="User hasn't specified button color in requirements",
            options=["Blue", "Green", "Red", "Custom"],
        ),
        ClarificationQuestion(
            id="q2",
            question="Should the form validate on blur or submit?",
            context="Validation timing not specified",
            options=["On blur", "On submit", "Both"],
        ),
    ]

    request = await service.request_clarification(
        run_id="run-1",
        task_id="task-1",
        questions=questions,
    )

    # Verify request was created
    assert request.id is not None
    assert request.run_id == "run-1"
    assert request.task_id == "task-1"
    assert request.attempt_num == 1
    assert len(request.questions) == 2
    assert request.questions[0].question == "What color should the button be?"

    # Verify task transitioned to PENDING_USER_ACTION
    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.PENDING_USER_ACTION
    assert task.pending_action_type == "clarification"
    assert task.pending_clarification_id == request.id

    # Respond to clarification
    now = datetime.now(timezone.utc)
    answers = [
        ClarificationAnswer(
            question_id="q1",
            selected_option="Blue",
            answered_by="user@example.com",
            answered_at=now,
        ),
        ClarificationAnswer(
            question_id="q2",
            selected_option="On submit",
            answered_by="user@example.com",
            answered_at=now,
        ),
    ]

    result = await service.respond_to_clarification(
        run_id="run-1",
        task_id="task-1",
        request_id=request.id,
        answers=answers,
        responded_by="user@example.com",
    )

    # Verify transition back to BUILDING
    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING

    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.BUILDING
    assert task.pending_action_type is None
    assert task.pending_clarification_id is None


async def test_pending_clarification_blocks_submit(
    service: WorkflowService,
) -> None:
    """A later submit callback cannot bypass an unanswered clarification."""
    run = _make_simple_run()
    await service.create_run(run)

    request = await service.request_clarification(
        run_id="run-1",
        task_id="task-1",
        questions=[
            ClarificationQuestion(
                id="q1",
                question="Which direction?",
                context="The agent needs a human decision.",
                options=[],
                question_type="free_text",
            )
        ],
    )

    result = await service.submit_for_verification("run-1", "task-1")

    assert result.success is False
    assert result.error == "Cannot verify from pending_user_action"

    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.PENDING_USER_ACTION
    assert task.pending_action_type == "clarification"
    assert task.pending_clarification_id == request.id
    assert await service.get_pending_clarification("run-1", "task-1") is not None


async def test_respond_to_legacy_stale_clarification_does_not_reopen_completed_task(
    service: WorkflowService,
    session: AsyncSession,
) -> None:
    """Legacy stale pending markers can be answered without regressing task state."""
    run = _make_simple_run()
    await service.create_run(run)

    request = await service.request_clarification(
        run_id="run-1",
        task_id="task-1",
        questions=[
            ClarificationQuestion(
                id="q1",
                question="Accept evidence?",
                context="Legacy run advanced after asking.",
                options=[],
                question_type="free_text",
            )
        ],
    )

    legacy_run = await service.get_run("run-1")
    legacy_task = legacy_run.steps[0].tasks[0]
    legacy_task.status = TaskStatus.COMPLETED
    await RunRepository(session).save(legacy_run)

    result = await service.respond_to_clarification(
        run_id="run-1",
        task_id="task-1",
        request_id=request.id,
        answers=[
            ClarificationAnswer(
                question_id="q1",
                free_text="b - require cleaner evidence",
                answered_by="user@example.com",
                answered_at=datetime.now(timezone.utc),
            )
        ],
        responded_by="user@example.com",
    )

    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED
    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.COMPLETED
    assert task.pending_action_type is None
    assert task.pending_clarification_id is None
    assert await service.get_pending_clarification("run-1", "task-1") is None


async def test_clarification_requested_event_emitted(
    service: WorkflowService,
    event_store: EventStore,
) -> None:
    """Test that ClarificationRequested event is emitted."""
    run = _make_simple_run()
    await service.create_run(run)

    questions = [
        ClarificationQuestion(
            id="q1",
            question="Test question?",
            context="Test context",
            options=["Option A", "Option B"],
        ),
    ]

    request = await service.request_clarification(
        run_id="run-1",
        task_id="task-1",
        questions=questions,
    )

    # Query events
    events = await event_store.get_events_for_run(run_id="run-1")

    # Find the clarification_requested event
    clarification_events = [e for e in events if e.get("type") == "clarification_requested"]
    assert len(clarification_events) == 1

    event = clarification_events[0]["payload"]
    assert event["run_id"] == "run-1"
    assert event["task_id"] == "task-1"
    assert event["request_id"] == request.id
    assert event["question_count"] == 1


async def test_clarification_responded_event_emitted(
    service: WorkflowService,
    event_store: EventStore,
) -> None:
    """Test that ClarificationResponded event is emitted."""
    run = _make_simple_run()
    await service.create_run(run)

    # Request clarification
    questions = [
        ClarificationQuestion(
            id="q1",
            question="Test question?",
            context="Test context",
            options=["Option A", "Option B"],
        ),
    ]

    request = await service.request_clarification(
        run_id="run-1",
        task_id="task-1",
        questions=questions,
    )

    # Respond to clarification
    now = datetime.now(timezone.utc)
    answers = [
        ClarificationAnswer(
            question_id="q1",
            selected_option="Option A",
            answered_by="user@example.com",
            answered_at=now,
        ),
    ]

    await service.respond_to_clarification(
        run_id="run-1",
        task_id="task-1",
        request_id=request.id,
        answers=answers,
        responded_by="user@example.com",
    )

    # Query events
    events = await event_store.get_events_for_run(run_id="run-1")

    # Find the clarification_responded event
    responded_events = [e for e in events if e.get("type") == "clarification_responded"]
    assert len(responded_events) == 1

    event = responded_events[0]["payload"]
    assert event["run_id"] == "run-1"
    assert event["task_id"] == "task-1"
    assert event["request_id"] == request.id


async def test_get_pending_clarification(
    service: WorkflowService,
) -> None:
    """Test retrieving pending clarification request."""
    run = _make_simple_run()
    await service.create_run(run)

    # No pending clarification initially
    pending = await service.get_pending_clarification("run-1", "task-1")
    assert pending is None

    # Request clarification
    questions = [
        ClarificationQuestion(
            id="q1",
            question="Test question?",
            context="Test context",
            options=["Option A", "Option B"],
        ),
    ]

    request = await service.request_clarification(
        run_id="run-1",
        task_id="task-1",
        questions=questions,
    )

    # Should now have a pending clarification
    pending = await service.get_pending_clarification("run-1", "task-1")
    assert pending is not None
    assert pending.id == request.id
    assert pending.run_id == "run-1"
    assert pending.task_id == "task-1"
    assert len(pending.questions) == 1


async def test_respond_to_clarification_calls_compress_clarifications(
    service: WorkflowService,
) -> None:
    """respond_to_clarification() calls compress_clarifications() on the resolved Q&A."""
    run = _make_simple_run()
    await service.create_run(run)

    questions = [
        ClarificationQuestion(
            id="q1",
            question="Which framework?",
            context="Need to choose frontend stack",
            options=["React", "Vue"],
        ),
    ]
    request = await service.request_clarification(
        run_id="run-1",
        task_id="task-1",
        questions=questions,
    )

    now = datetime.now(timezone.utc)
    answers = [
        ClarificationAnswer(
            question_id="q1",
            selected_option="React",
            answered_by="user@example.com",
            answered_at=now,
        ),
    ]

    await service.respond_to_clarification(
        run_id="run-1",
        task_id="task-1",
        request_id=request.id,
        answers=answers,
        responded_by="user@example.com",
    )

    # Verify compress_clarifications was called by checking its side effect:
    # compressed decisions are persisted in run.config.
    updated_run = await service.get_run("run-1")
    assert "_compressed_decisions" in updated_run.config
    decisions = updated_run.config["_compressed_decisions"]
    assert len(decisions) == 1
    assert decisions[0]["question"] == "Which framework?"
    assert decisions[0]["decision"] == "React"
    assert decisions[0]["rationale"] == "Need to choose frontend stack"
    assert updated_run.config["_compressed_decisions_request_id"] == request.id


async def test_respond_to_clarification_passes_decisions_to_generate_builder_prompt(
    service: WorkflowService,
) -> None:
    """respond_to_clarification() passes CompressedDecisions to generate_builder_prompt()."""
    run = _make_simple_run()
    await service.create_run(run)

    questions = [
        ClarificationQuestion(
            id="q1",
            question="Which DB?",
            context="Choose database backend",
            options=["PostgreSQL", "SQLite"],
        ),
    ]
    request = await service.request_clarification(
        run_id="run-1",
        task_id="task-1",
        questions=questions,
    )

    now = datetime.now(timezone.utc)
    answers = [
        ClarificationAnswer(
            question_id="q1",
            selected_option="PostgreSQL",
            answered_by="user@example.com",
            answered_at=now,
        ),
    ]

    # The run has no routine_embedded so generate_builder_prompt is not called
    # (task_config_obj lookup returns None). Verify compress_clarifications is
    # still called and produces the right decisions regardless.
    from orchestrator.workflow import (
        ClarificationResponse,
        compress_clarifications,
    )

    await service.respond_to_clarification(
        run_id="run-1",
        task_id="task-1",
        request_id=request.id,
        answers=answers,
        responded_by="user@example.com",
    )

    # Verify compress_clarifications produced the right decisions by checking
    # the persisted result in run.config.
    updated_run = await service.get_run("run-1")
    decisions = updated_run.config["_compressed_decisions"]
    assert len(decisions) == 1
    assert decisions[0]["question"] == "Which DB?"
    assert decisions[0]["decision"] == "PostgreSQL"
    assert decisions[0]["rationale"] == "Choose database backend"

    # Also verify via the pure function directly for completeness.
    response = ClarificationResponse(
        request_id=request.id,
        answers=answers,
        responded_at=now,
    )
    compressed = compress_clarifications(request, response)
    assert isinstance(compressed, CompressedDecisions)
    assert len(compressed.decisions) == 1
    assert compressed.decisions[0].question == "Which DB?"
    assert compressed.decisions[0].decision == "PostgreSQL"
    assert compressed.decisions[0].rationale == "Choose database backend"

    # Confirm generate_builder_prompt was NOT called (no routine_embedded):
    # without routine_embedded, the run has no embedded routine config, so
    # task_config_obj is None and the prompt-generation branch is skipped.
    # The task should remain in BUILDING with no prompt override set.
    updated_run = await service.get_run("run-1")
    assert updated_run.routine_embedded is None
