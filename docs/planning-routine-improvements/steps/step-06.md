# Step 6: Validation and Live Test (M4c)

Validate the complete optimized routine end-to-end: schema validation, unit tests, integration tests, and a live test run using Claude CLI. Confirm cost and time savings against the baseline ($18.28, 70 min, 703 tool calls). Ensure the original routine is unchanged.

## Intent Verification
**Original Intent**: Completion criteria #8 (schema validation), #10 (live test), #13 (original unchanged) from intent.md
**Functionality to Produce**:
- Schema validation passes for the optimized routine
- All unit and integration tests pass
- Live test run completes with measurably lower cost
- Original routine confirmed unchanged
**Final Verification Criteria**:
- `uv run orchestrator --json routines validate` exits 0
- `git diff HEAD -- routines/idea-to-plan/routine.yaml` shows no changes
- All test suites pass
- Live test metrics documented

---

## Task 1: Run Schema Validation and Test Suites

**Description**: Validate the optimized routine against the schema and run the full test suite to ensure no regressions from engine enhancements.

**Implementation Plan (Do These Steps)**

This task runs validation commands and fixes any issues discovered. No new code is written — this is purely verification and bug-fixing.

- [ ] Run schema validation:
  ```bash
  uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml
  ```
- [ ] If validation fails, fix the YAML issues and re-run until it passes
- [ ] Verify original routine unchanged:
  ```bash
  git diff HEAD -- routines/idea-to-plan/routine.yaml
  ```
- [ ] Run unit tests:
  ```bash
  uv run pytest tests/unit/ -x -q
  ```
- [ ] Run integration tests:
  ```bash
  uv run pytest tests/integration/ -x -q --ignore=tests/integration/test_openhands*.py
  ```
- [ ] If any tests fail due to engine changes (Step 04), fix the issues in `templates.py` or `executor.py` and re-run

**Dependencies**
- [ ] Steps 01-05 completed — all routine YAML changes and engine enhancements applied

**References**
- Step plan: `docs/planning-routine-improvements/step-06-plan.md`
- Intent: `docs/planning-routine-improvements/intent.md` — completion criteria #8, #13
- Architecture: `docs/planning-routine-improvements/architecture.md` — testing strategy

**Constraints**
- Do not modify the original routine at `routines/idea-to-plan/routine.yaml`
- Known test failures (openhands module not installed) should be excluded, not fixed

**Functionality (Expected Outcomes)**
- [ ] Schema validation passes with zero errors
- [ ] Original routine has zero diff from HEAD
- [ ] Unit tests all pass
- [ ] Integration tests all pass (excluding known openhands failures)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml` exits 0
- [ ] `git diff HEAD -- routines/idea-to-plan/routine.yaml` produces no output
- [ ] `uv run pytest tests/unit/ -x -q` exits 0
- [ ] `uv run pytest tests/integration/ -x -q --ignore=tests/integration/test_openhands*.py` exits 0

---

## Task 2: Execute Live Test Run

**Description**: Run the optimized routine end-to-end using Claude CLI on a small test idea. Collect metrics and compare to the baseline.

**Implementation Plan (Do These Steps)**

The live test validates that all optimizations work together in a real execution environment. Profile-to-model mappings must be configured on the agent runner before running.

- [ ] **Pre-flight environment checks** (run ALL before proceeding):
  ```bash
  # Check server is running
  curl -sf http://localhost:8000/health && echo "Server OK" || echo "FAIL: Server not running"
  # Check Claude CLI is available
  which claude && echo "CLI OK" || echo "FAIL: Claude CLI not found"
  # Check profile mappings are configured (query agents API)
  curl -sf http://localhost:8000/api/agents | python3 -c "import sys,json; data=json.load(sys.stdin); print('Agents:', len(data))" || echo "FAIL: Cannot query agents"
  ```
  If any check fails, fix the environment before proceeding. Do NOT attempt the live test without a running server.
- [ ] Ensure profile-to-model mappings are configured on the CLI_SUBPROCESS agent runner:
  - `architect` → `claude-opus-4-6`
  - `coder` → `claude-sonnet-4-6`
  - `summarizer` → `claude-haiku-4-5`
  If profile mappings are not set, configure them via the Agents page in the UI at `http://localhost:3000/agents` or via API: `PATCH http://localhost:8000/api/agents/{runner_type}/profile-defaults`
- [ ] Create a small test idea for the live run (2-3 step plan complexity)
- [ ] Execute the optimized routine:
  ```bash
  uv run orchestrator runs create --routine routines/idea-to-plan-optimized/routine.yaml --input feature=test-feature --input idea="<test idea>"
  ```
- [ ] Monitor the run to completion, noting:
  - Fan-out steps (S-04, S-05) spawn concurrent sub-agents
  - No LLM verifier spawns for S-07/T-01 or S-08/T-01
  - Agent metadata shows correct models per profile
- [ ] Collect metrics from the completed run:
  - Total cost
  - Wall-clock time
  - Total tool calls
  - Duplicate file reads
- [ ] Compare metrics to baseline and document results:

  | Metric | Baseline | Target | Actual | Pass Threshold |
  |--------|----------|--------|--------|----------------|
  | Cost | $18.28 | $5-7 | (measured) | < $12 (35% reduction minimum) |
  | Wall-clock | 70 min | 20-25 min | (measured) | < 50 min (30% reduction minimum) |
  | Tool calls | 703 | 250-300 | (measured) | < 500 (reduction indicates context injection working) |
  | Duplicate reads | 103 (41%) | 10-15 (5%) | (measured) | < 60 (significant reduction) |

  **Pass/fail criteria**: The live test PASSES if cost is below the pass threshold ($12). Other metrics are informational — they validate specific optimizations but don't block completion. If cost exceeds $12, diagnose which optimization isn't working:
  - Cost near baseline ($16+) → profile routing not working (check agent model metadata)
  - Tool calls near baseline (600+) → context injection not working (check context_from resolution)
  - Wall-clock near baseline (60+ min) → fan-out not working (check concurrent child execution)

- [ ] Verify all expected artifact files exist:
  - `docs/{feature}/intent.md`, `plan.md`, `architecture.md`, `clarifications.md`
  - `docs/{feature}/step-*-plan.md` (step plans)
  - `docs/{feature}/steps/step-*.md` (step files, from fan-out)
  - `docs/{feature}/dry-run/*-notes.md` (per-step notes, from fan-out)
  - `docs/{feature}/dry-run-notes.md` (merged)
  - `docs/{feature}/verification-report.md`
  - `docs/{feature}/plan-summary.md`
  - Routine YAML output
- [ ] If any step fails, diagnose and fix, then re-run

**Dependencies**
- [ ] Task 1 (validation and tests) must pass first
- [ ] Claude CLI must be configured and available
- [ ] Server must be running with engine enhancements deployed

**References**
- Step plan: `docs/planning-routine-improvements/step-06-plan.md`
- Intent: `docs/planning-routine-improvements/intent.md` — completion criterion #10
- Plan: `docs/planning-routine-improvements/plan.md` — testing strategy, live test
- Clarification Q5: Live test using Claude CLI (already configured)
- Baseline: run b46dbe62 metrics ($18.28, 70 min, 703 tool calls)

**Constraints**
- The live test requires active agent runners and configured profile mappings
- If profile mappings are not configured, tasks fall back to default model — cost savings won't be achieved but the run still completes
- The test idea should be small enough to complete in reasonable time but complex enough to exercise fan-out (2-3 steps)

**Functionality (Expected Outcomes)**
- [ ] Live test run completes all 8 steps successfully
- [ ] All expected artifact files exist in the output directory
- [ ] Fan-out steps (S-04, S-05) show concurrent child tasks in run detail (not sequential)
- [ ] S-07/T-01 and S-08/T-01 have NO verifier attempt (auto-verify only — check attempt count = 1, no verifier_prompt)
- [ ] Agent metadata on tasks shows correct model per profile (architect=opus, coder=sonnet, summarizer=haiku)
- [ ] Cost is below $12 pass threshold
- [ ] Metrics comparison documented with all 4 columns filled

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Live test run reaches "completed" status
- [ ] All expected artifact files exist (intent.md, plan.md, architecture.md, step plans, step files, dry-run notes, merged notes, verification report, summary, routine YAML)
- [ ] Cost from live run is documented and lower than $18.28
- [ ] Metrics comparison table is filled in with actual values
