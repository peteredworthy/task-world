# Failure Mode Analysis in the Dry-Run Stage

## What Is Failure Mode Analysis?

Failure mode analysis is a structured review of a plan **before** execution begins. For each task in the plan, you ask: *what could go wrong, and what would the agent do if it did?*

This is not pessimism — it is how you convert a plan from a list of intentions into a set of executable instructions. Gaps that feel minor at planning time reliably become blockers mid-run: a wrong file reference wastes an attempt, an undefined format produces an incompatible implementation, a misnamed model produces a duplicate.

The dry-run stage exists specifically to catch these before any agent starts.

---

## When to Perform It

Failure mode analysis is part of the **dry-run stage** — after the plan is written and before execution is approved.

The sequence is:

1. Write the plan (steps, tasks, requirements, acceptance criteria)
2. **Dry-run:** Simulate execution of every task, tracking assumptions and gaps
3. Perform failure mode analysis on the simulation results
4. Update task instructions to address identified risks
5. Approve and execute

Do not skip failure mode analysis on tasks that seem simple. "Documentation only" tasks are low-risk. Tasks that require agents to find, modify, or extend existing code are higher-risk, and most plans contain several.

---

## How to Identify Failure Modes Per Step

For each task, work through the following questions:

### 1. Are the file references correct?

Name the specific file(s) the agent should edit. Verify these files exist and contain the code the task assumes they contain.

**Common failure:** The architecture document names a conceptual layer (e.g., "the engine"), but the actual logic lives elsewhere (e.g., `service.py`). An agent given the wrong file either edits the wrong place or wastes an attempt searching for code that isn't there.

**Fix:** Open the file. Confirm the method or class is there. Add the method name and approximate line range to the task instructions.

### 2. Are the model/schema names correct?

If the task says "extend `ContextFromConfig`," verify that is the real class name in the codebase. A wrong name leads the agent to create a duplicate class.

**Fix:** Grep for the class name before writing the task. Use the actual name.

### 3. Are format-dependent interfaces specified?

If the task introduces a new config file, YAML schema, CLI flag, or data structure that other tasks or routines will depend on, the format must be defined explicitly in the task instructions. Agents left to invent formats will produce valid-but-incompatible ones.

**Fix:** Provide the exact schema. Example:
```yaml
test_command: "uv run pytest --tb=no -q"
```
Not "define a config file that stores the test command."

### 4. Does "create" vs. "update" match reality?

If a file does not exist, the instruction must say "create." If it does exist, the instruction must say "update" or "extend." Saying "update `loader.py`" when `loader.py` doesn't exist forces the agent to either create an orphan file or spend tool calls confirming the situation.

**Fix:** Check for the file. If it exists, note where the insertion point is. If it doesn't, say "create" and explain what it should extract or implement.

### 5. Will existing tests break?

If the task removes, renames, or restructures code that existing tests assert against, those tests will fail. This is predictable.

**Fix:** Note in the task instructions that prompt content, API response shapes, or schema fields that are changing have corresponding tests that must be updated.

### 6. Is there an implicit async or infrastructure dependency?

Some features sound simple ("call an LLM to summarize context") but require async infrastructure, API keys, error handling, and test-environment mocking. Identify these before an agent builds a synchronous implementation that blocks the event loop.

**Fix:** State explicitly whether the implementation should be sync or async, which client to use, what the fallback is when no API key is present, and how tests should handle the external call.

### 7. Are existing patterns documented for the agent?

Agents work faster and more accurately when the task instructions reference the pattern to follow. "Follow the existing pause_run(reason=...) pattern" is more actionable than "implement a pause mechanism."

**Fix:** Add a one-line pointer: "See `src/orchestrator/engine.py:pause_run()` for the pattern to follow."

---

## How to Re-Engineer the Plan Based on Identified Risks

After identifying failure modes, classify each by impact:

| Classification | Criteria | Action |
|---|---|---|
| **Critical** | Wrong file, wrong model name, or "create vs. update" mismatch — agent will almost certainly fail | Fix task instructions before execution |
| **High** | Undefined format, missing pattern reference, async dependency — likely to produce wrong or incompatible implementation | Fix task instructions; consider splitting task |
| **Medium** | Ambiguous terminology, implicit knowledge requirement — agent may succeed or may not | Clarify with explicit statement |
| **Low** | Minor ambiguity where reasonable assumptions exist | Document expected interpretation; no instruction change needed |

### Applying the changes

For critical and high-risk items, rewrite the affected portion of the task instructions. Do not add a separate "known issues" section that agents must cross-reference — place the fix directly in the task that will fail.

For high-risk tasks that depend on LLM calls, external state, or async infrastructure, consider splitting:
- Task A: Implement the data model and synchronous stub
- Task B: Wire the async integration and write tests

This allows verification at each stage and makes the failure surface smaller.

For environmental dependencies (API keys, database state, tool availability), add an `auto_verify` check to the step:
```yaml
step_auto_verify:
  - run: "uv run pytest tests/relevant_module/ --tb=short -q"
    expect_exit: 0
```

---

## Example: Failure Modes from the Routine Improvements Dry Run

The following examples are drawn from `docs/routine-improvements/dry-run-notes.md`, which documents a simulation of a 15-step, 26-task plan.

### Example 1: Wrong file reference (Critical)

**Step 1, Task 1.1** — "Reorder auto_verify execution in `submit_for_verification`"

The task instructions referenced `engine.py`. The dry-run simulation found that auto_verify logic actually lives in `service.py` (lines 738-826). The engine delegates to the service. An agent following the original instructions would edit the wrong file and produce a non-functional change.

**Hardening applied:** Changed file reference to `service.py`. Added the method name (`WorkflowService.submit_task()`) and line range. Added a description of the call chain: `engine.submit_for_verification()` → `service.submit_task()` → auto_verify execution.

**Lesson:** Never reference a file without opening it and confirming the relevant code is there.

---

### Example 2: Wrong model name (Critical)

**Step 12, Task 12.1** — "Extend `ContextFromConfig` schema"

`ContextFromConfig` is the name used in the architecture document. The actual model in `config/models.py` is `ContextSource`. An agent following the original instructions would either fail to find the class or create a new, duplicate class named `ContextFromConfig`.

**Hardening applied:** Changed the instruction to "Extend the existing `ContextSource` model in `config/models.py`."

**Lesson:** Architecture documents use conceptual names. Always verify the actual class name in the code before writing task instructions.

---

### Example 3: "Create" vs. "Update" mismatch (Critical)

**Step 14, Task 14.2** — "Update `loader.py` to resolve multi-file step references"

`loader.py` did not exist. The task implied a file to modify; the agent would have to create it. Without knowing where routine loading currently happens or where to create the file, an agent might create `loader.py` in the wrong location or with the wrong API.

**Hardening applied:** Changed to "Create `src/orchestrator/config/loader.py`." Added instruction to find where routine loading currently happens (in API routers or `service.py`) and extract/extend that logic into the new module.

**Lesson:** Confirm file existence. If the file doesn't exist, provide the full target path and explain what it should extract or implement from existing code.

---

### Example 4: Undefined format (High)

**Step 3, Task 3.1** — "Add test health check to executor"

The health check reads a project-level config file at `.task-world/config.yaml`. The format of this file was not defined in the task instructions. An agent inventing the format might produce something incompatible with how the file is parsed by other tools.

**Hardening applied:** Added explicit YAML schema to the task instructions:
```yaml
test_command: "uv run pytest --tb=no -q"
# or
test_command: null  # opt out of health check
```

**Lesson:** Any format that crosses a module or tool boundary must be specified explicitly.

---

### Example 5: Async/infrastructure dependency (High)

**Step 12, Task 12.3** — "Integrate summarization into prompt assembly"

Calling an LLM from within prompt assembly introduces async complexity (prompt assembly may be synchronous), an API key dependency, latency, and test-environment handling. A naive implementation would block the event loop or fail silently when no key is configured.

**Hardening applied:** Added:
- Specification of which LLM client to use (same as the verifier)
- Whether prompt assembly should be made async (yes)
- Explicit fallback: if model call fails, use full content unchanged
- Environment check: skip summarization when no API key is configured
- Test guidance: use a test-specific summarization function that returns truncated content (rather than mocking the LLM)

**Lesson:** Features that call external services during request handling require explicit decisions about async behavior, failure modes, and test isolation before implementation begins.

---

### Example 6: Method naming difference across agents (Medium)

**Step 6, Task 6.1** — "Move agent-specific instructions from shared prompt to individual agent runners"

Most agents implement `build_prompt()`. `codex_server.py` implements `_build_prompt()` (private, different name). An agent applying the same transformation to all runners would miss `codex_server` or produce a broken integration.

**Hardening applied:** Added explicit note: "`codex_server.py` uses `_build_prompt()`, not `build_prompt()`. Apply changes to the correct method."

**Lesson:** Patterns that appear uniform often have one exception. Find the exception during dry-run, not during a failed attempt.

---

## Checklist for Dry-Run Failure Mode Analysis

Use this checklist when simulating each task:

- [ ] File references verified against actual codebase (file exists, code is there)
- [ ] Class and model names verified against actual source (not architecture docs)
- [ ] "Create" vs. "update" matches file existence
- [ ] All format-dependent interfaces have explicit schemas in the task instructions
- [ ] Existing tests that will break are identified and listed
- [ ] Async/infrastructure dependencies are resolved (client, fallback, test strategy)
- [ ] Pattern references are provided for non-obvious implementation choices
- [ ] Agent-specific method name variations are noted

For each identified risk, add the fix directly to the task instructions. Record the gap in the dry-run notes file for future plan audits.
