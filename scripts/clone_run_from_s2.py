"""Clone a completed-S2 run so experiments can restart from S3.

Clones the state of a reference run (must have S1+S2 completed) into a new
DRAFT run whose worktree will be based on the reference run's git branch.
The new run has steps[0] and steps[1] pre-marked as completed so the engine
picks up at S3 when started.

This avoids re-running the slow S1 (intent clarification) and S2 (code-map
generation) stages when iterating on S3/S4/S5 improvements.

Usage:
    uv run scripts/clone_run_from_s2.py <ref_run_id> [--start]

Options:
    --start   Also start the run immediately (requires server on localhost:8000)

Example:
    uv run scripts/clone_run_from_s2.py 3acffefe-2c9f-4993-85e1-56747d1ddf88 --start
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

DB_PATH = "orchestrator.db"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def clone_run(ref_run_id: str, start: bool) -> None:
    # WorkflowService must be imported first to avoid circular import:
    # RunRepository → repositories.py → orchestrator.workflow → service.py → RunRepository
    from orchestrator.workflow.service import WorkflowService
    from orchestrator.workflow import PersistentEventEmitter
    from orchestrator.config.enums import RoutineSource, RunStatus, TaskStatus
    from orchestrator.db import create_engine, create_session_factory, init_db, EventStore
    from orchestrator.db import RunRepository
    from orchestrator.state.factory import create_run_from_routine
    from orchestrator.state.models import Attempt, AttemptMetrics

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

        # ── Load reference run ────────────────────────────────────────────────
        ref_run = await service.get_run(ref_run_id)

        # Verify S1 and S2 are actually completed
        completed_steps = sum(1 for s in ref_run.steps if s.completed)
        if completed_steps < 2:
            print(
                f"ERROR: Reference run {ref_run_id[:8]}... only has {completed_steps} "
                f"completed step(s). Need at least 2 (S1 + S2) completed."
            )
            sys.exit(1)

        print(f"Reference run:  {ref_run_id[:8]}... ({ref_run.status.value})")
        print(f"  Routine:      {ref_run.routine_id}")
        print(f"  Config:       {ref_run.config}")
        print(f"  Steps done:   {completed_steps}/{len(ref_run.steps)}")

        # ── Load current routine from disk (NOT from reference run's snapshot) ──
        # We always use the current routine.yaml so that V6/V7/... experiments
        # pick up the latest changes, not the frozen config from V5.
        from orchestrator.routines.discovery import discover_routines

        routine_dirs_list = [
            (Path(__file__).parent.parent / "routines", RoutineSource.LOCAL),
        ]
        found = discover_routines(routine_dirs_list)
        routine_config = None
        matched_routine = None
        for r in found:
            if r.config.id == ref_run.routine_id:
                routine_config = r.config
                matched_routine = r
                break

        if routine_config is None or matched_routine is None:
            print(
                f"ERROR: Routine '{ref_run.routine_id}' not found in routines/ directory. "
                f"Cannot clone with current routine."
            )
            sys.exit(1)

        print(f"  Using routine: {routine_config.id} (from disk, not embedded snapshot)")

        # ── Create new run branching from reference run's git branch ──────────
        source_branch = f"orchestrator/run-{ref_run_id}"
        new_run = create_run_from_routine(
            routine=routine_config,
            repo_name=ref_run.repo_name,
            source_branch=source_branch,
            config=ref_run.config,
            routine_source=RoutineSource.LOCAL,
            routine_path=str(matched_routine.path) if matched_routine.commit else None,
            routine_commit=matched_routine.commit,
        )

        # Store current routine config (not V5's frozen snapshot)
        new_run.routine_embedded = routine_config.model_dump(mode="json", by_alias=True)
        if isinstance(matched_routine.path, Path):
            new_run.routine_source_dir = str(matched_routine.path.parent)
        new_run.agent_type = ref_run.agent_type
        new_run.agent_config = dict(ref_run.agent_config)
        new_run.verifier_model = ref_run.verifier_model
        new_run.merge_strategy = ref_run.merge_strategy
        new_run.env_file_specs = list(ref_run.env_file_specs)
        new_run.env_source_dir = ref_run.env_source_dir

        # ── Pre-complete S1 and S2 with synthetic attempts ────────────────────
        now = _utcnow()
        for step_idx in range(2):
            step = new_run.steps[step_idx]
            step.completed = True
            for task in step.tasks:
                task.status = TaskStatus.COMPLETED
                task.current_attempt = 1
                task.attempts = [
                    Attempt(
                        attempt_num=1,
                        started_at=now,
                        completed_at=now,
                        outcome="passed",
                        metrics=AttemptMetrics(),
                        agent_type=ref_run.agent_type,
                        agent_model=ref_run.verifier_model,
                    )
                ]

        new_run.current_step_index = 2

        # ── Optionally pre-start (skip DRAFT → ACTIVE signal) ─────────────────
        if start:
            new_run.status = RunStatus.ACTIVE
            new_run.started_at = now

        # ── Persist ───────────────────────────────────────────────────────────
        await repo.save(new_run)
        await session.commit()

        status_label = "ACTIVE" if start else "DRAFT (start via UI or API)"
        print(f"\nNew run created: {new_run.id}")
        print(f"  Status:       {status_label}")
        print(f"  Branch:       {source_branch}")
        print("  Starts at:    S3 (steps 0 and 1 pre-completed)")
        print("\nTo start via API (if not using --start):")
        print(f"  curl -X POST http://localhost:8000/api/runs/{new_run.id}/start")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("ref_run_id", help="ID of the reference run (must have S1+S2 completed)")
    parser.add_argument(
        "--start", action="store_true", help="Start the run immediately (skips DRAFT state)"
    )
    args = parser.parse_args()

    asyncio.run(clone_run(args.ref_run_id, args.start))


if __name__ == "__main__":
    main()
