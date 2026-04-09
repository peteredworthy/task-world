# Execution Plans for Token-Reduction Experiments

This directory documents how to actually run the experiments described in the
synthesis report. Each experiment has an execution plan covering: prerequisites,
clone setup, routine modifications, termination, data collection, and repeatability.

## Design premises (verified)

- **Routine embedding**: The engine uses `run.routine_embedded` (a JSON dict on the
  run record) at runtime. It never re-reads routine files from disk once a run is
  created. This was verified across 11 code paths. See `/tmp/routine_embedding.txt`.
- **Clone isolation**: A cloned run with a patched `routine_embedded` runs its variant
  in full isolation. No disk files are needed per variant.
- **Step pre-marking**: Steps 0..N-1 can be marked complete with synthetic attempts
  before the run starts. The engine will begin at step N.
- **Source branch inheritance**: A cloned run's worktree starts from the reference
  run's git branch, so all committed artifacts from steps 0..N-1 are already in the
  worktree without needing to be regenerated.
- **Termination**: There is no `stop_after_step` config. An experiment harness must
  poll the run and either patch `run.status = COMPLETED` in the DB when the target
  step finishes, or rely on a natural pause at a `human_approval` gate.

---

## Tooling needed

### T1 — Generalized clone script: `scripts/clone_run_to_step.py`

A generalization of the existing `clone_run_from_s2.py` that supports:
- `--from-run <ref_id>`: reference run whose branch will be the source
- `--start-step <N>`: 0-based index of the first step to execute (steps 0..N-1 will
  be pre-marked completed)
- `--routine-patch <path>`: optional YAML file whose contents are deep-merged into
  `new_run.routine_embedded` before save
- `--stop-after-step <M>`: optional. **Truncates** `routine_embedded["steps"]` to
  the first M+1 entries (0-based). The engine then completes naturally when step M
  finishes because `check_run_completion()` sees all remaining steps done. Clean
  COMPLETED status, no polling, no sidecar.
- `--pause-after-step <M>`: alternative to `--stop-after-step`. Instead of
  truncating, inserts a new step at position M+1 containing a `human_approval` gate
  with no tasks. The engine reaches the gate, finds no approval recorded, and pauses
  (run.status stays ACTIVE, no tasks proceed). Use this when you want to resume the
  run later rather than formally complete it.
- `--start`: if set, immediately sets the run to ACTIVE; otherwise leaves it DRAFT

**Relationship to existing script**: `clone_run_from_s2.py` is a special case where
`--start-step 2` and no routine patch. The new script subsumes it. The old script
can remain as a convenience wrapper.

**Key implementation points**:
- Must import `WorkflowService` BEFORE any `orchestrator.db` imports to avoid the
  known circular import (`RunRepository → repositories.py → orchestrator.workflow →
  service.py → RunRepository`).
- Must load routine from disk via `discover_routines()` by the reference run's
  `routine_id`, NOT from `ref_run.routine_embedded` (the embedded snapshot may be
  stale; we want current disk + patch).
- After creating the new run and before `repo.save()`, apply the deep merge of the
  patch YAML into `new_run.routine_embedded`.
- Pre-mark steps[0..N-1] with synthetic `Attempt` records (outcome="passed").
- Set `new_run.current_step_index = N`.
- Set `new_run.source_branch = f"orchestrator/run-{ref_run_id}"`.
- If `--stop-after-step M`: slice `new_run.routine_embedded["steps"]` to
  `[:M+1]`, and also truncate `new_run.steps` to the same length so the state
  shape matches. The engine's `check_run_completion()` will set
  `run.status = COMPLETED` automatically when step M finishes — no polling.
- If `--pause-after-step M`: append a synthetic step at position M+1 to both
  `routine_embedded["steps"]` and `new_run.steps`. The synthetic step has an
  empty task list and a `gate: {type: human_approval, approval_prompt: "Experiment
  endpoint"}`. The engine pauses at the gate; `run.status` remains ACTIVE.

### T2 — Retrospective toolkit: `scripts/retrospectives/`

A directory of scripts, one per retrospective:
- `r0_preflight.py` — data existence checks
- `r1_v5_attribution.py` — rate V5 sub-agents against V7 discovery doc
- `r2_hot_file_overlap.py` — turn-delta parsing for V7 downstream sub-agents
- `r3_pytest_failure_census.py` — grep action logs across runs for pre-commit pytest failures
- `r4_cross_child_census.py` — walk git logs of fan-out run branches

Each script writes its output to `docs/experiments/retrospectives/` for versioning.

---

## Per-experiment execution plans

### R0 preflight — Data existence checks

**Script**: `scripts/retrospectives/r0_preflight.py`

**Inputs**: none
**Outputs**: `docs/experiments/retrospectives/r0_preflight.json` with:
```json
{
  "usage_is_cumulative": true,
  "runs_with_action_log": [{"run_id": "...", "attempt_count": N}, ...],
  "runs_with_surviving_branches": [{"run_id": "...", "branch": "..."}, ...],
  "gates": {
    "r3_can_run": true/false,
    "r4_can_run": true/false
  }
}
```

**Steps**:
1. Load one V7 sub-agent jsonl and walk consecutive assistant turns. Assert
   `cache_read_input_tokens` is monotonically non-decreasing. Record result.
2. Query DB: runs with at least 10 attempts where action_log is non-null.
3. Run `git branch -a | grep 'orchestrator/run-'` and cross-ref with DB run IDs.
4. Compute gates:
   - `r3_can_run`: ≥ 3 runs with ≥ 10 action_log attempts each
   - `r4_can_run`: ≥ 3 runs with fan_out tasks whose branches survive

**Token cost**: 0

**Run duration**: < 30 seconds

---

### R1 — V5 sub-agent attribution

**Script**: `scripts/retrospectives/r1_v5_attribution.py`

**Prerequisites**:
1. V7 discovery doc exists on disk at the V7 worktree (r64). Extract its file list
   into `r1_v7_discovery_files.json`.
2. Coding manual written to `docs/experiments/retrospectives/r1_coding_manual.md`
   with 3–5 worked examples per bucket (YES/NO/UNCERTAIN) — MUST be written before
   rating begins.

**Rating protocol**:
1. Dispatch TWO independent sub-agents (Explore type) with identical prompts containing
   the coding manual and the list of 17 V5 sub-agent session paths.
2. Each rater independently classifies all 17 sessions and writes `r1_ratings_A.json`
   / `r1_ratings_B.json`.
3. Script computes Cohen's kappa. If κ < 0.6, refine manual (add edge-case examples)
   and re-rate.
4. Script computes final tally: X_YES / X_UNCERTAIN / X_NO.
5. Script subtracts V7 S3 T-02 discovery task cost from gross savings to produce net
   attribution.

**Output**: `docs/experiments/retrospectives/r1_attribution.md` with:
- Cohen's kappa
- Per-session YES/NO/UNCERTAIN with file-set comparison
- Gross savings estimate (tokens from YES sub-agents)
- Net attribution (gross minus V7 discovery task cost)
- Confidence interval from the UNCERTAIN bucket

**Token cost**: ~1M if sub-agent-rated (two raters × 17 classifications × ~30K tokens
each). 0 if human-rated.

**Run duration**: 1 hour sub-agent, 2 hours human.

---

### R2 — Hot-file overlap with turn-delta parsing

**Script**: `scripts/retrospectives/r2_hot_file_overlap.py`

**Prerequisites**: R0 confirms cumulative-usage parsing is required.

**Steps**:
1. Load V7's 6 downstream sub-agent jsonls (from V7 DB action_log sub_agents field).
2. For each sub-agent, walk assistant turns in order. Compute `delta_cr[n] =
   cr[n] - cr[n-1]`.
3. For turns with exactly one Read tool_use, attribute delta to that file. For other
   turns, accumulate to UNATTRIBUTED.
4. Intersect the read file set with S3 discovery's file set.
5. Compute: attributable overlap fraction, attributable overlap cache_read,
   UNATTRIBUTED fraction.
6. Pre-compute E3 arithmetic: top-N hot file sizes, projected prompt inflation under
   E3a and E3b, savings ceiling.
7. Report gate status for E3.

**Output**: `docs/experiments/retrospectives/r2_hot_files.json` + markdown summary.

**Token cost**: 0

**Run duration**: < 1 minute

---

### R3 — Pre-commit failure census

**Script**: `scripts/retrospectives/r3_pytest_failure_census.py`

**Prerequisites**: R0.2 shows ≥ 3 runs with action_log data.

**Behavior**:
1. Query the DB for failed attempts across all runs with action_log.
2. For each failed attempt, scan `action_log.entries` for bash tool_use entries.
3. Flag entries where `command` matches `/\bcommit\b/` or `/pre-commit/`.
4. Inspect subsequent tool_result for keywords: `pytest`, `Failed`, `hook`, `exit code`.
5. Classify and tally per run.
6. Report gate for E2.

**If preflight fails**: Run produces V7-only report labeled "V7 failure inventory,
N=1 run; no gate for E2".

**Output**: `docs/experiments/retrospectives/r3_failure_census.md`

**Token cost**: 0

---

### R4 — Cross-child commit census

**Script**: `scripts/retrospectives/r4_cross_child_census.py`

**Prerequisites**: R0.3 shows ≥ 3 fan-out runs with surviving branches.

**Behavior**:
1. For each fan-out run with a surviving branch, run `git log --format='%H %aN %s'
   --stat` on the branch.
2. For each commit, match its changed files against the run's fan_out_index output
   patterns.
3. Count cross-contaminated commits per run.
4. Compute mean rate.

**If preflight fails**: R4 is dropped; E4 cannot be gated.

**Output**: `docs/experiments/retrospectives/r4_cross_child.md`

**Token cost**: 0

---

### E1 — Retry feedback injection (always runs)

**Prerequisites**:
1. T1 (`clone_run_to_step.py`) exists and works.
2. Code branch for `executor.py` with retry feedback injection exists — this is a
   real code change: in `_execute_fan_out_child`, for `attempt_num ≥ 2`, load the
   previous attempt from DB and populate `child_feedback` from its `error` field
   (and optionally `auto_verify_results`). Also write a second variant of executor.py
   that reads `.hook-diagnostic.log` from the worktree root and includes its contents.

**Experimental setup**:

Three arms, run sequentially from the same reference (V7):

**Arm A (control)**: clone V7 at step 3. No executor changes. Inject the obfuscated
pre-commit hook.

```bash
# 1. Prepare pre-commit hook file on the V7 source branch (one-time)
#    Write to .git/hooks/pre-commit in a SEPARATE branch, committed once:
#    #!/bin/sh
#    if [ ! -f .sentinel-present ]; then
#        echo "HOOK FAILED — see .hook-diagnostic.log for details" >&2
#        exit 1
#    fi
#
# 2. Ensure .hook-diagnostic.log (gitignored) contains:
#    "Create file .sentinel-present in the repo root to pass this hook."
#
# 3. Clone
uv run scripts/clone_run_to_step.py \
    --from-run 4e5d94a0-d362-493e-87ed-d106016138e5 \
    --start-step 3 \
    --stop-after-step 3 \
    --start \
    --label "E1-arm-A-control"
```

**Arm B (experimental — feedback from error field)**: Same setup but on an executor
branch with retry feedback injection from `attempt.error`.

**Arm C (ablation — feedback is just a hint)**: Executor branch that injects
`"Check .hook-diagnostic.log if present"` as feedback regardless of actual failure.

**Data collection**:
- For each arm, read the S4 task's 4 fan-out children's action logs.
- For each child's retry attempt (att 2), list the first 3 tool_use entries.
- Classify each arm: did retry attempt touch `.sentinel-present` in its first 3 tools?
- Compute retry cache_read per arm.

**Termination**: Routine truncation — `routine_embedded["steps"]` is sliced to end at
S4, so the engine marks the run COMPLETED naturally when the last S4 task finishes.
No sidecar needed.

**Cost per arm**: ~2M cache_read. Total: ~6M.

**Repeatability**: Yes. The hook is deterministic. Any clone from the reference with
the hook applied will fail the first attempt identically.

---

### E2 — Pytest-skip quality regression (gated on R3)

**Prerequisites**:
1. R3 gate passes.
2. T1 exists.
3. Pre-commit config investigation: identify the exact pytest hook ID in
   `.pre-commit-config.yaml`. Something like `pytest-local` or `pytest`.

**Experimental setup**: ONE clone.

```bash
uv run scripts/clone_run_to_step.py \
    --from-run 4e5d94a0-d362-493e-87ed-d106016138e5 \
    --start-step 3 \
    --stop-after-step 4 \
    --start \
    --label "E2-pytest-skip"

# Before the clone starts, set SKIP env var on the worktree:
# echo 'SKIP=pytest-local' > worktrees/rNN/.env
# OR patch .pre-commit-config.yaml in the worktree to comment out pytest
```

**Data collection**:
- V7's S4 verifier rubric grades for each step file (from V7 DB, steps[3].tasks[*].attempts[*].grade_snapshot).
- E2's S4 verifier rubric grades for each step file (same query on the E2 clone).
- Diff grade-by-grade.

**Success**: grade parity on all rubric items.
**Failure**: any step file drops ≥ 1 grade level.

**Termination**: Routine truncation at S4 (the verifier phase is part of S4's tasks
and runs before the step is marked complete, so truncating after S4 captures it).

**Cost**: ~4M.

**Repeatability**: Yes. Deterministic skip.

---

### E3 — Two-variant doc placement (gated on R2)

**Prerequisites**:
1. R2 gate passes (hot-file overlap > 50% AND savings ceiling > 2× inflation cost).
2. T1 exists.
3. Hot-file list from R2 available.

**Experimental setup**: Two clones.

```bash
# E3a: expand the discovery doc content, keep it in shared_context
uv run scripts/clone_run_to_step.py \
    --from-run 4e5d94a0-d362-493e-87ed-d106016138e5 \
    --start-step 3 \
    --stop-after-step 5 \
    --start \
    --label "E3a-expanded-shared-context" \
    --post-clone-hook "scripts/experiments/e3a_expand_discovery.py"

# E3b: move expanded doc into per_item_prompt via routine patch
uv run scripts/clone_run_to_step.py \
    --from-run 4e5d94a0-d362-493e-87ed-d106016138e5 \
    --start-step 3 \
    --stop-after-step 5 \
    --start \
    --label "E3b-inline-prompt" \
    --routine-patch scripts/experiments/e3b_patch.yaml
```

The `post-clone-hook` is a script that runs after the clone is created but before
the run is started. For E3a it appends hot-file contents to the worktree's
`codebase-discovery.md`. For E3b the routine patch modifies the S4 and S5
`per_item_prompt` to inline the hot-file contents at the top.

**Data collection**:
- Per arm, total (parent + sub-agent) cache_read for S4 and S5.
- Per arm, sub-agent count and their file read lists.
- Compare against V7 control (from DB).

**Success**: Any arm's total cache_read < 75% of V7 control.

**Termination**: Routine truncation at S5.

**Cost**: ~22M (two runs × ~11M).

**Repeatability**: Clones are deterministic given same source branch and same patch.
Model-side variance remains.

---

### E0 — TMPDIR hotfix (run first, cheapest)

**Prerequisites**: T1 (`clone_run_to_step.py`).

**Code change** (literally one line):

In `src/orchestrator/git/worktree.py::_write_sandbox_settings`, change the `allowWrite`
list around line 141 from:
```python
"allowWrite": [
    wt_abs,
    "/tmp",
],
```
to:
```python
"allowWrite": [
    wt_abs,
    "/tmp",
    os.environ.get("TMPDIR", "/tmp"),
],
```
(add `import os` at the top of the file if not already present.)

**Execution**:
```bash
uv run scripts/clone_run_to_step.py \
    --from-run 4e5d94a0-d362-493e-87ed-d106016138e5 \
    --start-step 3 \
    --stop-after-step 3 \
    --start \
    --label "E0-tmpdir-hotfix"
```

**Data collection**:
- Count of failed attempts in S4 (expect 0; V7 baseline was 3/7).
- Total S4 cache_read (expect <3M; V7 baseline was 6.72M).
- Grep the fan-out children's action logs for any bash output mentioning `sandbox`,
  `permission`, or `Operation not permitted`. None should remain.

**Success**: 0 failures, <3M total. Run E0 before E1 and before any of the architectural
experiments — if it succeeds, C4's cost contribution is eliminated and the program
budget drops significantly.

**Failure**: Failures persist. This means either the mktemp interpretation was wrong or
there's a second failure mode. Continue to E6 for the deeper fix.

**Cost**: ~3M cache_read, one run.

---

### E6 — Sandboxed fan-out + merge step (architectural; only if E0 insufficient)

**Prerequisites**:
1. T1 (`clone_run_to_step.py`) exists.
2. E0 has been run; if it fixed the problem, E6 is optional. Run E6 only if deeper
   isolation is needed (e.g., to eliminate worktree races C5) or if E0 did not
   resolve the failure mode.
3. **Code change** (~30–50 lines in existing files, no new schema):
   - `src/orchestrator/git/worktree.py::_write_sandbox_settings` — refactor to accept
     an optional `allow_write_override: list[str] | None` parameter. When provided,
     use it instead of the default `[wt_abs, "/tmp"]`.
   - `src/orchestrator/git/worktree.py` — add a helper or context manager
     `narrow_sandbox_for_fanout(worktree_path, output_dir)` that snapshots the existing
     `.claude/settings.local.json`, writes a narrowed version, and provides a restore
     method.
   - `src/orchestrator/runners/executor.py` — in the fan-out entry point (around line
     960, before `run_child` dispatch), call the narrowing helper. After the gather
     completes, restore. Handle the restore in a finally block so a crash doesn't leave
     the worktree with narrowed permissions.
   - Worktree re-entry path (startup auto-resume) — unconditionally reset the sandbox
     settings file to the permissive default on re-entry to recover from crashes.
4. Routine patch at `scripts/experiments/e6_routine_patch.yaml`:
   - S4 T-01 `output_pattern` → `.orchestrator/fanout/{{run_id}}/s4/{{item_stem}}.md`
     (existing field, different value only)
   - `per_item_prompt` stays unchanged — the sandbox physically prevents writes to
     `docs/` and to `.git/`, so there's no need to instruct the agent.
   - `auto_verify` tests the new path: `test -f {{output_path}}`.
   - New S4 T-02 sequential task "Publish step files" that copies artifacts from the
     sandbox into `docs/{{feature}}/steps/` and performs one batched `git add && git commit`
     with a `--no-verify` fallback. This task runs under the restored permissive sandbox.
5. No changes to `factory.py`. No changes to `--dangerously-skip-permissions`. No new
   schema fields. No new config keys.
6. Ideally E1's executor patch is merged so the merge task's retries benefit from
   failure-context injection.

**Execution**:
```bash
uv run scripts/clone_run_to_step.py \
    --from-run 4e5d94a0-d362-493e-87ed-d106016138e5 \
    --start-step 3 \
    --stop-after-step 3 \
    --start \
    --label "E6-sandboxed-fanout" \
    --routine-patch scripts/experiments/e6_routine_patch.yaml
```

**Data collection**:
- Count of failed attempts across S4 T-01's 4 children (expect 0).
- Merge task attempt count (expect 1; at most 2 if pre-commit hook fires once).
- Per-attempt cache_read for children and merge task.
- Grand total vs V7 S4 (6.72M parent + 2.79M sub-agent = 9.51M).
- Inspect the worktree after the run: the sandbox directory should be clean
  (git rm'd or gitignored), final files present in `docs/{feature}/steps/`, a
  single commit on the branch covering all 4 step files.

**Success criteria**:
- 0 of 4 children fail.
- Merge task succeeds in ≤ 2 attempts.
- Total S4 cache_read ≤ 5.7M (40% reduction vs V7).
- Step file quality (verifier rubric) matches V7 baseline.

**Failure criteria**:
- Any child fails (means the sandbox pattern doesn't actually isolate the children
  from the failure mode — investigate whether the child is trying to commit despite
  the prompt).
- Merge task costs more than the savings (means hook failures are the real driver
  and contain to one agent doesn't help — points toward E2-style hook surgery).

**Dependencies noted**:
- Best combined with E1 (retry feedback) already landed, so the merge task's retries
  aren't blind.
- Independent of R2/R3 retrospectives — E6 targets a different cost axis than E3.

**Cost**: ~5M cache_read. One run for initial signal, second run to confirm.

---

### E7 — 3-phase remediation for regular tasks (architectural)

**Prerequisites**:
1. Code branch implementing minimal 3-phase support:
   - Add `TaskStatus.REMEDIATING` to `src/orchestrator/config/enums.py`
   - Update `VALID_TRANSITIONS` in `src/orchestrator/workflow/engine/transitions.py`
     to allow VERIFYING → REMEDIATING and REMEDIATING → VERIFYING
   - Modify `transition_after_verification` (around line 343) to set status to
     REMEDIATING instead of BUILDING when `revision_needed`
   - Add `generate_remediation_prompt(task_config, task_state, grade_snapshot)` in
     `src/orchestrator/workflow/agent/prompts.py` that uses the structured format
     described in the synthesis report
   - Route REMEDIATING to the builder executor in
     `src/orchestrator/runners/executor.py::_execute_task`, calling the new prompt
     generator instead of `generate_builder_prompt`
2. A task that reliably fails verification on first attempt. Options:
   - Use an existing run from the DB that had a revision loop (if R0.2 surfaces any)
   - Create a minimal synthetic routine where the verifier deliberately grades F on
     one item based on a missing section in the artifact, and the builder's first
     attempt is prompted to omit that section

**Execution**:
```bash
# Arm A — control (existing revision path; no code changes)
uv run scripts/clone_run_to_step.py \
    --from-run <ref_run_id> \
    --start-step <step_with_task_to_test> \
    --stop-after-step <same_step> \
    --start \
    --label "E7-arm-A-control"

# Arm B — experimental (on the 3-phase code branch)
git checkout experiments/3-phase-remediation
uv run scripts/clone_run_to_step.py \
    --from-run <ref_run_id> \
    --start-step <step_with_task_to_test> \
    --stop-after-step <same_step> \
    --start \
    --label "E7-arm-B-experimental"
```

**Data collection**:
- For each arm's target task, inspect the DB:
  - `task_state.attempts[0].outcome` (should be `revision_needed` in both arms)
  - `task_state.attempts[1].outcome` (the remediation attempt)
  - `task_state.attempts[1].action_log.total_cache_read_tokens`
  - `task_state.attempts[1].action_log.total_input_tokens + total_output_tokens`
  - Tool call distribution in attempt 1 (from action_log.entries)
  - Files modified in attempt 1 (cross-reference with the failing rubric items)

**Success criteria** (any ONE of):
- Arm B passes attempt 2 where Arm A fails
- Both arms pass attempt 2, but Arm B uses ≥ 30% fewer cache_read tokens
- Arm B modifies strictly fewer files than Arm A (scope containment)

**Failure criteria**:
- Equivalent outcomes on all metrics — structured prompt adds no signal

**Cost**: ~2M cache_read (two single-task runs, ~1M each).

**Caveat**: This experiment validates the structured-feedback hypothesis for regular
tasks only. Extending to fan-out children is a separate, larger change (per the effort
estimates in the synthesis report). If E7 succeeds, a follow-up would extend the same
pattern to fan-out children.

---

## Reproducibility checklist

For every experiment:
- [ ] Reference run ID is documented in the execution log
- [ ] Routine patch file (if any) is version-controlled under `scripts/experiments/`
- [ ] Pre-clone worktree modifications (hooks, config) are scripted, not manual
- [ ] The experiment's new run ID is recorded in `docs/experiments/retrospectives/run_log.md`
- [ ] Data collection script runs automatically when the stop condition is met
- [ ] Outputs are written to `docs/experiments/results/{experiment_id}/` with
  timestamps

## Concurrency notes

Multiple experiments can run in parallel — each clone gets a unique worktree and
unique run ID. SQLite WAL handles the DB contention up to ~50 concurrent runs.
Avoid running experiments while the main server is processing production runs
if token budget is constrained.
