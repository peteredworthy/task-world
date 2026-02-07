"""Agent liveness monitoring and death handling."""

import asyncio
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone

from orchestrator.config.enums import AgentType, RunStatus
from orchestrator.config.global_config import GlobalConfig
from orchestrator.db.event_store import EventStore
from orchestrator.db.repositories import RunRepository
from orchestrator.state.models import Run
from orchestrator.workflow.events import AgentDiedEvent, RunStatusChanged

logger = logging.getLogger(__name__)


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive.

    Uses os.kill(pid, 0) which sends no signal but checks if the process exists.
    Returns False if the process doesn't exist or we don't have permission to check it.
    """
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


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


class AgentMonitor:
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
        repository: RunRepository,
        event_store: EventStore,
        global_config: GlobalConfig | None = None,
    ) -> None:
        """Initialize the agent monitor.

        Args:
            repository: Run repository for loading and saving runs.
            event_store: Event store for logging agent events.
            global_config: Global configuration (used for timeouts, etc).
        """
        self._repository = repository
        self._event_store = event_store
        self._global_config = global_config or GlobalConfig()

    async def on_agent_died(
        self,
        run_id: str,
        agent_type: AgentType,
        exit_code: int | None = None,
        reason: str = "agent_process_died",
    ) -> None:
        """Handle unexpected agent death - transition run to PAUSED.

        This is called by agent wrappers when they detect the agent process
        has died unexpectedly (not via normal completion or orchestrator kill).

        The run is transitioned from ACTIVE to PAUSED so the user can resume
        with the same or a different agent.

        Args:
            run_id: The run whose agent died.
            agent_type: The type of agent that died.
            exit_code: Optional exit code if available.
            reason: Reason string (e.g., "agent_process_died", "agent_not_running_on_startup").
        """
        run = await self._repository.get(run_id)

        # Only handle if the run is still ACTIVE
        # (might have been manually paused/stopped in the meantime)
        if run.status != RunStatus.ACTIVE:
            logger.info(f"Run {run_id}: agent died but run is {run.status}, no action taken")
            return

        # Log the agent death event
        event = AgentDiedEvent(
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            event_type="agent_died",
            agent_type=agent_type,
            exit_code=exit_code,
            reason=reason,
        )
        await self._event_store.append(event)

        # Transition run to PAUSED
        old_status = run.status
        run.status = RunStatus.PAUSED
        run.updated_at = datetime.now(timezone.utc)

        # Log the status change event
        status_event = RunStatusChanged(
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            event_type="run_status_changed",
            old_status=old_status,
            new_status=RunStatus.PAUSED,
        )
        await self._event_store.append(status_event)

        # Persist the state change
        await self._repository.save(run)

        logger.warning(
            f"Run {run_id}: agent {agent_type.value} died (exit_code={exit_code}), "
            f"transitioned to PAUSED. Reason: {reason}"
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

        if run.agent_type == AgentType.CLI_SUBPROCESS:
            # Check if PID from run metadata is still alive
            pid = run.agent_config.get("pid")
            if pid is None:
                return False
            return _is_process_alive(pid)

        elif run.agent_type == AgentType.OPENHANDS_DOCKER:
            # Check if container from run metadata is still running
            container_id = run.agent_config.get("container_id")
            if container_id is None:
                return False
            return await _is_container_running(container_id)

        elif run.agent_type == AgentType.OPENHANDS_LOCAL:
            # In-process agent — if server restarted, agent is gone
            return False

        elif run.agent_type == AgentType.USER_MANAGED:
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

        # Unknown agent type
        return False

    async def recover_active_runs_on_startup(self) -> list[str]:
        """Check all ACTIVE runs and pause those whose agents are no longer alive.

        This is called on application startup to handle runs that were ACTIVE
        when the orchestrator was shut down.

        Returns:
            List of run IDs that were transitioned to PAUSED.
        """
        paused_runs: list[str] = []

        # Get all ACTIVE runs
        active_runs = await self._repository.list_by_status(RunStatus.ACTIVE)

        for run in active_runs:
            agent_alive = await self.check_agent_alive(run)

            if not agent_alive:
                # Log event and transition to PAUSED
                await self.on_agent_died(
                    run_id=run.id,
                    agent_type=run.agent_type or AgentType.CLI_SUBPROCESS,
                    reason="agent_not_running_on_startup",
                )
                paused_runs.append(run.id)
                logger.info(f"Run {run.id}: agent not running on startup, moved to PAUSED")
            else:
                logger.info(f"Run {run.id}: agent still alive, no action needed")
                # TODO: Re-attach monitoring for still-alive agents
                # This would require storing monitor state and reconnecting to processes

        return paused_runs
