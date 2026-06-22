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
    extract_codex_model_ids,
    extract_item_activity_line,
    extract_token_usage_update,
    extract_turn_error,
    extract_turn_usage,
    fetch_codex_models,
    is_allowed_tool,
    normalize_codex_metrics,
    normalize_codex_output_lines,
    route_tool_call,
    select_preferred_codex_model,
)
from orchestrator.config.enums import ChecklistStatus
from orchestrator.runners.types import ExecutionContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(
    prompt: str = "Do the work.",
    requirements: list[str] | None = None,
    api_base_url: str | None = None,
    node_kind: str | None = None,
    node_role: str | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp/work",
        prompt=prompt,
        requirements=requirements or ["Req A", "Req B"],
        api_base_url=api_base_url,
        node_kind=node_kind,
        node_role=node_role,
    )


# ---------------------------------------------------------------------------
# Allow-list content
# ---------------------------------------------------------------------------


def test_tool_allowlist_contains_expected_tools() -> None:
    """v1 allow-list contains the expected callback tools."""
    assert CODEX_SERVER_TOOL_ALLOWLIST == frozenset(
        {
            "update_checklist",
            "grade",
            "submit",
            "submit_graph_patch",
            "request_clarification",
            "complete_recovery",
            "create_work_region",
            "create_corrective_region",
            "attach_verifier",
            "attach_check",
            "create_gap_planner",
            "create_join",
            "request_gate",
            "retire_or_supersede",
        }
    )


# ---------------------------------------------------------------------------
# is_allowed_tool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool",
    [
        "update_checklist",
        "grade",
        "submit",
        "submit_graph_patch",
        "request_clarification",
        "create_work_region",
        "attach_check",
    ],
)
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
        "record_heartbeat",
        "agent_died",
        "submit_artifact",
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
        "record_heartbeat",
        "agent_died",
        "submit_artifact",
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


def test_builder_planner_prompt_contains_submit_graph_patch_instructions() -> None:
    result = build_codex_server_prompt(
        _ctx(node_kind="planner", node_role="planner"), is_verifier=False
    )
    assert "Planner Graph-Mutation Tool" in result
    assert "Prefer graph macros" in result
    assert "create_work_region" in result
    assert "submit_graph_patch" in result
    assert "base_graph_position: Use current_graph_position from the planner packet." in result
    assert "ops: Validated raw fallback list using only allowed_patch_operations" in result
    assert "gap planners may use [] for an explicit no-op decision" in result
    assert "submit a corrected macro or patch" in result
    assert (
        "Plain submit is only for finishing after at least one submit_graph_patch attempt."
        in result
    )


def test_builder_gap_planner_prompt_contains_submit_graph_patch_instructions() -> None:
    result = build_codex_server_prompt(
        _ctx(node_kind="planner", node_role="gap_planner"),
        is_verifier=False,
    )
    assert "Planner Graph-Mutation Tool" in result
    assert "submit_graph_patch" in result


def test_builder_worker_and_verifier_prompts_do_not_include_submit_graph_patch() -> None:
    worker_prompt = build_codex_server_prompt(
        _ctx(node_kind="worker", node_role="builder"), is_verifier=False
    )
    assert "Planner Graph-Mutation Tool" not in worker_prompt
    assert "submit_graph_patch" not in worker_prompt

    verifier_prompt = build_codex_server_prompt(
        _ctx(node_kind="verifier", node_role="verifier"), is_verifier=True
    )
    assert "Planner Graph-Mutation Tool" not in verifier_prompt
    assert "submit_graph_patch" not in verifier_prompt


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
# Codex model discovery
# ---------------------------------------------------------------------------


def _make_jsonl(*objs: dict) -> str:
    """Build a JSONL string from one or more dicts."""
    return "".join(json.dumps(o) + "\n" for o in objs)


class _FakeCodexProc:
    def __init__(self, response_lines: str) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(response_lines)
        self.returncode = 0

    def terminate(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        pass


def test_fetch_codex_models_returns_empty_when_codex_not_installed() -> None:
    """fetch_codex_models() returns [] when codex binary is not in PATH."""
    result = fetch_codex_models(codex_path=None)
    assert result == []


def test_fetch_codex_models_uses_injected_process() -> None:
    """fetch_codex_models() performs the JSON-RPC handshake with an injected process."""
    response_lines = _make_jsonl(
        {"jsonrpc": "2.0", "id": 1, "result": {}},
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

    result = fetch_codex_models(
        codex_path="/usr/bin/codex",
        process_factory=lambda *args, **kwargs: _FakeCodexProc(response_lines),
    )
    assert result == ["codex-1", "codex-mini"]


def test_extract_codex_model_ids_all_hidden_models_returns_all() -> None:
    """When every model is hidden, extraction returns all of them."""
    result = extract_codex_model_ids(
        {
            "result": {
                "models": [
                    {"id": "hidden-model-a", "hidden": True},
                    {"id": "hidden-model-b", "hidden": True},
                ]
            }
        }
    )
    assert result == ["hidden-model-a", "hidden-model-b"]


def test_extract_codex_model_ids_filters_hidden_models() -> None:
    """Model extraction excludes hidden models when non-hidden ones exist."""
    result = extract_codex_model_ids(
        {
            "result": {
                "models": [
                    {"id": "visible-model", "hidden": False},
                    {"id": "hidden-model", "hidden": True},
                ]
            }
        }
    )
    assert result == ["visible-model"]
    assert "hidden-model" not in result


def test_extract_codex_model_ids_accepts_data_shape() -> None:
    """Model extraction handles the current {'data': [...]} result shape."""
    result = extract_codex_model_ids(
        {"result": {"data": [{"id": "codex-a", "hidden": False}, {"id": "codex-b"}]}}
    )
    assert result == ["codex-a", "codex-b"]


def test_extract_codex_model_ids_empty_models_list() -> None:
    """Model extraction returns [] when models list is empty."""
    result = extract_codex_model_ids({"result": {"models": []}})
    assert result == []


def test_extract_codex_model_ids_missing_result() -> None:
    """Model extraction returns [] when the JSON-RPC result is missing."""
    assert extract_codex_model_ids(None) == []
    assert extract_codex_model_ids({"jsonrpc": "2.0", "id": 2}) == []


def test_fetch_codex_models_returns_empty_on_subprocess_error() -> None:
    """fetch_codex_models() returns [] when the process factory fails."""

    def raise_spawn_error(*args: object, **kwargs: object) -> _FakeCodexProc:
        raise OSError("spawn failed")

    result = fetch_codex_models(
        codex_path="/usr/bin/codex",
        process_factory=raise_spawn_error,
    )
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


def test_submit_graph_patch_exposed_only_to_graph_planner() -> None:
    ordinary = {s["name"] for s in build_dynamic_tool_specs(is_verifier=False, context=_ctx())}
    planner_specs = build_dynamic_tool_specs(
        is_verifier=False,
        context=_ctx(node_kind="planner", node_role="planner"),
    )
    gap_planner_specs = build_dynamic_tool_specs(
        is_verifier=False,
        context=_ctx(node_kind="planner", node_role="gap_planner"),
    )
    planner = {s["name"] for s in planner_specs}
    gap_planner = {s["name"] for s in gap_planner_specs}
    verifier = {
        s["name"]
        for s in build_dynamic_tool_specs(
            is_verifier=True,
            context=_ctx(node_kind="planner", node_role="planner"),
        )
    }

    assert "submit_graph_patch" not in ordinary
    assert "submit_graph_patch" in planner
    assert "submit_graph_patch" in gap_planner
    assert "submit_graph_patch" not in verifier
    spec = next(s for s in planner_specs if s["name"] == "submit_graph_patch")
    schema = spec["inputSchema"]
    assert schema["additionalProperties"] is False
    assert schema["oneOf"] == [
        {"required": ["patch"]},
        {"required": ["patch_id", "base_graph_position", "ops"]},
    ]
    assert schema["properties"]["patch"]["properties"]["ops"]["minItems"] == 0
    assert (
        "Validated low-level patch expansion"
        in schema["properties"]["patch"]["properties"]["ops"]["description"]
    )
    assert schema["properties"]["ops"]["minItems"] == 0
    assert "Validated low-level patch expansion" in schema["properties"]["ops"]["description"]


def test_planner_macros_are_exposed_with_typed_schemas() -> None:
    specs = build_dynamic_tool_specs(
        is_verifier=False,
        context=_ctx(node_kind="planner", node_role="planner"),
    )
    names = {s["name"] for s in specs}
    assert {
        "create_work_region",
        "attach_verifier",
        "attach_check",
        "create_gap_planner",
        "create_join",
        "request_gate",
        "retire_or_supersede",
    }.issubset(names)

    create_join = next(s for s in specs if s["name"] == "create_join")
    join_schema = create_join["inputSchema"]
    assert join_schema["additionalProperties"] is False
    assert join_schema["required"] == ["patch_id", "base_graph_position", "join_id"]
    assert join_schema["properties"]["source_ids"]["type"] == "array"
    assert join_schema["properties"]["source_ids"]["items"]["type"] == "string"

    request_gate = next(s for s in specs if s["name"] == "request_gate")
    gate_schema = request_gate["inputSchema"]
    assert gate_schema["additionalProperties"] is False
    assert gate_schema["properties"]["kind"]["enum"] == ["human_gate", "authority_request"]
    assert gate_schema["properties"]["requested_authority"]["minItems"] == 1
    assert gate_schema["properties"]["target_node_id"]["type"] == "string"


def test_gap_planner_macros_are_exposed_with_typed_schemas() -> None:
    specs = build_dynamic_tool_specs(
        is_verifier=False,
        context=_ctx(node_kind="planner", node_role="gap_planner"),
    )
    names = {s["name"] for s in specs}
    assert {
        "create_corrective_region",
        "attach_verifier",
        "attach_check",
        "request_gate",
        "submit_graph_patch",
    }.issubset(names)
    assert "create_work_region" not in names
    assert "create_gap_planner" not in names
    assert "create_join" not in names
    assert "retire_or_supersede" not in names


@pytest.mark.asyncio
async def test_submit_graph_patch_routes_empty_ops_no_op_patch() -> None:
    received: list[dict[str, object]] = []

    async def on_checklist_update(
        _req_id: str,
        _status: ChecklistStatus,
        _note: str | None,
    ) -> None:
        return None

    async def on_submit() -> None:
        return None

    async def on_submit_graph_patch(payload: dict[str, object]) -> str:
        received.append(payload)
        return "accepted no-op"

    result = await route_tool_call(
        "submit_graph_patch",
        {"patch_id": "gap-no-op", "base_graph_position": 42, "ops": []},
        on_checklist_update,
        on_submit,
        on_submit_graph_patch=on_submit_graph_patch,
    )

    assert result == "accepted no-op"
    assert received == [{"patch_id": "gap-no-op", "base_graph_position": 42, "ops": []}]


@pytest.mark.asyncio
async def test_macro_tool_routes_as_graph_patch_invocation() -> None:
    received: list[dict[str, object]] = []

    async def on_checklist_update(
        _req_id: str,
        _status: ChecklistStatus,
        _note: str | None,
    ) -> None:
        return None

    async def on_submit() -> None:
        return None

    async def on_submit_graph_patch(payload: dict[str, object]) -> str:
        received.append(payload)
        return "macro accepted"

    result = await route_tool_call(
        "create_work_region",
        {
            "patch_id": "macro-work",
            "base_graph_position": 42,
            "region_id": "feature-region",
            "worker_id": "worker-feature",
        },
        on_checklist_update,
        on_submit,
        on_submit_graph_patch=on_submit_graph_patch,
    )

    assert result == "macro accepted"
    assert received == [
        {
            "patch_id": "macro-work",
            "base_graph_position": 42,
            "macro_invocations": [
                {
                    "macro": "create_work_region",
                    "args": {"region_id": "feature-region", "worker_id": "worker-feature"},
                }
            ],
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["record_heartbeat", "agent_died", "submit_artifact"])
async def test_lifecycle_and_artifact_callbacks_are_not_agent_routable_tools(
    tool_name: str,
) -> None:
    callback_calls: list[str] = []

    async def on_checklist_update(
        _req_id: str,
        _status: ChecklistStatus,
        _note: str | None,
    ) -> None:
        callback_calls.append("checklist")

    async def on_submit() -> None:
        callback_calls.append("submit")

    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await route_tool_call(
            tool_name,
            {},
            on_checklist_update,
            on_submit,
        )

    assert callback_calls == []


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
    assert result == {
        "tokens_read": 1500,
        "tokens_write": 300,
        "tokens_cache": 50,
        "tokens_reasoning": 0,
    }


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
    assert result == {
        "tokens_read": 2000,
        "tokens_write": 400,
        "tokens_cache": 100,
        "tokens_reasoning": 0,
    }


def test_extract_turn_usage_without_usage_field() -> None:
    """extract_turn_usage returns zeros when no usage field is present."""
    msg = {
        "method": "turn/completed",
        "params": {"turn": {"status": "completed"}},
    }
    result = extract_turn_usage(msg)
    assert result == {"tokens_read": 0, "tokens_write": 0, "tokens_cache": 0, "tokens_reasoning": 0}


def test_extract_turn_usage_non_terminal_notification() -> None:
    """extract_turn_usage returns zeros for non-turn/completed notifications."""
    msg = {
        "method": "item/agentMessage/delta",
        "params": {"delta": "hello"},
    }
    result = extract_turn_usage(msg)
    assert result == {"tokens_read": 0, "tokens_write": 0, "tokens_cache": 0, "tokens_reasoning": 0}


def test_extract_turn_usage_empty_usage_dict() -> None:
    """extract_turn_usage returns zeros when usage is an empty dict."""
    msg = {
        "method": "turn/completed",
        "params": {"turn": {"status": "completed", "usage": {}}},
    }
    result = extract_turn_usage(msg)
    assert result == {"tokens_read": 0, "tokens_write": 0, "tokens_cache": 0, "tokens_reasoning": 0}


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


# ---------------------------------------------------------------------------
# select_preferred_codex_model
# ---------------------------------------------------------------------------


def test_select_preferred_returns_none_for_empty_list() -> None:
    """select_preferred_codex_model returns None when no models are available."""
    assert select_preferred_codex_model([]) is None


def test_select_preferred_picks_gpt53_codex_over_gpt52_codex() -> None:
    """gpt-5.3-codex is preferred over gpt-5.2-codex (the deprecated model)."""
    result = select_preferred_codex_model(["gpt-5.2-codex", "gpt-5.3-codex"])
    assert result == "gpt-5.3-codex"


def test_select_preferred_picks_gpt53_when_first() -> None:
    """gpt-5.3-codex is returned when it appears first in the list."""
    result = select_preferred_codex_model(["gpt-5.3-codex", "gpt-5.2-codex"])
    assert result == "gpt-5.3-codex"


def test_select_preferred_picks_gpt53_from_mixed_list() -> None:
    """gpt-5.3-codex is selected from a realistic mixed list regardless of order."""
    models = ["gpt-5.2-codex", "gpt-5.2", "gpt-5.3-codex", "gpt-5.1-codex-mini"]
    assert select_preferred_codex_model(models) == "gpt-5.3-codex"


def test_select_preferred_falls_back_to_first_when_no_preferred_present() -> None:
    """Falls back to the first available model when no preferred models are in the list."""
    models = ["my-custom-model", "another-model"]
    assert select_preferred_codex_model(models) == "my-custom-model"


def test_select_preferred_single_model_list() -> None:
    """Single-element list with a known-good model returns that model; known-unsupported returns None."""
    # gpt-5.2-codex is known-unsupported, so no safe default can be offered
    assert select_preferred_codex_model(["gpt-5.2-codex"]) is None
    assert select_preferred_codex_model(["gpt-5.3-codex"]) == "gpt-5.3-codex"


def test_select_preferred_codex_mini_over_deprecated() -> None:
    """gpt-5.1-codex-mini is preferred over gpt-5.2-codex when 5.3 is absent."""
    result = select_preferred_codex_model(["gpt-5.2-codex", "gpt-5.1-codex-mini"])
    assert result == "gpt-5.1-codex-mini"


# --- extract_item_activity_line / extract_turn_error ---


def _item_completed(item: dict[str, object]) -> dict[str, object]:
    return {"method": "item/completed", "params": {"item": item}}


def test_item_activity_command_execution_with_exit_code() -> None:
    note = _item_completed(
        {"type": "commandExecution", "command": "uv run pytest -q", "exit_code": 0}
    )
    assert extract_item_activity_line(note) == "$ uv run pytest -q (exit 0)"


def test_item_activity_command_execution_snake_case_type() -> None:
    note = _item_completed({"type": "command_execution", "command": "ls", "exitCode": 1})
    assert extract_item_activity_line(note) == "$ ls (exit 1)"


def test_item_activity_file_change_lists_paths() -> None:
    note = _item_completed(
        {"type": "fileChange", "changes": [{"path": "src/a.py"}, {"path": "src/b.py"}]}
    )
    assert extract_item_activity_line(note) == "file change: src/a.py, src/b.py"


def test_item_activity_tool_call() -> None:
    note = _item_completed({"type": "mcpToolCall", "tool": "submit_work", "status": "completed"})
    assert extract_item_activity_line(note) == "tool: submit_work (completed)"


def test_item_activity_skips_agent_message_and_reasoning() -> None:
    assert (
        extract_item_activity_line(_item_completed({"type": "agentMessage", "text": "hi"})) is None
    )
    assert extract_item_activity_line(_item_completed({"type": "reasoning", "text": "hmm"})) is None


def test_item_activity_ignores_other_methods() -> None:
    assert (
        extract_item_activity_line(
            {"method": "item/started", "params": {"item": {"type": "commandExecution"}}}
        )
        is None
    )


def test_extract_turn_error_from_dict_and_string() -> None:
    base = {"method": "turn/completed"}
    assert (
        extract_turn_error({**base, "params": {"turn": {"error": {"message": "quota exceeded"}}}})
        == "quota exceeded"
    )
    assert (
        extract_turn_error({**base, "params": {"turn": {"error": "rate limited"}}})
        == "rate limited"
    )
    assert extract_turn_error({**base, "params": {"turn": {"status": "failed"}}}) is None


# ---------------------------------------------------------------------------
# extract_token_usage_update
# ---------------------------------------------------------------------------


def test_extract_token_usage_update_total_cumulative() -> None:
    """extract_token_usage_update extracts cumulative token usage from total_token_usage."""
    import json
    from pathlib import Path

    fixture_path = (
        Path(__file__).parent.parent / "fixtures" / "codex" / "thread_token_usage_updated.json"
    )
    msg = json.loads(fixture_path.read_text())
    result = extract_token_usage_update(msg)
    assert result is not None
    # From total_token_usage: inputTokens=2500, cachedInputTokens=1200,
    # outputTokens=450, reasoningOutputTokens=120
    assert result["tokens_read"] == 2500
    assert result["tokens_cache"] == 1200
    # Reasoning folded into write: 450 + 120 = 570
    assert result["tokens_write"] == 570
    assert result["tokens_reasoning"] == 120


def test_extract_token_usage_update_camel_and_snake() -> None:
    """extract_token_usage_update handles both camelCase and snake_case field names."""
    # Test camelCase (from fixture)
    msg_camel = {
        "method": "thread/tokenUsage/updated",
        "params": {
            "total_token_usage": {
                "inputTokens": 1000,
                "cachedInputTokens": 200,
                "outputTokens": 150,
                "reasoningOutputTokens": 50,
            }
        },
    }
    result = extract_token_usage_update(msg_camel)
    assert result is not None
    assert result["tokens_read"] == 1000
    assert result["tokens_cache"] == 200
    assert result["tokens_write"] == 200  # 150 + 50
    assert result["tokens_reasoning"] == 50

    # Test snake_case
    msg_snake = {
        "method": "thread/tokenUsage/updated",
        "params": {
            "total_token_usage": {
                "input_tokens": 800,
                "cached_input_tokens": 100,
                "output_tokens": 120,
                "reasoning_output_tokens": 30,
            }
        },
    }
    result = extract_token_usage_update(msg_snake)
    assert result is not None
    assert result["tokens_read"] == 800
    assert result["tokens_cache"] == 100
    assert result["tokens_write"] == 150  # 120 + 30
    assert result["tokens_reasoning"] == 30


def test_extract_token_usage_update_non_usage_returns_none() -> None:
    """extract_token_usage_update returns None for non-usage notifications."""
    msg = {
        "method": "item/agentMessage/delta",
        "params": {"delta": "hello"},
    }
    assert extract_token_usage_update(msg) is None

    msg2 = {
        "method": "turn/completed",
        "params": {"turn": {"status": "completed"}},
    }
    assert extract_token_usage_update(msg2) is None


def test_extract_turn_usage_reasoning_folded() -> None:
    """extract_turn_usage also folds reasoning into write for parity."""
    msg = {
        "method": "turn/completed",
        "params": {
            "turn": {
                "status": "completed",
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 100,
                    "reasoning_output_tokens": 25,
                    "cache_read_tokens": 50,
                },
            }
        },
    }
    result = extract_turn_usage(msg)
    # Reasoning folded into write: 100 + 25 = 125
    assert result["tokens_read"] == 500
    assert result["tokens_write"] == 125
    assert result["tokens_reasoning"] == 25
    assert result["tokens_cache"] == 50
