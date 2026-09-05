"""Server-side issuance and runtime verification of reliable-plan authority."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import ReliablePlanQualificationRepository
from orchestrator.graph import (
    GraphProjection,
    ReliablePlanQualificationAuthorityFacts,
    ReliablePlanQualificationGrant,
    ReliablePlanScenarioManifest,
    qualification_from_accepted_records,
    reliable_plan_assignment_carrier,
)


_INTERNAL_AUTHORIZATION_KEY = "_reliable_plan_authorization"


async def issue_reliable_plan_qualification(
    session: AsyncSession,
    manifest: ReliablePlanScenarioManifest,
    projection: GraphProjection,
    accepted_receipt_record_id: str,
    *,
    reference_factory: Callable[[], str],
) -> ReliablePlanQualificationGrant:
    """Issue one opaque grant from exact controller-accepted projection facts."""
    qualification, receipt = qualification_from_accepted_records(
        manifest,
        projection,
        accepted_receipt_record_id,
    )
    facts = ReliablePlanQualificationAuthorityFacts(
        qualification=qualification,
        receipt=receipt,
    )
    reference = f"rpq_{reference_factory()}"
    grant = ReliablePlanQualificationGrant(reference=reference, facts=facts)
    await ReliablePlanQualificationRepository(session).issue(
        grant.reference,
        grant.facts.model_dump(mode="json"),
    )
    return grant


async def consume_reliable_plan_qualification(
    session: AsyncSession,
    *,
    reference: str,
    run_id: str,
    skeleton_id: str,
) -> ReliablePlanQualificationAuthorityFacts:
    """Atomically bind a grant to one run and validate its server-owned facts."""
    raw = await ReliablePlanQualificationRepository(session).consume(reference, run_id)
    facts = ReliablePlanQualificationAuthorityFacts.model_validate(raw)
    if facts.qualification.manifest.skeleton_id != skeleton_id:
        raise ValueError("qualification reference does not match reliable-plan skeleton")
    return facts


async def require_reliable_plan_qualification_for_run(
    session: AsyncSession,
    *,
    run_id: str,
    run_config: dict[str, Any],
    selected_runner_type: str,
) -> ReliablePlanQualificationAuthorityFacts:
    """Revalidate the durable reference/run binding immediately before graph seed."""
    raw_authorization = run_config.get(_INTERNAL_AUTHORIZATION_KEY)
    if not isinstance(raw_authorization, dict):
        raise ValueError("reliable-plan run is missing server authorization")
    authorization = cast(dict[str, object], raw_authorization)
    reference = authorization.get("reference")
    if not isinstance(reference, str):
        raise ValueError("reliable-plan run authorization reference is missing")
    raw = await ReliablePlanQualificationRepository(session).require_bound(reference, run_id)
    facts = ReliablePlanQualificationAuthorityFacts.model_validate(raw)
    expected_hash = authorization.get("evidence_hash")
    if facts.receipt.evidence_hash != expected_hash:
        raise ValueError("reliable-plan run authorization evidence mismatch")
    skeleton_id = run_config.get("reliable_plan_skeleton_id")
    if facts.qualification.manifest.skeleton_id != skeleton_id:
        raise ValueError("reliable-plan run authorization skeleton mismatch")
    reliable_plan_assignment_carrier(
        skeleton_id=str(skeleton_id),
        arm=run_config.get("reliable_plan_model_assignments"),
        selected_runner_type=selected_runner_type,
    )
    return facts


def sealed_reliable_plan_run_authorization(
    reference: str,
    facts: ReliablePlanQualificationAuthorityFacts,
) -> dict[str, str]:
    """Build the private persisted marker after atomic server-side consumption."""
    return {
        "reference": reference,
        "evidence_hash": facts.receipt.evidence_hash,
    }


def has_caller_supplied_reliable_plan_authorization(config: dict[str, Any]) -> bool:
    return _INTERNAL_AUTHORIZATION_KEY in config


def verified_reliable_plan_seed_config(
    run_config: dict[str, Any],
    facts: ReliablePlanQualificationAuthorityFacts,
    *,
    selected_runner_type: str,
) -> dict[str, Any]:
    """Replace the opaque reference with the bounded capability consumed by compilation."""
    result = dict(run_config)
    carrier = reliable_plan_assignment_carrier(
        skeleton_id=str(result.get("reliable_plan_skeleton_id")),
        arm=result.get("reliable_plan_model_assignments"),
        selected_runner_type=selected_runner_type,
    )
    result.pop(_INTERNAL_AUTHORIZATION_KEY, None)
    result["reliable_plan_model_assignments"] = carrier.arm.model_dump(mode="json")
    result["reliable_plan_selected_runner_type"] = carrier.selected_runner_type
    result["reliable_plan_one_horizon_authorized"] = True
    # Controller-owned authority for the supported bounded sequential profile:
    # horizon one, followed by one successor planned from accepted evidence.
    result["reliable_plan_remaining_horizons"] = 2
    result["reliable_plan_qualification_evidence_hash"] = facts.receipt.evidence_hash
    return result
