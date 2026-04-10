# D5: Adversarial Gate Bypass Analysis (Static)

## Summary

This experiment traces the full task lifecycle gate-by-gate to determine
whether a non-performing agent (one that marks checklist items "done"
without writing code) can bypass the system and reach COMPLETED status.

**Key finding**: A non-performing agent CAN pass the checklist gate and
reach VERIFYING status trivially. Whether it then reaches COMPLETED depends
entirely on whether (a) auto-verify commands are configured AND correctly
detect the absence of work, and (b) an LLM verifier rubric is configured.
If neither is present, the task auto-completes with grade "A".

**Secondary finding from run data**: In run `8bf41c40`, auto-verify commands
using shell pipes (`pytest ... | tail -5`) reported `passed: true` despite
the output showing "5 failed" -- because the pipe exit code comes from
`tail` (always 0), not `pytest`. A validator (`_reject_pipes`) was later
added to `AutoVerifyItemConfig` to prevent this, but existing embedded
routines are unaffected since `routine_embedded` is a creation-time snapshot.

---

## Gate Checkpoint Analysis

### Gate 1: Checklist Gate (BUILDING -> VERIFYING)

**Source**: `src/orchestrator/workflow/gates.py:22` (`evaluate_checklist_gate`)
Called from `src/orchestrator/workflow/transitions.py:83` (`transition_to_verifying`)

**What is checked**:
- Each `ChecklistItem` with `priority=CRITICAL`:
  - Must be `status=DONE`, OR
  - `status=NOT_APPLICABLE/BLOCKED` WITH a non-empty `note` (justification)
  - If `status=OPEN` -> BLOCKING
  - If `NOT_APPLICABLE/BLOCKED` without note -> BLOCKING
- Items with `priority=EXPECTED`: same logic but produce warnings only
- Items with `priority=NICE`: informational only, never block

**Can a non-performing agent pass it?**
YES, trivially. The agent calls:
```
PATCH /api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}
  { "status": "done", "note": "Implemented as specified" }
```
for each requirement. The checklist gate checks ONLY the self-reported
status field. It does NOT verify that any files were created, modified,
or that tests pass. The gate is purely a self-attestation mechanism.

**What would stop it?**
Nothing at the checklist gate level. The gate trusts the agent's
self-report completely.

**Pre-gate auto-verify shortcut** (service.py lines 723-766):
Before the checklist gate runs, the service checks if auto-verify is
configured. If all `must` auto-verify items pass, it auto-marks any
remaining `OPEN` checklist items as `DONE`. This means that for tasks
WITH auto-verify, a legitimate agent does not even need to manually
mark items -- the auto-verify results do it. But this also means the
gate is redundant when auto-verify is present.

### Gate 2: Auto-Verify (Post-Submission, VERIFYING phase)

**Source**: `src/orchestrator/workflow/auto_verify.py` (runner)
Called from `src/orchestrator/workflow/service.py:790-942` (`submit_for_verification`)

**What is checked**:
- Each `AutoVerifyItemConfig` defines a shell command (`cmd`)
- Commands are run via `asyncio.create_subprocess_shell`
- Exit code 0 = passed, non-zero = failed
- Items with `must=True` cause the task to be sent back to BUILDING
  (revision) if they fail
- Items with `must=False` are recorded but do not block

**Can a non-performing agent pass it?**
DEPENDS on the auto-verify commands:
- If commands check for file existence, importability, or test passes:
  NO -- the agent wrote no code, so these checks fail
- If commands use shell pipes (historical bug): YES -- the pipe masks
  the real exit code
- If no auto-verify items are configured: N/A -- this gate is skipped
  entirely

**What happens when auto-verify fails?**
1. Results are stored in `attempt.auto_verify_results`
2. Failing `must` item IDs are recorded
3. Actionable feedback is stored in `attempt.verifier_comment`
4. Task transitions back to `BUILDING` (new attempt created)
5. If `current_attempt >= max_attempts`, triggers RECOVERY instead
6. If any command crashed (exception/signal), triggers RECOVERY
7. The task does NOT proceed to LLM verification -- auto-verify
   failure is handled entirely within the `submit_for_verification`
   method, before the verifier agent is spawned

**Critical**: Auto-verify runs AFTER the checklist gate, AFTER the
transition to VERIFYING. The sequence is:
```
1. Pre-gate auto-verify (auto-marks items if all pass)
2. Checklist gate evaluation (blocking if CRITICAL items OPEN)
3. State transition: BUILDING -> VERIFYING
4. Post-submission auto-verify (same commands, recorded + enforced)
5. If auto-verify fails: VERIFYING -> BUILDING (revision)
6. If auto-verify passes (or not configured): proceed to verifier
```

### Gate 3: Grade Evaluation (VERIFYING -> COMPLETED/BUILDING/FAILED)

**Source**: `src/orchestrator/workflow/grades.py` (`evaluate_grades`)
Called from `src/orchestrator/workflow/transitions.py:242` (`transition_after_verification`)

**What is checked**:
- CRITICAL items: grade must meet threshold (default "A")
- EXPECTED items: grade must meet threshold (default "B")
- Ungraded CRITICAL/EXPECTED items are treated as FAILING
- NICE items: may remain ungraded without affecting pass/fail
- If NO items have grades at all: auto-grade path triggers

**Auto-grade path** (transitions.py:278-286):
When no verifier has set any grades (no LLM rubric ran), the system
auto-grades:
- Items with `status=DONE` get grade "A"
- Items with `status=NOT_APPLICABLE` get grade "A"
- Items with `status=OPEN/BLOCKED` remain ungraded (treated as failing)

**Can a non-performing agent pass it?**
- WITH a verifier rubric: NO (assuming the verifier is competent).
  The LLM verifier is given the code diff, the rubric questions, and
  asked to grade each requirement. A non-performing agent produces no
  code changes, which the verifier should grade as "F".
- WITHOUT a verifier rubric: YES. If the agent marked all items as
  "done", the auto-grade path assigns them all grade "A", and the
  task completes successfully.

**What would stop it?**
Only an LLM verifier with a rubric that inspects actual work product.
The auto-grade path trusts the builder's self-reported checklist status.

---

## Traced Scenario: Non-Performing Agent

**Setup**: Agent starts task S-01/T-01 from routine `mcp-ops-c`.
Task has 3 CRITICAL requirements (R1, R2, R3), 2 auto-verify items
(both `must=True`), and a verifier rubric.

### Step-by-step trace:

**1. Agent marks R1, R2, R3 as "done" without writing any code**

Calls:
```
PATCH /api/runs/{run_id}/tasks/{task_id}/checklist/R1
  { "status": "done", "note": "Implemented" }
PATCH .../R2 { "status": "done" }
PATCH .../R3 { "status": "done" }
```

Service validates: task status must be BUILDING (not terminal/verifying).
No content validation. All three items now have `status=DONE`.

**2. Agent calls submit**

```
POST /api/runs/{run_id}/tasks/{task_id}/submit
```

**3. Pre-gate auto-verify runs** (service.py:738-766)

Since all checklist items are already DONE (no OPEN items), the
pre-gate auto-verify is SKIPPED (line 742 condition fails:
`any(item.status == ChecklistStatus.OPEN for item in task.checklist)`
is False).

**4. Checklist gate evaluates** (transitions.py:96)

All CRITICAL items are DONE. Gate PASSES.
State transitions: BUILDING -> VERIFYING.

**5. Post-submission auto-verify runs** (service.py:803-942)

Two `must=True` commands execute:
- `model_importable`: `uv run python -c "from orchestrator.config.models import MCPServerConfig; ..."`
  - Agent wrote no code, so `MCPServerConfig` does not exist
  - Exit code: non-zero (ImportError)
  - Result: `passed=False`
- `dual_transport_rejected`: similar import-based check
  - Result: `passed=False`

Both `must` items failed. The service:
1. Stores feedback in `attempt.verifier_comment`
2. Checks `current_attempt < max_attempts`
3. Transitions task back to BUILDING (new attempt created)
4. Returns `TransitionResult(success=True, new_status=BUILDING,
   error="Auto-verify must-items failed")`

**6. The verifier is NOT spawned**

Auto-verify failure short-circuits the flow. The task never reaches
the verifier agent. It goes back to BUILDING for revision.

**7. Repeated failure scenario**

If the agent continues marking items done without writing code:
- Each submit triggers auto-verify, which fails
- After `max_attempts` exhausted: triggers RECOVERY (not FAILED)
- Recovery agent gets detailed failure information
- If recovery also fails: run is paused

**8. Can the task reach COMPLETED?**

NOT with auto-verify configured. The `must=True` commands would
catch the absence of code. However, if the auto-verify commands were
poorly written (e.g., using shell pipes that mask exit codes), the
agent could pass auto-verify fraudulently and reach the LLM verifier.

If auto-verify were NOT configured: the LLM verifier rubric is the
last line of defense. The verifier sees the git diff (empty, since no
code was written) and the rubric questions. A competent verifier would
grade everything F.

If NEITHER auto-verify NOR verifier rubric is configured: the task
auto-completes. The auto-grade path sees all items marked DONE and
assigns grade A. Task reaches COMPLETED with zero actual work.

---

## Actual Data from Run 8bf41c40

### Overview
- Routine: `mcp-ops-c`
- 9 steps, 28 tasks total
- 24 tasks completed, 1 failed (S-08/T-01), 1 building, 3 pending
- Run status: paused

### Auto-Verify Events

**18 total `auto_verify_completed` events, all with `passed=true`.**

No auto-verify failures were recorded. However, inspection of the
actual command output reveals a significant finding:

**Task 946657c8 (S-08/T-01)**: Auto-verify command `full_suite_pass`
used `uv run pytest tests/ -x --timeout=30 -q 2>&1 | tail -5`. The
output clearly shows "5 failed, 445 passed" but the auto-verify
reported `passed=true` because the shell pipe exit code comes from
`tail` (always 0), not from `pytest`.

This is precisely the class of bug the `_reject_pipes` validator
(added later) was designed to prevent. The routine embedded in this
run predates the validator.

### Grade Failures

**Task 682ae9e0 (S-04/T-01)**: No auto-verify configured. First
attempt graded R1: F by LLM verifier. Revision triggered. Second
attempt passed. System worked as designed -- the LLM verifier caught
inadequate work.

**Task 946657c8 (S-08/T-01)**: 8 attempts, all grade failures.
Despite auto-verify reporting `passed=true` (pipe bug), the LLM
verifier consistently graded below threshold:
| Attempt | R1 Grade | R2 Grade |
|---------|----------|----------|
| 1       | B        | F        |
| 2       | D        | D        |
| 3       | C        | F        |
| 4       | B        | F        |
| 5       | D        | C        |
| 6       | B (pass) | F        |
| 7       | C (fail) | C        |
| 8       | (fail)   | C        |

The LLM verifier was the effective last line of defense here, catching
that the full test suite was NOT passing despite auto-verify reporting
success. After 8 attempts (max_attempts=8), the task reached FAILED.

### Checklist Gate Events

**37 total `checklist_gate_evaluated` events, all with `passed=true`.**

Zero checklist gate failures. The builder agents either:
1. Explicitly marked all items done before submitting, or
2. The pre-gate auto-verify auto-marked remaining items

### Tasks Where Auto-Verify Passed But Grades Failed

Cross-referencing the two event types:

| Task ID (short) | Auto-Verify | Grade Result | Implication |
|-----------------|-------------|--------------|-------------|
| 946657c8        | passed      | failed (8x)  | Pipe bug masked real failures; verifier caught it |

This is the ONLY case in the run where auto-verify and grades disagreed.
The verifier was correct -- the full test suite was failing.

---

## Vulnerability Assessment

### High Risk: Tasks without auto-verify AND without verifier rubric

If a task has only a checklist (no auto-verify, no rubric), the
lifecycle is:
```
BUILDING -> mark items done -> submit -> gate passes ->
VERIFYING -> complete_verification -> auto-grade (all A) -> COMPLETED
```
A non-performing agent completes with zero actual work.

### Medium Risk: Tasks with auto-verify but using pipes

The `_reject_pipes` validator prevents this for NEW routines, but
existing embedded routines with pipes continue to have false-positive
auto-verify results.

### Low Risk: Tasks with auto-verify AND verifier rubric

Both layers must be bypassed. The LLM verifier sees the actual diff
and can detect absence of work. However, the verifier is also an LLM
and can be fooled by adversarial commit messages or misleading notes.

### Minimal Risk: Tasks with well-written auto-verify (no pipes)

Direct exit code from test commands accurately reflects pass/fail.
A non-performing agent cannot bypass this.

---

## Recommendations

1. **Never allow tasks without at least one of**: auto-verify items
   (with `must=True`) or a verifier rubric. The checklist gate alone
   is insufficient.

2. **Retroactively validate embedded routines**: When loading
   `routine_embedded` for active runs, re-validate against current
   `AutoVerifyItemConfig` validators (including `_reject_pipes`).

3. **Add content-aware gates**: Consider a gate type that checks for
   non-empty git diffs or minimum file change counts before allowing
   submission.

4. **Audit the pre-gate auto-mark behavior**: The pre-gate auto-verify
   that auto-marks OPEN items as DONE (service.py:761-765) effectively
   bypasses the checklist gate for tasks WITH auto-verify. This is
   convenient but means the checklist gate is never the enforcement
   point -- auto-verify is.

5. **Fix the pipe bug in running routines**: For runs with embedded
   routines containing piped auto-verify commands, the system should
   either warn or refuse to trust the exit codes.
