"""Phase-aware agent execution handler.

Given a ready ``ExecutionContext`` and phase, wires the appropriate callbacks
and invokes ``agent.execute()``, then stores results via ``AttemptStore``.

Extracted from ``AgentRunnerExecutor._execute_task``, ``_handle_verification``,
and ``_handle_recovery`` -- preserves exact same logic and error handling.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from orchestrator.config.enums import ChecklistStatus, RunStatus, TaskStatus
from orchestrator.runners.execution.usage import extract_metrics_and_usage
from orchestrator.runners.types import ExecutionContext, ExecutionMetrics
from orchestrator.state.models import ModelTokenUsage

if TYPE_CHECKING:
    from orchestrator.runners.execution.attempt_store import AttemptStore
    from orchestrator.runners.execution.event_broadcaster import EventBroadcaster
    from orchestrator.runners.execution.output_batcher import OutputBatcher
    from orchestrator.runners.interface import AgentRunner
    from orchestrator.state.models import Run, TaskState
    from orchestrator.workflow.service import WorkflowService

logger = logging.getLogger(__name__)


class PhaseHandler:
    """Invoke an agent for a given phase and persist the results."""

    def __init__(
        self,
        attempt_store: "AttemptStore",
        event_broadcaster: "EventBroadcaster",
        api_base_url: str = "http://localhost:8000",
        output_batcher: "OutputBatcher | None" = None,
    ) -> None:
        self._attempt_store = attempt_store
        self._broadcaster = event_broadcaster
        self._api_base_url = api_base_url
        self._output_batcher = output_batcher

    # ------------------------------------------------------------------
    # Metrics helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_metrics_and_usage(
        result: Any,
    ) -> tuple[ExecutionMetrics, list[ModelTokenUsage]]:
        """Delegate to the shared, carrier-agnostic usage extractor.

        Kept as a thin method so existing call sites are unchanged; the logic is
        shared with the graph dispatch path via ``runners.execution.usage``.
        """
        return extract_metrics_and_usage(result)

    @staticmethod
    def _execution_model_name(
        result: Any,
        token_usage_by_model: list[ModelTokenUsage],
        agent: "AgentRunner",
    ) -> str:
        if token_usage_by_model:
            return token_usage_by_model[0].model
        action_log = getattr(result, "action_log", None)
        if action_log is not None and getattr(action_log, "agent_model", None):
            return action_log.agent_model
        try:
            return agent.info.name or "unknown"
        except Exception:
            return "unknown"

    @staticmethod
    def _agent_runner_type_value(agent: "AgentRunner", explicit_value: str = "") -> str:
        if explicit_value:
            return explicit_value
        try:
            return agent.info.agent_runner_type.value
        except Exception:
            return "unknown"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def execute_phase(
        self,
        *,
        phase: str,
        run: "Run",
        task_state: "TaskState",
        service: "WorkflowService | None",
        agent: "AgentRunner",
        context: ExecutionContext,
        req_desc_to_id: dict[str, str],
        agent_runner_type_value: str = "",
        session: Any = None,
    ) -> None:
        """Execute the agent for a single phase (building / verifying / recovering).

        Args:
            phase: One of ``"building"``, ``"verifying"``, ``"recovering"``.
            run: The current Run state object.
            task_state: The task being executed.
            service: WorkflowService for state transitions.
            agent: The agent instance to execute.
            context: Ready-to-use ExecutionContext (prompt, working_dir, etc.).
            req_desc_to_id: Mapping of lowercase requirement descriptions to IDs
                            for fuzzy-match fallback.
            agent_runner_type_value: String label for the agent runner type (used in error messages).
            session: Optional DB session (forwarded to ``store_attempt_prompt``
                     in the building phase to avoid StaticPool issues).
        """
        if phase == "building":
            await self._execute_building(
                run,
                task_state,
                service,
                agent,
                context,
                req_desc_to_id,
                agent_runner_type_value=agent_runner_type_value,
                session=session,
            )
        elif phase == "verifying":
            assert service is not None, "service is required for verifying phase"
            await self._execute_verifying(
                run,
                task_state,
                service,
                agent,
                context,
                req_desc_to_id,
                agent_runner_type_value=agent_runner_type_value,
                session=session,
            )
        elif phase == "recovering":
            assert service is not None, "service is required for recovering phase"
            await self._execute_recovering(
                run,
                task_state,
                service,
                agent,
                context,
                agent_runner_type_value=agent_runner_type_value,
            )
        else:
            raise ValueError(f"Unknown phase: {phase}")

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------

    async def _execute_building(
        self,
        run: "Run",
        task_state: "TaskState",
        service: "WorkflowService | None",
        agent: "AgentRunner",
        context: ExecutionContext,
        req_desc_to_id: dict[str, str],
        agent_runner_type_value: str = "",
        session: Any = None,
    ) -> None:
        from orchestrator.runners.errors import AgentExecutionError
        from orchestrator.workflow import GateBlockedError

        # Store the builder prompt BEFORE agent execution.
        await self._attempt_store.store_attempt_prompt(
            run.id, task_state.id, builder_prompt=context.prompt, session=session
        )

        # Define callbacks that use the service
        async def on_checklist_update(
            req_id: str, status: ChecklistStatus, note: str | None
        ) -> None:
            if service is None:
                return
            actual_id = req_id
            if req_id.lower().strip() in req_desc_to_id:
                actual_id = req_desc_to_id[req_id.lower().strip()]
            await service.update_checklist_item(run.id, task_state.id, actual_id, status, note)

        async def on_submit() -> None:
            if service is None:
                return
            # Flush buffered output before the task transitions out of BUILDING
            if self._output_batcher is not None:
                await self._output_batcher.flush_immediate()
            # The builder agent may have already called submit via REST/MCP
            # during execution (a separate session).  Expire the shared session's
            # identity map so the status check below hits the DB, not a stale
            # cache.  Without this, expire_on_commit=False leaves the task looking
            # BUILDING even though the REST submit already moved it to VERIFYING
            # (and bumped its version), causing a StaleDataError when we try to
            # flush the same task a second time.
            if session is not None:
                session.expire_all()
            # If the run paused mid-attempt (e.g. requirement_escalated,
            # awaiting_clarification, manual_pause), don't try to submit. The
            # CLI exited cleanly because the agent acknowledged the pause; a
            # post-exit submit would only raise InvalidTransitionError.
            current_run = await service.get_run(run.id)
            if current_run.status != RunStatus.ACTIVE:
                logger.info(
                    f"Run {run.id}: status is {current_run.status.value} "
                    f"(pause_reason={current_run.pause_reason!r}); skipping "
                    f"post-exit submit for task {task_state.id}"
                )
                return
            current_task = await service.get_task(run.id, task_state.id)
            if current_task.status != TaskStatus.BUILDING:
                logger.info(
                    f"Task {task_state.id}: already transitioned to "
                    f"{current_task.status.value}, skipping redundant submit"
                )
                return
            await service.submit_for_verification(run.id, task_state.id)

        # Define output streaming callback
        attempt_num_building = task_state.current_attempt + 1

        async def on_output(lines: list[str]) -> None:
            if self._output_batcher is not None:
                for line in lines:
                    await self._output_batcher.add_line(
                        run.id, task_state.id, attempt_num_building, line
                    )

        # Define agent metadata callback
        async def on_agent_metadata(metadata: dict[str, Any]) -> None:
            await self._attempt_store.persist_agent_metadata(run.id, metadata)

        # Define escalation callback
        async def on_escalation(requirement_id: str, reason: str) -> None:
            if service is None:
                return
            await service.escalate_requirement(run.id, task_state.id, requirement_id, reason)

        # Execute the agent
        logger.info(f"Task {task_state.id}: starting builder agent")
        try:
            result = await agent.execute(
                context,
                on_checklist_update,
                on_submit,
                on_output=on_output,
                on_grade=None,
                on_agent_metadata=on_agent_metadata,
                on_escalation=on_escalation,
            )
        except GateBlockedError:
            logger.warning("Agent submit blocked by gate - task remains BUILDING, will retry")
            if self._output_batcher is not None:
                await self._output_batcher.flush_immediate()
            return

        # Flush any remaining buffered output before storing final results
        if self._output_batcher is not None:
            await self._output_batcher.flush_immediate()

        # Store agent metadata (PID, etc.) in run's agent_runner_config
        if result.agent_metadata:
            run.agent_runner_config = {**run.agent_runner_config, **result.agent_metadata}

        # Extract metrics and per-model token usage from action_log
        metrics, token_usage_by_model = self._extract_metrics_and_usage(result)
        resolved_agent_runner_type = self._agent_runner_type_value(agent, agent_runner_type_value)

        # Store agent output, action log, and metrics on attempt
        await self._attempt_store.store_attempt_output(
            run.id,
            task_state.id,
            result.output_lines,
            result.error,
            result.action_log,
            phase="building",
            agent_runner_type=resolved_agent_runner_type,
        )
        await self._attempt_store.store_attempt_metrics(
            run.id,
            task_state.id,
            metrics,
            token_usage_by_model=token_usage_by_model,
            phase="building",
            agent_runner_type=resolved_agent_runner_type,
            model_name=self._execution_model_name(result, token_usage_by_model, agent),
            mode_tag=context.work_mode,
        )

        if not result.success:
            raise AgentExecutionError(
                agent_runner_type=resolved_agent_runner_type,
                message=result.error or "Agent execution returned unsuccessful result",
            )

        logger.info(f"Task {task_state.id}: builder execution complete, success={result.success}")

    # ------------------------------------------------------------------
    # Verifying
    # ------------------------------------------------------------------

    async def _execute_verifying(
        self,
        run: "Run",
        task_state: "TaskState",
        service: "WorkflowService",
        agent: "AgentRunner",
        context: ExecutionContext,
        req_desc_to_id: dict[str, str],
        agent_runner_type_value: str = "",
        session: Any = None,
    ) -> None:
        # Store the verifier prompt BEFORE agent execution
        await self._attempt_store.store_attempt_prompt(
            run.id, task_state.id, verifier_prompt=context.prompt
        )

        # Define callbacks for verifier
        async def on_checklist_update(
            req_id: str, status: ChecklistStatus, note: str | None
        ) -> None:
            actual_id = req_id
            if req_id.lower().strip() in req_desc_to_id:
                actual_id = req_desc_to_id[req_id.lower().strip()]
            await service.update_checklist_item(run.id, task_state.id, actual_id, status, note)

        async def on_complete() -> None:
            # Flush buffered output before the task transitions out of VERIFYING
            if self._output_batcher is not None:
                await self._output_batcher.flush_immediate()
            # Expire shared session's identity map so status checks below
            # hit the DB rather than a stale cache.  The verifier agent may
            # have already called complete_verification via REST (a separate
            # session that bumped the task version); without this, the identity
            # map would return stale VERIFYING status and trigger a duplicate
            # complete_verification → StaleDataError on flush.
            if session is not None:
                session.expire_all()
            current_run = await service.get_run(run.id)
            if current_run.status != RunStatus.ACTIVE:
                logger.info(
                    f"Task {task_state.id}: run already {current_run.status.value}, "
                    f"skipping redundant complete_verification"
                )
                return

            current_task = await service.get_task(run.id, task_state.id)
            if current_task.status != TaskStatus.VERIFYING:
                logger.info(
                    f"Task {task_state.id}: already transitioned to "
                    f"{current_task.status.value}, skipping redundant complete_verification"
                )
                return

            # Fallback: if verifier is completing but didn't set any grades,
            # auto-grade all requirements as "A".
            ungraded = [item for item in current_task.checklist if item.grade is None]
            if ungraded:
                logger.warning(
                    f"Task {task_state.id}: verifier completing but "
                    f"{len(ungraded)} requirements have no grade -- auto-grading as A"
                )
                for item in ungraded:
                    await service.set_grade(
                        run.id,
                        task_state.id,
                        item.req_id,
                        "A",
                        "Auto-graded: verifier agent exited successfully without setting grade",
                    )
            await service.complete_verification(run.id, task_state.id)

        async def on_grade(req_id: str, grade: str, grade_reason: str | None) -> None:
            actual_id = req_id
            if req_id.lower().strip() in req_desc_to_id:
                actual_id = req_desc_to_id[req_id.lower().strip()]
            await service.set_grade(run.id, task_state.id, actual_id, grade, grade_reason)

        # Define output streaming callback
        attempt_num_verifying = task_state.current_attempt

        async def on_output(lines: list[str]) -> None:
            if self._output_batcher is not None:
                for line in lines:
                    await self._output_batcher.add_line(
                        run.id, task_state.id, attempt_num_verifying, line
                    )

        # Define agent metadata callback
        async def on_agent_metadata(metadata: dict[str, Any]) -> None:
            await self._attempt_store.persist_agent_metadata(run.id, metadata)

        # Define escalation callback
        async def on_escalation(requirement_id: str, reason: str) -> None:
            await service.escalate_requirement(run.id, task_state.id, requirement_id, reason)

        # Execute the verifier agent
        result = await agent.execute(
            context,
            on_checklist_update,
            on_complete,
            on_output=on_output,
            on_grade=on_grade,
            on_agent_metadata=on_agent_metadata,
            on_escalation=on_escalation,
        )

        # Flush any remaining buffered output before storing final results
        if self._output_batcher is not None:
            await self._output_batcher.flush_immediate()

        # Store agent metadata
        if result.agent_metadata:
            run.agent_runner_config = {**run.agent_runner_config, **result.agent_metadata}

        # Extract metrics and per-model token usage from action_log
        metrics, token_usage_by_model = self._extract_metrics_and_usage(result)

        # Store agent output, action log, and metrics on attempt
        await self._attempt_store.store_attempt_output(
            run.id,
            task_state.id,
            result.output_lines,
            result.error,
            result.action_log,
            phase="verifying",
            agent_runner_type=self._agent_runner_type_value(agent, agent_runner_type_value),
        )
        await self._attempt_store.store_attempt_metrics(
            run.id,
            task_state.id,
            metrics,
            token_usage_by_model=token_usage_by_model,
            phase="verifying",
            agent_runner_type=self._agent_runner_type_value(agent, agent_runner_type_value),
            model_name=self._execution_model_name(result, token_usage_by_model, agent),
            mode_tag=context.work_mode,
        )

        logger.info(f"Task {task_state.id}: verifier execution complete, success={result.success}")

    # ------------------------------------------------------------------
    # Recovering
    # ------------------------------------------------------------------

    async def _execute_recovering(
        self,
        run: "Run",
        task_state: "TaskState",
        service: "WorkflowService",
        agent: "AgentRunner",
        context: ExecutionContext,
        agent_runner_type_value: str = "",
    ) -> None:
        # Store the recovery prompt on the verifier-side prompt field so
        # recovering artifacts capture the prompt for this execution phase.
        await self._attempt_store.store_attempt_prompt(
            run.id, task_state.id, verifier_prompt=context.prompt
        )

        # Define callbacks - recovery agent uses complete_recovery via dynamic tool
        async def on_checklist_update(  # pragma: no cover
            req_id: str, status: ChecklistStatus, note: str | None
        ) -> None:
            pass  # Recovery agent does not update checklist directly

        async def on_submit() -> None:  # pragma: no cover
            pass  # Recovery agent uses complete_recovery, not submit

        # Define output streaming callback
        attempt_num_recovering = task_state.current_attempt

        async def on_output(lines: list[str]) -> None:
            if self._output_batcher is not None:
                for line in lines:
                    await self._output_batcher.add_line(
                        run.id, task_state.id, attempt_num_recovering, line
                    )

        # Define agent metadata callback
        async def on_agent_metadata(metadata: dict[str, Any]) -> None:
            await self._attempt_store.persist_agent_metadata(run.id, metadata)

        # Execute the recovery agent
        logger.info(f"Task {task_state.id}: starting recovery agent")
        result = await agent.execute(
            context,
            on_checklist_update,
            on_submit,
            on_output=on_output,
            on_grade=None,
            on_agent_metadata=on_agent_metadata,
        )

        # Flush any remaining buffered output before storing final results
        if self._output_batcher is not None:
            await self._output_batcher.flush_immediate()

        # Store agent metadata
        if result.agent_metadata:
            run.agent_runner_config = {**run.agent_runner_config, **result.agent_metadata}

        # Extract metrics and per-model token usage from action_log
        metrics, token_usage_by_model = self._extract_metrics_and_usage(result)

        # Store agent output, action log, and metrics on attempt
        await self._attempt_store.store_attempt_output(
            run.id,
            task_state.id,
            result.output_lines,
            result.error,
            result.action_log,
            phase="recovering",
            agent_runner_type=self._agent_runner_type_value(agent, agent_runner_type_value),
        )
        await self._attempt_store.store_attempt_metrics(
            run.id,
            task_state.id,
            metrics,
            token_usage_by_model=token_usage_by_model,
            phase="recovering",
            agent_runner_type=self._agent_runner_type_value(agent, agent_runner_type_value),
            model_name=self._execution_model_name(result, token_usage_by_model, agent),
            mode_tag=context.work_mode,
        )

        logger.info(f"Task {task_state.id}: recovery execution complete, success={result.success}")
