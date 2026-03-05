# Execution Summary: Routine System Effectiveness Improvements

## Intent Satisfaction

This plan implements 16 actions (A1-A2, A4-A14, A16-A18) from the routine effectiveness review to raise execution fidelity from ~70% gate accuracy to a system with independent verification on every task, leaner prompts, and failure-mode defenses.

Three actions are explicitly out of scope: A3 (per-requirement grading, not observed on passed tasks), A9 (OpenHands sub-agent tool, requires SDK research), and A15 (golden contract tests, high effort/fragility risk).

All 15 completion criteria from the intent are covered by at least one step. Every clarification decision (Q1-Q7) is reflected in the plan and step files.

## Ordered Step List

| Step | Action | Description | Tasks |
|------|--------|-------------|-------|
| 1 | A1 | Fix auto_verify timing — run before checklist gate | 2 |
| 2 | A2 | Require verification on every task (warn/strict) | 3 |
| 3 | A5 | Pre-run test health check with project-level config | 2 |
| 4 | A10 | Pin verifier model at run creation | 1 |
| 5 | A7 | Trim prompt dead weight (remove "Avoiding Loops" etc.) | 1 |
| 6 | A8 | Migrate agent-specific instructions to agent runners | 1 |
| 7 | A6 | Compress clarifications into decisions on resolution | 1 |
| 8 | A14 | Step context guidance for planners | 1 |
| 9 | A4 | Test count regression guard script | 2 |
| 10 | A11 | Agent escalation for unfulfillable requirements | 3 |
| 11 | A12 | Step-level integration tests (step_auto_verify) | 2 |
| 12 | A13 | Context summarization with critical-aspect preservation | 3 |
| 13 | A16 | Task complexity labeling (simple/standard) | 1 |
| 14 | A17 | Multi-file routine definitions | 3 |
| 15 | A18 | Failure mode analysis in planner documentation | 1 |
| | | **Total** | **27** |

### Milestone Structure

- **M1 (Gate Fixes & Safety):** Steps 1-4 — closes structural holes in gates
- **M2 (Prompt & Context Efficiency):** Steps 5-8 — reduces prompt waste
- **M3 (Safety Guards):** Steps 9-10 — regression detection and agent escalation
- **M4 (Schema & Architecture Extensions):** Steps 11-14 — new config capabilities
- **M5 (Planning Documentation):** Step 15 — failure mode analysis docs

M1 and M2 run in parallel (per clarification Q5). M3-M5 follow sequentially after M1/M2 complete.

## Key Decisions

| Decision | Source | Choice |
|----------|--------|--------|
| A2 enforcement strategy | Clarification Q2 | Warn by default; `strict_validation` flag for hard rejection |
| A5 test command config | Clarification Q1 | Project-level config file (`.task-world/config.yaml`) with convention fallback |
| A7 reduction target | Clarification Q6 | Remove identified dead-weight sections only; 39% figure is informational |
| A12 step_auto_verify failure | Clarification Q3 | Fail the step and halt the run (no auto-advance) |
| A13 summarization model | Clarification Q4 | Configurable with sensible cheap default (e.g., Haiku) |
| A17 file+field overlap | Clarification Q7 | Validation fails if step specifies both `file` and other step fields |
| M1/M2 execution order | Clarification Q5 | Parallel for faster delivery |

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Step 12 (A13): LLM call from prompt assembly** introduces async complexity, latency, and failure modes | High | High | Use executor's existing LLM client; fallback to full content on failure; cache aggressively; skip summarization when no API key configured |
| **Steps 1 & 11: File references point to `engine.py`** but auto_verify and step completion logic live in `service.py` | High | Medium | Dry-run identified this; step files must be corrected to reference `service.py` before execution |
| **Step 14: `loader.py` doesn't exist** but task says "Update" | High | Medium | Change to "Create"; add guidance on finding current routine loading code |
| **Step 12: Model name mismatch** — architecture says `ContextFromConfig`, actual code may use `ContextSource` | Medium | Medium | Verify actual model name in codebase before execution; update all references |
| **Step 6: Agent method name differences** — `codex_server.py` uses `_build_prompt` not `build_prompt` | Medium | Low | Note method name in step instructions |
| **Step 3: Project config format undefined** | Medium | Medium | Format explicitly defined in step plan: `test_command: "string"` or `test_command: null` |
| **Step 9: Script interface unspecified** | Medium | Low | Define `--snapshot <file>` and `--compare <file>` modes |
| Existing test baseline (786+ tests) regression | Low | High | Every step includes regression check via `uv run pytest --tb=no -q` |

## Caveats for Execution

1. **Must-fix before starting:** The verification report identified 3 critical issues in step files that must be corrected before execution begins: wrong file references in Steps 1 and 11, wrong verb ("Update" vs "Create") in Step 14 Task 14.2, and model name verification needed for Step 12. These are documented in the verification report and dry-run notes.

2. **Step 12 is the highest-risk step.** Context summarization (A13) requires calling an external LLM from within prompt assembly. This introduces async complexity, cost, and failure modes not present elsewhere. Consider splitting Task 12.3 into separate sub-tasks: (a) implement the summarizer, (b) integrate into prompt assembly.

3. **No mocking constraint.** Per AGENTS.md, tests cannot use `patch`, `MagicMock`, or monkeypatching. Step 12 tests for summarization must use real objects or test-specific implementations rather than mocked LLM calls.

4. **DB schema changes.** Steps adding fields to state models (Step 4: `verifier_model` on Run) must use `None` defaults so existing database rows remain compatible without migration.

5. **Auto-verify coverage.** The task description requires contract-level `auto_verify` on every task in the routine. Every code-change task should verify baseline tests still pass; documentation-only tasks (Steps 8, 15) have file-existence checks.

6. **Agent-specific prompt migration (Step 6)** depends on Step 5 completing first (prompt trimming before migration prevents moving dead-weight sections). Within M2, execute Step 5 before Step 6.

7. **Parallel M1/M2 merge conflicts.** Both milestones touch `prompts.py` and `engine.py`. Coordinate to avoid conflicting edits — M1 changes the execution flow, M2 changes the content.
