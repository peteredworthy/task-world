"""Tests for rate-limit detection and handling in the orchestrator."""

from __future__ import annotations

import json
from datetime import datetime

from orchestrator.runners import (
    RATE_LIMIT_PATTERN,
    RATE_LIMIT_RESET_PATTERN,
    ClaudeStreamParser,
    parse_reset_time,
)
from orchestrator.runners.errors import AgentRateLimitError
from orchestrator.state.models import ActionLog


def _make_line(event: dict) -> str:
    return json.dumps(event)


def _assistant_event(content: list, usage: dict | None = None) -> dict:
    msg: dict = {"role": "assistant", "content": content}
    if usage:
        msg["usage"] = usage
    return {"type": "assistant", "message": msg}


# ---------------------------------------------------------------------------
# RATE_LIMIT_PATTERN regex
# ---------------------------------------------------------------------------


def test_rate_limit_pattern_matches_exact_message():
    text = "You've hit your limit · resets 6pm (America/New_York)"
    assert RATE_LIMIT_PATTERN.search(text) is not None


def test_rate_limit_pattern_matches_weekly_variant():
    text = "You've hit your weekly limit · resets Jan 7, 9am (America/New_York)"
    assert RATE_LIMIT_PATTERN.search(text) is not None


def test_rate_limit_pattern_matches_5_hour_variant():
    text = "You've hit your 5-hour limit · resets 3pm (UTC)"
    assert RATE_LIMIT_PATTERN.search(text) is not None


def test_rate_limit_pattern_does_not_match_normal_text():
    assert RATE_LIMIT_PATTERN.search("Everything looks good, moving on.") is None
    assert RATE_LIMIT_PATTERN.search("You've reached the end of the file.") is None
    assert RATE_LIMIT_PATTERN.search("") is None


# ---------------------------------------------------------------------------
# RATE_LIMIT_RESET_PATTERN regex
# ---------------------------------------------------------------------------


def test_rate_limit_reset_pattern_extracts_simple_time():
    text = "You've hit your limit · resets 6pm (America/New_York)"
    m = RATE_LIMIT_RESET_PATTERN.search(text)
    assert m is not None
    assert m.group(1) == "6pm"
    assert m.group(2) == "America/New_York"


def test_rate_limit_reset_pattern_extracts_date_and_time():
    text = "You've hit your weekly limit · resets Jan 7, 9am (America/New_York)"
    m = RATE_LIMIT_RESET_PATTERN.search(text)
    assert m is not None
    assert "9am" in m.group(1)
    assert m.group(2) == "America/New_York"


def test_rate_limit_reset_pattern_no_match_on_plain_text():
    assert RATE_LIMIT_RESET_PATTERN.search("Normal assistant message.") is None


# ---------------------------------------------------------------------------
# parse_reset_time
# ---------------------------------------------------------------------------


def testparse_reset_time_simple_hour():
    result = parse_reset_time("6pm", "America/New_York")
    assert result is not None
    assert isinstance(result, datetime)
    assert result.tzinfo is not None
    # Hour should be 18 (6pm)
    assert result.hour == 18


def testparse_reset_time_am():
    result = parse_reset_time("9am", "America/Los_Angeles")
    assert result is not None
    assert result.hour == 9
    assert result.tzinfo is not None


def testparse_reset_time_with_date_string():
    # dateutil should parse "Jan 7, 9am" with timezone
    result = parse_reset_time("Jan 7, 9am", "America/New_York")
    # May return None if dateutil is not installed; if it does return something
    # it must be a timezone-aware datetime
    if result is not None:
        assert isinstance(result, datetime)
        assert result.tzinfo is not None


def testparse_reset_time_invalid_timezone_returns_none():
    result = parse_reset_time("6pm", "Not/AReal_Timezone")
    assert result is None


def testparse_reset_time_utc_timezone():
    result = parse_reset_time("3pm", "UTC")
    assert result is not None
    assert result.hour == 15


# ---------------------------------------------------------------------------
# ClaudeStreamParser — rate-limit detection
# ---------------------------------------------------------------------------


def test_parser_detects_exact_rate_limit_message():
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            _assistant_event(
                [
                    {
                        "type": "text",
                        "text": "You've hit your limit · resets 6pm (America/New_York)",
                    }
                ]
            )
        )
    )
    log = parser.finalize()
    assert log.rate_limit_hit is True


def test_parser_detects_weekly_rate_limit_variant():
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            _assistant_event(
                [
                    {
                        "type": "text",
                        "text": "You've hit your weekly limit · resets Jan 7, 9am (America/New_York)",
                    }
                ]
            )
        )
    )
    log = parser.finalize()
    assert log.rate_limit_hit is True


def test_parser_does_not_flag_normal_assistant_text():
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            _assistant_event([{"type": "text", "text": "I've completed the task successfully."}])
        )
    )
    log = parser.finalize()
    assert log.rate_limit_hit is False


def test_finalize_sets_rate_limit_resets_at_when_hit():
    parser = ClaudeStreamParser()
    parser.parse_line(
        _make_line(
            _assistant_event(
                [
                    {
                        "type": "text",
                        "text": "You've hit your limit · resets 6pm (America/New_York)",
                    }
                ]
            )
        )
    )
    log = parser.finalize()
    assert log.rate_limit_hit is True
    assert log.rate_limit_resets_at is not None
    assert isinstance(log.rate_limit_resets_at, datetime)


def test_finalize_rate_limit_resets_at_is_none_for_normal_output():
    parser = ClaudeStreamParser()
    parser.parse_line(_make_line(_assistant_event([{"type": "text", "text": "All done."}])))
    log = parser.finalize()
    assert log.rate_limit_hit is False
    assert log.rate_limit_resets_at is None


def test_finalize_rate_limit_hit_false_by_default():
    parser = ClaudeStreamParser()
    log = parser.finalize()
    assert log.rate_limit_hit is False
    assert log.rate_limit_resets_at is None


def test_parser_only_flags_rate_limit_once_on_repeated_messages():
    """Parser should set rate_limit_hit on first match and not error on repeats."""
    parser = ClaudeStreamParser()
    for _ in range(3):
        parser.parse_line(
            _make_line(
                _assistant_event(
                    [
                        {
                            "type": "text",
                            "text": "You've hit your limit · resets 6pm (America/New_York)",
                        }
                    ]
                )
            )
        )
    log = parser.finalize()
    assert log.rate_limit_hit is True


# ---------------------------------------------------------------------------
# AgentRateLimitError
# ---------------------------------------------------------------------------


def test_agent_rate_limit_error_full_construction():
    resets_at = datetime(2026, 1, 7, 18, 0, 0)
    err = AgentRateLimitError(
        agent_runner_type="claude_cli",
        session_id="sess_abc123",
        resets_at=resets_at,
    )
    assert err.agent_runner_type == "claude_cli"
    assert err.session_id == "sess_abc123"
    assert err.resets_at == resets_at
    assert "rate limit" in str(err).lower()
    assert "claude_cli" in str(err)


def test_agent_rate_limit_error_str_includes_reset_time():
    resets_at = datetime(2026, 1, 7, 18, 0, 0)
    err = AgentRateLimitError(agent_runner_type="claude_cli", resets_at=resets_at)
    assert "resets at" in str(err).lower()


def test_agent_rate_limit_error_minimal_construction():
    err = AgentRateLimitError(agent_runner_type="claude_cli")
    assert err.agent_runner_type == "claude_cli"
    assert err.session_id is None
    assert err.resets_at is None
    assert "rate limit" in str(err).lower()


def test_agent_rate_limit_error_is_agent_error():
    from orchestrator.runners.errors import AgentError

    err = AgentRateLimitError(agent_runner_type="claude_cli")
    assert isinstance(err, AgentError)
    assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# ActionLog model fields
# ---------------------------------------------------------------------------


def test_action_log_accepts_rate_limit_fields():
    log = ActionLog(
        entries=[],
        rate_limit_hit=True,
        rate_limit_resets_at=datetime(2026, 1, 7, 18, 0, 0),
    )
    assert log.rate_limit_hit is True
    assert log.rate_limit_resets_at == datetime(2026, 1, 7, 18, 0, 0)


def test_action_log_rate_limit_fields_default_to_false_and_none():
    log = ActionLog(entries=[])
    assert log.rate_limit_hit is False
    assert log.rate_limit_resets_at is None


def test_action_log_rate_limit_hit_can_be_false_explicitly():
    log = ActionLog(entries=[], rate_limit_hit=False, rate_limit_resets_at=None)
    assert log.rate_limit_hit is False
    assert log.rate_limit_resets_at is None
