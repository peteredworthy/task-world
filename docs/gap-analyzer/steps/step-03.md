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
- [ ] Section 2 — "## Step Context": step title/id, current iteration (`step_state.verifier_iterations`), max iterations (`step_config.step_verifier.max_iterations`)
- [ ] Section 3 — "## Task Outcomes": for each task in `step_state.tasks` where `task.parent_task_id is None` (skip fan-out children): status, last attempt outcome, grades, auto-verify results
  - If `task.gap_report_feedback` is set, include it as "Retry feedback: {task.gap_report_feedback}" under that task's section (this feedback was injected by the gap report's retry_task action)
- [ ] Section 4 — "## Step Auto-Verify Results": render `auto_verify_results` items if present; **omit the section entirely** if `auto_verify_results` is empty (do not include an empty section header)
- [ ] Section 5 — "## Required Output": instruction to respond with JSON only; include schema: `{"assessment": "...", "verdict": "pass"|"retry"|"fix"|"fail", "actions": [...]}`
- [ ] Write a unit test in `tests/unit/test_gap_analyzer_prompts.py` confirming all sections present in output

**Dependencies**
- [ ] Step 1 complete: `StepVerifierConfig`, `GapReport`, `StepState` all defined.

**References**
- `docs/gap-analyzer/architecture.md` — prompt template specification
- `docs/gap-analyzer/step-03-plan.md` — full functional contract

**Constraints**
- The "## Required Output" section must instruct the agent to respond with JSON only — no markdown fences, no preamble.
- Function must handle `auto_verify_results=[]` gracefully — omit the "## Step Auto-Verify Results" section entirely.
- Only include root tasks (skip fan-out child tasks where `task.parent_task_id is not None`).

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

**Step A — Find the insertion point:**
- The insertion point is the `if task_state is None:` block in `_run_agent_loop` (around line 509).
  Currently it reads:
  ```python
  if task_state is None:
      logger.info(f"Run {run_id}: no pending tasks, checking run completion")
      break
  ```
  This block runs when `_find_next_task()` returns `None` — i.e., all tasks in the current step are terminal.

**Step B — Add step verifier check BEFORE the break:**
```python
if task_state is None:
    logger.info(f"Run {run_id}: no pending tasks found")

    # Check if current step has a step_verifier and needs verification
    step_index = run.current_step_index
    while step_index < len(run.steps) and run.steps[step_index].completed:
        step_index += 1
    if step_index < len(run.steps):
        current_step = run.steps[step_index]
        # Fan-out parent step check (inline — no helper function exists)
        is_fanout_parent = any(t.status == TaskStatus.FAN_OUT_RUNNING for t in current_step.tasks)
        # Only verify if: step_verifier configured, not fan-out parent, step not complete
        if (
            run.routine_embedded is not None
            and not is_fanout_parent
            and not current_step.completed
        ):
            from orchestrator.config.models import RoutineConfig
            routine_config = RoutineConfig.model_validate(run.routine_embedded)
            step_cfg = next(
                (s for s in routine_config.steps if s.id == current_step.config_id), None
            )
            if step_cfg is not None and step_cfg.step_verifier is not None:
                await self._run_step_verification(
                    run_id, current_step, step_cfg, service, agent_type, agent_config, session
                )
                continue  # loop back — if RETRY/FIX, newly-PENDING tasks will be found; if PASS/FAIL, run will be non-ACTIVE

    logger.info(f"Run {run_id}: no pending tasks, checking run completion")
    break
```
- The `continue` after `_run_step_verification` is critical: it causes the loop to re-check `run.status` (may now be PAUSED) and re-check for pending tasks (set to PENDING by retry_task).

**Step C — Implement `_run_step_verification` as a private method:**
```python
async def _run_step_verification(
    self,
    run_id: str,
    step_state: StepState,
    step_config: StepConfig,
    service: WorkflowService,
    agent_type: AgentRunnerType,
    agent_config: dict[str, Any],
    session: AsyncSession,
) -> None:
    """Run the step verifier agent and call engine lifecycle methods."""
    import json
    from pydantic import ValidationError
    from orchestrator.workflow.prompts import build_step_verifier_prompt
    from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner, run_auto_verify
    from orchestrator.state.models import GapReport, generate_id
    from orchestrator.config.enums import StepVerdict
    from datetime import datetime, timezone

    # 1. Mark step as verifying
    await service.start_step_verification(run_id, step_state.id)

    # 2. Refresh run state (start_step_verification mutated it)
    async with self._session_factory() as fresh_session:
        from orchestrator.db.repositories import RunRepository
        run = await RunRepository(fresh_session).get(run_id)
        step_state = next(s for s in run.steps if s.id == step_state.id)

    # 3. Run step-level auto_verify (if configured)
    auto_verify_results = []
    if step_config.step_verifier.auto_verify and run.worktree_path:
        from pathlib import Path
        runner = LocalAutoVerifyRunner()
        auto_verify_results = await run_auto_verify(
            step_config.step_verifier.auto_verify,
            runner,
            Path(run.worktree_path),
        )

    # 4. Build prompt
    prompt_str = build_step_verifier_prompt(step_config, step_state, auto_verify_results)

    # 5. Spawn verifier agent and collect output
    #    Use the same agent runner as step tasks.
    #    Get or create an AgentRunner instance, call execute() with a one-shot context.
    from orchestrator.runners.types import ExecutionContext
    agent = self._get_or_create_runner(agent_type, agent_config)
    collected_lines: list[str] = []
    ctx = ExecutionContext(
        run_id=run_id,
        task_id=f"step_verifier_{step_state.id}",
        worktree_path=run.worktree_path or "",
        prompt=prompt_str,
        attempt_num=step_state.verifier_iterations,
        api_base_url=self._api_base_url,
    )
    await agent.execute(
        ctx,
        on_output=lambda lines: collected_lines.extend(lines),
        on_agent_metadata=lambda _: None,
    )
    raw_output = "\n".join(collected_lines)

    # 6. Parse and validate JSON output
    try:
        data = json.loads(raw_output)
        gap_report = GapReport(
            id=generate_id(),
            iteration=step_state.verifier_iterations,
            assessment=data["assessment"],
            verdict=StepVerdict(data["verdict"]),
            actions=data.get("actions", []),
            timestamp=datetime.now(timezone.utc),
        )
    except (json.JSONDecodeError, KeyError, ValueError, ValidationError) as e:
        logger.warning(
            f"Run {run_id}: step verifier output parse failed: {e}. "
            f"Raw output: {raw_output[:500]}"
        )
        gap_report = GapReport(
            id=generate_id(),
            iteration=step_state.verifier_iterations,
            assessment=f"Parse error: {e}",
            verdict=StepVerdict.FAIL,
            actions=[],
            timestamp=datetime.now(timezone.utc),
        )

    # 7. Dispatch result to engine
    await service.complete_step_verification(run_id, step_state.id, gap_report)
```

- `_get_or_create_runner(agent_type, agent_config)` — look for this existing method in executor.py. If it doesn't exist, use the same pattern as `_execute_task` uses to create the agent runner.
- The `ExecutionContext` shape: check `src/orchestrator/runners/types.py` for the exact constructor args.

**Step D — Clear `gap_report_feedback` after builder uses it:**
- In `PhaseHandler` or the executor's builder phase: after building the prompt for a task, if `task.gap_report_feedback` is set, include it in the builder prompt preamble, then call `service.clear_gap_report_feedback(run_id, task.id)` — OR — set `task.gap_report_feedback = None` on `TaskState` before the next `_execute_task` call.
- Simpler approach: in `generate_builder_prompt()` (or the caller), check `task.gap_report_feedback`; if set, prepend "Previous attempt feedback: {feedback}\n\n" to the user prompt. Then reset via a new service call or inline mutation.

**Dependencies**
- [ ] Task 1 complete: `build_step_verifier_prompt` available.
- [ ] Step 2 complete: `start_step_verification` and `complete_step_verification` on WorkflowService working and tested.

**References**
- `docs/gap-analyzer/architecture.md` — executor pseudocode and interaction diagram
- `docs/gap-analyzer/clarifications.md` — fan-out path must not be touched; verifier uses same agent runner as step tasks
- `docs/gap-analyzer/step-03-plan.md` — full task list
- `src/orchestrator/runners/types.py` — `ExecutionContext` constructor
- `src/orchestrator/runners/executor.py` lines ~460–512 — insertion point in `_run_agent_loop`

**Constraints**
- Must not modify the fan-out parent step execution path.
- JSON parse error: log raw output at WARNING level before constructing fail-verdict `GapReport`.
- The step verification check must use `continue`, not `break`, so the loop re-checks run status.
- `is_fanout_parent` check is inline (`any(t.status == FAN_OUT_RUNNING for t in step.tasks)`) — there is no `is_fanout_parent_step()` helper function in the codebase.

**Functionality (Expected Outcomes)**
- [ ] Executor calls `start_step_verification` and `complete_step_verification` when `step_verifier` is configured
- [ ] JSON parse error path produces a `fail`-verdict `GapReport` with `assessment` describing the error
- [ ] Raw agent output logged when parse fails
- [ ] After RETRY/FIX verdict, the loop `continue`s and picks up newly-PENDING tasks
- [ ] `gap_report_feedback` is injected into builder prompt for retried tasks

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/ -v` — no regressions from executor changes
- [ ] Manual confirmation: fan-out parent step path code section is unmodified (no `step_verifier` branch in fan-out code)
- [ ] Manual confirmation: JSON parse error path logs raw output and constructs fail-verdict report
