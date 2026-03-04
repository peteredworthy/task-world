"""Tests for RepetitionDetector, ReasoningRepetitionDetector, and ActionBudget."""

from __future__ import annotations

from orchestrator.agents.repetition_detector import (
    ActionBudget,
    ActionBudgetConfig,
    ReasoningDetectorConfig,
    ReasoningRepetitionDetector,
    RepetitionAction,
    RepetitionDetector,
    RepetitionDetectorConfig,
)


def test_no_kill_initially() -> None:
    detector = RepetitionDetector()
    assert detector.record_action("git status") == RepetitionAction.NONE
    assert detector.total_actions == 1
    assert detector.repeated_command is None


def test_no_kill_below_min_actions() -> None:
    """Even with all identical commands, don't trigger before min_actions."""
    detector = RepetitionDetector(RepetitionDetectorConfig(min_actions=10))
    for _ in range(9):
        assert detector.record_action("git diff") == RepetitionAction.NONE
    assert detector.total_actions == 9


def test_kill_after_repeated_commands() -> None:
    """5 identical commands in a window of 8 after min_actions → KILL."""
    detector = RepetitionDetector(
        RepetitionDetectorConfig(window_size=8, threshold=5, min_actions=5)
    )
    # Fill up to min_actions with the same command
    for i in range(4):
        assert detector.record_action("reset") == RepetitionAction.NONE
    # 5th identical command, meets both min_actions and threshold
    assert detector.record_action("reset") == RepetitionAction.KILL
    assert detector.repeated_command == "reset"


def test_varied_commands_no_kill() -> None:
    """Different commands don't trigger."""
    detector = RepetitionDetector(
        RepetitionDetectorConfig(window_size=8, threshold=5, min_actions=5)
    )
    commands = [
        "git status",
        "ls",
        "cat file.py",
        "git diff",
        "pwd",
        "echo hello",
        "git log",
        "make test",
        "git add .",
        "npm run build",
    ]
    for cmd in commands:
        assert detector.record_action(cmd) == RepetitionAction.NONE
    assert detector.repeated_command is None


def test_mixed_commands_with_majority_repeat() -> None:
    """5 of 8 same command → KILL, even with some different ones mixed in."""
    detector = RepetitionDetector(
        RepetitionDetectorConfig(window_size=8, threshold=5, min_actions=5)
    )
    # First fill min_actions with varied commands
    for i, cmd in enumerate(["a", "b", "c", "d", "e"]):
        detector.record_action(cmd)

    # Now push a pattern: 5 "reset" with 3 other commands in window of 8
    detector.record_action("other1")
    detector.record_action("reset")
    detector.record_action("reset")
    detector.record_action("other2")
    detector.record_action("reset")
    detector.record_action("reset")
    result = detector.record_action("reset")
    assert result == RepetitionAction.KILL
    assert detector.repeated_command == "reset"


def test_further_calls_after_kill_still_kill() -> None:
    """After KILL, the repeated_command stays set."""
    detector = RepetitionDetector(
        RepetitionDetectorConfig(window_size=8, threshold=5, min_actions=5)
    )
    for _ in range(5):
        detector.record_action("reset")
    assert detector.repeated_command == "reset"

    # Further identical commands also return KILL
    assert detector.record_action("reset") == RepetitionAction.KILL
    assert detector.repeated_command == "reset"


def test_whitespace_normalization() -> None:
    """'reset' and 'reset  ' and '  reset' are treated as the same."""
    detector = RepetitionDetector(
        RepetitionDetectorConfig(window_size=8, threshold=5, min_actions=5)
    )
    commands = ["reset", "reset ", " reset", "reset  ", "  reset  "]
    for cmd in commands:
        detector.record_action(cmd)
    assert detector.repeated_command == "reset"


def test_ansi_escape_normalization() -> None:
    """ANSI escape codes are stripped before comparison."""
    detector = RepetitionDetector(
        RepetitionDetectorConfig(window_size=8, threshold=5, min_actions=5)
    )
    plain = "git diff"
    ansi = "\x1b[32mgit diff\x1b[0m"
    for _ in range(3):
        detector.record_action(plain)
    for _ in range(2):
        detector.record_action(ansi)
    assert detector.repeated_command == "git diff"


def test_custom_config() -> None:
    """Custom window_size and threshold values work correctly."""
    detector = RepetitionDetector(
        RepetitionDetectorConfig(window_size=4, threshold=3, min_actions=3)
    )
    for _ in range(3):
        detector.record_action("echo loop")
    assert detector.repeated_command == "echo loop"


def test_empty_command_ignored() -> None:
    """Empty or whitespace-only commands are ignored."""
    detector = RepetitionDetector(RepetitionDetectorConfig(min_actions=1))
    assert detector.record_action("") == RepetitionAction.NONE
    assert detector.record_action("   ") == RepetitionAction.NONE
    assert detector.total_actions == 0


# --- Expanded detection: file_editor and tool actions (#1) ---


def test_file_editor_view_repeat_kills() -> None:
    """5x same file_editor:view path triggers KILL."""
    detector = RepetitionDetector(
        RepetitionDetectorConfig(window_size=8, threshold=5, min_actions=5)
    )
    for _ in range(5):
        result = detector.record_action("file_editor:view:/workspace/src/main.py")
    assert result == RepetitionAction.KILL
    assert detector.repeated_command == "file_editor:view:/workspace/src/main.py"


def test_str_replace_not_tracked() -> None:
    """Productive edits (str_replace) should not be fed to the detector.

    This test verifies the *convention*: callers must not feed str_replace
    actions. The detector itself treats any string the same way.
    """
    detector = RepetitionDetector(
        RepetitionDetectorConfig(window_size=8, threshold=5, min_actions=5)
    )
    # Only views are fed; str_replace actions are skipped by the caller.
    # Here we simulate: 3 views + 5 different commands = no trigger.
    for i in range(3):
        detector.record_action(f"file_editor:view:/workspace/file{i}.py")
    for i in range(5):
        detector.record_action(f"command_{i}")
    assert detector.repeated_command is None


def test_mixed_terminal_and_tool_no_false_positive() -> None:
    """Varied terminal + tool actions don't trigger."""
    detector = RepetitionDetector(
        RepetitionDetectorConfig(window_size=8, threshold=5, min_actions=5)
    )
    actions = [
        "git status",
        "file_editor:view:/workspace/a.py",
        "grep:pattern",
        "ls -la",
        "file_editor:view:/workspace/b.py",
        "glob:*.py",
        "cat README.md",
        "file_editor:view:/workspace/c.py",
        "find . -name '*.txt'",
        "grep:other_pattern",
    ]
    for a in actions:
        assert detector.record_action(a) == RepetitionAction.NONE
    assert detector.repeated_command is None


# --- ReasoningRepetitionDetector (#2) ---


def test_reasoning_kill_on_repeat() -> None:
    """Same 200-char prefix 3x in window triggers KILL after min events."""
    detector = ReasoningRepetitionDetector(
        ReasoningDetectorConfig(window_size=10, threshold=3, min_reasoning_events=5)
    )
    same_text = "A" * 200
    # Fill up to min_reasoning_events with varied texts
    for i in range(4):
        assert (
            detector.record_reasoning(f"different text {i} " + "x" * 200) == RepetitionAction.NONE
        )
    # Now feed the same text 3 times
    assert detector.record_reasoning(same_text) == RepetitionAction.NONE  # 5th total, 1st match
    assert detector.record_reasoning(same_text) == RepetitionAction.NONE  # 6th total, 2nd match
    assert detector.record_reasoning(same_text) == RepetitionAction.KILL  # 7th total, 3rd match


def test_reasoning_no_kill_below_min() -> None:
    """Below min_reasoning_events, no trigger even with repeats."""
    detector = ReasoningRepetitionDetector(
        ReasoningDetectorConfig(window_size=10, threshold=3, min_reasoning_events=5)
    )
    same_text = "B" * 200
    for _ in range(4):
        assert detector.record_reasoning(same_text) == RepetitionAction.NONE


def test_reasoning_varied_no_kill() -> None:
    """Different reasoning texts don't trigger."""
    detector = ReasoningRepetitionDetector(
        ReasoningDetectorConfig(window_size=10, threshold=3, min_reasoning_events=5)
    )
    for i in range(20):
        assert (
            detector.record_reasoning(f"unique reasoning text number {i} " + "x" * 200)
            == RepetitionAction.NONE
        )


def test_reasoning_empty_ignored() -> None:
    """Empty or whitespace-only reasoning is ignored."""
    detector = ReasoningRepetitionDetector()
    assert detector.record_reasoning("") == RepetitionAction.NONE
    assert detector.record_reasoning("   ") == RepetitionAction.NONE
    assert detector.total_events == 0


# --- ActionBudget (#3) ---


def test_action_budget_no_kill_below_limit() -> None:
    """Actions below the limit don't trigger."""
    budget = ActionBudget(ActionBudgetConfig(max_actions=10))
    for _ in range(9):
        assert budget.record_action() == RepetitionAction.NONE
    assert budget.total_actions == 9


def test_action_budget_kills_at_limit() -> None:
    """Reaching the limit triggers KILL."""
    budget = ActionBudget(ActionBudgetConfig(max_actions=5))
    for _ in range(4):
        assert budget.record_action() == RepetitionAction.NONE
    assert budget.record_action() == RepetitionAction.KILL
    assert budget.total_actions == 5


def test_action_budget_disabled_with_zero() -> None:
    """max_actions=0 disables the budget entirely."""
    budget = ActionBudget(ActionBudgetConfig(max_actions=0))
    for _ in range(1000):
        assert budget.record_action() == RepetitionAction.NONE
    assert budget.total_actions == 1000
