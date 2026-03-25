"""Restore database from the event journal (history.jsonl).

Creates run skeletons from routine YAML files with the correct IDs
extracted from the journal, then replays events to reconstruct state.

Usage:
    uv run python scripts/restore_from_journal.py

State before destruction (from merged journal with stash recovery):
- b14aa49f: conditional-steps — COMPLETED at seq 636 (all 20 tasks, 6 steps)
- d5c76a7d: idea-to-plan — FAILED at seq 804 (task 0b05d30a failed,
  but all work was merged to main; the "failure" was likely a gate/approval)
- fab1755e: orchestrated-expansion — IN PROGRESS (paused at seq 927).
  6 tasks touched, 5 completed, 1 verifying, 22 pending. Step 1 in progress.

Note: seq 928 (b14aa49f active->paused) is a ghost event from a server restart
after DB destruction. It's excluded from replay.
"""

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

from orchestrator.config.models import RoutineConfig
from orchestrator.db import replay_events
from orchestrator.state.models import Run, StepState, TaskState, ChecklistItem, Attempt
from orchestrator.config.enums import TaskStatus


JOURNAL_PATH = Path(".orchestrator/state/history.jsonl")

# Ghost events to exclude — spurious events written after DB was destroyed,
# when the server restarted with a fresh DB and tried to manage stale run state.
EXCLUDE_SEQUENCES = {928}  # b14aa49f active->paused after it was already completed


# ── Run definitions ──────────────────────────────────────────────────

RUN_DEFINITIONS = {
    # ── b14aa49f: conditional-steps (COMPLETED) ──────────────────────
    # All 20 tasks completed, all 6 steps completed. Seq 636: active->completed.
    "b14aa49f-5be8-46a1-97ec-db1db06c685f": {
        "routine_path": "routines/conditional-steps/routine.yaml",
        "routine_id": "conditional-steps",
        "repo_name": "task-world",
        "source_branch": "main",
        "worktree_path": "worktrees/r21",
        "step_ids": {
            0: "192998b7-9df1-4488-854d-89fda08d3fdd",
            1: "4e769021-0192-48bb-8b28-f0beb6dc0821",
        },
        # Tasks from step 0 (4 tasks), step 1 (3 tasks), step 2 (3 tasks)
        # Steps 3-5 (10 more tasks) come from the recovered journal
        "task_ids": {
            (0, 0): "764d2a72-d4cc-4571-b4cd-10be4061adf1",
            (0, 1): "d617c3ce-db01-4fc5-b36c-6acdda81154e",
            (0, 2): "ff771c3d-089a-4388-ba09-6ed69f9bb566",
            (0, 3): "3fa78ef6-7816-4f1f-9afc-4862f4c798cd",
            (1, 0): "b16e9607-4700-4b72-a7ae-fa9104e102b3",
            (1, 1): "8dfe4bec-2f28-4e98-9a9b-ef322eb6e958",
            (1, 2): "2b4859d6-da87-4da7-af97-8e6a9cabe8eb",
            (2, 0): "1c00f24d-95dc-4e04-8d36-15c386d71288",
            (2, 1): "0930a627-8432-41a7-af04-a5d2a3862bf0",
            (2, 2): "36b95ea3-5f12-4e86-8251-405071d1aa10",
            # Step 3 (3 tasks) - from recovered journal
            (3, 0): "c9e9bcb2",  # placeholder, will be filled from journal
            (3, 1): "0c64c2a3",
            (3, 2): "0610b6a4",
            # Step 4 (3 tasks)
            (4, 0): "b777d353",
            (4, 1): "249ea044",
            (4, 2): "a4d69533",
            # Step 5 (4 tasks)
            (5, 0): "86da8eb8",
            (5, 1): "391d7343",
            (5, 2): "71bd0f53",
            (5, 3): "9e511ea0",
        },
    },
    # ── d5c76a7d: idea-to-plan (FAILED) ─────────────────────────────
    # All steps completed, but run ended as FAILED at seq 804.
    # Task 0b05d30a failed (step 7, the execution-ready step).
    # Despite the failure, the routine YAML was produced and merged.
    "d5c76a7d-f92c-4222-9b74-fe9cd3a8ef8a": {
        "routine_path": "routines/idea-to-plan/routine.yaml",
        "routine_id": "idea-to-plan",
        "repo_name": "task-world",
        "source_branch": "main",
        "worktree_path": None,
        "step_ids": {},
        "task_ids": {
            (0, 0): "70337140",
            (1, 0): "cecb2c8a",
            (2, 0): "76a6e229",
            (3, 0): "3df544e0",
            (4, 0): "16c3ca23",
            (5, 0): "b569a824",
            (6, 0): "e11b3e49",
            (7, 0): "99b57192",
            (7, 1): "0b05d30a",
        },
    },
    # ── fab1755e: orchestrated-expansion (IN PROGRESS / PAUSED) ──────
    # Working in worktree r22. Last status: active->paused at seq 927.
    # 6 of 27 tasks touched in step 1. Task 9ee0e511 was already building
    # when journal started (from a prior run segment).
    "fab1755e-3839-4efe-9d22-26b23d7b7989": {
        "routine_path": "routines/orchestrated-expansion/routine.yaml",
        "routine_id": "orchestrated-expansion",
        "repo_name": "task-world",
        "source_branch": "main",
        "worktree_path": "worktrees/r22",
        "step_ids": {},
        "task_ids": {
            (0, 0): "9ee0e511-4184-463b-9dfd-338962558887",  # T-01
            (0, 1): "7b23d842-47a5-4ac3-a3d7-30ff67c2b898",  # T-02
            (0, 2): "667ee4b3-1831-4ef0-8516-52b2c72c2c4d",  # T-03
            (0, 3): "32d37a4a-ddb3-47ee-8962-51c9358e51de",  # T-04
            (0, 4): "73cd81a2-bf81-4b00-a016-c8fee77c4030",  # T-05
            (0, 5): "2bbdbac7",  # T-06 (from recovered journal)
        },
        "pre_building_tasks": {"9ee0e511-4184-463b-9dfd-338962558887"},
    },
}


def load_routine(path: str) -> RoutineConfig:
    """Load a routine YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return RoutineConfig.model_validate(data["routine"])


def create_checklist(task_config) -> list[ChecklistItem]:
    """Create checklist items from task config requirements."""
    return [
        ChecklistItem(
            req_id=req.id,
            desc=req.desc,
            priority=req.priority,
        )
        for req in task_config.requirements
    ]


def extract_full_task_ids(run_id: str) -> dict[str, str]:
    """Extract full UUIDs for tasks from journal events.

    Returns mapping of short_id_prefix -> full_uuid.
    """
    full_ids = {}
    with open(JOURNAL_PATH) as f:
        for line in f:
            entry = json.loads(line)
            if entry.get("run_id") != run_id:
                continue
            payload = entry.get("payload", {})
            task_id = payload.get("task_id", "")
            if task_id and len(task_id) > 8:
                full_ids[task_id[:8]] = task_id
    return full_ids


def build_run_skeleton(run_id: str, definition: dict) -> Run:
    """Build a Run skeleton with specific IDs from the journal."""
    routine = load_routine(definition["routine_path"])

    step_id_map = definition.get("step_ids", {})
    task_id_map = definition.get("task_ids", {})

    # Resolve short task IDs to full UUIDs from journal
    full_ids = extract_full_task_ids(run_id)

    # Also extract step IDs from step_completed events
    step_ids_from_journal = {}
    with open(JOURNAL_PATH) as f:
        for line in f:
            entry = json.loads(line)
            if entry.get("run_id") != run_id:
                continue
            if entry.get("event_type") == "step_completed":
                p = entry["payload"]
                step_ids_from_journal[p.get("step_index")] = p.get("step_id", "")

    steps = []
    for step_idx, step_config in enumerate(routine.steps):
        tasks = []
        for task_idx, task_config in enumerate(step_config.tasks):
            task_id = task_id_map.get((step_idx, task_idx))
            if task_id and len(task_id) <= 8:
                # Short ID — resolve to full UUID
                task_id = full_ids.get(task_id, str(uuid4()))
            elif not task_id:
                task_id = str(uuid4())

            has_verification = bool(task_config.auto_verify.items) or bool(
                task_config.verifier.rubric
            )
            tasks.append(
                TaskState(
                    id=task_id,
                    config_id=task_config.id,
                    title=task_config.title,
                    complexity=task_config.complexity.value,
                    checklist=create_checklist(task_config),
                    max_attempts=task_config.retry.max_attempts,
                    has_verification=has_verification,
                )
            )

        step_id = step_id_map.get(step_idx) or step_ids_from_journal.get(step_idx) or str(uuid4())
        steps.append(
            StepState(
                id=step_id,
                config_id=step_config.id,
                title=step_config.title or step_config.id,
                tasks=tasks,
            )
        )

    routine_embedded = routine.model_dump(mode="json", by_alias=True)

    return Run(
        id=run_id,
        repo_name=definition["repo_name"],
        source_branch=definition["source_branch"],
        routine_id=definition["routine_id"],
        routine_embedded=routine_embedded,
        routine_source="local",
        steps=steps,
        worktree_enabled=True,
        worktree_path=definition.get("worktree_path"),
    )


def load_journal_events(run_id: str) -> list[dict]:
    """Load and parse journal events for a specific run."""
    from orchestrator.db import parse_journal_timestamp

    events = []
    with open(JOURNAL_PATH) as f:
        for line in f:
            entry = json.loads(line)
            if entry.get("run_id") != run_id:
                continue

            seq = entry.get("sequence_number", 0)
            if seq in EXCLUDE_SEQUENCES:
                continue

            timestamp_raw = entry.get("timestamp")
            if not isinstance(timestamp_raw, str):
                continue

            timestamp = parse_journal_timestamp(timestamp_raw)
            events.append(
                {
                    "type": entry["event_type"],
                    "timestamp": timestamp,
                    "payload": entry.get("payload", {}),
                    "sequence_number": seq,
                }
            )

    events.sort(key=lambda e: e["sequence_number"])
    return events


async def restore_run(run_id: str, definition: dict, session) -> Run | None:
    """Restore a single run from journal."""
    from orchestrator.db import RunRepository

    print(f"\n{'=' * 60}")
    print(f"Restoring run: {run_id}")
    print(f"  Routine: {definition['routine_id']}")

    # Build skeleton
    run = build_run_skeleton(run_id, definition)
    print(f"  Steps: {len(run.steps)}, Tasks: {sum(len(s.tasks) for s in run.steps)}")

    # Handle pre-existing task states (tasks already building before journal)
    pre_building = definition.get("pre_building_tasks", set())
    for task_id in pre_building:
        for step in run.steps:
            for task in step.tasks:
                if task.id == task_id:
                    task.status = TaskStatus.BUILDING
                    task.current_attempt = 1
                    task.attempts.append(Attempt(attempt_num=1))
                    print(f"  Pre-set task {task_id[:8]} as BUILDING (attempt 1)")

    # Load and replay journal events
    events = load_journal_events(run_id)
    print(f"  Journal events: {len(events)}")
    replay_events(run, events)
    print(f"  After replay: status={run.status.value}")

    # Summary
    status_counts = defaultdict(int)
    for step in run.steps:
        for task in step.tasks:
            status_counts[task.status.value] += 1
    step_completed = sum(1 for s in run.steps if s.completed)
    print(f"  Steps completed: {step_completed}/{len(run.steps)}")
    print(f"  Task statuses: {dict(status_counts)}")

    # Save to DB
    repo = RunRepository(session)
    await repo.save(run)
    await session.commit()
    print("  Saved to database")

    return run


async def main():
    """Main restoration entry point."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    db_path = Path("orchestrator.db")

    if not db_path.exists():
        print("ERROR: orchestrator.db not found")
        sys.exit(1)

    if not JOURNAL_PATH.exists():
        print(f"ERROR: Journal not found at {JOURNAL_PATH}")
        sys.exit(1)

    # Check current DB state
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    run_count = conn.execute("SELECT count(*) FROM runs").fetchone()[0]
    conn.close()

    if run_count > 0:
        print(f"WARNING: Database already has {run_count} runs.")
        print("Clearing existing data for clean restore...")
        conn = sqlite3.connect(str(db_path))
        for table in [
            "events",
            "attempts",
            "tasks",
            "steps",
            "runs",
            "clarification_responses",
            "clarification_requests",
        ]:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()
        print("  Cleared all run data.")

    # Create async engine
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print(f"\nRestoring from {JOURNAL_PATH}")
    print(f"Journal has {sum(1 for _ in open(JOURNAL_PATH))} entries")

    restored = []
    for run_id, definition in RUN_DEFINITIONS.items():
        async with async_session() as session:
            run = await restore_run(run_id, definition, session)
            if run:
                restored.append((run_id, run.status.value))

    await engine.dispose()

    print(f"\n{'=' * 60}")
    print(f"Restoration complete: {len(restored)} runs restored")
    for rid, status in restored:
        defn = RUN_DEFINITIONS[rid]
        print(f"  - {rid} ({defn['routine_id']}, {status.upper()})")

    # Replay events into the events table
    print("\nReplaying events into events table...")
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM events")

    with open(JOURNAL_PATH) as f:
        count = 0
        for line in f:
            entry = json.loads(line)
            run_id = entry.get("run_id", "")
            seq = entry.get("sequence_number", 0)
            event_type = entry.get("event_type", "")
            timestamp = entry.get("timestamp", "")
            payload = entry.get("payload", {})

            if run_id in RUN_DEFINITIONS and seq not in EXCLUDE_SEQUENCES:
                conn.execute(
                    "INSERT INTO events (run_id, event_type, timestamp, payload) VALUES (?, ?, ?, ?)",
                    (run_id, event_type, timestamp, json.dumps(payload)),
                )
                count += 1

    conn.commit()
    conn.close()
    print(f"  Inserted {count} events")


if __name__ == "__main__":
    asyncio.run(main())
