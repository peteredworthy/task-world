"""Seed the database with multiple runs in various states for UI testing.

Usage:
    uv run python scripts/seed_db.py

Correct workflow order:
1. create_run → DRAFT
2. start_run → ACTIVE
3. start_task → BUILDING (creates attempt)
4. update_checklist_item → mark items DONE (builder phase)
5. submit_for_verification → VERIFYING (gate check: critical items must be DONE)
6. set_grade → assign grades (verifier phase)
7. complete_verification → COMPLETED (if grades pass) or BUILDING (revision)
"""

import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from orchestrator.config.enums import ChecklistStatus, RoutineSource
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import EventStore
from orchestrator.db import RunRepository
from orchestrator.routines.discovery import discover_routines
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import AttemptMetrics
from orchestrator.workflow.event_logger import PersistentEventEmitter
from orchestrator.workflow.service import WorkflowService


DB_PATH = "orchestrator.db"
ROUTINE_DIRS = [
    (Path(__file__).parent.parent / "routines", RoutineSource.LOCAL),
    (Path(__file__).parent.parent / "tests" / "fixtures" / "routines", RoutineSource.LOCAL),
]


def _random_metrics() -> AttemptMetrics:
    """Generate realistic-looking attempt metrics."""
    tokens_read = random.randint(8000, 45000)
    tokens_write = random.randint(2000, 15000)
    tokens_cache = random.randint(1000, tokens_read // 2)
    duration_ms = random.randint(15000, 180000)
    return AttemptMetrics(
        tokens_read=tokens_read,
        tokens_write=tokens_write,
        tokens_cache=tokens_cache,
        duration_ms=duration_ms,
    )


async def _apply_metrics(
    service: WorkflowService, repo: RunRepository, run_id: str, task_id: str
) -> None:
    """Apply random metrics to the most recently completed attempt and update run totals."""
    run = await service.get_run(run_id)
    task = None
    for step in run.steps:
        for t in step.tasks:
            if t.id == task_id:
                task = t
                break
    if not task or not task.attempts:
        return
    # Find the most recently completed attempt (has outcome set)
    completed_attempts = [a for a in task.attempts if a.outcome is not None]
    if not completed_attempts:
        # Fallback: apply to last attempt (e.g. still building)
        completed_attempts = [task.attempts[-1]]
    attempt = completed_attempts[-1]
    m = _random_metrics()
    attempt.metrics = m
    run.total_tokens_read += m.tokens_read
    run.total_tokens_write += m.tokens_write
    run.total_tokens_cache += m.tokens_cache
    run.total_duration_ms += m.duration_ms
    await repo.save(run)


async def complete_task(
    service: WorkflowService,
    repo: RunRepository,
    run_id: str,
    task_id: str,
    grades: dict[str, tuple[str, str]],
    statuses: dict[str, tuple[ChecklistStatus, str | None]] | None = None,
) -> None:
    """Helper: walk a task through the full lifecycle.

    Args:
        grades: {req_id: (grade, reason)}
        statuses: {req_id: (status, note)} — defaults to DONE for all
    """
    # 1. Start task → BUILDING
    result = await service.start_task(run_id, task_id)
    if not result.success:
        print(f"    WARNING: start_task failed: {result.error}")
        return

    # 2. Mark checklist items (builder phase)
    for req_id, (grade, reason) in grades.items():
        st = ChecklistStatus.DONE
        note: str | None = None
        if statuses and req_id in statuses:
            st, note = statuses[req_id]
        await service.update_checklist_item(run_id, task_id, req_id, st, note)

    # 3. Submit for verification (gate check)
    result = await service.submit_for_verification(run_id, task_id)
    if not result.success:
        print(f"    WARNING: submit failed: {result.error}")
        return

    # 4. Set grades (verifier phase)
    for req_id, (grade, reason) in grades.items():
        await service.set_grade(run_id, task_id, req_id, grade, reason)

    # 5. Complete verification (grade evaluation)
    result = await service.complete_verification(run_id, task_id)

    # 6. Apply realistic metrics to the attempt
    await _apply_metrics(service, repo, run_id, task_id)

    print(f"    Task {task_id[:8]}... → {result.new_status.value}")


async def main() -> None:
    routines = discover_routines(ROUTINE_DIRS)
    print(f"Discovered {len(routines)} routines:")
    for r in routines:
        print(f"  - {r.config.id}: {r.config.name} ({len(r.config.steps)} steps)")

    fullstack = None
    complete = None
    simple = None
    for r in routines:
        if r.config.id == "fullstack-feature":
            fullstack = r.config
        elif r.config.id == "complete-routine":
            complete = r.config
        elif r.config.id == "simple-routine":
            simple = r.config

    if not fullstack:
        print("ERROR: fullstack-feature routine not found!")
        return

    engine = create_engine(DB_PATH)
    session_factory = create_session_factory(engine)
    await init_db(engine)

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
        )

        # Delete existing runs to start fresh
        existing = await service.list_runs()
        print(f"\nDeleting {len(existing)} existing runs...")
        for r in existing:
            await service.delete_run(r.id)

        # =============================================
        # RUN 1: Fully completed run (all tasks passed)
        # =============================================
        print("\n--- Run 1: Completed full-stack feature ---")
        run1 = create_run_from_routine(
            routine=fullstack,
            project_id="/projects/acme-app",
            config={
                "feature_name": "User Authentication",
                "target_branch": "main",
                "language": "python",
            },
            routine_source=RoutineSource.LOCAL,
        )
        created1 = await service.create_run(run1)
        run1 = await service.start_run(created1.id)

        # Step 1: Design Doc (T-01)
        t01 = run1.steps[0].tasks[0]
        await complete_task(
            service,
            repo,
            run1.id,
            t01.id,
            {
                "R-01": ("A", "Comprehensive architecture overview"),
                "R-02": ("A", "Clear endpoint specifications"),
                "R-03": ("B", "Good coverage, minor edge cases missing"),
                "R-04": ("A", "OWASP top 10 addressed"),
                "R-05": ("B", "Basic performance notes included"),
            },
        )

        # Step 2: Data Models (T-02), API Endpoints (T-03), Tests (T-04)
        run1 = await service.get_run(run1.id)
        t02 = run1.steps[1].tasks[0]
        await complete_task(
            service,
            repo,
            run1.id,
            t02.id,
            {
                "R-06": ("A", "Models properly typed with constraints"),
                "R-07": ("B", "Migration works but could be cleaner"),
                "R-08": ("A", "Full Pydantic validation schemas"),
            },
        )

        run1 = await service.get_run(run1.id)
        t03 = run1.steps[1].tasks[1]
        await complete_task(
            service,
            repo,
            run1.id,
            t03.id,
            {
                "R-09": ("A", "All CRUD endpoints working correctly"),
                "R-10": ("A", "Comprehensive input validation"),
                "R-11": ("B", "Mostly correct status codes"),
                "R-12": ("C", "Basic OpenAPI docs, missing descriptions"),
            },
        )

        run1 = await service.get_run(run1.id)
        t04 = run1.steps[1].tasks[2]
        await complete_task(
            service,
            repo,
            run1.id,
            t04.id,
            {
                "R-13": ("A", "Full unit test coverage of logic"),
                "R-14": ("A", "Integration tests comprehensive"),
                "R-15": ("B", "Most edge cases covered"),
                "R-16": ("A", "Coverage at 92%"),
            },
        )

        # Step 3: UI Components (T-05), E2E Testing (T-06)
        run1 = await service.get_run(run1.id)
        t05 = run1.steps[2].tasks[0]
        await complete_task(
            service,
            repo,
            run1.id,
            t05.id,
            {
                "R-17": ("A", "Clean component architecture"),
                "R-18": ("B", "Good validation, minor UX gaps"),
                "R-19": ("A", "Loading skeletons and empty states"),
                "R-20": ("B", "Responsive on most breakpoints"),
                "R-21": ("C", "ARIA labels present, keyboard nav incomplete"),
            },
        )

        run1 = await service.get_run(run1.id)
        t06 = run1.steps[2].tasks[1]
        await complete_task(
            service,
            repo,
            run1.id,
            t06.id,
            {
                "R-22": ("A", "Happy path fully tested"),
                "R-23": ("A", "Error scenarios handled well"),
                "R-24": ("B", "Performance acceptable, room for optimization"),
            },
        )
        print("  Run 1 complete!")

        # =============================================
        # RUN 2: Active run, in-progress (step 1 done, step 2 building)
        # =============================================
        print("\n--- Run 2: Active, in-progress ---")
        run2 = create_run_from_routine(
            routine=fullstack,
            project_id="/projects/dashboard-v2",
            config={
                "feature_name": "Real-time Notifications",
                "target_branch": "feat/notifications",
                "language": "python",
            },
            routine_source=RoutineSource.LOCAL,
        )
        created2 = await service.create_run(run2)
        run2 = await service.start_run(created2.id)

        # Complete step 1
        t01 = run2.steps[0].tasks[0]
        await complete_task(
            service,
            repo,
            run2.id,
            t01.id,
            {
                "R-01": ("A", "Good architecture overview"),
                "R-02": ("A", "Detailed API contracts"),
                "R-03": ("B", "Data model docs present"),
                "R-04": ("B", "Security section adequate"),
                "R-05": ("B", "Performance notes included"),
            },
        )

        # Start T-02 (Data Models) - left in BUILDING state
        run2 = await service.get_run(run2.id)
        t02 = run2.steps[1].tasks[0]
        result = await service.start_task(run2.id, t02.id)
        await _apply_metrics(service, repo, run2.id, t02.id)
        print(f"  T-02 is now {result.new_status.value} (run is active/in-progress)")

        # =============================================
        # RUN 3: Paused run (step 1 done, then paused)
        # =============================================
        print("\n--- Run 3: Paused ---")
        run3 = create_run_from_routine(
            routine=fullstack,
            project_id="/projects/api-gateway",
            config={
                "feature_name": "Rate Limiting",
                "target_branch": "feat/rate-limit",
                "language": "python",
            },
            routine_source=RoutineSource.LOCAL,
        )
        created3 = await service.create_run(run3)
        run3 = await service.start_run(created3.id)

        t01 = run3.steps[0].tasks[0]
        await complete_task(
            service,
            repo,
            run3.id,
            t01.id,
            {
                "R-01": ("A", "Excellent rate limiting design"),
                "R-02": ("A", "Clear API docs with rate limit headers"),
                "R-03": ("A", "Complete data model for quotas"),
                "R-04": ("B", "Good security notes for abuse prevention"),
                "R-05": ("A", "Performance benchmarks planned"),
            },
        )
        await service.pause_run(run3.id)
        print("  Run 3 is now PAUSED")

        # =============================================
        # RUN 4: Failed task with multiple attempts
        # =============================================
        print("\n--- Run 4: Failed task with retries ---")
        run4 = create_run_from_routine(
            routine=fullstack,
            project_id="/projects/analytics-service",
            config={
                "feature_name": "Event Tracking Pipeline",
                "target_branch": "feat/tracking",
                "language": "python",
            },
            routine_source=RoutineSource.LOCAL,
        )
        created4 = await service.create_run(run4)
        run4 = await service.start_run(created4.id)

        t01 = run4.steps[0].tasks[0]

        # Attempt 1: Bad grades on critical items → revision_needed
        result = await service.start_task(run4.id, t01.id)
        await service.update_checklist_item(
            run4.id, t01.id, "R-01", ChecklistStatus.DONE, "Vague design"
        )
        await service.update_checklist_item(
            run4.id, t01.id, "R-02", ChecklistStatus.DONE, "Incomplete"
        )
        await service.update_checklist_item(
            run4.id, t01.id, "R-03", ChecklistStatus.DONE, "Minimal"
        )
        await service.update_checklist_item(run4.id, t01.id, "R-04", ChecklistStatus.DONE, "Brief")
        await service.update_checklist_item(run4.id, t01.id, "R-05", ChecklistStatus.DONE, "N/A")
        result = await service.submit_for_verification(run4.id, t01.id)
        await service.set_grade(run4.id, t01.id, "R-01", "D", "Architecture overview too vague")
        await service.set_grade(
            run4.id, t01.id, "R-02", "F", "No API endpoints documented properly"
        )
        await service.set_grade(run4.id, t01.id, "R-03", "C", "Minimal data model")
        await service.set_grade(run4.id, t01.id, "R-04", "D", "Security not addressed")
        await service.set_grade(run4.id, t01.id, "R-05", "C", "No performance notes")
        result = await service.complete_verification(run4.id, t01.id)
        await _apply_metrics(service, repo, run4.id, t01.id)
        print(f"    Attempt 1: {result.new_status.value}")

        # Attempt 2: Better but still failing critical grade threshold
        run4 = await service.get_run(run4.id)
        t01 = run4.steps[0].tasks[0]
        # Note: after revision_needed, task goes back to BUILDING with new attempt
        # But we need to re-mark items and re-submit
        await service.update_checklist_item(
            run4.id, t01.id, "R-01", ChecklistStatus.DONE, "Improved design"
        )
        await service.update_checklist_item(
            run4.id, t01.id, "R-02", ChecklistStatus.DONE, "Added API docs"
        )
        await service.update_checklist_item(
            run4.id, t01.id, "R-03", ChecklistStatus.DONE, "Models added"
        )
        await service.update_checklist_item(
            run4.id, t01.id, "R-04", ChecklistStatus.DONE, "Security added"
        )
        await service.update_checklist_item(
            run4.id, t01.id, "R-05", ChecklistStatus.DONE, "Perf noted"
        )
        result = await service.submit_for_verification(run4.id, t01.id)
        await service.set_grade(run4.id, t01.id, "R-01", "C", "Improved but still lacking detail")
        await service.set_grade(run4.id, t01.id, "R-02", "C", "Partial API docs")
        await service.set_grade(run4.id, t01.id, "R-03", "B", "Better data model")
        await service.set_grade(run4.id, t01.id, "R-04", "C", "Basic security covered")
        await service.set_grade(run4.id, t01.id, "R-05", "B", "Performance noted")
        result = await service.complete_verification(run4.id, t01.id)
        await _apply_metrics(service, repo, run4.id, t01.id)
        print(f"    Attempt 2: {result.new_status.value}")

        # Attempt 3: Max attempts reached → FAILED
        run4 = await service.get_run(run4.id)
        t01 = run4.steps[0].tasks[0]
        await service.update_checklist_item(
            run4.id, t01.id, "R-01", ChecklistStatus.DONE, "Third try"
        )
        await service.update_checklist_item(
            run4.id, t01.id, "R-02", ChecklistStatus.DONE, "Third try"
        )
        await service.update_checklist_item(
            run4.id, t01.id, "R-03", ChecklistStatus.DONE, "Third try"
        )
        await service.update_checklist_item(
            run4.id, t01.id, "R-04", ChecklistStatus.DONE, "Third try"
        )
        await service.update_checklist_item(
            run4.id, t01.id, "R-05", ChecklistStatus.DONE, "Third try"
        )
        result = await service.submit_for_verification(run4.id, t01.id)
        await service.set_grade(run4.id, t01.id, "R-01", "B", "Better architecture section")
        await service.set_grade(
            run4.id, t01.id, "R-02", "C", "API docs present but still incomplete"
        )
        await service.set_grade(run4.id, t01.id, "R-03", "B", "Data models well specified now")
        await service.set_grade(run4.id, t01.id, "R-04", "B", "Security adequately covered")
        await service.set_grade(run4.id, t01.id, "R-05", "A", "Performance benchmarked")
        result = await service.complete_verification(run4.id, t01.id)
        await _apply_metrics(service, repo, run4.id, t01.id)
        print(f"    Attempt 3: {result.new_status.value} (should be failed - max attempts)")

        # =============================================
        # RUN 5: Draft (not started)
        # =============================================
        print("\n--- Run 5: Draft ---")
        run5 = create_run_from_routine(
            routine=fullstack,
            project_id="/projects/mobile-app",
            config={
                "feature_name": "Offline Sync",
                "target_branch": "feat/offline",
                "language": "python",
            },
            routine_source=RoutineSource.LOCAL,
        )
        created5 = await service.create_run(run5)
        print(f"  Run 5 is DRAFT: {created5.id[:8]}...")

        # =============================================
        # RUN 6: Simple routine, completed
        # =============================================
        if simple:
            print("\n--- Run 6: Simple routine (completed) ---")
            run6 = create_run_from_routine(
                routine=simple,
                project_id="/projects/docs-update",
                config={},
                routine_source=RoutineSource.LOCAL,
            )
            created6 = await service.create_run(run6)
            run6 = await service.start_run(created6.id)
            t = run6.steps[0].tasks[0]

            result = await service.start_task(run6.id, t.id)
            await service.update_checklist_item(run6.id, t.id, "R1", ChecklistStatus.DONE, "Done")
            result = await service.submit_for_verification(run6.id, t.id)
            await service.set_grade(run6.id, t.id, "R1", "A", "Task completed perfectly")
            result = await service.complete_verification(run6.id, t.id)
            print(f"    Task → {result.new_status.value}")

        # =============================================
        # RUN 7: Complete routine, in verifying state
        # =============================================
        if complete:
            print("\n--- Run 7: Complete routine (verifying) ---")
            run7 = create_run_from_routine(
                routine=complete,
                project_id="/projects/feature-flags",
                config={"feature_name": "dark-mode", "branch": "feat/dark-mode"},
                routine_source=RoutineSource.LOCAL,
            )
            created7 = await service.create_run(run7)
            run7 = await service.start_run(created7.id)
            t = run7.steps[0].tasks[0]
            result = await service.start_task(run7.id, t.id)
            # Mark items done (builder)
            await service.update_checklist_item(
                run7.id, t.id, "R1", ChecklistStatus.DONE, "Plan created"
            )
            await service.update_checklist_item(
                run7.id, t.id, "R2", ChecklistStatus.DONE, "Timeline added"
            )
            result = await service.submit_for_verification(run7.id, t.id)
            print(f"    Task submitted → {result.new_status.value}")
            # Set partial grades (still in verifying)
            await service.set_grade(run7.id, t.id, "R1", "A", "Plan file created")
            await service.set_grade(run7.id, t.id, "R2", "B", "Timeline present but vague")
            print("  Run 7 is ACTIVE with task in VERIFYING state (partial grades)")

        # Summary
        all_runs = await service.list_runs()
        print(f"\n=== SUMMARY: {len(all_runs)} runs in database ===")
        for r in all_runs:
            task_info: list[str] = []
            for step in r.steps:
                for task in step.tasks:
                    att_count = len(task.attempts)
                    grade_count = sum(1 for c in task.checklist if c.grade)
                    task_info.append(
                        f"{task.config_id}:{task.status.value}(att={att_count},gr={grade_count})"
                    )
            print(f"  {r.id[:8]}... [{r.status.value:>10}] {r.routine_id:>20} | {r.project_id}")
            for info in task_info:
                print(f"    {info}")

    await engine.dispose()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
