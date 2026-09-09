"""Deterministic product-boundary tests for the isolated model-phase probe."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import AgentRunnerType
from orchestrator.runners import CodexServerAgent


_SPEC = importlib.util.spec_from_file_location(
    "model_phase_probe", Path("examples/recovery/model_phase_probe.py")
)
assert _SPEC and _SPEC.loader
probe = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = probe
_SPEC.loader.exec_module(probe)


@pytest.mark.asyncio
async def test_cli_workspace_is_canonical_and_supports_real_artifact_publication() -> None:
    canonical_temp = Path(tempfile.gettempdir()).resolve(strict=True)
    content = b"canonical recovery probe artifact"

    with probe._temporary_probe_workspace("planner") as workspace:
        assert workspace.parent == canonical_temp
        assert workspace.is_relative_to(canonical_temp)

        store = FilesystemArtifactStore(workspace / "artifacts")
        async with store.publication():
            ref = await store.put(content, media_type="text/plain", encoding="utf-8")

        assert await store.read(ref) == content

    assert not workspace.exists()


def _response(request_id: int, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_call(request_id: int, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "item/tool/call",
        "params": {"tool": tool, "arguments": arguments},
    }


def _completed() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "turn/completed",
        "params": {
            "turn": {
                "id": "turn-probe",
                "status": "completed",
                "items": [],
                "error": None,
                "usage": {
                    "inputTokens": 120,
                    "outputTokens": 30,
                    "cachedInputTokens": 20,
                    "reasoningOutputTokens": 5,
                },
            }
        },
    }


class PlannerTransport:
    def __init__(self, *, complete: bool = True, submit: bool = True) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._complete = complete
        self._submit = submit
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queue.put_nowait(_response(1, {"userAgent": "probe-test"}))
        self._queue.put_nowait(
            _response(
                2,
                {
                    "thread": {
                        "id": "thread-probe",
                        "preview": "",
                        "modelProvider": "openai",
                        "createdAt": 0,
                    }
                },
            )
        )
        self._queue.put_nowait(
            _response(
                3,
                {
                    "turn": {
                        "id": "turn-probe",
                        "status": "inProgress",
                        "items": [],
                        "error": None,
                    }
                },
            )
        )

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)
        if message.get("method") != "turn/start" or not self._complete:
            return
        prompt = message["params"]["input"][0]["text"]
        match = re.search(r'"current_graph_position"\s*:\s*(\d+)', prompt)
        assert match is not None
        position = int(match.group(1))
        self._queue.put_nowait(
            _tool_call(
                10,
                "construct_reliable_plan_region",
                {
                    "patch_id": "stage2-test-patch",
                    "base_graph_position": position,
                    "operation_key": "decision",
                    "scope": "README.md",
                    "objective": "Discover one bounded read-only plan.",
                    "requirement_ids": ["dynamic_feature_acceptance"],
                    "dependencies": [],
                    "acceptance": ["the bounded plan is explicit"],
                    "checks": [
                        {
                            "name": "fixture check",
                            "command_definition": {"cmd": "true"},
                        }
                    ],
                    "rubric": ["the decision is independently executable"],
                },
            )
        )
        if self._submit:
            self._queue.put_nowait(_tool_call(11, "submit", {}))
        self._queue.put_nowait(_completed())

    async def recv(self) -> dict[str, Any]:
        return await self._queue.get()

    async def close(self) -> None:
        self.closed = True


class VerifierTransport:
    def __init__(self, *, good_grade: str = "A", duplicate_good: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        messages = [
            _response(1, {"userAgent": "probe-test"}),
            _response(
                2,
                {
                    "thread": {
                        "id": "thread-verifier",
                        "preview": "",
                        "modelProvider": "openai",
                        "createdAt": 0,
                    }
                },
            ),
            _response(
                3,
                {
                    "turn": {
                        "id": "turn-verifier",
                        "status": "inProgress",
                        "items": [],
                        "error": None,
                    }
                },
            ),
            _tool_call(
                10,
                "grade",
                {
                    "req_id": "R-GOOD",
                    "grade": good_grade,
                    "grade_reason": "Correctly rejects the missing node_states evidence.",
                },
            ),
            _tool_call(
                11,
                "grade",
                {
                    "req_id": "R-MISSING-NODE-STATES",
                    "grade": "F",
                    "grade_reason": (
                        "candidate-bad falsely reports complete when node_states is missing"
                    ),
                },
            ),
        ]
        if duplicate_good:
            messages.append(
                _tool_call(
                    13,
                    "grade",
                    {
                        "req_id": "R-GOOD",
                        "grade": "A",
                        "grade_reason": "duplicate grade must invalidate the probe",
                    },
                )
            )
        messages.extend((_tool_call(12, "submit", {}), _completed()))
        for message in messages:
            self._queue.put_nowait(message)

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    async def recv(self) -> dict[str, Any]:
        return await self._queue.get()

    async def close(self) -> None:
        return None


class InjectedRunnerBuilder:
    def __init__(self, transport: PlannerTransport) -> None:
        self.transport = transport
        self.calls: list[tuple[AgentRunnerType, dict[str, Any], str, str]] = []

    def __call__(
        self,
        runner_type: AgentRunnerType,
        config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> CodexServerAgent:
        self.calls.append((runner_type, dict(config), run_id, phase))
        return CodexServerAgent(
            model=config.get("model"),
            reasoning_effort=config.get("reasoning_effort", "medium"),
            restrictions=config.get("restrictions", "managed"),
            api_key=None,
            _transport=self.transport,
            _environ={},
        )


@pytest.mark.asyncio
async def test_planner_probe_uses_real_dispatch_schema_and_stops_before_downstream(
    tmp_path: Path,
) -> None:
    transport = PlannerTransport()
    builder = InjectedRunnerBuilder(transport)

    evidence = await probe.run_planner_probe(tmp_path, runner_builder=builder)

    assert evidence.status == "passed"
    assert evidence.observations["accepted_patch_id"] == "stage2-test-patch"
    assert evidence.observations["downstream_lease_count"] == 0
    assert evidence.observations["downstream_dispatch_count"] == 0
    assert evidence.fixture_unchanged is True
    assert len(builder.calls) == 1
    assert builder.calls[0][0] == AgentRunnerType.CODEX_SERVER
    assert builder.calls[0][1]["model"] == "gpt-5.6-luna"
    assert builder.calls[0][1]["reasoning_effort"] == "medium"
    thread_start = next(
        message for message in transport.sent if message.get("method") == "thread/start"
    )
    tools = thread_start["params"]["dynamicTools"]
    macro = next(tool for tool in tools if tool["name"] == "construct_reliable_plan_region")
    assert macro["inputSchema"]["required"]
    assert sum(message.get("method") == "turn/start" for message in transport.sent) == 1


@pytest.mark.asyncio
async def test_planner_probe_timeout_quiesces_owned_runner(tmp_path: Path) -> None:
    transport = PlannerTransport(complete=False)
    builder = InjectedRunnerBuilder(transport)

    evidence = await probe.run_planner_probe(tmp_path, timeout_seconds=0.01, runner_builder=builder)

    assert evidence.status == "incomplete"
    assert evidence.timed_out is True
    assert evidence.incomplete_reason == "operator wall timeout expired"
    assert evidence.observations["owned_process_count_after"] == 0


@pytest.mark.asyncio
async def test_planner_probe_does_not_pass_without_submit_and_finalization(
    tmp_path: Path,
) -> None:
    transport = PlannerTransport(submit=False)
    builder = InjectedRunnerBuilder(transport)

    evidence = await probe.run_planner_probe(tmp_path, runner_builder=builder)

    assert evidence.status == "failed"
    assert evidence.observations["accepted_patch_id"] == "stage2-test-patch"
    assert evidence.observations["plain_submit_finalized"] is False
    assert evidence.observations["runner_failure_event_types"]


@pytest.mark.asyncio
async def test_verifier_probe_separates_good_and_defective_fixture(tmp_path: Path) -> None:
    transport = VerifierTransport()

    evidence = await probe.run_verifier_probe(
        tmp_path,
        agent_factory=lambda: CodexServerAgent(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            api_key=None,
            _transport=transport,
            _environ={},
        ),
    )

    assert evidence.status == "passed"
    assert evidence.fixture_unchanged is True
    assert evidence.observations["submit_count"] == 1
    commands = evidence.observations["independent_commands"]
    assert [command["returncode"] for command in commands] == [0, 1]
    grades = {item["req_id"]: item for item in evidence.observations["grades"]}
    assert grades["R-GOOD"]["grade"] == "A"
    assert grades["R-MISSING-NODE-STATES"]["grade"] == "F"
    assert "node_states" in grades["R-MISSING-NODE-STATES"]["reason"]
    thread_start = next(
        message for message in transport.sent if message.get("method") == "thread/start"
    )
    assert {tool["name"] for tool in thread_start["params"]["dynamicTools"]} >= {
        "grade",
        "submit",
    }


@pytest.mark.asyncio
async def test_verifier_timeout_is_bounded_and_drained(tmp_path: Path) -> None:
    transport = PlannerTransport(complete=False)

    evidence = await probe.run_verifier_probe(
        tmp_path,
        timeout_seconds=0.05,
        agent_factory=lambda: CodexServerAgent(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            api_key=None,
            _transport=transport,
            _environ={},
        ),
    )

    assert evidence.status == "incomplete"
    assert evidence.timed_out is True
    assert evidence.observations["cancellation_requested"] is True
    assert evidence.observations["execution_task_drained"] is True
    assert any(message.get("method") == "turn/interrupt" for message in transport.sent)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport", "expected_grade_count"),
    [
        pytest.param(VerifierTransport(good_grade="B"), 2, id="good-control-must-be-a"),
        pytest.param(VerifierTransport(duplicate_good=True), 3, id="duplicate-grade"),
    ],
)
async def test_verifier_rejects_weak_or_duplicate_grades(
    tmp_path: Path,
    transport: VerifierTransport,
    expected_grade_count: int,
) -> None:
    evidence = await probe.run_verifier_probe(
        tmp_path,
        agent_factory=lambda: CodexServerAgent(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            api_key=None,
            _transport=transport,
            _environ={},
        ),
    )

    assert evidence.status == "failed"
    assert len(evidence.observations["grades"]) == expected_grade_count


def test_cli_serializes_unexpected_execution_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail(_phase: str, _timeout: float) -> tuple[Any, int]:
        raise RuntimeError("bounded test runner failure")

    assert probe.main(["verifier"], run_cli=fail) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["status"] == "error"
    assert payload["phase"] == "verifier"
    assert payload["error"] == "bounded test runner failure"


def test_cli_rejects_timeout_above_operator_cap(capsys: pytest.CaptureFixture[str]) -> None:
    assert probe.main(["planner", "--timeout-seconds", "181"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["phase"] == "planner"
    assert "at most 180" in payload["error"]
