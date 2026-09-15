"""Shared, provider-neutral failure diagnostics."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


FailureCategory = Literal[
    "answer_validation",
    "stale_binding",
    "execution",
    "candidate_check",
    "infrastructure_environment",
    "budget_exhaustion",
]

FailureNextAction = Literal[
    "correct_answer",
    "refresh_binding",
    "retry_or_recover",
    "correct_candidate",
    "resolve_environment",
    "stop",
]


class FailureDiagnostic(BaseModel):
    """Bounded, provider-neutral explanation of one observable failure."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    category: FailureCategory
    code: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    message: str = Field(min_length=1, max_length=2_048)
    next_action: FailureNextAction
    correction_allowed: bool
    protected_evidence_refs: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("protected_evidence_refs")
    @classmethod
    def validate_protected_evidence_refs(cls, refs: tuple[str, ...]) -> tuple[str, ...]:
        for ref in refs:
            if len(ref) > 256 or not ref.strip() or ":" not in ref:
                raise ValueError("protected evidence references must be opaque scheme references")
            scheme, identifier = ref.split(":", 1)
            if scheme not in {"artifact", "cas", "evidence", "graph-event"} or not identifier:
                raise ValueError(
                    "protected evidence references must use a protected evidence scheme"
                )
        return refs
