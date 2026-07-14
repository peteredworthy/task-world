from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.w5_payload_ast_inventory import (
    BASELINE_COMMAND_NAMES,
    BASELINE_EVENT_NAMES,
    main as inventory_main,
    render_consumer_report,
    scan_graph_payload_architecture,
    scan_payload_consumers,
    _default_paths,
)
from scripts.check_graph_payload_architecture import check_paths


def test_inventory_cli_runs_when_invoked_as_a_script() -> None:
    root = Path(__file__).parents[2]

    result = subprocess.run(
        (
            sys.executable,
            "scripts/w5_payload_ast_inventory.py",
            "--format",
            "json",
            "src/orchestrator/graph/events",
        ),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "literal_event_names" in json.loads(result.stdout)


def test_architecture_checker_cli_runs_when_invoked_as_a_script() -> None:
    root = Path(__file__).parents[2]

    result = subprocess.run(
        (sys.executable, "scripts/check_graph_payload_architecture.py"),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_architecture_checker_rejects_retired_strict_cutover_constructs(tmp_path: Path) -> None:
    source = tmp_path / "legacy_cutover.py"
    source.write_text(
        """\
class LegacyEventPayload:
    def get(self, key):
        return key

def hydrate(source_schema_version):
    if source_schema_version == 1:
        return _D3_LEGACY_RECORD_EVENT_TYPES
    return LegacyEventPayload()
"""
    )

    diagnostics = check_paths([source])

    assert {diagnostic.category for diagnostic in diagnostics} == {
        "retired D-series mapping method",
        "retired graph payload compatibility",
    }


@pytest.mark.parametrize("payload_expression", ("{}", "payload", "make_payload()"))
def test_architecture_checker_rejects_every_raw_event_envelope_payload_shape(
    tmp_path: Path, payload_expression: str
) -> None:
    source = tmp_path / "production_graph.py"
    source.write_text(
        f"""\
from orchestrator.graph.models import EventEnvelope

def make_payload():
    return {{"node_id": "node-1"}}

def emit(payload):
    return EventEnvelope(event_type="node_created", payload={payload_expression})
"""
    )

    diagnostics = check_paths([source])

    assert "W5RAW_EVENT_ENVELOPE_CONSTRUCTION" in {
        diagnostic.category for diagnostic in diagnostics
    }


def test_architecture_checker_allows_stored_event_envelope_serialization_boundary(
    tmp_path: Path,
) -> None:
    source = tmp_path / "storage_boundary.py"
    source.write_text(
        """\
from orchestrator.graph.specifications import StoredEventEnvelope

def serialize(metadata, payload):
    return StoredEventEnvelope(**metadata, payload=payload)
"""
    )

    diagnostics = check_paths([source])

    assert "W5RAW_EVENT_ENVELOPE_CONSTRUCTION" not in {
        diagnostic.category for diagnostic in diagnostics
    }


EXPECTED_ARCHITECTURE_METRICS = {
    "registered_event_specs": 44,
    "registered_command_specs": 23,
    "event_payload_raw_reads_in_kernel": 0,
    "raw_event_or_command_boundary_dict_annotations": 0,
    "direct_dictionary_event_construction_sites": 0,
    "hand_maintained_payload_field_allowlists": 0,
    "w5_legacy_payload_before_validators": 0,
    "w5_top_level_payload_extra_fields": 0,
    "central_command_handler_tables": 0,
    "central_reduce_event_name_branches": 0,
    "eligible_ast_cst_migration_sites_remaining": 0,
    "codemod_second_run_changes": 0,
    "unclassified_dynamic_event_or_command_sites": 0,
    "retired_payload_compatibility_adapters": 0,
}


def test_architecture_metrics_emit_stable_json_and_separate_deferred_sites() -> None:
    from scripts.measure_graph_payload_architecture import measure

    root = Path(__file__).parents[2]

    first = measure(root, migrations={})
    second = measure(root, migrations={})

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["metrics"] == EXPECTED_ARCHITECTURE_METRICS
    assert first["deferred_compatibility"] == {"site_count": 0, "sites": []}


def test_architecture_metrics_emit_stable_markdown() -> None:
    from scripts.measure_graph_payload_architecture import _markdown, measure

    root = Path(__file__).parents[2]

    rendered = _markdown(measure(root, migrations={}))

    assert rendered.startswith("# Graph Payload Architecture Metrics\n\n")
    for name, value in EXPECTED_ARCHITECTURE_METRICS.items():
        assert f"| `{name}` | {value} |" in rendered
    assert "## Deferred D1-D6 Compatibility" in rendered


def test_retired_compatibility_metric_counts_legacy_adapters_and_seam_comments(
    tmp_path: Path,
) -> None:
    from scripts.measure_graph_payload_architecture import (
        _retired_payload_compatibility_count,
    )

    source = tmp_path / "adapter.py"
    source.write_text("# Task 9 deletion seam\nclass LegacyTemporaryAdapter:\n    pass\n")

    assert _retired_payload_compatibility_count([source]) == 2


def test_architecture_checker_rejects_legacy_adapters_and_seam_comments(
    tmp_path: Path,
) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    source = tmp_path / "src/orchestrator/graph/adapter.py"
    source.parent.mkdir(parents=True)
    source.write_text("# Task 9 deletion seam\nclass LegacyTemporaryAdapter:\n    pass\n")

    assert {item.category for item in check_paths([source])} == {
        "retired graph compatibility adapter",
        "retired graph compatibility seam",
    }


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


def test_catalog_inventory_default_scope_covers_all_production_roots() -> None:
    assert _default_paths() == (Path("src/orchestrator"),)


def test_inventory_recognizes_typed_lifecycle_specs_and_dispatch_sites() -> None:
    """Typed declarations remain part of the authoritative 44/23 inventory."""
    report = scan_graph_payload_architecture(
        [Path("src/orchestrator/graph"), Path("src/orchestrator/graph_runtime")]
    )

    assert {
        "agent_died",
        "agent_dispatch_requested",
        "callback_accepted",
        "callback_duplicate_returned",
        "callback_rejected_conflict",
        "callback_rejected_stale",
        "command_rejected",
        "heartbeat_recorded",
        "run_lifecycle_changed",
        "runtime_retry_scheduled",
    } <= report.produced_event_names
    assert {
        "accept_run",
        "acknowledge_start",
        "agent_died",
        "cancel",
        "complete",
        "fail",
        "pause",
        "resume",
        "seed_compiled_events",
        "start",
        "submit_callback",
    } <= set(report.command_names)

    classifications = {
        (Path(site.path).as_posix(), site.expression): site.classification
        for site in report.dynamic_event_sites
    }
    assert (
        classifications[("src/orchestrator/graph/_commands.py", "specification.name")]
        == "typed_specification_dispatch"
    )


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


@pytest.mark.parametrize(
    ("source_text", "rule", "line"),
    [
        ("def reduce(event):\n    return event.payload.get('node_id')\n", "W5RAW_PAYLOAD_READ", 2),
        ("def reduce(event):\n    return event.payload['node_id']\n", "W5RAW_PAYLOAD_READ", 2),
        (
            "from typing import Any\ndef handle(payload: dict[str, Any]):\n    return payload\n",
            "W5RAW_BOUNDARY_DICT",
            2,
        ),
        (
            "event = EventEnvelope(event_type='node_created', payload={'node_id': 'n-1'})\n",
            "W5DIRECT_DICTIONARY_EVENT",
            1,
        ),
        *[
            (f"{name} = ('node_id',)\n", "W5PAYLOAD_ALLOWLIST", 1)
            for name in (
                "GRAPH_PROJECTION_PAYLOAD_FIELDS",
                "LIGHT_GRAPH_PAYLOAD_FIELDS",
                "SUMMARY_REBUILD_PAYLOAD_FIELDS",
                "NODE_DETAIL_PAYLOAD_FIELDS",
            )
        ],
        (
            "from pydantic import model_validator\n"
            "class NodeCreatedPayload(StrictPayload):\n"
            "    @model_validator(mode='before')\n"
            "    @classmethod\n"
            "    def normalize(cls, value):\n"
            "        return value\n",
            "W5BEFORE_PAYLOAD_NORMALIZER",
            3,
        ),
        (
            "class NodeCreatedPayload(StrictPayload):\n    extra: dict[str, object]\n",
            "W5TOP_LEVEL_PAYLOAD_EXTRA",
            2,
        ),
        ("COMMAND_HANDLERS = {'start': handle_start}\n", "W5CENTRAL_COMMAND_HANDLERS", 1),
        (
            "def reduce_event(event):\n"
            "    if event.metadata.event_type == 'node_created':\n"
            "        return event.payload\n",
            "W5CENTRAL_REDUCE_EVENT_BRANCH",
            2,
        ),
        ("DEFAULT_CATALOG = build_graph_catalog()\n", "W5IMPLICIT_CATALOG", 1),
        (
            "def emit(event_name, payload):\n    return make_event(event_name, payload)\n",
            "W5UNCLASSIFIED_DYNAMIC_SITE",
            2,
        ),
    ],
)
def test_architecture_checker_reports_each_catalog_wide_rule_from_valid_source(
    tmp_path: Path, source_text: str, rule: str, line: int
) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    ast.parse(source_text)
    source = tmp_path / "src/orchestrator/graph/fixture.py"
    source.parent.mkdir(parents=True)
    source.write_text(source_text)

    diagnostics = check_paths([source])

    expected = [(rule, line)]
    if "EventEnvelope(" in source_text:
        expected.append(("W5RAW_EVENT_ENVELOPE_CONSTRUCTION", line))
    assert [(item.rule, item.line) for item in diagnostics] == expected


@pytest.mark.parametrize(
    ("relative_path", "source_text"),
    [
        (
            "src/orchestrator/graph/events/example.py",
            "def reduce(payload):\n    return payload.node_id\n",
        ),
        (
            "src/orchestrator/api/routers/graph.py",
            "from typing import Any\n"
            "def parse_graph_command_payload(payload: dict[str, Any]):\n"
            "    return payload\n",
        ),
        (
            "src/orchestrator/graph/events/example.py",
            "def serialize(payload):\n    return payload.model_dump(mode='json')\n",
        ),
    ],
)
def test_architecture_checker_keeps_typed_boundaries_clean(
    tmp_path: Path, relative_path: str, source_text: str
) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    ast.parse(source_text)
    source = tmp_path / relative_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(source_text)

    assert check_paths([source]) == ()


@pytest.mark.parametrize(
    ("case", "relative_path", "dirty_source", "expected_rules", "allowed_source"),
    [
        (
            "fake registered function name",
            "src/orchestrator/graph/callbacks.py",
            "def _history_payload_value(event):\n    return event.payload.get('node_id')\n",
            ("W5RAW_PAYLOAD_READ",),
            "def helper(value):\n    return value.get('node_id')\n",
        ),
        (
            "unrelated EventEnvelope handler",
            "src/orchestrator/graph/events/example.py",
            "def handle_current(event: EventEnvelope):\n    return event.payload.get('node_id')\n",
            ("W5RAW_PAYLOAD_READ",),
            "def handle_current(event: HydratedEvent):\n    return event.payload.node_id\n",
        ),
        (
            "nonstandard command boundary name",
            "src/orchestrator/graph/commands/example.py",
            "from typing import Any\n"
            "def route(command_type: str, payload: dict[str, Any], catalog: GraphCatalog):\n"
            "    return catalog.resolve_command(command_type).validate(payload)\n",
            ("W5RAW_BOUNDARY_DICT",),
            "from typing import Any\n"
            "def format_for_log(payload: dict[str, Any]):\n"
            "    return sorted(payload)\n",
        ),
        (
            "positional envelope dictionary",
            "src/orchestrator/graph/events/example.py",
            "event = EventEnvelope('event-1', 'run-1', 0, 'node_created', 2, actor, "
            "None, None, now, {'node_id': 'n-1'})\n",
            ("W5DIRECT_DICTIONARY_EVENT", "W5RAW_EVENT_ENVELOPE_CONSTRUCTION"),
            "event = NODE_CREATED.create(metadata, NodeCreatedPayload(node_id='n-1'))\n",
        ),
        (
            "inherited strict payload violations",
            "src/orchestrator/graph/events/example.py",
            "from pydantic import model_validator\n"
            "class DomainPayload(StrictPayload):\n"
            "    value: str\n"
            "class ChildPayload(DomainPayload):\n"
            "    extra: dict[str, object]\n"
            "    @model_validator(mode='before')\n"
            "    @classmethod\n"
            "    def normalize(cls, value):\n"
            "        return value\n",
            ("W5TOP_LEVEL_PAYLOAD_EXTRA", "W5BEFORE_PAYLOAD_NORMALIZER"),
            "class NestedRecord(BaseModel):\n    extra: dict[str, object]\n",
        ),
        (
            "equivalent command dispatch table",
            "src/orchestrator/graph/commands/example.py",
            "ROUTES = {'start': handle_start, 'pause': handle_pause}\n",
            ("W5CENTRAL_COMMAND_HANDLERS",),
            "LABELS = {'start': 'Start', 'pause': 'Pause'}\n",
        ),
    ],
)
def test_architecture_checker_adversarial_cases_fail_closed_with_clean_neighbors(
    tmp_path: Path,
    case: str,
    relative_path: str,
    dirty_source: str,
    expected_rules: tuple[str, ...],
    allowed_source: str,
) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    ast.parse(dirty_source)
    ast.parse(allowed_source)
    dirty = tmp_path / "dirty" / relative_path
    dirty.parent.mkdir(parents=True)
    dirty.write_text(dirty_source)
    allowed = tmp_path / "allowed" / relative_path
    allowed.parent.mkdir(parents=True)
    allowed.write_text(allowed_source)

    assert tuple(item.rule for item in check_paths([dirty])) == expected_rules, case
    assert check_paths([allowed]) == (), case


@pytest.mark.parametrize(
    ("source", "expected_rule"),
    [
        (
            """\
async def assigned_return(controller, run_id, position, payload):
    result = await controller.handle_command(run_id, position, "start", payload)
    return result

async def caller(controller, run_id, position, payload):
    result = await assigned_return(controller, run_id, position, payload)
    for event in result.events:
        return event.payload.get("record_id")
""",
            "W5RAW_PAYLOAD_READ",
        ),
        (
            """\
async def aliased_method(controller, run_id, position, payload):
    invoke = controller.handle_command
    return await invoke(run_id, position, "start", payload)

async def caller(controller, run_id, position, payload):
    result = await aliased_method(controller, run_id, position, payload)
    for event in result.events:
        return event.payload.get("record_id")
""",
            "W5RAW_PAYLOAD_READ",
        ),
        (
            """\
async def first(controller, run_id, position, payload):
    return await controller.handle_command(run_id, position, "start", payload)

second = first
third = second

async def caller(controller, run_id, position, payload):
    result = await third(controller, run_id, position, payload)
    for event in result.events:
        return event.payload.get("record_id")
""",
            "W5RAW_PAYLOAD_READ",
        ),
    ],
    ids=("assigned_return", "aliased_method", "multi_hop"),
)
def test_architecture_checker_tracks_command_wrapper_provenance_to_a_fixed_point(
    tmp_path: Path, source: str, expected_rule: str
) -> None:
    path = tmp_path / "src/orchestrator/graph_runtime/example.py"
    path.parent.mkdir(parents=True)
    path.write_text(source)

    assert expected_rule in {diagnostic.rule for diagnostic in check_paths([path])}


def test_architecture_checker_allows_explicit_storage_serializer_boundary(tmp_path: Path) -> None:
    path = tmp_path / "src/orchestrator/graph_runtime/store.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        """\
def serialize_for_storage(event: HydratedEvent):
    return event.payload.to_json()
"""
    )

    assert check_paths([path]) == ()


def test_architecture_metrics_measure_codemod_passes_independently(tmp_path: Path) -> None:
    from scripts.codemods.w5_strict_payload_cutover import DomainMigration, EventRoute
    from scripts.measure_graph_payload_architecture import measure

    source = tmp_path / "graph.py"
    source.write_text("from package import make_event\nevent = make_event('started', payload)\n")
    migration = DomainMigration(
        domain="fixture",
        paths=("graph.py",),
        event_routes=(EventRoute("started", "StartedPayload", "STARTED"),),
        event_factory_qualified_names=("package.make_event",),
    )

    report = measure(tmp_path, migrations={"fixture": migration})
    metrics = report["metrics"]

    assert isinstance(metrics, dict)
    assert metrics["eligible_ast_cst_migration_sites_remaining"] == 1
    assert metrics["codemod_second_run_changes"] == 0


def test_legacy_exemption_requires_guard_event_and_read_in_same_branch(tmp_path: Path) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    source = tmp_path / "src/orchestrator/graph/projections.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """\
def unrelated_guard(event):
    return event.schema_version == 1 and event.event_type == "output_record_accepted"

def reduce_d3_legacy_record_replay(event):
    return event.payload.get("record")
"""
    )

    assert [item.rule for item in check_paths([source])] == ["W5RAW_PAYLOAD_READ"]


def test_legacy_exemption_rejects_read_outside_matching_guard_branch(tmp_path: Path) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    source = tmp_path / "src/orchestrator/graph/projections.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """\
def reduce_d3_legacy_record_replay(event):
    if event.schema_version == 1 and event.event_type == "output_record_accepted":
        marker = True
    return event.payload.get("record")
"""
    )

    assert [item.rule for item in check_paths([source])] == ["W5RAW_PAYLOAD_READ"]


def test_legacy_payload_reads_are_not_exempt_inside_matching_branches(
    tmp_path: Path,
) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    source = tmp_path / "src/orchestrator/graph/projections.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """\
def reduce_d3_legacy_record_replay(event):
    if event.schema_version == 1 and event.event_type == "output_record_accepted":
        registered = event.payload.get("record")
        added = event.payload.get("unregistered")
        return registered, added
    return None
"""
    )

    diagnostics = check_paths([source])

    assert [(item.rule, item.line) for item in diagnostics] == [
        ("W5RAW_PAYLOAD_READ", 3),
        ("W5RAW_PAYLOAD_READ", 4),
    ]


def test_event_envelope_annotation_never_bypasses_raw_read_rule(tmp_path: Path) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    source = tmp_path / "src/orchestrator/graph/events/example.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def helper(event: EventEnvelope):\n    return event.payload.get('node_id')\n"
    )

    assert [item.rule for item in check_paths([source])] == ["W5RAW_PAYLOAD_READ"]


def test_hydrated_payload_local_alias_never_bypasses_mapping_read_rule(tmp_path: Path) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    source = tmp_path / "src/orchestrator/graph_runtime/prompts.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """\
def accepted_patch_id(event):
    payload = event.payload
    if isinstance(payload, GraphPatchAcceptedPayload):
        return payload.get("patch_id")

def file_state_id(event):
    record = event.payload
    if isinstance(record, StrictFileStateRecord):
        return record["record_id"]
"""
    )

    diagnostics = check_paths([source])

    assert [(item.rule, item.line) for item in diagnostics] == [
        ("W5RAW_PAYLOAD_READ", 4),
        ("W5RAW_PAYLOAD_READ", 9),
    ]


def test_strict_payload_parameter_alias_never_bypasses_mapping_read_rule(tmp_path: Path) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    source = tmp_path / "src/orchestrator/graph_runtime/gatekeeper.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """\
def metadata(record: StrictFileStateRecord):
    return record.get("record_id"), record["residue"], record.items()
"""
    )

    diagnostics = check_paths([source])

    assert [(item.rule, item.line) for item in diagnostics] == [
        ("W5RAW_PAYLOAD_READ", 2),
        ("W5RAW_PAYLOAD_READ", 2),
        ("W5RAW_PAYLOAD_READ", 2),
    ]


def test_current_workflow_and_api_hydrated_aliases_never_bypass_mapping_read_rule(
    tmp_path: Path,
) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    workflow = tmp_path / "src/orchestrator/workflow/graph_driver.py"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        """\
async def cancel(controller):
    result = await controller.handle_command("run", 1, "cancel", {})
    return any(
        event.payload.get("to_state") == "cancelled"
        or event.payload.get("command_type") == "cancel"
        for event in result.events
    )
"""
    )
    api = tmp_path / "src/orchestrator/api/routers/graph.py"
    api.parent.mkdir(parents=True)
    api.write_text(
        """\
def callback(event: HydratedEvent):
    return event.payload.to_json().get("trigger")

def summary(events: Sequence[HydratedEvent]):
    for event in reversed(events):
        return event.payload.to_json().get("prompt_summary")

async def decision(controller):
    result = await controller.handle_command("run", 1, "record_decision", {})
    rejected = [event.payload for event in result.events if event.event_type == "command_rejected"]
    return rejected[-1].get("reason")

async def patch(controller):
    result = await controller.handle_command("run", 1, "submit_patch", {})
    rejection = next((event for event in result.events if event.event_type == "graph_patch_rejected"), None)
    return rejection.payload.get("reason")

def external_boundary(event: EventEnvelope):
    return event.payload.get("node_id")
"""
    )

    diagnostics = check_paths([workflow, api])

    assert [(item.rule, item.path, item.line) for item in diagnostics] == [
        ("W5RAW_PAYLOAD_READ", str(api), 2),
        ("W5RAW_PAYLOAD_READ", str(api), 6),
        ("W5RAW_PAYLOAD_READ", str(api), 11),
        ("W5RAW_PAYLOAD_READ", str(api), 16),
        ("W5RAW_PAYLOAD_READ", str(workflow), 4),
        ("W5RAW_PAYLOAD_READ", str(workflow), 5),
    ]


def test_retry_helper_event_payload_json_alias_never_bypasses_mapping_read_rule(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/orchestrator/graph_runtime/dispatch.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """\
class Dispatcher:
    async def _handle_command_retry_stale(self, controller):
        return await controller.handle_command("run", 1, "record_heartbeat", {})

    async def heartbeat(self, controller):
        result = await self._handle_command_retry_stale(controller)
        rejection = next(event for event in result.events if event.event_type == "command_rejected")
        payload = event_payload_json(rejection)
        return payload.get("reason")
"""
    )

    diagnostics = check_paths([source])

    assert [(item.rule, item.line) for item in diagnostics] == [("W5RAW_PAYLOAD_READ", 9)]


def test_retry_helper_narrowed_strict_payload_never_bypasses_mapping_read_rule(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/orchestrator/graph_runtime/dispatch.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """\
class Dispatcher:
    async def retry(self, controller):
        return await controller.handle_command("run", 1, "record_cleanup_applied", {})

    async def cleanup(self, controller):
        result = await self.retry(controller)
        rejection = next(event for event in result.events if event.event_type == "command_rejected")
        payload = rejection.payload
        return payload.get("reason")
"""
    )

    diagnostics = check_paths([source])

    assert [(item.rule, item.line) for item in diagnostics] == [("W5RAW_PAYLOAD_READ", 9)]


def test_command_dispatch_dictionary_uses_callable_structure_not_known_keys(
    tmp_path: Path,
) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    dirty = tmp_path / "dirty/src/orchestrator/graph/commands/example.py"
    dirty.parent.mkdir(parents=True)
    dirty.write_text(
        "def launch_handler(): pass\n"
        "def halt_handler(): pass\n"
        "ROUTES = {'launch-custom': launch_handler, 'halt-custom': halt_handler}\n"
    )
    allowed = tmp_path / "allowed/src/orchestrator/graph/commands/example.py"
    allowed.parent.mkdir(parents=True)
    allowed.write_text("LABELS = {'launch-custom': 'Launch', 'halt-custom': {'label': 'Halt'}}\n")

    assert [item.rule for item in check_paths([dirty])] == ["W5CENTRAL_COMMAND_HANDLERS"]
    assert check_paths([allowed]) == ()


def test_deferred_legacy_sites_are_pinned_to_exact_current_identities() -> None:
    report = scan_graph_payload_architecture(
        [Path("src/orchestrator/graph"), Path("src/orchestrator/graph_runtime")]
    )
    identities = {
        (
            fact.path,
            fact.line,
            fact.column,
            fact.rule,
            "apply_command"
            if fact.expression.startswith("def apply_command")
            else fact.expression.split(": ", 1)[0],
        )
        for fact in report.deferred_architecture_facts
    }

    assert identities == set()


def test_records_legacy_replay_requires_a_recognized_d3_branch(tmp_path: Path) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    source = tmp_path / "projection.py"
    source.write_text(
        """\
def reduce_event(projection, event):
    if event.event_type == "unrelated_event":
        return projection
    marker = "output_record_accepted"
    return projection, marker
"""
    )

    diagnostics = check_paths([source], domain="records")

    assert {item.category for item in diagnostics} == {"converted reducer branch"}


def test_records_random_verification_branch_is_not_a_d3_exemption(tmp_path: Path) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    source = tmp_path / "projection.py"
    source.write_text(
        """\
def reduce_event(projection, event):
    if event.event_type == "verification_passed":
        return projection
    return projection
"""
    )

    diagnostics = check_paths([source], domain="records")

    assert {item.category for item in diagnostics} == {"converted reducer branch"}


def test_records_rejects_generation_one_d3_adapter(tmp_path: Path) -> None:
    from scripts.check_graph_payload_architecture import check_paths

    source = tmp_path / "projection.py"
    source.write_text(
        """\
def _is_d3_legacy_record_replay_event(event):
    return event.schema_version == 1 and event.event_type in {"verification_passed"}

def reduce_d3_legacy_record_replay(projection, event):
    if event.schema_version != 1:
        raise ValueError
    return reduce_legacy_event(projection, event)

def reduce_event(projection, event):
    marker = "output_record_accepted"
    if _is_d3_legacy_record_replay_event(event):
        return reduce_d3_legacy_record_replay(projection, event)
    return projection, marker
"""
    )

    assert {item.category for item in check_paths([source], domain="records")} == {
        "converted reducer branch"
    }


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


CONSUMER_READ_SOURCE = """\
from typing import Any

from orchestrator.graph.events.records import OutputRecordAcceptedPayload


def read_flat_subscript(event: Any) -> Any:
    if event.event_type == "output_record_accepted":
        return event.payload["record_type"]
    return None


def read_flat_get(event: Any) -> Any:
    if event.event_type == "output_record_accepted":
        return event.payload.get("record_id")
    return None


def read_nested(event: Any) -> Any:
    if event.event_type != "output_record_accepted":
        return None
    return event.payload["record"]["record_type"]


def read_missing_attribute(event: Any) -> str:
    payload = OutputRecordAcceptedPayload.model_validate(event.payload)
    return payload.record_id


def read_declared_attribute(event: Any) -> str:
    payload = OutputRecordAcceptedPayload.model_validate(event.payload)
    return payload.record.record_id


def read_record_dump(event: Any) -> Any:
    if event.event_type != "output_record_accepted":
        return None
    payload = OutputRecordAcceptedPayload.model_validate(event.payload).record.model_dump()
    return payload.get("record_id")


def read_isinstance_guarded(events: list) -> object:
    return next(
        event
        for event in events
        if event.metadata.event_type == "output_record_accepted"
        and isinstance(event.payload, OutputRecordAcceptedPayload)
        and event.payload.record_id == "routine-snapshot-record"
    )
"""


CONSUMER_SEED_SOURCE = """\
from typing import Any

from orchestrator.graph import EventEnvelope


def seed_valid() -> object:
    return EventEnvelope(
        event_id="evt-valid",
        run_id="run-1",
        position=-1,
        event_type="output_record_accepted",
        schema_version=1,
        actor=None,
        timestamp=None,
        payload={
            "record": {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "record_type": "candidate",
                "candidate_id": "candidate-1",
                "value": {"summary": "done"},
            }
        },
    )


def seed_flat_invalid() -> object:
    return EventEnvelope(
        event_type="output_record_accepted",
        payload={
            "record_type": "candidate",
            "record_id": "candidate-2",
            "value": {"summary": "done"},
        },
    )


def seed_make_event_flat() -> object:
    return make_event("output_record_accepted", {"record_type": "candidate"})


def seed_dynamic(payload: dict[str, Any]) -> object:
    return EventEnvelope(event_type="output_record_accepted", payload=payload)


def _event(event_type: str, payload: dict[str, Any]) -> object:
    body = {"record": payload} if "record" not in payload else payload
    return EventEnvelope(event_type=event_type, payload=body)


def seed_wrapped_valid() -> object:
    return _event(
        "output_record_accepted",
        {
            "record_id": "candidate-3",
            "record_kind": "output",
            "producer_node_id": "worker-1",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "record_type": "candidate",
            "candidate_id": "candidate-3",
            "value": {"summary": "done"},
        },
    )
"""


def test_consumer_scan_flags_flat_reads_and_attribute_misses_only(tmp_path: Path) -> None:
    source = tmp_path / "consumer_reads.py"
    source.write_text(CONSUMER_READ_SOURCE)

    sites = scan_payload_consumers([source], frozenset({"output_record_accepted"}))

    flat = [site for site in sites if site.classification == "flat_shape_read"]
    assert {site.snippet for site in flat} == {
        "event.payload['record_type']",
        "event.payload.get('record_id')",
    }
    attribute_misses = [site for site in sites if site.classification == "unknown_attribute_read"]
    assert {site.snippet for site in attribute_misses} == {
        "payload.record_id",
        "event.payload.record_id",
    }
    assert all(site.event == "output_record_accepted" for site in sites)
    # The correct nested form and declared attribute chains are not flagged.
    assert len(sites) == 4
    assert all("['record']['record_type']" not in site.snippet for site in sites)


def test_consumer_scan_requires_event_payload_provenance_for_local_payload_names(
    tmp_path: Path,
) -> None:
    source = tmp_path / "payload_provenance.py"
    source.write_text(
        """\
def command(payload: dict[str, object], event: object) -> object:
    emitted = make_event("output_record_accepted", {"record": {}})
    requested_id = payload.get("record_id")
    event_payload = event.payload
    if event.event_type == "output_record_accepted":
        return emitted, requested_id, event_payload.get("record_id")
    return emitted, requested_id, None
"""
    )

    sites = scan_payload_consumers([source], frozenset({"output_record_accepted"}))

    assert [site.snippet for site in sites if site.classification == "flat_shape_read"] == [
        "event_payload.get('record_id')"
    ]


def test_consumer_scan_narrows_shared_event_payload_reads_to_the_matching_branch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "event_branch.py"
    source.write_text(
        """\
def reduce(event: object) -> object:
    payload = event.payload
    if event.event_type == "node_created":
        return payload.get("task_region_id")
    if event.event_type == "output_record_accepted":
        return payload.get("record_id")
    return None
"""
    )

    sites = scan_payload_consumers([source], frozenset({"output_record_accepted"}))

    assert [site.snippet for site in sites if site.classification == "flat_shape_read"] == [
        "payload.get('record_id')"
    ]


def test_routine_compile_uses_nested_output_record_attributes() -> None:
    source = Path("tests/integration/test_graph_routine_compile.py")

    sites = scan_payload_consumers([source], frozenset({"output_record_accepted"}))

    assert [site for site in sites if site.classification == "unknown_attribute_read"] == []


def test_consumer_scan_validates_seed_literals_against_the_catalog(tmp_path: Path) -> None:
    source = tmp_path / "consumer_seeds.py"
    source.write_text(CONSUMER_SEED_SOURCE)

    sites = scan_payload_consumers([source], frozenset({"output_record_accepted"}))

    by_classification: dict[str, list[str]] = {}
    for site in sites:
        by_classification.setdefault(site.classification, []).append(site.snippet)
    invalid = by_classification.pop("invalid_seed")
    genuinely_invalid = [
        snippet
        for snippet in invalid
        if "payload={'record_type': 'candidate'" in snippet
        or snippet.startswith("make_event('output_record_accepted'")
    ]
    assert len(genuinely_invalid) == 2
    signature_false_positives = [snippet for snippet in invalid if snippet not in genuinely_invalid]
    assert len(signature_false_positives) == 2
    assert all(
        "stored_graph_event() missing 1 required positional argument: 'event'" in snippet
        for snippet in signature_false_positives
    )
    assert by_classification.pop("unverifiable_seed") == [
        "EventEnvelope(event_type='output_record_accepted', payload=payload)"
    ]
    # Valid seeds (direct nested and helper-wrapped) produce no findings.
    assert by_classification == {}


def test_consumer_scan_excludes_explicit_intentional_corruption_boundary(tmp_path: Path) -> None:
    source = tmp_path / "intentional_corruption.py"
    source.write_text(
        """\
async def persist(store, run_id):
    await store.append_events(
        run_id,
        0,
        [
            _event(
                "output_record_accepted",
                {"record": {"record_id": "intentionally-malformed"}},
            )
        ],
        allow_invalid_payloads=True,
    )
"""
    )

    sites = scan_payload_consumers([source], frozenset({"output_record_accepted"}))

    assert sites == ()


def test_check_consumers_cli_fails_on_flat_read_and_passes_when_clean(tmp_path: Path) -> None:
    dirty = tmp_path / "dirty.py"
    dirty.write_text(CONSUMER_READ_SOURCE)
    clean = tmp_path / "clean.py"
    clean.write_text(
        """\
def read_nested(event):
    if event.event_type != "output_record_accepted":
        return None
    return event.payload["record"]["record_type"]
"""
    )

    assert inventory_main(["--check-consumers", "records", str(dirty)]) == 1
    assert inventory_main(["--check-consumers", "records", str(clean)]) == 0
    assert inventory_main(["--check-consumers", "no-such-domain", str(clean)]) == 2


def test_catalog_cutover_inventory_classifies_current_dispatch_and_central_specs(
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
    return apply_command(catalog, projection, events, command_type, payload, context)
return apply_command(projection, events, command_type, payload, clock, id_gen)
"""
    )

    domain = scan_graph_payload_architecture([tmp_path]).for_domain("catalog_cutover")

    assert {site.classification for site in domain.catalog_cutover_sites} == {
        "catalog_membership_fallback_dispatch",
        "central_command_spec_enumeration",
    }
    assert not domain.is_clean


def test_catalog_cutover_inventory_detects_reduce_legacy_event(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/graph/projections.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """\
def reduce_legacy_event(command_type, payload):
    if command_type in catalog.command_specs:
        return apply_command(projection, events, command_type, payload, clock, id_gen)
    return None
"""
    )

    domain = scan_graph_payload_architecture([tmp_path]).for_domain("catalog_cutover")

    assert [site.classification for site in domain.catalog_cutover_sites] == [
        "catalog_membership_fallback_dispatch",
    ]


def test_catalog_cutover_inventory_detects_arbitrary_production_legacy_dispatch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "arbitrary_production_module.py"
    source.write_text(
        "apply_command(projection, events, command_type, payload, clock, id_gen, catalog=catalog, context=context)\n"
    )

    domain = scan_graph_payload_architecture([source]).for_domain("catalog_cutover")

    assert [site.classification for site in domain.catalog_cutover_sites] == [
        "legacy_apply_command"
    ]


def test_catalog_injection_inventory_classifies_escapes_and_missing_injection(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/orchestrator/api/deps.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """\
from orchestrator.graph import build_graph_catalog
from orchestrator.graph_runtime import GraphEventStore

GLOBAL_CATALOG = build_graph_catalog()

def factory(session, catalog=build_graph_catalog()):
    return GraphEventStore(session)
"""
    )

    domain = scan_graph_payload_architecture([tmp_path]).for_domain("catalog_injection")

    assert {site.classification for site in domain.catalog_cutover_sites} == {
        "catalog_default_escape",
        "catalog_global_escape",
        "missing_catalog_injection",
    }
    assert not domain.is_clean


def test_catalog_injection_inventory_allows_create_app_catalog_owner(tmp_path: Path) -> None:
    source = tmp_path / "src/orchestrator/api/app.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """\
def create_app():
    catalog = build_graph_catalog()
    return catalog
"""
    )

    domain = scan_graph_payload_architecture([tmp_path]).for_domain("catalog_injection")

    assert domain.catalog_cutover_sites == ()


def test_consumer_report_lists_sites_deterministically(tmp_path: Path) -> None:
    source = tmp_path / "consumer_reads.py"
    source.write_text(CONSUMER_READ_SOURCE)

    first = scan_payload_consumers([source], frozenset({"output_record_accepted"}))
    second = scan_payload_consumers([source], frozenset({"output_record_accepted"}))
    assert first == second

    rendered = render_consumer_report(first, frozenset({"output_record_accepted"}))
    assert rendered.splitlines()[0].startswith("Consumer payload scan (4 sites)")
    assert "flat_shape_read=2" in rendered
    assert "unknown_attribute_read=2" in rendered
