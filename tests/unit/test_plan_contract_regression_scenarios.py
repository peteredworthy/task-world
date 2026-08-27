"""Regression tests for contract-doc scenarios from reliable-plan-execution-contract.md.

These tests join the admission, projection, and prompt-rendering chain that
no single existing test crosses, closing gaps introduced by Slice 1 chunks 1-5.
"""

import json
from typing import Any

from orchestrator.graph import (
    FakeClock,
    SequentialIdGenerator,
    build_projection,
    initial_projection,
    reduce_event,
)
from orchestrator.graph_runtime.dispatch import (
    GraphDispatchContext,
    _node_payload,
    _prompt_for_node,
    _requirements_for_node,
)
from tests.unit.graph_test_utils import apply_command, event, patch_command_context


# ============================================================================
# Module-level helpers
# ============================================================================

_DISCOVERY_WORKER: dict[str, Any] = {
    "node_id": "worker-1",
    "kind": "worker",
    "role": "discovery",
    "state": "planned",
    "task_region_id": "region-1",
    "candidate_id": "candidate-1",
    "attempt_number": 1,
    "objective": "Investigate the failure and report findings.",
    "access_mode": "read_only",
    "acceptance": ["root cause identified and documented"],
    "scope": "docs/ and tests/ only",
    "bound_requirement_ids": ["REQ-1"],
    "invariants": ["never modify src/"],
    "prohibited_actions": ["git commit"],
    "inputs": [{"port": "requirement_1", "schema": "RequirementRecord"}],
}


def _project(events):
    """Build projection by folding initial state with all events."""
    projection = initial_projection()
    for evt in events:
        projection = reduce_event(projection, evt)
    return projection


def _submit(events, patch_id, ops):
    """Submit a patch via apply_command, returning the full event list."""
    projection = _project(events)
    emitted = apply_command(
        projection,
        events,
        "submit_patch",
        {
            "patch_id": patch_id,
            "base_graph_position": max((e.position for e in events), default=-1),
            "ops": ops,
        },
        patch_command_context(
            events,
            proposed_by_node_id="planner-1",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    return events + emitted


def _admitted_discovery_graph():
    """Build a complete event sequence: requirement node + admitted discovery worker with bound requirement.

    Steps:
    1. Seed requirement node
    2. Submit patch with create_node (discovery worker) and create_edge
    3. Accept output_record for requirement
    4. Append input_bound event to bind the requirement to the worker
    """
    events = [
        event(
            "node_created",
            {
                "node_id": "requirement-REQ-1",
                "kind": "requirement",
                "state": "completed",
            },
            position=0,
        )
    ]

    # Submit patch with discovery worker and requirement binding edge
    events = _submit(
        events,
        "patch-1",
        [
            {"op": "create_node", "node": dict(_DISCOVERY_WORKER)},
            {
                "op": "create_edge",
                "edge_id": "edge-req-1",
                "from_node_id": "requirement-REQ-1",
                "from_port": "requirement",
                "to_node_id": "worker-1",
                "to_port": "requirement_1",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "requirement_record",
                    "schema": "Requirement",
                },
            },
        ],
    )

    # Verify the patch was accepted
    event_types = [e.event_type for e in events[-3:]]
    assert event_types == [
        "graph_patch_accepted",
        "node_created",
        "edge_created",
    ]

    # Accept output record for the requirement
    events.append(
        event(
            "output_record_accepted",
            {
                "record_id": "requirement-REQ-1",
                "record_kind": "graph_record",
                "record_type": "requirement_record",
                "producer_node_id": "requirement-REQ-1",
                "port": "requirement",
                "schema": "RequirementRecord",
                "value": {
                    "id": "REQ-1",
                    "text": "report the root cause",
                    "source": "routine",
                },
            },
            position=len(events),
        )
    )

    # Bind the requirement to the worker
    events.append(
        event(
            "input_bound",
            {
                "edge_id": "edge-req-1",
                "to_node_id": "worker-1",
                "to_port": "requirement_1",
                "record_ids": ["requirement-REQ-1"],
                "bound_at_position": len(events),
            },
            position=len(events),
        )
    )

    return events


def _dispatch_context(events):
    """Build GraphDispatchContext from event list, hydrating worker-1."""
    projection = build_projection(events)
    payload = _node_payload(events, "worker-1", projection=projection)

    return GraphDispatchContext(
        run_id="run-1",
        node_id="worker-1",
        node_kind=payload.get("kind", "worker"),
        node_role=payload.get("role"),
        node_payload=payload,
        requirements=_requirements_for_node(projection, "worker-1", events),
        graph_projection=projection,
        graph_events=list(events),
        worktree_path="/tmp/worktree",
        lease_id="lease-1",
        lease_generation=1,
        execution_id="exec-1",
        base_snapshot_id="snap-1",
        dispatch_event_id="dispatch-1",
    )


def _prompt_line_json(prompt: str, prefix: str) -> dict[str, Any]:
    """Extract and parse a JSON line from the prompt by its prefix.

    Raises AssertionError if the line is not found.
    """
    for line in prompt.split("\n"):
        if line.startswith(f"{prefix}: "):
            json_str = line[len(prefix) + 2 :]  # Skip "prefix: "
            return json.loads(json_str)
    raise AssertionError(f"{prefix} line not found in prompt")


# ============================================================================
# Tests
# ============================================================================


def test_scenario_1_read_only_discovery_worker_cannot_obtain_write_authority():
    """Scenario #1: analysis-only discovery node cannot obtain repo write authority.

    Verifies that a read_only discovery worker:
    1. Receives a read claim, never write
    2. Its prompt advertises read authority only
    3. Its contract reflects read_only access_mode
    4. It cannot be escalated to write via set_resource_claims
    """
    events = _admitted_discovery_graph()
    context = _dispatch_context(events)

    # Step 1: Verify the worker_authority packet grants read, not write
    prompt = _prompt_for_node(context)
    authority = _prompt_line_json(prompt, "worker_authority")
    assert authority["resource_claims"] == [{"mode": "read", "scope": "repo", "paths": ["."]}]

    # Step 2: Verify the prompt contains no write grant
    assert '"mode": "write"' not in prompt

    # Step 3: Verify work_contract line reflects read_only access_mode
    contract = _prompt_line_json(prompt, "work_contract")
    assert contract["access_mode"] == "read_only"

    # Step 4: Verify escalation to write is rejected
    escalate_events = apply_command(
        _project(events),
        events,
        "submit_patch",
        {
            "patch_id": "patch-escalate",
            "base_graph_position": max((e.position for e in events), default=-1),
            "ops": [
                {
                    "op": "set_resource_claims",
                    "node_id": "worker-1",
                    "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["."]}],
                }
            ],
        },
        patch_command_context(
            events,
            proposed_by_node_id="planner-1",
            actor_role="planner",
        ),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert len(escalate_events) == 1
    assert escalate_events[0].event_type == "graph_patch_rejected"
    assert escalate_events[0].payload["reason"] == "resource claim escalation for worker-1: write"


def test_scenario_4_worker_prompt_carries_its_bound_requirement_and_objective():
    """Scenario #4: worker prompts contain bound requirement and objective records.

    Verifies end to end:
    1. Requirement binding resolves from edge through input_bound to requirement text
    2. Worker prompt carries full work_contract with all eight keys
    3. bound_requirement_ids and bound_requirements both present and correct
    """
    events = _admitted_discovery_graph()
    context = _dispatch_context(events)

    # Step 1: Verify requirements resolved from binding
    assert context.requirements == ["REQ-1: report the root cause"]

    # Step 2: Extract and parse work_contract from prompt
    prompt = _prompt_for_node(context)
    contract = _prompt_line_json(prompt, "work_contract")

    # Step 3: Verify all eight keys present with correct values
    expected_contract = {
        "acceptance": ["root cause identified and documented"],
        "access_mode": "read_only",
        "bound_requirement_ids": ["REQ-1"],
        "bound_requirements": ["REQ-1: report the root cause"],
        "invariants": ["never modify src/"],
        "objective": "Investigate the failure and report findings.",
        "prohibited_actions": ["git commit"],
        "scope": "docs/ and tests/ only",
    }
    assert contract == expected_contract

    # Step 4: Explicitly verify bound_requirement_ids and bound_requirements
    assert contract["bound_requirement_ids"] == ["REQ-1"]
    assert contract["bound_requirements"] == ["REQ-1: report the root cause"]
