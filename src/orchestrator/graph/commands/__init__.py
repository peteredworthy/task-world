"""Pure command applier for execution graph fixtures."""

from typing import Any

from pydantic import ValidationError

from orchestrator.graph._commands import (
    Clock,
    EventEnvelope,
    GraphProjection,
    IdGenerator,
    NONTERMINAL_RUN_STATES,
    RUN_LIFECYCLE_TRANSITIONS,
    TERMINAL_RUN_STATES,
    command_rejected,
    reliable_plan_proposal_rejection_limit,
    authoritative_batch_verification_report_ids,
    event_factory,
    serialize_event_payload,
)
from orchestrator.graph._error_rendering import safe_exception_reason, safe_validation_diagnostics
from orchestrator.graph.command_models import (
    AcceptRunCommand,
    AcknowledgeStartCommand,
    AgentDiedCommand,
    CancelCommand,
    CommandSpec,
    CompleteCommand,
    EvaluateFinalGateCommand,
    EvaluateJoinCommand,
    FailCommand,
    GraphCommandContext,
    PatchCommandContext,
    PauseCommand,
    RaiseAppealCommand,
    ReconcileCommand,
    RecordCleanupAppliedCommand,
    RecordManagedSnapshotCleanupAppliedCommand,
    RecordDecisionCommand,
    RecordGatekeeperVerdictsCommand,
    RecordHeartbeatCommand,
    RecordNodeUsageCommand,
    RecordRequirementRevisionCommand,
    RecordSupportEvidenceCommand,
    ResumeCommand,
    ScheduleTickCommand,
    SeedCompiledEventsCommand,
    StartCommand,
    SubmitCallbackCommand,
    SubmitPatchCommand,
    submit_patch_operation_fingerprint,
    submit_patch_operation_key,
    RecordRunnerBaselineCommand,
    StageRunnerSubmissionCommand,
    WitnessRunnerCompletionCommand,
    FinalizeRunnerExecutionCommand,
    RecordDecisionAnswerRejectionCommand,
    CompleteRunnerRecoveryCommand,
    CompleteValidationEnvironmentBlockageResolutionCommand,
    RequestRunnerRecoveryCommand,
    ResolveValidationEnvironmentBlockageCommand,
)
from orchestrator.graph.commands.callbacks import (
    handle_acknowledge_start,
    handle_raise_appeal,
    handle_record_cleanup_applied,
    handle_record_decision,
    handle_record_gatekeeper_verdicts,
    handle_record_node_usage,
    handle_record_requirement_revision,
    handle_record_support_evidence,
    handle_submit_callback,
)
from orchestrator.graph.commands.boundary import (
    handle_complete_runner_recovery,
    handle_complete_validation_environment_blockage_resolution,
    handle_finalize_runner_execution,
    handle_record_decision_answer_rejection,
    handle_record_runner_baseline,
    handle_record_managed_snapshot_cleanup_applied,
    handle_request_runner_recovery,
    handle_resolve_validation_environment_blockage,
    handle_stage_runner_submission,
    handle_witness_runner_completion,
)
from orchestrator.graph.commands.lifecycle import (
    handle_accept_run,
    handle_cancel,
    handle_complete,
    handle_fail,
    handle_pause,
    handle_record_heartbeat,
    handle_resume,
    handle_start,
)
from orchestrator.graph.commands.patches import handle_submit_patch
from orchestrator.graph.commands.records import (
    handle_agent_died,
    handle_evaluate_final_gate,
    handle_evaluate_join,
)
from orchestrator.graph.commands.schedule import (
    handle_reconcile,
    handle_schedule_tick,
    handle_seed_compiled_events,
)


COMMAND_SPECS: dict[str, CommandSpec] = {
    "accept_run": CommandSpec(AcceptRunCommand, handle_accept_run),
    "start": CommandSpec(StartCommand, handle_start),
    "pause": CommandSpec(PauseCommand, handle_pause),
    "resume": CommandSpec(ResumeCommand, handle_resume),
    "cancel": CommandSpec(CancelCommand, handle_cancel),
    "complete": CommandSpec(CompleteCommand, handle_complete),
    "fail": CommandSpec(FailCommand, handle_fail),
    "record_heartbeat": CommandSpec(RecordHeartbeatCommand, handle_record_heartbeat),
    "seed_compiled_events": CommandSpec(SeedCompiledEventsCommand, handle_seed_compiled_events),
    "schedule_tick": CommandSpec(ScheduleTickCommand, handle_schedule_tick),
    "reconcile": CommandSpec(ReconcileCommand, handle_reconcile),
    "submit_callback": CommandSpec(SubmitCallbackCommand, handle_submit_callback),
    "record_runner_baseline": CommandSpec(
        RecordRunnerBaselineCommand, handle_record_runner_baseline
    ),
    "record_decision_answer_rejection": CommandSpec(
        RecordDecisionAnswerRejectionCommand, handle_record_decision_answer_rejection
    ),
    "stage_runner_submission": CommandSpec(
        StageRunnerSubmissionCommand, handle_stage_runner_submission
    ),
    "witness_runner_completion": CommandSpec(
        WitnessRunnerCompletionCommand, handle_witness_runner_completion
    ),
    "finalize_runner_execution": CommandSpec(
        FinalizeRunnerExecutionCommand, handle_finalize_runner_execution
    ),
    "request_runner_recovery": CommandSpec(
        RequestRunnerRecoveryCommand, handle_request_runner_recovery
    ),
    "complete_runner_recovery": CommandSpec(
        CompleteRunnerRecoveryCommand, handle_complete_runner_recovery
    ),
    "resolve_validation_environment_blockage": CommandSpec(
        ResolveValidationEnvironmentBlockageCommand,
        handle_resolve_validation_environment_blockage,
    ),
    "complete_validation_environment_blockage_resolution": CommandSpec(
        CompleteValidationEnvironmentBlockageResolutionCommand,
        handle_complete_validation_environment_blockage_resolution,
    ),
    "submit_patch": CommandSpec(SubmitPatchCommand, handle_submit_patch),
    "acknowledge_start": CommandSpec(AcknowledgeStartCommand, handle_acknowledge_start),
    "agent_died": CommandSpec(AgentDiedCommand, handle_agent_died),
    "raise_appeal": CommandSpec(RaiseAppealCommand, handle_raise_appeal),
    "record_decision": CommandSpec(RecordDecisionCommand, handle_record_decision),
    "record_gatekeeper_verdicts": CommandSpec(
        RecordGatekeeperVerdictsCommand, handle_record_gatekeeper_verdicts
    ),
    "record_node_usage": CommandSpec(RecordNodeUsageCommand, handle_record_node_usage),
    "record_requirement_revision": CommandSpec(
        RecordRequirementRevisionCommand, handle_record_requirement_revision
    ),
    "record_support_evidence": CommandSpec(
        RecordSupportEvidenceCommand, handle_record_support_evidence
    ),
    "evaluate_join": CommandSpec(EvaluateJoinCommand, handle_evaluate_join),
    "evaluate_final_gate": CommandSpec(EvaluateFinalGateCommand, handle_evaluate_final_gate),
    "record_cleanup_applied": CommandSpec(
        RecordCleanupAppliedCommand, handle_record_cleanup_applied
    ),
    "record_managed_snapshot_cleanup_applied": CommandSpec(
        RecordManagedSnapshotCleanupAppliedCommand, handle_record_managed_snapshot_cleanup_applied
    ),
}


def apply_command(
    projection: GraphProjection,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    context: GraphCommandContext,
    clock: Clock,
    id_gen: IdGenerator,
) -> list[EventEnvelope]:
    """Apply a pure graph command and return events a controller would append."""

    make_event = event_factory(context.run_id, command_type, clock, id_gen)
    spec = COMMAND_SPECS.get(command_type)
    if spec is None:
        return [
            command_rejected(
                make_event,
                command_type,
                f"unknown command: {command_type}",
            )
        ]
    if command_type == "submit_patch" and not isinstance(context, PatchCommandContext):
        return [
            command_rejected(
                make_event,
                command_type,
                "invalid command context: submit_patch requires PatchCommandContext",
            )
        ]
    if command_type == "submit_patch" and isinstance(context, PatchCommandContext):
        rejection_limit = reliable_plan_proposal_rejection_limit(projection, context)
        if rejection_limit is not None and context.reliable_plan_rejection_count >= rejection_limit:
            raw_patch_id = payload.get("patch_id")
            raw_base_position = payload.get("base_graph_position")
            rejection_payload: dict[str, Any] = {
                "command_type": "submit_patch",
                "reason": "proposal_rejection_limit_exhausted",
                "actor_role": context.actor_role,
                "proposed_by_node_id": context.proposed_by_node_id,
                "budget": rejection_limit,
                "count": context.reliable_plan_rejection_count,
            }
            if isinstance(raw_patch_id, str):
                rejection_payload["patch_id"] = raw_patch_id
            if isinstance(raw_base_position, int) and not isinstance(raw_base_position, bool):
                rejection_payload["base_graph_position"] = raw_base_position
            return [make_event("command_rejected", rejection_payload)]
    try:
        validated = spec.payload_model.model_validate(payload)
    except ValidationError as exc:
        rejection_payload: dict[str, Any] = {
            "command_type": command_type,
            "reason": safe_exception_reason(
                exc,
                code="invalid_command_payload",
                message="invalid command payload",
            ),
            "diagnostics": safe_validation_diagnostics(exc),
        }
        if command_type == "submit_patch" and isinstance(context, PatchCommandContext):
            rejection_payload.update(
                {
                    "actor_role": context.actor_role,
                    "proposed_by_node_id": context.proposed_by_node_id,
                }
            )
            raw_patch_id = payload.get("patch_id")
            if isinstance(raw_patch_id, str):
                rejection_payload["patch_id"] = raw_patch_id
        return [make_event("command_rejected", rejection_payload)]
    return spec.handler(
        projection,
        events,
        command_type,
        validated,
        context,
        make_event,
        clock,
        id_gen,
    )


__all__ = [
    "Clock",
    "EventEnvelope",
    "GraphProjection",
    "IdGenerator",
    "RUN_LIFECYCLE_TRANSITIONS",
    "TERMINAL_RUN_STATES",
    "NONTERMINAL_RUN_STATES",
    "apply_command",
    "authoritative_batch_verification_report_ids",
    "COMMAND_SPECS",
    "serialize_event_payload",
    "submit_patch_operation_fingerprint",
    "submit_patch_operation_key",
]
