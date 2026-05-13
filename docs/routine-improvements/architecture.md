# Architecture: Routine System Effectiveness Improvements

## Integration Points

This work touches four subsystems of the orchestrator. Each change integrates at a well-defined point with minimal cross-cutting concerns.

### 1. Workflow Engine (`src/orchestrator/workflow/`)

**Current flow:**
```
Builder marks items done → submit_for_verification() → checklist gate → auto_verify → transition to VERIFYING
```

**After A1 (auto_verify timing fix):**
```
Builder marks items done → submit_for_verification() → auto_verify FIRST → checklist gate → transition to VERIFYING
```

The change is within `engine.py:submit_for_verification()`. Auto_verify execution moves before the checklist gate evaluation. If any `must: true` auto_verify item fails, raise `GateBlockedError` with details of which items failed.

**After A10 (verifier model pinning):**
Add `verifier_model: str | None` to `Run` state. Set at run creation from the current agent config. The executor passes this pinned model to all verifier invocations, ignoring any subsequent config changes.

**After A12 (step-level auto_verify):**
In the step completion path (`check_step_progression` or the engine method that calls it), after confirming all tasks are terminal, run `step_auto_verify` commands. **Decision:** If any fail, the step fails and the run halts (no auto-advance to next step). Tasks remain complete but the step is marked as failed. There is no "pending" intermediate state — it either passes and advances, or fails and stops the run.

### 2. Config Models (`src/orchestrator/config/models.py`)

**A2 — Verification requirement validation:**
Add a `model_validator` on `TaskConfig` that checks: if `auto_verify` is empty AND `verifier` rubric is empty, raise `ValueError`. This catches undefended tasks at routine load time.

**Decision:** Warn by default (log warning, allow loading). Add a `strict_validation: bool` flag on the routine config — when `True`, undefended tasks cause a hard rejection. This allows existing routines to continue working while encouraging migration to full verification coverage.

**A12 — StepConfig extension:**
```python
class StepConfig(BaseModel):
    # ... existing fields ...
    step_auto_verify: list[AutoVerifyItemConfig] = Field(default_factory=list)
```

**A13 — ContextFrom extension:**
```python
class ContextFromConfig(BaseModel):
    # ... existing fields ...
    summarize: bool = False
    critical: str | None = None  # description of what must be preserved
    summarize_model: str | None = None  # override summarization model (default: cheap model like Haiku)
```

**A16 — Task complexity:**
```python
class TaskConfig(BaseModel):
    # ... existing fields ...
    complexity: Literal["simple", "standard"] = "standard"
```

Add `Complexity` to `enums.py` or use `Literal` directly in the model.

**A17 — Step file references:**
```python
class StepConfig(BaseModel):
    # ... existing fields ...
    file: str | None = None  # relative path to step YAML file
```

When `file` is set, the loader reads the referenced YAML and uses it as the complete step definition. **Decision:** If a step specifies `file` AND includes other step fields (name, tasks, etc.), validation fails. A routine must not include step fields that overlap with a referenced file — this prevents ambiguity about which definition takes precedence.

### 3. Config Loader (`src/orchestrator/config/loader.py`)

**A17 — Multi-file resolution:**
The loader currently reads a single YAML file. After A17:
1. Parse root `routine.yaml`
2. For each step with a `file` field, resolve the path relative to the routine directory
3. Load and parse the referenced step YAML
4. Validate all referenced files exist before proceeding
5. Assemble the complete `RoutineConfig` from the combined sources

Error handling: if a referenced file is missing, raise `RoutineValidationError` with the missing path and the step that referenced it.

### 4. Prompt Builder (`src/orchestrator/workflow/prompts.py`)

**A7 — Dead weight removal:**
Remove these sections from the system message template:
- "Avoiding Loops" section (~512 chars) — universally ignored per D4
- Other agent-behavioral instructions that belong in individual runners

**Decision:** The 39% figure is informational only. Remove the specific identified dead-weight sections; do not target an exact percentage.

**A8 — Agent-specific instruction migration:**
Move to individual agent runners:
- CLI agent (`cli.py`): git workflow instructions, commit conventions
- OpenHands agent (`openhands.py`): file re-reading avoidance, Docker context awareness
- Codex agent (`codex_server.py`): sandbox constraints, shorter response preferences
- Claude SDK agent (`claude_sdk.py`): tool usage patterns, sub-agent guidance

Each agent's `build_prompt()` method already exists and can prepend agent-specific instructions to the system message.

**A13 — Context summarization:**
When `context_from` has `summarize: true`:
1. Check summary cache (keyed by artifact path + content hash)
2. If cached, use cached summary
3. If not cached:
   a. Call the configured summarization model (default: a cheap model like Haiku; configurable per routine/project) with a summarization prompt
   b. If `critical` is set, verify the summary contains the critical aspects
   c. If critical aspects missing, re-summarize with explicit instruction to preserve them (max 2 iterations)
   d. Cache the result

The summary cache lives in `src/orchestrator/workflow/summary_cache.py` — a simple dict keyed by `(path, content_hash)`. Cache lifetime is the run duration.

### 5. Agent Interface (`src/orchestrator/agents/interface.py`)

**A11 — Escalation callback:**
```python
class EscalationCallback(Protocol):
    def escalate(self, requirement_id: str, reason: str) -> None: ...
```

New API endpoint:
```
POST /api/runs/{run_id}/tasks/{task_id}/escalate
Body: {"requirement_id": "R1", "reason": "OpenHands not installed in this environment"}
```

Effect: marks the requirement as `escalated`, pauses the run with `pause_reason="requirement_escalated"`. The human can then:
- Modify the requirement
- Mark it as not_applicable
- Provide environment guidance and resume

### 6. Executor (`src/orchestrator/agents/executor.py`)

**A5 — Pre-run test health check:**
Before executing the first task attempt in a run, run the test command (default: `uv run pytest --tb=no -q`). If exit code is non-zero, block with a descriptive error including the test output.

**Decision:** Test command is configured via a project-level config file (e.g. `.task-world/config.yaml` with a `test_command` field) with convention fallback (default: `uv run pytest --tb=no -q`). For projects without tests or config, the check uses the convention default. If the project explicitly opts out (e.g. `test_command: null`), the check is skipped.

---

## New Files

| File | Purpose |
|------|---------|
| `src/orchestrator/workflow/summary_cache.py` | Context summary caching (A13) |
| Documentation in `docs/` | Step context guidance (A14), failure mode analysis (A18) |

## Modified Files

| File | Changes |
|------|---------|
| `src/orchestrator/workflow/engine.py` | A1 (auto_verify order), A10 (model pinning), A12 (step auto_verify) |
| `src/orchestrator/config/models.py` | A2 (validation), A12 (step_auto_verify), A13 (context_from), A16 (complexity), A17 (file ref) |
| `src/orchestrator/config/loader.py` | A17 (multi-file loading) |
| `src/orchestrator/config/enums.py` | A16 (complexity enum) |
| `src/orchestrator/workflow/prompts.py` | A7 (trim), A8 (migrate out), A13 (summarization) |
| `src/orchestrator/workflow/transitions.py` | A2 (block auto-grade) |
| `src/orchestrator/workflow/service.py` | A6 (clarification compression) |
| `src/orchestrator/agents/executor.py` | A5 (health check), A10 (pinned model) |
| `src/orchestrator/agents/interface.py` | A11 (escalation callback) |
| `src/orchestrator/agents/cli.py` | A8 (agent-specific instructions) |
| `src/orchestrator/agents/openhands.py` | A8 (agent-specific instructions) |
| `src/orchestrator/agents/codex_server.py` | A8 (agent-specific instructions) |
| `src/orchestrator/agents/claude_sdk.py` | A8 (agent-specific instructions) |
| `src/orchestrator/routers/tasks.py` | A11 (escalation endpoint) |

---

## Testing Strategy

### Per-Feature Testing

**A1 (auto_verify timing):**
- Unit: `submit_for_verification()` with failing auto_verify → blocked. With passing auto_verify → proceeds.
- Integration: Full submit flow through API with auto_verify configured.

**A2 (require verification):**
- Unit: `TaskConfig` validation rejects task with no auto_verify and no verifier.
- Unit: `transition_after_verification()` blocks auto-grade when no verification configured.
- Integration: Routine load with undefended task → validation error.

**A5 (pre-run health check):**
- Integration: executor with failing test suite → task start blocked.
- Integration: executor with passing test suite → task starts normally.
- Edge case: project with no test command configured → check skipped.

**A6 (clarification compression):**
- Unit: compress function produces decisions section from Q&A input.
- Unit: downstream prompt contains decisions, not raw Q&A.

**A7 (prompt trim):**
- Unit: system prompt does not contain "Avoiding Loops" or other removed sections.
- Unit: system prompt still contains required sections (task context, requirements).

**A8 (agent-specific instructions):**
- Unit: each agent's prompt includes its specific instructions.
- Unit: shared prompt does not contain agent-specific content.

**A10 (model pinning):**
- Unit: run stores verifier_model at creation.
- Unit: verifier invocation uses pinned model, not current config.

**A11 (escalation):**
- Integration: POST escalation → requirement marked escalated, run paused.
- Integration: human modifies requirement → run can resume.

**A12 (step auto_verify):**
- Unit: StepConfig accepts step_auto_verify field.
- Unit: step completion runs step_auto_verify commands.
- Unit: failing step_auto_verify blocks step advancement.

**A13 (context summarization):**
- Unit: summary generation with critical-aspect check.
- Unit: cache hit returns cached summary.
- Unit: missing critical aspect triggers re-summarization.

**A16 (complexity):**
- Unit: TaskConfig accepts complexity field with valid values.
- Unit: default is "standard".

**A17 (multi-file routines):**
- Unit: loader resolves step file references.
- Unit: missing step file raises RoutineValidationError.
- Integration: full routine load from multi-file structure.

### Regression Testing

- Run full test suite (786+ tests) after each milestone
- No mocking — all tests use real objects with dependency injection
- Test fixtures: `tmp_dir`, `fixed_time`, `in_memory_db`, `routine_repo`

### Test Organization

New tests go in:
- `tests/unit/test_engine.py` — A1, A10, A12 engine changes
- `tests/unit/test_models.py` — A2, A12, A13, A16, A17 schema changes
- `tests/unit/test_prompts.py` — A7, A8 prompt changes
- `tests/unit/test_transitions.py` — A2 auto-grade blocking
- `tests/integration/test_api_tasks.py` — A11 escalation endpoint
- `tests/integration/test_api_full_lifecycle.py` — A1, A5 full flow tests
- New test file for multi-file loader: `tests/unit/test_loader_multifile.py`
- New test file for summary cache: `tests/unit/test_summary_cache.py`
