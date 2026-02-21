"""Integration-level parity tests for CodexServerRemoteAgent.

Exercises the 2×2 parity matrix (builder/verifier × REST/MCP) using real
agent objects — no mocking.  These tests confirm that the remote agent
produces the correct prompt structure and dispatches callbacks identically
for all four cells of the matrix.

Auto-verify filter: codex_server_remote and (builder or verifier) and (rest or mcp)
"""

from __future__ import annotations

import pytest

from orchestrator.agents.codex_server import CodexServerAgent
from orchestrator.agents.codex_server_remote import CodexServerRemoteAgent
from orchestrator.agents.types import ExecutionContext
from orchestrator.config.enums import ChecklistStatus

_VALID_URL = "https://codex.example.com"
_VALID_KEY = "sk-integration-parity-key"  # pragma: allowlist secret


def _remote(channel: str) -> CodexServerRemoteAgent:
    return CodexServerRemoteAgent(
        base_url=_VALID_URL,
        api_key=_VALID_KEY,
        callback_channel=channel,
        _environ={},
    )


def _local(channel: str) -> CodexServerAgent:
    return CodexServerAgent(callback_channel=channel)


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-int-parity",
        task_id="task-int-parity",
        working_dir="/tmp/int-parity",
        prompt="Integration parity task.",
        requirements=["R-01: first requirement", "R-02: second requirement"],
    )


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


# ===========================================================================
# Cell (1): builder phase × REST channel
# ===========================================================================


def test_codex_server_remote_builder_rest_prompt_contains_update_checklist() -> None:
    """Cell (1): remote builder/REST prompt has update_checklist instructions."""
    prompt = _remote("rest")._build_prompt(_ctx(), is_verifier=False)
    assert "update_checklist" in prompt


def test_codex_server_remote_builder_rest_prompt_excludes_grade_workflow() -> None:
    """Cell (1): remote builder/REST prompt excludes verifier grading instructions."""
    prompt = _remote("rest")._build_prompt(_ctx(), is_verifier=False)
    assert "Grade EVERY requirement" not in prompt


async def test_codex_server_remote_builder_rest_callback_parity() -> None:
    """Cell (1): remote builder/REST dispatches update_checklist identically to local."""
    remote_received: list[tuple[str, ChecklistStatus, str | None]] = []
    local_received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def remote_capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        remote_received.append((req_id, status, note))

    async def local_capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        local_received.append((req_id, status, note))

    args = {"req_id": "R-01", "status": "done", "note": "rest-builder"}
    await _remote("rest")._route_tool_call("update_checklist", args, remote_capture, _noop_submit)
    await _local("rest")._route_tool_call("update_checklist", args, local_capture, _noop_submit)
    assert remote_received == local_received


# ===========================================================================
# Cell (2): builder phase × MCP channel
# ===========================================================================


def test_codex_server_remote_builder_mcp_prompt_contains_update_checklist() -> None:
    """Cell (2): remote builder/MCP prompt has update_checklist instructions."""
    prompt = _remote("mcp")._build_prompt(_ctx(), is_verifier=False)
    assert "update_checklist" in prompt


def test_codex_server_remote_builder_mcp_prompt_excludes_grade_workflow() -> None:
    """Cell (2): remote builder/MCP prompt excludes verifier grading instructions."""
    prompt = _remote("mcp")._build_prompt(_ctx(), is_verifier=False)
    assert "Grade EVERY requirement" not in prompt


async def test_codex_server_remote_builder_mcp_callback_parity() -> None:
    """Cell (2): remote builder/MCP dispatches update_checklist identically to local."""
    remote_received: list[tuple[str, ChecklistStatus, str | None]] = []
    local_received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def remote_capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        remote_received.append((req_id, status, note))

    async def local_capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        local_received.append((req_id, status, note))

    args = {"req_id": "R-01", "status": "done", "note": "mcp-builder"}
    await _remote("mcp")._route_tool_call("update_checklist", args, remote_capture, _noop_submit)
    await _local("mcp")._route_tool_call("update_checklist", args, local_capture, _noop_submit)
    assert remote_received == local_received


# ===========================================================================
# Cell (3): verifier phase × REST channel
# ===========================================================================


def test_codex_server_remote_verifier_rest_prompt_contains_grade_tool() -> None:
    """Cell (3): remote verifier/REST prompt has grade instructions."""
    prompt = _remote("rest")._build_prompt(_ctx(), is_verifier=True)
    assert "grade" in prompt


def test_codex_server_remote_verifier_rest_prompt_contains_grading_workflow() -> None:
    """Cell (3): remote verifier/REST prompt has Grade EVERY requirement workflow."""
    prompt = _remote("rest")._build_prompt(_ctx(), is_verifier=True)
    assert "Grade EVERY requirement" in prompt


async def test_codex_server_remote_verifier_rest_callback_parity() -> None:
    """Cell (3): remote verifier/REST grade dispatch identical to local."""
    remote_grades: list[tuple[str, str, str | None]] = []
    local_grades: list[tuple[str, str, str | None]] = []

    async def remote_capture(req_id: str, grade: str, reason: str | None) -> None:
        remote_grades.append((req_id, grade, reason))

    async def local_capture(req_id: str, grade: str, reason: str | None) -> None:
        local_grades.append((req_id, grade, reason))

    args = {"req_id": "R-01", "grade": "A", "grade_reason": "verifier-rest"}
    await _remote("rest")._route_tool_call(
        "grade", args, _noop_checklist, _noop_submit, on_grade=remote_capture
    )
    await _local("rest")._route_tool_call(
        "grade", args, _noop_checklist, _noop_submit, on_grade=local_capture
    )
    assert remote_grades == local_grades


# ===========================================================================
# Cell (4): verifier phase × MCP channel
# ===========================================================================


def test_codex_server_remote_verifier_mcp_prompt_contains_grade_tool() -> None:
    """Cell (4): remote verifier/MCP prompt has grade instructions."""
    prompt = _remote("mcp")._build_prompt(_ctx(), is_verifier=True)
    assert "grade" in prompt


def test_codex_server_remote_verifier_mcp_prompt_contains_grading_workflow() -> None:
    """Cell (4): remote verifier/MCP prompt has Grade EVERY requirement workflow."""
    prompt = _remote("mcp")._build_prompt(_ctx(), is_verifier=True)
    assert "Grade EVERY requirement" in prompt


async def test_codex_server_remote_verifier_mcp_callback_parity() -> None:
    """Cell (4): remote verifier/MCP grade dispatch identical to local."""
    remote_grades: list[tuple[str, str, str | None]] = []
    local_grades: list[tuple[str, str, str | None]] = []

    async def remote_capture(req_id: str, grade: str, reason: str | None) -> None:
        remote_grades.append((req_id, grade, reason))

    async def local_capture(req_id: str, grade: str, reason: str | None) -> None:
        local_grades.append((req_id, grade, reason))

    args = {"req_id": "R-01", "grade": "A", "grade_reason": "verifier-mcp"}
    await _remote("mcp")._route_tool_call(
        "grade", args, _noop_checklist, _noop_submit, on_grade=remote_capture
    )
    await _local("mcp")._route_tool_call(
        "grade", args, _noop_checklist, _noop_submit, on_grade=local_capture
    )
    assert remote_grades == local_grades


# ===========================================================================
# Cross-cell prompt identity: same phase → same prompt regardless of channel
# ===========================================================================


@pytest.mark.parametrize("channel", ["rest", "mcp"])
def test_codex_server_remote_builder_rest_and_mcp_produce_identical_prompts(
    channel: str,
) -> None:
    """Builder prompts are identical for REST and MCP channels."""
    rest_prompt = _remote("rest")._build_prompt(_ctx(), is_verifier=False)
    mcp_prompt = _remote("mcp")._build_prompt(_ctx(), is_verifier=False)
    assert rest_prompt == mcp_prompt


@pytest.mark.parametrize("channel", ["rest", "mcp"])
def test_codex_server_remote_verifier_rest_and_mcp_produce_identical_prompts(
    channel: str,
) -> None:
    """Verifier prompts are identical for REST and MCP channels."""
    rest_prompt = _remote("rest")._build_prompt(_ctx(), is_verifier=True)
    mcp_prompt = _remote("mcp")._build_prompt(_ctx(), is_verifier=True)
    assert rest_prompt == mcp_prompt


# ===========================================================================
# Allow-list enforcement: same reject behavior across all four matrix cells
# ===========================================================================


@pytest.mark.parametrize("channel", ["rest", "mcp"])
async def test_codex_server_remote_builder_rest_mcp_rejects_disallowed_tools(
    channel: str,
) -> None:
    """Builder phase (REST/MCP): disallowed tools raise ValueError before any callback."""
    agent = _remote(channel)
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await agent._route_tool_call("bash", {}, _noop_checklist, _noop_submit)


@pytest.mark.parametrize("channel", ["rest", "mcp"])
async def test_codex_server_remote_verifier_rest_mcp_rejects_disallowed_tools(
    channel: str,
) -> None:
    """Verifier phase (REST/MCP): disallowed tools raise ValueError before any callback."""
    agent = _remote(channel)
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await agent._route_tool_call("write_file", {}, _noop_checklist, _noop_submit)
