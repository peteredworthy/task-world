"""Kick off E8 Arm B — back-to-back ablation of S3-T02 (codebase-discovery.md).

Creates a new run that:
  - Clones V7's state (step plans + ctx/* already exist on the source branch)
  - Uses source branch `experiment/e8-arm-b-no-discovery`, which is forked from V7's
    branch with `docs/better-state/codebase-discovery.md` git-rm'd in a prior commit.
  - Pre-marks S1, S2, S3 as completed (synthetic attempts, outcome=passed) so the
    run starts execution at S4.
  - Truncates `routine_embedded["steps"]` to end at S5 so the engine naturally
    marks the run COMPLETED when S5 finishes (no sidecar watcher).
  - Patches `routine_embedded` to remove the `codebase-discovery.md` reference from
    both S4 T-01 and S5 T-01 `fan_out.shared_context` lists.
  - Starts ACTIVE immediately.

Arm A baseline: V7 run `4e5d94a0-d362-493e-87ed-d106016138e5`'s existing DB data.
Arm B (this script): one fresh run, cost ~10M cache_read expected with E0 hotfix
applied.

Run this from the project root:
    uv run scripts/experiments/kickoff_e8_arm_b.py
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

REF_RUN_ID = "4e5d94a0-d362-493e-87ed-d106016138e5"
SOURCE_BRANCH = "experiment/e8-arm-b-no-discovery"
DISCOVERY_DOC_REF = "docs/{{feature}}/codebase-discovery.md"
DISCOVERY_DOC_REF_WITH_FILE_PREFIX = "{{file:docs/{{feature}}/codebase-discovery.md}}"
STOP_AFTER_STEP_INDEX = 4  # S5 (0-based): S1=0, S2=1, S3=2, S4=3, S5=4
START_STEP_INDEX = 3  # S4
# The previous arm B run hit max_turns=25 while still in exploration mode
# without the discovery doc. Bump to 100 for this experiment to let the agent
# finish and give us actual cost numbers. Arm A's V7 baseline ran at 25 and
# succeeded with the doc — the comparison is still fair.
BUMPED_MAX_TURNS = 100


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _strip_discovery_from_shared_context(
    routine_embedded: dict,
) -> tuple[int, list[tuple[str, str]]]:
    """Remove codebase-discovery.md entries from S-04 T-01 and S-05 T-01 shared_context.

    Returns (removals_count, removed_entries) for logging.
    """
    removed: list[tuple[str, str]] = []
    for step in routine_embedded.get("steps", []):
        step_id = step.get("id", "?")
        if step_id not in ("S-04", "S-05"):
            continue
        for task in step.get("tasks", []):
            task_id = task.get("id", "?")
            fan_out = task.get("fan_out") or task.get("fanOut")
            if not fan_out:
                continue
            shared = fan_out.get("shared_context") or fan_out.get("sharedContext") or []
            new_shared = []
            for entry in shared:
                if isinstance(entry, str) and "codebase-discovery.md" in entry:
                    removed.append((f"{step_id}/{task_id}", entry))
                    continue
                new_shared.append(entry)
            # Write back using the same key name the dict had
            if "shared_context" in fan_out:
                fan_out["shared_context"] = new_shared
            elif "sharedContext" in fan_out:
                fan_out["sharedContext"] = new_shared
    return len(removed), removed


def _bump_max_turns(routine_embedded: dict, new_max: int) -> list[tuple[str, int, int]]:
    """Set max_turns to new_max for fan_out tasks in S-04 T-01 and S-05 T-01.

    Returns a list of (location, old_value, new_value) tuples for logging.
    """
    changes: list[tuple[str, int, int]] = []
    for step in routine_embedded.get("steps", []):
        step_id = step.get("id", "?")
        if step_id not in ("S-04", "S-05"):
            continue
        for task in step.get("tasks", []):
            task_id = task.get("id", "?")
            fan_out = task.get("fan_out") or task.get("fanOut")
            if not fan_out:
                continue
            old = fan_out.get("max_turns") or fan_out.get("maxTurns")
            if "max_turns" in fan_out:
                fan_out["max_turns"] = new_max
            elif "maxTurns" in fan_out:
                fan_out["maxTurns"] = new_max
            else:
                # Neither key present — add the snake_case form that the
                # pydantic schema serialises by default
                fan_out["max_turns"] = new_max
            changes.append((f"{step_id}/{task_id}", old or 0, new_max))
    return changes


async def clone_run() -> None:
    logging.disable(logging.CRITICAL)

    # Import order matters — WorkflowService first to avoid a circular import
    # (RunRepository → repositories.py → orchestrator.workflow → service.py → RunRepository)
    from orchestrator.workflow.service import WorkflowService  # noqa: F401  # break circular import
    from orchestrator.workflow import PersistentEventEmitter
    from orchestrator.config.enums import RoutineSource, RunStatus, TaskStatus
    from orchestrator.db import (
        EventStore,
        RunRepository,
        create_engine,
        create_session_factory,
        init_db,
    )
    from orchestrator.state.factory import create_run_from_routine
    from orchestrator.state.models import Attempt, AttemptMetrics
    from orchestrator.config import discover_routines

    engine = create_engine("orchestrator.db")
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

        # ── Load reference run (V7) ───────────────────────────────────────
        ref_run = await service.get_run(REF_RUN_ID)
        print(f"Reference run: {REF_RUN_ID[:8]}... ({ref_run.status.value})")
        print(f"  Routine:     {ref_run.routine_id}")
        print(f"  Config:      {ref_run.config}")

        # ── Load current routine from disk ────────────────────────────────
        routine_dirs_list = [
            (Path(__file__).parent.parent.parent / "routines", RoutineSource.LOCAL),
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
            print(f"ERROR: Routine '{ref_run.routine_id}' not found in routines/")
            sys.exit(1)
        print(f"  Using routine: {routine_config.id} (from disk)")

        # ── Create new run ────────────────────────────────────────────────
        new_run = create_run_from_routine(
            routine=routine_config,
            repo_name=ref_run.repo_name,
            source_branch=SOURCE_BRANCH,  # custom branch with discovery doc removed
            config=ref_run.config,
            routine_source=RoutineSource.LOCAL,
            routine_path=str(matched_routine.path) if matched_routine.commit else None,
            routine_commit=matched_routine.commit,
        )

        new_run.routine_embedded = routine_config.model_dump(mode="json", by_alias=True)
        if isinstance(matched_routine.path, Path):
            new_run.routine_source_dir = str(matched_routine.path.parent)
        new_run.agent_type = ref_run.agent_type
        new_run.agent_config = dict(ref_run.agent_config)
        new_run.verifier_model = ref_run.verifier_model
        new_run.merge_strategy = ref_run.merge_strategy
        new_run.env_file_specs = list(ref_run.env_file_specs)
        new_run.env_source_dir = ref_run.env_source_dir

        # ── Patch routine_embedded: strip discovery doc from S4/S5 ────────
        removals, removed_entries = _strip_discovery_from_shared_context(new_run.routine_embedded)
        print(f"\nRoutine patch 1/2: removed {removals} codebase-discovery.md reference(s)")
        for loc, entry in removed_entries:
            print(f"  - {loc}: {entry}")
        if removals == 0:
            print("ERROR: expected to remove at least 2 references, got 0")
            sys.exit(1)

        # ── Patch routine_embedded: bump max_turns for S4/S5 fan-outs ─────
        # The previous arm B run (080fe19c) hit max_turns=25 while still in
        # exploration mode without the discovery doc. Bump to give agents
        # room to finish and produce actual cost numbers.
        max_turns_changes = _bump_max_turns(new_run.routine_embedded, BUMPED_MAX_TURNS)
        print(f"\nRoutine patch 2/2: bumped max_turns in {len(max_turns_changes)} fan_out task(s)")
        for loc, old, new in max_turns_changes:
            print(f"  - {loc}: {old} → {new}")
        if len(max_turns_changes) == 0:
            print("ERROR: expected to bump max_turns in at least 2 tasks, got 0")
            sys.exit(1)

        # ── Truncate routine_embedded steps to end at S5 ──────────────────
        # Engine reads routine_embedded["steps"] at runtime; truncating here means
        # check_run_completion() marks the run COMPLETED after S5 finishes with
        # no sidecar polling needed.
        original_step_count = len(new_run.routine_embedded["steps"])
        new_run.routine_embedded["steps"] = new_run.routine_embedded["steps"][
            : STOP_AFTER_STEP_INDEX + 1
        ]
        # Also truncate the runtime state list to match
        new_run.steps = new_run.steps[: STOP_AFTER_STEP_INDEX + 1]
        print(
            f"\nTruncated routine: {original_step_count} steps → "
            f"{len(new_run.routine_embedded['steps'])} steps (end at S5)"
        )

        # ── Pre-complete S1, S2, S3 with synthetic attempts ───────────────
        now = _utcnow()
        for step_idx in range(START_STEP_INDEX):
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
        new_run.current_step_index = START_STEP_INDEX
        print(
            f"\nPre-completed steps {list(range(START_STEP_INDEX))} "
            f"(S1, S2, S3); current_step_index = {START_STEP_INDEX} (S4)"
        )

        # ── Set ACTIVE and save ───────────────────────────────────────────
        new_run.status = RunStatus.ACTIVE
        new_run.started_at = now

        await repo.save(new_run)
        await session.commit()

        print(f"\n{'=' * 60}")
        print(f"E8 Arm B run created: {new_run.id}")
        print("  Status:         ACTIVE")
        print(f"  Source branch:  {SOURCE_BRANCH}")
        print(f"  Label:          E8-arm-B-no-discovery-doc-maxturns{BUMPED_MAX_TURNS}")
        print("  Starts at:      S4 (3 steps pre-completed)")
        print("  Ends at:        S5 (routine truncated)")
        print(f"  max_turns:      {BUMPED_MAX_TURNS} for S4-T01 and S5-T01 fan-outs")
        print("  Expected cost:  ~15-25M cache_read (higher due to bumped turn budget)")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(clone_run())
