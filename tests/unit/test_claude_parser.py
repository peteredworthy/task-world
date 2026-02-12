"""Tests for Claude stream-json parser."""

import json

from orchestrator.agents.action_log import ActionEntryKind
from orchestrator.agents.parsers.claude_parser import ClaudeStreamParser


def _make_line(event: dict) -> str:
    return json.dumps(event)


def test_system_init():
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "sess_123",
                "model": "claude-sonnet-4-5-20250514",
                "tools": ["bash", "read", "write"],
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    assert log.entries[0].kind == ActionEntryKind.SYSTEM_INIT
    assert log.session_id == "sess_123"
    assert log.agent_model == "claude-sonnet-4-5-20250514"
    assert log.tools_available == ["bash", "read", "write"]


def test_assistant_text():
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "assistant",
                "content": [{"type": "text", "text": "Hello, world!"}],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.ASSISTANT_TEXT
    assert entry.text == "Hello, world!"
    assert entry.metrics is not None
    assert entry.metrics.input_tokens == 100
    assert entry.metrics.output_tokens == 50

    # Readable text should include the message
    assert "Hello, world!" in parser.get_readable_text()


def test_thinking_block():
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "assistant",
                "content": [{"type": "thinking", "thinking": "Let me consider..."}],
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    assert log.entries[0].kind == ActionEntryKind.THINKING
    assert log.entries[0].text == "Let me consider..."


def test_tool_use():
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_abc",
                        "name": "bash",
                        "input": {"command": "ls -la"},
                    }
                ],
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.TOOL_USE
    assert entry.tool_use is not None
    assert entry.tool_use.tool_use_id == "tu_abc"
    assert entry.tool_use.tool_name == "bash"
    assert entry.tool_use.arguments == {"command": "ls -la"}
    assert entry.tool_use.summary == "bash: ls -la"


def test_tool_result():
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "tool_result",
                "tool_use_id": "tu_abc",
                "content": "file1.py\nfile2.py",
                "is_error": False,
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.TOOL_RESULT
    assert entry.tool_result is not None
    assert entry.tool_result.tool_use_id == "tu_abc"
    assert entry.tool_result.output == "file1.py\nfile2.py"
    assert entry.tool_result.success is True
    assert entry.tool_result.output_length == 17


def test_tool_result_truncation():
    parser = ClaudeStreamParser()
    long_output = "x" * 10000
    parser.parse_line(
        _make_line(
            {
                "type": "tool_result",
                "tool_use_id": "tu_big",
                "content": long_output,
            }
        )
    )
    log = parser.finalize()

    entry = log.entries[0]
    assert entry.tool_result is not None
    assert len(entry.tool_result.output) < len(long_output)
    assert entry.tool_result.output_length == 10000
    assert entry.tool_result.output.endswith("... (truncated)")


def test_result_event():
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "result",
                "content": [{"type": "text", "text": "Task completed!"}],
                "usage": {"input_tokens": 1000, "output_tokens": 500},
                "cost_usd": 0.05,
                "duration_ms": 30000,
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.RESULT
    assert entry.text == "Task completed!"
    assert log.total_cost_usd == 0.05
    assert log.total_input_tokens == 1000
    assert log.total_output_tokens == 500

    # Readable text should include the result
    assert "Task completed!" in parser.get_readable_text()


def test_error_event():
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "error",
                "error": {"message": "Rate limit exceeded"},
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 1
    assert log.entries[0].kind == ActionEntryKind.ERROR
    assert log.entries[0].text == "Rate limit exceeded"


def test_full_conversation():
    """Test parsing a full conversation flow."""
    parser = ClaudeStreamParser()

    lines = [
        {
            "type": "system",
            "subtype": "init",
            "session_id": "s1",
            "model": "claude-sonnet-4-5-20250514",
            "tools": ["bash"],
        },
        {
            "type": "assistant",
            "content": [{"type": "text", "text": "I'll check the files."}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
        {
            "type": "assistant",
            "content": [
                {"type": "tool_use", "id": "tu_1", "name": "bash", "input": {"command": "ls"}}
            ],
        },
        {"type": "tool_result", "tool_use_id": "tu_1", "content": "main.py\ntest.py"},
        {
            "type": "assistant",
            "content": [{"type": "text", "text": "Found 2 files."}],
            "usage": {"input_tokens": 200, "output_tokens": 15},
        },
        {
            "type": "result",
            "content": [{"type": "text", "text": "Done!"}],
            "usage": {"input_tokens": 300, "output_tokens": 35},
            "cost_usd": 0.02,
        },
    ]

    for event in lines:
        parser.parse_line(_make_line(event))

    log = parser.finalize()

    assert len(log.entries) == 6
    assert log.entries[0].kind == ActionEntryKind.SYSTEM_INIT
    assert log.entries[1].kind == ActionEntryKind.ASSISTANT_TEXT
    assert log.entries[2].kind == ActionEntryKind.TOOL_USE
    assert log.entries[3].kind == ActionEntryKind.TOOL_RESULT
    assert log.entries[4].kind == ActionEntryKind.ASSISTANT_TEXT
    assert log.entries[5].kind == ActionEntryKind.RESULT

    assert log.total_turns == 2  # Two assistant_text entries
    assert log.total_cost_usd == 0.02
    assert log.session_id == "s1"

    # Readable text should concatenate assistant texts and result
    readable = parser.get_readable_text()
    assert "I'll check the files." in readable
    assert "Found 2 files." in readable
    assert "Done!" in readable


def test_skips_unknown_event_types():
    parser = ClaudeStreamParser()
    parser.parse_line(_make_line({"type": "unknown_event", "data": "foo"}))
    log = parser.finalize()
    assert len(log.entries) == 0


def test_skips_non_json_lines():
    parser = ClaudeStreamParser()
    parser.parse_line("not json at all")
    parser.parse_line("")
    parser.parse_line("   ")
    log = parser.finalize()
    assert len(log.entries) == 0


def test_multiple_content_blocks():
    """An assistant message with text + tool_use in same turn."""
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            {
                "type": "assistant",
                "content": [
                    {"type": "text", "text": "Let me read that file."},
                    {
                        "type": "tool_use",
                        "id": "tu_x",
                        "name": "read",
                        "input": {"file_path": "src/main.py"},
                    },
                ],
                "usage": {"input_tokens": 50, "output_tokens": 30},
            }
        )
    )
    log = parser.finalize()

    assert len(log.entries) == 2
    assert log.entries[0].kind == ActionEntryKind.ASSISTANT_TEXT
    assert log.entries[0].metrics is not None  # First block gets metrics
    assert log.entries[1].kind == ActionEntryKind.TOOL_USE
    assert log.entries[1].metrics is None  # Second block doesn't duplicate metrics
    assert log.entries[1].tool_use is not None
    assert log.entries[1].tool_use.summary == "read: src/main.py"
