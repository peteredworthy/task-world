"""Integration tests for the single-queue signal model.

These tests verify:
- R4: Full lifecycle via queue: RUN_START consumed → DRAFT→ACTIVE
- R5: STOPPING state path: pause active run → STOPPING → PAUSED
- Concurrent runs: two runs process signals independently
- RESUME functional: PAUSED → ACTIVE via queue
- CANCEL via queue: ACTIVE/PAUSED → FAILED
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport
from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport_obj = InMemorySignalTransport()
    app.state.signal_transport = transport_obj
    drain = make_drain_fn(app, transport_obj)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


@pytest.fixture
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    return client_and_drain[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_run(
    client: AsyncClient,
    routine_id: str = "simple-routine",
    repo_name: str = "queue-test-repo",
    branch: str = "main",
    **extra: Any,
) -> dict[str, Any]:
    resp = await client.post(
        "/api/runs",
        json={"routine_id": routine_id, "repo_name": repo_name, "branch": branch, **extra},
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    return resp.json()


async def _get_run(client: AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# R4: Full lifecycle via queue — RUN_START consumed → DRAFT→ACTIVE
# ---------------------------------------------------------------------------


async def test_run_start_signal_consumed_draft_to_active(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """POST /start returns 202; RUN_START signal is consumed by drain; run becomes ACTIVE.

    This is the core R4 requirement: the single-queue model routes RUN_START
    through events_v2 and the consumer applies the DRAFT→ACTIVE transition.
    """
    client, drain = client_and_drain

    # 1. Create a run — starts in DRAFT state
    run_data = await _create_run(client, repo_name="r4-draft-to-active")
    run_id = run_data["id"]
    assert run_data["status"] == "draft", "Newly created run must be DRAFT"

    # 2. POST /start — returns 202 (signal enqueued, not yet applied)
    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202, f"Expected 202, got {start_resp.status_code}"

    # 3. Before drain: run should still be DRAFT (signal not yet processed)
    before_drain = await _get_run(client, run_id)
    assert before_drain["status"] == "draft", (
        "Before consumer processes RUN_START, run must still be DRAFT"
    )

    # 4. Drain — consumer processes RUN_START signal
    await drain(run_id)

    # 5. After drain: run must be ACTIVE
    after_drain = await _get_run(client, run_id)
    assert after_drain["status"] == "active", (
        f"After RUN_START consumed, run must be ACTIVE; got {after_drain['status']!r}"
    )
    assert after_drain["started_at"] is not None, "started_at must be set after RUN_START"


async def test_resume_signal_consumed_paused_to_active(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """RESUME signal is functional (not a no-op): PAUSED→ACTIVE via queue.

    Verifies [I-09] / [I-36]: RUN_START and RESUME signals are functional.
    """
    client, drain = client_and_drain

    # Start the run
    run_data = await _create_run(client, repo_name="r4-resume-to-active")
    run_id = run_data["id"]
    await client.post(f"/api/runs/{run_id}/start")
    await drain(run_id)
    assert (await _get_run(client, run_id))["status"] == "active"

    # Pause it (goes ACTIVE → STOPPING → enqueue PAUSE → drain → PAUSED)
    await client.post(f"/api/runs/{run_id}/pause")
    await drain(run_id)
    assert (await _get_run(client, run_id))["status"] == "paused"

    # Resume — enqueues RESUME signal, returns 202
    resume_resp = await client.post(f"/api/runs/{run_id}/resume")
    assert resume_resp.status_code == 202

    # Before drain: still PAUSED
    assert (await _get_run(client, run_id))["status"] == "paused"

    # Drain — consumer processes RESUME → ACTIVE
    await drain(run_id)
    assert (await _get_run(client, run_id))["status"] == "active", (
        "After RESUME consumed, run must be ACTIVE"
    )


# ---------------------------------------------------------------------------
# R5: STOPPING state path — pause active run → STOPPING → PAUSED
# ---------------------------------------------------------------------------


async def test_pause_active_run_enters_stopping_then_paused(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Pausing an ACTIVE run: run enters STOPPING immediately, then PAUSED after drain.

    This is the core R5 requirement: the STOPPING state is observable between
    when the pause request is received and when the consumer applies PAUSED.
    Verifies [I-03], [I-08], [I-30].
    """
    client, drain = client_and_drain

    # 1. Create and start run
    run_data = await _create_run(client, repo_name="r5-stopping-path")
    run_id = run_data["id"]
    await client.post(f"/api/runs/{run_id}/start")
    await drain(run_id)
    assert (await _get_run(client, run_id))["status"] == "active"

    # 2. POST /pause — run immediately enters STOPPING (observable before drain)
    pause_resp = await client.post(f"/api/runs/{run_id}/pause")
    assert pause_resp.status_code == 202

    # 3. STOPPING is immediately visible (no drain needed)
    run_stopping = await _get_run(client, run_id)
    assert run_stopping["status"] == "stopping", (
        f"Immediately after POST /pause, run must be STOPPING; got {run_stopping['status']!r}"
    )

    # 4. Cannot pause/resume/cancel a STOPPING run (API guards)
    assert (await client.post(f"/api/runs/{run_id}/pause")).status_code == 409
    assert (await client.post(f"/api/runs/{run_id}/resume")).status_code == 409
    assert (await client.post(f"/api/runs/{run_id}/cancel")).status_code == 409

    # 5. Drain — consumer processes PAUSE signal (STOPPING → PAUSED)
    await drain(run_id)

    # 6. Run must now be PAUSED
    run_paused = await _get_run(client, run_id)
    assert run_paused["status"] == "paused", (
        f"After PAUSE signal consumed, run must be PAUSED; got {run_paused['status']!r}"
    )
    assert run_paused["pause_reason"] == "manual_pause"


async def test_cancel_active_run_via_queue(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Cancel an active run via queue: enqueued CANCEL → ACTIVE/PAUSED → FAILED after drain."""
    client, drain = client_and_drain

    run_data = await _create_run(client, repo_name="r5-cancel-active")
    run_id = run_data["id"]
    await client.post(f"/api/runs/{run_id}/start")
    await drain(run_id)
    assert (await _get_run(client, run_id))["status"] == "active"

    # Cancel — 202 response
    cancel_resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert cancel_resp.status_code == 202

    # Drain processes CANCEL signal → FAILED
    await drain(run_id)
    run_after = await _get_run(client, run_id)
    assert run_after["status"] == "failed", (
        f"After CANCEL signal consumed, run must be FAILED; got {run_after['status']!r}"
    )
    assert run_after["completed_at"] is not None


# ---------------------------------------------------------------------------
# Concurrent runs: two runs process signals independently
# ---------------------------------------------------------------------------


async def test_concurrent_runs_process_signals_independently(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Two runs enqueue signals independently and transition correctly when drained.

    Verifies [I-12]: per-run FIFO, concurrent across runs.
    """
    client, drain = client_and_drain

    # Create two independent runs
    run_a = (await _create_run(client, repo_name="concurrent-run-a"))["id"]
    run_b = (await _create_run(client, repo_name="concurrent-run-b"))["id"]

    # Enqueue RUN_START for both (no drain yet)
    assert (await client.post(f"/api/runs/{run_a}/start")).status_code == 202
    assert (await client.post(f"/api/runs/{run_b}/start")).status_code == 202

    # Both are still DRAFT
    assert (await _get_run(client, run_a))["status"] == "draft"
    assert (await _get_run(client, run_b))["status"] == "draft"

    # Drain run A only
    await drain(run_a)
    assert (await _get_run(client, run_a))["status"] == "active", "Run A should be ACTIVE"
    assert (await _get_run(client, run_b))["status"] == "draft", "Run B not yet drained"

    # Drain run B
    await drain(run_b)
    assert (await _get_run(client, run_b))["status"] == "active", "Run B should now be ACTIVE"

    # Pause run A, cancel run B simultaneously
    assert (await client.post(f"/api/runs/{run_a}/pause")).status_code == 202
    assert (await client.post(f"/api/runs/{run_b}/cancel")).status_code == 202

    # Drain both
    await drain(run_a)
    await drain(run_b)

    assert (await _get_run(client, run_a))["status"] == "paused"
    assert (await _get_run(client, run_b))["status"] == "failed"
