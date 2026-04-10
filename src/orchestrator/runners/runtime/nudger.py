"""Nudger: stuck detection for CLI subprocess agents.

Pure logic, zero I/O. All time-dependent behavior uses injected TimeProvider.
"""

from datetime import datetime
from typing import Protocol

from orchestrator.config.models import NudgerConfig


class TimeProvider(Protocol):
    """Protocol for injectable time source."""

    def now(self) -> datetime: ...


class NudgeAction:
    """Constants for nudge check results."""

    NONE = "none"
    NUDGE = "nudge"
    KILL = "kill"


class Nudger:
    """Detects stuck CLI agents and decides when to nudge or kill.

    Usage:
        nudger = Nudger(config, time_provider)
        nudger.record_output()  # Call when agent produces output

        action = nudger.check()
        if action == NudgeAction.NUDGE:
            message = nudger.record_nudge()
            # send message to agent stdin
        elif action == NudgeAction.KILL:
            # terminate the agent
    """

    def __init__(self, config: NudgerConfig, time_provider: TimeProvider) -> None:
        self._config = config
        self._time = time_provider
        self._last_output_at: datetime = time_provider.now()
        self._last_nudge_at: datetime | None = None
        self._nudge_count: int = 0

    def record_output(self) -> None:
        """Record that the agent produced output. Resets stuck timer and nudge count."""
        self._last_output_at = self._time.now()
        self._nudge_count = 0
        self._last_nudge_at = None

    def check(self) -> str:
        """Check if the agent is stuck.

        Returns:
            NudgeAction.NONE: Agent is producing output normally.
            NudgeAction.NUDGE: Agent appears stuck, should be nudged.
            NudgeAction.KILL: Agent has been nudged too many times, should be killed.
        """
        now = self._time.now()
        elapsed_since_output = now - self._last_output_at

        # Not stuck yet
        if elapsed_since_output < self._config.output_timeout:
            return NudgeAction.NONE

        # Max nudges reached — kill
        if self._nudge_count >= self._config.max_nudges:
            return NudgeAction.KILL

        # Check nudge interval
        if self._last_nudge_at is not None:
            elapsed_since_nudge = now - self._last_nudge_at
            if elapsed_since_nudge < self._config.nudge_interval:
                return NudgeAction.NONE

        return NudgeAction.NUDGE

    def record_nudge(self) -> str:
        """Record that a nudge was sent. Returns the nudge message."""
        self._nudge_count += 1
        self._last_nudge_at = self._time.now()
        return self._config.nudge_message

    @property
    def nudge_count(self) -> int:
        """Number of nudges sent since last output."""
        return self._nudge_count
