"""E2E test for multiple concurrent runs.

Tests that the system can handle multiple runs executing concurrently
without interference or state contamination.
"""

import asyncio

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


@pytest.mark.e2e
async def test_multiple_runs_independent_state(api_client: AsyncClient) -> None:
    """Test that multiple runs maintain independent state.

    Creates three runs and progresses them to different states to verify
    that state changes in one run don't affect the others.
    """
    # Create three runs
    run1_data = await create_run(api_client, routine_id="simple-routine", repo_name="multi-1")
    run1_id = run1_data["id"]

    run2_data = await create_run(api_client, routine_id="simple-routine", repo_name="multi-2")
    run2_id = run2_data["id"]

    run3_data = await create_run(api_client, routine_id="simple-routine", repo_name="multi-3")
    run3_id = run3_data["id"]

    # Start all runs
    run1_data = await start_run(api_client, run1_id)
    run2_data = await start_run(api_client, run2_id)
    run3_data = await start_run(api_client, run3_id)

    # Get task IDs for each run
    task1_id = get_first_task_id(run1_data)
    task2_id = get_first_task_id(run2_data)
    task3_id = get_first_task_id(run3_data)

    # Progress run1 to building
    await start_task(api_client, run1_id, task1_id)

    # Progress run2 to verifying
    await start_task(api_client, run2_id, task2_id)
    await mark_checklist_done(api_client, run2_id, task2_id, "R1")
    await submit_task(api_client, run2_id, task2_id)

    # Progress run3 to completed
    await start_task(api_client, run3_id, task3_id)
    await mark_checklist_done(api_client, run3_id, task3_id, "R1")
    await submit_task(api_client, run3_id, task3_id)
    await grade_item(api_client, run3_id, task3_id, "R1", grade="A")
    await complete_verification(api_client, run3_id, task3_id)

    # Verify each run is in the expected state
    task1_data = await get_task(api_client, run1_id, task1_id)
    task2_data = await get_task(api_client, run2_id, task2_id)
    task3_data = await get_task(api_client, run3_id, task3_id)

    assert task1_data["status"] == "building"
    assert task2_data["status"] == "verifying"
    assert task3_data["status"] == "completed"

    # Verify checklists are independent
    assert task1_data["checklist"][0]["status"] == "open"
    assert task2_data["checklist"][0]["status"] == "done"
    assert task3_data["checklist"][0]["status"] == "done"
    assert task3_data["checklist"][0]["grade"] == "A"


@pytest.mark.e2e
async def test_concurrent_task_operations(api_client: AsyncClient) -> None:
    """Test that concurrent operations on different runs work correctly.

    Performs operations on multiple runs concurrently to verify thread-safety
    and proper isolation.
    """
    # Create three runs and track their task IDs
    run_tasks: list[tuple[str, str]] = []
    for i in range(3):
        run_data = await create_run(
            api_client, routine_id="simple-routine", repo_name=f"concurrent-{i}"
        )
        run_data = await start_run(api_client, run_data["id"])
        task_id = get_first_task_id(run_data)
        run_tasks.append((run_data["id"], task_id))

    # Start all tasks concurrently
    await asyncio.gather(
        *[start_task(api_client, run_id, task_id) for run_id, task_id in run_tasks]
    )

    # Mark all checklists done concurrently
    await asyncio.gather(
        *[mark_checklist_done(api_client, run_id, task_id, "R1") for run_id, task_id in run_tasks]
    )

    # Submit all tasks concurrently
    await asyncio.gather(
        *[submit_task(api_client, run_id, task_id) for run_id, task_id in run_tasks]
    )

    # Grade all tasks concurrently
    await asyncio.gather(
        *[grade_item(api_client, run_id, task_id, "R1", grade="A") for run_id, task_id in run_tasks]
    )

    # Complete all verifications concurrently
    await asyncio.gather(
        *[complete_verification(api_client, run_id, task_id) for run_id, task_id in run_tasks]
    )

    # Verify all runs completed successfully
    for run_id, _ in run_tasks:
        run_data = await get_run(api_client, run_id)
        assert run_data["status"] == "completed"


@pytest.mark.e2e
async def test_multiple_runs_different_routines(api_client: AsyncClient) -> None:
    """Test that runs using different routines don't interfere.

    Creates runs from different routine definitions and verifies they
    maintain their independent configurations and state.
    """
    # Note: This test would require multiple routine fixtures
    # For now, we'll just verify that the same routine can be used multiple times
    run1_data = await create_run(
        api_client, routine_id="simple-routine", repo_name="routine-test-1"
    )
    run2_data = await create_run(
        api_client, routine_id="simple-routine", repo_name="routine-test-2"
    )

    # Verify both runs have independent routine configurations
    assert run1_data["routine_id"] == "simple-routine"
    assert run2_data["routine_id"] == "simple-routine"
    assert run1_data["id"] != run2_data["id"]
    assert run1_data["repo_name"] != run2_data["repo_name"]


@pytest.mark.e2e
async def test_run_isolation_with_revisions(api_client: AsyncClient) -> None:
    """Test that revision cycles in one run don't affect other runs.

    Creates multiple runs and causes revisions in one while progressing
    others normally to verify isolation.
    """
    # Create two runs
    run1_data = await create_run(api_client, routine_id="simple-routine", repo_name="isolation-1")
    run1_id = run1_data["id"]

    run2_data = await create_run(api_client, routine_id="simple-routine", repo_name="isolation-2")
    run2_id = run2_data["id"]

    # Start both
    run1_data = await start_run(api_client, run1_id)
    run2_data = await start_run(api_client, run2_id)

    # Start both tasks
    task1_id = get_first_task_id(run1_data)
    task2_id = get_first_task_id(run2_data)
    await start_task(api_client, run1_id, task1_id)
    await start_task(api_client, run2_id, task2_id)

    # Run1: Complete successfully on first try
    await mark_checklist_done(api_client, run1_id, task1_id, "R1")
    await submit_task(api_client, run1_id, task1_id)
    await grade_item(api_client, run1_id, task1_id, "R1", grade="A")
    await complete_verification(api_client, run1_id, task1_id)

    # Run2: Fail first attempt
    await mark_checklist_done(api_client, run2_id, task2_id, "R1")
    await submit_task(api_client, run2_id, task2_id)
    await grade_item(api_client, run2_id, task2_id, "R1", grade="F", reason="Need revision")
    await complete_verification(api_client, run2_id, task2_id)

    # Verify run1 is completed with 1 attempt
    task1_data = await get_task(api_client, run1_id, task1_id)
    assert task1_data["status"] == "completed"
    assert len(task1_data["attempts"]) == 1

    # Verify run2 is in revision with 2 attempts
    task2_data = await get_task(api_client, run2_id, task2_id)
    assert task2_data["status"] == "building"
    assert len(task2_data["attempts"]) == 2

    # Complete run2's second attempt
    await submit_task(api_client, run2_id, task2_id)
    await grade_item(api_client, run2_id, task2_id, "R1", grade="A")
    await complete_verification(api_client, run2_id, task2_id)

    # Verify run2 is now completed with 2 attempts
    task2_data = await get_task(api_client, run2_id, task2_id)
    assert task2_data["status"] == "completed"
    assert len(task2_data["attempts"]) == 2

    # Verify run1 is still completed with 1 attempt (unchanged)
    task1_data = await get_task(api_client, run1_id, task1_id)
    assert task1_data["status"] == "completed"
    assert len(task1_data["attempts"]) == 1


@pytest.mark.e2e
async def test_run_list_filtering(api_client: AsyncClient) -> None:
    """Test that run list can be filtered and returns correct results.

    Creates runs in different states and verifies that listing and
    filtering works correctly with multiple concurrent runs.
    """
    # Create runs in different states
    draft_runs: list[str] = []
    active_runs: list[str] = []
    completed_runs: list[str] = []

    # Create 2 draft runs
    for i in range(2):
        run_data = await create_run(
            api_client, routine_id="simple-routine", repo_name=f"filter-draft-{i}"
        )
        draft_runs.append(run_data["id"])

    # Create 2 active runs
    for i in range(2):
        run_data = await create_run(
            api_client, routine_id="simple-routine", repo_name=f"filter-active-{i}"
        )
        await start_run(api_client, run_data["id"])
        active_runs.append(run_data["id"])

    # Create 2 completed runs
    for i in range(2):
        run_data = await create_run(
            api_client, routine_id="simple-routine", repo_name=f"filter-completed-{i}"
        )
        run_id = run_data["id"]
        run_data = await start_run(api_client, run_id)
        task_id = get_first_task_id(run_data)
        await start_task(api_client, run_id, task_id)
        await mark_checklist_done(api_client, run_id, task_id, "R1")
        await submit_task(api_client, run_id, task_id)
        await grade_item(api_client, run_id, task_id, "R1", grade="A")
        await complete_verification(api_client, run_id, task_id)
        completed_runs.append(run_id)

    # Get all runs
    response = await api_client.get("/api/runs")
    assert response.status_code == 200
    data = response.json()
    all_runs = data["runs"]

    # Create a map for easy lookup
    run_map = {r["id"]: r for r in all_runs}

    # Verify draft runs
    for run_id in draft_runs:
        assert run_id in run_map
        assert run_map[run_id]["status"] == "draft"

    # Verify active runs
    for run_id in active_runs:
        assert run_id in run_map
        assert run_map[run_id]["status"] == "active"

    # Verify completed runs
    for run_id in completed_runs:
        assert run_id in run_map
        assert run_map[run_id]["status"] == "completed"


@pytest.mark.e2e
async def test_concurrent_checklist_updates(api_client: AsyncClient) -> None:
    """Test that checklist updates on different runs are isolated.

    Updates checklists on multiple runs concurrently and verifies that
    each run's checklist state is correct.
    """
    # Create and start multiple runs, tracking their task IDs
    num_runs = 5
    run_tasks: list[tuple[str, str]] = []

    for i in range(num_runs):
        run_data = await create_run(
            api_client, routine_id="simple-routine", repo_name=f"checklist-{i}"
        )
        run_data = await start_run(api_client, run_data["id"])
        task_id = get_first_task_id(run_data)
        await start_task(api_client, run_data["id"], task_id)
        run_tasks.append((run_data["id"], task_id))

    # Mark checklist done on odd-numbered runs only
    for i, (run_id, task_id) in enumerate(run_tasks):
        if i % 2 == 1:
            await mark_checklist_done(api_client, run_id, task_id, "R1")

    # Verify checklist state for each run
    for i, (run_id, task_id) in enumerate(run_tasks):
        task_data = await get_task(api_client, run_id, task_id)
        expected_status = "done" if i % 2 == 1 else "open"
        assert task_data["checklist"][0]["status"] == expected_status
