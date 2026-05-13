"""Pure delegated-work command and state models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from orchestrator.workflow.delegation.immutable import (
    ImmutableJsonMapping,
    freeze_json_mapping,
    thaw_json_mapping,
)


DelegationStableState = Literal[
    "WaitingOnDelegate",
    "ReviewDelegateResult",
    "MergeConflict",
    "AwaitingGate",
    "StaleCommandIgnored",
    "InvalidEvidence",
    "MissingDelegate",
    "NeedsRevision",
]

DelegatedWorkStatus = Literal[
    "requested",
    "running",
    "waiting",
    "terminal",
    "review",
    "integrated",
    "rejected",
    "abandoned",
    "stale_command_ignored",
]

DelegateCommandKind = Literal[
    "launch",
    "observe",
    "integrate",
    "reject",
    "abandon",
    "retry",
    "cancel",
]

DelegationDecisionKind = Literal[
    "launch",
    "wait",
    "review",
    "integrate",
    "reject",
    "retry",
    "ask_user",
    "complete",
    "stale_command_ignored",
    "conflict",
]


class DelegatedWork(BaseModel):
    """A reusable, policy-neutral representation of sub-agent work."""

    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    owner_kind: Literal["run", "task"]
    delegate_kind: Literal["run", "task", "external"]
    goal: str = ""
    generation: int = 0
    status: DelegatedWorkStatus = "requested"
    output_contract: str = ""
    policy_metadata: ImmutableJsonMapping = Field(default_factory=dict[str, Any])
    owner_token: str | None = None
    idempotency_keys: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("policy_metadata", mode="after")
    @classmethod
    def _freeze_policy_metadata(cls, value: ImmutableJsonMapping) -> ImmutableJsonMapping:
        return freeze_json_mapping(value)

    @field_serializer("policy_metadata")
    def _serialize_policy_metadata(self, value: ImmutableJsonMapping) -> dict[str, Any]:
        return thaw_json_mapping(value)


class DelegateCommand(BaseModel):
    """A command against delegated work with fencing and idempotency metadata."""

    model_config = ConfigDict(frozen=True)

    kind: DelegateCommandKind
    work_id: str
    owner_id: str
    idempotency_key: str
    expected_generation: int
    owner_token: str | None = None
    payload: ImmutableJsonMapping = Field(default_factory=dict[str, Any])

    @field_validator("payload", mode="after")
    @classmethod
    def _freeze_payload(cls, value: ImmutableJsonMapping) -> ImmutableJsonMapping:
        return freeze_json_mapping(value)

    @field_serializer("payload")
    def _serialize_payload(self, value: ImmutableJsonMapping) -> dict[str, Any]:
        return thaw_json_mapping(value)


class DelegateResultEnvelope(BaseModel):
    """Typed terminal result envelope produced by a delegate."""

    model_config = ConfigDict(frozen=True)

    work_id: str
    generation: int
    terminal_status: Literal["completed", "failed", "cancelled", "paused"]
    outcome: str = ""
    artifact_manifest: tuple[str, ...] = Field(default_factory=tuple)
    validation_status: Literal["valid", "invalid", "missing", "not_checked"] = "not_checked"
    integration_ready: bool = False
    reasons: tuple[str, ...] = Field(default_factory=tuple)


class DelegationDecision(BaseModel):
    """Policy result for the coordinator's next action."""

    model_config = ConfigDict(frozen=True)

    kind: DelegationDecisionKind
    work_id: str | None = None
    reason: str = ""
    stable_state: DelegationStableState | None = None
    payload: ImmutableJsonMapping = Field(default_factory=dict[str, Any])

    @field_validator("payload", mode="after")
    @classmethod
    def _freeze_payload(cls, value: ImmutableJsonMapping) -> ImmutableJsonMapping:
        return freeze_json_mapping(value)

    @field_serializer("payload")
    def _serialize_payload(self, value: ImmutableJsonMapping) -> dict[str, Any]:
        return thaw_json_mapping(value)


class DelegationPolicy(Protocol):
    """Pure reducer from owner/delegate facts to a next decision."""

    def reduce(
        self,
        owner_facts: Mapping[str, Any],
        works: Sequence[DelegatedWork],
        results: Mapping[str, DelegateResultEnvelope],
    ) -> DelegationDecision: ...


def apply_delegate_command(
    work: DelegatedWork | None,
    command: DelegateCommand,
) -> tuple[DelegatedWork | None, DelegationDecision]:
    """Apply common command fencing/idempotency rules without I/O.

    Policy-specific code should call this before it performs any side effects.
    """
    if work is None:
        return None, DelegationDecision(
            kind="review",
            work_id=command.work_id,
            reason="delegated_work_not_found",
            stable_state="MissingDelegate",
        )

    if command.work_id != work.id:
        return work, DelegationDecision(
            kind="stale_command_ignored",
            work_id=work.id,
            reason="work_id_mismatch",
            stable_state="StaleCommandIgnored",
        )

    if command.owner_id != work.owner_id:
        return work, DelegationDecision(
            kind="stale_command_ignored",
            work_id=work.id,
            reason="owner_mismatch",
            stable_state="StaleCommandIgnored",
        )

    if work.owner_token is not None and command.owner_token != work.owner_token:
        return work, DelegationDecision(
            kind="stale_command_ignored",
            work_id=work.id,
            reason="owner_token_mismatch",
            stable_state="StaleCommandIgnored",
        )

    if command.expected_generation != work.generation:
        return work, DelegationDecision(
            kind="stale_command_ignored",
            work_id=work.id,
            reason="generation_mismatch",
            stable_state="StaleCommandIgnored",
        )

    if command.idempotency_key in work.idempotency_keys:
        return work, DelegationDecision(
            kind="stale_command_ignored",
            work_id=work.id,
            reason="duplicate_command",
            stable_state="StaleCommandIgnored",
        )

    semantic_noop = _semantic_noop_reason(work, command.kind)
    if semantic_noop is not None:
        return work, DelegationDecision(
            kind="stale_command_ignored",
            work_id=work.id,
            reason=semantic_noop,
            stable_state="StaleCommandIgnored",
        )

    updated = work.model_copy(
        update={"idempotency_keys": (*work.idempotency_keys, command.idempotency_key)},
    )
    if command.kind == "launch" and updated.status == "requested":
        updated = updated.model_copy(update={"status": "running"})
        return updated, DelegationDecision(kind="launch", work_id=updated.id)
    if command.kind == "observe" and updated.status in ("requested", "running", "waiting"):
        updated = updated.model_copy(update={"status": "waiting"})
        return updated, DelegationDecision(
            kind="wait",
            work_id=updated.id,
            stable_state="WaitingOnDelegate",
        )
    if command.kind == "integrate" and updated.status in ("terminal", "review"):
        updated = updated.model_copy(update={"status": "integrated"})
        return updated, DelegationDecision(kind="integrate", work_id=updated.id)
    if command.kind in ("reject", "abandon") and updated.status in (
        "terminal",
        "review",
        "waiting",
    ):
        updated = updated.model_copy(
            update={"status": "abandoned" if command.kind == "abandon" else "rejected"}
        )
        return updated, DelegationDecision(kind="reject", work_id=updated.id)
    if command.kind == "retry" and updated.status in ("terminal", "review", "rejected"):
        updated = updated.model_copy(
            update={"status": "requested", "generation": updated.generation + 1}
        )
        return updated, DelegationDecision(kind="retry", work_id=updated.id)

    return work, DelegationDecision(
        kind="review",
        work_id=work.id,
        reason=f"command_{command.kind}_not_allowed_from_{work.status}",
        stable_state="ReviewDelegateResult",
    )


def _semantic_noop_reason(work: DelegatedWork, kind: DelegateCommandKind) -> str | None:
    """Return the deterministic reason for semantically duplicate commands."""
    if kind == "launch" and work.status in (
        "running",
        "waiting",
        "terminal",
        "integrated",
        "rejected",
        "abandoned",
    ):
        return f"launch_already_{work.status}"
    if kind in ("reject", "abandon") and work.status in (
        "integrated",
        "rejected",
        "abandoned",
    ):
        return f"resolve_already_{work.status}"
    if kind == "integrate" and work.status == "integrated":
        return "integrate_already_integrated"
    return None
