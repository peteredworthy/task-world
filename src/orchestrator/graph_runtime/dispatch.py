"""Outbox-to-agent bridge for graph runtime dispatch."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType, ChecklistStatus
from orchestrator.graph import EventEnvelope, GraphProjection
from orchestrator.graph_runtime.controller import GraphController, rebuild_projection
from orchestrator.graph_runtime.errors import CompromisedFileStateError, StaleProjectionError
from orchestrator.graph_runtime.file_state import (
    apply_cleanup_requested,
    capture_file_state_boundary,
)
from orchestrator.graph_runtime.gatekeeper import (
    ResidueClassifier,
    metadata_from_file_state_record,
    policy_with_pattern_library,
)
from orchestrator.graph_runtime.outbox import OutboxItem, SideEffectExecutor
from orchestrator.graph_runtime.store import GraphEventStore
from orchestrator.runners import AgentRunner, create_agent_runner
from orchestrator.runners.types import ExecutionContext


@dataclass(frozen=True)
class GraphDispatchContext:
    """Graph facts mapped into an existing runner execution context.

    Mapping decisions:
    - ``node_payload`` is the compiled executable node payload. It provides
      task title/context, role, candidate identity, tools, and verifier rubric.
    - ``requirements`` are reconstructed from requirement nodes bound to the
      executable node by compiler-created input bindings.
    - ``worktree_path`` is injected by runtime construction because filesystem
      location is run setup state, not a pure graph fact in slice 2.3.
    - Lease identity stays outside ``ExecutionContext`` and is copied into the
      graph callback envelope when the runner submits.
    """

    run_id: str
    node_id: str
    node_kind: str
    node_payload: dict[str, Any]
    requirements: list[str]
    worktree_path: str
    lease_id: str
    lease_generation: int
    execution_id: str
    base_snapshot_id: str
    dispatch_event_id: str


class GraphAgentFactory(Protocol):
    def create_runner(self, context: GraphDispatchContext) -> AgentRunner: ...


class GraphProcessRegistry(Protocol):
    def is_running(self, execution_id: str) -> bool: ...


class StaticGraphAgentFactory:
    """Production-oriented adapter around the existing runner registry."""

    def __init__(
        self,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
    ) -> None:
        self._runner_type = runner_type
        self._runner_config = dict(runner_config or {})

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        phase = "verifying" if context.node_kind == "verifier" else "building"
        return create_agent_runner(
            self._runner_type,
            self._runner_config,
            run_id=context.run_id,
            phase=phase,
        )


class GraphDispatchExecutor(SideEffectExecutor):
    """Start graph-leased agent executions from durable outbox items."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        controller: GraphController,
        agent_factory: GraphAgentFactory,
        *,
        worktree_path: str | Path,
        running_executions: dict[str, asyncio.Task[None]] | None = None,
        process_registry: GraphProcessRegistry | None = None,
        residue_classifier: ResidueClassifier | None = None,
        max_gatekeeper_items_per_boundary: int = 20,
        on_agent_output: Callable[[GraphDispatchContext, list[str]], Awaitable[None]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._controller = controller
        self._agent_factory = agent_factory
        self._worktree_path = str(worktree_path)
        self._running = running_executions if running_executions is not None else {}
        self._process_registry = process_registry
        self._residue_classifier = residue_classifier
        self._max_gatekeeper_items_per_boundary = max_gatekeeper_items_per_boundary
        self._on_agent_output = on_agent_output

    async def dispatch(self, item: OutboxItem) -> None:
        if item.kind == "snapshot_cleanup":
            await self._dispatch_snapshot_cleanup(item)
            return
        if item.kind != "agent_dispatch":
            return

        context = await self._build_dispatch_context(item)
        existing = self._running.get(context.execution_id)
        if existing is not None and not existing.done():
            return

        runner = self._agent_factory.create_runner(context)
        task = asyncio.create_task(self._run_agent(context, runner))
        task.add_done_callback(_consume_task_exception)
        self._running[context.execution_id] = task

    def is_running(self, execution_id: str) -> bool:
        task = self._running.get(execution_id)
        if task is not None and not task.done():
            return True
        return self._process_registry is not None and self._process_registry.is_running(
            execution_id
        )

    async def wait_for_all(self) -> None:
        tasks = list(self._running.values())
        if tasks:
            await asyncio.gather(*tasks)

    def cancel_all(self) -> None:
        for task in self._running.values():
            task.cancel()

    async def _run_agent(self, context: GraphDispatchContext, runner: AgentRunner) -> None:
        try:
            await self._acknowledge_start(context)
            grades: list[tuple[str, str, str | None]] = []

            async def on_checklist_update(
                _req_id: str,
                _status: ChecklistStatus,
                _note: str | None,
            ) -> None:
                return None

            async def on_submit() -> None:
                await self._submit_callback(context, grades)

            async def on_grade(req_id: str, grade: str, grade_reason: str | None) -> None:
                grades.append((req_id, grade, grade_reason))

            async def on_output(lines: list[str]) -> None:
                if self._on_agent_output is not None:
                    await self._on_agent_output(context, lines)

            await runner.execute(
                self._execution_context(context),
                on_checklist_update,
                on_submit,
                on_output=on_output,
                on_grade=on_grade if context.node_kind == "verifier" else None,
            )
        except Exception as exc:
            await self._agent_died(context, str(exc))

    async def _build_dispatch_context(self, item: OutboxItem) -> GraphDispatchContext:
        payload = item.payload
        node_id = str(payload["node_id"])
        async with self._session_factory() as session:
            events = await GraphEventStore(session).read_run(item.run_id)

        projection = rebuild_projection(events)
        _guard_no_pending_compromised_file_state_bindings(projection, node_id)
        node_payload = _node_payload(events, node_id)
        node_kind = str(node_payload.get("kind", "worker"))
        base_snapshot_id = payload.get("base_snapshot_id")
        if not isinstance(base_snapshot_id, str) or not base_snapshot_id:
            msg = "agent dispatch payload missing base_snapshot_id"
            raise ValueError(msg)
        return GraphDispatchContext(
            run_id=item.run_id,
            node_id=node_id,
            node_kind=node_kind,
            node_payload=node_payload,
            requirements=_requirements_for_node(events, node_id),
            worktree_path=self._worktree_path,
            lease_id=str(payload["lease_id"]),
            lease_generation=_payload_int(payload, "generation"),
            execution_id=str(payload["execution_id"]),
            base_snapshot_id=base_snapshot_id,
            dispatch_event_id=item.event_id,
        )

    def _execution_context(self, context: GraphDispatchContext) -> ExecutionContext:
        node = context.node_payload
        prompt = _prompt_for_node(context)
        return ExecutionContext(
            run_id=context.run_id,
            task_id=str(node.get("task_id") or node.get("task_region_id") or context.node_id),
            working_dir=context.worktree_path,
            prompt=prompt,
            requirements=context.requirements,
            step_id=cast(str | None, node.get("step_id")),
            available_tools=cast(list[str] | None, node.get("available_tools")),
            mcp_servers=cast(Any, node.get("mcp_servers")),
            work_mode=_work_mode(node.get("work_mode")),
        )

    async def _acknowledge_start(self, context: GraphDispatchContext) -> None:
        await self._controller.handle_command(
            context.run_id,
            await self._current_position(context.run_id),
            "acknowledge_start",
            {
                "node_id": context.node_id,
                "lease_id": context.lease_id,
                "lease_generation": context.lease_generation,
                "execution_id": context.execution_id,
            },
        )

    async def _submit_callback(
        self,
        context: GraphDispatchContext,
        grades: list[tuple[str, str, str | None]],
    ) -> None:
        observed_position = await self._current_position(context.run_id)
        output_records = _output_records_for_submit(context, grades)
        events_before_boundary = await self._events(context.run_id)
        boundary = capture_file_state_boundary(
            worktree_path=context.worktree_path,
            run_id=context.run_id,
            node_id=context.node_id,
            execution_id=context.execution_id,
            base_snapshot_id=context.base_snapshot_id,
            policy=policy_with_pattern_library(events_before_boundary),
        )
        if boundary.output_record is not None:
            output_records.append(boundary.output_record)
        if boundary.rejection_record is not None:
            payload: dict[str, object] = {
                "payload_hash": _payload_hash([boundary.rejection_record]),
                "output_records": [],
                "file_state_rejected": boundary.rejection_record,
            }
            result = await self._controller.handle_command(
                context.run_id,
                observed_position,
                "submit_callback",
                {
                    "node_id": context.node_id,
                    "execution_id": context.execution_id,
                    "lease_id": context.lease_id,
                    "lease_generation": context.lease_generation,
                    "base_snapshot_id": context.base_snapshot_id,
                    "observed_graph_position": observed_position,
                    "idempotency_key": (
                        f"{context.dispatch_event_id}:{context.execution_id}:file-state-rejected"
                    ),
                    "payload_hash": payload["payload_hash"],
                    "payload": payload,
                    "complete_node": False,
                },
            )
            if any(event.event_type == "file_state_rejected" for event in result.events):
                # A rejected boundary means the managed runner exited without an
                # accepted file-state record. Reuse the existing process-death
                # recovery path so evidence remains durable and the lease is
                # revoked before the same node becomes retryable.
                await self._agent_died(context, "file_state_rejected_boundary")
            return
        payload = {
            "payload_hash": _payload_hash(output_records),
            "output_records": output_records,
        }
        payload_data: dict[str, object] = {
            "node_id": context.node_id,
            "execution_id": context.execution_id,
            "lease_id": context.lease_id,
            "lease_generation": context.lease_generation,
            "base_snapshot_id": context.base_snapshot_id,
            "observed_graph_position": observed_position,
            "idempotency_key": f"{context.dispatch_event_id}:{context.execution_id}:submit",
            "payload_hash": payload["payload_hash"],
            "payload": payload,
        }
        result = await self._handle_command_retry_stale(
            context.run_id,
            observed_position,
            "submit_callback",
            payload_data,
        )
        await self._record_gatekeeper_verdicts(context, result.projection_position, result.events)

    async def _agent_died(self, context: GraphDispatchContext, reason: str) -> None:
        await self._controller.handle_command(
            context.run_id,
            await self._current_position(context.run_id),
            "agent_died",
            {
                "lease_id": context.lease_id,
                "execution_id": context.execution_id,
                "reason": reason or "runtime_process_died",
            },
        )

    async def _handle_command_retry_stale(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object],
    ) -> Any:
        try:
            return await self._controller.handle_command(
                run_id,
                expected_position,
                command_type,
                payload,
            )
        except StaleProjectionError:
            current_position = await self._current_position(run_id)
            retry_payload = dict(payload)
            if "observed_graph_position" in retry_payload:
                retry_payload["observed_graph_position"] = current_position
            return await self._controller.handle_command(
                run_id,
                current_position,
                command_type,
                retry_payload,
            )

    async def _current_position(self, run_id: str) -> int:
        async with self._session_factory() as session:
            return await GraphEventStore(session).current_position(run_id)

    async def _events(self, run_id: str) -> list[EventEnvelope]:
        async with self._session_factory() as session:
            return await GraphEventStore(session).read_run(run_id)

    async def _record_gatekeeper_verdicts(
        self,
        context: GraphDispatchContext,
        projection_position: int,
        accepted_events: list[EventEnvelope],
    ) -> None:
        if self._residue_classifier is None:
            return
        current_position = projection_position
        for event in accepted_events:
            if event.event_type != "file_state_accepted":
                continue
            metadata = metadata_from_file_state_record(
                event.payload,
                max_items=self._max_gatekeeper_items_per_boundary,
            )
            if not metadata:
                continue
            verdicts = self._residue_classifier.classify(metadata)
            if not verdicts:
                continue
            result = await self._controller.handle_command(
                context.run_id,
                current_position,
                "record_gatekeeper_verdicts",
                {
                    "file_state_record_id": event.payload.get("record_id"),
                    "execution_id": context.execution_id,
                    "consult_id": f"{context.execution_id}:{event.payload.get('record_id')}",
                    "verdicts": [verdict.to_payload() for verdict in verdicts],
                },
            )
            current_position = result.projection_position

    async def _dispatch_snapshot_cleanup(self, item: OutboxItem) -> None:
        """Apply a cleanup side effect and record its durable result.

        ``snapshot_cleanup`` outbox rows are at-least-once. A retry may observe
        that ``cleanup_applied`` was already committed after an earlier
        filesystem cleanup; in that case the side effect intent is complete.
        """
        events = await self._events(item.run_id)
        cleanup_id = str(item.payload.get("cleanup_id", ""))
        if _cleanup_applied_exists(events, cleanup_id):
            return
        cleanup_event = _cleanup_requested_event(events, cleanup_id)
        if cleanup_event is None:
            msg = f"unknown cleanup_requested: {cleanup_id}"
            raise ValueError(msg)
        record_id = cleanup_event.payload.get("file_state_record_id")
        if not isinstance(record_id, str):
            msg = f"cleanup_requested missing file_state_record_id: {cleanup_id}"
            raise ValueError(msg)
        projection = rebuild_projection(events)
        compromised_record = projection["file_state_records"].get(record_id)
        if compromised_record is None:
            msg = f"unknown cleanup file_state record: {record_id}"
            raise ValueError(msg)

        cleanup = apply_cleanup_requested(
            worktree_path=self._worktree_path,
            cleanup_request=cleanup_event.payload,
            compromised_record=compromised_record,
        )
        result = await self._controller.handle_command(
            item.run_id,
            await self._current_position(item.run_id),
            "record_cleanup_applied",
            {
                "cleanup_id": cleanup.cleanup_id,
                "superseding_file_state_record": cleanup.superseding_file_state_record,
                "deleted_snapshot_ref": cleanup.deleted_snapshot_ref,
            },
        )
        if _rejected_cleanup_already_applied(result.events, cleanup_id):
            return
        rejected = next(
            (
                event
                for event in result.events
                if event.event_type == "command_rejected"
                and event.payload.get("command_type") == "record_cleanup_applied"
            ),
            None,
        )
        if rejected is not None:
            msg = str(rejected.payload.get("reason") or "record_cleanup_applied rejected")
            raise ValueError(msg)


async def reconcile_runtime(
    controller: GraphController,
    dispatcher: GraphDispatchExecutor,
    report: object,
) -> None:
    """Reconcile recovered active leases with in-process runtime liveness."""

    for lease in [
        *cast(Any, getattr(report, "awaiting_start_ack", [])),
        *cast(Any, getattr(report, "awaiting_callback", [])),
    ]:
        execution_id = str(lease.get("execution_id", ""))
        if execution_id and dispatcher.is_running(execution_id):
            continue
        run_id = str(lease["run_id"])
        await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "agent_died",
            {
                "lease_id": str(lease["lease_id"]),
                "execution_id": execution_id,
                "reason": "runtime_process_missing_after_restart",
            },
        )


def build_graph_runtime(
    session_factory: async_sessionmaker[AsyncSession],
    clock: Any,
    id_gen: Any,
    *,
    worktree_path: str | Path,
    runner_type: AgentRunnerType,
    runner_config: dict[str, Any] | None = None,
    on_agent_output: Callable[[GraphDispatchContext, list[str]], Awaitable[None]] | None = None,
) -> tuple[GraphController, GraphDispatchExecutor]:
    """Assemble graph controller and dispatch executor without API imports."""

    controller = GraphController(session_factory, clock, id_gen, auto_dispatch=False)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        StaticGraphAgentFactory(runner_type, runner_config),
        worktree_path=worktree_path,
        on_agent_output=on_agent_output,
    )
    return controller, executor


def _node_payload(events: list[EventEnvelope], node_id: str) -> dict[str, Any]:
    for event in events:
        if event.event_type != "node_created":
            continue
        if event.payload.get("node_id") == node_id:
            return dict(event.payload)
    return {"node_id": node_id}


def _requirements_for_node(events: list[EventEnvelope], node_id: str) -> list[str]:
    projection = rebuild_projection(events)
    _guard_no_pending_compromised_file_state_bindings(projection, node_id)
    bound_record_ids: set[str] = set()
    for port, binding in projection["input_bindings"].get(node_id, {}).items():
        if not port.startswith("requirement_"):
            continue
        record_ids = binding.get("record_ids")
        if isinstance(record_ids, list):
            bound_record_ids.update(str(record_id) for record_id in cast(list[object], record_ids))

    requirements: list[str] = []
    for event in events:
        if event.event_type != "node_created":
            continue
        requirement_node_id = event.payload.get("node_id")
        if not isinstance(requirement_node_id, str) or requirement_node_id not in bound_record_ids:
            continue
        requirement = event.payload.get("requirement")
        if isinstance(requirement, dict):
            req = cast(dict[str, Any], requirement)
            requirements.append(f"{req.get('id', requirement_node_id)}: {req.get('desc', '')}")
    return requirements


def _guard_no_pending_compromised_file_state_bindings(
    projection: GraphProjection,
    node_id: str,
) -> None:
    """Refuse to build runtime bindings from a cleanup-pending snapshot.

    Slice 2.6+ will add richer file-state restore/consumption paths. Until
    then this is the single runtime binding read boundary: if a downstream
    node is bound to a file-state record that the projection has marked as
    compromised and still awaiting cleanup, dispatch must stop before a runner
    can consume that snapshot identity.
    """
    for binding in projection["input_bindings"].get(node_id, {}).values():
        record_ids = binding.get("record_ids")
        if not isinstance(record_ids, list):
            continue
        for raw_record_id in cast(list[object], record_ids):
            if not isinstance(raw_record_id, str):
                continue
            record = projection["file_state_records"].get(raw_record_id)
            if record is None:
                continue
            if record.get("compromised") is True and record.get("superseded_pending") is True:
                cleanup_id = record.get("cleanup_id")
                msg = (
                    "refusing to bind compromised file-state record "
                    f"{raw_record_id} for node {node_id}"
                )
                if isinstance(cleanup_id, str) and cleanup_id:
                    msg = f"{msg}; cleanup pending: {cleanup_id}"
                raise CompromisedFileStateError(msg)


def _cleanup_requested_event(
    events: list[EventEnvelope],
    cleanup_id: str,
) -> EventEnvelope | None:
    for event in events:
        if event.event_type != "cleanup_requested":
            continue
        if event.payload.get("cleanup_id") == cleanup_id:
            return event
    return None


def _cleanup_applied_exists(events: list[EventEnvelope], cleanup_id: str) -> bool:
    return any(
        event.event_type == "cleanup_applied" and event.payload.get("cleanup_id") == cleanup_id
        for event in events
    )


def _rejected_cleanup_already_applied(
    events: list[EventEnvelope],
    cleanup_id: str,
) -> bool:
    return any(
        event.event_type == "command_rejected"
        and event.payload.get("command_type") == "record_cleanup_applied"
        and event.payload.get("reason") == f"cleanup already applied: {cleanup_id}"
        for event in events
    )


def _prompt_for_node(context: GraphDispatchContext) -> str:
    node = context.node_payload
    if context.node_kind == "verifier":
        rubric = node.get("rubric")
        return "\n".join(
            [
                f"Verify task region {node.get('task_region_id', context.node_id)}.",
                f"Candidate: {node.get('candidate_id', '')}",
                f"Rubric: {json.dumps(rubric or [], sort_keys=True)}",
            ]
        )
    return "\n".join(
        [
            str(node.get("title", context.node_id)),
            str(node.get("task_context", "")),
        ]
    ).strip()


def _output_records_for_submit(
    context: GraphDispatchContext,
    grades: list[tuple[str, str, str | None]],
) -> list[dict[str, Any]]:
    node = context.node_payload
    candidate_id = str(node.get("candidate_id") or f"candidate-{context.node_id}")
    task_region_id = str(node.get("task_region_id") or context.node_id)
    attempt_number = int(node.get("attempt_number", 0))
    if context.node_kind == "planner":
        role = str(node.get("role") or "")
        if role == "fan_out_reader":
            return [
                {
                    "record_id": candidate_id,
                    "record_kind": "output",
                    "producer_node_id": context.node_id,
                    "port": "reader_output",
                    "schema": "FanOutInputs",
                    "candidate_id": candidate_id,
                    "task_region_id": task_region_id,
                    "attempt_number": attempt_number,
                    "value": {"summary": "fan-out inputs submitted by graph runner"},
                }
            ]
        if role == "fan_out_join":
            return [
                {
                    "record_id": candidate_id,
                    "record_kind": "output",
                    "producer_node_id": context.node_id,
                    "port": "fan_out_inputs",
                    "schema": "FanOutJoinedInputs",
                    "candidate_id": candidate_id,
                    "task_region_id": task_region_id,
                    "attempt_number": attempt_number,
                    "value": {"summary": "fan-out join submitted by graph runner"},
                }
            ]
        return []
    if context.node_kind == "check":
        command_definition = node.get("command_definition")
        return [
            {
                "record_id": f"check-{context.execution_id}",
                "record_kind": "output",
                "producer_node_id": context.node_id,
                "port": "check_result",
                "schema": "CheckResult",
                "candidate_id": candidate_id,
                "task_region_id": task_region_id,
                "attempt_number": attempt_number,
                "value": {
                    "status": "passed",
                    "exit_code": 0,
                    "command": command_definition,
                },
            }
        ]
    if context.node_kind == "verifier":
        verdict = "passed" if _grades_pass(grades) else "failed"
        return [
            {
                "record_id": f"verification-{context.execution_id}",
                "record_kind": "verification",
                "producer_node_id": context.node_id,
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": candidate_id,
                "task_region_id": task_region_id,
                "verdict": verdict,
                "value": {
                    "grades": [
                        {"requirement_id": req_id, "grade": grade, "reason": reason}
                        for req_id, grade, reason in grades
                    ]
                },
            }
        ]
    return [
        {
            "record_id": candidate_id,
            "record_kind": "output",
            "producer_node_id": context.node_id,
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "candidate_id": candidate_id,
            "task_region_id": task_region_id,
            "attempt_number": attempt_number,
            "value": {"summary": "submitted by graph runner"},
        }
    ]


def _grades_pass(grades: list[tuple[str, str, str | None]]) -> bool:
    if not grades:
        return True
    passing = {"a", "pass", "passed", "ok", "yes"}
    return all(grade.strip().lower() in passing for _, grade, _ in grades)


def _payload_hash(output_records: list[dict[str, Any]]) -> str:
    encoded = json.dumps(output_records, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _payload_int(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    msg = f"payload field {key} must be int-compatible"
    raise TypeError(msg)


def _work_mode(value: object) -> Literal["implementation", "oversight"]:
    return "oversight" if value == "oversight" else "implementation"


def _consume_task_exception(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    task.exception()
