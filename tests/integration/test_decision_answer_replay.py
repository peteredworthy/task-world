"""Protected decision-answer receipts are replayable without a model."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import FailureDiagnostic
from orchestrator.db import EventV2Model, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    DecisionSubmissionRequest,
    FakeClock,
    SequentialIdGenerator,
    StoredArtifactRef,
    batch_decision_schema_sha256,
    resolve_decision_context,
)
from orchestrator.graph_runtime import (
    DecisionAnswerRejectionOutcome,
    DecisionAnswerReceiptArtifact,
    GraphController,
    GraphEventStore,
    capture_decision_answer_receipt,
    graph_aggregate_id,
    replay_decision_answer_receipt,
)
from orchestrator.runners import SubmissionRejectionEvidence
from tests.integration.test_decision_recovery_crash_matrix import _decision_seed


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Replay Test")
    source = repo / "src" / "orchestrator" / "source.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "source")
    return repo


async def _request(
    store: FilesystemArtifactStore,
    sessions: Any,
    run_id: str,
) -> tuple[DecisionSubmissionRequest, dict[str, Any], int]:
    events = _decision_seed(run_id)
    async with sessions() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()
    controller = GraphController(
        sessions, FakeClock(), SequentialIdGenerator(), auto_dispatch=False
    )
    resolved = resolve_decision_context(
        await controller.read_projection(run_id),
        "planner-plan",
    )
    context = resolved.protected_question_context()
    context_ref = await store.put(
        json.dumps(context, sort_keys=True, separators=(",", ":")).encode(),
        media_type="application/json",
        encoding="utf-8",
    )
    request = DecisionSubmissionRequest(
        decision_request_id="decision-request-1",
        execution_id="execution-1",
        routine_snapshot_record_id=resolved.routine_snapshot_record_id,
        interaction_contract="decision-v1",
        answer_schema_id="orchestrator.reliable-plan.batch-decision",
        answer_schema_version=1,
        answer_schema_sha256=batch_decision_schema_sha256(),
        compiler_contract_version=1,
        question_context_ref=context_ref,
        question_context_sha256=context_ref.content_hash,
        bound_inputs=resolved.bound_inputs,
    )
    # The schema hash is deliberately supplied by the caller in the fixture;
    # the receipt helper replaces it with the graph-owned identity.
    return request, context, len(events)


async def _capture(
    tmp_path: Path,
    *,
    status: str,
    request: dict[str, Any] | None = None,
    response: str | None = "accepted",
    answer: dict[str, Any] | None = None,
    authorize: bool = True,
    graph_position_offset: int = 0,
    omit_question_context: bool = False,
    incomplete_source: bool = False,
    owner_diagnostic_message: str | None = None,
    owner_extra_evidence_ref: str | None = None,
) -> tuple[FilesystemArtifactStore, StoredArtifactRef, Path, Any, Any]:
    source = _source_repo(tmp_path)
    store = FilesystemArtifactStore(tmp_path / "protected")
    engine = create_engine(tmp_path / "authority.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    isolated_engine = create_engine(tmp_path / "isolated.db")
    await init_db(isolated_engine)
    isolated_sessions = create_session_factory(isolated_engine)
    run_id = "decision-receipt-run"
    request_model, context, graph_position = await _request(store, sessions, run_id)
    if request is None:
        request = (
            {"outputs": answer}
            if answer is not None
            else {"outputs": {"decision": {"disposition": "invalid"}}}
        )
    rejection_outcome = None
    if status == "rejected" and response is not None:
        submitted_hash = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        rejection_outcome = DecisionAnswerRejectionOutcome(
            phase="answer_validation",
            submitted_answer_sha256=submitted_hash,
            failure_diagnostic=FailureDiagnostic(
                category="answer_validation",
                code="answer_validation_failed",
                message="The submitted answer does not match the bound answer contract.",
                next_action="correct_answer",
                correction_allowed=True,
            ),
            rejection_category="submission_format_rejected",
            rejection_evidence=SubmissionRejectionEvidence(
                category="submission_format_rejected",
                final_diagnostic=response,
            ),
        )
    public = await capture_decision_answer_receipt(
        artifact_store=store,
        session_factory=sessions,
        run_id=run_id,
        worktree_path=(tmp_path / "missing-source" if incomplete_source else source),
        status=cast(Literal["accepted", "rejected"], status),
        answer_family="batch_decision",
        request=request,
        response=response,
        answer=answer,
        question_context=None if omit_question_context else context,
        request_model=request_model,
        answer_attempt_id="attempt-1",
        delivery_id="a" * 64,
        graph_position=graph_position + graph_position_offset,
        node_id="planner-plan",
        rejection_outcome=rejection_outcome,
    )
    if authorize:
        owner_event = _decision_seed(run_id)[-1].model_copy(
            update={
                "event_id": "receipt-owner",
                "event_type": (
                    "runner_submission_staged"
                    if status == "accepted"
                    else "decision_answer_rejected"
                ),
                "position": graph_position + 1,
                "payload": {
                    "node_id": "planner-plan",
                    "execution_id": "execution-1",
                    "decision_answer_receipt_ref": public.artifact_ref.model_dump(mode="json"),
                    **(
                        {
                            "answer_attempt_id": "attempt-1",
                            "delivery_id": "a" * 64,
                            "answer_sha256": rejection_outcome.submitted_answer_sha256,
                            "failure_diagnostic": rejection_outcome.failure_diagnostic.model_copy(
                                update={
                                    "message": (
                                        owner_diagnostic_message
                                        or rejection_outcome.failure_diagnostic.message
                                    ),
                                    "protected_evidence_refs": (
                                        f"artifact:{public.content_hash}",
                                        *(
                                            (owner_extra_evidence_ref,)
                                            if owner_extra_evidence_ref is not None
                                            else ()
                                        ),
                                    ),
                                }
                            ).model_dump(mode="json"),
                        }
                        if rejection_outcome is not None
                        else {}
                    ),
                },
            }
        )
        async with sessions() as session:
            session.add(
                EventV2Model(
                    aggregate_id=graph_aggregate_id(run_id),
                    version=graph_position + 1,
                    event_type=owner_event.event_type,
                    payload=owner_event.model_dump_json(),
                    timestamp=owner_event.timestamp.isoformat(),
                )
            )
            await session.flush()
            await GraphEventStore(session).append_artifact_references(run_id, [owner_event])
            await session.commit()
    return store, public.artifact_ref, source, sessions, isolated_sessions


async def _replay(
    store: FilesystemArtifactStore,
    ref: StoredArtifactRef,
    source: Path,
    sessions: Any,
    isolated_sessions: Any,
) -> Any:
    return await replay_decision_answer_receipt(
        artifact_store=store,
        evidence_ref=ref,
        authorization_session_factory=sessions,
        isolated_session_factory=isolated_sessions,
        run_id="decision-receipt-run",
        worktree_path=source,
        clock=FakeClock(),
        id_gen=SequentialIdGenerator(),
    )


@pytest.mark.asyncio
async def test_accepted_and_rejected_receipts_replay_after_workspace_disposal(
    tmp_path: Path,
) -> None:
    answer = {"decision": {"disposition": "proceed", "implementation_notes": "continue"}}
    (
        accepted_store,
        accepted_ref,
        accepted_source,
        accepted_sessions,
        accepted_isolated,
    ) = await _capture(tmp_path / "accepted", status="accepted", answer=answer)
    (
        rejected_store,
        rejected_ref,
        rejected_source,
        rejected_sessions,
        rejected_isolated,
    ) = await _capture(
        tmp_path / "rejected",
        status="rejected",
        response="answer_validation: invalid disposition",
        answer=None,
    )

    accepted = await _replay(
        accepted_store, accepted_ref, accepted_source, accepted_sessions, accepted_isolated
    )
    rejected = await _replay(
        rejected_store, rejected_ref, rejected_source, rejected_sessions, rejected_isolated
    )

    assert accepted.original_status == "accepted"
    assert accepted.replayed is True
    assert rejected.original_status == "rejected"
    assert rejected.replayed is True
    assert rejected.original_status != "accepted"


@pytest.mark.asyncio
async def test_receipt_rejects_tampering_and_unknown_contract(tmp_path: Path) -> None:
    store, ref, source, sessions, isolated_sessions = await _capture(
        tmp_path / "tamper",
        status="accepted",
        answer={"decision": {"disposition": "proceed", "implementation_notes": "ok"}},
    )
    content = json.loads((await store.read(ref)).decode())

    tampered_request = dict(content)
    tampered_request["request"] = {"execution_id": "changed"}
    tampered_ref = await store.put(
        json.dumps(tampered_request, sort_keys=True, separators=(",", ":")).encode(),
        media_type="application/json",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mismatch"):
        await _replay(store, tampered_ref, source, sessions, isolated_sessions)

    tampered_status = dict(content)
    tampered_status["status"] = "rejected"
    tampered_status_ref = await store.put(
        json.dumps(tampered_status, sort_keys=True, separators=(",", ":")).encode(),
        media_type="application/json",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="integrity mismatch"):
        await _replay(store, tampered_status_ref, source, sessions, isolated_sessions)

    unknown = dict(content)
    unknown["answer_schema_version"] = 99
    unknown_ref = await store.put(
        json.dumps(unknown, sort_keys=True, separators=(",", ":")).encode(),
        media_type="application/json",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mismatch"):
        await _replay(store, unknown_ref, source, sessions, isolated_sessions)

    (source / "src" / "orchestrator" / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source identity mismatch"):
        await _replay(store, ref, source, sessions, isolated_sessions)

    assert DecisionAnswerReceiptArtifact.model_validate_json(await store.read(ref))


@pytest.mark.asyncio
async def test_receipt_cannot_self_declare_invalid_answer_as_accepted(tmp_path: Path) -> None:
    store, ref, source, sessions, isolated_sessions = await _capture(
        tmp_path / "invalid-accepted",
        status="accepted",
        request={"outputs": {"decision": {"disposition": "not-a-valid-batch-decision"}}},
        answer={"decision": {"disposition": "not-a-valid-batch-decision"}},
    )

    with pytest.raises(ValueError, match="answer validation"):
        await _replay(store, ref, source, sessions, isolated_sessions)


@pytest.mark.asyncio
async def test_replay_requires_durable_event_authorization(tmp_path: Path) -> None:
    store, ref, source, sessions, isolated_sessions = await _capture(
        tmp_path / "unauthorized",
        status="rejected",
        response="answer validation failed",
        authorize=False,
    )

    with pytest.raises(ValueError, match="no durable event authorization"):
        await _replay(store, ref, source, sessions, isolated_sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["diagnostic", "evidence"])
async def test_replay_rejects_mismatched_owner_diagnostic_or_evidence(
    tmp_path: Path,
    mismatch: str,
) -> None:
    store, ref, source, sessions, isolated_sessions = await _capture(
        tmp_path / mismatch,
        status="rejected",
        response="answer validation failed",
        owner_diagnostic_message=(
            "A different failure was recorded." if mismatch == "diagnostic" else None
        ),
        owner_extra_evidence_ref=("evidence:different-owner" if mismatch == "evidence" else None),
    )

    with pytest.raises(ValueError, match="owner diagnostic mismatch"):
        await _replay(store, ref, source, sessions, isolated_sessions)


@pytest.mark.asyncio
async def test_empty_and_oversized_receipts_are_explicitly_incomplete(tmp_path: Path) -> None:
    store, ref, source, sessions, isolated_sessions = await _capture(
        tmp_path / "incomplete", status="rejected", response=None
    )
    receipt = DecisionAnswerReceiptArtifact.model_validate_json(await store.read(ref))
    assert receipt.replayable is False
    assert receipt.classification == "unreceived"
    with pytest.raises(ValueError, match="non-replayable"):
        await _replay(store, ref, source, sessions, isolated_sessions)

    (
        oversized_store,
        oversized_ref,
        oversized_source,
        oversized_sessions,
        oversized_isolated,
    ) = await _capture(
        tmp_path / "oversized",
        status="rejected",
        request={"outputs": {"decision": {"reason": "x" * 100_000}}},
    )
    oversized = DecisionAnswerReceiptArtifact.model_validate_json(
        await oversized_store.read(oversized_ref)
    )
    assert oversized.classification == "evidence_oversize"
    assert oversized.replayable is False
    with pytest.raises(ValueError, match="non-replayable"):
        await _replay(
            oversized_store,
            oversized_ref,
            oversized_source,
            oversized_sessions,
            oversized_isolated,
        )

    prefix_store, prefix_ref, *_ = await _capture(
        tmp_path / "missing-prefix",
        status="rejected",
        response="answer validation failed",
        graph_position_offset=1,
    )
    missing_prefix = DecisionAnswerReceiptArtifact.model_validate_json(
        await prefix_store.read(prefix_ref)
    )
    assert missing_prefix.classification == "graph_prefix_incomplete"
    assert missing_prefix.graph_prefix_complete is False
    assert missing_prefix.replayable is False

    context_store, context_ref, *_ = await _capture(
        tmp_path / "missing-context",
        status="rejected",
        response="answer validation failed",
        omit_question_context=True,
    )
    missing_context = DecisionAnswerReceiptArtifact.model_validate_json(
        await context_store.read(context_ref)
    )
    assert missing_context.classification == "question_context_incomplete"
    assert missing_context.question_context_complete is False
    assert missing_context.replayable is False

    source_store, source_ref, *_ = await _capture(
        tmp_path / "missing-source",
        status="rejected",
        response="answer validation failed",
        incomplete_source=True,
    )
    missing_source = DecisionAnswerReceiptArtifact.model_validate_json(
        await source_store.read(source_ref)
    )
    assert missing_source.classification == "source_boundary_incomplete"
    assert missing_source.source_identity.complete is False
    assert missing_source.replayable is False
