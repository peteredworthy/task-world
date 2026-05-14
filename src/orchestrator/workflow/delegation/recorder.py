"""Shared delegation-state recording helper."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from orchestrator.workflow.delegation.coordinator import DelegationState
from orchestrator.workflow.delegation.models import (
    DelegateCommand,
    DelegateResultEnvelope,
    DelegatedWork,
    DelegationDecision,
    DelegationStableState,
)
from orchestrator.workflow.engine import Clock


class DelegationRecorder:
    """Record delegated-work commands, results, and review states into owner facts."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def apply_command(
        self,
        owner_state: Mapping[str, Any],
        work: DelegatedWork | None,
        command: DelegateCommand,
    ) -> tuple[dict[str, Any], DelegatedWork | None, DelegationDecision]:
        delegation = DelegationState.from_oversight_state(owner_state)
        updated, updated_work, decision = delegation.apply_command(
            work,
            command,
            recorded_at=self._clock.now(),
        )
        return updated.merge_into(owner_state), updated_work, decision

    def record_decision(
        self,
        owner_state: Mapping[str, Any],
        decision: DelegationDecision,
        *,
        idempotency_key: str | None = None,
        expected_generation: int | None = None,
        owner_token: str | None = None,
    ) -> dict[str, Any]:
        return (
            DelegationState.from_oversight_state(owner_state)
            .with_decision(
                decision,
                recorded_at=self._clock.now(),
                idempotency_key=idempotency_key,
                expected_generation=expected_generation,
                owner_token=owner_token,
            )
            .merge_into(owner_state)
        )

    def record_result(
        self,
        owner_state: Mapping[str, Any],
        result: DelegateResultEnvelope,
        decision: DelegationDecision,
    ) -> dict[str, Any]:
        return (
            DelegationState.from_oversight_state(owner_state)
            .with_result(result, decision, recorded_at=self._clock.now())
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
    ) -> dict[str, Any]:
        return (
            DelegationState.from_oversight_state(owner_state)
            .with_review_state(
                work_id=work_id,
                stable_state=stable_state,
                reason=reason,
                payload=payload,
                recorded_at=self._clock.now(),
            )
            .merge_into(owner_state)
        )

    def record_work(
        self,
        owner_state: Mapping[str, Any],
        work: DelegatedWork,
    ) -> dict[str, Any]:
        return (
            DelegationState.from_oversight_state(owner_state)
            .with_work(work)
            .merge_into(owner_state)
        )
