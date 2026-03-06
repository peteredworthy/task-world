"""Unit tests for shared OpenHands code in openhands_common.py.

Tests for build_openhands_prompt, extract_metrics, CallbackRegistry,
and tool registration helpers.
"""

import asyncio
from typing import Any

from orchestrator.runners.openhands_common import (
    DEFAULT_OPENHANDS_TOOLS,
    OPENHANDS_TOOL_IMPORTS,
    CallbackRegistry,
    build_openhands_prompt,
    extract_metrics,
)
from orchestrator.runners.types import ExecutionContext, ExecutionMetrics
from orchestrator.config.enums import ChecklistStatus


# --- build_openhands_prompt ---


def test_build_openhands_prompt_includes_requirements() -> None:
    ctx = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="Build the auth system",
        requirements=["Add login form", "Add logout button"],
    )
    result = build_openhands_prompt(ctx)

    assert "Build the auth system" in result
    assert "- Add login form" in result
    assert "- Add logout button" in result
    assert "## Requirements" in result
    assert "## Orchestrator Integration" in result
    assert "### Available Tools" in result
    assert "orc_get_requirements" in result
    assert "orc_update_checklist" in result
    assert "orc_submit" in result


def test_build_openhands_prompt_empty_requirements() -> None:
    ctx = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="Do the thing",
        requirements=[],
    )
    result = build_openhands_prompt(ctx)

    assert "Do the thing" in result
    assert "## Requirements" in result


def test_build_openhands_prompt_single_requirement() -> None:
    ctx = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="Fix the bug",
        requirements=["R1"],
    )
    result = build_openhands_prompt(ctx)
    assert "- R1" in result


# --- extract_metrics ---


def test_extract_metrics_no_stats() -> None:
    """Returns empty metrics when conversation_stats is None."""

    class FakeConversation:
        conversation_stats = None

    result = extract_metrics(FakeConversation())
    assert result == ExecutionMetrics()


def test_extract_metrics_with_stats() -> None:
    """Extracts token counts from conversation stats."""

    class FakeTokenUsage:
        prompt_tokens = 1000
        completion_tokens = 500
        cache_read_tokens = 200

    class FakeMetrics:
        accumulated_token_usage = FakeTokenUsage()

    class FakeStats:
        usage_to_metrics = {"gpt-4": FakeMetrics()}

    class FakeConversation:
        conversation_stats = FakeStats()

    result = extract_metrics(FakeConversation())
    assert result.tokens_read == 1000
    assert result.tokens_write == 500
    assert result.tokens_cache == 200


def test_extract_metrics_multiple_models() -> None:
    """Sums token counts across multiple models."""

    class FakeTokenUsage:
        def __init__(self, prompt: int, completion: int, cache: int) -> None:
            self.prompt_tokens = prompt
            self.completion_tokens = completion
            self.cache_read_tokens = cache

    class FakeMetrics:
        def __init__(self, usage: FakeTokenUsage) -> None:
            self.accumulated_token_usage = usage

    class FakeStats:
        usage_to_metrics = {
            "model-a": FakeMetrics(FakeTokenUsage(100, 50, 10)),
            "model-b": FakeMetrics(FakeTokenUsage(200, 100, 20)),
        }

    class FakeConversation:
        conversation_stats = FakeStats()

    result = extract_metrics(FakeConversation())
    assert result.tokens_read == 300
    assert result.tokens_write == 150
    assert result.tokens_cache == 30


def test_extract_metrics_none_token_usage() -> None:
    """Handles None accumulated_token_usage gracefully."""

    class FakeMetrics:
        accumulated_token_usage = None

    class FakeStats:
        usage_to_metrics = {"gpt-4": FakeMetrics()}

    class FakeConversation:
        conversation_stats = FakeStats()

    result = extract_metrics(FakeConversation())
    assert result == ExecutionMetrics()


def test_extract_metrics_exception() -> None:
    """Returns empty metrics on any exception."""

    class FakeConversation:
        @property
        def conversation_stats(self) -> None:
            raise RuntimeError("boom")

    result = extract_metrics(FakeConversation())
    assert result == ExecutionMetrics()


# --- CallbackRegistry ---


def test_callback_registry_register_and_get() -> None:
    registry = CallbackRegistry()

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        pass

    loop = asyncio.new_event_loop()
    try:
        registry.register("key1", on_update, on_submit, loop)
        entry = registry.get("key1")
        assert entry["on_checklist_update"] is on_update
        assert entry["on_submit"] is on_submit
        assert entry["loop"] is loop
    finally:
        loop.close()


def test_callback_registry_pop() -> None:
    registry = CallbackRegistry()

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        pass

    loop = asyncio.new_event_loop()
    try:
        registry.register("key1", on_update, on_submit, loop)
        entry = registry.pop("key1")
        assert entry is not None
        assert entry["on_checklist_update"] is on_update

        # Second pop returns None
        assert registry.pop("key1") is None
    finally:
        loop.close()


def test_callback_registry_get_missing_key() -> None:
    registry = CallbackRegistry()
    import pytest

    with pytest.raises(KeyError):
        registry.get("nonexistent")


def test_callback_registry_pop_missing_key() -> None:
    registry = CallbackRegistry()
    assert registry.pop("nonexistent") is None


# --- Tool registry constants ---


def test_openhands_tool_imports_has_expected_keys() -> None:
    """OPENHANDS_TOOL_IMPORTS has the expected built-in tool names."""
    assert "terminal" in OPENHANDS_TOOL_IMPORTS
    assert "file_editor" in OPENHANDS_TOOL_IMPORTS
    assert "browser" in OPENHANDS_TOOL_IMPORTS
    assert "glob" in OPENHANDS_TOOL_IMPORTS
    assert "grep" in OPENHANDS_TOOL_IMPORTS


# --- ValidateRoutineExecutor ---


def test_validate_routine_valid_yaml(tmp_path: Any) -> None:
    """Valid routine YAML returns success message."""
    from orchestrator.runners.openhands_common import ValidateRoutineExecutor

    routine_dir = tmp_path / "routines" / "test"
    routine_dir.mkdir(parents=True)
    routine_file = routine_dir / "routine.yaml"
    routine_file.write_text(
        'id: "test"\nname: "Test"\nsteps:\n'
        '  - id: "S-01"\n    title: "Step 1"\n    tasks:\n'
        '      - id: "T-01"\n        title: "Task 1"\n'
        '        task_context: "Do the thing"\n'
    )

    executor = ValidateRoutineExecutor(str(tmp_path), observation_factory=lambda text: text)
    result = executor.validate("routines/test/routine.yaml")
    assert "VALID" in result


def test_validate_routine_invalid_yaml(tmp_path: Any) -> None:
    """Invalid routine YAML returns validation errors."""
    from orchestrator.runners.openhands_common import ValidateRoutineExecutor

    routine_dir = tmp_path / "routines" / "test"
    routine_dir.mkdir(parents=True)
    routine_file = routine_dir / "routine.yaml"
    routine_file.write_text('id: "test"\nschema_version: "1"\n')

    executor = ValidateRoutineExecutor(str(tmp_path), observation_factory=lambda text: text)
    result = executor.validate("routines/test/routine.yaml")
    assert "VALIDATION FAILED" in result


def test_validate_routine_missing_file(tmp_path: Any) -> None:
    """Missing file returns error."""
    from orchestrator.runners.openhands_common import ValidateRoutineExecutor

    executor = ValidateRoutineExecutor(str(tmp_path), observation_factory=lambda text: text)
    result = executor.validate("nonexistent.yaml")
    assert "ERROR" in result
    assert "not found" in result.lower()


def test_default_openhands_tools() -> None:
    """DEFAULT_OPENHANDS_TOOLS includes terminal and file_editor."""
    assert DEFAULT_OPENHANDS_TOOLS == ["terminal", "file_editor"]


def test_all_default_tools_in_imports() -> None:
    """Every default tool has a corresponding module path in OPENHANDS_TOOL_IMPORTS."""
    for tool_name in DEFAULT_OPENHANDS_TOOLS:
        assert tool_name in OPENHANDS_TOOL_IMPORTS
