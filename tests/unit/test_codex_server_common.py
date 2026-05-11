"""Unit tests for codex_server_common: allow-list, prompt assembly, normalization."""

from __future__ import annotations

import io
import json

import pytest

from orchestrator.runners import (
    CODEX_SERVER_TOOL_ALLOWLIST,
    build_codex_server_prompt,
    build_dynamic_tool_specs,
    build_execution_result,
    enforce_tool_allowlist,
    extract_turn_usage,
    fetch_codex_models,
    is_allowed_tool,
    normalize_codex_metrics,
    normalize_codex_output_lines,
)
from orchestrator.runners.types import ExecutionContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(
    prompt: str = "Do the work.",
    requirements: list[str] | None = None,
    api_base_url: str | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp/work",
        prompt=prompt,
        requirements=requirements or ["Req A", "Req B"],
        api_base_url=api_base_url,
    )


# ---------------------------------------------------------------------------
# Allow-list content
# ---------------------------------------------------------------------------


def test_tool_allowlist_contains_expected_tools() -> None:
    """v1 allow-list contains the expected callback tools."""
    assert CODEX_SERVER_TOOL_ALLOWLIST == frozenset(
        {"update_checklist", "grade", "submit", "request_clarification", "complete_recovery"}
    )


# ---------------------------------------------------------------------------
# is_allowed_tool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["update_checklist", "grade", "submit", "request_clarification"])
def test_is_allowed_tool_true_for_allowed(tool: str) -> None:
    assert is_allowed_tool(tool) is True


@pytest.mark.parametrize(
    "tool",
    [
        "bash",
        "read_file",
        "write_file",
        "execute_command",
        "delete_file",
        "arbitrary_tool",
        "",
        "UPDATE_CHECKLIST",  # case-sensitive
        "GRADE",
    ],
)
def test_is_allowed_tool_false_for_disallowed(tool: str) -> None:
    assert is_allowed_tool(tool) is False


# ---------------------------------------------------------------------------
# enforce_tool_allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["update_checklist", "grade", "submit", "request_clarification"])
def test_enforce_tool_allowlist_passes_for_allowed(tool: str) -> None:
    """enforce_tool_allowlist does not raise for allowed tools."""
    enforce_tool_allowlist(tool)  # must not raise


@pytest.mark.parametrize(
    "tool",
    [
        "bash",
        "read_file",
        "write_file",
        "delete_file",
        "shell",
        "",
        "SUBMIT",
    ],
)
def test_enforce_tool_allowlist_raises_for_disallowed(tool: str) -> None:
    """enforce_tool_allowlist raises ValueError for any disallowed tool."""
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        enforce_tool_allowlist(tool)


def test_enforce_tool_allowlist_error_message_includes_tool_name() -> None:
    tool = "some_disallowed_tool"
    with pytest.raises(ValueError, match=tool):
        enforce_tool_allowlist(tool)


def test_enforce_tool_allowlist_error_message_includes_allowed_list() -> None:
    with pytest.raises(ValueError, match="update_checklist"):
        enforce_tool_allowlist("not_allowed")


# ---------------------------------------------------------------------------
# build_codex_server_prompt — builder phase
# ---------------------------------------------------------------------------


def test_builder_prompt_contains_task_prompt() -> None:
    ctx = _ctx(prompt="Implement feature X.")
    result = build_codex_server_prompt(ctx, is_verifier=False)
    assert "Implement feature X." in result


def test_builder_prompt_contains_requirements() -> None:
    ctx = _ctx(requirements=["Req-1: do this", "Req-2: do that"])
    result = build_codex_server_prompt(ctx, is_verifier=False)
    assert "Req-1: do this" in result
    assert "Req-2: do that" in result


def test_builder_prompt_contains_update_checklist_tool() -> None:
    result = build_codex_server_prompt(_ctx(), is_verifier=False)
    assert "update_checklist" in result


def test_builder_prompt_contains_submit_tool() -> None:
    result = build_codex_server_prompt(_ctx(), is_verifier=False)
    assert "submit" in result


def test_builder_prompt_contains_request_clarification_tool() -> None:
    result = build_codex_server_prompt(_ctx(), is_verifier=False)
    assert "request_clarification" in result


def test_builder_prompt_does_not_contain_grade_tool_section() -> None:
    """Builder prompt should not include grading instructions."""
    result = build_codex_server_prompt(_ctx(), is_verifier=False)
    # The verifier-only "grade" tool instructions should not appear in builder
    assert "Grade EVERY requirement" not in result
    assert "grade_reason" not in result


# ---------------------------------------------------------------------------
# build_codex_server_prompt — verifier phase
# ---------------------------------------------------------------------------


def test_verifier_prompt_contains_task_prompt() -> None:
    ctx = _ctx(prompt="Verify the implementation.")
    result = build_codex_server_prompt(ctx, is_verifier=True)
    assert "Verify the implementation." in result


def test_verifier_prompt_contains_requirements() -> None:
    ctx = _ctx(requirements=["R-01: check this", "R-02: check that"])
    result = build_codex_server_prompt(ctx, is_verifier=True)
    assert "R-01: check this" in result
    assert "R-02: check that" in result


def test_verifier_prompt_contains_grade_tool() -> None:
    result = build_codex_server_prompt(_ctx(), is_verifier=True)
    assert "grade" in result


def test_verifier_prompt_contains_submit_tool() -> None:
    result = build_codex_server_prompt(_ctx(), is_verifier=True)
    assert "submit" in result


def test_verifier_prompt_does_not_contain_update_checklist_tool() -> None:
    result = build_codex_server_prompt(_ctx(), is_verifier=True)
    assert "update_checklist" not in result


def test_verifier_prompt_does_not_contain_request_clarification_tool() -> None:
    result = build_codex_server_prompt(_ctx(), is_verifier=True)
    assert "request_clarification" not in result


def test_verifier_prompt_contains_grading_workflow() -> None:
    """Verifier prompt explicitly mentions reviewing and grading."""
    result = build_codex_server_prompt(_ctx(), is_verifier=True)
    assert "Verifier" in result or "VERIFY" in result or "grade" in result.lower()


# ---------------------------------------------------------------------------
# build_codex_server_prompt — api_base_url hint
# ---------------------------------------------------------------------------


def test_prompt_includes_api_base_url_hint() -> None:
    ctx = _ctx(api_base_url="http://localhost:8000")
    result = build_codex_server_prompt(ctx, is_verifier=False)
    assert "http://localhost:8000" in result


def test_prompt_no_url_hint_when_missing() -> None:
    ctx = _ctx(api_base_url=None)
    result = build_codex_server_prompt(ctx, is_verifier=False)
    assert "localhost:8000" not in result


# ---------------------------------------------------------------------------
# normalize_codex_output_lines
# ---------------------------------------------------------------------------


def test_normalize_string_items_pass_through() -> None:
    lines = normalize_codex_output_lines(["hello", "world"])
    assert lines == ["hello", "world"]


def test_normalize_empty_list_returns_empty() -> None:
    assert normalize_codex_output_lines([]) == []


def test_normalize_dict_with_text_key() -> None:
    lines = normalize_codex_output_lines([{"text": "some content"}])
    assert lines == ["some content"]


def test_normalize_dict_with_content_key() -> None:
    lines = normalize_codex_output_lines([{"content": "body text"}])
    assert lines == ["body text"]


def test_normalize_dict_with_message_key() -> None:
    lines = normalize_codex_output_lines([{"message": "a message"}])
    assert lines == ["a message"]


def test_normalize_dict_with_output_key() -> None:
    lines = normalize_codex_output_lines([{"output": "raw output"}])
    assert lines == ["raw output"]


def test_normalize_dict_priority_text_over_content() -> None:
    """'text' key is preferred over 'content'."""
    lines = normalize_codex_output_lines([{"text": "text val", "content": "content val"}])
    assert lines == ["text val"]


def test_normalize_dict_without_known_keys_json_serialized() -> None:
    item = {"unknown_key": "some_value", "another": 42}
    lines = normalize_codex_output_lines([item])
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed == item


def test_normalize_non_string_non_dict_converted_with_str() -> None:
    lines = normalize_codex_output_lines([42, 3.14, True, None])
    assert lines == ["42", "3.14", "True", "None"]


def test_normalize_mixed_types() -> None:
    raw = [
        "plain string",
        {"text": "dict with text"},
        {"content": "dict with content"},
        99,
    ]
    lines = normalize_codex_output_lines(raw)
    assert lines == ["plain string", "dict with text", "dict with content", "99"]


# ---------------------------------------------------------------------------
# normalize_codex_metrics
# ---------------------------------------------------------------------------


def test_normalize_metrics_defaults() -> None:
    metrics = normalize_codex_metrics()
    assert metrics.tokens_read == 0
    assert metrics.tokens_write == 0
    assert metrics.tokens_cache == 0
    assert metrics.duration_ms == 0
    assert metrics.num_actions == 0


def test_normalize_metrics_values_round_trip() -> None:
    metrics = normalize_codex_metrics(
        duration_ms=1234,
        tokens_read=500,
        tokens_write=200,
        tokens_cache=100,
        num_actions=7,
    )
    assert metrics.duration_ms == 1234
    assert metrics.tokens_read == 500
    assert metrics.tokens_write == 200
    assert metrics.tokens_cache == 100
    assert metrics.num_actions == 7


# ---------------------------------------------------------------------------
# fetch_codex_models
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_codex_model_cache() -> None:
    """Clear the lru_cache on fetch_codex_models (if present) before each test
    so monkeypatch changes to shutil.which / _sp.Popen take effect."""
    if hasattr(fetch_codex_models, "cache_clear"):
        fetch_codex_models.cache_clear()  # type: ignore[attr-defined]


def _make_jsonl(*objs: dict) -> str:
    """Build a JSONL string from one or more dicts."""
    return "".join(json.dumps(o) + "\n" for o in objs)


def test_fetch_codex_models_returns_empty_when_codex_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_codex_models() returns [] when codex binary is not in PATH."""
    monkeypatch.setattr("orchestrator.runners.agents.codex.common.shutil.which", lambda name: None)
    result = fetch_codex_models()
    assert result == []


def test_fetch_codex_models_returns_model_ids_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_codex_models() extracts visible model IDs from a model/list response."""

    response_lines = _make_jsonl(
        # Noise before the response for id=2 (e.g. initialize response).
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        # model/list response.
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "models": [
                    {"id": "codex-1", "hidden": False},
                    {"id": "codex-mini", "hidden": False},
                ]
            },
        },
    )

    class _FakeProc:
        stdin = io.StringIO()
        stdout = io.StringIO(response_lines)
        returncode = 0

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            pass

    monkeypatch.setattr(
        "orchestrator.runners.agents.codex.common.shutil.which", lambda name: "/usr/bin/codex"
    )
    monkeypatch.setattr(
        "orchestrator.runners.agents.codex.common._sp.Popen",
        lambda *a, **kw: _FakeProc(),
    )

    result = fetch_codex_models()
    assert result == ["codex-1", "codex-mini"]


def test_fetch_codex_models_all_hidden_models_returns_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When every model is hidden, fetch_codex_models() returns all of them.\n\n    This is the 'all hidden → use all' fallback branch.\n"""
    import io

    response_lines = _make_jsonl(
        # Initialize response.
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        # Model/list response.
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "models": [
                    {"id": "hidden-model-a", "hidden": True},
                    {"id": "hidden-model-b", "hidden": True},
                ]
            },
        },
    )

    class _FakeProc:
        stdin = io.StringIO()
        stdout = io.StringIO(response_lines)
        returncode = 0

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            pass

    monkeypatch.setattr(
        "orchestrator.runners.agents.codex.common.shutil.which", lambda name: "/usr/bin/codex"
    )
    monkeypatch.setattr(
        "orchestrator.runners.agents.codex.common._sp.Popen",
        lambda *a, **kw: _FakeProc(),
    )

    result = fetch_codex_models()
    assert result == ["hidden-model-a", "hidden-model-b"]


def test_fetch_codex_models_filters_hidden_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_codex_models() excludes hidden models when non-hidden ones exist."""
    import io

    response_lines = _make_jsonl(
        # Initialize response.
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        # Model/list response.
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "models": [
                    {"id": "visible-model", "hidden": False},
                    {"id": "hidden-model", "hidden": True},
                ]
            },
        },
    )

    class _FakeProc:
        stdin = io.StringIO()
        stdout = io.StringIO(response_lines)
        returncode = 0

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            pass

    monkeypatch.setattr(
        "orchestrator.runners.agents.codex.common.shutil.which", lambda name: "/usr/bin/codex"
    )
    monkeypatch.setattr(
        "orchestrator.runners.agents.codex.common._sp.Popen",
        lambda *a, **kw: _FakeProc(),
    )

    result = fetch_codex_models()
    assert result == ["visible-model"]
    assert "hidden-model" not in result


def test_fetch_codex_models_empty_models_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_codex_models() returns [] when models list is empty."""
    import io

    response_lines = _make_jsonl(
        # Initialize response.
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        # Model/list response.
        {"jsonrpc": "2.0", "id": 2, "result": {"models": []}},
    )

    class _FakeProc:
        stdin = io.StringIO()
        stdout = io.StringIO(response_lines)
        returncode = 0

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            pass

    monkeypatch.setattr(
        "orchestrator.runners.agents.codex.common.shutil.which", lambda name: "/usr/bin/codex"
    )
    monkeypatch.setattr(
        "orchestrator.runners.agents.codex.common._sp.Popen",
        lambda *a, **kw: _FakeProc(),
    )

    result = fetch_codex_models()
    assert result == []


def test_fetch_codex_models_returns_empty_on_subprocess_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_codex_models() returns [] (not raises) when Popen fails."""
    monkeypatch.setattr(
        "orchestrator.runners.agents.codex.common.shutil.which", lambda name: "/usr/bin/codex"
    )
    monkeypatch.setattr(
        "orchestrator.runners.agents.codex.common._sp.Popen",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("spawn failed")),
    )

    result = fetch_codex_models()
    assert result == []


# ---------------------------------------------------------------------------
# build_dynamic_tool_specs — phase filtering
# ---------------------------------------------------------------------------


def test_builder_no_grade_tool() -> None:
    """Builder phase (is_verifier=False) excludes the grade tool."""
    specs = build_dynamic_tool_specs(is_verifier=False)
    names = {s["name"] for s in specs}
    assert "grade" not in names


def test_verifier_has_grade_tool() -> None:
    """Verifier phase (is_verifier=True) includes the grade tool."""
    specs = build_dynamic_tool_specs(is_verifier=True)
    names = {s["name"] for s in specs}
    assert "grade" in names


def test_builder_tools_are_present() -> None:
    """Builder phase exposes progress and clarification tools."""
    specs = build_dynamic_tool_specs(is_verifier=False)
    names = {s["name"] for s in specs}
    assert "update_checklist" in names
    assert "submit" in names
    assert "request_clarification" in names
    assert "complete_recovery" not in names


def test_verifier_tools_are_present() -> None:
    """Verifier phase exposes grading and recovery tools."""
    specs = build_dynamic_tool_specs(is_verifier=True)
    names = {s["name"] for s in specs}
    assert "grade" in names
    assert "submit" in names
    assert "complete_recovery" in names
    assert "update_checklist" not in names
    assert "request_clarification" not in names


# ---------------------------------------------------------------------------
# build_dynamic_tool_specs — step-level tools and unknown tool warnings
# ---------------------------------------------------------------------------


def test_unknown_tool_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Unknown tools in context.available_tools trigger a warning."""
    ctx = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="test",
        requirements=["R1"],
        available_tools=["nonexistent_tool"],
    )
    with caplog.at_level("WARNING"):
        build_dynamic_tool_specs(is_verifier=False, context=ctx)
    assert "nonexistent_tool" in caplog.text
    assert "Unknown tool" in caplog.text


def test_no_context_backward_compat() -> None:
    """Without context, build_dynamic_tool_specs returns standard tools."""
    specs = build_dynamic_tool_specs(is_verifier=False, context=None)
    assert len(specs) > 0
    names = {s["name"] for s in specs}
    assert "update_checklist" in names


def test_available_tools_none_backward_compat() -> None:
    """When context.available_tools is None, no warnings are raised."""
    ctx = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="test",
        requirements=["R1"],
        available_tools=None,
    )
    specs = build_dynamic_tool_specs(is_verifier=False, context=ctx)
    assert len(specs) > 0


def test_empty_available_tools_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Empty available_tools list doesn't trigger warnings."""
    ctx = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="test",
        requirements=["R1"],
        available_tools=[],
    )
    with caplog.at_level("WARNING"):
        build_dynamic_tool_specs(is_verifier=False, context=ctx)
    assert "Unknown tool" not in caplog.text


def test_known_tool_no_duplicate(caplog: pytest.LogCaptureFixture) -> None:
    """Existing tools in available_tools don't trigger warnings."""
    ctx = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="test",
        requirements=["R1"],
        available_tools=["update_checklist"],  # Already a built-in tool
    )
    with caplog.at_level("WARNING"):
        specs = build_dynamic_tool_specs(is_verifier=False, context=ctx)
    # Should not warn about update_checklist since it's already in specs
    assert "Unknown tool" not in caplog.text or "update_checklist" not in caplog.text
    # And it should still be in the specs (no duplication)
    names = {s["name"] for s in specs}
    assert "update_checklist" in names


# ---------------------------------------------------------------------------
# extract_turn_usage
# ---------------------------------------------------------------------------


def test_extract_turn_usage_with_input_output_tokens() -> None:
    """extract_turn_usage extracts input_tokens and output_tokens."""
    msg = {
        "method": "turn/completed",
        "params": {
            "turn": {
                "status": "completed",
                "usage": {
                    "input_tokens": 1500,
                    "output_tokens": 300,
                    "cache_read_tokens": 50,
                },
            }
        },
    }
    result = extract_turn_usage(msg)
    assert result == {"tokens_read": 1500, "tokens_write": 300, "tokens_cache": 50}


def test_extract_turn_usage_with_prompt_completion_tokens() -> None:
    """extract_turn_usage handles prompt_tokens/completion_tokens field names."""
    msg = {
        "method": "turn/completed",
        "params": {
            "turn": {
                "status": "completed",
                "usage": {
                    "prompt_tokens": 2000,
                    "completion_tokens": 400,
                    "cached_tokens": 100,
                },
            }
        },
    }
    result = extract_turn_usage(msg)
    assert result == {"tokens_read": 2000, "tokens_write": 400, "tokens_cache": 100}


def test_extract_turn_usage_without_usage_field() -> None:
    """extract_turn_usage returns zeros when no usage field is present."""
    msg = {
        "method": "turn/completed",
        "params": {"turn": {"status": "completed"}},
    }
    result = extract_turn_usage(msg)
    assert result == {"tokens_read": 0, "tokens_write": 0, "tokens_cache": 0}


def test_extract_turn_usage_non_terminal_notification() -> None:
    """extract_turn_usage returns zeros for non-turn/completed notifications."""
    msg = {
        "method": "item/agentMessage/delta",
        "params": {"delta": "hello"},
    }
    result = extract_turn_usage(msg)
    assert result == {"tokens_read": 0, "tokens_write": 0, "tokens_cache": 0}


def test_extract_turn_usage_empty_usage_dict() -> None:
    """extract_turn_usage returns zeros when usage is an empty dict."""
    msg = {
        "method": "turn/completed",
        "params": {"turn": {"status": "completed", "usage": {}}},
    }
    result = extract_turn_usage(msg)
    assert result == {"tokens_read": 0, "tokens_write": 0, "tokens_cache": 0}


def test_extract_turn_usage_cache_read_input_tokens() -> None:
    """extract_turn_usage handles cache_read_input_tokens field name."""
    msg = {
        "method": "turn/completed",
        "params": {
            "turn": {
                "status": "completed",
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 100,
                    "cache_read_input_tokens": 200,
                },
            }
        },
    }
    result = extract_turn_usage(msg)
    assert result["tokens_cache"] == 200


# ---------------------------------------------------------------------------
# build_execution_result — with token/action params
# ---------------------------------------------------------------------------


def test_build_execution_result_with_tokens() -> None:
    """build_execution_result passes token counts through to metrics."""
    result = build_execution_result(
        ["hello\n", "world\n"],
        duration_ms=5000,
        tokens_read=1000,
        tokens_write=200,
        tokens_cache=50,
        num_actions=3,
        agent_model="gpt-5.4",
    )
    assert result.success is True
    assert result.metrics.tokens_read == 1000
    assert result.metrics.tokens_write == 200
    assert result.metrics.tokens_cache == 50
    assert result.metrics.num_actions == 3
    assert result.metrics.duration_ms == 5000
    assert result.action_log is not None
    assert result.action_log.agent_model == "gpt-5.4"
    assert result.action_log.total_input_tokens == 1000
    assert result.action_log.total_output_tokens == 200
    assert result.action_log.total_cache_read_tokens == 50
    assert result.action_log.total_duration_ms == 5000


def test_build_execution_result_defaults_to_zero_tokens() -> None:
    """build_execution_result defaults token counts to 0 for backward compat."""
    result = build_execution_result(["test\n"], duration_ms=100)
    assert result.metrics.tokens_read == 0
    assert result.metrics.tokens_write == 0
    assert result.metrics.tokens_cache == 0
    assert result.metrics.num_actions == 0
    assert result.action_log is not None
    assert result.action_log.total_input_tokens == 0
    assert result.action_log.total_output_tokens == 0
