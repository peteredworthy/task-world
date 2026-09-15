"""Focused real-transport coverage for opt-in Codex dynamic-tool receipts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from orchestrator.runners import (
    AgentExecutionError,
    CodexDynamicToolReceipt,
    CodexServerAgent,
    ExecutionContext,
    SubmissionAcknowledgement,
    SubmissionContract,
    SubmissionInvocation,
    SubmissionOutputContract,
)
from orchestrator.graph import (
    DECISION_PLAN_SCHEMA_ID,
    DECISION_PLAN_SCHEMA_VERSION,
    decision_plan_declaration,
)


def _response(request_id: int, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _turn_completed() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "turn/completed",
        "params": {
            "turn": {
                "id": "turn-receipt",
                "status": "completed",
                "items": [],
                "error": None,
            }
        },
    }


def _tool_call(request_id: int, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "item/tool/call",
        "params": {"tool": tool, "arguments": arguments},
    }


class ScriptedJsonRpcTransport:
    """Small real Protocol implementation used through constructor injection."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = list(messages)
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    async def recv(self) -> dict[str, Any]:
        if not self._messages:
            raise EOFError("script exhausted")
        return self._messages.pop(0)

    async def close(self) -> None:
        return None


def _context(
    *,
    graph_patch_callback: Any | None = None,
    submission_contract: SubmissionContract | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-receipt",
        task_id="task-receipt",
        working_dir="/tmp/receipt-worktree",
        prompt="Run the receipt probe.",
        requirements=["R-01: preserve tool evidence"],
        graph_patch_callback=graph_patch_callback,
        submission_contract=submission_contract,
    )


async def _noop_checklist(_req_id: str, _status: Any, _note: str | None) -> None:
    return None


async def _noop_submit(*_args: Any) -> None:
    return None


def _handshake_and(*messages: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _response(1, {"userAgent": "receipt-test"}),
        _response(2, {"thread": {"id": "thread-receipt"}}),
        _response(3, {"turn": {"id": "turn-receipt", "status": "inProgress"}}),
        *messages,
    ]


def _implementation_plan_contract() -> SubmissionContract:
    return SubmissionContract(
        interaction_contract="decision-v1",
        outputs=(
            SubmissionOutputContract(
                port="semantic_artifact",
                schema_name="ImplementationPlan",
                semantic_schema_id=DECISION_PLAN_SCHEMA_ID,
                semantic_schema_version=DECISION_PLAN_SCHEMA_VERSION,
                semantic_role="implementation_plan",
                content_json_schema=decision_plan_declaration().json_schema,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_codex_decision_ingress_invokes_callback_for_command_parser_fallbacks() -> None:
    command_definition = {"argv": [" ", "arg"], "cmd": "true"}
    arguments = {
        "outputs": {
            "semantic_artifact": {
                "summary": "Preserve authoritative command fallback semantics.",
                "batches": [
                    {
                        "key": "command-schema",
                        "objective": "Keep Codex ingress aligned with dispatch.",
                        "scope": ["src/orchestrator/graph/command_bindings.py"],
                        "requirements": ["r1"],
                        "acceptance": ["The actual callback receives the plan."],
                        "checks": [
                            {
                                "name": "parser fallback",
                                "command_definition": command_definition,
                            }
                        ],
                    }
                ],
            }
        }
    }
    transport = ScriptedJsonRpcTransport(
        _handshake_and(_tool_call(7, "submit", arguments), _turn_completed())
    )
    agent = CodexServerAgent(api_key=None, _environ={}, _transport=transport)
    callback_calls: list[SubmissionInvocation] = []

    async def on_submit(payload: SubmissionInvocation) -> SubmissionAcknowledgement:
        callback_calls.append(payload)
        return SubmissionAcknowledgement(disposition="durably_staged", message="staged")

    await agent.execute(
        _context(submission_contract=_implementation_plan_contract()),
        _noop_checklist,
        on_submit,
    )

    response = next(message for message in transport.sent if message.get("id") == 7)
    assert response["result"]["success"] is True
    assert [invocation.arguments for invocation in callback_calls] == [arguments]


@pytest.mark.asyncio
async def test_receipt_captures_exact_normalization_rejection() -> None:
    request = _tool_call(7, "construct_reliable_plan_region", {"operation_key": "missing-patch"})
    accepted_request = _tool_call(
        8,
        "submit_graph_patch",
        {
            "patch": {
                "patch_id": "candidate",
                "base_graph_position": 0,
                "nested": {"marker": "original"},
            }
        },
    )
    transport = ScriptedJsonRpcTransport(
        _handshake_and(request, accepted_request, _turn_completed())
    )
    accepted_request_json = json.dumps(accepted_request, sort_keys=True, separators=(",", ":"))
    receipts: list[CodexDynamicToolReceipt] = []

    async def record(receipt: CodexDynamicToolReceipt) -> None:
        receipts.append(receipt)

    agent = CodexServerAgent(
        api_key=None,
        _environ={},
        _transport=transport,
        dynamic_tool_receipt_observer=record,
    )

    async def controller_rejection(payload: dict[str, Any]) -> str:
        payload["nested"]["marker"] = "mutated-by-controller"
        return "controller rejected this candidate for the deterministic probe"

    await agent.execute(
        _context(graph_patch_callback=controller_rejection),
        _noop_checklist,
        _noop_submit,
    )

    assert len(receipts) == 2
    receipt = receipts[0]
    assert (receipt.thread_id, receipt.turn_id, receipt.request_id) == (
        "thread-receipt",
        "turn-receipt",
        7,
    )
    assert receipt.request == json.dumps(request, sort_keys=True, separators=(",", ":"))
    response = next(message for message in transport.sent if message.get("id") == 7)
    assert receipt.response == json.dumps(response, sort_keys=True, separators=(",", ":"))
    assert receipt.request_response_complete is True

    accepted_receipt = receipts[1]
    accepted_response = next(message for message in transport.sent if message.get("id") == 8)
    assert accepted_receipt.request == accepted_request_json
    assert accepted_receipt.response == json.dumps(
        accepted_response, sort_keys=True, separators=(",", ":")
    )
    assert accepted_receipt.thread_id == "thread-receipt"
    assert accepted_receipt.turn_id == "turn-receipt"
    assert "controller rejected" in accepted_receipt.response
    assert '"mutated-by-controller"' not in accepted_receipt.request


@pytest.mark.asyncio
async def test_receipt_omits_oversized_payloads_but_keeps_hash_and_size() -> None:
    large_request = _tool_call(8, "request_clarification", {"question": "x" * (96 * 1024)})
    large_feedback = "controller rejection " + ("y" * (96 * 1024))

    async def reject_with_large_feedback(_payload: dict[str, Any]) -> str:
        return large_feedback

    accepted_shape = {"patch": {"patch_id": "probe", "base_graph_position": 0}}
    transport = ScriptedJsonRpcTransport(
        _handshake_and(
            large_request,
            _tool_call(9, "submit_graph_patch", accepted_shape),
            _turn_completed(),
        )
    )
    receipts: list[CodexDynamicToolReceipt] = []

    async def record(receipt: CodexDynamicToolReceipt) -> None:
        receipts.append(receipt)

    agent = CodexServerAgent(
        api_key=None,
        _environ={},
        _transport=transport,
        dynamic_tool_receipt_observer=record,
    )
    await agent.execute(
        _context(graph_patch_callback=reject_with_large_feedback),
        _noop_checklist,
        _noop_submit,
    )

    assert len(receipts) == 2
    request_receipt, response_receipt = receipts
    assert request_receipt.request is None
    assert request_receipt.request_size_bytes > 96 * 1024
    assert request_receipt.request_sha256 == (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                large_request, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
    assert request_receipt.response is not None
    assert request_receipt.request_response_complete is False
    assert response_receipt.response is None
    assert response_receipt.response_size_bytes > 96 * 1024
    assert response_receipt.request_response_complete is False


@pytest.mark.asyncio
async def test_receipt_observer_failure_fails_closed_before_transport_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = _tool_call(10, "request_clarification", {"question": "record me"})
    transport = ScriptedJsonRpcTransport(_handshake_and(request, _turn_completed()))

    async def failing_observer(_receipt: CodexDynamicToolReceipt) -> None:
        raise RuntimeError("probe storage unavailable")

    agent = CodexServerAgent(
        api_key=None,
        _environ={},
        _transport=transport,
        dynamic_tool_receipt_observer=failing_observer,
    )

    with pytest.raises(AgentExecutionError, match="Dynamic tool receipt observer failed"):
        await agent.execute(_context(), _noop_checklist, _noop_submit)
    assert not any(message.get("id") == 10 for message in transport.sent)
    assert "probe storage unavailable" not in caplog.text
