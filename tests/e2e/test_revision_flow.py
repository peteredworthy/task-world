"""E2E test for revision flow.

Tests the workflow when tasks fail verification and require revision,
including failed checklist gates and failed grade thresholds.
"""

import pytest
from httpx import AsyncClient

from tests.e2e.conftest import (
    complete_verification,
    create_run,
    get_first_task_id,
    get_run,
    get_task,
    grade_item,
    mark_checklist_done,
    start_run,
    start_task,
    submit_task,
)
from tests.integration.signal_helpers import DrainFn


@pytest.mark.e2e
async def test_revision_flow_gate_blocked(api_client: AsyncClient, drain: DrainFn) -> None:
    """Test task revision when checklist gate blocks submission.

    When a task is submitted with incomplete checklist items, the gate
    blocks and pauses the run with pause_reason="gate_blocked".
    """
    # Create and start run
    run_data = await create_run(api_client, routine_id="simple-routine", repo_name="rev-proj-1")
    run_id = run_data["id"]
    run_data = await start_run(api_client, run_id, drain=drain)

    # Start task
    task_id = get_first_task_id(run_data)
    await start_task(api_client, run_id, task_id)

    # Submit WITHOUT completing checklist — gate check runs synchronously → 409
    response = await api_client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert response.status_code == 409

    # Run should still be ACTIVE (gate is checked synchronously; no state change)
    run_data = await get_run(api_client, run_id)
    assert run_data["status"] == "active"

    # Task should still be in BUILDING state
    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "building"

    # Complete the checklist and try again
    await mark_checklist_done(api_client, run_id, task_id, "R1")
    result = await submit_task(api_client, run_id, task_id, drain=drain)
    assert result["success"] is True

    # Task should now be in VERIFYING state
    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "verifying"


@pytest.mark.e2e
async def test_revision_flow_failed_grades(api_client: AsyncClient, drain: DrainFn) -> None:
    """Test task revision when grades fail threshold.

    When verification grades fail to meet the threshold, the task should
    transition back to BUILDING with a new attempt.
    """
    # Create and start run
    run_data = await create_run(api_client, routine_id="simple-routine", repo_name="rev-proj-2")
    run_id = run_data["id"]
    run_data = await start_run(api_client, run_id, drain=drain)

    # Start task and complete building phase
    task_id = get_first_task_id(run_data)
    await start_task(api_client, run_id, task_id)
    await mark_checklist_done(api_client, run_id, task_id, "R1")
    await submit_task(api_client, run_id, task_id, drain=drain)

    # First verification attempt - fail the grade
    await grade_item(api_client, run_id, task_id, "R1", grade="F", reason="Not good enough")
    result = await complete_verification(api_client, run_id, task_id, drain=drain)
    assert result["success"] is True

    # Task should be back in BUILDING (revision)
    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "building"

    # Should have 2 attempts now (original + revision)
    assert len(task_data["attempts"]) == 2
    assert task_data["attempts"][0]["outcome"] == "revision_needed"
    assert task_data["attempts"][1]["outcome"] is None  # In progress

    # Verify grade reason is stored
    checklist_item = task_data["checklist"][0]
    assert checklist_item["grade"] == "F"
    assert checklist_item["grade_reason"] == "Not good enough"

    # Second attempt - pass this time
    await submit_task(api_client, run_id, task_id, drain=drain)
    await grade_item(api_client, run_id, task_id, "R1", grade="A")
    await complete_verification(api_client, run_id, task_id, drain=drain)

    # Task should now be completed
    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "completed"
    assert len(task_data["attempts"]) == 2
    assert task_data["attempts"][1]["outcome"] == "passed"


@pytest.mark.e2e
async def test_revision_flow_multiple_rounds(api_client: AsyncClient, drain: DrainFn) -> None:
    """Test task can go through multiple revision rounds.

    Verifies that a task can fail verification multiple times and continue
    to create new attempts until it eventually passes.
    """
    # Create and start run
    run_data = await create_run(api_client, routine_id="simple-routine", repo_name="rev-proj-3")
    run_id = run_data["id"]
    run_data = await start_run(api_client, run_id, drain=drain)

    # Start task
    task_id = get_first_task_id(run_data)
    await start_task(api_client, run_id, task_id)

    # Round 1: Fail
    await mark_checklist_done(api_client, run_id, task_id, "R1")
    await submit_task(api_client, run_id, task_id, drain=drain)
    await grade_item(api_client, run_id, task_id, "R1", grade="F", reason="Round 1 fail")
    await complete_verification(api_client, run_id, task_id, drain=drain)

    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "building"
    assert len(task_data["attempts"]) == 2

    # Round 2: Fail again
    await submit_task(api_client, run_id, task_id, drain=drain)
    await grade_item(api_client, run_id, task_id, "R1", grade="F", reason="Round 2 fail")
    await complete_verification(api_client, run_id, task_id, drain=drain)

    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "building"
    assert len(task_data["attempts"]) == 3

    # Round 3: Pass
    await submit_task(api_client, run_id, task_id, drain=drain)
    await grade_item(api_client, run_id, task_id, "R1", grade="A")
    await complete_verification(api_client, run_id, task_id, drain=drain)

    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "completed"
    assert len(task_data["attempts"]) == 3
    assert task_data["attempts"][0]["outcome"] == "revision_needed"
    assert task_data["attempts"][1]["outcome"] == "revision_needed"
    assert task_data["attempts"][2]["outcome"] == "passed"


@pytest.mark.e2e
async def test_revision_preserves_checklist_state(api_client: AsyncClient, drain: DrainFn) -> None:
    """Test that checklist state is preserved on revision.

    When a task enters revision, the checklist items preserve their status
    and grades from the failed verification. The agent must re-mark items
    as done to re-submit.
    """
    # Create and start run
    run_data = await create_run(api_client, routine_id="simple-routine", repo_name="rev-proj-4")
    run_id = run_data["id"]
    run_data = await start_run(api_client, run_id, drain=drain)

    # Start task and complete first attempt
    task_id = get_first_task_id(run_data)
    await start_task(api_client, run_id, task_id)
    await mark_checklist_done(api_client, run_id, task_id, "R1")
    await submit_task(api_client, run_id, task_id, drain=drain)

    # Fail verification
    await grade_item(api_client, run_id, task_id, "R1", grade="F")
    await complete_verification(api_client, run_id, task_id, drain=drain)

    # Check that grade is preserved after revision
    task_data = await get_task(api_client, run_id, task_id)
    checklist_item = task_data["checklist"][0]
    assert checklist_item["grade"] == "F"  # Grade preserved from previous attempt

    # Re-mark checklist done for second attempt
    await mark_checklist_done(api_client, run_id, task_id, "R1")
    await submit_task(api_client, run_id, task_id, drain=drain)
    await grade_item(api_client, run_id, task_id, "R1", grade="A")
    await complete_verification(api_client, run_id, task_id, drain=drain)

    # Verify final state
    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "completed"
    checklist_item = task_data["checklist"][0]
    assert checklist_item["status"] == "done"
    assert checklist_item["grade"] == "A"


@pytest.mark.e2e
async def test_revision_preserves_task_context(api_client: AsyncClient, drain: DrainFn) -> None:
    """Test that task context is preserved across revisions.

    The task's context, requirements, and other metadata should remain
    consistent across revision cycles.
    """
    # Create and start run
    run_data = await create_run(api_client, routine_id="simple-routine", repo_name="rev-proj-5")
    run_id = run_data["id"]
    run_data = await start_run(api_client, run_id, drain=drain)

    # Start task
    task_id = get_first_task_id(run_data)
    await start_task(api_client, run_id, task_id)

    # Capture initial checklist count
    task_data = await get_task(api_client, run_id, task_id)
    initial_checklist_count = len(task_data["checklist"])

    # Complete first attempt and fail
    await mark_checklist_done(api_client, run_id, task_id, "R1")
    await submit_task(api_client, run_id, task_id, drain=drain)
    await grade_item(api_client, run_id, task_id, "R1", grade="F")
    await complete_verification(api_client, run_id, task_id, drain=drain)

    # Verify checklist is preserved after revision
    task_data = await get_task(api_client, run_id, task_id)
    assert len(task_data["checklist"]) == initial_checklist_count
    assert task_data["checklist"][0]["req_id"] == "R1"
