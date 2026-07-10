from __future__ import annotations

from pathlib import Path

from scripts.codemods.w5_strict_payload_cutover import (
    CatalogInjection,
    CommandRoute,
    DomainMigration,
    EventRoute,
    ImportRoute,
    StrictPayloadCutoverCodemod,
    SymbolRelocation,
    run_migration,
)


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
    catalog_injections=(CatalogInjection(callable_name="GraphController"),),
    report_dynamic_emissions=True,
)


BEFORE_LIFECYCLE_SOURCE = """\
from typing import Any

from orchestrator.graph.models import HeartbeatRecordedPayload

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

from orchestrator.graph.events.lifecycle import HeartbeatRecordedPayload

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
    assert "# Payload explanation stays with the class." in result.sources["events/records.py"]
    assert '"OutputRecordPayload"' in result.sources["events/records.py"]
    assert (
        StrictPayloadCutoverCodemod(migration).transform_files(result.sources).sources
        == result.sources
    )


def test_ambiguous_dynamic_emission_is_reported_without_editing() -> None:
    source = "event = make_event(event_name, payload)\n"

    result = StrictPayloadCutoverCodemod(LIFECYCLE_MIGRATION).transform_source(source)

    assert result.source == source
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "W5AMBIGUOUS_EVENT"
    assert result.diagnostics[0].line == 1


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
    source.write_text("first = make_event(first_name, {})\nsecond = make_event(second_name, {})\n")

    result = run_migration(LIFECYCLE_MIGRATION, tmp_path, mode="assert-clean")

    assert result.exit_code == 1
    assert "graph.py:1" in result.output
    assert "graph.py:2" in result.output


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
