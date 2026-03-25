"""Repetition detector for stuck OpenHands agents.

Pure logic, zero I/O. Detects when an agent is stuck repeating the same
terminal command (e.g., ``git diff``, ``reset``, ``Ctrl+C``) in a loop,
when reasoning content shows amnesia patterns, or when the total action
count exceeds a budget.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, deque
from dataclasses import dataclass


class RepetitionAction:
    """Constants for repetition check results."""

    NONE = "none"
    KILL = "kill"


# Regex to strip ANSI escape sequences
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _normalize(command: str) -> str:
    """Strip ANSI escapes and whitespace for comparison."""
    return _ANSI_RE.sub("", command).strip()


@dataclass
class RepetitionDetectorConfig:
    """Configuration for the repetition detector.

    Attributes:
        window_size: Rolling window of recent commands to examine.
        threshold: How many identical commands in the window trigger a kill.
        min_actions: Don't trigger before this many total actions.
    """

    window_size: int = 8
    threshold: int = 5
    min_actions: int = 10


class RepetitionDetector:
    """Detects when an agent is stuck repeating the same command.

    Usage:
        detector = RepetitionDetector(RepetitionDetectorConfig())

        result = detector.record_action("git diff")
        if result == RepetitionAction.KILL:
            # pause the conversation
    """

    def __init__(self, config: RepetitionDetectorConfig | None = None) -> None:
        self.config = config or RepetitionDetectorConfig()
        self._window: deque[str] = deque(maxlen=self.config.window_size)
        self._total_actions: int = 0
        self._repeated_command: str | None = None

    def record_action(self, command: str) -> str:
        """Record a tool command. Returns RepetitionAction.KILL if stuck."""
        normalized = _normalize(command)
        if not normalized:
            return RepetitionAction.NONE

        self._window.append(normalized)
        self._total_actions += 1

        if self._total_actions < self.config.min_actions:
            return RepetitionAction.NONE

        counts = Counter(self._window)
        most_common_cmd, most_common_count = counts.most_common(1)[0]
        if most_common_count >= self.config.threshold:
            self._repeated_command = most_common_cmd
            return RepetitionAction.KILL

        return RepetitionAction.NONE

    @property
    def total_actions(self) -> int:
        """Total number of actions recorded."""
        return self._total_actions

    @property
    def repeated_command(self) -> str | None:
        """The command that triggered the kill, if any."""
        return self._repeated_command


# ---------------------------------------------------------------------------
# Reasoning repetition detector
# ---------------------------------------------------------------------------


@dataclass
class ReasoningDetectorConfig:
    """Configuration for reasoning repetition detection.

    Attributes:
        window_size: Rolling window of recent reasoning fingerprints.
        threshold: How many identical fingerprints in the window trigger a kill.
        min_reasoning_events: Don't trigger before this many reasoning events.
        fingerprint_chars: Number of leading chars to fingerprint.
    """

    window_size: int = 10
    threshold: int = 3
    min_reasoning_events: int = 5
    fingerprint_chars: int = 200


class ReasoningRepetitionDetector:
    """Detects when an agent keeps restarting with the same reasoning prefix.

    Fingerprints the first N characters of reasoning text (MD5 hash) and
    tracks occurrences in a rolling window. Triggers KILL when the same
    fingerprint appears ``threshold`` times after ``min_reasoning_events``.
    """

    def __init__(self, config: ReasoningDetectorConfig | None = None) -> None:
        self.config = config or ReasoningDetectorConfig()
        self._window: deque[str] = deque(maxlen=self.config.window_size)
        self._total: int = 0

    def record_reasoning(self, text: str) -> str:
        """Record reasoning text. Returns RepetitionAction.KILL if stuck."""
        stripped = text.strip()
        if not stripped:
            return RepetitionAction.NONE

        prefix = stripped[: self.config.fingerprint_chars]
        fingerprint = hashlib.md5(prefix.encode("utf-8", errors="replace")).hexdigest()

        self._window.append(fingerprint)
        self._total += 1

        if self._total < self.config.min_reasoning_events:
            return RepetitionAction.NONE

        counts = Counter(self._window)
        _, top_count = counts.most_common(1)[0]
        if top_count >= self.config.threshold:
            return RepetitionAction.KILL

        return RepetitionAction.NONE

    @property
    def total_events(self) -> int:
        return self._total


# ---------------------------------------------------------------------------
# Action budget
# ---------------------------------------------------------------------------


@dataclass
class ActionBudgetConfig:
    """Configuration for action budget.

    Attributes:
        max_actions: Hard ceiling on total actions. 0 disables the budget.
    """

    max_actions: int = 200


class ActionBudget:
    """Enforces a hard cap on total agent actions independent of iteration count.

    Returns ``RepetitionAction.KILL`` once total actions >= ``max_actions``.
    A ``max_actions`` of 0 disables the budget entirely.
    """

    def __init__(self, config: ActionBudgetConfig | None = None) -> None:
        self.config = config or ActionBudgetConfig()
        self._total: int = 0

    def record_action(self) -> str:
        """Record an action. Returns KILL if budget exhausted."""
        self._total += 1

        if self.config.max_actions == 0:
            return RepetitionAction.NONE

        if self._total >= self.config.max_actions:
            return RepetitionAction.KILL

        return RepetitionAction.NONE

    @property
    def total_actions(self) -> int:
        return self._total
