"""Agent executor - spawns and runs agents for runs.

This module bridges the gap between starting a run and actually executing
an agent to process tasks. When a run is started via the API, the executor
creates the appropriate agent and runs it in the background.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from orchestrator.agents.cli import CLIAgent
from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.agents.types import ExecutionContext
from orchestrator.config.enums import AgentType, ChecklistStatus, RunStatus, TaskStatus
from orchestrator.workflow.events import AgentErrorEvent, AgentOutputEvent
from orchestrator.workflow.prompts import generate_builder_prompt

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from orchestrator.agents.monitor import AgentMonitor
    from orchestrator.config.global_config import GlobalConfig
    from orchestrator.state.models import Run, TaskState
    from orchestrator.workflow.locks import LockManager
    from orchestrator.workflow.service import SubmitEventRegistry, WorkflowService

logger = logging.getLogger(__name__)

_LLM_CONFIG_KEYS = {
    "reasoning_effort",
    "extended_thinking_budget",
    "temperature",
    "top_p",
    "max_output_tokens",
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
        api_base_url: str = "http://localhost:8000",
        *,
        spawn_agents: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._global_config = global_config
        self._lock_manager = lock_manager
        self._submit_event_registry = submit_event_registry
        self._agent_monitor = agent_monitor
        self._api_base_url = api_base_url
        self._spawn_agents = spawn_agents
        self._running_tasks: dict[str, asyncio.Task[None]] = {}

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
        2. Spawns the agent in a background task
        3. Returns immediately while agent works

        Args:
            run_id: The run to start
            service: The workflow service (for the initial start_run call)

        Returns:
            The started run
        """
        # First, start the run (changes status to ACTIVE)
        run = await service.start_run(run_id)

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
        ):
            assert agent_type is not None  # Type narrowing for pyright
            task = asyncio.create_task(self._run_agent_loop(run_id, agent_type, run.agent_config))
            self._running_tasks[run_id] = task
            logger.info(f"Run {run_id}: spawned {agent_type.value} agent in background")

        return run

    async def _run_agent_loop(
        self, run_id: str, agent_type: AgentType, agent_config: dict[str, Any]
    ) -> None:
        """Main loop that runs agent for all tasks in a run.

        This runs in the background and processes tasks until the run is
        complete, paused, or failed.
        """
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
                    task_state = self._find_next_task(run)
                    if task_state is None:
                        logger.info(f"Run {run_id}: no pending tasks, checking run completion")
                        # All tasks done - run will be marked complete by the workflow
                        break

                    # Execute the agent for this task
                    logger.info(
                        f"Run {run_id}: executing task {task_state.id} ({task_state.config_id})"
                    )
                    try:
                        await self._execute_task(run, task_state, service, agent_type, agent_config)
                        await session.commit()
                    except AgentCancelledError:
                        logger.info(f"Run {run_id}: agent cancelled")
                        break
                    except AgentNotAvailableError as e:
                        logger.error(f"Run {run_id}: agent not available: {e}")
                        await self._emit_error_event(
                            run_id, task_state, "AgentNotAvailableError", str(e)
                        )
                        await self._store_attempt_output(run_id, task_state.id, [], str(e))
                        await service.pause_run(run_id)
                        await session.commit()
                        break
                    except AgentExecutionError as e:
                        logger.error(f"Run {run_id}: agent execution error: {e}")
                        await self._emit_error_event(
                            run_id, task_state, "AgentExecutionError", str(e)
                        )
                        await self._store_attempt_output(run_id, task_state.id, [], str(e))
                        await service.pause_run(run_id)
                        await session.commit()
                        break
                    except Exception as e:
                        logger.exception(f"Run {run_id}: unexpected error: {e}")
                        # Pause the run on unexpected errors so the issue can be investigated
                        try:
                            await service.pause_run(run_id)
                            await session.commit()
                        except Exception:
                            logger.exception(f"Run {run_id}: failed to pause run after error")
                        break

        except Exception as e:
            logger.exception(f"Run {run_id}: unexpected error in agent loop: {e}")
            # Try to pause the run if there's an outer exception
            try:
                async with self._session_factory() as session:
                    service = await self._create_service(session)
                    await service.pause_run(run_id)
                    await session.commit()
            except Exception:
                logger.exception(f"Run {run_id}: failed to pause run after outer error")
        finally:
            self._running_tasks.pop(run_id, None)
            logger.info(f"Run {run_id}: agent loop ended")

    def _find_next_task(self, run: Run) -> TaskState | None:
        """Find the next task to execute.

        Looks for tasks in PENDING, BUILDING, or VERIFYING status.
        VERIFYING tasks need to be completed (via complete_verification)
        before the loop can move on.
        """
        for step in run.steps:
            for task in step.tasks:
                if task.status in (TaskStatus.PENDING, TaskStatus.BUILDING, TaskStatus.VERIFYING):
                    return task
        return None

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
        task_config = None
        step_context: str | None = None
        for step in routine_config.steps:
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

        # Handle VERIFYING phase
        if task_state.status == TaskStatus.VERIFYING:
            await self._handle_verification(
                run, task_state, task_config, service, agent_type, agent_config
            )
            return

        # Handle PENDING/BUILDING phase
        # Start the task if pending
        if task_state.status == TaskStatus.PENDING:
            await service.start_task(run.id, task_state.id)

        # Create the agent
        agent = self._create_agent(agent_type, agent_config)

        # Build the context
        working_dir = run.worktree_path or run.project_id
        prompt = generate_builder_prompt(
            task_config, task_state, run.config, step_context=step_context
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

        # Execute the agent
        logger.info(f"Task {task_state.id}: starting builder agent")
        result = await agent.execute(
            context, on_checklist_update, on_submit, on_output=on_output, on_grade=None
        )

        # Store agent metadata (PID, etc.) in run's agent_config
        if result.agent_metadata:
            run.agent_config = {**run.agent_config, **result.agent_metadata}
            # The session will be committed by the caller

        # Store agent output on attempt
        await self._store_attempt_output(run.id, task_state.id, result.output_lines, result.error)

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

        # Create the agent for verification
        agent = self._create_agent(agent_type, agent_config)

        # Build the verifier context
        working_dir = run.worktree_path or run.project_id
        prompt = generate_verifier_prompt(task_config, task_state)
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

        # Execute the verifier agent
        result = await agent.execute(
            context, on_checklist_update, on_complete, on_output=on_output, on_grade=on_grade
        )

        # Store agent metadata
        if result.agent_metadata:
            run.agent_config = {**run.agent_config, **result.agent_metadata}

        # Store agent output on attempt
        await self._store_attempt_output(run.id, task_state.id, result.output_lines, result.error)

        logger.info(f"Task {task_state.id}: verifier execution complete, success={result.success}")

    async def _emit_log_event(self, event: AgentOutputEvent | AgentErrorEvent) -> None:
        """Persist a log event using a separate session to avoid transaction conflicts."""
        try:
            async with self._session_factory() as session:
                from orchestrator.db.event_store import EventStore

                store = EventStore(session)
                await store.append(event)
                await session.commit()
        except Exception:
            logger.debug(f"Failed to persist log event: {event.event_type}", exc_info=True)

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
    ) -> None:
        """Store agent output and error on the current attempt."""
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
                                # Truncate to last 10000 lines
                                truncated = output_lines[-10000:]
                                attempt.agent_output = "\n".join(truncated)
                            if error:
                                attempt.error = error
                            await repo.save(run)
                            await session.commit()
                            return
        except Exception:
            logger.debug(f"Failed to store attempt output for {task_id}", exc_info=True)

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

    def _create_agent(self, agent_type: AgentType, agent_config: dict[str, Any]) -> CLIAgent:
        """Create the appropriate agent based on run configuration."""
        if agent_type == AgentType.CLI_SUBPROCESS:
            command = agent_config.get("command", "claude")
            model = agent_config.get("model")
            callback_channel = agent_config.get("callback_channel", "rest")
            poll_interval = agent_config.get("poll_interval", 5.0)

            # Build args based on command - claude needs special flags
            args = agent_config.get("args", [])
            if command == "claude" and not args:
                # Use -p for print mode (non-interactive) and skip permissions
                # for automated execution
                args = ["-p", "--dangerously-skip-permissions"]

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
            )

        elif agent_type == AgentType.OPENHANDS_LOCAL:
            # Import here to avoid circular imports (optional dependency)
            from orchestrator.agents.openhands import OpenHandsAgent

            api_key = agent_config.get("api_key")
            model = agent_config.get("model", "gpt-4o-mini")
            max_iterations = agent_config.get("max_iterations", 100)
            tools = agent_config.get("tools")
            llm_config = {k: v for k, v in agent_config.items() if k in _LLM_CONFIG_KEYS}

            return OpenHandsAgent(
                api_key=api_key,
                model=model,
                max_iterations=max_iterations,
                tools=tools,
                llm_config=llm_config,
            )  # type: ignore[return-value]

        elif agent_type == AgentType.OPENHANDS_DOCKER:
            # Import here to avoid circular imports (optional dependency)
            from orchestrator.agents.openhands_docker import DockerOpenHandsAgent

            api_key = agent_config.get("api_key")
            model = agent_config.get("model", "gpt-4o-mini")
            max_iterations = agent_config.get("max_iterations", 100)
            tools = agent_config.get("tools")
            server_image = agent_config.get("server_image")
            llm_config = {k: v for k, v in agent_config.items() if k in _LLM_CONFIG_KEYS}

            # Build kwargs, only include server_image if explicitly set
            kwargs: dict[str, Any] = {
                "api_key": api_key,
                "model": model,
                "max_iterations": max_iterations,
                "tools": tools,
                "llm_config": llm_config,
            }
            if server_image is not None:
                kwargs["server_image"] = server_image

            return DockerOpenHandsAgent(**kwargs)  # type: ignore[return-value]

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
