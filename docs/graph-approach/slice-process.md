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
production orchestrator (not test harness). Being satisfied via slice 3.1
(`slice-3.1-spec.md`) run as a graph-backed orchestrator run.

## Phase 3 (Dynamic planning)

| Slice | Status | Spec |
|---|---|---|
| 3.1 Recursive horizon planner (kernel) | ✅ done | slice-3.1-spec.md |

Slice 3.1 ran as orchestrator run `38ab0331` (codex_server / gpt-5.5,
3 builder/verifier rounds: termination-invariant bypass and parallel-planner
fork both caught by the auditor and fixed). All six rubric criteria graded A.
