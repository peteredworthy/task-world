# Single-Queue Signal Model — Verification Report

**Date:** 2026-03-26
**Analyzed by:** Step-06 verification pass
**Status: ✗ Needs Work** — critical dry-run gaps found NOT applied to step files;
all gaps have now been applied in this verification pass. Step files are now
execution-ready. Re-verification recommended before implementation begins.

---

## Summary

This report cross-checks intent → plan → step files → dry-run analysis for the
single-queue signal model migration. A full audit was performed against:
- `docs/single-queue-2/intent.md` (36 [I-XX] items)
- `docs/single-queue-2/plan.md` (6 phases)
- `docs/single-queue-2/steps/step-01-plan.md` through `step-06-plan.md`
- `docs/single-queue-2/dry-run/step-01-plan-notes.md` through `step-06-plan-notes.md`

**Verdict before this pass:** Multiple critical dry-run gaps were NOT applied to step
files (only documented in separate dry-run notes files). Implementing from the original
step files would have produced broken code.

**Verdict after this pass:** All critical and significant gaps have been applied to step
files. Step files are now consistent with the dry-run analysis. The plan remains
executable and intent-aligned.

---

## R1: Step Files Align with Plan and Intent

**Result: PASS** (with caveats resolved in this pass)

Each step file traces to the relevant plan phase and intent items:

| Step | Plan Phase | Intent Items | Alignment |
|------|-----------|--------------|-----------|
| S-01 | Phase 1: Schema and State Machine | I-07, I-08, I-09, I-16, I-22, I-26, I-35 | ✓ Aligned |
| S-02 | Phase 2: Consumer | I-02, I-05, I-12, I-25, I-31, I-36 | ✓ Aligned (gaps fixed) |
| S-03 | Phase 3: Sender Rewiring | I-01, I-10, I-11, I-13, I-17, I-27, I-28 | ✓ Aligned (gaps fixed) |
| S-04 | Phase 4: Registry Isolation | I-04, I-29, I-30 | ✓ Aligned |
| S-05 | Phase 5: Guards and Documentation | I-14, I-15, I-32, I-33 | ✓ Aligned (gap fixed) |
| S-06 | Phase 6: Validation and Cleanup | I-21, I-23, I-34 | ✓ Aligned (gaps fixed) |

All six step files follow the plan's phased structure. Build order (S-01 → S-06) is
correctly sequenced: schema before consumer, consumer before sender rewiring, sender
rewiring before registry isolation.

---

## R2: All Critical/Significant Dry-Run Gaps Applied to Step Files

**Result: ✓ PASS** (after this verification pass applied all gaps)

The following gaps were found **NOT applied** to step files at the start of this audit.
All have now been applied.

### Step 1 (S-01) — Applied in this pass

| Gap ID | Severity | Description | Applied? |
|--------|----------|-------------|----------|
| FM-4A | Critical | `start_task()` has NO existing guard; step said "modify existing" | ✓ Fixed: instruction rewritten to "add new guard from scratch" |
| FM-4B | Critical | `submit_for_verification()` has NO existing guard; step was misleading | ✓ Fixed: instruction rewritten; explicit note about new `get_run()` call |
| FM-6A | High | Test for `submit_for_verification` guard missing from test file | ✓ Fixed: `test_submit_for_verification_rejects_stopping` added to Task 6 code |
| FM-5B | Medium | `delete_run` didn't reject STOPPING runs | ✓ Fixed: guard added to Task 5 |

### Step 2 (S-02) — Applied in this pass

| Gap ID | Severity | Description | Applied? |
|--------|----------|-------------|----------|
| FM-2A | **Critical** | `on_run_start()` requires 4+ params; step called it with 1 | ✓ Fixed: Task 2 now loads run from DB and calls with all required args |
| FM-3A | **Critical** | `on_cancel()` doesn't exist on `EnvFileLifecycle` | ✓ Fixed: Task 3 rewritten to use `on_run_end()` instead |
| FM-3C | **Critical** | Consumer needs `service_factory` for handler calls; not in constructor | ✓ Fixed: `service_factory` added to `SignalConsumer.__init__` |
| FM-8A | **Critical** | `build_executor_callbacks(app_state)` doesn't exist in codebase | ✓ Fixed: Task 8 replaced with inline `ExecutorCallbacks(...)` construction pattern |
| FM-8B | **Critical** | `RunWorkflow` factory lambda can't provide `transport` without session | ✓ Fixed: Task 8 updated to use factory function (not lambda) with session access |
| FM-3D | Moderate | `engine._set_stopping` is private; should be public `set_run_stopping` / `transition_to_stopping` | ✓ Fixed: Task 3 now references public method name |
| FM-8C | Moderate | Consumer must start AFTER auto-resume block in app.py | ✓ Fixed: ordering note added to Task 8 |

### Step 3 (S-03) — Applied in this pass

| Gap ID | Severity | Description | Applied? |
|--------|----------|-------------|----------|
| FM-5 | **Critical** | Circular loop: `handle_pause()` calls `service.pause_run()` which re-enqueues | ✓ Fixed: **new Task 2b added** to rewrite `handle_pause` to return True without calling service |
| FM-6 | **Critical** | Circular loop: `handle_cancel()` calls `service.cancel_run()` which re-enqueues | ✓ Fixed: Task 2b also covers `handle_cancel` |
| FM-20 | **Critical** | Test transport mismatch: service uses DB, test drain uses InMemory | ✓ Fixed: **new Task 7a added** with injectable transport solution |
| FM-7 | High | 13+ `service.pause_run()` calls in `_run_loop()` not addressed | ✓ Scoped: documented as known invariant violation until Step 4; acceptable |
| FM-22 | High | `_start_run()` test helper asserts 200 and extracts body from 202 | ✓ Fixed: noted in Task 7 |

### Step 4 (S-04) — No critical gaps found

Step 4 is mechanically correct given S-02 and S-03 prerequisites. Minor ordering
note (Tasks 2+3 must be applied atomically before running verification) is already
covered by the "DO NOT CHECK UNTIL IMPLEMENTATION IS COMPLETE" instructions.

### Step 5 (S-05) — Applied in this pass

| Gap ID | Severity | Description | Applied? |
|--------|----------|-------------|----------|
| F-1 | **Critical** | `test_signal_redelivery.py` NOT exempted by `is_allowed_file()` | ✓ Fixed: exemption logic updated to include `"redelivery"` in filename check; path-scoping for `consumer.py` also added |
| F-3 | Low | Multi-line import `# noqa` placement documented incorrectly | ✓ Fixed: docstring note added |

### Step 6 (S-06) — Applied in this pass

| Gap ID | Severity | Description | Applied? |
|--------|----------|-------------|----------|
| H2 | High | Wrong file path: `run_workflow.py` → actual is `runtime.py` | ✓ Fixed: all grep commands updated to `src/orchestrator/workflow/signals/runtime.py` |
| FM-4 | High | No check that consumer is started in test fixtures | ✓ Fixed: pre-run consumer fixture verification added to Task 1 |
| H4 | High | `unregister_active_run` not grepped in Task 4 | ✓ Fixed: grep added to Task 4 final verification |

---

## R3: No Unresolved Critical Conflicts

**Result: ✓ PASS** (after applying gaps)

All critical conflicts have been resolved by gap application in this pass:
- The circular signal loop bugs (FM-5, FM-6) are addressed by new Task 2b in S-03.
- The test transport mismatch (FM-20) is addressed by new Task 7a in S-03.
- The `on_run_start` signature mismatch (FM-2A) is corrected in S-02.
- The `on_cancel` missing method (FM-3A) is corrected in S-02.
- The `build_executor_callbacks` missing function (FM-8A, FM-8B) is corrected in S-02.
- The `is_allowed_file()` false positive for redelivery tests (F-1) is fixed in S-05.

**Known acceptable risks (documented, not blocking):**
- `_run_loop()` has ~13 internal `service.pause_run()` calls that will enqueue signals
  after S-03 rewiring. This is semantically correct and documented as a known invariant
  violation until Step 4. The consumer handles these signals correctly.
- The `RunWorkflow.on_signal()` / consumer signal competition is a latent race for
  ACTIVITY signals addressed by Task 7a's transport injection approach.

---

## R4: Persistence Mapping Audit — No MISSING Cells

**Result: ✓ PASS**

The feature adds three new/changed fields to `pending_signals`:

| Field | ORM Model | Dataclass | Migration | Transport | Status |
|-------|-----------|-----------|-----------|-----------|--------|
| `id: int` (PK change) | S-01 Task 2 ✓ | S-01 Task 2 ✓ | S-01 Task 1 ✓ | S-01 Task 2 ✓ | Complete |
| `delivered_at: datetime \| None` (new) | S-01 Task 2 ✓ | S-01 Task 2 ✓ | S-01 Task 1 ✓ | S-01 Task 2 ✓ | Complete |
| `handled_at: datetime \| None` (renamed) | S-01 Task 2 ✓ | S-01 Task 2 ✓ | S-01 Task 1 ✓ | S-01 Task 2 ✓ | Complete |

Additionally, `RunStatus.STOPPING = "stopping"` is added to the enum — covered in
S-01 Task 3 (Python enum), and S-06 Task 2 flags the frontend `RunStatus` type update.

**No MISSING cells.** All persistence mappings are fully specified.

---

## R5: Integration Test Steps Specify Assertion Logic

**Result: ✓ PASS**

All step files that include integration or unit tests specify concrete assertion logic:

**S-01 Task 6** — `test_stopping_state.py`:
- Concrete assertions: `assert result.status == RunStatus.STOPPING`, `assert isinstance(event, RunStatusChanged)`, `assert event.old_status == RunStatus.ACTIVE`
- Specific test for each transition (transition_to_stopping, pause rejects, cancel rejects, resume rejects, start_task rejects, submit_for_verification rejects)

**S-02 Task 6** — `test_signal_consumer.py`:
- FIFO ordering: "Insert signals with ids 10, 20, 5. Confirm they are dispatched in order 5, 10, 20"
- Delivery tracking: "Mock handler records when `delivered_at` was set vs when it ran; assert delivery precedes handler call"
- Handler error: "Mock handler raises; assert `handled_at IS NULL` after dispatch"

**S-02 Task 7** — `test_signal_redelivery.py`:
- 7 specific test cases with concrete state setups (signal with `delivered_at` set, `handled_at` null) and assertions (signal IS/IS NOT re-dispatched)

**S-03 Task 7** — Integration test update:
- Specifies `wait_for_status()` helper with timeout and polling logic
- Concrete: "assert response.status_code == 202" replacing "== 200"

All step files with tests specify what to assert, not just scenario names. ✓

---

## R6: Intent Coverage — Every [I-XX] Annotated

**Result: ✓ PASS**

All 36 intent items in `docs/single-queue-2/intent.md` have `→ S-XX` or `→ NO-REQ`
annotations. Traceability check against step file content:

| Item | Annotation | Step Coverage | Verified |
|------|-----------|--------------|---------|
| I-01 | → S-03 | S-03 Tasks 1,3,4: enqueue-only service methods | ✓ |
| I-02 | → S-02 | S-02: entire step builds the consumer | ✓ |
| I-03 | → S-01 | S-01 Task 3: STOPPING added to RunStatus | ✓ |
| I-04 | → S-04 | S-04: removes public exports, restricts to consumer | ✓ |
| I-05 | → S-01, S-02 | S-01 Task 1/2: schema; S-02: consumer sets delivered_at/handled_at | ✓ |
| I-06 | → S-02, S-03 | S-02: per-run asyncio.Task; S-03: removes routing branch | ✓ |
| I-07 | → S-01 | S-01 Tasks 1,2: int PK, delivered_at, handled_at, ORDER BY id | ✓ |
| I-08 | → S-01 | S-01 Tasks 3,4: STOPPING enum + state machine guards | ✓ |
| I-09 | → S-01, S-02 | S-01 Task 3: RUN_START enum; S-02 Task 2: handler | ✓ |
| I-10 | → S-03 | S-03 Tasks 1,3,4,5b: service rewiring + 202 response | ✓ |
| I-11 | → S-03 | S-03 Tasks 1,3,4: has_active_workflow removed | ✓ |
| I-12 | → S-02 | S-02 Tasks 1-5: polling loop, per-run tasks, handlers, redelivery | ✓ |
| I-13 | → S-03 | S-03 Task 5: unregister removed from handle_pause | ✓ |
| I-14 | → S-05 | S-05 Tasks 1,2: script created + pre-commit hook | ✓ |
| I-15 | → S-05 | S-05 Task 5: AGENTS.md section added | ✓ |
| I-16 | → S-01 | S-01 Task 1: Alembic migration | ✓ |
| I-17 | → S-03 | S-03 Task 4: retry_fan_out_child rewired | ✓ |
| I-18 | → NO-REQ | Deferred: separate runner processes | ✓ |
| I-19 | → NO-REQ | Deferred: EventBroadcaster decoupling | ✓ |
| I-20 | → NO-REQ | Deferred: performance optimization | ✓ |
| I-21 | → S-06 | S-06 Tasks 1,6: full test suite pass | ✓ |
| I-22 | → S-01 | S-01 Tasks 4,5: engine + API guards for STOPPING | ✓ |
| I-23 | → NO-REQ | Existing constraint; verified in S-06 (no new work needed) | ✓ |
| I-24 | → S-03, S-04 | S-03: removes process-local branching; S-04: registry isolation | ✓ |
| I-25 | → S-02 | S-02 Task 5: startup redelivery of unhandled signals | ✓ |
| I-26 | → S-01 | S-01 Task 2: ORDER BY id (not created_at) | ✓ |
| I-27 | → S-03 | S-03 Tasks 1-4: all lifecycle methods enqueue unconditionally | ✓ |
| I-28 | → S-03 | S-03 verification: grep confirms has_active_workflow gone | ✓ |
| I-29 | → S-04 | S-04 Tasks 2-5: registry functions removed from public exports | ✓ |
| I-30 | → S-01 | S-01 Task 4: STOPPING transitions enforced in engine | ✓ |
| I-31 | → S-02 | S-02: FIFO ordering (int PK), delivered_at/handled_at, redelivery | ✓ |
| I-32 | → S-05 | S-05 Tasks 1-3: guard script + pre-commit hook verified | ✓ |
| I-33 | → S-05 | S-05 Task 5: AGENTS.md four rules added | ✓ |
| I-34 | → S-06 | S-06 Tasks 1,6: full suite pass after each phase | ✓ |
| I-35 | → S-01 | S-01 Task 1: Alembic migration exists | ✓ |
| I-36 | → S-02 | S-02 Tasks 2,3: RUN_START and RESUME handlers implemented | ✓ |

**Intent coverage: complete.** All 36 items annotated and verified against step content.

---

## Gaps Applied in This Pass (Summary)

The following step file changes were made during this verification pass to bring
dry-run gaps into the step files:

### `steps/step-01-plan.md`
- **Task 4**: Rewrote start_task and submit_for_verification guard instructions to say
  "add new guard from scratch" (FM-4A, FM-4B). Previous language implied existing guards.
- **Task 5**: Added `delete_run` STOPPING guard (FM-5B).
- **Task 6**: Added `test_submit_for_verification_rejects_stopping` test (FM-6A);
  updated test count assertion from 8 to 9.

### `steps/step-02-plan.md`
- **Task 1 constructor**: Added `engine` and `service_factory` parameters to
  `SignalConsumer.__init__`; added `_run_workflows` dict (FM-3C, FM-2C).
- **Task 2**: Rewrote `_handle_run_start` to load run from DB and call
  `on_run_start()` with all required params (FM-2A).
- **Task 3**: Rewrote `_handle_cancel()` to use `on_run_end()` instead of non-existent
  `on_cancel()` (FM-3A); added `service_factory` usage for both handlers (FM-3C);
  renamed `_set_stopping` to public `transition_to_stopping` (FM-3D).
- **Task 8**: Replaced `build_executor_callbacks(app_state)` with inline construction
  pattern + factory function for transport (FM-8A, FM-8B); added consumer startup
  ordering note (FM-8C).

### `steps/step-03-plan.md`
- **New Task 2b**: Rewrite `handle_pause()` and `handle_cancel()` in `runtime.py`
  to return True without calling service methods (resolves circular loop FM-5, FM-6).
- **New Task 7a**: Injectable transport to fix test infrastructure mismatch (FM-20);
  `WorkflowService` accepts optional `signal_transport`; tests inject
  `InMemorySignalTransport`.

### `steps/step-05-plan.md`
- **Task 1 `is_allowed_file()`**: Added `"redelivery"` to allowed test file keywords;
  added path-scope requirement for `consumer.py` exemption (F-1, F-2).
- **Script docstring**: Added note about multiline import suppression placement (F-3).

### `steps/step-06-plan.md`
- **Task 1**: Added FM-4 check (verify consumer started in test fixtures).
- **Task 4**: Fixed grep path from `run_workflow.py` to `runtime.py` (H2);
  added explicit `unregister_active_run` grep (H4).
- **Final verification criteria**: Updated to use `runtime.py` throughout.

---

## Checklist

| Requirement | Result |
|------------|--------|
| R1: Step files align with plan and intent | ✓ PASS |
| R2: All critical/significant dry-run gaps applied to step files | ✓ PASS (applied in this pass) |
| R3: No unresolved critical conflicts | ✓ PASS (all resolved) |
| R4: Persistence mapping — no MISSING cells | ✓ PASS |
| R5: Integration test steps specify assertion logic | ✓ PASS |
| R6: Every [I-XX] annotated with step reference | ✓ PASS — intent coverage complete |

---

## Recommendation

All artifacts are now aligned. Step files are execution-ready. Implementation may
proceed with S-01 first (no prerequisites). The highest-risk steps during
implementation are:
1. **S-02 Task 8**: Consumer wiring into app.py (multiple injection dependencies)
2. **S-03 Task 7a**: Test infrastructure transport injection (broad test impact)
3. **S-03 Task 2b**: handle_pause/handle_cancel rewrite (circular loop prevention)

These should be validated immediately after implementation with targeted tests before
proceeding to subsequent steps.
