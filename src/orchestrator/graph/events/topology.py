"""Strict topology, node, session, input, and revision specifications."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from orchestrator.graph.models import (
    CommandDefinitionProjection,
    PlannerChainPayload,
    PortModel,
    ResourceClaimProjection,
)
from orchestrator.graph.payloads import JsonValue, StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    EventMetadata,
    EventSpecification,
    HydratedEvent,
    ProjectionParticipation,
    projection_neutral,
)


def _empty_resource_claims() -> list[ResourceClaimProjection]:
    return []


def _empty_ports() -> list[PortModel]:
    return []


class NodeCreatedPayload(StrictPayload):
    node_id: str
    kind: str
    run_id: str | None = None
    role: str | None = None
    state: str | None = None
    task_region_id: str | None = None
    attempt_number: int | None = None
    candidate_id: str | None = None
    failed_candidate_id: str | None = None
    resource_claims: list[ResourceClaimProjection] = Field(default_factory=_empty_resource_claims)
    allowed_actions: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    planner_generation_budget: int | None = None
    generation_index: int | None = None
    region_label: str | None = None
    session_id: str | None = None
    carryover_record_id: str | None = None
    session_intent: str | None = None
    planner_chain: PlannerChainPayload | None = None
    gate_type: str | None = None
    approval_type: str | None = None
    reason: str | None = None
    prompt: str | None = None
    approval_prompt: str | None = None
    human_prompt: str | None = None
    message: str | None = None
    blocker: str | None = None
    blocker_reason: str | None = None
    decision_request: dict[str, JsonValue] | None = None
    authority_request_record: dict[str, JsonValue] | None = None
    authority_request: dict[str, JsonValue] | None = None
    decision_request_record_id: str | None = None
    authority_request_record_id: str | None = None
    command_definition: CommandDefinitionProjection | None = None
    command_definition_id: str | None = None
    hidden_oracle_command: str | None = None
    command_binding: str | None = None
    command: str | None = None
    command_text: str | None = None
    recovery_reason: str | None = None
    recovery_of_node_id: str | None = None
    recovery_of_record_id: str | None = None
    guarded_planner_node_id: str | None = None
    rejected_patch_id: str | None = None
    predecessor_node_ids: list[str] | None = None
    appealed_node_id: str | None = None
    requirement_id: str | None = None
    id: str | None = None
    priority: str | None = None
    requirement: dict[str, JsonValue] | None = None
    inputs: list[PortModel] = Field(default_factory=_empty_ports)
    outputs: list[PortModel] = Field(default_factory=_empty_ports)
    artifact_reference_record: dict[str, JsonValue] | None = None
    artifacts: list[JsonValue] | None = None
    available_tools: list[JsonValue] | None = None
    builder_agent: str | None = None
    candidate_record: dict[str, JsonValue] | None = None
    check_index: int | None = None
    complexity: str | None = None
    context_source: dict[str, JsonValue] | None = None
    dynamic_feature: dict[str, JsonValue] | None = None
    execution_id: str | None = None
    fan_out: dict[str, JsonValue] | None = None
    gate: dict[str, JsonValue] | None = None
    max_attempts: int | None = None
    mcp_servers: list[JsonValue] | None = None
    profile: str | None = None
    requirement_record: dict[str, JsonValue] | None = None
    routine: dict[str, JsonValue] | None = None
    routine_snapshot_record: dict[str, JsonValue] | None = None
    rubric: list[JsonValue] | None = None
    run_context_record: dict[str, JsonValue] | None = None
    snapshot: dict[str, JsonValue] | None = None
    step_id: str | None = None
    step_index: int | None = None
    step_context: str | None = None
    submission_template: dict[str, JsonValue] | None = None
    task_context: str | None = None
    task_id: str | None = None
    task_index: int | None = None
    title: str | None = None
    verifier_agent: str | None = None
    work_mode: str | None = None


class NodeStateChangedPayload(StrictPayload):
    node_id: str
    new_state: str
    trigger: str | None = None
    reason: str | None = None
    attempt_number: int | None = None
    max_attempts: int | None = None
    completion_status: str | None = None
    completion_decision_record_id: str | None = None
    join_result_record_id: str | None = None
    retry_not_before: str | None = None
    prompt_summary: dict[str, JsonValue] | None = None


class NodeRetiredPayload(StrictPayload):
    node_id: str
    reason: str | None = None


class NodeReadyPayload(StrictPayload):
    node_id: str


class NodeDeferredPayload(StrictPayload):
    node_id: str
    reason: str


class NodeAuthorityChangedPayload(StrictPayload):
    node_id: str
    resource_claims: list[ResourceClaimProjection] = Field(default_factory=_empty_resource_claims)
    allowed_actions: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)


class PlanRegionMarkedSuspectPayload(StrictPayload):
    region_node_ids: list[str]
    reason: str
    region_id: str | None = None


class NodeSuspectPayload(PlanRegionMarkedSuspectPayload):
    pass


class EdgeCreatedPayload(StrictPayload):
    edge_id: str
    from_node_id: str
    from_port: str
    to_node_id: str
    to_port: str
    required: bool = True
    purpose: str | None = None
    dependency_type: str | None = None
    accepted_record_selector: dict[str, JsonValue] | None = None
    metadata: dict[str, JsonValue] | None = None
    binding_policy: str | None = None
    freshness_policy: str | None = None
    prompt_hydration_policy: str | None = None
    description: str | None = None
    selection: str | None = None
    from_node_kind: str | None = None
    from_node_role: str | None = None


class InputBoundPayload(StrictPayload):
    edge_id: str
    to_node_id: str
    to_port: str
    record_ids: list[str]
    bound_at_position: int
    binding_policy: str | None = None
    supersedes_record_id: str | None = None
    record_bound_positions: dict[str, int] | None = None
    trigger: str | None = None


class PlannerSessionStateChangedPayload(StrictPayload):
    session_id: str
    state: str
    node_id: str
    lease_generation: int
    carryover_record_id: str | None

    def to_json(self) -> dict[str, JsonValue]:
        data = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        if "carryover_record_id" in self.model_fields_set:
            data["carryover_record_id"] = self.carryover_record_id
        return data


class DeadInputDetectedPayload(StrictPayload):
    node_id: str
    edge_id: str | None = None
    from_node_id: str | None = None
    from_port: str | None = None
    to_node_id: str | None = None
    to_port: str | None = None
    source_node_id: str | None = None
    reason: str


class RevisionCreatedPayload(StrictPayload):
    revision_id: str | None = None
    task_region_id: str | None = None
    attempt_number: int | None = None
    candidate_id: str | None = None
    failed_candidate_id: str | None = None
    reason: str | None = None


def _topology_reducer(name: str) -> Any:
    """Resolve projection-owned state mechanics after import initialization."""
    from orchestrator.graph import projections

    return getattr(projections, name)


def reduce_node_created(state: Any, payload: NodeCreatedPayload, metadata: EventMetadata) -> Any:
    return _topology_reducer("reduce_node_created")(state, payload, metadata)


def reduce_node_state_changed(
    state: Any, payload: NodeStateChangedPayload, metadata: EventMetadata
) -> Any:
    return _topology_reducer("reduce_node_state_changed")(state, payload, metadata)


def reduce_node_retired(state: Any, payload: NodeRetiredPayload, metadata: EventMetadata) -> Any:
    return _topology_reducer("reduce_node_retired")(state, payload, metadata)


def reduce_node_ready(state: Any, payload: NodeReadyPayload, metadata: EventMetadata) -> Any:
    return _topology_reducer("reduce_node_ready")(state, payload, metadata)


def reduce_node_deferred(state: Any, payload: NodeDeferredPayload, metadata: EventMetadata) -> Any:
    return _topology_reducer("reduce_node_deferred")(state, payload, metadata)


def reduce_node_authority_changed(
    state: Any, payload: NodeAuthorityChangedPayload, metadata: EventMetadata
) -> Any:
    return _topology_reducer("reduce_node_authority_changed")(state, payload, metadata)


def reduce_plan_region_marked_suspect(
    state: Any, payload: PlanRegionMarkedSuspectPayload, metadata: EventMetadata
) -> Any:
    return _topology_reducer("reduce_plan_region_marked_suspect")(state, payload, metadata)


def reduce_edge_created(state: Any, payload: EdgeCreatedPayload, metadata: EventMetadata) -> Any:
    return _topology_reducer("reduce_edge_created")(state, payload, metadata)


def reduce_input_bound(state: Any, payload: InputBoundPayload, metadata: EventMetadata) -> Any:
    return _topology_reducer("reduce_input_bound")(state, payload, metadata)


def reduce_session_state_changed(
    state: Any, payload: PlannerSessionStateChangedPayload, metadata: EventMetadata
) -> Any:
    return _topology_reducer("reduce_session_state_changed")(state, payload, metadata)


NODE_CREATED = EventSpecification(
    "node_created", NodeCreatedPayload, reduce_node_created, ProjectionParticipation.MUTATES
)
NODE_STATE_CHANGED = EventSpecification(
    "node_state_changed",
    NodeStateChangedPayload,
    reduce_node_state_changed,
    ProjectionParticipation.MUTATES,
)
NODE_RETIRED = EventSpecification(
    "node_retired", NodeRetiredPayload, reduce_node_retired, ProjectionParticipation.MUTATES
)
NODE_READY = EventSpecification(
    "node_ready", NodeReadyPayload, reduce_node_ready, ProjectionParticipation.MUTATES
)
NODE_DEFERRED = EventSpecification(
    "node_deferred", NodeDeferredPayload, reduce_node_deferred, ProjectionParticipation.MUTATES
)
NODE_AUTHORITY_CHANGED = EventSpecification(
    "node_authority_changed",
    NodeAuthorityChangedPayload,
    reduce_node_authority_changed,
    ProjectionParticipation.MUTATES,
)
PLAN_REGION_MARKED_SUSPECT = EventSpecification(
    "plan_region_marked_suspect",
    PlanRegionMarkedSuspectPayload,
    reduce_plan_region_marked_suspect,
    ProjectionParticipation.MUTATES,
)
EDGE_CREATED = EventSpecification(
    "edge_created", EdgeCreatedPayload, reduce_edge_created, ProjectionParticipation.MUTATES
)
INPUT_BOUND = EventSpecification(
    "input_bound", InputBoundPayload, reduce_input_bound, ProjectionParticipation.MUTATES
)
SESSION_STATE_CHANGED = EventSpecification(
    "session_state_changed",
    PlannerSessionStateChangedPayload,
    reduce_session_state_changed,
    ProjectionParticipation.MUTATES,
)
DEAD_INPUT_DETECTED = EventSpecification(
    "dead_input_detected",
    DeadInputDetectedPayload,
    projection_neutral,
    ProjectionParticipation.NEUTRAL,
)
REVISION_CREATED = EventSpecification(
    "revision_created", RevisionCreatedPayload, projection_neutral, ProjectionParticipation.NEUTRAL
)


class SeedCompiledEventsCommand(StrictPayload):
    events: tuple[HydratedEvent, ...]


def handle_seed_compiled_events(
    command: SeedCompiledEventsCommand,
    projection: Any,
    events: tuple[Any, ...],
    context: CommandExecutionContext,
) -> tuple[HydratedEvent, ...]:
    del events
    if projection["node_creation_payloads"]:
        raise ValueError("run topology already seeded")
    return command.events


SEED_COMPILED_EVENTS = CommandSpecification(
    "seed_compiled_events", SeedCompiledEventsCommand, handle_seed_compiled_events
)
COMMAND_SPECIFICATIONS = (SEED_COMPILED_EVENTS,)


EVENT_SPECIFICATIONS = (
    NODE_CREATED,
    NODE_STATE_CHANGED,
    NODE_RETIRED,
    NODE_READY,
    NODE_DEFERRED,
    NODE_AUTHORITY_CHANGED,
    PLAN_REGION_MARKED_SUSPECT,
    EDGE_CREATED,
    INPUT_BOUND,
    SESSION_STATE_CHANGED,
    DEAD_INPUT_DETECTED,
    REVISION_CREATED,
)


__all__ = [
    "DEAD_INPUT_DETECTED",
    "EDGE_CREATED",
    "EVENT_SPECIFICATIONS",
    "INPUT_BOUND",
    "NODE_AUTHORITY_CHANGED",
    "NODE_CREATED",
    "NODE_DEFERRED",
    "NODE_READY",
    "NODE_RETIRED",
    "NODE_STATE_CHANGED",
    "PLAN_REGION_MARKED_SUSPECT",
    "REVISION_CREATED",
    "SEED_COMPILED_EVENTS",
    "SESSION_STATE_CHANGED",
    "DeadInputDetectedPayload",
    "EdgeCreatedPayload",
    "InputBoundPayload",
    "NodeAuthorityChangedPayload",
    "NodeCreatedPayload",
    "NodeDeferredPayload",
    "NodeReadyPayload",
    "NodeRetiredPayload",
    "NodeStateChangedPayload",
    "NodeSuspectPayload",
    "PlannerSessionStateChangedPayload",
    "RevisionCreatedPayload",
    "SeedCompiledEventsCommand",
]
