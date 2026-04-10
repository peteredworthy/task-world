# Dry Run Simulation Notes

Simulated execution of all 15 steps (26 tasks) with gap analysis and failure mode hardening.

---

## Per-Step Simulation Results

### Step 1: Fix auto_verify timing (A1)

**Task 1.1: Reorder auto_verify execution in submit_for_verification**

- **Assumption:** auto_verify logic lives in `engine.py:submit_for_verification()`
- **GAP FOUND:** auto_verify execution actually lives in `service.py` (lines 738-826), not `engine.py`. The engine delegates to the service. The task instructions reference the wrong file.
- **Expected output:** auto_verify runs before checklist gate; `must: true` failures raise `GateBlockedError`
- **Blockers:** Agent may waste time searching `engine.py` for auto_verify code that isn't there
- **Mitigation:** Update task instructions to reference `service.py` and clarify the call chain: `engine.submit_for_verification()` -> `service.submit_task()` -> auto_verify execution

**Task 1.2: Integration test for auto_verify gate via API**

- **Assumption:** Test infrastructure supports creating runs with auto_verify config
- **Expected output:** Test exercising 409 response on failing `must: true` auto_verify
- **Blockers:** None — existing test patterns in `test_api_full_lifecycle.py` provide templates
- **Mitigation:** None needed

### Step 2: Require verification on every task (A2)

**Task 2.1: Add verification requirement validation to TaskConfig**

- **Assumption:** `TaskConfig` in `models.py` is straightforward to extend with `model_validator`
- **Expected output:** Validator warns/rejects tasks without auto_verify or verifier rubric
- **Blockers:** Need to understand what constitutes "verifier rubric" — is it `verifier` field? Need to check schema.
- **Mitigation:** Task should explicitly name the fields that count as verification: `auto_verify.items` non-empty OR `verifier` section present

**Task 2.2: Block auto-grade path for unverified tasks**

- **Assumption:** There's a clear "auto-grade" code path in `transitions.py`
- **Expected output:** Unverified tasks can't silently pass
- **Blockers:** Agent needs to understand the transition flow to find the right insertion point
- **Mitigation:** Add a pointer: "Look for the code path that auto-assigns grades when no verifier runs"

**Task 2.3: Integration test for strict validation**

- **Assumption:** Routine loading is testable through API
- **Expected output:** Validation error on undefended task in strict mode
- **Blockers:** None
- **Mitigation:** None needed

### Step 3: Pre-run test health check (A5)

**Task 3.1: Add test health check to executor**

- **Assumption:** Executor has a clear "before first attempt" hook point
- **Expected output:** Test command runs before first task; non-zero exit blocks start
- **Blockers:**
  - `.task-world/config.yaml` format not formally defined — agent must create/decide format
  - Running subprocess in executor context (worktree path, environment)
  - "First task attempt in a run" detection — need run-level state tracking
- **Mitigation:**
  - Define minimal config format in task instructions: `test_command: "uv run pytest --tb=no -q"` or `test_command: null`
  - Specify that the command runs in the worktree directory
  - Clarify: track via a `health_check_completed` flag on run state or check attempt count

**Task 3.2: Tests for pre-run health check**

- **Assumption:** Can create test projects with configurable test outcomes
- **Expected output:** Tests for all scenarios (fail, pass, opt-out, no config)
- **Blockers:** Test setup complexity — needs tmp directories with config files and test suites
- **Mitigation:** Use existing test fixtures (`tmp_dir`, `routine_repo`)

### Step 4: Verifier model pinning (A10)

**Task 4.1: Add verifier_model to Run state**

- **Assumption:** Run model in `state/models.py` is easy to extend
- **Expected output:** `verifier_model` field on Run, set at creation, used by executor
- **Blockers:**
  - Where does verifier model config currently live? Agent needs to trace this.
  - DB schema migration — adding field to existing table requires DB recreation per MEMORY.md
- **Mitigation:**
  - Add instruction: "Verifier model comes from agent config at run creation time"
  - Add instruction: "New field has `None` default, so existing DB rows are compatible (no migration needed)"

### Step 5: Trim prompt dead weight (A7)

**Task 5.1: Remove dead-weight sections from system prompt**

- **Assumption:** "Avoiding Loops" section is clearly delineated in `prompts.py`
- **Expected output:** Section removed; prompt still functional
- **Blockers:**
  - Other "dead weight" sections not explicitly named — only "Avoiding Loops" is called out
  - Existing tests may assert on prompt content that changes
- **Mitigation:**
  - Task should list ALL sections to remove, not just "Avoiding Loops"
  - Add instruction: "Update prompt test expectations to match new content"

### Step 6: Migrate agent-specific instructions (A8)

**Task 6.1: Move agent-specific instructions to agent runners**

- **Assumption:** Instructions are clearly agent-specific and can be cleanly separated
- **Expected output:** Each agent's `build_prompt()` includes its instructions; shared prompt is leaner
- **Blockers:**
  - `codex_server.py` uses `_build_prompt` (different method name) — not `build_prompt`
  - `openhands.py` and `claude_sdk.py` may not have `build_prompt()` methods at all
  - Need to identify which sections in `prompts.py` are agent-specific vs. universal
- **Mitigation:**
  - Task should inventory the specific sections to move AND the target method in each agent
  - Add note: "codex_server uses `_build_prompt`, not `build_prompt`"
  - Add note: "If agent doesn't have a prompt method, add one or use the agent's execute context"

### Step 7: Compress clarifications on resolution (A6)

**Task 7.1: Add clarification compression logic**

- **Assumption:** Clarification Q&A data is accessible in a structured format
- **Expected output:** Template-based extraction producing decisions section
- **Blockers:**
  - Need to understand current clarification data format in `service.py`
  - "Template-based extraction" needs a concrete template definition
  - Where do "downstream prompts" consume clarifications? Need to trace the data flow.
- **Mitigation:**
  - Task should specify the input format (Q&A pairs) and output format (decisions list)
  - Provide a concrete template: `"Decision: {answer}\nRationale: {context}"`
  - Add pointer to where clarifications are injected into prompts

### Step 8: Step context guidance (A14)

**Task 8.1: Write planner guidance for compact step_context**

- **Assumption:** Documentation task only
- **Expected output:** New docs file with guidance
- **Blockers:** None
- **Mitigation:** None needed

### Step 9: Test count regression guard (A4)

**Task 9.1: Create check_test_count.sh script**

- **Assumption:** `pytest --collect-only -q` produces a stable, parseable output
- **Expected output:** Shell script that diffs test lists
- **Blockers:**
  - pytest output format varies by version and plugins
  - Script needs to run both "before" (snapshot) and "after" (compare) — how is the snapshot stored?
  - Different platforms may have different `diff` behavior
- **Mitigation:**
  - Task should specify: snapshot saved to a temp file, script accepts `--snapshot` and `--compare` modes
  - Use `comm` or simple grep-based comparison instead of relying on diff formatting
  - Add `set -euo pipefail` and handle pytest failure (exit code != 0 from collect-only)

**Task 9.2: Document test regression guard**

- **Assumption:** Documentation task only
- **Expected output:** Usage guide for routine authors
- **Blockers:** None
- **Mitigation:** None needed

### Step 10: Agent escalation for unfulfillable requirements (A11)

**Task 10.1: Add EscalationCallback protocol and engine handling**

- **Assumption:** Engine can pause runs with custom reasons
- **Expected output:** Protocol defined; engine handles escalation → pause
- **Blockers:**
  - "Requirement" as a concept — how are requirements identified at runtime? Need to understand checklist model.
  - Marking a requirement as "escalated" — what field/status does this map to?
- **Mitigation:**
  - Task should reference the existing checklist/requirement model and specify where `escalated` status is added
  - Reference existing `pause_run(reason=...)` pattern from MEMORY.md

**Task 10.2: Add escalation API endpoint**

- **Assumption:** Standard router pattern in `tasks.py`
- **Expected output:** POST endpoint with proper validation
- **Blockers:** None — follows existing endpoint patterns
- **Mitigation:** None needed

**Task 10.3: Integration tests for escalation flow**

- **Assumption:** Can test escalation → pause → resume cycle
- **Expected output:** Full lifecycle test
- **Blockers:** "Human modifies requirement" step is hard to test automatically
- **Mitigation:** Test the API-level flow: escalate → verify paused → update requirement → resume

### Step 11: Step-level integration tests (A12)

**Task 11.1: Add step_auto_verify to StepConfig**

- **Assumption:** `AutoVerifyItemConfig` type already exists
- **Expected output:** New field on StepConfig
- **Blockers:** None — additive schema change
- **Mitigation:** None needed

**Task 11.2: Execute step_auto_verify after step completion**

- **Assumption:** Step completion logic is in `engine.py`
- **GAP FOUND:** Step progression logic may be in `service.py` (same pattern as task auto_verify). Agent needs to trace where step completion is handled.
- **Expected output:** step_auto_verify commands run after all tasks complete; failure halts run
- **Blockers:**
  - Need to find the exact step completion code path
  - Running auto_verify commands requires a worktree context — step-level commands may need a different execution context than task-level ones
- **Mitigation:**
  - Task should specify: "Trace step completion from `check_step_progression` or equivalent in service.py"
  - Clarify: step_auto_verify commands run in the same worktree as the step's tasks

### Step 12: Context summarization (A13)

**Task 12.1: Extend ContextFromConfig schema**

- **Assumption:** `ContextSource` model is the right place (it's `ContextSource`, not `ContextFromConfig`)
- **GAP FOUND:** Architecture doc references `ContextFromConfig` but actual model is `ContextSource`. Task should use the correct name.
- **Expected output:** New fields on the model
- **Blockers:** None
- **Mitigation:** Fix model name reference in task

**Task 12.2: Implement summary cache**

- **Assumption:** Simple dict cache is sufficient
- **Expected output:** New module with cache class
- **Blockers:** None — straightforward implementation
- **Mitigation:** None needed

**Task 12.3: Integrate summarization into prompt assembly**

- **Assumption:** Can call an LLM from prompt assembly code
- **Expected output:** Summarized context injected when `summarize: true`
- **Blockers:**
  - **HIGH RISK:** Prompt assembly calling an external LLM introduces async dependency, latency, and potential failure
  - Which LLM client/SDK to use? The orchestrator uses different agent backends — need a generic summarization call
  - Cost concerns — every prompt assembly could trigger LLM calls
  - Error handling for model failures
- **Mitigation:**
  - Task should specify: "Use the same LLM client infrastructure as the verifier"
  - Require fallback: if model call fails, use full content (already specified)
  - Add environment check: verify LLM API key is available before attempting summarization
  - Cache aggressively to minimize calls

### Step 13: Task complexity labeling (A16)

**Task 13.1: Add complexity field to TaskConfig**

- **Assumption:** Simple schema addition
- **Expected output:** New field with Literal type
- **Blockers:** None — purely additive
- **Mitigation:** None needed

### Step 14: Multi-file routine definitions (A17)

**Task 14.1: Add file field to StepConfig with overlap validation**

- **Assumption:** Can detect "other step fields" reliably in a validator
- **Expected output:** Validator rejects steps with both `file` and content fields
- **Blockers:**
  - Determining which fields constitute "other step fields" — need to distinguish between `file` and all other non-default fields
  - Pydantic validators run after field parsing — need to check which fields were explicitly provided vs. defaulted
- **Mitigation:**
  - Task should list the specific fields that conflict with `file`: `name`, `tasks`, `step_context`, `step_auto_verify`
  - Use `model_fields_set` to distinguish provided vs. defaulted fields

**Task 14.2: Implement multi-file resolution in loader**

- **Assumption:** `loader.py` doesn't exist yet — agent must create it
- **GAP FOUND:** No `loader.py` exists in the config directory. The task says "Update `loader.py`" but it needs to be created. Need to understand how routines are currently loaded.
- **Expected output:** New loader module handling multi-file resolution
- **Blockers:**
  - Need to understand current routine loading mechanism (where does it happen now?)
  - File path resolution (relative to routine directory) needs the routine's directory path
  - Error handling for circular references (step file references another file)
- **Mitigation:**
  - Task should specify: "Find the current routine loading code (likely in config/models.py or API layer) and extract/extend it into loader.py"
  - Add: "Paths are relative to the directory containing the root routine.yaml"
  - Add: "No recursive file references — step files must be complete definitions"

**Task 14.3: Multi-file loader tests**

- **Assumption:** Can create temporary YAML files for testing
- **Expected output:** Comprehensive test coverage
- **Blockers:** None — straightforward test setup
- **Mitigation:** None needed

### Step 15: Failure mode analysis in dry run (A18)

**Task 15.1: Write failure mode analysis documentation**

- **Assumption:** Documentation task only
- **Expected output:** New planner guidance doc
- **Blockers:** None
- **Mitigation:** None needed

---

## Failure Mode Analysis

| Step | Task | Failure Mode | Likelihood | Impact | Hardening Action |
|------|------|-------------|------------|--------|------------------|
| 1 | 1.1 | Agent edits `engine.py` instead of `service.py` where auto_verify logic actually lives | **High** | Wasted attempt, incorrect fix | **Fix task instructions:** Change file reference from `engine.py` to `service.py`. Add: "auto_verify execution is in `service.py:submit_task()` method, lines 738-826. The engine delegates to service." |
| 2 | 2.1 | Agent can't determine what constitutes "verifier rubric" in the schema | Medium | Incorrect validation logic | **Tighten instructions:** "Verification is present when `auto_verify.items` is non-empty OR when a verifier section exists on the task config" |
| 2 | 2.2 | Agent can't find the "auto-grade" code path in transitions.py | Medium | Blocked | **Add pointer:** "Look for the transition that auto-assigns passing grades when no external verifier ran" |
| 3 | 3.1 | Agent struggles with "first task in a run" detection — no obvious hook point | Medium | Overcomplicated implementation | **Add implementation hint:** "Add a `health_check_passed: bool` flag to Run state. Check it at the start of task execution. Run health check only when flag is False." |
| 3 | 3.1 | `.task-world/config.yaml` format undefined — agent invents incompatible format | Medium | Future compatibility issues | **Define format explicitly:** Provide exact YAML schema: `test_command: "command"` or `test_command: null` |
| 4 | 4.1 | DB migration issue — new field on Run state breaks existing DB | Low | Server crash on startup | **Add note:** "Use `None` default so existing rows are compatible. No DB recreation needed." |
| 5 | 5.1 | Existing prompt tests break after content removal | Medium | Test failures block completion | **Add instruction:** "Update all prompt-related test expectations after removing sections" |
| 6 | 6.1 | Agent can't find agent-specific content in prompts.py — sections not clearly labeled | Medium | Incomplete migration | **List specific sections to move** with line numbers or content snippets |
| 6 | 6.1 | codex_server uses `_build_prompt` not `build_prompt` | Medium | Wrong method modified | **Note the method name difference** in task instructions |
| 7 | 7.1 | Agent can't trace clarification data flow through the system | Medium | Incorrect integration point | **Add data flow description:** "Clarifications are stored in run state, injected into prompts via `prompts.py:build_prompt()`. Compressed form should replace raw Q&A at injection point." |
| 9 | 9.1 | pytest --collect-only output format differs across versions/plugins | Medium | Script breaks in some environments | **Add environment check:** "Verify pytest is available; parse output defensively (grep for `::` test markers)" |
| 9 | 9.1 | Script snapshot storage mechanism unclear | Medium | Agent invents incompatible approach | **Specify modes:** "Script operates in two modes: `--snapshot <file>` saves test list, `--compare <file>` compares current tests against snapshot" |
| 10 | 10.1 | "Requirement" runtime representation unclear | Medium | Wrong data model | **Reference existing model:** "Requirements map to checklist items. Add `escalated` as a valid checklist item status alongside `done`, `blocked`, `not_applicable`." |
| 11 | 11.2 | Step completion logic is in service.py, not engine.py (same issue as Step 1) | **High** | Agent edits wrong file | **Fix file reference:** "Step completion is handled in `service.py`. Trace from `check_step_progression`." |
| 12 | 12.1 | Task references `ContextFromConfig` but actual model is `ContextSource` | Medium | Agent creates wrong/duplicate model | **Fix model name:** "Extend the existing `ContextSource` model in `config/models.py`" |
| 12 | 12.3 | LLM call from prompt assembly — async complexity, no client available | **High** | Feature can't be implemented as designed | **Add fallback plan:** "If direct LLM call is too complex, implement summarization as a pre-processing step before prompt assembly, using the executor's existing LLM client infrastructure. Provide a sync wrapper or make prompt assembly async." |
| 12 | 12.3 | No API key for summarization model in test/CI environments | Medium | Tests fail or are skipped | **Add environment check:** "Skip summarization (use full content) when no API key is configured. Tests should mock the LLM call." Wait — AGENTS.md says no mocking. **Alternative:** "Tests should use a test-specific summarization function that returns truncated content." |
| 14 | 14.2 | No `loader.py` exists — task says "Update" but needs "Create" | **High** | Agent confused about starting point | **Fix instruction:** "Create `src/orchestrator/config/loader.py`. Find current routine loading code (check API routers, service.py, or config module) and extract the loading logic." |
| 14 | 14.1 | Detecting "explicitly set" vs "defaulted" fields in Pydantic is subtle | Medium | Validator lets overlapping fields through | **Add implementation hint:** "Use `self.model_fields_set` in the validator to check which fields were explicitly provided in the YAML" |

---

## Plan Changes Recommended

### Critical (fix before execution)

1. **Step 1, Task 1.1 — Wrong file reference:** Change `engine.py` to `service.py`. The auto_verify execution logic is in `WorkflowService.submit_task()`, not the engine. Add the specific method name and approximate line range.

2. **Step 11, Task 11.2 — Wrong file reference:** Same issue. Step completion logic is likely in `service.py`, not `engine.py`. Add pointer to trace the code path.

3. **Step 12, Task 12.1 — Wrong model name:** Change `ContextFromConfig` to `ContextSource` (the actual model name in `config/models.py`).

4. **Step 14, Task 14.2 — File doesn't exist:** Change "Update `loader.py`" to "Create `loader.py`". Add instruction to find where routine loading currently happens and extract/extend that logic.

### High Priority (reduce failure likelihood)

5. **Step 3, Task 3.1 — Define config format:** Add explicit YAML schema for `.task-world/config.yaml` to prevent agents from inventing incompatible formats. Minimal: `test_command: "string" | null`.

6. **Step 6, Task 6.1 — Inventory sections to move:** List the specific prompt sections that are agent-specific, with identifiable markers. Note that `codex_server.py` uses `_build_prompt` not `build_prompt`.

7. **Step 9, Task 9.1 — Define script modes:** Specify `--snapshot` and `--compare` operating modes explicitly. This prevents agents from designing an incompatible interface.

8. **Step 12, Task 12.3 — LLM integration complexity:** This is the highest-risk task in the entire plan. Add:
   - Clear specification of which LLM client to use
   - Whether prompt assembly should become async
   - Fallback behavior when no API key is available
   - Consider splitting into: (a) implement sync summarizer with LLM call, (b) integrate into prompt assembly

### Medium Priority (improve clarity)

9. **Step 2, Tasks 2.1/2.2 — Define "verification present":** Explicitly state: `auto_verify.items` non-empty OR verifier rubric present.

10. **Step 7, Task 7.1 — Trace clarification data flow:** Add description of how clarifications flow through the system and where the compression should be integrated.

11. **Step 10, Task 10.1 — Reference existing models:** Point to the checklist item model and existing pause_reason patterns.

12. **Step 14, Task 14.1 — List conflicting fields:** Enumerate which StepConfig fields conflict with `file` and recommend using `model_fields_set`.

### Environmental Pre-checks (add as auto_verify)

13. **All steps:** Add auto_verify command: `uv run pytest --tb=no -q` to confirm baseline tests still pass after changes.

14. **Step 12:** Add auto_verify: check that the LLM client/API key configuration is documented (or that fallback works without it).

15. **Step 3:** Add auto_verify: verify `.task-world/config.yaml` parsing works with the defined format.
