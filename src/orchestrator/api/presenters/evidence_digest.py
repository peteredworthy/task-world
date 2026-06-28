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
    SchedulerView,
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


def _node_evidence_summary(node_id: str, events: list[EventEnvelope], state: str | None) -> str:
    output_records = 0
    file_state_records = 0
    state_changes = 0
    lease_state = None
    lease_generation = None

    for event in events:
        payload = event.payload
        if event.event_type == "output_record_accepted" and payload.get("producer_node_id") == node_id:
            output_records += 1
        elif event.event_type == "file_state_accepted" and payload.get("producer_node_id") == node_id:
            file_state_records += 1
        elif event.event_type == "node_state_changed" and payload.get("node_id") == node_id:
            state_changes += 1
        elif event.event_type == "lease_granted" and payload.get("node_id") == node_id:
            lease_state = "active"
            generation = payload.get("generation")
            if isinstance(generation, int):
                lease_generation = generation
        elif event.event_type == "lease_suspended" and payload.get("node_id") == node_id:
            lease_state = "suspended"

    parts = [f"state={state or 'unknown'}"]
    if lease_state is not None:
        parts.append(f"lease={lease_state}")
    if lease_generation is not None:
        parts.append(f"generation={lease_generation}")
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
    max_nodes: int,
    include_node_evidence: bool,
) -> list[RepresentativeNodeEvidence]:
    if not events:
        return []

    node_states = project_node_states(events)
    if not node_states:
        return []

    node_metadata = project_node_metadata(events)
    scheduler_view = project_scheduler_view(events)
    decision_view = project_decision_view(events)
    creation_payloads = _node_creation_payloads(events)

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
            decision_view["review"]["blockers"],
        )
        entries.append(
            RepresentativeNodeEvidence(
                node_id=node_id,
                state=state,
                role=metadata.get("role") if isinstance(metadata.get("role"), str) else None,
                title=title if isinstance(title, str) else node_id,
                evidence_summary=(
                    _node_evidence_summary(node_id, events, state)
                    if include_node_evidence
                    else None
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
) -> RunEvidenceDigestResponse:
    """Build a bounded evidence digest from the run and graph projections."""
    graph_event_count = _graph_event_count(events)
    is_graph_backed = graph_event_count > 0
    metrics: RunMetricSummary = compute_run_metrics(run)
    pending_actions = pending_actions or []

    scheduler = RunEvidenceDigestScheduler(
        graph_event_count=graph_event_count if is_graph_backed else 0,
        ready_count=0,
        blocked_count=0,
        waiting_resource_count=0,
        waiting_gate_count=0,
        active_lease_count=0,
        suspended_lease_count=0,
    )
    blockers: list[str] = []
    representative_nodes: list[RepresentativeNodeEvidence] = []

    if is_graph_backed:
        scheduler_view = project_scheduler_view(events)
        lease_view = project_lease_view(events)
        decision_view = project_decision_view(events)
        scheduler = RunEvidenceDigestScheduler(
            graph_event_count=graph_event_count,
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
        blockers.extend(f"graph_review:{blocker}" for blocker in decision_view["review"]["blockers"])

        representative_nodes = _representative_nodes(
            events,
            max_nodes=max_nodes,
            include_node_evidence=include_node_evidence,
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
