from __future__ import annotations

from pathlib import Path

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
