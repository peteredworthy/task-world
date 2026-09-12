"""Product-real decision-v1 dispatch, CAS, and atomic-finalization proof."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from contextlib import asynccontextmanager
import json
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from httpx import ASGITransport, AsyncClient
from starlette.types import Message

import pytest
from sqlalchemy import select

from orchestrator.api import GraphMcpDispatcher
from orchestrator.artifacts import (
    ArtifactIntegrityError,
    FilesystemArtifactStore,
    StoredArtifactRef,
)
from orchestrator.config import AgentRunnerType
from orchestrator.db import GraphOutboxModel, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    DecisionSubmissionEnvelope,
    FakeClock,
    SequentialIdGenerator,
    execution_attempts_view,
    input_bindings_view,
    leases_view,
    node_kinds_view,
    node_payload_view,
    node_states_view,
    output_record_payloads_view,
    resolve_batch_decision_context,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchExecutor,
    GraphEventStore,
    GraphMcpExecutionRegistry,
    StaticGraphAgentFactory,
)
from orchestrator.runners import (
    AgentRunnerInfo,
    ExecutionContext,
    ExecutionResult,
    SubmissionAcknowledgement,
    SubmissionInvocation,
)
from orchestrator.runners.errors import SubmissionRejectedError
from orchestrator.runners.types import (
    AgentMetadataCallback,
    ChecklistUpdateCallback,
    EscalationCallback,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from tests.unit.test_graph_decisions import decision_successor_events
from tests.unit.test_initial_planning_decision import _durable_initial_events
from tests.unit.graph_test_utils import event as graph_event


def _events_for_runner(events: list[Any], runner_type: AgentRunnerType) -> list[Any]:
    """Retarget a disposable qualified graph to one supported runner adapter."""
    output: list[Any] = []
    for event in events:
        payload = dict(event.payload)
        if event.event_type == "node_created":
            payload["reliable_plan_selected_runner_type"] = runner_type.value
            carrier = payload.get("reliable_plan_assignment_carrier")
            if isinstance(carrier, dict):
                updated_carrier = deepcopy(carrier)
                updated_carrier["selected_runner_type"] = runner_type.value
                arm = updated_carrier.get("arm")
                if isinstance(arm, dict):
                    for assignment in arm.values():
                        if isinstance(assignment, dict):
                            assignment["runner_type"] = runner_type.value
                payload["reliable_plan_assignment_carrier"] = updated_carrier
        if event.event_type == "edge_created":
            selector = payload.get("accepted_record_selector")
            if isinstance(selector, dict) and "record_type" not in selector:
                record_type = {
                    "semantic_artifact": "semantic_artifact",
                    "verification_report": "verification_report",
                }.get(str(payload.get("to_port")), "requirement_record")
                payload["accepted_record_selector"] = {
                    **selector,
                    "record_type": record_type,
                }
        output.append(event.model_copy(update={"payload": payload}))
    return output


def _ordered_decision_seed_events(runner_type: AgentRunnerType) -> list[Any]:
    """Make the compact decision fixture valid for durable replay seeding."""
    events = _events_for_runner(decision_successor_events(), runner_type)
    planner_authority = next(
        event.payload
        for event in events
        if event.event_type == "node_created" and event.payload.get("node_id") == "planner-plan"
    )
    planner_carrier = planner_authority["reliable_plan_assignment_carrier"]
    planner_skeleton_id = planner_authority["reliable_plan_skeleton_id"]
    planner_evidence_hash = planner_authority["reliable_plan_qualification_evidence_hash"]
    requirement_events = [
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "requirement_record"
    ]
    events = [event for event in events if event not in requirement_events]
    plan_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "accepted-decision-plan"
    )
    events[plan_index:plan_index] = requirement_events
    positioned: list[Any] = []
    for position, event in enumerate(events, start=1):
        payload = dict(event.payload)
        if event.event_type == "node_created" and payload.get("node_id") == "root":
            payload.update(
                {
                    "reliable_plan_skeleton_id": planner_skeleton_id,
                    "reliable_plan_assignment_carrier": deepcopy(planner_carrier),
                    "reliable_plan_qualification_evidence_hash": planner_evidence_hash,
                    "reliable_plan_selected_runner_type": runner_type.value,
                    "reliable_plan_assignment_role": "planner",
                    "runner_model_override": "test-model",
                    "profile": "architect",
                }
            )
        if event.event_type == "node_created" and payload.get("node_id") == "planner-plan":
            payload.update(
                {
                    "state": "planned",
                    "reliable_plan_assignment_role": "successor_planner",
                    "reliable_plan_selected_runner_type": runner_type.value,
                    "runner_model_override": "test-model",
                    "profile": "architect",
                }
            )
        if event.event_type == "output_record_accepted":
            payload["graph_position"] = position
        if event.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {record_id: position for record_id in record_ids}
        positioned.append(event.model_copy(update={"position": position, "payload": payload}))
    return positioned


def _correction_seed_events() -> list[Any]:
    """Build a durable accepted-plan plus failed-batch correction fixture."""
    events = _ordered_decision_seed_events(AgentRunnerType.CODEX_SERVER)
    cache_authority_hash = next(
        event.payload["cache_authority_hash"]
        for event in events
        if event.event_type == "node_created" and event.payload.get("node_id") == "root"
    )
    updated: list[Any] = []
    for event in events:
        if event.event_type != "node_created" or event.payload.get("node_id") != "planner-plan":
            updated.append(event)
            continue
        payload = dict(event.payload)
        payload.update(
            {
                "role": "gap_planner",
                "semantic_stage": "gap_planning",
                "task_region_id": "successor-core",
                "scope": "core",
                "inputs": [
                    {
                        "port": "routine_snapshot",
                        "direction": "input",
                        "schema": "RoutineSnapshot",
                        "required": True,
                    },
                    {
                        "port": "verification_evidence",
                        "direction": "input",
                        "schema": "VerificationReport",
                        "required": True,
                    },
                ],
                "outputs": [
                    {
                        "port": "decision",
                        "direction": "output",
                        "schema": "DecisionAnswer",
                        "record_layers": ["graph_record"],
                        "required": True,
                    },
                    {
                        "port": "classified_gap",
                        "direction": "output",
                        "schema": "GapClassification",
                        "record_layers": ["graph_record"],
                        "required": True,
                    },
                    {
                        "port": "semantic_artifact",
                        "direction": "output",
                        "schema": "SemanticArtifact",
                        "record_layers": ["graph_record"],
                        "required": False,
                    },
                ],
            }
        )
        updated.append(event.model_copy(update={"payload": payload}))
    events = updated
    position = len(events) + 1
    additions: list[tuple[str, dict[str, Any]]] = [
        (
            "node_created",
            {
                "node_id": "worker-batch-core",
                "kind": "worker",
                "role": "worker",
                "state": "completed",
                "cache_authority_hash": cache_authority_hash,
                "task_region_id": "successor-core",
            },
        ),
        (
            "node_created",
            {
                "node_id": "check-batch-core",
                "kind": "check",
                "role": "check",
                "state": "completed",
                "cache_authority_hash": cache_authority_hash,
                "command_definition": {"argv": ["pytest"]},
                "outputs": [
                    {
                        "port": "check_result",
                        "direction": "output",
                        "schema": "CheckResult",
                        "record_layers": ["verification"],
                    }
                ],
            },
        ),
        (
            "node_created",
            {
                "node_id": "verifier-batch-core",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "cache_authority_hash": cache_authority_hash,
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "core",
                "planning_horizon": 1,
                "outputs": [
                    {
                        "port": "verification_report",
                        "direction": "output",
                        "schema": "VerificationReport",
                        "record_layers": ["verification"],
                    },
                    {
                        "port": "check_result",
                        "direction": "output",
                        "schema": "CheckResult",
                        "record_layers": ["verification"],
                    },
                ],
            },
        ),
        (
            "output_record_accepted",
            {
                "record_id": "candidate-core",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-batch-core",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-core",
                "task_region_id": "successor-core",
                "attempt_number": 1,
                "value": {"summary": "failed batch candidate"},
            },
        ),
        (
            "output_record_accepted",
            {
                "record_id": "gap-evidence-check",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-batch-core",
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": "candidate-core",
                "task_region_id": "successor-core",
                "attempt_number": 1,
                "value": {
                    "status": "failed",
                    "classification": "failed",
                    "command_id": "unit",
                    "command_text": "pytest",
                    "command": {"argv": ["pytest"]},
                    "worktree_path": "/tmp/worktree",
                    "base_snapshot_id": "decision-base",
                    "execution_id": "gap-execution",
                    "exit_code": 1,
                    "duration_ms": 1,
                    "stdout_tail": "",
                    "stderr_tail": "failed",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "timeout_seconds": 10.0,
                    "evaluated_record_ids": ["candidate-core"],
                    "environment_policy": {},
                },
            },
        ),
        (
            "output_record_accepted",
            {
                "record_id": "gap-evidence-report",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-batch-core",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-core",
                "candidate_record_id": "candidate-core",
                "candidate_record_ids": ["candidate-core"],
                "task_region_id": "successor-core",
                "outcome": "failed",
                "value": {"outcome": "failed", "grades": []},
                "evaluated_record_ids": ["gap-evidence-check", "candidate-core"],
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "gap-evidence-to-planner",
                "from_node_id": "verifier-batch-core",
                "from_port": "verification_report",
                "to_node_id": "planner-plan",
                "to_port": "verification_evidence",
                "required": True,
                "dependency_type": "input_binding",
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "failed",
                },
            },
        ),
        (
            "input_bound",
            {
                "edge_id": "gap-evidence-to-planner",
                "to_node_id": "planner-plan",
                "to_port": "verification_evidence",
                "record_ids": ["gap-evidence-report"],
                "record_bound_positions": {"gap-evidence-report": position},
            },
        ),
    ]
    for event_type, payload in additions:
        if event_type == "output_record_accepted":
            payload = {**payload, "graph_position": position}
        if event_type == "input_bound":
            payload = {
                **payload,
                "bound_at_position": position,
                "record_bound_positions": {
                    record_id: position for record_id in payload["record_ids"]
                },
            }
        events.append(graph_event(event_type, payload, position=position))
        position += 1
    return events


def _with_second_initial_requirement(events: list[Any]) -> list[Any]:
    output = list(events)
    position = max(event.position for event in output)
    cache_authority_hash = next(
        event.payload["cache_authority_hash"]
        for event in output
        if event.event_type == "node_created" and event.payload.get("node_id") == "root"
    )
    additions = [
        (
            "node_created",
            {
                "node_id": "requirement-secondary",
                "kind": "requirement",
                "role": "requirement",
                "state": "completed",
                "cache_authority_hash": cache_authority_hash,
                "outputs": [
                    {
                        "port": "requirement",
                        "direction": "output",
                        "schema": "RequirementRecord",
                        "required": True,
                    }
                ],
            },
        ),
        (
            "output_record_accepted",
            {
                "record_id": "requirement-secondary-record",
                "record_kind": "graph_record",
                "record_type": "requirement_record",
                "producer_node_id": "requirement-secondary",
                "port": "requirement",
                "schema": "RequirementRecord",
                "value": {
                    "id": "secondary_requirement",
                    "text": "Expose the bounded parser through the API.",
                    "priority": "critical",
                    "source": "routine",
                    "version": "v1",
                    "must": True,
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-secondary-requirement-to-initial",
                "from_node_id": "requirement-secondary",
                "from_port": "requirement",
                "to_node_id": "planner-plan",
                "to_port": "requirement_2",
                "required": True,
                "dependency_type": "input_binding",
                "accepted_record_selector": {
                    "record_id": "requirement-secondary-record",
                    "record_type": "requirement_record",
                },
            },
        ),
        (
            "input_bound",
            {
                "edge_id": "edge-secondary-requirement-to-initial",
                "to_node_id": "planner-plan",
                "to_port": "requirement_2",
                "record_ids": ["requirement-secondary-record"],
            },
        ),
    ]
    for event_type, raw_payload in additions:
        position += 1
        payload = dict(raw_payload)
        if event_type == "output_record_accepted":
            payload["graph_position"] = position
        if event_type == "input_bound":
            payload["bound_at_position"] = position
            payload["record_bound_positions"] = {"requirement-secondary-record": position}
        output.append(graph_event(event_type, payload, position=position))
    return output


class _BoundaryRestartObserver:
    """Pause after durable boundary commits so a fresh controller can replay."""

    def __init__(self) -> None:
        self.stage_committed = asyncio.Event()
        self.witness_committed = asyncio.Event()
        self.release_stage = asyncio.Event()
        self.release_witness = asyncio.Event()

    async def __call__(
        self,
        phase: str,
        _run_id: str,
        command_type: str,
        _events: tuple[Any, ...],
    ) -> None:
        if phase != "after_commit":
            return
        if command_type == "stage_runner_submission":
            self.stage_committed.set()
            await self.release_stage.wait()
        if command_type == "witness_runner_completion":
            self.witness_committed.set()
            await self.release_witness.wait()


class _GraphMcpProtocolClient:
    """Real JSON-RPC over registered ASGI SSE, without a listening server."""

    def __init__(self, registry: GraphMcpExecutionRegistry, url: str) -> None:
        self._dispatcher = GraphMcpDispatcher(registry)
        self._path = urlsplit(url).path
        self._received: asyncio.Queue[Message] = asyncio.Queue()
        self._sent: asyncio.Queue[Message] = asyncio.Queue()
        self._endpoint = ""
        self._next_id = 0

    @asynccontextmanager
    async def connected(self) -> AsyncIterator[_GraphMcpProtocolClient]:
        await self._received.put({"type": "http.request", "body": b""})
        task = asyncio.create_task(
            self._dispatcher(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": self._path,
                    "raw_path": self._path.encode(),
                    "root_path": "",
                    "query_string": b"",
                    "headers": [(b"host", b"localhost:8000")],
                    "server": ("localhost", 8000),
                    "client": ("test-client", 1),
                },
                self._received.get,
                self._sent.put,
            )
        )
        try:
            response = await asyncio.wait_for(self._sent.get(), 5)
            assert response["type"] == "http.response.start" and response["status"] == 200
            self._endpoint = await self._event_data()
            result = await self.request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "disposable-claude-protocol-client", "version": "1"},
                },
            )
            assert result["serverInfo"]["name"] == "orchestrator-graph-exec"
            await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
            yield self
        finally:
            await self._received.put({"type": "http.disconnect"})
            await asyncio.wait_for(task, 5)

    async def _event_data(self) -> str:
        while True:
            message = await asyncio.wait_for(self._sent.get(), 5)
            body = message.get("body", b"").decode()
            for line in body.splitlines():
                if line.startswith("data: "):
                    return line.removeprefix("data: ")

    async def _post(self, payload: dict[str, Any]) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=self._dispatcher),
            base_url="http://localhost:8000",
        ) as client:
            response = await client.post(self._endpoint, json=payload)
            assert response.status_code == 202, response.text

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        await self._post(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        )
        response = json.loads(await self._event_data())
        assert response["id"] == self._next_id
        assert "error" not in response, response
        return response["result"]

    async def submit(self, invocation: SubmissionInvocation) -> SubmissionAcknowledgement:
        result = await self.request(
            "tools/call", {"name": "submit", "arguments": invocation.arguments}
        )
        content = result["content"][0]["text"]
        if result.get("isError"):
            raise SubmissionRejectedError(
                SubmissionAcknowledgement(
                    disposition="rejected",
                    message=content[:4096],
                    execution_id=invocation.execution_id,
                )
            )
        return SubmissionAcknowledgement.model_validate_json(content)


class _DecisionRunner:
    def __init__(
        self,
        controller: GraphController,
        sessions: Any,
        artifacts: FilesystemArtifactStore,
        execution_id: str,
        arguments: dict[str, Any] | None = None,
        mutate_path_after_submit: Path | None = None,
        runner_type: AgentRunnerType = AgentRunnerType.CODEX_SERVER,
        graph_mcp_registry: Any | None = None,
    ) -> None:
        self._controller = controller
        self._sessions = sessions
        self._artifacts = artifacts
        self._execution_id = execution_id
        self._arguments = arguments
        self._mutate_path_after_submit = mutate_path_after_submit
        self._runner_type = runner_type
        self._graph_mcp_registry = graph_mcp_registry
        self.stage_was_effect_free = False
        self.context_resolved = False
        self.corruption_rejected = False
        self.duplicate_acknowledgement: SubmissionAcknowledgement | None = None
        self.conflict_rejected = False
        self.terminal_close_calls = 0
        self.execution_context: ExecutionContext | None = None
        self.graph_mcp_was_registered = False

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=self._runner_type,
            name="decision-product-runner",
        )

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        if self._runner_type == AgentRunnerType.CLI_SUBPROCESS:
            assert context.graph_mcp_url is not None
            assert self._graph_mcp_registry is not None
            client = _GraphMcpProtocolClient(self._graph_mcp_registry, context.graph_mcp_url)
            async with client.connected():
                listed = await client.request("tools/list", {})
                assert [tool["name"] for tool in listed["tools"]] == ["submit"]
                return await self._execute_decision(context, on_checklist_update, client.submit)
        return await self._execute_decision(context, on_checklist_update, on_submit)

    async def _execute_decision(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        del on_checklist_update, on_output, on_grade, on_agent_metadata, on_escalation
        self.execution_context = context
        if self._runner_type == AgentRunnerType.CLI_SUBPROCESS:
            assert context.graph_mcp_url is not None
            assert self._graph_mcp_registry is not None
            token = context.graph_mcp_url.split("/mcp-graph/", 1)[1].split("/", 1)[0]
            self.graph_mcp_was_registered = self._graph_mcp_registry.get(token) is not None
            assert self.graph_mcp_was_registered
        typed_submit = cast(
            Callable[
                [SubmissionInvocation],
                Awaitable[SubmissionAcknowledgement],
            ],
            on_submit,
        )
        arguments = self._arguments or {
            "outputs": {
                "decision": {
                    "disposition": "proceed",
                    "implementation_notes": "Implement the exact selected batch.",
                }
            }
        }
        invocation = SubmissionInvocation(
            execution_id=self._execution_id,
            answer_attempt_id="attempt-1",
            transport_channel=(
                "claude_graph_mcp"
                if self._runner_type == AgentRunnerType.CLI_SUBPROCESS
                else "codex_dynamic_tool"
            ),
            transport_session_id="session-1",
            transport_request_id="request-1",
            arguments=arguments,
        )
        first = await typed_submit(invocation)
        self.duplicate_acknowledgement = await typed_submit(invocation)
        assert self.duplicate_acknowledgement.disposition == first.disposition
        assert self.duplicate_acknowledgement.execution_id == first.execution_id

        projection = await self._controller.read_projection(context.run_id)
        attempt = execution_attempts_view(projection)[self._execution_id]
        assert attempt.state == "submission_staged"
        async with self._sessions() as session:
            events = await GraphEventStore(session).read_run(context.run_id)
        stage_position = max(
            event.position
            for event in events
            if event.event_type == "runner_submission_staged"
            and event.payload.get("execution_id") == self._execution_id
        )
        post_stage = [event for event in events if event.position >= stage_position]
        self.stage_was_effect_free = not any(
            event.event_type
            in {"graph_patch_accepted", "output_record_accepted", "node_state_changed"}
            for event in post_stage
        )

        assert attempt.payload_ref is not None
        envelope_bytes = await self._artifacts.read(
            StoredArtifactRef.model_validate(attempt.payload_ref.model_dump(mode="json"))
        )
        envelope = DecisionSubmissionEnvelope.model_validate_json(envelope_bytes)
        question_bytes = await self._artifacts.read(envelope.request.question_context_ref)
        self.context_resolved = isinstance(json.loads(question_bytes), dict)
        corrupt_ref = envelope.request.question_context_ref.model_copy(
            update={"content_hash": "sha256:" + "0" * 64}
        )
        try:
            await self._artifacts.read(corrupt_ref)
        except ArtifactIntegrityError:
            self.corruption_rejected = True

        if "semantic_artifact" in cast(dict[str, Any], arguments["outputs"]):
            semantic_artifact = cast(
                dict[str, Any], cast(dict[str, Any], arguments["outputs"])["semantic_artifact"]
            )
            conflicting_arguments = {
                "outputs": {
                    "semantic_artifact": {
                        **semantic_artifact,
                        "summary": "A conflicting implementation plan.",
                    }
                }
            }
        else:
            original_decision = cast(
                dict[str, Any],
                cast(dict[str, Any], arguments["outputs"])["decision"],
            )
            disposition = original_decision.get("disposition")
            if disposition == "revise_plan":
                conflicting_decision = {
                    **original_decision,
                    "reason": "A different valid amendment cannot replace staging.",
                }
            elif disposition == "blocked":
                blocker = cast(dict[str, Any], original_decision["blocker"])
                conflicting_decision = {
                    **original_decision,
                    "blocker": {
                        **blocker,
                        "reason": "A different valid blocker cannot replace staging.",
                    },
                }
            else:
                conflicting_decision = {
                    **original_decision,
                    "implementation_notes": "Conflicting retransmission.",
                }
            conflicting_arguments = (
                {
                    "outputs": {
                        "decision": conflicting_decision,
                    }
                }
                if self._arguments is not None
                else {
                    "outputs": {
                        "decision": {
                            "disposition": "proceed",
                            "implementation_notes": "Conflicting retransmission.",
                        }
                    }
                }
            )
        conflict = invocation.model_copy(
            update={
                "answer_attempt_id": "attempt-2",
                "transport_request_id": "request-2",
                "arguments": conflicting_arguments,
            }
        )
        try:
            await typed_submit(conflict)
        except SubmissionRejectedError:
            self.conflict_rejected = True
        if self._mutate_path_after_submit is not None:
            self._mutate_path_after_submit.write_text(
                "post-answer authoritative mutation\n", encoding="utf-8"
            )
        return ExecutionResult(
            success=True,
            completion_cause="terminal_answer_completed",
        )

    async def request_terminal_answer_completion(self) -> None:
        self.terminal_close_calls += 1

    async def cancel(self) -> None:
        return None


class _PlanVerifierRunner:
    def __init__(
        self, grade: str, runner_type: AgentRunnerType = AgentRunnerType.CODEX_SERVER
    ) -> None:
        self._runner_type = runner_type
        self.execution_context: ExecutionContext | None = None
        self._grade = grade

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=self._runner_type,
            name="decision-plan-verifier",
        )

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        del on_checklist_update, on_output, on_agent_metadata, on_escalation
        self.execution_context = context
        assert on_grade is not None
        requirement_id = context.requirements[0].partition(":")[0]
        await on_grade(
            requirement_id,
            self._grade,
            "The typed plan was assessed against the exact requirement.",
        )
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class _AuthorityMutationDecisionRunner:
    """Revise an exact dispatch input immediately before submitting its answer."""

    def __init__(
        self,
        controller: GraphController,
        sessions: Any,
        execution_id: str,
        *,
        requirement_id: str = "dynamic_feature_acceptance",
        requirement_node_id: str = "initial",
        arguments: dict[str, Any] | None = None,
    ) -> None:
        self._controller = controller
        self._sessions = sessions
        self._execution_id = execution_id
        self._arguments = arguments
        self._requirement_id = requirement_id
        self._requirement_node_id = requirement_node_id
        self.rejection: SubmissionAcknowledgement | None = None
        self.acknowledgement: SubmissionAcknowledgement | None = None
        self.terminal_close_calls = 0

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
            name="authority-mutation-decision-runner",
        )

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        del on_checklist_update, on_output, on_grade, on_agent_metadata, on_escalation
        async with self._sessions() as session:
            position = await GraphEventStore(session).current_position(context.run_id)
        revised = await self._controller.handle_command(
            context.run_id,
            position,
            "record_requirement_revision",
            {
                "requirement_id": self._requirement_id,
                "version_id": f"{self._requirement_id}.v2",
                "classification": "semantic",
                "node_id": self._requirement_node_id,
            },
        )
        assert [event.event_type for event in revised.events] == ["requirement_revision_recorded"]
        invocation = SubmissionInvocation(
            execution_id=self._execution_id,
            answer_attempt_id="attempt-after-authority-change",
            transport_channel="codex_dynamic_tool",
            transport_session_id="session-authority-change",
            transport_request_id="request-authority-change",
            arguments=self._arguments
            or {
                "outputs": {
                    "decision": {
                        "questions": ["Which parser seam should own the feature?"],
                        "rationale": "Repository ownership requires inspection.",
                        "focus": ["docs/spec.md"],
                    }
                }
            },
        )
        typed_submit = cast(
            Callable[[SubmissionInvocation], Awaitable[SubmissionAcknowledgement]],
            on_submit,
        )
        try:
            self.acknowledgement = await typed_submit(invocation)
        except SubmissionRejectedError as exc:
            self.rejection = exc.acknowledgement
        return ExecutionResult(
            success=True,
            completion_cause=(
                "terminal_answer_completed" if self.acknowledgement is not None else None
            ),
        )

    async def request_terminal_answer_completion(self) -> None:
        self.terminal_close_calls += 1

    async def cancel(self) -> None:
        return None


@pytest.mark.parametrize(
    "runner_type", [AgentRunnerType.CODEX_SERVER, AgentRunnerType.CLI_SUBPROCESS]
)
@pytest.mark.parametrize(
    ("verifier_grade", "expected_outcome", "mutate_after_answer", "disjoint_plan"),
    [
        ("A", "passed", False, False),
        ("F", "failed", False, False),
        ("A", None, True, False),
        ("A", "passed", False, True),
    ],
    ids=["passing-plan", "failed-plan", "post-answer-mutation", "disjoint-plan"],
)
@pytest.mark.asyncio
async def test_initial_discovery_brief_runs_through_production_dispatch_and_finalization(
    tmp_path: Path,
    runner_type: AgentRunnerType,
    verifier_grade: str,
    expected_outcome: str | None,
    mutate_after_answer: bool,
    disjoint_plan: bool,
) -> None:
    worktree = tmp_path / "initial-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "initial-decision.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    run_id = "initial-decision-product"
    registry = GraphMcpExecutionRegistry()
    raw_seed_events = _events_for_runner(_durable_initial_events(), runner_type)
    if disjoint_plan:
        raw_seed_events = _with_second_initial_requirement(raw_seed_events)
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in raw_seed_events
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events), [
        (event.event_type, event.payload) for event in seeded.events
    ]
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "initial-base",
            "max_grants": 1,
            "priorities": {"planner-plan": 100},
        },
    )
    dispatch_item = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    projection = await controller.read_projection(run_id)
    lease = next(
        item for item in leases_view(projection).values() if item.node_id == "planner-plan"
    )
    assert lease.execution_id is not None
    artifacts = FilesystemArtifactStore(tmp_path / "initial-artifacts")
    runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        lease.execution_id,
        runner_type=runner_type,
        graph_mcp_registry=registry,
        arguments={
            "outputs": {
                "decision": {
                    "questions": ["Which parser seam should own the feature?"],
                    "rationale": "Repository ownership requires inspection.",
                    "focus": ["docs/spec.md"],
                }
            }
        },
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            runner_type,
            runner_config={"command": "claude"}
            if runner_type == AgentRunnerType.CLI_SUBPROCESS
            else None,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
        graph_mcp_registry=registry,
        base_url="http://localhost:8000",
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)
    assert runner.execution_context is not None
    if runner_type == AgentRunnerType.CLI_SUBPROCESS:
        mcp_url = runner.execution_context.graph_mcp_url
        assert mcp_url is not None
        token = mcp_url.split("/mcp-graph/", 1)[1].split("/", 1)[0]
        assert registry.get(token) is None

    restarted = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    final = await restarted.read_projection(run_id)
    async with sessions() as session:
        diagnostic_events = await GraphEventStore(session).read_run(run_id)
    assert node_states_view(final)["planner-plan"] == "completed", " | ".join(
        f"{event.event_type}:{event.payload.get('reason')}:{event.payload.get('error_detail')}"
        for event in diagnostic_events[-20:]
    )
    decision_records = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "decision_answer"
    ]
    assert len(decision_records) == 1
    assert decision_records[0].value.family == "discovery_brief"
    assert decision_records[0].value.bound_input_record_ids == [
        "routine-snapshot-record",
        "requirement-dynamic-feature-acceptance",
        *(["requirement-secondary-record"] if disjoint_plan else []),
    ]
    semantic_stages = {
        payload.get("semantic_stage")
        for node_id in node_kinds_view(final)
        if (payload := node_payload_view(final, node_id)) is not None
    }
    assert {"discovery", "plan_verification"}.issubset(semantic_stages)
    assert "successor_planning" not in semantic_stages
    assert runner.stage_was_effect_free
    assert runner.terminal_close_calls == 1

    discovery_id = next(
        node_id
        for node_id in node_kinds_view(final)
        if (payload := node_payload_view(final, node_id)) is not None
        and payload.get("semantic_stage") == "discovery"
        and isinstance(payload.get("decision_successor_node_id"), str)
    )
    verifier_id = next(
        node_id
        for node_id in node_kinds_view(final)
        if (payload := node_payload_view(final, node_id)) is not None
        and payload.get("semantic_stage") == "plan_verification"
    )
    discovery_payload = node_payload_view(final, discovery_id)
    assert discovery_payload is not None
    successor_id = cast(str, discovery_payload["decision_successor_node_id"])
    discovery_scheduled = await controller.handle_command(
        run_id,
        max(event.position for event in diagnostic_events),
        "schedule_tick",
        {
            "base_snapshot_id": "initial-base",
            "max_grants": 1,
            "priorities": {discovery_id: 100, verifier_id: 50},
        },
    )
    discovery_item = next(
        item for item in discovery_scheduled.outbox_items if item.kind == "agent_dispatch"
    )
    discovery_projection = await controller.read_projection(run_id)
    discovery_lease = next(
        item for item in leases_view(discovery_projection).values() if item.node_id == discovery_id
    )
    assert discovery_lease.execution_id is not None
    plan_runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        discovery_lease.execution_id,
        runner_type=runner_type,
        graph_mcp_registry=registry,
        arguments={
            "outputs": {
                "semantic_artifact": {
                    "summary": "Implement and validate the bounded parser feature.",
                    "batches": [
                        {
                            "key": "parser",
                            "objective": "Implement the bounded parser feature.",
                            "scope": ["src/parser.py", "tests/unit/test_parser.py"],
                            "requirements": ["r1"],
                            "acceptance": [
                                "The parser satisfies the supplied feature specification."
                            ],
                            "checks": [
                                {
                                    "name": "parser unit tests",
                                    "command_definition": {
                                        "argv": [
                                            "uv",
                                            "run",
                                            "pytest",
                                            "tests/unit/test_parser.py",
                                        ]
                                    },
                                }
                            ],
                        },
                        *(
                            [
                                {
                                    "key": "api",
                                    "objective": "Expose the bounded parser API.",
                                    "scope": ["src/api.py"],
                                    "requirements": ["r2"],
                                    "depends_on": ["parser"],
                                    "acceptance": ["The API exposes the parser."],
                                    "checks": [
                                        {
                                            "name": "api tests",
                                            "command_definition": {"argv": ["uv", "run", "pytest"]},
                                        }
                                    ],
                                }
                            ]
                            if disjoint_plan
                            else []
                        ),
                    ],
                }
            }
        },
        mutate_path_after_submit=(worktree / "README.md" if mutate_after_answer else None),
    )

    def build_plan_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return plan_runner

    plan_executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            runner_type,
            runner_config={"command": "claude"}
            if runner_type == AgentRunnerType.CLI_SUBPROCESS
            else None,
            runner_builder=build_plan_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
        graph_mcp_registry=registry,
        base_url="http://localhost:8000",
    )
    await plan_executor.dispatch(discovery_item)
    await plan_executor.wait_for_all(timeout_seconds=10)
    assert plan_runner.execution_context is not None
    if runner_type == AgentRunnerType.CLI_SUBPROCESS:
        mcp_url = plan_runner.execution_context.graph_mcp_url
        assert mcp_url is not None
        token = mcp_url.split("/mcp-graph/", 1)[1].split("/", 1)[0]
        assert registry.get(token) is None
    plan_projection = await controller.read_projection(run_id)
    async with sessions() as session:
        plan_diagnostic_events = await GraphEventStore(session).read_run(run_id)
    plan_records = [
        record
        for record in output_record_payloads_view(plan_projection).values()
        if record.record_type == "semantic_artifact" and record.producer_node_id == discovery_id
    ]
    if mutate_after_answer:
        assert not plan_records
        assert node_states_view(plan_projection)[discovery_id] != "completed"
        assert successor_id not in node_states_view(plan_projection)
        assert any(
            event.event_type == "runner_boundary_mismatch" for event in plan_diagnostic_events
        )
        await engine.dispose()
        return
    assert len(plan_records) == 1, " | ".join(
        f"{event.event_type}:{event.payload.get('reason')}:{event.payload.get('error_detail')}"
        for event in plan_diagnostic_events[-30:]
    )
    plan_record = plan_records[0]
    assert plan_record.value.schema_id == "orchestrator.reliable-plan.decision-plan"
    assert plan_record.value.requirement_ids == [
        "dynamic_feature_acceptance",
        *(["secondary_requirement"] if disjoint_plan else []),
    ]
    assert plan_record.value.provenance == {
        "source": "agent_submit",
        "execution_id": discovery_lease.execution_id,
    }
    assert plan_runner.execution_context is not None
    assert plan_runner.execution_context is not runner.execution_context
    assert plan_runner.execution_context.execution_id != runner.execution_context.execution_id
    assert Path(plan_runner.execution_context.working_dir) != worktree
    assert (
        subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
    assert node_states_view(plan_projection)[successor_id] == "planned"
    assert not any(
        record.record_type == "verification_report" and record.producer_node_id == verifier_id
        for record in output_record_payloads_view(plan_projection).values()
    )
    async with sessions() as session:
        plan_events = await GraphEventStore(session).read_run(run_id)

    verifier_scheduled = await controller.handle_command(
        run_id,
        max(event.position for event in plan_events),
        "schedule_tick",
        {
            "base_snapshot_id": "initial-base",
            "max_grants": 1,
            "priorities": {verifier_id: 100, successor_id: 1},
        },
    )
    verifier_item = next(
        item for item in verifier_scheduled.outbox_items if item.kind == "agent_dispatch"
    )
    verifier_projection = await controller.read_projection(run_id)
    verifier_lease = next(
        item for item in leases_view(verifier_projection).values() if item.node_id == verifier_id
    )
    assert verifier_lease.execution_id is not None
    verifier_runner = _PlanVerifierRunner(verifier_grade, runner_type)

    def build_verifier_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _PlanVerifierRunner:
        del run_id, phase
        return verifier_runner

    verifier_executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            runner_type,
            runner_config={"command": "claude"}
            if runner_type == AgentRunnerType.CLI_SUBPROCESS
            else None,
            runner_builder=build_verifier_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
        graph_mcp_registry=registry,
        base_url="http://localhost:8000",
    )
    await verifier_executor.dispatch(verifier_item)
    await verifier_executor.wait_for_all(timeout_seconds=10)
    assert verifier_runner.execution_context is not None
    if runner_type == AgentRunnerType.CLI_SUBPROCESS:
        mcp_url = verifier_runner.execution_context.graph_mcp_url
        assert mcp_url is not None
        token = mcp_url.split("/mcp-graph/", 1)[1].split("/", 1)[0]
        assert registry.get(token) is None
    verified = await controller.read_projection(run_id)
    reports = [
        record
        for record in output_record_payloads_view(verified).values()
        if record.record_type == "verification_report" and record.producer_node_id == verifier_id
    ]
    assert len(reports) == 1
    assert reports[0].outcome == expected_outcome
    assert reports[0].evaluated_record_ids == [
        "requirement-dynamic-feature-acceptance",
        *(["requirement-secondary-record"] if disjoint_plan else []),
        plan_record.record_id,
    ]
    assert verifier_runner.execution_context is not None
    assert verifier_runner.execution_context.execution_id == verifier_lease.execution_id
    assert (
        plan_runner.execution_context.execution_id != verifier_runner.execution_context.execution_id
    )
    async with sessions() as session:
        verified_events = await GraphEventStore(session).read_run(run_id)

    successor_scheduled = await controller.handle_command(
        run_id,
        max(event.position for event in verified_events),
        "schedule_tick",
        {
            "base_snapshot_id": "initial-base",
            "max_grants": 1,
            "priorities": {successor_id: 100},
        },
    )
    successor_dispatches = [
        item.kind == "agent_dispatch" and item.payload.get("node_id") == successor_id
        for item in successor_scheduled.outbox_items
    ]
    assert any(successor_dispatches) is (expected_outcome == "passed")
    if expected_outcome == "failed":
        correction_projection = await controller.read_projection(run_id)
        correction_id = next(
            node_id
            for node_id in node_kinds_view(correction_projection)
            if (node_payload_view(correction_projection, node_id) or {}).get("role")
            == "gap_planner"
        )
        assert any(
            item.kind == "agent_dispatch" and item.payload.get("node_id") == correction_id
            for item in successor_scheduled.outbox_items
        )
        assert input_bindings_view(correction_projection)[correction_id][
            "verification_evidence"
        ].record_ids == [reports[0].record_id]
    if expected_outcome == "passed":
        successor_item = next(
            item
            for item in successor_scheduled.outbox_items
            if item.kind == "agent_dispatch" and item.payload.get("node_id") == successor_id
        )
        successor_projection = await controller.read_projection(run_id)
        successor_lease = next(
            item
            for item in leases_view(successor_projection).values()
            if item.node_id == successor_id
        )
        assert successor_lease.execution_id is not None
        successor_runner = _DecisionRunner(
            controller,
            sessions,
            artifacts,
            successor_lease.execution_id,
            runner_type=runner_type,
            graph_mcp_registry=registry,
        )

        def build_successor_runner(
            _runner_type: AgentRunnerType,
            _runner_config: dict[str, Any],
            *,
            run_id: str,
            phase: str,
        ) -> _DecisionRunner:
            del run_id, phase
            return successor_runner

        successor_executor = GraphDispatchExecutor(
            sessions,
            controller,
            StaticGraphAgentFactory(
                runner_type,
                runner_config={"command": "claude"}
                if runner_type == AgentRunnerType.CLI_SUBPROCESS
                else None,
                runner_builder=build_successor_runner,
            ),
            worktree_path=worktree,
            artifact_store=artifacts,
            graph_mcp_registry=registry,
            base_url="http://localhost:8000",
        )
        await successor_executor.dispatch(successor_item)
        await successor_executor.wait_for_all(timeout_seconds=10)
        assert successor_runner.execution_context is not None
        if runner_type == AgentRunnerType.CLI_SUBPROCESS:
            mcp_url = successor_runner.execution_context.graph_mcp_url
            assert mcp_url is not None
            token = mcp_url.split("/mcp-graph/", 1)[1].split("/", 1)[0]
            assert registry.get(token) is None
        joined = await controller.read_projection(run_id)
        async with sessions() as session:
            joined_events = await GraphEventStore(session).read_run(run_id)

        successor_answers = [
            record
            for record in output_record_payloads_view(joined).values()
            if record.record_type == "decision_answer" and record.producer_node_id == successor_id
        ]
        assert len(successor_answers) == 1
        assert successor_answers[0].value.family == "batch_decision"
        assert node_states_view(joined)[successor_id] == "completed"
        assert not any(lease.state == "active" for lease in leases_view(joined).values())
        assert all(
            attempt.state == "finalized" for attempt in execution_attempts_view(joined).values()
        )
        assert successor_runner.execution_context is not None
        assert successor_runner.execution_context.execution_id not in {
            runner.execution_context.execution_id,
            plan_runner.execution_context.execution_id,
            verifier_runner.execution_context.execution_id,
        }
        assert any(
            (node_payload_view(joined, node_id) or {}).get("semantic_stage") == "effectful_batch"
            for node_id in node_kinds_view(joined)
        )
        if disjoint_plan:
            resolved_successor = resolve_batch_decision_context(joined, successor_id)
            assert resolved_successor.selected_batch.key == "parser"
            assert resolved_successor.requirement_record_ids == (
                "requirement-dynamic-feature-acceptance",
            )
            assert all(event.event_type != "command_rejected" for event in joined_events), (
                joined_events
            )
    await engine.dispose()


@pytest.mark.parametrize(
    ("requirement_id", "requirement_node_id", "expect_rejection"),
    [
        ("dynamic_feature_acceptance", "initial", True),
        ("unrelated_requirement", "unrelated-node", False),
    ],
    ids=["bound-authority-rejected", "unrelated-movement-accepted"],
)
@pytest.mark.asyncio
async def test_initial_discovery_brief_freezes_dispatch_authority_without_blocking_unrelated_tail(
    tmp_path: Path,
    requirement_id: str,
    requirement_node_id: str,
    expect_rejection: bool,
) -> None:
    worktree = tmp_path / "authority-race-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "authority-race.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    run_id = "initial-decision-authority-race"
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in _durable_initial_events()
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "authority-race-base",
            "max_grants": 1,
            "priorities": {"planner-plan": 100},
        },
    )
    dispatch_item = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    dispatched = await controller.read_projection(run_id)
    lease = next(
        item for item in leases_view(dispatched).values() if item.node_id == "planner-plan"
    )
    assert lease.execution_id is not None
    artifacts = FilesystemArtifactStore(tmp_path / "authority-race-artifacts")
    runner = _AuthorityMutationDecisionRunner(
        controller,
        sessions,
        lease.execution_id,
        requirement_id=requirement_id,
        requirement_node_id=requirement_node_id,
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _AuthorityMutationDecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)

    final = await controller.read_projection(run_id)
    async with sessions() as session:
        events = await GraphEventStore(session).read_run(run_id)
    staged = [event for event in events if event.event_type == "runner_submission_staged"]
    decision_patches = [
        event
        for event in events
        if event.event_type == "graph_patch_accepted"
        and event.payload.get("proposed_by_node_id") == "planner-plan"
    ]
    decision_records = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "decision_answer"
    ]
    downstream_stages = {
        payload.get("semantic_stage")
        for node_id in node_kinds_view(final)
        if (payload := node_payload_view(final, node_id)) is not None
    } & {"discovery", "plan_verification", "successor_planning"}
    if not expect_rejection:
        assert runner.rejection is None
        assert runner.acknowledgement is not None
        assert runner.acknowledgement.disposition == "durably_staged"
        assert runner.terminal_close_calls == 1
        assert len(staged) == len(decision_patches) == len(decision_records) == 1
        assert downstream_stages == {
            "discovery",
            "plan_verification",
        }
        await engine.dispose()
        return

    assert runner.rejection is not None
    assert runner.rejection.disposition == "rejected"
    assert "read authority changed" in runner.rejection.message
    assert not staged
    assert not decision_patches
    assert not decision_records
    assert not downstream_stages
    await engine.dispose()


@pytest.mark.parametrize(
    ("requirement_id", "requirement_node_id", "expect_rejection"),
    [
        ("REQ-1", "requirement-1", True),
        ("unrelated_requirement", "unrelated-node", False),
    ],
    ids=["bound-authority-rejected", "unrelated-movement-accepted"],
)
@pytest.mark.asyncio
async def test_correction_freezes_dispatch_requirement_authority_without_blocking_unrelated_tail(
    tmp_path: Path,
    requirement_id: str,
    requirement_node_id: str,
    expect_rejection: bool,
) -> None:
    worktree = tmp_path / "authority-race-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "authority-race.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    run_id = "correction-decision-authority-race"
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in _correction_seed_events()
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "authority-race-base",
            "max_grants": 1,
            "priorities": {"planner-plan": 100},
        },
    )
    dispatch_item = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    dispatched = await controller.read_projection(run_id)
    lease = next(
        item for item in leases_view(dispatched).values() if item.node_id == "planner-plan"
    )
    assert lease.execution_id is not None
    artifacts = FilesystemArtifactStore(tmp_path / "authority-race-artifacts")
    runner = _AuthorityMutationDecisionRunner(
        controller,
        sessions,
        lease.execution_id,
        requirement_id=requirement_id,
        requirement_node_id=requirement_node_id,
        arguments={
            "outputs": {
                "decision": {
                    "disposition": "corrective_work",
                    "diagnosis": "The accepted batch failed its required check.",
                    "remedy": "Repair only the failed batch implementation.",
                    "focus": ["src/core.py"],
                    "evidence": ["e1", "e2"],
                }
            }
        },
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _AuthorityMutationDecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)

    final = await controller.read_projection(run_id)
    async with sessions() as session:
        events = await GraphEventStore(session).read_run(run_id)
    staged = [event for event in events if event.event_type == "runner_submission_staged"]
    decision_patches = [
        event
        for event in events
        if event.event_type == "graph_patch_accepted"
        and event.payload.get("proposed_by_node_id") == "planner-plan"
    ]
    decision_records = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "decision_answer"
    ]
    downstream_stages = {
        payload.get("semantic_stage")
        for node_id in node_kinds_view(final)
        if (payload := node_payload_view(final, node_id)) is not None
    } & {"corrective_work"}
    if not expect_rejection:
        assert runner.rejection is None
        assert runner.acknowledgement is not None
        assert runner.acknowledgement.disposition == "durably_staged"
        assert runner.terminal_close_calls == 1
        assert len(staged) == len(decision_patches) == len(decision_records) == 1
        assert downstream_stages == {"corrective_work"}
        assert decision_records[0].value.family == "correction_decision"
        assert not any(lease.state == "active" for lease in leases_view(final).values())
        await engine.dispose()
        return

    assert runner.rejection is not None
    assert runner.rejection.disposition == "rejected"
    assert "read authority changed" in runner.rejection.message
    assert not staged
    assert not decision_patches
    assert not decision_records
    assert not downstream_stages
    assert set(output_record_payloads_view(final)) == set(output_record_payloads_view(dispatched))
    assert set(node_kinds_view(final)) == set(node_kinds_view(dispatched))
    await engine.dispose()


@pytest.mark.asyncio
async def test_claude_cli_decision_dispatch_uses_a_live_per_execution_graph_mcp_route(
    tmp_path: Path,
) -> None:
    """The supported CLI adapter receives the same typed decision contract."""
    worktree = tmp_path / "cli-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "cli-decision.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    run_id = "cli-decision-product"
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in _ordered_decision_seed_events(AgentRunnerType.CLI_SUBPROCESS)
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events), [
        (event.event_type, event.payload) for event in seeded.events
    ]
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "cli-decision-base",
            "max_grants": 1,
            "priorities": {"planner-plan": 100},
        },
    )
    dispatch_item = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    projection = await controller.read_projection(run_id)
    lease = next(
        item for item in leases_view(projection).values() if item.node_id == "planner-plan"
    )
    assert lease.execution_id is not None
    artifacts = FilesystemArtifactStore(tmp_path / "cli-artifacts")
    registry = GraphMcpExecutionRegistry()
    runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        lease.execution_id,
        runner_type=AgentRunnerType.CLI_SUBPROCESS,
        graph_mcp_registry=registry,
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CLI_SUBPROCESS,
            {"command": "claude"},
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
        graph_mcp_registry=registry,
        base_url="http://localhost:8000",
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)

    final = await controller.read_projection(run_id)
    answers = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "decision_answer"
    ]
    assert len(answers) == 1
    assert answers[0].value.family == "batch_decision"
    assert node_states_view(final)["planner-plan"] == "completed"
    assert runner.graph_mcp_was_registered
    assert runner.execution_context is not None
    assert runner.execution_context.submission_contract is not None
    assert runner.execution_context.submission_contract.interaction_contract == "decision-v1"
    await engine.dispose()


@pytest.mark.asyncio
async def test_rejected_batch_dispatches_a_bounded_correction_decision(
    tmp_path: Path,
) -> None:
    """A failed batch offers exact evidence to one production correction answer."""
    worktree = tmp_path / "correction-worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "correction-decision.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    run_id = "correction-decision-product"
    seed_events = [
        event.model_copy(
            update={
                "run_id": run_id,
                "payload": {**event.payload, "run_id": run_id},
            }
        )
        for event in _correction_seed_events()
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events), [
        (event.event_type, event.payload) for event in seeded.events
    ]
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "correction-decision-base",
            "max_grants": 1,
            "priorities": {"planner-plan": 100},
        },
    )
    dispatch_item = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    projection = await controller.read_projection(run_id)
    lease = next(
        item for item in leases_view(projection).values() if item.node_id == "planner-plan"
    )
    assert lease.execution_id is not None
    artifacts = FilesystemArtifactStore(tmp_path / "correction-artifacts")
    runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        lease.execution_id,
        arguments={
            "outputs": {
                "decision": {
                    "disposition": "corrective_work",
                    "diagnosis": "The accepted batch failed its required check.",
                    "remedy": "Repair only the failed batch implementation.",
                    "focus": ["src/core.py"],
                    "evidence": ["e1", "e2"],
                }
            }
        },
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
    )
    await executor.dispatch(dispatch_item)
    await executor.wait_for_all(timeout_seconds=10)

    final = await controller.read_projection(run_id)
    answers = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "decision_answer"
    ]
    gap_records = [
        record
        for record in output_record_payloads_view(final).values()
        if record.record_type == "classified_gap"
    ]
    assert len(answers) == 1
    assert answers[0].value.family == "correction_decision"
    assert len(gap_records) == 1
    assert gap_records[0].value.classification == "corrective_work_required"
    assert node_states_view(final)["planner-plan"] == "completed"
    assert any(
        (node_payload_view(final, node_id) or {}).get("semantic_stage") == "corrective_work"
        for node_id in node_kinds_view(final)
    )
    assert not any(lease.state == "active" for lease in leases_view(final).values())
    assert all(attempt.state == "finalized" for attempt in execution_attempts_view(final).values())
    assert runner.terminal_close_calls == 1
    await engine.dispose()


def _init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test User"], check=True)
    (path / "README.md").write_text("decision runtime\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "initial"], check=True)


def _successor_decision_arguments(case: str) -> dict[str, Any] | None:
    if case == "proceed":
        return None
    if case == "revise_plan_final_pass":
        return {
            "outputs": {
                "decision": {
                    "disposition": "revise_plan",
                    "reason": "The final core batch needs one explicit compatibility check.",
                    "amendment": {
                        "refinements": [
                            {
                                "batch": "core",
                                "acceptance": [
                                    "The accepted core preserves legacy request behavior."
                                ],
                            }
                        ]
                    },
                }
            }
        }
    if case.startswith("revise_plan_nonfinal_"):
        return {
            "outputs": {
                "decision": {
                    "disposition": "revise_plan",
                    "reason": "A separate API batch is required before finalization.",
                    "amendment": {
                        "additional_batches": [
                            {
                                "key": "api",
                                "objective": "Expose the accepted core through its public API.",
                                "scope": ["src/core.py"],
                                "requirements": ["r1"],
                                "depends_on": ["core"],
                                "acceptance": ["The public API exposes the accepted core."],
                                "checks": [
                                    {
                                        "name": "api tests",
                                        "command_definition": {"argv": ["pytest"]},
                                    }
                                ],
                            }
                        ]
                    },
                }
            }
        }
    if case == "blocked":
        return {
            "outputs": {
                "decision": {
                    "disposition": "blocked",
                    "blocker": {
                        "reason": "The public compatibility policy is not available.",
                        "needed_information": [
                            "Confirm whether legacy request payloads remain supported."
                        ],
                        "evidence": ["e1"],
                    },
                }
            }
        }
    raise AssertionError(f"unknown decision test case: {case}")


@pytest.mark.parametrize(
    ("decision_case", "cancel_after_witness"),
    [
        ("proceed", False),
        ("proceed", True),
        ("revise_plan_nonfinal_pass", False),
        ("revise_plan_nonfinal_pass", True),
        ("revise_plan_nonfinal_fail", False),
        ("revise_plan_final_pass", False),
        ("blocked", False),
    ],
    ids=[
        "proceed-finalization-wins",
        "proceed-cancellation-wins",
        "revise-plan-nonfinal-pass",
        "revise-plan-cancellation-wins",
        "revise-plan-nonfinal-fail",
        "revise-plan-final-pass",
        "blocked",
    ],
)
@pytest.mark.asyncio
async def test_decision_dispatch_stages_cas_then_atomically_finalizes(
    tmp_path: Path,
    decision_case: str,
    cancel_after_witness: bool,
) -> None:
    worktree = tmp_path / "worktree"
    _init_repo(worktree)
    engine = create_engine(tmp_path / "decision.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    boundary_observer = _BoundaryRestartObserver()
    controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
        command_commit_observer=boundary_observer,
    )
    run_id = "decision-run"
    source_events = decision_successor_events()
    planner_authority = next(
        event.payload
        for event in source_events
        if event.event_type == "node_created" and event.payload.get("node_id") == "planner-plan"
    )
    seed_events = []
    for event in source_events:
        payload = dict(event.payload)
        if event.event_type == "node_created" and payload.get("node_id") == "root":
            for key in (
                "reliable_plan_skeleton_id",
                "reliable_plan_assignment_carrier",
                "reliable_plan_qualification_evidence_hash",
            ):
                payload[key] = planner_authority[key]
            payload["reliable_plan_selected_runner_type"] = "codex_server"
            payload["reliable_plan_assignment_role"] = "planner"
            payload["runner_model_override"] = "test-model"
            payload["profile"] = "architect"
        if event.event_type == "node_created" and payload.get("node_id") == "planner-plan":
            payload["state"] = "planned"
            payload["reliable_plan_assignment_role"] = "successor_planner"
            payload["reliable_plan_selected_runner_type"] = "codex_server"
            payload["runner_model_override"] = "test-model"
            payload["profile"] = "architect"
        if event.event_type == "edge_created":
            selector = payload.get("accepted_record_selector")
            if isinstance(selector, dict) and "record_type" not in selector:
                record_type = {
                    "semantic_artifact": "semantic_artifact",
                    "verification_report": "verification_report",
                }.get(str(payload.get("to_port")), "requirement_record")
                payload["accepted_record_selector"] = {
                    **selector,
                    "record_type": record_type,
                }
        seed_events.append(event.model_copy(update={"run_id": run_id, "payload": payload}))
    requirement_events = [
        event
        for event in seed_events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "requirement_record"
    ]
    seed_events = [event for event in seed_events if event not in requirement_events]
    plan_index = next(
        index
        for index, event in enumerate(seed_events)
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_id") == "accepted-decision-plan"
    )
    seed_events[plan_index:plan_index] = requirement_events
    positioned_seed_events = []
    for position, event in enumerate(seed_events, start=1):
        payload = dict(event.payload)
        if event.event_type == "output_record_accepted":
            payload["graph_position"] = position
        positioned_seed_events.append(
            event.model_copy(update={"position": position, "payload": payload})
        )
    seed_events = []
    for event in positioned_seed_events:
        payload = dict(event.payload)
        if event.event_type == "input_bound":
            record_ids = cast(list[str], payload["record_ids"])
            payload["bound_at_position"] = event.position
            payload["record_bound_positions"] = {
                record_id: event.position for record_id in record_ids
            }
        seed_events.append(event.model_copy(update={"payload": payload}))
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": seed_events},
    )
    assert not any(event.event_type == "command_rejected" for event in seeded.events), [
        (event.event_type, event.payload) for event in seeded.events
    ]
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    scheduled = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {
            "base_snapshot_id": "decision-base",
            "max_grants": 1,
            "priorities": {"planner-plan": 100},
        },
    )
    assert scheduled.outbox_items, [(event.event_type, event.payload) for event in scheduled.events]
    dispatch_item = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    projection = await controller.read_projection(run_id)
    lease = next(
        item for item in leases_view(projection).values() if item.node_id == "planner-plan"
    )
    assert lease.execution_id is not None
    artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
    runner = _DecisionRunner(
        controller,
        sessions,
        artifacts,
        lease.execution_id,
        arguments=_successor_decision_arguments(decision_case),
    )

    def build_runner(
        _runner_type: AgentRunnerType,
        _runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> _DecisionRunner:
        del run_id, phase
        return runner

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            runner_builder=build_runner,
        ),
        worktree_path=worktree,
        artifact_store=artifacts,
    )
    await executor.dispatch(dispatch_item)
    await asyncio.wait_for(boundary_observer.stage_committed.wait(), timeout=5)
    stage_restart = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    staged_projection = await stage_restart.read_projection(run_id)
    assert execution_attempts_view(staged_projection)[cast(str, lease.execution_id)].state == (
        "submission_staged"
    )
    boundary_observer.release_stage.set()
    await asyncio.wait_for(boundary_observer.witness_committed.wait(), timeout=5)
    witness_restart = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    witnessed_projection = await witness_restart.read_projection(run_id)
    assert execution_attempts_view(witnessed_projection)[cast(str, lease.execution_id)].state == (
        "completion_witnessed"
    )
    if cancel_after_witness:
        async with sessions() as session:
            witnessed_position = await GraphEventStore(session).current_position(run_id)
        cancelled = await witness_restart.handle_command(
            run_id,
            witnessed_position,
            "cancel",
            {"trigger": "serialized_test_cancellation"},
        )
        assert any(event.event_type == "run_lifecycle_changed" for event in cancelled.events)
    boundary_observer.release_witness.set()
    await executor.wait_for_all(timeout_seconds=10)

    async with sessions() as diagnostic_session:
        diagnostic_events = await GraphEventStore(diagnostic_session).read_run(run_id)
    assert runner.stage_was_effect_free, " | ".join(
        f"{event.event_type}:{event.payload.get('reason')}:{event.payload.get('error_detail')}:{event.payload.get('new_state')}"
        for event in diagnostic_events[-20:]
    )
    assert runner.context_resolved
    assert runner.corruption_rejected
    assert runner.duplicate_acknowledgement is not None
    assert runner.duplicate_acknowledgement.disposition == "durably_staged"
    assert runner.conflict_rejected
    assert runner.terminal_close_calls == 1

    restarted_controller = GraphController(
        sessions,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    final_projection = await restarted_controller.read_projection(run_id)
    if cancel_after_witness:
        assert node_states_view(final_projection)["planner-plan"] == "cancelled"
    else:
        expected_state = "failed" if decision_case == "blocked" else "completed"
        assert node_states_view(final_projection)["planner-plan"] == expected_state, " | ".join(
            f"{event.event_type}:{event.payload.get('reason')}:{event.payload.get('error_detail')}"
            for event in diagnostic_events[-20:]
        )
    attempt = execution_attempts_view(final_projection)[cast(str, lease.execution_id)]
    decision_records = [
        record
        for record in output_record_payloads_view(final_projection).values()
        if record.record_type == "decision_answer"
    ]
    assert len(decision_records) == (0 if cancel_after_witness else 1)
    async with sessions() as session:
        events = await GraphEventStore(session).read_run(run_id)
        outbox = list(
            (
                await session.execute(
                    select(GraphOutboxModel).where(GraphOutboxModel.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
    finalizations = [event for event in events if event.event_type == "runner_execution_finalized"]
    decision_patches = [
        event
        for event in events
        if event.event_type == "graph_patch_accepted"
        and event.payload.get("proposed_by_node_id") == "planner-plan"
    ]
    decision_outputs = [
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "decision_answer"
    ]
    terminal_transitions = [
        event
        for event in events
        if event.event_type == "node_state_changed"
        and event.payload.get("node_id") == "planner-plan"
        and event.payload.get("new_state")
        == ("failed" if decision_case == "blocked" else "completed")
    ]
    if decision_case == "blocked" and terminal_transitions:
        assert "public compatibility policy" in str(terminal_transitions[0].payload.get("reason"))
        assert len(str(terminal_transitions[0].payload.get("reason"))) <= 1000
    expected_effect_sets = 0 if cancel_after_witness else 1
    assert (
        len(finalizations)
        == len(decision_patches)
        == len(decision_outputs)
        == len(terminal_transitions)
        == expected_effect_sets
    )
    if not cancel_after_witness:
        assert attempt.state == "finalized"
        causation_ids = {
            event.causation_id
            for event in [
                finalizations[0],
                decision_patches[0],
                decision_outputs[0],
                terminal_transitions[0],
            ]
        }
        assert causation_ids == {"finalize_runner_execution"}

        semantic_records = [
            record
            for record in output_record_payloads_view(final_projection).values()
            if record.record_type == "semantic_artifact"
            and record.producer_node_id == "planner-plan"
        ]
        human_gates = [
            payload
            for node_id in node_states_view(final_projection)
            if (payload := node_payload_view(final_projection, node_id)) is not None
            and payload.get("kind") == "human_gate"
        ]
        if decision_case.startswith("revise_plan_"):
            assert len(semantic_records) == 1
            amendment_id = semantic_records[0].record_id
            assert semantic_records[0].value.supersedes_record_id == "accepted-decision-plan"
            created_payloads = [
                payload
                for node_id in node_states_view(final_projection)
                if (payload := node_payload_view(final_projection, node_id)) is not None
                and payload.get("accepted_plan_amendment_record_id") == amendment_id
            ]
            assert {payload.get("semantic_stage") for payload in created_payloads} == {
                "plan_verification",
                "successor_planning",
            }
            assert not human_gates
        elif decision_case == "blocked":
            assert not semantic_records
            assert len(human_gates) == 1
            assert human_gates[0]["decision_request"]["target_node_id"] == "planner-plan"

        finalize_position = events[-1].position
        duplicate_executor = GraphDispatchExecutor(
            sessions,
            restarted_controller,
            StaticGraphAgentFactory(
                AgentRunnerType.CODEX_SERVER,
                runner_builder=build_runner,
            ),
            worktree_path=worktree,
            artifact_store=artifacts,
        )
        assert cast(
            str, lease.execution_id
        ) in await duplicate_executor.reconcile_execution_attempts(run_id)
        async with sessions() as session:
            duplicate_position = await GraphEventStore(session).current_position(run_id)
        assert duplicate_position == finalize_position

        if decision_case.startswith("revise_plan_"):
            verifier_id = next(
                cast(str, payload["node_id"])
                for payload in created_payloads
                if payload.get("semantic_stage") == "plan_verification"
            )
            successor_id = next(
                cast(str, payload["node_id"])
                for payload in created_payloads
                if payload.get("semantic_stage") == "successor_planning"
            )
            scheduled_verifier = await restarted_controller.handle_command(
                run_id,
                duplicate_position,
                "schedule_tick",
                {
                    "base_snapshot_id": "decision-base",
                    "max_grants": 1,
                    "priorities": {verifier_id: 100, successor_id: 1},
                },
            )
            verifier_item = next(
                item
                for item in scheduled_verifier.outbox_items
                if item.kind == "agent_dispatch" and item.payload.get("node_id") == verifier_id
            )
            verifier_projection = await restarted_controller.read_projection(run_id)
            verifier_lease = next(
                item
                for item in leases_view(verifier_projection).values()
                if item.node_id == verifier_id
            )
            verifier_runner = _PlanVerifierRunner("F" if decision_case.endswith("_fail") else "A")

            def build_verifier_runner(
                _runner_type: AgentRunnerType,
                _runner_config: dict[str, Any],
                *,
                run_id: str,
                phase: str,
            ) -> _PlanVerifierRunner:
                del run_id, phase
                return verifier_runner

            verifier_executor = GraphDispatchExecutor(
                sessions,
                restarted_controller,
                StaticGraphAgentFactory(
                    AgentRunnerType.CODEX_SERVER,
                    runner_builder=build_verifier_runner,
                ),
                worktree_path=worktree,
                artifact_store=artifacts,
            )
            await verifier_executor.dispatch(verifier_item)
            await verifier_executor.wait_for_all(timeout_seconds=10)
            verified = await restarted_controller.read_projection(run_id)
            reports = [
                record
                for record in output_record_payloads_view(verified).values()
                if record.record_type == "verification_report"
                and record.producer_node_id == verifier_id
            ]
            assert len(reports) == 1
            expected_outcome = "failed" if decision_case.endswith("_fail") else "passed"
            assert reports[0].outcome == expected_outcome
            assert amendment_id in reports[0].evaluated_record_ids
            assert verifier_lease.execution_id != lease.execution_id
            async with sessions() as session:
                verified_position = await GraphEventStore(session).current_position(run_id)
            scheduled_successor = await restarted_controller.handle_command(
                run_id,
                verified_position,
                "schedule_tick",
                {
                    "base_snapshot_id": "decision-base",
                    "max_grants": 1,
                    "priorities": {successor_id: 100},
                },
            )
            successor_dispatched = any(
                item.kind == "agent_dispatch" and item.payload.get("node_id") == successor_id
                for item in scheduled_successor.outbox_items
            )
            assert successor_dispatched is (expected_outcome == "passed")
            async with sessions() as session:
                cleanup_position = await GraphEventStore(session).current_position(run_id)
            cancelled = await restarted_controller.handle_command(
                run_id,
                cleanup_position,
                "cancel",
                {"trigger": "serialized_amendment_test_cleanup"},
            )
            assert any(event.event_type == "run_lifecycle_changed" for event in cancelled.events)
            cleaned = await restarted_controller.read_projection(run_id)
            assert all(lease.state != "active" for lease in leases_view(cleaned).values())
        else:
            if decision_case == "blocked":
                blocked_gate_id = cast(str, human_gates[0]["node_id"])
                scheduled_after_blocker = await restarted_controller.handle_command(
                    run_id,
                    duplicate_position,
                    "schedule_tick",
                    {
                        "base_snapshot_id": "decision-base",
                        "max_grants": 10,
                        "priorities": {blocked_gate_id: 1000, "planner-plan": 999},
                    },
                )
                forbidden_dispatch_ids = {
                    cast(str, item.payload.get("node_id"))
                    for item in scheduled_after_blocker.outbox_items
                    if item.kind == "agent_dispatch"
                    and item.payload.get("node_id") in {blocked_gate_id, "planner-plan"}
                }
                assert not forbidden_dispatch_ids
                after_blocker_tick = await restarted_controller.read_projection(run_id)
                assert all(
                    lease.state != "active"
                    for lease in leases_view(after_blocker_tick).values()
                    if lease.node_id in {blocked_gate_id, "planner-plan"}
                )
                assert any(
                    record.record_type == "decision_request"
                    and record.producer_node_id == blocked_gate_id
                    for record in output_record_payloads_view(after_blocker_tick).values()
                )
                async with sessions() as session:
                    duplicate_position = await GraphEventStore(session).current_position(run_id)
            cancelled = await restarted_controller.handle_command(
                run_id,
                duplicate_position,
                "cancel",
                {"trigger": "serialized_test_cancellation_after_finalize"},
            )
            assert any(event.event_type == "run_lifecycle_changed" for event in cancelled.events)
            after_cancel = await restarted_controller.read_projection(run_id)
            assert (
                len(
                    [
                        record
                        for record in output_record_payloads_view(after_cancel).values()
                        if record.record_type == "decision_answer"
                    ]
                )
                == 1
            )
    assert outbox
    assert {row.event_id for row in outbox}.issubset({event.event_id for event in events})
    await engine.dispose()
