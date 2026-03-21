# Guide to Creating `STEP-XX.md` Files

This document defines the structure and best practices for creating `STEP-XX.md` files used to guide AI implementation tasks. Adhering to this format ensures clarity, verifiability, and successful execution by the implementing AI.

---

## 1. File Structure Principles

### 1.1. Purpose

Each `STEP-XX.md` file represents a single, cohesive stage of a larger plan. It must:

- Be self-contained.
- Be broken down into atomic tasks.

### 1.2. Overall Layout

A STEP file has two main components:

- **Preamble Header**: Context and intent.
- **Task List**: A series of tasks separated by a marker.

```
# Step [step #]: [Descriptive Title]

[Context paragraph explaining the goal]

## Intent Verification
**Original Intent**: [Reference to specific intent.md requirement]
**Functionality to Produce**: [A bulleted list of the functionality that must be present once the step is complete]
**Final Verification Criteria**: [A bulleted list of how the step must be evaluated]

---

## Task 1: [Descriptive Title]
...
```

### 1.3. Preamble Header

- Begins with a **level 1 markdown heading** containing the step number and descriptive title.
- Followed by one or two paragraphs of explanatory text providing context.

### 1.4. Task Separator

- Each task is separated from the previous one by a line containing exactly three hyphens (`---`).
- The separator must be surrounded by blank lines for readability.

---

## 2. Task Format Requirements

Each task must follow a consistent structure to provide the AI with clear, unambiguous instructions.

- **Title**: A level 2 markdown heading describing the objective.

- **Description (Optional)**: A brief explanation of the goal.

- **Implementation Plan (Do These Steps)**: A checklist of the breakdown of changes that should be made, including edits, file creation, and commands to run.

  - Include fenced code blocks where appropriate with explicit code to be inserted or modified.
  - Use comments like `# existingcode` to indicate context without including the full file.
  - Include fenced shell command blocks that are suitable for direct execution.
  - May include inline verification checkpoints (e.g., run tests, lint checks) expressed as **actions** to perform before continuing.

- **Dependencies (Optional)**: Preconditions that must exist before starting (e.g., library must be installed).

- **References (Optional)**: Links to external documentation, related specs, or supporting material.

- **Constraints (Optional)**: Explicit boundaries for what may or may not change. Example:

  ```
  Only ClassY and ClassZ should have their functionality changed.
  No other class should be altered, except imports/references.
  ```

- **Side Effects (Optional)**: Known impacts, such as temporary breakage in another module.

- **Functionality (Expected Outcomes)**:

  This section defines the end-state that must exist once the task is complete.

  -

- **Final Verification (Proof of Completion)**:

  DO NOT perform these until all Implementation Plan items are complete. These must be repeated even if similar checks were performed earlier.

  -

````
# Task [Task #]: [Descriptive Title]
**Description**:
[Description of the purpose of the task]

**Implementation Plan (Do These Steps)**
[Rationale / contextual notes explaining why the plan is structured this way]
- [ ] [Action, edit file, create file, run command]
```
[Optional code block(s) giving clear guidance on implementation]
```
- [ ] [Further breakdown action]

**Dependencies (Optional)**
- [ ] [Dependency that must exist]

**References (Optional)**
- [Link to relevant documentation]

**Constraints (Optional)**
- [ ] [Explicit boundary on what may or may not be changed]

**Side Effects (Optional)**
- [ ] [Known impacts]

**Functionality (Expected Outcomes)**
- [ ] [Functionality that must be present at the end of this task]
- [ ] [Functionality]

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] [Action that must be carried out to verify that the task is complete and successful]
- [ ] [Additional verification step]
````

---

## 3. Best Practices

- **Atomicity**: Each task should be the smallest possible unit of work that leaves the codebase valid and testable. Do not bundle unrelated changes.
- **Provide Full Context**: Include necessary background for libraries, APIs, or tools. For example:
  > This task uses LangChain's Pydantic output parser. It requires X, Y, and Z. See the [official documentation](https://example.com).
- **Be Explicit**:
  - Code in `implementation` must be copy-paste ready.
  - Commands in `command` must be directly executable.
  - Acceptance criteria must be objective, verifiable, and unambiguous.

---

## 4. Writing Verification That Catches Real Failures

The most common failure mode in step files is **verifying presence instead of behavior**. A task that requires "implement X" passes its verification by creating files and helper functions, while leaving the core I/O path as a stub — and the tests are written to assert the stub behavior rather than requiring it to be replaced.

### The Presence Trap

A verification command is a **presence check** if it confirms that something exists or compiles, but cannot distinguish a working implementation from a typed-but-empty placeholder. Examples:

```bash
# BAD — presence check only
test -f src/orchestrator/agents/codex_server.py   # exists, but execute() is a stub
uv run pyright src/orchestrator/agents/codex_server.py  # type-checks, but execute() raises immediately
uv run pytest tests/unit -k 'codex_server and callbacks'  # passes if _route_tool_call() works,
                                                           # even if execute() never calls it
```

These commands would all pass even if `execute()` were:
```python
raise AgentNotAvailableError("transport not yet implemented")
```

### The Silent Zero-Test Pass

A pytest `-k` filter that matches **zero tests** exits with code 0, silently satisfying an auto-verify check. Always confirm that the filter expression you write actually matches tests that exist. A filter like:

```bash
uv run pytest tests/integration -k 'agent and (builder or verifier) and (rest or mcp)' -v
```

passes vacuously if no such tests have been written yet. Use explicit file paths rather than broad `-k` expressions when the test files are known:

```bash
# BETTER — explicit file, known to exist
uv run pytest tests/integration/test_codex_server_callbacks.py -v
```

Or add `--collect-only` as a dry-run check during planning to confirm the filter finds tests.

### Write Behavioral Verification

A behavioral check cannot pass unless the feature actually works end-to-end. Ask: **"Could this check pass if the core I/O was missing?"** If yes, it is a presence check and must be strengthened.

| Task requires | Weak (presence) | Strong (behavior) |
|---|---|---|
| Implement `execute()` that POSTs to a server | `test -f agent.py` | Start a fake HTTP server; call `execute()`; assert it POSTs and invokes the callback |
| Agent routes callbacks correctly | Test that `_route_tool_call()` dispatches | Call `execute()` with a fake server returning a tool event; assert the callback fires |
| Lifecycle start/pause/resume works | `GET /api/runs/{id}` returns 200 | Start run; pause it; resume it; assert status transitions in sequence |
| Tests cover error paths | `uv run pytest -k error` passes | Assert that specific exception types are raised for specific failure inputs |

### When True End-to-End Tests Are Impractical

Sometimes the real I/O requires an external service (e.g., a live Codex server). In that case:

1. **Use a fake/in-process server** in tests (e.g., `httpx` mock transport, an in-process ASGI app, or a minimal TCP stub). This is the preferred approach.
2. **If the transport is genuinely unimplemented**, make the verification explicitly state that: mark the requirement as blocked with a note, rather than writing a test that asserts the stub behavior and passes as if that were success.
3. **Never write a test that asserts `raises AgentNotAvailableError`** as the sole proof that an execute path works. That test proves the path is broken, not that it works.

### Checklist for Final Verification Steps

Before adding a verification item to **Final Verification (Proof of Completion)**, ask:

- [ ] Would this check fail if the implementation was a stub that immediately raises?
- [ ] Does it exercise the actual I/O path (HTTP call, file write, DB insert, callback invocation)?
- [ ] If it uses a pytest `-k` filter, have I confirmed it matches at least one test?
- [ ] Does passing this check prove the feature is usable, not just present?

If any answer is "no", the check is a presence check. Either strengthen it or add a complementary behavioral check alongside it.
