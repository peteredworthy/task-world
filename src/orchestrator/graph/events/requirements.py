"""Strict requirement-revision and support-evidence specifications and reducers."""

from typing import Any, Literal

from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    EventMetadata,
    EventSpecification,
    ProjectionParticipation,
)


class RequirementRevisionPayload(StrictPayload):
    requirement_id: str
    version_id: str
    record_id: str | None = None
    classification: str | None = None
    change_classification: str | None = None
    revision_type: str | None = None
    requires_authority: bool | None = None
    explicit_authority_required: bool | None = None
    new_behavior: bool | None = None
    behavior_change: bool | None = None
    semantic_change: bool | None = None
    validation_strengthening: bool | None = None
    active: bool = True
    previous_version_id: str | None = None
    revision_index: int | None = None
    authority_required_reason: str | None = None


class SupportEvidencePayload(StrictPayload):
    support_id: str
    evidence_id: str
    requirement_id: str
    requirement_version_id: str
    status: Literal["active", "stale"] = "active"
    stale_reason: str | None = None
    confidence: str | None = None


def reduce_requirement_revision(
    state: Any, payload: RequirementRevisionPayload, metadata: EventMetadata
) -> Any:
    from orchestrator.graph.projections import (
        authority_required_reason,
        mark_superseded_support_stale,
        requirement_revision_classification,
        requirement_revision_from_payload,
        requires_explicit_requirement_authority,
        copy_projection,
    )

    next_state = copy_projection(state)
    values = payload.model_dump(mode="python", exclude_none=True)
    classification = requirement_revision_classification(values)
    requires_authority = requires_explicit_requirement_authority(values, classification)
    revision_values: dict[str, Any] = {
        "requirement_id": payload.requirement_id,
        "version_id": payload.version_id,
        "change_classification": classification,
        "requires_authority": requires_authority,
        "position": metadata.position,
        "validation_strengthening": payload.validation_strengthening is True
        or classification == "validation_strengthening",
    }
    authority_reason = authority_required_reason(values, classification)
    if authority_reason is not None:
        revision_values["authority_required_reason"] = authority_reason
    for name in ("previous_version_id", "revision_index", "authority_required_reason"):
        value = getattr(payload, name)
        if value is not None:
            revision_values[name] = value
    revision = requirement_revision_from_payload(revision_values)
    if revision is not None:
        next_state["requirement_revisions"][payload.version_id] = revision
        if payload.active:
            next_state["active_requirement_versions"][payload.requirement_id] = payload.version_id
        if revision.validation_strengthening:
            mark_superseded_support_stale(next_state, payload.requirement_id, payload.version_id)
    if requires_authority:
        next_state["authority_revision_blockers"][payload.version_id] = {
            "kind": "unresolved_authority_required_revision",
            "reason": "semantic or new-behavior requirement revision lacks authority resolution",
            "revision_id": payload.version_id,
            "requirement_id": payload.requirement_id,
        }
    else:
        next_state["authority_revision_blockers"].pop(payload.version_id, None)
    return next_state


def reduce_support_evidence(
    state: Any, payload: SupportEvidencePayload, metadata: EventMetadata
) -> Any:
    from orchestrator.graph.projections import support_evidence_from_payload, copy_projection

    next_state = copy_projection(state)
    values = payload.model_dump(mode="python", exclude_none=True)
    values["position"] = metadata.position
    support = support_evidence_from_payload(values)
    if support is not None:
        next_state["support_evidence"][payload.support_id] = support
    return next_state


REQUIREMENT_REVISION_RECORDED = EventSpecification(
    "requirement_revision_recorded",
    RequirementRevisionPayload,
    reduce_requirement_revision,
    ProjectionParticipation.MUTATES,
)
SUPPORT_EVIDENCE_RECORDED = EventSpecification(
    "support_evidence_recorded",
    SupportEvidencePayload,
    reduce_support_evidence,
    ProjectionParticipation.MUTATES,
)
EVENT_SPECIFICATIONS = (REQUIREMENT_REVISION_RECORDED, SUPPORT_EVIDENCE_RECORDED)
