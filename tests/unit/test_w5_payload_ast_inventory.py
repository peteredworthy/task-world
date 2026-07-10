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
