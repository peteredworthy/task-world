# Implementation Slices: Phase 2 - Workflow Engine

**Goal:** Implement the core workflow logic: checklist gates, grade evaluation, state machine, and transitions.

**End state:** Can execute a complete task lifecycle (pending → building → verifying → completed) with gate enforcement.

**Prerequisites:** Phase 1 complete.

---

## Slice 2.1: Checklist Gate Logic

### Goal
Implement pure functions that evaluate whether a checklist passes the gate to proceed to verification.

### Prerequisites
- Slice 1.4 complete (state models)

### Deliverables

```
src/orchestrator/
├── workflow/
│   ├── __init__.py
│   ├── gates.py       # Gate evaluation logic
│   └── errors.py      # Workflow errors
tests/unit/
└── test_checklist_gates.py
```

### Architecture Constraints

1. **Pure functions only** - Gates are logic, not I/O. They take data, return results.

2. **Gate rules are explicit:**
   - CRITICAL requirements: Must be DONE, or (NOT_APPLICABLE/BLOCKED with note)
   - EXPECTED requirements: Should be DONE, warn if not
   - NICE requirements: Informational only

3. **GateResult is a value object** - Contains pass/fail, blocking items, and messages.

### Implementation Steps

1. Create `src/orchestrator/workflow/errors.py`:
   ```python
   class WorkflowError(Exception):
       """Base class for workflow errors."""
       pass
   
   class GateBlockedError(WorkflowError):
       def __init__(self, gate_name: str, blocking_items: list[str]):
           self.gate_name = gate_name
           self.blocking_items = blocking_items
           super().__init__(
               f"Gate '{gate_name}' blocked by: {', '.join(blocking_items)}"
           )
   
   class InvalidTransitionError(WorkflowError):
       def __init__(self, from_status: str, to_status: str):
           self.from_status = from_status
           self.to_status = to_status
           super().__init__(f"Invalid transition: {from_status} → {to_status}")
   ```

2. Create `src/orchestrator/workflow/gates.py`:
   ```python
   from dataclasses import dataclass, field
   from orchestrator.state.models import ChecklistItem
   from orchestrator.config.enums import ChecklistStatus, Priority
   
   @dataclass
   class GateResult:
       """Result of gate evaluation."""
       passed: bool
       blocking_items: list[str] = field(default_factory=list)
       warnings: list[str] = field(default_factory=list)
       message: str | None = None
   
   def evaluate_checklist_gate(checklist: list[ChecklistItem]) -> GateResult:
       """
       Evaluate whether checklist passes the gate to proceed.
       
       Rules:
       - CRITICAL items must be DONE, or (NOT_APPLICABLE/BLOCKED with note)
       - EXPECTED items should be DONE (warning if not)
       - NICE items are informational
       """
       blocking = []
       warnings = []
       
       for item in checklist:
           if item.priority == Priority.CRITICAL:
               if item.status == ChecklistStatus.OPEN:
                   blocking.append(f"{item.req_id}: {item.desc} (not completed)")
               elif item.status in (ChecklistStatus.NOT_APPLICABLE, ChecklistStatus.BLOCKED):
                   if not item.note:
                       blocking.append(
                           f"{item.req_id}: {item.desc} "
                           f"(marked {item.status.value} without justification)"
                       )
           elif item.priority == Priority.EXPECTED:
               if item.status == ChecklistStatus.OPEN:
                   warnings.append(f"{item.req_id}: {item.desc} (not completed)")
               elif item.status in (ChecklistStatus.NOT_APPLICABLE, ChecklistStatus.BLOCKED):
                   if not item.note:
                       warnings.append(
                           f"{item.req_id}: {item.desc} "
                           f"(marked {item.status.value} without justification)"
                       )
       
       passed = len(blocking) == 0
       message = None
       if not passed:
           message = f"Checklist gate failed: {len(blocking)} blocking item(s)"
       elif warnings:
           message = f"Checklist gate passed with {len(warnings)} warning(s)"
       
       return GateResult(passed=passed, blocking_items=blocking, warnings=warnings, message=message)
   ```

3. Create comprehensive unit tests in `tests/unit/test_checklist_gates.py` covering:
   - Empty checklist passes
   - All done passes
   - Critical open blocks
   - Critical N/A without note blocks
   - Critical N/A with note passes
   - Expected open warns but passes
   - Nice open does not warn

### Verification

#### Unit Tests
```bash
uv run pytest tests/unit/test_checklist_gates.py -v
```

### Definition of Done
- [ ] `evaluate_checklist_gate` function works correctly
- [ ] All priority levels handled correctly
- [ ] N/A and blocked with/without notes handled
- [ ] All unit tests pass

---

## Slice 2.2: Grade Evaluation Logic

### Goal
Implement pure functions that evaluate verifier grades against requirements.

### Prerequisites
- Slice 2.1 complete

### Deliverables

```
src/orchestrator/workflow/grades.py
tests/unit/test_grade_evaluation.py
```

### Architecture Constraints

1. **Grade order is fixed** - A > B > C > D > F (best to worst)
2. **Threshold rules:**
   - CRITICAL: Must be A (configurable)
   - EXPECTED: Must be B or higher
   - NICE: No threshold

### Implementation Steps

1. Create `src/orchestrator/workflow/grades.py`:
   ```python
   from dataclasses import dataclass, field
   from orchestrator.state.models import ChecklistItem
   from orchestrator.config.enums import Priority
   
   DEFAULT_GRADE_ORDER = ["A", "B", "C", "D", "F"]
   
   @dataclass
   class GradeResult:
       passed: bool
       failing_items: list[str] = field(default_factory=list)
       revision_guidance: list[str] = field(default_factory=list)
       message: str | None = None
   
   def grade_meets_threshold(
       grade: str, threshold: str, grade_order: list[str] = DEFAULT_GRADE_ORDER
   ) -> bool:
       """Check if a grade meets or exceeds a threshold."""
       try:
           return grade_order.index(grade) <= grade_order.index(threshold)
       except ValueError:
           return False
   
   def evaluate_grades(
       checklist: list[ChecklistItem],
       critical_threshold: str = "A",
       expected_threshold: str = "B",
       grade_order: list[str] = DEFAULT_GRADE_ORDER,
   ) -> GradeResult:
       """Evaluate grades against thresholds by priority."""
       failing = []
       guidance = []
       
       for item in checklist:
           if item.grade is None:
               continue
           
           if item.priority == Priority.CRITICAL:
               if not grade_meets_threshold(item.grade, critical_threshold, grade_order):
                   failing.append(f"{item.req_id}: Grade {item.grade} below {critical_threshold}")
                   if item.grade_reason:
                       guidance.append(f"{item.req_id}: {item.grade_reason}")
           elif item.priority == Priority.EXPECTED:
               if not grade_meets_threshold(item.grade, expected_threshold, grade_order):
                   failing.append(f"{item.req_id}: Grade {item.grade} below {expected_threshold}")
                   if item.grade_reason:
                       guidance.append(f"{item.req_id}: {item.grade_reason}")
       
       passed = len(failing) == 0
       message = f"Grade evaluation failed: {len(failing)} item(s) below threshold" if not passed else None
       return GradeResult(passed=passed, failing_items=failing, revision_guidance=guidance, message=message)
   ```

### Verification

#### Unit Tests
```bash
uv run pytest tests/unit/test_grade_evaluation.py -v
```

### Definition of Done
- [ ] `grade_meets_threshold` function works
- [ ] `evaluate_grades` function works
- [ ] Priority thresholds applied correctly
- [ ] All unit tests pass

---

## Slice 2.3: Task State Machine

### Goal
Implement state transitions for task lifecycle with validation.

### Prerequisites
- Slices 2.1, 2.2 complete

### Deliverables

```
src/orchestrator/workflow/transitions.py
tests/unit/test_task_transitions.py
```

### Architecture Constraints

1. **Valid transitions only:**
   ```
   PENDING → BUILDING
   BUILDING → VERIFYING (if checklist gate passes)
   VERIFYING → COMPLETED (if grades pass)
   VERIFYING → BUILDING (revision if grades fail, attempts remain)
   BUILDING → FAILED (max attempts on checklist failure)
   VERIFYING → FAILED (max attempts on grade failure)
   ```

2. **Transition functions are pure** - Take state + time, return result

3. **Time is injected** - Pass `now` parameter, never call datetime.now() inside

### Implementation Steps

1. Create `src/orchestrator/workflow/transitions.py`:
   ```python
   from dataclasses import dataclass
   from datetime import datetime
   from orchestrator.state.models import TaskState, Attempt
   from orchestrator.config.enums import TaskStatus
   from orchestrator.workflow.gates import evaluate_checklist_gate, GateResult
   from orchestrator.workflow.grades import evaluate_grades, GradeResult
   
   VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
       TaskStatus.PENDING: {TaskStatus.BUILDING},
       TaskStatus.BUILDING: {TaskStatus.VERIFYING, TaskStatus.FAILED},
       TaskStatus.VERIFYING: {TaskStatus.COMPLETED, TaskStatus.BUILDING, TaskStatus.FAILED},
       TaskStatus.COMPLETED: set(),
       TaskStatus.FAILED: set(),
   }
   
   @dataclass
   class TransitionResult:
       success: bool
       new_status: TaskStatus
       gate_result: GateResult | None = None
       grade_result: GradeResult | None = None
       error: str | None = None
   
   def transition_to_building(task: TaskState, now: datetime) -> TransitionResult:
       """Start building (from PENDING or VERIFYING for revision)."""
       if task.status not in (TaskStatus.PENDING, TaskStatus.VERIFYING):
           return TransitionResult(
               success=False, new_status=task.status,
               error=f"Cannot start building from {task.status.value}"
           )
       
       attempt_num = len(task.attempts) + 1
       task.attempts.append(Attempt(attempt_num=attempt_num, started_at=now))
       task.current_attempt = attempt_num
       task.status = TaskStatus.BUILDING
       return TransitionResult(success=True, new_status=TaskStatus.BUILDING)
   
   def transition_to_verifying(task: TaskState) -> TransitionResult:
       """Move to verification (requires checklist gate pass)."""
       if task.status != TaskStatus.BUILDING:
           return TransitionResult(
               success=False, new_status=task.status,
               error=f"Cannot verify from {task.status.value}"
           )
       
       gate_result = evaluate_checklist_gate(task.checklist)
       if not gate_result.passed:
           return TransitionResult(
               success=False, new_status=TaskStatus.BUILDING,
               gate_result=gate_result, error="Checklist gate failed"
           )
       
       task.status = TaskStatus.VERIFYING
       return TransitionResult(success=True, new_status=TaskStatus.VERIFYING, gate_result=gate_result)
   
   def transition_after_verification(task: TaskState, now: datetime) -> TransitionResult:
       """Complete verification - to COMPLETED, revision, or FAILED."""
       if task.status != TaskStatus.VERIFYING:
           return TransitionResult(
               success=False, new_status=task.status,
               error=f"Cannot complete verification from {task.status.value}"
           )
       
       grade_result = evaluate_grades(task.checklist)
       
       # Mark attempt complete
       if task.attempts:
           task.attempts[-1].completed_at = now
           task.attempts[-1].outcome = "passed" if grade_result.passed else "revision_needed"
       
       if grade_result.passed:
           task.status = TaskStatus.COMPLETED
           return TransitionResult(success=True, new_status=TaskStatus.COMPLETED, grade_result=grade_result)
       
       # Check retry limit
       if task.current_attempt >= task.max_attempts:
           task.status = TaskStatus.FAILED
           if task.attempts:
               task.attempts[-1].outcome = "failed"
           return TransitionResult(
               success=True, new_status=TaskStatus.FAILED,
               grade_result=grade_result, error=f"Max attempts ({task.max_attempts}) reached"
           )
       
       # Start revision
       task.status = TaskStatus.BUILDING
       task.attempts.append(Attempt(attempt_num=task.current_attempt + 1, started_at=now))
       task.current_attempt += 1
       return TransitionResult(success=True, new_status=TaskStatus.BUILDING, grade_result=grade_result)
   ```

2. Create tests covering:
   - Valid transitions succeed
   - Invalid transitions fail
   - Gate enforcement on BUILDING → VERIFYING
   - Grade enforcement on VERIFYING completion
   - Retry logic and max attempts
   - Attempt tracking

### Verification

#### Unit Tests
```bash
uv run pytest tests/unit/test_task_transitions.py -v
```

### Definition of Done
- [ ] All transition functions work
- [ ] Invalid transitions rejected
- [ ] Gates enforced correctly
- [ ] Retry logic works
- [ ] Attempts tracked correctly

---

## Slice 2.4: Workflow Engine

### Goal
Create the WorkflowEngine class that orchestrates task execution through the state machine.

### Prerequisites
- Slice 2.3 complete

### Deliverables

```
src/orchestrator/workflow/engine.py
tests/unit/test_workflow_engine.py
tests/integration/test_workflow_execution.py
```

### Architecture Constraints

1. **Engine coordinates, doesn't execute** - It manages state transitions, not agent calls
2. **Inject all dependencies** - StateManager, clock, event emitter
3. **Events for observability** - Emit events on state changes for UI/logging
4. **Engine is stateless** - All state lives in StateManager

### Implementation Steps

1. Create `src/orchestrator/workflow/events.py`:
   ```python
   from dataclasses import dataclass
   from datetime import datetime
   from orchestrator.config.enums import TaskStatus, RunStatus
   
   @dataclass
   class WorkflowEvent:
       timestamp: datetime
       run_id: str
       event_type: str
   
   @dataclass
   class TaskStatusChanged(WorkflowEvent):
       task_id: str
       old_status: TaskStatus
       new_status: TaskStatus
       message: str | None = None
   
   @dataclass
   class RunStatusChanged(WorkflowEvent):
       old_status: RunStatus
       new_status: RunStatus
   
   @dataclass
   class ChecklistGateEvaluated(WorkflowEvent):
       task_id: str
       passed: bool
       blocking_items: list[str]
   
   @dataclass
   class GradesEvaluated(WorkflowEvent):
       task_id: str
       passed: bool
       failing_items: list[str]
   ```

2. Create `src/orchestrator/workflow/engine.py`:
   ```python
   from typing import Protocol, Callable
   from datetime import datetime
   from orchestrator.state.session import SessionStateManager
   from orchestrator.state.models import Run, TaskState
   from orchestrator.config.enums import RunStatus, TaskStatus
   from orchestrator.workflow.transitions import (
       transition_to_building,
       transition_to_verifying,
       transition_after_verification,
       TransitionResult,
   )
   from orchestrator.workflow.events import (
       WorkflowEvent, TaskStatusChanged, RunStatusChanged
   )
   
   class Clock(Protocol):
       def now(self) -> datetime: ...
   
   class EventEmitter(Protocol):
       def emit(self, event: WorkflowEvent) -> None: ...
   
   class DefaultClock:
       def now(self) -> datetime:
           return datetime.utcnow()
   
   class NoOpEmitter:
       def emit(self, event: WorkflowEvent) -> None:
           pass
   
   class WorkflowEngine:
       def __init__(
           self,
           state_manager: SessionStateManager,
           clock: Clock | None = None,
           emitter: EventEmitter | None = None,
       ):
           self._state = state_manager
           self._clock = clock or DefaultClock()
           self._emitter = emitter or NoOpEmitter()
       
       def start_run(self, run_id: str) -> Run:
           """Start a run - move from DRAFT to ACTIVE."""
           run = self._state.get_run(run_id)
           if run.status != RunStatus.DRAFT:
               raise ValueError(f"Cannot start run in status {run.status.value}")
           
           old_status = run.status
           run.status = RunStatus.ACTIVE
           run.started_at = self._clock.now()
           self._state.update_run(run)
           
           self._emitter.emit(RunStatusChanged(
               timestamp=self._clock.now(), run_id=run_id,
               event_type="run_status_changed",
               old_status=old_status, new_status=RunStatus.ACTIVE
           ))
           return run
       
       def start_task(self, run_id: str, task_id: str) -> TransitionResult:
           """Start building a task."""
           task = self._state.get_task(run_id, task_id)
           old_status = task.status
           
           result = transition_to_building(task, self._clock.now())
           
           if result.success:
               self._state.update_run(self._state.get_run(run_id))
               self._emitter.emit(TaskStatusChanged(
                   timestamp=self._clock.now(), run_id=run_id,
                   event_type="task_status_changed", task_id=task_id,
                   old_status=old_status, new_status=result.new_status
               ))
           return result
       
       def submit_for_verification(self, run_id: str, task_id: str) -> TransitionResult:
           """Submit task for verification (builder done)."""
           task = self._state.get_task(run_id, task_id)
           old_status = task.status
           
           result = transition_to_verifying(task)
           
           if result.success:
               self._state.update_run(self._state.get_run(run_id))
               self._emitter.emit(TaskStatusChanged(
                   timestamp=self._clock.now(), run_id=run_id,
                   event_type="task_status_changed", task_id=task_id,
                   old_status=old_status, new_status=result.new_status
               ))
           return result
       
       def complete_verification(self, run_id: str, task_id: str) -> TransitionResult:
           """Complete verification phase."""
           task = self._state.get_task(run_id, task_id)
           old_status = task.status
           
           result = transition_after_verification(task, self._clock.now())
           
           self._state.update_run(self._state.get_run(run_id))
           self._emitter.emit(TaskStatusChanged(
               timestamp=self._clock.now(), run_id=run_id,
               event_type="task_status_changed", task_id=task_id,
               old_status=old_status, new_status=result.new_status
           ))
           return result
   ```

3. Create unit tests with mocked dependencies
4. Create integration test that runs a task through full lifecycle

### Verification

#### Unit Tests
```bash
uv run pytest tests/unit/test_workflow_engine.py -v
```

#### Integration Tests
```bash
uv run pytest tests/integration/test_workflow_execution.py -v
```

**Integration test scenario:**
1. Create run from routine
2. Start run
3. Start task (PENDING → BUILDING)
4. Update checklist items to DONE
5. Submit for verification (BUILDING → VERIFYING)
6. Set grade on each individual requirement (per checklist item)
7. Complete verification — evaluate_grades checks each item by priority (VERIFYING → COMPLETED)
8. Verify final state

### Definition of Done
- [ ] WorkflowEngine class works
- [ ] Events emitted on transitions
- [ ] Dependencies are injected
- [ ] Full lifecycle integration test passes

---

## Slice 2.5: Prompt Generation

### Goal
Generate prompts for builder and verifier personas from task configuration.

### Prerequisites
- Slice 1.2 complete (config models)

### Deliverables

```
src/orchestrator/workflow/prompts.py
tests/unit/test_prompt_generation.py
```

### Architecture Constraints

1. **Fresh context per phase** - Builder prompt != Verifier prompt. No shared history.
2. **Templates are data** - Prompt templates can be overridden via config
3. **Model overrides applied** - If task has model_overrides for current model, use them
4. **Pure functions** - No I/O in prompt generation
5. **Submission template is for prompt generation** - `SubmissionTemplateConfig` (`grade_scale`,
   `require_reason_if_below`, `require_remediation_if_below`) generates instructions for the LLM
   verifier telling it what grade scale to use and when to provide reasons/remediation. These are
   complementary to `evaluate_grades()` which enforces priority-based thresholds programmatically.
   The verifier grades each requirement individually; the template tells it how to format those grades.

### Implementation Steps

1. Create `src/orchestrator/workflow/prompts.py`:
   ```python
   from dataclasses import dataclass
   from orchestrator.config.models import TaskConfig
   from orchestrator.state.models import TaskState, Attempt
   
   @dataclass
   class BuilderPrompt:
       system: str
       user: str
       task_context: str
       requirements: list[str]
       previous_feedback: str | None = None
   
   @dataclass
   class VerifierPrompt:
       system: str
       user: str
       requirements: list[str]
       rubric: list[str]
       submission_instructions: str
   
   def get_task_context(task_config: TaskConfig, model: str | None = None) -> str:
       """Get task context, applying model overrides if present."""
       if model and task_config.model_overrides:
           override = task_config.model_overrides.get(model, {})
           if "task_context" in override:
               return override["task_context"]
       return task_config.task_context
   
   def generate_builder_prompt(
       task_config: TaskConfig,
       task_state: TaskState,
       config: dict,  # Run config for variable substitution
       model: str | None = None,
   ) -> BuilderPrompt:
       """Generate builder prompt with fresh context."""
       task_context = get_task_context(task_config, model)
       
       # Simple variable substitution
       for key, value in config.items():
           task_context = task_context.replace(f"{{{{{key}}}}}", str(value))
       
       requirements = [f"- {req.desc}" for req in task_config.requirements]
       
       # Get previous feedback if this is a revision
       previous_feedback = None
       if task_state.attempts:
           last_attempt = task_state.attempts[-1]
           if last_attempt.verifier_comment:
               previous_feedback = last_attempt.verifier_comment
       
       system = """You are a skilled software developer. Complete the task according to the requirements.
   Mark each requirement as done when completed using the provided tools."""
       
       user = f"""## Task
   {task_context}
   
   ## Requirements
   {chr(10).join(requirements)}"""
       
       if previous_feedback:
           user += f"""
   
   ## Previous Feedback (Revision Required)
   {previous_feedback}
   
   Address the feedback above while maintaining all other requirements."""
       
       return BuilderPrompt(
           system=system,
           user=user,
           task_context=task_context,
           requirements=requirements,
           previous_feedback=previous_feedback,
       )
   
   def generate_verifier_prompt(
       task_config: TaskConfig,
       task_state: TaskState,
   ) -> VerifierPrompt:
       """Generate verifier prompt with fresh context.

       Note: No `config` param -- the verifier prompt does not perform variable
       substitution (that is a builder concern).

       The submission_template generates LLM instructions for per-requirement grading.
       Each requirement is graded individually. The template fields tell the LLM:
       - grade_scale: what grades to use (e.g. A-F)
       - require_reason_if_below: when to include a reason (maps to grade_reason)
       - require_remediation_if_below: when to suggest fixes

       Actual pass/fail enforcement happens later in evaluate_grades() using
       priority-based thresholds (CRITICAL=A, EXPECTED=B, NICE=none).
       """
       requirements = [f"- {req.desc}" for req in task_config.requirements]
       rubric = [f"- {item.text}" for item in task_config.verifier.rubric]

       template = task_config.verifier.submission_template
       submission_instructions = f"""Grade each requirement individually using scale: {', '.join(template.grade_scale)}
   Provide reason if grade below {template.require_reason_if_below}.
   Provide remediation if grade below {template.require_remediation_if_below}."""
       
       system = """You are a code reviewer. Evaluate the work against requirements.
   Be thorough but fair. Provide actionable feedback for any issues."""
       
       user = f"""## Requirements to Verify
   {chr(10).join(requirements)}
   
   ## Rubric Questions
   {chr(10).join(rubric) if rubric else "Evaluate based on requirements only."}
   
   ## Submission Instructions
   {submission_instructions}"""
       
       return VerifierPrompt(
           system=system,
           user=user,
           requirements=requirements,
           rubric=rubric,
           submission_instructions=submission_instructions,
       )
   ```

2. Create tests for:
   - Basic prompt generation
   - Variable substitution
   - Model overrides applied
   - Previous feedback included in revisions
   - Rubric inclusion

### Verification

#### Unit Tests
```bash
uv run pytest tests/unit/test_prompt_generation.py -v
```

### Definition of Done
- [ ] Builder prompt generation works
- [ ] Verifier prompt generation works
- [ ] Model overrides applied
- [ ] Variable substitution works
- [ ] Previous feedback included for revisions

---

## Phase 2 Milestone Verification

After completing all Phase 2 slices:

```bash
# All tests pass
uv run pytest tests/ -v

# Type checking passes
uv run pyright src/

# Manual verification: Complete task lifecycle
uv run python -c "
from pathlib import Path
from datetime import datetime
from orchestrator.routines.loader import load_routine_from_path
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow.engine import WorkflowEngine
from orchestrator.config.enums import TaskStatus, ChecklistStatus

# Setup
routine = load_routine_from_path(Path('tests/fixtures/routines/valid_simple.yaml'))
run = create_run_from_routine(routine, 'test-project')
manager = SessionStateManager()
manager.add_run(run)
engine = WorkflowEngine(manager)

# Start
engine.start_run(run.id)
task = run.steps[0].tasks[0]

# Build
result = engine.start_task(run.id, task.id)
print(f'Started task: {result.new_status}')

# Mark requirements done
for item in task.checklist:
    item.status = ChecklistStatus.DONE

# Submit for verification
result = engine.submit_for_verification(run.id, task.id)
print(f'Submitted: {result.new_status}, gate passed: {result.gate_result.passed}')

# Grade each requirement individually (per checklist item)
for item in task.checklist:
    item.grade = 'A'

# Complete verification — evaluate_grades checks each item by priority
result = engine.complete_verification(run.id, task.id)
print(f'Completed: {result.new_status}')

assert task.status == TaskStatus.COMPLETED
print('SUCCESS: Full lifecycle complete!')
"
```

If this works, Phase 2 is complete. Proceed to Phase 3.
