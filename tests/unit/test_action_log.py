"""Tests for action log types - serialization/deserialization round-trip."""

from datetime import datetime, timezone

from orchestrator.state.models import (
    ActionEntryKind,
    ActionLog,
    ActionLogEntry,
    ToolResultDetail,
    ToolUseDetail,
    TurnMetrics,
)


def test_action_log_entry_serialization_roundtrip():
    """ActionLogEntry serializes to JSON and back without data loss."""
    entry = ActionLogEntry(
        sequence_num=1,
        kind=ActionEntryKind.TOOL_USE,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        tool_use=ToolUseDetail(
            tool_use_id="tu_123",
            tool_name="bash",
            arguments={"command": "ls -la"},
            summary="bash: ls -la",
        ),
        metrics=TurnMetrics(input_tokens=100, output_tokens=50, cost_usd=0.01),
        raw_type="assistant.tool_use",
    )

    data = entry.model_dump(mode="json")
    restored = ActionLogEntry.model_validate(data)

    assert restored.sequence_num == 1
    assert restored.kind == ActionEntryKind.TOOL_USE
    assert restored.tool_use is not None
    assert restored.tool_use.tool_use_id == "tu_123"
    assert restored.tool_use.tool_name == "bash"
    assert restored.tool_use.arguments == {"command": "ls -la"}
    assert restored.tool_use.summary == "bash: ls -la"
    assert restored.metrics is not None
    assert restored.metrics.input_tokens == 100
    assert restored.metrics.cost_usd == 0.01


def test_action_log_full_roundtrip():
    """Full ActionLog with multiple entry types round-trips through JSON."""
    log = ActionLog(
        entries=[
            ActionLogEntry(
                sequence_num=1,
                kind=ActionEntryKind.SYSTEM_INIT,
                text="Session started",
            ),
            ActionLogEntry(
                sequence_num=2,
                kind=ActionEntryKind.ASSISTANT_TEXT,
                text="Hello, I'll help you.",
            ),
            ActionLogEntry(
                sequence_num=3,
                kind=ActionEntryKind.TOOL_USE,
                tool_use=ToolUseDetail(
                    tool_use_id="tu_1",
                    tool_name="read",
                    arguments={"file_path": "/tmp/test.py"},
                    summary="read: /tmp/test.py",
                ),
            ),
            ActionLogEntry(
                sequence_num=4,
                kind=ActionEntryKind.TOOL_RESULT,
                tool_result=ToolResultDetail(
                    tool_use_id="tu_1",
                    output="print('hello')",
                    success=True,
                    output_length=15,
                ),
            ),
            ActionLogEntry(
                sequence_num=5,
                kind=ActionEntryKind.RESULT,
                text="Done!",
                metrics=TurnMetrics(
                    input_tokens=500,
                    output_tokens=200,
                    cost_usd=0.05,
                ),
            ),
        ],
        session_id="sess_abc",
        agent_model="claude-sonnet-4-5-20250514",
        tools_available=["bash", "read", "write"],
        total_turns=2,
        total_cost_usd=0.05,
        total_input_tokens=500,
        total_output_tokens=200,
    )

    data = log.model_dump(mode="json")
    restored = ActionLog.model_validate(data)

    assert len(restored.entries) == 5
    assert restored.entries[0].kind == ActionEntryKind.SYSTEM_INIT
    assert restored.entries[1].kind == ActionEntryKind.ASSISTANT_TEXT
    assert restored.entries[2].kind == ActionEntryKind.TOOL_USE
    assert restored.entries[3].kind == ActionEntryKind.TOOL_RESULT
    assert restored.entries[4].kind == ActionEntryKind.RESULT
    assert restored.session_id == "sess_abc"
    assert restored.agent_model == "claude-sonnet-4-5-20250514"
    assert restored.tools_available == ["bash", "read", "write"]
    assert restored.total_cost_usd == 0.05


def test_action_log_empty():
    """Empty ActionLog serializes cleanly."""
    log = ActionLog()
    data = log.model_dump(mode="json")
    restored = ActionLog.model_validate(data)

    assert restored.entries == []
    assert restored.session_id is None
    assert restored.total_turns == 0


def test_action_entry_kind_values():
    """ActionEntryKind enum values are correct strings."""
    assert ActionEntryKind.SYSTEM_INIT.value == "system_init"
    assert ActionEntryKind.ASSISTANT_TEXT.value == "assistant_text"
    assert ActionEntryKind.THINKING.value == "thinking"
    assert ActionEntryKind.TOOL_USE.value == "tool_use"
    assert ActionEntryKind.TOOL_RESULT.value == "tool_result"
    assert ActionEntryKind.RESULT.value == "result"
    assert ActionEntryKind.ERROR.value == "error"


def test_tool_result_with_exit_code():
    """ToolResultDetail correctly carries exit_code and success flag."""
    detail = ToolResultDetail(
        tool_use_id="tu_1",
        output="error: file not found",
        exit_code=1,
        success=False,
        output_length=22,
    )
    data = detail.model_dump(mode="json")
    restored = ToolResultDetail.model_validate(data)
    assert restored.exit_code == 1
    assert restored.success is False
    assert restored.output_length == 22
