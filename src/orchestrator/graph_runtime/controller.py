"""Effectful graph controller wrapper around the pure command kernel."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.graph import (
    AgentDispatchResourceClaim,
    Actor,
    ActorKind,
    EventEnvelope,
    GraphCommandContext,
    PatchCommandContext,
    GraphProjection,
    validate_emitted_event_type,
    apply_command,
    build_projection,
    serialize_event_payload,
    StoredArtifactRef,
    SubmitPatchCommand,
    node_payload_view,
    planner_patch_decisions_by_id_view,
    semantic_schema_declarations_view,
    submit_patch_operation_fingerprint,
    submit_patch_operation_key,
)
from orchestrator.artifacts import ArtifactStore
from orchestrator.artifacts import ArtifactIntegrityError, ArtifactNotFoundError
from orchestrator.state import ModelTokenUsage
from orchestrator.db import (
    CommittedSecondaryOutputError,
    commit_with_event_outbox,
    is_retriable_sqlite_write_conflict,
    retry_committed_secondary_output,
)
from orchestrator.graph import Clock, IdGenerator
from orchestrator.graph_runtime.errors import PatchOperationConflictError, StaleProjectionError
from orchestrator.graph_runtime.outbox import OutboxDispatcher, OutboxItem, append_outbox_rows
from orchestrator.graph_runtime.store import GraphEventStore

if TYPE_CHECKING:
    from orchestrator.graph_runtime.dispatch import GraphDispatchContext


@dataclass(frozen=True)
class GraphCommandResult:
    events: list[EventEnvelope]
    outbox_items: list[OutboxItem]
    projection_position: int
    reconciled_patch_id: str | None = None
    reconciled_successor_planner_node_ids: tuple[str, ...] = ()


CommandCommitObserver = Callable[
    [Literal["before_commit", "after_commit"], str, str, tuple[EventEnvelope, ...]],
    Awaitable[None],
]
ReliablePlanRejectionRecorder = Callable[
    [str, int, dict[str, object], PatchCommandContext, list[EventEnvelope]],
    Awaitable[dict[str, object]],
]


MAX_NODE_USAGE_WRITE_RETRIES = 5
logger = logging.getLogger(__name__)


def _is_reliable_plan_macro_request(payload: dict[str, object]) -> bool:
    invocations = payload.get("macro_invocations")
    return isinstance(invocations, list) and any(
        isinstance(item, dict)
        and cast(dict[str, object], item).get("macro") == "construct_reliable_plan_region"
        for item in cast(list[object], invocations)
    )


class RuntimeBoundaryCapability:
    """Unforgeable in-process authority for managed runner boundary writes."""

    __slots__ = ()


_RUNTIME_BOUNDARY_COMMANDS = frozenset(
    {
        "record_runner_baseline",
        "stage_runner_submission",
        "witness_runner_completion",
        "finalize_runner_execution",
        "request_runner_recovery",
    }
)


class GraphController:
    """Loads graph state, applies pure commands, and commits events plus outbox."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        id_gen: IdGenerator,
        *,
        dispatcher: OutboxDispatcher | None = None,
        auto_dispatch: bool = True,
        journal_max_bytes: int = 64 * 1024 * 1024,
        runtime_boundary_capability: RuntimeBoundaryCapability | None = None,
        artifact_store: ArtifactStore | None = None,
        command_commit_observer: CommandCommitObserver | None = None,
        reliable_plan_rejection_recorder: ReliablePlanRejectionRecorder | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._id_gen = id_gen
        self._dispatcher = dispatcher
        self._auto_dispatch = auto_dispatch
        self._journal_max_bytes = journal_max_bytes
        self._runtime_boundary_capability = (
            runtime_boundary_capability or RuntimeBoundaryCapability()
        )
        self._artifact_store = artifact_store
        self._command_commit_observer = command_commit_observer
        self._reliable_plan_rejection_recorder = reliable_plan_rejection_recorder

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
        *,
        context: GraphCommandContext | None = None,
    ) -> GraphCommandResult:
        if command_type in _RUNTIME_BOUNDARY_COMMANDS:
            raise ValueError("managed runner boundary commands require runtime capability")
        return await self._handle_command(
            run_id, expected_position, command_type, payload, context=context
        )

    async def handle_runtime_boundary_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None,
        capability: RuntimeBoundaryCapability,
        *,
        context: GraphCommandContext | None = None,
    ) -> GraphCommandResult:
        if command_type not in _RUNTIME_BOUNDARY_COMMANDS:
            raise ValueError("runtime capability is reserved for boundary commands")
        if capability is not self._runtime_boundary_capability:
            raise ValueError("invalid runtime boundary capability")
        return await self._handle_command(
            run_id, expected_position, command_type, payload, context=context
        )

    async def _handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
        *,
        context: GraphCommandContext | None = None,
    ) -> GraphCommandResult:
        """Apply a command and atomically commit accepted events plus outbox rows.

        Before taking a write lock, the controller loads the latest persisted
        projection checkpoint and folds only its bounded event tail. If that
        tail exceeds the runtime cap, the read model is reported unavailable;
        command handling never falls back to replaying the full event log.
        Only the cheap position re-check and the append itself run inside the
        ``BEGIN IMMEDIATE`` write transaction, so the write lock is held for a
        bounded, small amount of work regardless of how large the run's event
        log has grown. If the position moved between the pre-read and the
        write (a concurrent writer landed first), this raises
        ``StaleProjectionError`` just like a losing ``append_events`` race
        used to; callers already retry on that (see
        ``dispatch._handle_command_retry_stale`` and
        ``graph_driver._handle_command_at_head``), so correctness is
        preserved by optimistic concurrency. ``append_events`` also performs
        its own ``current_position`` check and the UNIQUE constraint on
        ``(aggregate_id, version)`` is the final backstop, so the invariant
        holds even if two callers somehow race past the explicit check below.
        """
        command_payload = dict(payload or {})

        # Phase 1: load the persisted projection snapshot and fold only the
        # event tail OUTSIDE any write lock. This is the part that can take
        # time on a large graph history, so it must not hold BEGIN IMMEDIATE
        # while it runs.
        async with self._session_factory() as read_session:
            read_store = GraphEventStore(read_session)
            (
                projection,
                existing_events,
                current_position,
            ) = await read_store.load_projection_with_tail(run_id)
        reconciled = None
        if (
            command_type == "submit_patch"
            and isinstance(context, PatchCommandContext)
            and context.run_id == run_id
            and context.actor_role == "planner"
        ):
            reconciled = _reconciled_committed_patch(
                projection,
                command_type,
                command_payload,
                context,
            )
        if reconciled is not None:
            patch_id, successor_node_ids = reconciled
            return GraphCommandResult(
                events=[],
                outbox_items=[],
                projection_position=current_position,
                reconciled_patch_id=patch_id,
                reconciled_successor_planner_node_ids=successor_node_ids,
            )
        planner_payload = (
            node_payload_view(projection, context.proposed_by_node_id)
            if command_type == "submit_patch" and isinstance(context, PatchCommandContext)
            else None
        )
        if (
            command_type == "submit_patch"
            and isinstance(context, PatchCommandContext)
            and context.actor_role == "planner"
            and planner_payload is not None
            and planner_payload.get("kind") == "planner"
            and planner_payload.get("role") != "gap_planner"
            and isinstance(planner_payload.get("reliable_plan_skeleton_id"), str)
        ):
            async with self._session_factory() as count_session:
                rejection_count = await GraphEventStore(
                    count_session
                ).reliable_plan_rejection_count(run_id, context.proposed_by_node_id)
            context = context.model_copy(update={"reliable_plan_rejection_count": rejection_count})
        if current_position != expected_position:
            msg = (
                f"stale graph projection for run {run_id}: "
                f"expected {expected_position}, found {current_position}"
            )
            raise StaleProjectionError(msg)

        command_payload = await self._validate_semantic_artifact_references(
            command_type, command_payload, projection
        )

        command_context = context or GraphCommandContext(
            run_id=run_id,
            current_graph_position=current_position,
        )
        if (
            command_context.run_id != run_id
            or command_context.current_graph_position != current_position
        ):
            msg = "command context does not match the loaded graph head"
            raise ValueError(msg)
        command_events = existing_events
        patch_base_position = _patch_base_graph_position(command_type, command_payload)
        if patch_base_position is not None and patch_base_position < current_position:
            async with self._session_factory() as read_session:
                command_events = await GraphEventStore(read_session).read_bounded_runtime_events(
                    run_id,
                    from_position=patch_base_position + 1,
                )
        planned_events = apply_command(
            projection,
            command_events,
            command_type,
            command_payload,
            command_context,
            self._clock,
            self._id_gen,
        )
        planned_events = self._add_dispatch_intent_events(
            planned_events,
            command_type,
            run_id,
        )
        if (
            command_type == "submit_patch"
            and isinstance(context, PatchCommandContext)
            and context.actor_role == "planner"
            and _is_reliable_plan_macro_request(command_payload)
            and any(
                event.event_type in {"graph_patch_rejected", "command_rejected"}
                for event in planned_events
            )
            and self._reliable_plan_rejection_recorder is not None
        ):
            try:
                rejection_evidence = await self._reliable_plan_rejection_recorder(
                    run_id,
                    expected_position,
                    command_payload,
                    context,
                    planned_events,
                )
            except Exception:
                logger.error("reliable-plan rejection evidence capture failed")
                rejection_evidence = {
                    "classification": "capture_failed",
                    "replayable": False,
                }
            planned_events = [
                event.model_copy(
                    update={
                        "payload": serialize_event_payload(
                            event.event_type,
                            {**event.payload, "rejection_evidence": rejection_evidence},
                        )
                    }
                )
                if event.event_type in {"graph_patch_rejected", "command_rejected"}
                else event
                for event in planned_events
            ]

        # Phase 2: short write transaction. Re-check the position cheaply
        # (COUNT/MAX query, not a full read) before appending, so a writer
        # that landed between phase 1 and here is detected without ever
        # re-reading the whole event log inside the lock.
        async with self._session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                store = GraphEventStore(session, journal_max_bytes=self._journal_max_bytes)
                head_position = await store.current_position(run_id)
                if head_position != expected_position:
                    msg = (
                        f"stale graph projection for run {run_id}: "
                        f"expected {expected_position}, found {head_position}"
                    )
                    raise StaleProjectionError(msg)

                stored_events = await store.append_events(
                    run_id,
                    expected_position,
                    planned_events,
                    # The projection was loaded at ``expected_position`` for
                    # pure command planning, and the transactional head check
                    # above proves it is still authoritative. Reuse it instead
                    # of decoding the same immutable checkpoint a second time.
                    authoritative_projection=projection,
                )
                outbox_items = await append_outbox_rows(session, stored_events, self._clock)
                if self._command_commit_observer is not None:
                    await self._command_commit_observer(
                        "before_commit",
                        run_id,
                        command_type,
                        tuple(stored_events),
                    )
                # Graph events queue the same post-commit JSONL observer used
                # by workflow events. A secondary journal failure propagates
                # only after the authoritative graph transaction is committed.
                try:
                    await commit_with_event_outbox(session)
                except CommittedSecondaryOutputError as exc:
                    # The graph command is already durable. Retry its exact
                    # observer batch, rather than reapplying the command or
                    # letting dispatch translate a journal fault to agent death.
                    try:
                        await retry_committed_secondary_output(exc)
                    except CommittedSecondaryOutputError as retry_error:
                        # The authoritative DB rows are the durable reconciliation
                        # debt. Do not turn a secondary output failure into an
                        # agent failure after the graph command has committed.
                        logger.exception(
                            "committed graph events await startup journal reconciliation",
                            exc_info=retry_error,
                        )
                if self._command_commit_observer is not None:
                    await self._command_commit_observer(
                        "after_commit",
                        run_id,
                        command_type,
                        tuple(stored_events),
                    )
            except Exception:
                await session.rollback()
                raise

        if self._dispatcher is not None and self._auto_dispatch and outbox_items:
            await self._dispatcher.dispatch_pending()

        return GraphCommandResult(
            events=stored_events,
            outbox_items=outbox_items,
            projection_position=expected_position + len(stored_events),
        )

    async def _validate_semantic_artifact_references(
        self,
        command_type: str,
        command_payload: dict[str, object],
        projection: GraphProjection,
    ) -> dict[str, object]:
        """Replace caller-supplied evidence with controller-derived artifact proof."""
        if command_type not in {
            "submit_callback",
            "stage_runner_submission",
            "finalize_runner_execution",
        }:
            return command_payload
        output = dict(command_payload)
        container_key = (
            "callback_payload" if command_type == "finalize_runner_execution" else "payload"
        )
        raw_container = output.get(container_key)
        if not isinstance(raw_container, dict):
            return output
        container = dict(cast(dict[str, object], raw_container))
        raw_records = container.get("output_records")
        if not isinstance(raw_records, list):
            return output
        declarations = semantic_schema_declarations_view(projection)
        records: list[object] = []
        for raw_record in cast(list[object], raw_records):
            if not isinstance(raw_record, dict):
                records.append(raw_record)
                continue
            typed_raw_record = cast(dict[str, object], raw_record)
            if typed_raw_record.get("record_type") != "semantic_artifact":
                records.append(typed_raw_record)
                continue
            record = dict(typed_raw_record)
            raw_value = record.get("value")
            if not isinstance(raw_value, dict):
                records.append(record)
                continue
            value = dict(cast(dict[str, object], raw_value))
            # Validation evidence is controller-owned. Never trust a runner's
            # structurally similar object, even when no artifact store exists.
            value.pop("artifact_validation", None)
            raw_ref = value.get("artifact_ref")
            if not isinstance(raw_ref, dict) or self._artifact_store is None:
                record["value"] = value
                records.append(record)
                continue
            try:
                ref = StoredArtifactRef.model_validate(raw_ref)
                if ref.media_type != "application/json":
                    raise ValueError("referenced semantic artifact must use application/json")
                content = await self._artifact_store.read(ref)
                decoded = json.loads(content.decode(ref.encoding or "utf-8"))
                if not isinstance(decoded, dict):
                    raise ValueError("referenced semantic artifact JSON must contain an object")
            except (
                ArtifactIntegrityError,
                ArtifactNotFoundError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ):
                record["value"] = value
                records.append(record)
                continue
            schema_id = value.get("schema_id")
            schema_version = value.get("schema_version")
            declaration = (
                declarations.get((schema_id, schema_version))
                if isinstance(schema_id, str)
                and isinstance(schema_version, int)
                and not isinstance(schema_version, bool)
                else None
            )
            if declaration is not None:
                value["artifact_validation"] = {
                    "declaration_record_id": declaration.record_id,
                    "content_hash": ref.content_hash,
                    "validated_json": decoded,
                }
            record["value"] = value
            records.append(record)
        container["output_records"] = records
        output[container_key] = container
        return output

    async def current_position(self, run_id: str) -> int:
        """Return the current durable graph position for a run."""
        async with self._session_factory() as session:
            return await GraphEventStore(session).current_position(run_id)

    async def record_node_usage(
        self,
        context: GraphDispatchContext,
        usage: Sequence[ModelTokenUsage],
        *,
        num_actions: int = 0,
    ) -> GraphCommandResult:
        """Record immutable per-model usage facts for one graph execution."""
        if not usage:
            return GraphCommandResult(
                events=[],
                outbox_items=[],
                projection_position=await self.current_position(context.run_id),
            )
        profile = context.node_payload.get("profile")
        payload: dict[str, object] = {
            "node_id": context.node_id,
            "node_kind": context.node_kind,
            "node_role": context.node_role or None,
            "profile": profile if isinstance(profile, str) else None,
            "execution_id": context.execution_id,
            "num_actions": num_actions,
            "usage": [item.model_dump(mode="json") for item in usage],
        }
        delay_seconds = 0.1
        for attempt in range(MAX_NODE_USAGE_WRITE_RETRIES + 1):
            position = await self.current_position(context.run_id)
            try:
                return await self.handle_command(
                    context.run_id,
                    position,
                    "record_node_usage",
                    payload,
                )
            except StaleProjectionError:
                if attempt >= MAX_NODE_USAGE_WRITE_RETRIES:
                    raise
            except OperationalError as exc:
                if (
                    not is_retriable_sqlite_write_conflict(exc)
                    or attempt >= MAX_NODE_USAGE_WRITE_RETRIES
                ):
                    raise
            await asyncio.sleep(delay_seconds * (attempt + 1))
        raise StaleProjectionError(f"graph usage write retry loop exhausted: {context.run_id}")

    async def read_projection(self, run_id: str) -> GraphProjection:
        """Return the current projection through the bounded runtime checkpoint."""
        async with self._session_factory() as session:
            projection, _, _ = await GraphEventStore(session).load_projection_with_tail(run_id)
        return projection

    def _add_dispatch_intent_events(
        self,
        events: list[EventEnvelope],
        command_type: str,
        run_id: str,
    ) -> list[EventEnvelope]:
        """Normalize lease grants into explicit side-effect-intent events.

        The current pure kernel grants leases during ``schedule_tick``. This
        runtime layer adds the PRD §12.3 ``agent_dispatch_requested`` event next
        to each grant, then the outbox mapping keys dispatch by that event id.
        """
        expanded: list[EventEnvelope] = []
        for event in events:
            expanded.append(event)
            if event.event_type != "lease_granted":
                continue
            node_id = event.payload.get("node_id")
            raw_resource_claims = event.payload.get("resource_claims", [])
            resource_claims = (
                [
                    AgentDispatchResourceClaim.model_validate(claim).model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                    for claim in cast(list[object], raw_resource_claims)
                ]
                if isinstance(raw_resource_claims, list)
                else raw_resource_claims
            )
            validate_emitted_event_type("graph_runtime_controller", "agent_dispatch_requested")
            expanded.append(
                EventEnvelope(
                    event_id=self._id_gen.next_id("event"),
                    run_id=run_id,
                    position=-1,
                    event_type="agent_dispatch_requested",
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    causation_id=command_type,
                    correlation_id=str(node_id) if isinstance(node_id, str) else None,
                    timestamp=self._clock.now(),
                    payload=serialize_event_payload(
                        "agent_dispatch_requested",
                        {
                            "lease_granted_event_id": event.event_id,
                            "lease_id": event.payload.get("lease_id"),
                            "node_id": node_id,
                            "generation": event.payload.get("generation"),
                            "execution_id": event.payload.get("execution_id"),
                            "base_snapshot_id": event.payload.get("base_snapshot_id"),
                            "resource_claims": resource_claims,
                            "cache_authority_hash": event.payload.get("cache_authority_hash"),
                        },
                    ),
                )
            )
        return expanded


def rebuild_projection(events: list[EventEnvelope]) -> GraphProjection:
    return build_projection(events)


def _patch_base_graph_position(
    command_type: str,
    payload: dict[str, object],
) -> int | None:
    if command_type == "finalize_runner_execution":
        value = payload.get("decision_base_graph_position")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return None
    if command_type == "stage_runner_submission":
        value = payload.get("observed_graph_position")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return None
    if command_type != "submit_patch":
        return None
    value = payload.get("base_graph_position")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _reconciled_committed_patch(
    projection: GraphProjection,
    command_type: str,
    payload: dict[str, object],
    context: PatchCommandContext,
) -> tuple[str, tuple[str, ...]] | None:
    """Recognize an identical durable patch after its acknowledgement was lost."""

    if command_type != "submit_patch":
        return None
    try:
        command = SubmitPatchCommand.model_validate(payload)
    except ValueError:
        return None
    operation_key = submit_patch_operation_key(command)
    proposed_by_node_id = context.proposed_by_node_id
    decisions = [
        decision
        for decision in planner_patch_decisions_by_id_view(projection).values()
        if decision.status == "accepted"
        and (decision.operation_key or decision.patch_id) == operation_key
        and decision.proposed_by_node_id == proposed_by_node_id
    ]
    if not decisions:
        return None
    if len(decisions) != 1:
        raise PatchOperationConflictError(
            f"semantic patch operation {operation_key!r} has multiple durable decisions"
        )
    decision = decisions[0]
    fingerprint = submit_patch_operation_fingerprint(command)
    if decision.operation_fingerprint != fingerprint:
        raise PatchOperationConflictError(
            f"semantic patch operation {operation_key!r} was already committed with different intent"
        )
    return decision.patch_id, tuple(decision.successor_planner_node_ids)
