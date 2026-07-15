from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from scripts.codemods.w5_strict_payload_cutover import (
    AllowlistConsumer,
    CatalogInjection,
    CommandRoute,
    DomainMigration,
    EventRoute,
    ImportRoute,
    StrictPayloadCutoverCodemod,
    SymbolRelocation,
    VERTICAL_SLICE_MIGRATION,
    DOMAIN_MIGRATIONS,
    run_migration,
)
from scripts.codemods.w5_task12_event_payload_reads import (
    transform_test_source as transform_task13_reads,
    transform_source as transform_task12_reads,
)


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("domain", "migration"),
    tuple(sorted(DOMAIN_MIGRATIONS.items())),
    ids=tuple(sorted(DOMAIN_MIGRATIONS)),
)
def test_every_registered_domain_is_catalog_wide_clean_and_idempotent(
    domain: str, migration: DomainMigration
) -> None:
    root = Path(__file__).parents[2]

    second_run = run_migration(migration, root, "assert-clean")
    assert second_run.exit_code == 0, f"{domain}:\n{second_run.output}"
    assert second_run.output == "", domain


@pytest.mark.timeout(120)
def test_measurement_counts_actual_first_and_second_diffs_not_noop_visits() -> None:
    root = Path(__file__).parents[2]

    result = run_migration(DOMAIN_MIGRATIONS["complete_reads"], root, "measure")

    assert result.eligible_sites == 0, result.output
    assert result.second_run_changes == 0, result.output


def test_task12_payload_read_codemod_transforms_all_raw_reads_and_is_idempotent() -> None:
    source = """\
def current(event: EventEnvelope):
    return event.payload.get("node_id"), event.payload["generation"]

def _history_payload_value(event: EventEnvelope):
    return event.payload.get("node_id")
"""

    first, changes = transform_task12_reads(source, "src/orchestrator/graph/callbacks.py")
    second, second_changes = transform_task12_reads(first, "src/orchestrator/graph/callbacks.py")

    assert changes == 3
    assert first.count('event_payload_json(event).get("node_id")') == 2
    assert 'event_payload_json(event)["generation"]' in first
    assert "event.payload.get(" not in first
    assert "event.payload[" not in first
    assert second == first
    assert second_changes == 0


def test_task13_test_payload_read_codemod_routes_hydrated_mapping_reads_to_json_once() -> None:
    source = """\
from orchestrator.graph import EventEnvelope

def current(event):
    return event.payload.get("node_id"), event.payload["generation"], event.payload.items(), events[-1].payload["node_id"], result.events[0].payload.get("reason")

def nested(event):
    return event.payload.record.record_id

def corruption(envelope: EventEnvelope):
    return envelope.payload.get("node_id"), envelope.payload["generation"], envelope.payload.items()
"""

    first, changes = transform_task13_reads(source, "tests/unit/test_example.py")
    second, second_changes = transform_task13_reads(first, "tests/unit/test_example.py")

    assert changes == 5
    assert 'event_payload_json(event).get("node_id")' in first
    assert 'event_payload_json(event)["generation"]' in first
    assert "event_payload_json(event).items()" in first
    assert 'event_payload_json(events[-1])["node_id"]' in first
    assert 'event_payload_json(result.events[0]).get("reason")' in first
    assert "event.payload.record.record_id" in first
    assert 'envelope.payload.get("node_id")' in first
    assert 'envelope.payload["generation"]' in first
    assert "envelope.payload.items()" in first
    assert "from orchestrator.graph import EventEnvelope, event_payload_json" in first
    assert (
        first
        == """\
from orchestrator.graph import EventEnvelope, event_payload_json

def current(event):
    return event_payload_json(event).get("node_id"), event_payload_json(event)["generation"], event_payload_json(event).items(), event_payload_json(events[-1])["node_id"], event_payload_json(result.events[0]).get("reason")

def nested(event):
    return event.payload.record.record_id

def corruption(envelope: EventEnvelope):
    return envelope.payload.get("node_id"), envelope.payload["generation"], envelope.payload.items()
"""
    )
    assert second == first
    assert second_changes == 0


def test_task13_test_payload_read_codemod_routes_hydrated_payload_aliases_to_json_once() -> None:
    source = """\
from orchestrator.graph import EventEnvelope

def current(event):
    payload = event.payload
    return payload["node_id"], payload.get("generation"), payload.items()

def corruption(envelope: EventEnvelope):
    payload = envelope.payload
    return payload["node_id"], payload.get("generation"), payload.items()
"""

    first, changes = transform_task13_reads(source, "tests/unit/test_example.py")
    second, second_changes = transform_task13_reads(first, "tests/unit/test_example.py")

    assert changes == 1
    assert "payload = event_payload_json(event)" in first
    assert "payload = envelope.payload" in first
    assert 'return payload["node_id"], payload.get("generation"), payload.items()' in first
    assert second == first
    assert second_changes == 0


def test_task13_test_payload_read_codemod_routes_hydrated_generator_aliases_to_json_once() -> None:
    source = """\
from orchestrator.graph import EventEnvelope

def current(events):
    payload = next(event.payload for event in events)
    return payload["node_id"]

def typed(events):
    result = next(event.payload for event in events)
    return result.node_id

def corruption(envelope: EventEnvelope):
    payload = next(envelope.payload for _ in range(1))
    return payload["node_id"]
"""

    first, changes = transform_task13_reads(source, "tests/unit/test_example.py")
    second, second_changes = transform_task13_reads(first, "tests/unit/test_example.py")

    assert changes == 1
    assert "payload = next(event_payload_json(event) for event in events)" in first
    assert "result = next(event.payload for event in events)" in first
    assert "payload = next(envelope.payload for _ in range(1))" in first
    assert second == first
    assert second_changes == 0


def test_lifecycle_domain_routes_cover_complete_slice() -> None:
    migration = DOMAIN_MIGRATIONS["lifecycle"]

    assert {route.event_name for route in migration.event_routes} == {
        "run_lifecycle_changed",
        "command_rejected",
        "callback_accepted",
        "callback_rejected_stale",
        "callback_rejected_conflict",
        "callback_duplicate_returned",
        "runtime_retry_scheduled",
        "heartbeat_recorded",
        "agent_died",
        "agent_dispatch_requested",
    }
    assert {route.command_name for route in migration.command_routes} == {
        "accept_run",
        "start",
        "pause",
        "resume",
        "cancel",
        "complete",
        "fail",
        "record_heartbeat",
        "agent_died",
        "acknowledge_start",
        "submit_callback",
    }
    assert {relocation.symbol for relocation in migration.relocations} == {
        "RunLifecycleChangedPayload",
        "CommandRejectedPayload",
        "CallbackAcceptedPayload",
        "CallbackRejectedPayload",
        "CallbackDuplicateReturnedPayload",
        "RuntimeRetryScheduledPayload",
        "AgentDiedPayload",
        "build_agent_died_effects",
    }


def test_remaining_domain_migrations_cover_authoritative_routing_surface() -> None:
    expected = {
        "topology": (
            {
                "node_created",
                "node_state_changed",
                "node_retired",
                "node_ready",
                "node_deferred",
                "node_authority_changed",
                "plan_region_marked_suspect",
                "edge_created",
                "input_bound",
                "session_state_changed",
                "dead_input_detected",
                "revision_created",
            },
            {"seed_compiled_events"},
            "src/orchestrator/graph/events/topology.py",
        ),
        "leases": (
            {"lease_granted", "lease_renewed", "lease_released", "lease_revoked", "lease_expired"},
            {"schedule_tick", "reconcile"},
            "src/orchestrator/graph/events/leases.py",
        ),
        "records": (
            {"output_record_accepted", "verification_passed", "verification_failed"},
            {"evaluate_join", "evaluate_final_gate"},
            "src/orchestrator/graph/events/records.py",
        ),
        "patches": (
            {"graph_patch_accepted", "graph_patch_rejected"},
            {"submit_patch"},
            "src/orchestrator/graph/events/patches.py",
        ),
        "decisions": (
            {
                "appeal_opened",
                "approval_decision_recorded",
                "authority_decision_recorded",
                "oversight_decision_recorded",
            },
            {"raise_appeal", "record_decision"},
            "src/orchestrator/graph/events/decisions.py",
        ),
        "requirements": (
            {"requirement_revision_recorded", "support_evidence_recorded"},
            {"record_requirement_revision", "record_support_evidence"},
            "src/orchestrator/graph/events/requirements.py",
        ),
        "file_state": (
            {
                "file_state_accepted",
                "file_state_rejected",
                "gatekeeper_verdict_recorded",
                "gatekeeper_cost_recorded",
                "cleanup_requested",
                "cleanup_applied",
            },
            {"record_gatekeeper_verdicts", "record_cleanup_applied"},
            "src/orchestrator/graph/events/file_state.py",
        ),
    }

    for domain, (event_names, command_names, target_module) in expected.items():
        migration = DOMAIN_MIGRATIONS[domain]
        assert {route.event_name for route in migration.event_routes} == event_names
        assert {route.command_name for route in migration.command_routes} == command_names
        assert migration.target_module == target_module


def test_lease_cutover_does_not_require_deleted_compatibility_bridge() -> None:
    assert (
        "src/orchestrator/graph/commands/lease_bridge.py" not in DOMAIN_MIGRATIONS["leases"].paths
    )


def test_lease_codemod_wraps_routed_make_event_with_strict_validator() -> None:
    source = """\
def _apply_schedule_tick(make_event, payload):
    return make_event("lease_granted", payload)
"""
    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["leases"]).transform_source(
        source, "src/orchestrator/graph/_commands.py"
    )
    assert "make_strict_event(make_event, LEASE_GRANTED, payload)" in result.source


def test_fixture_envelope_codemod_hydrates_generation_two_events_once() -> None:
    source = """\
from orchestrator.graph import EventEnvelope

event = EventEnvelope(
    event_id="event-1",
    run_id="run-1",
    position=1,
    event_type="node_created",
    schema_version=1,
    actor=actor,
    timestamp=clock.now(),
    payload={"node_id": "node-1", "kind": "worker"},
)
"""

    migration = DOMAIN_MIGRATIONS["fixture_envelopes"]
    first = StrictPayloadCutoverCodemod(migration).transform_files(
        {"tests/unit/test_example.py": source}
    )

    transformed = first.sources["tests/unit/test_example.py"]
    assert "event = EventEnvelope(" not in transformed
    assert "build_graph_catalog().resolve_event(" in transformed.replace(" ", "")
    assert 'event_type = "node_created"' in transformed
    assert ".hydrate(StoredEventEnvelope(" in transformed
    assert "StoredEventEnvelope(" in transformed
    assert "payload_schema_generation = 2" in transformed
    assert "from orchestrator.graph import StoredEventEnvelope, build_graph_catalog" in transformed
    second = StrictPayloadCutoverCodemod(migration).transform_files(
        {"tests/unit/test_example.py": transformed}
    )
    assert second.sources["tests/unit/test_example.py"] == transformed
    assert second.changes == 0


def test_lease_fixture_codemod_completes_sparse_grants_and_schedule_commands() -> None:
    source = """\
event = _event("lease_granted", {"lease_id": "lease-1", "node_id": "node-1", "generation": 1, "execution_id": "exec-1"})
result = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})
"""
    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["leases"]).transform_source(
        source, "tests/unit/test_graph_commands.py"
    )
    assert '"base_snapshot_id": "S0"' in result.source
    assert '"expires_at": "2026-01-01T00:05:00+00:00"' in result.source
    assert '"resource_claims": []' in result.source
    assert '"lease_seconds": 300' in result.source
    assert '"max_grants": 10' in result.source


def test_patch_fixture_codemod_preserves_actor_role_for_submit_patch_only() -> None:
    source = """\
command_payload = {key: value for key, value in raw_payload.items() if key not in {"run_id", "actor_role"}}
"""
    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["patches"]).transform_source(
        source, "tests/unit/test_graph_commands.py"
    )
    assert 'command_type == "submit_patch"' in result.source


def test_patch_fixture_codemod_preserves_actor_role_in_shared_dispatch_helper() -> None:
    source = """\
raw_payload = dict(payload or {})
actor_role = raw_payload.pop("actor_role", None)
"""
    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["patches"]).transform_source(
        source, "tests/graph_command_support.py"
    )
    assert 'raw_payload.get("actor_role")' in result.source
    assert 'if command_type != "submit_patch":' in result.source
    assert 'raw_payload.pop("actor_role", None)' in result.source


def test_patch_fixture_codemod_completes_strict_event_fields() -> None:
    source = """\
event = _event("graph_patch_accepted", {"patch_id": "patch-1", "proposed_by_node_id": "planner-1", "successor_planner_node_ids": []})
"""
    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["patches"]).transform_source(
        source, "tests/unit/test_graph_commands.py"
    )
    assert '"base_graph_position": -1' in result.source
    assert '"actor_role": "planner"' in result.source


def test_complete_reads_migration_removes_partial_read_helpers() -> None:
    migration = DOMAIN_MIGRATIONS["complete_reads"]
    assert set(migration.allowlist_names) == {
        "GRAPH_PROJECTION_PAYLOAD_FIELDS",
        "LIGHT_GRAPH_PAYLOAD_FIELDS",
        "SUMMARY_REBUILD_PAYLOAD_FIELDS",
        "NODE_DETAIL_PAYLOAD_FIELDS",
    }
    assert {
        "GraphEventStore._read_run_extracting_fields",
        "_node_detail_light_event",
    }.issubset(migration.allowed_allowlist_owners)
    source = """\
from orchestrator.graph import GRAPH_PROJECTION_PAYLOAD_FIELDS\n\nLIGHT_GRAPH_PAYLOAD_FIELDS = (\"node_id\",)\n\nasync def read_run_light(self, run_id, from_position=0):\n    return await self._read_run_extracting_fields(run_id, from_position, LIGHT_GRAPH_PAYLOAD_FIELDS)\n\nasync def _read_run_extracting_fields(self, run_id, from_position, fields):\n    return []\n"""
    result = StrictPayloadCutoverCodemod(migration).transform_source(source, "store.py")
    assert "LIGHT_GRAPH_PAYLOAD_FIELDS" not in result.source
    assert "GRAPH_PROJECTION_PAYLOAD_FIELDS" not in result.source
    assert "_read_run_extracting_fields" not in result.source
    assert "return await self.read_run(run_id, from_position)" in result.source


def test_records_migration_nests_output_record_payload_once() -> None:
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    source = """\
def emit(make_event, payload):
    first = make_event("output_record_accepted", payload)
    second = make_event("output_record_accepted", {"record": payload})
    return first, second
"""
    result = StrictPayloadCutoverCodemod(migration).transform_source(source, "commands.py")
    assert 'make_event("output_record_accepted", {"record": payload})' in result.source
    assert result.source.count('"record": payload') == 2
    second = StrictPayloadCutoverCodemod(migration).transform_source(result.source, "commands.py")
    assert second.source == result.source
    assert second.changes == 0


def test_records_migration_routes_raw_output_acceptance_through_existing_spec() -> None:
    source = """\
def emit(make_event, payload):
    return make_event("output_record_accepted", {"record": payload})
"""

    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["records"]).transform_source(
        source, "src/orchestrator/graph/_commands.py"
    )

    assert (
        'make_strict_event(make_event, OUTPUT_RECORD_ACCEPTED, {"record": payload})'
        in result.source
    )


def test_records_fixture_codemod_adds_explicit_verification_outcome() -> None:
    source = """\
event = _event("output_record_accepted", {"record": {"record_id": "verification-1", "record_kind": "verification", "record_type": "verification_report", "producer_node_id": "verifier-1", "port": "verification_report", "schema": "VerificationReport", "candidate_id": "candidate-1", "value": {"grades": []}}})
"""

    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["records"]).transform_source(
        source, "tests/integration/test_graph_event_store.py"
    )

    assert '"outcome": "passed"' in result.source
    assert '"value": {"grades": [], "outcome": "passed"}' in result.source


def test_records_migration_transforms_yaml_fixture_paths(tmp_path: Path) -> None:
    fixture = tmp_path / "tests/fixtures/graph/invariants.yaml"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("given_events:\n  - output_record_accepted: {record_id: record-1}\n")

    result = run_migration(DOMAIN_MIGRATIONS["records"], tmp_path, "dry-run")

    assert "record: {record_id: record-1}" in result.output


def test_task3_fixture_migration_completes_planner_session_generation_once() -> None:
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    source = """\
event = _event(
    "session_state_changed",
    {
        "session_id": "session-1",
        "state": "attached",
        "node_id": "planner-1",
        "carryover_record_id": "carryover-1",
    },
    4,
)
"""

    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_planner_packet.py"
    )

    assert '"lease_generation": 3' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_planner_packet.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_nests_strict_record_reads_once() -> None:
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    source = """\
passed = any(
    event.event_type == "output_record_accepted"
    and event.payload.get("record_type") == "check_result"
    and event.payload.get("value", {}).get("status") == "passed"
    for event in events
)
"""

    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/integration/test_graph_dynamic_e2e.py"
    )

    assert 'event.payload["record"].get("record_type")' in result.source
    assert 'event.payload["record"].get("value", {})' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/integration/test_graph_dynamic_e2e.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_records_migration_preserves_unconverted_evaluate_command_routing() -> None:
    source = """\
from orchestrator.graph.commands.records import handle_evaluate_final_gate, handle_evaluate_join

_UNCONVERTED_W5_BRIDGE = {
    "evaluate_join": handle_evaluate_join,
    "evaluate_final_gate": handle_evaluate_final_gate,
}
COMMAND_SPECIFICATIONS = (RECORD_HEARTBEAT,)
"""
    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["records"]).transform_source(
        source, "src/orchestrator/graph/commands/__init__.py"
    )

    assert result.source == source
    assert result.changes == 0
    assert not result.diagnostics


def test_records_nesting_does_not_change_topology_codemod_output() -> None:
    source = 'make_event("node_created", payload)\n'
    topology = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["topology"]).transform_source(
        source, "src/orchestrator/graph/_commands.py"
    )
    records = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["records"]).transform_source(
        source, "src/orchestrator/graph/_commands.py"
    )
    assert records.source == source
    assert topology.source == source


def test_records_migration_nests_event_envelope_keyword_payload_once() -> None:
    source = (
        'EventEnvelope(event_type="output_record_accepted", payload=payload, '
        'event_id="e", run_id="r")\n'
    )
    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["records"]).transform_source(
        source, "tests/unit/test_fixture.py"
    )
    assert 'payload={"record": payload}' in result.source
    second = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["records"]).transform_source(
        result.source, "tests/unit/test_fixture.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_records_migration_rewrites_output_record_assertions_once() -> None:
    source = """\
assert output[1].payload["record_type"] == "failure_record"
assert output[1].payload["value"]["retryable"] is False
assert output[1].payload["provenance"] == {"source": "test"}
assert decision_events[0].payload["value"]["status"] == "passed"
accepted_record = output[1].payload
assert accepted_record["record_id"] == "record-1"
assert output[2].payload["candidate_id"] == "candidate-1"
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_commands.py"
    )

    assert 'output[1].payload["record"]["record_type"]' in result.source
    assert 'output[1].payload["record"]["value"]["retryable"]' in result.source
    assert 'output[1].payload["record"]["provenance"]' in result.source
    assert 'decision_events[0].payload["record"]["value"]["status"]' in result.source
    assert 'accepted_record = output[1].payload["record"]' in result.source
    assert 'output[2].payload["candidate_id"]' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_commands.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_rewrites_selected_output_record_once() -> None:
    source = """\
accepted_record = next(
    event.payload for event in output if event.event_type == "output_record_accepted"
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_commands.py"
    )

    assert 'event.payload["record"] for event in output' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_commands.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_completes_input_bound_once() -> None:
    source = """\
event = _event(
    "input_bound",
    {
        "to_node_id": "join-1",
        "to_port": "source_record_1",
    },
    4,
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_commands.py"
    )

    assert '"edge_id": "edge-join-1-source_record_1"' in result.source
    assert '"bound_at_position": 0' in result.source
    assert '"record_ids": []' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_commands.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_completes_planner_packet_input_bound_once() -> None:
    source = """\
event = _event(
    "input_bound",
    {
        "to_node_id": "verifier-1",
        "to_port": "candidate_under_test",
        "record_ids": ["candidate-1"],
    },
    4,
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_planner_packet.py"
    )

    assert '"edge_id": "edge-verifier-1-candidate_under_test"' in result.source
    assert '"bound_at_position": 0' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_planner_packet.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_completes_strict_record_variants_once() -> None:
    source = """\
snapshot = _event(
    "output_record_accepted",
    {"record": {
        "record_id": "routine-snapshot-record",
        "record_kind": "routine_snapshot",
        "record_type": "routine_snapshot",
        "producer_node_id": "routine-snapshot",
        "port": "snapshot",
        "schema": "RoutineSnapshot",
        "value": {"routine_id": "routine-1"},
    }},
)
verification = _event(
    "output_record_accepted",
    {"record": {
        "record_id": "verification-1",
        "record_kind": "verification",
        "producer_node_id": "verifier-1",
        "port": "verification_report",
        "candidate_id": "candidate-1",
        "verdict": "passed",
    }},
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_commands.py"
    )

    assert '"record_kind": "graph_record"' in result.source
    assert '"name": "Test Routine"' in result.source
    assert '"content_hash": "test-content-hash"' in result.source
    assert '"step_count": 1' in result.source
    assert '"task_count": 1' in result.source
    assert '"record_type": "verification_report"' in result.source
    assert '"schema": "VerificationReport"' in result.source
    assert '"value": {"outcome": "passed", "grades": []}' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_commands.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_rewrites_routine_snapshot_node_once() -> None:
    source = """\
event = _event(
    "node_created",
    {
        "node_id": "routine-snapshot",
        "kind": "artifact",
        "state": "completed",
        "snapshot": {
            "dynamic_feature": {"hidden_oracle_command": "uv run pytest tests/oracle -q"}
        },
    },
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_planner.py"
    )

    assert '"output_record_accepted"' in result.source
    assert '"record_type": "routine_snapshot"' in result.source
    assert '"producer_node_id": "routine-snapshot"' in result.source
    assert '"dynamic_feature": {"hidden_oracle_command"' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_planner.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_rewrites_planner_packet_routine_snapshot_once() -> None:
    source = """\
event = _event(
    "node_created",
    {
        "node_id": "routine-snapshot",
        "kind": "artifact",
        "state": "completed",
        "snapshot": {"dynamic_feature": {"feature_spec_path": "docs/spec.md"}},
    },
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_planner_packet.py"
    )

    assert '"output_record_accepted"' in result.source
    assert '"record_type": "routine_snapshot"' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_planner_packet.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_completes_typed_candidate_identity_once() -> None:
    source = """\
event = _event(
    "output_record_accepted",
    {"record": {
        "record_id": "candidate-1",
        "record_kind": "output",
        "record_type": "candidate",
        "producer_node_id": "worker-1",
        "port": "candidate",
        "value": {"summary": "done"},
    }},
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/integration/test_graph_event_store.py"
    )

    assert '"candidate_id": "candidate-1"' in result.source
    assert '"schema": "ImplementationCandidate"' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/integration/test_graph_event_store.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_completes_four_argument_candidate_once() -> None:
    source = """\
event = _event(
    "evt-candidate",
    run_id,
    "output_record_accepted",
    {
        "record_id": "candidate-1",
        "record_kind": "output",
        "producer_node_id": "worker-1",
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "value": {"summary": "done"},
    },
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/integration/test_graph_event_store.py"
    )

    assert '"record": {' in result.source
    assert '"record_type": "candidate"' in result.source
    assert '"candidate_id": "candidate-1"' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/integration/test_graph_event_store.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_completes_read_model_output_records_once() -> None:
    source = """\
plain_output = _event(
    "evt-output",
    run_id,
    "output_record_accepted",
    {
        "record_id": "record-1",
        "record_kind": "output",
        "producer_node_id": "worker-1",
        "port": "result",
        "value": {"large": "x"},
    },
)
candidate = _event(
    "evt-candidate",
    run_id,
    "output_record_accepted",
    {
        "record_id": "candidate-1",
        "record_kind": "output",
        "producer_node_id": "worker-1",
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "value": {"body": "x", "grades": {"req-1": "pass"}},
    },
)
sparse_candidate = _event(
    "evt-sparse",
    run_id,
    "output_record_accepted",
    {
        "task_region_id": "task-1",
        "candidate_id": "candidate-2",
        "attempt_number": 1,
        "record_id": "candidate-2",
        "record_kind": "output",
        "record_type": "candidate",
        "producer_node_id": "worker-2",
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "supersedes_task_region_id": "task-0",
        "value": {"summary": "existing candidate"},
    },
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/integration/test_graph_read_models.py"
    )

    assert '"schema": "OutputRecord"' in result.source
    assert result.source.count('"record_type": "candidate"') == 2
    assert result.source.count('"candidate_id": "candidate-1"') == 1
    assert result.source.count('"summary": "test candidate"') == 1
    assert '"summary": "existing candidate"' in result.source
    assert '"supersedes_task_region_ids": ["task-0"]' in result.source
    assert '"supersedes_task_region_id":' not in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/integration/test_graph_read_models.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_completes_four_argument_check_result_once() -> None:
    source = """\
event = _event(
    "evt-check",
    run_id,
    "output_record_accepted",
    {
        "record_id": "check-1",
        "record_kind": "output",
        "producer_node_id": "check-1",
        "port": "check_result",
        "schema": "CheckResult",
        "value": {"status": "passed", "classification": "passed"},
    },
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/integration/test_graph_event_store.py"
    )

    assert '"record": {' in result.source
    assert '"task_region_id": "task-test"' in result.source
    assert '"command_text": "test"' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/integration/test_graph_event_store.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_repairs_authority_request_record_type_once() -> None:
    source = """\
event = _event(
    "evt-authority",
    run_id,
    "output_record_accepted",
    {"record": {
        "record_id": "authority-1",
        "record_kind": "graph_record",
        "record_type": "authority_request",
        "producer_node_id": "authority-1",
        "port": "authority_request_record",
        "schema": "AuthorityRequest",
        "value": {"requested_authority": ["repo:write"], "reason": "needed"},
    }},
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/integration/test_graph_event_store.py"
    )

    assert '"record_type": "authority_request_record"' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/integration/test_graph_event_store.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_repairs_recovery_plan_record_kind_once() -> None:
    source = """\
event = _event(
    "evt-recovery",
    run_id,
    "output_record_accepted",
    {"record": {
        "record_id": "recovery-1",
        "record_kind": "graph_record",
        "record_type": "recovery_plan",
        "producer_node_id": "recovery-1",
        "port": "recovery_plan",
        "schema": "RecoveryPlan",
        "value": {"action": "retry", "responsible_actor": "controller", "graph_changes": []},
    }},
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/integration/test_graph_event_store.py"
    )

    assert '"record_kind": "output"' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/integration/test_graph_event_store.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_rewrites_event_store_record_reads_once() -> None:
    source = """\
candidate = stored[0].payload
file_state = stored[1].payload
verification = stored[2].payload
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/integration/test_graph_event_store.py"
    )

    assert 'candidate = stored[0].payload["record"]' in result.source
    assert "file_state = stored[1].payload" in result.source
    assert 'verification = stored[2].payload["record"]' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/integration/test_graph_event_store.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_completes_event_store_check_result_expectation_once() -> None:
    source = """\
assert check_result["payload"] == {
    "status": "passed",
    "classification": "passed",
    "command_id": "unit-check",
}
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/integration/test_graph_event_store.py"
    )

    assert '"command_text": "test"' in result.source
    assert '"timeout_seconds": 60' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/integration/test_graph_event_store.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_rewrites_output_record_get_once() -> None:
    source = """\
assert any(
    event.event_type == "output_record_accepted"
    and event.payload.get("record_type") == "check_result"
    for event in events
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/integration/test_graph_default_carrier.py"
    )

    assert 'event.payload["record"].get("record_type")' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/integration/test_graph_default_carrier.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_records_migration_rewrites_whole_output_record_comparison_once() -> None:
    source = """\
assert output[1].payload == {
    "record_id": "record-1",
    "record_kind": "output",
    "record_type": "decision_record",
    "producer_node_id": "gate-1",
    "port": "decision_record",
    "schema": "DecisionRecord",
    "value": {"decision": "approved"},
}
assert output[2].payload == {"edge_id": "edge-1", "record_ids": ["record-1"]}
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_commands.py"
    )

    assert 'assert output[1].payload["record"] == {' in result.source
    assert 'assert output[2].payload == {"edge_id"' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_commands.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_records_migration_completes_sparse_candidate_fixture_once() -> None:
    source = """\
event = _event(
    "output_record_accepted",
    {"record": {"task_region_id": "task-1", "candidate_id": "cand-1", "attempt_number": 1}},
)
"""
    migration = DOMAIN_MIGRATIONS["records"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_projections.py"
    )

    assert '"record_id": "cand-1"' in result.source
    assert '"record_kind": "output"' in result.source
    assert '"record_type": "candidate"' in result.source
    assert '"producer_node_id": "worker-test"' in result.source
    assert '"port": "candidate"' in result.source
    assert '"schema": "ImplementationCandidate"' in result.source
    assert '"value": {"summary": "test candidate"}' in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_projections.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_records_migration_completes_verification_fixture_with_explicit_outcome() -> None:
    source = """\
event = _event(
    "output_record_accepted",
    {"record": {
        "record_id": "verification-1",
        "record_kind": "verification",
        "producer_node_id": "verifier-1",
        "port": "verification_report",
        "candidate_id": "cand-1",
        "verdict": "passed",
    }},
)
"""
    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["records"]).transform_source(
        source, "tests/unit/test_graph_commands.py"
    )

    assert '"record_type": "verification_report"' in result.source
    assert '"schema": "VerificationReport"' in result.source
    assert result.source.count('"outcome": "passed"') == 2
    assert result.changes == 1


def test_records_migration_completes_candidate_value_summary_once() -> None:
    source = """\
event = _event(
    "output_record_accepted",
    {"record": {
        "record_type": "candidate",
        "candidate_id": "cand-1",
        "value": {"file_state_record_ids": ["file-1"]},
    }},
)
"""
    migration = DOMAIN_MIGRATIONS["records"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_projections.py"
    )

    assert (
        '"value": {"summary": "test candidate", "file_state_record_ids": ["file-1"]}'
        in result.source
    )
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_projections.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_records_migration_completes_sparse_check_result_fixture_once() -> None:
    source = """\
event = _event(
    "output_record_accepted",
    {"record": {
        "record_id": "check-1",
        "record_kind": "output",
        "record_type": "check_result",
        "producer_node_id": "check-1",
        "port": "check_result",
        "task_region_id": "task-1",
        "value": {"status": "failed", "stderr": "boom"},
    }},
)
"""
    migration = DOMAIN_MIGRATIONS["records"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_projections.py"
    )

    assert '"schema": "CheckResult"' in result.source
    assert '"candidate_id": "candidate-test"' not in result.source
    assert '"attempt_number": 1' in result.source
    assert '"classification": "failed"' in result.source
    assert '"stderr": "boom"' in result.source
    assert '"timeout_seconds": 60' in result.source
    assert result.source.count('"status": "failed"') == 1
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_projections.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_task3_fixture_migration_completes_candidate_and_failure_records_once() -> None:
    source = """\
candidate = _event(
    "output_record_accepted",
    {"record": {
        "record_id": "cand-1",
        "record_kind": "output",
        "record_type": "candidate",
        "producer_node_id": "worker-1",
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "candidate_id": "cand-1",
    }},
)
failure = _event(
    "output_record_accepted",
    {"record": {
        "record_id": "failure-1",
        "record_kind": "failure_record",
        "record_type": "failure_record",
        "producer_node_id": "check-1",
        "port": "failure_record",
        "schema": "FailureRecord",
        "task_region_id": "region-1",
        "value": {
            "failed_node_id": "check-1",
            "phase": "runtime",
            "error_class": "runtime_error",
            "retryable": False,
        },
    }},
)
"""
    migration = DOMAIN_MIGRATIONS["task3_fixtures"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        source, "tests/unit/test_graph_commands.py"
    )

    assert '"value": {"summary": "test candidate"}' in result.source
    assert '"record_kind": "graph_record"' in result.source
    assert '"task_region_id"' not in result.source
    second = StrictPayloadCutoverCodemod(migration).transform_source(
        result.source, "tests/unit/test_graph_commands.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_complete_reads_assert_clean_rejects_leftover_partial_consumer() -> None:
    migration = DOMAIN_MIGRATIONS["complete_reads"]
    result = StrictPayloadCutoverCodemod(migration).transform_source(
        'async def unrelated(event):\n    return event.payload["node_id"]\n',
        "src/orchestrator/graph_runtime/store.py",
    )
    assert any(item.code == "W5ALLOWLIST_REFERENCE" for item in result.diagnostics) is False
    leftover = StrictPayloadCutoverCodemod(migration).transform_source(
        'LIGHT_GRAPH_PAYLOAD_FIELDS = ("node_id",)\n\n'
        'def unrelated(event):\n    return event.payload if "node_id" in LIGHT_GRAPH_PAYLOAD_FIELDS else {}\n',
        "src/orchestrator/graph_runtime/store.py",
    )
    assert any(item.code == "W5ALLOWLIST_REFERENCE" for item in leftover.diagnostics)


def test_catalog_injection_scope_includes_presenters_and_cli() -> None:
    paths = set(DOMAIN_MIGRATIONS["catalog_injection"].paths)
    assert "src/orchestrator/api/presenters/evidence_digest.py" in paths
    assert "src/orchestrator/cli/runs.py" in paths


def test_catalog_injection_run_scans_unlisted_workflow_production_file(tmp_path: Path) -> None:
    workflow = tmp_path / "src" / "orchestrator" / "workflow"
    workflow.mkdir(parents=True)
    source = workflow / "sample.py"
    source.write_text(
        "from orchestrator.graph import build_graph_catalog\n\n"
        "def compose():\n"
        "    return build_graph_catalog()\n"
    )

    result = run_migration(DOMAIN_MIGRATIONS["catalog_injection"], tmp_path, "dry-run")

    assert "src/orchestrator/workflow/sample.py" in result.output


def test_other_domain_does_not_rewrite_node_detail_helper_call() -> None:
    source = "def use(event):\n    return _node_detail_light_event(event)\n"
    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["topology"]).transform_source(
        source,
        "src/orchestrator/graph/projections.py",
    )
    assert result.source == source


def test_topology_codemod_creates_target_and_repairs_generated_references() -> None:
    migration = DOMAIN_MIGRATIONS["topology"]
    sources = {
        "src/orchestrator/graph/models.py": "class NodeReadyPayload(GraphEventPayloadBase):\n    node_id: str\n",
        "src/orchestrator/graph/commands/__init__.py": (
            '_UNCONVERTED_W5_BRIDGE = {"seed_compiled_events": handle_seed_compiled_events}\n'
            "COMMAND_SPECIFICATIONS = (RECORD_HEARTBEAT,)\n"
        ),
        "src/orchestrator/graph/commands/schedule.py": (
            "def handle_seed_compiled_events(payload: dict[str, object]):\n    return payload\n"
        ),
    }

    result = StrictPayloadCutoverCodemod(migration).transform_files(sources)

    assert "class NodeReadyPayload" in result.sources["src/orchestrator/graph/events/topology.py"]
    assert (
        "from orchestrator.graph.events.topology import SEED_COMPILED_EVENTS"
        in result.sources["src/orchestrator/graph/commands/__init__.py"]
    )
    assert (
        "SeedCompiledEventsCommand" in result.sources["src/orchestrator/graph/commands/schedule.py"]
    )
    second = StrictPayloadCutoverCodemod(migration).transform_files(result.sources)
    assert second.sources == result.sources
    assert second.changes == 0


def test_lifecycle_bridge_entries_become_composed_specifications() -> None:
    migration = DomainMigration(
        domain="lifecycle",
        paths=("commands.py",),
        command_routes=(
            CommandRoute("start", "handle_start", "START", "EmptyLifecycleCommand"),
            CommandRoute(
                "submit_callback",
                "handle_submit_callback",
                "SUBMIT_CALLBACK",
                "SubmitCallbackCommand",
            ),
        ),
    )
    source = """\
_UNCONVERTED_W5_BRIDGE: dict[str, object] = {
    "start": handle_lifecycle_command,
    "submit_callback": handle_submit_callback,
    "submit_patch": handle_submit_patch,
}

COMMAND_SPECIFICATIONS = (RECORD_HEARTBEAT,)
"""

    transformed = apply_codemod(source, migration)

    assert '"start"' not in transformed
    assert '"submit_callback"' not in transformed
    assert '"submit_patch": handle_submit_patch' in transformed
    assert "COMMAND_SPECIFICATIONS = (RECORD_HEARTBEAT, START, SUBMIT_CALLBACK,)" in transformed


def test_multiple_relocations_deduplicate_shared_target_imports() -> None:
    migration = DomainMigration(
        domain="lifecycle",
        paths=("models.py", "events.py"),
        relocations=(
            SymbolRelocation("FirstPayload", "models.py", "events.py", "models"),
            SymbolRelocation("SecondPayload", "models.py", "events.py", "models"),
        ),
    )
    sources = {
        "models.py": """\
from pydantic import model_validator

class SharedBase: pass

class FirstPayload(SharedBase):
    @model_validator(mode=\"before\")
    @classmethod
    def validate_first(cls, value): return value

class SecondPayload(SharedBase):
    @model_validator(mode=\"before\")
    @classmethod
    def validate_second(cls, value): return value
""",
        "events.py": "",
    }

    result = StrictPayloadCutoverCodemod(migration).transform_files(sources)

    assert result.sources["events.py"].count("from pydantic import model_validator") == 1
    assert result.sources["events.py"].count("from models import SharedBase") == 1


def test_direct_event_envelope_becomes_named_specification_creation() -> None:
    migration = DomainMigration(
        domain="lifecycle",
        paths=("controller.py",),
        event_routes=(
            EventRoute(
                "agent_dispatch_requested",
                "AgentDispatchRequestedPayload",
                "AGENT_DISPATCH_REQUESTED",
            ),
        ),
    )
    source = """EventEnvelope(event_id="e", run_id="r", position=-1, event_type="agent_dispatch_requested", schema_version=1, actor=actor, timestamp=now, payload=payload)\n"""

    transformed = apply_codemod(source, migration)

    assert "AGENT_DISPATCH_REQUESTED.create(" in transformed
    assert "EventMetadata(" in transformed
    assert "AgentDispatchRequestedPayload.model_validate(payload)" in transformed


def test_converted_event_registry_entries_are_removed() -> None:
    migration = DomainMigration(
        domain="lifecycle",
        paths=("graph.py",),
        event_routes=(EventRoute("agent_died", "AgentDiedPayload", "AGENT_DIED"),),
    )
    source = '_LIFECYCLE_EVENT_PAYLOAD_MODELS = {"agent_died": AgentDiedPayload, "dead_input_detected": DeadInputDetectedPayload}\n'
    transformed = apply_codemod(source, migration)
    assert '"agent_died"' not in transformed
    assert '"dead_input_detected"' in transformed


LIFECYCLE_MIGRATION = DomainMigration(
    domain="lifecycle",
    paths=("graph.py",),
    event_routes=(
        EventRoute(
            event_name="heartbeat_recorded",
            payload_class="HeartbeatRecordedPayload",
            specification="HEARTBEAT_RECORDED",
        ),
    ),
    command_routes=(
        CommandRoute(
            command_name="record_heartbeat",
            handler="handle_record_heartbeat",
            specification="RECORD_HEARTBEAT",
            payload_class="RecordHeartbeatCommand",
        ),
    ),
    import_routes=(
        ImportRoute(
            old_module="orchestrator.graph.models",
            new_module="orchestrator.graph.events.lifecycle",
            symbols=("HeartbeatRecordedPayload",),
        ),
    ),
    catalog_injections=(
        CatalogInjection(
            callable_name="GraphController",
            qualified_names=("orchestrator.graph_runtime.GraphController",),
        ),
    ),
    event_factory_qualified_names=("orchestrator.graph._commands.make_event",),
    report_dynamic_emissions=True,
    allowlist_names=("LIGHT_GRAPH_PAYLOAD_FIELDS",),
)


BEFORE_LIFECYCLE_SOURCE = """\
from typing import Any

from orchestrator.graph._commands import make_event
from orchestrator.graph.models import HeartbeatRecordedPayload
from orchestrator.graph_runtime import GraphController

__all__ = ["HeartbeatRecordedPayload", "keep"]

# This projection list is temporary.
LIGHT_GRAPH_PAYLOAD_FIELDS = ("node_id", "lease_id")


def handle_record_heartbeat(payload: dict[str, Any]) -> list[object]:
    # Preserve this producer explanation.
    event = make_event(
        "heartbeat_recorded",
        HeartbeatRecordedPayload.model_validate(payload).model_dump(mode="json"),
    )
    controller = GraphController(store=store)
    return [event, controller]


COMMAND_HANDLERS: dict[str, object] = {
    "record_heartbeat": handle_record_heartbeat,
}
"""


AFTER_LIFECYCLE_SOURCE = """\
from typing import Any

from orchestrator.graph._commands import make_event
from orchestrator.graph.events.lifecycle import HeartbeatRecordedPayload
from orchestrator.graph_runtime import GraphController

__all__ = ["HeartbeatRecordedPayload", "keep"]


def handle_record_heartbeat(payload: RecordHeartbeatCommand) -> list[object]:
    # Preserve this producer explanation.
    event = HEARTBEAT_RECORDED.create(
        HeartbeatRecordedPayload.model_validate(payload),
    )
    controller = GraphController(store=store, catalog=catalog)
    return [event, controller]


COMMAND_SPECIFICATIONS = (RECORD_HEARTBEAT,)
"""


def apply_codemod(source: str, migration: DomainMigration) -> str:
    return StrictPayloadCutoverCodemod(migration).transform_source(source).source


def test_domain_codemod_preserves_comments_and_is_idempotent() -> None:
    once = apply_codemod(BEFORE_LIFECYCLE_SOURCE, LIFECYCLE_MIGRATION)

    assert once == AFTER_LIFECYCLE_SOURCE
    assert apply_codemod(once, LIFECYCLE_MIGRATION) == once


def test_relocation_moves_class_and_repairs_target_export() -> None:
    migration = DomainMigration(
        domain="records",
        paths=("models.py", "events/records.py"),
        relocations=(
            SymbolRelocation(
                symbol="OutputRecordPayload",
                source_path="models.py",
                target_path="events/records.py",
            ),
        ),
    )
    sources = {
        "models.py": """\
from pydantic import BaseModel

__all__ = ["OutputRecordPayload", "KeepMe"]

# Payload explanation stays with the class.
class OutputRecordPayload(BaseModel):
    record_id: str


class KeepMe(BaseModel):
    value: str
""",
        "events/records.py": '__all__ = ["EXISTING"]\n',
    }

    result = StrictPayloadCutoverCodemod(migration).transform_files(sources)

    assert "class OutputRecordPayload" not in result.sources["models.py"]
    assert "class KeepMe" in result.sources["models.py"]
    assert '"OutputRecordPayload"' not in result.sources["models.py"]
    assert "# Payload explanation stays with the class." in result.sources["events/records.py"]
    assert '"OutputRecordPayload"' in result.sources["events/records.py"]
    assert "from pydantic import BaseModel" in result.sources["events/records.py"]
    namespace: dict[str, object] = {}
    exec(result.sources["events/records.py"], namespace)
    assert "OutputRecordPayload" in namespace
    second = StrictPayloadCutoverCodemod(migration).transform_files(result.sources)
    assert second.sources == result.sources
    assert second.changes == 0
    assert not second.diagnostics


def test_ambiguous_dynamic_emission_is_reported_without_editing() -> None:
    source = "from orchestrator.graph._commands import make_event\nevent = make_event(event_name, payload)\n"

    result = StrictPayloadCutoverCodemod(LIFECYCLE_MIGRATION).transform_source(source)

    assert result.source == source
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "W5AMBIGUOUS_EVENT"
    assert result.diagnostics[0].line == 2


def test_cli_dry_run_apply_assert_clean_and_idempotency(tmp_path: Path) -> None:
    source = tmp_path / "graph.py"
    source.write_text(BEFORE_LIFECYCLE_SOURCE)

    dry_run = run_migration(LIFECYCLE_MIGRATION, tmp_path, mode="dry-run")
    assert dry_run.exit_code == 0
    assert "--- a/graph.py" in dry_run.output
    assert source.read_text() == BEFORE_LIFECYCLE_SOURCE

    applied = run_migration(LIFECYCLE_MIGRATION, tmp_path, mode="apply")
    assert applied.exit_code == 0
    assert source.read_text() == AFTER_LIFECYCLE_SOURCE

    clean = run_migration(LIFECYCLE_MIGRATION, tmp_path, mode="assert-clean")
    assert clean.exit_code == 0
    assert clean.output == ""

    second_apply = run_migration(LIFECYCLE_MIGRATION, tmp_path, mode="apply")
    assert second_apply.exit_code == 0
    assert second_apply.output == ""


def test_assert_clean_lists_every_remaining_ambiguous_site(tmp_path: Path) -> None:
    source = tmp_path / "graph.py"
    source.write_text(
        "from orchestrator.graph._commands import make_event\n"
        "first = make_event(first_name, {})\n"
        "second = make_event(second_name, {})\n"
    )

    result = run_migration(LIFECYCLE_MIGRATION, tmp_path, mode="assert-clean")

    assert result.exit_code == 1
    assert "graph.py:2" in result.output
    assert "graph.py:3" in result.output


def test_catalog_cutover_rewrites_mechanically_eligible_current_dispatch_once() -> None:
    source = """\
planned = apply_command(
    projection, events, command_type, payload, clock, id_gen,
    catalog=catalog, context=context,
)
"""

    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["catalog_cutover"]).transform_source(
        source, "src/orchestrator/graph_runtime/controller.py"
    )

    assert "catalog, projection, events, command_type, payload, context" in result.source
    assert result.diagnostics == ()
    second = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["catalog_cutover"]).transform_source(
        result.source, "src/orchestrator/graph_runtime/controller.py"
    )
    assert second.source == result.source
    assert second.changes == 0


def test_catalog_cutover_rewrites_scenario_style_dispatch_in_any_production_module() -> None:
    source = "planned = apply_command(projection, events, command_type, payload, clock, id_gen, catalog=catalog, context=context)\n"

    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["catalog_cutover"]).transform_source(
        source, "src/orchestrator/graph_runtime/arbitrary_production_module.py"
    )

    assert (
        "apply_command(catalog, projection, events, command_type, payload, context)"
        in result.source
    )


def test_catalog_cutover_assert_clean_reports_current_fallback_and_central_enumeration(
    tmp_path: Path,
) -> None:
    commands = tmp_path / "src/orchestrator/graph/commands/__init__.py"
    commands.parent.mkdir(parents=True)
    commands.write_text("COMMAND_SPECIFICATIONS = (START, PAUSE)\n")
    controller = tmp_path / "src/orchestrator/graph_runtime/controller.py"
    controller.parent.mkdir(parents=True)
    controller.write_text(
        """\
if command_type in catalog.command_specs:
    apply_command(catalog, projection, events, command_type, payload, context)
else:
    apply_command(projection, events, command_type, payload, clock, id_gen)
"""
    )
    for relative_path in (
        "src/orchestrator/graph/catalog.py",
        "src/orchestrator/graph/events/__init__.py",
        "src/orchestrator/graph/projections.py",
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n")

    result = run_migration(DOMAIN_MIGRATIONS["catalog_cutover"], tmp_path, "assert-clean")

    assert result.exit_code == 1
    assert "W5CATALOG_FALLBACK_DISPATCH" in result.output
    assert "W5CENTRAL_COMMAND_SPEC_ENUMERATION" in result.output


def test_catalog_cutover_ignores_explicit_legacy_replay_boundary(tmp_path: Path) -> None:
    projection = tmp_path / "src/orchestrator/graph/projections.py"
    projection.parent.mkdir(parents=True)
    projection.write_text(
        """\
def reduce_legacy_event(command_type, payload):
    if command_type in catalog.command_specs:
        return apply_command(projection, events, command_type, payload, clock, id_gen)
    return None
"""
    )
    for relative_path in (
        "src/orchestrator/graph/catalog.py",
        "src/orchestrator/graph/events/__init__.py",
        "src/orchestrator/graph/commands/__init__.py",
        "src/orchestrator/graph_runtime/controller.py",
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n")

    result = run_migration(DOMAIN_MIGRATIONS["catalog_cutover"], tmp_path, "assert-clean")

    assert result.exit_code == 0


def test_catalog_cutover_apply_is_idempotent(tmp_path: Path) -> None:
    controller = tmp_path / "src/orchestrator/graph_runtime/controller.py"
    controller.parent.mkdir(parents=True)
    controller.write_text(
        """\
planned = apply_command(
    projection, events, command_type, payload, clock, id_gen,
    catalog=catalog, context=context,
)
"""
    )
    for relative_path in (
        "src/orchestrator/graph/catalog.py",
        "src/orchestrator/graph/commands/__init__.py",
        "src/orchestrator/graph/events/__init__.py",
        "src/orchestrator/graph/projections.py",
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n")

    first = run_migration(DOMAIN_MIGRATIONS["catalog_cutover"], tmp_path, "apply")
    second = run_migration(DOMAIN_MIGRATIONS["catalog_cutover"], tmp_path, "apply")

    assert first.exit_code == 0
    assert "catalog, projection, events, command_type, payload, context" in controller.read_text()
    assert second.exit_code == 0
    assert second.output == ""


def test_mixed_import_and_registry_entries_are_split_mechanically() -> None:
    source = """\
from orchestrator.graph.models import HeartbeatRecordedPayload, KeepPayload

COMMAND_HANDLERS = {
    "record_heartbeat": handle_record_heartbeat,
    "keep": handle_keep,
}
"""

    result = StrictPayloadCutoverCodemod(LIFECYCLE_MIGRATION).transform_source(source)

    assert "from orchestrator.graph.models import KeepPayload" in result.source
    assert (
        "from orchestrator.graph.events.lifecycle import HeartbeatRecordedPayload" in result.source
    )
    assert '"keep": handle_keep' in result.source
    assert '"record_heartbeat": handle_record_heartbeat' not in result.source
    assert "COMMAND_SPECIFICATIONS = (RECORD_HEARTBEAT,)" in result.source
    assert not result.diagnostics


def test_vertical_slice_routes_generated_specification_imports() -> None:
    sources = {
        "src/orchestrator/graph/_commands.py": """\
\"\"\"Command compatibility bridge.\"\"\"

from orchestrator.graph.models import HeartbeatRecordedPayload

def _apply_record_heartbeat(make_event, payload):
    return make_event("heartbeat_recorded", payload)
""",
        "src/orchestrator/graph/commands/__init__.py": """\
from orchestrator.graph.commands.lifecycle import handle_record_heartbeat

COMMAND_HANDLERS = {"record_heartbeat": handle_record_heartbeat}
""",
    }

    result = StrictPayloadCutoverCodemod(VERTICAL_SLICE_MIGRATION).transform_files(sources)

    assert result.sources["src/orchestrator/graph/_commands.py"].startswith(
        '"""Command compatibility bridge."""'
    )
    assert (
        "from orchestrator.graph.events.lifecycle import HEARTBEAT_RECORDED"
        in result.sources["src/orchestrator/graph/_commands.py"]
    )
    assert (
        "from orchestrator.graph.commands.lifecycle import RECORD_HEARTBEAT"
        in result.sources["src/orchestrator/graph/commands/__init__.py"]
    )
    assert (
        StrictPayloadCutoverCodemod(VERTICAL_SLICE_MIGRATION)
        .transform_files(result.sources)
        .sources
        == result.sources
    )


def test_vertical_slice_does_not_import_specification_without_generated_reference() -> None:
    source = "def keep() -> None:\n    pass\n"

    result = StrictPayloadCutoverCodemod(VERTICAL_SLICE_MIGRATION).transform_files(
        {"src/orchestrator/graph/_commands.py": source}
    )

    assert result.sources["src/orchestrator/graph/_commands.py"] == source


def test_relocation_can_preview_and_create_a_new_target_file(tmp_path: Path) -> None:
    source = tmp_path / "models.py"
    source.write_text("class OutputRecordPayload(BaseModel):\n    record_id: str\n")
    migration = DomainMigration(
        domain="records",
        paths=("models.py", "events/records.py"),
        relocations=(
            SymbolRelocation(
                symbol="OutputRecordPayload",
                source_path="models.py",
                target_path="events/records.py",
            ),
        ),
    )

    preview = run_migration(migration, tmp_path, mode="dry-run")

    assert "+++ b/events/records.py" in preview.output
    assert not (tmp_path / "events/records.py").exists()

    applied = run_migration(migration, tmp_path, mode="apply")
    assert applied.exit_code == 0
    assert "class OutputRecordPayload" in (tmp_path / "events/records.py").read_text()


def test_relocation_moves_declared_transitive_dependency_closure() -> None:
    sources = {
        "commands.py": """\
from package import External

DOMAIN_STATES = {"active"}

def _domain_helper(value):
    return External(value) in DOMAIN_STATES

def handle_domain(value):
    return _domain_helper(value)

def keep(value):
    return value
""",
        "domain.py": '"""Domain commands."""\n',
    }
    migration = DomainMigration(
        domain="domain",
        paths=("commands.py", "domain.py"),
        relocations=(
            SymbolRelocation(
                "handle_domain",
                "commands.py",
                "domain.py",
                dependency_closure=("_domain_helper", "DOMAIN_STATES"),
            ),
        ),
    )

    result = StrictPayloadCutoverCodemod(migration).transform_files(sources)

    assert "handle_domain" not in result.sources["commands.py"]
    assert "_domain_helper" not in result.sources["commands.py"]
    assert "DOMAIN_STATES" not in result.sources["commands.py"]
    assert "def keep" in result.sources["commands.py"]
    assert "from package import External" in result.sources["domain.py"]
    assert "DOMAIN_STATES =" in result.sources["domain.py"]
    assert "def _domain_helper" in result.sources["domain.py"]
    assert "def handle_domain" in result.sources["domain.py"]
    assert not result.diagnostics
    assert (
        StrictPayloadCutoverCodemod(migration).transform_files(result.sources).sources
        == result.sources
    )


def test_relocation_dependency_closure_fails_closed_when_dependency_is_shared() -> None:
    sources = {
        "commands.py": """\
def shared_helper(value):
    return value

def handle_domain(value):
    return shared_helper(value)

def keep(value):
    return shared_helper(value)
""",
        "domain.py": "",
    }
    migration = DomainMigration(
        domain="domain",
        paths=("commands.py", "domain.py"),
        relocations=(
            SymbolRelocation(
                "handle_domain",
                "commands.py",
                "domain.py",
                dependency_closure=("shared_helper",),
            ),
        ),
    )

    result = StrictPayloadCutoverCodemod(migration).transform_files(sources)

    assert any(item.code == "W5SHARED_RELOCATION_DEPENDENCY" for item in result.diagnostics)


def test_relocation_routes_cross_target_dependencies_without_source_import() -> None:
    sources = {
        "commands.py": """\
def shared_effect(value):
    return value

def handle_domain(value):
    return shared_effect(value)
""",
        "domain.py": "",
        "future_effects.py": "",
    }
    migration = DomainMigration(
        domain="domain",
        paths=("commands.py", "domain.py", "future_effects.py"),
        relocations=(
            SymbolRelocation("shared_effect", "commands.py", "future_effects.py"),
            SymbolRelocation("handle_domain", "commands.py", "domain.py"),
        ),
    )

    result = StrictPayloadCutoverCodemod(migration).transform_files(sources)

    assert "from future_effects import shared_effect" in result.sources["domain.py"]
    assert "from commands import" not in result.sources["domain.py"]
    assert not result.diagnostics
    assert (
        StrictPayloadCutoverCodemod(migration).transform_files(result.sources).sources
        == result.sources
    )


def test_symbol_resolution_rewrites_alias_and_ignores_unrelated_local() -> None:
    source = """\
from orchestrator.graph._commands import make_event as graph_make_event

def make_event(name, payload):
    return (name, payload)

local = make_event("heartbeat_recorded", payload)
graph = graph_make_event("heartbeat_recorded", payload)
"""

    result = StrictPayloadCutoverCodemod(LIFECYCLE_MIGRATION).transform_source(source)

    assert 'local = make_event("heartbeat_recorded", payload)' in result.source
    assert "graph = HEARTBEAT_RECORDED.create(payload)" in result.source


def test_qualified_event_factory_and_module_alias_are_rewritten(
    tmp_path: Path,
) -> None:
    migration = DomainMigration(
        domain="qualified",
        paths=("events.py",),
        event_routes=(EventRoute("started", "StartedPayload", "STARTED"),),
        event_factory_qualified_names=("pkg.make_event",),
    )
    source = """\
import pkg
import pkg as alias

first = pkg.make_event("started", payload)
second = alias.make_event("started", payload)
"""

    result = StrictPayloadCutoverCodemod(migration).transform_source(source, "events.py")

    assert "first = STARTED.create(payload)" in result.source
    assert "second = STARTED.create(payload)" in result.source
    assert result.changes == 2
    (tmp_path / "events.py").write_text(source)
    assert run_migration(migration, tmp_path, mode="assert-clean").exit_code == 1


def test_catalog_injection_rewrites_alias_and_ignores_unrelated_local() -> None:
    source = """\
from orchestrator.graph_runtime import GraphController as RuntimeController

def GraphController(**kwargs):
    return kwargs

local = GraphController(store=store)
runtime = RuntimeController(store=store)
"""

    result = StrictPayloadCutoverCodemod(LIFECYCLE_MIGRATION).transform_source(source)

    assert "local = GraphController(store=store)" in result.source
    assert "runtime = RuntimeController(store=store, catalog=catalog)" in result.source


def test_task10_catalog_injection_rewrites_factory_escape_and_missing_store_argument() -> None:
    source = """\
from orchestrator.graph import build_graph_catalog
from orchestrator.graph_runtime import GraphEventStore

def make_store(session, catalog):
    return GraphEventStore(session, build_graph_catalog())
"""

    first = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["catalog_injection"]).transform_source(
        source, "src/orchestrator/api/deps.py"
    )
    second = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["catalog_injection"]).transform_source(
        first.source, "src/orchestrator/api/deps.py"
    )

    assert "GraphEventStore(session, catalog)" in first.source
    assert first.changes == 1
    assert second.source == first.source
    assert second.changes == 0


def test_catalog_injection_removes_retired_future_effects_argument() -> None:
    source = """\
from orchestrator.graph_runtime import GraphController

controller = GraphController(store=store, future_effects=effects)
"""

    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["catalog_injection"]).transform_source(
        source, "src/orchestrator/workflow/service.py"
    )

    assert "future_effects" not in result.source
    assert "GraphController(store=store, catalog=catalog)" in result.source


def test_catalog_injection_never_declares_retired_future_effects_requirement() -> None:
    migration = DOMAIN_MIGRATIONS["catalog_injection"]

    assert all(
        "future_effects" not in route.additional_arguments for route in migration.catalog_injections
    )


@pytest.mark.timeout(120)
def test_catalog_injection_cli_runs_with_command_effects_deletion_migration() -> None:
    root = Path(__file__).parents[2]

    result = subprocess.run(
        (
            sys.executable,
            "scripts/codemods/w5_strict_payload_cutover.py",
            "--domain",
            "catalog_injection",
            "--assert-clean",
        ),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_task10_catalog_injection_adds_catalog_to_qualified_constructor_only() -> None:
    source = """\
from orchestrator.graph_runtime import GraphEventStore as Store

def GraphEventStore(session):
    return session

local = GraphEventStore(session)
runtime = Store(session)
"""

    result = StrictPayloadCutoverCodemod(DOMAIN_MIGRATIONS["catalog_injection"]).transform_source(
        source, "src/orchestrator/api/deps.py"
    )

    assert "local = GraphEventStore(session)" in result.source
    assert "runtime = Store(session, catalog=catalog)" in result.source


def test_catalog_injection_without_qualified_contract_refuses_local_collision() -> None:
    migration = DomainMigration(
        domain="catalog",
        paths=("controller.py",),
        catalog_injections=(CatalogInjection("GraphController"),),
    )
    source = """\
def GraphController(**kwargs):
    return kwargs

controller = GraphController(store=store)
"""

    result = StrictPayloadCutoverCodemod(migration).transform_source(source, "controller.py")

    assert result.source == source
    assert result.changes == 0
    assert result.diagnostics[0].code == "W5UNQUALIFIED_CATALOG_ROUTE"


def test_command_specifications_compose_across_sequential_domain_passes() -> None:
    first = DomainMigration(
        domain="first",
        paths=("commands.py",),
        command_routes=(CommandRoute("first", "handle_first", "FIRST", "FirstCommand"),),
    )
    second = DomainMigration(
        domain="second",
        paths=("commands.py",),
        command_routes=(CommandRoute("second", "handle_second", "SECOND", "SecondCommand"),),
    )
    source = """\
COMMAND_HANDLERS = {
    "first": handle_first,
    "second": handle_second,
}
"""

    after_first = StrictPayloadCutoverCodemod(first).transform_source(source).source
    after_second = StrictPayloadCutoverCodemod(second).transform_source(after_first).source

    assert "COMMAND_SPECIFICATIONS = (FIRST, SECOND,)" in after_second
    assert StrictPayloadCutoverCodemod(second).transform_source(after_second).source == after_second


def test_command_specifications_compose_when_tuple_precedes_handlers() -> None:
    migration = DomainMigration(
        domain="second",
        paths=("commands.py",),
        command_routes=(CommandRoute("second", "handle_second", "SECOND", "SecondCommand"),),
    )
    source = """\
COMMAND_SPECIFICATIONS = (FIRST,)
COMMAND_HANDLERS = {"second": handle_second}
"""

    first = StrictPayloadCutoverCodemod(migration).transform_source(source)
    second = StrictPayloadCutoverCodemod(migration).transform_source(first.source)

    assert first.source.count("COMMAND_SPECIFICATIONS =") == 1
    assert "COMMAND_SPECIFICATIONS = (FIRST, SECOND,)" in first.source
    assert second.source == first.source
    assert second.changes == 0
    assert not second.diagnostics


def test_duplicate_command_specification_assignments_are_diagnostic() -> None:
    source = """\
COMMAND_SPECIFICATIONS = (FIRST,)
COMMAND_SPECIFICATIONS = (SECOND,)
"""

    result = StrictPayloadCutoverCodemod(
        DomainMigration(domain="commands", paths=("commands.py",))
    ).transform_source(source, "commands.py")

    assert result.diagnostics[0].code == "W5DUPLICATE_COMMAND_SPECIFICATIONS"


def test_nested_command_handler_registry_is_not_rewritten() -> None:
    migration = DomainMigration(
        domain="second",
        paths=("commands.py",),
        command_routes=(CommandRoute("second", "handle_second", "SECOND", "SecondCommand"),),
    )
    source = """\
def local_registry():
    COMMAND_HANDLERS = {"second": handle_second}
    return COMMAND_HANDLERS
"""

    result = StrictPayloadCutoverCodemod(migration).transform_source(source, "commands.py")

    assert result.source == source
    assert result.changes == 0


@pytest.mark.parametrize(
    "existing",
    (
        "COMMAND_SPECIFICATIONS = [FIRST]",
        "COMMAND_SPECIFICATIONS = (*BASE,)",
        "COMMAND_SPECIFICATIONS = (specs.FIRST,)",
    ),
)
def test_noncanonical_command_specifications_fail_closed(tmp_path: Path, existing: str) -> None:
    migration = DomainMigration(
        domain="second",
        paths=("commands.py",),
        command_routes=(CommandRoute("second", "handle_second", "SECOND", "SecondCommand"),),
    )
    source = f'{existing}\nCOMMAND_HANDLERS = {{"second": handle_second}}\n'
    path = tmp_path / "commands.py"
    path.write_text(source)

    dry_run = run_migration(migration, tmp_path, mode="dry-run")
    applied = run_migration(migration, tmp_path, mode="apply")
    assert_clean = run_migration(migration, tmp_path, mode="assert-clean")

    assert dry_run.exit_code == applied.exit_code == assert_clean.exit_code == 1
    assert "commands.py:1:0: W5NONCANONICAL_COMMAND_SPECIFICATIONS" in dry_run.output
    assert path.read_text() == source


def test_missing_configured_file_and_relocation_symbol_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "models.py"
    source.write_text("class Present: pass\n")
    migration = DomainMigration(
        domain="missing",
        paths=("models.py", "required.py", "events.py"),
        relocations=(SymbolRelocation("MissingPayload", "models.py", "events.py"),),
    )

    result = run_migration(migration, tmp_path, mode="assert-clean")

    assert result.exit_code == 1
    assert "W5MISSING_FILE configured path does not exist: required.py" in result.output
    assert "W5MISSING_SYMBOL expected relocation symbol MissingPayload" in result.output


def test_allowlist_consumer_is_replaced_before_constant_removal() -> None:
    migration = DomainMigration(
        domain="reads",
        paths=("store.py",),
        allowlist_names=("LIGHT_GRAPH_PAYLOAD_FIELDS",),
        allowlist_consumers=(
            AllowlistConsumer(
                function_name="compact_event",
                replacement_expression="catalog.hydrate(event)",
            ),
        ),
    )
    source = """\
LIGHT_GRAPH_PAYLOAD_FIELDS = ("node_id",)

def compact_event(event, catalog):
    return {key: value for key, value in event.payload.items() if key in LIGHT_GRAPH_PAYLOAD_FIELDS}
"""

    result = StrictPayloadCutoverCodemod(migration).transform_source(source)

    assert "LIGHT_GRAPH_PAYLOAD_FIELDS" not in result.source
    assert "return catalog.hydrate(event)" in result.source
    assert not result.diagnostics


def test_allowlist_with_unknown_consumer_is_retained_and_reported() -> None:
    source = """\
LIGHT_GRAPH_PAYLOAD_FIELDS = ("node_id",)
filtered = {key: value for key, value in payload.items() if key in LIGHT_GRAPH_PAYLOAD_FIELDS}
"""

    result = StrictPayloadCutoverCodemod(
        DomainMigration(
            domain="reads",
            paths=("store.py",),
            allowlist_names=("LIGHT_GRAPH_PAYLOAD_FIELDS",),
        )
    ).transform_source(source, "store.py")

    assert "LIGHT_GRAPH_PAYLOAD_FIELDS =" in result.source
    assert result.diagnostics[0].code == "W5ALLOWLIST_REFERENCE"


def test_allowlist_consumer_does_not_rewrite_same_named_nested_method() -> None:
    migration = DomainMigration(
        domain="reads",
        paths=("store.py",),
        allowlist_names=("LIGHT_GRAPH_PAYLOAD_FIELDS",),
        allowlist_consumers=(
            AllowlistConsumer(
                function_name="compact_event",
                replacement_expression="catalog.hydrate(event)",
            ),
        ),
    )
    source = """\
LIGHT_GRAPH_PAYLOAD_FIELDS = ("node_id",)

class Unrelated:
    def compact_event(self, event):
        return {key: value for key, value in event.payload.items() if key in LIGHT_GRAPH_PAYLOAD_FIELDS}
"""

    result = StrictPayloadCutoverCodemod(migration).transform_source(source, "store.py")

    assert "class Unrelated:" in result.source
    assert "return {key: value" in result.source
    assert "LIGHT_GRAPH_PAYLOAD_FIELDS =" in result.source
    assert result.diagnostics[0].code == "W5ALLOWLIST_REFERENCE"


def test_relocation_does_not_move_same_named_nested_class() -> None:
    migration = DomainMigration(
        domain="records",
        paths=("models.py", "records.py"),
        relocations=(SymbolRelocation("OutputRecordPayload", "models.py", "records.py"),),
    )
    sources = {
        "models.py": """\
class Unrelated:
    class OutputRecordPayload:
        record_id: str
""",
        "records.py": "",
    }

    result = StrictPayloadCutoverCodemod(migration).transform_files(sources)

    assert "class Unrelated:" in result.sources["models.py"]
    assert "class OutputRecordPayload:" in result.sources["models.py"]
    assert "OutputRecordPayload" not in result.sources["records.py"]
    assert result.diagnostics[0].code == "W5MISSING_SYMBOL"


def test_relocation_imports_follow_docstring_and_all_future_imports() -> None:
    migration = DomainMigration(
        domain="records",
        paths=("models.py", "records.py"),
        relocations=(SymbolRelocation("OutputRecordPayload", "models.py", "records.py"),),
    )
    sources = {
        "models.py": """\
from pydantic import BaseModel

class OutputRecordPayload(BaseModel):
    record_id: str
""",
        "records.py": '''\
"""Record payload specifications."""

from __future__ import annotations

__all__ = ["EXISTING"]
''',
    }

    result = StrictPayloadCutoverCodemod(migration).transform_files(sources)
    target = result.sources["records.py"]

    assert target.index('"""Record payload specifications."""') < target.index(
        "from __future__ import annotations"
    )
    assert target.index("from __future__ import annotations") < target.index(
        "from pydantic import BaseModel"
    )
    namespace: dict[str, object] = {}
    exec(compile(target, "records.py", "exec"), namespace)
    assert "OutputRecordPayload" in namespace
