from __future__ import annotations

import json
from pathlib import Path

from scripts.w5_payload_ast_inventory import (
    BASELINE_COMMAND_NAMES,
    BASELINE_EVENT_NAMES,
    scan_graph_payload_architecture,
)


SAMPLE_EVENT_AND_COMMAND_SOURCE = """\
from typing import Any

from pydantic import BaseModel, model_validator


class NodeCreatedPayload(BaseModel):
    node_id: str

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy(cls, value: Any) -> Any:
        return value


def make_event(event_type: str, payload: dict[str, Any]) -> object:
    return EventEnvelope(event_type=event_type, payload=payload)


def produce(event_type: str, payload: dict[str, Any]) -> list[object]:
    return [
        make_event("node_created", payload),
        make_event(event_type, payload),
    ]


def reduce_event(event: object) -> str | None:
    if event.event_type == "node_created":
        return event.payload["node_id"]
    return None


COMMAND_HANDLERS = {
    "start": handle_start,
}
"""


def test_inventory_finds_literal_dynamic_and_registry_sites(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(SAMPLE_EVENT_AND_COMMAND_SOURCE)

    report = scan_graph_payload_architecture([source])

    assert report.literal_event_names == {"node_created"}
    assert any(site.expression == "event_type" for site in report.dynamic_event_sites)
    assert report.command_names == ("start",)
    assert report.raw_payload_reads[0].field == "node_id"
    assert report.payload_models[0].name == "NodeCreatedPayload"
    assert report.payload_models[0].before_validators == ("normalize_legacy",)


def test_inventory_output_is_stable_and_records_dynamic_locations(tmp_path: Path) -> None:
    later = tmp_path / "z_later.py"
    earlier = tmp_path / "a_earlier.py"
    later.write_text('make_event(dynamic_name, {})\nmake_event("z_event", {})\n')
    earlier.write_text('make_event("a_event", {})\n')

    first = scan_graph_payload_architecture([later, earlier])
    second = scan_graph_payload_architecture([earlier, later])

    assert first.to_json() == second.to_json()
    rendered = json.loads(first.to_json())
    assert rendered["literal_event_names"] == ["a_event", "z_event"]
    assert rendered["dynamic_event_sites"] == [
        {
            "classification": "unresolved",
            "column": 0,
            "expression": "dynamic_name",
            "line": 1,
            "path": str(later),
            "resolved_values": [],
        }
    ]


def test_inventory_resolves_factory_parameter_from_literal_callers(tmp_path: Path) -> None:
    source = tmp_path / "factory.py"
    source.write_text(
        """\
def emit(name, payload):
    return make_event(name, payload)

emit("first", {})
emit("second", {})
"""
    )

    report = scan_graph_payload_architecture([source])

    assert report.dynamic_event_sites[0].classification == "resolved_finite"
    assert report.dynamic_event_sites[0].resolved_values == ("first", "second")


def test_repository_baseline_constants_have_expected_counts() -> None:
    assert len(BASELINE_EVENT_NAMES) == 44
    assert len(BASELINE_COMMAND_NAMES) == 23


def test_inventory_locates_allowlist_comprehension_consumers(tmp_path: Path) -> None:
    source = tmp_path / "allowlist.py"
    source.write_text(
        """\
LIGHT_GRAPH_PAYLOAD_FIELDS = ("node_id",)
filtered = {
    key: value
    for key, value in payload.items()
    if key in LIGHT_GRAPH_PAYLOAD_FIELDS
}
"""
    )

    report = scan_graph_payload_architecture([source])

    assert report.allowlists[0].name == "LIGHT_GRAPH_PAYLOAD_FIELDS"
    assert report.partial_payload_consumers[0].line == 4


def test_inventory_resolves_local_branches_and_method_factory_callers(
    tmp_path: Path,
) -> None:
    source = tmp_path / "branches.py"
    source.write_text(
        """\
from orchestrator.graph.models import EventEnvelope

def decide(flag, payload):
    event_type = "passed" if flag else "failed"
    return make_event(event_type, payload)

class Compiler:
    def _event(self, event_type, payload):
        return EventEnvelope(event_type=event_type, payload=payload)

    def emit(self):
        self._event("compiled", {})
"""
    )

    report = scan_graph_payload_architecture([source])

    sites = {site.expression: site for site in report.dynamic_event_sites}
    assert sites["event_type"].classification == "resolved_finite"
    assert report.produced_event_names == {"compiled", "failed", "passed"}


def test_inventory_classifies_stored_event_hydration(tmp_path: Path) -> None:
    source = tmp_path / "store.py"
    source.write_text(
        """\
from orchestrator.graph.models import EventEnvelope

def rows_to_events(rows):
    return [
        EventEnvelope(event_type=str(row["event_type"]), payload=row["payload"])
        for row in rows
    ]
"""
    )

    report = scan_graph_payload_architecture([source])

    assert report.dynamic_event_sites[0].classification == "stored_event_hydration"


def test_inventory_reports_fixture_events_without_counting_them_as_live(
    tmp_path: Path,
) -> None:
    source = tmp_path / "scenario.py"
    source.write_text('make_event("fixture_only", {})\n')

    report = scan_graph_payload_architecture([source])

    assert report.literal_event_names == {"fixture_only"}
    assert report.nonproduction_event_sites[0].name == "fixture_only"
    assert report.produced_event_names == set()


def test_domain_inventory_uses_domain_surface_and_raw_boundary_shape(
    tmp_path: Path,
) -> None:
    source = tmp_path / "commands.py"
    source.write_text(
        """\
def handle_record_heartbeat(payload: dict[str, object]):
    return make_event("heartbeat_recorded", payload)

COMMAND_HANDLERS = {"record_heartbeat": handle_record_heartbeat}
"""
    )

    domain = scan_graph_payload_architecture([source]).for_domain("lifecycle")

    assert domain.event_names == ("heartbeat_recorded",)
    assert domain.command_names == ("record_heartbeat",)
    assert len(domain.raw_producers) == 1
    assert len(domain.raw_handler_boundaries) == 1
    assert not domain.is_clean


def test_inventory_counts_typed_event_and_command_specifications_without_raw_sites(
    tmp_path: Path,
) -> None:
    source = tmp_path / "specifications.py"
    source.write_text(
        """\
HEARTBEAT_RECORDED = EventSpecification(name="heartbeat_recorded", payload_type=Payload)
RECORD_HEARTBEAT = CommandSpecification(name="record_heartbeat", payload_type=Command)
"""
    )

    report = scan_graph_payload_architecture([source])
    domain = report.for_domain("vertical_slice")

    assert report.produced_event_names == {"heartbeat_recorded"}
    assert report.command_names == ("record_heartbeat",)
    assert domain.raw_producers == ()
    assert domain.raw_handler_boundaries == ()


def test_inventory_combines_typed_specs_with_explicit_unconverted_bridge(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mixed.py"
    source.write_text(
        """\
HEARTBEAT_RECORDED = EventSpecification(name="heartbeat_recorded", payload_type=Payload)
RECORD_HEARTBEAT = CommandSpecification(name="record_heartbeat", payload_type=Command)
_UNCONVERTED_W5_BRIDGE = {"start": handle_start}

def legacy(emit_unconverted_event):
    return emit_unconverted_event("lease_renewed", {})
"""
    )

    report = scan_graph_payload_architecture([source])

    assert report.produced_event_names == {"heartbeat_recorded", "lease_renewed"}
    assert report.command_names == ("record_heartbeat", "start")


def test_domain_rejects_converted_names_that_remain_in_unconverted_bridge(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mixed.py"
    source.write_text(
        """\
HEARTBEAT_RECORDED = EventSpecification(name="heartbeat_recorded", payload_type=Payload)
RECORD_HEARTBEAT = CommandSpecification(name="record_heartbeat", payload_type=Command)
_UNCONVERTED_W5_BRIDGE = {"record_heartbeat": legacy_heartbeat}

def legacy(emit_unconverted_event):
    return emit_unconverted_event("heartbeat_recorded", {})
"""
    )

    domain = scan_graph_payload_architecture([source]).for_domain("vertical_slice")

    assert [site.command_name for site in domain.raw_handler_boundaries] == ["record_heartbeat"]
    assert len(domain.raw_producers) == 1
    assert not domain.is_clean


def test_inventory_counts_unconverted_event_registry_and_typed_serialization(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mixed_events.py"
    source.write_text(
        """\
from orchestrator.graph import EventEnvelope

_LIFECYCLE_EVENT_PAYLOAD_MODELS = {"lease_renewed": LeaseRenewedPayload}

def _to_legacy_envelope(event):
    return EventEnvelope(event_type=event.metadata.event_type, payload=event.payload.to_json())
"""
    )

    report = scan_graph_payload_architecture([source])

    assert report.produced_event_names == {"lease_renewed"}
    assert {site.classification for site in report.dynamic_event_sites} == {
        "typed_event_serialization",
        "unconverted_event_registry",
    }


def test_inventory_classifies_temporary_lease_renewal_without_dirtying_vertical_slice(
    tmp_path: Path,
) -> None:
    source = tmp_path / "lease_bridge.py"
    source.write_text(
        """\
HEARTBEAT_RECORDED = EventSpecification(name="heartbeat_recorded", payload_type=Payload)
RECORD_HEARTBEAT = CommandSpecification(name="record_heartbeat", payload_type=Command)

def temporary_bridge(emit_unconverted_event):
    return emit_unconverted_event("lease_renewed", {})
"""
    )

    report = scan_graph_payload_architecture([source])

    assert any(
        site.classification == "unconverted_bridge" and site.resolved_values == ("lease_renewed",)
        for site in report.dynamic_event_sites
    )
    assert report.for_domain("vertical_slice").is_clean


def test_inventory_resolves_positional_keyword_qualified_and_aliased_envelopes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "direct.py"
    source.write_text(
        """\
from orchestrator.graph.models import EventEnvelope as Envelope
import orchestrator.graph.models as graph_models

def EventEnvelope(*args, **kwargs):
    return (args, kwargs)

local = EventEnvelope(event_type="not_a_graph_event", payload={})
aliased = Envelope("event-1", "run-1", 0, "aliased_event", payload={})
qualified = graph_models.EventEnvelope(event_type="qualified_event", payload={})
"""
    )

    report = scan_graph_payload_architecture([source])

    assert report.literal_event_names == {"aliased_event", "qualified_event"}


def test_call_graph_resolution_does_not_merge_same_named_functions(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text(
        """\
def emit(name, payload):
    return make_event(name, payload)

emit("first_event", {})
"""
    )
    second.write_text(
        """\
def emit(name, payload):
    return make_event(name, payload)

emit("second_event", {})
"""
    )

    report = scan_graph_payload_architecture([first, second])

    resolved_by_path = {
        Path(site.path).name: site.resolved_values for site in report.dynamic_event_sites
    }
    assert resolved_by_path == {
        "first.py": ("first_event",),
        "second.py": ("second_event",),
    }


def test_call_graph_resolution_scopes_same_named_methods_by_class(
    tmp_path: Path,
) -> None:
    source = tmp_path / "classes.py"
    source.write_text(
        """\
from orchestrator.graph.models import EventEnvelope

class First:
    def _event(self, event_type, payload):
        return EventEnvelope(event_type=event_type, payload=payload)
    def emit(self):
        self._event("first_event", {})

class Second:
    def _event(self, event_type, payload):
        return EventEnvelope(event_type=event_type, payload=payload)
    def emit(self):
        self._event("second_event", {})
"""
    )

    report = scan_graph_payload_architecture([source])

    assert [site.resolved_values for site in report.dynamic_event_sites] == [
        ("first_event",),
        ("second_event",),
    ]


def test_domain_cleanliness_lists_every_remaining_category_and_location(
    tmp_path: Path,
) -> None:
    source = tmp_path / "lifecycle.py"
    source.write_text(
        """\
from pydantic import BaseModel, model_validator

LIGHT_GRAPH_PAYLOAD_FIELDS = ("node_id",)

class HeartbeatRecordedPayload(BaseModel):
    node_id: str
    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value):
        return value

def handle_record_heartbeat(payload: dict[str, object]):
    filtered = {key: value for key, value in payload.items() if key in LIGHT_GRAPH_PAYLOAD_FIELDS}
    return make_event("heartbeat_recorded", filtered)

COMMAND_HANDLERS = {"record_heartbeat": handle_record_heartbeat}
"""
    )

    domain = scan_graph_payload_architecture([source]).for_domain("lifecycle")
    diagnostics = domain.remaining_diagnostics()

    assert [item.split(": ", 1)[0] for item in diagnostics] == [
        "raw producer",
        "raw handler boundary",
        "compatibility model",
        "allowlist",
        "partial payload consumer",
    ]
    assert all(f"{source}:" in item for item in diagnostics)


def test_explicit_domain_owns_heartbeat_compatibility_models(
    tmp_path: Path,
) -> None:
    source = tmp_path / "models.py"
    source.write_text(
        """\
from pydantic import BaseModel

class LifecycleEventPayloadBase(BaseModel):
    pass

class HeartbeatRecordedPayload(LifecycleEventPayloadBase):
    node_id: str | None = None
"""
    )

    domain = scan_graph_payload_architecture([source]).for_domain("vertical_slice")

    assert [model.name for model in domain.compatibility_models] == [
        "LifecycleEventPayloadBase",
        "HeartbeatRecordedPayload",
    ]
    assert not domain.is_clean


def test_vertical_slice_does_not_own_shared_base_after_heartbeat_relocation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "models.py"
    source.write_text(
        """\
from pydantic import BaseModel

class LifecycleEventPayloadBase(BaseModel):
    pass
"""
    )

    domain = scan_graph_payload_architecture([source]).for_domain("vertical_slice")

    assert domain.compatibility_models == ()


def test_lifecycle_domain_rejects_task2_architecture_backdoors(tmp_path: Path) -> None:
    source = tmp_path / "commands.py"
    source.write_text(
        """\
def temporary_unconverted_callback(command):
    return _renamed_raw_callback(command.model_dump())

def apply_command(name, payload, catalog=None):
    if name == "submit_callback" and catalog is None:
        return _renamed_raw_callback(payload)

def reduce_event(projection, event):
    if event.event_type == "callback_accepted":
        payload = CallbackAcceptedPayload.model_validate(event.payload)
        return projection.with_value(payload.get("node_id"))

def wrapper(command):
    effects = future_command_effects()
    return effects.callback(command)
"""
    )

    domain = scan_graph_payload_architecture([source]).for_domain("lifecycle")

    categories = {item.split(":", 1)[0] for item in domain.remaining_diagnostics()}
    assert categories == {
        "central reducer validation",
        "converted reducer branch",
        "converted payload.get",
        "implicit future effects",
        "raw converted command bypass",
        "strict model delegation",
        "temporary unconverted marker",
    }
    assert not domain.is_clean


def test_lifecycle_domain_rejects_delegated_raw_handler_even_without_model_dump(
    tmp_path: Path,
) -> None:
    source = tmp_path / "callbacks.py"
    source.write_text(
        """\
def handle_submit_callback(command: SubmitCallbackCommand):
    return _renamed_raw_callback(command)

def _renamed_raw_callback(payload: dict[str, object]):
    return payload.get("node_id")
"""
    )

    diagnostics = (
        scan_graph_payload_architecture([source]).for_domain("lifecycle").remaining_diagnostics()
    )

    assert any(item.startswith("delegated raw handler:") for item in diagnostics)


def test_graph_payload_architecture_checker_reports_real_fixture(tmp_path: Path) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    source = tmp_path / "projection.py"
    source.write_text(
        """\
def reduce_event(projection, event):
    if event.event_type == "agent_died":
        return AgentDiedPayload.model_validate(event.payload)
"""
    )

    diagnostics = check_paths([source], domain="lifecycle")

    assert {item.category for item in diagnostics} == {
        "central reducer validation",
        "converted reducer branch",
    }
    assert {item.path for item in diagnostics} == {str(source)}


def test_topology_domain_rejects_the_same_architecture_backdoors(tmp_path: Path) -> None:
    source = tmp_path / "topology.py"
    source.write_text(
        """\
def handle_seed_compiled_events(command: SeedCompiledEventsCommand):
    return raw_seed(command.model_dump())

def raw_seed(payload: dict[str, object]):
    return payload

def apply_command(name, payload, catalog=None):
    if name == "seed_compiled_events" and catalog is None:
        return raw_seed(payload)

def reduce_event(projection, event):
    if event.event_type == "node_created":
        payload = NodeCreatedPayload.model_validate(event.payload)
        return payload.get("node_id")
"""
    )

    categories = {
        item.split(":", 1)[0]
        for item in scan_graph_payload_architecture([source])
        .for_domain("topology")
        .remaining_diagnostics()
    }

    assert categories == {
        "central reducer validation",
        "converted payload.get",
        "converted reducer branch",
        "raw converted command bypass",
        "strict model delegation",
    }


def test_checker_ignores_runtime_command_callers_and_unrelated_payload_reads(
    tmp_path: Path,
) -> None:
    source = tmp_path / "dispatch.py"
    source.write_text(
        """\
class Dispatcher:
    async def _submit_callback(self, context):
        return await self._handle_command_retry_stale("submit_callback", {})

    async def _agent_died(self, context):
        return await self._handle_command_retry_stale("agent_died", {})

    async def _submit_graph_patch_callback(self, patch_payload):
        payload = dict(patch_payload)
        return payload.get("patch_id", "unknown")

    async def _handle_command_retry_stale(self, command_type, payload: dict[str, object]):
        return command_type, payload
"""
    )

    from scripts.check_graph_payload_architecture import check_paths

    assert check_paths([source], domain="lifecycle") == ()


def test_temporary_marker_blocks_its_own_domain_only(tmp_path: Path) -> None:
    source = tmp_path / "lease_bridge.py"
    source.write_text(
        """\
def apply_temporary_unconverted_lease_renewal(command):
    return emit_unconverted_event("lease_renewed", command)
"""
    )

    from scripts.check_graph_payload_architecture import check_paths

    assert check_paths([source], domain="topology") == ()
    assert {item.category for item in check_paths([source], domain="leases")} == {
        "temporary unconverted marker"
    }
