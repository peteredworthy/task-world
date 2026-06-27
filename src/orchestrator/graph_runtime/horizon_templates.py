"""Deterministic graph horizon templates for planner prompts."""

from __future__ import annotations

from typing import Any


HORIZON_REGION_PURPOSES = (
    "discovery_region",
    "implementation_region",
    "validation_region",
    "gap_analysis_region",
    "corrective_work_region",
    "final_invariant_region",
)


def horizon_region_templates() -> list[dict[str, Any]]:
    """Return compact standard region-building templates for graph planners."""

    return [instantiate_horizon_template(purpose) for purpose in HORIZON_REGION_PURPOSES]


def instantiate_horizon_template(
    purpose: str,
    *,
    region_id: str = "region-template",
    candidate_id: str = "candidate-template",
) -> dict[str, Any]:
    """Instantiate a standard horizon template with placeholder-like ids."""

    if purpose == "discovery_region":
        return {
            "purpose": purpose,
            "description": "Create a bounded worker region that gathers missing evidence.",
            "expected_successor_readiness": (
                "Successor planning waits for accepted discovery output or file-state evidence."
            ),
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": f"worker-discovery-{region_id}",
                        "kind": "worker",
                        "role": "discovery",
                        "state": "planned",
                        "task_region_id": region_id,
                        "attempt_number": 1,
                        "candidate_id": f"discovery-{candidate_id}",
                    },
                }
            ],
        }

    if purpose == "implementation_region":
        return {
            "purpose": purpose,
            "description": "Create a bounded implementation worker for one candidate.",
            "expected_successor_readiness": (
                "Validation remains blocked until the worker produces an accepted candidate record."
            ),
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": f"worker-implementation-{region_id}",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "task_region_id": region_id,
                        "attempt_number": 1,
                        "candidate_id": candidate_id,
                    },
                }
            ],
        }

    if purpose == "validation_region":
        return {
            "purpose": purpose,
            "description": "Create a verifier that consumes one implementation candidate.",
            "expected_successor_readiness": (
                "The verifier is ready only after the candidate edge binds an accepted candidate."
            ),
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": f"verifier-validation-{region_id}",
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "planned",
                        "task_region_id": region_id,
                        "candidate_id": candidate_id,
                        "rubric": ["candidate satisfies the bound requirements"],
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": f"edge-implementation-validation-{region_id}",
                    "from_node_id": f"worker-implementation-{region_id}",
                    "from_port": "candidate",
                    "to_node_id": f"verifier-validation-{region_id}",
                    "to_port": "candidate_under_test",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["candidate"]},
                },
            ],
        }

    if purpose == "gap_analysis_region":
        return {
            "purpose": purpose,
            "description": "Create a gap planner that classifies verifier or check failures.",
            "expected_successor_readiness": (
                "Gap analysis waits for bound failure evidence before proposing corrective work. "
                "Use this as the failure continuation for required checks."
            ),
            "canonical_inputs": {
                "verification_evidence": {
                    "from_port": "verification_report",
                    "accepted_record_selector": {"record_kinds": ["verification", "check_result"]},
                }
            },
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": f"planner-gap-{region_id}",
                        "kind": "planner",
                        "role": "gap_planner",
                        "state": "planned",
                        "task_region_id": region_id,
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": f"edge-verification-gap-{region_id}",
                    "from_node_id": f"verifier-validation-{region_id}",
                    "from_port": "verification_report",
                    "to_node_id": f"planner-gap-{region_id}",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["verification", "check_result"]},
                },
            ],
        }

    if purpose == "corrective_work_region":
        return {
            "purpose": purpose,
            "description": "Create a corrective worker and verifier for a failed candidate.",
            "expected_successor_readiness": (
                "The corrective verifier waits on the corrective candidate edge."
            ),
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": f"worker-corrective-{region_id}",
                        "kind": "worker",
                        "role": "fixer",
                        "state": "planned",
                        "task_region_id": region_id,
                        "attempt_number": 2,
                        "candidate_id": f"corrective-{candidate_id}",
                    },
                },
                {
                    "op": "create_node",
                    "node": {
                        "node_id": f"verifier-corrective-{region_id}",
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "planned",
                        "task_region_id": region_id,
                        "candidate_id": f"corrective-{candidate_id}",
                        "rubric": ["corrective candidate resolves the classified gap"],
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": f"edge-classified-gap-corrective-{region_id}",
                    "from_node_id": f"planner-gap-{region_id}",
                    "from_port": "classified_gap",
                    "to_node_id": f"worker-corrective-{region_id}",
                    "to_port": "classified_gap",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["gap_analysis"]},
                },
                {
                    "op": "create_edge",
                    "edge_id": f"edge-corrective-validation-{region_id}",
                    "from_node_id": f"worker-corrective-{region_id}",
                    "from_port": "candidate",
                    "to_node_id": f"verifier-corrective-{region_id}",
                    "to_port": "candidate_under_test",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["candidate"]},
                },
            ],
        }

    if purpose == "final_invariant_region":
        return {
            "purpose": purpose,
            "description": "Create a final invariant check for accepted graph work.",
            "expected_successor_readiness": (
                "Completion waits for the check result record accepted by the invariant node. "
                "The planner must supply command_definition or command_binding and wire failed "
                "check_result evidence to a gap-analysis or corrective-work continuation."
            ),
            "runtime_binding_required": {
                "check_command": (
                    "Use command_binding='dynamic_feature_hidden_oracle' when the runtime "
                    "dynamic feature oracle should be bound; otherwise provide a concrete "
                    "command_definition for the invariant being checked."
                )
            },
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": f"check-final-invariant-{region_id}",
                        "kind": "check",
                        "role": "invariant_gate",
                        "state": "planned",
                        "task_region_id": region_id,
                        "command_binding": "dynamic_feature_hidden_oracle",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": f"edge-corrective-verification-final-{region_id}",
                    "from_node_id": f"verifier-corrective-{region_id}",
                    "from_port": "verification_report",
                    "to_node_id": f"check-final-invariant-{region_id}",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {"record_kinds": ["verification", "check_result"]},
                },
            ],
        }

    raise ValueError(f"unknown horizon region template purpose: {purpose}")
