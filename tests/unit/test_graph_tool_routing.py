"""Unit tests for the runner-agnostic graph tool routing module."""

from __future__ import annotations

import pytest

from orchestrator.config import ChecklistStatus
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


def test_normalize_patch_payload_raw_fields() -> None:
    payload = normalize_patch_payload({"patch_id": "p1", "base_graph_position": 3, "ops": []})
    assert payload == {"patch_id": "p1", "base_graph_position": 3, "ops": []}


def test_normalize_patch_payload_nested_patch() -> None:
    payload = normalize_patch_payload(
        {"patch": {"patch_id": "p1", "base_graph_position": 3, "ops": []}}
    )
    assert payload == {"patch_id": "p1", "base_graph_position": 3, "ops": []}


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
