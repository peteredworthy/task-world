"""Agent executor - spawns and runs agents for runs.

This module bridges the gap between starting a run and actually executing
an agent to process tasks. When a run is started via the API, the executor
creates the appropriate agent and runs it in the background.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from orchestrator.runners.interface import AgentRunner
from orchestrator.runners.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.runners.types import ExecutionContext
from orchestrator.config.enums import (
    AgentRunnerType,
    GateType,
    RunStatus,
    TaskStatus,
)
from orchestrator.workflow.events import (
    ApprovalRequested,
    WorkflowEvent,
)
from orchestrator.runners.execution.attempt_store import AttemptStore
from orchestrator.runners.execution.event_broadcaster import EventBroadcaster
from orchestrator.runners.execution.phase_handler import PhaseHandler
from orchestrator.workflow.errors import GateBlockedError
from orchestrator.workflow.prompts import generate_builder_prompt
from orchestrator.workflow.summary_cache import SummaryCache

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from orchestrator.runners.monitor import AgentRunnerMonitor
    from orchestrator.api.websocket import ConnectionManager
    from orchestrator.config.global_config import GlobalConfig
    from orchestrator.state.models import Run, StepState, TaskState
    from orchestrator.workflow.locks import LockManager
    from orchestrator.workflow.service import SubmitEventRegistry, WorkflowService

logger = logging.getLogger(__name__)


def resolve_verifier_config(
    agent_config: dict[str, Any],
    verifier_model: str | None,
) -> dict[str, Any]:
    """Build the effective agent config for the verifier phase.

    If *verifier_model* is set (pinned at run creation), it overrides the
    ``model`` key in *agent_config*.  Otherwise *agent_config* is returned
    as-is (shallow copy).  This is a pure function so it can be unit-tested
    without mocking executor internals.
    """
    config = dict(agent_config)
    if verifier_model is not None:
        config["model"] = verifier_model
    return config


class AgentRunnerExecutor:
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
        runner_monitor: AgentRunnerMonitor | None = None,
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
        self._runner_monitor = runner_monitor
        self._lazy_runner_monitor_init = runner_monitor is None

        # Extracted sub-components
        self._attempt_store = AttemptStore(session_factory)
        self._broadcaster = EventBroadcaster(session_factory, connection_manager)
        self._phase_handler = PhaseHandler(self._attempt_store, self._broadcaster, api_base_url)

    async def _get_runner_monitor(self) -> AgentRunnerMonitor | None:
        """Lazy-initialize agent monitor if not provided."""
        if self._runner_monitor is not None:
            return self._runner_monitor

        if not self._lazy_runner_monitor_init:
            return None

        # Lazy init - create monitor instance with session_factory and lock_manager
        try:
            from orchestrator.runners.monitor import AgentRunnerMonitor

            self._runner_monitor = AgentRunnerMonitor(
                self._session_factory,
                self._global_config,
                lock_manager=self._lock_manager,
            )
            self._lazy_runner_monitor_init = False
            return self._runner_monitor
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

    async def _run_project_health_check(self, project_dir: str) -> str | None:
        """Run the project test suite before the first task attempt.

        Reads .task-world/config.yaml for test_command. Falls back to the
        convention default. Returns None on success/skip, or an error message
        if the tests fail.
        """
        import yaml

        config_path = Path(project_dir) / ".task-world" / "config.yaml"
        # Worktrees don't have .task-world/ (it's untracked). Fall back to the
        # main worktree's config so worktree runs use the same health check.
        if not config_path.exists():
            git_file = Path(project_dir) / ".git"
            if git_file.is_file():
                # Git worktree: .git is a file containing "gitdir: <path>"
                # The commondir points to the main repo's .git directory.
                try:
                    gitdir = git_file.read_text().strip().removeprefix("gitdir: ")
                    commondir_file = Path(gitdir) / "commondir"
                    if commondir_file.exists():
                        commondir = (Path(gitdir) / commondir_file.read_text().strip()).resolve()
                        main_root = commondir.parent  # .git's parent is repo root
                        candidate = main_root / ".task-world" / "config.yaml"
                        if candidate.exists():
                            config_path = candidate
                except Exception:
                    pass  # Fall through to default
        test_command: str | None = "uv run pytest --tb=no -q"

        if config_path.exists():
            try:
                with open(config_path) as f:
                    config_data = yaml.safe_load(f)
                if isinstance(config_data, dict) and "test_command" in config_data:
                    from typing import cast

                    cfg: dict[str, Any] = cast(dict[str, Any], config_data)
                    raw = cfg["test_command"]
                    test_command = str(raw) if raw is not None else None
            except Exception as e:
                logger.warning(f"Health check: failed to read {config_path}: {e}")

        if test_command is None:
            logger.info("Health check: test_command is null, skipping")
            return None

        logger.info(f"Health check: running '{test_command}' in {project_dir}")
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    test_command,
                    shell=True,
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    timeout=300,
                ),
            )
            if result.returncode != 0:
                output = (result.stdout + result.stderr).strip()
                return (
                    f"Pre-run health check failed.\n"
                    f"Command: {test_command}\n"
                    f"Exit code: {result.returncode}\n"
                    f"Output:\n{output}"
                )
            logger.info("Health check: tests passed")
            return None
        except subprocess.TimeoutExpired:
            return f"Pre-run health check timed out.\nCommand: {test_command}"
        except Exception as e:
            logger.warning(f"Health check: unexpected error: {e}")
            return f"Pre-run health check error: {e}\nCommand: {test_command}"

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
        if run.agent_type == AgentRunnerType.USER_MANAGED:
            logger.info(f"Run {run_id}: user-managed agent, waiting for external connection")
            return run

        # For managed agents, spawn in background
        agent_type = run.agent_type
        if agent_type in (
            AgentRunnerType.CLI_SUBPROCESS,
            AgentRunnerType.OPENHANDS_LOCAL,
            AgentRunnerType.OPENHANDS_DOCKER,
            AgentRunnerType.CODEX_SERVER,
            AgentRunnerType.CLAUDE_SDK,
        ):
            assert agent_type is not None  # Type narrowing for pyright
            # Clear stale PID so the health monitor treats the agent as
            # "not yet spawned" until the new subprocess registers its PID.
            # Without this, the monitor finds the old dead PID and immediately
            # pauses the run again after resume.
            agent_config = {k: v for k, v in run.agent_config.items() if k != "pid"}
            if "pid" in run.agent_config:
                await self._attempt_store.persist_agent_metadata(run_id, {"pid": None})
            task = asyncio.create_task(self._run_agent_loop(run_id, agent_type, agent_config))
            self._running_tasks[run_id] = task
            logger.info(f"Run {run_id}: spawned {agent_type.value} agent in background")

        return run

    async def _monitor_agent_health(
        self, run_id: str, agent_type: AgentRunnerType, check_interval: float = 30.0
    ) -> None:
        """Background task to periodically check if the agent is still alive.

        If the agent is found to be dead, transitions the run to PAUSED.
        """
        monitor = await self._get_runner_monitor()
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
        self, run_id: str, agent_type: AgentRunnerType, agent_config: dict[str, Any]
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

        # Run-scoped summary cache: summaries from earlier tasks are reused by
        # later tasks, avoiding redundant API calls during context_from lookups.
        summary_cache = SummaryCache()

        # Run project health check before the first task attempt.
        health_check_done = False

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
                        await self._broadcaster.emit_log_event(event)
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

                    # Run project health check before the very first task attempt.
                    if not health_check_done and run.worktree_path:
                        health_check_done = True
                        await self._broadcaster.emit_health_check_event(
                            run_id, "started", "Running pre-run health check..."
                        )
                        health_error = await self._run_project_health_check(run.worktree_path)
                        if health_error:
                            logger.error(f"Run {run_id}: pre-run health check failed, pausing run")
                            await self._broadcaster.emit_health_check_event(
                                run_id, "failed", health_error
                            )
                            await service.pause_run(
                                run_id,
                                reason="health_check_failed",
                                error_detail=health_error,
                            )
                            await session.commit()
                            break
                        await self._broadcaster.emit_health_check_event(
                            run_id, "completed", "Health check passed"
                        )
                    elif not health_check_done:
                        health_check_done = True  # No worktree_path, skip silently

                    try:
                        await self._execute_task(
                            run,
                            task_state,
                            service,
                            agent_type,
                            effective_config,
                            summary_cache=summary_cache,
                            session=session,
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
                        await self._broadcaster.emit_error_event(
                            run_id, task_state, "AgentNotAvailableError", str(e)
                        )
                        await self._attempt_store.store_attempt_output(
                            run_id, task_state.id, [], str(e)
                        )
                        await service.pause_run(
                            run_id,
                            reason="agent_not_available",
                            error_detail=str(e),
                        )
                        await session.commit()
                        break
                    except AgentExecutionError as e:
                        logger.error(f"Run {run_id}: agent execution error: {e}")
                        await self._broadcaster.emit_error_event(
                            run_id, task_state, "AgentExecutionError", str(e)
                        )
                        await self._attempt_store.store_attempt_output(
                            run_id, task_state.id, [], str(e)
                        )
                        await service.pause_run(
                            run_id,
                            reason="agent_execution_error",
                            error_detail=str(e),
                        )
                        await session.commit()
                        break
                    except Exception as e:
                        logger.exception(f"Run {run_id}: unexpected error: {e}")
                        await self._broadcaster.emit_error_event(
                            run_id, task_state, type(e).__name__, str(e)
                        )
                        # Pause the run on unexpected errors so the issue can be investigated
                        try:
                            await service.pause_run(
                                run_id,
                                reason="unexpected_error",
                                error_detail=str(e),
                            )
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
            # Skip child tasks — they are managed by the fan-out executor
            if task.parent_task_id is not None:
                continue
            # FAN_OUT_RUNNING tasks are handled by the fan-out executor,
            # not by the normal task loop. Skip them.
            if task.status == TaskStatus.FAN_OUT_RUNNING:
                continue
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
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
        summary_cache: SummaryCache | None = None,
        session: "AsyncSession | None" = None,
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
        step_id: str | None = None
        available_tools: list[str] | None = None
        mcp_servers: list[Any] | None = None
        for step in routine_config.steps:
            if step_config_id is not None and step.id != step_config_id:
                continue
            for task in step.tasks:
                if task.id == task_state.config_id:
                    task_config = task
                    step_context = step.step_context
                    step_id = step.id
                    available_tools = step.available_tools
                    mcp_servers = step.mcp_servers
                    break
            if task_config is not None:
                break

        if task_config is None:
            raise AgentExecutionError(
                agent_type.value, f"Task config not found: {task_state.config_id}"
            )

        # Only intercept fan-out/script for initial execution, not for
        # verification or recovery — those should fall through to their
        # dedicated handlers below.
        if task_state.status not in (TaskStatus.VERIFYING, TaskStatus.RECOVERING):
            # Script tasks: run the script directly instead of spawning an agent
            if task_config.script is not None:
                logger.info(
                    f"Run {run.id}: task {task_state.id} is a script task, "
                    f"executing via service.execute_script_task()"
                )
                await service.execute_script_task(run.id, task_state.id)
                return

            # Fan-out tasks: expand and execute children in parallel
            if task_config.fan_out is not None:
                logger.info(
                    f"Run {run.id}: task {task_state.id} is a fan-out task, "
                    f"executing via _execute_fan_out()"
                )
                await self._execute_fan_out(
                    run,
                    task_state,
                    task_config,
                    service,
                    agent_type,
                    agent_config,
                    step_context=step_context,
                    step_id=step_id,
                    available_tools=available_tools,
                    mcp_servers=mcp_servers,
                    summary_cache=summary_cache,
                    session=session,
                )
                return

        # Apply profile-based model resolution when the task has a profile assigned.
        # Resolution order: runner profile defaults (DB) -> agent_config model -> None
        if task_config.profile is not None and session is not None:
            from sqlalchemy import select as sa_select

            from orchestrator.config.enums import ModelProfile
            from orchestrator.db.models import RunnerProfileDefaultModel
            from orchestrator.runners.profile_resolution import resolve_model_for_profile

            rows = (
                (
                    await session.execute(
                        sa_select(RunnerProfileDefaultModel).where(
                            RunnerProfileDefaultModel.runner_type == agent_type.value
                        )
                    )
                )
                .scalars()
                .all()
            )
            profile_defaults: dict[str, str] = {
                row.profile: row.model
                for row in rows
                if row.profile in {p.value for p in ModelProfile}
            }
            resolved_model = resolve_model_for_profile(
                task_config.profile,
                profile_defaults,
                fallback_model=agent_config.get("model"),
            )
            if resolved_model is not None and resolved_model != agent_config.get("model"):
                logger.debug(
                    f"Task {task_state.id}: resolved model '{resolved_model}' "
                    f"from profile '{task_config.profile.value}'"
                )
                agent_config = {**agent_config, "model": resolved_model}

        phase = self._phase_for_task_status(task_state.status)

        # Handle VERIFYING phase
        if task_state.status == TaskStatus.VERIFYING:
            await self._handle_verification(
                run,
                task_state,
                task_config,
                service,
                agent_type,
                agent_config,
                step_id=step_id,
                available_tools=available_tools,
                mcp_servers=mcp_servers,
            )
            return

        # Handle RECOVERING phase - use stored recovery prompt
        if task_state.status == TaskStatus.RECOVERING:
            await self._handle_recovery(
                run,
                task_state,
                service,
                agent_type,
                agent_config,
                step_id=step_id,
                available_tools=available_tools,
                mcp_servers=mcp_servers,
            )
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

        # Ensure the worktree is on its named branch (not detached HEAD).
        # Verification checkouts can leave HEAD detached; re-attach so the
        # builder's commits land on the run's branch.
        branch_name = f"orchestrator/run-{run.id}"
        reattach = subprocess.run(
            ["git", "checkout", branch_name],
            cwd=working_dir,
            capture_output=True,
            text=True,
        )
        if reattach.returncode != 0:
            logger.warning(
                f"Could not re-attach HEAD to {branch_name} in {working_dir}: "
                f"{reattach.stderr.strip()}"
            )

        # Resolve clarifications artifact path if configured
        from orchestrator.workflow.clarifications import (
            decisions_from_config,
            resolve_artifact_path as _resolve_path,
        )

        clarifications_path: str | None = None
        if routine_config.clarifications is not None and run.worktree_path:
            raw_clar_path = _resolve_path(routine_config.clarifications.artifact_path, run.config)
            clar_artifact = Path(run.worktree_path) / raw_clar_path
            if clar_artifact.exists():
                clarifications_path = str(clar_artifact)

        # Reconstruct compressed decisions from persisted run.config
        decisions = decisions_from_config(run.config)

        # Build artifact context from context_from if configured
        run_config = dict(run.config)
        if task_config.context_from:
            from orchestrator.artifacts.registry import ArtifactRegistry
            from orchestrator.workflow.context_builder import TaskContextBuilder

            worktree_path = Path(run.worktree_path) if run.worktree_path else None
            ctx_builder = TaskContextBuilder(ArtifactRegistry(), worktree_path=worktree_path)
            artifact_context = await ctx_builder.build_context(
                run_id=run.id,
                context_sources=task_config.context_from,
                variables=run.config,
                summary_cache=summary_cache,
            )
            run_config.update(artifact_context)

        prompt = generate_builder_prompt(
            task_config,
            task_state,
            run_config,
            step_context=step_context,
            clarifications_path=clarifications_path,
            decisions=decisions,
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
            step_id=step_id,
            available_tools=available_tools,
            mcp_servers=mcp_servers,
        )

        await self._phase_handler.execute_phase(
            phase="building",
            run=run,
            task_state=task_state,
            service=service,
            agent=agent,
            context=context,
            req_desc_to_id=req_desc_to_id,
            agent_type_value=agent_type.value,
            session=session,
        )

    async def _execute_fan_out(
        self,
        run: Run,
        parent_task: TaskState,
        task_config: Any,  # TaskConfig from config/models.py
        service: WorkflowService,
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
        step_context: str | None = None,
        step_id: str | None = None,
        available_tools: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        summary_cache: SummaryCache | None = None,
        session: "AsyncSession | None" = None,
    ) -> None:
        """Execute a fan-out task: expand into children, run in parallel, aggregate.

        Flow:
        1. Expand fan-out task into children via service
        2. Execute children concurrently (up to max_concurrent)
        3. Each child: build prompt -> spawn agent -> auto_verify -> retry
        4. All children complete -> parent VERIFYING or COMPLETED
        5. Any child exhausts retries -> parent FAILED -> run pauses
        """
        from orchestrator.config.models import FanOutConfig

        fan_out: FanOutConfig = task_config.fan_out
        worktree_path = run.worktree_path
        if not worktree_path:
            raise AgentExecutionError(agent_type.value, "Cannot run fan-out without worktree_path")

        # Check if children already exist from a previous expansion (e.g. after
        # outer verification failure → revision back to BUILDING).
        existing_children: list[TaskState] = []
        for step in run.steps:
            for task in step.tasks:
                if task.parent_task_id == parent_task.id:
                    existing_children.append(task)

        if existing_children:
            # Re-run existing children instead of expanding again.
            # Reset them to PENDING so the executor can re-execute them.
            logger.info(
                f"Run {run.id}: fan-out task {parent_task.id} has "
                f"{len(existing_children)} existing children, resetting for re-run"
            )

            # Get verifier feedback from the parent's most recent attempt
            verifier_feedback: str | None = None
            if parent_task.attempts:
                latest_attempt = parent_task.attempts[-1]
                verifier_feedback = getattr(latest_attempt, "verifier_comment", None)

            # Reset children to PENDING and parent to FAN_OUT_RUNNING
            await service.reset_fan_out_children(run.id, parent_task.id)

            children = existing_children
        else:
            # 1. Expand: create child tasks (first time)
            children = await service.expand_fan_out_task(run.id, parent_task.id)
            verifier_feedback = None

        if not children:
            # No files matched — mark parent completed with no children
            logger.warning(
                f"Run {run.id}: fan-out task {parent_task.id} produced 0 children, "
                f"marking as COMPLETED"
            )
            async with self._session_factory() as sess:
                svc = await self._create_service(sess)
                await svc.complete_fan_out_parent(run.id, parent_task.id, all_passed=True)
                await sess.commit()
            return

        # 2. Execute children with semaphore
        sem = asyncio.Semaphore(fan_out.max_concurrent)
        child_results: dict[str, bool] = {}  # child_id -> passed

        async def run_child(child: TaskState) -> None:
            """Execute a single child task with retries."""
            child_id = child.id
            passed = False

            for attempt_num in range(1, fan_out.max_attempts + 1):
                try:
                    # On the first attempt of a re-run (after outer verification
                    # failure), prepend the outer verifier's feedback so the
                    # agent knows what to fix.
                    child_feedback = verifier_feedback if attempt_num == 1 else None
                    async with sem:
                        passed = await self._execute_fan_out_child(
                            run=run,
                            child=child,
                            fan_out=fan_out,
                            task_config=task_config,
                            agent_type=agent_type,
                            agent_config=agent_config,
                            worktree_path=worktree_path,
                            step_context=step_context,
                            step_id=step_id,
                            available_tools=available_tools,
                            mcp_servers=mcp_servers,
                            attempt_num=attempt_num,
                            verifier_feedback=child_feedback,
                        )

                    if passed:
                        break

                    # Auto-verify failed — retry if attempts remain
                    if attempt_num < fan_out.max_attempts:
                        logger.info(
                            f"Run {run.id}: child {child_id} attempt "
                            f"{attempt_num}/{fan_out.max_attempts} failed, retrying"
                        )
                    else:
                        logger.warning(
                            f"Run {run.id}: child {child_id} exhausted "
                            f"{fan_out.max_attempts} attempts"
                        )
                except Exception as e:
                    logger.error(f"Run {run.id}: child {child_id} attempt {attempt_num} error: {e}")
                    if attempt_num >= fan_out.max_attempts:
                        break

            # After all retries, transition child to appropriate terminal status
            if not passed:
                async with self._session_factory() as sess:
                    svc = await self._create_service(sess)
                    await svc.update_child_task_state(
                        run.id,
                        child_id,
                        {"status": TaskStatus.FAILED},
                    )

            child_results[child_id] = passed

        # Run all children concurrently
        await asyncio.gather(*[run_child(c) for c in children], return_exceptions=True)

        # 3. Determine parent outcome
        all_passed = all(child_results.get(c.id, False) for c in children)
        any_failed = any(not child_results.get(c.id, True) for c in children)

        # 4. Transition parent
        async with self._session_factory() as sess:
            svc = await self._create_service(sess)

            if any_failed:
                # Mark parent FAILED, which will pause the run
                await svc.complete_fan_out_parent(run.id, parent_task.id, all_passed=False)
                await sess.commit()
                logger.warning(
                    f"Run {run.id}: fan-out task {parent_task.id} FAILED "
                    f"(children failed: "
                    f"{[c.id for c in children if not child_results.get(c.id, True)]})"
                )
            elif all_passed:
                # Check if parent has outer verifier (rubric)
                has_outer_verifier = bool(task_config.verifier.rubric)
                if has_outer_verifier:
                    await svc.complete_fan_out_parent(
                        run.id, parent_task.id, all_passed=True, to_verifying=True
                    )
                    await sess.commit()
                    logger.info(
                        f"Run {run.id}: fan-out task {parent_task.id} children "
                        f"all passed, moving to VERIFYING for outer verification"
                    )
                else:
                    await svc.complete_fan_out_parent(run.id, parent_task.id, all_passed=True)
                    await sess.commit()
                    logger.info(
                        f"Run {run.id}: fan-out task {parent_task.id} COMPLETED "
                        f"(all {len(children)} children passed)"
                    )

    async def _execute_fan_out_child(
        self,
        run: Run,
        child: TaskState,
        fan_out: Any,  # FanOutConfig
        task_config: Any,  # TaskConfig (parent)
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
        worktree_path: str,
        step_context: str | None = None,
        step_id: str | None = None,
        available_tools: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        attempt_num: int = 1,
        verifier_feedback: str | None = None,
    ) -> bool:
        """Execute a single fan-out child task.

        Builds the prompt, spawns agent, runs auto_verify.
        Returns True if auto_verify passes, False otherwise.
        """
        from orchestrator.workflow.auto_verify import (
            LocalAutoVerifyRunner,
            run_auto_verify,
        )
        from orchestrator.workflow.templates import resolve_template

        child_id = child.id
        input_path = child.fan_out_input or ""
        output_path = child.fan_out_output or ""

        # Start the child task (PENDING -> BUILDING)
        async with self._session_factory() as sess:
            svc = await self._create_service(sess)
            await svc.start_task(run.id, child_id)
            await sess.commit()

        # Read input file content
        input_full = Path(worktree_path) / input_path
        try:
            item_content = input_full.read_text()
        except (FileNotFoundError, OSError) as e:
            item_content = f"[Error reading {input_path}: {e}]"

        item_stem = Path(input_path).stem

        # Resolve shared_context entries
        shared_parts: list[str] = []
        for ctx_entry in fan_out.shared_context:
            resolved = resolve_template(ctx_entry, worktree_path=worktree_path)
            shared_parts.append(resolved)

        # Build per_item_prompt with variables
        variables: dict[str, str] = {
            "item_content": item_content,
            "item_stem": item_stem,
            "output_path": output_path,
        }
        # Add run config variables
        for k, v in run.config.items():
            if v is not None and k not in variables:
                variables[k] = str(v)

        prompt_body = resolve_template(
            fan_out.per_item_prompt,
            variables=variables,
            worktree_path=worktree_path,
        )

        # Build full prompt
        prompt_parts: list[str] = []
        if verifier_feedback:
            prompt_parts.append(
                f"IMPORTANT - Previous verification feedback:\n{verifier_feedback}\n"
            )
        if shared_parts:
            prompt_parts.append("## Shared Context\n" + "\n".join(shared_parts))
        if step_context:
            prompt_parts.append(f"## Step Context\n{step_context}")
        prompt_parts.append(f"## Task\n{prompt_body}")
        prompt_parts.append(f"\nInput file: {input_path}\nOutput file: {output_path}")

        full_prompt = "\n\n".join(prompt_parts)

        # Create agent and execute
        agent = self._create_agent(agent_type, agent_config, run.id, phase="building")
        context = ExecutionContext(
            run_id=run.id,
            task_id=child_id,
            working_dir=worktree_path,
            prompt=full_prompt,
            requirements=[],
            api_base_url=self._api_base_url,
            step_id=step_id,
            available_tools=available_tools,
            mcp_servers=mcp_servers,
        )

        # Run the agent
        try:
            await self._phase_handler.execute_phase(
                phase="building",
                run=run,
                task_state=child,
                service=None,  # Children don't use service callbacks
                agent=agent,
                context=context,
                req_desc_to_id={},
                agent_type_value=agent_type.value,
                session=None,
            )
        except Exception as e:
            logger.error(f"Run {run.id}: child {child_id} agent error: {e}")
            # Mark child as failed for this attempt
            async with self._session_factory() as sess:
                svc = await self._create_service(sess)
                await svc.update_child_task_state(
                    run.id,
                    child_id,
                    {
                        "error": str(e),
                        "outcome": "failed",
                        "completed_at": datetime.now(timezone.utc),
                    },
                )
            return False

        # Run auto_verify if configured
        if fan_out.auto_verify is not None and fan_out.auto_verify.items:
            auto_vars = {"output_path": output_path, "item_stem": item_stem}
            runner = LocalAutoVerifyRunner()
            cwd = Path(worktree_path)

            results = await run_auto_verify(fan_out.auto_verify, runner, cwd, variables=auto_vars)
            all_passed = all(r.passed for r in results)

            # Store auto_verify results on the child's attempt
            async with self._session_factory() as sess:
                svc = await self._create_service(sess)
                if all_passed:
                    await svc.update_child_task_state(
                        run.id,
                        child_id,
                        {
                            "auto_verify_results": [r.model_dump() for r in results],
                            "outcome": "passed",
                            "completed_at": datetime.now(timezone.utc),
                            "status": TaskStatus.COMPLETED,
                        },
                    )
                else:
                    await svc.update_child_task_state(
                        run.id,
                        child_id,
                        {
                            "auto_verify_results": [r.model_dump() for r in results],
                            "outcome": "failed",
                            "completed_at": datetime.now(timezone.utc),
                        },
                    )

            return all_passed
        else:
            # No auto_verify: mark child as completed
            async with self._session_factory() as sess:
                svc = await self._create_service(sess)
                await svc.update_child_task_state(
                    run.id,
                    child_id,
                    {
                        "outcome": "passed",
                        "completed_at": datetime.now(timezone.utc),
                        "status": TaskStatus.COMPLETED,
                    },
                )

            return True

    async def _handle_verification(
        self,
        run: Run,
        task_state: TaskState,
        task_config: Any,  # TaskConfig from config/models.py
        service: WorkflowService,
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
        step_id: str | None = None,
        available_tools: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
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

        # Use pinned verifier model from run state (snapshotted at creation time)
        effective_verifier_config = resolve_verifier_config(agent_config, run.verifier_model)

        # Create the agent for verification (pass run_id for death detection)
        agent = self._create_agent(agent_type, effective_verifier_config, run.id, phase=phase)

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
        # We reset the branch pointer to this commit rather than detaching HEAD,
        # so the worktree stays on its named branch. This prevents HEAD from
        # being left in a detached state after verification.
        if end_commit and working_dir:
            branch_name = f"orchestrator/run-{run.id}"
            # First, reset the branch to the end_commit
            reset_result = subprocess.run(
                ["git", "checkout", "-B", branch_name, end_commit],
                cwd=working_dir,
                capture_output=True,
                text=True,
            )
            if reset_result.returncode != 0:
                # Fallback to plain checkout if branch reset fails
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
            step_id=step_id,
            available_tools=available_tools,
            mcp_servers=mcp_servers,
        )

        await self._phase_handler.execute_phase(
            phase="verifying",
            run=run,
            task_state=task_state,
            service=service,
            agent=agent,
            context=context,
            req_desc_to_id=req_desc_to_id,
        )

    async def _handle_recovery(
        self,
        run: Run,
        task_state: TaskState,
        service: WorkflowService,
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
        step_id: str | None = None,
        available_tools: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
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
            step_id=step_id,
            available_tools=available_tools,
            mcp_servers=mcp_servers,
        )

        await self._phase_handler.execute_phase(
            phase="recovering",
            run=run,
            task_state=task_state,
            service=service,
            agent=agent,
            context=context,
            req_desc_to_id={},
        )

    @staticmethod
    def _phase_for_task_status(task_status: TaskStatus) -> str:
        """Map workflow task status to MCP phase."""
        if task_status == TaskStatus.VERIFYING:
            return "verifying"
        return "building"

    @staticmethod
    def _prepare_codex_config(
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        """Delegate to the codex config module for session recovery."""
        from orchestrator.runners.agents.codex.config import prepare_codex_config

        return prepare_codex_config(agent_type, agent_config)

    def _get_nudger_config(self) -> Any:
        """Extract nudger config from global config, if available."""
        if self._global_config and self._global_config.nudger:
            return self._global_config.nudger.to_agent_config()
        return None

    def _create_agent(
        self,
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
        run_id: str | None = None,
        phase: str = "building",
    ) -> AgentRunner:
        """Create the appropriate agent via the registry-based factory."""
        from orchestrator.runners import agent_factory

        return agent_factory.create(
            agent_type,
            agent_config,
            run_id=run_id,
            phase=phase,
            nudger_config=self._get_nudger_config(),
            runner_monitor=self._runner_monitor,
            global_config=self._global_config,
        )

    def spawn_for_run(
        self, run_id: str, agent_type: AgentRunnerType, agent_config: dict[str, Any]
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
            AgentRunnerType.CLI_SUBPROCESS,
            AgentRunnerType.OPENHANDS_LOCAL,
            AgentRunnerType.OPENHANDS_DOCKER,
            AgentRunnerType.CODEX_SERVER,
            AgentRunnerType.CLAUDE_SDK,
        ):
            return False

        # Clear stale PID so the health monitor treats the agent as "not yet
        # spawned" until the new subprocess registers its PID via the
        # on_agent_metadata callback.  Without this, resuming a run whose old
        # process has died causes the monitor to immediately re-pause it.
        clean_config = {k: v for k, v in agent_config.items() if k != "pid"}
        if "pid" in agent_config:
            asyncio.create_task(self._attempt_store.persist_agent_metadata(run_id, {"pid": None}))

        task = asyncio.create_task(self._run_agent_loop(run_id, agent_type, clean_config))
        task.add_done_callback(lambda t: self._on_agent_loop_done(run_id, t))
        self._running_tasks[run_id] = task
        logger.info(f"Run {run_id}: spawned {agent_type.value} agent in background")
        return True

    def _on_agent_loop_done(self, run_id: str, task: asyncio.Task[None]) -> None:
        """Callback when an executor task finishes.

        If the task raised an exception that wasn't caught by _run_agent_loop's
        own handlers (shouldn't happen, but defense-in-depth), schedule a
        pause so the run doesn't stay stuck as ACTIVE forever.
        """
        exc = task.exception() if not task.cancelled() else None
        if exc is not None:
            logger.error(f"Run {run_id}: executor task died with unhandled exception: {exc}")
            asyncio.ensure_future(self._emergency_pause(run_id, str(exc)))

    async def _emergency_pause(self, run_id: str, error_msg: str) -> None:
        """Last-resort pause for runs whose executor task crashed."""
        try:
            async with self._session_factory() as session:
                service = await self._create_service(session)
                run = await service.get_run(run_id)
                if run.status == RunStatus.ACTIVE:
                    await service.pause_run(run_id, reason="executor_crash")
                    await session.commit()
                    logger.info(f"Run {run_id}: emergency-paused after executor crash")
        except Exception:
            logger.exception(f"Run {run_id}: failed to emergency-pause")

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
