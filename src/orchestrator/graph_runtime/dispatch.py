"""Outbox-to-agent bridge for graph runtime dispatch."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType, ChecklistStatus
from orchestrator.graph import (
    CheckResultRecord,
    DEFAULT_NODE_CONTRACTS,
    EventEnvelope,
    GapClassificationRecord,
    GraphProjection,
    PLANNER_OPS,
    RequirementRecord,
    initial_projection,
    project_planner_freshness_packet,
    resolve_check_command_definition,
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

MAX_GRAPH_PROMPT_CHARS = 60_000
MAX_GRAPH_JSON_SECTION_CHARS = 36_000
MAX_GRAPH_PROMPT_FIELD_CHARS = 8_000
MAX_CHECK_OUTPUT_CHARS = 20_000
DEFAULT_CHECK_TIMEOUT_SECONDS = 300
MAX_STALE_COMMAND_RETRIES = 5
SNAPSHOT_REF_PATTERN = re.compile(r"^refs/orchestrator/snapshots/[0-9a-f]{32}$")


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


@dataclass(frozen=True)
class CheckExecutionWorktree:
    path: str
    snapshot_id: str | None = None
    snapshot_ref: str | None = None
    temporary_path: str | None = None


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

        if context.node_kind == "check":
            task = asyncio.create_task(self._run_check(context))
        elif context.node_kind == "join":
            task = asyncio.create_task(self._run_join(context))
        elif context.node_kind == "final_gate":
            task = asyncio.create_task(self._run_final_gate(context))
        else:
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
            await self._record_start_heartbeat(context)
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

    async def _run_check(self, context: GraphDispatchContext) -> None:
        try:
            await self._acknowledge_start(context)
            record = await _execute_check_command(context)
            await self._submit_check_result(context, record)
        except Exception as exc:
            await self._agent_died(context, str(exc))

    async def _run_final_gate(self, context: GraphDispatchContext) -> None:
        try:
            await self._acknowledge_start(context)
            observed_position = await self._current_position(context.run_id)
            await self._handle_command_retry_stale(
                context.run_id,
                observed_position,
                "evaluate_final_gate",
                {
                    "node_id": context.node_id,
                    "lease_id": context.lease_id,
                    "lease_generation": context.lease_generation,
                },
            )
        except Exception as exc:
            await self._agent_died(context, str(exc))

    async def _run_join(self, context: GraphDispatchContext) -> None:
        try:
            await self._acknowledge_start(context)
            observed_position = await self._current_position(context.run_id)
            await self._handle_command_retry_stale(
                context.run_id,
                observed_position,
                "evaluate_join",
                {
                    "node_id": context.node_id,
                    "lease_id": context.lease_id,
                    "lease_generation": context.lease_generation,
                },
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
            available_tools=_available_tools_for_context(context),
            mcp_servers=cast(Any, node.get("mcp_servers")),
            work_mode=_work_mode(node.get("work_mode")),
        )

    async def _acknowledge_start(self, context: GraphDispatchContext) -> None:
        await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "acknowledge_start",
            {
                "node_id": context.node_id,
                "lease_id": context.lease_id,
                "lease_generation": context.lease_generation,
                "execution_id": context.execution_id,
                "prompt_summary": _prompt_summary_for_node(context),
            },
        )

    async def _record_start_heartbeat(self, context: GraphDispatchContext) -> None:
        result = await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "record_heartbeat",
            {
                "node_id": context.node_id,
                "lease_id": context.lease_id,
                "generation": context.lease_generation,
                "ttl_seconds": 300,
            },
        )
        rejection = next(
            (
                event
                for event in result.events
                if event.event_type == "command_rejected"
                and event.payload.get("command_type") == "record_heartbeat"
            ),
            None,
        )
        if rejection is not None:
            reason = rejection.payload.get("reason") or "record_heartbeat rejected"
            raise ValueError(str(reason))

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
        conflict_reason = _callback_conflict_reason(result.events)
        if conflict_reason is not None:
            raise ValueError(f"submit callback rejected: {conflict_reason}")
        await self._record_gatekeeper_verdicts(context, result.projection_position, result.events)

    async def _submit_check_result(
        self,
        context: GraphDispatchContext,
        record: dict[str, Any],
    ) -> None:
        observed_position = await self._current_position(context.run_id)
        payload = {
            "payload_hash": _payload_hash([record]),
            "output_records": [record],
        }
        await self._handle_command_retry_stale(
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
                "idempotency_key": f"{context.dispatch_event_id}:{context.execution_id}:check",
                "payload_hash": payload["payload_hash"],
                "payload": payload,
            },
        )

    async def _submit_graph_patch_callback(
        self,
        context: GraphDispatchContext,
        patch_payload: dict[str, Any],
    ) -> str:
        if not _can_submit_graph_patch(context):
            msg = f"node {context.node_id} is not authorized to submit graph patches"
            raise ValueError(msg)
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
        payload: dict[str, object] = {
            "lease_id": context.lease_id,
            "execution_id": context.execution_id,
            "reason": reason or "runtime_process_died",
        }
        max_attempts = context.node_payload.get("max_attempts")
        if isinstance(max_attempts, int):
            payload["max_attempts"] = max_attempts
        await self._handle_command_retry_stale(
            context.run_id,
            await self._current_position(context.run_id),
            "agent_died",
            payload,
        )

    async def _handle_command_retry_stale(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object],
    ) -> Any:
        current_position = expected_position
        retry_payload = dict(payload)
        for attempt in range(MAX_STALE_COMMAND_RETRIES + 1):
            try:
                return await self._controller.handle_command(
                    run_id,
                    current_position,
                    command_type,
                    retry_payload,
                )
            except StaleProjectionError:
                if attempt >= MAX_STALE_COMMAND_RETRIES:
                    raise
                current_position = await self._current_position(run_id)
                if "observed_graph_position" in retry_payload:
                    retry_payload["observed_graph_position"] = current_position
        raise StaleProjectionError(f"stale graph projection for run {run_id}: retry loop exhausted")

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
        lease_id = str(lease["lease_id"])
        for attempt in range(MAX_STALE_COMMAND_RETRIES):
            if not await _recovered_lease_still_active(
                controller,
                run_id,
                lease_id,
                execution_id,
            ):
                break
            try:
                await controller.handle_command(
                    run_id,
                    await controller.current_position(run_id),
                    "agent_died",
                    {
                        "lease_id": lease_id,
                        "execution_id": execution_id,
                        "reason": "runtime_process_missing_after_restart",
                    },
                )
                break
            except StaleProjectionError:
                if attempt == MAX_STALE_COMMAND_RETRIES - 1:
                    raise
                continue


async def _recovered_lease_still_active(
    controller: GraphController,
    run_id: str,
    lease_id: str,
    execution_id: str,
) -> bool:
    projection = await controller.read_projection(run_id)
    lease = projection["leases"].get(lease_id)
    if lease is None or lease.get("state") != "active":
        return False
    lease_execution_id = lease.get("execution_id")
    return not isinstance(lease_execution_id, str) or lease_execution_id == execution_id


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
        requirement_record = event.payload.get("requirement_record")
        if isinstance(requirement_record, dict):
            try:
                record = RequirementRecord.model_validate(requirement_record)
            except ValueError:
                continue
            requirements.append(f"{record.value.id}: {record.value.text}")
            continue
        requirement = event.payload.get("requirement")
        if isinstance(requirement, dict):
            req = cast(dict[str, Any], requirement)
            requirements.append(f"{req.get('id', requirement_node_id)}: {req.get('desc', '')}")
    if requirements:
        return requirements

    dynamic_feature = _dynamic_feature_from_events(events)
    if dynamic_feature is not None:
        requirement = _dynamic_feature_acceptance_requirement(dynamic_feature)
        if requirement is not None:
            return [requirement]
    return requirements


def _dynamic_feature_from_events(events: list[EventEnvelope]) -> dict[str, Any] | None:
    for event in reversed(events):
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


def _dynamic_feature_acceptance_requirement(
    dynamic_feature: dict[str, Any],
) -> str | None:
    content = dynamic_feature.get("feature_spec_content")
    command = dynamic_feature.get("acceptance_command")
    parts: list[str] = []
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    if isinstance(command, str) and command.strip():
        parts.append(f"Acceptance command: {command.strip()}")
    if not parts:
        return None
    return f"dynamic_feature_acceptance: {' '.join(parts)}"


def _callback_conflict_reason(events: list[EventEnvelope]) -> str | None:
    conflict = next(
        (
            event
            for event in events
            if event.event_type in {"callback_rejected_conflict", "command_rejected"}
        ),
        None,
    )
    if conflict is None:
        return None
    reason = conflict.payload.get("reason")
    if isinstance(reason, str) and reason:
        return reason
    return "unknown callback conflict"


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


def _bounded_prompt(prompt: str) -> str:
    if len(prompt) <= MAX_GRAPH_PROMPT_CHARS:
        return prompt
    omitted = len(prompt) - MAX_GRAPH_PROMPT_CHARS
    suffix = f"\n[graph prompt truncated; omitted_chars={omitted}]"
    return f"{prompt[: MAX_GRAPH_PROMPT_CHARS - len(suffix)]}{suffix}"


def _bounded_json(value: object, *, max_chars: int = MAX_GRAPH_JSON_SECTION_CHARS) -> str:
    encoded = json.dumps(value, sort_keys=True)
    if len(encoded) <= max_chars:
        return encoded
    preview_chars = max(0, max_chars - 160)
    return json.dumps(
        {
            "truncated": True,
            "original_chars": len(encoded),
            "preview": encoded[:preview_chars],
        },
        sort_keys=True,
    )


def _bounded_text(value: object, *, max_chars: int = MAX_GRAPH_PROMPT_FIELD_CHARS) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    suffix = f"\n[truncated; omitted_chars={omitted}]"
    return f"{text[: max_chars - len(suffix)]}{suffix}"


def _verifier_packet(context: GraphDispatchContext) -> dict[str, Any]:
    node = context.node_payload
    return {
        "node_id": context.node_id,
        "task_region_id": node.get("task_region_id", context.node_id),
        "candidate_id": node.get("candidate_id"),
        "requirements": list(context.requirements),
        "rubric": node.get("rubric") or [],
        "bound_records": _planner_evidence(
            context,
            context.graph_projection,
            context.graph_events,
        )["bound_records"],
        "evaluated_record_citations": _evaluated_record_citations(context),
        "required_report_schema": {
            "record_kind": "verification",
            "port": "verification_report",
            "schema": "VerificationReport",
            "required_fields": [
                "candidate_id",
                "verdict",
                "value.grades",
                "evidence.evaluated_record_ids",
            ],
            "verdict_values": ["passed", "failed"],
        },
    }


def _summarizer_packet(context: GraphDispatchContext) -> dict[str, Any]:
    node = context.node_payload
    return {
        "node_id": context.node_id,
        "task_region_id": node.get("task_region_id", context.node_id),
        "source_records": _planner_evidence(
            context,
            context.graph_projection,
            context.graph_events,
        )["bound_records"].get("source_records", []),
        "required_summary_schema": {
            "record_kind": "output",
            "record_type": "analysis_summary",
            "port": "analysis_summary",
            "schema": "AnalysisSummary",
            "required_fields": [
                "summary",
                "source_record_ids",
                "lossiness",
                "omitted_details",
            ],
            "lossiness_values": ["lossless", "lossy"],
        },
    }


def _prompt_for_node(context: GraphDispatchContext) -> str:
    node = context.node_payload
    if context.node_kind == "verifier":
        packet = _verifier_packet(context)
        rubric = node.get("rubric")
        return _bounded_prompt(
            "\n".join(
                [
                    f"Verify task region {node.get('task_region_id', context.node_id)}.",
                    f"Candidate: {node.get('candidate_id', '')}",
                    f"Rubric: {_bounded_json(rubric or [])}",
                    "",
                    "Verifier context packet:",
                    _bounded_json(packet),
                ]
            )
        )
    if context.node_kind == "summarizer":
        packet = _summarizer_packet(context)
        return _bounded_prompt(
            "\n".join(
                [
                    f"Summarize source records for {node.get('task_region_id', context.node_id)}.",
                    "",
                    "Summarizer context packet:",
                    _bounded_json(packet),
                ]
            )
        )
    if context.node_kind == "planner":
        packet = _planner_packet(context)
        return _bounded_prompt(
            "\n".join(
                [
                    "Planner context packet:",
                    _bounded_json(packet),
                    "",
                    "Planner mutation contract:",
                    "- Your job is to propose future graph structure, not edit repository files.",
                    "- Prefer planner-facing graph macros; low-level ops are the internal expansion format.",
                    "- Mutate the graph only through submit_graph_patch or macro-backed patch envelopes.",
                    "- Use current_graph_position from the packet as base_graph_position.",
                    "- Use node_id from the packet as planner identity; dispatch will bind proposer evidence.",
                    "- When using raw fallback ops, choose only from allowed_patch_operations.",
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
                    _bounded_json(packet["allowed_patch_operations"]),
                    "Standard horizon region templates:",
                    _bounded_json(packet["horizon_region_templates"]),
                    "Compact patch examples:",
                    _bounded_json(packet["patch_examples"]),
                ]
            )
        )
    return _worker_like_prompt(context)


def _prompt_summary_for_node(context: GraphDispatchContext) -> dict[str, Any]:
    packet = _packet_for_prompt_summary(context)
    summary: dict[str, Any] = {
        "node_id": context.node_id,
        "node_kind": context.node_kind,
        "node_role": context.node_role,
        "packet_type": _packet_type_for_context(context),
        "packet_keys": sorted(packet),
        "prompt_sections": _prompt_sections_for_context(context),
        "available_tools": _available_tools_for_context(context) or [],
        "lease": {
            "lease_id": context.lease_id,
            "generation": context.lease_generation,
            "execution_id": context.execution_id,
            "base_snapshot_id": context.base_snapshot_id,
        },
        "input_ports": _prompt_summary_input_ports(context),
        "bound_records": _prompt_summary_bound_records(context),
    }
    task_region_id = context.node_payload.get("task_region_id")
    if isinstance(task_region_id, str):
        summary["task_region_id"] = task_region_id
    command_definition = context.node_payload.get("command_definition")
    if isinstance(command_definition, dict):
        summary["command_definition"] = dict(cast(dict[str, Any], command_definition))
    if "required_report_schema" in packet:
        summary["required_report_schema"] = packet["required_report_schema"]
    if "required_summary_schema" in packet:
        summary["required_summary_schema"] = packet["required_summary_schema"]
    if "gap_analysis_contract" in packet:
        summary["gap_analysis_contract"] = packet["gap_analysis_contract"]
    return summary


def _packet_for_prompt_summary(context: GraphDispatchContext) -> dict[str, Any]:
    if context.node_kind == "verifier":
        return _verifier_packet(context)
    if context.node_kind == "summarizer":
        return _summarizer_packet(context)
    if context.node_kind == "planner":
        return _planner_packet(context)
    if context.node_kind == "check":
        return {
            "node_id": context.node_id,
            "task_region_id": context.node_payload.get("task_region_id", context.node_id),
            "command_definition": resolve_check_command_definition(
                context.node_payload,
                context.graph_events,
            ),
            "bound_records": _planner_evidence(
                context,
                context.graph_projection,
                context.graph_events,
            )["bound_records"],
        }
    return {
        "node_id": context.node_id,
        "task_region_id": context.node_payload.get("task_region_id", context.node_id),
        "worker_authority": _worker_authority_packet(context),
    }


def _packet_type_for_context(context: GraphDispatchContext) -> str:
    if context.node_kind == "planner" and context.node_role == "gap_planner":
        return "gap_planner"
    return context.node_kind


def _prompt_sections_for_context(context: GraphDispatchContext) -> list[str]:
    if context.node_kind == "verifier":
        return ["rubric", "verifier_context_packet"]
    if context.node_kind == "summarizer":
        return ["summarizer_context_packet"]
    if context.node_kind == "planner":
        sections = [
            "planner_context_packet",
            "planner_mutation_contract",
            "allowed_patch_operations",
            "horizon_region_templates",
            "patch_examples",
        ]
        if context.node_role == "gap_planner":
            sections.append("gap_analysis_contract")
        return sections
    if context.node_kind == "check":
        return ["check_command", "bound_evidence"]
    return ["worker_instruction", "worker_authority"]


def _prompt_summary_input_ports(context: GraphDispatchContext) -> dict[str, list[str]]:
    bindings = context.graph_projection["input_bindings"].get(context.node_id, {})
    input_ports: dict[str, list[str]] = {}
    for port, binding in sorted(bindings.items()):
        record_ids = binding.get("record_ids")
        if isinstance(record_ids, list):
            input_ports[port] = [
                record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)
            ]
    return input_ports


def _prompt_summary_bound_records(context: GraphDispatchContext) -> dict[str, list[dict[str, Any]]]:
    evidence = _planner_evidence(context, context.graph_projection, context.graph_events)
    compact: dict[str, list[dict[str, Any]]] = {}
    for port, records in evidence["bound_records"].items():
        compact[port] = [_compact_prompt_bound_record(record) for record in records[:10]]
    return compact


def _compact_prompt_bound_record(record: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: record[key]
        for key in ("record_id", "record_kind", "hydration_policy", "status")
        if key in record
    }
    payload = record.get("record_payload")
    if isinstance(payload, dict):
        typed_payload = cast(dict[str, Any], payload)
        for key in ("record_type", "schema", "producer_node_id", "port"):
            value = typed_payload.get(key)
            if isinstance(value, str):
                compact[key] = value
    reference = record.get("record_reference")
    if isinstance(reference, dict):
        compact["record_reference"] = dict(cast(dict[str, Any], reference))
    summary = record.get("record_summary")
    if isinstance(summary, dict):
        compact["record_summary"] = dict(cast(dict[str, Any], summary))
    if record.get("omitted_from_prompt") is True:
        compact["omitted_from_prompt"] = True
    return compact


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
            context_lines.append(f"{key}: {_bounded_text(value)}")

    expected_outputs = node.get("expected_outputs")
    if isinstance(expected_outputs, list) and expected_outputs:
        context_lines.append(
            f"expected_outputs: {_bounded_json(cast(list[Any], expected_outputs))}"
        )

    invariants = node.get("invariants")
    if isinstance(invariants, list) and invariants:
        context_lines.append(f"invariants: {_bounded_json(cast(list[Any], invariants))}")

    authority_packet = _worker_authority_packet(context)
    if authority_packet:
        context_lines.append(f"worker_authority: {_bounded_json(authority_packet)}")

    dynamic_feature = _dynamic_feature_from_context(context)
    if dynamic_feature is not None:
        context_lines.extend(_dynamic_feature_prompt_lines(node, dynamic_feature))

    return _bounded_prompt("\n".join([_bounded_text(title), *context_lines]).strip())


def _worker_authority_packet(context: GraphDispatchContext) -> dict[str, Any]:
    node = context.node_payload
    authority = node.get("authority")
    authority_payload = cast(dict[str, Any], authority) if isinstance(authority, dict) else {}
    allowed_actions = authority_payload.get("allowed_actions")
    resource_claims = authority_payload.get("resource_claims")
    available_tools = _available_tools_for_context(context)

    packet: dict[str, Any] = {
        "node_id": context.node_id,
        "lease_id": context.lease_id,
        "lease_generation": context.lease_generation,
        "worktree_path": context.worktree_path,
    }
    if isinstance(allowed_actions, list):
        packet["allowed_actions"] = [
            action for action in cast(list[Any], allowed_actions) if isinstance(action, str)
        ]
    if isinstance(resource_claims, list):
        packet["resource_claims"] = [
            claim for claim in cast(list[Any], resource_claims) if isinstance(claim, dict)
        ]
    if available_tools is not None:
        packet["available_tools"] = list(available_tools)
    return packet


def _available_tools_for_context(context: GraphDispatchContext) -> list[str] | None:
    explicit_tools = context.node_payload.get("available_tools")
    if isinstance(explicit_tools, list):
        return [tool for tool in cast(list[Any], explicit_tools) if isinstance(tool, str)]
    contract_tools = sorted(
        DEFAULT_NODE_CONTRACTS.allowed_tools_for(context.node_kind, context.node_role)
    )
    return contract_tools or None


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
            lines.append(f"{prompt_key}: {_bounded_text(value)}")

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
        hydration_policy = _hydration_policy_for_binding(binding, projection)
        records: list[dict[str, Any]] = []
        for raw_record_id in cast(list[object], raw_record_ids):
            if not isinstance(raw_record_id, str):
                continue

            if raw_record_id in projection["file_state_records"]:
                records.append(
                    _hydrated_bound_record(
                        record_id=raw_record_id,
                        record_kind="file_state",
                        record_payload=_compact_file_state_record(
                            projection["file_state_records"][raw_record_id]
                        ),
                        hydration_policy=hydration_policy,
                    )
                )
                continue

            output_payload = output_records.get(raw_record_id)
            if output_payload is not None:
                records.append(
                    _hydrated_bound_record(
                        record_id=raw_record_id,
                        record_kind=str(output_payload.get("record_kind", "output")),
                        record_payload=output_payload,
                        hydration_policy=hydration_policy,
                    )
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


def _hydration_policy_for_binding(
    binding: dict[str, Any],
    projection: GraphProjection,
) -> str:
    edge_id = binding.get("edge_id")
    if not isinstance(edge_id, str):
        return "structured_json"
    edge = projection["edges"].get(edge_id)
    if not isinstance(edge, dict):
        return "structured_json"
    policy = edge.get("prompt_hydration_policy")
    if isinstance(policy, str) and policy in {
        "inline_summary",
        "structured_json",
        "artifact_reference",
        "tool_only",
    }:
        return policy
    return "structured_json"


def _hydrated_bound_record(
    *,
    record_id: str,
    record_kind: str,
    record_payload: dict[str, Any],
    hydration_policy: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_id": record_id,
        "record_kind": record_kind,
        "hydration_policy": hydration_policy,
        "status": "accepted",
    }
    if hydration_policy == "tool_only":
        record["omitted_from_prompt"] = True
        return record
    if hydration_policy == "artifact_reference":
        record["record_reference"] = _artifact_reference_payload(record_payload)
        return record
    if hydration_policy == "inline_summary":
        record["record_summary"] = _inline_record_summary(record_payload)
        return record
    record["record_payload"] = record_payload
    return record


def _artifact_reference_payload(record_payload: dict[str, Any]) -> dict[str, Any]:
    value = record_payload.get("value")
    typed_value = cast(dict[str, Any], value) if isinstance(value, dict) else {}
    reference: dict[str, Any] = {
        "record_id": record_payload.get("record_id"),
        "record_type": record_payload.get("record_type"),
        "schema": record_payload.get("schema"),
        "producer_node_id": record_payload.get("producer_node_id"),
        "producer_port": record_payload.get("producer_port") or record_payload.get("port"),
    }
    for key in ("artifact_id", "artifact_type", "uri", "summary"):
        value_field = typed_value.get(key)
        if isinstance(value_field, str) and value_field:
            reference[key] = value_field
    return {key: value for key, value in reference.items() if value is not None}


def _inline_record_summary(record_payload: dict[str, Any]) -> dict[str, Any]:
    value = record_payload.get("value")
    typed_value = cast(dict[str, Any], value) if isinstance(value, dict) else {}
    summary = typed_value.get("summary") or typed_value.get("text") or record_payload.get("summary")
    inline: dict[str, Any] = {
        "record_id": record_payload.get("record_id"),
        "record_type": record_payload.get("record_type"),
        "schema": record_payload.get("schema"),
    }
    if isinstance(summary, str) and summary:
        inline["summary"] = _bounded_text(summary, max_chars=MAX_GRAPH_PROMPT_FIELD_CHARS)
    for key in ("status", "classification", "verdict", "candidate_id"):
        value_field = record_payload.get(key) or typed_value.get(key)
        if isinstance(value_field, str) and value_field:
            inline[key] = value_field
    return {key: value for key, value in inline.items() if value is not None}


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
    return "submit_graph_patch" in DEFAULT_NODE_CONTRACTS.allowed_tools_for(
        context.node_kind, context.node_role
    )


def _requires_graph_patch_before_submit(context: GraphDispatchContext) -> bool:
    return _can_submit_graph_patch(context)


def _graph_patch_feedback_accepted(feedback: str) -> bool:
    return " accepted" in feedback and " rejected" not in feedback


def _patch_payload_has_ops(patch_payload: dict[str, Any]) -> bool:
    raw_patch = patch_payload.get("patch")
    payload = cast(dict[str, Any], raw_patch) if isinstance(raw_patch, dict) else patch_payload
    ops = payload.get("ops")
    if isinstance(ops, list) and bool(cast(list[object], ops)):
        return True
    macro_invocations = payload.get("macro_invocations")
    return isinstance(macro_invocations, list) and bool(cast(list[object], macro_invocations))


def _evaluated_record_citations(context: GraphDispatchContext) -> dict[str, list[str]]:
    candidate_record_ids = _bound_record_ids_for_ports(
        context,
        ("candidate_under_test", "candidate"),
    )
    file_state_record_ids = _bound_record_ids_for_ports(
        context,
        ("file_state", "accepted_file_state"),
    )
    evidence_record_ids = _bound_record_ids_for_ports(
        context,
        ("verification_evidence", "verification_report", "verifier_check_results"),
    )
    for record in _record_payloads_for_ids(context.graph_events, candidate_record_ids):
        file_state_record_ids.extend(_citation_record_ids(record, "file_state_record_ids"))
    for record in _record_payloads_for_ids(context.graph_events, evidence_record_ids):
        candidate_record_ids.extend(_citation_record_ids(record, "candidate_record_ids"))
        file_state_record_ids.extend(_citation_record_ids(record, "file_state_record_ids"))
    if not file_state_record_ids:
        file_state_record_ids.extend(_file_state_record_ids_for_task_region(context))
    citations: dict[str, list[str]] = {}
    unique_candidate_record_ids = _unique_record_ids(candidate_record_ids)
    unique_file_state_record_ids = _unique_record_ids(file_state_record_ids)
    if unique_candidate_record_ids:
        citations["candidate_record_ids"] = unique_candidate_record_ids
    if unique_file_state_record_ids:
        citations["file_state_record_ids"] = unique_file_state_record_ids
    evaluated_record_ids = _unique_record_ids(
        [*evidence_record_ids, *unique_candidate_record_ids, *unique_file_state_record_ids]
    )
    if evaluated_record_ids:
        citations["evaluated_record_ids"] = evaluated_record_ids
    return citations


def _record_payloads_for_ids(
    events: list[EventEnvelope],
    record_ids: list[str],
) -> list[dict[str, Any]]:
    wanted = set(record_ids)
    records: list[dict[str, Any]] = []
    for event in events:
        if event.event_type not in {"output_record_accepted", "file_state_accepted"}:
            continue
        record_id = event.payload.get("record_id")
        if isinstance(record_id, str) and record_id in wanted:
            records.append(dict(event.payload))
    return records


def _citation_record_ids(record: dict[str, Any], field: str) -> list[str]:
    for source in (record, record.get("value"), record.get("provenance"), record.get("evidence")):
        if not isinstance(source, dict):
            continue
        raw_ids = cast(dict[str, Any], source).get(field)
        if not isinstance(raw_ids, list):
            continue
        record_ids = [
            record_id for record_id in cast(list[Any], raw_ids) if isinstance(record_id, str)
        ]
        if record_ids:
            return record_ids
    return []


def _file_state_record_ids_for_task_region(context: GraphDispatchContext) -> list[str]:
    task_region_id = context.node_payload.get("task_region_id")
    if not isinstance(task_region_id, str):
        return []
    output: list[str] = []
    for record_id, record in context.graph_projection["file_state_records"].items():
        record_region_id = record.get("task_region_id")
        if not isinstance(record_region_id, str):
            producer_node_id = record.get("producer_node_id")
            if isinstance(producer_node_id, str):
                record_region_id = context.graph_projection["node_task_regions"].get(
                    producer_node_id
                )
        if record_region_id != task_region_id:
            continue
        if record.get("verdict") in {"rejected", "failed"}:
            continue
        output.append(record_id)
    return _unique_record_ids(output)


def _bound_record_ids_for_ports(
    context: GraphDispatchContext,
    ports: tuple[str, ...],
) -> list[str]:
    bindings = context.graph_projection["input_bindings"].get(context.node_id, {})
    output: list[str] = []
    for port in ports:
        binding = bindings.get(port)
        if binding is None:
            continue
        record_ids = binding.get("record_ids")
        if not isinstance(record_ids, list):
            continue
        output.extend(
            record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)
        )
    return _unique_record_ids(output)


def _unique_record_ids(record_ids: list[str]) -> list[str]:
    output: list[str] = []
    for record_id in record_ids:
        if record_id not in output:
            output.append(record_id)
    return output


def _add_evaluated_record_citations(
    record: dict[str, Any],
    citations: dict[str, list[str]],
    *,
    evidence: bool = False,
    value: bool = False,
) -> dict[str, Any]:
    if not citations:
        return record
    output = dict(record)
    for key, record_ids in citations.items():
        output.setdefault(key, list(record_ids))
    candidate_ids = citations.get("candidate_record_ids")
    if candidate_ids is not None and len(candidate_ids) == 1:
        output.setdefault("candidate_record_id", candidate_ids[0])
    _merge_record_citations(output, "provenance", citations)
    if evidence:
        _merge_record_citations(output, "evidence", citations)
    if value:
        _merge_record_citations(output, "value", citations)
    return output


def _merge_record_citations(
    record: dict[str, Any],
    field: str,
    citations: dict[str, list[str]],
) -> None:
    existing = record.get(field)
    if existing is None:
        record[field] = {key: list(value) for key, value in citations.items()}
        return
    if not isinstance(existing, dict):
        return
    merged = dict(cast(dict[str, Any], existing))
    for key, value in citations.items():
        merged.setdefault(key, list(value))
    record[field] = merged


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
                _gap_classification_record(
                    f"gap-plan-{context.execution_id}",
                    context.node_id,
                    "gap_plan",
                    gap_value,
                ),
                _gap_classification_record(
                    f"gap-classification-{context.execution_id}",
                    context.node_id,
                    "gap_classification",
                    gap_value,
                ),
                _gap_classification_record(
                    f"classified-gap-{context.execution_id}",
                    context.node_id,
                    "classified_gap",
                    gap_value,
                ),
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
        return []
    if context.node_kind == "verifier":
        verdict = "passed" if _grades_pass(grades) else "failed"
        citations = _evaluated_record_citations(context)
        return [
            _add_evaluated_record_citations(
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
                },
                citations,
                evidence=True,
            )
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
        },
        *_artifact_reference_records_for_submit(context, candidate_id),
    ]


def _artifact_reference_records_for_submit(
    context: GraphDispatchContext,
    candidate_id: str,
) -> list[dict[str, Any]]:
    artifacts = context.node_payload.get("artifacts")
    if not isinstance(artifacts, list):
        return []
    output: list[dict[str, Any]] = []
    for index, raw_artifact in enumerate(cast(list[Any], artifacts)):
        if not isinstance(raw_artifact, dict):
            continue
        artifact = cast(dict[str, Any], raw_artifact)
        raw_path = artifact.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        artifact_id = str(artifact.get("id") or raw_path)
        summary = artifact.get("summary") or artifact.get("description")
        output.append(
            {
                "record_id": f"artifact-reference-{context.execution_id}-{index}",
                "record_kind": "graph_record",
                "record_type": "artifact_reference",
                "producer_node_id": context.node_id,
                "port": "artifact_reference",
                "schema": "ArtifactReference",
                "value": {
                    "artifact_id": artifact_id,
                    "artifact_type": "run_output",
                    "uri": raw_path,
                    "summary": str(summary) if summary is not None else None,
                    "source_record_ids": [candidate_id],
                },
            }
        )
    return output


def _gap_classification_record(
    record_id: str,
    producer_node_id: str,
    port: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    return GapClassificationRecord.model_validate(
        {
            "record_id": record_id,
            "record_kind": "output",
            "record_type": port,
            "producer_node_id": producer_node_id,
            "port": port,
            "schema": "GapClassification",
            "value": value,
        }
    ).model_dump(mode="json")


def _grades_pass(grades: list[tuple[str, str, str | None]]) -> bool:
    if not grades:
        return True
    passing = {"a", "pass", "passed", "ok", "yes"}
    return all(grade.strip().lower() in passing for _, grade, _ in grades)


async def _execute_check_command(context: GraphDispatchContext) -> dict[str, Any]:
    command_definition = _check_command_definition(context.node_payload, context.graph_events)
    invocation, command_text, shell = _check_invocation(command_definition)
    timeout_seconds = _check_timeout_seconds(command_definition)
    execution_worktree = await asyncio.to_thread(_prepare_check_execution_worktree, context)
    started = perf_counter()
    stdout = ""
    stderr = ""
    timed_out = False
    exit_code: int | None
    proc: asyncio.subprocess.Process | None = None

    try:
        if shell:
            proc = await asyncio.create_subprocess_shell(
                cast(str, invocation),
                cwd=execution_worktree.path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            argv = cast(list[str], invocation)
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=execution_worktree.path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
        exit_code = proc.returncode
        stdout = _decode_output(stdout_bytes)
        stderr = _decode_output(stderr_bytes)
    except TimeoutError:
        timed_out = True
        exit_code = None
        if proc is not None:
            proc.kill()
            await proc.wait()
    finally:
        await asyncio.to_thread(_cleanup_check_execution_worktree, context, execution_worktree)

    duration_ms = int((perf_counter() - started) * 1000)
    status = "timeout" if timed_out else "passed" if exit_code == 0 else "failed"
    candidate_id = str(context.node_payload.get("candidate_id") or f"candidate-{context.node_id}")
    task_region_id = str(context.node_payload.get("task_region_id") or context.node_id)
    attempt_number = int(context.node_payload.get("attempt_number", 0))
    command_id = str(command_definition.get("id") or context.node_id)
    value = {
        "status": status,
        "classification": status,
        "command_id": command_id,
        "command_binding": command_definition.get("command_binding")
        or context.node_payload.get("command_binding"),
        "command_text": command_text,
        "command": command_definition,
        "worktree_path": context.worktree_path,
        "source_worktree_path": context.worktree_path,
        "execution_worktree_path": execution_worktree.path,
        "base_snapshot_id": context.base_snapshot_id,
        "execution_snapshot_id": execution_worktree.snapshot_id,
        "execution_snapshot_ref": execution_worktree.snapshot_ref,
        "execution_id": context.execution_id,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": _trim_check_output(stdout),
        "stderr": _trim_check_output(stderr),
        "stdout_truncated": len(stdout) > MAX_CHECK_OUTPUT_CHARS,
        "stderr_truncated": len(stderr) > MAX_CHECK_OUTPUT_CHARS,
        "timeout_seconds": timeout_seconds,
        "environment_policy": {
            "cwd": execution_worktree.path,
            "env": "inherited",
            "shell": shell,
            "source_worktree_path": context.worktree_path,
            "snapshot_id": execution_worktree.snapshot_id,
        },
    }
    record_payload = _add_evaluated_record_citations(
        {
            "record_id": f"check-{context.execution_id}",
            "record_kind": "output",
            "record_type": "check_result",
            "producer_node_id": context.node_id,
            "port": "check_result",
            "schema": "CheckResult",
            "candidate_id": candidate_id,
            "task_region_id": task_region_id,
            "attempt_number": attempt_number,
            "value": value,
        },
        _evaluated_record_citations(context),
        value=True,
    )
    return CheckResultRecord.model_validate(record_payload).model_dump(mode="json")


def _prepare_check_execution_worktree(context: GraphDispatchContext) -> CheckExecutionWorktree:
    snapshot = _bound_file_state_snapshot(context)
    if snapshot is None:
        return CheckExecutionWorktree(path=context.worktree_path)

    snapshot_id, snapshot_ref = snapshot
    if not SNAPSHOT_REF_PATTERN.fullmatch(snapshot_ref):
        msg = f"invalid file-state snapshot ref for check execution: {snapshot_ref}"
        raise ValueError(msg)

    tempdir = tempfile.mkdtemp(prefix="orchestrator-check-snapshot-")
    result = subprocess.run(
        ["git", "worktree", "add", "--detach", tempdir, snapshot_ref],
        cwd=context.worktree_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        shutil.rmtree(tempdir, ignore_errors=True)
        msg = f"failed to create check snapshot worktree: {result.stderr.strip()}"
        raise ValueError(msg)
    return CheckExecutionWorktree(
        path=tempdir,
        snapshot_id=snapshot_id,
        snapshot_ref=snapshot_ref,
        temporary_path=tempdir,
    )


def _cleanup_check_execution_worktree(
    context: GraphDispatchContext,
    execution_worktree: CheckExecutionWorktree,
) -> None:
    tempdir = execution_worktree.temporary_path
    if tempdir is None:
        return
    subprocess.run(
        ["git", "worktree", "remove", "--force", tempdir],
        cwd=context.worktree_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    shutil.rmtree(tempdir, ignore_errors=True)


def _bound_file_state_snapshot(context: GraphDispatchContext) -> tuple[str, str] | None:
    citations = _evaluated_record_citations(context)
    file_state_record_ids = citations.get("file_state_record_ids", [])
    if not file_state_record_ids:
        return None
    wanted = set(file_state_record_ids)
    for event in context.graph_events:
        if event.event_type not in {"output_record_accepted", "file_state_accepted"}:
            continue
        record_id = event.payload.get("record_id")
        if not isinstance(record_id, str) or record_id not in wanted:
            continue
        snapshot_id = event.payload.get("snapshot_id")
        git = event.payload.get("git")
        snapshot_ref = cast(dict[str, Any], git).get("ref") if isinstance(git, dict) else None
        if isinstance(snapshot_id, str) and isinstance(snapshot_ref, str):
            return snapshot_id, snapshot_ref
    return None


def _check_command_definition(
    node: dict[str, Any],
    events: list[EventEnvelope],
) -> dict[str, Any]:
    command_definition = resolve_check_command_definition(node, events)
    if command_definition is None:
        msg = "check node missing command_definition"
        raise ValueError(msg)
    return command_definition


def _check_invocation(command_definition: dict[str, Any]) -> tuple[str | list[str], str, bool]:
    raw_argv = command_definition.get("argv")
    if isinstance(raw_argv, list):
        raw_parts = cast(list[Any], raw_argv)
        typed_argv = [part for part in raw_parts if isinstance(part, str)]
        if len(typed_argv) != len(raw_parts):
            typed_argv = []
        if typed_argv:
            return typed_argv, " ".join(typed_argv), False

    command = command_definition.get("cmd")
    if not isinstance(command, str):
        command = command_definition.get("command")
    if isinstance(command, str) and command.strip():
        return command, command, True

    msg = "check command_definition requires non-empty argv or cmd"
    raise ValueError(msg)


def _check_timeout_seconds(command_definition: dict[str, Any]) -> float:
    raw_timeout = command_definition.get("timeout_seconds")
    if isinstance(raw_timeout, int | float) and not isinstance(raw_timeout, bool):
        if raw_timeout > 0:
            return float(raw_timeout)
    return float(DEFAULT_CHECK_TIMEOUT_SECONDS)


def _decode_output(output: bytes | None) -> str:
    if output is None:
        return ""
    return output.decode("utf-8", errors="replace")


def _trim_check_output(output: str) -> str:
    if len(output) <= MAX_CHECK_OUTPUT_CHARS:
        return output
    return output[-MAX_CHECK_OUTPUT_CHARS:]


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
