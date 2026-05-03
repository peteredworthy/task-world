"""Kick off E8 Arm C — ablation of per-step ctx/* files only.

Arm A (baseline): WITH codebase-discovery.md AND ctx/* files  → $5.27
Arm B:            WITHOUT discovery doc, WITH ctx/* files     → $7.32
Arm C (this):     WITH codebase-discovery.md, WITHOUT ctx/* files

Hypothesis: the discovery doc alone is sufficient context for S4/S5 children;
the per-step ctx/* files (plan-context, architecture-context, code-context) add
marginal value beyond what the discovery doc already provides.

If Arm C ≈ Arm A cost: ctx/* files are redundant overhead (can drop S-03 T-02a/b).
If Arm C > Arm A cost: ctx/* files provide signal not covered by the discovery doc.

Uses V7 as reference run (same S3 artifacts on source branch as Arm A/B), pre-marks
S1/S2/S3 complete, starts at S4 with patched routine_embedded.

Run from project root:
    uv run scripts/experiments/kickoff_e8_arm_c.py
"""

import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

REF_RUN_ID = "4e5d94a0-d362-493e-87ed-d106016138e5"  # V7
# Reuse V7's branch — has all S3 artifacts: step plans, ctx/*, intent, clarifications,
# codebase-discovery.md. Children will see the discovery doc but NOT get ctx/* files
# injected into their per_item_prompt.
SOURCE_BRANCH = f"orchestrator/run-{REF_RUN_ID}"

STOP_AFTER_STEP_INDEX = 4  # S5 (0-based): S1=0, S2=1, S3=2, S4=3, S5=4
START_STEP_INDEX = 3  # S4
BUMPED_MAX_TURNS = 100  # Match Arm A/B for fair comparison


# Patterns to strip from per_item_prompt in both S-04 T-01 and S-05 T-01.
# Each pattern is a section header + file reference block.
CTX_SECTIONS_TO_STRIP = [
    # plan-context block
    re.compile(
        r"PLAN CONTEXT \(plan sections relevant to this step\):\s*"
        r"\{\{file:docs/\{\{feature\}\}/ctx/\{\{item_stem\}\}-plan-context\.md\}\}\s*\n?",
        re.MULTILINE,
    ),
    # architecture-context block
    re.compile(
        r"ARCHITECTURE CONTEXT \(architecture sections relevant to this step\):\s*"
        r"\{\{file:docs/\{\{feature\}\}/ctx/\{\{item_stem\}\}-architecture-context\.md\}\}\s*\n?",
        re.MULTILINE,
    ),
    # code-context block (S-04 only)
    re.compile(
        r"CODE CONTEXT \(source file/function/line pointers for this step\):\s*"
        r"\{\{file:docs/\{\{feature\}\}/ctx/\{\{item_stem\}\}-code-context\.md\}\}\s*\n?",
        re.MULTILINE,
    ),
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _strip_ctx_from_per_item_prompts(routine_embedded: dict) -> tuple[int, list[tuple[str, str]]]:
    """Remove ctx/* file references from S-04 T-01 and S-05 T-01 per_item_prompt.

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
            prompt = fan_out.get("per_item_prompt") or fan_out.get("perItemPrompt")
            if not prompt:
                continue

            new_prompt = prompt
            for pattern in CTX_SECTIONS_TO_STRIP:
                match = pattern.search(new_prompt)
                if match:
                    removed.append((f"{step_id}/{task_id}", match.group(0).strip()))
                    new_prompt = pattern.sub("", new_prompt)

            if "per_item_prompt" in fan_out:
                fan_out["per_item_prompt"] = new_prompt
            elif "perItemPrompt" in fan_out:
                fan_out["perItemPrompt"] = new_prompt

    return len(removed), removed


def _bump_max_turns(routine_embedded: dict, new_max: int) -> list[tuple[str, int, int]]:
    """Set max_turns to new_max for fan_out tasks in S-04 and S-05."""
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
                fan_out["max_turns"] = new_max
            changes.append((f"{step_id}/{task_id}", old or 0, new_max))
    return changes


async def clone_run() -> None:
    logging.disable(logging.CRITICAL)

    from orchestrator.workflow.service import WorkflowService  # noqa: F401
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
            source_branch=SOURCE_BRANCH,
            config=ref_run.config,
            routine_source=RoutineSource.LOCAL,
            routine_path=str(matched_routine.path) if matched_routine.commit else None,
            routine_commit=matched_routine.commit,
        )

        new_run.routine_embedded = routine_config.model_dump(mode="json", by_alias=True)
        if isinstance(matched_routine.path, Path):
            new_run.routine_source_dir = str(matched_routine.path.parent)
        new_run.agent_runner_type = ref_run.agent_runner_type
        new_run.agent_runner_config = dict(ref_run.agent_runner_config)
        new_run.verifier_model = ref_run.verifier_model
        new_run.merge_strategy = ref_run.merge_strategy
        new_run.env_file_specs = list(ref_run.env_file_specs)
        new_run.env_source_dir = ref_run.env_source_dir

        # ── Patch routine_embedded: strip ctx/* from per_item_prompt ──────
        removals, removed_entries = _strip_ctx_from_per_item_prompts(new_run.routine_embedded)
        print(f"\nRoutine patch 1/2: removed {removals} ctx/* reference(s) from per_item_prompt")
        for loc, entry in removed_entries:
            first_line = entry.splitlines()[0]
            print(f"  - {loc}: {first_line}")
        if removals == 0:
            print("ERROR: expected to remove ctx/* references, got 0. Check routine.yaml format.")
            sys.exit(1)

        # ── Patch routine_embedded: bump max_turns for S4/S5 fan-outs ─────
        max_turns_changes = _bump_max_turns(new_run.routine_embedded, BUMPED_MAX_TURNS)
        print(f"\nRoutine patch 2/2: bumped max_turns in {len(max_turns_changes)} fan_out task(s)")
        for loc, old, new in max_turns_changes:
            print(f"  - {loc}: {old} → {new}")

        # ── Truncate routine_embedded steps to end at S5 ──────────────────
        original_step_count = len(new_run.routine_embedded["steps"])
        new_run.routine_embedded["steps"] = new_run.routine_embedded["steps"][
            : STOP_AFTER_STEP_INDEX + 1
        ]
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
                        agent_runner_type=ref_run.agent_runner_type,
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
        print(f"E8 Arm C run created: {new_run.id}")
        print("  Status:         ACTIVE")
        print(f"  Source branch:  {SOURCE_BRANCH}")
        print(f"  Label:          E8-arm-C-no-ctx-files-maxturns{BUMPED_MAX_TURNS}")
        print("  Starts at:      S4 (3 steps pre-completed)")
        print("  Ends at:        S5 (routine truncated)")
        print(f"  max_turns:      {BUMPED_MAX_TURNS} for S4-T01 and S5-T01 fan-outs")
        print("  Discovery doc:  IN shared_context (kept)")
        print("  ctx/* files:    REMOVED from per_item_prompt (ablated)")
        print("  Expected cost:  ~$4-6 if discovery doc compensates; ~$7+ if not")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(clone_run())
