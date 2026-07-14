"""Outbox-to-agent bridge for graph runtime dispatch."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Protocol, cast

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType, ChecklistStatus
from orchestrator.db import is_retriable_sqlite_write_conflict
from orchestrator.graph import (
    CallbackDuplicateReturnedPayload,
    CallbackRejectedPayload,
    CheckResultRecord,
    CleanupAppliedPayload,
    CleanupRequestedPayload,
    CommandRejectedPayload,
    GraphPatchAcceptedPayload,
    GraphPatchRejectedPayload,
    HydratedEvent,
    GraphProjection,
    OutputRecordAcceptedPayload,
    RequirementRecord,
    StrictFileStateRecord,
    NodeCreatedPayload,
    check_command_uses_acceptance_fallback,
    initial_projection,
    resolve_check_command_definition,
)
from orchestrator.graph_runtime import prompts as _prompts
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
from orchestrator.graph import build_graph_command_dependencies
from orchestrator.graph import GraphCatalog

MAX_GRAPH_PROMPT_CHARS = _prompts.MAX_GRAPH_PROMPT_CHARS
MAX_GRAPH_JSON_SECTION_CHARS = _prompts.MAX_GRAPH_JSON_SECTION_CHARS
MAX_GRAPH_PROMPT_FIELD_CHARS = _prompts.MAX_GRAPH_PROMPT_FIELD_CHARS
MAX_CHECK_OUTPUT_CHARS = 20_000
DEFAULT_CHECK_TIMEOUT_SECONDS = 300
MAX_STALE_COMMAND_RETRIES = 5
DEFAULT_GAP_PLANNER_RUNTIME_DEATH_MAX_ATTEMPTS = 3
SNAPSHOT_REF_PATTERN = re.compile(r"^refs/orchestrator/snapshots/[0-9a-f]{32}$")

_prompt_for_node = _prompts.prompt_for_node
_prompt_summary_for_node = _prompts.prompt_summary_for_node
_planner_evidence = _prompts.planner_evidence
_planner_packet = _prompts.planner_packet
_can_submit_graph_patch = _prompts.can_submit_graph_patch
_requires_graph_patch_before_submit = _prompts.requires_graph_patch_before_submit
_graph_patch_feedback_accepted = _prompts.graph_patch_feedback_accepted
_node_role = _prompts.node_role
_available_tools_for_context = _prompts.available_tools_for_context
_patch_payload_has_ops = _prompts.patch_payload_has_ops
_output_records_for_submit = _prompts.output_records_for_submit
_candidate_id_for_check = _prompts.candidate_id_for_check
_evaluated_record_citations = _prompts.evaluated_record_citations
_add_evaluated_record_citations = _prompts.add_evaluated_record_citations


def _empty_event_list() -> list[HydratedEvent]:
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
    graph_events: list[HydratedEvent] = field(default_factory=_empty_event_list)
    node_role: str = ""


@dataclass(frozen=True)
class CheckExecutionWorktree:
    path: str
    snapshot_id: str | None = None
    snapshot_ref: str | None = None
    temporary_path: str | None = None


@dataclass(frozen=True)
class DependencyProvisionResult:
    package_dir: str
    strategy: str
    status: Literal["provisioned", "skipped", "failed"]
    detail: str


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


def _runtime_death_max_attempts(context: GraphDispatchContext) -> int | None:
    max_attempts = context.node_payload.get("max_attempts")
    if isinstance(max_attempts, int) and not isinstance(max_attempts, bool):
        return max_attempts
    if context.node_role == "gap_planner":
        return DEFAULT_GAP_PLANNER_RUNTIME_DEATH_MAX_ATTEMPTS
    return None


class GraphDispatchExecutor(SideEffectExecutor):
    """Start graph-leased agent executions from durable outbox items."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        controller: GraphController,
        agent_factory: GraphAgentFactory,
        *,
        catalog: GraphCatalog,
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
        self._catalog = catalog
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

    async def wait_for_all(
        self,
        *,
        timeout_seconds: float | None = None,
        active_execution_ids: set[str] | None = None,
    ) -> None:
        self._prune_done()
        if active_execution_ids is None:
            tasks = list(self._running.values())
        else:
            tasks = [
                task
                for execution_id, task in self._running.items()
                if execution_id in active_execution_ids
            ]
        if tasks:
            if timeout_seconds is None:
                await asyncio.gather(*tasks)
            else:
                await asyncio.wait(tasks, timeout=max(0.0, timeout_seconds))
        self._prune_done()

    def cancel_all(self) -> None:
        for task in self._running.values():
            task.cancel()

    def _prune_done(self) -> None:
        for execution_id, task in list(self._running.items()):
            if task.done():
                self._running.pop(execution_id, None)

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
                    patch_has_ops = _patch_payload_has_ops(patch_payload)
                    if context.node_role == "gap_planner":
                        context.node_payload["_accepted_gap_planner_patch_had_ops"] = patch_has_ops
                    if patch_has_ops:
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
            events = await GraphEventStore(
                session,
                self._catalog,
            ).read_run(item.run_id)

        projection = rebuild_projection(self._catalog, events)
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
            requirements=_requirements_for_node(events, node_id, catalog=self._catalog),
            worktree_path=self._worktree_path,
            lease_id=str(payload["lease_id"]),
            lease_generation=_payload_int(payload, "generation"),
            execution_id=str(payload["execution_id"]),
            base_snapshot_id=base_snapshot_id,
            dispatch_event_id=item.event_id,
            graph_projection=projection,
            graph_events=events,
        )

    def _execution_context(
        self,
        context: GraphDispatchContext,
        graph_patch_callback: Callable[[dict[str, Any]], Awaitable[str]] | None = None,
    ) -> ExecutionContext:
        node = context.node_payload
        prompt = _prompt_for_node(context, catalog=self._catalog)
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
                "prompt_summary": _prompt_summary_for_node(context, catalog=self._catalog),
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
                "lease_generation": context.lease_generation,
            },
        )
        rejection_payload: CommandRejectedPayload | None = None
        for event in result.events:
            if event.event_type != "command_rejected":
                continue
            if not isinstance(event.payload, CommandRejectedPayload):
                raise TypeError("command_rejected event has an unexpected payload type")
            if event.payload.command_type == "record_heartbeat":
                rejection_payload = event.payload
                break
        if rejection_payload is not None:
            reason = cast(str | None, rejection_payload.reason)
            if reason is None:
                reason = "record_heartbeat rejected"
            raise ValueError(reason)

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
            result = await self._handle_command_retry_stale(
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
        accepted = next(
            (event for event in result.events if event.event_type == "graph_patch_accepted"),
            None,
        )
        if accepted is not None:
            accepted_payload = accepted.payload
            if not isinstance(accepted_payload, GraphPatchAcceptedPayload):
                raise TypeError("graph_patch_accepted event has an unexpected payload type")
            patch_id = accepted_payload.patch_id
            successors = accepted_payload.successor_planner_node_ids
            return (
                f"graph patch {patch_id} accepted; "
                f"successor planner nodes: {json.dumps(successors, sort_keys=True)}"
            )

        rejection = next(
            (event for event in result.events if event.event_type == "graph_patch_rejected"),
            None,
        )
        if rejection is not None:
            rejection_payload = rejection.payload
            if not isinstance(rejection_payload, GraphPatchRejectedPayload):
                raise TypeError("graph_patch_rejected event has an unexpected payload type")
            return f"graph patch {rejection_payload.patch_id} rejected: {rejection_payload.reason}"

        command_rejection = next(
            (event for event in result.events if event.event_type == "command_rejected"),
            None,
        )
        if command_rejection is not None:
            rejection_payload = command_rejection.payload
            if not isinstance(rejection_payload, CommandRejectedPayload):
                raise TypeError("command_rejected event has an unexpected payload type")
            patch_id = rejection_payload.patch_id
            if patch_id is None:
                patch_id = str(payload.get("patch_id", "unknown"))
            return f"graph patch {patch_id} rejected: {rejection_payload.reason}"

        return "graph patch command completed without accepted or rejected patch event"

    async def _agent_died(self, context: GraphDispatchContext, reason: str) -> None:
        payload: dict[str, object] = {
            "lease_id": context.lease_id,
            "execution_id": context.execution_id,
            "reason": reason or "runtime_process_died",
        }
        max_attempts = _runtime_death_max_attempts(context)
        if max_attempts is not None:
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
        """Issue a graph command, retrying stale-projection races and transient DB locks.

        Two independent, retriable failure modes can surface from
        ``GraphController.handle_command``: a losing optimistic-concurrency
        race (``StaleProjectionError``, re-read position and resend), and a
        transient SQLite write-lock contention error (``OperationalError``
        with "database is locked"/"database is busy", back off briefly and
        resend the same payload — mirrors ``OutboxDispatcher._retry_locked``).
        Both share this method's retry budget.
        """
        current_position = expected_position
        retry_payload = dict(payload)
        delay_seconds = 0.1
        for attempt in range(MAX_STALE_COMMAND_RETRIES + 1):
            try:
                return await self._controller.handle_command(
                    run_id,
                    current_position,
                    command_type,
                    retry_payload,
                )
            except OperationalError as exc:
                if (
                    not is_retriable_sqlite_write_conflict(exc)
                    or attempt >= MAX_STALE_COMMAND_RETRIES
                ):
                    raise
                await asyncio.sleep(delay_seconds * (attempt + 1))
            except StaleProjectionError:
                if attempt >= MAX_STALE_COMMAND_RETRIES:
                    raise
                current_position = await self._current_position(run_id)
                if "observed_graph_position" in retry_payload:
                    retry_payload["observed_graph_position"] = current_position
        raise StaleProjectionError(f"stale graph projection for run {run_id}: retry loop exhausted")

    async def _current_position(self, run_id: str) -> int:
        async with self._session_factory() as session:
            return await GraphEventStore(
                session,
                self._catalog,
            ).current_position(run_id)

    async def _events(self, run_id: str) -> list[HydratedEvent]:
        async with self._session_factory() as session:
            events = await GraphEventStore(
                session,
                self._catalog,
            ).read_run(run_id)
        return events

    async def _record_gatekeeper_verdicts(
        self,
        context: GraphDispatchContext,
        projection_position: int,
        accepted_events: list[HydratedEvent],
    ) -> None:
        if self._residue_classifier is None:
            return
        current_position = projection_position
        for event in accepted_events:
            if event.event_type != "file_state_accepted" or not isinstance(
                event.payload, StrictFileStateRecord
            ):
                continue
            record = event.payload
            metadata = metadata_from_file_state_record(
                record,
                max_items=self._max_gatekeeper_items_per_boundary,
            )
            if not metadata:
                continue
            verdicts = self._residue_classifier.classify(metadata)
            if not verdicts:
                continue
            model_ids = sorted({verdict.model_id for verdict in verdicts})
            result = await self._handle_command_retry_stale(
                context.run_id,
                current_position,
                "record_gatekeeper_verdicts",
                {
                    "file_state_record_id": record.record_id,
                    "execution_id": context.execution_id,
                    "consult_id": f"{context.execution_id}:{record.record_id}",
                    "model_id": model_ids[0] if len(model_ids) == 1 else "mixed",
                    "verdicts": verdicts,
                },
            )
            current_position = result.projection_position

    async def _dispatch_snapshot_cleanup(self, item: OutboxItem) -> None:
        """Apply a cleanup side effect and record its durable result.

        ``snapshot_cleanup`` outbox rows are at-least-once. A retry may observe
        that ``cleanup_applied`` was already committed after an earlier
        filesystem cleanup; in that case the side effect intent is complete.
        """
        async with self._session_factory() as session:
            events = await GraphEventStore(session, self._catalog).read_run(item.run_id)
        cleanup_id = str(item.payload.get("cleanup_id", ""))
        if _cleanup_applied_exists(events, cleanup_id):
            return
        cleanup_event = _cleanup_requested_event(events, cleanup_id)
        if cleanup_event is None:
            msg = f"unknown cleanup_requested: {cleanup_id}"
            raise ValueError(msg)
        cleanup_payload = cleanup_event.payload
        if not isinstance(cleanup_payload, CleanupRequestedPayload):
            raise TypeError("cleanup_requested event has an unexpected payload type")
        record_id = cleanup_payload.file_state_record_id
        projection = rebuild_projection(self._catalog, events)
        compromised_record = projection["file_state_records"].get(record_id)
        if compromised_record is None:
            msg = f"unknown cleanup file_state record: {record_id}"
            raise ValueError(msg)

        cleanup = apply_cleanup_requested(
            worktree_path=self._worktree_path,
            cleanup_request=cleanup_payload,
            compromised_record=compromised_record,
        )
        result = await self._handle_command_retry_stale(
            item.run_id,
            await self._current_position(item.run_id),
            "record_cleanup_applied",
            {
                "cleanup_id": cleanup.cleanup_id,
                "superseding_file_state_record": StrictFileStateRecord.model_validate(
                    cleanup.superseding_file_state_record
                ),
                "deleted_snapshot_ref": cleanup.deleted_snapshot_ref,
            },
        )
        if _rejected_cleanup_already_applied(result.events, cleanup_id):
            return
        rejection_payload: CommandRejectedPayload | None = None
        for event in result.events:
            if event.event_type != "command_rejected":
                continue
            if not isinstance(event.payload, CommandRejectedPayload):
                raise TypeError("command_rejected event has an unexpected payload type")
            if event.payload.command_type == "record_cleanup_applied":
                rejection_payload = event.payload
                break
        if rejection_payload is not None:
            reason = cast(str | None, rejection_payload.reason)
            if reason is None:
                reason = "record_cleanup_applied rejected"
            raise ValueError(reason)


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
        delay_seconds = 0.1
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
            except OperationalError as exc:
                if (
                    not is_retriable_sqlite_write_conflict(exc)
                    or attempt == MAX_STALE_COMMAND_RETRIES - 1
                ):
                    raise
                await asyncio.sleep(delay_seconds * (attempt + 1))
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
    catalog: GraphCatalog,
) -> tuple[GraphController, GraphDispatchExecutor]:
    """Assemble graph controller and dispatch executor without API imports."""

    controller = GraphController(
        session_factory,
        clock,
        id_gen,
        catalog=catalog,
        auto_dispatch=False,
        future_effects=build_graph_command_dependencies(catalog).future_effects,
    )
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        StaticGraphAgentFactory(runner_type, runner_config),
        catalog=catalog,
        worktree_path=worktree_path,
        on_agent_output=on_agent_output,
        on_agent_usage=on_agent_usage,
    )
    return controller, executor


def _node_payload(events: Sequence[HydratedEvent], node_id: str) -> dict[str, Any]:
    for event in events:
        if event.event_type != "node_created":
            continue
        if not isinstance(event.payload, NodeCreatedPayload):
            raise TypeError("node_created event has an unexpected payload type")
        if event.payload.node_id == node_id:
            return event.payload.to_json()
    return {"node_id": node_id}


def _requirements_for_node(
    events: Sequence[HydratedEvent], node_id: str, *, catalog: GraphCatalog
) -> list[str]:
    projection = rebuild_projection(catalog, events)
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
        if not isinstance(event.payload, NodeCreatedPayload):
            raise TypeError("node_created event has an unexpected payload type")
        payload = event.payload
        if payload.node_id not in bound_record_ids:
            continue
        if payload.requirement_record is not None:
            try:
                record = RequirementRecord.model_validate(payload.requirement_record)
            except ValueError:
                continue
            requirements.append(f"{record.value.id}: {record.value.text}")
            continue
        if payload.requirement is not None:
            requirement_id = payload.requirement.get("id", payload.node_id)
            description = payload.requirement.get("desc", "")
            if isinstance(requirement_id, str) and isinstance(description, str):
                requirements.append(f"{requirement_id}: {description}")
    if requirements:
        return requirements

    dynamic_feature = _dynamic_feature_from_events(events)
    if dynamic_feature is not None:
        requirement = _dynamic_feature_acceptance_requirement(dynamic_feature)
        if requirement is not None:
            return [requirement]
    return requirements


def _dynamic_feature_from_events(events: Sequence[HydratedEvent]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.event_type != "node_created":
            continue
        if not isinstance(event.payload, NodeCreatedPayload):
            raise TypeError("node_created event has an unexpected payload type")
        snapshot = event.payload.snapshot
        if isinstance(snapshot, dict):
            typed_snapshot = cast(dict[str, Any], snapshot)
            snapshot_feature = typed_snapshot.get("dynamic_feature")
            if isinstance(snapshot_feature, dict):
                return cast(dict[str, Any], snapshot_feature)
        payload_feature = event.payload.dynamic_feature
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


_CALLBACK_REJECTION_EVENT_TYPES = {"callback_rejected_conflict", "callback_rejected_stale"}


def _callback_conflict_reason(events: list[HydratedEvent]) -> str | None:
    # A ``callback_duplicate_returned`` event only means "we've seen this
    # idempotency key before" — the prior result it replays may itself have
    # been a rejection (historic event logs can contain duplicate-of-rejection
    # events even though current validation no longer produces them). Treating
    # a duplicate-of-rejection as success would silently swallow the original
    # conflict/staleness, so its prior_result must be inspected rather than
    # assumed to be an acceptance.
    for event in events:
        if event.event_type in _CALLBACK_REJECTION_EVENT_TYPES:
            if not isinstance(event.payload, CallbackRejectedPayload):
                raise TypeError(f"{event.event_type} event has an unexpected payload type")
            return event.payload.reason or "unknown callback conflict"
        if event.event_type == "command_rejected":
            if not isinstance(event.payload, CommandRejectedPayload):
                raise TypeError("command_rejected event has an unexpected payload type")
            return event.payload.reason or "unknown callback conflict"
        if event.event_type == "callback_duplicate_returned":
            if not isinstance(event.payload, CallbackDuplicateReturnedPayload):
                raise TypeError("callback_duplicate_returned event has an unexpected payload type")
            duplicate_reason = _duplicate_of_rejection_reason(event.payload)
            if duplicate_reason is not None:
                return duplicate_reason
    return None


def _duplicate_of_rejection_reason(
    payload: CallbackDuplicateReturnedPayload,
) -> str | None:
    prior_result = payload.prior_result
    if not isinstance(prior_result, dict):
        return None
    prior = cast(dict[str, Any], prior_result)
    prior_outcome = prior.get("outcome")
    if prior_outcome not in _CALLBACK_REJECTION_EVENT_TYPES:
        return None
    prior_payload = prior.get("payload")
    reason = (
        cast(dict[str, Any], prior_payload).get("reason")
        if isinstance(prior_payload, dict)
        else None
    )
    return str(reason) if isinstance(reason, str) and reason else f"duplicate of {prior_outcome}"


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
            if record.compromised is True and record.superseded_pending is True:
                cleanup_id = record.cleanup_id
                msg = (
                    "refusing to bind compromised file-state record "
                    f"{raw_record_id} for node {node_id}"
                )
                if isinstance(cleanup_id, str) and cleanup_id:
                    msg = f"{msg}; cleanup pending: {cleanup_id}"
                raise CompromisedFileStateError(msg)


def _cleanup_requested_event(
    events: list[HydratedEvent],
    cleanup_id: str,
) -> HydratedEvent | None:
    for event in events:
        if event.event_type != "cleanup_requested":
            continue
        if not isinstance(event.payload, CleanupRequestedPayload):
            raise TypeError("cleanup_requested event has an unexpected payload type")
        if event.payload.cleanup_id == cleanup_id:
            return event
    return None


def _cleanup_applied_exists(events: list[HydratedEvent], cleanup_id: str) -> bool:
    for event in events:
        if event.event_type != "cleanup_applied":
            continue
        if not isinstance(event.payload, CleanupAppliedPayload):
            raise TypeError("cleanup_applied event has an unexpected payload type")
        if event.payload.cleanup_id == cleanup_id:
            return True
    return False


def _rejected_cleanup_already_applied(
    events: list[HydratedEvent],
    cleanup_id: str,
) -> bool:
    for event in events:
        if event.event_type != "command_rejected":
            continue
        if not isinstance(event.payload, CommandRejectedPayload):
            raise TypeError("command_rejected event has an unexpected payload type")
        if (
            event.payload.command_type == "record_cleanup_applied"
            and event.payload.reason == f"cleanup already applied: {cleanup_id}"
        ):
            return True
    return False


async def _execute_check_command(context: GraphDispatchContext) -> dict[str, Any]:
    command_definition = _check_command_definition(context.node_payload, context.graph_events)
    cited_record = _check_result_from_bound_verification_if_redundant(
        context,
        command_definition,
    )
    if cited_record is not None:
        return cited_record
    invocation, command_text, shell = _check_invocation(command_definition)
    timeout_seconds = _check_timeout_seconds(command_definition)
    execution_worktree = await asyncio.to_thread(_prepare_check_execution_worktree, context)
    dependency_provisioning = await asyncio.to_thread(
        _provision_check_dependencies,
        context,
        execution_worktree,
        command_text,
    )
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
    classification = _classify_check_result(
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        dependency_provisioning=dependency_provisioning,
    )
    candidate_id = _candidate_id_for_check(context)
    task_region_id = str(context.node_payload.get("task_region_id") or context.node_id)
    attempt_number = int(context.node_payload.get("attempt_number", 0))
    command_id = str(command_definition.get("id") or context.node_id)
    value: dict[str, Any] = {
        "status": status,
        "classification": classification,
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
            "dependency_provisioning": [
                {
                    "package_dir": result.package_dir,
                    "strategy": result.strategy,
                    "status": result.status,
                    "detail": result.detail,
                }
                for result in dependency_provisioning
            ],
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


def _check_result_from_bound_verification_if_redundant(
    context: GraphDispatchContext,
    command_definition: dict[str, Any],
) -> dict[str, Any] | None:
    if command_definition.get("source") != "dynamic_feature_hidden_oracle_binding":
        return None
    if not check_command_uses_acceptance_fallback(context.node_payload, context.graph_events):
        return None
    citations = _evaluated_record_citations(context)
    verification_record = _latest_passed_verification_citation(
        context.graph_events,
        citations.get("verification_report_record_ids", []),
    )
    if verification_record is None:
        return None
    candidate_id = _candidate_id_for_check(context)
    task_region_id = str(context.node_payload.get("task_region_id") or context.node_id)
    attempt_number = int(context.node_payload.get("attempt_number", 0))
    value: dict[str, Any] = {
        "status": "passed",
        "classification": "passed",
        "command_id": str(command_definition.get("id") or context.node_id),
        "command_binding": "dynamic_feature_hidden_oracle",
        "command_text": command_definition.get("cmd"),
        "command": command_definition,
        "citation_mode": "verification_report_reused",
        "reused_verification_record_id": verification_record["record_id"],
        "worktree_path": context.worktree_path,
        "source_worktree_path": context.worktree_path,
        "execution_id": context.execution_id,
        "base_snapshot_id": context.base_snapshot_id,
        "duration_ms": 0,
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timeout_seconds": 1,
        "environment_policy": {
            "cwd": context.worktree_path,
            "env": "inherited",
            "source_worktree_path": context.worktree_path,
            "dependency_provisioning": [],
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
        citations,
        value=True,
    )
    return CheckResultRecord.model_validate(record_payload).model_dump(mode="json")


def _latest_passed_verification_citation(
    events: list[HydratedEvent],
    record_ids: list[str],
) -> dict[str, Any] | None:
    wanted = set(record_ids)
    latest: dict[str, Any] | None = None
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        payload = OutputRecordAcceptedPayload.model_validate(event.payload).record.model_dump(
            mode="json",
            by_alias=True,
        )
        if payload.get("record_id") not in wanted:
            continue
        if payload.get("record_type") != "verification_report":
            continue
        outcome = payload.get("outcome") or payload.get("verdict")
        value = payload.get("value")
        if outcome is None and isinstance(value, dict):
            outcome = cast(dict[str, Any], value).get("outcome")
        if outcome not in {"passed", "pass"}:
            continue
        latest = dict(payload)
    return latest


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


def _provision_check_dependencies(
    context: GraphDispatchContext,
    execution_worktree: CheckExecutionWorktree,
    command_text: str,
) -> list[DependencyProvisionResult]:
    if execution_worktree.temporary_path is None:
        return []
    if not _command_needs_node_dependencies(command_text):
        return []

    source_root = Path(context.worktree_path)
    execution_root = Path(execution_worktree.path)
    results: list[DependencyProvisionResult] = []
    for package_dir in _node_package_dirs(execution_root, command_text):
        source_package_dir = source_root / package_dir
        execution_package_dir = execution_root / package_dir
        node_modules = execution_package_dir / "node_modules"
        if node_modules.exists():
            results.append(
                DependencyProvisionResult(
                    package_dir=package_dir,
                    strategy="existing_node_modules",
                    status="skipped",
                    detail="node_modules already exists in check worktree",
                )
            )
            continue

        source_node_modules = source_package_dir / "node_modules"
        if source_node_modules.exists():
            try:
                os.symlink(source_node_modules, node_modules, target_is_directory=True)
            except OSError as exc:
                results.append(
                    DependencyProvisionResult(
                        package_dir=package_dir,
                        strategy="symlink_source_node_modules",
                        status="failed",
                        detail=str(exc),
                    )
                )
            else:
                results.append(
                    DependencyProvisionResult(
                        package_dir=package_dir,
                        strategy="symlink_source_node_modules",
                        status="provisioned",
                        detail=f"linked {source_node_modules}",
                    )
                )
            continue

        lockfile = execution_package_dir / "package-lock.json"
        if lockfile.exists():
            result = subprocess.run(
                ["npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"],
                cwd=execution_package_dir,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if result.returncode == 0:
                results.append(
                    DependencyProvisionResult(
                        package_dir=package_dir,
                        strategy="npm_ci",
                        status="provisioned",
                        detail="npm ci completed",
                    )
                )
            else:
                detail = _trim_check_output(result.stderr or result.stdout)
                results.append(
                    DependencyProvisionResult(
                        package_dir=package_dir,
                        strategy="npm_ci",
                        status="failed",
                        detail=detail,
                    )
                )
            continue

        results.append(
            DependencyProvisionResult(
                package_dir=package_dir,
                strategy="node_modules_unavailable",
                status="failed",
                detail="no source node_modules or package-lock.json available",
            )
        )
    return results


def _command_needs_node_dependencies(command_text: str) -> bool:
    lowered = command_text.lower()
    return any(
        token in lowered for token in ("npm", "npx", "vitest", "vite", "tsx", "node_modules")
    )


def _node_package_dirs(execution_root: Path, command_text: str) -> list[str]:
    candidates: list[str] = []
    if (execution_root / "package.json").exists():
        candidates.append(".")
    for match in re.finditer(r"(?:--prefix|-C)\s+([^\s;&|]+)", command_text):
        raw_path = match.group(1).strip("'\"")
        if raw_path and not raw_path.startswith(("/", "..")):
            candidates.append(raw_path)
    if " ui " in f" {command_text} " or "--prefix ui" in command_text or "ui/" in command_text:
        candidates.append("ui")
    if not candidates and (execution_root / "ui" / "package.json").exists():
        candidates.append("ui")

    output: list[str] = []
    for candidate in candidates:
        normalized = candidate.rstrip("/") or "."
        if normalized not in output and (execution_root / normalized / "package.json").exists():
            output.append(normalized)
    return output


def _classify_check_result(
    *,
    status: str,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    dependency_provisioning: list[DependencyProvisionResult],
) -> str:
    if status in {"passed", "timeout"}:
        return status
    if any(result.status == "failed" for result in dependency_provisioning):
        return "environment_error"
    combined = f"{stdout}\n{stderr}".lower()
    if exit_code == 127 or any(
        phrase in combined
        for phrase in (
            "command not found",
            "no such file or directory",
            "could not determine executable to run",
            "sh: vitest:",
            "vitest: not found",
        )
    ):
        return "tool_unavailable"
    if "enoent" in combined or "cannot find module" in combined:
        return "tool_error"
    return "failed"


def _bound_file_state_snapshot(context: GraphDispatchContext) -> tuple[str, str] | None:
    citations = _evaluated_record_citations(context)
    file_state_record_ids = citations.get("file_state_record_ids", [])
    if not file_state_record_ids:
        return None
    wanted = set(file_state_record_ids)
    for event in context.graph_events:
        if event.event_type not in {
            "output_record_accepted",
            "file_state_accepted",
        }:
            continue
        if event.event_type == "output_record_accepted":
            if not isinstance(event.payload, OutputRecordAcceptedPayload):
                raise TypeError("output_record_accepted event has an unexpected payload type")
            record = event.payload.record
        else:
            if not isinstance(event.payload, StrictFileStateRecord):
                raise TypeError("file_state_accepted event has an unexpected payload type")
            record = event.payload
        if not isinstance(record, StrictFileStateRecord) or record.record_id not in wanted:
            continue
        snapshot_ref = record.git.ref if record.git is not None else None
        if record.snapshot_id is not None and snapshot_ref is not None:
            return record.snapshot_id, snapshot_ref
    return None


def _check_command_definition(
    node: dict[str, Any],
    events: list[HydratedEvent],
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
