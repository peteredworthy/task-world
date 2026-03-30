"""E2E test for full happy path workflow.

Tests the complete workflow from run creation through task completion
without any failures or revisions.
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
async def test_full_workflow_happy_path(api_client: AsyncClient, drain: DrainFn) -> None:
    """Test complete workflow: create → start → build → verify → complete.

    This test exercises the entire workflow without any failures or revisions,
    representing the ideal "happy path" where everything succeeds on the first try.
    """
    # 1. Create a run
    run_data = await create_run(api_client, routine_id="simple-routine", repo_name="test-proj-1")
    run_id = run_data["id"]
    assert run_data["status"] == "draft"
    assert run_data["current_step_index"] == 0

    # 2. Start the run (DRAFT → ACTIVE)
    run_data = await start_run(api_client, run_id, drain=drain)
    assert run_data["status"] == "active"

    # 3. Get the first task
    task_id = get_first_task_id(run_data)
    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "pending"

    # 4. Start the task (PENDING → BUILDING)
    await start_task(api_client, run_id, task_id)
    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "building"

    # 5. Mark checklist item as done
    req_id = "R1"
    await mark_checklist_done(api_client, run_id, task_id, req_id)
    task_data = await get_task(api_client, run_id, task_id)
    checklist_item = next(
        (item for item in task_data["checklist"] if item["req_id"] == req_id),
        None,
    )
    assert checklist_item is not None
    assert checklist_item["status"] == "done"

    # 6. Submit for verification (BUILDING → VERIFYING)
    result = await submit_task(api_client, run_id, task_id, drain=drain)
    assert result["success"] is True
    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "verifying"

    # 7. Set passing grade
    await grade_item(api_client, run_id, task_id, req_id, grade="A")
    task_data = await get_task(api_client, run_id, task_id)
    checklist_item = next(
        (item for item in task_data["checklist"] if item["req_id"] == req_id),
        None,
    )
    assert checklist_item is not None
    assert checklist_item["grade"] == "A"

    # 8. Complete verification (VERIFYING → COMPLETED)
    result = await complete_verification(api_client, run_id, task_id, drain=drain)
    assert result["success"] is True
    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "completed"

    # 9. Verify final run state
    run_data = await get_run(api_client, run_id)
    assert run_data["status"] == "completed"
    # Step should be marked as completed
    assert run_data["steps"][0]["completed"] is True


@pytest.mark.e2e
async def test_workflow_with_task_context(api_client: AsyncClient, drain: DrainFn) -> None:
    """Test that task context is properly available throughout workflow.

    Verifies that the task's context, requirements, and checklist are
    consistently available across all workflow transitions.
    """
    # Create and start run
    run_data = await create_run(api_client, routine_id="simple-routine", repo_name="test-proj-2")
    run_id = run_data["id"]
    run_data = await start_run(api_client, run_id, drain=drain)

    # Start task
    task_id = get_first_task_id(run_data)
    await start_task(api_client, run_id, task_id)

    # Verify task data is available
    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["id"] == task_id
    assert len(task_data["checklist"]) == 1
    assert task_data["checklist"][0]["req_id"] == "R1"

    # Complete the workflow
    await mark_checklist_done(api_client, run_id, task_id, "R1")
    await submit_task(api_client, run_id, task_id, drain=drain)
    await grade_item(api_client, run_id, task_id, "R1", grade="A")
    await complete_verification(api_client, run_id, task_id, drain=drain)

    # Verify task is completed
    task_data = await get_task(api_client, run_id, task_id)
    assert task_data["status"] == "completed"


@pytest.mark.e2e
async def test_workflow_tracks_attempts(api_client: AsyncClient, drain: DrainFn) -> None:
    """Test that attempts are properly tracked throughout workflow.

    Verifies that each phase (building, verifying) creates appropriate
    attempt records with outcomes.
    """
    # Create and start run
    run_data = await create_run(api_client, routine_id="simple-routine", repo_name="test-proj-3")
    run_id = run_data["id"]
    run_data = await start_run(api_client, run_id, drain=drain)

    # Start and complete task
    task_id = get_first_task_id(run_data)
    await start_task(api_client, run_id, task_id)

    # After starting, should have one attempt
    task_data = await get_task(api_client, run_id, task_id)
    assert len(task_data["attempts"]) == 1
    assert task_data["attempts"][0]["attempt_num"] == 1
    assert task_data["attempts"][0]["outcome"] is None  # Still in progress

    # Complete workflow
    await mark_checklist_done(api_client, run_id, task_id, "R1")
    await submit_task(api_client, run_id, task_id, drain=drain)
    await grade_item(api_client, run_id, task_id, "R1", grade="A")
    await complete_verification(api_client, run_id, task_id, drain=drain)

    # Should still have one attempt (no revision)
    task_data = await get_task(api_client, run_id, task_id)
    assert len(task_data["attempts"]) == 1
    assert task_data["attempts"][0]["outcome"] == "passed"


@pytest.mark.e2e
async def test_run_progression_updates_current_step(
    api_client: AsyncClient, drain: DrainFn
) -> None:
    """Test that run's current_step_index is updated as steps complete.

    Verifies that the run tracks which step is currently active and
    advances correctly.
    """
    # Create and start run
    run_data = await create_run(api_client, routine_id="simple-routine", repo_name="test-proj-4")
    run_id = run_data["id"]
    assert run_data["current_step_index"] == 0

    run_data = await start_run(api_client, run_id, drain=drain)
    assert run_data["current_step_index"] == 0

    # Complete the task
    task_id = get_first_task_id(run_data)
    await start_task(api_client, run_id, task_id)
    await mark_checklist_done(api_client, run_id, task_id, "R1")
    await submit_task(api_client, run_id, task_id, drain=drain)
    await grade_item(api_client, run_id, task_id, "R1", grade="A")
    await complete_verification(api_client, run_id, task_id, drain=drain)

    # Run should be completed (only one step)
    run_data = await get_run(api_client, run_id)
    assert run_data["status"] == "completed"
    assert run_data["steps"][0]["completed"] is True
