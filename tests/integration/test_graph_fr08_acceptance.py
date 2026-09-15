"""FR-08 acceptance coverage for mutation validation and authority decisions."""

from datetime import timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api import create_app
from orchestrator.config import GlobalConfig, PathsConfig, RunStatus
from orchestrator.db import RunModel, StepModel, TaskModel, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    CacheAuthorityPolicy,
    EventEnvelope,
    FakeClock,
    PatchCommandContext,
    edges_view,
    input_bindings_view,
    leases_view,
    node_payload_view,
    node_states_view,
    requirements_for_node_view,
    cache_authority_hash,
    canonicalize_cache_authority,
)
from orchestrator.graph_runtime import GraphController, GraphEventStore
from orchestrator.workflow import InMemorySignalTransport


SECRET_COMMAND = "uv run pytest tests/oracle -q"
_FR18_FIXTURE_RUN_ID = "cd72f306-27f7-4cf2-8213-f770ff78f412"
_FR18_FIXTURE_EVENT_COUNT = 455
_FR18_SOURCE_EVENT_STREAM_SHA256 = (
    "sha256:3c59033da2e44520f49c49fa492f896f258e1f221c25554df17e179d910883c6"
)
_FR18_SOURCE_WRAPPER_STREAM_SHA256 = (
    "sha256:2d5eb0fd4d4b229f8dc97603bfb22f42d75ed20f0e0e82c6a91ebab17571f0d3"
)
_FR18_EXPORTED_EVENT_STREAM_SHA256 = (
    "sha256:77d5b606845e19aef4abd96903840567fb81630d8de38db47aef94251adfd06a"
)
_FR18_FIXTURE_PATH = Path(__file__).parents[1] / "fixtures/graph/fr18-cd72-position-455-export.json"


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _json_pointer_value(value: object, pointer: str) -> object:
    current = value
    for encoded_part in pointer.removeprefix("/").split("/"):
        part = encoded_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise ValueError(f"invalid sanitization JSON pointer: {pointer}")
    return current


def _validate_fr18_fixture(document: dict[str, Any]) -> list[EventEnvelope]:
    """Validate the pinned source identity and every exported event digest."""
    if set(document) != {"schema", "source", "sanitization", "manifest", "events"}:
        raise ValueError("fixture document fields are incomplete")
    if document["schema"] != "orchestrator.graph.canonical-event-export.v1":
        raise ValueError("fixture export schema is invalid")

    source = document["source"]
    expected_source = {
        "kind": "local_secondary_journal_read_only",
        "path": ".orchestrator/state/history.jsonl",
        "aggregate_id": f"graph:{_FR18_FIXTURE_RUN_ID}",
        "run_id": _FR18_FIXTURE_RUN_ID,
        "event_count": _FR18_FIXTURE_EVENT_COUNT,
        "first_graph_position": 1,
        "last_graph_position": _FR18_FIXTURE_EVENT_COUNT,
        "first_journal_position": 91932,
        "last_journal_position": 92932,
        "last_source_timestamp": "2026-09-03T17:29:27.658147+00:00",
        "source_event_stream_sha256": _FR18_SOURCE_EVENT_STREAM_SHA256,
        "source_wrapper_stream_sha256": _FR18_SOURCE_WRAPPER_STREAM_SHA256,
    }
    if source != expected_source:
        raise ValueError("fixture source acquisition metadata is not the pinned export")

    events = document["events"]
    manifest = document["manifest"]
    entries = manifest["entries"]
    if not (len(events) == len(entries) == manifest["event_count"] == _FR18_FIXTURE_EVENT_COUNT):
        raise ValueError("fixture event/manifest completeness mismatch")
    positions = [event["position"] for event in events]
    if positions != list(range(1, _FR18_FIXTURE_EVENT_COUNT + 1)):
        raise ValueError("fixture positions are not exactly 1..455")
    event_types = [event["event_type"] for event in events]
    if manifest["positions_sha256"] != _canonical_sha256(positions):
        raise ValueError("fixture position manifest hash mismatch")
    if manifest["event_types_sha256"] != _canonical_sha256(event_types):
        raise ValueError("fixture event-type manifest hash mismatch")
    if manifest["exported_event_stream_sha256"] != _FR18_EXPORTED_EVENT_STREAM_SHA256:
        raise ValueError("fixture exported stream identity is not pinned")
    if manifest["exported_event_stream_sha256"] != _canonical_sha256(events):
        raise ValueError("fixture exported event stream hash mismatch")

    sanitization = document["sanitization"]
    changes = sanitization["changes"]
    if sanitization != {
        "policy": "replace only the local home-directory username in free-form text",
        "replacement_preserves_utf8_length": True,
        "change_count": len(changes),
        "changes": changes,
    }:
        raise ValueError("fixture sanitization manifest is invalid")
    changed_positions: set[int] = set()
    events_by_position = {event["position"]: event for event in events}
    for change in changes:
        if change["rules"] != ["local_home_username"]:
            raise ValueError("fixture contains an unapproved sanitization rule")
        if change["source_utf8_bytes"] != change["exported_utf8_bytes"]:
            raise ValueError("fixture sanitization changed UTF-8 length")
        exported_value = _json_pointer_value(
            events_by_position[change["position"]],
            change["json_pointer"],
        )
        if change["exported_value_sha256"] != _canonical_sha256(exported_value):
            raise ValueError("fixture sanitized value hash mismatch")
        if change["source_value_sha256"] == change["exported_value_sha256"]:
            raise ValueError("fixture sanitization does not record a change")
        changed_positions.add(change["position"])

    envelopes: list[EventEnvelope] = []
    for event, entry in zip(events, entries, strict=True):
        if (entry["position"], entry["event_id"], entry["event_type"]) != (
            event["position"],
            event["event_id"],
            event["event_type"],
        ):
            raise ValueError("fixture event identity manifest mismatch")
        if entry["exported_event_sha256"] != _canonical_sha256(event):
            raise ValueError("fixture exported event hash mismatch")
        if entry["exported_payload_sha256"] != _canonical_sha256(event["payload"]):
            raise ValueError("fixture exported payload hash mismatch")
        source_matches_export = (
            entry["source_event_sha256"] == entry["exported_event_sha256"]
            and entry["source_payload_sha256"] == entry["exported_payload_sha256"]
        )
        if source_matches_export != (event["position"] not in changed_positions):
            raise ValueError("fixture source/export hashes do not match sanitization scope")
        envelopes.append(EventEnvelope.model_validate(event))
    return envelopes


def _load_fr18_fixture() -> tuple[dict[str, Any], list[EventEnvelope]]:
    document = json.loads(_FR18_FIXTURE_PATH.read_text(encoding="utf-8"))
    return document, _validate_fr18_fixture(document)


def _exact_fr18_closed_repair(events: list[EventEnvelope]) -> dict[str, Any]:
    by_position = {event.position: event for event in events}
    old_id = "worker-reliable-plan-recovery"
    replacement_id = f"{old_id}-v2"
    patch_id = "repair-live-blocked-worker-v2"
    old_node = dict(by_position[420].payload)
    assert by_position[420].event_type == "node_created"
    assert old_node["node_id"] == old_id
    assert old_node["failed_candidate_id"] == (
        "semantic-artifact-exec-2b7cc9e419e141679ef1c6188a7f3a87-semantic_artifact"
    )
    expected_edges = {
        422: "edge-failed-verification-to-recovery-worker",
        424: "edge-recovery-candidate-to-verifier",
        425: "edge-recovery-artifact-to-verifier",
    }
    replacement_edges: list[dict[str, Any]] = []
    for position, edge_id in expected_edges.items():
        event = by_position[position]
        assert event.event_type == "edge_created"
        assert event.payload["edge_id"] == edge_id
        edge = {key: value for key, value in event.payload.items() if key != "patch_id"}
        edge.update(op="create_edge", edge_id=f"{edge_id}-v2")
        if edge["from_node_id"] == old_id:
            edge["from_node_id"] = replacement_id
        if edge["to_node_id"] == old_id:
            edge["to_node_id"] = replacement_id
        replacement_edges.append(edge)
    replacement = {
        **old_node,
        "node_id": replacement_id,
        "state": "planned",
        "patch_id": patch_id,
        "effect_contract": "effectful_write",
    }
    return {
        "patch_id": patch_id,
        "base_graph_position": _FR18_FIXTURE_EVENT_COUNT,
        "ops": [
            {"op": "retire_node", "node_id": old_id},
            {"op": "create_node", "node": replacement},
            *replacement_edges,
        ],
    }


def _event(event_type: str, payload: dict[str, Any], position: int = -1) -> EventEnvelope:
    from tests.unit.graph_test_utils import canonical_event_payload

    return EventEnvelope(
        event_id=f"{event_type}-{uuid4().hex}",
        run_id="placeholder",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=canonical_event_payload(event_type, payload),
    )


class _RunSeedIdGenerator:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id.replace("-", "")
        self._count = 0

    def next_id(self, prefix: str) -> str:
        self._count += 1
        return f"{prefix}-{self._run_id}-{self._count}"


async def _save_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    now = FakeClock().now().astimezone(timezone.utc).replace(tzinfo=None)
    run = RunModel(
        id=run_id,
        repo_name=f"graph-fr08-acceptance-repo-{run_id}",
        status=RunStatus.ACTIVE.value,
        execution_mode="graph",
        source_branch="main",
        created_at=now,
        updated_at=now,
        current_step_index=0,
        steps=[
            StepModel(
                id=f"{run_id}-step-1",
                run_id=run_id,
                config_id="step-1",
                title="Step 1",
                order_index=0,
                tasks=[
                    TaskModel(
                        id=f"{run_id}-task-1",
                        step_id=f"{run_id}-step-1",
                        config_id="task-1",
                        title="Prove mutation validation",
                        order_index=0,
                        status="pending",
                        checklist=[],
                    )
                ],
            )
        ],
    )
    async with session_factory() as session:
        session.add(run)
        await session.commit()


async def _seed_invalid_patch_graph_run(app: Any, run_id: str) -> GraphController:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_graph_run(session_factory, run_id)
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {"node_id": "planner-1", "kind": "planner", "role": "planner", "state": "running"},
        ),
        _event("node_created", {"node_id": "verifier-1", "kind": "verifier", "state": "planned"}),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "resource_claims": [{"mode": "read", "scope": "repo", "paths": ["docs/"]}],
            },
        ),
        _event(
            "node_state_changed",
            {"node_id": "worker-1", "new_state": "running", "trigger": "test_seed"},
        ),
        _event(
            "node_created",
            {"node_id": "worker-stale", "kind": "worker", "role": "builder", "state": "planned"},
        ),
        _event(
            "node_state_changed",
            {"node_id": "worker-stale", "new_state": "cancelled", "trigger": "test_seed"},
        ),
    ]
    async with session_factory() as session:
        store = GraphEventStore(session)
        await store.append_events(run_id, 0, events)
        await store.rebuild_archival_views(run_id)
        await session.commit()

    return GraphController(
        session_factory,
        FakeClock(),
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
    )


async def _submit_patch(
    controller: GraphController,
    run_id: str,
    *,
    expected_position: int,
    patch_id: str,
    ops: list[dict[str, Any]],
    actor_role: str = "planner",
    base_graph_position: int | None = None,
) -> None:
    await controller.handle_command(
        run_id,
        expected_position,
        "submit_patch",
        {
            "patch_id": patch_id,
            "base_graph_position": expected_position
            if base_graph_position is None
            else base_graph_position,
            "ops": ops,
        },
        context=PatchCommandContext(
            run_id=run_id,
            current_graph_position=expected_position,
            proposed_by_node_id="planner-1",
            actor_role=actor_role,
        ),
    )


async def _events(client: AsyncClient, run_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")
    assert response.status_code == 200
    return response.json()


async def test_operator_patch_replaces_exhausted_discovery_in_same_run(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    """The supported HTTP patch retires the blocker and preserves its topology."""
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-operator-discovery-repair-{uuid4().hex[:8]}"
    sessions: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_graph_run(sessions, run_id)
    seed_events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "planner-reliable-plan",
                "kind": "planner",
                "role": "planner",
                "state": "running",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "schema-reliable-plan-implementation-plan-v1",
                "record_kind": "graph_record",
                "record_type": "semantic_schema_declaration",
                "schema_version": 1,
                "producer_node_id": "planner-reliable-plan",
                "port": "semantic_schema_declaration",
                "schema": "SemanticSchemaDeclaration",
                "value": {
                    "schema_id": "reliable-plan-implementation-plan",
                    "version": 1,
                    "semantic_role": "implementation_plan",
                    "json_schema": {"type": "object"},
                    "authority": "routine_snapshot",
                },
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "requirement-dynamic-feature-acceptance",
                "kind": "requirement",
                "role": "requirement",
                "state": "completed",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "requirement-dynamic-feature-acceptance",
                "record_kind": "graph_record",
                "record_type": "requirement_record",
                "producer_node_id": "requirement-dynamic-feature-acceptance",
                "port": "requirement",
                "schema": "RequirementRecord",
                "value": {
                    "id": "dynamic_feature_acceptance",
                    "text": "The reliable-plan product-path acceptance command passes.",
                    "source": "routine",
                },
            },
        ),
    ]
    async with sessions() as session:
        await GraphEventStore(session).append_events(run_id, 0, seed_events)
        await session.commit()
    controller = GraphController(
        sessions,
        FakeClock(),
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
    )
    initial = await controller.handle_command(
        run_id,
        len(seed_events),
        "submit_patch",
        {
            "patch_id": "initial-discovery",
            "base_graph_position": len(seed_events),
            "macro_invocations": [
                {
                    "macro": "create_discovery_region",
                    "args": {
                        "region_id": "reliable-plan-discovery",
                        "worker_id": "worker-reliable-plan-discovery",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "objective": "Discover the implementation plan.",
                        "acceptance": ["Produce an ordered implementation plan"],
                        "requirement_source_node_ids": ["requirement-dynamic-feature-acceptance"],
                    },
                },
                {
                    "macro": "create_plan_verification",
                    "args": {
                        "region_id": "reliable-plan-discovery-verification",
                        "verifier_id": "verifier-reliable-plan-discovery",
                        "artifact_source_node_id": "worker-reliable-plan-discovery",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "objective": "Independently verify the plan.",
                        "acceptance": ["All requirements are mapped"],
                        "rubric": ["The plan is executable"],
                        "requirement_source_node_ids": ["requirement-dynamic-feature-acceptance"],
                    },
                },
            ],
        },
        context=PatchCommandContext(
            run_id=run_id,
            current_graph_position=len(seed_events),
            proposed_by_node_id="planner-reliable-plan",
            actor_role="planner",
        ),
    )
    assert any(event.event_type == "graph_patch_accepted" for event in initial.events), [
        event.payload.get("reason") for event in initial.events
    ]
    failed_events = [
        _event(
            "node_state_changed",
            {
                "node_id": "worker-reliable-plan-discovery",
                "new_state": "failed",
                "trigger": "max_attempts_exhausted",
            },
        ),
        _event("run_lifecycle_changed", {"to_state": "paused"}),
    ]
    async with sessions() as session:
        await GraphEventStore(session).append_events(
            run_id,
            initial.projection_position,
            failed_events,
        )
        await session.commit()
    current_position = initial.projection_position + len(failed_events)
    replacement_macro = {
        "macro": "create_discovery_region",
        "args": {
            "region_id": "reliable-plan-discovery",
            "worker_id": "worker-reliable-plan-discovery-retry-1",
            "semantic_schema_id": "reliable-plan-implementation-plan",
            "semantic_schema_version": 1,
            "objective": "Discover the implementation plan.",
            "acceptance": ["Produce an ordered implementation plan"],
            "requirement_source_node_ids": ["requirement-dynamic-feature-acceptance"],
        },
    }
    incomplete = await client.post(
        f"/api/runs/{run_id}/graph/patch",
        json={
            "patch_id": "operator-incomplete-repair",
            "base_graph_position": current_position,
            "ops": [{"op": "retire_node", "node_id": "worker-reliable-plan-discovery"}],
            "macro_invocations": [replacement_macro],
        },
    )
    assert incomplete.status_code == 409
    assert "preserve required outgoing edge" in incomplete.text
    current_position += 1

    response = await client.post(
        f"/api/runs/{run_id}/graph/patch",
        json={
            "patch_id": "operator-retry-reliable-plan-discovery-after-hermetic-gate-fix-v1",
            "base_graph_position": current_position,
            "ops": [
                {"op": "retire_node", "node_id": "worker-reliable-plan-discovery"},
                {
                    "op": "create_edge",
                    "edge_id": (
                        "edge-reliable-plan-discovery-retry-1-to-independent-plan-verifier"
                    ),
                    "from_node_id": "worker-reliable-plan-discovery-retry-1",
                    "from_port": "semantic_artifact",
                    "to_node_id": "verifier-reliable-plan-discovery",
                    "to_port": "semantic_artifact",
                    "required": True,
                    "dependency_type": "input_binding",
                    "accepted_record_selector": {
                        "record_type": "semantic_artifact",
                        "schema": "SemanticArtifact",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "authority_status": "accepted",
                    },
                    "prompt_hydration_policy": "structured_json",
                },
            ],
            "macro_invocations": [replacement_macro],
        },
    )
    assert response.status_code == 200, response.text
    patched_position = response.json()["graph_position"]
    projection = await controller.read_projection(run_id)
    replacement_id = "worker-reliable-plan-discovery-retry-1"
    assert node_states_view(projection)["worker-reliable-plan-discovery"] == "retired"
    assert node_states_view(projection)[replacement_id] == "planned"
    replacement = node_payload_view(projection, replacement_id)
    assert replacement is not None
    assert replacement["task_region_id"] == "reliable-plan-discovery"
    assert replacement["semantic_stage"] == "discovery"
    assert requirements_for_node_view(projection, replacement_id) == [
        "dynamic_feature_acceptance: The reliable-plan product-path acceptance command passes."
    ]
    assert input_bindings_view(projection)[replacement_id]["requirement_1"].record_ids == [
        "requirement-dynamic-feature-acceptance",
    ]
    replacement_edge = edges_view(projection)[
        "edge-reliable-plan-discovery-retry-1-to-independent-plan-verifier"
    ]
    assert replacement_edge.to_node_id == "verifier-reliable-plan-discovery"
    assert replacement_edge.to_port == "semantic_artifact"

    resuming = await controller.handle_command(run_id, patched_position, "resume")
    active = await controller.handle_command(run_id, resuming.projection_position, "resume")
    scheduled = await controller.handle_command(
        run_id,
        active.projection_position,
        "schedule_tick",
        {
            "max_grants": 1,
            "lease_seconds": 60,
            "base_snapshot_id": "baseline",
            "priorities": {replacement_id: 100},
        },
    )
    grant = next(event for event in scheduled.events if event.event_type == "lease_granted")
    assert grant.payload["node_id"] == replacement_id
    assert grant.payload["execution_id"]
    assert grant.payload["lease_id"]
    final_projection = await controller.read_projection(run_id)
    replacement_lease = next(
        lease for lease in leases_view(final_projection).values() if lease.node_id == replacement_id
    )
    assert replacement_lease.state == "active"


async def test_public_api_repairs_live_shaped_blocked_legacy_worker(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-fr18-live-repair-{uuid4().hex[:8]}"
    sessions: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_graph_run(sessions, run_id)
    old_id = "worker-reliable-plan-recovery"
    replacement_id = "worker-reliable-plan-recovery-v2"
    failure_id = f"failure-{old_id}-lease-old"
    reason = "submission quality gate contract is invalid: worker effect_contract is missing"
    authority = {
        "allowed_actions": ["submit_records", "request_clarification", "raise_appeal"],
        "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["."]}],
    }
    node = {
        "node_id": old_id,
        "kind": "worker",
        "role": "fixer",
        "state": "blocked",
        "task_region_id": "reliable-plan-recovery-attempt",
        "attempt_number": 2,
        "candidate_id": "semantic-artifact-recovery-4b5fcd8b",
        "failed_candidate_id": (
            "semantic-artifact-exec-2b7cc9e419e141679ef1c6188a7f3a87-semantic_artifact"
        ),
        "base_snapshot_selection": "run_baseline",
        "access_mode": "write",
        "semantic_stage": "corrective_work",
        "semantic_schema_id": "reliable-plan-implementation-plan",
        "semantic_schema_version": 1,
        "bound_requirement_ids": ["dynamic_feature_acceptance"],
        "objective": "Repair the failed reliable-plan implementation candidate.",
        "scope": "Preserve the accepted plan and correct the failed implementation.",
        "acceptance": ["Replacement produces a verifiable candidate and semantic artifact"],
        "invariants": ["Preserve accepted reliable-plan semantics"],
        "prohibited_actions": ["Do not widen the accepted plan"],
        "authority": authority,
    }
    edge_specs = [
        {
            "edge_id": "failed-report-to-old",
            "from_node_id": "verifier-discovery",
            "from_port": "verification_report",
            "to_node_id": old_id,
            "to_port": "verification_report",
            "accepted_record_selector": {
                "record_type": "verification_report",
                "schema": "VerificationReport",
                "record_id": "failed-verification-live",
            },
        },
        {
            "edge_id": "old-candidate-to-verifier",
            "from_node_id": old_id,
            "from_port": "candidate",
            "to_node_id": "verifier-recovery",
            "to_port": "candidate_under_test",
            "accepted_record_selector": {
                "record_type": "candidate",
                "schema": "ImplementationCandidate",
            },
        },
        {
            "edge_id": "old-semantic-to-verifier",
            "from_node_id": old_id,
            "from_port": "semantic_artifact",
            "to_node_id": "verifier-recovery",
            "to_port": "semantic_artifact",
            "accepted_record_selector": {
                "record_type": "semantic_artifact",
                "schema": "SemanticArtifact",
                "semantic_schema_id": "reliable-plan-implementation-plan",
                "semantic_schema_version": 1,
            },
        },
    ]
    seed_events = [
        _event("run_lifecycle_changed", {"to_state": "paused"}),
        _event(
            "node_created",
            {
                "node_id": "verifier-discovery",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "failed-verification-live",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-discovery",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": node["failed_candidate_id"],
                "task_region_id": "reliable-plan-discovery-verification",
                "outcome": "failed",
                "value": {"outcome": "failed", "grades": []},
            },
        ),
        _event("node_created", node),
        _event(
            "node_created",
            {
                "node_id": "verifier-recovery",
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
            },
        ),
        *[
            _event(
                "edge_created",
                {**edge, "required": True, "prompt_hydration_policy": "structured_json"},
            )
            for edge in edge_specs
        ],
        _event("lease_granted", {"lease_id": "lease-old", "node_id": old_id, "generation": 1}),
        _event(
            "lease_revoked",
            {"lease_id": "lease-old", "node_id": old_id, "generation": 1, "reason": reason},
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": failure_id,
                "record_kind": "graph_record",
                "record_type": "failure_record",
                "producer_node_id": old_id,
                "port": "failure_record",
                "schema": "FailureRecord",
                "value": {
                    "failed_node_id": old_id,
                    "phase": "runtime",
                    "failure_class": "infrastructure_failure",
                    "error_class": "runtime_death_recovery_required",
                    "retryable": True,
                    "lease_id": "lease-old",
                    "reason": reason,
                },
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": f"recovery-plan-{old_id}-lease-old",
                "record_kind": "output",
                "record_type": "recovery_plan",
                "producer_node_id": old_id,
                "port": "recovery_plan",
                "schema": "RecoveryPlan",
                "value": {
                    "action": "pause",
                    "responsible_actor": "controller",
                    "graph_changes": [
                        {"op": "set_node_state", "node_id": old_id, "state": "blocked"}
                    ],
                    "reason": reason,
                    "failure_class": "infrastructure_failure",
                    "retry_basis": "no_differentiating_action",
                },
            },
        ),
        _event(
            "node_deferred",
            {"node_id": old_id, "reason": f"recovery_authorization_required:{failure_id}"},
        ),
    ]
    async with sessions() as session:
        await GraphEventStore(session).append_events(run_id, 0, seed_events)
        await session.commit()
    replacement = {**node, "node_id": replacement_id, "state": "planned"}
    replacement["effect_contract"] = "effectful_write"
    replacement_edges = []
    for edge in edge_specs:
        replacement_edge = dict(edge)
        replacement_edge["op"] = "create_edge"
        replacement_edge["edge_id"] = f"{edge['edge_id']}-replacement"
        if replacement_edge["from_node_id"] == old_id:
            replacement_edge["from_node_id"] = replacement_id
        if replacement_edge["to_node_id"] == old_id:
            replacement_edge["to_node_id"] = replacement_id
        replacement_edge["required"] = True
        replacement_edge["prompt_hydration_policy"] = "structured_json"
        replacement_edges.append(replacement_edge)

    response = await client.post(
        f"/api/runs/{run_id}/graph/patch",
        json={
            "patch_id": "repair-live-blocked-worker",
            "base_graph_position": len(seed_events),
            "ops": [
                {"op": "retire_node", "node_id": old_id},
                {"op": "create_node", "node": replacement},
                *replacement_edges,
            ],
        },
    )

    assert response.status_code == 200, response.text
    projection_response = await client.get(f"/api/runs/{run_id}/graph")
    assert projection_response.status_code == 200
    states = projection_response.json()["node_states"]
    assert states[old_id] == "retired"
    assert states[replacement_id] == "planned"
    events = await _events(client, run_id)
    created = [
        event
        for event in events
        if event["event_type"] == "node_created"
        and event["payload"].get("node_id") == replacement_id
    ]
    assert len(created) == 1
    assert created[0]["payload"]["effect_contract"] == "effectful_write"

    controller = GraphController(
        sessions,
        FakeClock(),
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
    )
    patched_position = response.json()["graph_position"]
    resuming = await controller.handle_command(run_id, patched_position, "resume")
    active = await controller.handle_command(
        run_id,
        resuming.projection_position,
        "resume",
    )
    scheduled = await controller.handle_command(
        run_id,
        active.projection_position,
        "schedule_tick",
        {
            "max_grants": 1,
            "lease_seconds": 60,
            "priorities": {replacement_id: 100},
            "base_snapshot_id": "baseline-live-repair",
        },
    )
    grants = [event for event in scheduled.events if event.event_type == "lease_granted"]
    assert len(grants) == 1, [(event.event_type, event.payload) for event in scheduled.events]
    assert grants[0].payload["node_id"] == replacement_id


async def test_file_sqlite_public_api_repairs_synthetic_position_455_semantic_plan_revision(
    tmp_path: Any,
) -> None:
    """A focused synthetic 455-event stream survives the real HTTP/store path."""
    repos_dir = tmp_path / "repos"
    worktrees_dir = tmp_path / "worktrees"
    repos_dir.mkdir()
    worktrees_dir.mkdir()
    app = create_app(
        db_path=str(tmp_path / "orchestrator.db"),
        routine_dirs=[],
        global_config=GlobalConfig(
            paths=PathsConfig(
                repos_dir=str(repos_dir),
                worktrees_dir=str(worktrees_dir),
            )
        ),
    )
    app.state.signal_transport = InMemorySignalTransport()
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            run_id = "graph-fr18-exact-position-455"
            sessions: async_sessionmaker[AsyncSession] = app.state.session_factory
            await _save_graph_run(sessions, run_id)
            policy = CacheAuthorityPolicy()
            authority_preimage = canonicalize_cache_authority(policy)
            authority_hash = cache_authority_hash(policy)
            artifact_id = "semantic-artifact-exec-original"
            report_id = "verification-exec-original"
            old_id = "worker-reliable-plan-recovery"
            replacement_id = f"{old_id}-v2"
            reason = (
                "submission quality gate contract is invalid: worker effect_contract is missing"
            )
            authority = {
                "allowed_actions": [
                    "submit_records",
                    "request_clarification",
                    "raise_appeal",
                ],
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["."]}],
            }
            old_node = {
                "node_id": old_id,
                "kind": "worker",
                "role": "fixer",
                "state": "planned",
                "task_region_id": "reliable-plan-recovery-attempt",
                "attempt_number": 2,
                "candidate_id": "semantic-artifact-recovery",
                "failed_candidate_id": artifact_id,
                "base_snapshot_selection": "run_baseline",
                "authority": authority,
                "recovery_reason": "Revise the rejected semantic plan artifact.",
                "recovery_of_record_id": artifact_id,
                "patch_id": "revision-recovery-plan-contract",
                "access_mode": "write",
                "acceptance": ["Every declared batch has explicit recovery."],
                "bound_requirement_ids": ["dynamic_feature_acceptance"],
                "invariants": ["Preserve accepted typed plan lineage."],
                "objective": "Revise the failed typed semantic plan.",
                "prohibited_actions": ["Do not execute an implementation batch."],
                "scope": "the rejected semantic plan artifact",
                "cache_authority_hash": authority_hash,
                "semantic_stage": "corrective_work",
                "semantic_schema_id": "reliable-plan-implementation-plan",
                "semantic_schema_version": 1,
            }
            edge_specs = [
                {
                    "edge_id": "edge-failed-verification-to-recovery-worker",
                    "from_node_id": "verifier-reliable-plan-discovery",
                    "from_port": "verification_report",
                    "to_node_id": old_id,
                    "to_port": "verification_report",
                    "required": True,
                    "dependency_type": "input_binding",
                    "accepted_record_selector": {
                        "record_id": report_id,
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "failed",
                    },
                    "prompt_hydration_policy": "structured_json",
                },
                {
                    "edge_id": "edge-recovery-candidate-to-verifier",
                    "from_node_id": old_id,
                    "from_port": "candidate",
                    "to_node_id": "verifier-reliable-plan-recovery",
                    "to_port": "candidate_under_test",
                    "required": True,
                    "dependency_type": "input_binding",
                    "accepted_record_selector": {
                        "record_type": "candidate",
                        "schema": "ImplementationCandidate",
                    },
                    "prompt_hydration_policy": "structured_json",
                },
                {
                    "edge_id": "edge-recovery-artifact-to-verifier",
                    "from_node_id": old_id,
                    "from_port": "semantic_artifact",
                    "to_node_id": "verifier-reliable-plan-recovery",
                    "to_port": "semantic_artifact",
                    "required": True,
                    "dependency_type": "input_binding",
                    "accepted_record_selector": {
                        "record_type": "semantic_artifact",
                        "schema": "SemanticArtifact",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                    },
                    "prompt_hydration_policy": "structured_json",
                },
            ]
            seed_events = [
                _event("run_lifecycle_changed", {"to_state": "paused"}),
                _event(
                    "node_created",
                    {
                        "node_id": "routine-snapshot",
                        "kind": "artifact",
                        "role": "routine_snapshot",
                        "state": "completed",
                        "cache_authority_hash": authority_hash,
                    },
                ),
                _event(
                    "output_record_accepted",
                    {
                        "record_id": "routine-snapshot-record",
                        "record_kind": "graph_record",
                        "record_type": "routine_snapshot",
                        "producer_node_id": "routine-snapshot",
                        "port": "routine_snapshot",
                        "schema": "RoutineSnapshot",
                        "value": {
                            "routine_id": "dynamic-graph-feature",
                            "name": "Dynamic graph feature",
                            "content_hash": "fixture-content-hash",
                            "step_count": 1,
                            "task_count": 1,
                            "cache_authority_version": "cache-authority-v1",
                            "cache_authority_preimage": authority_preimage,
                            "cache_authority_hash": authority_hash,
                        },
                    },
                ),
                _event(
                    "output_record_accepted",
                    {
                        "record_id": "schema-reliable-plan-v1",
                        "record_kind": "graph_record",
                        "record_type": "semantic_schema_declaration",
                        "schema_version": 1,
                        "producer_node_id": "routine-snapshot",
                        "port": "semantic_schema_declaration",
                        "schema": "SemanticSchemaDeclaration",
                        "value": {
                            "schema_id": "reliable-plan-implementation-plan",
                            "version": 1,
                            "semantic_role": "implementation_plan",
                            "json_schema": {"type": "object"},
                            "authority": "routine_snapshot",
                        },
                    },
                ),
                _event(
                    "node_created",
                    {
                        "node_id": "requirement-dynamic-feature-acceptance",
                        "kind": "requirement",
                        "state": "completed",
                        "cache_authority_hash": authority_hash,
                    },
                ),
                _event(
                    "output_record_accepted",
                    {
                        "record_id": "requirement-dynamic-feature-acceptance",
                        "record_kind": "graph_record",
                        "record_type": "requirement_record",
                        "producer_node_id": "requirement-dynamic-feature-acceptance",
                        "port": "requirement",
                        "schema": "RequirementRecord",
                        "value": {
                            "id": "dynamic_feature_acceptance",
                            "text": "The dynamic feature contract is satisfied.",
                            "must": True,
                        },
                    },
                ),
                _event(
                    "node_created",
                    {
                        "node_id": "worker-reliable-plan-discovery",
                        "kind": "worker",
                        "role": "discovery",
                        "state": "completed",
                        "access_mode": "read_only",
                        "effect_contract": "read_only_semantic",
                        "semantic_stage": "discovery",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "cache_authority_hash": authority_hash,
                    },
                ),
                _event(
                    "output_record_accepted",
                    {
                        "record_id": artifact_id,
                        "record_kind": "graph_record",
                        "record_type": "semantic_artifact",
                        "schema_version": 1,
                        "producer_node_id": "worker-reliable-plan-discovery",
                        "port": "semantic_artifact",
                        "schema": "SemanticArtifact",
                        "value": {
                            "semantic_role": "implementation_plan",
                            "schema_id": "reliable-plan-implementation-plan",
                            "schema_version": 1,
                            "content": {"batches": [{"batch_id": "slice-1"}]},
                            "provenance": {"source": "discovery"},
                            "source_record_ids": [],
                            "requirement_ids": ["requirement-dynamic-feature-acceptance"],
                            "task_region_id": "reliable-plan-discovery",
                            "validation_status": "validated",
                            "authority_status": "accepted",
                        },
                    },
                ),
                _event(
                    "node_created",
                    {
                        "node_id": "verifier-reliable-plan-discovery",
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "completed",
                        "semantic_stage": "plan_verification",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "cache_authority_hash": authority_hash,
                    },
                ),
                _event(
                    "output_record_accepted",
                    {
                        "record_id": report_id,
                        "record_kind": "verification",
                        "record_type": "verification_report",
                        "producer_node_id": "verifier-reliable-plan-discovery",
                        "port": "verification_report",
                        "schema": "VerificationReport",
                        "candidate_id": artifact_id,
                        "candidate_record_id": artifact_id,
                        "candidate_record_ids": [artifact_id],
                        "outcome": "failed",
                        "value": {"outcome": "failed", "grades": []},
                        "evaluated_record_ids": [
                            artifact_id,
                            "requirement-dynamic-feature-acceptance",
                        ],
                    },
                ),
            ]
            seed_events.extend(
                _event("command_rejected", {"command_type": "padding", "reason": "padding"})
                for _ in range(409)
            )
            seed_events.extend(
                [
                    _event("node_created", old_node),
                    _event(
                        "node_created",
                        {
                            "node_id": "verifier-reliable-plan-recovery",
                            "kind": "verifier",
                            "role": "verifier",
                            "state": "planned",
                            "task_region_id": "reliable-plan-recovery-attempt",
                            "failed_candidate_id": artifact_id,
                            "cache_authority_hash": authority_hash,
                        },
                    ),
                    _event("edge_created", edge_specs[0]),
                    _event("command_rejected", {"command_type": "padding", "reason": "padding"}),
                    _event("edge_created", edge_specs[1]),
                    _event("edge_created", edge_specs[2]),
                    _event(
                        "lease_granted",
                        {
                            "lease_id": "lease-old",
                            "node_id": old_id,
                            "generation": 1,
                            "cache_authority_hash": authority_hash,
                        },
                    ),
                    _event(
                        "lease_revoked",
                        {
                            "lease_id": "lease-old",
                            "node_id": old_id,
                            "generation": 1,
                            "reason": reason,
                        },
                    ),
                    _event(
                        "node_state_changed",
                        {"node_id": old_id, "new_state": "blocked", "trigger": "agent_died"},
                    ),
                ]
            )
            seed_events.extend(
                _event("command_rejected", {"command_type": "padding", "reason": "padding"})
                for _ in range(23)
            )
            failure_id = f"failure-{old_id}-lease-old"
            seed_events.extend(
                [
                    _event(
                        "output_record_accepted",
                        {
                            "record_id": failure_id,
                            "record_kind": "graph_record",
                            "record_type": "failure_record",
                            "producer_node_id": old_id,
                            "port": "failure_record",
                            "schema": "FailureRecord",
                            "value": {
                                "failed_node_id": old_id,
                                "phase": "runtime",
                                "failure_class": "infrastructure_failure",
                                "error_class": "runtime_death_recovery_required",
                                "retryable": True,
                                "lease_id": "lease-old",
                                "reason": reason,
                            },
                        },
                    ),
                    _event(
                        "output_record_accepted",
                        {
                            "record_id": f"recovery-plan-{old_id}-lease-old",
                            "record_kind": "output",
                            "record_type": "recovery_plan",
                            "producer_node_id": old_id,
                            "port": "recovery_plan",
                            "schema": "RecoveryPlan",
                            "value": {
                                "action": "pause",
                                "responsible_actor": "controller",
                                "graph_changes": [
                                    {"op": "set_node_state", "node_id": old_id, "state": "blocked"}
                                ],
                                "reason": reason,
                                "failure_class": "infrastructure_failure",
                                "retry_basis": "no_differentiating_action",
                            },
                        },
                    ),
                    _event("command_rejected", {"command_type": "padding", "reason": "padding"}),
                    _event(
                        "node_deferred",
                        {
                            "node_id": old_id,
                            "reason": f"recovery_authorization_required:{failure_id}",
                        },
                    ),
                ]
            )
            assert len(seed_events) == 455
            async with sessions() as session:
                store = GraphEventStore(session)
                await store.append_events(run_id, 0, seed_events)
                await store.rebuild_archival_views(run_id)
                await session.commit()

            replacement = {
                **old_node,
                "node_id": replacement_id,
                "state": "planned",
                "patch_id": "repair-live-blocked-worker-v2",
                "effect_contract": "effectful_write",
            }
            replacement_edges = []
            for edge in edge_specs:
                replacement_edge = {**edge, "op": "create_edge"}
                replacement_edge["edge_id"] = f"{edge['edge_id']}-v2"
                if replacement_edge["from_node_id"] == old_id:
                    replacement_edge["from_node_id"] = replacement_id
                if replacement_edge["to_node_id"] == old_id:
                    replacement_edge["to_node_id"] = replacement_id
                replacement_edges.append(replacement_edge)
            response = await client.post(
                f"/api/runs/{run_id}/graph/patch",
                json={
                    "patch_id": "repair-live-blocked-worker-v2",
                    "base_graph_position": 455,
                    "ops": [
                        {"op": "retire_node", "node_id": old_id},
                        {"op": "create_node", "node": replacement},
                        *replacement_edges,
                    ],
                },
            )
            assert response.status_code == 200, response.text
            async with sessions() as session:
                await GraphEventStore(session).rebuild_archival_views(run_id)
                await session.commit()
            topology_response = await client.get(f"/api/runs/{run_id}/graph/topology")
            assert topology_response.status_code == 200, topology_response.text
            topology = topology_response.json()
            assert len(topology["edges"]) == 6
            states = {node["node_id"]: node["state"] for node in topology["nodes"]}
            assert states[old_id] == "retired"
            assert states[replacement_id] == "planned"

            controller = GraphController(
                sessions,
                FakeClock(),
                _RunSeedIdGenerator(run_id),
                auto_dispatch=False,
            )
            resuming = await controller.handle_command(
                run_id, response.json()["graph_position"], "resume"
            )
            active = await controller.handle_command(run_id, resuming.projection_position, "resume")
            scheduled = await controller.handle_command(
                run_id,
                active.projection_position,
                "schedule_tick",
                {
                    "max_grants": 1,
                    "lease_seconds": 60,
                    "priorities": {replacement_id: 100},
                    "base_snapshot_id": "baseline-live-repair",
                },
            )
            grants = [event for event in scheduled.events if event.event_type == "lease_granted"]
            assert [event.payload["node_id"] for event in grants] == [replacement_id]
    finally:
        await app.state.engine.dispose()


async def test_file_sqlite_public_api_repairs_exported_canonical_position_455_stream(
    tmp_path: Any,
) -> None:
    """Replay the hash-pinned live export unchanged through the production path."""
    raw_document, fixture_events = _load_fr18_fixture()
    repair = _exact_fr18_closed_repair(fixture_events)
    run_id = _FR18_FIXTURE_RUN_ID
    old_id = "worker-reliable-plan-recovery"
    replacement_id = f"{old_id}-v2"
    original_edge_ids = {
        "edge-failed-verification-to-recovery-worker",
        "edge-recovery-candidate-to-verifier",
        "edge-recovery-artifact-to-verifier",
    }
    replacement_edge_ids = {f"{edge_id}-v2" for edge_id in original_edge_ids}

    repos_dir = tmp_path / "repos"
    worktrees_dir = tmp_path / "worktrees"
    repos_dir.mkdir()
    worktrees_dir.mkdir()
    app = create_app(
        db_path=str(tmp_path / "orchestrator.db"),
        routine_dirs=[],
        global_config=GlobalConfig(
            paths=PathsConfig(
                repos_dir=str(repos_dir),
                worktrees_dir=str(worktrees_dir),
            )
        ),
    )
    app.state.signal_transport = InMemorySignalTransport()
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    try:
        sessions: async_sessionmaker[AsyncSession] = app.state.session_factory
        await _save_graph_run(sessions, run_id)
        async with sessions() as session:
            store = GraphEventStore(session)
            stored = await store.append_events(run_id, 0, fixture_events)
            assert [event.model_dump(mode="json") for event in stored] == raw_document["events"]
            persisted = await store.read_run(run_id)
            assert [event.model_dump(mode="json") for event in persisted] == raw_document["events"]
            await store.rebuild_archival_views(run_id)
            await session.commit()

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            before_response = await client.get(f"/api/runs/{run_id}/graph/topology")
            assert before_response.status_code == 200, before_response.text
            before = before_response.json()
            before_node_ids = {node["node_id"] for node in before["nodes"]}
            before_edge_ids = {edge["edge_id"] for edge in before["edges"]}
            assert old_id in before_node_ids
            assert original_edge_ids <= before_edge_ids
            assert replacement_id not in before_node_ids
            assert replacement_edge_ids.isdisjoint(before_edge_ids)

            response = await client.post(
                f"/api/runs/{run_id}/graph/patch",
                json=repair,
            )
            assert response.status_code == 200, response.text
            assert response.json()["graph_position"] == 463

            async with sessions() as session:
                store = GraphEventStore(session)
                appended = await store.read_run(run_id, from_position=456)
                assert [event.event_type for event in appended] == [
                    "graph_patch_accepted",
                    "node_retired",
                    "node_state_changed",
                    "node_created",
                    "edge_created",
                    "input_bound",
                    "edge_created",
                    "edge_created",
                ]
                created = next(event for event in appended if event.event_type == "node_created")
                assert created.payload == repair["ops"][1]["node"]
                created_edge_payloads = {
                    event.payload["edge_id"]: event.payload
                    for event in appended
                    if event.event_type == "edge_created"
                }
                assert set(created_edge_payloads) == replacement_edge_ids
                for requested in repair["ops"][2:]:
                    emitted = created_edge_payloads[requested["edge_id"]]
                    assert emitted == {
                        key: value for key, value in requested.items() if key != "op"
                    } | {"patch_id": repair["patch_id"]}
                await store.rebuild_archival_views(run_id)
                await session.commit()

            after_response = await client.get(f"/api/runs/{run_id}/graph/topology")
            assert after_response.status_code == 200, after_response.text
            after = after_response.json()
            after_node_ids = {node["node_id"] for node in after["nodes"]}
            after_edge_ids = {edge["edge_id"] for edge in after["edges"]}
            assert after_node_ids - before_node_ids == {replacement_id}
            assert after_edge_ids - before_edge_ids == replacement_edge_ids
            assert before_edge_ids <= after_edge_ids
            states = {node["node_id"]: node["state"] for node in after["nodes"]}
            assert states[old_id] == "retired"
            assert states[replacement_id] == "planned"

        controller = GraphController(
            sessions,
            FakeClock(),
            _RunSeedIdGenerator(run_id),
            auto_dispatch=False,
        )
        resuming = await controller.handle_command(run_id, 463, "resume")
        active = await controller.handle_command(
            run_id,
            resuming.projection_position,
            "resume",
        )
        scheduled = await controller.handle_command(
            run_id,
            active.projection_position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "priorities": {replacement_id: 100},
                "base_snapshot_id": "baseline-live-repair",
            },
        )
        grants = [event for event in scheduled.events if event.event_type == "lease_granted"]
        assert [event.payload["node_id"] for event in grants] == [replacement_id]
        projection = await controller.read_projection(run_id)
        active_leases = [
            lease for lease in leases_view(projection).values() if lease.state == "active"
        ]
        assert len(active_leases) == 1
        assert active_leases[0].node_id == replacement_id
    finally:
        await app.state.engine.dispose()


async def _patches(client: AsyncClient, run_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/runs/{run_id}/graph/patches")
    assert response.status_code == 200
    return response.json()


async def _seed_authority_denial_graph_run(app: Any, run_id: str) -> None:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_graph_run(session_factory, run_id)
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {"node_id": "authority-1", "kind": "authority_request", "state": "running"},
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "authority-request-1",
                "record_kind": "graph_record",
                "record_type": "authority_request_record",
                "producer_node_id": "authority-1",
                "port": "authority_request_record",
                "schema": "AuthorityRequest",
                "value": {
                    "requested_authority": ["repo:docs/**:write"],
                    "target_node_id": "worker-docs",
                    "reason": "Worker needs docs write access.",
                },
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-authority-request",
                "from_node_id": "authority-1",
                "from_port": "authority_request_record",
                "to_node_id": "authority-1",
                "to_port": "authority_request_record",
            },
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-authority-request",
                "to_node_id": "authority-1",
                "to_port": "authority_request_record",
                "record_ids": ["authority-request-1"],
            },
        ),
        _event(
            "lease_granted",
            {
                "lease_id": "lease-authority-1",
                "node_id": "authority-1",
                "generation": 1,
                "execution_id": "exec-authority-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-docs",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-authority-worker",
                "from_node_id": "authority-1",
                "from_port": "authority_decision",
                "to_node_id": "worker-docs",
                "to_port": "authority",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "authority_decision",
                    "schema": "AuthorityDecision",
                },
            },
        ),
    ]
    async with session_factory() as session:
        store = GraphEventStore(session)
        await store.append_events(run_id, 0, events)
        await store.rebuild_archival_views(run_id)
        await session.commit()


async def test_fr08_invalid_patch_matrix_rejected_and_readable(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-fr08-patch-{uuid4().hex[:8]}"
    controller = await _seed_invalid_patch_graph_run(app, run_id)

    await _submit_patch(
        controller,
        run_id,
        expected_position=7,
        patch_id="patch-stale",
        base_graph_position=6,
        ops=[{"op": "retire_node", "node_id": "worker-stale"}],
    )
    await _submit_patch(
        controller,
        run_id,
        expected_position=8,
        patch_id="patch-unauthorized",
        actor_role="worker",
        ops=[{"op": "create_node", "node": {"node_id": "artifact-unauth", "kind": "artifact"}}],
    )
    await _submit_patch(
        controller,
        run_id,
        expected_position=9,
        patch_id="patch-duplicate-node",
        ops=[
            {
                "op": "create_node",
                "node": {"node_id": "worker-1", "kind": "worker", "role": "builder"},
            }
        ],
    )
    await _submit_patch(
        controller,
        run_id,
        expected_position=10,
        patch_id="patch-hidden-command",
        ops=[
            {
                "op": "create_node",
                "node": {
                    "node_id": "check-hidden",
                    "kind": "check",
                    "role": "invariant_gate",
                    "state": "planned",
                    "hidden_oracle_command": SECRET_COMMAND,
                },
            },
            {
                "op": "create_edge",
                "edge_id": "edge-verifier-check-hidden",
                "from_node_id": "verifier-1",
                "from_port": "verification_report",
                "to_node_id": "check-hidden",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "any_of",
                    "selectors": [
                        {"record_type": "verification_report", "schema": "VerificationReport"},
                        {"record_type": "check_result", "schema": "CheckResult"},
                    ],
                },
            },
        ],
    )
    await _submit_patch(
        controller,
        run_id,
        expected_position=11,
        patch_id="patch-resource-escalation",
        ops=[
            {
                "op": "set_resource_claims",
                "node_id": "worker-1",
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["docs/"]}],
            }
        ],
    )
    await _submit_patch(
        controller,
        run_id,
        expected_position=12,
        patch_id="patch-active-retire",
        ops=[{"op": "retire_node", "node_id": "worker-1"}],
    )
    await _submit_patch(
        controller,
        run_id,
        expected_position=13,
        patch_id="patch-invalid-revision-composite",
        ops=[
            {
                "op": "create_revision_attempt",
                "task_region_id": "region-revision",
                "failed_candidate_id": "candidate-failed",
                "worker_node": {
                    "node_id": "worker-revision-invalid",
                    "kind": "worker",
                    "role": "builder",
                    "state": "planned",
                    "objective": "Produce a corrected candidate.",
                    "access_mode": "write",
                    "acceptance": ["candidate resolves the failed requirement"],
                },
                "verifier_node": {
                    "node_id": "verifier-revision-invalid",
                    "kind": "verifier",
                    "role": "verifier",
                    "state": "planned",
                },
            }
        ],
    )

    events = await _events(client, run_id)
    patch_view = await _patches(client, run_id)
    topology_resp = await client.get(f"/api/runs/{run_id}/graph/topology")
    assert topology_resp.status_code == 200

    rejected = [event for event in events if event["event_type"] == "graph_patch_rejected"]
    assert [event["payload"]["patch_id"] for event in rejected] == [
        "patch-stale",
        "patch-unauthorized",
        "patch-duplicate-node",
        "patch-hidden-command",
        "patch-resource-escalation",
        "patch-active-retire",
        "patch-invalid-revision-composite",
    ]
    expected_reasons = {
        "patch-stale": "stale patch conflicts with invalidating events",
        "patch-unauthorized": "actor role worker cannot perform create_node",
        "patch-duplicate-node": "duplicate node id: worker-1",
        "patch-hidden-command": (
            "check node cannot expose hidden_oracle_command; use command_binding: check-hidden"
        ),
        "patch-resource-escalation": "resource claim escalation for worker-1: write",
        "patch-active-retire": "cannot retire active node: worker-1",
        "patch-invalid-revision-composite": (
            "worker node requires a valid effect_contract: worker-revision-invalid"
        ),
    }
    assert {event["payload"]["patch_id"]: event["payload"]["reason"] for event in rejected} == (
        expected_reasons
    )
    stale_payload = rejected[0]["payload"]
    assert stale_payload["read_set_diff"]["patch_read_set"] == ["worker-stale"]
    assert stale_payload["read_set_diff"]["conflicting_event_ids"]

    attempts = patch_view["attempts"]
    assert [attempt["patch_id"] for attempt in attempts] == list(expected_reasons)
    assert {attempt["patch_id"]: attempt["status"] for attempt in attempts} == {
        patch_id: "rejected" for patch_id in expected_reasons
    }
    assert {attempt["patch_id"]: attempt["rejection_reason"] for attempt in attempts} == (
        expected_reasons
    )
    assert all(attempt["created_node_ids"] == [] for attempt in attempts)
    assert all(attempt["created_edge_ids"] == [] for attempt in attempts)
    invalid_composite_events = [
        event
        for event in events
        if event["payload"].get("node_id")
        in {"worker-revision-invalid", "verifier-revision-invalid"}
        or event["payload"].get("producer_node_id")
        in {"worker-revision-invalid", "verifier-revision-invalid"}
    ]
    assert invalid_composite_events == []
    assert not any(
        event["event_type"]
        in {
            "revision_created",
            "lease_granted",
            "baseline_created",
            "runtime_retry_scheduled",
        }
        and (
            event["payload"].get("node_id")
            in {"worker-revision-invalid", "verifier-revision-invalid"}
            or event["payload"].get("worker_node", {}).get("node_id") == "worker-revision-invalid"
        )
        for event in events
    )
    topology = topology_resp.json()
    assert {node["node_id"] for node in topology["nodes"]} == {
        "planner-1",
        "verifier-1",
        "worker-1",
        "worker-stale",
    }
    assert topology["edges"] == []
    assert SECRET_COMMAND not in json.dumps(events)
    assert SECRET_COMMAND not in json.dumps(patch_view)


async def test_fr08_authority_denial_and_rejection_readbacks(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-fr08-authority-{uuid4().hex[:8]}"
    await _seed_authority_denial_graph_run(app, run_id)

    response = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "authority",
            "node_id": "authority-1",
            "decision": "denied",
            "decider": {"kind": "human", "id": "alice"},
            "reason": "Rejected for FR-08 denial proof.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    event_types = [event["event_type"] for event in body["events"]]
    assert event_types[:5] == [
        "authority_decision_recorded",
        "output_record_accepted",
        "input_bound",
        "node_state_changed",
        "lease_released",
    ]
    assert "node_deferred" in event_types
    decision_record = body["events"][1]["payload"]
    assert decision_record["record_type"] == "authority_decision"
    assert decision_record["value"]["decision"] == "denied"
    assert body["events"][4]["payload"]["lease_id"] == "lease-authority-1"
    assert any(
        event["event_type"] == "node_deferred"
        and event["payload"]
        == {
            "node_id": "worker-docs",
            "reason": "authority_not_granted:authority-1",
        }
        for event in body["events"]
    )

    # Authority denial completes the authority node and binds its decision
    # record, both of which change the archival topology.  The last complete
    # generation must fail closed until the maintenance writer republishes it.
    stale_topology = await client.get(f"/api/runs/{run_id}/graph/topology")
    assert stale_topology.status_code == 503
    async with app.state.session_factory() as session:
        await GraphEventStore(session).rebuild_archival_views(run_id)
        await session.commit()

    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    authority_resp = await client.get(
        f"/api/runs/{run_id}/graph/nodes/authority-1?payload_mode=full"
    )
    worker_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/worker-docs")
    topology_resp = await client.get(f"/api/runs/{run_id}/graph/topology")
    events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")
    assert scheduler_resp.status_code == 200
    assert authority_resp.status_code == 200
    assert worker_resp.status_code == 200
    assert topology_resp.status_code == 200
    assert events_resp.status_code == 200

    scheduler = scheduler_resp.json()
    authority = authority_resp.json()
    worker = worker_resp.json()
    assert scheduler["scheduler"]["ready"] == []
    assert scheduler["scheduler"]["blocked"] == []
    assert scheduler["leases"]["active"] == []
    assert authority["state"] == "completed"
    authority_decisions = [
        record
        for record in authority["output_records"]
        if record["record_type"] == "authority_decision"
    ]
    assert len(authority_decisions) == 1
    assert authority_decisions[0]["value"]["decision"] == "denied"
    assert worker["state"] == "planned"
    assert worker["input_ports"]["authority"] == ["authority_decision-authority-1"]
    authority_edge = next(
        edge for edge in topology_resp.json()["edges"] if edge["edge_id"] == "edge-authority-worker"
    )
    assert authority_edge["binding"]["record_ids"] == ["authority_decision-authority-1"]

    invalid_target = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "authority",
            "node_id": "worker-docs",
            "decision": "granted",
            "decider": {"kind": "human", "id": "alice"},
        },
    )
    assert invalid_target.status_code == 409
    assert "authority decisions require authority_request target" in invalid_target.text

    invalid_shape = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "authority",
            "node_id": "authority-1",
            "decision": "approved",
            "decider": {"kind": "human", "id": "alice"},
        },
    )
    assert invalid_shape.status_code == 422
    assert "decision for authority must be one of" in invalid_shape.text

    events = events_resp.json()
    assert any(
        event["event_type"] == "authority_decision_recorded"
        and event["payload"]["decision"] == "denied"
        for event in events
    )
    assert not any(
        event["event_type"] == "output_record_accepted"
        and event["payload"].get("producer_node_id") == "worker-docs"
        for event in events
    )
