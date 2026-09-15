"""Deterministic product-boundary tests for the isolated model-phase probe."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import shlex
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


def _command_completed(
    item_id: str,
    command: str,
    cwd: str,
    exit_code: int,
    output: str = "bounded fixture result",
    status: str = "completed",
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "item/completed",
        "params": {
            "threadId": "thread-verifier",
            "turnId": "turn-verifier",
            "item": {
                "id": item_id,
                "type": "commandExecution",
                "command": command,
                "cwd": cwd,
                "status": status,
                "exitCode": exit_code,
                "aggregatedOutput": output,
            },
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
    def __init__(
        self,
        *,
        alpha_grade: str = "A",
        duplicate_alpha: bool = False,
        execute_commands: bool = True,
        commands_after_submit: bool = False,
        receipt_turn_id: str = "turn-verifier",
        inspection_command: bool = False,
    ) -> None:
        self.sent: list[dict[str, Any]] = []
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._alpha_grade = alpha_grade
        self._duplicate_alpha = duplicate_alpha
        self._execute_commands = execute_commands
        self._commands_after_submit = commands_after_submit
        self._receipt_turn_id = receipt_turn_id
        self._inspection_command = inspection_command
        messages = (
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
        )
        for message in messages:
            self._queue.put_nowait(message)

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)
        if message.get("method") != "turn/start":
            return
        prompt = message["params"]["input"][0]["text"]
        commands = [
            command
            for command in re.findall(r"^[12]\. (.+)$", prompt, flags=re.MULTILINE)
            if "oracle.py candidate-" in command
        ]
        assert len(commands) == 2
        assert all(shlex.split(command) for command in commands)
        cwd = message["params"]["cwd"]
        receipts = (
            _command_completed(
                "cmd-alpha",
                commands[0],
                cwd,
                0,
                json.dumps({"candidate": "candidate-alpha.py", "contract_satisfied": True}) + "\n",
            ),
            _command_completed(
                "cmd-beta",
                commands[1],
                cwd,
                1,
                json.dumps({"candidate": "candidate-beta.py", "contract_satisfied": False}) + "\n",
                status="failed",
            ),
        )
        if self._inspection_command:
            self._queue.put_nowait(_command_completed("cmd-inspect", "ls", cwd, 0))
        for receipt in receipts:
            receipt["params"]["turnId"] = self._receipt_turn_id
        if self._execute_commands and not self._commands_after_submit:
            for receipt in receipts:
                self._queue.put_nowait(receipt)
        self._queue.put_nowait(
            _tool_call(
                10,
                "grade",
                {
                    "req_id": "R-CANDIDATE-ALPHA",
                    "grade": self._alpha_grade,
                    "grade_reason": "Observed contract_satisfied true with exit code zero.",
                },
            )
        )
        self._queue.put_nowait(
            _tool_call(
                11,
                "grade",
                {
                    "req_id": "R-CANDIDATE-BETA",
                    "grade": "F",
                    "grade_reason": "Observed contract_satisfied false with exit code one.",
                },
            )
        )
        if self._duplicate_alpha:
            self._queue.put_nowait(
                _tool_call(
                    13,
                    "grade",
                    {
                        "req_id": "R-CANDIDATE-ALPHA",
                        "grade": "A",
                        "grade_reason": "duplicate grade must invalidate the probe",
                    },
                )
            )
        self._queue.put_nowait(_tool_call(12, "submit", {}))
        if self._execute_commands and self._commands_after_submit:
            for receipt in receipts:
                self._queue.put_nowait(receipt)
        self._queue.put_nowait(_completed())

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
async def test_verifier_probe_separates_neutral_candidates_with_command_receipts(
    tmp_path: Path,
) -> None:
    transport = VerifierTransport(inspection_command=True)

    evidence = await probe.run_verifier_probe(
        tmp_path,
        agent_factory=lambda observer: CodexServerAgent(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            api_key=None,
            _transport=transport,
            _environ={},
            command_completion_observer=observer,
        ),
    )

    assert evidence.status == "passed"
    assert evidence.fixture_unchanged is True
    assert evidence.observations["submit_count"] == 1
    commands = evidence.observations["fixture_oracle_commands"]
    assert [command["returncode"] for command in commands] == [0, 1]
    grades = {item["req_id"]: item for item in evidence.observations["grades"]}
    assert grades["R-CANDIDATE-ALPHA"]["grade"] == "A"
    assert grades["R-CANDIDATE-BETA"]["grade"] == "F"
    receipts = evidence.observations["model_command_receipts"]
    assert [receipt["exit_code"] for receipt in receipts] == [0, 1]
    assert all(Path(receipt["cwd"]) == tmp_path / "verifier-repo" for receipt in receipts)
    assert evidence.observations["model_commands_match_fixture_oracle"] is True
    assert evidence.observations["other_model_command_count"] == 1
    thread_start = next(
        message for message in transport.sent if message.get("method") == "thread/start"
    )
    assert {tool["name"] for tool in thread_start["params"]["dynamicTools"]} >= {
        "grade",
        "submit",
    }
    turn_start = next(
        message for message in transport.sent if message.get("method") == "turn/start"
    )
    prompt = turn_start["params"]["input"][0]["text"].lower()
    assert "candidate-good" not in prompt
    assert "candidate-bad" not in prompt
    assert "known defect" not in prompt


@pytest.mark.asyncio
async def test_verifier_timeout_is_bounded_and_drained(tmp_path: Path) -> None:
    transport = PlannerTransport(complete=False)

    evidence = await probe.run_verifier_probe(
        tmp_path,
        timeout_seconds=0.05,
        agent_factory=lambda _observer: CodexServerAgent(
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
async def test_verifier_rejects_weak_or_duplicate_grades(
    tmp_path: Path,
) -> None:
    transport = VerifierTransport(alpha_grade="B")
    expected_grade_count = 2
    evidence = await probe.run_verifier_probe(
        tmp_path,
        agent_factory=lambda observer: CodexServerAgent(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            api_key=None,
            _transport=transport,
            _environ={},
            command_completion_observer=observer,
        ),
    )

    assert evidence.status == "failed"
    assert len(evidence.observations["grades"]) == expected_grade_count


@pytest.mark.asyncio
async def test_verifier_rejects_duplicate_grade_for_same_obligation(
    tmp_path: Path,
) -> None:
    transport = VerifierTransport(duplicate_alpha=True)
    evidence = await probe.run_verifier_probe(
        tmp_path,
        agent_factory=lambda observer: CodexServerAgent(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            api_key=None,
            _transport=transport,
            _environ={},
            command_completion_observer=observer,
        ),
    )

    assert evidence.status == "failed"
    assert evidence.observations["grades"]


@pytest.mark.asyncio
async def test_verifier_rejects_grade_only_behavior_without_command_receipts(
    tmp_path: Path,
) -> None:
    transport = VerifierTransport(execute_commands=False)

    evidence = await probe.run_verifier_probe(
        tmp_path,
        agent_factory=lambda observer: CodexServerAgent(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            api_key=None,
            _transport=transport,
            _environ={},
            command_completion_observer=observer,
        ),
    )

    assert evidence.status == "failed"
    assert evidence.observations["model_command_receipts"] == []
    assert evidence.observations["model_commands_match_fixture_oracle"] is False


@pytest.mark.asyncio
async def test_verifier_rejects_unbound_or_late_command_receipts(
    tmp_path: Path,
) -> None:
    transport = VerifierTransport(commands_after_submit=True)
    evidence = await probe.run_verifier_probe(
        tmp_path,
        agent_factory=lambda observer: CodexServerAgent(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            api_key=None,
            _transport=transport,
            _environ={},
            command_completion_observer=observer,
        ),
    )

    assert evidence.status == "failed"


@pytest.mark.asyncio
async def test_verifier_rejects_receipt_from_another_turn(
    tmp_path: Path,
) -> None:
    transport = VerifierTransport(receipt_turn_id="turn-other")
    evidence = await probe.run_verifier_probe(
        tmp_path,
        agent_factory=lambda observer: CodexServerAgent(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            api_key=None,
            _transport=transport,
            _environ={},
            command_completion_observer=observer,
        ),
    )

    assert evidence.status == "failed"


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
