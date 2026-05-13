"""Persistence helpers for delegated-work decisions stored in owner facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field
from pydantic import field_serializer, field_validator

from orchestrator.workflow.delegation.immutable import (
    ImmutableJsonMapping,
    freeze_json_mapping,
    thaw_json_mapping,
)
from orchestrator.workflow.delegation.models import (
    DelegateCommand,
    DelegateResultEnvelope,
    DelegatedWork,
    DelegationDecision,
    DelegationStableState,
    apply_delegate_command,
)


class DelegationRecord(BaseModel):
    """JSON-safe audit record for a delegated-work command or result."""

    model_config = ConfigDict(frozen=True)

    work_id: str | None = None
    kind: str
    reason: str = ""
    stable_state: str | None = None
    idempotency_key: str | None = None
    expected_generation: int | None = None
    owner_token: str | None = None
    recorded_at: datetime
    payload: ImmutableJsonMapping = Field(default_factory=dict[str, Any])

    @field_validator("payload", mode="after")
    @classmethod
    def _freeze_payload(cls, value: ImmutableJsonMapping) -> ImmutableJsonMapping:
        return freeze_json_mapping(value)

    @field_serializer("payload")
    def _serialize_payload(self, value: ImmutableJsonMapping) -> dict[str, Any]:
        return thaw_json_mapping(value)


class DelegationResultRecord(BaseModel):
    """JSON-safe immutable record for a delegate terminal result."""

    model_config = ConfigDict(frozen=True)

    work_id: str
    generation: int
    terminal_status: str
    outcome: str = ""
    artifact_manifest: tuple[str, ...] = Field(default_factory=tuple)
    validation_status: str = "not_checked"
    integration_ready: bool = False
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    recorded_at: datetime


class DelegationReviewStateRecord(BaseModel):
    """JSON-safe immutable record for a visible delegate review blocker."""

    model_config = ConfigDict(frozen=True)

    work_id: str | None = None
    stable_state: str
    reason: str = ""
    payload: ImmutableJsonMapping = Field(default_factory=dict[str, Any])
    recorded_at: datetime

    @field_validator("payload", mode="after")
    @classmethod
    def _freeze_payload(cls, value: ImmutableJsonMapping) -> ImmutableJsonMapping:
        return freeze_json_mapping(value)

    @field_serializer("payload")
    def _serialize_payload(self, value: ImmutableJsonMapping) -> dict[str, Any]:
        return thaw_json_mapping(value)


class DelegationState(BaseModel):
    """Immutable value object for delegated-work state stored in oversight JSON."""

    model_config = ConfigDict(frozen=True)

    delegated_work: tuple[DelegatedWork, ...] = Field(default_factory=tuple)
    delegation_decisions: tuple[DelegationRecord, ...] = Field(default_factory=tuple)
    delegation_results: tuple[DelegationResultRecord, ...] = Field(default_factory=tuple)
    delegation_review_states: tuple[DelegationReviewStateRecord, ...] = Field(default_factory=tuple)

    @classmethod
    def from_oversight_state(cls, owner_state: Mapping[str, Any]) -> "DelegationState":
        """Load delegation facts from raw oversight JSON."""
        raw_work = owner_state.get("delegated_work")
        delegated_work: tuple[DelegatedWork, ...] = ()
        if isinstance(raw_work, Mapping):
            delegated_work = tuple(
                DelegatedWork.model_validate(item)
                for key, item in sorted(
                    cast(Mapping[Any, Any], raw_work).items(), key=lambda pair: str(pair[0])
                )
                if isinstance(key, str) and isinstance(item, Mapping)
            )

        return cls(
            delegated_work=delegated_work,
            delegation_decisions=tuple(
                DelegationRecord.model_validate(item)
                for item in _dict_list(owner_state.get("delegation_decisions"))
            ),
            delegation_results=tuple(
                DelegationResultRecord.model_validate(item)
                for item in _dict_list(owner_state.get("delegation_results"))
            ),
            delegation_review_states=tuple(
                DelegationReviewStateRecord.model_validate(item)
                for item in _dict_list(owner_state.get("delegation_review_states"))
            ),
        )

    def to_oversight_patch(self) -> dict[str, Any]:
        """Return only the delegation-owned JSON fields."""
        return {
            "delegated_work": {
                work.id: work.model_dump(mode="json") for work in self.delegated_work
            },
            "delegation_decisions": [
                item.model_dump(mode="json") for item in self.delegation_decisions
            ],
            "delegation_results": [
                item.model_dump(mode="json") for item in self.delegation_results
            ],
            "delegation_review_states": [
                item.model_dump(mode="json") for item in self.delegation_review_states
            ],
        }

    def merge_into(self, owner_state: Mapping[str, Any]) -> dict[str, Any]:
        """Merge delegation-owned JSON fields into an oversight state payload."""
        updated_state = dict(owner_state)
        updated_state.update(self.to_oversight_patch())
        return updated_state

    def with_decision(
        self,
        decision: DelegationDecision,
        *,
        recorded_at: datetime,
        idempotency_key: str | None = None,
        expected_generation: int | None = None,
        owner_token: str | None = None,
    ) -> "DelegationState":
        records = (
            *self.delegation_decisions,
            DelegationRecord(
                work_id=decision.work_id,
                kind=decision.kind,
                reason=decision.reason,
                stable_state=decision.stable_state,
                idempotency_key=idempotency_key,
                expected_generation=expected_generation,
                owner_token=owner_token,
                recorded_at=recorded_at,
                payload=decision.payload,
            ),
        )[-100:]
        return self.model_copy(update={"delegation_decisions": records})

    def with_work(self, work: DelegatedWork) -> "DelegationState":
        delegated_work = {item.id: item for item in self.delegated_work}
        delegated_work[work.id] = work
        return self.model_copy(
            update={"delegated_work": tuple(item for _, item in sorted(delegated_work.items()))}
        )

    def apply_command(
        self,
        work: DelegatedWork | None,
        command: DelegateCommand,
        *,
        recorded_at: datetime,
    ) -> tuple["DelegationState", DelegatedWork | None, DelegationDecision]:
        """Apply a delegate command and return a new immutable state."""
        updated_work, decision = apply_delegate_command(work, command)
        updated_state = self.with_decision(
            decision,
            recorded_at=recorded_at,
            idempotency_key=command.idempotency_key,
            expected_generation=command.expected_generation,
            owner_token=command.owner_token,
        )
        if updated_work is not None:
            updated_state = updated_state.with_work(updated_work)
        return updated_state, updated_work, decision

    def with_result(
        self,
        result: DelegateResultEnvelope,
        decision: DelegationDecision,
        *,
        recorded_at: datetime,
    ) -> "DelegationState":
        results = (
            *self.delegation_results,
            DelegationResultRecord(
                work_id=result.work_id,
                generation=result.generation,
                terminal_status=result.terminal_status,
                outcome=result.outcome,
                artifact_manifest=tuple(result.artifact_manifest),
                validation_status=result.validation_status,
                integration_ready=result.integration_ready,
                reasons=tuple(result.reasons),
                recorded_at=recorded_at,
            ),
        )[-100:]
        updated_state = self.model_copy(update={"delegation_results": results}).with_decision(
            decision,
            recorded_at=recorded_at,
        )
        if decision.kind in ("complete", "integrate"):
            review_states = tuple(
                item
                for item in updated_state.delegation_review_states
                if item.work_id != decision.work_id
            )[-100:]
            updated_state = updated_state.model_copy(
                update={"delegation_review_states": review_states}
            )
        if decision.stable_state is not None and decision.kind in ("conflict", "review", "reject"):
            review_states = tuple(
                item
                for item in updated_state.delegation_review_states
                if item.work_id != decision.work_id
            )
            review_states = (
                *review_states,
                DelegationReviewStateRecord(
                    work_id=decision.work_id,
                    stable_state=decision.stable_state,
                    reason=decision.reason,
                    payload=decision.payload,
                    recorded_at=recorded_at,
                ),
            )[-100:]
            updated_state = updated_state.model_copy(
                update={"delegation_review_states": review_states}
            )
        return updated_state

    def with_review_state(
        self,
        *,
        work_id: str,
        stable_state: DelegationStableState,
        reason: str,
        payload: dict[str, Any],
        recorded_at: datetime,
    ) -> "DelegationState":
        decision = DelegationDecision(
            kind="review" if stable_state != "MergeConflict" else "conflict",
            work_id=work_id,
            reason=reason,
            stable_state=stable_state,
            payload=payload,
        )
        updated_state = self.with_decision(decision, recorded_at=recorded_at)
        review_states = tuple(
            item for item in updated_state.delegation_review_states if item.work_id != work_id
        )
        review_states = (
            *review_states,
            DelegationReviewStateRecord(
                work_id=work_id,
                stable_state=stable_state,
                reason=reason,
                payload=payload,
                recorded_at=recorded_at,
            ),
        )[-100:]
        return updated_state.model_copy(update={"delegation_review_states": review_states})


class DelegationCoordinator:
    """Apply generic delegation rules and persist their observable decisions."""

    def record_work_state(
        self,
        owner_state: Mapping[str, Any],
        work: DelegatedWork,
    ) -> dict[str, Any]:
        """Replace one durable delegated-work fact."""
        return (
            DelegationState.from_oversight_state(owner_state)
            .with_work(work)
            .merge_into(owner_state)
        )

    def apply_command(
        self,
        owner_state: Mapping[str, Any],
        work: DelegatedWork | None,
        command: DelegateCommand,
        *,
        recorded_at: datetime,
    ) -> tuple[dict[str, Any], DelegatedWork | None, DelegationDecision]:
        """Apply a command and append a durable decision audit entry."""
        delegation_state = DelegationState.from_oversight_state(owner_state)
        updated_delegation_state, updated_work, decision = delegation_state.apply_command(
            work,
            command,
            recorded_at=recorded_at,
        )
        return updated_delegation_state.merge_into(owner_state), updated_work, decision

    def record_result(
        self,
        owner_state: Mapping[str, Any],
        result: DelegateResultEnvelope,
        decision: DelegationDecision,
        *,
        recorded_at: datetime,
    ) -> dict[str, Any]:
        """Append a durable delegate result and matching decision."""
        return (
            DelegationState.from_oversight_state(owner_state)
            .with_result(result, decision, recorded_at=recorded_at)
            .merge_into(owner_state)
        )

    def record_decision(
        self,
        owner_state: Mapping[str, Any],
        decision: DelegationDecision,
        *,
        recorded_at: datetime,
        idempotency_key: str | None = None,
        expected_generation: int | None = None,
        owner_token: str | None = None,
    ) -> dict[str, Any]:
        """Append a durable delegated-work decision audit entry."""
        return (
            DelegationState.from_oversight_state(owner_state)
            .with_decision(
                decision,
                recorded_at=recorded_at,
                idempotency_key=idempotency_key,
                expected_generation=expected_generation,
                owner_token=owner_token,
            )
            .merge_into(owner_state)
        )

    def record_review_state(
        self,
        owner_state: Mapping[str, Any],
        *,
        work_id: str,
        stable_state: DelegationStableState,
        reason: str,
        payload: dict[str, Any],
        recorded_at: datetime,
    ) -> dict[str, Any]:
        """Record a visible review blocker for a delegate."""
        return (
            DelegationState.from_oversight_state(owner_state)
            .with_review_state(
                work_id=work_id,
                stable_state=stable_state,
                reason=reason,
                payload=payload,
                recorded_at=recorded_at,
            )
            .merge_into(owner_state)
        )

    def _dict_list(self, value: Any) -> list[dict[str, Any]]:
        return _dict_list(value)


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (bytes, str)):
        return []
    return [
        dict(cast(Mapping[str, Any], item))
        for item in cast(Sequence[Any], value)
        if isinstance(item, Mapping)
    ]
