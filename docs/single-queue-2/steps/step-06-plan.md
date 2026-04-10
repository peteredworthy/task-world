# Step 6: Validation and Cleanup

Final verification that all intent items are satisfied, dead code from the old
dual-path routing is removed, and the full test suite is green. This step does not
introduce new functionality — it confirms the implementation is complete and clean.

All phases S-01 through S-05 must be complete before starting this step. Any
failures found here should either be fixed inline (dead code removal, trivial test
fixes) or escalated if they reveal a design problem in a prior step.

## Intent Verification

**Original Intent**: [I-21], [I-23], [I-34] — All existing tests pass after each phase; `RunWorkflow` and `AgentRunnerExecutor` do not access `app.state` directly; dead code from the old dual-path routing is removed.

**Functionality to Produce**:
- Full backend test suite (unit + integration) passes with no failures.
- Full frontend test suite passes with no failures.
- Type checker and linter report no errors.
- No dead branching logic from the old `has_active_workflow` dual-path routing remains in `service.py`.
- No no-op `handle_resume` log message remains in `run_workflow.py`.
- Every [I-XX] intent item from `docs/single-queue-2/intent.md` is annotated with a step reference.

**Final Verification Criteria**:
- `uv run pytest tests/unit/ tests/integration/ -q` exits 0.
- `cd ui && npm test -- --run` exits 0.
- `uv run pyright src/` and `uv run ruff check src/` exit 0.
- `grep -rn "has_active_workflow" src/orchestrator/workflow/service.py` returns no output.
- `grep -rn "has_active_workflow" src/orchestrator/api/` returns no output.
- `grep -n "handle_resume" src/orchestrator/workflow/run_workflow.py` returns no output (or only a real implementation, not a no-op log).
- Every `[I-XX]` in `docs/single-queue-2/intent.md` contains a `→ S-` step annotation.

---

## Task 1: Run Full Backend Test Suite

**Description**:
Execute the complete backend test suite and confirm all tests pass. Any failures
must be diagnosed and fixed before proceeding.

**Implementation Plan (Do These Steps)**

- [ ] **FM-4: Verify consumer is started in test fixtures before running the suite.**
  If integration tests exercise the full lifecycle (start → active → verify → complete)
  but no consumer is running, signals will queue up but no state transitions will happen.
  Check the test fixture setup:
  ```bash
  grep -n "consumer\|SignalConsumer\|signal_transport" tests/integration/conftest.py tests/conftest.py 2>/dev/null
  ```
  If no hits: the test transport injection (from S-03 Task 7a) must be present in conftest.py.
  If Task 7a was implemented, `app.state.signal_transport = InMemorySignalTransport()` should
  appear in the test fixture and drain_signals() should route lifecycle signals through
  consumer handlers.

- [ ] Run the full backend unit and integration suites together:

```bash
uv run pytest tests/unit/ tests/integration/ -q --tb=short 2>&1 | tail -40
```

- [ ] If failures appear, read the failure output and fix the root cause. Do NOT skip
  or delete failing tests unless they test behaviour that was intentionally removed
  in S-01 through S-05 (and that removal was documented).

- [ ] Re-run until the suite is fully green.

**Functionality (Expected Outcomes)**
- [ ] All backend unit and integration tests pass with exit code 0.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -q` exits 0 and reports 0 failures.

---

## Task 2: Run Full Frontend Test Suite

**Description**:
Execute the complete frontend test suite and confirm all tests pass. This validates
that the API response-code changes (200 → 202) and the addition of `STOPPING` to the
`RunStatus` type did not break frontend expectations.

**Implementation Plan (Do These Steps)**

- [ ] Run the frontend test suite:

```bash
cd ui && npm test -- --run 2>&1 | tail -30
```

- [ ] If failures appear, read the failure output and fix the root cause. Common
  causes after S-01–S-05:
  - Frontend `RunStatus` type missing `"stopping"`.
  - Test assertions expecting HTTP 200 from start/pause/resume/cancel endpoints that
    now return 202.

- [ ] Re-run until the suite is fully green.

**Functionality (Expected Outcomes)**
- [ ] All frontend tests pass with exit code 0.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `cd ui && npm test -- --run` exits 0 and reports 0 failures.

---

## Task 3: Run Type Checker and Linter

**Description**:
Run `pyright` for type checking and `ruff` for linting on the backend source. Run
`tsc --noEmit` on the frontend. Any errors must be fixed before this step is complete.

**Implementation Plan (Do These Steps)**

- [ ] Run pyright:

```bash
uv run pyright src/ 2>&1 | tail -20
```

- [ ] Run ruff:

```bash
uv run ruff check src/ 2>&1 | tail -20
```

- [ ] Run TypeScript type check for the frontend:

```bash
cd ui && npx tsc --noEmit 2>&1 | tail -20
```

- [ ] For any error reported, fix the underlying issue. Common post-S-05 errors:
  - Missing `STOPPING` in frontend `RunStatus` union type.
  - Unused import warnings for registry functions removed in S-04.
  - Pyright errors from `consumer.py` after import path change in S-04.

**Functionality (Expected Outcomes)**
- [ ] `pyright src/` reports 0 errors.
- [ ] `ruff check src/` reports 0 errors.
- [ ] `tsc --noEmit` in `ui/` reports 0 errors.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pyright src/` exits 0.
- [ ] `uv run ruff check src/` exits 0.
- [ ] `cd ui && npx tsc --noEmit` exits 0.

---

## Task 4: Remove Dead Code from Old Dual-Path Routing

**Description**:
After S-01 through S-04, the old `has_active_workflow` branching in `service.py`
and the no-op `handle_resume` log in `run_workflow.py` are dead. Remove them so no
backward-compatibility stubs remain.

**Implementation Plan (Do These Steps)**

- [ ] Search for residual `has_active_workflow` usage in service and API layers:

```bash
grep -rn "has_active_workflow" src/orchestrator/workflow/service.py src/orchestrator/api/ --include="*.py"
```

  If any matches appear, they are dead code left from S-03 rewiring. Remove each
  occurrence (import line + any surrounding conditional block that was gated on it).

- [ ] **H2: Correct file path** — `handle_resume` lives in `runtime.py`, not `run_workflow.py`.
  Search in the correct file:

```bash
grep -n "handle_resume" src/orchestrator/workflow/signals/runtime.py
```

  If the method exists only as a no-op log (e.g., `logger.debug("handle_resume called — no-op")`),
  remove it entirely. In the target architecture RESUME is handled by the consumer
  (creates a new RunWorkflow for a PAUSED run) — `RunWorkflow.handle_resume()` is genuinely
  dead after S-02/S-03. Also verify `unregister_active_run` calls are gone from runtime.py:</p>

```bash
grep -n "unregister_active_run\|register_active_run" src/orchestrator/workflow/signals/runtime.py
```
  Expected: no output (should have been removed in S-03).

- [ ] Search for other old-routing patterns — any conditional that was only needed
  because `has_active_workflow` returned True or False (H2 fix: use `runtime.py`):

```bash
grep -n "has_active_workflow\|if.*active_workflow\|direct.*branch" \
  src/orchestrator/workflow/service.py \
  src/orchestrator/workflow/signals/runtime.py
```

  Remove each confirmed dead block.

- [ ] After removals, run the backend unit tests to confirm nothing broke:

```bash
uv run pytest tests/unit/ -x -q 2>&1 | tail -20
```

**Constraints**
- Only remove code that is provably unreachable (no callers, no live conditional path
  leading to it).
- If removing a block causes a test failure, the code was NOT dead — restore it and
  investigate why S-03/S-04 did not fully clean it up.
- Files touched should be limited to `service.py` and `run_workflow.py` (plus any
  additional files surfaced by the grep).

**Functionality (Expected Outcomes)**
- [ ] `service.py` contains no `has_active_workflow` imports or calls.
- [ ] `run_workflow.py` contains no no-op `handle_resume` log-only method.
- [ ] All backend unit tests continue to pass.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "has_active_workflow" src/orchestrator/workflow/service.py` returns no output.
- [ ] `grep -rn "has_active_workflow" src/orchestrator/api/` returns no output.
- [ ] `grep -n "handle_resume" src/orchestrator/workflow/signals/runtime.py` returns no output (or only a real, non-no-op implementation). [H2: correct path]
- [ ] `grep -n "unregister_active_run" src/orchestrator/workflow/signals/runtime.py` returns no output. [FM-2: must be removed by S-03]
- [ ] `uv run pytest tests/unit/ -x -q` exits 0.

---

## Task 5: Verify [I-XX] Traceability Coverage

**Description**:
Confirm that every intent item in `docs/single-queue-2/intent.md` is annotated with
a step reference (`→ S-NN`) or explicitly marked as deferred (`→ NO-REQ`). Any item
lacking a step annotation indicates a gap.

**Implementation Plan (Do These Steps)**

- [ ] Read `docs/single-queue-2/intent.md` and collect every `[I-XX]` item.

- [ ] For each item, verify it has a `→ S-` or `→ NO-REQ` annotation in the intent
  file itself. The current annotation format used in the file is inline on the same
  line as the intent statement, e.g.:

  ```
  - Eliminate sender-side routing ... [I-01 → S-03]
  ```

- [ ] List any [I-XX] items that lack a step annotation.

- [ ] For each unannotated item:
  1. If the item is addressed by an existing step (S-01 through S-06), add the
     annotation inline in `docs/single-queue-2/intent.md`.
  2. If the item is explicitly deferred (no implementation planned), annotate with
     `→ NO-REQ: <reason>`.
  3. If the item appears to be unaddressed, escalate — do not silently skip it.

- [ ] After any edits to `intent.md`, re-read the file and confirm every `[I-XX]`
  item has an annotation.

**Constraints**
- Only `docs/single-queue-2/intent.md` should be modified (annotation additions only).
- Do not change the substance of any intent item — only add or correct step references.

**Functionality (Expected Outcomes)**
- [ ] Every `[I-XX]` item in `intent.md` has either a `→ S-NN` or `→ NO-REQ` annotation.
- [ ] No item is silently unannotated.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "\[I-[0-9]" docs/single-queue-2/intent.md | grep -v "→"` returns no output
  (every intent item has an arrow annotation).

---

## Task 6: Final Full Suite Pass

**Description**:
After all dead code removal and traceability fixes, run the complete test suite one
final time end-to-end to confirm the codebase is clean.

**Implementation Plan (Do These Steps)**

- [ ] Run the complete backend suite:

```bash
uv run pytest tests/unit/ tests/integration/ -q 2>&1 | tail -20
```

- [ ] Run the complete frontend suite:

```bash
cd ui && npm test -- --run 2>&1 | tail -20
```

- [ ] Run type check and lint:

```bash
uv run pyright src/ && uv run ruff check src/ && echo "Backend static analysis clean"
cd ui && npx tsc --noEmit && echo "Frontend types clean"
```

- [ ] Confirm the pre-commit guard script also passes (added in S-05):

```bash
uv run python scripts/check_signal_routing.py && echo "Signal routing guard clean"
```

- [ ] If any check fails, fix the issue and re-run from the failing check.

**Functionality (Expected Outcomes)**
- [ ] All backend unit and integration tests pass.
- [ ] All frontend tests pass.
- [ ] Type checker and linter are clean.
- [ ] Pre-commit signal routing guard passes.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -q` exits 0.
- [ ] `cd ui && npm test -- --run` exits 0.
- [ ] `uv run pyright src/` exits 0.
- [ ] `uv run ruff check src/` exits 0.
- [ ] `cd ui && npx tsc --noEmit` exits 0.
- [ ] `uv run python scripts/check_signal_routing.py` exits 0.
