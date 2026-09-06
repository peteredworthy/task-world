"""Integration-level callback tests for the local CodexServerAgent.

Tests that the allow-listed callback tools are dispatched correctly using
real agent objects — no mocking.

This file provides the explicit integration target for:

    uv run pytest tests/integration/test_codex_server_callbacks.py -v

Auto-verify filter: codex_server and callbacks and local
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.db import (
    GraphSubmissionGateAuditRepository,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph_runtime import GraphDispatchExecutor, OutboxDispatcher
from orchestrator.runners import (
    AgentRunner,
    CodexServerAgent,
    SubmissionAcknowledgement,
    SubmissionRejectionEvidence,
)
from orchestrator.runners import CODEX_SERVER_TOOL_ALLOWLIST
from orchestrator.runners.types import ExecutionContext
from orchestrator.config import ChecklistStatus
from tests.integration.test_graph_runner_e2e import (
    AgentFactory,
    FixedClock,
    SequentialIds,
    _init_repo,
    _schedule_dispatch_and_wait,
    _seed_active_run,
)

# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------


def _local() -> CodexServerAgent:
    return CodexServerAgent()


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-int-callbacks",
        task_id="task-int-callbacks",
        working_dir="/tmp/int-callbacks",
        prompt="Integration callback test task.",
        requirements=["R-01: first requirement", "R-02: second requirement"],
    )


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


async def _noop_grade(req_id: str, grade: str, reason: str | None) -> None:
    pass


class _PromptDrivenRejectingTransport:
    """Concrete JSON-RPC transport that acts only on observed production traffic."""

    def __init__(self, worktree: Path) -> None:
        self._worktree = worktree
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.prompt: str | None = None
        self.submit_response: dict[str, Any] | None = None

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)
        request_id = message.get("id")
        method = message.get("method")
        if method == "initialize":
            self._queue.put_nowait(
                {"jsonrpc": "2.0", "id": request_id, "result": {"userAgent": "gate-test/1"}}
            )
            return
        if method == "thread/start":
            self._queue.put_nowait(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"thread": {"id": "thread-gate-feedback", "modelProvider": "openai"}},
                }
            )
            return
        if method == "turn/start":
            input_items = message["params"]["input"]
            self.prompt = "\n".join(
                str(item["text"]) for item in input_items if item.get("type") == "text"
            )
            if "Produce one implementation candidate." not in self.prompt:
                raise AssertionError("scripted transport did not receive the real task prompt")
            (self._worktree / "test_late_gate_failure.py").write_text(
                "def test_actionable_summary():\n"
                "    print('x' * 20000)\n"
                "    print('FINAL_DIAGNOSTIC_SENTINEL')\n"
                "    raise AssertionError('actionable late failure')\n",
                encoding="utf-8",
            )
            self._queue.put_nowait(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "turn": {
                            "id": "turn-gate-feedback",
                            "status": "inProgress",
                            "items": [],
                        }
                    },
                }
            )
            self._queue.put_nowait(
                {
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "item/tool/call",
                    "params": {"tool": "submit", "arguments": {}},
                }
            )
            return
        result = message.get("result")
        if request_id == 10 and isinstance(result, dict):
            self.submit_response = message
            self._queue.put_nowait(
                {
                    "jsonrpc": "2.0",
                    "method": "turn/completed",
                    "params": {
                        "turn": {
                            "id": "turn-gate-feedback",
                            "status": "completed",
                            "items": [],
                            "error": None,
                        }
                    },
                }
            )

    async def recv(self) -> dict[str, Any]:
        return await self._queue.get()

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Allow-list: common constant is the single source of truth
# ---------------------------------------------------------------------------


def test_integration_allowlist_has_expected_tools() -> None:
    """The canonical allow-list contains the expected v1 orchestrator callback tools."""
    assert "update_checklist" in CODEX_SERVER_TOOL_ALLOWLIST
    assert "grade" in CODEX_SERVER_TOOL_ALLOWLIST
    assert "submit" in CODEX_SERVER_TOOL_ALLOWLIST
    assert "request_clarification" in CODEX_SERVER_TOOL_ALLOWLIST
    assert "complete_recovery" in CODEX_SERVER_TOOL_ALLOWLIST


# ---------------------------------------------------------------------------
# update_checklist
# ---------------------------------------------------------------------------


async def test_integration_local_update_checklist_done() -> None:
    """Local agent: update_checklist with 'done' dispatches correctly."""
    agent = _local()
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await agent._route_tool_call(
        "update_checklist",
        {"req_id": "R-01", "status": "done", "note": None},
        capture,
        _noop_submit,
    )
    assert received == [ChecklistStatus.DONE]


async def test_integration_local_update_checklist_blocked() -> None:
    """Local agent: 'blocked' status dispatched correctly."""
    agent = _local()
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await agent._route_tool_call(
        "update_checklist",
        {"req_id": "R-01", "status": "blocked", "note": None},
        capture,
        _noop_submit,
    )
    assert received == [ChecklistStatus.BLOCKED]


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("disposition", "message"),
    [
        ("rejected", "submission rejected: acceptance command failed"),
        ("durably_staged", "durably staged; pending runner completion and not yet accepted"),
        ("finalized_accepted", "submission is durably finalized and accepted"),
    ],
)
async def test_integration_local_submit_dispatched_with_three_way_acknowledgement(
    disposition: str,
    message: str,
) -> None:
    """Local agent returns the exact typed submission disposition."""
    agent = _local()
    submitted: list[bool] = []

    async def capture() -> SubmissionAcknowledgement:
        submitted.append(True)
        return SubmissionAcknowledgement.model_validate(
            {
                "disposition": disposition,
                "message": message,
                "execution_id": "execution-1",
                "graph_position": 12,
            }
        )

    result = await agent._route_tool_call("submit", {}, _noop_checklist, capture)
    assert submitted == [True]
    assert f'"disposition":"{disposition}"' in result
    assert message in result


async def test_codex_submit_response_preserves_late_structured_failure_evidence() -> None:
    """Codex's real tool-response JSON must not lose diagnostics after char 4,096."""
    agent = _local()
    failed_test = "tests/integration/test_late_failure.py::test_actionable_summary"

    async def reject() -> SubmissionAcknowledgement:
        return SubmissionAcknowledgement(
            disposition="rejected",
            message="." * 4_096,
            execution_id="execution-long-output",
            rejection_category="candidate_check_failed",
            rejection_evidence=SubmissionRejectionEvidence(
                category="candidate_check_failed",
                command="uv run pytest tests/unit tests/integration -q",
                command_source="project_test_command",
                command_sha256="a" * 64,
                exit_code=1,
                failed_test_ids=(failed_test,),
                final_diagnostic=f"FAILED {failed_test} - AssertionError: useful tail",
                evidence_truncated=True,
                durable_audit_reference="graph-event:run-1:4242",
            ),
        )

    response = await agent._route_tool_call("submit", {}, _noop_checklist, reject)
    decoded = json.loads(response)
    assert len(decoded["message"]) == 4_096
    assert decoded["rejection_evidence"]["failed_test_ids"] == [failed_test]
    assert decoded["rejection_evidence"]["final_diagnostic"].startswith("FAILED ")
    assert decoded["rejection_evidence"]["durable_audit_reference"] == ("graph-event:run-1:4242")


async def test_codex_execute_retains_late_real_gate_failure_and_durable_audit(
    tmp_path: Path,
) -> None:
    """A real Codex execute/submit path returns late pytest evidence intact."""
    engine = create_engine(tmp_path / "codex-gate-feedback.db")
    await init_db(engine)
    sessions: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    worktree = tmp_path / "repo-codex-gate-feedback"
    _init_repo(worktree)
    failed_test = "test_late_gate_failure.py::test_actionable_summary"
    (worktree / "test_late_gate_failure.py").write_text(
        "def test_actionable_summary():\n    assert True\n",
        encoding="utf-8",
    )
    config_dir = worktree / ".task-world"
    config_dir.mkdir()
    command = f"{shlex.quote(sys.executable)} -m pytest -q test_late_gate_failure.py"
    (config_dir / "config.yaml").write_text(
        f"test_command: {json.dumps(command)}\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "test_late_gate_failure.py", ".task-world/config.yaml"],
        cwd=worktree,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "add passing submission gate",
        ],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    )
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "codex-late-gate-feedback"
    transport = _PromptDrivenRejectingTransport(worktree)
    agent = CodexServerAgent(api_key=None, _transport=transport, _environ={})
    agents: dict[str, AgentRunner] = {"worker": agent}

    try:
        controller = await _seed_active_run(sessions, run_id, clock, ids)
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            AgentFactory(agents),
            worktree_path=worktree,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
        dispatcher = OutboxDispatcher(sessions, executor, clock)

        await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

        assert transport.prompt is not None
        assert "call **submit**" in transport.prompt
        response = transport.submit_response
        assert response is not None
        assert response["result"]["success"] is False
        (content_item,) = response["result"]["contentItems"]
        feedback = content_item["text"]
        prefix = "submit callback rejected:"
        assert feedback.startswith(prefix)
        acknowledgement = SubmissionAcknowledgement.model_validate_json(
            feedback.removeprefix(prefix).strip()
        )
        evidence = acknowledgement.rejection_evidence
        assert acknowledgement.disposition == "rejected"
        assert acknowledgement.rejection_category == "candidate_check_failed"
        assert evidence is not None
        assert evidence.category == "candidate_check_failed"
        assert evidence.failed_test_ids == (failed_test,)
        assert failed_test in evidence.final_diagnostic
        assert "FINAL_DIAGNOSTIC_SENTINEL" in evidence.final_diagnostic
        assert evidence.stdout_truncated is True
        assert evidence.evidence_truncated is True
        assert len(evidence.command_sha256 or "") == 64
        assert len(evidence.stdout_sha256 or "") == 64
        assert len(evidence.stderr_sha256 or "") == 64
        assert len(evidence.semantic_failure_fingerprint or "") == 64
        assert evidence.durable_audit_reference is not None

        async with sessions() as session:
            audits = await GraphSubmissionGateAuditRepository(session).list_for_run(
                run_id, limit=10
            )
        failed_audit = next(
            audit for audit in audits if audit.phase == "submission" and audit.status == "failed"
        )
        assert evidence.durable_audit_reference == (f"graph-event:{run_id}:{failed_audit.id}")
        (gate_result,) = failed_audit.report["results"]
        assert gate_result["stdout_bytes"] > 4_096
        assert gate_result["stdout_truncated"] is True
        assert gate_result["stdout_tail"].index(f"FAILED {failed_test}") > 4_096
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# grade: dispatched in verifier phase, ignored in builder phase
# ---------------------------------------------------------------------------


async def test_integration_local_grade_dispatched_verifier() -> None:
    """Local agent: grade dispatched when on_grade is provided (verifier phase)."""
    agent = _local()
    grades: list[tuple[str, str, str | None]] = []

    async def capture(req_id: str, grade: str, reason: str | None) -> None:
        grades.append((req_id, grade, reason))

    await agent._route_tool_call(
        "grade",
        {"req_id": "R-01", "grade": "A", "grade_reason": "Excellent"},
        _noop_checklist,
        _noop_submit,
        on_grade=capture,
    )
    assert grades == [("R-01", "A", "Excellent")]


async def test_integration_local_grade_no_op_in_builder() -> None:
    """Local agent: grade is silently ignored (no error) in builder phase."""
    agent = _local()
    await agent._route_tool_call(
        "grade",
        {"req_id": "R-01", "grade": "A"},
        _noop_checklist,
        _noop_submit,
        on_grade=None,
    )


# ---------------------------------------------------------------------------
# request_clarification
# ---------------------------------------------------------------------------


async def test_integration_local_request_clarification_handled() -> None:
    """Local agent: request_clarification is handled without raising."""
    agent = _local()
    await agent._route_tool_call(
        "request_clarification",
        {"question": "What does R-01 require?"},
        _noop_checklist,
        _noop_submit,
    )


# ---------------------------------------------------------------------------
# Allow-list enforcement: disallowed tools rejected before callbacks run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "disallowed_tool",
    ["bash", "read_file", "write_file", "execute_command", "shell", "SUBMIT", "GRADE", ""],
)
async def test_integration_local_rejects_disallowed_tool(disallowed_tool: str) -> None:
    """Local agent rejects any disallowed tool call."""
    agent = _local()
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await agent._route_tool_call(disallowed_tool, {}, _noop_checklist, _noop_submit)


async def test_integration_disallowed_tool_does_not_invoke_any_callback() -> None:
    """Disallowed tool rejection precedes all callback invocations."""
    checklist_called: list[bool] = []
    submit_called: list[bool] = []

    async def cb_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        checklist_called.append(True)

    async def cb_submit() -> None:
        submit_called.append(True)

    with pytest.raises(ValueError):
        await _local()._route_tool_call("bash", {}, cb_checklist, cb_submit)

    assert checklist_called == [], "No checklist callback must fire on rejected tool"
    assert submit_called == [], "No submit callback must fire on rejected tool"
