"""Agent executor - spawns and runs agents for runs.

This module bridges the gap between starting a run and actually executing
an agent to process tasks. When a run is started via the API, the executor
creates the appropriate agent and runs it in the background.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from orchestrator.agents.action_log import ActionLog
from orchestrator.agents.cli import CLIAgent
from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.agents.types import ExecutionContext, ExecutionMetrics
from orchestrator.config.enums import AgentType, ChecklistStatus, GateType, RunStatus, TaskStatus
from orchestrator.workflow.events import (
    AgentErrorEvent,
    AgentOutputEvent,
    ApprovalRequested,
    WorkflowEvent,
)
from orchestrator.workflow.errors import GateBlockedError
from orchestrator.workflow.prompts import generate_builder_prompt

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from orchestrator.agents.monitor import AgentMonitor
    from orchestrator.api.websocket import ConnectionManager
    from orchestrator.config.global_config import GlobalConfig
    from orchestrator.state.models import Run, StepState, TaskState
    from orchestrator.workflow.locks import LockManager
    from orchestrator.workflow.service import SubmitEventRegistry, WorkflowService

logger = logging.getLogger(__name__)

_LLM_CONFIG_KEYS = {
    "reasoning_effort",
    "extended_thinking_budget",
    "temperature",
    "top_p",
    "max_output_tokens",
    "base_url",
    "timeout",
    "num_retries",
    "model_canonical_name",
}


class AgentExecutor:
    """Executes agents for runs in the background.

    This class is responsible for:
    1. Creating the appropriate agent based on agent_type
    2. Running the agent in a background task
    3. Handling callbacks to update workflow state
    4. Persisting agent metadata (PID, etc.) for liveness detection
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        global_config: GlobalConfig | None = None,
        lock_manager: LockManager | None = None,
        submit_event_registry: SubmitEventRegistry | None = None,
        agent_monitor: AgentMonitor | None = None,
        connection_manager: ConnectionManager | None = None,
        api_base_url: str = "http://localhost:8000",
        *,
        spawn_agents: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._global_config = global_config
        self._lock_manager = lock_manager
        self._submit_event_registry = submit_event_registry
        self._connection_manager = connection_manager
        self._api_base_url = api_base_url
        self._spawn_agents = spawn_agents
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        # Agent monitor is lazy-initialized if not provided, to avoid circular import
        self._agent_monitor = agent_monitor
        self._lazy_agent_monitor_init = agent_monitor is None

    async def _get_agent_monitor(self) -> AgentMonitor | None:
        """Lazy-initialize agent monitor if not provided."""
        if self._agent_monitor is not None:
            return self._agent_monitor

        if not self._lazy_agent_monitor_init:
            return None

        # Lazy init - create monitor instance with session_factory and lock_manager
        try:
            from orchestrator.agents.monitor import AgentMonitor

            self._agent_monitor = AgentMonitor(
                self._session_factory,
                self._global_config,
                lock_manager=self._lock_manager,
            )
            self._lazy_agent_monitor_init = False
            return self._agent_monitor
        except Exception as e:
            logger.warning(f"Failed to initialize agent monitor: {e}")
            return None

    async def _create_service(self, session: AsyncSession) -> WorkflowService:
        """Create a WorkflowService for the given session."""
        from orchestrator.db.event_store import EventStore
        from orchestrator.db.repositories import RunRepository
        from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
        from orchestrator.workflow.event_logger import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)

        # Wire events to WebSocket broadcast so the frontend receives real-time
        # updates for agent-driven state changes (task completions, grade
        # evaluations, step transitions, etc.).
        if self._connection_manager is not None:
            manager = self._connection_manager

            def _on_event(event: WorkflowEvent) -> None:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(manager.broadcast_event(event))
                except RuntimeError:
                    pass

            emitter.add_listener(_on_event)

        return WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            submit_event_registry=self._submit_event_registry,
            auto_verify_runner=LocalAutoVerifyRunner(),
            lock_manager=self._lock_manager,
        )

    async def start_run_with_agent(self, run_id: str, service: WorkflowService) -> Run:
        """Start a run and spawn the appropriate agent.

        This method:
        1. Starts the run (changes status to ACTIVE)
        2. Creates a git worktree if enabled
        3. Spawns the agent in a background task
        4. Returns immediately while agent works

        Args:
            run_id: The run to start
            service: The workflow service (for the initial start_run call)

        Returns:
            The started run
        """
        # First, start the run (changes status to ACTIVE)
        run = await service.start_run(run_id)

        # Create worktree if enabled and we have config for repo/worktree paths
        if run.worktree_enabled and run.source_branch and self._global_config is not None:
            try:
                from orchestrator.git.worktree import WorktreeManager

                repos_dir = self._global_config.paths.get_repos_path()
                worktrees_dir = self._global_config.paths.get_worktrees_path()
                repo_path = repos_dir / run.repo_name

                if repo_path.is_dir():
                    wt_mgr = WorktreeManager(repo_path, worktrees_dir)
                    wt_info = wt_mgr.create(run.id, run.source_branch)
                    run = await service.set_worktree_path(run_id, str(wt_info.path))
                    logger.info(
                        f"Run {run_id}: created worktree at {wt_info.path} "
                        f"(branch={wt_info.branch})"
                    )

                    # Copy scaffolding if routine has it
                    if run.routine_path and run.routine_commit:
                        try:
                            from orchestrator.scaffolding.copier import copy_scaffolding

                            scaffolding_result = copy_scaffolding(
                                repo_path=repo_path,
                                routine_path=run.routine_path,
                                routine_commit=run.routine_commit,
                                worktree_path=wt_info.path,
                            )
                            if scaffolding_result.files_copied > 0:
                                logger.info(
                                    f"Run {run_id}: copied {scaffolding_result.files_copied} "
                                    f"scaffolding files to {scaffolding_result.target_path}"
                                )
                            else:
                                logger.debug(
                                    f"Run {run_id}: no scaffolding files found for routine"
                                )
                        except Exception as e:
                            # Scaffolding is optional - log but don't fail the run
                            logger.warning(f"Run {run_id}: scaffolding copy failed: {e}")
                else:
                    logger.info(
                        f"Run {run_id}: repo {run.repo_name} not found at {repo_path}, "
                        f"skipping worktree creation"
                    )
            except Exception as e:
                logger.warning(f"Run {run_id}: worktree creation failed: {e}")

        # Skip spawning if disabled (e.g., in tests)
        if not self._spawn_agents:
            logger.info(f"Run {run_id}: agent spawning disabled, skipping")
            return run

        # For user-managed agents, don't spawn anything - external agent will poll
        if run.agent_type == AgentType.USER_MANAGED:
            logger.info(f"Run {run_id}: user-managed agent, waiting for external connection")
            return run

        # For managed agents, spawn in background
        agent_type = run.agent_type
        if agent_type in (
            AgentType.CLI_SUBPROCESS,
            AgentType.OPENHANDS_LOCAL,
            AgentType.OPENHANDS_DOCKER,
            AgentType.CODEX_SERVER,
            AgentType.CLAUDE_SDK,
        ):
            assert agent_type is not None  # Type narrowing for pyright
            task = asyncio.create_task(self._run_agent_loop(run_id, agent_type, run.agent_config))
            self._running_tasks[run_id] = task
            logger.info(f"Run {run_id}: spawned {agent_type.value} agent in background")

        return run

    async def _monitor_agent_health(
        self, run_id: str, agent_type: AgentType, check_interval: float = 30.0
    ) -> None:
        """Background task to periodically check if the agent is still alive.

        If the agent is found to be dead, transitions the run to PAUSED.
        """
        monitor = await self._get_agent_monitor()
        if not monitor:
            logger.debug(f"Run {run_id}: agent health monitor not available, skipping checks")
            return

        try:
            while True:
                await asyncio.sleep(check_interval)

                try:
                    async with self._session_factory() as session:
                        from orchestrator.db.repositories import RunRepository

                        repo = RunRepository(session)
                        run = await repo.get(run_id)

                        # Check if run is still active
                        if run.status != RunStatus.ACTIVE:
                            logger.debug(
                                f"Run {run_id}: run is {run.status}, stopping health monitor"
                            )
                            break

                        # Check if agent is still alive
                        agent_alive = await monitor.check_agent_alive(run)
                        if not agent_alive:
                            logger.warning(
                                f"Run {run_id}: agent {agent_type.value} is no longer alive, "
                                f"transitioning to PAUSED"
                            )
                            await monitor.on_agent_died(
                                run_id=run_id,
                                agent_type=agent_type,
                                reason="agent_health_check_failed",
                            )
                            break
                except Exception as e:
                    logger.warning(f"Run {run_id}: agent health check failed: {e}")
                    # Continue checking, don't break on transient errors
        except asyncio.CancelledError:
            logger.debug(f"Run {run_id}: agent health monitor cancelled")
        except Exception as e:
            logger.warning(f"Run {run_id}: unexpected error in agent health monitor: {e}")

    async def _run_agent_loop(
        self, run_id: str, agent_type: AgentType, agent_config: dict[str, Any]
    ) -> None:
        """Main loop that runs agent for all tasks in a run.

        This runs in the background and processes tasks until the run is
        complete, paused, or failed.
        """
        # Start a background health monitor for the agent
        health_monitor_task = asyncio.create_task(self._monitor_agent_health(run_id, agent_type))

        # Track tasks whose recovery was already attempted in this executor session.
        # If _handle_recovery completes without transitioning the task out of RECOVERING,
        # we pause the run instead of looping forever.
        recovery_attempted: set[str] = set()

        try:
            while True:
                # Create a new session for each iteration
                async with self._session_factory() as session:
                    service = await self._create_service(session)
                    from orchestrator.db.repositories import RunRepository

                    repo = RunRepository(session)

                    # Refresh run state
                    run = await repo.get(run_id)

                    # Check if run is still active
                    if run.status != RunStatus.ACTIVE:
                        logger.info(
                            f"Run {run_id}: status is {run.status.value}, stopping agent loop"
                        )
                        break

                    # Find the first pending or building task
                    task_state, blocked_by_gate = self._find_next_task(run)
                    if blocked_by_gate:
                        # Step has an unsatisfied human_approval gate
                        # Find the blocked step for logging/event
                        blocked_step = None
                        for step in run.steps:
                            for task in step.tasks:
                                if task.status in (
                                    TaskStatus.PENDING,
                                    TaskStatus.BUILDING,
                                    TaskStatus.VERIFYING,
                                ):
                                    blocked_step = step
                                    break
                            if blocked_step is not None:
                                break

                        step_id = blocked_step.id if blocked_step else ""
                        logger.info(
                            f"Run {run_id}: blocked by human_approval gate "
                            f"on step {step_id}, waiting for approval"
                        )
                        event = ApprovalRequested(
                            timestamp=datetime.now(timezone.utc),
                            run_id=run_id,
                            event_type="approval_requested",
                            step_id=step_id,
                        )
                        await self._emit_log_event(event)
                        break
                    if task_state is None:
                        logger.info(f"Run {run_id}: no pending tasks, checking run completion")
                        # All tasks done - run will be marked complete by the workflow
                        break

                    # Apply deterministic recovery rule for Codex agents.
                    # For a healthy persisted session the config is passed
                    # unchanged (agent can resume).  For a stale session the
                    # session keys are stripped so the agent starts fresh.
                    effective_config, stale_reason = self._prepare_codex_config(
                        agent_type, agent_config
                    )
                    if stale_reason is not None:
                        logger.info(
                            f"Run {run_id}: task {task_state.id}: Codex session discarded "
                            f"({stale_reason}); new attempt will start fresh"
                        )

                    # Execute the agent for this task
                    logger.info(
                        f"Run {run_id}: executing task {task_state.id} ({task_state.config_id})"
                    )
                    was_recovering = task_state.status == TaskStatus.RECOVERING

                    # Guard against infinite loop: if we already ran recovery for
                    # this task and it's still RECOVERING, pause instead of looping.
                    if was_recovering and task_state.id in recovery_attempted:
                        logger.warning(
                            f"Run {run_id}: task {task_state.id} still RECOVERING after "
                            "previous recovery attempt without complete_recovery call — pausing"
                        )
                        await service.pause_run(run_id, reason="recovery_loop")
                        await session.commit()
                        break
                    if was_recovering:
                        recovery_attempted.add(task_state.id)

                    try:
                        await self._execute_task(
                            run, task_state, service, agent_type, effective_config
                        )
                        await session.commit()
                    except GateBlockedError as e:
                        logger.warning(
                            f"Run {run_id}: task {task_state.id} checklist gate blocked on submit: {e}. "
                            f"Agent ran but could not satisfy the gate — pausing run."
                        )
                        await service.pause_run(run_id, reason="gate_blocked")
                        await session.commit()
                        break
                    except AgentCancelledError:
                        logger.info(f"Run {run_id}: agent cancelled")
                        break
                    except AgentNotAvailableError as e:
                        logger.error(f"Run {run_id}: agent not available: {e}")
                        await self._emit_error_event(
                            run_id, task_state, "AgentNotAvailableError", str(e)
                        )
                        await self._store_attempt_output(run_id, task_state.id, [], str(e))
                        await service.pause_run(run_id, reason="agent_not_available")
                        await session.commit()
                        break
                    except AgentExecutionError as e:
                        logger.error(f"Run {run_id}: agent execution error: {e}")
                        await self._emit_error_event(
                            run_id, task_state, "AgentExecutionError", str(e)
                        )
                        await self._store_attempt_output(run_id, task_state.id, [], str(e))
                        await service.pause_run(run_id, reason="agent_execution_error")
                        await session.commit()
                        break
                    except Exception as e:
                        logger.exception(f"Run {run_id}: unexpected error: {e}")
                        await self._emit_error_event(run_id, task_state, type(e).__name__, str(e))
                        # Pause the run on unexpected errors so the issue can be investigated
                        try:
                            await service.pause_run(run_id, reason="unexpected_error")
                            await session.commit()
                        except Exception:
                            logger.exception(f"Run {run_id}: failed to pause run after error")
                        break

        except asyncio.CancelledError:
            # Server shutdown/reload cancels asyncio tasks. CancelledError is a
            # BaseException (not Exception) in Python 3.9+, so it must be caught
            # explicitly. Use "server_shutdown" reason so startup recovery can
            # auto-resume these runs rather than leaving them stuck in PAUSED.
            logger.warning(f"Run {run_id}: agent loop cancelled (server shutdown?), pausing run")
            try:
                async with self._session_factory() as session:
                    service = await self._create_service(session)
                    await service.pause_run(run_id, reason="server_shutdown")
                    await session.commit()
            except Exception:
                # DB/engine might be shutting down too (connection already closed).
                # Startup recovery will detect the orphaned run and pause it.
                logger.debug(f"Run {run_id}: could not pause run during shutdown (expected)")
        except Exception as e:
            logger.exception(f"Run {run_id}: unexpected error in agent loop: {e}")
            # Try to pause the run if there's an outer exception
            try:
                async with self._session_factory() as session:
                    service = await self._create_service(session)
                    await service.pause_run(run_id, reason="unexpected_error")
                    await session.commit()
            except Exception:
                logger.exception(f"Run {run_id}: failed to pause run after outer error")
        finally:
            # Cancel health monitor
            health_monitor_task.cancel()
            try:
                await health_monitor_task
            except asyncio.CancelledError:
                pass
            self._running_tasks.pop(run_id, None)
            logger.info(f"Run {run_id}: agent loop ended")

    def _is_step_gate_satisfied(self, run: Run, step: StepState) -> bool:
        """Check if a step's human_approval gate is satisfied.

        Returns True if the step has no human_approval gate, or if the gate
        has been approved. Returns False if the gate requires approval and
        no approval has been recorded yet.
        """
        from orchestrator.config.models import RoutineConfig

        if run.routine_embedded is None:
            return True

        routine_config = RoutineConfig.model_validate(run.routine_embedded)
        for step_config in routine_config.steps:
            if step_config.id == step.config_id:
                if (
                    step_config.gate is not None
                    and step_config.gate.type == GateType.HUMAN_APPROVAL
                    and step.human_approval is None
                ):
                    return False
                break
        return True

    def _find_next_task(self, run: Run) -> tuple[TaskState | None, bool]:
        """Find the next task to execute.

        Looks for tasks in the current actionable step only.
        The executor must never start tasks from future steps while an earlier
        step is still active (for example, waiting on human clarification).
        It may skip over already-completed steps if current_step_index lags.

        Looks for tasks in PENDING, BUILDING, or VERIFYING status.
        VERIFYING tasks need to be completed (via complete_verification)
        before the loop can move on.

        Returns:
            A tuple of (task, blocked_by_gate). If the first executable task's
            step has an unsatisfied human_approval gate, returns (None, True).
            If no tasks remain, returns (None, False).
        """
        step_index = run.current_step_index

        # Be resilient to stale indices by skipping already-completed steps.
        while step_index < len(run.steps) and run.steps[step_index].completed:
            step_index += 1

        if step_index >= len(run.steps):
            return (None, False)

        step = run.steps[step_index]

        # If the step is waiting on human input, do not move to future steps.
        if any(task.status == TaskStatus.PENDING_USER_ACTION for task in step.tasks):
            return (None, False)

        for task in step.tasks:
            if task.status in (
                TaskStatus.PENDING,
                TaskStatus.BUILDING,
                TaskStatus.VERIFYING,
                TaskStatus.RECOVERING,
            ):
                if not self._is_step_gate_satisfied(run, step):
                    return (None, True)
                return (task, False)
        return (None, False)

    async def _execute_task(
        self,
        run: Run,
        task_state: TaskState,
        service: WorkflowService,
        agent_type: AgentType,
        agent_config: dict[str, Any],
    ) -> None:
        """Execute the agent for a single task.

        Handles both BUILDING and VERIFYING phases:
        - PENDING/BUILDING: Run the builder agent, then submit for verification
        - VERIFYING: Complete verification (for tasks with no rubric, auto-complete)
        """
        from orchestrator.config.models import RoutineConfig

        # Get routine config
        if run.routine_embedded is None:
            raise AgentExecutionError(
                agent_type.value, "Cannot execute task without routine config"
            )

        routine_config = RoutineConfig.model_validate(run.routine_embedded)

        # Find the task config and step context
        # First, find which step contains this task to disambiguate config lookup
        step_config_id: str | None = None
        for step in run.steps:
            for task in step.tasks:
                if task.id == task_state.id:
                    step_config_id = step.config_id
                    break
            if step_config_id is not None:
                break

        task_config = None
        step_context: str | None = None
        for step in routine_config.steps:
            if step_config_id is not None and step.id != step_config_id:
                continue
            for task in step.tasks:
                if task.id == task_state.config_id:
                    task_config = task
                    step_context = step.step_context
                    break
            if task_config is not None:
                break

        if task_config is None:
            raise AgentExecutionError(
                agent_type.value, f"Task config not found: {task_state.config_id}"
            )

        phase = self._phase_for_task_status(task_state.status)

        # Handle VERIFYING phase
        if task_state.status == TaskStatus.VERIFYING:
            await self._handle_verification(
                run, task_state, task_config, service, agent_type, agent_config
            )
            return

        # Handle RECOVERING phase - use stored recovery prompt
        if task_state.status == TaskStatus.RECOVERING:
            await self._handle_recovery(run, task_state, service, agent_type, agent_config)
            return

        # Handle PENDING/BUILDING phase
        # Start the task if pending
        if task_state.status == TaskStatus.PENDING:
            await service.start_task(run.id, task_state.id)

        # Create the agent (pass run_id for death detection)
        agent = self._create_agent(agent_type, agent_config, run.id, phase=phase)

        # Build the context - worktree_path is required for agent execution
        if not run.worktree_path:
            raise AgentExecutionError(
                agent_type=agent_type.value,
                message="Cannot run agent without worktree_path set on run",
            )
        working_dir = run.worktree_path
        # Resolve clarifications artifact path if configured
        from orchestrator.workflow.clarifications import resolve_artifact_path as _resolve_path

        clarifications_path: str | None = None
        if routine_config.clarifications is not None and run.worktree_path:
            raw_clar_path = _resolve_path(routine_config.clarifications.artifact_path, run.config)
            clar_artifact = Path(run.worktree_path) / raw_clar_path
            if clar_artifact.exists():
                clarifications_path = str(clar_artifact)

        prompt = generate_builder_prompt(
            task_config,
            task_state,
            run.config,
            step_context=step_context,
            clarifications_path=clarifications_path,
        )
        # Include both ID and description so agent can use the ID for callbacks
        requirements = [f"{item.req_id}: {item.desc}" for item in task_state.checklist]
        # Also build a map from description to ID for fuzzy matching
        req_desc_to_id = {item.desc.lower().strip(): item.req_id for item in task_state.checklist}

        context = ExecutionContext(
            run_id=run.id,
            task_id=task_state.id,
            working_dir=working_dir,
            prompt=f"{prompt.system}\n\n{prompt.user}",
            requirements=requirements,
            api_base_url=self._api_base_url,
        )

        # Store the builder prompt BEFORE agent execution
        await self._store_attempt_prompt(run.id, task_state.id, builder_prompt=context.prompt)

        # Define callbacks that use the service
        async def on_checklist_update(
            req_id: str, status: ChecklistStatus, note: str | None
        ) -> None:
            # Try exact match first, then fallback to description-based lookup
            actual_id = req_id
            if req_id.lower().strip() in req_desc_to_id:
                actual_id = req_desc_to_id[req_id.lower().strip()]
            await service.update_checklist_item(run.id, task_state.id, actual_id, status, note)

        async def on_submit() -> None:
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
            await self._emit_log_event(event)
            line_offset += len(lines)

        # Define agent metadata callback - persist PID/container_id immediately
        async def on_agent_metadata(metadata: dict[str, Any]) -> None:
            await self._persist_agent_metadata(run.id, metadata)

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
            )
        except GateBlockedError:
            logger.warning("Agent submit blocked by gate - task remains BUILDING, will retry")
            return

        # Store agent metadata (PID, etc.) in run's agent_config
        if result.agent_metadata:
            run.agent_config = {**run.agent_config, **result.agent_metadata}
            # The session will be committed by the caller

        # Extract metrics from action_log if available (overrides empty defaults)
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
        await self._store_attempt_output(
            run.id, task_state.id, result.output_lines, result.error, result.action_log
        )
        await self._store_attempt_metrics(run.id, task_state.id, metrics)

        if not result.success:
            raise AgentExecutionError(
                agent_type.value,
                result.error or "Agent execution returned unsuccessful result",
            )

        logger.info(f"Task {task_state.id}: builder execution complete, success={result.success}")

    async def _handle_verification(
        self,
        run: Run,
        task_state: TaskState,
        task_config: Any,  # TaskConfig from config/models.py
        service: WorkflowService,
        agent_type: AgentType,
        agent_config: dict[str, Any],
    ) -> None:
        """Handle the VERIFYING phase for a task.

        For tasks with no rubric (auto-verify only), automatically complete
        the verification. For tasks with a rubric, run the verifier agent.
        """
        from orchestrator.workflow.prompts import generate_verifier_prompt

        # Check if task has a rubric that needs LLM evaluation
        has_rubric = bool(task_config.verifier.rubric)

        if not has_rubric:
            # No rubric - auto-complete verification (auto-verify already ran)
            logger.info(f"Task {task_state.id}: no rubric, auto-completing verification")
            await service.complete_verification(run.id, task_state.id)
            return

        # Has rubric - need to run verifier agent
        logger.info(f"Task {task_state.id}: running verifier agent for rubric evaluation")
        phase = self._phase_for_task_status(task_state.status)

        # Create the agent for verification (pass run_id for death detection)
        agent = self._create_agent(agent_type, agent_config, run.id, phase=phase)

        # Build the verifier context - worktree_path is required
        if not run.worktree_path:
            raise AgentExecutionError(
                agent_type=agent_type.value,
                message="Cannot run agent without worktree_path set on run",
            )
        working_dir = run.worktree_path
        prompt = generate_verifier_prompt(task_config, task_state)
        # Include both ID and description so agent can use the ID for callbacks
        requirements = [f"{item.req_id}: {item.desc}" for item in task_state.checklist]
        # Also build a map from description to ID for fuzzy matching
        req_desc_to_id = {item.desc.lower().strip(): item.req_id for item in task_state.checklist}

        # Get the end_commit from the current attempt
        end_commit = None
        if task_state.attempts:
            current_attempt = task_state.attempts[-1]
            end_commit = current_attempt.end_commit

        # Checkout the builder's end commit on the host worktree so the
        # verifier (including Docker bind-mounts) sees the correct files.
        if end_commit and working_dir:
            import subprocess

            checkout = subprocess.run(
                ["git", "checkout", end_commit],
                cwd=working_dir,
                capture_output=True,
                text=True,
            )
            if checkout.returncode != 0:
                logger.warning(
                    f"Failed to checkout end_commit {end_commit} in {working_dir}: "
                    f"{checkout.stderr.strip()}"
                )

        context = ExecutionContext(
            run_id=run.id,
            task_id=task_state.id,
            working_dir=working_dir,
            prompt=f"{prompt.system}\n\n{prompt.user}",
            requirements=requirements,
            api_base_url=self._api_base_url,
            end_commit=end_commit,
        )

        # Store the verifier prompt BEFORE agent execution
        await self._store_attempt_prompt(run.id, task_state.id, verifier_prompt=context.prompt)

        # Define callbacks for verifier
        async def on_checklist_update(
            req_id: str, status: ChecklistStatus, note: str | None
        ) -> None:
            # Try exact match first, then fallback to description-based lookup
            actual_id = req_id
            if req_id.lower().strip() in req_desc_to_id:
                actual_id = req_desc_to_id[req_id.lower().strip()]
            await service.update_checklist_item(run.id, task_state.id, actual_id, status, note)

        async def on_complete() -> None:
            # The verifier agent may have already called complete-verification
            # via REST/MCP during execution.  Re-read the run to avoid a
            # redundant call that would fail if the run already transitioned
            # to a terminal status (e.g. FAILED after max attempts).
            current_run = await service.get_run(run.id)
            if current_run.status != RunStatus.ACTIVE:
                logger.info(
                    f"Task {task_state.id}: run already {current_run.status.value}, "
                    f"skipping redundant complete_verification"
                )
                return

            # Also skip if the task is no longer in VERIFYING (already completed
            # or moved back to BUILDING for a revision).
            current_task = await service.get_task(run.id, task_state.id)
            if current_task.status != TaskStatus.VERIFYING:
                logger.info(
                    f"Task {task_state.id}: already transitioned to "
                    f"{current_task.status.value}, skipping redundant complete_verification"
                )
                return

            # Fallback: if verifier is completing but didn't set any grades,
            # auto-grade all requirements as "A". Some CLI agents (e.g. codex)
            # may not reliably call the grade REST API even when review passes.
            ungraded = [item for item in current_task.checklist if item.grade is None]
            if ungraded:
                logger.warning(
                    f"Task {task_state.id}: verifier completing but "
                    f"{len(ungraded)} requirements have no grade — auto-grading as A"
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
            # Try exact match first, then fallback to description-based lookup
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
            await self._emit_log_event(event)
            line_offset += len(lines)

        # Define agent metadata callback - persist PID/container_id immediately
        async def on_agent_metadata(metadata: dict[str, Any]) -> None:
            await self._persist_agent_metadata(run.id, metadata)

        # Execute the verifier agent
        result = await agent.execute(
            context,
            on_checklist_update,
            on_complete,
            on_output=on_output,
            on_grade=on_grade,
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
        await self._store_attempt_output(
            run.id, task_state.id, result.output_lines, result.error, result.action_log
        )
        await self._store_attempt_metrics(run.id, task_state.id, metrics)

        logger.info(f"Task {task_state.id}: verifier execution complete, success={result.success}")

    async def _handle_recovery(
        self,
        run: Run,
        task_state: TaskState,
        service: WorkflowService,
        agent_type: AgentType,
        agent_config: dict[str, Any],
    ) -> None:
        """Handle the RECOVERING phase for a task.

        Uses the stored recovery prompt from the latest attempt's builder_prompt
        field (set by trigger_recovery) and spawns an agent to diagnose the failure.
        The recovery agent calls MCP tools (complete_recovery, request_clarification)
        to drive resolution.
        """
        # The recovery prompt is stored in the latest attempt's builder_prompt
        recovery_prompt: str | None = None
        if task_state.attempts:
            recovery_prompt = task_state.attempts[-1].builder_prompt

        if not recovery_prompt:
            raise AgentExecutionError(
                agent_type.value,
                "No recovery prompt found on latest attempt for RECOVERING task",
            )

        # Create the agent for recovery phase (uses "building" MCP tools)
        agent = self._create_agent(agent_type, agent_config, run.id, phase="building")

        # Build the context - worktree_path is required for agent execution
        if not run.worktree_path:
            raise AgentExecutionError(
                agent_type=agent_type.value,
                message="Cannot run agent without worktree_path set on run",
            )

        context = ExecutionContext(
            run_id=run.id,
            task_id=task_state.id,
            working_dir=run.worktree_path,
            prompt=recovery_prompt,
            requirements=[],
            api_base_url=self._api_base_url,
        )

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
            await self._emit_log_event(event)
            line_offset += len(lines)

        # Define agent metadata callback
        async def on_agent_metadata(metadata: dict[str, Any]) -> None:
            await self._persist_agent_metadata(run.id, metadata)

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
        await self._store_attempt_output(
            run.id, task_state.id, result.output_lines, result.error, result.action_log
        )
        await self._store_attempt_metrics(run.id, task_state.id, metrics)

        logger.info(f"Task {task_state.id}: recovery execution complete, success={result.success}")

    async def _emit_log_event(self, event: WorkflowEvent) -> None:
        """Persist a log event and broadcast via WebSocket."""
        try:
            async with self._session_factory() as session:
                from orchestrator.db.event_store import EventStore

                store = EventStore(session)
                await store.append(event)
                await session.commit()
        except Exception:
            logger.debug(f"Failed to persist log event: {event.event_type}", exc_info=True)

        # Broadcast to WebSocket subscribers regardless of persistence success
        if self._connection_manager is not None:
            try:
                await self._connection_manager.broadcast_event(event)
            except Exception:
                logger.debug(f"Failed to broadcast log event: {event.event_type}", exc_info=True)

    async def _emit_error_event(
        self, run_id: str, task_state: TaskState, error_type: str, message: str
    ) -> None:
        """Emit an AgentErrorEvent."""
        attempt_num = task_state.current_attempt if task_state.attempts else 0
        event = AgentErrorEvent(
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            event_type="agent_error",
            task_id=task_state.id,
            attempt_num=attempt_num,
            error_type=error_type,
            error_message=message,
        )
        await self._emit_log_event(event)

    async def _store_attempt_output(
        self,
        run_id: str,
        task_id: str,
        output_lines: list[str],
        error: str | None = None,
        action_log: Any = None,
    ) -> None:
        """Store agent output, error, and optional structured action log on the current attempt."""
        try:
            async with self._session_factory() as session:
                from orchestrator.db.repositories import RunRepository

                repo = RunRepository(session)
                run = await repo.get(run_id)
                # Find the task and its latest attempt
                for step in run.steps:
                    for task in step.tasks:
                        if task.id == task_id and task.attempts:
                            attempt = task.attempts[-1]
                            if output_lines:
                                # Append phase output (builder + verifier) and keep tail.
                                new_text = "\n".join(output_lines)
                                if attempt.agent_output:
                                    combined = f"{attempt.agent_output}\n{new_text}"
                                    attempt.agent_output = "\n".join(combined.splitlines()[-10000:])
                                else:
                                    attempt.agent_output = "\n".join(output_lines[-10000:])
                            if error:
                                attempt.error = error
                            if action_log is not None:
                                if attempt.action_log is None:
                                    attempt.action_log = action_log
                                else:
                                    attempt.action_log = self._merge_action_logs(
                                        attempt.action_log, action_log
                                    )
                            await repo.save(run)
                            await session.commit()
                            return
        except Exception:
            logger.debug(f"Failed to store attempt output for {task_id}", exc_info=True)

    def _merge_action_logs(self, first: ActionLog, second: ActionLog) -> ActionLog:
        """Merge builder + verifier action logs for a single attempt."""
        merged = first.model_copy(deep=True)
        seq_offset = merged.entries[-1].sequence_num if merged.entries else 0

        for idx, entry in enumerate(second.entries, start=1):
            adjusted = entry.model_copy(deep=True)
            adjusted.sequence_num = seq_offset + idx
            merged.entries.append(adjusted)

        if not merged.session_id:
            merged.session_id = second.session_id
        if not merged.agent_model:
            merged.agent_model = second.agent_model
        if second.tools_available:
            merged.tools_available = list(
                dict.fromkeys(merged.tools_available + second.tools_available)
            )

        merged.total_turns += second.total_turns
        merged.total_cost_usd += second.total_cost_usd
        merged.total_duration_ms += second.total_duration_ms
        merged.total_input_tokens += second.total_input_tokens
        merged.total_output_tokens += second.total_output_tokens
        merged.total_cache_read_tokens += second.total_cache_read_tokens
        merged.total_cache_creation_tokens += second.total_cache_creation_tokens
        return merged

    async def _store_attempt_prompt(
        self,
        run_id: str,
        task_id: str,
        builder_prompt: str | None = None,
        verifier_prompt: str | None = None,
    ) -> None:
        """Store builder or verifier prompt on the current attempt.

        This should be called BEFORE agent execution so the prompt is
        available even if the agent crashes.
        """
        try:
            async with self._session_factory() as session:
                from orchestrator.db.repositories import RunRepository

                repo = RunRepository(session)
                run = await repo.get(run_id)
                # Find the task and its latest attempt
                for step in run.steps:
                    for task in step.tasks:
                        if task.id == task_id and task.attempts:
                            attempt = task.attempts[-1]
                            if builder_prompt is not None:
                                attempt.builder_prompt = builder_prompt
                            if verifier_prompt is not None:
                                attempt.verifier_prompt = verifier_prompt
                            await repo.save(run)
                            await session.commit()
                            return
        except Exception:
            logger.debug(f"Failed to store attempt prompt for {task_id}", exc_info=True)

    async def _persist_agent_metadata(
        self,
        run_id: str,
        agent_metadata: dict[str, Any],
    ) -> None:
        """Persist agent metadata (PID, container_id, etc.) to run.agent_config immediately.

        This should be called right after creating the agent process so that if the
        orchestrator crashes or the agent dies, we can still check if it's alive
        via AgentMonitor.check_agent_alive().
        """
        if not agent_metadata:
            return

        try:
            async with self._session_factory() as session:
                from orchestrator.db.repositories import RunRepository

                repo = RunRepository(session)
                run = await repo.get(run_id)
                # Merge new metadata with existing config
                run.agent_config = {**run.agent_config, **agent_metadata}
                run.updated_at = datetime.now(timezone.utc)
                await repo.save(run)
                await session.commit()
                logger.info(f"Run {run_id}: persisted agent metadata {list(agent_metadata.keys())}")
        except Exception as e:
            logger.warning(f"Failed to persist agent metadata for {run_id}: {e}")

    async def _store_attempt_metrics(
        self,
        run_id: str,
        task_id: str,
        metrics: ExecutionMetrics,
    ) -> None:
        """Store execution metrics on the current attempt and accumulate into run totals."""
        try:
            async with self._session_factory() as session:
                from orchestrator.db.repositories import RunRepository

                repo = RunRepository(session)
                run = await repo.get(run_id)
                for step in run.steps:
                    for task in step.tasks:
                        if task.id == task_id and task.attempts:
                            attempt = task.attempts[-1]
                            attempt.metrics.tokens_read += metrics.tokens_read
                            attempt.metrics.tokens_write += metrics.tokens_write
                            attempt.metrics.tokens_cache += metrics.tokens_cache
                            attempt.metrics.duration_ms += metrics.duration_ms
                            attempt.metrics.num_actions += metrics.num_actions
                            # Accumulate into run totals
                            run.total_tokens_read += metrics.tokens_read
                            run.total_tokens_write += metrics.tokens_write
                            run.total_tokens_cache += metrics.tokens_cache
                            run.total_duration_ms += metrics.duration_ms
                            run.total_num_actions += metrics.num_actions
                            await repo.save(run)
                            await session.commit()
                            return
        except Exception:
            logger.debug(f"Failed to store attempt metrics for {task_id}", exc_info=True)

    @staticmethod
    def _phase_for_task_status(task_status: TaskStatus) -> str:
        """Map workflow task status to MCP phase."""
        if task_status == TaskStatus.VERIFYING:
            return "verifying"
        return "building"

    @staticmethod
    def _is_codex_process_alive(pid: int) -> bool:
        """Check if a process with the given PID is still running."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _prepare_codex_config(
        self,
        agent_type: AgentType,
        agent_config: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        """Apply the deterministic recovery rule for Codex agents.

        Inspects the stored session state (PID for local, session_id +
        session_created_at for remote) and decides whether to resume the
        persisted session or discard it and start a fresh attempt.

        Rule:
        - Healthy persisted session  → return config unchanged so the agent
          can resume (session_id / PID passed through).
        - Stale / missing session    → return a cleaned config (session keys
          removed) and a non-None ``stale_reason`` string describing why the
          session was discarded.

        Only CODEX_SERVER is handled; all other agent types are returned
        unchanged with ``stale_reason=None``.

        Args:
            agent_type: The agent type of the run.
            agent_config: The current agent_config dict from the run.

        Returns:
            ``(effective_config, stale_reason)`` where ``effective_config``
            is the agent_config to use for agent creation (may have session
            keys stripped) and ``stale_reason`` is ``None`` when the session
            is healthy or the agent type is not Codex.
        """
        if agent_type == AgentType.CODEX_SERVER:
            pid_raw = agent_config.get("pid")
            if pid_raw is None:
                # No PID stored — no prior session to resume or discard.
                return agent_config, None
            pid = int(pid_raw)
            if self._is_codex_process_alive(pid):
                # Healthy: local process still running — pass PID through.
                return agent_config, None
            # Stale: local process is gone — clear PID and return reason.
            stale_reason = f"local_codex_process_not_alive (pid={pid})"
            cleaned = {k: v for k, v in agent_config.items() if k != "pid"}
            logger.info("Executor: Codex local session stale — %s; starting fresh", stale_reason)
            return cleaned, stale_reason

        # Non-Codex agent type — no session classification needed.
        return agent_config, None

    def _create_agent(
        self,
        agent_type: AgentType,
        agent_config: dict[str, Any],
        run_id: str | None = None,
        phase: str = "building",
    ) -> CLIAgent:
        """Create the appropriate agent based on run configuration."""
        if agent_type == AgentType.CLI_SUBPROCESS:
            from orchestrator.agents.parsers.claude_parser import ClaudeStreamParser
            from orchestrator.agents.parsers.codex_parser import CodexStreamParser

            command = agent_config.get("command", "claude")
            model = agent_config.get("model")
            callback_channel = agent_config.get("callback_channel", "rest")
            poll_interval = agent_config.get("poll_interval", 5.0)

            # Build args based on command - claude needs special flags
            args = agent_config.get("args", [])
            parser = None
            if command == "claude" and not args:
                # Use -p for print mode (non-interactive) and skip permissions
                # for automated execution, with stream-json for structured output
                args = [
                    "-p",
                    "--dangerously-skip-permissions",
                    "--output-format",
                    "stream-json",
                    "--verbose",
                ]
                parser = ClaudeStreamParser()
            elif command == "codex" and not args:
                # Use non-interactive mode with unrestricted execution for
                # orchestrator-managed runs, with --json for structured output.
                args = ["exec", "--dangerously-bypass-approvals-and-sandbox", "--json"]
                parser = CodexStreamParser()

            # Get nudger config from global config
            nudger_config = None
            if self._global_config and self._global_config.nudger:
                nudger_config = self._global_config.nudger.to_agent_config()

            return CLIAgent(
                command=command,
                args=args,
                model=model,
                callback_channel=callback_channel,
                nudger_config=nudger_config,
                poll_interval=poll_interval,
                parser=parser,
                agent_monitor=self._agent_monitor,
                run_id=run_id,
                phase=phase,
            )

        elif agent_type == AgentType.OPENHANDS_LOCAL:
            # Import here to avoid circular imports (optional dependency)
            from orchestrator.agents.openhands import OpenHandsAgent

            api_key = agent_config.get("api_key")
            model = agent_config.get("model", "gpt-5-mini")
            max_iterations = agent_config.get("max_iterations", 100)
            llm_config = {k: v for k, v in agent_config.items() if k in _LLM_CONFIG_KEYS}

            return OpenHandsAgent(
                api_key=api_key,
                model=model,
                max_iterations=max_iterations,
                llm_config=llm_config,
            )  # type: ignore[return-value]

        elif agent_type == AgentType.OPENHANDS_DOCKER:
            # Import here to avoid circular imports (optional dependency)
            from orchestrator.agents.openhands_docker import DockerOpenHandsAgent

            api_key = agent_config.get("api_key")
            model = agent_config.get("model", "gpt-5-mini")
            max_iterations = agent_config.get("max_iterations", 100)
            server_image = agent_config.get("server_image")
            llm_config = {k: v for k, v in agent_config.items() if k in _LLM_CONFIG_KEYS}

            # Build kwargs, only include server_image if explicitly set
            kwargs: dict[str, Any] = {
                "api_key": api_key,
                "model": model,
                "max_iterations": max_iterations,
                "llm_config": llm_config,
            }
            if server_image is not None:
                kwargs["server_image"] = server_image

            return DockerOpenHandsAgent(**kwargs)  # type: ignore[return-value]

        elif agent_type == AgentType.CODEX_SERVER:
            from orchestrator.agents.codex_server import CodexServerAgent

            model = agent_config.get("model")
            callback_channel = agent_config.get("callback_channel", "rest")
            api_key = agent_config.get("api_key")
            restrictions = agent_config.get("restrictions", "no-network")

            return CodexServerAgent(  # type: ignore[return-value]
                model=model,
                callback_channel=callback_channel,
                api_key=api_key,
                restrictions=str(restrictions),
            )

        elif agent_type == AgentType.CLAUDE_SDK:
            from orchestrator.agents.claude_sdk import ClaudeSDKAgent

            model = agent_config.get("model", "claude-sonnet-4-5")
            api_key = agent_config.get("api_key")
            auth_token = agent_config.get("auth_token")
            max_tokens = agent_config.get("max_tokens", 4096)
            max_iterations = agent_config.get("max_iterations", 50)

            return ClaudeSDKAgent(  # type: ignore[return-value]
                model=model,
                api_key=api_key,
                auth_token=auth_token,
                max_tokens=max_tokens,
                max_iterations=max_iterations,
            )

        else:
            raise AgentNotAvailableError(
                agent_type.value if agent_type else "none",
                f"Unsupported agent type: {agent_type}",
            )

    def spawn_for_run(
        self, run_id: str, agent_type: AgentType, agent_config: dict[str, Any]
    ) -> bool:
        """Spawn an agent for a run in the background.

        Args:
            run_id: The run ID
            agent_type: The type of agent to spawn
            agent_config: Configuration for the agent

        Returns:
            True if an agent was spawned, False if spawning is disabled or
            the agent type is not managed.
        """
        if not self._spawn_agents:
            logger.info(f"Run {run_id}: agent spawning disabled, skipping")
            return False

        if agent_type not in (
            AgentType.CLI_SUBPROCESS,
            AgentType.OPENHANDS_LOCAL,
            AgentType.OPENHANDS_DOCKER,
            AgentType.CODEX_SERVER,
            AgentType.CLAUDE_SDK,
        ):
            return False

        task = asyncio.create_task(self._run_agent_loop(run_id, agent_type, agent_config))
        self._running_tasks[run_id] = task
        logger.info(f"Run {run_id}: spawned {agent_type.value} agent in background")
        return True

    async def cancel_run(self, run_id: str) -> None:
        """Cancel a running agent for a run."""
        task = self._running_tasks.get(run_id)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._running_tasks.pop(run_id, None)
            logger.info(f"Run {run_id}: agent cancelled")

    def is_running(self, run_id: str) -> bool:
        """Check if an agent is currently running for a run."""
        return run_id in self._running_tasks
