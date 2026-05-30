"""Tests for backward transition logic."""

import pytest
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.config import ChecklistStatus, Priority, RunStatus, TaskStatus
from orchestrator.config.models import (
    RoutineConfig,
    StepConfig,
    StepTransitions,
    TaskConfig,
    TransitionCondition,
)
from orchestrator.state.models import (
    Attempt,
    ChecklistItem,
    Run,
    StepState,
    TaskState,
    TransitionTracker,
)
from orchestrator.workflow import (
    BufferingEmitter,
    DefaultClock,
    RunStepBackward,
    check_step_progression,
    evaluate_condition,
    evaluate_transition_conditions,
)

NOW = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

# --- TransitionTracker Tests ---


def test_transition_tracker_init() -> None:
    """TransitionTracker initializes with empty counts."""
    tracker = TransitionTracker()
    assert tracker.counts == {}


def test_transition_tracker_record() -> None:
    """record_transition increments the count."""
    tracker = TransitionTracker()
    tracker.record_transition("S-01", "S-02")
    assert tracker.get_count("S-01", "S-02") == 1
    tracker.record_transition("S-01", "S-02")
    assert tracker.get_count("S-01", "S-02") == 2


def test_transition_tracker_can_transition_allows() -> None:
    """can_transition returns True when under max iterations."""
    tracker = TransitionTracker()
    tracker.record_transition("S-01", "S-02")
    assert tracker.can_transition("S-01", "S-02", max_iterations=3) is True


def test_transition_tracker_can_transition_blocks_at_max() -> None:
    """can_transition returns False when at max iterations."""
    tracker = TransitionTracker()
    tracker.record_transition("S-01", "S-02")
    tracker.record_transition("S-01", "S-02")
    tracker.record_transition("S-01", "S-02")
    assert tracker.can_transition("S-01", "S-02", max_iterations=3) is False


def test_transition_tracker_get_count_nonexistent() -> None:
    """get_count returns 0 for non-existent transitions."""
    tracker = TransitionTracker()
    assert tracker.get_count("S-01", "S-02") == 0


def test_transition_tracker_independent_transitions() -> None:
    """Different transitions are tracked independently."""
    tracker = TransitionTracker()
    tracker.record_transition("S-01", "S-02")
    tracker.record_transition("S-02", "S-03")
    assert tracker.get_count("S-01", "S-02") == 1
    assert tracker.get_count("S-02", "S-03") == 1
    assert tracker.get_count("S-01", "S-03") == 0


# --- Condition Evaluation Tests ---


def test_evaluate_condition_checklist_incomplete_true() -> None:
    """checklist_incomplete returns True when critical items are not done."""
    checklist = [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.OPEN,
        ),
    ]
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("checklist_incomplete", checklist, run) is True


def test_evaluate_condition_checklist_incomplete_false() -> None:
    """checklist_incomplete returns False when all critical items are done."""
    checklist = [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.DONE,
        ),
    ]
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("checklist_incomplete", checklist, run) is False


def test_evaluate_condition_checklist_incomplete_expected_not_done() -> None:
    """checklist_incomplete ignores non-critical items."""
    checklist = [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.EXPECTED,
            status=ChecklistStatus.OPEN,
        ),
    ]
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("checklist_incomplete", checklist, run) is False


def test_evaluate_condition_checklist_specific_item() -> None:
    """checklist:item_id checks specific checklist item."""
    checklist = [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.OPEN,
        ),
        ChecklistItem(
            req_id="R2",
            desc="Req 2",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.DONE,
        ),
    ]
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("checklist:R1", checklist, run) is True
    assert evaluate_condition("checklist:R2", checklist, run) is False


def test_evaluate_condition_checklist_item_not_found() -> None:
    """checklist:item_id returns False when item not found."""
    checklist = [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.DONE,
        ),
    ]
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("checklist:R999", checklist, run) is False


def test_evaluate_condition_has_unresolved_conflicts_no_worktree() -> None:
    """has_unresolved_conflicts returns False when no worktree provided."""
    checklist: list[ChecklistItem] = []
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("has_unresolved_conflicts", checklist, run) is False


def test_evaluate_condition_has_unresolved_conflicts_no_file(tmp_path: Path) -> None:
    """has_unresolved_conflicts returns False when CONFLICTS.md doesn't exist."""
    checklist: list[ChecklistItem] = []
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("has_unresolved_conflicts", checklist, run, tmp_path) is False


def test_evaluate_condition_has_unresolved_conflicts_with_unresolved(tmp_path: Path) -> None:
    """has_unresolved_conflicts returns True when file contains unresolved items."""
    conflicts_file = tmp_path / "CONFLICTS.md"
    conflicts_file.write_text(
        "# Conflicts\n\n- [ ] Unresolved conflict 1\n- [x] Resolved conflict 2"
    )
    checklist: list[ChecklistItem] = []
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("has_unresolved_conflicts", checklist, run, tmp_path) is True


def test_evaluate_condition_has_unresolved_conflicts_all_resolved(tmp_path: Path) -> None:
    """has_unresolved_conflicts returns False when all conflicts are resolved."""
    conflicts_file = tmp_path / "CONFLICTS.md"
    conflicts_file.write_text("# Conflicts\n\n- [x] Resolved conflict 1\n- [x] Resolved conflict 2")
    checklist: list[ChecklistItem] = []
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("has_unresolved_conflicts", checklist, run, tmp_path) is False


def test_evaluate_condition_has_open_questions_no_worktree() -> None:
    """has_open_questions returns False when no worktree provided."""
    checklist: list[ChecklistItem] = []
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("has_open_questions", checklist, run) is False


def test_evaluate_condition_has_open_questions_no_file(tmp_path: Path) -> None:
    """has_open_questions returns False when design-questions.md doesn't exist."""
    checklist: list[ChecklistItem] = []
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("has_open_questions", checklist, run, tmp_path) is False


def test_evaluate_condition_has_open_questions_with_open(tmp_path: Path) -> None:
    """has_open_questions returns True when file contains open questions."""
    questions_file = tmp_path / "design-questions.md"
    questions_file.write_text("# Questions\n\n- [ ] Open question 1\n- [x] Answered question 2")
    checklist: list[ChecklistItem] = []
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("has_open_questions", checklist, run, tmp_path) is True


def test_evaluate_condition_has_open_questions_all_answered(tmp_path: Path) -> None:
    """has_open_questions returns False when all questions are answered."""
    questions_file = tmp_path / "design-questions.md"
    questions_file.write_text("# Questions\n\n- [x] Answered question 1\n- [x] Answered question 2")
    checklist: list[ChecklistItem] = []
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("has_open_questions", checklist, run, tmp_path) is False


def test_evaluate_condition_unknown() -> None:
    """Unknown conditions return False."""
    checklist: list[ChecklistItem] = []
    run = Run(id="run-1", repo_name="proj-1")
    assert evaluate_condition("unknown_condition", checklist, run) is False


# --- evaluate_transition_conditions Tests ---


def test_evaluate_transition_conditions_no_transitions() -> None:
    """Returns None, None when step has no transitions configured."""
    step_config = StepConfig(
        id="S-01",
        title="Step 1",
        tasks=[TaskConfig(id="T-01", title="Task 1", task_context="Context")],
    )
    step_state = StepState(id="step-1", config_id="S-01")
    checklist: list[ChecklistItem] = []
    run = Run(id="run-1", repo_name="proj-1")

    target, message = evaluate_transition_conditions(step_config, step_state, checklist, run)
    assert target is None
    assert message is None


def test_evaluate_transition_conditions_condition_not_met() -> None:
    """Returns on_complete when conditions are not met."""
    step_config = StepConfig(
        id="S-01",
        title="Step 1",
        tasks=[TaskConfig(id="T-01", title="Task 1", task_context="Context")],
        transitions=StepTransitions(
            on_complete="S-02",
            on_condition=[
                TransitionCondition(
                    condition="checklist_incomplete",
                    target="S-00",
                    max_iterations=3,
                    message="Checklist incomplete",
                ),
            ],
        ),
    )
    step_state = StepState(id="step-1", config_id="S-01")
    checklist = [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.DONE,
        ),
    ]
    run = Run(id="run-1", repo_name="proj-1")

    target, message = evaluate_transition_conditions(step_config, step_state, checklist, run)
    assert target == "S-02"
    assert message is None


def test_evaluate_transition_conditions_condition_met() -> None:
    """Returns target and message when condition is met."""
    step_config = StepConfig(
        id="S-01",
        title="Step 1",
        tasks=[TaskConfig(id="T-01", title="Task 1", task_context="Context")],
        transitions=StepTransitions(
            on_complete="S-02",
            on_condition=[
                TransitionCondition(
                    condition="checklist_incomplete",
                    target="S-00",
                    max_iterations=3,
                    message="Checklist incomplete - returning to review",
                ),
            ],
        ),
    )
    step_state = StepState(id="step-1", config_id="S-01")
    checklist = [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.OPEN,
        ),
    ]
    run = Run(id="run-1", repo_name="proj-1")

    target, message = evaluate_transition_conditions(step_config, step_state, checklist, run)
    assert target == "S-00"
    assert message == "Checklist incomplete - returning to review"
    # Verify transition was recorded
    assert run.transition_tracker is not None
    assert run.transition_tracker.get_count("S-01", "S-00") == 1


def test_evaluate_transition_conditions_max_iterations_reached() -> None:
    """Skips condition when max iterations reached."""
    step_config = StepConfig(
        id="S-01",
        title="Step 1",
        tasks=[TaskConfig(id="T-01", title="Task 1", task_context="Context")],
        transitions=StepTransitions(
            on_complete="S-02",
            on_condition=[
                TransitionCondition(
                    condition="checklist_incomplete",
                    target="S-00",
                    max_iterations=2,
                    message="Checklist incomplete",
                ),
            ],
        ),
    )
    step_state = StepState(id="step-1", config_id="S-01")
    checklist = [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.OPEN,
        ),
    ]
    run = Run(id="run-1", repo_name="proj-1")

    # Record the transition twice to reach max
    run.transition_tracker = TransitionTracker()
    run.transition_tracker.record_transition("S-01", "S-00")
    run.transition_tracker.record_transition("S-01", "S-00")

    # Now the condition should be skipped despite being met
    target, message = evaluate_transition_conditions(step_config, step_state, checklist, run)
    assert target == "S-02"  # Should proceed normally
    assert message is None
    # Count should remain at 2 (not incremented)
    assert run.transition_tracker.get_count("S-01", "S-00") == 2


def test_evaluate_transition_conditions_multiple_conditions_first_wins() -> None:
    """First matching condition wins."""
    step_config = StepConfig(
        id="S-01",
        title="Step 1",
        tasks=[TaskConfig(id="T-01", title="Task 1", task_context="Context")],
        transitions=StepTransitions(
            on_complete="S-03",
            on_condition=[
                TransitionCondition(
                    condition="checklist:R1",
                    target="S-00",
                    max_iterations=3,
                    message="R1 not done",
                ),
                TransitionCondition(
                    condition="checklist:R2",
                    target="S-02",
                    max_iterations=3,
                    message="R2 not done",
                ),
            ],
        ),
    )
    step_state = StepState(id="step-1", config_id="S-01")
    checklist = [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.OPEN,
        ),
        ChecklistItem(
            req_id="R2",
            desc="Req 2",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.OPEN,
        ),
    ]
    run = Run(id="run-1", repo_name="proj-1")

    target, message = evaluate_transition_conditions(step_config, step_state, checklist, run)
    assert target == "S-00"  # First condition wins
    assert message == "R1 not done"


def test_evaluate_transition_conditions_second_condition_after_first_max() -> None:
    """Second condition can trigger after first reaches max iterations."""
    step_config = StepConfig(
        id="S-01",
        title="Step 1",
        tasks=[TaskConfig(id="T-01", title="Task 1", task_context="Context")],
        transitions=StepTransitions(
            on_complete="S-03",
            on_condition=[
                TransitionCondition(
                    condition="checklist:R1",
                    target="S-00",
                    max_iterations=1,
                    message="R1 not done",
                ),
                TransitionCondition(
                    condition="checklist:R2",
                    target="S-02",
                    max_iterations=3,
                    message="R2 not done",
                ),
            ],
        ),
    )
    step_state = StepState(id="step-1", config_id="S-01")
    checklist = [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.OPEN,
        ),
        ChecklistItem(
            req_id="R2",
            desc="Req 2",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.OPEN,
        ),
    ]
    run = Run(id="run-1", repo_name="proj-1")

    # Record first transition to reach max
    run.transition_tracker = TransitionTracker()
    run.transition_tracker.record_transition("S-01", "S-00")

    # Now second condition should trigger
    target, message = evaluate_transition_conditions(step_config, step_state, checklist, run)
    assert target == "S-02"  # Second condition
    assert message == "R2 not done"


def test_evaluate_transition_conditions_initializes_tracker() -> None:
    """Initializes transition tracker if not present."""
    step_config = StepConfig(
        id="S-01",
        title="Step 1",
        tasks=[TaskConfig(id="T-01", title="Task 1", task_context="Context")],
        transitions=StepTransitions(
            on_complete="S-02",
            on_condition=[
                TransitionCondition(
                    condition="checklist_incomplete",
                    target="S-00",
                    max_iterations=3,
                ),
            ],
        ),
    )
    step_state = StepState(id="step-1", config_id="S-01")
    checklist = [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.OPEN,
        ),
    ]
    run = Run(id="run-1", repo_name="proj-1")
    run.transition_tracker = None  # Explicitly set to None

    evaluate_transition_conditions(step_config, step_state, checklist, run)
    assert run.transition_tracker is not None
    assert run.transition_tracker.get_count("S-01", "S-00") == 1


def test_step_progression_applies_configured_loop_transition() -> None:
    """Completed steps can route backward through configured transition rules."""
    routine = RoutineConfig(
        id="super-parent-test",
        name="Super Parent Test",
        steps=[
            StepConfig(
                id="SP-02",
                title="Select Next Slice",
                tasks=[TaskConfig(id="T-01", title="Select", task_context="Select")],
            ),
            StepConfig(
                id="SP-03",
                title="Launch Child Run",
                tasks=[TaskConfig(id="T-01", title="Launch", task_context="Launch")],
            ),
            StepConfig(
                id="SP-04",
                title="Evaluate Evidence",
                tasks=[TaskConfig(id="T-01", title="Evaluate", task_context="Evaluate")],
                transitions=StepTransitions(
                    on_condition=[
                        TransitionCondition(
                            condition="super_parent_has_unresolved_inventory",
                            target="SP-02",
                            max_iterations=3,
                            message="Inventory remains unresolved",
                        )
                    ]
                ),
            ),
        ],
    )
    run = Run(
        id="run-1",
        repo_name="proj-1",
        status=RunStatus.ACTIVE,
        current_step_index=2,
        oversight_state={"target_inventory": [{"id": "INV-001", "resolved": False}]},
        steps=[
            StepState(
                id="step-1",
                config_id="SP-02",
                completed=True,
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.COMPLETED,
                        attempts=[Attempt(attempt_num=1, started_at=NOW, outcome="passed")],
                        current_attempt=1,
                    )
                ],
            ),
            StepState(
                id="step-2",
                config_id="SP-03",
                completed=True,
                tasks=[
                    TaskState(
                        id="task-2",
                        config_id="T-01",
                        status=TaskStatus.COMPLETED,
                        attempts=[Attempt(attempt_num=1, started_at=NOW, outcome="passed")],
                        current_attempt=1,
                    )
                ],
            ),
            StepState(
                id="step-3",
                config_id="SP-04",
                completed=False,
                tasks=[TaskState(id="task-3", config_id="T-01", status=TaskStatus.COMPLETED)],
            ),
        ],
    )
    emitter = BufferingEmitter()

    changed = check_step_progression(
        run,
        routine_config=routine,
        clock=DefaultClock(),
        emitter=emitter,
    )

    assert changed is True
    assert run.current_step_index == 0
    assert [step.completed for step in run.steps] == [False, False, False]
    assert [step.tasks[0].status for step in run.steps] == [
        TaskStatus.PENDING,
        TaskStatus.PENDING,
        TaskStatus.PENDING,
    ]
    assert [step.tasks[0].current_attempt for step in run.steps] == [0, 0, 0]
    assert [step.tasks[0].attempts for step in run.steps] == [[], [], []]
    assert run.transition_tracker is not None
    assert run.transition_tracker.get_count("SP-04", "SP-02") == 1
    events = emitter.drain()
    assert len(events) == 1
    assert isinstance(events[0], RunStepBackward)
    assert events[0].from_step_index == 2
    assert events[0].to_step_index == 0
    assert events[0].transition_tracker_delta == {"SP-04->SP-02": 1}


def test_step_progression_allows_conditional_loop_transition_for_failed_step() -> None:
    """Conditional loop transitions can handle a terminal step with failures."""
    routine = RoutineConfig(
        id="super-parent-test",
        name="Super Parent Test",
        steps=[
            StepConfig(
                id="SP-02",
                title="Select Next Slice",
                tasks=[TaskConfig(id="T-01", title="Select", task_context="Select")],
            ),
            StepConfig(
                id="SP-03",
                title="Launch Child Run",
                tasks=[TaskConfig(id="T-01", title="Launch", task_context="Launch")],
            ),
            StepConfig(
                id="SP-04",
                title="Evaluate Evidence",
                tasks=[
                    TaskConfig(id="T-01", title="Evaluate", task_context="Evaluate"),
                    TaskConfig(id="T-02", title="Accept", task_context="Accept"),
                ],
                transitions=StepTransitions(
                    on_condition=[
                        TransitionCondition(
                            condition="super_parent_has_unresolved_inventory",
                            target="SP-02",
                            max_iterations=3,
                            message="Inventory remains unresolved",
                        )
                    ],
                    on_complete="SP-05",
                ),
            ),
            StepConfig(
                id="SP-05",
                title="Validate",
                tasks=[TaskConfig(id="T-01", title="Validate", task_context="Validate")],
            ),
        ],
    )
    run = Run(
        id="run-1",
        repo_name="proj-1",
        status=RunStatus.ACTIVE,
        current_step_index=2,
        oversight_state={"target_inventory": [{"id": "INV-001", "resolved": False}]},
        steps=[
            StepState(
                id="step-1",
                config_id="SP-02",
                completed=True,
                tasks=[TaskState(id="task-1", config_id="T-01", status=TaskStatus.COMPLETED)],
            ),
            StepState(
                id="step-2",
                config_id="SP-03",
                completed=True,
                tasks=[TaskState(id="task-2", config_id="T-01", status=TaskStatus.COMPLETED)],
            ),
            StepState(
                id="step-3",
                config_id="SP-04",
                completed=False,
                tasks=[
                    TaskState(id="task-3", config_id="T-01", status=TaskStatus.FAILED),
                    TaskState(id="task-4", config_id="T-02", status=TaskStatus.COMPLETED),
                ],
            ),
            StepState(
                id="step-4",
                config_id="SP-05",
                completed=False,
                tasks=[TaskState(id="task-5", config_id="T-01", status=TaskStatus.PENDING)],
            ),
        ],
    )
    emitter = BufferingEmitter()

    changed = check_step_progression(
        run,
        routine_config=routine,
        clock=DefaultClock(),
        emitter=emitter,
    )

    assert changed is True
    assert run.status == RunStatus.ACTIVE
    assert run.current_step_index == 0
    assert [step.completed for step in run.steps] == [False, False, False, False]
    assert [task.status for task in run.steps[2].tasks] == [
        TaskStatus.PENDING,
        TaskStatus.PENDING,
    ]
    assert run.transition_tracker is not None
    assert run.transition_tracker.get_count("SP-04", "SP-02") == 1
    events = emitter.drain()
    assert len(events) == 1
    assert isinstance(events[0], RunStepBackward)
    assert events[0].from_step_index == 2
    assert events[0].to_step_index == 0
    assert events[0].transition_tracker_delta == {"SP-04->SP-02": 1}


def test_evaluate_transition_conditions_with_worktree(tmp_path: Path) -> None:
    """File-based conditions work with worktree path."""
    conflicts_file = tmp_path / "CONFLICTS.md"
    conflicts_file.write_text("- [ ] Unresolved conflict")

    step_config = StepConfig(
        id="S-01",
        title="Step 1",
        tasks=[TaskConfig(id="T-01", title="Task 1", task_context="Context")],
        transitions=StepTransitions(
            on_complete="S-02",
            on_condition=[
                TransitionCondition(
                    condition="has_unresolved_conflicts",
                    target="S-00",
                    max_iterations=3,
                    message="Conflicts found",
                ),
            ],
        ),
    )
    step_state = StepState(id="step-1", config_id="S-01")
    checklist: list[ChecklistItem] = []
    run = Run(id="run-1", repo_name="proj-1")

    target, message = evaluate_transition_conditions(
        step_config, step_state, checklist, run, tmp_path
    )
    assert target == "S-00"
    assert message == "Conflicts found"


# --- WorkflowEngine.transition_backward Tests ---


def test_transition_backward_basic() -> None:
    """Test basic backward transition."""
    from orchestrator.state.session import SessionStateManager
    from orchestrator.workflow import WorkflowEngine
    from orchestrator.workflow import BufferingEmitter, RunStepBackward

    # Create a run with 3 steps
    run = Run(id="run-1", repo_name="proj-1")
    run.steps = [
        StepState(id="step-1", config_id="S-01", completed=True),
        StepState(id="step-2", config_id="S-02", completed=True),
        StepState(id="step-3", config_id="S-03", completed=False),
    ]
    run.steps[0].tasks = [
        TaskState(
            id="task-1",
            config_id="T-01",
            status=TaskStatus.COMPLETED,
        )
    ]
    run.steps[1].tasks = [
        TaskState(
            id="task-2",
            config_id="T-02",
            status=TaskStatus.PENDING,
        )
    ]
    run.steps[2].tasks = [
        TaskState(
            id="task-3",
            config_id="T-03",
            status=TaskStatus.PENDING,
        )
    ]
    run.current_step_index = 2

    state = SessionStateManager()
    state.add_run(run)
    buffer = BufferingEmitter()
    engine = WorkflowEngine(state, emitter=buffer)

    # Transition backward to step 0
    updated_run = engine.transition_backward("run-1", 0, "Need to revise")

    assert updated_run.current_step_index == 0
    assert updated_run.steps[0].completed is False
    assert updated_run.steps[1].completed is False
    assert updated_run.steps[2].completed is False

    # Completed task should remain completed
    assert updated_run.steps[0].tasks[0].status == TaskStatus.COMPLETED
    # Other tasks should remain pending
    assert updated_run.steps[1].tasks[0].status == TaskStatus.PENDING

    # Check event was emitted
    events = buffer.drain()
    assert len(events) == 1
    assert events[0].event_type == "run_step_backward"
    event = events[0]
    assert isinstance(event, RunStepBackward)
    assert event.from_step_index == 2
    assert event.to_step_index == 0
    assert event.reason == "Need to revise"


def test_transition_backward_invalid_target_out_of_bounds() -> None:
    """Test backward transition with invalid target (out of bounds)."""
    from orchestrator.state.session import SessionStateManager
    from orchestrator.workflow import WorkflowEngine
    from orchestrator.workflow import InvalidTransitionError

    run = Run(id="run-1", repo_name="proj-1")
    run.steps = [
        StepState(id="step-1", config_id="S-01"),
        StepState(id="step-2", config_id="S-02"),
    ]
    run.current_step_index = 1

    state = SessionStateManager()
    state.add_run(run)
    engine = WorkflowEngine(state)

    # Try to transition to invalid index
    with pytest.raises(InvalidTransitionError, match="out of bounds"):
        engine.transition_backward("run-1", 5)


def test_transition_backward_invalid_target_forward() -> None:
    """Test that transitioning forward raises error."""
    from orchestrator.state.session import SessionStateManager
    from orchestrator.workflow import WorkflowEngine
    from orchestrator.workflow import InvalidTransitionError

    run = Run(id="run-1", repo_name="proj-1")
    run.steps = [
        StepState(id="step-1", config_id="S-01"),
        StepState(id="step-2", config_id="S-02"),
    ]
    run.current_step_index = 0

    state = SessionStateManager()
    state.add_run(run)
    engine = WorkflowEngine(state)

    # Try to transition forward (should fail)
    with pytest.raises(InvalidTransitionError, match="must be before current"):
        engine.transition_backward("run-1", 1)


def test_transition_backward_invalid_target_same_step() -> None:
    """Test that transitioning to same step raises error."""
    from orchestrator.state.session import SessionStateManager
    from orchestrator.workflow import WorkflowEngine
    from orchestrator.workflow import InvalidTransitionError

    run = Run(id="run-1", repo_name="proj-1")
    run.steps = [
        StepState(id="step-1", config_id="S-01"),
        StepState(id="step-2", config_id="S-02"),
    ]
    run.current_step_index = 1

    state = SessionStateManager()
    state.add_run(run)
    engine = WorkflowEngine(state)

    # Try to transition to same step (should fail)
    with pytest.raises(InvalidTransitionError, match="must be before current"):
        engine.transition_backward("run-1", 1)
