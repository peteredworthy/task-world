from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from orchestrator.graph import (
    PLANNER_OPS,
    Actor,
    ActorKind,
    EventEnvelope,
    GraphProjection,
    initial_projection,
)
from orchestrator.graph import reduce_event
from orchestrator.graph_runtime import GraphDispatchContext, HORIZON_REGION_PURPOSES
from orchestrator.graph_runtime.dispatch import (
    MAX_GRAPH_PROMPT_CHARS,
    _planner_packet,
    _prompt_for_node,
)
from tests.unit.graph_test_utils import canonical_event_payload


def _event(
    event_type: str,
    payload: dict[str, Any],
    position: int,
    run_id: str = "run-planner-packet",
) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"event-{position}",
        run_id=run_id,
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.SCHEDULER),
        causation_id="test",
        correlation_id=None,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )


def _projection(events: list[EventEnvelope]) -> GraphProjection:
    projection = initial_projection()
    for evt in sorted(events, key=lambda item: item.position):
        projection = reduce_event(projection, evt)
    return projection


def _planner_context(events: list[EventEnvelope]) -> GraphDispatchContext:
    projection = _projection(events)
    return GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="planner-1",
        node_kind="planner",
        node_payload={
            "node_id": "planner-1",
            "kind": "planner",
            "role": "planner",
            "title": "Plan region one",
            "task_context": "Plan successor nodes.",
            "task_region_id": "region-1",
            "generation_index": 2,
        },
        requirements=[
            "REQ-1: Keep graph state complete.",
            "REQ-2: Bound evidence before planning.",
        ],
        worktree_path="/tmp/worktree",
        lease_id="lease-planner-1",
        lease_generation=3,
        execution_id="exec-1",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-1",
        graph_projection=projection,
        graph_events=events,
    )


def _gap_planner_context(events: list[EventEnvelope]) -> GraphDispatchContext:
    projection = _projection(events)
    return GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="planner-1",
        node_kind="planner",
        node_role="gap_planner",
        node_payload={
            "node_id": "planner-1",
            "kind": "planner",
            "role": "gap_planner",
            "title": "Find remaining gaps",
            "task_context": "Compare accepted work to intent.",
            "task_region_id": "gap-analysis-region",
            "corrective_work_region": "corrective_work_region",
        },
        requirements=[
            "REQ-1: Keep graph state complete.",
            "REQ-2: Bound evidence before planning.",
        ],
        worktree_path="/tmp/worktree",
        lease_id="lease-gap-planner-1",
        lease_generation=3,
        execution_id="exec-gap",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-gap",
        graph_projection=projection,
        graph_events=events,
    )


def _graph_events() -> list[EventEnvelope]:
    return [
        _event("run_lifecycle_changed", {"to_state": "active"}, 1),
        _event(
            "node_created",
            {
                "node_id": "root",
                "kind": "root",
                "state": "completed",
                "planner_generation_budget": 8,
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-1",
                "kind": "planner",
                "role": "planner",
                "state": "running",
                "generation_index": 2,
                "task_region_id": "region-1",
                "session_id": "session-1",
            },
            3,
        ),
        _event(
            "session_state_changed",
            {
                "session_id": "session-1",
                "state": "attached",
                "node_id": "planner-1",
                "carryover_record_id": "carryover-1",
            },
            4,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "ready",
                "task_region_id": "region-1",
                "attempt_number": 1,
                "candidate_id": "candidate-1",
            },
            5,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-2",
                "kind": "worker",
                "role": "builder",
                "state": "blocked",
                "task_region_id": "region-1",
                "attempt_number": 1,
                "candidate_id": "candidate-2",
            },
            6,
        ),
        _event(
            "node_deferred",
            {"node_id": "worker-2", "reason": "missing candidate output"},
            7,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-3",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
                "task_region_id": "region-2",
            },
            8,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "blocked",
                "task_region_id": "region-1",
            },
            9,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "planner-1",
                "to_port": "accepted_file_state",
                "edge_id": "edge-fs",
                "record_ids": ["file-state-1"],
                "bound_at_position": 10,
            },
            10,
        ),
        _event(
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "snapshot_id": "snapshot-1",
                "base_snapshot_id": "snapshot-0",
                "producer_node_id": "worker-1",
                "port": "accepted_file_state",
                "tracked": [
                    {
                        "path": "src/orchestrator/example.py",
                        "classification": "source",
                        "source": "tracked",
                        "rejected": False,
                    }
                ],
                "untracked": [
                    {
                        "path": "docs/graph-approach/dynamic-smoke-output.txt",
                        "classification": "artifact",
                        "source": "untracked",
                        "rejected": False,
                    }
                ],
                "ignored": [
                    {
                        "path": f".venv/lib/package-{idx}.py",
                        "classification": "tool_cache",
                        "source": "ignored",
                        "rejected": False,
                    }
                    for idx in range(25)
                ],
                "rejected_paths": [],
            },
            11,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "planner-1",
                "to_port": "region_summary",
                "edge_id": "edge-summary",
                "record_ids": ["summary-1"],
                "bound_at_position": 12,
            },
            12,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "summary-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "region_summary",
                "schema": "RegionSummary",
                "record_type": "analysis_summary",
                "value": {
                    "summary": "region-1 summary",
                    "source_record_ids": ["file-state-1"],
                    "lossy": False,
                    "omitted_details": [],
                },
            },
            13,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-region-1",
                "record_kind": "check_result",
                "record_type": "check_result",
                "producer_node_id": "worker-1",
                "port": "check_result",
                "node_id": "worker-1",
                "task_region_id": "region-1",
                "value": {"classification": "tool_error", "reason": "API timeout"},
            },
            14,
        ),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-beta",
                "proposed_by_node_id": "planner-1",
                "successor_planner_node_ids": ["planner-2"],
                "base_graph_position": 12,
            },
            15,
        ),
        _event(
            "graph_patch_rejected",
            {
                "patch_id": "patch-alpha",
                "proposed_by_node_id": "planner-1",
                "reason": "node_deferred:planner-1",
            },
            16,
        ),
    ]


def test_planner_packet_includes_generation_frontier_evidence_and_rejections() -> None:
    events = _graph_events()
    context = _planner_context(events)
    packet = _planner_packet(context)

    assert packet["planner_generation"] == {"index": 2, "budget": 8}
    assert packet["bound_requirements"] == [
        "REQ-1: Keep graph state complete.",
        "REQ-2: Bound evidence before planning.",
    ]
    assert packet["frontier"]["ready_nodes"] == ["worker-1"]
    assert {
        "node_id": "worker-2",
        "state": "blocked",
        "reason": "missing candidate output",
    } in packet["frontier"]["blocked_or_deferred_nodes"]
    assert any(
        record["record_id"] == "file-state-1" and record["record_kind"] == "file_state"
        for record in packet["evidence"]["bound_records"].get("accepted_file_state", [])
    )
    file_state_record = next(
        record
        for record in packet["evidence"]["bound_records"].get("accepted_file_state", [])
        if record["record_id"] == "file-state-1"
    )
    file_state_payload = file_state_record["record_payload"]
    assert file_state_payload["counts"] == {
        "tracked": 1,
        "untracked": 1,
        "ignored": 25,
        "rejected_paths": 0,
    }
    assert file_state_payload["tracked_paths"] == [
        {
            "path": "src/orchestrator/example.py",
            "classification": "source",
            "source": "tracked",
            "rejected": False,
        }
    ]
    assert file_state_payload["untracked_paths"] == [
        {
            "path": "docs/graph-approach/dynamic-smoke-output.txt",
            "classification": "artifact",
            "source": "untracked",
            "rejected": False,
        }
    ]
    assert "ignored" not in file_state_payload
    assert any(
        record["record_id"] == "summary-1"
        for record in packet["evidence"]["bound_records"].get("region_summary", [])
    )
    assert packet["evidence"]["session_carryover_record_id"] == "carryover-1"
    failures = packet["evidence"]["outstanding_failures"]
    assert len(failures) == 1
    assert failures[0] == {
        "position": 14,
        "node_id": "worker-1",
        "classification": "tool_error",
        "reason": "check tool error while running: check command",
        "task_region_id": "region-1",
        "record_id": "check-region-1",
        "command_text": "check command",
        "stderr_tail": "",
        "exit_code": None,
    }
    assert packet["open_planner_proposals"] == []
    assert packet["accepted_planner_patches"] == [
        {
            "patch_id": "patch-beta",
            "base_graph_position": 12,
            "position": 15,
        }
    ]
    assert packet["patch_rejections"] == [
        {
            "patch_id": "patch-alpha",
            "reason": "node_deferred:planner-1",
            "position": 16,
        }
    ]

    allowed_ops = packet["allowed_patch_operations"]["allowed_ops"]
    assert allowed_ops == sorted(PLANNER_OPS)
    examples = packet["patch_examples"]
    assert examples
    for example in examples:
        # Match PatchEnvelope shape.
        assert "proposed_by_node_id" not in example
        assert "actor_role" not in example
        assert "run_id" not in example
        assert isinstance(example["patch_id"], str)
        assert isinstance(example["ops"], list)
        assert example["base_graph_position"] == 16
        for op in example["ops"]:
            assert op["op"] in PLANNER_OPS

    templates = packet["horizon_region_templates"]
    assert [template["purpose"] for template in templates] == list(HORIZON_REGION_PURPOSES)
    for template in templates:
        assert template["description"]
        assert template["expected_successor_readiness"]
        for op in template["ops"]:
            assert op["op"] in PLANNER_OPS


def test_planner_packet_includes_requirement_freshness_facts() -> None:
    events = [
        *_graph_events(),
        _event(
            "requirement_revision_recorded",
            {"requirement_id": "REQ-1", "version_id": "REQ-1.v1"},
            17,
        ),
        _event(
            "support_evidence_recorded",
            {
                "support_id": "SUP-1",
                "evidence_id": "summary-1",
                "requirement_id": "REQ-1",
                "requirement_version_id": "REQ-1.v1",
            },
            18,
        ),
        _event(
            "requirement_revision_recorded",
            {
                "requirement_id": "REQ-2",
                "version_id": "REQ-2.v1",
                "classification": "semantic",
            },
            19,
        ),
    ]

    packet = _planner_packet(_gap_planner_context(events))

    assert packet["freshness"] == {
        "requirement_freshness": [
            {
                "requirement_id": "REQ-1",
                "active_version_id": "REQ-1.v1",
                "revision_classification": "initial",
                "requires_authority": False,
                "authority_required_reason": None,
                "fresh_support_ids": ["SUP-1"],
                "stale_support_ids": [],
                "unsupported": False,
            },
            {
                "requirement_id": "REQ-2",
                "active_version_id": "REQ-2.v1",
                "revision_classification": "semantic",
                "requires_authority": True,
                "authority_required_reason": "semantic",
                "fresh_support_ids": [],
                "stale_support_ids": [],
                "unsupported": True,
            },
        ],
        "unsupported_requirement_ids": ["REQ-2"],
        "stale_support_ids": [],
        "authority_required_requirement_ids": ["REQ-2"],
    }


def test_planner_packet_deterministic_ordering_and_projection_neutral_event_tolerance() -> None:
    base_events = _graph_events()
    base_context = _planner_context(base_events)
    base_packet = _planner_packet(base_context)

    shuffled_events = [
        base_events[10],
        base_events[0],
        base_events[6],
        base_events[4],
        base_events[1],
        base_events[11],
        base_events[15],
        base_events[13],
        base_events[2],
        base_events[8],
        base_events[5],
        base_events[12],
        base_events[7],
        base_events[9],
        base_events[3],
        base_events[14],
    ]
    shuffled_context = _planner_context(shuffled_events)
    shuffled_packet = _planner_packet(shuffled_context)

    assert base_packet["open_planner_proposals"] == shuffled_packet["open_planner_proposals"]
    assert base_packet["accepted_planner_patches"] == shuffled_packet["accepted_planner_patches"]
    assert base_packet["patch_rejections"] == shuffled_packet["patch_rejections"]
    assert base_packet["frontier"]["ready_nodes"] == shuffled_packet["frontier"]["ready_nodes"]
    assert (
        base_packet["frontier"]["blocked_or_deferred_nodes"]
        == shuffled_packet["frontier"]["blocked_or_deferred_nodes"]
    )

    with_projection_neutral_event = [
        *shuffled_events,
        _event(
            "outbox_requeued",
            {
                "run_id": "run-planner-packet",
                "outbox_id": 1,
                "event_id": "event-1",
                "kind": "dispatch",
                "previous_status": "failed",
                "previous_attempts": 1,
                "previous_last_error": "transient failure",
                "operator": "test",
                "graph_position": 16,
            },
            -1,
        ),
    ]
    noisy_context = _planner_context(with_projection_neutral_event)
    assert _planner_packet(noisy_context) == shuffled_packet


def test_projection_rejects_unknown_event_type() -> None:
    unknown_event = EventEnvelope(
        event_id="event-unknown",
        run_id="run-planner-packet",
        position=1,
        event_type="mystery_signal",
        schema_version=1,
        actor=Actor(kind=ActorKind.SCHEDULER),
        causation_id="test",
        correlation_id=None,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"text": "deliberately noncanonical"},
    )

    with pytest.raises(
        ValueError,
        match="unsupported graph projection event type: 'mystery_signal'",
    ):
        _projection([unknown_event])


def test_prompt_routing_for_planner_worker_and_verifier() -> None:
    events = _graph_events()
    planner_context = _planner_context(events)
    planner_prompt = _prompt_for_node(planner_context)
    assert "Planner context packet:" in planner_prompt
    assert '"run_id": "run-planner-packet"' in planner_prompt
    assert "Planner mutation contract:" in planner_prompt
    assert "For reliable-plan dependencies" in planner_prompt
    assert "Use [] for the first or only batch" in planner_prompt
    assert "Prefer planner-facing graph macros" in planner_prompt
    assert "Mutate the graph only through submit_graph_patch or macro-backed patch envelopes." in (
        planner_prompt
    )
    assert (
        "Your job is to propose future graph structure, not edit repository files."
        in planner_prompt
    )
    assert (
        "Call plain submit only after submit_graph_patch feedback says the patch was accepted."
        in planner_prompt
    )
    assert "current_graph_position from the packet as base_graph_position" in planner_prompt
    assert "allowed_patch_operations" in planner_prompt
    assert "horizon_region_templates" in planner_prompt
    assert "frontier, evidence, open_planner_proposals" in planner_prompt
    assert "Allowed patch operations:" in planner_prompt
    assert "Standard horizon region templates:" in planner_prompt
    assert "discovery_region" in planner_prompt
    assert "implementation_region" in planner_prompt
    assert "validation_region" in planner_prompt
    assert "gap_analysis_region" in planner_prompt
    assert "corrective_work_region" in planner_prompt
    assert "final_invariant_region" in planner_prompt
    assert "Every required check, including final invariant checks" in planner_prompt
    assert "failed check_result evidence into a gap planner" in planner_prompt
    assert "Compact patch examples:" in planner_prompt
    assert "create_worker_verifier_region" in planner_prompt
    assert "create_successor_planner" in planner_prompt
    assert "create_gap_planner" in planner_prompt
    assert "create_invariant_check" in planner_prompt
    assert "no_safe_mutation_termination" in planner_prompt

    gap_planner_context = _gap_planner_context(events)
    gap_planner_prompt = _prompt_for_node(gap_planner_context)
    assert "Planner context packet:" in gap_planner_prompt
    assert "gap_analysis_contract" in gap_planner_prompt
    assert "corrective_work_region" in gap_planner_prompt
    assert "create_corrective_work_region" in gap_planner_prompt
    assert "no_gap_no_op_patch" in gap_planner_prompt
    assert (
        "Gap planners must call submit_graph_patch even when no corrective mutation is safe"
        in gap_planner_prompt
    )
    assert "use a no-op patch with ops: [] for no-gap decisions" in gap_planner_prompt
    assert "create_successor_planner" not in gap_planner_prompt
    assert "create_gap_planner" not in gap_planner_prompt

    worker_context = GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="worker-1",
        node_kind="worker",
        node_payload={
            "node_id": "worker-1",
            "title": "Implement candidate",
            "task_context": "Build it.",
            "available_tools": ["read_file", "write_file"],
            "authority": {
                "allowed_actions": ["submit_records"],
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["docs/out.md"]}],
            },
        },
        requirements=["REQ-1"],
        worktree_path="/tmp/worktree",
        lease_id="lease-worker-1",
        lease_generation=1,
        execution_id="exec-worker",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-worker",
    )
    worker_prompt = _prompt_for_node(worker_context)
    assert "Planner mutation contract" not in worker_prompt
    assert "submit_graph_patch" not in worker_prompt
    assert "horizon_region_templates" not in worker_prompt
    assert "Standard horizon region templates" not in worker_prompt
    assert "Implement candidate" in worker_prompt
    assert "Build it." in worker_prompt
    assert "worker_authority:" in worker_prompt
    assert '"allowed_actions": ["submit_records"]' in worker_prompt
    assert '"available_tools": ["read_file", "write_file"]' in worker_prompt
    assert '"lease_id": "lease-worker-1"' in worker_prompt
    assert '"paths": ["docs/out.md"]' in worker_prompt
    assert '"worktree_path": "/tmp/worktree"' in worker_prompt

    fallback_dynamic_worker_context = GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="worker-ds-builder",
        node_kind="worker",
        node_payload={
            "node_id": "worker-ds-builder",
            "kind": "worker",
            "role": "builder",
            "task_region_id": "region-ds",
        },
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-fallback-worker",
        lease_generation=1,
        execution_id="exec-fallback-worker",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-fallback-worker",
        graph_events=[
            _event(
                "node_created",
                {
                    "node_id": "routine-snapshot",
                    "kind": "artifact",
                    "state": "completed",
                    "snapshot": {
                        "dynamic_feature": {
                            "feature_spec_path": (
                                "docs/graph-approach/dynamic-smoke-feature-spec.md"
                            ),
                            "feature_spec_content": (
                                "Create docs/graph-approach/dynamic-smoke-output.txt "
                                "for dynamic-smoke."
                            ),
                            "acceptance_command": (
                                'rg -q "dynamic-smoke" docs/graph-approach/dynamic-smoke-output.txt'
                            ),
                            "hidden_oracle_command": (
                                'rg -q "validation-strengthened: true" '
                                "docs/graph-approach/dynamic-smoke-output.txt"
                            ),
                        }
                    },
                },
                1,
            )
        ],
    )
    fallback_dynamic_worker_prompt = _prompt_for_node(fallback_dynamic_worker_context)
    assert "worker-ds-builder" in fallback_dynamic_worker_prompt
    assert "dynamic_feature_spec_path:" in fallback_dynamic_worker_prompt
    assert "dynamic_feature_spec_content:" in fallback_dynamic_worker_prompt
    assert "dynamic_acceptance_command:" in fallback_dynamic_worker_prompt
    assert "dynamic_hidden_oracle_command:" not in fallback_dynamic_worker_prompt
    assert "validation-strengthened" not in fallback_dynamic_worker_prompt
    assert "dynamic_worker_instruction:" in fallback_dynamic_worker_prompt
    assert "Do not work on unrelated repository slices." in fallback_dynamic_worker_prompt

    read_only_context = GraphDispatchContext(
        run_id="run-dynamic",
        node_id="worker-discovery",
        node_kind="worker",
        node_role="discovery",
        node_payload={
            "node_id": "worker-discovery",
            "kind": "worker",
            "role": "discovery",
            "access_mode": "read_only",
            "semantic_stage": "discovery",
            "effect_contract": "read_only_semantic",
        },
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-discovery",
        lease_generation=1,
        execution_id="exec-discovery",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-discovery",
        graph_events=fallback_dynamic_worker_context.graph_events,
    )
    read_only_prompt = _prompt_for_node(read_only_context)
    assert "downstream_acceptance_command:" in read_only_prompt
    assert "dynamic_acceptance_command:" not in read_only_prompt
    assert "do not execute downstream_acceptance_command" in read_only_prompt
    assert "Do not modify repository files" in read_only_prompt

    batch_context = GraphDispatchContext(
        run_id="run-dynamic",
        node_id="worker-batch-1",
        node_kind="worker",
        node_role="implementer",
        node_payload={
            "node_id": "worker-batch-1",
            "kind": "worker",
            "role": "implementer",
            "access_mode": "write",
            "semantic_stage": "effectful_batch",
            "effect_contract": "effectful_write",
            "declared_batch_id": "batch-1",
        },
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-batch-1",
        lease_generation=1,
        execution_id="exec-batch-1",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-batch-1",
        graph_events=fallback_dynamic_worker_context.graph_events,
    )
    batch_prompt = _prompt_for_node(batch_context)
    assert "downstream_acceptance_command:" in batch_prompt
    assert "dynamic_acceptance_command:" not in batch_prompt
    assert "Do not execute or broaden scope" in batch_prompt
    assert "explicit check nodes and the final audit own that evidence" in batch_prompt

    semantic_revision_context = GraphDispatchContext(
        run_id="run-dynamic",
        node_id="worker-semantic-plan-revision",
        node_kind="worker",
        node_role="fixer",
        node_payload={
            "node_id": "worker-semantic-plan-revision",
            "kind": "worker",
            "role": "fixer",
            "access_mode": "write",
            "semantic_stage": "corrective_work",
            "effect_contract": "effectful_write",
            "semantic_schema_id": "reliable-plan-implementation-plan",
            "semantic_schema_version": 1,
            "recovery_of_record_id": "failed-plan-record",
        },
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-semantic-revision",
        lease_generation=1,
        execution_id="exec-semantic-revision",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-semantic-revision",
        graph_events=fallback_dynamic_worker_context.graph_events,
    )
    semantic_revision_prompt = _prompt_for_node(semantic_revision_context)
    assert "submit outputs.semantic_artifact using the declared semantic schema" in (
        semantic_revision_prompt
    )
    assert "Do not modify repository files" in semantic_revision_prompt
    assert "this node repairs the plan artifact" in semantic_revision_prompt

    verifier_events = [
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "task_region_id": "region-1",
                "value": {"summary": "candidate payload"},
            },
            100,
        ),
        _event(
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "snapshot_id": "snapshot-1",
                "base_snapshot_id": "snapshot-0",
                "candidate_id": "candidate-1",
                "task_region_id": "region-1",
                "verdict": "captured",
            },
            101,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            102,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "file_state",
                "record_ids": ["file-state-1"],
            },
            103,
        ),
    ]
    verifier_context = GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="verifier-1",
        node_kind="verifier",
        node_payload={
            "node_id": "verifier-1",
            "title": "Verify candidate",
            "task_region_id": "region-1",
            "candidate_id": "candidate-1",
            "rubric": ["Does it compile?"],
        },
        requirements=["REQ-1"],
        worktree_path="/tmp/worktree",
        lease_id="lease-verifier-1",
        lease_generation=1,
        execution_id="exec-verifier",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-verifier",
        graph_projection=_projection(verifier_events),
        graph_events=verifier_events,
    )
    verifier_prompt = _prompt_for_node(verifier_context)
    assert "Verify task region region-1." in verifier_prompt
    assert "Candidate: candidate-1" in verifier_prompt
    assert "Rubric:" in verifier_prompt
    assert "Verifier context packet:" in verifier_prompt
    assert '"bound_records"' in verifier_prompt
    assert '"candidate_under_test"' in verifier_prompt
    assert '"file-state-1"' in verifier_prompt
    assert '"required_report_schema"' in verifier_prompt
    assert '"candidate_record_ids": ["candidate-1"]' in verifier_prompt
    assert '"file_state_record_ids": ["file-state-1"]' in verifier_prompt
    assert "submit_graph_patch" not in verifier_prompt
    assert "horizon_region_templates" not in verifier_prompt
    assert "Standard horizon region templates" not in verifier_prompt

    summarizer_events = [
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-summary-source",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "candidate details"},
            },
            110,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-summary-source"],
            },
            111,
        ),
    ]
    summarizer_context = GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="summarizer-1",
        node_kind="summarizer",
        node_payload={
            "node_id": "summarizer-1",
            "kind": "summarizer",
            "task_region_id": "region-1",
        },
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-summarizer-1",
        lease_generation=1,
        execution_id="exec-summarizer",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-summarizer",
        graph_projection=_projection(summarizer_events),
        graph_events=summarizer_events,
    )
    summarizer_prompt = _prompt_for_node(summarizer_context)
    assert "Summarizer context packet:" in summarizer_prompt
    assert '"source_records"' in summarizer_prompt
    assert '"candidate-summary-source"' in summarizer_prompt
    assert '"required_summary_schema"' in summarizer_prompt
    assert '"schema": "AnalysisSummary"' in summarizer_prompt
    assert "worker_authority:" not in summarizer_prompt


def _work_contract_json(prompt: str) -> dict[str, Any]:
    for line in prompt.splitlines():
        if line.startswith("work_contract: "):
            return json.loads(line[len("work_contract: ") :])
    raise AssertionError("work_contract line not found in prompt")


def test_worker_prompt_renders_the_full_typed_work_contract() -> None:
    context = GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="worker-contract-1",
        node_kind="worker",
        node_payload={
            "node_id": "worker-contract-1",
            "kind": "worker",
            "title": "Implement candidate",
            "objective": "Ship the bounded worker contract.",
            "access_mode": "write",
            "acceptance": ["Tests pass", "Docs updated"],
            "scope": "src/orchestrator/graph_runtime/",
            "bound_requirement_ids": ["REQ-1"],
            "invariants": ["Never widen repo write authority."],
            "prohibited_actions": ["force_push"],
        },
        requirements=["REQ-1: ship it"],
        worktree_path="/tmp/worktree",
        lease_id="lease-worker-contract-1",
        lease_generation=1,
        execution_id="exec-worker-contract-1",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-worker-contract-1",
    )
    prompt = _prompt_for_node(context)
    assert "work_contract:" in prompt
    work_contract = _work_contract_json(prompt)
    assert work_contract == {
        "objective": "Ship the bounded worker contract.",
        "access_mode": "write",
        "acceptance": ["Tests pass", "Docs updated"],
        "scope": "src/orchestrator/graph_runtime/",
        "bound_requirement_ids": ["REQ-1"],
        "invariants": ["Never widen repo write authority."],
        "prohibited_actions": ["force_push"],
        "bound_requirements": ["REQ-1: ship it"],
    }
    assert prompt.index("work_contract:") < prompt.index("worker_authority:")


def test_worker_prompt_work_contract_omits_absent_optional_fields_and_nulls_mandatory_ones() -> (
    None
):
    context = GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="worker-contract-2",
        node_kind="worker",
        node_payload={
            "node_id": "worker-contract-2",
            "kind": "worker",
        },
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-worker-contract-2",
        lease_generation=1,
        execution_id="exec-worker-contract-2",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-worker-contract-2",
    )
    prompt = _prompt_for_node(context)
    work_contract = _work_contract_json(prompt)
    assert work_contract == {"objective": None, "access_mode": None, "acceptance": None}


def test_worker_prompt_no_longer_renders_retired_loose_node_keys() -> None:
    retired = {
        "corrective_requirement": "sentinel-corrective-requirement",
        "corrective_evidence_required": "sentinel-corrective-evidence-required",
        "expected_gap": "sentinel-expected-gap",
        "expected_artifact": "sentinel-expected-artifact",
        "feature_spec_path": "sentinel-feature-spec-path",
        "acceptance_command": "sentinel-acceptance-command",
        "expected_outputs": ["sentinel-expected-outputs"],
    }
    context = GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="worker-contract-3",
        node_kind="worker",
        node_payload={
            "node_id": "worker-contract-3",
            "kind": "worker",
            **retired,
        },
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-worker-contract-3",
        lease_generation=1,
        execution_id="exec-worker-contract-3",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-worker-contract-3",
    )
    prompt = _prompt_for_node(context)
    for key, value in retired.items():
        assert key not in prompt
        if isinstance(value, str):
            assert value not in prompt
        else:
            for item in value:
                assert item not in prompt


def test_check_node_prompt_has_no_work_contract_section() -> None:
    context = GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="check-1",
        node_kind="check",
        node_payload={
            "node_id": "check-1",
            "kind": "check",
        },
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-check-1",
        lease_generation=1,
        execution_id="exec-check-1",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-check-1",
    )
    prompt = _prompt_for_node(context)
    assert "work_contract:" not in prompt


def test_worker_prompt_work_contract_renders_resolved_bound_requirements() -> None:
    context = GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="worker-contract-4",
        node_kind="worker",
        node_payload={
            "node_id": "worker-contract-4",
            "kind": "worker",
            "bound_requirement_ids": ["REQ-1"],
        },
        requirements=["REQ-1: the bound requirement text"],
        worktree_path="/tmp/worktree",
        lease_id="lease-worker-contract-4",
        lease_generation=1,
        execution_id="exec-worker-contract-4",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-worker-contract-4",
    )
    prompt = _prompt_for_node(context)
    work_contract = _work_contract_json(prompt)
    assert work_contract["bound_requirement_ids"] == ["REQ-1"]
    assert work_contract["bound_requirements"] == ["REQ-1: the bound requirement text"]


def test_verifier_prompt_is_bounded_for_oversized_rubric() -> None:
    context = GraphDispatchContext(
        run_id="run-planner-packet",
        node_id="verifier-huge",
        node_kind="verifier",
        node_payload={
            "node_id": "verifier-huge",
            "task_region_id": "region-huge",
            "candidate_id": "candidate-huge",
            "rubric": [{"requirement": "x" * 2_000_000}],
        },
        requirements=["REQ-1"],
        worktree_path="/tmp/worktree",
        lease_id="lease-verifier-huge",
        lease_generation=1,
        execution_id="exec-verifier-huge",
        base_snapshot_id="snapshot-0",
        dispatch_event_id="dispatch-verifier-huge",
    )

    prompt = _prompt_for_node(context)

    assert len(prompt) <= MAX_GRAPH_PROMPT_CHARS
    assert "Rubric:" in prompt
    assert '"truncated": true' in prompt
    assert "original_chars" in prompt


def test_planner_packet_includes_dynamic_feature_inputs() -> None:
    context = _planner_context(_graph_events())
    context.node_payload["dynamic_feature"] = {
        "feature_spec_path": "docs/graph-approach/dynamic-smoke-feature-spec.md",
        "feature_spec_content": "Build the dynamic-smoke artifact.",
        "acceptance_command": "uv run pytest tests/smoke -q",
        "hidden_oracle_command": "uv run pytest tests/oracle -q",
        "patch_budget": 4,
        "gap_policy_profile": "standard",
    }
    context.node_payload["task_context"] = (
        "Plan regions for docs/graph-approach/dynamic-smoke-feature-spec.md"
    )

    packet = _planner_packet(context)
    prompt = _prompt_for_node(context)

    assert packet["dynamic_feature"]["feature_spec_path"] == (
        "docs/graph-approach/dynamic-smoke-feature-spec.md"
    )
    assert packet["dynamic_feature"]["feature_spec_content"] == (
        "Build the dynamic-smoke artifact."
    )
    assert "hidden_oracle_command" not in packet["dynamic_feature"]
    assert packet["dynamic_feature"]["hidden_oracle_binding"] == ("dynamic_feature_hidden_oracle")
    assert packet["active_intent"]["context"] == (
        "Plan regions for docs/graph-approach/dynamic-smoke-feature-spec.md"
    )
    assert "If dynamic_feature is present" in prompt
    assert "uv run pytest tests/oracle -q" not in prompt
    assert "dynamic_feature_hidden_oracle" in prompt


def test_planner_packet_marks_absent_hidden_oracle_binding_unavailable() -> None:
    context = _planner_context(_graph_events())
    context.node_payload["dynamic_feature"] = {
        "feature_spec_content": "Build the dynamic-smoke artifact.",
        "acceptance_command": "uv run pytest tests/smoke -q",
        "hidden_oracle_command": "",
    }
    packet = _planner_packet(context)

    assert packet["dynamic_feature"]["hidden_oracle_binding"] == "unavailable"
    assert packet["dynamic_feature"]["available_check_bindings"] == ["dynamic_feature_acceptance"]


def test_unavailable_hidden_oracle_prompt_requires_batch_command_definition() -> None:
    context = _planner_context(_graph_events())
    context.node_payload["dynamic_feature"] = {
        "feature_spec_content": "Build the dynamic-smoke artifact.",
        "acceptance_command": "uv run pytest tests/smoke -q",
        "hidden_oracle_command": "",
    }
    context.node_payload.update(
        {
            "semantic_stage": "successor_planning",
            "reliable_plan_skeleton_id": "reliable-plan-test-v1",
            "reliable_plan_remaining_horizons": 1,
        }
    )

    packet = _planner_packet(context)
    prompt = _prompt_for_node(context)
    invariant_example = next(
        example
        for example in packet["patch_examples"]
        if example["purpose"] == "create_invariant_check"
    )
    semantic_example = next(
        example
        for example in packet["patch_examples"]
        if example["purpose"] == "construct_reliable_plan_region"
    )

    assert (
        "use command_binding='dynamic_feature_hidden_oracle' only when the packet's "
        "available_check_bindings includes it"
    ) in prompt
    assert (
        "for dynamic_feature final invariant checks, use "
        "command_binding='dynamic_feature_hidden_oracle'."
    ) not in prompt
    assert "otherwise provide an explicit batch-scoped command_definition" in prompt
    assert "do not use dynamic_feature_acceptance as a semantic-region binding" in prompt
    invariant_node = invariant_example["ops"][0]["node"]
    semantic_check = semantic_example["checks"][0]
    assert "command_binding" not in invariant_node
    assert invariant_node["command_definition"] == {"cmd": "uv run pytest tests/batch -q"}
    assert "command_binding" not in semantic_check
    assert semantic_check["command_definition"] == {"cmd": "uv run pytest tests/batch -q"}


def test_planner_packet_contract_fields_remain_stable() -> None:
    events = _graph_events()
    context = _planner_context(events)
    packet = _planner_packet(context)

    assert set(
        [
            "run_id",
            "node_id",
            "node_kind",
            "role",
            "active_intent",
            "current_graph_position",
            "planner_generation",
            "bound_requirements",
            "frontier",
            "evidence",
            "freshness",
            "open_planner_proposals",
            "accepted_planner_patches",
            "patch_rejections",
            "allowed_patch_operations",
            "horizon_region_templates",
            "patch_examples",
        ]
    ).issubset(packet.keys())
    assert packet["current_graph_position"] == max((event.position for event in events), default=0)
    assert packet["node_id"] == "planner-1"
    for entry in ["frontier", "evidence", "open_planner_proposals", "accepted_planner_patches"]:
        assert isinstance(packet[entry], object)


def test_gap_planner_packet_includes_gap_contract_and_corrective_examples() -> None:
    events = _graph_events()
    context = _gap_planner_context(events)
    packet = _planner_packet(context)

    assert packet["role"] == "gap_planner"
    assert packet["gap_analysis_contract"] == {
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
            "meaning": (
                "bound evidence shows no corrective work is needed; accepted no-op "
                "emits a no_gap classified_gap record on submit"
            ),
        },
        "corrective_region": "corrective_work_region",
        "corrective_categories": {
            "implementation": "create_effectful_batch with failed batch evidence",
            "semantic_plan_revision": (
                "create_revision_attempt with exact failed implementation-plan artifact, "
                "failed plan-verification report, schema, requirements, and consumer edges"
            ),
        },
        "repository_edits": "forbidden",
    }

    purposes = [example["purpose"] for example in packet["patch_examples"]]
    assert purposes == [
        "no_gap_no_op_patch",
        "semantic_plan_revision",
        "create_corrective_work_region",
    ]
    assert "create_successor_planner" not in purposes
    assert "create_gap_planner" not in purposes

    corrective_example = next(
        example
        for example in packet["patch_examples"]
        if example["purpose"] == "create_corrective_work_region"
    )
    for op in corrective_example["ops"]:
        if op["op"] != "create_node":
            continue
        node = op["node"]
        if node["kind"] in {"worker", "verifier"}:
            assert node["task_region_id"] == "corrective_work_region"

    revision_example = next(
        example
        for example in packet["patch_examples"]
        if example["purpose"] == "semantic_plan_revision"
    )
    revision = revision_example["ops"][0]
    assert revision["op"] == "create_revision_attempt"
    worker = revision["worker_node"]
    assert worker["semantic_stage"] == "corrective_work"
    assert worker["access_mode"] == "write"
    assert worker["effect_contract"] == "effectful_write"
    assert worker["failed_candidate_id"] == worker["recovery_of_record_id"]
    failed_report_edge = revision_example["ops"][1]
    assert failed_report_edge["accepted_record_selector"]["outcome"] == "failed"
    assert failed_report_edge["accepted_record_selector"]["record_id"]


def test_final_reliable_plan_horizon_gets_exact_finalization_guidance() -> None:
    events = _graph_events()
    next_position = max(event.position for event in events) + 1
    for batch_id, verifier_id in (
        ("batch-1-pure", "verifier-batch-1"),
        ("batch-2-cli", "verifier-batch-2"),
    ):
        events.append(
            _event(
                "node_created",
                {
                    "node_id": verifier_id,
                    "kind": "verifier",
                    "role": "verifier",
                    "state": "planned",
                    "task_region_id": batch_id,
                    "semantic_stage": "effectful_batch",
                    "declared_batch_id": batch_id,
                },
                next_position,
            )
        )
        next_position += 1

    base_context = _planner_context(events)
    context = replace(
        base_context,
        node_payload={
            **base_context.node_payload,
            "semantic_stage": "successor_planning",
            "planning_horizon": 2,
            "reliable_plan_skeleton_id": "plan-record-1",
            "reliable_plan_remaining_horizons": 1,
            "declared_batch_id": "batch-2-cli",
            "declared_batch_ids": ["batch-1-pure", "batch-2-cli"],
        },
    )

    packet = _planner_packet(context)

    assert packet["reliable_plan_contract"] == {
        "semantic_stage": "successor_planning",
        "planning_horizon": 2,
        "remaining_horizons_including_current": 1,
        "declared_batch_ids": ["batch-1-pure", "batch-2-cli"],
        "current_declared_batch_id": "batch-2-cli",
        "required_sequence": [
            "call construct_reliable_plan_region once for the current accepted batch scope",
            "the controller atomically creates the batch, dynamic acceptance, independent audit, and final gate",
            "the controller rejects a partial batch-only or finalization-only patch",
            "call plain submit only after that complete patch is accepted",
        ],
        "finalization_rules": [
            "do not create another worker, check, batch, or successor planner",
            "create exactly one controller-bound dynamic_feature_acceptance check distinct from any hidden oracle check",
            "the acceptance check must consume a passed verification report from every declared batch verifier",
            "the final-audit verifier must consume those passed batch reports and the passed acceptance receipt",
            "the final gate must consume the passed batch reports, acceptance receipt, and final-audit report",
            "the final gate declared_batch_ids must exactly equal declared_batch_ids",
            "declare every concrete input port used by an edge",
        ],
    }
    purposes = [example["purpose"] for example in packet["patch_examples"]]
    assert "create_successor_planner" not in purposes
    assert "construct_reliable_plan_region" in purposes

    construction = next(
        example
        for example in packet["patch_examples"]
        if example["purpose"] == "construct_reliable_plan_region"
    )
    assert construction["scope"] == "batch-2-cli"
    assert "ops" not in construction
    assert "node_id" not in construction
    assert construction["checks"] == [
        {
            "name": "bounded project check",
            "command_definition": {"cmd": "uv run pytest tests/batch -q"},
        }
    ]


def test_gap_planner_packet_includes_blocking_obligations() -> None:
    events = [
        *_graph_events(),
        _event(
            "node_created",
            {
                "node_id": "worker-corrective",
                "kind": "worker",
                "role": "fixer",
                "state": "blocked",
                "task_region_id": "corrective_work_region",
            },
            17,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-gap-to-corrective",
                "from_node_id": "planner-1",
                "from_port": "classified_gap",
                "to_node_id": "worker-corrective",
                "to_port": "classified_gap",
                "required": True,
            },
            18,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final",
                "kind": "check",
                "role": "invariant_gate",
                "state": "blocked",
                "task_region_id": "final-invariant-region",
            },
            19,
        ),
        _event(
            "node_deferred",
            {
                "node_id": "check-final",
                "reason": "missing_required_input:verification_evidence",
            },
            20,
        ),
    ]
    packet = _planner_packet(_gap_planner_context(events))

    assert packet["gap_analysis_obligations"] == [
        {
            "kind": "classified_gap_successor_waiting",
            "edge_id": "edge-gap-to-corrective",
            "to_node_id": "worker-corrective",
            "to_port": "classified_gap",
            "reason": (
                "required classified_gap successor is waiting; submit a no_gap no-op "
                "patch or create corrective work so the successor can receive a "
                "durable gap classification"
            ),
        },
        {
            "kind": "final_invariant_waiting_for_verification_evidence",
            "node_id": "check-final",
            "reason": (
                "final invariant is still pending verification_evidence; a weak verifier "
                "pass is not sufficient if corrective/final invariant work remains"
            ),
        },
    ]
