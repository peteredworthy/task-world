# Graph-Kernel Slice Execution Process

Every implementation slice for the execution-graph kernel follows the same
3-agent pattern, and every slice runs **through the task-world orchestrator
itself** (dogfood). This document is the canonical reference.

## 3-Agent Pattern (Builder → Auditor → Fixer)

The orchestrator's builder/verifier/retry cycle maps directly:

| Orchestrator concept | Slice role |
|---|---|
| Builder phase | BUILDER — writes code + tests, runs suite |
| Verifier phase | AUDITOR — checks spec "Done when" criteria, reports gaps |
| Retry (builder with verifier feedback) | FIXER — addresses audit gaps |

The verifier's feedback is passed back verbatim to the builder on retry, so
the retry IS the fixer. No manual round-tripping needed.

## Slice Spec Files

Every slice has a spec in `docs/graph-approach/slice-N.N-spec.md`. The spec
format is fixed:

```
# Slice N.N — <title>

## Ground truth
Links to §§ in execution-graph-evaluation.md and execution-graph-prd-plus.md.

## Scope — what to build
Concrete list: files to create/modify, protocol/class shapes, command handlers.

## Tests
Exact test files + what each test proves.

## Done when
Numbered, testable criteria. The AUDITOR grades against this list.

## Hard constraints
Non-negotiable rules (no mocks, kernel purity, etc.). See § below.
```

## Universal Hard Constraints (all slices)

These are non-negotiable and apply to every slice. The verifier rubric
always checks them before grading anything else:

- **No mocks**: zero `unittest.mock` / `monkeypatching` anywhere in tests.
  Hand-written fake/recording classes injected via constructor only.
- **Real SQLite in tmp dirs**: never touch `orchestrator.db`; no server.
- **Kernel purity**: `src/orchestrator/graph/` — zero IO/DB/subprocess/HTTP
  imports. `import sqlite3`, `import asyncio` (outside `asyncio.AbstractEventLoop`
  type hints), `import subprocess`, `import aiohttp`, `import fastapi` etc.
  are all forbidden. Check: `grep -r 'sqlite\|subprocess\|aiohttp\|fastapi\|httpx'
  src/orchestrator/graph/`.
- **graph_runtime import boundary**: `src/orchestrator/graph_runtime/` must
  import no FastAPI / workflow-service internals.
- **Kernel tests stay fast**: the graph-kernel unit tests (`tests/unit/test_graph_*`)
  must stay in the low single-digit seconds. The full `tests/unit` suite has no
  hard time bound (measured ~33 s at end of phase 2 — acceptable).
- **No git mutation on main repo**: codex agents operate inside a run worktree;
  all git ops are on the worktree branch only.
- **§28 rule 1**: only `GraphController.handle_command()` appends accepted graph
  mutation events. No other path writes to `events_v2`.

## Running a Slice via the Orchestrator

### Prerequisites

```bash
# Server must be running
uv run orchestrator serve --reload
# (or: bash dev.sh)
```

### Create a run

Use the UI or API:

```bash
# Via API
curl -s http://localhost:8000/api/routines | jq '.[] | select(.routine_id=="graph-kernel-slice")'

curl -X POST http://localhost:8000/api/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "routine_id": "graph-kernel-slice",
    "project_path": "/Users/peter/code/task-world",
    "config": {
      "slice_id": "2.6",
      "spec_path": "docs/graph-approach/slice-2.6-spec.md"
    }
  }'
```

### Start the run

Select the **Codex Server** or **Claude CLI** runner in the UI, then start.
The run creates a worktree at `worktrees/run-<id>/`, codex operates there,
callbacks return through the API.

### Monitoring

- Builder output streams in real time in the UI activity log.
- When the builder submits, the verifier phase starts automatically.
- If the verifier finds gaps, the run retries (max 3 attempts per task).
- On pass, the run advances to the next step.

### After the run completes

1. Review the verifier's final grade (must be A or B to advance).
2. If the builder wrote new files, pull them from the worktree:
   ```bash
   # Worktree is at worktrees/run-<id>/
   # The orchestrator merges on completion if merge_strategy is set
   ```
3. Run the full suites from the project root to confirm nothing regressed:
   ```bash
   uv run pytest tests/unit -q && uv run pytest tests/integration -q
   uv run ruff check src tests
   uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime
   ```
4. Commit the slice (squash-merge from the run worktree branch).

## Slice Sequencing (Phase 2)

| Slice | Status | Spec |
|---|---|---|
| 2.1 Event store + outbox | ✅ done | slice-audits/builder-2.1.md |
| 2.2 Routine compiler | ✅ done | slice-audits/builder-2.2.md |
| 2.3 Runner integration | ✅ done | slice-audits/builder-2.3.md |
| 2.4 File-state boundary | ✅ done | slice-audits/builder-2.4.md |
| 2.5 LLM gatekeeper | ✅ done | slice-audits/builder-2.5.md |
| 2.6 Compat API + UI projection | ✅ done | slice-2.6-spec.md |

Builder prompts and audit/reaudit reports for 1.8–2.5 are preserved in
`docs/graph-approach/slice-audits/` (recovered from `/tmp/codex-graph/`).
Raw agent transcripts (`*.log`) were not committed.

Dogfood gate: after 2.6, execute a graph run end-to-end through the
production orchestrator (not test harness). The kernel slices (3.1, etc.)
are *built by* the orchestrator on the legacy path, but no run has yet
*executed as a graph* in the server — `graph_runtime` has no production
caller. **Slice 2.7 (`slice-2.7-spec.md`) builds that production driver and
retires this gate**; slice 2.8 adds graph startup/crash recovery wiring.

## Phase 2 completion (runtime integration)

| Slice | Status | Spec |
|---|---|---|
| 2.7 Production graph run driver | ✅ done | slice-2.7-spec.md |
| 2.8 Graph run lifecycle + recovery | ✅ done | slice-2.8-spec.md |

Slice 2.5 received a final independent crash-safety re-audit
(`slice-audits/reaudit-2.5-final.md`, verdict ACCEPT, no gaps), so 2.8 carries
no 2.5 remediation.

### Dogfood gate outcome (live graph runs through the server)

Running graph-mode runs through the production `GraphRunDriver` (the gate) was
done directly rather than via a graph-built slice, because a graph run cannot
build the fixes for its own lifecycle. The live runs surfaced and we fixed
**five** real latent defects (each committed with tests):

1. `_sweep_stale_runs` paused graph runs as `no_executor_running` at 60s —
   graph runs now excluded from the legacy executor sweeper/startup recovery.
2. Driver infinite-spin when an agent ends without a callback — no-progress
   signature guard (schedule_tick emits per-tick audit events).
3. `graph_outbox` UNIQUE(event_id) violation on re-driven runs — production
   driver now uses UUID event ids + a wall clock.
4. Operator cancel/pause did not stop the driver loop — `drive_to_quiescence`
   now honours a `should_continue` check.
5. **File-state boundary rejected every real worktree** — `_classify_path` ran
   the secret-name (`*credentials*`, `*.pem`) and repo-escape heuristics BEFORE
   the tool-cache check, so the in-worktree `.venv` (32k files: authlib/google/
   docker `credentials.py`, certifi `cacert.pem`, `.venv/bin/python` symlinks)
   was flagged as secrets/external and rejected. Tool-cache/dependency dirs are
   now classified first; genuine worker-introduced secrets outside them are
   still rejected. Also allow `.claude/` and `.worktree-manifest.json`.

**Proven live:** routine → graph compile → worker dispatch → real codex agent
execution → **clean file-state boundary capture** (after fix 5), surviving the
sweeper, with UUID-safe ids, no crash/spin, and the §13 agent_died→requeue
retry path firing. **Test-covered (integration):** worker → verifier →
`accepted` → `run_state` completed → `Run.status` COMPLETED
(`test_graph_run_driver.py`), dead-lease resume, idempotent re-arm.

A fully-green live run to COMPLETED remains the one open item. After fix 5 the
graph pipeline reaches a clean boundary capture; the final blocker observed was
**codex app-server transport instability** ("Transport error communicating with
codex app-server") after ~12 sessions in one day — the per-run app-server
processes degrade/disconnect. This is codex infra, not a graph defect (the same
codex_server/gpt-5.5 path completed run `38ab0331` earlier the same day, and the
first graph run dispatched codex fine). Re-run the live gate with a fresh codex
app-server, per the 2.8 spec's "Manual dogfood gate" — a no-op or commit-and-
clean worker on a trivial embedded routine completes the full pipeline.

Slice 2.7 ran as orchestrator run `04818168` (codex_server / gpt-5.5,
first-pass all-A). Audit-pass correction before merge: the builder's Alembic
migration declared a merge `down_revision` against an ancestor + descendant;
fixed to the linear single head and verified (upgrade/downgrade round-trip,
clean application to the live DB). The graph runtime now has a production
caller. The live dogfood gate (graph-mode run executing in the server) is
implementable as of this slice — run it manually per the 2.7 spec's
"Manual dogfood gate" section.

## Phase 3 (Dynamic planning + frontend/observability)

Phase 3 has two tracks that proceed in parallel: the **dynamic-planning** track
(the kernel/runtime payoff features) and the **frontend/observability** track
(realising PRD §26 so graph runs are inspectable as they become the default
carrier in Phase 4). Both are numbered 3.x.

### Dynamic-planning track

| Slice | Status | Spec |
|---|---|---|
| 3.1 Recursive horizon planner (kernel) | ✅ done | slice-3.1-spec.md |
| 3.7 Retained planner session | ⬜ planned | slice-3.7-spec.md |
| 3.8 Parent/child re-expressed as planner chain | ⬜ planned | slice-3.8-spec.md |

### Frontend / observability track (PRD §26)

2.6 shipped the first UI slice (read-only graph API + `GraphIndicator`/
`GraphPanel` + the `graph: <state>` projection-vs-fact label) — roughly a third
of §26. The remaining §26 requirements are sliced here:

| Slice | Status | Spec | §26 coverage |
|---|---|---|---|
| 3.2 Live graph-run activity timeline | ✅ done | slice-3.2-spec.md | Activity/event timeline (+ fixed the graph-run `on_output` regression) |
| 3.3 Node-detail drill-down | ✅ done | slice-3.3-spec.md | Node detail: inputs/outputs/file-state/callback history; "link to facts" |
| 3.4 Scheduler & leases view | ✅ done | slice-3.4-spec.md | Scheduler view (ready/blocked/waiting); active+suspended leases |
| 3.5 File-state diff & residue/gatekeeper viewer | ✅ done | slice-3.5-spec.md | File-state diff & manifest summary |
| 3.6 Human decisions, appeals & review-readiness | ⬜ next | slice-3.6-spec.md | Human decisions pending; appeals/oversight; review readiness/blockers |

Known regression folded into 3.2 (now FIXED): graph-mode runs previously emitted
**zero** `agent_output` activity events because `GraphDispatchExecutor` never
wired `on_output`. 3.2 threads an injected `on_agent_output` callback (emitter
above the import boundary) so graph runs now stream live activity.

Slice 3.2 ran as orchestrator run `e3c8089d` (codex_server / gpt-5.5,
first-pass all-A; 12 files, 752 insertions). Verified from main: 2671 unit +
1164 integration + 433 frontend pass; import boundary + kernel purity intact.

Slice 3.3 ran as orchestrator run `d6cf51be` (codex_server / gpt-5.5;
11 files, +703). The builder completed but its submit predated the codex
submission-feedback fix and hit a **latent orchestrator gap**: a
`WorktreeCommitError` from the pre-submit commit gate (2 pyright errors —
`len()` over `isinstance`-narrowed lists in `graph.py`) was re-raised in the
codex agent's `_dispatch_tool_call` generic handler, killing the session and
pausing the run as `agent_execution_error` instead of bouncing the hook output
back to the builder for a fix. **Fixed (`8f62b04c`)**: `WorktreeCommitError` is
now caught alongside `InvalidTransitionError` and returned to the agent as a
failed tool result carrying the hook output (`build_dynamic_tool_call_response`
gained an `output` arg so feedback reaches the model); the session continues so
the builder fixes and resubmits in-session — matching the HTTP `/submit`
endpoint's 409 reject-with-feedback and the claude-SDK tool-error path. The 3.3
pyright errors were hand-fixed before merge (the run predated the fix);
subsequent slices self-heal. Verified from main: import boundary + kernel
purity zero; 436 frontend pass; pyright clean.

Slice 3.1 ran as orchestrator run `38ab0331` (codex_server / gpt-5.5,
3 builder/verifier rounds: termination-invariant bypass and parallel-planner
fork both caught by the auditor and fixed). All six rubric criteria graded A.

## Phase 4 (Converge)

Graph runs become the default carrier; the parent/child oversight layer is
deleted; the loop-vs-routine-vs-graph mode experiment concludes by data. The
§26 frontend track (3.2–3.6) is a prerequisite for deleting the legacy
oversight UI.

| Slice | Status | Spec | Depends on |
|---|---|---|---|
| 4.1 Graph runs become the default carrier | ⬜ planned | slice-4.1-spec.md | gate D, 3.2–3.6 |
| 4.2 Retire the parent/child oversight layer | ⬜ planned | slice-4.2-spec.md | 3.8, 3.6, 4.1 |
| 4.3 Conclude the carrier experiment (data) | ⬜ planned | slice-4.3-spec.md | 4.1, 4.2 |

Execution order for the remaining work: dogfood gate (D) → 3.5 → 3.6 → 3.7 →
3.8 → 4.1 → 4.2 → 4.3. 4.1 must not flip the default until gate D is green; 4.2
must not delete the legacy oversight code until 3.8 (planner-chain) and 3.6
(decisions UI) provide the replacement capability.
