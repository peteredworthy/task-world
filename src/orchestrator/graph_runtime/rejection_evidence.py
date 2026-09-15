"""Protected, bounded reproduction evidence for rejected graph patches."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.artifacts import ArtifactIntegrityError, ArtifactNotFoundError, ArtifactStore
from orchestrator.config import FailureDiagnostic
from orchestrator.db import EventV2Model
from orchestrator.graph import (
    BoundaryValidationError,
    Clock,
    DECISION_COMPILER_CONTRACT_VERSION,
    DecisionSubmissionRequest,
    EventEnvelope,
    GraphProjection,
    IdGenerator,
    PatchCommandContext,
    StoredArtifactRef,
    canonical_decision_answer,
    canonical_decision_answer_hash,
    compile_decision,
    compile_implementation_plan,
    decision_answer_schema,
    execution_attempts_view,
    resolve_decision_applicability,
    resolve_decision_context,
)
from orchestrator.graph_runtime.controller import GraphController
from orchestrator.graph_runtime.store import GraphEventStore
from orchestrator.graph_runtime.submission_gate import (
    SubmissionGateCommandResult,
    gate_rejection_evidence,
    submission_gate_failure_fingerprint,
)
from orchestrator.runners import SubmissionRejectionCategory, SubmissionRejectionEvidence

REJECTION_EVIDENCE_MEDIA_TYPE = "application/vnd.orchestrator.rejection-evidence+json"
MAX_REJECTION_EVIDENCE_BYTES = 512 * 1024
MAX_REJECTION_PREFIX_EVENTS = 4_096
MAX_SOURCE_BOUNDARY_BYTES = 2 * 1024 * 1024
_GRAPH_PREFIX_BYTES = 384 * 1024
_REQUEST_RESPONSE_BYTES = 96 * 1024
_GRAPH_READ_BATCH = 32
_SOURCE_PATHS = ("src/orchestrator", "routines", "pyproject.toml", "uv.lock")

RejectionEvidenceClassification = Literal[
    "exact_replay",
    "evidence_oversize",
    "graph_prefix_incomplete",
    "source_boundary_oversize",
]

DecisionAnswerReceiptClassification = Literal[
    "exact_replay",
    "evidence_oversize",
    "graph_prefix_incomplete",
    "question_context_incomplete",
    "source_boundary_incomplete",
    "unreceived",
    "unknown_contract",
    "rejection_outcome_incomplete",
]


class SourceIdentity(BaseModel):
    """Git and dirty-worktree identity observed at the rejected request boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    head_commit: str
    status_sha256: str
    tracked_diff_sha256: str
    untracked_content_sha256: str
    complete: bool


class RejectionEvidencePublicRef(BaseModel):
    """Safe metadata suitable for graph events and public API projections."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_ref: StoredArtifactRef
    content_hash: str
    size_bytes: int = Field(ge=0)
    classification: RejectionEvidenceClassification
    replayable: bool


class RejectionEvidenceArtifact(BaseModel):
    """Private CAS payload. Caller-controlled request text never enters public events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    classification: RejectionEvidenceClassification
    replayable: bool
    run_id: str
    proposed_by_node_id: str
    actor_role: str
    graph_position: int = Field(ge=0)
    graph_prefix_sha256: str
    graph_prefix_complete: bool
    source_identity: SourceIdentity
    request_sha256: str
    response_sha256: str
    request_size_bytes: int = Field(ge=0)
    response_size_bytes: int = Field(ge=0)
    request_response_complete: bool
    request: dict[str, Any] | None = None
    response: str | None = None
    graph_prefix: tuple[EventEnvelope, ...] | None = None


class RejectionReplayResult(BaseModel):
    """Result of a deterministic rejection replay in an isolated store."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reproduced: Literal[True] = True
    response: str
    graph_prefix_sha256: str
    source_identity: SourceIdentity


class DecisionAnswerReceiptPublicRef(BaseModel):
    """Safe metadata for a protected decision-answer receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_ref: StoredArtifactRef
    content_hash: str
    size_bytes: int = Field(ge=0)
    classification: DecisionAnswerReceiptClassification
    replayable: bool


class DecisionAnswerRejectionOutcome(BaseModel):
    """Typed semantic cause retained before the receipt's own CAS identity exists."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: Literal["answer_validation", "candidate_check"]
    submitted_answer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_diagnostic: FailureDiagnostic
    rejection_category: SubmissionRejectionCategory
    rejection_evidence: SubmissionRejectionEvidence
    candidate_tree_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40,64}$")

    @model_validator(mode="after")
    def outcome_is_consistent(self) -> "DecisionAnswerRejectionOutcome":
        if self.rejection_evidence.category != self.rejection_category:
            raise ValueError("decision rejection category and evidence conflict")
        if self.phase == "candidate_check":
            if self.rejection_category != "candidate_check_failed":
                raise ValueError("candidate-check outcome requires candidate-check evidence")
            if self.candidate_tree_sha is None:
                raise ValueError("candidate-check outcome requires candidate tree identity")
            audit_ref = self.rejection_evidence.durable_audit_reference
            if (
                audit_ref is None
                or audit_ref not in self.failure_diagnostic.protected_evidence_refs
            ):
                raise ValueError("candidate-check outcome requires protected gate-audit evidence")
            if self.failure_diagnostic.category not in {
                "candidate_check",
                "budget_exhaustion",
            }:
                raise ValueError("candidate-check outcome has incompatible failure diagnostic")
        elif self.rejection_category != "submission_format_rejected":
            raise ValueError("answer-validation outcome requires format-rejection evidence")
        elif self.failure_diagnostic.category not in {
            "answer_validation",
            "budget_exhaustion",
        }:
            raise ValueError("answer-validation outcome has incompatible failure diagnostic")
        return self


class DecisionAnswerReceiptArtifact(BaseModel):
    """Bounded protected evidence for one received decision answer.

    The artifact carries only trusted contract metadata plus canonical request,
    response, answer, and question-context values.  It is deliberately not a
    graph record: a replay can verify the original experiment boundary without
    becoming a second source of lifecycle or graph authority.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    status: Literal["accepted", "rejected"]
    classification: DecisionAnswerReceiptClassification
    replayable: bool
    interaction_contract: Literal["decision-v1"]
    answer_family: Literal[
        "discovery_brief",
        "implementation_plan",
        "batch_decision",
        "correction_decision",
        "verification_decision",
        "work_result",
    ]
    compiler_contract_version: int = Field(ge=1)
    run_id: str = Field(min_length=1)
    answer_schema_id: str = Field(min_length=1)
    answer_schema_version: int = Field(ge=1)
    answer_schema_sha256: str
    decision_request_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    graph_position: int = Field(ge=0)
    answer_attempt_id: str = Field(min_length=1)
    delivery_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_identity: SourceIdentity
    request_sha256: str
    response_sha256: str
    request_size_bytes: int = Field(ge=0)
    response_size_bytes: int = Field(ge=0)
    request_response_complete: bool
    contract_request_sha256: str | None = None
    contract_request_size_bytes: int = Field(default=0, ge=0)
    contract_request_complete: bool = False
    question_context_sha256: str
    question_context_size_bytes: int = Field(ge=0)
    question_context_complete: bool
    graph_prefix_sha256: str
    graph_prefix_complete: bool
    answer_sha256: str | None = None
    rejection_outcome: DecisionAnswerRejectionOutcome | None = None
    receipt_integrity_sha256: str
    request: dict[str, Any] | None = None
    contract_request: dict[str, Any] | None = None
    response: dict[str, Any] | str | None = None
    answer: dict[str, Any] | None = None
    question_context: dict[str, Any] | None = None
    graph_prefix: tuple[EventEnvelope, ...] | None = None

    @field_validator(
        "answer_schema_sha256",
        "request_sha256",
        "response_sha256",
        "contract_request_sha256",
        "question_context_sha256",
        "answer_sha256",
        "receipt_integrity_sha256",
        "graph_prefix_sha256",
    )
    @classmethod
    def hashes_are_canonical(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith("sha256:") or len(value) != 71:
            raise ValueError("receipt hashes must use sha256:<64 lowercase hex>")
        if any(char not in "0123456789abcdef" for char in value.removeprefix("sha256:")):
            raise ValueError("receipt hashes must use sha256:<64 lowercase hex>")
        return value


class DecisionAnswerReplayResult(BaseModel):
    """No-model replay result; original status is never upgraded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    replayed: Literal[True] = True
    original_status: Literal["accepted", "rejected"]
    answer_family: str
    decision_request_id: str
    answer_sha256: str | None
    rejection_phase: Literal["answer_validation", "candidate_check"] | None = None
    failure_diagnostic: FailureDiagnostic | None = None
    source_identity: SourceIdentity


def _decision_contract_identity(
    answer_family: str,
) -> tuple[str, int, str]:
    if answer_family not in {
        "discovery_brief",
        "implementation_plan",
        "batch_decision",
        "correction_decision",
        "verification_decision",
        "work_result",
    }:
        raise BoundaryValidationError("unknown decision answer family")
    try:
        schema_id, schema_version, schema_sha256, _schema = decision_answer_schema(
            cast(Any, answer_family)
        )
    except (TypeError, ValueError) as exc:
        raise BoundaryValidationError("unknown decision answer family") from exc
    return schema_id, schema_version, schema_sha256


def _receipt_value_bytes(value: dict[str, Any] | str) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return _canonical_json(value)


def _decision_answer_receipt_integrity_hash(
    receipt: DecisionAnswerReceiptArtifact,
) -> str:
    return _sha256(
        _canonical_json(receipt.model_dump(mode="json", exclude={"receipt_integrity_sha256"}))
    )


def _canonical_received_decision_answer(
    answer_family: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Re-run the graph-owned authored-answer boundary for a receipt."""
    if set(request) != {"outputs"} or not isinstance(request.get("outputs"), dict):
        raise BoundaryValidationError("decision answer receipt answer validation failed")
    outputs = cast(dict[str, Any], request["outputs"])
    output_port = "semantic_artifact" if answer_family == "implementation_plan" else "decision"
    if output_port not in outputs or not isinstance(outputs[output_port], dict):
        raise BoundaryValidationError("decision answer receipt answer validation failed")
    if answer_family != "work_result" and set(outputs) != {output_port}:
        raise BoundaryValidationError("decision answer receipt answer validation failed")
    try:
        canonical = canonical_decision_answer(
            cast(Any, answer_family), cast(dict[str, Any], outputs[output_port])
        )
    except (TypeError, ValueError) as exc:
        raise BoundaryValidationError("decision answer receipt answer validation failed") from exc
    return {
        output_port: canonical,
        **(
            {port: value for port, value in outputs.items() if port != output_port}
            if answer_family == "work_result"
            else {}
        ),
    }


def _seal_decision_answer_receipt(
    receipt: DecisionAnswerReceiptArtifact,
) -> DecisionAnswerReceiptArtifact:
    return receipt.model_copy(
        update={"receipt_integrity_sha256": _decision_answer_receipt_integrity_hash(receipt)}
    )


async def capture_decision_answer_receipt(
    *,
    artifact_store: ArtifactStore,
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    worktree_path: str | Path,
    status: Literal["accepted", "rejected"],
    answer_family: Literal[
        "discovery_brief",
        "implementation_plan",
        "batch_decision",
        "correction_decision",
        "verification_decision",
        "work_result",
    ],
    request: dict[str, Any] | None,
    response: dict[str, Any] | str | None,
    answer: dict[str, Any] | None,
    question_context: dict[str, Any] | None,
    request_model: DecisionSubmissionRequest | None,
    answer_attempt_id: str,
    delivery_id: str,
    graph_position: int,
    node_id: str,
    rejection_outcome: DecisionAnswerRejectionOutcome | None = None,
    publication_held: bool = False,
) -> DecisionAnswerReceiptPublicRef:
    """Capture a bounded, source-bound receipt for a decision ingress.

    The function intentionally accepts missing values and writes a truthful
    non-replayable manifest.  An upstream transport failure that supplied no
    arguments therefore cannot be mistaken for a received answer.
    """
    schema_id, schema_version, schema_sha256 = _decision_contract_identity(answer_family)
    request_bytes = _receipt_value_bytes(request) if request is not None else b""
    response_bytes = _receipt_value_bytes(response) if response is not None else b""
    contract_request: dict[str, Any] | None = (
        request_model.model_dump(mode="json", by_alias=True) if request_model is not None else None
    )
    contract_request_bytes = (
        _canonical_json(contract_request) if contract_request is not None else b""
    )
    context_bytes = _canonical_json(question_context) if question_context is not None else b""
    source_identity = await capture_source_identity(worktree_path)
    graph_prefix = await _read_bounded_graph_prefix(
        session_factory,
        run_id,
        graph_position,
    )
    request_response_complete = (
        request is not None
        and response is not None
        and len(request_bytes) + len(response_bytes) <= _REQUEST_RESPONSE_BYTES
    )
    contract_request_complete = (
        contract_request is not None and len(contract_request_bytes) <= _REQUEST_RESPONSE_BYTES
    )
    question_context_complete = (
        question_context is not None and len(context_bytes) <= _REQUEST_RESPONSE_BYTES
    )
    classification: DecisionAnswerReceiptClassification = "exact_replay"
    if request is None or response is None:
        classification = "unreceived"
    elif not request_response_complete:
        classification = "evidence_oversize"
    elif not contract_request_complete or not question_context_complete:
        classification = (
            "evidence_oversize"
            if len(contract_request_bytes) > _REQUEST_RESPONSE_BYTES
            or len(context_bytes) > _REQUEST_RESPONSE_BYTES
            else "question_context_incomplete"
        )
    elif source_identity.complete is False:
        classification = "source_boundary_incomplete"
    elif graph_prefix is None:
        classification = "graph_prefix_incomplete"
    elif status == "rejected" and rejection_outcome is None:
        classification = "rejection_outcome_incomplete"
    elif (schema_id, schema_version, schema_sha256) != _decision_contract_identity(answer_family):
        classification = "unknown_contract"
    receipt = DecisionAnswerReceiptArtifact(
        status=status,
        classification=classification,
        replayable=classification == "exact_replay",
        interaction_contract="decision-v1",
        answer_family=answer_family,
        compiler_contract_version=DECISION_COMPILER_CONTRACT_VERSION,
        run_id=run_id,
        answer_schema_id=schema_id,
        answer_schema_version=schema_version,
        answer_schema_sha256=schema_sha256,
        decision_request_id=(
            request_model.decision_request_id if request_model is not None else "unreceived"
        ),
        execution_id=(request_model.execution_id if request_model is not None else "unreceived"),
        node_id=node_id,
        graph_position=graph_position,
        answer_attempt_id=answer_attempt_id,
        delivery_id=delivery_id,
        source_identity=source_identity,
        request_sha256=_sha256(request_bytes),
        response_sha256=_sha256(response_bytes),
        request_size_bytes=len(request_bytes),
        response_size_bytes=len(response_bytes),
        request_response_complete=request_response_complete,
        contract_request_sha256=(
            _sha256(contract_request_bytes) if contract_request is not None else None
        ),
        contract_request_size_bytes=len(contract_request_bytes),
        contract_request_complete=contract_request_complete,
        question_context_sha256=_sha256(context_bytes),
        question_context_size_bytes=len(context_bytes),
        question_context_complete=question_context_complete,
        graph_prefix_sha256=_graph_prefix_hash(graph_prefix or ()),
        graph_prefix_complete=graph_prefix is not None,
        answer_sha256=(canonical_decision_answer_hash(answer) if answer is not None else None),
        rejection_outcome=rejection_outcome,
        receipt_integrity_sha256="sha256:" + "0" * 64,
        request=request if request_response_complete else None,
        contract_request=contract_request if contract_request_complete else None,
        response=response if request_response_complete else None,
        answer=answer if request_response_complete else None,
        question_context=question_context if question_context_complete else None,
        graph_prefix=graph_prefix,
    )
    receipt = _seal_decision_answer_receipt(receipt)
    content = _canonical_json(receipt.model_dump(mode="json"))
    if len(content) > MAX_REJECTION_EVIDENCE_BYTES:
        receipt = receipt.model_copy(
            update={
                "classification": "evidence_oversize",
                "replayable": False,
                "request": None,
                "contract_request": None,
                "response": None,
                "answer": None,
                "question_context": None,
                "graph_prefix": None,
                "request_response_complete": False,
                "contract_request_complete": False,
                "question_context_complete": False,
                "graph_prefix_complete": False,
            }
        )
        receipt = _seal_decision_answer_receipt(receipt)
        content = _canonical_json(receipt.model_dump(mode="json"))
    if publication_held:
        ref = await artifact_store.put(
            content,
            media_type="application/vnd.orchestrator.decision-answer-receipt+json",
            encoding="utf-8",
        )
    else:
        async with artifact_store.publication():
            ref = await artifact_store.put(
                content,
                media_type="application/vnd.orchestrator.decision-answer-receipt+json",
                encoding="utf-8",
            )
    return DecisionAnswerReceiptPublicRef(
        artifact_ref=ref,
        content_hash=ref.content_hash,
        size_bytes=ref.size_bytes,
        classification=receipt.classification,
        replayable=receipt.replayable,
    )


def _expected_owner_failure_diagnostic(
    outcome: DecisionAnswerRejectionOutcome,
    evidence_ref: StoredArtifactRef,
) -> FailureDiagnostic:
    self_ref = f"artifact:{evidence_ref.content_hash}"
    refs = outcome.failure_diagnostic.protected_evidence_refs
    return outcome.failure_diagnostic.model_copy(
        update={"protected_evidence_refs": (*refs, self_ref)}
    )


def _validate_decision_receipt_owner(
    receipt: DecisionAnswerReceiptArtifact,
    evidence_ref: StoredArtifactRef,
    owner: EventEnvelope,
) -> None:
    expected_type = (
        "runner_submission_staged" if receipt.status == "accepted" else "decision_answer_rejected"
    )
    if owner.event_type != expected_type:
        raise BoundaryValidationError("decision answer receipt owner status mismatch")
    payload = owner.payload
    if payload.get("decision_answer_receipt_ref") != evidence_ref.model_dump(mode="json"):
        raise BoundaryValidationError("decision answer receipt owner reference mismatch")
    if (
        payload.get("node_id") != receipt.node_id
        or payload.get("execution_id") != receipt.execution_id
    ):
        raise BoundaryValidationError("decision answer receipt owner identity mismatch")
    if receipt.status == "accepted":
        if receipt.rejection_outcome is not None:
            raise BoundaryValidationError("accepted decision answer receipt has rejection outcome")
        return
    outcome = receipt.rejection_outcome
    if outcome is None:
        raise BoundaryValidationError("rejected decision answer receipt has no typed outcome")
    if f"sha256:{outcome.submitted_answer_sha256}" != receipt.request_sha256:
        raise BoundaryValidationError("decision answer receipt submitted answer identity mismatch")
    if (
        payload.get("answer_attempt_id") != receipt.answer_attempt_id
        or payload.get("delivery_id") != receipt.delivery_id
        or payload.get("answer_sha256") != outcome.submitted_answer_sha256
    ):
        raise BoundaryValidationError("decision answer receipt rejected owner identity mismatch")
    try:
        raw_diagnostic: object = payload.get("failure_diagnostic")
        diagnostic_dict: dict[str, Any] | None = None
        raw_diagnostic_value = raw_diagnostic
        if isinstance(raw_diagnostic_value, dict):
            diagnostic_dict = cast(dict[str, Any], raw_diagnostic_value)
        if diagnostic_dict is not None and isinstance(
            diagnostic_dict.get("protected_evidence_refs"), list
        ):
            refs = cast(list[Any], diagnostic_dict["protected_evidence_refs"])
            raw_diagnostic = {
                **diagnostic_dict,
                "protected_evidence_refs": tuple(refs),
            }
        owner_diagnostic = FailureDiagnostic.model_validate(raw_diagnostic)
    except ValueError as exc:
        raise BoundaryValidationError(
            "decision answer receipt owner diagnostic is invalid"
        ) from exc
    if owner_diagnostic != _expected_owner_failure_diagnostic(outcome, evidence_ref):
        raise BoundaryValidationError("decision answer receipt owner diagnostic mismatch")


def _gate_audit_position(reference: str, run_id: str) -> int:
    prefix = f"graph-event:{run_id}:"
    if not reference.startswith(prefix):
        raise BoundaryValidationError("candidate-check gate audit run identity mismatch")
    raw_position = reference.removeprefix(prefix)
    if not raw_position.isdigit() or int(raw_position) < 1:
        raise BoundaryValidationError("candidate-check gate audit reference is invalid")
    return int(raw_position)


async def _validate_candidate_check_audit(
    session: AsyncSession,
    receipt: DecisionAnswerReceiptArtifact,
    outcome: DecisionAnswerRejectionOutcome,
) -> None:
    audit_reference = outcome.rejection_evidence.durable_audit_reference
    if audit_reference is None:
        raise BoundaryValidationError("candidate-check receipt has no protected gate audit")
    position = _gate_audit_position(audit_reference, receipt.run_id)
    row = await session.scalar(
        select(EventV2Model).where(
            EventV2Model.position == position,
            EventV2Model.aggregate_id == receipt.run_id,
            EventV2Model.event_type == "graph_submission_gate_audited",
        )
    )
    if row is None:
        raise BoundaryValidationError("candidate-check gate audit is unavailable")
    try:
        payload = cast(dict[str, Any], json.loads(row.payload))
        report = cast(dict[str, Any], payload["report"])
        raw_results = cast(list[Any], report["results"])
        if len(raw_results) != 1:
            raise ValueError("candidate-check gate audit requires one failed result")
        result = SubmissionGateCommandResult.model_validate(raw_results[0])
    except (KeyError, TypeError, ValueError) as exc:
        raise BoundaryValidationError("candidate-check gate audit is invalid") from exc
    if (
        payload.get("run_id") != receipt.run_id
        or payload.get("node_id") != receipt.node_id
        or payload.get("execution_id") != receipt.execution_id
        or payload.get("phase") != "submission"
        or payload.get("status") != "failed"
        or payload.get("candidate_tree_sha") != outcome.candidate_tree_sha
        or result.run_id != receipt.run_id
        or result.node_id != receipt.node_id
        or result.execution_id != receipt.execution_id
        or result.failure_category != "candidate_check_failure"
        or result.status != "failed"
    ):
        raise BoundaryValidationError("candidate-check gate audit binding mismatch")
    fingerprint = submission_gate_failure_fingerprint(result)
    if payload.get("failure_fingerprint") != fingerprint:
        raise BoundaryValidationError("candidate-check gate audit fingerprint mismatch")
    gate_evidence = gate_rejection_evidence(result)
    expected_evidence = SubmissionRejectionEvidence(
        category="candidate_check_failed",
        command=gate_evidence.command,
        command_source=gate_evidence.command_source,
        command_sha256=gate_evidence.command_sha256,
        exit_code=gate_evidence.exit_code,
        timed_out=gate_evidence.timed_out,
        failed_test_ids=gate_evidence.failed_test_ids,
        failed_test_ids_truncated=gate_evidence.failed_test_ids_truncated,
        final_diagnostic=(
            gate_evidence.final_diagnostic
            or str(report.get("message") or "candidate check failed")[-2_048:]
        ),
        stdout_sha256=gate_evidence.stdout_sha256,
        stderr_sha256=gate_evidence.stderr_sha256,
        stdout_bytes=gate_evidence.stdout_bytes,
        stderr_bytes=gate_evidence.stderr_bytes,
        stdout_truncated=gate_evidence.stdout_truncated,
        stderr_truncated=gate_evidence.stderr_truncated,
        evidence_truncated=gate_evidence.evidence_truncated,
        failure_identity_status=gate_evidence.failure_identity_status,
        semantic_failure_fingerprint=gate_evidence.semantic_failure_fingerprint,
        durable_audit_reference=audit_reference,
    )
    if outcome.rejection_evidence != expected_evidence:
        raise BoundaryValidationError("candidate-check gate audit evidence mismatch")


async def replay_decision_answer_receipt(
    *,
    artifact_store: ArtifactStore,
    evidence_ref: StoredArtifactRef,
    authorization_session_factory: async_sessionmaker[AsyncSession],
    isolated_session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    worktree_path: str | Path,
    clock: Clock,
    id_gen: IdGenerator,
) -> DecisionAnswerReplayResult:
    """Verify one receipt locally without invoking a runner or changing a graph."""
    try:
        content = await artifact_store.read(evidence_ref)
    except (ArtifactIntegrityError, ArtifactNotFoundError) as exc:
        raise BoundaryValidationError("decision answer receipt is unavailable") from exc
    try:
        receipt = DecisionAnswerReceiptArtifact.model_validate_json(content)
    except ValueError as exc:
        raise BoundaryValidationError("decision answer receipt is invalid") from exc
    if not receipt.replayable or receipt.classification != "exact_replay":
        raise BoundaryValidationError(
            f"decision answer receipt is non-replayable: {receipt.classification}"
        )
    if _decision_answer_receipt_integrity_hash(receipt) != receipt.receipt_integrity_sha256:
        raise BoundaryValidationError("decision answer receipt integrity mismatch")
    if (
        not receipt.request_response_complete
        or not receipt.contract_request_complete
        or not receipt.question_context_complete
        or not receipt.graph_prefix_complete
        or receipt.request is None
        or receipt.contract_request is None
        or receipt.response is None
        or receipt.contract_request_sha256 is None
        or receipt.question_context is None
        or receipt.graph_prefix is None
    ):
        raise BoundaryValidationError("decision answer receipt is incomplete")
    expected_identity = _decision_contract_identity(receipt.answer_family)
    if (
        receipt.answer_schema_id,
        receipt.answer_schema_version,
        receipt.answer_schema_sha256,
    ) != expected_identity:
        raise BoundaryValidationError("decision answer receipt schema identity mismatch")
    if receipt.compiler_contract_version != DECISION_COMPILER_CONTRACT_VERSION:
        raise BoundaryValidationError("unknown decision compiler contract version")
    if receipt.run_id != run_id:
        raise BoundaryValidationError("decision answer receipt run identity mismatch")
    request_bytes = _receipt_value_bytes(receipt.request)
    response_bytes = _receipt_value_bytes(receipt.response)
    contract_request_bytes = _canonical_json(receipt.contract_request)
    context_bytes = _canonical_json(receipt.question_context)
    if (
        _sha256(request_bytes) != receipt.request_sha256
        or len(request_bytes) != receipt.request_size_bytes
        or _sha256(response_bytes) != receipt.response_sha256
        or len(response_bytes) != receipt.response_size_bytes
        or _sha256(contract_request_bytes) != receipt.contract_request_sha256
        or len(contract_request_bytes) != receipt.contract_request_size_bytes
        or _sha256(context_bytes) != receipt.question_context_sha256
        or len(context_bytes) != receipt.question_context_size_bytes
        or _graph_prefix_hash(receipt.graph_prefix) != receipt.graph_prefix_sha256
    ):
        raise BoundaryValidationError("decision answer receipt identity mismatch")
    try:
        contract_request = DecisionSubmissionRequest.model_validate(receipt.contract_request)
    except ValueError as exc:
        raise BoundaryValidationError(
            "decision answer receipt contract request is invalid"
        ) from exc
    if (
        contract_request.decision_request_id != receipt.decision_request_id
        or contract_request.execution_id != receipt.execution_id
        or contract_request.interaction_contract != receipt.interaction_contract
        or contract_request.answer_schema_id != receipt.answer_schema_id
        or contract_request.answer_schema_version != receipt.answer_schema_version
        or contract_request.answer_schema_sha256 != receipt.answer_schema_sha256
        or contract_request.compiler_contract_version != receipt.compiler_contract_version
        or contract_request.question_context_sha256 != receipt.question_context_sha256
    ):
        raise BoundaryValidationError("decision answer receipt bound contract mismatch")
    try:
        context_ref_bytes = await artifact_store.read(contract_request.question_context_ref)
    except (ArtifactIntegrityError, ArtifactNotFoundError) as exc:
        raise BoundaryValidationError(
            "decision answer receipt question context is unavailable"
        ) from exc
    if context_ref_bytes != context_bytes:
        raise BoundaryValidationError("decision answer receipt question context mismatch")
    async with authorization_session_factory() as session:
        authorization_store = GraphEventStore(session)
        authorized = await authorization_store.read_authorized_artifact_reference(
            run_id,
            evidence_ref.content_hash,
        )
        try:
            owner = await authorization_store.read_decision_answer_receipt_owner(
                run_id,
                evidence_ref.content_hash,
            )
        except ValueError as exc:
            raise BoundaryValidationError(str(exc)) from exc
        if owner is not None:
            _validate_decision_receipt_owner(receipt, evidence_ref, owner)
        if (
            receipt.status == "rejected"
            and receipt.rejection_outcome is not None
            and receipt.rejection_outcome.phase == "candidate_check"
        ):
            await _validate_candidate_check_audit(
                session,
                receipt,
                receipt.rejection_outcome,
            )
    if authorized != evidence_ref.model_dump(mode="json"):
        raise BoundaryValidationError("decision answer receipt has no durable event authorization")
    if owner is None:
        raise BoundaryValidationError("decision answer receipt has no exact durable owner event")
    observed_source = await capture_source_identity(worktree_path)
    if observed_source != receipt.source_identity:
        raise BoundaryValidationError("decision answer receipt source identity mismatch")
    if (
        receipt.answer is not None
        and canonical_decision_answer_hash(receipt.answer) != receipt.answer_sha256
    ):
        raise BoundaryValidationError("decision answer receipt answer identity mismatch")

    async with isolated_session_factory() as session:
        store = GraphEventStore(session)
        graph_event_count = await session.scalar(
            select(func.count(EventV2Model.position)).where(
                EventV2Model.aggregate_id.like("graph:%")
            )
        )
        if int(graph_event_count or 0) != 0:
            raise BoundaryValidationError("isolated replay graph store is not empty")
        await store.append_events(run_id, 0, list(receipt.graph_prefix))
        await session.commit()
    isolated_controller = GraphController(
        isolated_session_factory,
        clock,
        id_gen,
        auto_dispatch=False,
    )
    projection = await isolated_controller.read_projection(run_id)
    try:
        applicability = resolve_decision_applicability(projection, receipt.node_id)
        if applicability is None or applicability.family != receipt.answer_family:
            raise BoundaryValidationError("decision answer receipt applicability identity mismatch")
        resolved = resolve_decision_context(projection, receipt.node_id)
    except (TypeError, ValueError) as exc:
        raise BoundaryValidationError(
            "decision answer receipt authority could not be replayed"
        ) from exc
    if resolved.bound_inputs != contract_request.bound_inputs:
        raise BoundaryValidationError("decision answer receipt frozen input binding mismatch")
    if resolved.routine_snapshot_record_id != contract_request.routine_snapshot_record_id:
        raise BoundaryValidationError("decision answer receipt frozen snapshot binding mismatch")
    if resolved.protected_question_context() != receipt.question_context:
        raise BoundaryValidationError("decision answer receipt frozen question context mismatch")

    reproduced_rejection: BoundaryValidationError | ValueError | TypeError | None = None
    try:
        canonical_answer = _canonical_received_decision_answer(
            receipt.answer_family,
            receipt.request,
        )
        authored = canonical_answer[applicability.output_port]
        if receipt.answer_family == "implementation_plan":
            compile_implementation_plan(
                projection,
                node_id=receipt.node_id,
                execution_id=receipt.execution_id,
                answer=authored,
            )
        else:
            compile_decision(
                projection,
                node_id=receipt.node_id,
                decision_request_id=receipt.decision_request_id,
                base_graph_position=receipt.graph_position,
                answer=authored,
            )
    except (BoundaryValidationError, TypeError, ValueError) as exc:
        reproduced_rejection = exc
        canonical_answer = None
    if receipt.status == "accepted":
        if reproduced_rejection is not None:
            raise BoundaryValidationError(
                "decision answer receipt answer validation/compiler replay failed"
            ) from reproduced_rejection
        if receipt.answer is None or receipt.answer != canonical_answer:
            raise BoundaryValidationError("decision answer receipt answer validation mismatch")
    else:
        outcome = receipt.rejection_outcome
        if outcome is None:
            raise BoundaryValidationError("rejected decision answer receipt has no typed outcome")
        if outcome.phase == "answer_validation":
            if reproduced_rejection is None:
                raise BoundaryValidationError(
                    "decision answer receipt rejected status was not reproduced by compiler replay"
                )
        else:
            if reproduced_rejection is not None:
                raise BoundaryValidationError(
                    "candidate-check receipt did not reproduce answer/compiler acceptance"
                ) from reproduced_rejection
            if receipt.answer is None or receipt.answer != canonical_answer:
                raise BoundaryValidationError("candidate-check receipt answer validation mismatch")
    return DecisionAnswerReplayResult(
        original_status=receipt.status,
        answer_family=receipt.answer_family,
        decision_request_id=receipt.decision_request_id,
        answer_sha256=receipt.answer_sha256,
        rejection_phase=(
            receipt.rejection_outcome.phase if receipt.rejection_outcome is not None else None
        ),
        failure_diagnostic=(
            receipt.rejection_outcome.failure_diagnostic
            if receipt.rejection_outcome is not None
            else None
        ),
        source_identity=observed_source,
    )


async def require_replayed_decision_receipt_before_retry(
    *,
    projection: GraphProjection,
    node_id: str,
    execution_id: str,
    artifact_store: ArtifactStore,
    authorization_session_factory: async_sessionmaker[AsyncSession],
    isolated_session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    worktree_path: str | Path,
    clock: Clock,
    id_gen: IdGenerator,
) -> DecisionAnswerReplayResult | None:
    """Require local replay before a later decision execution may start.

    The current execution is never treated as its own retry.  Any earlier
    attempt for the same node with a durable rejected-answer fact requires its
    protected receipt to be present, event-authorized, and reproducible in the
    caller-supplied empty disposable store.  No authoritative graph mutation
    records the preflight; a crash simply repeats it.
    """
    prior_rejections = sorted(
        (
            rejection
            for attempt in execution_attempts_view(projection).values()
            if attempt.node_id == node_id and attempt.execution_id != execution_id
            for rejection in attempt.decision_answer_rejections
        ),
        key=lambda rejection: rejection.position,
    )
    if not prior_rejections:
        return None
    evidence_ref = prior_rejections[-1].decision_answer_receipt_ref
    if evidence_ref is None:
        raise BoundaryValidationError("decision retry requires a protected rejected-answer receipt")
    result = await replay_decision_answer_receipt(
        artifact_store=artifact_store,
        evidence_ref=evidence_ref,
        authorization_session_factory=authorization_session_factory,
        isolated_session_factory=isolated_session_factory,
        run_id=run_id,
        worktree_path=worktree_path,
        clock=clock,
        id_gen=id_gen,
    )
    if result.original_status != "rejected":
        raise BoundaryValidationError("decision retry requires a replayed rejected-answer receipt")
    return result


class ReliablePlanRejectionRecorder:
    """Production callable used by the controller before persisting a rejection."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        artifact_store: ArtifactStore,
        orchestrator_source_path: str | Path,
    ) -> None:
        self._session_factory = session_factory
        self._artifact_store = artifact_store
        self._orchestrator_source_path = orchestrator_source_path

    async def __call__(
        self,
        run_id: str,
        graph_position: int,
        request: dict[str, object],
        context: PatchCommandContext,
        planned_events: list[EventEnvelope],
    ) -> dict[str, object]:
        response = render_rejected_graph_patch_response(
            planned_events,
            cast(dict[str, Any], request),
        )
        if response is None:
            raise BoundaryValidationError("rejection recorder received no rejected event")
        public_ref = await capture_reliable_plan_rejection_evidence(
            session_factory=self._session_factory,
            artifact_store=self._artifact_store,
            worktree_path=self._orchestrator_source_path,
            run_id=run_id,
            proposed_by_node_id=context.proposed_by_node_id,
            actor_role=context.actor_role,
            graph_position=graph_position,
            request=cast(dict[str, Any], request),
            response=response,
        )
        return public_ref.model_dump(mode="json")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _run_git_bounded(root: Path, arguments: list[str]) -> tuple[bytes, bool]:
    process = subprocess.Popen(
        ["git", *arguments],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    chunks: list[bytes] = []
    observed = 0
    complete = True
    while True:
        chunk = process.stdout.read(64 * 1024)
        if not chunk:
            break
        observed += len(chunk)
        if observed > MAX_SOURCE_BOUNDARY_BYTES:
            complete = False
            process.kill()
            break
        chunks.append(chunk)
    process.wait()
    return b"".join(chunks), complete and process.returncode == 0


def _hash_files_bounded(root: Path, paths: bytes) -> tuple[str, bool]:
    digest = hashlib.sha256()
    observed = 0
    for raw_path in paths.split(b"\0"):
        if not raw_path:
            continue
        digest.update(len(raw_path).to_bytes(8, "big"))
        digest.update(raw_path)
        path = root / os.fsdecode(raw_path)
        try:
            if not path.is_file():
                digest.update((0).to_bytes(8, "big"))
                continue
            size = path.stat().st_size
            observed += len(raw_path) + size
            if observed > MAX_SOURCE_BOUNDARY_BYTES:
                return f"sha256:{digest.hexdigest()}", False
            digest.update(size.to_bytes(8, "big"))
            with path.open("rb") as stream:
                while chunk := stream.read(64 * 1024):
                    digest.update(chunk)
        except OSError:
            return f"sha256:{digest.hexdigest()}", False
    return f"sha256:{digest.hexdigest()}", True


def _capture_source_identity_sync(root: Path) -> SourceIdentity:
    head, head_complete = _run_git_bounded(root, ["rev-parse", "HEAD"])
    status, status_complete = _run_git_bounded(
        root,
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *_SOURCE_PATHS,
        ],
    )
    tracked_diff, diff_complete = _run_git_bounded(
        root,
        ["diff", "--binary", "--no-ext-diff", "HEAD", "--", *_SOURCE_PATHS],
    )
    untracked, untracked_complete = _run_git_bounded(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z", "--", *_SOURCE_PATHS],
    )
    untracked_digest, content_complete = _hash_files_bounded(root, untracked)
    return SourceIdentity(
        head_commit=head.decode("ascii", errors="replace").strip() or "unavailable",
        status_sha256=_sha256(status),
        tracked_diff_sha256=_sha256(tracked_diff),
        untracked_content_sha256=untracked_digest,
        complete=all(
            (head_complete, status_complete, diff_complete, untracked_complete, content_complete)
        ),
    )


async def capture_source_identity(worktree_path: str | Path) -> SourceIdentity:
    """Capture HEAD plus bounded staged, unstaged, and untracked source identity."""
    try:
        return await asyncio.to_thread(_capture_source_identity_sync, Path(worktree_path))
    except (OSError, subprocess.SubprocessError):
        unavailable = _sha256(b"")
        return SourceIdentity(
            head_commit="unavailable",
            status_sha256=unavailable,
            tracked_diff_sha256=unavailable,
            untracked_content_sha256=unavailable,
            complete=False,
        )


def resolve_orchestrator_source_root() -> Path:
    """Resolve the checkout containing the executing orchestrator package."""
    module_path = Path(__file__).resolve()
    for candidate in module_path.parents:
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "orchestrator"
        ).is_dir():
            return candidate
    # Installed distributions may not retain repository metadata. The package
    # parent still yields an explicit incomplete source identity rather than
    # falsely identifying a target run checkout as controller source.
    return module_path.parent.parent


def _graph_prefix_hash(events: tuple[EventEnvelope, ...]) -> str:
    return _sha256(_canonical_json([event.model_dump(mode="json") for event in events]))


async def _read_bounded_graph_prefix(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    graph_position: int,
) -> tuple[EventEnvelope, ...] | None:
    if graph_position > MAX_REJECTION_PREFIX_EVENTS:
        return None
    events: list[EventEnvelope] = []
    encoded_bytes = 2
    next_position = 1
    async with session_factory() as session:
        store = GraphEventStore(session)
        while next_position <= graph_position:
            batch = await store.read_run(
                run_id,
                from_position=next_position,
                limit=min(_GRAPH_READ_BATCH, graph_position - next_position + 1),
            )
            if not batch:
                return None
            for event in batch:
                if event.position != next_position:
                    return None
                encoded_bytes += len(_canonical_json(event.model_dump(mode="json"))) + 1
                if encoded_bytes > _GRAPH_PREFIX_BYTES:
                    return None
                events.append(event)
                next_position += 1
    return tuple(events) if len(events) == graph_position else None


async def capture_reliable_plan_rejection_evidence(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    artifact_store: ArtifactStore,
    worktree_path: str | Path,
    run_id: str,
    proposed_by_node_id: str,
    actor_role: str,
    graph_position: int,
    request: dict[str, Any],
    response: str,
) -> RejectionEvidencePublicRef:
    """Persist exact replay evidence when bounded, or a truthful omission manifest."""
    request_bytes = _canonical_json(request)
    response_bytes = response.encode("utf-8")
    source_identity = await capture_source_identity(worktree_path)
    classification: RejectionEvidenceClassification = "exact_replay"
    request_response_complete = len(request_bytes) + len(response_bytes) <= _REQUEST_RESPONSE_BYTES
    if not request_response_complete:
        classification = "evidence_oversize"
    graph_prefix: tuple[EventEnvelope, ...] | None = None
    graph_prefix = await _read_bounded_graph_prefix(session_factory, run_id, graph_position)
    if graph_prefix is None and classification == "exact_replay":
        classification = "graph_prefix_incomplete"
    if not source_identity.complete and classification == "exact_replay":
        classification = "source_boundary_oversize"

    prefix_hash = _graph_prefix_hash(graph_prefix or ())
    artifact = RejectionEvidenceArtifact(
        classification=classification,
        replayable=classification == "exact_replay",
        run_id=run_id,
        proposed_by_node_id=proposed_by_node_id,
        actor_role=actor_role,
        graph_position=graph_position,
        graph_prefix_sha256=prefix_hash,
        graph_prefix_complete=graph_prefix is not None,
        source_identity=source_identity,
        request_sha256=_sha256(request_bytes),
        response_sha256=_sha256(response_bytes),
        request_size_bytes=len(request_bytes),
        response_size_bytes=len(response_bytes),
        request_response_complete=request_response_complete,
        request=(request if request_response_complete else None),
        response=(response if request_response_complete else None),
        graph_prefix=graph_prefix,
    )
    content = _canonical_json(artifact.model_dump(mode="json"))
    if len(content) > MAX_REJECTION_EVIDENCE_BYTES:
        artifact = artifact.model_copy(
            update={
                "classification": "evidence_oversize",
                "replayable": False,
                "graph_prefix": None,
                "graph_prefix_complete": False,
            }
        )
        content = _canonical_json(artifact.model_dump(mode="json"))
        if len(content) > MAX_REJECTION_EVIDENCE_BYTES:
            artifact = artifact.model_copy(update={"request": None, "response": None})
            content = _canonical_json(artifact.model_dump(mode="json"))
    async with artifact_store.publication():
        ref = await artifact_store.put(
            content,
            media_type=REJECTION_EVIDENCE_MEDIA_TYPE,
            encoding="utf-8",
        )
    return RejectionEvidencePublicRef(
        artifact_ref=ref,
        content_hash=ref.content_hash,
        size_bytes=ref.size_bytes,
        classification=artifact.classification,
        replayable=artifact.replayable,
    )


def render_rejected_graph_patch_response(
    events: list[EventEnvelope],
    request: dict[str, Any],
    fallback_diagnostics: dict[str, Any] | None = None,
) -> str | None:
    """Render the stable safe response for a rejected controller result."""
    rejection = next(
        (
            event
            for event in events
            if event.event_type in {"graph_patch_rejected", "command_rejected"}
        ),
        None,
    )
    if rejection is None:
        return None
    reason = rejection.payload.get("reason") or "unknown rejection"
    patch_id = rejection.payload.get("patch_id", request.get("patch_id", "unknown"))
    event_diagnostics = rejection.payload.get("diagnostics")
    diagnostics = (
        cast(dict[str, Any], event_diagnostics)
        if isinstance(event_diagnostics, dict)
        else fallback_diagnostics
    )
    if diagnostics is not None:
        rendered = json.dumps(diagnostics, sort_keys=True, separators=(",", ":"))
        return (
            f"graph patch {patch_id} rejected: {reason}; graph_patch_rejected; "
            f"validation_diagnostics={rendered}"
        )
    return f"graph patch {patch_id} rejected: {reason}"


async def replay_reliable_plan_rejection(
    *,
    artifact_store: ArtifactStore,
    evidence_ref: StoredArtifactRef,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    clock: Clock,
    id_gen: IdGenerator,
    worktree_path: str | Path,
) -> RejectionReplayResult:
    """Restore captured authority into an empty store and reproduce its rejection."""
    content = await artifact_store.read(evidence_ref)
    artifact = RejectionEvidenceArtifact.model_validate_json(content)
    if not artifact.replayable or artifact.classification != "exact_replay":
        raise BoundaryValidationError(
            f"rejection evidence is non-replayable: {artifact.classification}"
        )
    if (
        not artifact.request_response_complete
        or not artifact.graph_prefix_complete
        or artifact.request is None
        or artifact.response is None
        or artifact.graph_prefix is None
    ):
        raise BoundaryValidationError("replayable rejection evidence is incomplete")
    if _sha256(_canonical_json(artifact.request)) != artifact.request_sha256:
        raise BoundaryValidationError("rejection request identity mismatch")
    if _sha256(artifact.response.encode("utf-8")) != artifact.response_sha256:
        raise BoundaryValidationError("rejection response identity mismatch")
    if _graph_prefix_hash(artifact.graph_prefix) != artifact.graph_prefix_sha256:
        raise BoundaryValidationError("rejection graph prefix identity mismatch")
    observed_source = await capture_source_identity(worktree_path)
    if observed_source != artifact.source_identity:
        raise BoundaryValidationError("rejection orchestrator source identity mismatch")

    async with isolated_session_factory() as session:
        store = GraphEventStore(session)
        graph_event_count = await session.scalar(
            select(func.count(EventV2Model.position)).where(
                EventV2Model.aggregate_id.like("graph:%")
            )
        )
        if int(graph_event_count or 0) != 0:
            raise BoundaryValidationError("isolated replay graph store is not empty")
        if artifact.graph_prefix:
            await store.append_events(artifact.run_id, 0, list(artifact.graph_prefix))
            await session.commit()
    isolated_controller = GraphController(
        isolated_session_factory,
        clock,
        id_gen,
        auto_dispatch=False,
    )
    result = await isolated_controller.handle_command(
        artifact.run_id,
        artifact.graph_position,
        "submit_patch",
        dict(artifact.request),
        context=PatchCommandContext(
            run_id=artifact.run_id,
            current_graph_position=artifact.graph_position,
            proposed_by_node_id=artifact.proposed_by_node_id,
            actor_role=artifact.actor_role,
        ),
    )
    response = render_rejected_graph_patch_response(result.events, artifact.request)
    if response is None or response != artifact.response:
        raise BoundaryValidationError("captured controller rejection was not reproduced")
    return RejectionReplayResult(
        response=response,
        graph_prefix_sha256=artifact.graph_prefix_sha256,
        source_identity=observed_source,
    )


__all__ = [
    "DecisionAnswerRejectionOutcome",
    "DecisionAnswerReceiptArtifact",
    "DecisionAnswerReceiptPublicRef",
    "DecisionAnswerReplayResult",
    "MAX_REJECTION_EVIDENCE_BYTES",
    "MAX_REJECTION_PREFIX_EVENTS",
    "REJECTION_EVIDENCE_MEDIA_TYPE",
    "RejectionEvidenceArtifact",
    "RejectionEvidencePublicRef",
    "RejectionReplayResult",
    "ReliablePlanRejectionRecorder",
    "SourceIdentity",
    "capture_reliable_plan_rejection_evidence",
    "capture_decision_answer_receipt",
    "capture_source_identity",
    "render_rejected_graph_patch_response",
    "resolve_orchestrator_source_root",
    "replay_reliable_plan_rejection",
    "replay_decision_answer_receipt",
    "require_replayed_decision_receipt_before_retry",
]
