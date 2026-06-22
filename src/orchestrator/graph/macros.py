"""Planner-facing graph macro expansion.

Macros keep planner tool calls focused on typed graph intent while preserving
low-level patch ops as the kernel's internal representation.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


MACRO_FIELD = "macro_invocations"


class MacroInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    macro: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_macro_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized: dict[str, Any] = dict(cast(dict[str, Any], data))
        if "macro" not in normalized:
            for alias in ("name", "tool"):
                alias_value = normalized.get(alias)
                if alias_value is not None:
                    normalized["macro"] = alias_value
                    break
        raw_args = normalized.get("args")
        if raw_args is None:
            normalized["args"] = {}
        return normalized


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


class AttachVerifierArgs(MacroArgs):
    region_id: str = Field(min_length=1)
    candidate_source_node_id: str | None = None
    worker_id: str | None = None
    verifier_id: str | None = None
    edge_id: str | None = None
    candidate_id: str | None = None
    rubric: list[str] | None = None


class AttachCheckArgs(MacroArgs):
    region_id: str = Field(min_length=1)
    check_id: str | None = None
    node_id: str | None = None
    evidence_source_node_id: str | None = None
    verifier_id: str | None = None
    edge_id: str | None = None
    role: str | None = None
    candidate_id: str | None = None
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


_MACRO_SPECS = {
    "create_work_region": CreateWorkRegionArgs,
    "create_corrective_region": CreateWorkRegionArgs,
    "attach_verifier": AttachVerifierArgs,
    "attach_check": AttachCheckArgs,
    "create_gap_planner": CreateGapPlannerArgs,
    "create_join": CreateJoinArgs,
    "request_gate": RequestGateArgs,
    "retire_or_supersede": RetireOrSupersedeArgs,
}


def expand_patch_macros(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a patch payload with macro invocations expanded into ``ops``."""

    invocations = payload.get(MACRO_FIELD)
    if invocations is None:
        return dict(payload)
    if not isinstance(invocations, list):
        msg = "macro_invocations must be a list"
        raise ValueError(msg)

    ops = _ops(payload.get("ops"))
    for raw_invocation in cast(list[Any], invocations):
        invocation = _validate_invocation(raw_invocation)
        ops.extend(_expand_macro(invocation.macro, invocation.args, payload))

    expanded = dict(payload)
    expanded["ops"] = ops
    return expanded


def _expand_macro(
    macro_name: str,
    args: dict[str, Any],
    patch_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    if macro_name == "create_work_region":
        return _create_work_region(args, corrective=False, patch_payload=patch_payload)
    if macro_name == "create_corrective_region":
        return _create_work_region(args, corrective=True, patch_payload=patch_payload)
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
    msg = f"unknown graph macro: {macro_name}"
    raise ValueError(msg)


def _validate_invocation(raw_invocation: Any) -> MacroInvocation:
    try:
        invocation = MacroInvocation.model_validate(raw_invocation)
    except ValidationError as exc:
        raise ValueError(f"invalid macro invocation: {exc.errors()[0]['msg']}") from exc

    args_model = _MACRO_SPECS.get(invocation.macro)
    if args_model is None:
        msg = f"unknown graph macro: {invocation.macro}"
        raise ValueError(msg)
    try:
        typed_args = args_model.model_validate(invocation.args)
    except ValidationError as exc:
        first_error = exc.errors()[0]
        location = ".".join(str(part) for part in first_error["loc"])
        detail = first_error["msg"]
        if location:
            raise ValueError(f"{invocation.macro} args invalid: {location}: {detail}") from exc
        raise ValueError(f"{invocation.macro} args invalid: {detail}") from exc
    return invocation.model_copy(update={"args": typed_args.model_dump(exclude_none=True)})


def _create_work_region(
    args: dict[str, Any],
    *,
    corrective: bool,
    patch_payload: dict[str, Any],
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
        ),
        _verifier_node(
            verifier_id,
            region_id,
            candidate_id,
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
    if corrective:
        gap_source = (
            _str(args, "classified_gap_source_node_id")
            or _str(args, "gap_planner_node_id")
            or _str(patch_payload, "proposed_by_node_id")
        )
        if gap_source is not None:
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
    candidate_id = _str(args, "candidate_id") or f"candidate-{region_id}"
    return [
        _verifier_node(verifier_id, region_id, candidate_id, rubric=_rubric(args)),
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
    candidate_id = _str(args, "candidate_id")
    if candidate_id is not None:
        node["candidate_id"] = candidate_id
    _copy_command(args, node)
    return [
        {"op": "create_node", "node": node},
        _edge(
            _str(args, "edge_id") or f"edge-{evidence_source}-verification-to-{check_id}",
            evidence_source,
            _str(args, "evidence_source_port") or "verification_report",
            check_id,
            "verification_evidence",
            ("verification", "check_result"),
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
            ("verification", "check_result"),
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
                ("candidate", "verification", "check_result", "file_state"),
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


def _worker_node(
    node_id: str,
    region_id: str,
    candidate_id: str,
    *,
    role: str,
    attempt_number: int,
) -> dict[str, Any]:
    return {
        "op": "create_node",
        "node": {
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
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["."]}],
            },
        },
    }


def _verifier_node(
    node_id: str,
    region_id: str,
    candidate_id: str,
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
            "candidate_id": candidate_id,
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
) -> dict[str, Any]:
    return {
        "op": "create_edge",
        "edge_id": edge_id,
        "from_node_id": from_node_id,
        "from_port": from_port,
        "to_node_id": to_node_id,
        "to_port": to_port,
        "required": True,
        "accepted_record_selector": {"record_kinds": list(selector_kinds)},
    }


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
