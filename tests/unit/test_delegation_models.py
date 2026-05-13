"""Unit tests for reusable delegated-work coordination primitives."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.config import RunStatus
from orchestrator.state import Run
from orchestrator.workflow import (
    DelegateCommand,
    DelegateResultEnvelope,
    DelegationDecision,
    DelegationState,
    DelegatedWork,
    SuperParentDelegationPolicy,
    apply_delegate_command,
)


def test_apply_delegate_command_launches_requested_work_once() -> None:
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        status="requested",
    )
    command = DelegateCommand(
        kind="launch",
        work_id="child-1",
        owner_id="parent",
        idempotency_key="create-child-1",
        expected_generation=0,
    )

    launched, decision = apply_delegate_command(work, command)
    assert launched is not None
    assert launched.status == "running"
    assert launched.idempotency_keys == ("create-child-1",)
    assert decision.kind == "launch"

    duplicate, duplicate_decision = apply_delegate_command(launched, command)
    assert duplicate == launched
    assert duplicate_decision.kind == "stale_command_ignored"
    assert duplicate_decision.reason == "duplicate_command"


def test_apply_delegate_command_ignores_stale_generation() -> None:
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        generation=2,
        status="running",
    )
    command = DelegateCommand(
        kind="observe",
        work_id="child-1",
        owner_id="parent",
        idempotency_key="observe-old",
        expected_generation=1,
    )

    updated, decision = apply_delegate_command(work, command)

    assert updated == work
    assert decision.kind == "stale_command_ignored"
    assert decision.reason == "generation_mismatch"


def test_apply_delegate_command_ignores_work_id_mismatch_as_stale() -> None:
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        status="terminal",
    )
    command = DelegateCommand(
        kind="integrate",
        work_id="child-2",
        owner_id="parent",
        idempotency_key="integrate-wrong-child",
        expected_generation=0,
    )

    updated, decision = apply_delegate_command(work, command)

    assert updated == work
    assert decision.kind == "stale_command_ignored"
    assert decision.reason == "work_id_mismatch"
    assert decision.stable_state == "StaleCommandIgnored"


def test_apply_delegate_command_ignores_owner_token_mismatch() -> None:
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        owner_token="owner-a",
        status="running",
    )
    command = DelegateCommand(
        kind="observe",
        work_id="child-1",
        owner_id="parent",
        owner_token="owner-b",
        idempotency_key="observe",
        expected_generation=0,
    )

    updated, decision = apply_delegate_command(work, command)

    assert updated == work
    assert decision.kind == "stale_command_ignored"
    assert decision.reason == "owner_token_mismatch"


def test_launch_running_work_with_new_idempotency_key_is_semantic_noop() -> None:
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        status="running",
    )
    command = DelegateCommand(
        kind="launch",
        work_id="child-1",
        owner_id="parent",
        idempotency_key="new-launch-key",
        expected_generation=0,
    )

    updated, decision = apply_delegate_command(work, command)

    assert updated == work
    assert decision.kind == "stale_command_ignored"
    assert decision.reason == "launch_already_running"


def test_resolve_already_rejected_work_with_new_idempotency_key_is_semantic_noop() -> None:
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        status="rejected",
    )
    command = DelegateCommand(
        kind="reject",
        work_id="child-1",
        owner_id="parent",
        idempotency_key="new-reject-key",
        expected_generation=0,
    )

    updated, decision = apply_delegate_command(work, command)

    assert updated == work
    assert decision.kind == "stale_command_ignored"
    assert decision.reason == "resolve_already_rejected"


def test_observe_running_work_with_new_idempotency_key_records_wait() -> None:
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        status="running",
    )
    command = DelegateCommand(
        kind="observe",
        work_id="child-1",
        owner_id="parent",
        idempotency_key="new-observe-key",
        expected_generation=0,
    )

    updated, decision = apply_delegate_command(work, command)

    assert updated is not None
    assert updated.status == "waiting"
    assert updated.idempotency_keys == ("new-observe-key",)
    assert decision.kind == "wait"
    assert decision.stable_state == "WaitingOnDelegate"


def test_apply_delegate_command_rejects_missing_owner_token_when_work_is_fenced() -> None:
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        status="terminal",
        owner_token="fresh-token",
    )
    command = DelegateCommand(
        kind="integrate",
        work_id="child-1",
        owner_id="parent",
        idempotency_key="accept-child-1",
        expected_generation=0,
    )

    updated, decision = apply_delegate_command(work, command)

    assert updated == work
    assert decision.kind == "stale_command_ignored"
    assert decision.reason == "owner_token_mismatch"


def test_integrate_already_integrated_work_with_new_key_is_semantic_noop() -> None:
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        status="integrated",
    )
    command = DelegateCommand(
        kind="integrate",
        work_id="child-1",
        owner_id="parent",
        idempotency_key="new-integrate-key",
        expected_generation=0,
    )

    updated, decision = apply_delegate_command(work, command)

    assert updated == work
    assert decision.kind == "stale_command_ignored"
    assert decision.reason == "integrate_already_integrated"


def test_delegation_state_records_command_decisions() -> None:
    fixed_time = datetime(2026, 1, 1, tzinfo=UTC)
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        owner_token="owner-a",
        status="requested",
    )
    command = DelegateCommand(
        kind="launch",
        work_id="child-1",
        owner_id="parent",
        owner_token="owner-a",
        idempotency_key="launch-child-1",
        expected_generation=0,
    )

    updated_state, updated_work, decision = DelegationState().apply_command(
        work,
        command,
        recorded_at=fixed_time,
    )
    state = updated_state.merge_into({})

    assert updated_work is not None
    assert updated_work.status == "running"
    assert decision.kind == "launch"
    assert state["delegated_work"]["child-1"]["status"] == "running"
    assert state["delegation_decisions"][-1]["idempotency_key"] == "launch-child-1"


def test_delegation_state_records_review_state() -> None:
    fixed_time = datetime(2026, 1, 1, tzinfo=UTC)

    state = (
        DelegationState()
        .with_review_state(
            work_id="child-1",
            stable_state="InvalidEvidence",
            reason="child_evidence_invalid",
            payload={"path": "docs/evidence.json"},
            recorded_at=fixed_time,
        )
        .merge_into({})
    )

    assert state["delegation_review_states"] == [
        {
            "work_id": "child-1",
            "stable_state": "InvalidEvidence",
            "reason": "child_evidence_invalid",
            "payload": {"path": "docs/evidence.json"},
            "recorded_at": "2026-01-01T00:00:00Z",
        }
    ]
    assert DelegationDecision.model_validate(state["delegation_decisions"][-1]).kind == "review"


def test_record_result_clears_review_state_on_successful_integration() -> None:
    fixed_time = datetime(2026, 1, 1, tzinfo=UTC)
    state = DelegationState().with_review_state(
        work_id="child-1",
        stable_state="InvalidEvidence",
        reason="child_evidence_invalid",
        payload={},
        recorded_at=fixed_time,
    )

    state = state.with_result(
        DelegateResultEnvelope(
            work_id="child-1",
            generation=1,
            terminal_status="completed",
            outcome="verified_fix",
            validation_status="valid",
            integration_ready=True,
        ),
        DelegationDecision(kind="integrate", work_id="child-1"),
        recorded_at=fixed_time,
    )

    assert state.to_oversight_patch()["delegation_review_states"] == []


def test_delegation_state_is_immutable_value_object() -> None:
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        status="requested",
    )
    state = DelegationState()

    updated = state.with_work(work)

    assert state.delegated_work == ()
    assert updated.delegated_work == (work,)
    assert updated.to_oversight_patch()["delegated_work"]["child-1"]["status"] == "requested"
    with pytest.raises(ValidationError, match="frozen"):
        setattr(updated, "delegated_work", ())


def test_delegation_value_nested_json_fields_are_immutable() -> None:
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        policy_metadata={"nested": {"items": ["a"]}},
    )
    decision = DelegationDecision(
        kind="review",
        payload={"paths": ["docs/evidence.json"]},
    )

    with pytest.raises(TypeError):
        work.policy_metadata["extra"] = "value"
    with pytest.raises(TypeError):
        work.policy_metadata["nested"]["other"] = "value"
    with pytest.raises(TypeError):
        decision.payload["paths"][0] = "docs/other.json"

    assert work.model_dump(mode="json")["policy_metadata"] == {"nested": {"items": ["a"]}}
    assert decision.model_dump(mode="json")["payload"] == {"paths": ["docs/evidence.json"]}


def test_delegation_state_apply_command_returns_new_state_without_mutating_old_state() -> None:
    fixed_time = datetime(2026, 1, 1, tzinfo=UTC)
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        status="requested",
    )
    state = DelegationState().with_work(work)
    command = DelegateCommand(
        kind="launch",
        work_id="child-1",
        owner_id="parent",
        idempotency_key="launch-child-1",
        expected_generation=0,
    )

    updated, updated_work, decision = state.apply_command(work, command, recorded_at=fixed_time)

    assert updated_work is not None
    assert decision.kind == "launch"
    assert state.delegated_work[0].status == "requested"
    assert state.delegation_decisions == ()
    assert updated.delegated_work[0].status == "running"
    assert updated.delegation_decisions[-1].idempotency_key == "launch-child-1"


def test_super_parent_policy_waits_for_active_delegate() -> None:
    policy = SuperParentDelegationPolicy()
    work = DelegatedWork(
        id="child-1",
        owner_id="parent",
        owner_kind="run",
        delegate_kind="run",
        status="running",
    )

    decision = policy.reduce(
        {
            "parent_run_id": "parent",
            "parent_status": "active",
            "max_child_runs": 20,
            "resolved_child_run_ids": set(),
            "child_count": 1,
        },
        [work],
        {},
    )

    assert decision.kind == "wait"
    assert decision.stable_state == "WaitingOnDelegate"


def test_super_parent_policy_detects_duplicate_child_create() -> None:
    policy = SuperParentDelegationPolicy()
    parent = Run(id="parent", repo_name="repo", status=RunStatus.ACTIVE)
    child = Run(
        id="child-1",
        repo_name="repo",
        status=RunStatus.ACTIVE,
        parent_run_id="parent",
        parent_slice_id="slice-1",
        routine_id="child-routine",
    )

    decision = policy.decision_for_create_child(
        parent,
        [child],
        child_run_id="child-1",
        max_child_runs=20,
        resolved_child_run_ids=set(),
    )

    assert decision.kind == "stale_command_ignored"
    assert decision.reason == "duplicate_child_create"
