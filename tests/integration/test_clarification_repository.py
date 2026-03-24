"""Integration tests for clarification request/response repository methods."""

from datetime import datetime, timezone
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import RunRepository
from orchestrator.workflow.clarifications import (
    ClarificationAnswer,
    ClarificationQuestion,
    ClarificationRequest,
    ClarificationResponse,
)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> RunRepository:
    return RunRepository(session)


def _make_clarification_request(
    request_id: str = "req-1",
    run_id: str = "run-1",
    task_id: str = "task-1",
) -> ClarificationRequest:
    """Create a sample clarification request for testing."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return ClarificationRequest(
        id=request_id,
        run_id=run_id,
        task_id=task_id,
        attempt_num=1,
        questions=[
            ClarificationQuestion(
                id="q1",
                question="Should we use authentication?",
                context="The spec mentions user access but doesn't specify auth.",
                options=["Yes, use OAuth", "Yes, use basic auth", "No auth needed"],
            ),
            ClarificationQuestion(
                id="q2",
                question="Which database?",
                context="No database is specified in requirements.",
                options=["PostgreSQL", "MySQL", "SQLite", "MongoDB"],
            ),
        ],
        created_at=now,
    )


def _make_clarification_response(
    request_id: str = "req-1",
) -> ClarificationResponse:
    """Create a sample clarification response for testing."""
    now = datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc)
    return ClarificationResponse(
        request_id=request_id,
        answers=[
            ClarificationAnswer(
                question_id="q1",
                selected_option="Yes, use OAuth",
                answered_by="user@example.com",
                answered_at=now,
            ),
            ClarificationAnswer(
                question_id="q2",
                selected_option="PostgreSQL",
                answered_by="user@example.com",
                answered_at=now,
            ),
        ],
        responded_at=now,
    )


async def test_create_clarification_request(repo: RunRepository) -> None:
    """Test creating a clarification request."""
    request = _make_clarification_request()

    created = await repo.create_clarification_request(request)

    assert created.id == "req-1"
    assert created.run_id == "run-1"
    assert created.task_id == "task-1"
    assert created.attempt_num == 1
    assert len(created.questions) == 2
    assert created.questions[0].id == "q1"
    assert created.questions[0].question == "Should we use authentication?"
    assert created.questions[1].id == "q2"
    assert created.responded_at is None


async def test_get_clarification_request(repo: RunRepository) -> None:
    """Test retrieving a clarification request by ID."""
    request = _make_clarification_request()
    await repo.create_clarification_request(request)

    loaded = await repo.get_clarification_request("req-1")

    assert loaded is not None
    assert loaded.id == "req-1"
    assert loaded.run_id == "run-1"
    assert loaded.task_id == "task-1"
    assert loaded.attempt_num == 1
    assert len(loaded.questions) == 2
    assert loaded.questions[0].question == "Should we use authentication?"
    assert loaded.questions[0].context == "The spec mentions user access but doesn't specify auth."
    assert loaded.questions[0].options == [
        "Yes, use OAuth",
        "Yes, use basic auth",
        "No auth needed",
    ]
    assert loaded.questions[1].question == "Which database?"
    assert loaded.questions[1].options == ["PostgreSQL", "MySQL", "SQLite", "MongoDB"]
    assert loaded.responded_at is None


async def test_get_clarification_request_nonexistent(repo: RunRepository) -> None:
    """Test getting a nonexistent clarification request returns None."""
    loaded = await repo.get_clarification_request("nonexistent")

    assert loaded is None


async def test_get_pending_clarification(repo: RunRepository) -> None:
    """Test retrieving a pending clarification for a task."""
    request = _make_clarification_request()
    await repo.create_clarification_request(request)

    pending = await repo.get_pending_clarification("run-1", "task-1")

    assert pending is not None
    assert pending.id == "req-1"
    assert pending.responded_at is None
    assert len(pending.questions) == 2


async def test_get_pending_clarification_wrong_task(repo: RunRepository) -> None:
    """Test that pending clarification is task-specific."""
    request = _make_clarification_request()
    await repo.create_clarification_request(request)

    pending = await repo.get_pending_clarification("run-1", "task-2")

    assert pending is None


async def test_get_pending_clarification_wrong_run(repo: RunRepository) -> None:
    """Test that pending clarification is run-specific."""
    request = _make_clarification_request()
    await repo.create_clarification_request(request)

    pending = await repo.get_pending_clarification("run-2", "task-1")

    assert pending is None


async def test_get_pending_clarification_after_response(repo: RunRepository) -> None:
    """Test that responded clarifications are not returned as pending."""
    request = _make_clarification_request()
    await repo.create_clarification_request(request)

    # Save a response
    response = _make_clarification_response()
    await repo.save_clarification_response(response)

    # Should no longer be pending
    pending = await repo.get_pending_clarification("run-1", "task-1")

    assert pending is None


async def test_save_clarification_response(repo: RunRepository) -> None:
    """Test saving a clarification response."""
    request = _make_clarification_request()
    await repo.create_clarification_request(request)

    response = _make_clarification_response()
    await repo.save_clarification_response(response)

    # Verify request is marked as responded
    loaded = await repo.get_clarification_request("req-1")

    assert loaded is not None
    assert loaded.responded_at is not None
    assert loaded.responded_at == datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc)


async def test_save_clarification_response_updates_responded_at(repo: RunRepository) -> None:
    """Test that save_clarification_response updates responded_at timestamp."""
    request = _make_clarification_request()
    await repo.create_clarification_request(request)

    # Verify initially None
    loaded = await repo.get_clarification_request("req-1")
    assert loaded is not None
    assert loaded.responded_at is None

    # Save response
    response_time = datetime(2025, 1, 15, 11, 30, 0, tzinfo=timezone.utc)
    response = ClarificationResponse(
        request_id="req-1",
        answers=[
            ClarificationAnswer(
                question_id="q1",
                selected_option="Yes, use OAuth",
                answered_by="admin@example.com",
                answered_at=response_time,
            ),
        ],
        responded_at=response_time,
    )
    await repo.save_clarification_response(response)

    # Verify responded_at is updated
    loaded = await repo.get_clarification_request("req-1")
    assert loaded is not None
    assert loaded.responded_at == response_time


async def test_multiple_clarifications_for_different_tasks(repo: RunRepository) -> None:
    """Test multiple clarification requests for different tasks."""
    req1 = _make_clarification_request("req-1", "run-1", "task-1")
    req2 = _make_clarification_request("req-2", "run-1", "task-2")

    await repo.create_clarification_request(req1)
    await repo.create_clarification_request(req2)

    # Each task should have its own pending clarification
    pending1 = await repo.get_pending_clarification("run-1", "task-1")
    pending2 = await repo.get_pending_clarification("run-1", "task-2")

    assert pending1 is not None
    assert pending1.id == "req-1"
    assert pending2 is not None
    assert pending2.id == "req-2"


async def test_multiple_clarifications_for_different_runs(repo: RunRepository) -> None:
    """Test multiple clarification requests for different runs."""
    req1 = _make_clarification_request("req-1", "run-1", "task-1")
    req2 = _make_clarification_request("req-2", "run-2", "task-1")

    await repo.create_clarification_request(req1)
    await repo.create_clarification_request(req2)

    # Each run should have its own pending clarification
    pending1 = await repo.get_pending_clarification("run-1", "task-1")
    pending2 = await repo.get_pending_clarification("run-2", "task-1")

    assert pending1 is not None
    assert pending1.id == "req-1"
    assert pending2 is not None
    assert pending2.id == "req-2"


async def test_clarification_with_free_text_answer(repo: RunRepository) -> None:
    """Test clarification response with free text answer."""
    request = _make_clarification_request()
    await repo.create_clarification_request(request)

    response_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    response = ClarificationResponse(
        request_id="req-1",
        answers=[
            ClarificationAnswer(
                question_id="q1",
                free_text="We should use OAuth 2.0 with PKCE flow",
                answered_by="tech-lead@example.com",
                answered_at=response_time,
            ),
        ],
        responded_at=response_time,
    )

    await repo.save_clarification_response(response)

    # Verify request is marked as responded
    loaded = await repo.get_clarification_request("req-1")
    assert loaded is not None
    assert loaded.responded_at == response_time


async def test_clarification_roundtrip_preserves_data(repo: RunRepository) -> None:
    """Test that clarification data survives save/load cycle."""
    original = _make_clarification_request()
    await repo.create_clarification_request(original)

    loaded = await repo.get_clarification_request("req-1")

    assert loaded is not None
    assert loaded.id == original.id
    assert loaded.run_id == original.run_id
    assert loaded.task_id == original.task_id
    assert loaded.attempt_num == original.attempt_num
    assert loaded.created_at == original.created_at
    assert loaded.responded_at == original.responded_at

    # Verify questions are preserved exactly
    assert len(loaded.questions) == len(original.questions)
    for loaded_q, orig_q in zip(loaded.questions, original.questions):
        assert loaded_q.id == orig_q.id
        assert loaded_q.question == orig_q.question
        assert loaded_q.context == orig_q.context
        assert loaded_q.options == orig_q.options
