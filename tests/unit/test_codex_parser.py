"""Tests for Codex --json parser."""

import json

from orchestrator.state.models import ActionEntryKind
from orchestrator.runners import CodexStreamParser


def _make_line(event: dict) -> str:
    return json.dumps(event)


def test_thread_started():
    parser = CodexStreamParser()
    parser.parse_line(_make_line({"type": "thread.started"}))
    log = parser.finalize()

    assert len(log.entries) == 1
    assert log.entries[0].kind == ActionEntryKind.SYSTEM_INIT
    assert log.entries[0].raw_type == "thread.started"


def test_message_created_assistant():
    parser = CodexStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "message.created",
                "role": "assistant",
                "content": "Here is the plan.",
                "usage": {"input_tokens": 200, "output_tokens": 40},
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.ASSISTANT_TEXT
    assert entry.text == "Here is the plan."
    assert entry.metrics is not None
    assert entry.metrics.input_tokens == 200

    assert "Here is the plan." in parser.get_readable_text()


def test_message_created_user_skipped():
    """Non-assistant messages are skipped."""
    parser = CodexStreamParser()
    parser.parse_line(_make_line({"type": "message.created", "role": "user", "content": "help"}))
    log = parser.finalize()
    assert len(log.entries) == 0


def test_tool_call():
    parser = CodexStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "tool_call",
                "id": "tc_1",
                "name": "bash",
                "arguments": {"command": "echo hello"},
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.TOOL_USE
    assert entry.tool_use is not None
    assert entry.tool_use.tool_use_id == "tc_1"
    assert entry.tool_use.tool_name == "bash"
    assert entry.tool_use.summary == "bash: echo hello"


def test_tool_call_with_string_arguments():
    """Codex may pass arguments as a JSON string."""
    parser = CodexStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "tool_call",
                "id": "tc_2",
                "name": "read",
                "arguments": json.dumps({"file_path": "test.py"}),
            }
        )
    )
    log = parser.finalize()
    entry = log.entries[0]
    assert entry.tool_use is not None
    assert entry.tool_use.arguments == {"file_path": "test.py"}


def test_tool_output():
    parser = CodexStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "tool_output",
                "call_id": "tc_1",
                "output": "hello\n",
                "exit_code": 0,
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.TOOL_RESULT
    assert entry.tool_result is not None
    assert entry.tool_result.tool_use_id == "tc_1"
    assert entry.tool_result.output == "hello\n"
    assert entry.tool_result.exit_code == 0
    assert entry.tool_result.success is True


def test_tool_output_failure():
    parser = CodexStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "tool_output",
                "call_id": "tc_fail",
                "output": "error: permission denied",
                "exit_code": 1,
                "success": False,
            }
        )
    )
    log = parser.finalize()

    entry = log.entries[0]
    assert entry.tool_result is not None
    assert entry.tool_result.success is False
    assert entry.tool_result.exit_code == 1


def test_result_event():
    parser = CodexStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "result",
                "content": "All tasks completed successfully.",
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.RESULT
    assert entry.text == "All tasks completed successfully."
    assert "All tasks completed" in parser.get_readable_text()


def test_turn_completed():
    parser = CodexStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "turn.completed",
                "message": "Turn done.",
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    assert log.entries[0].kind == ActionEntryKind.RESULT


def test_error_event():
    parser = CodexStreamParser()
    parser.parse_line(_make_line({"type": "error", "message": "Something went wrong"}))
    log = parser.finalize()

    assert len(log.entries) == 1
    assert log.entries[0].kind == ActionEntryKind.ERROR
    assert log.entries[0].text == "Something went wrong"


def test_turn_failed():
    parser = CodexStreamParser()
    parser.parse_line(_make_line({"type": "turn.failed", "message": "Tool execution failed"}))
    log = parser.finalize()

    assert len(log.entries) == 1
    assert log.entries[0].kind == ActionEntryKind.ERROR


def test_item_completed_agent_message():
    parser = CodexStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "item.completed",
                "item": {"id": "item_1", "type": "agent_message", "text": "Review complete."},
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    assert log.entries[0].kind == ActionEntryKind.ASSISTANT_TEXT
    assert log.entries[0].text == "Review complete."
    assert "Review complete." in parser.get_readable_text()


def test_item_completed_reasoning():
    parser = CodexStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "item.completed",
                "item": {"id": "item_2", "type": "reasoning", "text": "Checking files..."},
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    assert log.entries[0].kind == ActionEntryKind.THINKING
    assert log.entries[0].text == "Checking files..."


def test_item_completed_command_execution():
    parser = CodexStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_3",
                    "type": "command_execution",
                    "command": "/bin/zsh -lc 'rg -n foo src'",
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": "src/example.py:42:foo",
                },
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 2
    assert log.entries[0].kind == ActionEntryKind.TOOL_USE
    assert log.entries[0].tool_use is not None
    assert log.entries[0].tool_use.tool_name == "bash"
    assert log.entries[0].tool_use.tool_use_id == "item_3"
    assert log.entries[1].kind == ActionEntryKind.TOOL_RESULT
    assert log.entries[1].tool_result is not None
    assert log.entries[1].tool_result.tool_use_id == "item_3"
    assert log.entries[1].tool_result.exit_code == 0
    assert log.entries[1].tool_result.success is True


def test_full_conversation():
    parser = CodexStreamParser()

    events = [
        {"type": "thread.started"},
        {"type": "message.created", "role": "assistant", "content": "Starting work."},
        {
            "type": "tool_call",
            "id": "tc_1",
            "name": "bash",
            "arguments": {"command": "cat README.md"},
        },
        {"type": "tool_output", "call_id": "tc_1", "output": "# My Project\n"},
        {"type": "result", "content": "Done!"},
    ]

    for event in events:
        parser.parse_line(_make_line(event))

    log = parser.finalize()

    assert len(log.entries) == 5
    assert log.entries[0].kind == ActionEntryKind.SYSTEM_INIT
    assert log.entries[1].kind == ActionEntryKind.ASSISTANT_TEXT
    assert log.entries[2].kind == ActionEntryKind.TOOL_USE
    assert log.entries[3].kind == ActionEntryKind.TOOL_RESULT
    assert log.entries[4].kind == ActionEntryKind.RESULT
    assert log.total_turns == 1


def test_skips_unknown_types():
    parser = CodexStreamParser()
    parser.parse_line(_make_line({"type": "something.unknown", "data": 42}))
    log = parser.finalize()
    assert len(log.entries) == 0


def test_skips_bad_json():
    parser = CodexStreamParser()
    parser.parse_line("not valid json")
    parser.parse_line("")
    log = parser.finalize()
    assert len(log.entries) == 0


def test_parse_jsonrpc_message_accumulates_delta_and_command_execution() -> None:
    parser = CodexStreamParser()

    parser.parse_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "method": "item/agentMessage/delta",
            "params": {"delta": "Checking files"},
        }
    )
    parser.parse_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "method": "item/agentMessage/delta",
            "params": {"delta": " now"},
        }
    )
    parser.parse_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "method": "item/completed",
            "params": {
                "item": {
                    "id": "cmd_1",
                    "type": "commandExecution",
                    "command": "git status --short",
                    "status": "completed",
                    "exitCode": 0,
                    "aggregatedOutput": " M src/example.py",
                }
            },
        }
    )

    log = parser.finalize()

    assert [entry.kind for entry in log.entries] == [
        ActionEntryKind.ASSISTANT_TEXT,
        ActionEntryKind.TOOL_USE,
        ActionEntryKind.TOOL_RESULT,
    ]
    assert log.entries[0].text == "Checking files now"
    assert log.entries[1].tool_use is not None
    assert log.entries[1].tool_use.summary == "bash: git status --short"
    assert log.entries[2].tool_result is not None
    assert log.entries[2].tool_result.output == " M src/example.py"


def test_parse_jsonrpc_message_handles_file_change_item() -> None:
    parser = CodexStreamParser()

    parser.parse_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "method": "item/completed",
            "params": {
                "item": {
                    "id": "fc_1",
                    "type": "fileChange",
                    "status": "completed",
                    "changes": [
                        {"path": "/tmp/a.py", "kind": "update"},
                        {"path": "/tmp/b.py", "kind": "create"},
                    ],
                }
            },
        }
    )

    log = parser.finalize()

    assert [entry.kind for entry in log.entries] == [ActionEntryKind.TOOL_USE]
    assert log.entries[0].tool_use is not None
    assert log.entries[0].tool_use.tool_name == "file_change"
    assert log.entries[0].tool_use.summary == "file change: 2 update(s)"


def test_parse_jsonrpc_message_records_dynamic_tool_call_and_result() -> None:
    parser = CodexStreamParser()

    parser.parse_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 17,
            "method": "item/tool/call",
            "params": {
                "tool": "update_checklist",
                "arguments": {"req_id": "R-01", "status": "done"},
            },
        }
    )
    parser.record_dynamic_tool_result("17", success=True)

    log = parser.finalize()

    assert [entry.kind for entry in log.entries] == [
        ActionEntryKind.TOOL_USE,
        ActionEntryKind.TOOL_RESULT,
    ]
    assert log.entries[0].tool_use is not None
    assert log.entries[0].tool_use.tool_name == "update_checklist"
    assert log.entries[1].tool_result is not None
    assert log.entries[1].tool_result.tool_use_id == "17"
    assert log.entries[1].tool_result.success is True
