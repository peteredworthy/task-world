# Intent: Routine System Effectiveness Improvements

## Goal

Raise the orchestrator's routine execution fidelity from its current ~70% gate accuracy and undefended auto-grade paths to a system where every task has independent verification, prompts are lean, and failure modes are caught before they cascade.

This work implements 16 actions (A1-A2, A4-A14, A16-A18) identified in the routine effectiveness review, targeting the structural weaknesses that allowed 30.4% false-positive gate passes, 2.1-hour death spirals, and destructive tasks that deleted test coverage undetected.

## Scope

### In Scope

**Gate & verification fixes (A1, A2, A5, A10, A12):**
- Fix auto_verify timing so it runs before checklist gate acceptance (A1)
- Require every task to have auto_verify or a verifier rubric — warn by default, hard reject when `strict_validation` is enabled (A2)
- Pre-run test health check — block task start if test suite fails; test command configured via project-level config file with convention fallback (A5)
- Pin verifier model at run creation to prevent mid-run switches (A10)
- Step-level integration tests via new `step_auto_verify` field on StepConfig; failure halts the run (A12)

**Prompt & context efficiency (A6, A7, A8, A13, A14):**
- Trim identified dead-weight prompt sections including "Avoiding Loops" — percentage target is informational only (A7)
- Migrate agent-specific instructions from shared prompt to individual agent runners (A8)
- Compress clarifications into decisions section after Q&A resolution (A6)
- Context summarization with critical-aspect preservation for `context_from`; model is configurable with a sensible cheap default (A13)
- Add guidance for keeping step_context compact (A14)

**Safety & regression guards (A4, A11):**
- Reusable test count regression guard script (A4)
- Agent escalation callback for unfulfillable requirements (A11)

**Schema & architecture extensions (A16, A17):**
- Task complexity labeling (`simple | standard`) in config schema (A16)
- Multi-file routine definitions with step-XX.yaml references (A17)

**Planning improvements (A18):**
- Ensure failure mode analysis is reflected in planner documentation (A18)

### Out of Scope

- A3 (per-requirement grading) — deprioritized by experiment D3 showing composite masking is not observed on passed tasks
- A9 (sub-agent tool for OpenHands) — longer-term capability; requires OpenHands SDK research
- A15 (golden contract tests during planning) — high effort, requires careful design to avoid fragility
- Full agent-capability-matched planning (P4 from review)
- Token budget enforcement (C3 from review — context size doesn't predict usage per D10)
- UI changes beyond displaying new fields (complexity, escalation status)

## Completion Criteria

1. **Auto-verify runs before checklist gate** — a task with failing `must: true` auto_verify items is blocked from BUILDING→VERIFYING regardless of self-reported checklist status
2. **No undefended tasks** — routine validation warns (default) or rejects (`strict_validation`) tasks that have neither auto_verify nor verifier rubric; runtime blocks auto-grade path for such tasks
3. **Test health gate** — task start is blocked if the test suite has pre-existing failures
4. **Verifier model pinned** — model is recorded at run creation and enforced on all verifier invocations within that run
5. **Prompt reduction** — identified dead-weight sections (including "Avoiding Loops") removed from shared system prompt; agent-specific instructions moved to respective runners
6. **Test regression guard** — reusable script that captures test list pre-builder and flags removals post-builder; documented for routine authors
7. **Agent escalation** — new callback type allowing agents to flag requirements as unfulfillable; API endpoint surfaces escalation to human
8. **Step-level auto_verify** — new `step_auto_verify` field on StepConfig; executed after all tasks in a step complete; failure halts the run (no auto-advance)
9. **Context summarization** — `context_from` supports `summarize: true` and `critical` fields; summaries cached per step; uses configurable model with cheap default (e.g. Haiku)
10. **Clarification compression** — resolved Q&A summarized into decisions; downstream tasks receive decisions only
11. **Multi-file routines** — loader resolves step-XX.yaml references from root routine.yaml; validation fails if a step specifies both `file` and other step fields
12. **Task complexity field** — `complexity: simple | standard` available in task config schema
13. **Planning docs updated** — step_context guidance and failure mode analysis reflected in planner documentation
14. **All existing tests pass** — no regressions in the 786+ test baseline
15. **New tests cover new functionality** — each new feature has unit and/or integration tests

## Unknowns and Risks

| Unknown | Impact | Mitigation |
|---------|--------|------------|
| Context summarization quality — can an LLM reliably preserve critical aspects? | High — lossy summaries defeat the purpose | Iterative verification loop: summarize, check critical aspects, re-summarize if missing. Start with optional opt-in, not forced. **Decided:** Use configurable model with cheap default (Haiku). |
| Multi-file YAML loading — how to handle cross-file references and validation? | Medium — invalid references fail at load time | Validate all step file references exist during routine loading; fail fast with clear error messages |
| Agent escalation UX — how should humans respond to escalations? | Medium — no response path blocks the run | Escalation pauses the run (like existing pause). Human can modify requirement, skip task, or provide guidance. |
| Pre-run test health check — what about environments with legitimately skipped tests? | Low — skipped tests are not failures | Only block on non-zero exit code from pytest; skipped tests pass. Document that tests should skip (not fail) when prerequisites are missing. |
| Clarification compression — when is summary sufficient vs. when is full context needed? | Medium — over-compression loses decisions | Preserve the decisions section verbatim; only compress raw Q&A dialogue. Downstream gets decisions + summary, not raw Q&A. |
