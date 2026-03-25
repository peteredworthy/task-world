"""Unit tests for task log reparsing fallback in API router."""

from orchestrator.api import (
    _looks_like_ndjson_agent_stream,
    _parse_action_log_from_raw,
)


def test_looks_like_ndjson_agent_stream() -> None:
    assert _looks_like_ndjson_agent_stream('{"type":"thread.started"}')
    assert _looks_like_ndjson_agent_stream('{"type":"item.completed","item":{"type":"reasoning"}}')
    assert not _looks_like_ndjson_agent_stream("plain text output")


def test_parse_action_log_from_raw_codex_item_completed() -> None:
    raw = "\n".join(
        [
            '{"type":"thread.started","thread_id":"t1"}',
            '{"type":"item.completed","item":{"id":"item_0","type":"reasoning","text":"Plan"}}',
            '{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"Hello"}}',
            '{"type":"item.completed","item":{"id":"item_2","type":"command_execution","command":"echo hi","aggregated_output":"hi\\\\n","exit_code":0,"status":"completed"}}',
            '{"type":"turn.completed","usage":{"input_tokens":3,"output_tokens":2}}',
        ]
    )
    parsed = _parse_action_log_from_raw(raw, {"command": "codex"})
    assert parsed is not None
    assert [e.kind.value for e in parsed.entries] == [
        "system_init",
        "thinking",
        "assistant_text",
        "tool_use",
        "tool_result",
        "result",
    ]
