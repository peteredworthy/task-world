"""Typed dynamic work graph contract registry.

The registry is deliberately small and pure: patch validation, callback
validation, prompt builders, and readback code can all consult the same contract
facts without reaching into runtime state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast


HandlerType = Literal["controller", "agent", "human", "deterministic_command"]
PortDirection = Literal["input", "output"]
BindingPolicy = Literal[
    "bind_first",
    "bind_latest",
    "bind_all",
    "rebind_on_superseding",
    "never_rebind",
]
PromptHydrationPolicy = Literal[
    "inline_summary",
    "structured_json",
    "artifact_reference",
    "tool_only",
]

VALID_BINDING_POLICIES: frozenset[str] = frozenset(
    {"bind_first", "bind_latest", "bind_all", "rebind_on_superseding", "never_rebind"}
)
VALID_PROMPT_HYDRATION_POLICIES: frozenset[str] = frozenset(
    {"inline_summary", "structured_json", "artifact_reference", "tool_only"}
)


@dataclass(frozen=True)
class PortContract:
    name: str
    record_types: frozenset[str]
    schemas: frozenset[str] = frozenset()
    selector_aliases: frozenset[str] = frozenset()
    required: bool = True
    cardinality: Literal["one", "many", "latest", "all"] = "one"


def _empty_port_contracts() -> dict[str, PortContract]:
    return {}


@dataclass(frozen=True)
class NodeContract:
    node_type: str
    contract_version: int
    handler_type: HandlerType
    roles: frozenset[str] | None = None
    input_ports: dict[str, PortContract] = field(default_factory=_empty_port_contracts)
    output_ports: dict[str, PortContract] = field(default_factory=_empty_port_contracts)
    allowed_tools: frozenset[str] = frozenset()
    compatibility_aliases: frozenset[str] = frozenset()

    def allows_role(self, role: str | None) -> bool:
        return self.roles is None or role is None or role in self.roles


@dataclass(frozen=True)
class NodeContractRegistry:
    contracts: dict[str, NodeContract]
    aliases: dict[str, str]

    def contract_for(self, node_type: str, role: str | None = None) -> NodeContract | None:
        if node_type == "planner" and role == "gap_planner":
            return self.contracts["gap_planner"]
        canonical = self.aliases.get(node_type, node_type)
        return self.contracts.get(canonical)

    def has_node_type(self, node_type: str, role: str | None = None) -> bool:
        return self.contract_for(node_type, role) is not None

    def allowed_tools_for(self, node_type: str, role: str | None = None) -> frozenset[str]:
        contract = self.contract_for(node_type, role)
        if contract is None:
            return frozenset()
        if contract.node_type == "planner" and role not in {None, "planner"}:
            return frozenset()
        return contract.allowed_tools


def validate_node_payload(node: dict[str, Any]) -> str | None:
    node_id = node.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        return "create_node requires node_id"
    kind = node.get("kind")
    if not isinstance(kind, str) or not kind:
        return f"node {node_id} requires kind"
    role = node.get("role")
    typed_role = role if isinstance(role, str) else None
    contract = DEFAULT_NODE_CONTRACTS.contract_for(kind, typed_role)
    if contract is None:
        return f"unknown node type: {kind}"
    if not contract.allows_role(typed_role):
        return f"node role {typed_role} is not allowed for {kind}"
    port_error = _validate_declared_ports(node, "inputs", "input", contract)
    if port_error is not None:
        return port_error
    return _validate_declared_ports(node, "outputs", "output", contract)


def validate_edge_payload(
    edge: dict[str, Any],
    *,
    source_kind: str,
    source_role: str | None,
    target_kind: str,
    target_role: str | None,
) -> str | None:
    edge_id = edge.get("edge_id")
    if not isinstance(edge_id, str) or not edge_id:
        return "create_edge requires edge_id"
    from_port = _canonical_port(edge.get("from_port"))
    to_port = _canonical_port(edge.get("to_port"))
    if not isinstance(from_port, str) or not from_port:
        return f"edge {edge_id} requires from_port"
    if not isinstance(to_port, str) or not to_port:
        return f"edge {edge_id} requires to_port"

    source_contract = DEFAULT_NODE_CONTRACTS.contract_for(source_kind, source_role)
    if source_contract is None:
        return f"edge {edge_id} has unknown source node type: {source_kind}"
    target_contract = DEFAULT_NODE_CONTRACTS.contract_for(target_kind, target_role)
    if target_contract is None:
        return f"edge {edge_id} has unknown target node type: {target_kind}"

    source = output_port_contract(source_contract, from_port)
    if source is None:
        return f"edge {edge_id} references unknown source port {source_kind}.{from_port}"
    target = input_port_contract(target_contract, to_port)
    if target is None:
        return f"edge {edge_id} references unknown target port {target_kind}.{to_port}"
    if source.record_types.isdisjoint(target.record_types):
        return (
            f"edge {edge_id} record type mismatch: {source_kind}.{from_port} -> "
            f"{target_kind}.{to_port}"
        )
    policy_error = _binding_policy_error(edge, edge_id, target)
    if policy_error is not None:
        return policy_error
    hydration_policy_error = _prompt_hydration_policy_error(edge, edge_id)
    if hydration_policy_error is not None:
        return hydration_policy_error
    return _selector_compatibility_error(edge, edge_id, source)


def validate_output_record(
    *,
    node_kind: str,
    node_role: str | None,
    record_payload: dict[str, Any],
    index: int,
) -> str | None:
    contract = DEFAULT_NODE_CONTRACTS.contract_for(node_kind, node_role)
    if contract is None:
        return f"output record at index {index} has unknown producer node type: {node_kind}"
    port = _canonical_port(record_payload.get("port"))
    if not isinstance(port, str) or not port:
        return f"output record at index {index} missing port"
    port_contract = output_port_contract(contract, port)
    if port_contract is None:
        return f"output record at index {index} uses unknown output port: {port}"
    record_type = record_payload.get("record_type")
    if record_type is not None:
        if not isinstance(record_type, str) or not record_type:
            return f"output record at index {index} has invalid record_type"
        if record_type not in port_contract.record_types:
            return (
                f"output record at index {index} has incompatible record_type for "
                f"{port}: {record_type}"
            )
    producer_port = record_payload.get("producer_port")
    if producer_port is not None:
        if not isinstance(producer_port, str) or producer_port != port:
            return (
                f"output record at index {index} producer_port does not match port: {producer_port}"
            )
    schema_version = record_payload.get("schema_version")
    if schema_version is not None and (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version <= 0
    ):
        return f"output record at index {index} has invalid schema_version"
    schema = record_payload.get("schema")
    if (
        isinstance(schema, str)
        and port_contract.schemas
        and schema not in port_contract.schemas
        and schema not in port_contract.selector_aliases
    ):
        return f"output record at index {index} has incompatible schema for {port}: {schema}"
    return None


def input_port_contract(contract: NodeContract, port: str) -> PortContract | None:
    canonical = _canonical_port(port)
    if not isinstance(canonical, str):
        return None
    exact = contract.input_ports.get(canonical)
    if exact is not None:
        return exact
    return _dynamic_input_port(contract, canonical)


def output_port_contract(contract: NodeContract, port: str) -> PortContract | None:
    canonical = _canonical_port(port)
    if not isinstance(canonical, str):
        return None
    exact = contract.output_ports.get(canonical)
    if exact is not None:
        return exact
    return _dynamic_output_port(contract, canonical)


def registered_node_contracts() -> dict[str, NodeContract]:
    return dict(DEFAULT_NODE_CONTRACTS.contracts)


def node_contract_summary(node_type: str | None, role: str | None = None) -> dict[str, Any] | None:
    if node_type is None:
        return None
    contract = DEFAULT_NODE_CONTRACTS.contract_for(node_type, role)
    if contract is None:
        return None
    return {
        "node_type": contract.node_type,
        "contract_version": contract.contract_version,
        "handler_type": contract.handler_type,
        "roles": sorted(contract.roles) if contract.roles is not None else None,
        "input_ports": {
            name: _port_summary(port) for name, port in sorted(contract.input_ports.items())
        },
        "output_ports": {
            name: _port_summary(port) for name, port in sorted(contract.output_ports.items())
        },
        "allowed_tools": sorted(contract.allowed_tools),
    }


def port_contract_summary(port: PortContract) -> dict[str, Any]:
    return _port_summary(port)


def binding_policy_for_edge(
    edge: dict[str, Any],
    target_port: PortContract | None,
) -> BindingPolicy:
    raw_policy = edge.get("binding_policy")
    if isinstance(raw_policy, str) and raw_policy in VALID_BINDING_POLICIES:
        return cast(BindingPolicy, raw_policy)
    if target_port is not None:
        if target_port.cardinality in {"many", "all"}:
            return "bind_all"
        if target_port.cardinality == "latest":
            return "bind_latest"
    return "bind_first"


def merge_bound_record_ids(
    policy: str,
    existing_ids: list[str],
    incoming_ids: list[str],
    *,
    supersedes_record_id: Any = None,
) -> list[str]:
    if not incoming_ids:
        return list(existing_ids)
    if policy in {"bind_first", "never_rebind"}:
        return list(existing_ids or incoming_ids[:1])
    if policy == "bind_latest":
        return [incoming_ids[-1]]
    if policy == "bind_all":
        output = list(existing_ids)
        for record_id in incoming_ids:
            if record_id not in output:
                output.append(record_id)
        return output
    if policy == "rebind_on_superseding":
        latest = incoming_ids[-1]
        if not existing_ids:
            return [latest]
        if isinstance(supersedes_record_id, str) and supersedes_record_id in existing_ids:
            return [
                latest if record_id == supersedes_record_id else record_id
                for record_id in existing_ids
            ]
        return list(existing_ids)
    return list(existing_ids or incoming_ids[:1])


def _port_summary(port: PortContract) -> dict[str, Any]:
    return {
        "record_types": sorted(port.record_types),
        "schemas": sorted(port.schemas),
        "required": port.required,
        "cardinality": port.cardinality,
    }


def _validate_declared_ports(
    node: dict[str, Any],
    field_name: str,
    direction: PortDirection,
    contract: NodeContract,
) -> str | None:
    raw_ports = node.get(field_name)
    if raw_ports is None:
        return None
    if not isinstance(raw_ports, list):
        return f"node {node.get('node_id')} {field_name} must be a list"
    for raw_port in cast(list[Any], raw_ports):
        if not isinstance(raw_port, dict):
            return f"node {node.get('node_id')} has malformed {direction} port"
        typed_port = cast(dict[str, Any], raw_port)
        port_name = typed_port.get("port")
        if not isinstance(port_name, str) or not port_name:
            return f"node {node.get('node_id')} has {direction} port without name"
        declared_direction = typed_port.get("direction")
        if isinstance(declared_direction, str) and declared_direction != direction:
            return f"node {node.get('node_id')} port {port_name} has wrong direction"
        port_contract = (
            input_port_contract(contract, port_name)
            if direction == "input"
            else output_port_contract(contract, port_name)
        )
        if port_contract is None:
            return f"node {node.get('node_id')} declares unknown {direction} port: {port_name}"
        schema = typed_port.get("schema")
        if (
            isinstance(schema, str)
            and port_contract.schemas
            and schema not in port_contract.schemas
            and schema not in port_contract.selector_aliases
        ):
            return f"node {node.get('node_id')} port {port_name} has incompatible schema: {schema}"
    return None


def _selector_compatibility_error(
    edge: dict[str, Any],
    edge_id: str,
    source: PortContract,
) -> str | None:
    selector = edge.get("accepted_record_selector")
    if not isinstance(selector, dict):
        return None
    typed_selector = cast(dict[str, Any], selector)
    raw_record_kinds = typed_selector.get("record_kinds")
    if isinstance(raw_record_kinds, list):
        selected = {value for value in cast(list[Any], raw_record_kinds) if isinstance(value, str)}
        accepted = source.record_types | source.schemas | source.selector_aliases
        if selected and selected.isdisjoint(accepted):
            return f"edge {edge_id} selector is incompatible with source output port"
    schema = typed_selector.get("schema")
    if isinstance(schema, str) and source.schemas and schema not in source.schemas:
        return f"edge {edge_id} schema selector is incompatible with source output port"
    return None


def _binding_policy_error(
    edge: dict[str, Any],
    edge_id: str,
    target: PortContract,
) -> str | None:
    raw_policy = edge.get("binding_policy")
    if raw_policy is None:
        return None
    if not isinstance(raw_policy, str) or raw_policy not in VALID_BINDING_POLICIES:
        return f"edge {edge_id} has unknown binding_policy: {raw_policy}"

    allowed_by_cardinality = {
        "one": {"bind_first", "never_rebind", "rebind_on_superseding"},
        "latest": {"bind_latest", "rebind_on_superseding"},
        "many": {"bind_all"},
        "all": {"bind_all"},
    }
    allowed = allowed_by_cardinality[target.cardinality]
    if raw_policy not in allowed:
        return (
            f"edge {edge_id} binding_policy {raw_policy} is incompatible with "
            f"target cardinality {target.cardinality}"
        )
    return None


def _prompt_hydration_policy_error(edge: dict[str, Any], edge_id: str) -> str | None:
    raw_policy = edge.get("prompt_hydration_policy")
    if raw_policy is None:
        return None
    if not isinstance(raw_policy, str) or raw_policy not in VALID_PROMPT_HYDRATION_POLICIES:
        return f"edge {edge_id} has unknown prompt_hydration_policy: {raw_policy}"
    return None


def _dynamic_input_port(contract: NodeContract, port: str) -> PortContract | None:
    if port.startswith("requirement_") and contract.node_type in {
        "worker",
        "verifier",
        "check",
        "planner",
        "gap_planner",
    }:
        return _port(port, "requirement_record", schemas=("Requirement", "RequirementRecord"))
    if port.startswith("context_") and contract.node_type in {"worker", "planner", "gap_planner"}:
        return _port(port, "artifact_reference", schemas=("ContextArtifact",))
    if port.startswith("source_record_") and contract.node_type == "join":
        return _port(
            port,
            "candidate",
            "verification_report",
            "check_result",
            "file_state",
            schemas=(
                "ImplementationCandidate",
                "VerificationReport",
                "CheckResult",
                "FileStateRecord",
            ),
        )
    return None


def _dynamic_output_port(contract: NodeContract, port: str) -> PortContract | None:
    if port.startswith("requirement_") and contract.node_type == "requirement":
        return _port(port, "requirement_record", schemas=("Requirement", "RequirementRecord"))
    return None


def _canonical_port(value: Any) -> Any:
    if value == "verification_result":
        return "verification_report"
    if value == "requirement":
        return "requirement_record"
    if value == "graph_patch":
        return "graph_patch_proposal"
    return value


def _port(
    name: str,
    *record_types: str,
    schemas: tuple[str, ...] = (),
    aliases: tuple[str, ...] = (),
    required: bool = True,
    cardinality: Literal["one", "many", "latest", "all"] = "one",
) -> PortContract:
    all_aliases = set(aliases) | set(record_types) | set(schemas) | {name}
    return PortContract(
        name=name,
        record_types=frozenset(record_types or (name,)),
        schemas=frozenset(schemas),
        selector_aliases=frozenset(all_aliases),
        required=required,
        cardinality=cardinality,
    )


def _node_contract(
    node_type: str,
    handler_type: HandlerType,
    *,
    roles: tuple[str, ...] | None = None,
    inputs: tuple[PortContract, ...] = (),
    outputs: tuple[PortContract, ...] = (),
    tools: tuple[str, ...] = (),
    aliases: tuple[str, ...] = (),
) -> NodeContract:
    return NodeContract(
        node_type=node_type,
        contract_version=1,
        handler_type=handler_type,
        roles=frozenset(roles) if roles is not None else None,
        input_ports={port.name: port for port in inputs},
        output_ports={port.name: port for port in outputs},
        allowed_tools=frozenset(tools),
        compatibility_aliases=frozenset(aliases),
    )


def _registry(contracts: tuple[NodeContract, ...]) -> NodeContractRegistry:
    by_type = {contract.node_type: contract for contract in contracts}
    aliases: dict[str, str] = {}
    for contract in contracts:
        for alias in contract.compatibility_aliases:
            aliases[alias] = contract.node_type
    return NodeContractRegistry(contracts=by_type, aliases=aliases)


_COMMON_EXEC_INPUTS = (
    _port("routine_snapshot", "routine_snapshot", schemas=("RoutineSnapshot",)),
    _port("base_snapshot", "routine_snapshot", schemas=("RoutineSnapshot",), required=False),
    _port("root_snapshot", "routine_snapshot", schemas=("RoutineSnapshot",), required=False),
    _port("prior_step_completion", "completion", schemas=("NodeCompletion",), required=False),
    _port("approval", "decision_record", schemas=("ApprovalDecision",), required=False),
    _port("file_state", "file_state", schemas=("FileStateRecord",), required=False),
)


DEFAULT_NODE_CONTRACTS = _registry(
    (
        _node_contract(
            "run_root",
            "controller",
            roles=("run_root",),
            outputs=(
                _port("run_context", "run_context", schemas=("RunContext",)),
                _port("routine_snapshot", "routine_snapshot", schemas=("RoutineSnapshot",)),
                _port("completion", "completion", schemas=("NodeCompletion",)),
            ),
            aliases=("root",),
        ),
        _node_contract(
            "routine_snapshot",
            "controller",
            roles=("routine_snapshot",),
            outputs=(
                _port("snapshot", "routine_snapshot", schemas=("RoutineSnapshot",)),
                _port("routine_snapshot", "routine_snapshot", schemas=("RoutineSnapshot",)),
                _port("artifact", "artifact_reference", schemas=("ContextArtifact",)),
            ),
            aliases=("artifact",),
        ),
        _node_contract(
            "requirement",
            "controller",
            roles=("requirement",),
            inputs=(
                _port("routine_snapshot", "routine_snapshot", schemas=("RoutineSnapshot",)),
                _port("analysis_summary", "analysis_summary", schemas=("AnalysisSummary",)),
            ),
            outputs=(
                _port("requirement_record", "requirement_record", schemas=("Requirement",)),
                _port("requirement", "requirement_record", schemas=("Requirement",)),
            ),
        ),
        _node_contract(
            "artifact_index",
            "controller",
            inputs=(
                _port("candidate", "candidate", schemas=("ImplementationCandidate",)),
                _port("file_state", "file_state", schemas=("FileStateRecord",)),
                _port("check_result", "check_result", schemas=("CheckResult",)),
                _port(
                    "verification_report", "verification_report", schemas=("VerificationReport",)
                ),
            ),
            outputs=(_port("artifact_reference", "artifact_reference"),),
            aliases=("artifact_index",),
        ),
        _node_contract(
            "planner",
            "agent",
            roles=("planner", "fan_out_reader", "fan_out_join"),
            inputs=(
                *_COMMON_EXEC_INPUTS,
                _port("requirement_record", "requirement_record", schemas=("Requirement",)),
                _port("analysis_summary", "analysis_summary", schemas=("AnalysisSummary",)),
                _port("graph_status_summary", "analysis_summary", schemas=("GraphStatusSummary",)),
                _port(
                    "verification_evidence",
                    "verification_report",
                    "check_result",
                    schemas=("VerificationReport", "CheckResult"),
                ),
                _port(
                    "verification_report", "verification_report", schemas=("VerificationReport",)
                ),
                _port("check_result", "check_result", schemas=("CheckResult",)),
                _port("region_summary", "analysis_summary", schemas=("AnalysisSummary",)),
                _port(
                    "accepted_file_state",
                    "file_state",
                    schemas=("FileStateRecord",),
                    cardinality="latest",
                ),
                _port("outstanding_failures", "failure_record", schemas=("FailureRecord",)),
                _port(
                    "session_carryover",
                    "analysis_summary",
                    schemas=("AnalysisSummary",),
                    required=False,
                ),
                _port("reader_outputs", "fan_out_inputs", schemas=("FanOutInputs",)),
            ),
            outputs=(
                _port(
                    "graph_patch_proposal",
                    "graph_patch_proposal",
                    schemas=("GraphPatch",),
                    required=False,
                ),
                _port(
                    "graph_patch",
                    "graph_patch_proposal",
                    schemas=("GraphPatch",),
                    required=False,
                ),
                _port(
                    "file_state",
                    "file_state",
                    schemas=("FileStateRecord",),
                    aliases=("accepted_file_state",),
                    required=False,
                ),
                _port(
                    "planning_summary",
                    "analysis_summary",
                    schemas=("AnalysisSummary",),
                    required=False,
                ),
                _port(
                    "analysis_summary",
                    "analysis_summary",
                    schemas=("AnalysisSummary",),
                    required=False,
                ),
                _port(
                    "region_summary",
                    "analysis_summary",
                    schemas=("AnalysisSummary",),
                    required=False,
                ),
                _port(
                    "reader_output",
                    "fan_out_inputs",
                    schemas=("FanOutInputs",),
                    required=False,
                ),
                _port(
                    "fan_out_inputs",
                    "fan_out_inputs",
                    schemas=("FanOutJoinedInputs",),
                    required=False,
                ),
                _port("completion", "completion", schemas=("NodeCompletion",), required=False),
            ),
            tools=(
                "create_work_region",
                "attach_verifier",
                "attach_check",
                "create_gap_planner",
                "create_join",
                "request_gate",
                "retire_or_supersede",
                "submit_graph_patch",
            ),
        ),
        _node_contract(
            "gap_planner",
            "agent",
            roles=("gap_planner",),
            inputs=(
                *_COMMON_EXEC_INPUTS,
                _port(
                    "verification_evidence",
                    "verification_report",
                    "check_result",
                    schemas=("VerificationReport", "CheckResult"),
                ),
                _port(
                    "verification_report", "verification_report", schemas=("VerificationReport",)
                ),
                _port("check_result", "check_result", schemas=("CheckResult",)),
                _port("candidate", "candidate", schemas=("ImplementationCandidate",)),
                _port("file_state", "file_state", schemas=("FileStateRecord",)),
                _port("requirement_record", "requirement_record", schemas=("Requirement",)),
                _port("graph_status_summary", "analysis_summary", schemas=("GraphStatusSummary",)),
            ),
            outputs=(
                _port(
                    "gap_plan",
                    "gap_plan",
                    schemas=("GapPlan", "GapClassification"),
                    aliases=("gap_analysis",),
                    required=False,
                ),
                _port(
                    "gap_classification",
                    "gap_classification",
                    "classified_gap",
                    schemas=("GapClassification",),
                    aliases=("gap_analysis", "gap_plan"),
                    required=False,
                ),
                _port(
                    "classified_gap",
                    "classified_gap",
                    schemas=("GapClassification",),
                    aliases=("gap_analysis", "gap_plan"),
                    required=False,
                ),
                _port(
                    "graph_patch_proposal",
                    "graph_patch_proposal",
                    schemas=("GraphPatch",),
                    required=False,
                ),
                _port(
                    "graph_patch",
                    "graph_patch_proposal",
                    schemas=("GraphPatch",),
                    required=False,
                ),
                _port(
                    "file_state",
                    "file_state",
                    schemas=("FileStateRecord",),
                    aliases=("accepted_file_state",),
                    required=False,
                ),
                _port(
                    "planning_summary",
                    "analysis_summary",
                    schemas=("AnalysisSummary",),
                    required=False,
                ),
                _port("completion", "completion", schemas=("NodeCompletion",), required=False),
            ),
            tools=(
                "create_corrective_region",
                "attach_verifier",
                "attach_check",
                "request_gate",
                "submit_graph_patch",
            ),
        ),
        _node_contract(
            "worker",
            "agent",
            roles=("builder", "discovery", "implementer", "fixer", "reviewer", "summarizer"),
            inputs=(
                *_COMMON_EXEC_INPUTS,
                _port(
                    "classified_gap",
                    "classified_gap",
                    schemas=("GapClassification",),
                    aliases=("gap_analysis",),
                ),
                _port("fan_out_inputs", "fan_out_inputs", schemas=("FanOutJoinedInputs",)),
                _port(
                    "candidate", "candidate", schemas=("ImplementationCandidate",), required=False
                ),
                _port(
                    "verification_report",
                    "verification_report",
                    schemas=("VerificationReport",),
                    required=False,
                ),
                _port("check_result", "check_result", schemas=("CheckResult",), required=False),
                _port(
                    "analysis_summary",
                    "analysis_summary",
                    schemas=("AnalysisSummary",),
                    required=False,
                ),
                _port("artifact_reference", "artifact_reference", required=False),
            ),
            outputs=(
                _port(
                    "candidate",
                    "candidate",
                    schemas=("ImplementationCandidate",),
                    aliases=("output",),
                ),
                _port(
                    "file_state",
                    "file_state",
                    schemas=("FileStateRecord",),
                    aliases=("accepted_file_state",),
                ),
                _port(
                    "analysis_summary",
                    "analysis_summary",
                    schemas=("AnalysisSummary",),
                    required=False,
                ),
                _port(
                    "classified_gap",
                    "classified_gap",
                    schemas=("GapClassification",),
                    aliases=("gap_analysis",),
                    required=False,
                ),
                _port(
                    "gap_classification",
                    "classified_gap",
                    schemas=("GapClassification",),
                    aliases=("gap_analysis",),
                    required=False,
                ),
                _port(
                    "region_summary",
                    "analysis_summary",
                    schemas=("AnalysisSummary",),
                    required=False,
                ),
                _port("completion", "completion", schemas=("NodeCompletion",), required=False),
            ),
        ),
        _node_contract(
            "verifier",
            "agent",
            roles=("verifier", "reviewer"),
            inputs=(
                *_COMMON_EXEC_INPUTS,
                _port("candidate_under_test", "candidate", schemas=("ImplementationCandidate",)),
                _port("candidate", "candidate", schemas=("ImplementationCandidate",)),
                _port("requirement_record", "requirement_record", schemas=("Requirement",)),
                _port("check_result", "check_result", schemas=("CheckResult",), required=False),
                _port("artifact_reference", "artifact_reference", required=False),
            ),
            outputs=(
                _port(
                    "verification_report",
                    "verification_report",
                    schemas=("VerificationReport",),
                    aliases=("verification", "verification_result"),
                ),
                _port(
                    "file_state",
                    "file_state",
                    schemas=("FileStateRecord",),
                    aliases=("accepted_file_state",),
                    required=False,
                ),
                _port(
                    "region_summary",
                    "analysis_summary",
                    schemas=("RegionSummary",),
                    required=False,
                ),
                _port("completion", "completion", schemas=("NodeCompletion",), required=False),
            ),
        ),
        _node_contract(
            "summarizer",
            "agent",
            inputs=(
                _port(
                    "source_records",
                    "candidate",
                    "verification_report",
                    "check_result",
                    "file_state",
                    cardinality="many",
                ),
            ),
            outputs=(
                _port("analysis_summary", "analysis_summary", schemas=("AnalysisSummary",)),
                _port(
                    "file_state",
                    "file_state",
                    schemas=("FileStateRecord",),
                    aliases=("accepted_file_state",),
                    required=False,
                ),
            ),
        ),
        _node_contract(
            "check",
            "deterministic_command",
            roles=None,
            inputs=(
                *_COMMON_EXEC_INPUTS,
                _port("candidate_under_test", "candidate", schemas=("ImplementationCandidate",)),
                _port("candidate", "candidate", schemas=("ImplementationCandidate",)),
                _port(
                    "verification_evidence",
                    "verification_report",
                    "check_result",
                    schemas=("VerificationReport", "CheckResult"),
                ),
                _port(
                    "requirement_record",
                    "requirement_record",
                    schemas=("Requirement",),
                    required=False,
                ),
            ),
            outputs=(
                _port("check_result", "check_result", schemas=("CheckResult",)),
                _port("completion", "completion", schemas=("NodeCompletion",), required=False),
            ),
        ),
        _node_contract(
            "join",
            "controller",
            roles=("fan_out_join", "join"),
            inputs=(
                _port(
                    "source_records",
                    "candidate",
                    "verification_report",
                    "check_result",
                    "file_state",
                    cardinality="many",
                ),
            ),
            outputs=(_port("join_result", "join_result", schemas=("JoinResult",)),),
        ),
        _node_contract(
            "final_gate",
            "controller",
            roles=("invariant_gate", "final_gate"),
            inputs=(
                _port(
                    "verification_evidence",
                    "verification_report",
                    "check_result",
                    schemas=("VerificationReport", "CheckResult"),
                ),
                _port("check_result", "check_result", schemas=("CheckResult",)),
            ),
            outputs=(
                _port(
                    "completion_decision", "completion_decision", schemas=("CompletionDecision",)
                ),
            ),
        ),
        _node_contract(
            "human_gate",
            "human",
            roles=None,
            inputs=(_port("decision_request", "decision_request", schemas=("DecisionRequest",)),),
            outputs=(
                _port("decision_record", "decision_record", schemas=("DecisionRecord",)),
                _port("approval", "decision_record", schemas=("ApprovalDecision",)),
                _port("decision", "decision_record", schemas=("DecisionRecord",)),
            ),
            aliases=("gate",),
        ),
        _node_contract(
            "authority_request",
            "human",
            inputs=(
                _port(
                    "authority_request_record",
                    "authority_request_record",
                    schemas=("AuthorityRequest",),
                ),
            ),
            outputs=(
                _port("authority_decision", "authority_decision", schemas=("AuthorityDecision",)),
            ),
        ),
        _node_contract(
            "recovery",
            "controller",
            roles=None,
            inputs=(_port("failure_record", "failure_record", schemas=("FailureRecord",)),),
            outputs=(
                _port("recovery_plan", "recovery_plan", schemas=("RecoveryPlan",)),
                _port(
                    "graph_patch_proposal",
                    "graph_patch_proposal",
                    schemas=("GraphPatch",),
                    required=False,
                ),
            ),
            aliases=("appeal", "oversight", "review", "task_projection", "file_state", "session"),
        ),
    )
)
