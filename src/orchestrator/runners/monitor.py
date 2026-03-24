"""Agent liveness monitoring and death handling."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from orchestrator.config.enums import AgentRunnerType, RunStatus, TaskStatus
from orchestrator.config.global_config import GlobalConfig
from orchestrator.state.models import Run
from orchestrator.workflow.events import AgentDiedEvent, RunStatusChanged

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from orchestrator.workflow.locks import LockManager

logger = logging.getLogger(__name__)


async def _is_container_running(container_id: str) -> bool:
    """Check if a Docker container is running.

    Uses 'docker inspect' to check container state.
    Returns True only if the container exists and is in 'running' state.
    """
    try:
        # Run docker inspect and parse the JSON output
        # The --format flag extracts just the State.Running field
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            "--format={{.State.Running}}",
            container_id,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            return False

        # Docker returns "true" or "false" as a string
        return stdout.decode().strip() == "true"
    except Exception as e:
        logger.warning(f"Failed to check container {container_id}: {e}")
        return False


class AgentRunnerMonitor:
    """Watches agent processes and transitions runs on unexpected death.

    Provides methods to:
    - Handle notification of agent death (on_agent_died)
    - Check if a run's agent is still alive (check_agent_alive)
    - Recover runs on startup (used by startup recovery logic)

    This class requires RunRepository and EventStore to persist state changes
    and log events.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        global_config: GlobalConfig | None = None,
        lock_manager: LockManager | None = None,
    ) -> None:
        """Initialize the agent monitor.

        Args:
            session_factory: Async session factory for creating fresh DB sessions.
            global_config: Global configuration (used for timeouts, etc).
            lock_manager: Optional lock manager. When provided, on_agent_died
                releases any task locks held by the dead agent to prevent
                orphaned locks that could block future task execution.
        """
        self._session_factory = session_factory
        self._global_config = global_config or GlobalConfig()
        self._lock_manager = lock_manager

    async def on_agent_died(
        self,
        run_id: str,
        agent_type: AgentRunnerType,
        exit_code: int | None = None,
        reason: str = "agent_process_died",
        pause_run: bool = True,
    ) -> None:
        """Handle unexpected agent death.

        This is called by agent wrappers when they detect the agent process
        has died unexpectedly (not via normal completion or orchestrator kill).

        When pause_run=True (default), the run is transitioned from ACTIVE to
        PAUSED so the user can resume with the same or a different agent.  When
        pause_run=False the death event is logged but the run state is left
        untouched — use this when the caller (e.g. the executor loop) will
        handle the pause itself via the normal error-handling path.

        Creates a fresh DB session to avoid stale-session issues.

        Args:
            run_id: The run whose agent died.
            agent_type: The type of agent that died.
            exit_code: Optional exit code if available.
            reason: Reason string (e.g., "agent_process_died", "agent_not_running_on_startup").
            pause_run: Whether to transition the run to PAUSED (default True).
                Set to False when called from within the executor loop where
                the error will propagate to _run_loop's exception handler.
        """
        from orchestrator.db import EventStore
        from orchestrator.db import RunRepository

        async with self._session_factory() as session:
            repo = RunRepository(session)
            event_store = EventStore(session)

            run = await repo.get(run_id)

            # Only handle if the run is still ACTIVE
            # (might have been manually paused/stopped in the meantime)
            if run.status != RunStatus.ACTIVE:
                logger.info(f"Run {run_id}: agent died but run is {run.status}, no action taken")
                return

            # Release any task locks held by the dead agent.
            # When an agent dies mid-task, the lock it acquired on BUILDING or
            # VERIFYING tasks remains held in-memory. Releasing them here prevents
            # orphaned locks and ensures the next agent that picks up the run can
            # acquire locks without stale state blocking it.
            if self._lock_manager is not None:
                for step in run.steps:
                    for task in step.tasks:
                        if task.status in (TaskStatus.BUILDING, TaskStatus.VERIFYING):
                            released = self._lock_manager.release(task.id, "default")
                            if released:
                                logger.debug(
                                    f"Run {run_id}: released orphaned lock on task "
                                    f"{task.id} (status={task.status.value}) after "
                                    f"agent {agent_type.value} death"
                                )

            # Log the agent death event
            event = AgentDiedEvent(
                timestamp=datetime.now(timezone.utc),
                run_id=run_id,
                event_type="agent_died",
                agent_type=agent_type,
                exit_code=exit_code,
                reason=reason,
            )
            await event_store.append(event)

            if pause_run:
                # Transition run to PAUSED
                old_status = run.status
                run.status = RunStatus.PAUSED
                run.pause_reason = reason
                run.updated_at = datetime.now(timezone.utc)

                # Log the status change event
                status_event = RunStatusChanged(
                    timestamp=datetime.now(timezone.utc),
                    run_id=run_id,
                    event_type="run_status_changed",
                    old_status=old_status,
                    new_status=RunStatus.PAUSED,
                    pause_reason=reason,
                )
                await event_store.append(status_event)

                # Persist the state change
                await repo.save(run)

            await session.commit()

        if pause_run:
            logger.warning(
                f"Run {run_id}: agent {agent_type.value} died (exit_code={exit_code}), "
                f"transitioned to PAUSED. Reason: {reason}"
            )
        else:
            logger.warning(
                f"Run {run_id}: agent {agent_type.value} died (exit_code={exit_code}), "
                f"logged event only (pause_run=False). Reason: {reason}"
            )

    async def check_agent_alive(self, run: Run) -> bool:
        """Check if a run's agent is still active.

        Different checks are performed based on the agent type:
        - CLI_SUBPROCESS: Check if PID from agent_config is alive
        - OPENHANDS_DOCKER: Check if container from agent_config is running
        - OPENHANDS_LOCAL: Always returns False (in-process agent gone after restart)
        - USER_MANAGED: Check if last_activity_at is within timeout

        Args:
            run: The run to check.

        Returns:
            True if the agent is still alive/active, False otherwise.
        """
        if run.agent_type is None:
            return False

        if run.agent_type == AgentRunnerType.CLI_SUBPROCESS:
            # CLIAgent spawns a NEW subprocess per task (each execute() call
            # creates a fresh `claude` process).  Between tasks the old PID is
            # dead while the executor loop is still running.  PID-based health
            # checking therefore causes false "agent died" events that pause
            # the run mid-flight.
            #
            # Like OPENHANDS_LOCAL / CLAUDE_SDK / CODEX_SERVER, the executor's
            # own try/except handles subprocess failures, so the health monitor
            # should not interfere during normal operation.  On startup recovery,
            # recover_active_runs_on_startup handles orphaned runs separately.
            return True

        elif run.agent_type == AgentRunnerType.OPENHANDS_DOCKER:
            # Check if container from run metadata is still running
            container_id = run.agent_config.get("container_id")
            if container_id is None:
                return False
            return await _is_container_running(container_id)

        elif run.agent_type == AgentRunnerType.OPENHANDS_LOCAL:
            # In-process agent — runs via asyncio.to_thread inside the
            # executor task.  The executor's own try/except handles failures,
            # so the health monitor should not interfere while it's running.
            # On startup recovery, recover_active_runs_on_startup handles
            # orphaned runs separately.
            return True

        elif run.agent_type == AgentRunnerType.CODEX_SERVER:
            # CodexServerAgent spawns a NEW subprocess per task (each execute()
            # call creates a fresh codex app-server process).  Between tasks the
            # old PID is dead while the executor loop is still running.  PID-based
            # health checking therefore causes false "agent died" events that
            # pause the run mid-flight.
            #
            # Like OPENHANDS_LOCAL / CLAUDE_SDK, the executor's own try/except
            # handles subprocess failures, so the health monitor should not
            # interfere during normal operation.  On startup recovery,
            # recover_active_runs_on_startup handles orphaned runs separately.
            return True

        elif run.agent_type == AgentRunnerType.USER_MANAGED:
            # Check if last activity was within timeout
            last_activity_str = run.agent_config.get("last_activity_at")
            if last_activity_str is None:
                return False

            # Parse the timestamp (stored as ISO string)
            try:
                if isinstance(last_activity_str, str):
                    last_activity = datetime.fromisoformat(last_activity_str.replace("Z", "+00:00"))
                elif isinstance(last_activity_str, datetime):
                    last_activity = last_activity_str
                else:
                    return False
            except (ValueError, AttributeError):
                return False

            # Get timeout from global config
            timeout_minutes = self._global_config.agents.user_managed_timeout_minutes
            timeout = timedelta(minutes=timeout_minutes)

            # Check if activity is recent enough
            now = datetime.now(timezone.utc)
            return now - last_activity < timeout

        elif run.agent_type == AgentRunnerType.CLAUDE_SDK:
            # In-process agent — same rationale as OPENHANDS_LOCAL
            return True

        # Unknown agent type
        return False

    async def recover_active_runs_on_startup(self) -> list[str]:
        """Check all ACTIVE runs and pause those whose agents are no longer alive.

        This is called on application startup to handle runs that were ACTIVE
        when the orchestrator was shut down.

        Creates a fresh DB session to list runs. Each on_agent_died call
        creates its own session internally.

        Returns:
            List of run IDs that were transitioned to PAUSED.
        """
        from orchestrator.db import RunRepository

        paused_runs: list[str] = []

        # Get all ACTIVE runs using a fresh session
        async with self._session_factory() as session:
            repo = RunRepository(session)
            active_runs = await repo.list_by_status(RunStatus.ACTIVE)

        # In-process agent types cannot survive a server restart, so they
        # are always considered dead on startup regardless of check_agent_alive
        # (which returns True for them during normal operation to avoid the
        # periodic health monitor killing them prematurely).
        _IN_PROCESS_AGENT_TYPES = {
            AgentRunnerType.OPENHANDS_LOCAL,
            AgentRunnerType.CLAUDE_SDK,
            AgentRunnerType.CODEX_SERVER,  # per-task subprocess; cannot survive restart
            AgentRunnerType.CLI_SUBPROCESS,  # per-task subprocess; cannot survive restart
        }

        for run in active_runs:
            if run.agent_type in _IN_PROCESS_AGENT_TYPES:
                agent_alive = False
            else:
                agent_alive = await self.check_agent_alive(run)

            if not agent_alive:
                # on_agent_died creates its own session and commits
                await self.on_agent_died(
                    run_id=run.id,
                    agent_type=run.agent_type or AgentRunnerType.CLI_SUBPROCESS,
                    reason="agent_not_running_on_startup",
                )
                paused_runs.append(run.id)
                logger.info(f"Run {run.id}: agent not running on startup, moved to PAUSED")
            else:
                logger.info(f"Run {run.id}: agent still alive, no action needed")

        return paused_runs
