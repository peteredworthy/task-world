"""Strict record-event specifications needed by topology compilation.

Only ``output_record_accepted`` lives here during Task 3 so compiled topology
can be hydrated by the catalog.  Verification and gate semantics remain owned
by the later records slice.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import Field, model_validator

from orchestrator.graph.models import (
    OutputRecordPayload,
)
from orchestrator.graph.payloads import JsonValue, StrictPayload
from orchestrator.graph.specifications import (
    EventMetadata,
    EventSpecification,
    ProjectionParticipation,
)


class OutputRecordAcceptedPayload(StrictPayload):
    """Strict durable envelope for one already-validated output record."""

    record: OutputRecordPayload

    @model_validator(mode="after")
    def record_has_durable_identity(self) -> "OutputRecordAcceptedPayload":
        if not self.record.producer_node_id:
            raise ValueError("record must include producer_node_id")
        if self.record.model_extra:
            fields = ", ".join(sorted(self.record.model_extra))
            raise ValueError(f"record contains unknown strict output record fields: {fields}")
        return self

    def to_json(self) -> dict[str, JsonValue]:
        """Serialize the explicit record envelope without legacy flattening."""

        return cast(
            dict[str, JsonValue], self.model_dump(mode="json", by_alias=True, exclude_none=True)
        )

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Keep the nested typed record's declared aliases at serialization boundaries."""

        dumped = super().model_dump(*args, **kwargs)
        dumped["record"] = self.record.model_dump(
            mode=kwargs.get("mode", "python"),
            by_alias=kwargs.get("by_alias") is not False,
            exclude_none=kwargs.get("exclude_none", False),
        )
        return dumped


class VerificationOutcomePayload(StrictPayload):
    """Explicit verifier outcome facts; the record remains in its own event."""

    node_id: str
    verifier_node_id: str
    candidate_id: str
    outcome: Literal["passed", "failed"]
    record_id: str
    task_region_id: str | None = None
    evaluated_record_ids: list[str] = Field(default_factory=list)
    evidence: JsonValue | None = None


def reduce_output_record_accepted(
    state: Any,
    payload: OutputRecordAcceptedPayload,
    metadata: EventMetadata,
) -> Any:
    from orchestrator.graph.projections import reduce_typed_output_record_accepted

    return reduce_typed_output_record_accepted(state, payload, metadata)


def reduce_verification_passed(
    state: Any,
    payload: VerificationOutcomePayload,
    metadata: EventMetadata,
) -> Any:
    from orchestrator.graph.projections import reduce_typed_verification_outcome

    return reduce_typed_verification_outcome(state, payload, metadata)


def reduce_verification_failed(
    state: Any,
    payload: VerificationOutcomePayload,
    metadata: EventMetadata,
) -> Any:
    from orchestrator.graph.projections import reduce_typed_verification_outcome

    return reduce_typed_verification_outcome(state, payload, metadata)


OUTPUT_RECORD_ACCEPTED = EventSpecification(
    "output_record_accepted",
    OutputRecordAcceptedPayload,
    reduce_output_record_accepted,
    ProjectionParticipation.NEUTRAL,
)
VERIFICATION_PASSED = EventSpecification(
    "verification_passed",
    VerificationOutcomePayload,
    reduce_verification_passed,
    ProjectionParticipation.MUTATES,
)
VERIFICATION_FAILED = EventSpecification(
    "verification_failed",
    VerificationOutcomePayload,
    reduce_verification_failed,
    ProjectionParticipation.MUTATES,
)


EVENT_SPECIFICATIONS = (OUTPUT_RECORD_ACCEPTED, VERIFICATION_PASSED, VERIFICATION_FAILED)


__all__ = [
    "EVENT_SPECIFICATIONS",
    "OUTPUT_RECORD_ACCEPTED",
    "OutputRecordAcceptedPayload",
    "VERIFICATION_FAILED",
    "VERIFICATION_PASSED",
    "VerificationOutcomePayload",
    "reduce_output_record_accepted",
    "reduce_verification_failed",
    "reduce_verification_passed",
]
