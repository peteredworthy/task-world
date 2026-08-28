"""Planner-facing graph macro expansion.

Macros keep planner tool calls focused on typed graph intent while preserving
low-level patch ops as the kernel's internal representation.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from orchestrator.graph._error_rendering import safe_exception_reason


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
}


def expand_patch_macros(
    ops: list[dict[str, Any]],
    invocations: list[MacroInvocation],
    proposed_by_node_id: str,
) -> list[dict[str, Any]]:
    """Expand validated macro invocations into patch operations."""

    expanded = list(ops)
    for invocation in invocations:
        invocation = _validate_invocation(invocation)
        expanded.extend(_expand_macro(invocation.macro, invocation.args, proposed_by_node_id))
    return expanded


def _expand_macro(
    macro_name: str,
    args: dict[str, Any],
    proposed_by_node_id: str,
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
                "failed_verification_record_id": args["failed_verification_record_id"],
                "failed_check_record_ids": list(args["failed_check_record_ids"]),
                "classified_gap_record_id": args["classified_gap_record_id"],
                "base_snapshot_region_id": args.get("base_snapshot_region_id"),
                "base_snapshot_candidate_id": args.get("base_snapshot_candidate_id"),
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
    for check_args in _checks(args):
        normalized = {"region_id": region_id, "evidence_source_node_id": verifier_id, **check_args}
        ops.extend(_attach_check(normalized))
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
                }
            ],
        }
    )
    verifier = _verifier_node(verifier_id, region_id, rubric=cast(list[str], args["rubric"]))
    verifier_payload = cast(dict[str, Any], verifier["node"])
    verifier_payload.update(
        {
            "semantic_stage": "effectful_batch",
            "declared_batch_id": batch_id,
            "bound_requirement_ids": list(args.get("requirement_source_node_ids", [])),
            "base_snapshot_selection": "candidate_under_test",
            "inputs": [
                {
                    "port": f"check_result_{index}",
                    "direction": "input",
                    "schema": "CheckResult",
                    "required": True,
                }
                for index, _ in enumerate(cast(list[dict[str, Any]], args["checks"]), start=1)
            ],
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
