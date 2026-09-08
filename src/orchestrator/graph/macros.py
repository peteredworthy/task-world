"""Planner-facing graph macro expansion.

Macros keep planner tool calls focused on typed graph intent while preserving
low-level patch ops as the kernel's internal representation.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from orchestrator.graph._error_rendering import safe_exception_reason
from orchestrator.graph.models import (
    CheckResultRecord,
    GapClassificationRecord,
    RequirementRecord,
    SemanticArtifactRecord,
    VerificationReportRecord,
)
from orchestrator.graph.projection_models import GraphProjection
from orchestrator.graph.projection_queries import (
    effective_active_node_ids_view,
    input_bindings_view,
    leases_view,
    node_kinds_view,
    node_payload_view,
    output_record_payloads_view,
    semantic_schema_declarations_view,
)


MACRO_FIELD = "macro_invocations"


class MacroInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    macro: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


class MacroArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateWorkRegionArgs(MacroArgs):
    region_id: str = Field(min_length=1)
    candidate_id: str | None = None
    worker_id: str | None = None
    verifier_id: str | None = None
    worker_role: str | None = None
    attempt_number: int | None = Field(default=None, gt=0)
    candidate_edge_id: str | None = None
    classified_gap_source_node_id: str | None = None
    gap_planner_node_id: str | None = None
    classified_gap_edge_id: str | None = None
    rubric: list[str] | None = None
    checks: list[dict[str, Any]] | None = None
    objective: str | None = None
    access_mode: Literal["read_only", "write"] | None = None
    acceptance: list[str] | None = None
    access_mode_override_justification: str | None = None
    failed_verification_source_node_id: str | None = None
    failed_check_source_node_ids: list[str] | None = None
    failed_verification_record_id: str | None = None
    failed_check_record_ids: list[str] | None = None
    classified_gap_record_id: str | None = None
    declared_batch_id: str | None = None
    planning_horizon: int | None = Field(default=None, gt=0)
    base_snapshot_selection: (
        Literal["run_baseline", "latest_accepted", "accepted_region", "rejected_candidate"] | None
    ) = None
    base_snapshot_region_id: str | None = None
    base_snapshot_candidate_id: str | None = None


class CreateCorrectiveRegionArgs(CreateWorkRegionArgs):
    @model_validator(mode="after")
    def exact_failure_evidence_is_required(self) -> "CreateCorrectiveRegionArgs":
        if self.failed_verification_source_node_id is None:
            raise ValueError("corrective region requires failed_verification_source_node_id")
        if not self.failed_check_source_node_ids:
            raise ValueError("corrective region requires failed_check_source_node_ids")
        if self.failed_verification_record_id is None:
            raise ValueError("corrective region requires failed_verification_record_id")
        if not self.failed_check_record_ids:
            raise ValueError("corrective region requires failed_check_record_ids")
        if len(self.failed_check_record_ids) != len(self.failed_check_source_node_ids):
            raise ValueError("corrective region requires one record ID per failed check source")
        if self.classified_gap_record_id is None:
            raise ValueError("corrective region requires classified_gap_record_id")
        if self.base_snapshot_selection not in {"accepted_region", "rejected_candidate"}:
            raise ValueError(
                "corrective region requires accepted_region or rejected_candidate snapshot selection"
            )
        if self.base_snapshot_selection == "accepted_region" and not self.base_snapshot_region_id:
            raise ValueError("accepted correction requires base_snapshot_region_id")
        if (
            self.base_snapshot_selection == "rejected_candidate"
            and not self.base_snapshot_candidate_id
        ):
            raise ValueError("rejected correction requires base_snapshot_candidate_id")
        return self


class AttachVerifierArgs(MacroArgs):
    region_id: str = Field(min_length=1)
    candidate_source_node_id: str | None = None
    worker_id: str | None = None
    verifier_id: str | None = None
    edge_id: str | None = None
    rubric: list[str] | None = None


class AttachCheckArgs(MacroArgs):
    region_id: str = Field(min_length=1)
    check_id: str | None = None
    node_id: str | None = None
    evidence_source_node_id: str | None = None
    verifier_id: str | None = None
    edge_id: str | None = None
    role: str | None = None
    evidence_source_port: str | None = None
    command_definition: dict[str, Any] | None = None
    command_binding: str | None = None
    hidden_oracle_command: str | None = None


class CreateGapPlannerArgs(MacroArgs):
    region_id: str = Field(min_length=1)
    node_id: str | None = None
    evidence_source_node_id: str | None = None
    verifier_id: str | None = None
    edge_id: str | None = None
    evidence_source_port: str | None = None


class CreateJoinSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    port: str | None = None


class CreateJoinArgs(MacroArgs):
    join_id: str = Field(min_length=1)
    sources: list[CreateJoinSource] | None = None
    source_ids: list[str] | None = None
    role: str | None = None


class RequestGateArgs(MacroArgs):
    gate_id: str | None = None
    node_id: str | None = None
    kind: Literal["human_gate", "authority_request"] | None = None
    reason: str | None = None
    decision_type: str | None = None
    options: list[str] | None = None
    default_option: str | None = None
    requested_authority: list[str] | None = None
    target_node_id: str | None = None
    target_region_id: str | None = None
    expires_at: str | None = None


class RetireOrSupersedeArgs(MacroArgs):
    target_id: str = Field(min_length=1)
    action: str | None = None
    replacement_ops: list[dict[str, Any]] | None = None


class SemanticStageArgs(MacroArgs):
    region_id: str = Field(min_length=1)
    semantic_schema_id: str = Field(min_length=1)
    semantic_schema_version: int = Field(ge=1)
    objective: str = Field(min_length=1)
    acceptance: list[str] = Field(min_length=1)
    requirement_source_node_ids: list[str] = Field(default_factory=list)


class CreateDiscoveryRegionArgs(SemanticStageArgs):
    worker_id: str | None = None


class CreatePlanVerificationArgs(SemanticStageArgs):
    artifact_source_node_id: str = Field(min_length=1)
    verifier_id: str | None = None
    rubric: list[str] = Field(min_length=1)


class CreateSuccessorPlannerArgs(MacroArgs):
    region_id: str = Field(min_length=1)
    node_id: str | None = None
    evidence_source_node_id: str = Field(min_length=1)
    evidence_source_port: Literal["semantic_artifact", "verification_report"]
    planning_horizon: int = Field(ge=1)
    semantic_schema_id: str | None = None
    semantic_schema_version: int | None = Field(default=None, ge=1)


class CreateEffectfulBatchArgs(SemanticStageArgs):
    batch_id: str = Field(min_length=1)
    plan_source_node_id: str = Field(min_length=1)
    plan_verification_source_node_id: str = Field(min_length=1)
    worker_id: str | None = None
    verifier_id: str | None = None
    checks: list[dict[str, Any]] = Field(min_length=1)
    rubric: list[str] = Field(min_length=1)
    planning_horizon: int = Field(ge=1)
    accepted_plan_amendment_record_id: str | None = None


class ReliablePlanCheckDecision(BaseModel):
    """A substantive check choice without graph execution identities."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    command_binding: Literal["dynamic_feature_hidden_oracle"] | None = None
    command_definition: dict[str, Any] | None = None

    @model_validator(mode="after")
    def command_is_declared(self) -> "ReliablePlanCheckDecision":
        if (self.command_binding is None) == (self.command_definition is None):
            raise ValueError("check requires exactly one command binding or command definition")
        return self


class ConstructReliablePlanRegionArgs(MacroArgs):
    """Semantic decisions used by the controller to build one reliable-plan region."""

    operation_key: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    scope: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    requirement_ids: list[str] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(min_length=1)
    checks: list[ReliablePlanCheckDecision]
    rubric: list[str] = Field(min_length=1)


_MACRO_SPECS = {
    "create_work_region": CreateWorkRegionArgs,
    "create_corrective_region": CreateCorrectiveRegionArgs,
    "attach_verifier": AttachVerifierArgs,
    "attach_check": AttachCheckArgs,
    "create_gap_planner": CreateGapPlannerArgs,
    "create_join": CreateJoinArgs,
    "request_gate": RequestGateArgs,
    "retire_or_supersede": RetireOrSupersedeArgs,
    "create_discovery_region": CreateDiscoveryRegionArgs,
    "create_plan_verification": CreatePlanVerificationArgs,
    "create_successor_planner": CreateSuccessorPlannerArgs,
    "create_effectful_batch": CreateEffectfulBatchArgs,
    "construct_reliable_plan_region": ConstructReliablePlanRegionArgs,
}

RELIABLE_PLAN_MAX_ATTEMPTS = 3


def expand_patch_macros(
    ops: list[dict[str, Any]],
    invocations: list[MacroInvocation],
    proposed_by_node_id: str,
    *,
    projection: GraphProjection | None = None,
    patch_id: str | None = None,
) -> list[dict[str, Any]]:
    """Expand validated macro invocations into patch operations."""

    macro_ops: list[dict[str, Any]] = []
    for invocation in invocations:
        invocation = _validate_invocation(invocation)
        macro_ops.extend(
            _expand_macro(
                invocation.macro,
                invocation.args,
                proposed_by_node_id,
                projection=projection,
                patch_id=patch_id,
            )
        )
    macro_ops.extend(
        _controller_reliable_plan_continuation_ops(
            [*macro_ops, *ops],
            projection=projection,
            proposed_by_node_id=proposed_by_node_id,
        )
    )
    # A raw operator edge may intentionally reconnect a replacement created by
    # a macro in the same atomic patch.  Emit every macro-created node before
    # raw operations so reducer relationship checks never observe a transient
    # dangling endpoint; retain all other user and macro ordering.
    macro_nodes = [operation for operation in macro_ops if operation.get("op") == "create_node"]
    macro_remainder = [operation for operation in macro_ops if operation.get("op") != "create_node"]
    return [*macro_nodes, *ops, *macro_remainder]


def _controller_reliable_plan_continuation_ops(
    operations: list[dict[str, Any]],
    *,
    projection: GraphProjection | None,
    proposed_by_node_id: str,
) -> list[dict[str, Any]]:
    """Complete mandatory failure branches for semantic, legacy-macro, and raw patches."""
    if projection is None:
        return []
    parent = node_payload_view(projection, proposed_by_node_id) or {}
    if not isinstance(parent.get("reliable_plan_skeleton_id"), str):
        return []
    created = {
        cast(dict[str, Any], operation["node"]).get("node_id"): cast(
            dict[str, Any], operation["node"]
        )
        for operation in operations
        if operation.get("op") == "create_node" and isinstance(operation.get("node"), dict)
    }
    final_nodes = [
        node
        for node in created.values()
        if node.get("semantic_stage") in {"final_acceptance", "final_audit", "final_gate"}
        or node.get("kind") == "final_gate"
    ]
    if final_nodes:
        accepted_plans = [
            record
            for record in output_record_payloads_view(projection).values()
            if isinstance(record, SemanticArtifactRecord)
            and record.value.authority_status == "accepted"
            and record.value.semantic_role == "implementation_plan"
        ]
        if len(accepted_plans) == 1:
            declared_batch_ids = _declared_batch_ids_from_plan(accepted_plans[0])
            for node in final_nodes:
                node.setdefault("declared_batch_ids", declared_batch_ids)
    existing_failure_sources: set[Any] = set()
    for operation in operations:
        raw_selector = operation.get("accepted_record_selector")
        if operation.get("op") != "create_edge" or not isinstance(raw_selector, dict):
            continue
        selector = cast(dict[str, Any], raw_selector)
        raw_options = selector.get("selectors", [selector])
        options = cast(list[Any], raw_options) if isinstance(raw_options, list) else []
        failure_gated = False
        for raw_option in options:
            if not isinstance(raw_option, dict):
                continue
            option = cast(dict[str, Any], raw_option)
            if option.get("outcome") == "failed" or option.get("status") == "failed":
                failure_gated = True
                break
        if failure_gated and created.get(operation.get("to_node_id"), {}).get("role") == (
            "gap_planner"
        ):
            existing_failure_sources.add(operation.get("from_node_id"))
    required_sources: list[tuple[str, str, str]] = []
    plan_verifiers = [
        node_id
        for node_id, node in created.items()
        if isinstance(node_id, str) and node.get("semantic_stage") == "plan_verification"
    ]
    required_sources.extend((node_id, "verification_report", "plan") for node_id in plan_verifiers)
    final_acceptance = [
        node_id
        for node_id, node in created.items()
        if isinstance(node_id, str) and node.get("semantic_stage") == "final_acceptance"
    ]
    final_audits = [
        node_id
        for node_id, node in created.items()
        if isinstance(node_id, str) and node.get("semantic_stage") == "final_audit"
    ]
    batch_verifiers = [
        node_id
        for node_id, node in created.items()
        if isinstance(node_id, str)
        and node.get("kind") == "verifier"
        and node.get("semantic_stage") in {"effectful_batch", "corrective_work"}
    ]
    if final_acceptance or final_audits:
        required_sources.extend(
            (node_id, "verification_report", "batch") for node_id in batch_verifiers
        )
        required_sources.extend(
            (node_id, "check_result", "acceptance") for node_id in final_acceptance
        )
        required_sources.extend(
            (node_id, "verification_report", "audit") for node_id in final_audits
        )
    else:
        required_sources.extend(
            (node_id, "verification_report", "batch") for node_id in batch_verifiers
        )
    additions: list[dict[str, Any]] = []
    for source_id, source_port, label in required_sources:
        if source_id in existing_failure_sources:
            continue
        additions.extend(
            _create_gap_planner(
                {
                    "region_id": f"recovery-{label}-{source_id}",
                    "node_id": f"planner-gap-{label}-{source_id}",
                    "evidence_source_node_id": source_id,
                    "evidence_source_port": source_port,
                }
            )
        )
    return additions


def _expand_macro(
    macro_name: str,
    args: dict[str, Any],
    proposed_by_node_id: str,
    *,
    projection: GraphProjection | None,
    patch_id: str | None,
) -> list[dict[str, Any]]:
    if macro_name == "create_work_region":
        return _create_work_region(args, corrective=False, proposed_by_node_id=proposed_by_node_id)
    if macro_name == "create_corrective_region":
        return _create_work_region(args, corrective=True, proposed_by_node_id=proposed_by_node_id)
    if macro_name == "attach_verifier":
        return _attach_verifier(args)
    if macro_name == "attach_check":
        return _attach_check(args)
    if macro_name == "create_gap_planner":
        return _create_gap_planner(args)
    if macro_name == "create_join":
        return _create_join(args)
    if macro_name == "request_gate":
        return _request_gate(args)
    if macro_name == "retire_or_supersede":
        return _retire_or_supersede(args)
    if macro_name == "create_discovery_region":
        return _create_discovery_region(args)
    if macro_name == "create_plan_verification":
        return _create_plan_verification(args)
    if macro_name == "create_successor_planner":
        return _create_successor_planner(args)
    if macro_name == "create_effectful_batch":
        return _create_effectful_batch(args)
    if macro_name == "construct_reliable_plan_region":
        if projection is None or patch_id is None:
            raise ValueError(
                "construct_reliable_plan_region requires controller projection and patch identity"
            )
        return _construct_reliable_plan_region(
            args,
            projection=projection,
            proposed_by_node_id=proposed_by_node_id,
            patch_id=patch_id,
        )
    msg = f"unknown graph macro: {macro_name}"
    raise ValueError(msg)


def _validate_invocation(invocation: MacroInvocation) -> MacroInvocation:
    args_model = _MACRO_SPECS.get(invocation.macro)
    if args_model is None:
        msg = f"unknown graph macro: {invocation.macro}"
        raise ValueError(msg)
    try:
        typed_args = args_model.model_validate(invocation.args)
    except ValidationError as exc:
        raise ValueError(
            safe_exception_reason(
                exc,
                code="invalid_macro_arguments",
                message=f"{invocation.macro} args invalid",
            )
        ) from exc
    return invocation.model_copy(update={"args": typed_args.model_dump(exclude_none=True)})


def _create_work_region(
    args: dict[str, Any],
    *,
    corrective: bool,
    proposed_by_node_id: str,
) -> list[dict[str, Any]]:
    region_id = _required_str(args, "region_id")
    candidate_id = _str(args, "candidate_id") or (
        f"corrective-candidate-{region_id}" if corrective else f"candidate-{region_id}"
    )
    worker_id = _str(args, "worker_id") or (
        f"worker-corrective-{region_id}" if corrective else f"worker-{region_id}"
    )
    verifier_id = _str(args, "verifier_id") or (
        f"verifier-corrective-{region_id}" if corrective else f"verifier-{region_id}"
    )
    worker_role = _str(args, "worker_role") or ("fixer" if corrective else "builder")
    attempt_number = _positive_int(args.get("attempt_number"), 2 if corrective else 1)
    ops = [
        _worker_node(
            worker_id,
            region_id,
            candidate_id,
            role=worker_role,
            attempt_number=attempt_number,
            objective=_str(args, "objective"),
            access_mode=args.get("access_mode"),
            acceptance=args.get("acceptance"),
            access_mode_override_justification=_str(args, "access_mode_override_justification"),
        ),
        _verifier_node(
            verifier_id,
            region_id,
            rubric=_rubric(args),
        ),
        _edge(
            _str(args, "candidate_edge_id") or f"edge-{worker_id}-candidate-to-{verifier_id}",
            worker_id,
            "candidate",
            verifier_id,
            "candidate_under_test",
            ("candidate",),
        ),
    ]
    worker_payload = cast(dict[str, Any], ops[0]["node"])
    worker_payload["base_snapshot_selection"] = (
        args["base_snapshot_selection"]
        if corrective
        else args.get("base_snapshot_selection", "run_baseline")
    )
    verifier_payload = cast(dict[str, Any], ops[1]["node"])
    verifier_payload["base_snapshot_selection"] = "candidate_under_test"
    if corrective:
        corrective_node = worker_payload
        corrective_node.update(
            {
                "semantic_stage": "corrective_work",
                "failed_candidate_id": args.get("base_snapshot_candidate_id"),
                "failed_verification_record_id": args["failed_verification_record_id"],
                "failed_check_record_ids": list(args["failed_check_record_ids"]),
                "classified_gap_record_id": args["classified_gap_record_id"],
                "base_snapshot_region_id": args.get("base_snapshot_region_id"),
                "base_snapshot_candidate_id": args.get("base_snapshot_candidate_id"),
                "declared_batch_id": args.get("declared_batch_id"),
                "planning_horizon": args.get("planning_horizon"),
            }
        )
        verifier_payload.update(
            {
                "semantic_stage": "corrective_work",
                "failed_candidate_id": args.get("base_snapshot_candidate_id"),
                "declared_batch_id": args.get("declared_batch_id"),
                "planning_horizon": args.get("planning_horizon"),
            }
        )
        gap_source = (
            _str(args, "classified_gap_source_node_id")
            or _str(args, "gap_planner_node_id")
            or proposed_by_node_id
        )
        ops.insert(
            2,
            _edge(
                _str(args, "classified_gap_edge_id")
                or f"edge-{gap_source}-classified-gap-to-{worker_id}",
                gap_source,
                "classified_gap",
                worker_id,
                "classified_gap",
                ("gap_analysis",),
                selector={
                    "record_id": args["classified_gap_record_id"],
                    "record_type": "gap_classification",
                    "schema": "GapClassification",
                    "classification": "corrective_work_required",
                },
                prompt_hydration_policy="structured_json",
            ),
        )
        failed_verifier = _str(args, "failed_verification_source_node_id")
        if failed_verifier is not None:
            ops.insert(
                3,
                _edge(
                    f"edge-{failed_verifier}-failed-verification-to-{worker_id}",
                    failed_verifier,
                    "verification_report",
                    worker_id,
                    "verification_report",
                    ("verification_report",),
                    selector={
                        "record_id": args["failed_verification_record_id"],
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "failed",
                    },
                    prompt_hydration_policy="structured_json",
                ),
            )
        check_sources = cast(list[str], args.get("failed_check_source_node_ids") or [])
        check_record_ids = cast(list[str], args.get("failed_check_record_ids") or [])
        for index, (check_source, check_record_id) in enumerate(
            zip(check_sources, check_record_ids, strict=True), start=1
        ):
            ops.insert(
                4,
                _edge(
                    f"edge-{check_source}-failed-check-to-{worker_id}-{index}",
                    check_source,
                    "check_result",
                    worker_id,
                    "check_result",
                    ("check_result",),
                    selector={
                        "record_id": check_record_id,
                        "record_type": "check_result",
                        "schema": "CheckResult",
                        "status": "failed",
                    },
                    prompt_hydration_policy="structured_json",
                ),
            )
    for index, check_args in enumerate(_checks(args), start=1):
        if not corrective:
            normalized = {
                "region_id": region_id,
                "evidence_source_node_id": verifier_id,
                **check_args,
            }
            ops.extend(_attach_check(normalized))
            continue
        check_id = _str(check_args, "check_id") or f"check-{region_id}-{index}"
        check_node: dict[str, Any] = {
            "node_id": check_id,
            "kind": "check",
            "role": "batch_check",
            "state": "planned",
            "task_region_id": region_id,
            "semantic_stage": "corrective_work",
            "declared_batch_id": args.get("declared_batch_id"),
            "planning_horizon": args.get("planning_horizon"),
            "base_snapshot_selection": "candidate_under_test",
        }
        _copy_command(check_args, check_node)
        ops.extend(
            [
                {"op": "create_node", "node": check_node},
                _edge(
                    f"edge-{worker_id}-candidate-to-{check_id}",
                    worker_id,
                    "candidate",
                    check_id,
                    "candidate_under_test",
                    ("candidate",),
                ),
                _edge(
                    f"edge-{check_id}-result-to-{verifier_id}",
                    check_id,
                    "check_result",
                    verifier_id,
                    f"check_result_{index}",
                    ("check_result",),
                    selector={
                        "record_type": "any_of",
                        "selectors": [
                            {
                                "record_type": "check_result",
                                "schema": "CheckResult",
                                "status": "passed",
                            },
                            {
                                "record_type": "check_result",
                                "schema": "CheckResult",
                                "status": "failed",
                            },
                        ],
                    },
                ),
            ]
        )
    return ops


def _attach_verifier(args: dict[str, Any]) -> list[dict[str, Any]]:
    region_id = _required_str(args, "region_id")
    candidate_source = (
        _str(args, "candidate_source_node_id") or _str(args, "worker_id") or f"worker-{region_id}"
    )
    verifier_id = _str(args, "verifier_id") or f"verifier-{region_id}"
    return [
        _verifier_node(verifier_id, region_id, rubric=_rubric(args)),
        _edge(
            _str(args, "edge_id") or f"edge-{candidate_source}-candidate-to-{verifier_id}",
            candidate_source,
            "candidate",
            verifier_id,
            "candidate_under_test",
            ("candidate",),
        ),
    ]


def _attach_check(args: dict[str, Any]) -> list[dict[str, Any]]:
    region_id = _required_str(args, "region_id")
    check_id = _str(args, "check_id") or _str(args, "node_id") or f"check-{region_id}"
    evidence_source = (
        _str(args, "evidence_source_node_id")
        or _str(args, "verifier_id")
        or f"verifier-{region_id}"
    )
    node = {
        "node_id": check_id,
        "kind": "check",
        "role": _str(args, "role") or "invariant_gate",
        "state": "planned",
        "task_region_id": region_id,
    }
    _copy_command(args, node)
    return [
        {"op": "create_node", "node": node},
        _edge(
            _str(args, "edge_id") or f"edge-{evidence_source}-verification-to-{check_id}",
            evidence_source,
            _str(args, "evidence_source_port") or "verification_report",
            check_id,
            "verification_evidence",
            ("verification_report", "check_result"),
            selector={
                "record_type": "any_of",
                "selectors": [
                    {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "passed",
                    },
                    {
                        "record_type": "check_result",
                        "schema": "CheckResult",
                        "status": "passed",
                    },
                ],
            },
        ),
    ]


def _create_gap_planner(args: dict[str, Any]) -> list[dict[str, Any]]:
    region_id = _required_str(args, "region_id")
    node_id = _str(args, "node_id") or f"planner-gap-{region_id}"
    evidence_source = (
        _str(args, "evidence_source_node_id")
        or _str(args, "verifier_id")
        or f"verifier-{region_id}"
    )
    return [
        {
            "op": "create_node",
            "node": {
                "node_id": node_id,
                "kind": "planner",
                "role": "gap_planner",
                "state": "planned",
                "task_region_id": region_id,
            },
        },
        _edge(
            _str(args, "edge_id") or f"edge-{evidence_source}-verification-to-{node_id}",
            evidence_source,
            _str(args, "evidence_source_port") or "verification_report",
            node_id,
            "verification_evidence",
            ("verification_report", "check_result"),
            selector={
                "record_type": "any_of",
                "selectors": [
                    {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "failed",
                    },
                    {
                        "record_type": "check_result",
                        "schema": "CheckResult",
                        "status": "failed",
                    },
                ],
            },
        ),
    ]


def _create_join(args: dict[str, Any]) -> list[dict[str, Any]]:
    join_id = _required_str(args, "join_id")
    raw_sources = args.get("sources", args.get("source_ids", []))
    if not isinstance(raw_sources, list) or not raw_sources:
        msg = "create_join requires sources or source_ids"
        raise ValueError(msg)
    ops = [
        {
            "op": "create_node",
            "node": {
                "node_id": join_id,
                "kind": "join",
                "role": _str(args, "role") or "join",
                "state": "planned",
            },
        }
    ]
    for index, source in enumerate(cast(list[Any], raw_sources), start=1):
        if isinstance(source, dict):
            source_node_id = _required_str(cast(dict[str, Any], source), "node_id")
            source_port = _str(cast(dict[str, Any], source), "port") or "candidate"
        elif isinstance(source, str):
            source_node_id = source
            source_port = "candidate"
        else:
            msg = "create_join sources must be strings or objects"
            raise ValueError(msg)
        ops.append(
            _edge(
                f"edge-{source_node_id}-{source_port}-to-{join_id}-{index}",
                source_node_id,
                source_port,
                join_id,
                f"source_record_{index}",
                ("candidate", "verification_report", "check_result", "file_state"),
            )
        )
    return ops


def _request_gate(args: dict[str, Any]) -> list[dict[str, Any]]:
    gate_id = _str(args, "gate_id") or _str(args, "node_id") or "human-gate"
    kind = _str(args, "kind") or "human_gate"
    reason = _str(args, "reason") or "Manual decision required before graph can continue."
    node: dict[str, Any] = {
        "node_id": gate_id,
        "kind": kind,
        "state": "planned",
        "reason": reason,
    }
    if kind == "human_gate":
        options = args.get("options")
        if options is None:
            options = ["approve", "reject"]
        request: dict[str, Any] = {
            "decision_type": _str(args, "decision_type") or "approval",
            "options": options,
            "consequence_summary": reason,
        }
        default_option = _str(args, "default_option")
        if default_option is not None:
            request["default_option"] = default_option
        node["decision_request"] = request
    elif kind == "authority_request":
        requested_authority = args.get("requested_authority")
        if not requested_authority:
            msg = "request_gate authority_request requires requested_authority"
            raise ValueError(msg)
        request = {
            "requested_authority": requested_authority,
            "reason": reason,
        }
        target_node_id = _str(args, "target_node_id")
        if target_node_id is not None:
            request["target_node_id"] = target_node_id
        target_region_id = _str(args, "target_region_id")
        if target_region_id is not None:
            request["target_region_id"] = target_region_id
        expires_at = _str(args, "expires_at")
        if expires_at is not None:
            request["expires_at"] = expires_at
        node["authority_request_record"] = request
    return [{"op": "create_node", "node": node}]


def _retire_or_supersede(args: dict[str, Any]) -> list[dict[str, Any]]:
    target_id = _required_str(args, "target_id")
    action = _str(args, "action") or "retire"
    if action == "retire":
        return [{"op": "retire_node", "node_id": target_id}]
    if action != "supersede":
        msg = "retire_or_supersede action must be retire or supersede"
        raise ValueError(msg)
    replacement_ops = _ops(args.get("replacement_ops"))
    if not replacement_ops:
        msg = "retire_or_supersede supersede requires replacement_ops"
        raise ValueError(msg)
    return [{"op": "retire_node", "node_id": target_id}, *replacement_ops]


def _create_discovery_region(args: dict[str, Any]) -> list[dict[str, Any]]:
    region_id = _required_str(args, "region_id")
    worker_id = _str(args, "worker_id") or f"worker-discovery-{region_id}"
    worker = _worker_node(
        worker_id,
        region_id,
        f"discovery-{region_id}",
        role="discovery",
        attempt_number=1,
        objective=_required_str(args, "objective"),
        access_mode="read_only",
        acceptance=cast(list[str], args["acceptance"]),
    )
    node = cast(dict[str, Any], worker["node"])
    node.update(
        {
            "semantic_stage": "discovery",
            "base_snapshot_selection": "run_baseline",
            "scope": "repository analysis",
            "semantic_schema_id": _required_str(args, "semantic_schema_id"),
            "semantic_schema_version": args["semantic_schema_version"],
            "outputs": [
                {
                    "port": "semantic_artifact",
                    "direction": "output",
                    "schema": "SemanticArtifact",
                    "record_layers": ["graph_record"],
                    "required": True,
                }
            ],
            "inputs": _requirement_input_ports(args),
            "max_attempts": RELIABLE_PLAN_MAX_ATTEMPTS,
            "bound_requirement_ids": list(args.get("requirement_source_node_ids", [])),
            "invariants": ["repository state is unchanged"],
            "prohibited_actions": ["modify repository files", "produce implementation changes"],
        }
    )
    return [worker, *_requirement_edges(args, worker_id)]


def _create_plan_verification(args: dict[str, Any]) -> list[dict[str, Any]]:
    region_id = _required_str(args, "region_id")
    verifier_id = _str(args, "verifier_id") or f"verifier-plan-{region_id}"
    schema_id = _required_str(args, "semantic_schema_id")
    schema_version = cast(int, args["semantic_schema_version"])
    node = _verifier_node(verifier_id, region_id, rubric=cast(list[str], args["rubric"]))
    node_payload = cast(dict[str, Any], node["node"])
    node_payload.update(
        {
            "semantic_stage": "plan_verification",
            "base_snapshot_selection": "run_baseline",
            "objective": _required_str(args, "objective"),
            "acceptance": list(args["acceptance"]),
            "semantic_schema_id": schema_id,
            "semantic_schema_version": schema_version,
            "bound_requirement_ids": list(args.get("requirement_source_node_ids", [])),
            "inputs": [
                {
                    "port": "semantic_artifact",
                    "direction": "input",
                    "schema": "SemanticArtifact",
                    "required": True,
                },
                *_requirement_input_ports(args),
            ],
            "outputs": [
                {
                    "port": "verification_report",
                    "direction": "output",
                    "schema": "VerificationReport",
                    "required": True,
                }
            ],
            "max_attempts": RELIABLE_PLAN_MAX_ATTEMPTS,
        }
    )
    artifact_source = _required_str(args, "artifact_source_node_id")
    return [
        node,
        _edge(
            f"edge-{artifact_source}-semantic-plan-to-{verifier_id}",
            artifact_source,
            "semantic_artifact",
            verifier_id,
            "semantic_artifact",
            ("semantic_artifact",),
            selector=_semantic_artifact_selector(schema_id, schema_version, accepted=True),
            prompt_hydration_policy="structured_json",
        ),
        *_requirement_edges(args, verifier_id),
    ]


def _create_successor_planner(args: dict[str, Any]) -> list[dict[str, Any]]:
    region_id = _required_str(args, "region_id")
    node_id = _str(args, "node_id") or f"planner-successor-{region_id}"
    source_node_id = _required_str(args, "evidence_source_node_id")
    source_port = _required_str(args, "evidence_source_port")
    node = {
        "op": "create_node",
        "node": {
            "node_id": node_id,
            "kind": "planner",
            "role": "planner",
            "state": "planned",
            "task_region_id": region_id,
            "semantic_stage": "successor_planning",
            "base_snapshot_selection": (
                "run_baseline" if args["planning_horizon"] == 1 else "latest_accepted"
            ),
            "planning_horizon": args["planning_horizon"],
            # The controller derives generation from the authorized horizon.
            # It is therefore stable across ambiguous replies and retries and
            # cannot be inflated independently by the planner.
            "generation_index": args["planning_horizon"],
            "max_attempts": RELIABLE_PLAN_MAX_ATTEMPTS,
            "inputs": [
                {
                    "port": source_port,
                    "direction": "input",
                    "schema": (
                        "SemanticArtifact"
                        if source_port == "semantic_artifact"
                        else "VerificationReport"
                    ),
                    "required": True,
                }
            ],
        },
    }
    selector = (
        _semantic_artifact_selector(
            _required_str(args, "semantic_schema_id"),
            cast(int, args["semantic_schema_version"]),
            accepted=True,
        )
        if source_port == "semantic_artifact"
        else {
            "record_type": "verification_report",
            "schema": "VerificationReport",
            "outcome": "passed",
        }
    )
    return [
        node,
        _edge(
            f"edge-{source_node_id}-{source_port}-to-{node_id}",
            source_node_id,
            source_port,
            node_id,
            source_port,
            (source_port,),
            selector=selector,
            prompt_hydration_policy="structured_json",
        ),
    ]


def _create_effectful_batch(args: dict[str, Any]) -> list[dict[str, Any]]:
    region_id = _required_str(args, "region_id")
    batch_id = _required_str(args, "batch_id")
    worker_id = _str(args, "worker_id") or f"worker-batch-{batch_id}"
    verifier_id = _str(args, "verifier_id") or f"verifier-batch-{batch_id}"
    schema_id = _required_str(args, "semantic_schema_id")
    schema_version = cast(int, args["semantic_schema_version"])
    worker = _worker_node(
        worker_id,
        region_id,
        f"candidate-{batch_id}",
        role="implementer",
        attempt_number=1,
        objective=_required_str(args, "objective"),
        access_mode="write",
        acceptance=cast(list[str], args["acceptance"]),
    )
    worker_payload = cast(dict[str, Any], worker["node"])
    worker_payload.update(
        {
            "semantic_stage": "effectful_batch",
            "planning_horizon": args["planning_horizon"],
            "declared_batch_id": batch_id,
            "semantic_schema_id": schema_id,
            "semantic_schema_version": schema_version,
            "accepted_plan_amendment_record_id": args.get("accepted_plan_amendment_record_id"),
            "scope": f"declared implementation batch {batch_id}",
            "bound_requirement_ids": list(args.get("requirement_source_node_ids", [])),
            "invariants": ["only the accepted declared batch scope is implemented"],
            "prohibited_actions": ["collapse other declared batches into this region"],
            "base_snapshot_selection": (
                "run_baseline" if args["planning_horizon"] == 1 else "latest_accepted"
            ),
            "inputs": [
                {
                    "port": "semantic_artifact",
                    "direction": "input",
                    "schema": "SemanticArtifact",
                    "required": True,
                },
                {
                    "port": "verification_report",
                    "direction": "input",
                    "schema": "VerificationReport",
                    "required": True,
                },
                *_requirement_input_ports(args),
            ],
            "max_attempts": RELIABLE_PLAN_MAX_ATTEMPTS,
        }
    )
    verifier = _verifier_node(verifier_id, region_id, rubric=cast(list[str], args["rubric"]))
    verifier_payload = cast(dict[str, Any], verifier["node"])
    verifier_payload.update(
        {
            "semantic_stage": "effectful_batch",
            "planning_horizon": args["planning_horizon"],
            "declared_batch_id": batch_id,
            "bound_requirement_ids": list(args.get("requirement_source_node_ids", [])),
            "base_snapshot_selection": "candidate_under_test",
            "inputs": [
                {
                    "port": "candidate_under_test",
                    "direction": "input",
                    "schema": "ImplementationCandidate",
                    "required": True,
                }
            ]
            + [
                {
                    "port": f"check_result_{index}",
                    "direction": "input",
                    "schema": "CheckResult",
                    "required": True,
                }
                for index, _ in enumerate(cast(list[dict[str, Any]], args["checks"]), start=1)
            ]
            + _requirement_input_ports(args),
            "max_attempts": RELIABLE_PLAN_MAX_ATTEMPTS,
        }
    )
    plan_source = _required_str(args, "plan_source_node_id")
    plan_verifier = _required_str(args, "plan_verification_source_node_id")
    ops: list[dict[str, Any]] = [
        worker,
        verifier,
        _edge(
            f"edge-{plan_source}-accepted-plan-to-{worker_id}",
            plan_source,
            "semantic_artifact",
            worker_id,
            "semantic_artifact",
            ("semantic_artifact",),
            selector=_semantic_artifact_selector(schema_id, schema_version, accepted=True),
            prompt_hydration_policy="structured_json",
        ),
        _edge(
            f"edge-{plan_verifier}-passed-plan-to-{worker_id}",
            plan_verifier,
            "verification_report",
            worker_id,
            "verification_report",
            ("verification_report",),
            selector={
                "record_type": "verification_report",
                "schema": "VerificationReport",
                "outcome": "passed",
            },
            prompt_hydration_policy="structured_json",
        ),
        _edge(
            f"edge-{worker_id}-candidate-to-{verifier_id}",
            worker_id,
            "candidate",
            verifier_id,
            "candidate_under_test",
            ("candidate",),
            prompt_hydration_policy="structured_json",
        ),
        *_requirement_edges(args, worker_id),
        *_requirement_edges(args, verifier_id),
    ]
    for index, raw_check in enumerate(cast(list[dict[str, Any]], args["checks"]), start=1):
        check_id = _str(raw_check, "check_id") or f"check-{batch_id}-{index}"
        check_node: dict[str, Any] = {
            "node_id": check_id,
            "kind": "check",
            "role": "batch_check",
            "state": "planned",
            "task_region_id": region_id,
            "semantic_stage": "effectful_batch",
            "declared_batch_id": batch_id,
            "base_snapshot_selection": "candidate_under_test",
            "max_attempts": RELIABLE_PLAN_MAX_ATTEMPTS,
            "inputs": [
                {
                    "port": "candidate_under_test",
                    "direction": "input",
                    "schema": "ImplementationCandidate",
                    "required": True,
                }
            ],
        }
        _copy_command(raw_check, check_node)
        ops.extend(
            [
                {"op": "create_node", "node": check_node},
                _edge(
                    f"edge-{worker_id}-candidate-to-{check_id}",
                    worker_id,
                    "candidate",
                    check_id,
                    "candidate_under_test",
                    ("candidate",),
                ),
                _edge(
                    f"edge-{check_id}-result-to-{verifier_id}",
                    check_id,
                    "check_result",
                    verifier_id,
                    f"check_result_{index}",
                    ("check_result",),
                    selector={
                        "record_type": "any_of",
                        "selectors": [
                            {
                                "record_type": "check_result",
                                "schema": "CheckResult",
                                "status": "passed",
                            },
                            {
                                "record_type": "check_result",
                                "schema": "CheckResult",
                                "status": "failed",
                            },
                            {
                                "record_type": "check_result",
                                "schema": "CheckResult",
                                "status": "timeout",
                            },
                        ],
                    },
                    prompt_hydration_policy="structured_json",
                ),
            ]
        )
    return ops


def _construct_reliable_plan_region(
    args: dict[str, Any],
    *,
    projection: GraphProjection,
    proposed_by_node_id: str,
    patch_id: str,
) -> list[dict[str, Any]]:
    """Compile semantic planner decisions into one complete authorized region.

    The proposer chooses work; the controller chooses graph identity, evidence
    wiring, snapshots, assignments (stamped at the command boundary), and the
    horizon continuation shape.  Expansion is all-or-nothing because the
    complete operation list is returned only after every dependency resolves.
    """
    parent = node_payload_view(projection, proposed_by_node_id) or {}
    if not isinstance(parent.get("reliable_plan_skeleton_id"), str):
        raise ValueError("construct_reliable_plan_region requires a reliable-plan planner")
    operation_key = _required_str(args, "operation_key")
    scope = _required_str(args, "scope")
    objective = _required_str(args, "objective")
    acceptance = cast(list[str], args["acceptance"])
    rubric = cast(list[str], args["rubric"])
    dependencies = list(dict.fromkeys(cast(list[str], args.get("dependencies", []))))
    requirement_ids = list(dict.fromkeys(cast(list[str], args["requirement_ids"])))
    requirement_bindings = _resolve_requirement_bindings(projection, requirement_ids)
    token = _reliable_plan_operation_token(
        parent["reliable_plan_skeleton_id"], proposed_by_node_id, operation_key, patch_id
    )
    check_decisions = cast(list[dict[str, Any]], args["checks"])
    checks = [
        {
            "check_id": f"check-{token}-{index}",
            **{
                key: value
                for key, value in check.items()
                if key in {"command_binding", "command_definition"}
            },
        }
        for index, check in enumerate(check_decisions, start=1)
    ]
    requirement_sources = [producer for _record_id, producer in requirement_bindings]

    if parent.get("role") == "gap_planner":
        if not check_decisions:
            raise ValueError("corrective reliable-plan construction requires at least one check")
        return _construct_reliable_plan_batch_correction(
            args,
            projection=projection,
            proposed_by_node_id=proposed_by_node_id,
            token=token,
            scope=scope,
            objective=objective,
            acceptance=acceptance,
            rubric=rubric,
            checks=checks,
            requirement_ids=requirement_ids,
            requirement_sources=requirement_sources,
            requirement_bindings=requirement_bindings,
        )

    if parent.get("semantic_stage") != "successor_planning":
        if dependencies:
            raise ValueError("initial reliable-plan construction cannot declare batch dependencies")
        schema_id, schema_version = _implementation_plan_schema(projection)
        discovery_id = f"worker-discovery-{token}"
        verifier_id = f"verifier-plan-{token}"
        successor_id = f"planner-successor-{token}"
        common = {
            "semantic_schema_id": schema_id,
            "semantic_schema_version": schema_version,
            "objective": objective,
            "acceptance": acceptance,
            "requirement_source_node_ids": requirement_sources,
        }
        ops = [
            *_create_discovery_region(
                {**common, "region_id": f"discovery-{token}", "worker_id": discovery_id}
            ),
            *_create_plan_verification(
                {
                    **common,
                    "region_id": f"plan-verification-{token}",
                    "verifier_id": verifier_id,
                    "artifact_source_node_id": discovery_id,
                    "rubric": rubric,
                }
            ),
            *_create_successor_planner(
                {
                    "region_id": f"successor-{token}",
                    "node_id": successor_id,
                    "evidence_source_node_id": verifier_id,
                    "evidence_source_port": "verification_report",
                    "planning_horizon": 1,
                }
            ),
            *_create_gap_planner(
                {
                    "region_id": f"recovery-plan-{token}",
                    "node_id": f"planner-gap-plan-{token}",
                    "evidence_source_node_id": verifier_id,
                    "evidence_source_port": "verification_report",
                }
            ),
        ]
        _stamp_semantic_decisions(
            ops,
            scope=scope,
            objective=objective,
            requirement_ids=requirement_ids,
            dependencies=dependencies,
            acceptance=acceptance,
            checks=check_decisions,
            rubric=rubric,
            operation_key=operation_key,
        )
        _bind_exact_requirements(ops, requirement_bindings)
        return ops

    horizon = parent.get("planning_horizon")
    remaining = parent.get("reliable_plan_remaining_horizons")
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
        raise ValueError("reliable-plan successor is missing controller-owned planning horizon")
    if not isinstance(remaining, int) or isinstance(remaining, bool) or remaining < 1:
        raise ValueError("reliable-plan successor has no remaining horizon authority")
    if not check_decisions:
        raise ValueError("effectful reliable-plan construction requires at least one check")

    plan_record, plan_verifier_id = _accepted_plan_and_verifier(projection, scope)
    declared_batch_ids = _declared_batch_ids_from_plan(plan_record)
    unknown_dependencies = sorted(set(dependencies) - set(declared_batch_ids))
    if unknown_dependencies:
        raise ValueError(
            "reliable-plan dependencies are not declared batches: "
            + ", ".join(unknown_dependencies)
        )
    if scope in dependencies:
        raise ValueError("reliable-plan batch cannot depend on itself")
    existing_batch_verifiers = _batch_verifier_ids(projection)
    unresolved_dependencies = sorted(set(dependencies) - set(existing_batch_verifiers))
    if unresolved_dependencies:
        raise ValueError(
            "reliable-plan dependencies are not yet materialized: "
            + ", ".join(unresolved_dependencies)
        )

    schema_id = plan_record.value.schema_id
    schema_version = plan_record.value.schema_version
    worker_id = f"worker-batch-{token}"
    verifier_id = f"verifier-batch-{token}"
    region_id = f"batch-{token}"
    ops = _create_effectful_batch(
        {
            "region_id": region_id,
            "batch_id": scope,
            "plan_source_node_id": plan_record.producer_node_id,
            "plan_verification_source_node_id": plan_verifier_id,
            "semantic_schema_id": schema_id,
            "semantic_schema_version": schema_version,
            "objective": objective,
            "acceptance": acceptance,
            "checks": checks,
            "rubric": rubric,
            "planning_horizon": horizon,
            "requirement_source_node_ids": requirement_sources,
            "worker_id": worker_id,
            "verifier_id": verifier_id,
        }
    )
    _bind_dependency_verifications(
        ops,
        worker_id=worker_id,
        dependencies=dependencies,
        verifier_ids=existing_batch_verifiers,
    )
    if remaining > 1:
        ops.extend(
            _create_successor_planner(
                {
                    "region_id": f"successor-{token}",
                    "node_id": f"planner-successor-{token}",
                    "evidence_source_node_id": verifier_id,
                    "evidence_source_port": "verification_report",
                    "planning_horizon": horizon + 1,
                }
            )
        )
        ops.extend(
            _create_gap_planner(
                {
                    "region_id": f"recovery-{token}",
                    "node_id": f"planner-gap-batch-{token}",
                    "evidence_source_node_id": verifier_id,
                    "evidence_source_port": "verification_report",
                }
            )
        )
    else:
        batch_verifiers = {**existing_batch_verifiers, scope: verifier_id}
        missing_batches = sorted(set(declared_batch_ids) - set(batch_verifiers))
        if missing_batches:
            raise ValueError(
                "final reliable-plan region is missing prior batch verifiers: "
                + ", ".join(missing_batches)
            )
        ops.extend(
            _reliable_plan_finalization_ops(
                token=token,
                region_id=region_id,
                declared_batch_ids=declared_batch_ids,
                batch_verifiers=batch_verifiers,
                rubric=rubric,
                acceptance=acceptance,
            )
        )
        final_acceptance_id = f"check-final-acceptance-{token}"
        final_audit_id = f"verifier-final-audit-{token}"
        for label, source_id, source_port in (
            ("batch", verifier_id, "verification_report"),
            ("acceptance", final_acceptance_id, "check_result"),
            ("audit", final_audit_id, "verification_report"),
        ):
            ops.extend(
                _create_gap_planner(
                    {
                        "region_id": f"recovery-{label}-{token}",
                        "node_id": f"planner-gap-{label}-{token}",
                        "evidence_source_node_id": source_id,
                        "evidence_source_port": source_port,
                    }
                )
            )
    _stamp_semantic_decisions(
        ops,
        scope=scope,
        objective=objective,
        requirement_ids=requirement_ids,
        dependencies=dependencies,
        acceptance=acceptance,
        checks=check_decisions,
        rubric=rubric,
        operation_key=operation_key,
    )
    _bind_exact_requirements(ops, requirement_bindings)
    return ops


def _construct_reliable_plan_batch_correction(
    args: dict[str, Any],
    *,
    projection: GraphProjection,
    proposed_by_node_id: str,
    token: str,
    scope: str,
    objective: str,
    acceptance: list[str],
    rubric: list[str],
    checks: list[dict[str, Any]],
    requirement_ids: list[str],
    requirement_sources: list[str],
    requirement_bindings: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Construct one exact failed-batch correction from durable evidence."""
    parent = node_payload_view(projection, proposed_by_node_id) or {}
    records = output_record_payloads_view(projection)
    classifications = [
        record
        for record in records.values()
        if isinstance(record, GapClassificationRecord)
        and record.producer_node_id == proposed_by_node_id
        and record.value.classification == "corrective_work_required"
    ]
    active_leases = [
        lease
        for lease in leases_view(projection).values()
        if lease.node_id == proposed_by_node_id and lease.state == "active"
    ]
    if len(classifications) == 1:
        classification_record_id = classifications[0].record_id
    elif not classifications and len(active_leases) == 1:
        classification_record_id = f"classified-gap-{active_leases[0].execution_id}"
    else:
        raise ValueError(
            "reliable-plan correction requires one accepted or execution-promised corrective "
            "gap classification from the proposing gap planner"
        )

    recovery_record_id = parent.get("recovery_of_record_id")
    bound_ids = (
        {recovery_record_id}
        if isinstance(recovery_record_id, str)
        else {
            record_id
            for binding in input_bindings_view(projection).get(proposed_by_node_id, {}).values()
            for record_id in binding.record_ids
        }
    )
    bound_reports = [
        record
        for record in records.values()
        if isinstance(record, VerificationReportRecord) and record.record_id in bound_ids
    ]
    bound_checks = [
        record
        for record in records.values()
        if isinstance(record, CheckResultRecord) and record.record_id in bound_ids
    ]
    failed_reports = [record for record in bound_reports if record.outcome == "failed"]
    failed_acceptance = [record for record in bound_checks if record.value.status == "failed"]
    if len(failed_reports) == 1:
        failed_report = failed_reports[0]
        failed_stage = (node_payload_view(projection, failed_report.producer_node_id) or {}).get(
            "semantic_stage"
        )
        correction_trigger = (
            "failed_final_audit" if failed_stage == "final_audit" else "failed_batch"
        )
    elif len(failed_acceptance) == 1:
        failed_acceptance_record = failed_acceptance[0]
        acceptance_node = (
            node_payload_view(projection, failed_acceptance_record.producer_node_id) or {}
        )
        if acceptance_node.get("semantic_stage") != "final_acceptance":
            raise ValueError(
                "reliable-plan correction requires failed batch verification, final acceptance, "
                "or final audit evidence"
            )
        cited_reports = [
            record
            for record in records.values()
            if isinstance(record, VerificationReportRecord)
            and record.outcome == "passed"
            and record.record_id in failed_acceptance_record.evaluated_record_ids
            and record.candidate_id == failed_acceptance_record.candidate_id
            and (node_payload_view(projection, record.producer_node_id) or {}).get(
                "declared_batch_id"
            )
            == scope
        ]
        if len(cited_reports) != 1:
            raise ValueError(
                "failed final acceptance must cite one exact passing report for its final batch"
            )
        failed_report = cited_reports[0]
        correction_trigger = "failed_final_acceptance"
    else:
        raise ValueError(
            "reliable-plan correction requires one exact failed batch verification, final "
            "acceptance, or final audit result"
        )
    failed_verifier = node_payload_view(projection, failed_report.producer_node_id) or {}
    plan_record, _plan_verifier_id = _accepted_plan_and_verifier(projection, scope)
    declared_batch_ids = _declared_batch_ids_from_plan(plan_record)
    if correction_trigger == "failed_final_audit":
        batch_id = declared_batch_ids[-1]
        horizon = len(declared_batch_ids)
    else:
        batch_id = failed_verifier.get("declared_batch_id")
        horizon = failed_verifier.get("planning_horizon")
    if batch_id != scope:
        raise ValueError("correction scope must equal the failed declared batch identity")
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
        raise ValueError("failed reliable-plan batch is missing its planning horizon")

    evaluated_ids = set(failed_report.evaluated_record_ids)
    if correction_trigger == "failed_final_acceptance":
        evaluated_ids.update(record.record_id for record in failed_acceptance)
    evidence_checks = [
        record
        for record_id, record in records.items()
        if record_id in evaluated_ids
        and isinstance(record, CheckResultRecord)
        and (
            (correction_trigger == "failed_final_audit" and record.value.status == "passed")
            or (correction_trigger != "failed_final_audit" and record.value.status == "failed")
        )
    ]
    if not evidence_checks:
        raise ValueError(
            "reliable-plan correction requires exact acceptance/check evidence in its closure"
        )

    correction_worker_id = f"worker-corrective-{token}"
    correction_verifier_id = f"verifier-corrective-{token}"
    # Gap-planner authority is deliberately confined to this controller-owned
    # region identity by the patch validator.
    region_id = "corrective_work_region"
    ops = _create_work_region(
        {
            "region_id": region_id,
            "candidate_id": f"candidate-corrective-{token}",
            "worker_id": correction_worker_id,
            "verifier_id": correction_verifier_id,
            "objective": objective,
            "access_mode": "write",
            "acceptance": acceptance,
            "checks": checks,
            "rubric": rubric,
            "classified_gap_source_node_id": proposed_by_node_id,
            "failed_verification_source_node_id": failed_report.producer_node_id,
            "failed_check_source_node_ids": [record.producer_node_id for record in evidence_checks],
            "failed_verification_record_id": failed_report.record_id,
            "failed_check_record_ids": [record.record_id for record in evidence_checks],
            "classified_gap_record_id": classification_record_id,
            "declared_batch_id": scope,
            "planning_horizon": horizon,
            "base_snapshot_selection": "rejected_candidate",
            "base_snapshot_candidate_id": failed_report.candidate_id,
            "requirement_source_node_ids": requirement_sources,
        },
        corrective=True,
        proposed_by_node_id=proposed_by_node_id,
    )
    correction_worker = next(
        cast(dict[str, Any], op["node"])
        for op in ops
        if op.get("op") == "create_node"
        and isinstance(op.get("node"), dict)
        and cast(dict[str, Any], op["node"]).get("node_id") == correction_worker_id
    )
    correction_worker["correction_trigger"] = correction_trigger
    correction_worker["inputs"] = [
        {
            "port": "classified_gap",
            "direction": "input",
            "schema": "GapClassification",
            "required": True,
        },
        {
            "port": "verification_report",
            "direction": "input",
            "schema": "VerificationReport",
            "required": True,
        },
        {
            "port": "check_result",
            "direction": "input",
            "schema": "CheckResult",
            "required": True,
        },
        *_requirement_input_ports({"requirement_source_node_ids": requirement_sources}),
    ]
    correction_verifier = next(
        cast(dict[str, Any], op["node"])
        for op in ops
        if op.get("op") == "create_node"
        and isinstance(op.get("node"), dict)
        and cast(dict[str, Any], op["node"]).get("node_id") == correction_verifier_id
    )
    correction_verifier["correction_trigger"] = correction_trigger
    correction_verifier["inputs"] = [
        {
            "port": "candidate_under_test",
            "direction": "input",
            "schema": "ImplementationCandidate",
            "required": True,
        },
        *[
            {
                "port": f"check_result_{index}",
                "direction": "input",
                "schema": "CheckResult",
                "required": True,
            }
            for index, _check in enumerate(checks, start=1)
        ],
        *_requirement_input_ports({"requirement_source_node_ids": requirement_sources}),
    ]
    expected_check_status = "passed" if correction_trigger == "failed_final_audit" else "failed"
    expected_report_outcome = (
        "passed" if correction_trigger == "failed_final_acceptance" else "failed"
    )
    for op in ops:
        if (
            op.get("op") == "create_edge"
            and op.get("to_node_id") == correction_worker_id
            and op.get("to_port") == "check_result"
            and isinstance(op.get("accepted_record_selector"), dict)
        ):
            cast(dict[str, Any], op["accepted_record_selector"])["status"] = expected_check_status
        if (
            op.get("op") == "create_edge"
            and op.get("to_node_id") == correction_worker_id
            and op.get("to_port") == "verification_report"
            and isinstance(op.get("accepted_record_selector"), dict)
        ):
            cast(dict[str, Any], op["accepted_record_selector"])["outcome"] = (
                expected_report_outcome
            )
    requirement_args = {"requirement_source_node_ids": requirement_sources}
    ops.extend(_requirement_edges(requirement_args, correction_worker_id))
    ops.extend(_requirement_edges(requirement_args, correction_verifier_id))
    # The old passed-only successor is permanently blocked by the failed
    # report. Retire it in the same patch before installing its correction-
    # gated replacement.
    for node_id in sorted(node_kinds_view(projection)):
        node = node_payload_view(projection, node_id) or {}
        stale_successor = (
            node.get("kind") == "planner"
            and node.get("role") == "planner"
            and node.get("semantic_stage") == "successor_planning"
            and node.get("planning_horizon") == horizon + 1
        )
        stale_finalization = (
            node.get("semantic_stage")
            in {
                "final_acceptance",
                "final_audit",
                "final_gate",
            }
            or node.get("kind") == "final_gate"
        )
        stale_final_recovery = (
            horizon >= len(declared_batch_ids)
            and node.get("kind") == "planner"
            and node.get("role") == "gap_planner"
        )
        if (
            node_id in effective_active_node_ids_view(projection)
            and node_id != proposed_by_node_id
            and (stale_successor or stale_finalization or stale_final_recovery)
        ):
            ops.append({"op": "retire_node", "node_id": node_id})
    if horizon < len(declared_batch_ids):
        ops.extend(
            _create_successor_planner(
                {
                    "region_id": f"successor-corrective-{token}",
                    "node_id": f"planner-successor-corrective-{token}",
                    "evidence_source_node_id": correction_verifier_id,
                    "evidence_source_port": "verification_report",
                    "planning_horizon": horizon + 1,
                }
            )
        )
        ops.extend(
            _create_gap_planner(
                {
                    "region_id": f"recovery-corrective-{token}",
                    "node_id": f"planner-gap-corrective-{token}",
                    "evidence_source_node_id": correction_verifier_id,
                    "evidence_source_port": "verification_report",
                }
            )
        )
    else:
        batch_verifiers = {**_batch_verifier_ids(projection), scope: correction_verifier_id}
        missing_batches = sorted(set(declared_batch_ids) - set(batch_verifiers))
        if missing_batches:
            raise ValueError(
                "final reliable-plan correction is missing prior batch verifiers: "
                + ", ".join(missing_batches)
            )
        ops.extend(
            _reliable_plan_finalization_ops(
                token=f"corrective-{token}",
                region_id=region_id,
                declared_batch_ids=declared_batch_ids,
                batch_verifiers=batch_verifiers,
                rubric=rubric,
                acceptance=acceptance,
            )
        )
        for label, source_id, source_port in (
            ("batch", correction_verifier_id, "verification_report"),
            ("acceptance", f"check-final-acceptance-corrective-{token}", "check_result"),
            ("audit", f"verifier-final-audit-corrective-{token}", "verification_report"),
        ):
            ops.extend(
                _create_gap_planner(
                    {
                        "region_id": f"recovery-corrective-{label}-{token}",
                        "node_id": f"planner-gap-corrective-{label}-{token}",
                        "evidence_source_node_id": source_id,
                        "evidence_source_port": source_port,
                    }
                )
            )
    _stamp_semantic_decisions(
        ops,
        scope=scope,
        objective=objective,
        requirement_ids=requirement_ids,
        dependencies=list(cast(list[str], args.get("dependencies", []))),
        acceptance=acceptance,
        checks=cast(list[dict[str, Any]], args["checks"]),
        rubric=rubric,
        operation_key=_required_str(args, "operation_key"),
    )
    _bind_exact_requirements(ops, requirement_bindings)
    return ops


def _reliable_plan_operation_token(
    skeleton_id: str, proposer_id: str, operation_key: str, patch_id: str
) -> str:
    del patch_id  # transport envelopes do not participate in controller-owned identity
    digest = hashlib.sha256(
        "\x00".join((skeleton_id, proposer_id, operation_key)).encode()
    ).hexdigest()[:16]
    stem = re.sub(r"[^a-z0-9]+", "-", operation_key.lower()).strip("-")[:24] or "region"
    return f"{stem}-{digest}"


def _resolve_requirement_bindings(
    projection: GraphProjection, requirement_ids: list[str]
) -> list[tuple[str, str]]:
    by_identity: dict[str, tuple[str, str]] = {}
    for record_id, record in output_record_payloads_view(projection).items():
        if not isinstance(record, RequirementRecord):
            continue
        by_identity[record.value.id] = (record_id, record.producer_node_id)
    bindings: list[tuple[str, str]] = []
    for requirement_id in requirement_ids:
        binding = by_identity.get(requirement_id)
        if binding is None and node_kinds_view(projection).get(requirement_id) == "requirement":
            binding = (requirement_id, requirement_id)
        if binding is None:
            raise ValueError(f"unknown reliable-plan requirement identity: {requirement_id}")
        bindings.append(binding)
    return bindings


def _implementation_plan_schema(projection: GraphProjection) -> tuple[str, int]:
    candidates = [
        key
        for key, declaration in semantic_schema_declarations_view(projection).items()
        if declaration.value.semantic_role == "implementation_plan"
    ]
    if len(candidates) != 1:
        raise ValueError(
            "reliable-plan construction requires exactly one implementation-plan schema"
        )
    return candidates[0]


def _declared_batch_ids_from_plan(plan_record: SemanticArtifactRecord) -> list[str]:
    content = plan_record.value.content
    raw_batches: Any = content.get("batches") if content is not None else None
    if not isinstance(raw_batches, list):
        raise ValueError("accepted reliable plan does not declare ordered batches")
    batch_ids: list[str] = []
    for raw_batch in cast(list[Any], raw_batches):
        batch_id: object | None = None
        if isinstance(raw_batch, str):
            batch_id = raw_batch
        elif isinstance(raw_batch, dict):
            batch = cast(dict[str, Any], raw_batch)
            batch_id = batch.get("batch_id", batch.get("id"))
        if not isinstance(batch_id, str) or not batch_id:
            raise ValueError("accepted reliable plan contains an invalid batch identity")
        batch_ids.append(batch_id)
    return list(dict.fromkeys(batch_ids))


def _accepted_plan_and_verifier(
    projection: GraphProjection, scope: str
) -> tuple[SemanticArtifactRecord, str]:
    records = output_record_payloads_view(projection)
    plans: list[SemanticArtifactRecord] = [
        record
        for record in records.values()
        if isinstance(record, SemanticArtifactRecord)
        and record.value.authority_status == "accepted"
        and scope in _declared_batch_ids_from_plan(record)
    ]
    if len(plans) != 1:
        raise ValueError(f"scope {scope!r} must identify exactly one accepted plan batch")
    plan = plans[0]
    verifiers = [
        record.producer_node_id
        for record in records.values()
        if isinstance(record, VerificationReportRecord)
        and record.outcome == "passed"
        and plan.record_id in record.evaluated_record_ids
        and (node_payload_view(projection, record.producer_node_id) or {}).get("semantic_stage")
        == "plan_verification"
    ]
    if len(set(verifiers)) != 1:
        raise ValueError("accepted reliable plan requires one exact passing independent verifier")
    return plan, verifiers[0]


def _batch_verifier_ids(projection: GraphProjection) -> dict[str, str]:
    result: dict[str, str] = {}
    active = effective_active_node_ids_view(projection)
    for node_id in node_kinds_view(projection):
        payload = node_payload_view(projection, node_id) or {}
        batch_id = payload.get("declared_batch_id")
        if (
            payload.get("kind") == "verifier"
            and payload.get("semantic_stage") in {"effectful_batch", "corrective_work"}
            and isinstance(batch_id, str)
            and node_id in active
        ):
            result[batch_id] = node_id
    return result


def _bind_dependency_verifications(
    ops: list[dict[str, Any]],
    *,
    worker_id: str,
    dependencies: list[str],
    verifier_ids: dict[str, str],
) -> None:
    worker = next(
        cast(dict[str, Any], op["node"])
        for op in ops
        if op.get("op") == "create_node"
        and isinstance(op.get("node"), dict)
        and cast(dict[str, Any], op["node"]).get("node_id") == worker_id
    )
    inputs = cast(list[dict[str, Any]], worker.setdefault("inputs", []))
    for index, dependency in enumerate(dependencies, start=1):
        port = f"dependency_verification_{index}"
        inputs.append(
            {
                "port": port,
                "direction": "input",
                "schema": "VerificationReport",
                "required": True,
            }
        )
        ops.append(
            _edge(
                f"edge-{verifier_ids[dependency]}-dependency-to-{worker_id}-{index}",
                verifier_ids[dependency],
                "verification_report",
                worker_id,
                port,
                ("verification_report",),
                selector={
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "passed",
                },
                prompt_hydration_policy="structured_json",
            )
        )


def _reliable_plan_finalization_ops(
    *,
    token: str,
    region_id: str,
    declared_batch_ids: list[str],
    batch_verifiers: dict[str, str],
    rubric: list[str],
    acceptance: list[str],
) -> list[dict[str, Any]]:
    acceptance_id = f"check-final-acceptance-{token}"
    audit_id = f"verifier-final-audit-{token}"
    gate_id = f"final-gate-{token}"
    batch_inputs = [
        {
            "port": f"verification_report_batch_{index}",
            "direction": "input",
            "schema": "VerificationReport",
            "required": True,
        }
        for index, _batch_id in enumerate(declared_batch_ids, start=1)
    ]
    ops: list[dict[str, Any]] = [
        {
            "op": "create_node",
            "node": {
                "node_id": acceptance_id,
                "kind": "check",
                "role": "acceptance_gate",
                "state": "planned",
                "semantic_stage": "final_acceptance",
                "task_region_id": region_id,
                "declared_batch_ids": declared_batch_ids,
                "command_binding": "dynamic_feature_acceptance",
                "acceptance": acceptance,
                "inputs": batch_inputs,
                "outputs": [
                    {
                        "port": "check_result",
                        "direction": "output",
                        "schema": "CheckResult",
                        "required": True,
                    }
                ],
                "max_attempts": RELIABLE_PLAN_MAX_ATTEMPTS,
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": audit_id,
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "semantic_stage": "final_audit",
                "task_region_id": region_id,
                "declared_batch_ids": declared_batch_ids,
                "rubric": rubric,
                "inputs": [
                    *batch_inputs,
                    {
                        "port": "dynamic_feature_acceptance",
                        "direction": "input",
                        "schema": "CheckResult",
                        "required": True,
                    },
                ],
                "outputs": [
                    {
                        "port": "verification_report",
                        "direction": "output",
                        "schema": "VerificationReport",
                        "required": True,
                    }
                ],
                "max_attempts": RELIABLE_PLAN_MAX_ATTEMPTS,
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": gate_id,
                "kind": "final_gate",
                "role": "final_gate",
                "state": "planned",
                "task_region_id": region_id,
                "declared_batch_ids": declared_batch_ids,
                "inputs": [
                    *batch_inputs,
                    {
                        "port": "dynamic_feature_acceptance",
                        "direction": "input",
                        "schema": "CheckResult",
                        "required": True,
                    },
                    {
                        "port": "verification_report_final_audit",
                        "direction": "input",
                        "schema": "VerificationReport",
                        "required": True,
                    },
                ],
            },
        },
    ]
    for index, batch_id in enumerate(declared_batch_ids, start=1):
        source = batch_verifiers[batch_id]
        port = f"verification_report_batch_{index}"
        for target in (acceptance_id, audit_id, gate_id):
            ops.append(
                _edge(
                    f"edge-{source}-passed-to-{target}-{index}",
                    source,
                    "verification_report",
                    target,
                    port,
                    ("verification_report",),
                    selector={
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "passed",
                    },
                )
            )
    ops.extend(
        [
            _edge(
                f"edge-{acceptance_id}-passed-to-{audit_id}",
                acceptance_id,
                "check_result",
                audit_id,
                "dynamic_feature_acceptance",
                ("check_result",),
                selector={
                    "record_type": "check_result",
                    "schema": "CheckResult",
                    "status": "passed",
                },
            ),
            _edge(
                f"edge-{acceptance_id}-passed-to-{gate_id}",
                acceptance_id,
                "check_result",
                gate_id,
                "dynamic_feature_acceptance",
                ("check_result",),
                selector={
                    "record_type": "check_result",
                    "schema": "CheckResult",
                    "status": "passed",
                },
            ),
            _edge(
                f"edge-{audit_id}-passed-to-{gate_id}",
                audit_id,
                "verification_report",
                gate_id,
                "verification_report_final_audit",
                ("verification_report",),
                selector={
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "passed",
                },
            ),
        ]
    )
    return ops


def _stamp_semantic_decisions(
    ops: list[dict[str, Any]],
    *,
    scope: str,
    objective: str,
    requirement_ids: list[str],
    dependencies: list[str],
    acceptance: list[str],
    checks: list[dict[str, Any]],
    rubric: list[str],
    operation_key: str,
) -> None:
    for op in ops:
        raw_node = op.get("node")
        if op.get("op") != "create_node" or not isinstance(raw_node, dict):
            continue
        node = cast(dict[str, Any], raw_node)
        node["scope"] = scope
        node.setdefault("objective", objective)
        node.setdefault("acceptance", acceptance)
        if dependencies:
            node["preconditions"] = [f"declared batch {item} passed" for item in dependencies]
        if node.get("kind") in {"worker", "verifier"}:
            node["bound_requirement_ids"] = requirement_ids


def _bind_exact_requirements(ops: list[dict[str, Any]], bindings: list[tuple[str, str]]) -> None:
    by_index = {index: record_id for index, (record_id, _producer) in enumerate(bindings, start=1)}
    for op in ops:
        to_port = op.get("to_port")
        if op.get("op") != "create_edge" or not isinstance(to_port, str):
            continue
        if not to_port.startswith("requirement_"):
            continue
        try:
            index = int(to_port.removeprefix("requirement_"))
        except ValueError:
            continue
        record_id = by_index.get(index)
        if record_id is not None:
            op["accepted_record_selector"] = {
                "record_id": record_id,
                "record_type": "requirement_record",
            }


def _semantic_artifact_selector(
    schema_id: str,
    schema_version: int,
    *,
    accepted: bool = False,
) -> dict[str, Any]:
    selector: dict[str, Any] = {
        "record_type": "semantic_artifact",
        "schema": "SemanticArtifact",
        "semantic_schema_id": schema_id,
        "semantic_schema_version": schema_version,
    }
    if accepted:
        selector["authority_status"] = "accepted"
    return selector


def _requirement_edges(args: dict[str, Any], target_node_id: str) -> list[dict[str, Any]]:
    source_ids = cast(list[str], args.get("requirement_source_node_ids", []))
    return [
        _edge(
            f"edge-{source_id}-requirement-to-{target_node_id}-{index}",
            source_id,
            "requirement",
            target_node_id,
            f"requirement_{index}",
            ("requirement_record",),
            selector={"record_type": "requirement_record"},
            prompt_hydration_policy="structured_json",
        )
        for index, source_id in enumerate(source_ids, start=1)
    ]


def _requirement_input_ports(args: dict[str, Any]) -> list[dict[str, Any]]:
    source_ids = cast(list[str], args.get("requirement_source_node_ids", []))
    return [
        {
            "port": f"requirement_{index}",
            "direction": "input",
            "schema": "Requirement",
            "required": True,
        }
        for index, _ in enumerate(source_ids, start=1)
    ]


def _worker_node(
    node_id: str,
    region_id: str,
    candidate_id: str,
    *,
    role: str,
    attempt_number: int,
    objective: str | None = None,
    access_mode: str | None = None,
    acceptance: list[str] | None = None,
    access_mode_override_justification: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "node_id": node_id,
        "kind": "worker",
        "role": role,
        "state": "planned",
        "task_region_id": region_id,
        "candidate_id": candidate_id,
        "attempt_number": attempt_number,
        "authority": {
            "allowed_actions": [
                "submit_records",
                "request_clarification",
                "raise_appeal",
            ],
            "resource_claims": [
                {"mode": "read", "scope": "repo", "paths": ["."]}
                if access_mode == "read_only"
                else {"mode": "write", "scope": "repo", "paths": ["."]}
            ],
        },
    }
    if objective is not None:
        node["objective"] = objective
    if access_mode is not None:
        node["access_mode"] = access_mode
        node["effect_contract"] = (
            "read_only_semantic" if access_mode == "read_only" else "effectful_write"
        )
    if acceptance is not None:
        node["acceptance"] = acceptance
    if access_mode_override_justification is not None:
        node["access_mode_override_justification"] = access_mode_override_justification
    return {"op": "create_node", "node": node}


def _verifier_node(
    node_id: str,
    region_id: str,
    *,
    rubric: list[str],
) -> dict[str, Any]:
    return {
        "op": "create_node",
        "node": {
            "node_id": node_id,
            "kind": "verifier",
            "role": "verifier",
            "state": "planned",
            "task_region_id": region_id,
            "rubric": rubric,
        },
    }


def _edge(
    edge_id: str,
    from_node_id: str,
    from_port: str,
    to_node_id: str,
    to_port: str,
    selector_kinds: tuple[str, ...],
    *,
    selector: dict[str, Any] | None = None,
    prompt_hydration_policy: str | None = None,
) -> dict[str, Any]:
    edge = {
        "op": "create_edge",
        "edge_id": edge_id,
        "from_node_id": from_node_id,
        "from_port": from_port,
        "to_node_id": to_node_id,
        "to_port": to_port,
        "required": True,
        "accepted_record_selector": selector or _selector_for_kinds(selector_kinds),
    }
    if prompt_hydration_policy is not None:
        edge["prompt_hydration_policy"] = prompt_hydration_policy
    return edge


def _selector_for_kinds(selector_kinds: tuple[str, ...]) -> dict[str, Any]:
    selectors = [_selector_for_kind(kind) for kind in selector_kinds]
    if len(selectors) == 1:
        return selectors[0]
    return {"record_type": "any_of", "selectors": selectors}


def _selector_for_kind(kind: str) -> dict[str, Any]:
    if kind == "candidate":
        return {"record_type": "candidate", "schema": "ImplementationCandidate"}
    if kind == "verification_report":
        return {"record_type": "verification_report", "schema": "VerificationReport"}
    if kind == "check_result":
        return {"record_type": "check_result", "schema": "CheckResult"}
    if kind in {"gap_analysis", "gap_plan", "classified_gap"}:
        return {"record_type": "gap_classification", "schema": "GapClassification"}
    if kind == "file_state":
        return {"record_type": "file_state", "schema": "FileStateRecord"}
    return {"record_type": kind}


def _copy_command(source: dict[str, Any], target: dict[str, Any]) -> None:
    command_definition = source.get("command_definition")
    if isinstance(command_definition, dict):
        target["command_definition"] = dict(cast(dict[str, Any], command_definition))
        return
    for key in ("command_binding", "hidden_oracle_command"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            target[key] = value
            return
    msg = "attach_check requires command_definition, command_binding, or hidden_oracle_command"
    raise ValueError(msg)


def _checks(args: dict[str, Any]) -> list[dict[str, Any]]:
    raw_checks = args.get("checks", [])
    if raw_checks is None:
        return []
    if not isinstance(raw_checks, list):
        msg = "checks must be a list"
        raise ValueError(msg)
    checks: list[dict[str, Any]] = []
    for raw_check in cast(list[Any], raw_checks):
        if not isinstance(raw_check, dict):
            msg = "checks entries must be objects"
            raise ValueError(msg)
        checks.append(dict(cast(dict[str, Any], raw_check)))
    return checks


def _rubric(args: dict[str, Any]) -> list[str]:
    raw_rubric = args.get("rubric")
    if isinstance(raw_rubric, list):
        rubric = [item for item in cast(list[Any], raw_rubric) if isinstance(item, str)]
        if rubric:
            return rubric
    return ["candidate satisfies the bound requirements"]


def _required_str(args: dict[str, Any], key: str) -> str:
    value = _str(args, key)
    if value is None:
        msg = f"{key} is required"
        raise ValueError(msg)
    return value


def _str(args: dict[str, Any], key: str) -> str | None:
    value = args.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


def _ops(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        msg = "ops must be a list"
        raise ValueError(msg)
    ops: list[dict[str, Any]] = []
    for raw_op in cast(list[Any], value):
        if not isinstance(raw_op, dict):
            msg = "ops entries must be objects"
            raise ValueError(msg)
        ops.append(dict(cast(dict[str, Any], raw_op)))
    return ops
