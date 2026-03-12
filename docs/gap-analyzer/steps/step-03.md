# Step 3: Executor + Prompts

Connect the executor to the engine lifecycle so verifier agents are actually spawned. Implements the step verifier prompt generator and wires the executor to detect when step verification should run, spawn the verifier agent, parse its JSON output, and call the engine lifecycle methods.

## Intent Verification
**Original Intent**: Complete the runtime wiring so a configured `step_verifier` actually runs when all step tasks reach terminal state (see `docs/gap-analyzer/intent.md`).
**Functionality to Produce**:
- `build_step_verifier_prompt(step_config, step_state, auto_verify_results)` returns a structured prompt string with task outcomes and required JSON output schema
- Executor detects all-tasks-terminal + `step_verifier` configured → calls `start_step_verification`, runs auto-verify, builds prompt, spawns agent, parses JSON, calls `complete_step_verification`
- JSON parse / validation failure → `fail`-verdict `GapReport` with descriptive `assessment`; raw output logged
- Fan-out parent step path unaffected

**Final Verification Criteria**:
- `uv run pytest tests/unit/ -v` — no regressions from executor changes
- Manual: verifier prompt contains all required sections (task outcomes, JSON schema block)
- Manual: JSON parse error produces `fail`-verdict `GapReport`

---

## Task 1: Add build_step_verifier_prompt to prompts.py

**Description**: Add `build_step_verifier_prompt(step_config, step_state, auto_verify_results)` to `src/orchestrator/workflow/prompts.py`. Returns a multi-section prompt string.

**Implementation Plan (Do These Steps)**
- [ ] Add `build_step_verifier_prompt(step_config: StepConfig, step_state: StepState, auto_verify_results: list[AutoVerifyResult]) -> str` to `src/orchestrator/workflow/prompts.py`
- [ ] Section 1 — user-supplied prompt: `{step_config.step_verifier.prompt}`
- [ ] Section 2 — "## Step Context": step title/id, current iteration, max iterations
- [ ] Section 3 — "## Task Outcomes": for each task in `step_state.tasks`: status, last attempt outcome, grades, auto-verify results
- [ ] Section 4 — "## Step Auto-Verify Results": render `auto_verify_results` items if present
- [ ] Section 5 — "## Required Output": instruction to respond with JSON only; include schema: `{"assessment": "...", "verdict": "pass"|"retry"|"fix"|"fail", "actions": [...]}`
- [ ] Write a unit test in `tests/unit/test_gap_analyzer_prompts.py` confirming all sections present in output

**Dependencies**
- [ ] Step 1 complete: `StepVerifierConfig`, `GapReport`, `StepState` all defined.

**References**
- `docs/gap-analyzer/architecture.md` — prompt template specification
- `docs/gap-analyzer/step-03-plan.md` — full functional contract

**Constraints**
- The "## Required Output" section must instruct the agent to respond with JSON only — no markdown fences, no preamble.
- Function must handle `auto_verify_results=[]` gracefully (omit section or show "None").

**Functionality (Expected Outcomes)**
- [ ] `build_step_verifier_prompt(...)` returns a non-empty string with all five sections
- [ ] Output includes `"verdict": "pass"|"retry"|"fix"|"fail"` in the JSON schema block

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_gap_analyzer_prompts.py -v` — passes
- [ ] Manual inspection: call function with sample data, confirm section headers present

---

## Task 2: Wire Executor to Step Verification Loop

**Description**: Modify `src/orchestrator/runners/executor.py` to detect when all tasks in a step have reached terminal state and `step_verifier` is configured, then drive the full verification flow.

**Implementation Plan (Do These Steps)**
- [ ] Locate the inner task execution loop in `executor.py` where step completion is checked
- [ ] After all tasks in a step reach terminal state, add check: `if step_config.step_verifier is not None and not is_fanout_parent_step(step):`
- [ ] Inside that block:
  1. Call `await engine.start_step_verification(run_id, step.id)`
  2. Run `step_verifier.auto_verify` items via existing `LocalAutoVerifyRunner` (if configured)
  3. Build prompt via `build_step_verifier_prompt(step_config, step_state, auto_verify_results)`
  4. Spawn verifier agent with prompt (use same agent runner as tasks in step)
  5. Parse agent output: `json.loads(agent_output)` in try/except
  6. On parse success: validate against `GapReport` schema
  7. On parse/validation error: construct `GapReport(verdict=StepVerdict.FAIL, assessment=f"Parse error: {details}")` and log raw output
  8. Call `await engine.complete_step_verification(run_id, step.id, gap_report)`
- [ ] Confirm the check is inside the step execution loop so newly-PENDING tasks (from `retry_task`) are picked up automatically

**Dependencies**
- [ ] Task 1 complete: `build_step_verifier_prompt` available.
- [ ] Step 2 complete: `start_step_verification` and `complete_step_verification` on engine working and tested.

**References**
- `docs/gap-analyzer/architecture.md` — executor pseudocode and interaction diagram
- `docs/gap-analyzer/clarifications.md` — fan-out path must not be touched; verifier uses same agent runner as step tasks
- `docs/gap-analyzer/step-03-plan.md` — full task list

**Constraints**
- Must not modify the fan-out parent step execution path.
- JSON parse error: log raw output at WARNING level before constructing fail-verdict `GapReport`.
- The step verification check must be inside the loop, not after it exits.

**Functionality (Expected Outcomes)**
- [ ] Executor calls `start_step_verification` and `complete_step_verification` when `step_verifier` is configured
- [ ] JSON parse error path produces a `fail`-verdict `GapReport` with `assessment` describing the error
- [ ] Raw agent output logged when parse fails

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/ -v` — no regressions from executor changes
- [ ] Manual confirmation: fan-out parent step path code section is unmodified
- [ ] Manual confirmation: JSON parse error path logs raw output and constructs fail-verdict report
