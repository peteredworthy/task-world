"""Phase-aware agent execution handler.

Given a ready ``ExecutionContext`` and phase, wires the appropriate callbacks
and invokes ``agent.execute()``, then stores results via ``AttemptStore``.

Extracted from ``AgentRunnerExecutor._execute_task``, ``_handle_verification``,
and ``_handle_recovery`` -- preserves exact same logic and error handling.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from orchestrator.config.enums import ChecklistStatus, RunStatus, TaskStatus
from orchestrator.runners.types import ExecutionContext, ExecutionMetrics
from orchestrator.workflow import AgentOutputEvent

if TYPE_CHECKING:
    from orchestrator.runners.execution.attempt_store import AttemptStore
    from orchestrator.runners.execution.event_broadcaster import EventBroadcaster
    from orchestrator.runners.interface import AgentRunner
    from orchestrator.state.models import Run, TaskState
    from orchestrator.workflow.service import WorkflowService

logger = logging.getLogger(__name__)


class PhaseHandler:
    """Invoke an agent for a given phase and persist the results."""

    def __init__(
        self,
        attempt_store: AttemptStore,
        event_broadcaster: EventBroadcaster,
        api_base_url: str = "http://localhost:8000",
    ) -> None:
        self._attempt_store = attempt_store
        self._broadcaster = event_broadcaster
        self._api_base_url = api_base_url

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
        agent_type_value: str = "",
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
            agent_type_value: String label for the agent type (used in error messages).
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
                agent_type_value=agent_type_value,
                session=session,
            )
        elif phase == "verifying":
            assert service is not None, "service is required for verifying phase"
            await self._execute_verifying(run, task_state, service, agent, context, req_desc_to_id)
        elif phase == "recovering":
            assert service is not None, "service is required for recovering phase"
            await self._execute_recovering(run, task_state, service, agent, context)
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
        agent_type_value: str = "",
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
            # The builder agent may have already called submit via REST/MCP
            # during execution.  Re-read the task to avoid a redundant call.
            current_task = await service.get_task(run.id, task_state.id)
            if current_task.status != TaskStatus.BUILDING:
                logger.info(
                    f"Task {task_state.id}: already transitioned to "
                    f"{current_task.status.value}, skipping redundant submit"
                )
                return
            await service.submit_for_verification(run.id, task_state.id)

        # Define output streaming callback
        line_offset = 0

        async def on_output(lines: list[str]) -> None:
            nonlocal line_offset
            event = AgentOutputEvent(
                timestamp=datetime.now(timezone.utc),
                run_id=run.id,
                event_type="agent_output",
                task_id=task_state.id,
                attempt_num=task_state.current_attempt + 1,
                lines=lines,
                line_offset=line_offset,
            )
            await self._broadcaster.emit_log_event(event)
            line_offset += len(lines)

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
            return

        # Store agent metadata (PID, etc.) in run's agent_config
        if result.agent_metadata:
            run.agent_config = {**run.agent_config, **result.agent_metadata}

        # Extract metrics from action_log if available
        metrics = result.metrics
        if result.action_log is not None:
            al = result.action_log
            if al.total_input_tokens or al.total_output_tokens:
                metrics = ExecutionMetrics(
                    tokens_read=al.total_input_tokens,
                    tokens_write=al.total_output_tokens,
                    tokens_cache=al.total_cache_read_tokens + al.total_cache_creation_tokens,
                    duration_ms=al.total_duration_ms,
                    num_actions=sum(1 for e in al.entries if e.kind.value == "tool_use"),
                )

        # Store agent output, action log, and metrics on attempt
        await self._attempt_store.store_attempt_output(
            run.id, task_state.id, result.output_lines, result.error, result.action_log
        )
        await self._attempt_store.store_attempt_metrics(run.id, task_state.id, metrics)

        if not result.success:
            raise AgentExecutionError(
                agent_type=agent_type_value,
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
        line_offset = 0

        async def on_output(lines: list[str]) -> None:
            nonlocal line_offset
            event = AgentOutputEvent(
                timestamp=datetime.now(timezone.utc),
                run_id=run.id,
                event_type="agent_output",
                task_id=task_state.id,
                attempt_num=task_state.current_attempt,
                lines=lines,
                line_offset=line_offset,
            )
            await self._broadcaster.emit_log_event(event)
            line_offset += len(lines)

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

        # Store agent metadata
        if result.agent_metadata:
            run.agent_config = {**run.agent_config, **result.agent_metadata}

        # Extract metrics from action_log if available
        metrics = result.metrics
        if result.action_log is not None:
            al = result.action_log
            if al.total_input_tokens or al.total_output_tokens:
                metrics = ExecutionMetrics(
                    tokens_read=al.total_input_tokens,
                    tokens_write=al.total_output_tokens,
                    tokens_cache=al.total_cache_read_tokens + al.total_cache_creation_tokens,
                    duration_ms=al.total_duration_ms,
                    num_actions=sum(1 for e in al.entries if e.kind.value == "tool_use"),
                )

        # Store agent output, action log, and metrics on attempt
        await self._attempt_store.store_attempt_output(
            run.id, task_state.id, result.output_lines, result.error, result.action_log
        )
        await self._attempt_store.store_attempt_metrics(run.id, task_state.id, metrics)

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
    ) -> None:
        # Define callbacks - recovery agent uses complete_recovery via dynamic tool
        async def on_checklist_update(
            req_id: str, status: ChecklistStatus, note: str | None
        ) -> None:
            pass  # Recovery agent does not update checklist directly

        async def on_submit() -> None:
            pass  # Recovery agent uses complete_recovery, not submit

        # Define output streaming callback
        line_offset = 0

        async def on_output(lines: list[str]) -> None:
            nonlocal line_offset
            event = AgentOutputEvent(
                timestamp=datetime.now(timezone.utc),
                run_id=run.id,
                event_type="agent_output",
                task_id=task_state.id,
                attempt_num=task_state.current_attempt,
                lines=lines,
                line_offset=line_offset,
            )
            await self._broadcaster.emit_log_event(event)
            line_offset += len(lines)

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

        # Store agent metadata
        if result.agent_metadata:
            run.agent_config = {**run.agent_config, **result.agent_metadata}

        # Extract metrics from action_log if available
        metrics = result.metrics
        if result.action_log is not None:
            al = result.action_log
            if al.total_input_tokens or al.total_output_tokens:
                metrics = ExecutionMetrics(
                    tokens_read=al.total_input_tokens,
                    tokens_write=al.total_output_tokens,
                    tokens_cache=al.total_cache_read_tokens + al.total_cache_creation_tokens,
                    duration_ms=al.total_duration_ms,
                    num_actions=sum(1 for e in al.entries if e.kind.value == "tool_use"),
                )

        # Store agent output, action log, and metrics on attempt
        await self._attempt_store.store_attempt_output(
            run.id, task_state.id, result.output_lines, result.error, result.action_log
        )
        await self._attempt_store.store_attempt_metrics(run.id, task_state.id, metrics)

        logger.info(f"Task {task_state.id}: recovery execution complete, success={result.success}")
