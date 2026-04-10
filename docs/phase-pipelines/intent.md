# Intent: Configurable Phase Pipelines

## Original Request

Replace the hardcoded builder→verifier two-phase cycle with a configurable per-task phase sequence. Every task currently follows BUILDING → VERIFYING. Making phases explicit and configurable enables planning phases before building, summarization after, gap-checks between build and verify, and tasks with a single phase (script-only, auto-verify-only). [S-01/T-01/R1, S-01/T-02/R1, S-01/T-03/R1]

## Goal

Enable task authors to define arbitrary phase chains in routine YAML. [S-01/T-03/R1] The current `build → verify` cycle becomes a special case of the general phase pipeline system. [S-02/T-05/R1] New phase types — `plan`, `summarize`, `gap-check`, `script`, `auto-verify`, `human-review` — compose freely within a task. [S-04/T-01/R2] Existing routines without a `phases` field continue working without modification. [S-02/T-05/R1, S-04/T-01/R3]

## Scope

### In Scope

- **`PhaseType` enum** — `build`, `verify`, `plan`, `summarize`, `gap_check`, `script`, `auto_verify`, `human_review` in `src/orchestrator/config/enums.py`. [S-01/T-01/R1]
- **`PhaseConfig` model** — `type: PhaseType`, `prompt: str | None`, `profile: ModelProfile | None`, `condition: str | None`, `cmd: str | None` (script type), `retry_target: int | None` (verify type) in `src/orchestrator/config/models.py`. [S-01/T-02/R1]
- **`phases` field on `TaskConfig`** — `phases: list[PhaseConfig] | None = None`. If `None`, existing behavior (synthesize `[build, verify]` from `task_context`/`verifier` fields) is preserved. [S-01/T-03/R1, S-02/T-05/R1]
- **Phase synthesis** — factory logic in `src/orchestrator/state/factory.py`: `task_context + verifier → [build, verify]`, `task_context + auto_verify (no verifier) → [build, auto_verify]`, `task_context only (no verifier, no auto_verify) → [build]`, `script → [script]`. [S-02/T-05/R1, S-02/T-05/R2]
- **`TaskState` phase tracking** — add `current_phase_index: int = 0`, `phase_outputs: dict[int, str] = {}`, `phases_config: list[PhaseConfig] | None = None` to `TaskState` in `src/orchestrator/state/models.py`. [S-02/T-01/R1, S-02/T-01/R2]
- **`TaskModel` DB columns** — `current_phase_index` (Integer), `phase_outputs` (JSON) via Alembic migration. [S-02/T-03/R1, S-02/T-03/R2, S-02/T-03/R3]
- **`PhaseStarted` and `PhaseCompleted` events** — with `phase_type`, `phase_index` fields in `src/orchestrator/workflow/events.py`. [S-02/T-02/R1, S-02/T-02/R2]
- **Phase-aware engine methods** — `advance_phase()`, `complete_phase()` in `WorkflowEngine`; `start_task()` starts at `current_phase_index` (or `retry_target` on revision); verify failure loops to `retry_target` instead of always to `BUILDING`. [S-03/T-01/R1, S-03/T-02/R1, S-03/T-03/R1, S-03/T-03/R2]
- **Phase-specific prompts** — `build_phase_prompt()` for plan, summarize, gap-check types in `src/orchestrator/workflow/prompts.py`; prior phase outputs injected as context. [S-04/T-02/R1, S-04/T-02/R2, S-04/T-02/R3]
- **Executor phase dispatch** — agent phases (plan/build/verify/summarize/gap_check) → spawn agent with profile override; script → run `cmd` via subprocess; auto_verify → run `AutoVerifyRunner`; human_review → transition to `PENDING_USER_ACTION`. [S-04/T-01/R1, S-04/T-01/R2, S-04/T-01/R4, S-04/T-01/R5]
- **`current_phase_type` tracking** — exposed as a field on `TaskState`/`TaskDetailResponse`; maps phase types to existing `TaskStatus` (`BUILDING` for agent phases except verify, `VERIFYING` for verify phases) for backward compatibility. [S-02/T-01/R2, S-04/T-03/R1, S-04/T-03/R3]
- **API schema additions** — `current_phase_index`, `current_phase_type`, `phase_count`, `phase_outputs` on `TaskDetailResponse`; `phase_type` on `PromptResponse`. [S-04/T-03/R1, S-04/T-03/R2, S-04/T-03/R3, S-04/T-03/R4]
- **Frontend phase progress indicator** — new component showing horizontal phase chain (completed/active/pending) in `TaskDetailCard.tsx`; phase-type-colored dots in `StepTimeline.tsx` task badges; phase events in `ActivityFeed.tsx`. [S-05/T-02/R1, S-05/T-02/R2, S-05/T-03/R1, S-05/T-03/R3, S-05/T-04/R1, S-05/T-04/R2]
- **Tests** — unit tests for `PhaseConfig` validation, phase synthesis, advance logic, context passing; integration tests for plan→build→verify chain, script-only task, verify `retry_target`, conditional phase skip, backward compatibility; frontend tests for phase indicator and phase-aware status display. [S-01/T-04/R1, S-02/T-05/R4, S-03/T-05/R1, S-04/T-04/R1, S-05/T-05/R1, S-05/T-05/R2, S-05/T-05/R3]

### Out of Scope

- Migrating all existing routines to the explicit `phases` format — backward compatibility keeps the old path working; migration is a follow-up. [NO-REQ: out of scope by design; backward compat is tested in S-04/T-04/R2 but migration itself is not required]
- Dynamic phase insertion at runtime (phases set at config time, not during execution). [NO-REQ: explicitly excluded from scope]
- Cross-task phase context sharing — `phase_outputs` is per-task only. [NO-REQ: explicitly excluded from scope]
- Option B (step verifier), Option C (conditional steps — already done), Option D (orchestrated expansion) — independent efforts; phase pipelines compose with them but don't depend on them. [NO-REQ: separate feature efforts]
- Fan-out tasks with custom phase pipelines — fan-out is an existing task mode; phase pipeline support for fan-out subtasks is deferred. [S-01/T-03/R2, S-02/T-05/R1]

## Key Unknowns / Risks

| Unknown | Impact | Mitigation |
|---------|--------|-----------|
| `TaskStatus` enum backward compatibility | High — `BUILDING`/`VERIFYING` are serialized in DB and API | Map all agent phases to `BUILDING`, verify phases to `VERIFYING`; add `current_phase_type` for fine-grained display without changing status values [S-04/T-03/R1, S-04/T-01/R3] |
| Conditional phase evaluation at runtime | Medium — condition expressions must be evaluated against run config | Reuse existing condition evaluation from conditional steps (Option C already implemented) [S-03/T-01/R2] |
| Phase context size in prompts | Medium — many prior phase outputs could overflow token limits | Summarize long outputs; cap via `max_tokens` option on phase config (deferred); for now, include raw output with truncation [S-04/T-02/R3] |
| Alembic migration on live DB | Low — additive columns with defaults | Test migration against existing `orchestrator.db` before deploying [S-02/T-03/R3] |
| `script` phase failure handling | Medium — script exit code != 0 should fail the task or loop to retry | Treat non-zero exit as phase failure; if verify `retry_target` points back, loop; otherwise fail the task [S-04/T-01/R2] |
| Phase prompt for `gap_check` type | Low — new prompt template needed | Model after existing verifier prompt; include build output, task context, required gap assessment output [S-04/T-02/R1] |

## Definition of Complete

- [ ] `PhaseType` enum exists in `config/enums.py` with all 8 values. [S-01/T-01/R1]
- [ ] `PhaseConfig` Pydantic model exists in `config/models.py`. [S-01/T-02/R1]
- [ ] `TaskConfig` has optional `phases: list[PhaseConfig] | None = None`; existing validator updated to allow `phases` to co-exist with (or replace) `task_context`/`verifier`/`script`. [S-01/T-03/R1, S-01/T-03/R5]
- [ ] Phase synthesis in `state/factory.py`: tasks without `phases` get synthesized pipeline; existing routines unaffected. [S-02/T-05/R1, S-02/T-05/R2]
- [ ] `TaskState` has `current_phase_index`, `phase_outputs`, `phases_config` fields. [S-02/T-01/R1]
- [ ] Alembic migration adds `current_phase_index` and `phase_outputs` to `tasks` table. [S-02/T-03/R1, S-02/T-03/R2]
- [ ] `PhaseStarted` and `PhaseCompleted` event types exist and are emitted. [S-02/T-02/R1, S-02/T-02/R2, S-03/T-01/R1, S-03/T-02/R1]
- [ ] `WorkflowEngine.advance_phase()` and `complete_phase()` exist; verify failure respects `retry_target`. [S-03/T-01/R1, S-03/T-02/R1, S-03/T-03/R1, S-03/T-03/R2]
- [ ] Phase-specific prompts generated for plan, summarize, gap-check types; prior phase outputs injected. [S-04/T-02/R1, S-04/T-02/R3]
- [ ] Executor dispatches correctly for all phase types (agent, script, auto_verify, human_review). [S-04/T-01/R2]
- [ ] `TaskDetailResponse` includes `current_phase_index`, `current_phase_type`, `phase_count`, `phase_outputs`. [S-04/T-03/R1, S-04/T-03/R3]
- [ ] `PromptResponse` includes `phase_type`. [S-04/T-03/R2, S-04/T-03/R4]
- [ ] Frontend phase progress indicator renders in `TaskDetailCard.tsx`. [S-05/T-02/R2, S-05/T-03/R1]
- [ ] `StepTimeline.tsx` shows mini phase dots for active tasks. [S-05/T-03/R3]
- [ ] `ActivityFeed.tsx` renders `PhaseStarted`/`PhaseCompleted` events. [S-05/T-04/R1, S-05/T-04/R2]
- [ ] Unit tests: `PhaseConfig` validation, synthesis, advance logic, context passing — all pass. [S-01/T-04/R1, S-02/T-05/R4, S-03/T-05/R1]
- [ ] Integration tests: plan→build→verify chain, script-only task, `retry_target`, conditional skip, backward compat — all pass. [S-04/T-04/R1, S-04/T-04/R2]
- [ ] Frontend tests: phase indicator, status display — all pass. [S-05/T-05/R1, S-05/T-05/R2, S-05/T-05/R3]
- [ ] All existing tests continue to pass (no regressions). [S-04/T-05/R2, S-05/T-05/R3]
- [ ] `uv run pre-commit run --all-files` passes. [S-04/T-05/R1]
