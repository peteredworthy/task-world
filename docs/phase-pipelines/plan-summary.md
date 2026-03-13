# Plan Summary: Configurable Phase Pipelines

Date: 2026-03-13
Status: Ready for implementation

---

## Intent Satisfaction Summary

The feature replaces the hardcoded `build → verify` two-phase cycle with a configurable
per-task phase sequence. Task authors can define arbitrary phase chains in routine YAML;
the existing two-phase cycle becomes a synthesized special case. New phase types (`plan`,
`summarize`, `gap_check`, `script`, `auto_verify`, `human_review`) compose freely within
a task. Existing routines without a `phases` field continue working without modification.

All 18 items in the Definition of Complete from `intent.md` are covered across the five
step files. All five planning/clarification/architecture questions were resolved without
requiring human input. The dry-run analysis identified 12 implementation gaps; all have
been applied as targeted constraints in the step files. A verification report confirms all
requirements pass and the plan is ready for execution.

---

## Ordered Step List with Task Counts

| Step | Milestone | Tasks | Focus |
|------|-----------|-------|-------|
| Step 1 | Config Models + Enums | 4 | `PhaseType` enum, `PhaseConfig` model, `TaskConfig.phases` field, unit tests |
| Step 2 | State, DB, and Factory | 5 | `TaskState` fields, Alembic migration, `repositories.py` mapping, phase synthesis, `PhaseStarted`/`PhaseCompleted` events, unit tests |
| Step 3 | Engine Lifecycle | 5 | `advance_phase`, `complete_phase`, verify `retry_target`, `WorkflowService._with_phases`, persistence, unit tests |
| Step 4 | Executor, Prompts, and API | 5 | Phase dispatch loop, prompt builders, API schema additions, router serialization, integration tests |
| Step 5 | Frontend | 6 | TypeScript types, `PhaseIndicator` component, `TaskDetailCard` updates, `StepTimeline` mini dots, `ActivityFeed` phase events, frontend tests |

**Total: 25 tasks across 5 steps.**

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| `TaskStatus` enum | Keep existing values (`BUILDING`, `VERIFYING`); add `current_phase_type` for fine-grained display | Zero DB enum migration; API consumers relying on `BUILDING`/`VERIFYING` continue working |
| Backward compatibility | Synthesize phases in `factory.py`; engine always uses `phases_config` | Single code path after synthesis; no if/else branches in engine for new vs old tasks |
| `retry_target` default | Phase immediately before the verify phase | Matches current behavior (always retries the build phase) |
| Phase output storage | `phase_outputs: dict[int, str]` on `TaskState`, JSON in DB | Keyed by index; survives phase skips; simple to inject into subsequent phase prompts |
| `phases_config` persistence | Not stored in DB — re-synthesized from `routine_embedded` on load | Config is derivable; avoids duplicating routine YAML in tasks table |
| Condition evaluation | Reuse existing conditional-steps `ConditionEvaluator` from Option C | Already implemented; consistent behavior; no new DSL |
| `fan_out` compatibility | `phases` is mutually exclusive with `fan_out`; fan-out subtask phases deferred | Separate executor path; mixing adds complexity without a clear current use case |
| Pipeline agent phase dispatch | Bypass `PhaseHandler.execute_phase()` string routing; call `agent.execute()` directly | `PhaseHandler` only accepts `-ing` suffix strings (`"building"`, `"verifying"`) — direct call avoids string mismatch and wrong terminal behavior |
| Pipeline verify phase | Split pass/fail paths: PASS → `complete_phase(output)`; FAIL → `complete_verification()` | Avoids double-transition bug where `complete_verification()` and `complete_phase()` both mutate task state |

---

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| `repositories.py` is actual persistence layer, not `WorkflowService` | Critical | Step files explicitly name `_to_domain()` and `_to_model()` in `repositories.py`; "NOT service.py" constraint added |
| `phases_config` is `None` after DB reload | Critical | `WorkflowService._with_phases(run, task)` helper re-synthesizes from `routine_embedded`; must be called before any engine or executor code reads `phases_config` |
| No `BUILDING → COMPLETED` transition exists | Critical | `transition_to_completed_direct` function + `VALID_TRANSITIONS` update + `_complete_phase_pipeline_task` engine method specified in step-03.md T1 |
| `PhaseHandler` string mismatch + wrong terminal behavior for pipeline agent phases | Critical | Do not route through `_execute_building`; call `agent.execute()` directly and then `engine.complete_phase()` |
| Double-transition bug for pipeline verify phases | Critical | PASS path calls `complete_phase(output)`; FAIL path calls `complete_verification()` — never both |
| `ConditionEvaluator` called with wrong context | High | Exact variables dict specified: `{str(i): output for i, output in task.phase_outputs.items()}`; `step_outcomes = {}` |
| Second `@model_validator` silently overrides the first | High | Step files instruct to EXTEND the existing validator body, not add a new method |
| Resume logic placed in wrong method (`start_task` instead of executor) | High | step-03.md T3 explicitly says "Do NOT modify `start_task()`"; step-04.md T1 specifies loop starts at `task.current_phase_index` |
| `phase_outputs` int-key coercion on DB read | Medium | JSON round-trips integer keys as strings; `_to_domain()` must apply `{int(k): v ...}` coercion |
| `PhaseCompleted` event uses wrong field (`output_length` from plan.md instead of `output: str`) | Medium | step-02.md T2 constraint specifies `output: str` is correct |
| Integration tests assert only scenario names, not values | Medium | All 10 integration test cases have explicit `Assert:` clauses with field names and expected values |
| Frontend test path uses non-existent `ui/src/__tests__/` directory | Low | Corrected to `ui/src/components/detail/__tests__/` in step-05.md |
| Phase prompt context too large (many prior outputs) | Medium | Truncate each prior output to 2000 chars in prompt builder; full text available via `phase_outputs` in API |
| Alembic migration on live DB | Low | Additive columns with server defaults; test migration against existing `orchestrator.db` before deploying |

---

## Caveats for Execution

1. **`architecture.md` is NOT authoritative** — it contains two known errors (Gap 5: `output_length` vs `output: str` on `PhaseCompleted`; Gap 3: wrong synthesis check order). The step files override `architecture.md` wherever there is a conflict. Implementers must follow the step files.

2. **Synthesis check order matters** — `_warn_if_no_verification` can auto-generate a rubric from `requirements`. In factory synthesis logic, check `auto_verify.items` BEFORE `verifier.rubric` to avoid tasks being incorrectly classified as `[build, verify]` when they should be `[build, auto_verify]`.

3. **Unit test fixture for `test_synthesize_build_auto_verify`** — use `requirements=[]` (empty) to prevent auto-rubric generation from converting the expected `[build, auto_verify]` output to `[build, verify]`.

4. **`_with_phases` must be called eagerly** — any code path that reads `task.phases_config` (engine, executor) must ensure `_with_phases` has been called first. After a DB reload, `phases_config` is always `None` until re-synthesized.

5. **`PromptResponse` already has `phase` field** — the new `phase_type` field must be added alongside `phase` without removing it. Document the relationship: `phase` reflects the high-level task status context (e.g., `"building"`, `"verifying"`); `phase_type` reflects the specific pipeline phase type (e.g., `"plan"`, `"gap_check"`).

6. **Fan-out tasks skip phase synthesis entirely** — no `phases_config` is set for fan-out tasks; the existing fan-out executor path handles them unchanged.

7. **Backward compatibility is the default path** — all existing routines without a `phases` field go through synthesis. The synthesized `phases_config` is functionally identical to today's hardcoded `build → verify` behavior. This must be validated by `test_backward_compat_no_phases` with concrete assertions.

---

## References

- [intent.md](intent.md) — Feature specification and Definition of Complete
- [plan.md](plan.md) — Five-milestone implementation plan
- [architecture.md](architecture.md) — Architecture overview (see caveats above)
- [clarifications.md](clarifications.md) — Design question resolutions
- [dry-run-notes.md](dry-run-notes.md) — 12 implementation gaps and analysis
- [verification-report.md](verification-report.md) — Readiness confirmation
- [steps/step-01.md](steps/step-01.md) through [steps/step-05.md](steps/step-05.md) — Authoritative per-step task specifications
