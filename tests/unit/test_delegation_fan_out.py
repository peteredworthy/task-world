"""Unit tests for fan-out delegation policy primitives."""

from orchestrator.config import RunStatus, TaskStatus
from orchestrator.state import Run, TaskState
from orchestrator.workflow import (
    FanOutDelegationPolicy,
    build_fan_out_facts,
    work_from_fan_out_child,
)


def test_fan_out_child_maps_to_delegated_work() -> None:
    child = TaskState(
        id="child-1",
        config_id="T-01_fan_0",
        title="Item 1",
        status=TaskStatus.BUILDING,
        parent_task_id="parent-task",
        fan_out_index=0,
        fan_out_input="docs/input.md",
        fan_out_output="docs/output.md",
        current_attempt=1,
        child_id="stable-child",
    )

    work = work_from_fan_out_child(child)

    assert work.owner_id == "parent-task"
    assert work.owner_kind == "task"
    assert work.delegate_kind == "task"
    assert work.generation == 1
    assert work.status == "running"
    assert work.output_contract == "fan_out.output.v1"


def test_fan_out_policy_waits_while_any_child_is_active() -> None:
    parent = TaskState(
        id="parent-task",
        config_id="T-01",
        status=TaskStatus.FAN_OUT_RUNNING,
    )
    children = [
        TaskState(
            id="child-1",
            config_id="T-01_fan_0",
            status=TaskStatus.COMPLETED,
            parent_task_id="parent-task",
        ),
        TaskState(
            id="child-2",
            config_id="T-01_fan_1",
            status=TaskStatus.BUILDING,
            parent_task_id="parent-task",
        ),
    ]
    facts, works = build_fan_out_facts(parent, children)

    decision = FanOutDelegationPolicy().reduce(facts.model_dump(), works, {})

    assert decision.kind == "wait"
    assert decision.stable_state == "WaitingOnDelegate"
    assert decision.payload["active_child_count"] == 1


def test_fan_out_policy_completes_when_all_children_completed() -> None:
    parent = TaskState(
        id="parent-task",
        config_id="T-01",
        status=TaskStatus.FAN_OUT_RUNNING,
    )
    children = [
        TaskState(
            id="child-1",
            config_id="T-01_fan_0",
            status=TaskStatus.COMPLETED,
            parent_task_id="parent-task",
        ),
        TaskState(
            id="child-2",
            config_id="T-01_fan_1",
            status=TaskStatus.COMPLETED,
            parent_task_id="parent-task",
        ),
    ]
    facts, works = build_fan_out_facts(parent, children)

    decision = FanOutDelegationPolicy().reduce(facts.model_dump(), works, {})

    assert decision.kind == "complete"
    assert decision.reason == "fan_out_children_complete"


def test_fan_out_parent_completion_duplicate_is_stale_noop() -> None:
    decision = FanOutDelegationPolicy().decision_for_parent_completion(
        TaskStatus.COMPLETED.value,
        all_passed=True,
        to_verifying=False,
    )

    assert decision.kind == "stale_command_ignored"
    assert decision.stable_state == "StaleCommandIgnored"


def test_fan_out_parent_completion_can_wait_on_verifier_gate() -> None:
    decision = FanOutDelegationPolicy().decision_for_parent_completion(
        TaskStatus.FAN_OUT_RUNNING.value,
        all_passed=True,
        to_verifying=True,
    )

    assert decision.kind == "complete"
    assert decision.stable_state == "AwaitingGate"
    assert decision.payload["new_status"] == TaskStatus.VERIFYING.value


def test_fan_out_start_parent_uses_stable_decision_vocabulary() -> None:
    run = Run(id="run-1", repo_name="repo", status=RunStatus.ACTIVE)
    task = TaskState(
        id="parent-task",
        config_id="T-01",
        status=TaskStatus.FAN_OUT_RUNNING,
    )

    decision = FanOutDelegationPolicy().decision_for_start_parent(run, task)

    assert decision.kind == "wait"
    assert decision.stable_state == "WaitingOnDelegate"
