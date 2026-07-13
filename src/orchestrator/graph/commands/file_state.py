"""Typed file-state and cleanup commands."""

from typing import Any

from pydantic import Field

from orchestrator.graph.events.file_state import (
    CLEANUP_APPLIED,
    CLEANUP_REQUESTED,
    FILE_STATE_ACCEPTED,
    GATEKEEPER_COST_RECORDED,
    GATEKEEPER_VERDICT_RECORDED,
    CleanupAppliedPayload,
    CleanupRequestedPayload,
    GatekeeperCostRecordedPayload,
    GatekeeperVerdict,
    GatekeeperVerdictRecordedPayload,
)
from orchestrator.graph.events.lifecycle import COMMAND_REJECTED, CommandRejectedPayload
from orchestrator.graph.events.records import OUTPUT_RECORD_ACCEPTED, OutputRecordAcceptedPayload
from orchestrator.graph.models import EventEnvelope, StrictFileStateRecord
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    CommandSpecification,
    HydratedEvent,
)
from orchestrator.graph.commands.event_creator import TypedEventCreator


class RecordGatekeeperVerdictsCommand(StrictPayload):
    file_state_record_id: str
    execution_id: str = Field(min_length=1)
    consult_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    verdicts: list[GatekeeperVerdict]


class RecordCleanupAppliedCommand(StrictPayload):
    cleanup_id: str
    superseding_file_state_record: StrictFileStateRecord
    deleted_snapshot_ref: bool
    reason: str | None = None


def handle_record_gatekeeper_verdicts(
    command: RecordGatekeeperVerdictsCommand,
    projection: Any,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    creator = TypedEventCreator(context, assign_position=False)
    record = projection["file_state_records"].get(command.file_state_record_id)
    if record is None:
        return [
            _rejected(
                creator,
                "record_gatekeeper_verdicts",
                f"unknown file_state record: {command.file_state_record_id}",
            )
        ]
    if not command.verdicts:
        return [_rejected(creator, "record_gatekeeper_verdicts", "missing verdicts")]

    unresolved_paths = {entry.path for entry in record.residue if entry.needs_gatekeeper is True}
    seen_paths: set[str] = set()
    for verdict in command.verdicts:
        if verdict.path in seen_paths:
            return [
                _rejected(
                    creator, "record_gatekeeper_verdicts", f"duplicate verdict path: {verdict.path}"
                )
            ]
        seen_paths.add(verdict.path)
        if verdict.path not in unresolved_paths:
            return [
                _rejected(
                    creator,
                    "record_gatekeeper_verdicts",
                    f"path is not unresolved residue: {verdict.path}",
                )
            ]

    verdicts = tuple(command.verdicts)
    output = [
        creator.create(
            GATEKEEPER_VERDICT_RECORDED,
            GatekeeperVerdictRecordedPayload(
                file_state_record_id=command.file_state_record_id,
                execution_id=command.execution_id,
                producer_node_id=record.producer_node_id,
                verdicts=verdicts,
                resolved_count=len(verdicts),
            ),
        )
    ]
    secret_paths = tuple(verdict.path for verdict in verdicts if verdict.classification == "secret")
    if secret_paths:
        output.append(
            creator.create(
                CLEANUP_REQUESTED,
                CleanupRequestedPayload(
                    cleanup_id=f"{command.file_state_record_id}:gatekeeper-secret",
                    file_state_record_id=command.file_state_record_id,
                    snapshot_id=record.snapshot_id,
                    paths=secret_paths,
                    authority="gatekeeper",
                    reason="gatekeeper_classified_secret_after_snapshot",
                    execution_id=command.execution_id,
                    producer_node_id=record.producer_node_id,
                ),
            )
        )
    output.append(
        creator.create(
            GATEKEEPER_COST_RECORDED,
            GatekeeperCostRecordedPayload(
                file_state_record_id=command.file_state_record_id,
                execution_id=command.execution_id,
                consult_id=command.consult_id,
                model_id=command.model_id,
                input_tokens=sum(verdict.input_tokens for verdict in verdicts),
                output_tokens=sum(verdict.output_tokens for verdict in verdicts),
                cache_read_tokens=sum(verdict.cache_read_tokens for verdict in verdicts),
                cache_write_tokens=sum(verdict.cache_write_tokens for verdict in verdicts),
                cost_usd=sum(verdict.cost_usd for verdict in verdicts),
                wall_time_ms=sum(verdict.wall_time_ms for verdict in verdicts),
                item_count=len(verdicts),
            ),
        )
    )
    return output


def handle_record_cleanup_applied(
    command: RecordCleanupAppliedCommand,
    projection: Any,
    events: tuple[EventEnvelope, ...],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    del events
    creator = TypedEventCreator(context, assign_position=False)
    requested = projection["cleanup_requested_events"].get(command.cleanup_id)
    if requested is None:
        return [
            _rejected(
                creator,
                "record_cleanup_applied",
                f"unknown cleanup_requested: {command.cleanup_id}",
            )
        ]
    if projection["cleanup_applied_ids"].get(command.cleanup_id) is True:
        return [
            _rejected(
                creator, "record_cleanup_applied", f"cleanup already applied: {command.cleanup_id}"
            )
        ]

    record_id = requested.file_state_record_id
    compromised = projection["file_state_records"].get(record_id)
    if compromised is None:
        return [
            _rejected(
                creator, "record_cleanup_applied", f"unknown cleanup file_state record: {record_id}"
            )
        ]
    if requested.snapshot_id != compromised.snapshot_id:
        return [
            _rejected(
                creator,
                "record_cleanup_applied",
                "cleanup snapshot_id does not match compromised record",
            )
        ]

    record = command.superseding_file_state_record
    if record.supersedes_record_id != record_id:
        return [
            _rejected(
                creator,
                "record_cleanup_applied",
                "superseding record does not match cleanup target",
            )
        ]
    if record.cleanup_id != command.cleanup_id:
        return [
            _rejected(
                creator,
                "record_cleanup_applied",
                "superseding record cleanup_id does not match cleanup target",
            )
        ]
    if record.snapshot_id == compromised.snapshot_id:
        return [
            _rejected(
                creator,
                "record_cleanup_applied",
                "superseding record must use a different snapshot_id",
            )
        ]
    retained_path = _retained_path(record, set(requested.paths))
    if retained_path is not None:
        return [
            _rejected(
                creator,
                "record_cleanup_applied",
                f"superseding record still contains cleanup secret path: {retained_path}",
            )
        ]

    emitted_record = StrictFileStateRecord.model_validate(
        {
            **record.model_dump(mode="python"),
            "record_kind": "file_state",
            "record_type": "file_state",
            "port": "file_state",
            "schema": "FileStateRecord",
        }
    )
    return [
        creator.create(
            CLEANUP_APPLIED,
            CleanupAppliedPayload(
                cleanup_id=command.cleanup_id,
                file_state_record_id=record_id,
                superseding_record_id=record.record_id,
                old_snapshot_id=requested.snapshot_id,
                new_snapshot_id=record.snapshot_id,
                paths=tuple(requested.paths),
                authority=requested.authority,
                reason=command.reason if command.reason is not None else requested.reason,
                execution_id=requested.execution_id,
                deleted_snapshot_ref=command.deleted_snapshot_ref,
                resolved_count=len(requested.paths),
            ),
        ),
        creator.create(OUTPUT_RECORD_ACCEPTED, OutputRecordAcceptedPayload(record=emitted_record)),
        creator.create(FILE_STATE_ACCEPTED, emitted_record),
    ]


def _retained_path(record: StrictFileStateRecord, paths: set[str]) -> str | None:
    entries = (
        *record.tracked,
        *record.untracked,
        *record.ignored,
        *record.external,
        *record.classifications,
        *record.residue,
        *record.rejected_paths,
    )
    return next((entry.path for entry in entries if entry.path in paths), None)


def _rejected(creator: TypedEventCreator, command_type: str, reason: str) -> HydratedEvent:
    return creator.create(
        COMMAND_REJECTED,
        CommandRejectedPayload(command_type=command_type, reason=reason),
    )


RECORD_GATEKEEPER_VERDICTS = CommandSpecification(
    "record_gatekeeper_verdicts",
    RecordGatekeeperVerdictsCommand,
    handle_record_gatekeeper_verdicts,
)
RECORD_CLEANUP_APPLIED = CommandSpecification(
    "record_cleanup_applied",
    RecordCleanupAppliedCommand,
    handle_record_cleanup_applied,
)
COMMAND_SPECIFICATIONS = (RECORD_GATEKEEPER_VERDICTS, RECORD_CLEANUP_APPLIED)
