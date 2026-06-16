"""Outbox-to-agent bridge for graph runtime dispatch."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType, ChecklistStatus
from orchestrator.graph import (
    EventEnvelope,
    GraphProjection,
    PLANNER_OPS,
    initial_projection,
    project_planner_freshness_packet,
)
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
from orchestrator.graph_runtime.horizon_templates import horizon_region_templates
from orchestrator.graph_runtime.outbox import OutboxItem, SideEffectExecutor
from orchestrator.graph_runtime.store import GraphEventStore
from orchestrator.runners import AgentRunner, create_agent_runner
from orchestrator.runners.types import ExecutionContext


def _empty_event_list() -> list[EventEnvelope]:
    return []


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
    graph_projection: GraphProjection = field(default_factory=initial_projection)
    graph_events: list[EventEnvelope] = field(default_factory=_empty_event_list)
    node_role: str = ""


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
        on_agent_usage: Callable[[GraphDispatchContext, Any], Awaitable[None]] | None = None,
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
        self._on_agent_usage = on_agent_usage

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
            graph_patch_submitted = False
            graph_patch_accepted = False
            submitted_callback = False

            async def on_checklist_update(
                _req_id: str,
                _status: ChecklistStatus,
                _note: str | None,
            ) -> None:
                return None

            async def on_submit() -> None:
                nonlocal submitted_callback
                if _requires_graph_patch_before_submit(context) and not graph_patch_submitted:
                    msg = (
                        "planner nodes must call submit_graph_patch before submit; "
                        "submit an accepted graph patch first"
                    )
                    raise ValueError(msg)
                if _requires_graph_patch_before_submit(context) and not graph_patch_accepted:
                    msg = (
                        "planner nodes must have an accepted submit_graph_patch before submit; "
                        "use patch rejection feedback to submit a corrected patch"
                    )
                    raise ValueError(msg)
                await self._submit_callback(context, grades)
                submitted_callback = True

            async def on_submit_graph_patch(patch_payload: dict[str, Any]) -> str:
                nonlocal graph_patch_submitted, graph_patch_accepted
                graph_patch_submitted = True
                feedback = await self._submit_graph_patch_callback(context, patch_payload)
                if _graph_patch_feedback_accepted(feedback):
                    graph_patch_accepted = True
                    if _patch_payload_has_ops(patch_payload):
                        context.node_payload["_accepted_graph_patch_had_ops"] = True
                return feedback

            async def on_grade(req_id: str, grade: str, grade_reason: str | None) -> None:
                grades.append((req_id, grade, grade_reason))

            async def on_output(lines: list[str]) -> None:
                if self._on_agent_output is not None:
                    await self._on_agent_output(context, lines)

            result = await runner.execute(
                self._execution_context(
                    context,
                    graph_patch_callback=(
                        on_submit_graph_patch if _can_submit_graph_patch(context) else None
                    ),
                ),
                on_checklist_update,
                on_submit,
                on_output=on_output,
                on_grade=on_grade if context.node_kind == "verifier" else None,
            )
            # Record this execution's token usage against the run via the shared,
            # carrier-agnostic sink (same path the legacy attempt flow uses). The
            # emitter lives above the import boundary and is injected.
            if self._on_agent_usage is not None:
                await self._on_agent_usage(context, result)
            if not submitted_callback:
                await self._agent_died(context, "agent exited without submit")
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
            node_role=_node_role(node_kind, node_payload),
            node_payload=node_payload,
            requirements=_requirements_for_node(events, node_id),
            worktree_path=self._worktree_path,
            lease_id=str(payload["lease_id"]),
            lease_generation=_payload_int(payload, "generation"),
            execution_id=str(payload["execution_id"]),
            base_snapshot_id=base_snapshot_id,
            dispatch_event_id=item.event_id,
            graph_projection=projection,
            graph_events=list(events),
        )

    def _execution_context(
        self,
        context: GraphDispatchContext,
        graph_patch_callback: Callable[[dict[str, Any]], Awaitable[str]] | None = None,
    ) -> ExecutionContext:
        node = context.node_payload
        prompt = _prompt_for_node(context)
        return ExecutionContext(
            run_id=context.run_id,
            task_id=str(node.get("task_id") or node.get("task_region_id") or context.node_id),
            working_dir=context.worktree_path,
            prompt=prompt,
            requirements=context.requirements,
            step_id=cast(str | None, node.get("step_id")),
            node_id=context.node_id,
            node_kind=context.node_kind,
            node_role=context.node_role,
            graph_patch_callback=graph_patch_callback,
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

    async def _submit_graph_patch_callback(
        self,
        context: GraphDispatchContext,
        patch_payload: dict[str, Any],
    ) -> str:
        observed_position = await self._current_position(context.run_id)
        payload: dict[str, object] = dict(patch_payload)
        payload["run_id"] = context.run_id
        payload["proposed_by_node_id"] = context.node_id
        payload["actor_role"] = context.node_role
        payload["lease_id"] = context.lease_id
        payload["lease_generation"] = context.lease_generation
        payload["execution_id"] = context.execution_id
        payload["base_snapshot_id"] = context.base_snapshot_id
        payload["observed_graph_position"] = observed_position
        payload["idempotency_key"] = (
            f"{context.dispatch_event_id}:{context.execution_id}:submit-graph-patch:"
            f"{payload.get('patch_id', 'unknown')}"
        )

        result = await self._handle_command_retry_stale(
            context.run_id,
            observed_position,
            "submit_patch",
            payload,
        )
        accepted = [event for event in result.events if event.event_type == "graph_patch_accepted"]
        if accepted:
            patch_id = accepted[0].payload.get("patch_id", payload.get("patch_id", "unknown"))
            raw_successors = accepted[0].payload.get("successor_planner_node_ids")
            successors = (
                [item for item in cast(list[object], raw_successors) if isinstance(item, str)]
                if isinstance(raw_successors, list)
                else []
            )
            return (
                f"graph patch {patch_id} accepted; "
                f"successor planner nodes: {json.dumps(successors, sort_keys=True)}"
            )

        rejection = next(
            (
                event
                for event in result.events
                if event.event_type in {"graph_patch_rejected", "command_rejected"}
            ),
            None,
        )
        if rejection is not None:
            reason = rejection.payload.get("reason") or "unknown rejection"
            patch_id = rejection.payload.get("patch_id", payload.get("patch_id", "unknown"))
            return f"graph patch {patch_id} rejected: {reason}"

        return "graph patch command completed without accepted or rejected patch event"

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
    on_agent_usage: Callable[[GraphDispatchContext, Any], Awaitable[None]] | None = None,
) -> tuple[GraphController, GraphDispatchExecutor]:
    """Assemble graph controller and dispatch executor without API imports."""

    controller = GraphController(session_factory, clock, id_gen, auto_dispatch=False)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        StaticGraphAgentFactory(runner_type, runner_config),
        worktree_path=worktree_path,
        on_agent_output=on_agent_output,
        on_agent_usage=on_agent_usage,
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
    if context.node_kind == "planner":
        packet = _planner_packet(context)
        return "\n".join(
            [
                "Planner context packet:",
                json.dumps(packet, sort_keys=True),
                "",
                "Planner mutation contract:",
                "- Your job is to propose future graph structure, not edit repository files.",
                "- Mutate the graph only by calling submit_graph_patch with a patch envelope.",
                "- Use current_graph_position from the packet as base_graph_position.",
                "- Use node_id from the packet as planner identity; dispatch will bind proposer evidence.",
                "- Choose ops only from allowed_patch_operations.",
                "- Use horizon_region_templates for standard discovery, implementation, validation, gap-analysis, corrective-work, and final invariant regions.",
                "- Read frontier, evidence, open_planner_proposals, accepted_planner_patches, and patch_rejections before proposing.",
                "- If dynamic_feature is present, ground generated worker, verifier, gap-analysis, corrective-work, and final invariant regions in those feature inputs.",
                "- Check nodes must include command_definition or command_binding; for dynamic_feature final invariant checks, use command_binding='dynamic_feature_hidden_oracle'.",
                "- For gap planners, follow gap_analysis_contract and prefer corrective_work_region for corrective worker/verifier patches.",
                "- For gap planners, gap_analysis_obligations are blocking; do not submit a no-op patch while any obligation is present.",
                "- Gap planners must call submit_graph_patch even when no corrective mutation is safe; use a no-op patch with ops: [] for no-gap decisions.",
                "- If feedback says the patch is stale, malformed, or rejected, submit a corrected patch.",
                "- Call plain submit only after submit_graph_patch feedback says the patch was accepted.",
                "- Do not append graph events directly and do not create source/test/doc edits from this planner node.",
                "",
                "Allowed patch operations:",
                json.dumps(packet["allowed_patch_operations"], sort_keys=True),
                "Standard horizon region templates:",
                json.dumps(packet["horizon_region_templates"], sort_keys=True),
                "Compact patch examples:",
                json.dumps(packet["patch_examples"], sort_keys=True),
            ]
        )
    return _worker_like_prompt(context)


def _worker_like_prompt(context: GraphDispatchContext) -> str:
    node = context.node_payload
    title = str(node.get("title") or node.get("objective") or context.node_id)
    task_context = node.get("task_context")
    context_lines = [str(task_context)] if isinstance(task_context, str) and task_context else []

    for key in (
        "objective",
        "corrective_requirement",
        "corrective_evidence_required",
        "expected_gap",
        "expected_artifact",
        "feature_spec_path",
        "acceptance_command",
    ):
        value = node.get(key)
        if isinstance(value, str) and value:
            context_lines.append(f"{key}: {value}")

    expected_outputs = node.get("expected_outputs")
    if isinstance(expected_outputs, list) and expected_outputs:
        context_lines.append(f"expected_outputs: {json.dumps(expected_outputs, sort_keys=True)}")

    invariants = node.get("invariants")
    if isinstance(invariants, list) and invariants:
        context_lines.append(f"invariants: {json.dumps(invariants, sort_keys=True)}")

    dynamic_feature = _dynamic_feature_from_context(context)
    if dynamic_feature is not None:
        context_lines.extend(_dynamic_feature_prompt_lines(node, dynamic_feature))

    return "\n".join([title, *context_lines]).strip()


def _dynamic_feature_from_context(context: GraphDispatchContext) -> dict[str, Any] | None:
    node_feature = context.node_payload.get("dynamic_feature")
    if isinstance(node_feature, dict):
        return cast(dict[str, Any], node_feature)

    for event in reversed(context.graph_events):
        if event.event_type != "node_created":
            continue
        snapshot = event.payload.get("snapshot")
        if isinstance(snapshot, dict):
            typed_snapshot = cast(dict[str, Any], snapshot)
            snapshot_feature = typed_snapshot.get("dynamic_feature")
            if isinstance(snapshot_feature, dict):
                return cast(dict[str, Any], snapshot_feature)
        payload_feature = event.payload.get("dynamic_feature")
        if isinstance(payload_feature, dict):
            return cast(dict[str, Any], payload_feature)
    return None


def _dynamic_feature_prompt_lines(
    node: dict[str, Any],
    dynamic_feature: dict[str, Any],
) -> list[str]:
    lines: list[str] = []
    for source_key, prompt_key in (
        ("feature_spec_path", "dynamic_feature_spec_path"),
        ("feature_spec_content", "dynamic_feature_spec_content"),
        ("acceptance_command", "dynamic_acceptance_command"),
    ):
        if isinstance(node.get(source_key), str) and node[source_key]:
            continue
        value = dynamic_feature.get(source_key)
        if isinstance(value, str) and value:
            lines.append(f"{prompt_key}: {value}")

    if node.get("kind") != "worker":
        return lines

    role = node.get("role")
    if role == "fixer" or "corrective" in str(node.get("node_id", "")):
        lines.append(
            "dynamic_worker_instruction: Correct the artifact described by "
            "dynamic_feature_spec_content so the final invariant oracle can pass. "
            "Do not work on unrelated repository slices."
        )
    else:
        lines.append(
            "dynamic_worker_instruction: Create or update only the artifact described by "
            "dynamic_feature_spec_content, then use dynamic_acceptance_command when possible. "
            "Do not work on unrelated repository slices."
        )
    return lines


def _planner_packet(context: GraphDispatchContext) -> dict[str, Any]:
    projection = context.graph_projection
    events = sorted(context.graph_events, key=lambda event: event.position)
    node = context.node_payload
    current_position = max((event.position for event in events), default=0)
    generation_index = projection["planner_generations"].get(context.node_id)

    frontier = _planner_frontier(projection, events, context)
    evidence = _planner_evidence(context, projection, events)
    proposals = _planner_proposals(context, events)

    packet = {
        "run_id": context.run_id,
        "node_id": context.node_id,
        "node_kind": context.node_kind,
        "role": node.get("role"),
        "active_intent": {
            "title": node.get("title", context.node_id),
            "context": node.get("task_context", ""),
            "task_region_id": projection["node_task_regions"].get(context.node_id),
        },
        "current_graph_position": current_position,
        "planner_generation": {
            "index": generation_index,
            "budget": projection["planner_generation_budget"],
        },
        "bound_requirements": list(context.requirements),
        "frontier": frontier,
        "evidence": evidence,
        "freshness": project_planner_freshness_packet(events),
        "open_planner_proposals": proposals["open_proposals"],
        "accepted_planner_patches": proposals["accepted_patches"],
        "patch_rejections": proposals["patch_rejections"],
    }
    dynamic_feature = node.get("dynamic_feature")
    if isinstance(dynamic_feature, dict):
        packet["dynamic_feature"] = _planner_visible_dynamic_feature(
            cast(dict[str, Any], dynamic_feature)
        )
    packet["allowed_patch_operations"] = _planner_allowed_ops_packet()
    packet["horizon_region_templates"] = horizon_region_templates()
    if context.node_role == "gap_planner":
        packet["gap_analysis_contract"] = {
            "inspect": [
                "bound_requirements",
                "accepted_evidence",
                "verifier_check_results",
                "outstanding_failures",
                "stale_or_missing_support_evidence",
                "active_intent",
            ],
            "decisions": [
                "no_gap_no_op_patch",
                "corrective_work_patch",
                "validation_strengthening_placeholder",
                "human_or_policy_escalation_placeholder",
            ],
            "required_patch_before_submit": (
                "submit corrective_work_patch or no_gap_no_op_patch before plain submit"
            ),
            "no_gap_no_op_patch": {
                "ops": [],
                "meaning": "no safe corrective mutation is available from bound evidence",
            },
            "corrective_region": "corrective_work_region",
            "repository_edits": "forbidden",
        }
        packet["gap_analysis_obligations"] = _gap_analysis_obligations(
            context,
            projection,
            events,
        )
    packet["patch_examples"] = _planner_patch_examples(packet, context)
    return packet


def _planner_visible_dynamic_feature(dynamic_feature: dict[str, Any]) -> dict[str, Any]:
    visible = {
        key: value for key, value in dynamic_feature.items() if key != "hidden_oracle_command"
    }
    if dynamic_feature.get("hidden_oracle_command"):
        visible["hidden_oracle_binding"] = "dynamic_feature_hidden_oracle"
    return visible


def _planner_frontier(
    projection: GraphProjection,
    events: list[EventEnvelope],
    context: GraphDispatchContext,
) -> dict[str, list[dict[str, Any]] | list[str]]:
    ready_nodes = sorted(projection["ready_nodes"])
    deferred_reasons = _planner_deferred_reasons(events)

    blocked_nodes: list[dict[str, Any]] = []
    for node_id in sorted(projection["node_states"]):
        node_state = projection["node_states"].get(node_id, "")
        if node_state == "ready":
            continue
        reason = deferred_reasons.get(node_id)
        if reason is None and node_id != context.node_id:
            continue
        if node_state in {"running", "leased", "completed", "failed", "cancelled", "retired"}:
            continue
        blocked_nodes.append(
            {
                "node_id": node_id,
                "state": node_state,
                "reason": reason,
            }
        )

    return {
        "ready_nodes": ready_nodes,
        "blocked_or_deferred_nodes": sorted(
            blocked_nodes,
            key=lambda item: (
                str(item.get("reason", "")),
                str(item.get("node_id", "")),
            ),
        ),
    }


def _planner_deferred_reasons(events: list[EventEnvelope]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for event in events:
        if event.event_type != "node_deferred":
            continue
        node_id = event.payload.get("node_id")
        reason = event.payload.get("reason")
        if isinstance(node_id, str) and isinstance(reason, str):
            reasons[node_id] = reason
    return reasons


def _gap_analysis_obligations(
    context: GraphDispatchContext,
    projection: GraphProjection,
    events: list[EventEnvelope],
) -> list[dict[str, Any]]:
    obligations: list[dict[str, Any]] = []
    terminal_states = {"completed", "failed", "cancelled", "retired"}

    for edge_id, edge in sorted(projection["edges"].items()):
        if edge.get("required") is False:
            continue
        if edge.get("from_node_id") != context.node_id:
            continue
        if edge.get("from_port") != "classified_gap" and edge.get("to_port") != "classified_gap":
            continue
        to_node_id = edge.get("to_node_id")
        to_port = edge.get("to_port")
        if not isinstance(to_node_id, str) or not isinstance(to_port, str):
            continue
        if projection["node_states"].get(to_node_id) in terminal_states:
            continue
        if to_port in projection["input_bindings"].get(to_node_id, {}):
            continue
        obligations.append(
            {
                "kind": "classified_gap_successor_waiting",
                "edge_id": edge_id,
                "to_node_id": to_node_id,
                "to_port": to_port,
                "reason": (
                    "required classified_gap successor is waiting; no-op patch will be "
                    "rejected until this planner classifies a gap or creates corrective work"
                ),
            }
        )

    deferred_reasons = _planner_deferred_reasons(events)
    for node_id, reason in sorted(deferred_reasons.items()):
        if reason != "missing_required_input:verification_evidence":
            continue
        if projection["node_states"].get(node_id) in terminal_states:
            continue
        if projection["node_kinds"].get(node_id) != "check":
            continue
        obligations.append(
            {
                "kind": "final_invariant_waiting_for_verification_evidence",
                "node_id": node_id,
                "reason": (
                    "final invariant is still pending verification_evidence; a weak verifier "
                    "pass is not sufficient if corrective/final invariant work remains"
                ),
            }
        )

    return obligations


def _planner_evidence(
    context: GraphDispatchContext,
    projection: GraphProjection,
    events: list[EventEnvelope],
) -> dict[str, Any]:
    bindings = projection["input_bindings"].get(context.node_id, {})
    output_records: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        payload = event.payload
        record_id = payload.get("record_id")
        if not isinstance(record_id, str):
            continue
        output_records[record_id] = dict(payload)

    bound_records: dict[str, list[dict[str, Any]]] = {}
    for port in sorted(bindings):
        binding = bindings[port]
        raw_record_ids = binding.get("record_ids")
        if not isinstance(raw_record_ids, list):
            continue
        records: list[dict[str, Any]] = []
        for raw_record_id in cast(list[object], raw_record_ids):
            if not isinstance(raw_record_id, str):
                continue

            if raw_record_id in projection["file_state_records"]:
                records.append(
                    {
                        "record_id": raw_record_id,
                        "record_kind": "file_state",
                        "record_payload": _compact_file_state_record(
                            projection["file_state_records"][raw_record_id]
                        ),
                        "status": "accepted",
                    }
                )
                continue

            output_payload = output_records.get(raw_record_id)
            if output_payload is not None:
                records.append(
                    {
                        "record_id": raw_record_id,
                        "record_kind": output_payload.get("record_kind", "output"),
                        "record_payload": output_payload,
                        "status": "accepted",
                    }
                )
                continue

            records.append(
                {
                    "record_id": raw_record_id,
                    "record_kind": None,
                    "status": "missing",
                }
            )

        bound_records[port] = sorted(records, key=lambda record: str(record["record_id"]))

    return {
        "bound_records": bound_records,
        "outstanding_failures": _planner_outstanding_failures(context, projection),
        "session_carryover_record_id": _planner_session_carryover_record(context, projection),
    }


def _compact_file_state_record(record: dict[str, Any]) -> dict[str, Any]:
    tracked = _path_entries(record.get("tracked"))
    untracked = _path_entries(record.get("untracked"))
    ignored = _path_entries(record.get("ignored"))
    rejected_paths = record.get("rejected_paths")
    rejected_path_count = (
        len(cast(list[object], rejected_paths)) if isinstance(rejected_paths, list) else 0
    )

    compact: dict[str, Any] = {
        "snapshot_id": record.get("snapshot_id"),
        "base_snapshot_id": record.get("base_snapshot_id"),
        "producer_node_id": record.get("producer_node_id"),
        "port": record.get("port"),
        "schema": record.get("schema"),
        "verdict": record.get("verdict"),
        "counts": {
            "tracked": len(tracked),
            "untracked": len(untracked),
            "ignored": len(ignored),
            "rejected_paths": rejected_path_count,
        },
        "tracked_paths": _compact_path_entries(tracked),
        "untracked_paths": _compact_path_entries(untracked),
    }
    if isinstance(rejected_paths, list) and rejected_paths:
        compact["rejected_paths"] = [str(path) for path in cast(list[object], rejected_paths)[:10]]
    git = record.get("git")
    if isinstance(git, dict):
        git_data = cast(dict[str, Any], git)
        compact["git"] = {
            "commit_sha": git_data.get("commit_sha"),
            "tree_sha": git_data.get("tree_sha"),
            "no_commit_reason": git_data.get("no_commit_reason"),
        }
    return compact


def _path_entries(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in cast(list[object], value):
        if isinstance(item, dict):
            entries.append(dict(cast(dict[str, Any], item)))
    return entries


def _compact_path_entries(entries: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for entry in entries[:limit]:
        compacted.append(
            {
                "path": entry.get("path"),
                "classification": entry.get("classification"),
                "source": entry.get("source"),
                "rejected": entry.get("rejected"),
            }
        )
    return compacted


def _planner_outstanding_failures(
    context: GraphDispatchContext,
    projection: GraphProjection,
) -> list[dict[str, Any]]:
    task_region_id = projection["node_task_regions"].get(context.node_id)
    failures: list[dict[str, Any]] = []

    for region_id, failure in projection["environment_failures"].items():
        if task_region_id is not None and task_region_id != region_id:
            continue
        entry = dict(failure)
        entry["task_region_id"] = region_id
        failures.append(entry)
    failures.sort(key=lambda item: str(item.get("task_region_id")))
    return failures


def _planner_session_carryover_record(
    context: GraphDispatchContext,
    projection: GraphProjection,
) -> str | None:
    session_id = projection["planner_sessions"].get(context.node_id)
    if not isinstance(session_id, str):
        return None
    carryover = projection["planner_session_carryovers"].get(session_id)
    if carryover is None:
        return None
    return str(carryover)


def _planner_proposals(
    context: GraphDispatchContext,
    events: list[EventEnvelope],
) -> dict[str, list[dict[str, Any]]]:
    open_proposals: list[dict[str, Any]] = []
    accepted_patches: list[dict[str, Any]] = []
    patch_rejections: list[dict[str, Any]] = []

    for event in events:
        payload = event.payload
        if event.event_type in {"graph_patch_proposed", "planner_proposal_opened"}:
            if payload.get("proposed_by_node_id") != context.node_id:
                continue
            open_proposals.append(
                {
                    "patch_id": payload.get("patch_id"),
                    "base_graph_position": payload.get("base_graph_position"),
                    "position": event.position,
                }
            )
            continue

        if event.event_type == "graph_patch_accepted":
            if payload.get("proposed_by_node_id") != context.node_id:
                continue
            accepted_patches.append(
                {
                    "patch_id": payload.get("patch_id"),
                    "base_graph_position": payload.get("base_graph_position"),
                    "position": event.position,
                }
            )
            continue

        if event.event_type != "graph_patch_rejected":
            continue
        if payload.get("proposed_by_node_id") != context.node_id:
            continue
        patch_rejections.append(
            {
                "patch_id": payload.get("patch_id"),
                "reason": payload.get("reason"),
                "position": event.position,
            }
        )

    open_proposals.sort(key=lambda item: str(item.get("patch_id", "")))
    accepted_patches.sort(key=lambda item: str(item.get("patch_id", "")))
    patch_rejections.sort(key=lambda item: str(item.get("patch_id", "")))
    return {
        "open_proposals": open_proposals,
        "accepted_patches": accepted_patches,
        "patch_rejections": patch_rejections,
    }


def _planner_allowed_ops_packet() -> dict[str, list[str]]:
    return {"allowed_ops": sorted(PLANNER_OPS)}


def _planner_patch_examples(
    packet: dict[str, Any],
    context: GraphDispatchContext,
) -> list[dict[str, Any]]:
    base_position = int(packet.get("current_graph_position", 0))
    examples: list[dict[str, Any]] = []

    if {"create_node", "create_edge"}.issubset(PLANNER_OPS):
        region_id = (
            "corrective_work_region" if context.node_role == "gap_planner" else "region-example"
        )
        examples.append(
            {
                "purpose": (
                    "create_corrective_work_region"
                    if context.node_role == "gap_planner"
                    else "create_worker_verifier_region"
                ),
                "patch_id": "example-worker-verifier-region",
                "proposed_by_node_id": context.node_id,
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "worker-example",
                            "kind": "worker",
                            "role": "builder",
                            "state": "planned",
                            "task_region_id": region_id,
                            "attempt_number": 1,
                            "candidate_id": "candidate-example",
                        },
                    },
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "verifier-example",
                            "kind": "verifier",
                            "role": "verifier",
                            "state": "planned",
                            "task_region_id": region_id,
                            "candidate_id": "candidate-example",
                            "rubric": ["candidate satisfies the bound requirements"],
                        },
                    },
                    {
                        "op": "create_edge",
                        "edge_id": "example-worker-to-verifier",
                        "from_node_id": "worker-example",
                        "from_port": "candidate",
                        "to_node_id": "verifier-example",
                        "to_port": "candidate_under_test",
                        "required": True,
                        "accepted_record_selector": {"record_kinds": ["candidate"]},
                    },
                ],
            }
        )

    if context.node_role == "gap_planner":
        examples.append(
            {
                "purpose": "no_gap_no_op_patch",
                "patch_id": "example-gap-no-op",
                "proposed_by_node_id": context.node_id,
                "base_graph_position": base_position,
                "ops": [],
            }
        )
        return sorted(examples, key=lambda example: str(example.get("patch_id", "")))

    if "create_node" in PLANNER_OPS:
        examples.append(
            {
                "purpose": "create_successor_planner",
                "patch_id": "example-successor-planner",
                "proposed_by_node_id": context.node_id,
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "planner-successor-example",
                            "kind": "planner",
                            "role": "planner",
                            "state": "planned",
                            "task_region_id": "region-example",
                        },
                    },
                ],
            }
        )
        examples.append(
            {
                "purpose": "create_gap_planner",
                "patch_id": "example-gap-planner",
                "proposed_by_node_id": context.node_id,
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "planner-gap-example",
                            "kind": "planner",
                            "role": "gap_planner",
                            "state": "planned",
                            "task_region_id": "region-example",
                        },
                    },
                    {
                        "op": "create_edge",
                        "edge_id": "example-verifier-to-gap",
                        "from_node_id": "verifier-example",
                        "from_port": "verification_report",
                        "to_node_id": "planner-gap-example",
                        "to_port": "verification_evidence",
                        "required": True,
                        "accepted_record_selector": {
                            "record_kinds": ["verification", "check_result"]
                        },
                    },
                ],
            }
        )
        examples.append(
            {
                "purpose": "create_invariant_check",
                "patch_id": "example-invariant-check",
                "proposed_by_node_id": context.node_id,
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "invariant-check-example",
                            "kind": "check",
                            "role": "invariant_gate",
                            "state": "planned",
                            "task_region_id": "region-example",
                            "command_binding": "dynamic_feature_hidden_oracle",
                        },
                    },
                    {
                        "op": "create_edge",
                        "edge_id": "example-verifier-to-invariant",
                        "from_node_id": "verifier-example",
                        "from_port": "verification_report",
                        "to_node_id": "invariant-check-example",
                        "to_port": "verification_evidence",
                        "required": True,
                        "accepted_record_selector": {
                            "record_kinds": ["verification", "check_result"]
                        },
                    },
                ],
            }
        )
        examples.append(
            {
                "purpose": "no_safe_mutation_termination",
                "patch_id": "example-no-safe-mutation",
                "proposed_by_node_id": context.node_id,
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "planner-no-safe-mutation-record",
                            "kind": "planner",
                            "role": "planner",
                            "state": "planned",
                            "task_region_id": "region-example",
                            "decision": "no safe graph mutation available from current evidence",
                        },
                    }
                ],
            }
        )

    if "set_resource_claims" in PLANNER_OPS:
        examples.append(
            {
                "purpose": "set_resource_claims",
                "patch_id": "example-set-resource-claims",
                "proposed_by_node_id": context.node_id,
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "set_resource_claims",
                        "node_id": "worker-example",
                        "resource_claims": [{"mode": "read", "scope": "repo"}],
                    }
                ],
            }
        )

    if "set_allowed_actions" in PLANNER_OPS:
        examples.append(
            {
                "purpose": "set_allowed_actions",
                "patch_id": "example-set-allowed-actions",
                "proposed_by_node_id": context.node_id,
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "set_allowed_actions",
                        "node_id": "worker-example",
                        "allowed_actions": ["submit", "view"],
                    }
                ],
            }
        )

    return sorted(examples, key=lambda example: str(example.get("patch_id", "")))


def _node_role(node_kind: str, node_payload: dict[str, Any]) -> str:
    role = node_payload.get("role")
    if isinstance(role, str) and role:
        return role
    if node_kind == "planner":
        return "planner"
    return ""


def _can_submit_graph_patch(context: GraphDispatchContext) -> bool:
    return context.node_kind == "planner" and context.node_role in {"planner", "gap_planner"}


def _requires_graph_patch_before_submit(context: GraphDispatchContext) -> bool:
    return _can_submit_graph_patch(context)


def _graph_patch_feedback_accepted(feedback: str) -> bool:
    return " accepted" in feedback and " rejected" not in feedback


def _patch_payload_has_ops(patch_payload: dict[str, Any]) -> bool:
    raw_patch = patch_payload.get("patch")
    payload = cast(dict[str, Any], raw_patch) if isinstance(raw_patch, dict) else patch_payload
    ops = payload.get("ops")
    return isinstance(ops, list) and bool(cast(list[object], ops))


def _output_records_for_submit(
    context: GraphDispatchContext,
    grades: list[tuple[str, str, str | None]],
) -> list[dict[str, Any]]:
    node = context.node_payload
    candidate_id = str(node.get("candidate_id") or f"candidate-{context.node_id}")
    task_region_id = str(node.get("task_region_id") or context.node_id)
    attempt_number = int(node.get("attempt_number", 0))
    if context.node_kind == "planner":
        role = context.node_role
        if role == "gap_planner" and node.get("_accepted_graph_patch_had_ops") is True:
            gap_value = {
                "milestone_kind": "gap_analysis",
                "classification": "corrective_work_required",
                "source": "accepted_gap_planner_patch",
                "task_region_id": task_region_id,
                "attempt_number": attempt_number,
            }
            return [
                {
                    "record_id": f"gap-plan-{context.execution_id}",
                    "record_kind": "output",
                    "producer_node_id": context.node_id,
                    "port": "gap_plan",
                    "schema": "GapClassification",
                    "value": gap_value,
                },
                {
                    "record_id": f"gap-classification-{context.execution_id}",
                    "record_kind": "output",
                    "producer_node_id": context.node_id,
                    "port": "gap_classification",
                    "schema": "GapClassification",
                    "value": gap_value,
                },
                {
                    "record_id": f"classified-gap-{context.execution_id}",
                    "record_kind": "output",
                    "producer_node_id": context.node_id,
                    "port": "classified_gap",
                    "schema": "GapClassification",
                    "value": gap_value,
                },
            ]
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
