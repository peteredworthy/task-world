"""Evidence digest presenter helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from orchestrator.api.presenters.runs import RunMetricSummary, compute_run_metrics
from orchestrator.api.schemas.runs import (
    RepresentativeNodeEvidence,
    RunEvidenceDigestMetrics,
    RunEvidenceDigestResponse,
    RunEvidenceDigestRunSummary,
    RunEvidenceDigestScheduler,
)
from orchestrator.graph import (
    EventEnvelope,
    GraphProjection,
    SchedulerView,
    build_projection,
    project_decision_view,
    project_lease_view,
    project_node_metadata,
    project_node_states,
    project_scheduler_view,
)
from orchestrator.state import Run


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _task_status_counts(run: Run) -> dict[str, int]:
    counts: dict[str, int] = {}
    for step in run.steps:
        for task in step.tasks:
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
    return counts


def _graph_event_count(events: list[EventEnvelope]) -> int:
    if not events:
        return 0
    return max(event.position for event in events)


def _node_creation_payloads(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type != "node_created":
            continue
        node_id = event.payload.get("node_id")
        if isinstance(node_id, str):
            payloads[node_id] = dict(event.payload)
    return payloads


def _node_evidence_summary(
    node_id: str,
    events: Iterable[EventEnvelope],
    state: str | None,
    *,
    evidence_complete: bool = True,
    associated_lease_ids: frozenset[str] | None = None,
) -> str:
    output_records = 0
    file_state_records = 0
    state_changes = 0
    latest_leases: dict[str, tuple[int, str, int | None]] = {}
    proven_lease_ids = set(associated_lease_ids or ())

    if associated_lease_ids is None:
        # Full-event callers have no bounded store DTO.  Establish ownership
        # only from canonical grant identities before accepting node-less
        # terminal facts; never infer it from another representative's lease.
        proven_lease_ids.update(
            str(event.payload["lease_id"])
            for event in events
            if event.event_type == "lease_granted"
            and event.payload.get("node_id") == node_id
            and isinstance(event.payload.get("lease_id"), str)
        )

    for event in events:
        payload = event.payload
        if (
            event.event_type == "output_record_accepted"
            and payload.get("producer_node_id") == node_id
        ):
            output_records += 1
        elif (
            event.event_type == "file_state_accepted" and payload.get("producer_node_id") == node_id
        ):
            file_state_records += 1
        elif event.event_type == "node_state_changed" and payload.get("node_id") == node_id:
            state_changes += 1
        elif event.event_type in {
            "lease_granted",
            "lease_renewed",
            "lease_suspended",
            "lease_released",
            "lease_revoked",
            "lease_expired",
        }:
            lease_id = payload.get("lease_id")
            if not isinstance(lease_id, str):
                continue
            event_node_id = payload.get("node_id")
            if event_node_id != node_id and lease_id not in proven_lease_ids:
                continue
            generation = payload.get("generation")
            previous = latest_leases.get(lease_id)
            if previous is None or event.position > previous[0]:
                latest_leases[lease_id] = (
                    event.position,
                    event.event_type,
                    generation if isinstance(generation, int) else None,
                )

    parts = [f"state={state or 'unknown'}"]
    if not evidence_complete:
        parts.append("lease=unavailable")
    elif not latest_leases:
        parts.append("lease=no-active")
    else:
        latest_values = tuple(latest_leases.values())
        active = [
            value for value in latest_values if value[1] in {"lease_granted", "lease_renewed"}
        ]
        suspended = [value for value in latest_values if value[1] == "lease_suspended"]
        terminal = [
            value
            for value in latest_values
            if value[1] in {"lease_released", "lease_revoked", "lease_expired"}
        ]
        if active:
            lease_state = "active"
            latest = max(active)
        elif suspended:
            lease_state = "suspended"
            latest = max(suspended)
        elif terminal:
            lease_state = "terminal"
            latest = max(terminal)
        else:
            lease_state = "no-active"
            latest = None
        parts.append(f"lease={lease_state}")
        if latest is not None and latest[2] is not None:
            parts.append(f"generation={latest[2]}")
    parts.append(f"outputs={output_records}")
    parts.append(f"file_state={file_state_records}")
    parts.append(f"state_changes={state_changes}")
    return "; ".join(parts)


def _node_blockers(
    node_id: str,
    scheduler_view: SchedulerView,
    decision_blockers: list[str],
) -> list[str]:
    blockers: list[str] = []

    for bucket_name in ("blocked", "waiting_resources", "waiting_gates"):
        for entry in scheduler_view.get(bucket_name, []):
            if entry.get("node_id") == node_id:
                reason = entry.get("reason")
                if isinstance(reason, str) and reason:
                    blockers.append(f"scheduler:{bucket_name}:{reason}")

    for blocker in decision_blockers:
        if blocker.startswith(f"{node_id}:"):
            blockers.append(f"graph_review:{blocker.removeprefix(f'{node_id}:').strip()}")

    return _dedupe(blockers)


def _representative_nodes(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection,
    scheduler_view: SchedulerView,
    decision_blockers: list[str],
    max_nodes: int,
    include_node_evidence: bool,
    evidence_by_node: dict[str, tuple[EventEnvelope, ...]] | None = None,
    associated_lease_ids_by_node: dict[str, frozenset[str]] | None = None,
    partial_evidence_node_ids: frozenset[str] = frozenset(),
    projection_available: bool = True,
) -> list[RepresentativeNodeEvidence]:
    node_states = project_node_states(events, projection=projection)
    if not node_states:
        return []

    node_metadata = project_node_metadata(events, projection=projection)
    creation_payloads = _node_creation_payloads(events)
    if evidence_by_node is not None:
        creation_payloads.update(
            _node_creation_payloads(
                [event for node_events in evidence_by_node.values() for event in node_events]
            )
        )

    entries: list[RepresentativeNodeEvidence] = []
    for node_id in sorted(node_states)[:max_nodes]:
        metadata = node_metadata.get(node_id, {})
        payload = creation_payloads.get(node_id, {})
        title = payload.get("title")
        if not isinstance(title, str) or not title:
            title = payload.get("task_id") if isinstance(payload.get("task_id"), str) else node_id
        state = node_states.get(node_id)
        blockers = _node_blockers(
            node_id,
            scheduler_view,
            decision_blockers,
        )
        entries.append(
            RepresentativeNodeEvidence(
                node_id=node_id,
                state=state,
                role=metadata.get("role") if isinstance(metadata.get("role"), str) else None,
                title=title if isinstance(title, str) else node_id,
                evidence_summary=(
                    _node_evidence_summary(
                        node_id,
                        evidence_by_node.get(node_id, ())
                        if evidence_by_node is not None
                        else events,
                        state,
                        evidence_complete=node_id not in partial_evidence_node_ids,
                        associated_lease_ids=(
                            associated_lease_ids_by_node.get(node_id)
                            if associated_lease_ids_by_node is not None
                            else None
                        ),
                    )
                    if include_node_evidence
                    else None
                ),
                evidence_status=(
                    "not_requested"
                    if not include_node_evidence
                    else "unavailable"
                    if not projection_available
                    else "partial"
                    if node_id in partial_evidence_node_ids
                    else "complete"
                ),
                blockers=blockers,
            )
        )

    return entries


def _representative_nodes_from_read_model(
    node_summaries: tuple[dict[str, str | None], ...],
    *,
    include_node_evidence: bool,
    evidence_by_node: dict[str, tuple[EventEnvelope, ...]],
    partial_evidence_node_ids: frozenset[str],
    associated_lease_ids_by_node: dict[str, frozenset[str]] | None = None,
) -> list[RepresentativeNodeEvidence]:
    creation_payloads = _node_creation_payloads(
        [event for node_events in evidence_by_node.values() for event in node_events]
    )
    entries: list[RepresentativeNodeEvidence] = []
    for summary in node_summaries:
        node_id = summary["node_id"]
        assert node_id is not None
        state = summary.get("state")
        creation = creation_payloads.get(node_id, {})
        title = creation.get("title")
        if not isinstance(title, str) or not title:
            title = creation.get("task_id") if isinstance(creation.get("task_id"), str) else node_id
        reason = summary.get("deferred_reason")
        blockers: list[str] = []
        if isinstance(reason, str):
            bucket = (
                "waiting_resources"
                if reason.startswith("resource_conflict")
                else "waiting_gates"
                if reason.startswith("gate_not_approved")
                else "blocked"
            )
            blockers.append(f"scheduler:{bucket}:{reason}")
        entries.append(
            RepresentativeNodeEvidence(
                node_id=node_id,
                state=state,
                role=summary.get("role"),
                title=title,
                evidence_summary=(
                    _node_evidence_summary(
                        node_id,
                        evidence_by_node.get(node_id, ()),
                        state,
                        evidence_complete=node_id not in partial_evidence_node_ids,
                        associated_lease_ids=(
                            associated_lease_ids_by_node.get(node_id)
                            if associated_lease_ids_by_node is not None
                            else None
                        ),
                    )
                    if include_node_evidence
                    else None
                ),
                evidence_status=(
                    "not_requested"
                    if not include_node_evidence
                    else "partial"
                    if node_id in partial_evidence_node_ids
                    else "complete"
                ),
                blockers=blockers,
            )
        )
    return entries


def build_run_evidence_digest_response(
    run: Run,
    events: list[EventEnvelope],
    *,
    pending_actions: list[dict[str, Any]] | None = None,
    max_nodes: int = 3,
    include_node_evidence: bool = True,
    generated_at: datetime | None = None,
    projection: GraphProjection | None = None,
    graph_event_count: int | None = None,
    evidence_by_node: dict[str, tuple[EventEnvelope, ...]] | None = None,
    associated_lease_ids_by_node: dict[str, frozenset[str]] | None = None,
    partial_evidence_node_ids: frozenset[str] = frozenset(),
    projection_available: bool = True,
    read_model_nodes: tuple[dict[str, str | None], ...] | None = None,
    read_model_scheduler: tuple[int, int, int, int, int, int] | None = None,
    read_model_blockers: tuple[str, ...] = (),
) -> RunEvidenceDigestResponse:
    """Build a bounded evidence digest from the run and graph projections."""
    event_count = graph_event_count if graph_event_count is not None else _graph_event_count(events)
    is_graph_backed = event_count > 0
    metrics: RunMetricSummary = compute_run_metrics(run)
    pending_actions = pending_actions or []

    scheduler = RunEvidenceDigestScheduler(
        graph_event_count=event_count if is_graph_backed else 0,
        ready_count=0,
        blocked_count=0,
        waiting_resource_count=0,
        waiting_gate_count=0,
        active_lease_count=0,
        suspended_lease_count=0,
    )
    blockers: list[str] = []
    representative_nodes: list[RepresentativeNodeEvidence] = []

    if is_graph_backed and read_model_nodes is not None and read_model_scheduler is not None:
        (
            ready_count,
            blocked_count,
            waiting_resource_count,
            waiting_gate_count,
            active_lease_count,
            suspended_lease_count,
        ) = read_model_scheduler
        scheduler = RunEvidenceDigestScheduler(
            graph_event_count=event_count,
            ready_count=ready_count,
            blocked_count=blocked_count,
            waiting_resource_count=waiting_resource_count,
            waiting_gate_count=waiting_gate_count,
            active_lease_count=active_lease_count,
            suspended_lease_count=suspended_lease_count,
        )
        if run.pause_reason:
            blockers.append(f"pause_reason:{run.pause_reason}")
        if run.last_error:
            blockers.append(f"last_error:{run.last_error}")
        blockers.extend(read_model_blockers)
        representative_nodes = _representative_nodes_from_read_model(
            read_model_nodes,
            include_node_evidence=include_node_evidence,
            evidence_by_node=evidence_by_node or {},
            partial_evidence_node_ids=partial_evidence_node_ids,
            associated_lease_ids_by_node=associated_lease_ids_by_node,
        )
    elif is_graph_backed and projection_available:
        # Fold the event stream a single time and reuse the projection across
        # every view below, instead of each project_* call re-folding from
        # scratch (an O(n^2) full replay per call).
        projection = projection if projection is not None else build_projection(events)
        scheduler_view = project_scheduler_view(events, projection=projection)
        lease_view = project_lease_view(events, projection=projection)
        decision_view = project_decision_view(events, projection=projection)
        scheduler = RunEvidenceDigestScheduler(
            graph_event_count=event_count,
            ready_count=len(scheduler_view["ready"]),
            blocked_count=len(scheduler_view["blocked"]),
            waiting_resource_count=len(scheduler_view["waiting_resources"]),
            waiting_gate_count=len(scheduler_view["waiting_gates"]),
            active_lease_count=len(lease_view["active"]),
            suspended_lease_count=len(lease_view["suspended"]),
        )

        if run.pause_reason:
            blockers.append(f"pause_reason:{run.pause_reason}")
        if run.last_error:
            blockers.append(f"last_error:{run.last_error}")
        blockers.extend(
            f"scheduler:{bucket}:{entry['node_id']}:{entry['reason']}"
            for bucket in ("blocked", "waiting_resources", "waiting_gates")
            for entry in scheduler_view[bucket]
        )
        blockers.extend(
            f"graph_review:{blocker}" for blocker in decision_view["review"]["blockers"]
        )

        representative_nodes = _representative_nodes(
            events,
            projection=projection,
            scheduler_view=scheduler_view,
            decision_blockers=decision_view["review"]["blockers"],
            max_nodes=max_nodes,
            include_node_evidence=include_node_evidence,
            evidence_by_node=evidence_by_node,
            associated_lease_ids_by_node=associated_lease_ids_by_node,
            partial_evidence_node_ids=partial_evidence_node_ids,
            projection_available=projection_available,
        )
    else:
        if run.pause_reason:
            blockers.append(f"pause_reason:{run.pause_reason}")
        if run.last_error:
            blockers.append(f"last_error:{run.last_error}")

    for action in pending_actions:
        action_type = action.get("action_type")
        if isinstance(action_type, str) and action_type in {"approval", "clarification"}:
            blockers.append(f"pending_action:{action_type}")

    summary = RunEvidenceDigestRunSummary(
        routine_id=run.routine_id,
        repo_name=run.repo_name,
        current_step_index=run.current_step_index,
        step_count=len(run.steps),
        task_count=sum(len(step.tasks) for step in run.steps),
        task_status_counts=_task_status_counts(run),
        pause_reason=run.pause_reason,
        last_error=run.last_error,
    )

    return RunEvidenceDigestResponse(
        run_id=run.id,
        status=run.status.value,
        execution_mode=run.execution_mode,
        is_graph_backed=is_graph_backed,
        graph_facts_status=(
            "partial"
            if is_graph_backed and read_model_nodes is not None
            else "complete"
            if is_graph_backed and projection_available
            else "unavailable"
        ),
        generated_at=generated_at or _now(),
        run_summary=summary,
        blockers=_dedupe(blockers),
        scheduler=scheduler,
        representative_nodes=representative_nodes,
        metrics=RunEvidenceDigestMetrics(
            total_tokens_read=metrics.total_tokens_read,
            total_tokens_write=metrics.total_tokens_write,
            total_tokens_cache=metrics.total_tokens_cache,
            total_duration_ms=metrics.total_duration_ms,
            total_num_actions=metrics.total_num_actions,
            estimated_cost_usd=metrics.estimated_cost_usd,
            token_usage_by_model_count=len(metrics.token_usage_by_model),
        ),
    )
