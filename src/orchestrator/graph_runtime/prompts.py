"""Pure prompt and packet assembly helpers for graph dispatch."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from orchestrator.artifacts import ArtifactStore, StoredArtifactRef
from orchestrator.graph import (
    accepted_declared_batch_ids,
    decision_answer_schema,
    planner_generation_budget,
    planner_generations_view,
    edges_view,
    evidence_closure_for_node,
    environment_failures_view,
    execution_attempts_view,
    file_state_records_view,
    input_bindings_view,
    last_deferred_reasons_view,
    node_kinds_view,
    node_payload_view,
    node_states_view,
    node_task_regions_view,
    planner_session_carryovers_view,
    planner_sessions_view,
    planner_freshness_packet_view,
    planner_patch_facts_view,
    record_payloads_view,
    ready_nodes_view,
    routine_snapshot_dynamic_feature_view,
    semantic_schema_declarations_view,
    correction_superseded_task_region_id,
    thaw_json,
    DEFAULT_NODE_CONTRACTS,
    EventEnvelope,
    GraphProjection,
    resolve_decision_context,
    resolve_decision_applicability,
)
from orchestrator.graph import resolve_check_command_definition
from orchestrator.graph import (
    FileStateRecord,
    GapClassificationRecord,
    InputBindingProjection,
)
from orchestrator.graph import PLANNER_OPS
from orchestrator.graph_runtime.errors import InvalidExecutionContractError
from orchestrator.graph_runtime.horizon_templates import horizon_region_templates

if TYPE_CHECKING:
    from orchestrator.graph_runtime.dispatch import GraphDispatchContext


MAX_GRAPH_PROMPT_CHARS = 60_000
MAX_GRAPH_JSON_SECTION_CHARS = 36_000
MAX_GRAPH_PROMPT_FIELD_CHARS = 8_000


async def hydrate_artifact_excerpt(
    store: ArtifactStore,
    ref: StoredArtifactRef,
    *,
    max_chars: int = MAX_GRAPH_PROMPT_FIELD_CHARS,
) -> str:
    """Read a verified artifact through the injected store and bound its text excerpt."""
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")
    content = await store.read(ref)
    return content.decode(ref.encoding or "utf-8", errors="replace")[:max_chars]


def _bounded_prompt(prompt: str) -> str:
    if len(prompt) <= MAX_GRAPH_PROMPT_CHARS:
        return prompt
    omitted = len(prompt) - MAX_GRAPH_PROMPT_CHARS
    suffix = f"\n[graph prompt truncated; omitted_chars={omitted}]"
    return f"{prompt[: MAX_GRAPH_PROMPT_CHARS - len(suffix)]}{suffix}"


def _bounded_json(value: object, *, max_chars: int = MAX_GRAPH_JSON_SECTION_CHARS) -> str:
    encoded = json.dumps(value, sort_keys=True)
    if len(encoded) <= max_chars:
        return encoded
    preview_chars = max(0, max_chars - 160)
    return json.dumps(
        {
            "truncated": True,
            "original_chars": len(encoded),
            "preview": encoded[:preview_chars],
        },
        sort_keys=True,
    )


def _bounded_text(value: object, *, max_chars: int = MAX_GRAPH_PROMPT_FIELD_CHARS) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    suffix = f"\n[truncated; omitted_chars={omitted}]"
    return f"{text[: max_chars - len(suffix)]}{suffix}"


def _verifier_packet(context: GraphDispatchContext) -> dict[str, Any]:
    node = context.node_payload
    _validate_verifier_contract(node)
    citations = _evaluated_record_citations(context)
    candidate_record_ids = _unique_record_ids(
        [
            *_bound_record_ids_for_ports(
                context,
                ("candidate_under_test", "candidate", "semantic_artifact"),
            ),
            *citations.get("candidate_record_ids", []),
        ]
    )
    requirement_record_ids = _bound_record_ids_for_ports(
        context,
        tuple(
            port
            for port in sorted(
                input_bindings_view(context.graph_projection).get(context.node_id, {})
            )
            if port == "requirement" or port.startswith("requirement_")
        ),
    )
    return {
        "node_id": context.node_id,
        "task_region_id": node.get("task_region_id", context.node_id),
        "candidate_id": _candidate_id_for_verifier(context),
        "semantic_stage": node.get("semantic_stage"),
        "semantic_schema_id": node.get("semantic_schema_id"),
        "semantic_schema_version": node.get("semantic_schema_version"),
        "objective": _verifier_objective(node),
        "acceptance_obligations": _verifier_acceptance_obligations(node),
        "requirements": list(context.requirements),
        "rubric": _effective_verifier_rubric(node),
        "candidate_evidence": {
            "bound_candidate_or_artifact_record_ids": candidate_record_ids,
        },
        "requirement_evidence": {
            "bound_requirement_ids": _string_list(node.get("bound_requirement_ids")),
            "resolved_requirements": list(context.requirements),
            "bound_requirement_record_ids": requirement_record_ids,
        },
        "bound_records": _planner_evidence(
            context,
            context.graph_projection,
        )["bound_records"],
        "cited_evidence_records": _hydrated_cited_records(
            context.graph_projection,
            _indirect_cited_record_ids(context, citations),
        ),
        "evaluated_record_citations": citations,
        "required_report_schema": {
            "record_kind": "verification",
            "port": "verification_report",
            "schema": "VerificationReport",
            "required_fields": [
                "candidate_id",
                "outcome",
                "value.outcome",
                "value.grades",
                "evidence.evaluated_record_ids",
            ],
            "outcome_values": ["passed", "failed"],
        },
    }


def _validate_verifier_contract(node: dict[str, Any]) -> None:
    if node.get("semantic_stage") != "plan_verification":
        return
    missing: list[str] = []
    objective = node.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        missing.append("objective")
    acceptance = _verifier_acceptance_obligations(node)
    if not acceptance or any(not obligation.strip() for obligation in acceptance):
        missing.append("acceptance")
    if missing:
        fields = ", ".join(missing)
        raise InvalidExecutionContractError(
            "plan_verification verifier requires a complete stage contract; "
            f"missing or empty fields: {fields}"
        )


def _verifier_objective(node: dict[str, Any]) -> str | None:
    objective = node.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        return None
    return _bounded_text(objective)


def _verifier_acceptance_obligations(node: dict[str, Any]) -> list[str]:
    return _string_list(node.get("acceptance"))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in cast(list[Any], value) if isinstance(item, str)]


def _effective_verifier_rubric(node: dict[str, Any]) -> list[Any]:
    authored = node.get("rubric")
    if isinstance(authored, list) and authored:
        return list(cast(list[Any], authored))
    if node.get("semantic_stage") != "plan_verification":
        return []
    return [
        "Coverage: the plan covers the stated objective and every bound requirement.",
        "Feasibility: the proposed work is technically executable within the declared scope and constraints.",
        "Obligations: the plan explicitly addresses every acceptance obligation.",
        "Evidence: plan claims are grounded in the exact bound semantic artifact/candidate and requirement evidence.",
        "Downstream implementation plan: the plan identifies implementable work and validation steps; assess the plan itself without requiring implementation or downstream tests to be complete at this stage.",
    ]


def _summarizer_packet(context: GraphDispatchContext) -> dict[str, Any]:
    node = context.node_payload
    return {
        "node_id": context.node_id,
        "task_region_id": node.get("task_region_id", context.node_id),
        "source_records": _planner_evidence(
            context,
            context.graph_projection,
        )["bound_records"].get("source_records", []),
        "required_summary_schema": {
            "record_kind": "output",
            "record_type": "analysis_summary",
            "port": "analysis_summary",
            "schema": "AnalysisSummary",
            "required_fields": [
                "summary",
                "source_record_ids",
                "lossiness",
                "omitted_details",
            ],
            "lossiness_values": ["lossless", "lossy"],
        },
    }


def _decision_packet(context: GraphDispatchContext) -> dict[str, Any]:
    """Render only model-facing judgment inputs for an activated decision."""
    applicability = resolve_decision_applicability(context.graph_projection, context.node_id)
    if applicability is None:
        raise InvalidExecutionContractError("decision packet requires decision-v1 authority")
    resolved = resolve_decision_context(context.graph_projection, context.node_id)
    protected = resolved.protected_question_context()
    _schema_id, _schema_version, _schema_sha256, schema = decision_answer_schema(
        cast(Any, applicability.family)
    )
    if applicability.family == "discovery_brief":
        return {
            "question": protected["question"],
            "bound_evidence": protected["bound_evidence"],
            "available_choices": protected["scope_choices"],
            "answer_schema": schema,
        }
    if applicability.family == "implementation_plan":
        return {
            "question": protected["question"],
            "bound_evidence": {
                "requirements": protected["requirements"],
                "plan_contract": protected["plan_contract"],
                "check_policy": protected["check_policy"],
                "source_references": protected["source_references"],
            },
            "available_choices": protected["check_policy"]["available_bindings"],
            "answer_schema": schema,
        }
    if applicability.family == "correction_decision":
        return {
            "question": protected["question"],
            "bound_evidence": {
                "scope": protected["scope"],
                "selected_batch": protected["selected_batch"],
                "accepted_baseline": protected["accepted_baseline"],
                "requirement_aliases": protected["requirement_aliases"],
                "evidence_aliases": protected["evidence_aliases"],
                "planning_policy": {
                    "planning_horizon": protected["planning_horizon"],
                    "remaining_horizons": protected["remaining_horizons"],
                },
                "check_policy": protected["check_policy"],
            },
            "available_choices": protected["available_dispositions"],
            "answer_schema": schema,
        }
    if applicability.family == "verification_decision":
        return {
            "question": protected["question"],
            "bound_evidence": {
                "semantic_stage": protected["semantic_stage"],
                "candidate_record_ids": protected["candidate_record_ids"],
                "obligations": protected["obligations"],
                "mandatory_check_receipts": protected["mandatory_check_receipts"],
                "evidence_aliases": protected["evidence_aliases"],
                "bound_records": _planner_evidence(context, context.graph_projection)[
                    "bound_records"
                ],
                "source_references": protected["source_references"],
            },
            "available_choices": ["A", "B", "C", "D", "F"],
            "answer_schema": schema,
        }
    aliases = list(cast(dict[str, str], protected["requirement_aliases"]))
    requirements = [
        {"alias": alias, "text": _bounded_text(context.requirements[index])}
        for index, alias in enumerate(aliases)
        if index < len(context.requirements)
    ]
    return {
        "question": protected["question"],
        "bound_evidence": {
            "selected_batch": protected["selected_batch"],
            "requirements": requirements,
            "check_policy": protected["check_policy"],
            "planning_policy": {
                "planning_horizon": protected["planning_horizon"],
                "remaining_horizons": protected["remaining_horizons"],
            },
        },
        "available_choices": protected["available_dispositions"],
        "answer_schema": schema,
    }


def _prompt_for_node(context: GraphDispatchContext) -> str:
    node = context.node_payload
    if context.node_kind == "verifier":
        applicability = resolve_decision_applicability(context.graph_projection, context.node_id)
        if applicability is not None and applicability.family == "verification_decision":
            packet = _decision_packet(context)
            return _bounded_prompt(
                "\n".join(
                    [
                        "Verification decision packet:",
                        _bounded_json(packet),
                        "",
                        "Return exactly one finding for every obligation through submit(outputs={decision: ...}).",
                        "Use only the supplied obligation and evidence aliases; the runtime derives outcome, candidate identity, and report provenance.",
                    ]
                )
            )
        packet = _verifier_packet(context)
        return _bounded_prompt(
            "\n".join(
                [
                    f"Verify task region {node.get('task_region_id', context.node_id)}.",
                    f"Candidate: {_candidate_id_for_verifier(context)}",
                    f"Semantic stage: {_bounded_text(packet['semantic_stage'])}",
                    f"Objective: {_bounded_text(packet['objective'])}",
                    "Acceptance obligations: "
                    + _bounded_json(
                        packet["acceptance_obligations"],
                        max_chars=MAX_GRAPH_PROMPT_FIELD_CHARS,
                    ),
                    "Rubric: "
                    + _bounded_json(
                        packet["rubric"],
                        max_chars=MAX_GRAPH_PROMPT_FIELD_CHARS,
                    ),
                    "Perform an independent review using only the exact bound candidate/artifact "
                    "and requirement evidence in the packet.",
                    "For plan_verification, grade the plan's coverage, feasibility, obligations, "
                    "evidence, and downstream implementation plan. Do not require completed "
                    "implementation or completed downstream tests.",
                    "",
                    "Verifier context packet:",
                    _bounded_json(packet),
                ]
            )
        )
    if context.node_kind == "summarizer":
        packet = _summarizer_packet(context)
        return _bounded_prompt(
            "\n".join(
                [
                    f"Summarize source records for {node.get('task_region_id', context.node_id)}.",
                    "",
                    "Summarizer context packet:",
                    _bounded_json(packet),
                ]
            )
        )
    if context.node_kind == "planner":
        applicability = resolve_decision_applicability(context.graph_projection, context.node_id)
        if applicability is not None and applicability.family in {
            "discovery_brief",
            "batch_decision",
            "correction_decision",
        }:
            packet = _decision_packet(context)
            return _bounded_prompt(
                "\n".join(
                    [
                        "Decision packet:",
                        _bounded_json(packet),
                        "",
                        "Return one typed answer through submit(outputs={decision: ...}).",
                        "Use the supplied question, bounded evidence, available choices, and exact generated answer schema.",
                        "The runtime owns graph construction and all bookkeeping consequences.",
                    ]
                )
            )
        packet = _planner_packet(context)
        if _is_reliable_plan_context(context):
            reliable_lines = [
                "Planner mutation contract:",
                "- This is a reliable-plan semantic decision. Describe only the current operation; the controller constructs the complete authorized horizon.",
                "- Call construct_reliable_plan_region exactly once with operation_key, scope, objective, requirement IDs, dependencies, acceptance, checks, and rubric.",
                "- Use only requirement IDs from bound_requirements and only dependency IDs listed in reliable_plan_options.",
                "- Use only check bindings listed in reliable_plan_options. If no binding is available, provide a concrete command_definition from the current task contract; do not invent a command.",
                "- Use current_graph_position from the packet as base_graph_position and use a stable patch_id for this attempt.",
                "- Wait for accepted construction feedback, then call plain submit. Do not submit raw operations or construct topology, evidence wiring, assignments, checks, or continuations yourself.",
                "",
                "Reliable-plan semantic contract:",
                _bounded_json(packet["reliable_plan_contract"]),
                "Reliable-plan options from current state:",
                _bounded_json(packet["reliable_plan_options"]),
            ]
            return _bounded_prompt(
                "\n".join(
                    [
                        "Planner context packet:",
                        _bounded_json(packet),
                        "",
                        *reliable_lines,
                    ]
                )
            )
        return _bounded_prompt(
            "\n".join(
                [
                    "Planner context packet:",
                    _bounded_json(packet),
                    "",
                    "Planner mutation contract:",
                    "- Your job is to propose future graph structure, not edit repository files.",
                    "- For reliable_plan_contract, call construct_reliable_plan_region once with scope, objective, requirement IDs, dependencies, acceptance, checks, and rubric; the controller constructs the entire authorized horizon.",
                    "- Prefer planner-facing graph macros; low-level ops are the internal expansion format.",
                    "- Mutate the graph only through submit_graph_patch or macro-backed patch envelopes.",
                    "- Use current_graph_position from the packet as base_graph_position.",
                    "- Use node_id from the packet as planner identity; dispatch will bind proposer evidence.",
                    "- When using raw fallback ops, choose only from allowed_patch_operations.",
                    "- Use horizon_region_templates only for non-reliable-plan compatibility authoring and gap recovery.",
                    "- Read frontier, evidence, open_planner_proposals, accepted_planner_patches, and patch_rejections before proposing.",
                    "- If dynamic_feature is present, ground generated worker, verifier, gap-analysis, corrective-work, and final invariant regions in those feature inputs.",
                    "- Check nodes must include command_definition or command_binding. For dynamic_feature semantic checks, use command_binding='dynamic_feature_hidden_oracle' only when the packet's available_check_bindings includes it; otherwise provide an explicit batch-scoped command_definition. The reliable-plan final acceptance check is controller-owned and must remain distinct; do not use dynamic_feature_acceptance as a semantic-region binding.",
                    "- For reliable-plan dependencies, use only previously materialized accepted batch IDs. Use [] for the first or only batch; never use the current scope, node IDs, record IDs, or requirement IDs.",
                    "- Every required check, including final invariant checks, must have a failure continuation: bind failed check_result evidence into a gap planner or corrective-work path so a failed check cannot leave the graph quiescent with no schedulable recovery node.",
                    "- For gap planners, follow gap_analysis_contract and prefer corrective_work_region for corrective worker/verifier patches.",
                    "- A write worker cannot evade declared-batch semantics by using corrective_work. Use effectful_batch for implementation correction; use semantic_plan_revision only with exact failed SemanticArtifact and plan-verification record/topology facts from the packet.",
                    "- For gap planners, gap_analysis_obligations are blocking; do not submit a no-op patch while any obligation is present.",
                    "- Gap planners must call submit_graph_patch even when no corrective mutation is safe; use a no-op patch with ops: [] for no-gap decisions.",
                    "- If feedback says the patch is stale, malformed, or rejected, submit a corrected patch.",
                    "- Call plain submit only after submit_graph_patch feedback says the patch was accepted.",
                    "- Do not append graph events directly and do not create source/test/doc edits from this planner node.",
                    "",
                    "Allowed patch operations:",
                    _bounded_json(packet["allowed_patch_operations"]),
                    "Standard horizon region templates:",
                    _bounded_json(packet["horizon_region_templates"]),
                    "Compact patch examples:",
                    _bounded_json(packet["patch_examples"]),
                ]
            )
        )
    return _worker_like_prompt(context)


def _prompt_summary_for_node(context: GraphDispatchContext) -> dict[str, Any]:
    packet = _packet_for_prompt_summary(context)
    summary: dict[str, Any] = {
        "node_id": context.node_id,
        "node_kind": context.node_kind,
        "node_role": context.node_role,
        "packet_type": _packet_type_for_context(context),
        "packet_keys": sorted(packet),
        "prompt_sections": _prompt_sections_for_context(context),
        "available_tools": _available_tools_for_context(context) or [],
        "lease": {
            "lease_id": context.lease_id,
            "generation": context.lease_generation,
            "execution_id": context.execution_id,
            "base_snapshot_id": context.base_snapshot_id,
        },
        "input_ports": _prompt_summary_input_ports(context),
        "bound_records": _prompt_summary_bound_records(context),
    }
    task_region_id = context.node_payload.get("task_region_id")
    if isinstance(task_region_id, str):
        summary["task_region_id"] = task_region_id
    command_definition = context.node_payload.get("command_definition")
    if isinstance(command_definition, dict):
        summary["command_definition"] = dict(cast(dict[str, Any], command_definition))
    if "required_report_schema" in packet:
        summary["required_report_schema"] = packet["required_report_schema"]
    if "required_summary_schema" in packet:
        summary["required_summary_schema"] = packet["required_summary_schema"]
    if "gap_analysis_contract" in packet:
        summary["gap_analysis_contract"] = packet["gap_analysis_contract"]
    return summary


def _packet_for_prompt_summary(context: GraphDispatchContext) -> dict[str, Any]:
    if context.node_kind == "verifier":
        return _verifier_packet(context)
    if context.node_kind == "summarizer":
        return _summarizer_packet(context)
    if context.node_kind == "planner":
        applicability = resolve_decision_applicability(context.graph_projection, context.node_id)
        if applicability is not None and applicability.family in {
            "discovery_brief",
            "batch_decision",
            "correction_decision",
        }:
            return _decision_packet(context)
        return _planner_packet(context)
    if context.node_kind == "check":
        return {
            "node_id": context.node_id,
            "task_region_id": context.node_payload.get("task_region_id", context.node_id),
            "command_definition": resolve_check_command_definition(
                context.node_payload,
                [],
                projection=context.graph_projection,
            ),
            "bound_records": _planner_evidence(
                context,
                context.graph_projection,
            )["bound_records"],
        }
    packet: dict[str, Any] = {
        "node_id": context.node_id,
        "task_region_id": context.node_payload.get("task_region_id", context.node_id),
        "worker_authority": _worker_authority_packet(context),
    }
    if context.node_kind == "worker":
        packet["work_contract"] = _worker_contract_packet(context)
        packet["bound_records"] = _planner_evidence(context, context.graph_projection)[
            "bound_records"
        ]
    return packet


def _packet_type_for_context(context: GraphDispatchContext) -> str:
    applicability = resolve_decision_applicability(context.graph_projection, context.node_id)
    if applicability is not None and applicability.family in {
        "discovery_brief",
        "batch_decision",
        "correction_decision",
        "verification_decision",
    }:
        return "decision_packet"
    if context.node_kind == "planner" and context.node_role == "gap_planner":
        return "gap_planner"
    return context.node_kind


def _prompt_sections_for_context(context: GraphDispatchContext) -> list[str]:
    if context.node_kind == "verifier":
        return ["rubric", "verifier_context_packet"]
    if context.node_kind == "summarizer":
        return ["summarizer_context_packet"]
    if context.node_kind == "planner":
        applicability = resolve_decision_applicability(context.graph_projection, context.node_id)
        if applicability is not None and applicability.family in {
            "discovery_brief",
            "batch_decision",
            "correction_decision",
        }:
            return [
                "decision_question",
                "bound_evidence",
                "available_choices",
                "answer_schema",
                "typed_submit",
            ]
        if _is_reliable_plan_context(context):
            return [
                "planner_context_packet",
                "reliable_plan_contract",
                "reliable_plan_options",
                "plain_submit_completion",
            ]
        sections = [
            "planner_context_packet",
            "planner_mutation_contract",
            "allowed_patch_operations",
            "horizon_region_templates",
            "patch_examples",
        ]
        if context.node_role == "gap_planner":
            sections.append("gap_analysis_contract")
        return sections
    if context.node_kind == "check":
        return ["check_command", "bound_evidence"]
    if context.node_kind == "worker":
        return ["worker_instruction", "work_contract", "bound_evidence", "worker_authority"]
    return ["worker_instruction", "worker_authority"]


def _prompt_summary_input_ports(context: GraphDispatchContext) -> dict[str, list[str]]:
    bindings = input_bindings_view(context.graph_projection).get(context.node_id, {})
    input_ports: dict[str, list[str]] = {}
    for port, binding in sorted(bindings.items()):
        input_ports[port] = list(binding.record_ids)
    return input_ports


def _prompt_summary_bound_records(context: GraphDispatchContext) -> dict[str, list[dict[str, Any]]]:
    evidence = _planner_evidence(context, context.graph_projection)
    rendered_prompt = _prompt_for_node(context)
    compact: dict[str, list[dict[str, Any]]] = {}
    for port, records in evidence["bound_records"].items():
        compact[port] = [
            _compact_prompt_bound_record(record, rendered_prompt=rendered_prompt)
            for record in records
        ]
    return compact


def _compact_prompt_bound_record(record: dict[str, Any], *, rendered_prompt: str) -> dict[str, Any]:
    compact = {
        key: record[key]
        for key in ("record_id", "record_kind", "hydration_policy", "status")
        if key in record
    }
    payload = record.get("record_payload")
    if isinstance(payload, dict):
        typed_payload = cast(dict[str, Any], payload)
        for key in ("record_type", "schema", "producer_node_id", "port"):
            value = typed_payload.get(key)
            if isinstance(value, str):
                compact[key] = value
    reference = record.get("record_reference")
    if isinstance(reference, dict):
        compact["record_reference"] = dict(cast(dict[str, Any], reference))
    summary = record.get("record_summary")
    if isinstance(summary, dict):
        compact["record_summary"] = dict(cast(dict[str, Any], summary))
    if record.get("status") == "missing":
        compact["prompt_disposition"] = "missing"
    elif record.get("omitted_from_prompt") is True:
        compact["omitted_from_prompt"] = True
        compact["prompt_disposition"] = "omitted"
    else:
        full_record = json.dumps(record, sort_keys=True)
        if _json_fragment_is_visible(full_record, rendered_prompt):
            if "record_summary" in record:
                compact["prompt_disposition"] = "summarized"
            elif "record_reference" in record:
                compact["prompt_disposition"] = "referenced"
            elif "record_payload" in record:
                compact["prompt_disposition"] = "hydrated"
            else:
                compact["prompt_disposition"] = "missing"
        elif _record_prefix_is_visible(record, full_record, rendered_prompt):
            compact["prompt_disposition"] = "truncated"
        else:
            compact["omitted_from_prompt"] = True
            compact["prompt_disposition"] = "omitted"
    return compact


def _json_fragment_is_visible(fragment: str, prompt: str) -> bool:
    return fragment in prompt or _escaped_json_fragment(fragment) in prompt


def _record_prefix_is_visible(record: dict[str, Any], encoded_record: str, prompt: str) -> bool:
    record_id = record.get("record_id")
    if not isinstance(record_id, str):
        return False
    record_id_field = f'"record_id": {json.dumps(record_id)}'
    field_end = encoded_record.find(record_id_field)
    if field_end < 0:
        return False
    prefix = encoded_record[: field_end + len(record_id_field)]
    return _json_fragment_is_visible(prefix, prompt)


def _escaped_json_fragment(fragment: str) -> str:
    return json.dumps(fragment)[1:-1]


def _worker_like_prompt(context: GraphDispatchContext) -> str:
    node = context.node_payload
    title = str(node.get("title") or node.get("objective") or context.node_id)
    task_context = node.get("task_context")
    context_lines = [str(task_context)] if isinstance(task_context, str) and task_context else []

    if context.node_kind == "worker":
        context_lines.append(f"work_contract: {_bounded_json(_worker_contract_packet(context))}")
        context_lines.append(
            "bound_evidence: "
            + _bounded_json(_planner_evidence(context, context.graph_projection)["bound_records"])
        )
        applicability = resolve_decision_applicability(context.graph_projection, context.node_id)
        if applicability is not None and applicability.family == "work_result":
            protected = resolve_decision_context(
                context.graph_projection, context.node_id
            ).protected_question_context()
            context_lines.append(
                "worker_result_evidence: "
                + _bounded_json({"evidence_aliases": protected["evidence_aliases"]})
            )
            context_lines.append(
                "worker_result_contract: finish by submitting outputs.decision with "
                "status=ready and a substantive summary, or status=blocked with a concrete "
                "blocker. Blocker evidence must use only the offered evidence aliases; "
                "use an empty evidence list when none apply. "
                "The runtime owns candidate, file-state, checks, commits, and completion."
            )

    authority_packet = _worker_authority_packet(context)
    if authority_packet:
        context_lines.append(f"worker_authority: {_bounded_json(authority_packet)}")

    dynamic_feature = _dynamic_feature_from_context(context)
    if dynamic_feature is not None:
        context_lines.extend(_dynamic_feature_prompt_lines(node, dynamic_feature))

    return _bounded_prompt("\n".join([_bounded_text(title), *context_lines]).strip())


def _worker_contract_packet(context: GraphDispatchContext) -> dict[str, Any]:
    """Render the node's typed work contract as a bounded packet.

    Mandatory-by-validator fields (``objective``/``access_mode``/``acceptance``)
    are always present so a compiler-seeded worker that predates the contract
    reads as an explicit ``null`` rather than a silent omission.
    """
    node = context.node_payload
    objective = node.get("objective")
    access_mode = node.get("access_mode")
    acceptance = node.get("acceptance")
    packet: dict[str, Any] = {
        "objective": (
            _bounded_text(objective) if isinstance(objective, str) and objective.strip() else None
        ),
        "access_mode": access_mode if isinstance(access_mode, str) else None,
        "acceptance": (
            [item for item in cast(list[Any], acceptance) if isinstance(item, str)]
            if isinstance(acceptance, list)
            else None
        ),
    }
    scope = node.get("scope")
    if isinstance(scope, str) and scope.strip():
        packet["scope"] = _bounded_text(scope)
    implementation_notes = node.get("implementation_notes")
    if isinstance(implementation_notes, str) and implementation_notes.strip():
        packet["implementation_notes"] = _bounded_text(implementation_notes)
    for key in ("bound_requirement_ids", "invariants", "prohibited_actions"):
        value = node.get(key)
        if isinstance(value, list) and value:
            packet[key] = [item for item in cast(list[Any], value) if isinstance(item, str)]
    if context.requirements:
        packet["bound_requirements"] = list(context.requirements)
    raw_outputs = node.get("outputs")
    if isinstance(raw_outputs, list):
        packet["outputs"] = [
            dict(cast(dict[str, Any], output))
            for output in cast(list[Any], raw_outputs)
            if isinstance(output, dict)
        ]
    schema_id = node.get("semantic_schema_id")
    schema_version = node.get("semantic_schema_version")
    if (
        isinstance(schema_id, str)
        and isinstance(schema_version, int)
        and not isinstance(schema_version, bool)
    ):
        packet["semantic_schema_id"] = schema_id
        packet["semantic_schema_version"] = schema_version
        declaration = semantic_schema_declarations_view(context.graph_projection).get(
            (schema_id, schema_version)
        )
        if declaration is not None:
            packet["semantic_role"] = declaration.value.semantic_role
            packet["content_json_schema"] = thaw_json(declaration.value.json_schema)
    prior_failure = _latest_same_node_failure(context)
    if prior_failure is not None:
        packet["prior_attempt_failure"] = prior_failure
    return packet


def _latest_same_node_failure(context: GraphDispatchContext) -> dict[str, Any] | None:
    """Expose bounded canonical redispatch feedback when graph history carries it."""
    attempts = [
        attempt
        for attempt in execution_attempts_view(context.graph_projection).values()
        if attempt.node_id == context.node_id and attempt.recovery_error_detail is not None
    ]
    if attempts:
        latest = max(
            attempts,
            key=lambda attempt: (attempt.lease_generation, attempt.execution_id),
        )
        return {
            "event_type": "runner_recovery_requested",
            "detail": _bounded_text(latest.recovery_error_detail or "previous attempt failed"),
        }
    for event in reversed(context.graph_events):
        if event.event_type not in {
            "agent_died",
            "runner_recovery_requested",
            "runtime_retry_scheduled",
            "callback_rejected_conflict",
            "callback_rejected_stale",
        }:
            continue
        if event.payload.get("node_id") != context.node_id:
            continue
        detail = event.payload.get("detail") or event.payload.get("reason")
        return {
            "event_type": event.event_type,
            "detail": _bounded_text(detail or "previous attempt failed"),
        }
    return None


def _worker_authority_packet(context: GraphDispatchContext) -> dict[str, Any]:
    node = context.node_payload
    authority = node.get("authority")
    authority_payload = cast(dict[str, Any], authority) if isinstance(authority, dict) else {}
    allowed_actions = authority_payload.get("allowed_actions")
    resource_claims = authority_payload.get("resource_claims")
    available_tools = _available_tools_for_context(context)

    packet: dict[str, Any] = {
        "node_id": context.node_id,
        "lease_id": context.lease_id,
        "lease_generation": context.lease_generation,
        "worktree_path": context.worktree_path,
    }
    if isinstance(allowed_actions, list):
        packet["allowed_actions"] = [
            action for action in cast(list[Any], allowed_actions) if isinstance(action, str)
        ]
    if isinstance(resource_claims, list):
        packet["resource_claims"] = [
            claim for claim in cast(list[Any], resource_claims) if isinstance(claim, dict)
        ]
    if available_tools is not None:
        packet["available_tools"] = list(available_tools)
    return packet


def _available_tools_for_context(context: GraphDispatchContext) -> list[str] | None:
    applicability = resolve_decision_applicability(context.graph_projection, context.node_id)
    if applicability is not None and applicability.family in {
        "discovery_brief",
        "batch_decision",
        "correction_decision",
    }:
        explicit_tools = context.node_payload.get("available_tools")
        if not isinstance(explicit_tools, list):
            return []
        graph_tools = DEFAULT_NODE_CONTRACTS.allowed_tools_for(context.node_kind, context.node_role)
        return [
            tool
            for tool in cast(list[Any], explicit_tools)
            if isinstance(tool, str) and tool not in graph_tools
        ]
    explicit_tools = context.node_payload.get("available_tools")
    if isinstance(explicit_tools, list):
        return [tool for tool in cast(list[Any], explicit_tools) if isinstance(tool, str)]
    contract_tools = sorted(
        DEFAULT_NODE_CONTRACTS.allowed_tools_for(context.node_kind, context.node_role)
    )
    return contract_tools or None


def _dynamic_feature_from_context(context: GraphDispatchContext) -> dict[str, Any] | None:
    node_feature = context.node_payload.get("dynamic_feature")
    if isinstance(node_feature, dict):
        return cast(dict[str, Any], node_feature)

    dynamic_feature = routine_snapshot_dynamic_feature_view(context.graph_projection)
    if dynamic_feature is not None:
        return dynamic_feature
    for event in reversed(context.graph_events):
        if event.event_type != "node_created":
            continue
        snapshot = event.payload.get("snapshot")
        if isinstance(snapshot, dict):
            value = cast(dict[str, Any], snapshot).get("dynamic_feature")
            if isinstance(value, dict):
                return cast(dict[str, Any], value)
        value = event.payload.get("dynamic_feature")
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
    return None


def _dynamic_feature_prompt_lines(
    node: dict[str, Any],
    dynamic_feature: dict[str, Any],
) -> list[str]:
    lines: list[str] = []
    read_only_semantic = node.get("effect_contract") == "read_only_semantic" or (
        node.get("effect_contract") is None
        and node.get("access_mode") == "read_only"
        and node.get("semantic_stage") == "discovery"
    )
    staged_reliable_plan_work = node.get("semantic_stage") in {
        "effectful_batch",
        "corrective_work",
    }
    defers_dynamic_acceptance = read_only_semantic or staged_reliable_plan_work
    for source_key, prompt_key in (
        ("feature_spec_path", "dynamic_feature_spec_path"),
        ("feature_spec_content", "dynamic_feature_spec_content"),
        (
            "acceptance_command",
            (
                "downstream_acceptance_command"
                if defers_dynamic_acceptance
                else "dynamic_acceptance_command"
            ),
        ),
    ):
        value = dynamic_feature.get(source_key)
        if isinstance(value, str) and value:
            lines.append(f"{prompt_key}: {_bounded_text(value)}")

    if node.get("kind") != "worker":
        return lines

    if read_only_semantic:
        lines.append(
            "dynamic_worker_instruction: Analyze the repository and submit only the typed "
            "semantic artifact. Do not modify repository files and do not execute "
            "downstream_acceptance_command; effectful workers and checks own that evidence."
        )
        return lines

    semantic_plan_revision = (
        node.get("semantic_stage") == "corrective_work"
        and isinstance(node.get("semantic_schema_id"), str)
        and isinstance(node.get("semantic_schema_version"), int)
        and isinstance(node.get("recovery_of_record_id"), str)
    )
    if semantic_plan_revision:
        lines.append(
            "dynamic_worker_instruction: Revise the exact bound failed semantic plan and "
            "submit outputs.semantic_artifact using the declared semantic schema. Do not "
            "modify repository files or execute downstream_acceptance_command; this node "
            "repairs the plan artifact for independent re-verification."
        )
        return lines

    if staged_reliable_plan_work:
        lines.append(
            "dynamic_worker_instruction: Work only within the node's declared batch or "
            "correction scope and its bound evidence. Do not execute or broaden scope to "
            "satisfy downstream_acceptance_command; explicit check nodes and the final "
            "audit own that evidence."
        )
        return lines

    role = node.get("role")
    if role == "fixer" or "corrective" in str(node.get("node_id", "")):
        lines.append(
            "dynamic_worker_instruction: Correct the artifact described by "
            "dynamic_feature_spec_content so the final invariant oracle can pass. "
            "Do not work on unrelated repository slices."
        )
    else:
        lines.append(
            "dynamic_worker_instruction: Create or update only the artifact described by "
            "dynamic_feature_spec_content, then use dynamic_acceptance_command when possible. "
            "Do not work on unrelated repository slices."
        )
    return lines


def _planner_packet(context: GraphDispatchContext) -> dict[str, Any]:
    projection = context.graph_projection
    node = context.node_payload
    current_position = context.graph_position
    generation_index = planner_generations_view(projection).get(context.node_id)

    frontier = _planner_frontier(projection, context)
    evidence = _planner_evidence(context, projection)
    proposals = _planner_proposals(context, projection)

    packet = {
        "run_id": context.run_id,
        "node_id": context.node_id,
        "node_kind": context.node_kind,
        "role": node.get("role"),
        "active_intent": {
            "title": node.get("title", context.node_id),
            "context": node.get("task_context", ""),
            "task_region_id": node_task_regions_view(projection).get(context.node_id),
        },
        "current_graph_position": current_position,
        "planner_generation": {
            "index": generation_index,
            "budget": planner_generation_budget(projection),
        },
        "bound_requirements": list(context.requirements),
        "frontier": frontier,
        "evidence": evidence,
        "freshness": planner_freshness_packet_view(projection),
        "open_planner_proposals": proposals["open_proposals"],
        "accepted_planner_patches": proposals["accepted_patches"],
        "patch_rejections": proposals["patch_rejections"],
    }
    dynamic_feature = node.get("dynamic_feature")
    if isinstance(dynamic_feature, dict):
        visible_dynamic_feature = _planner_visible_dynamic_feature(
            cast(dict[str, Any], dynamic_feature)
        )
        if _is_reliable_plan_context(context):
            # Whole-feature acceptance is controller-owned finalization.  It
            # must not be presented as a semantic check choice to the planner.
            visible_dynamic_feature.pop("available_check_bindings", None)
            visible_dynamic_feature.pop("hidden_oracle_binding", None)
        packet["dynamic_feature"] = visible_dynamic_feature
    reliable_plan_contract = _planner_reliable_plan_contract(context)
    if reliable_plan_contract is not None:
        packet["reliable_plan_contract"] = reliable_plan_contract
    if _is_reliable_plan_context(context):
        packet["reliable_plan_options"] = _planner_reliable_plan_options(context)
    else:
        packet["allowed_patch_operations"] = _planner_allowed_ops_packet()
        packet["horizon_region_templates"] = horizon_region_templates()
    if context.node_role == "gap_planner":
        packet["gap_analysis_contract"] = {
            "inspect": [
                "bound_requirements",
                "accepted_evidence",
                "verifier_check_results",
                "outstanding_failures",
                "stale_or_missing_support_evidence",
                "active_intent",
            ],
            "decisions": [
                "no_gap_no_op_patch",
                "corrective_work_patch",
                "validation_strengthening_placeholder",
                "human_or_policy_escalation_placeholder",
            ],
            "required_patch_before_submit": (
                "submit corrective_work_patch or no_gap_no_op_patch before plain submit"
            ),
            "no_gap_no_op_patch": {
                "ops": [],
                "meaning": (
                    "bound evidence shows no corrective work is needed; accepted no-op "
                    "emits a no_gap classified_gap record on submit"
                ),
            },
            "corrective_region": "corrective_work_region",
            "corrective_categories": {
                "implementation": "create_effectful_batch with failed batch evidence",
                "semantic_plan_revision": (
                    "create_revision_attempt with exact failed implementation-plan artifact, "
                    "failed plan-verification report, schema, requirements, and consumer edges"
                ),
            },
            "repository_edits": "forbidden",
        }
        packet["gap_analysis_obligations"] = _gap_analysis_obligations(
            context,
            projection,
        )
    if not _is_reliable_plan_context(context):
        packet["patch_examples"] = _planner_patch_examples(packet, context)
    return packet


def _is_reliable_plan_context(context: GraphDispatchContext) -> bool:
    """Return whether this is a root/successor reliable-plan planner.

    Gap planners can carry the same skeleton provenance, but their corrective
    contract intentionally remains the compatibility planner contract.
    """
    return (
        context.node_kind == "planner"
        and context.node_payload.get("role") != "gap_planner"
        and isinstance(context.node_payload.get("reliable_plan_skeleton_id"), str)
    )


def _planner_reliable_plan_options(context: GraphDispatchContext) -> dict[str, Any]:
    """Expose only currently usable semantic choices to a reliable planner."""
    node = context.node_payload
    raw_dynamic_feature = _dynamic_feature_from_context(context)
    dynamic_feature = (
        _planner_visible_dynamic_feature(raw_dynamic_feature)
        if raw_dynamic_feature is not None
        else None
    )
    available_bindings = (
        list(cast(list[Any], dynamic_feature.get("available_check_bindings", [])))
        if dynamic_feature is not None
        else []
    )
    # ``dynamic_feature_acceptance`` is controller-owned finalization and is
    # intentionally unavailable to semantic construction.  Only the binding
    # accepted by ReliablePlanCheckDecision can be offered here.
    available_bindings = [
        item
        for item in available_bindings
        if isinstance(item, str) and item == "dynamic_feature_hidden_oracle"
    ]
    declared = _reliable_plan_declared_batch_ids(context)
    materialized = sorted(accepted_declared_batch_ids(context.graph_projection))
    current_scope = node.get("declared_batch_id")
    if isinstance(current_scope, str) and current_scope:
        scopes = [current_scope]
    elif declared:
        scopes = [batch_id for batch_id in declared if batch_id not in materialized]
    else:
        scopes = []
    return {
        "scope_mode": (
            "author_new_initial_scope"
            if node.get("semantic_stage") != "successor_planning"
            else "current_declared_batch"
            if isinstance(current_scope, str) and current_scope
            else "select_declared_batch"
        ),
        "scope_options": scopes,
        "dependency_options": materialized,
        "available_check_bindings": available_bindings,
        "explicit_command_definition": "available; supply a concrete command from the task contract",
    }


def _planner_visible_dynamic_feature(dynamic_feature: dict[str, Any]) -> dict[str, Any]:
    visible = {
        key: value for key, value in dynamic_feature.items() if key != "hidden_oracle_command"
    }
    hidden_available = _nonempty_text(dynamic_feature.get("hidden_oracle_command"))
    acceptance_available = _nonempty_text(dynamic_feature.get("acceptance_command"))
    if hidden_available:
        visible["hidden_oracle_binding"] = "dynamic_feature_hidden_oracle"
        visible["available_check_bindings"] = [
            "dynamic_feature_hidden_oracle",
            *(["dynamic_feature_acceptance"] if acceptance_available else []),
        ]
    else:
        visible["hidden_oracle_binding"] = "unavailable"
        visible["available_check_bindings"] = (
            ["dynamic_feature_acceptance"] if acceptance_available else []
        )
    return visible


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _planner_frontier(
    projection: GraphProjection,
    context: GraphDispatchContext,
) -> dict[str, list[dict[str, Any]] | list[str]]:
    ready_nodes = sorted(ready_nodes_view(projection))
    deferred_reasons = last_deferred_reasons_view(projection)

    blocked_nodes: list[dict[str, Any]] = []
    for node_id in sorted(node_states_view(projection)):
        node_state = node_states_view(projection).get(node_id, "")
        if node_state == "ready":
            continue
        reason = deferred_reasons.get(node_id)
        if reason is None and node_id != context.node_id:
            continue
        if node_state in {"running", "leased", "completed", "failed", "cancelled", "retired"}:
            continue
        blocked_nodes.append(
            {
                "node_id": node_id,
                "state": node_state,
                "reason": reason,
            }
        )

    return {
        "ready_nodes": ready_nodes,
        "blocked_or_deferred_nodes": sorted(
            blocked_nodes,
            key=lambda item: (
                str(item.get("reason", "")),
                str(item.get("node_id", "")),
            ),
        ),
    }


def _gap_analysis_obligations(
    context: GraphDispatchContext,
    projection: GraphProjection,
) -> list[dict[str, Any]]:
    obligations: list[dict[str, Any]] = []
    terminal_states = {"completed", "failed", "cancelled", "retired"}

    for edge_id, edge in sorted(edges_view(projection).items()):
        if not edge.required:
            continue
        if edge.from_node_id != context.node_id:
            continue
        if edge.from_port != "classified_gap" and edge.to_port != "classified_gap":
            continue
        to_node_id = edge.to_node_id
        to_port = edge.to_port
        if node_states_view(projection).get(to_node_id) in terminal_states:
            continue
        if to_port in input_bindings_view(projection).get(to_node_id, {}):
            continue
        obligations.append(
            {
                "kind": "classified_gap_successor_waiting",
                "edge_id": edge_id,
                "to_node_id": to_node_id,
                "to_port": to_port,
                "reason": (
                    "required classified_gap successor is waiting; submit a no_gap no-op "
                    "patch or create corrective work so the successor can receive a "
                    "durable gap classification"
                ),
            }
        )

    deferred_reasons = last_deferred_reasons_view(projection)
    for node_id, reason in sorted(deferred_reasons.items()):
        if reason != "missing_required_input:verification_evidence":
            continue
        if node_states_view(projection).get(node_id) in terminal_states:
            continue
        if node_kinds_view(projection).get(node_id) != "check":
            continue
        obligations.append(
            {
                "kind": "final_invariant_waiting_for_verification_evidence",
                "node_id": node_id,
                "reason": (
                    "final invariant is still pending verification_evidence; a weak verifier "
                    "pass is not sufficient if corrective/final invariant work remains"
                ),
            }
        )

    return obligations


def _planner_evidence(
    context: GraphDispatchContext,
    projection: GraphProjection,
    _events: list[EventEnvelope] | None = None,
) -> dict[str, Any]:
    bindings = input_bindings_view(projection).get(context.node_id, {})
    output_records = record_payloads_view(projection)

    bound_records: dict[str, list[dict[str, Any]]] = {}
    for port in sorted(bindings):
        binding = bindings[port]
        raw_record_ids = binding.record_ids
        hydration_policy = _hydration_policy_for_binding(binding, projection)
        records: list[dict[str, Any]] = []
        for raw_record_id in cast(list[object], raw_record_ids):
            if not isinstance(raw_record_id, str):
                continue

            if raw_record_id in file_state_records_view(projection):
                records.append(
                    _hydrated_bound_record(
                        record_id=raw_record_id,
                        record_kind="file_state",
                        record_payload=_compact_file_state_record(
                            file_state_records_view(projection)[raw_record_id]
                        ),
                        hydration_policy=hydration_policy,
                    )
                )
                continue

            output_payload = output_records.get(raw_record_id)
            if output_payload is not None:
                records.append(
                    _hydrated_bound_record(
                        record_id=raw_record_id,
                        record_kind=str(output_payload.get("record_kind", "output")),
                        record_payload=_tail_only_prompt_record_payload(output_payload),
                        hydration_policy=hydration_policy,
                    )
                )
                continue

            records.append(
                {
                    "record_id": raw_record_id,
                    "record_kind": None,
                    "status": "missing",
                }
            )

        bound_records[port] = sorted(records, key=lambda record: str(record["record_id"]))

    return {
        "bound_records": bound_records,
        "outstanding_failures": _planner_outstanding_failures(context, projection),
        "session_carryover_record_id": _planner_session_carryover_record(context, projection),
    }


def _tail_only_prompt_record_payload(record_payload: dict[str, Any]) -> dict[str, Any]:
    """Keep normal prompt assembly independent from artifact hydration."""
    if record_payload.get("record_type") != "check_result":
        return record_payload
    value = record_payload.get("value")
    if not isinstance(value, dict):
        return record_payload
    bounded_value = dict(cast(dict[str, Any], value))
    bounded_value.pop("stdout_ref", None)
    bounded_value.pop("stderr_ref", None)
    bounded_record = dict(record_payload)
    bounded_record["value"] = bounded_value
    return bounded_record


def _hydration_policy_for_binding(
    binding: InputBindingProjection,
    projection: GraphProjection,
) -> str:
    edge_id = binding.edge_id
    if not isinstance(edge_id, str):
        return "structured_json"
    edge = edges_view(projection).get(edge_id)
    if edge is None:
        return "structured_json"
    policy = edge.prompt_hydration_policy
    if isinstance(policy, str) and policy in {
        "inline_summary",
        "structured_json",
        "artifact_reference",
        "tool_only",
    }:
        return policy
    return "structured_json"


def _hydrated_bound_record(
    *,
    record_id: str,
    record_kind: str,
    record_payload: dict[str, Any],
    hydration_policy: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_id": record_id,
        "record_kind": record_kind,
        "hydration_policy": hydration_policy,
        "status": "accepted",
    }
    if hydration_policy == "tool_only":
        record["omitted_from_prompt"] = True
        return record
    if hydration_policy == "artifact_reference":
        record["record_reference"] = _artifact_reference_payload(record_payload)
        return record
    if hydration_policy == "inline_summary":
        record["record_summary"] = _inline_record_summary(record_payload)
        return record
    record["record_payload"] = record_payload
    return record


def _artifact_reference_payload(record_payload: dict[str, Any]) -> dict[str, Any]:
    value = record_payload.get("value")
    typed_value = cast(dict[str, Any], value) if isinstance(value, dict) else {}
    reference: dict[str, Any] = {
        "record_id": record_payload.get("record_id"),
        "record_type": record_payload.get("record_type"),
        "schema": record_payload.get("schema"),
        "producer_node_id": record_payload.get("producer_node_id"),
        "producer_port": record_payload.get("producer_port") or record_payload.get("port"),
    }
    for key in ("artifact_id", "artifact_type", "uri", "summary"):
        value_field = typed_value.get(key)
        if isinstance(value_field, str) and value_field:
            reference[key] = value_field
    return {key: value for key, value in reference.items() if value is not None}


def _inline_record_summary(record_payload: dict[str, Any]) -> dict[str, Any]:
    value = record_payload.get("value")
    typed_value = cast(dict[str, Any], value) if isinstance(value, dict) else {}
    summary = typed_value.get("summary") or typed_value.get("text") or record_payload.get("summary")
    inline: dict[str, Any] = {
        "record_id": record_payload.get("record_id"),
        "record_type": record_payload.get("record_type"),
        "schema": record_payload.get("schema"),
    }
    if isinstance(summary, str) and summary:
        inline["summary"] = _bounded_text(summary, max_chars=MAX_GRAPH_PROMPT_FIELD_CHARS)
    for key in ("status", "classification", "outcome", "candidate_id"):
        value_field = record_payload.get(key) or typed_value.get(key)
        if isinstance(value_field, str) and value_field:
            inline[key] = value_field
    return {key: value for key, value in inline.items() if value is not None}


def _compact_file_state_record(record: dict[str, Any] | FileStateRecord) -> dict[str, Any]:
    record_payload = (
        record.model_dump(mode="json") if isinstance(record, FileStateRecord) else record
    )
    canonical_paths = _path_entries(record_payload.get("paths"))
    tracked = (
        canonical_paths
        and [entry for entry in canonical_paths if entry.get("source") == "tracked"]
        or _path_entries(record_payload.get("tracked"))
    )
    untracked = (
        canonical_paths
        and [entry for entry in canonical_paths if entry.get("source") == "untracked"]
        or _path_entries(record_payload.get("untracked"))
    )
    ignored = (
        canonical_paths
        and [entry for entry in canonical_paths if entry.get("source") == "ignored"]
        or _path_entries(record_payload.get("ignored"))
    )
    rejected_paths = (
        [entry for entry in canonical_paths if entry.get("rejected") is True]
        if canonical_paths
        else record_payload.get("rejected_paths")
    )
    rejected_path_count = (
        len(cast(list[object], rejected_paths)) if isinstance(rejected_paths, list) else 0
    )

    compact: dict[str, Any] = {
        "snapshot_id": record_payload.get("snapshot_id"),
        "base_snapshot_id": record_payload.get("base_snapshot_id"),
        "producer_node_id": record_payload.get("producer_node_id"),
        "port": record_payload.get("port"),
        "schema": record_payload.get("schema"),
        "verdict": record_payload.get("verdict"),
        "counts": {
            "tracked": len(tracked),
            "untracked": len(untracked),
            "ignored": len(ignored),
            "rejected_paths": rejected_path_count,
        },
        "tracked_paths": _compact_path_entries(tracked),
        "untracked_paths": _compact_path_entries(untracked),
    }
    if isinstance(rejected_paths, list) and rejected_paths:
        compact["rejected_paths"] = [str(path) for path in cast(list[object], rejected_paths)[:10]]
    git = record_payload.get("git")
    if isinstance(git, dict):
        git_data = cast(dict[str, Any], git)
        compact["git"] = {
            "commit_sha": git_data.get("commit_sha"),
            "tree_sha": git_data.get("tree_sha"),
            "no_commit_reason": git_data.get("no_commit_reason"),
        }
    return compact


def _path_entries(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in cast(list[object], value):
        if isinstance(item, dict):
            entries.append(dict(cast(dict[str, Any], item)))
    return entries


def _compact_path_entries(entries: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for entry in entries[:limit]:
        compacted.append(
            {
                "path": entry.get("path"),
                "classification": entry.get("classification"),
                "source": entry.get("source"),
                "rejected": entry.get("rejected"),
            }
        )
    return compacted


def _planner_outstanding_failures(
    context: GraphDispatchContext,
    projection: GraphProjection,
) -> list[dict[str, Any]]:
    task_region_id = node_task_regions_view(projection).get(context.node_id)
    failures: list[dict[str, Any]] = []

    for region_id, failure in environment_failures_view(projection).items():
        if task_region_id is not None and task_region_id != region_id:
            continue
        entry = failure.model_dump(mode="json")
        entry["task_region_id"] = region_id
        failures.append(entry)
    failures.sort(key=lambda item: str(item.get("task_region_id")))
    return failures


def _planner_session_carryover_record(
    context: GraphDispatchContext,
    projection: GraphProjection,
) -> str | None:
    session_id = planner_sessions_view(projection).get(context.node_id)
    if not isinstance(session_id, str):
        return None
    carryover = planner_session_carryovers_view(projection).get(session_id)
    if carryover is None:
        return None
    return str(carryover)


def _planner_proposals(
    context: GraphDispatchContext,
    projection: GraphProjection,
) -> dict[str, list[dict[str, Any]]]:
    return planner_patch_facts_view(projection, context.node_id)


def _planner_allowed_ops_packet() -> dict[str, list[str]]:
    return {"allowed_ops": sorted(PLANNER_OPS)}


def _planner_patch_examples(
    packet: dict[str, Any],
    context: GraphDispatchContext,
) -> list[dict[str, Any]]:
    base_position = int(packet.get("current_graph_position", 0))
    examples: list[dict[str, Any]] = []
    invariant_command = (
        {"command_binding": "dynamic_feature_hidden_oracle"}
        if _hidden_oracle_binding_available(packet)
        else {"command_definition": {"cmd": "uv run pytest tests/batch -q"}}
    )

    if {"create_node", "create_edge"}.issubset(PLANNER_OPS):
        region_id = (
            "corrective_work_region" if context.node_role == "gap_planner" else "region-example"
        )
        examples.append(
            {
                "purpose": (
                    "create_corrective_work_region"
                    if context.node_role == "gap_planner"
                    else "create_worker_verifier_region"
                ),
                "patch_id": "example-worker-verifier-region",
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "worker-example",
                            "kind": "worker",
                            "role": "builder",
                            "state": "planned",
                            "task_region_id": region_id,
                            "attempt_number": 1,
                            "candidate_id": "candidate-example",
                            "objective": "Implement a candidate that satisfies the bound requirements.",
                            "access_mode": "write",
                            "effect_contract": "effectful_write",
                            "acceptance": ["candidate satisfies the bound requirements"],
                        },
                    },
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "verifier-example",
                            "kind": "verifier",
                            "role": "verifier",
                            "state": "planned",
                            "task_region_id": region_id,
                            "rubric": ["candidate satisfies the bound requirements"],
                        },
                    },
                    {
                        "op": "create_edge",
                        "edge_id": "example-worker-to-verifier",
                        "from_node_id": "worker-example",
                        "from_port": "candidate",
                        "to_node_id": "verifier-example",
                        "to_port": "candidate_under_test",
                        "required": True,
                        "accepted_record_selector": {
                            "record_type": "candidate",
                            "schema": "ImplementationCandidate",
                        },
                    },
                ],
            }
        )

    if context.node_role == "gap_planner":
        examples.append(
            {
                "purpose": "semantic_plan_revision",
                "instruction": (
                    "Replace every example identity with exact accepted evidence IDs; "
                    "this shape is valid only for a failed typed implementation-plan artifact."
                ),
                "patch_id": "example-semantic-plan-revision",
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "create_revision_attempt",
                        "task_region_id": "plan-revision-region",
                        "failed_candidate_id": "accepted-semantic-plan-record-id",
                        "worker_node": {
                            "node_id": "worker-semantic-plan-revision",
                            "kind": "worker",
                            "role": "fixer",
                            "state": "planned",
                            "task_region_id": "plan-revision-region",
                            "candidate_id": "revised-semantic-plan",
                            "failed_candidate_id": "accepted-semantic-plan-record-id",
                            "recovery_of_record_id": "accepted-semantic-plan-record-id",
                            "semantic_stage": "corrective_work",
                            "semantic_schema_id": "declared-implementation-plan-schema",
                            "semantic_schema_version": 1,
                            "bound_requirement_ids": ["exact-bound-requirement-id"],
                            "objective": "Revise the exact failed semantic plan artifact.",
                            "access_mode": "write",
                            "effect_contract": "effectful_write",
                            "acceptance": ["The failed plan-verification grade is corrected."],
                            "outputs": [
                                {
                                    "port": "candidate",
                                    "direction": "output",
                                    "schema": "ImplementationCandidate",
                                    "required": True,
                                },
                                {
                                    "port": "semantic_artifact",
                                    "direction": "output",
                                    "schema": "SemanticArtifact",
                                    "required": True,
                                },
                            ],
                        },
                        "verifier_node": {
                            "node_id": "verifier-semantic-plan-revision",
                            "kind": "verifier",
                            "role": "verifier",
                            "state": "planned",
                            "task_region_id": "plan-revision-region",
                            "failed_candidate_id": "accepted-semantic-plan-record-id",
                        },
                    },
                    {
                        "op": "create_edge",
                        "edge_id": "failed-plan-report-to-revision",
                        "from_node_id": "exact-plan-verifier-node-id",
                        "from_port": "verification_report",
                        "to_node_id": "worker-semantic-plan-revision",
                        "to_port": "verification_report",
                        "required": True,
                        "accepted_record_selector": {
                            "record_id": "exact-failed-plan-report-id",
                            "record_type": "verification_report",
                            "schema": "VerificationReport",
                            "outcome": "failed",
                        },
                    },
                    {
                        "op": "create_edge",
                        "edge_id": "revised-plan-candidate-to-verifier",
                        "from_node_id": "worker-semantic-plan-revision",
                        "from_port": "candidate",
                        "to_node_id": "verifier-semantic-plan-revision",
                        "to_port": "candidate_under_test",
                        "required": True,
                        "accepted_record_selector": {
                            "record_type": "candidate",
                            "schema": "ImplementationCandidate",
                        },
                    },
                    {
                        "op": "create_edge",
                        "edge_id": "revised-plan-artifact-to-verifier",
                        "from_node_id": "worker-semantic-plan-revision",
                        "from_port": "semantic_artifact",
                        "to_node_id": "verifier-semantic-plan-revision",
                        "to_port": "semantic_artifact",
                        "required": True,
                        "accepted_record_selector": {
                            "record_type": "semantic_artifact",
                            "schema": "SemanticArtifact",
                            "semantic_schema_id": "declared-implementation-plan-schema",
                            "semantic_schema_version": 1,
                        },
                    },
                ],
            }
        )
        examples.append(
            {
                "purpose": "no_gap_no_op_patch",
                "patch_id": "example-gap-no-op",
                "base_graph_position": base_position,
                "ops": [],
            }
        )
        return sorted(examples, key=lambda example: str(example.get("patch_id", "")))

    final_reliable_plan_horizon = (
        context.node_payload.get("semantic_stage") == "successor_planning"
        and context.node_payload.get("reliable_plan_remaining_horizons") == 1
    )
    if "create_node" in PLANNER_OPS:
        if final_reliable_plan_horizon:
            examples.append(_reliable_plan_semantic_region_example(packet, context))
        else:
            examples.append(
                {
                    "purpose": "create_successor_planner",
                    "patch_id": "example-successor-planner",
                    "base_graph_position": base_position,
                    "ops": [
                        {
                            "op": "create_node",
                            "node": {
                                "node_id": "planner-successor-example",
                                "kind": "planner",
                                "role": "planner",
                                "state": "planned",
                                "task_region_id": "region-example",
                            },
                        },
                    ],
                }
            )
        examples.append(
            {
                "purpose": "create_gap_planner",
                "patch_id": "example-gap-planner",
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "planner-gap-example",
                            "kind": "planner",
                            "role": "gap_planner",
                            "state": "planned",
                            "task_region_id": "region-example",
                        },
                    },
                    {
                        "op": "create_edge",
                        "edge_id": "example-verifier-to-gap",
                        "from_node_id": "verifier-example",
                        "from_port": "verification_report",
                        "to_node_id": "planner-gap-example",
                        "to_port": "verification_evidence",
                        "required": True,
                        "accepted_record_selector": {
                            "record_type": "verification_report",
                            "schema": "VerificationReport",
                            "outcome": "failed",
                        },
                    },
                ],
            }
        )
        examples.append(
            {
                "purpose": "create_invariant_check",
                "patch_id": "example-invariant-check",
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "invariant-check-example",
                            "kind": "check",
                            "role": "invariant_gate",
                            "state": "planned",
                            "task_region_id": "region-example",
                            **invariant_command,
                        },
                    },
                    {
                        "op": "create_edge",
                        "edge_id": "example-verifier-to-invariant",
                        "from_node_id": "verifier-example",
                        "from_port": "verification_report",
                        "to_node_id": "invariant-check-example",
                        "to_port": "verification_evidence",
                        "required": True,
                        "accepted_record_selector": {
                            "record_type": "verification_report",
                            "schema": "VerificationReport",
                            "outcome": "passed",
                        },
                    },
                ],
            }
        )
        examples.append(
            {
                "purpose": "no_safe_mutation_termination",
                "patch_id": "example-no-safe-mutation",
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "planner-no-safe-mutation-record",
                            "kind": "planner",
                            "role": "planner",
                            "state": "planned",
                            "task_region_id": "region-example",
                            "decision": "no safe graph mutation available from current evidence",
                        },
                    }
                ],
            }
        )

    if "set_resource_claims" in PLANNER_OPS:
        examples.append(
            {
                "purpose": "set_resource_claims",
                "patch_id": "example-set-resource-claims",
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "set_resource_claims",
                        "node_id": "worker-example",
                        "resource_claims": [
                            {"mode": "read", "scope": "repo"},
                            {
                                "mode": "write",
                                "scope": "repo",
                                "paths": ["src/example_pkg", "tests/unit"],
                            },
                        ],
                    }
                ],
            }
        )

    if "set_allowed_actions" in PLANNER_OPS:
        examples.append(
            {
                "purpose": "set_allowed_actions",
                "patch_id": "example-set-allowed-actions",
                "base_graph_position": base_position,
                "ops": [
                    {
                        "op": "set_allowed_actions",
                        "node_id": "worker-example",
                        "allowed_actions": ["submit", "view"],
                    }
                ],
            }
        )

    return sorted(examples, key=lambda example: str(example.get("patch_id", "")))


def _planner_reliable_plan_contract(
    context: GraphDispatchContext,
) -> dict[str, Any] | None:
    node = context.node_payload
    if not isinstance(node.get("reliable_plan_skeleton_id"), str):
        return None
    remaining = node.get("reliable_plan_remaining_horizons")
    declared_batch_ids = _reliable_plan_declared_batch_ids(context)
    contract: dict[str, Any] = {
        "semantic_stage": node.get("semantic_stage"),
        "planning_horizon": node.get("planning_horizon"),
        "remaining_horizons_including_current": remaining,
        "declared_batch_ids": declared_batch_ids,
        "current_declared_batch_id": node.get("declared_batch_id"),
    }
    if node.get("semantic_stage") != "successor_planning":
        contract["required_sequence"] = [
            "call construct_reliable_plan_region once with the complete semantic planning decision",
            "the controller atomically creates discovery, plan verification, and the first successor",
            "call plain submit only after the construction acknowledgement is accepted",
        ]
        return contract
    if remaining == 1:
        contract["required_sequence"] = [
            "call construct_reliable_plan_region once for the current accepted batch scope",
            "the controller atomically creates the batch, dynamic acceptance, independent audit, and final gate",
            "the controller rejects a partial batch-only or finalization-only patch",
            "call plain submit only after that complete patch is accepted",
        ]
        contract["controller_outcomes"] = [
            "the controller creates exactly one final acceptance check distinct from any semantic check",
            "the controller binds that acceptance check to a passed verification report from every declared batch verifier",
            "the controller creates the final audit and gate with their complete typed evidence bindings",
        ]
    elif isinstance(remaining, int) and not isinstance(remaining, bool) and remaining > 1:
        contract["required_sequence"] = [
            "call construct_reliable_plan_region once for the current accepted batch scope",
            "the controller atomically creates the batch and its passed-report successor planner",
            "the controller rejects a partial batch-only or successor-only patch",
            "call plain submit only after that complete patch is accepted",
        ]
    return contract


def _reliable_plan_semantic_region_example(
    packet: dict[str, Any],
    context: GraphDispatchContext,
) -> dict[str, Any]:
    declared_batch_ids = _reliable_plan_declared_batch_ids(context)
    materialized = accepted_declared_batch_ids(context.graph_projection)
    current_scope = context.node_payload.get("declared_batch_id")
    scope = (
        current_scope
        if isinstance(current_scope, str)
        else next(
            (batch_id for batch_id in declared_batch_ids if batch_id not in materialized), None
        )
    )
    check = (
        {
            "name": "bounded project check",
            "command_binding": "dynamic_feature_hidden_oracle",
        }
        if _hidden_oracle_binding_available(packet)
        else {
            "name": "bounded project check",
            "command_definition": {"cmd": "uv run pytest tests/batch -q"},
        }
    )
    return {
        "purpose": "construct_reliable_plan_region",
        "patch_id": "stable-logical-operation-key",
        "base_graph_position": int(packet.get("current_graph_position", 0)),
        "operation_key": "stable-logical-operation-key",
        "scope": scope or "exact-accepted-batch-id",
        "objective": "Implement the selected accepted-plan batch.",
        "requirement_ids": ["exact-bound-requirement-id"],
        "dependencies": [],
        "acceptance": ["the batch obligations and required checks pass"],
        "checks": [check],
        "rubric": ["the exact batch and bound requirements are satisfied"],
    }


def _hidden_oracle_binding_available(packet: dict[str, Any]) -> bool:
    dynamic_feature = packet.get("dynamic_feature")
    if not isinstance(dynamic_feature, dict):
        return False
    typed_feature = cast(dict[str, Any], dynamic_feature)
    available = typed_feature.get("available_check_bindings")
    return isinstance(available, list) and "dynamic_feature_hidden_oracle" in cast(
        list[Any], available
    )


def legacy_reliable_plan_finalization_example(
    packet: dict[str, Any],
    context: GraphDispatchContext,
) -> dict[str, Any]:
    declared_batch_ids = _reliable_plan_declared_batch_ids(context)
    batch_verifiers: dict[str, str] = {}
    for node_id, kind in node_kinds_view(context.graph_projection).items():
        if kind != "verifier":
            continue
        payload = node_payload_view(context.graph_projection, node_id) or {}
        batch_id = payload.get("declared_batch_id")
        if payload.get("semantic_stage") == "effectful_batch" and isinstance(batch_id, str):
            batch_verifiers[batch_id] = node_id

    input_specs = [
        {
            "port": f"verification_report_batch_{index}",
            "direction": "input",
            "schema": "VerificationReport",
            "required": True,
        }
        for index, _batch_id in enumerate(declared_batch_ids, start=1)
    ]
    final_audit_id = "final-audit-exact-id"
    final_acceptance_id = "final-acceptance-exact-id"
    final_gate_id = "final-gate-exact-id"
    ops: list[dict[str, Any]] = [
        {
            "op": "create_node",
            "node": {
                "node_id": final_acceptance_id,
                "kind": "check",
                "role": "acceptance_gate",
                "state": "planned",
                "semantic_stage": "final_acceptance",
                "task_region_id": context.node_payload.get("task_region_id"),
                "command_binding": "dynamic_feature_acceptance",
                "inputs": input_specs,
                "outputs": [
                    {
                        "port": "check_result",
                        "direction": "output",
                        "schema": "CheckResult",
                        "required": True,
                    }
                ],
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": final_audit_id,
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "semantic_stage": "final_audit",
                "task_region_id": context.node_payload.get("task_region_id"),
                "inputs": [
                    *input_specs,
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
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": final_gate_id,
                "kind": "final_gate",
                "role": "final_gate",
                "state": "planned",
                "task_region_id": context.node_payload.get("task_region_id"),
                "declared_batch_ids": declared_batch_ids,
                "inputs": [
                    *input_specs,
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
        source = batch_verifiers.get(batch_id, f"exact-verifier-for-{batch_id}")
        port = f"verification_report_batch_{index}"
        for target in (final_acceptance_id, final_audit_id, final_gate_id):
            ops.append(
                {
                    "op": "create_edge",
                    "edge_id": f"edge-{batch_id}-to-{target}",
                    "from_node_id": source,
                    "from_port": "verification_report",
                    "to_node_id": target,
                    "to_port": port,
                    "required": True,
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "passed",
                    },
                }
            )
    ops.append(
        {
            "op": "create_edge",
            "edge_id": "edge-final-acceptance-to-final-audit",
            "from_node_id": final_acceptance_id,
            "from_port": "check_result",
            "to_node_id": final_audit_id,
            "to_port": "dynamic_feature_acceptance",
            "required": True,
            "accepted_record_selector": {
                "record_type": "check_result",
                "schema": "CheckResult",
                "status": "passed",
            },
        }
    )
    ops.append(
        {
            "op": "create_edge",
            "edge_id": "edge-final-acceptance-to-final-gate",
            "from_node_id": final_acceptance_id,
            "from_port": "check_result",
            "to_node_id": final_gate_id,
            "to_port": "dynamic_feature_acceptance",
            "required": True,
            "accepted_record_selector": {
                "record_type": "check_result",
                "schema": "CheckResult",
                "status": "passed",
            },
        }
    )
    ops.append(
        {
            "op": "create_edge",
            "edge_id": "edge-final-audit-to-final-gate",
            "from_node_id": final_audit_id,
            "from_port": "verification_report",
            "to_node_id": final_gate_id,
            "to_port": "verification_report_final_audit",
            "required": True,
            "accepted_record_selector": {
                "record_type": "verification_report",
                "schema": "VerificationReport",
                "outcome": "passed",
            },
        }
    )
    return {
        "purpose": "create_reliable_plan_finalization",
        "instruction": (
            "Use the exact declared batch IDs and existing verifier node IDs. Replace only "
            "placeholder final node IDs or any exact-verifier-for-* source that is not yet "
            "materialized. Keep the one dynamic_feature_acceptance check distinct from hidden "
            "oracle checks. Submit this topology atomically with the final effectful batch."
        ),
        "patch_id": "example-reliable-plan-finalization",
        "base_graph_position": int(packet.get("current_graph_position", 0)),
        "ops": ops,
    }


def _reliable_plan_declared_batch_ids(context: GraphDispatchContext) -> list[str]:
    accepted_ids = sorted(accepted_declared_batch_ids(context.graph_projection))
    if accepted_ids:
        return accepted_ids
    return _unique_record_ids(
        [
            item
            for item in cast(list[Any], context.node_payload.get("declared_batch_ids", []))
            if isinstance(item, str)
        ]
    )


def _node_role(node_kind: str, node_payload: dict[str, Any]) -> str:
    role = node_payload.get("role")
    if isinstance(role, str) and role:
        return role
    if node_kind == "planner":
        return "planner"
    return ""


def _can_submit_graph_patch(context: GraphDispatchContext) -> bool:
    applicability = resolve_decision_applicability(context.graph_projection, context.node_id)
    if applicability is not None and applicability.family in {
        "discovery_brief",
        "batch_decision",
        "correction_decision",
    }:
        return False
    return "submit_graph_patch" in DEFAULT_NODE_CONTRACTS.allowed_tools_for(
        context.node_kind, context.node_role
    )


def _requires_graph_patch_before_submit(context: GraphDispatchContext) -> bool:
    return _can_submit_graph_patch(context)


def _graph_patch_feedback_accepted(feedback: str) -> bool:
    return " accepted" in feedback and " rejected" not in feedback


def _candidate_id_for_verifier(context: GraphDispatchContext) -> str:
    bound_candidate_ids = _bound_record_ids_for_ports(
        context,
        ("candidate_under_test", "candidate", "semantic_artifact"),
    )
    if bound_candidate_ids:
        return bound_candidate_ids[0]
    if context.node_payload.get("semantic_stage") == "final_audit":
        cited_candidate_ids = _evaluated_record_citations(context).get("candidate_record_ids", [])
        if cited_candidate_ids:
            return cited_candidate_ids[0]
    audit_inputs = _bound_record_ids_for_ports(
        context,
        tuple(
            port
            for port in sorted(
                input_bindings_view(context.graph_projection).get(context.node_id, {})
            )
            if port.startswith("verification_report_")
        ),
    )
    if audit_inputs:
        return audit_inputs[0]
    return str(context.node_payload.get("candidate_id") or f"candidate-{context.node_id}")


def _candidate_id_for_check(context: GraphDispatchContext) -> str:
    candidate_ids = _evaluated_record_citations(context).get("candidate_record_ids", [])
    if candidate_ids:
        return candidate_ids[0]
    return str(context.node_payload.get("candidate_id") or f"candidate-{context.node_id}")


def _patch_payload_has_ops(patch_payload: dict[str, Any]) -> bool:
    raw_patch = patch_payload.get("patch")
    payload = cast(dict[str, Any], raw_patch) if isinstance(raw_patch, dict) else patch_payload
    ops = payload.get("ops")
    if isinstance(ops, list) and bool(cast(list[object], ops)):
        return True
    macro_invocations = payload.get("macro_invocations")
    return isinstance(macro_invocations, list) and bool(cast(list[object], macro_invocations))


def _patch_payload_creates_successor_planner(patch_payload: dict[str, Any]) -> bool:
    raw_patch = patch_payload.get("patch")
    payload = cast(dict[str, Any], raw_patch) if isinstance(raw_patch, dict) else patch_payload
    macro_invocations = payload.get("macro_invocations")
    if isinstance(macro_invocations, list) and any(
        isinstance(invocation, dict)
        and cast(dict[str, Any], invocation).get("macro") == "create_successor_planner"
        for invocation in cast(list[Any], macro_invocations)
    ):
        return True
    ops = payload.get("ops")
    return isinstance(ops, list) and any(
        isinstance(op, dict)
        and cast(dict[str, Any], op).get("op") == "create_node"
        and isinstance(cast(dict[str, Any], op).get("node"), dict)
        and cast(dict[str, Any], cast(dict[str, Any], op)["node"]).get("kind") == "planner"
        and cast(dict[str, Any], cast(dict[str, Any], op)["node"]).get("role") == "planner"
        for op in cast(list[Any], ops)
    )


def _patch_payload_creates_finalization(patch_payload: dict[str, Any]) -> bool:
    raw_patch = patch_payload.get("patch")
    payload = cast(dict[str, Any], raw_patch) if isinstance(raw_patch, dict) else patch_payload
    ops = payload.get("ops")
    if not isinstance(ops, list):
        return False
    nodes = [
        cast(dict[str, Any], op)["node"]
        for op in cast(list[Any], ops)
        if isinstance(op, dict)
        and cast(dict[str, Any], op).get("op") == "create_node"
        and isinstance(cast(dict[str, Any], op).get("node"), dict)
    ]
    return (
        any(
            node.get("kind") == "worker" and node.get("semantic_stage") == "effectful_batch"
            for node in nodes
        )
        and any(
            node.get("kind") == "check"
            and node.get("semantic_stage") == "final_acceptance"
            and node.get("command_binding") == "dynamic_feature_acceptance"
            for node in nodes
        )
        and any(node.get("kind") == "final_gate" for node in nodes)
        and any(
            node.get("kind") == "verifier" and node.get("semantic_stage") == "final_audit"
            for node in nodes
        )
    )


def _evaluated_record_citations(context: GraphDispatchContext) -> dict[str, list[str]]:
    # Match callback validation: legacy audits keep the complete historical
    # candidate closure; only decision-v1 uses final-acceptance authority.
    consumer = (
        "final_audit"
        if context.node_payload.get("semantic_stage") == "final_audit"
        and (
            applicability := resolve_decision_applicability(
                context.graph_projection, context.node_id
            )
        )
        is not None
        and applicability.family == "verification_decision"
        else "check"
        if context.node_kind == "check"
        else "verifier"
    )
    return evidence_closure_for_node(
        context.graph_projection,
        context.node_id,
        consumer=consumer,
    ).citations()


def _hydrated_cited_records(
    projection: GraphProjection,
    record_ids: list[str],
) -> list[dict[str, Any]]:
    output_records = record_payloads_view(projection)
    file_states = file_state_records_view(projection)
    hydrated: list[dict[str, Any]] = []
    for record_id in _unique_record_ids(record_ids):
        file_state = file_states.get(record_id)
        if file_state is not None:
            hydrated.append(
                _hydrated_bound_record(
                    record_id=record_id,
                    record_kind="file_state",
                    record_payload=_compact_file_state_record(file_state),
                    hydration_policy="structured_json",
                )
            )
            continue
        record = output_records.get(record_id)
        if record is None:
            continue
        hydrated.append(
            _hydrated_bound_record(
                record_id=record_id,
                record_kind=str(record.get("record_kind", "output")),
                record_payload=_tail_only_prompt_record_payload(record),
                hydration_policy="structured_json",
            )
        )
    return hydrated


def _indirect_cited_record_ids(
    context: GraphDispatchContext,
    citations: dict[str, list[str]],
) -> list[str]:
    direct_record_ids = {
        record_id
        for binding in input_bindings_view(context.graph_projection)
        .get(context.node_id, {})
        .values()
        for record_id in binding.record_ids
    }
    return [
        record_id
        for record_id in citations.get("evaluated_record_ids", [])
        if record_id not in direct_record_ids
    ]


def _bound_record_ids_for_ports(
    context: GraphDispatchContext,
    ports: tuple[str, ...],
) -> list[str]:
    bindings = input_bindings_view(context.graph_projection).get(context.node_id, {})
    output: list[str] = []
    for port in ports:
        binding = bindings.get(port)
        if binding is None:
            continue
        output.extend(binding.record_ids)
    return _unique_record_ids(output)


def _unique_record_ids(record_ids: list[str]) -> list[str]:
    output: list[str] = []
    for record_id in record_ids:
        if record_id not in output:
            output.append(record_id)
    return output


def _add_evaluated_record_citations(
    record: dict[str, Any],
    citations: dict[str, list[str]],
    *,
    evidence: bool = False,
    value: bool = False,
    verification_reports_at_top_level: bool = True,
) -> dict[str, Any]:
    if not citations:
        return record
    output = dict(record)
    for key, record_ids in citations.items():
        if key == "verification_report_record_ids" and not verification_reports_at_top_level:
            continue
        output.setdefault(key, list(record_ids))
    candidate_ids = citations.get("candidate_record_ids")
    if candidate_ids is not None and len(candidate_ids) == 1:
        output.setdefault("candidate_record_id", candidate_ids[0])
    _merge_record_citations(output, "provenance", citations)
    if evidence:
        _merge_record_citations(output, "evidence", citations)
    if value:
        _merge_record_citations(output, "value", citations)
    return output


def _merge_record_citations(
    record: dict[str, Any],
    field: str,
    citations: dict[str, list[str]],
) -> None:
    if not citations:
        return
    existing = record.get(field)
    if existing is None:
        record[field] = {key: list(value) for key, value in citations.items()}
        return
    if not isinstance(existing, dict):
        return
    merged = dict(cast(dict[str, Any], existing))
    for key, value in citations.items():
        merged.setdefault(key, list(value))
    record[field] = merged


def _output_records_for_submit(
    context: GraphDispatchContext,
    grades: list[tuple[str, str, str | None]],
) -> list[dict[str, Any]]:
    node = context.node_payload
    candidate_id = str(node.get("candidate_id") or f"candidate-{context.node_id}")
    task_region_id = str(node.get("task_region_id") or context.node_id)
    attempt_number = int(node.get("attempt_number", 0))
    if context.node_kind == "planner":
        role = context.node_role
        if role == "gap_planner" and "_accepted_gap_planner_patch_had_ops" in node:
            patch_had_ops = node.get("_accepted_gap_planner_patch_had_ops") is True
            citations = _evaluated_record_citations(context)
            gap_value = {
                "milestone_kind": "gap_analysis",
                "classification": "corrective_work_required" if patch_had_ops else "no_gap",
                "source": (
                    "accepted_gap_planner_patch"
                    if patch_had_ops
                    else "accepted_gap_planner_no_op_patch"
                ),
                "task_region_id": task_region_id,
                "attempt_number": attempt_number,
            }
            records = [
                _gap_classification_record(
                    f"gap-plan-{context.execution_id}",
                    context.node_id,
                    "gap_plan",
                    gap_value,
                ),
                _gap_classification_record(
                    f"gap-classification-{context.execution_id}",
                    context.node_id,
                    "gap_classification",
                    gap_value,
                ),
                _gap_classification_record(
                    f"classified-gap-{context.execution_id}",
                    context.node_id,
                    "classified_gap",
                    gap_value,
                ),
            ]
            for record in records:
                _merge_record_citations(record, "provenance", citations)
            return records
        if role == "fan_out_reader":
            return [
                {
                    "record_id": candidate_id,
                    "record_kind": "output",
                    "record_type": "fan_out_inputs",
                    "producer_node_id": context.node_id,
                    "port": "reader_output",
                    "schema": "FanOutInputs",
                    "candidate_id": candidate_id,
                    "task_region_id": task_region_id,
                    "attempt_number": attempt_number,
                    "value": {"summary": "fan-out inputs submitted by graph runner"},
                }
            ]
        if role == "fan_out_join":
            return [
                {
                    "record_id": candidate_id,
                    "record_kind": "output",
                    "record_type": "fan_out_inputs",
                    "producer_node_id": context.node_id,
                    "port": "fan_out_inputs",
                    "schema": "FanOutJoinedInputs",
                    "candidate_id": candidate_id,
                    "task_region_id": task_region_id,
                    "attempt_number": attempt_number,
                    "value": {"summary": "fan-out join submitted by graph runner"},
                }
            ]
        return []
    if context.node_kind == "check":
        return []
    if context.node_kind in {"appeal", "oversight", "recovery"}:
        return [
            {
                "record_id": f"recovery-plan-{context.execution_id}",
                "record_kind": "output",
                "record_type": "recovery_plan",
                "producer_node_id": context.node_id,
                "port": "recovery_plan",
                "schema": "RecoveryPlan",
                "value": {
                    "action": "pause",
                    "responsible_actor": "oversight",
                    "graph_changes": [],
                    "reason": "appeal reviewed; explicit recovery action required",
                    "attempt_number": attempt_number,
                    "max_attempts": int(node.get("max_attempts", 3)),
                },
            }
        ]
    if context.node_kind == "verifier":
        candidate_id = _candidate_id_for_verifier(context)
        outcome = "passed" if _grades_pass(grades) else "failed"
        citations = _evaluated_record_citations(context)
        return [
            _add_evaluated_record_citations(
                {
                    "record_id": f"verification-{context.execution_id}",
                    "record_kind": "verification",
                    "producer_node_id": context.node_id,
                    "port": "verification_report",
                    "schema": "VerificationReport",
                    "candidate_id": candidate_id,
                    "task_region_id": task_region_id,
                    "outcome": outcome,
                    "value": {
                        "outcome": outcome,
                        "grades": [
                            {"requirement_id": req_id, "grade": grade, "reason": reason}
                            for req_id, grade, reason in grades
                        ],
                    },
                },
                citations,
                evidence=True,
                verification_reports_at_top_level=False,
            )
        ]
    candidate_record = {
        "record_id": candidate_id,
        "record_kind": "output",
        "producer_node_id": context.node_id,
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "candidate_id": candidate_id,
        "task_region_id": task_region_id,
        "attempt_number": attempt_number,
        "value": {"summary": "submitted by graph runner"},
    }
    superseded_region_id = correction_superseded_task_region_id(
        context.graph_projection,
        node,
    )
    if superseded_region_id is not None:
        candidate_record["supersedes_task_region_id"] = superseded_region_id
    return [
        candidate_record,
        *_artifact_reference_records_for_submit(context, candidate_id),
    ]


def _artifact_reference_records_for_submit(
    context: GraphDispatchContext,
    candidate_id: str,
) -> list[dict[str, Any]]:
    artifacts = context.node_payload.get("artifacts")
    if not isinstance(artifacts, list):
        return []
    output: list[dict[str, Any]] = []
    for index, raw_artifact in enumerate(cast(list[Any], artifacts)):
        if not isinstance(raw_artifact, dict):
            continue
        artifact = cast(dict[str, Any], raw_artifact)
        raw_path = artifact.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        artifact_id = str(artifact.get("id") or raw_path)
        summary = artifact.get("summary") or artifact.get("description")
        output.append(
            {
                "record_id": f"artifact-reference-{context.execution_id}-{index}",
                "record_kind": "graph_record",
                "record_type": "artifact_reference",
                "producer_node_id": context.node_id,
                "port": "artifact_reference",
                "schema": "ArtifactReference",
                "value": {
                    "artifact_id": artifact_id,
                    "artifact_type": "run_output",
                    "uri": raw_path,
                    "summary": str(summary) if summary is not None else None,
                    "source_record_ids": [candidate_id],
                },
            }
        )
    return output


def _gap_classification_record(
    record_id: str,
    producer_node_id: str,
    port: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    return GapClassificationRecord.model_validate(
        {
            "record_id": record_id,
            "record_kind": "output",
            "record_type": port,
            "producer_node_id": producer_node_id,
            "port": port,
            "schema": "GapClassification",
            "value": value,
        }
    ).model_dump(mode="json")


def _grades_pass(grades: list[tuple[str, str, str | None]]) -> bool:
    if not grades:
        return True
    passing = {"a", "pass", "passed", "ok", "yes"}
    return all(grade.strip().lower() in passing for _, grade, _ in grades)


prompt_for_node = _prompt_for_node
prompt_summary_for_node = _prompt_summary_for_node


def render_graph_node_prompt(context: GraphDispatchContext) -> str:
    """Render the production prompt packet for an assembled dispatch context."""

    return _prompt_for_node(context)


def summarize_graph_node_prompt(context: GraphDispatchContext) -> dict[str, Any]:
    """Return the production prompt-summary packet for a dispatch context."""

    return _prompt_summary_for_node(context)


planner_evidence = _planner_evidence
planner_packet = _planner_packet
can_submit_graph_patch = _can_submit_graph_patch
requires_graph_patch_before_submit = _requires_graph_patch_before_submit
graph_patch_feedback_accepted = _graph_patch_feedback_accepted
node_role = _node_role
available_tools_for_context = _available_tools_for_context
patch_payload_has_ops = _patch_payload_has_ops
patch_payload_creates_successor_planner = _patch_payload_creates_successor_planner
patch_payload_creates_finalization = _patch_payload_creates_finalization
output_records_for_submit = _output_records_for_submit
candidate_id_for_check = _candidate_id_for_check
evaluated_record_citations = _evaluated_record_citations
add_evaluated_record_citations = _add_evaluated_record_citations
