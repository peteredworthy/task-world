"""Unit tests for the runner-agnostic graph tool routing module."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.config import ChecklistStatus
from orchestrator.runners import SubmissionAcknowledgement
from orchestrator.runners.graph_tool_routing import (
    GRAPH_MACRO_TOOL_NAMES,
    normalize_macro_tool_payload,
    normalize_patch_payload,
    route_tool_call,
)

_ALLOWLIST = frozenset(
    {"submit_graph_patch", "grade", "update_checklist", "submit"} | GRAPH_MACRO_TOOL_NAMES
)


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


@pytest.mark.parametrize(
    ("disposition", "message"),
    [
        ("rejected", "submission rejected: acceptance command failed"),
        ("durably_staged", "durably staged; pending runner completion and not yet accepted"),
        ("finalized_accepted", "submission is durably finalized and accepted"),
    ],
)
async def test_submit_route_returns_three_way_typed_acknowledgement(
    disposition: str,
    message: str,
) -> None:
    async def submit() -> SubmissionAcknowledgement:
        return SubmissionAcknowledgement(
            disposition=disposition,
            message=message,
            execution_id="execution-1",
            graph_position=12,
        )

    result = await route_tool_call(
        "submit",
        {},
        _noop_checklist,
        submit,
        allowlist=_ALLOWLIST,
    )

    assert f'"disposition":"{disposition}"' in result
    assert message in result
    assert '"graph_position":12' in result


def test_submit_acknowledgement_rejects_non_protocol_disposition() -> None:
    with pytest.raises(ValidationError):
        SubmissionAcknowledgement.model_validate(
            {"disposition": "accepted", "message": "ambiguous generic success"}
        )


def test_normalize_patch_payload_raw_fields() -> None:
    payload = normalize_patch_payload({"patch_id": "p1", "base_graph_position": 3, "ops": []})
    assert payload == {"patch_id": "p1", "base_graph_position": 3, "ops": []}


def test_normalize_patch_payload_nested_patch() -> None:
    payload = normalize_patch_payload(
        {"patch": {"patch_id": "p1", "base_graph_position": 3, "ops": []}}
    )
    assert payload == {"patch_id": "p1", "base_graph_position": 3, "ops": []}


@pytest.mark.parametrize(
    "arguments, expected",
    [
        (
            {"patch_id": "", "base_graph_position": "bad", "ops": "not-a-list"},
            {"patch_id": "", "base_graph_position": "bad", "ops": "not-a-list"},
        ),
        (
            {"patch": {"patch_id": "", "base_graph_position": "bad", "ops": "not-a-list"}},
            {"patch_id": "", "base_graph_position": "bad", "ops": "not-a-list"},
        ),
    ],
)
def test_normalize_patch_payload_defers_invalid_envelope_fields_for_feedback(
    arguments: dict[str, object],
    expected: dict[str, object],
) -> None:
    assert normalize_patch_payload(arguments) == expected


def test_normalize_macro_tool_payload_wraps_as_macro_invocation() -> None:
    payload = normalize_macro_tool_payload(
        "create_work_region",
        {"patch_id": "p1", "base_graph_position": 3, "region_id": "r1"},
    )
    assert payload == {
        "patch_id": "p1",
        "base_graph_position": 3,
        "macro_invocations": [{"macro": "create_work_region", "args": {"region_id": "r1"}}],
    }


async def test_route_tool_call_rejects_disallowed_tool() -> None:
    with pytest.raises(ValueError, match="not on the allow-list"):
        await route_tool_call(
            "bash",
            {},
            _noop_checklist,
            _noop_submit,
            allowlist=_ALLOWLIST,
        )


async def test_route_tool_call_submit_graph_patch_calls_callback() -> None:
    calls: list[dict[str, object]] = []

    async def on_submit_graph_patch(payload: dict[str, object]) -> str:
        calls.append(payload)
        return "accepted"

    result = await route_tool_call(
        "submit_graph_patch",
        {"patch_id": "p1", "base_graph_position": 1, "ops": []},
        _noop_checklist,
        _noop_submit,
        on_submit_graph_patch=on_submit_graph_patch,
        allowlist=_ALLOWLIST,
    )
    assert result == "accepted"
    assert calls == [{"patch_id": "p1", "base_graph_position": 1, "ops": []}]


@pytest.mark.parametrize(
    "arguments, expected_path",
    [
        (
            {
                "patch_id": "p1",
                "base_graph_position": -1,
                "ops": [],
                "unexpected_outer": "do-not-drop",
            },
            "unexpected_outer",
        ),
        (
            {
                "patch": {
                    "patch_id": "p1",
                    "base_graph_position": -1,
                    "ops": [],
                    "unexpected_nested": "do-not-drop",
                }
            },
            "unexpected_nested",
        ),
    ],
)
async def test_route_tool_call_preserves_unknown_patch_fields_for_safe_feedback(
    arguments: dict[str, object],
    expected_path: str,
) -> None:
    calls: list[dict[str, object]] = []

    async def on_submit_graph_patch(payload: dict[str, object]) -> str:
        calls.append(payload)
        return "rejected"

    result = await route_tool_call(
        "submit_graph_patch",
        arguments,
        _noop_checklist,
        _noop_submit,
        on_submit_graph_patch=on_submit_graph_patch,
        allowlist=_ALLOWLIST,
    )

    assert result == "rejected"
    assert calls[0][expected_path] == "do-not-drop"


async def test_route_tool_call_macro_tool_calls_callback_with_normalized_payload() -> None:
    calls: list[dict[str, object]] = []

    async def on_submit_graph_patch(payload: dict[str, object]) -> str:
        calls.append(payload)
        return "accepted"

    await route_tool_call(
        "create_work_region",
        {"patch_id": "p1", "base_graph_position": 1, "region_id": "r1"},
        _noop_checklist,
        _noop_submit,
        on_submit_graph_patch=on_submit_graph_patch,
        allowlist=_ALLOWLIST,
    )
    assert calls == [
        {
            "patch_id": "p1",
            "base_graph_position": 1,
            "macro_invocations": [{"macro": "create_work_region", "args": {"region_id": "r1"}}],
        }
    ]
