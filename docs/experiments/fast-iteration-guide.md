# Fast Iteration Guide: S3/S4/S5 Experiments

When iterating on the planning and implementation stages (S3, S4, S5), re-running
S1 (intent clarification) and S2 (code-map generation) every time wastes ~30 minutes
and burns tokens unnecessarily. This guide shows how to skip straight to S3 using
a clone of a completed reference run.

---

## The Pattern

```
Reference run (completed S1+S2)
        │
        └─ git branch: orchestrator/run-{ref_id}
                │
                ▼
        clone_run_from_s2.py
                │
                ▼
        New run (S1+S2 pre-marked complete, starts at S3)
                │
                ├─ S3: Plan generation + codebase discovery
                ├─ S4: Implementation fan-out
                ├─ S5: Cross-check
                └─ S6: [HUMAN APPROVAL GATE] ← blocks here
```

S6 has a human approval gate that prevents the run from burning tokens on final
review stages until you've inspected S3–S5 output and decided to proceed.

---

## Step 1: Identify a Reference Run

You need a completed run with at least S1 and S2 done. To find one:

```bash
# List recent runs via API
curl -s http://localhost:8000/api/runs | python3 -m json.tool | grep -E '"id"|"status"|"routine_id"'
```

Or check the UI. Look for a run with `routine_id: idea-to-plan-scoped` where S1 and S2
show as completed. The run can be in any state (ACTIVE, PAUSED, COMPLETED).

**V5 reference run** (better-state feature, 13 S4 children):
```
run_id: 3acffefe-2c9f-4993-85e1-56747d1ddf88
branch: orchestrator/run-3acffefe-2c9f-4993-85e1-56747d1ddf88
```

---

## Step 2: Clone the Run

```bash
# Create a new run pre-completing S1+S2, starting at S3
uv run scripts/clone_run_from_s2.py <ref_run_id>

# Or create AND immediately start (status set to ACTIVE in DB)
uv run scripts/clone_run_from_s2.py <ref_run_id> --start
```

The script:
1. Loads the reference run from the DB
2. Verifies S1 and S2 are completed
3. Creates a new run from the same routine + config
4. Sets `source_branch = orchestrator/run-{ref_id}` (reuses the S2 worktree artifacts)
5. Marks `steps[0]` and `steps[1]` as completed with synthetic pass attempts
6. Sets `current_step_index = 2`
7. If `--start`: sets status = ACTIVE immediately (skips the signal queue)

Example output:
```
Reference run:  3acffefe... (PAUSED)
  Routine:      idea-to-plan-scoped
  Config:       {'feature': 'better-state'}
  Steps done:   2/8

New run created: a1b2c3d4-...
  Status:       ACTIVE
  Branch:       orchestrator/run-3acffefe-2c9f-4993-85e1-56747d1ddf88
  Starts at:    S3 (steps 0 and 1 pre-completed)
```

---

## Step 3: Monitor S3–S5

Once the run is active, the orchestrator picks it up at S3. Watch progress via:

- **UI**: `/runs/{new_run_id}` — live task status, attempt details
- **Logs**: `dev.sh` console — agent output streaming

### Key artifacts to check after S3 completes

| File | What to look for |
|------|-----------------|
| `docs/{feature}/step-*-plan.md` | Step count — targeting ~4 steps |
| `docs/{feature}/codebase-discovery.md` | Exists? Is it 2–5KB? Dense signatures? |
| `docs/{feature}/clarifications.md` | Unchanged from reference run |

---

## Step 4: S6 Human Approval Gate

After S5, the run pauses at the S6 human approval gate. You'll see a pending
approval in the UI. Before approving:

1. Check `docs/{feature}/steps/` for implementation quality
2. Verify step count was ~4 (check S3 plan files)
3. Assess sub-agent usage (see below)

To approve in the UI: click "Approve" on the S6 gate in the run detail view.
To reject and iterate: click "Reject" — the run pauses and you can inspect/restart.

---

## Step 5: Assess Sub-Agent Usage

Sub-agents are the dominant cost driver. Use this script to check:

```python
from orchestrator.runners.agents.claude_cli.subagents import load_sub_agents

# For each S4/S5 child attempt: load_sub_agents(worktree_path, session_id)
# Read the action_log from the attempt's action_log field
```

Or query the DB directly:

```python
import asyncio, json
from pathlib import Path
import sys
sys.path.insert(0, "src")

from orchestrator.db import create_engine, create_session_factory, init_db, RunRepository

async def show_subagents(run_id: str):
    engine = create_engine("orchestrator.db")
    sf = create_session_factory(engine)
    await init_db(engine)
    async with sf() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)
        for step in run.steps:
            for task in step.tasks:
                for attempt in task.attempts:
                    if attempt.action_log:
                        sa = attempt.action_log.sub_agents
                        if sa:
                            cr = attempt.action_log.sub_agent_total_cache_read_tokens
                            print(f"  {step.config_id}/{task.config_id} att{attempt.attempt_num}: "
                                  f"{len(sa)} sub-agents, {cr:,} cache_read")
                            for s in sa:
                                print(f"    [{s.agent_type}] {s.description[:60]} "
                                      f"cr={s.total_cache_read_tokens:,}")

asyncio.run(show_subagents("<run_id>"))
```

### V6 target metrics

| Metric | Baseline | V5 | V6 target |
|--------|----------|-----|-----------|
| S4 children | 7 | 13 | ~4 |
| Sub-agents per child | ~1.7 | ~1.3 | < 1 |
| Sub-agent cache_read per child | ~4.4M | ~1.4M | < 500k |
| Total S4+S5 true tokens | ~26.6M | ~27.4M | ~8–12M |

### Rollback signals

If V6 sub-agent count/child is HIGHER than V5:
1. Check the discovery doc was injected: first lines of S4 child session JSONL should reference `codebase-discovery.md` in shared context
2. Read `sub_agent.description` to see what the child was looking for — this reveals what the discovery doc missed
3. Tighten the depth guard rails in the discovery task prompt in `routine.yaml`

---

## Experiment History

| Name | Run ID | Branch | Notes |
|------|--------|--------|-------|
| Baseline | `2e47c1ff` | `orchestrator/run-2e47c1ff-...` | idea-to-plan-optimized, 7 S4 children, 52.9M true tokens |
| V4 | `23aeef99` | `orchestrator/run-23aeef99-...` | idea-to-plan-scoped, 3 S4 children (flaky test failure), 30.2M true tokens |
| V5 | `3acffefe` | `orchestrator/run-3acffefe-...` | idea-to-plan-scoped, 13 S4 children, 38.2M true tokens |
| V6 | `f83dbb82` | from V5 S2 | +discovery task, step count guidance, S6 gate (RUNNING) |

---

## Notes on Source Branch Inheritance

When `source_branch = orchestrator/run-{ref_id}`, the new worktree starts from
that git branch. This means:

- All files written during S1+S2 (intent.md, clarifications.md, code-map, etc.) are
  already present in the new worktree — no need to regenerate them
- The S3 plan agent reads these files and builds on them directly
- New files written during S3+ go on a fresh commit on top of the reference branch

This is why the worktree doesn't need to re-run S1/S2 even though the DB shows
synthetic (empty) attempt records for those steps.
