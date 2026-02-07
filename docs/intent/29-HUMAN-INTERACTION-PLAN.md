# Implementation Slices: Phase 9 - Human Interaction

**Goal:** Implement human interaction patterns: clarification requests (questions) and approval gates.

**End state:** Agents can request clarification from humans; workflows can require human approval at step boundaries; all interactions are persisted and exposed via API, CLI, and UI.

**Prerequisites:** Phase 5 (Agent Integration) complete. MCP tools operational. Workflow engine functional.

---

## Overview

This phase implements two human interaction patterns from the design document (`28-HUMAN-INTERACTION-DESIGN.md`):

1. **Clarification (Question Answering)** - Builder requests human input during execution
2. **Approval Gate** - Human reviews and approves/rejects after verification

Both patterns use a new task status `PENDING_USER_ACTION` and produce persistent artifacts.

---

## Architecture Constraints

1. **Task-level scope** - All human interactions are scoped to tasks, not steps (per design doc).
2. **Gate sequencing** - When a step has `human_approval`, the gate sequence is: auto_verify THEN human_approval.
3. **Artifact persistence** - Clarifications written to markdown files in worktree with variable substitution.
4. **No YOLO mode** - Human gates cannot be bypassed.
5. **Event sourcing** - All status changes emit events for WebSocket broadcast and recovery.
6. **Pure functions** - Clarification formatting and artifact generation are pure functions.
7. **No mocking in tests** - Use real objects with dependency injection.

---

## Slice 9.1: Status Enum Extension

### Goal
Add `PENDING_USER_ACTION` status to the task status enum.

### Deliverables

**Files to Modify:**
```
src/orchestrator/config/enums.py       # Add PENDING_USER_ACTION to TaskStatus
src/orchestrator/workflow/transitions.py  # Update VALID_TRANSITIONS map
```

### Implementation

#### enums.py Changes

```python
class TaskStatus(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    PENDING_USER_ACTION = "pending_user_action"  # NEW
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
```

#### transitions.py Changes

Update `VALID_TRANSITIONS`:

```python
VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.BUILDING},
    TaskStatus.BUILDING: {TaskStatus.VERIFYING, TaskStatus.PENDING_USER_ACTION, TaskStatus.FAILED},
    TaskStatus.PENDING_USER_ACTION: {TaskStatus.BUILDING, TaskStatus.VERIFYING, TaskStatus.COMPLETED},
    TaskStatus.VERIFYING: {TaskStatus.COMPLETED, TaskStatus.BUILDING, TaskStatus.PENDING_USER_ACTION, TaskStatus.FAILED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
}
```

### Verification

```bash
uv run pytest tests/unit/test_task_transitions.py -v
uv run pyright src/orchestrator/config/enums.py
```

### Definition of Done
- [ ] `PENDING_USER_ACTION` added to TaskStatus enum
- [ ] VALID_TRANSITIONS updated with new status paths
- [ ] Existing tests pass
- [ ] Type checking passes

---

## Slice 9.2: Clarification Data Models

### Goal
Create Pydantic models for clarification questions, answers, requests, and responses.

### Deliverables

**Files to Create:**
```
src/orchestrator/workflow/clarifications.py   # Clarification models and artifact helpers
```

**Files to Modify:**
```
src/orchestrator/state/models.py              # Add clarification fields to TaskState
src/orchestrator/config/models.py             # Add clarification config to GateConfig
```

### Implementation

#### clarifications.py (New File)

```python
"""Clarification models and artifact generation (pure functions)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ClarificationQuestion(BaseModel):
    """A question from the builder needing human input."""
    id: str
    question: str
    context: str
    options: list[str]  # Multi-choice options (2-4)


class ClarificationAnswer(BaseModel):
    """Human's answer to a clarification question."""
    question_id: str
    selected_option: str | None = None  # If chose from options
    free_text: str | None = None  # If provided custom answer
    answered_by: str
    answered_at: datetime


class ClarificationRequest(BaseModel):
    """A set of questions from builder needing answers."""
    id: str
    run_id: str
    task_id: str
    attempt_num: int
    questions: list[ClarificationQuestion]
    created_at: datetime
    responded_at: datetime | None = None


class ClarificationResponse(BaseModel):
    """Human's answers to a clarification request."""
    request_id: str
    answers: list[ClarificationAnswer]
    responded_at: datetime


def format_clarification_artifact(
    request: ClarificationRequest,
    response: ClarificationResponse,
    step_id: str,
    clarification_number: int,
) -> str:
    """Format clarification Q&A as markdown section for artifact file.

    Pure function - no I/O.
    """
    lines = [
        f"## Clarification {clarification_number} (Step {step_id}, Attempt {request.attempt_num})",
        f"**Requested:** {request.created_at.isoformat()}",
        "",
    ]

    for i, q in enumerate(request.questions, 1):
        answer = next((a for a in response.answers if a.question_id == q.id), None)

        lines.append(f"### Q{i}: {q.question}")
        lines.append(f"**Context:** {q.context}")
        lines.append("**Options:**")
        for j, opt in enumerate(q.options, 1):
            lines.append(f"{j}. {opt}")
        lines.append("")

        if answer:
            if answer.free_text:
                lines.append(f"**Answer:** (custom) {answer.free_text}")
            elif answer.selected_option:
                lines.append(f"**Answer:** {answer.selected_option}")
            lines.append(f"**Answered by:** {answer.answered_by}")
            lines.append(f"**Answered at:** {answer.answered_at.isoformat()}")
        lines.append("")

    return "\n".join(lines)


def build_artifact_header() -> str:
    """Build the header for a new clarifications artifact file."""
    return """# Clarifications Log
<!-- Auto-generated by Orchestrator. Referenced in build/verify phases. -->

"""


def resolve_artifact_path(template: str, config: dict[str, Any]) -> str:
    """Resolve {{variable}} placeholders in artifact path template.

    Pure function - no I/O.
    """
    result = template
    for key, value in config.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result
```

#### state/models.py Changes

Add to `TaskState`:

```python
class TaskState(BaseModel):
    # ... existing fields ...
    pending_action_type: str | None = None  # "clarification" | "approval"
    pending_clarification_id: str | None = None
```

#### config/models.py Changes

Update `GateConfig`:

```python
class GateConfig(BaseModel):
    type: GateType
    # For human_approval
    approval_prompt: str | None = None
    require_comment: bool = False
    summary_artifact: str | None = None  # NEW: Path for summary artifact
    # For grade_threshold
    critical_threshold: str = "A"
    expected_threshold: str = "B"


class ClarificationsConfig(BaseModel):
    """Clarifications configuration for a routine."""
    artifact_path: str = "docs/clarifications.md"


class RoutineConfig(BaseModel):
    # ... existing fields ...
    clarifications: ClarificationsConfig | None = None  # NEW
```

### Tests

```
tests/unit/test_clarifications.py
```

Test cases:
- `format_clarification_artifact` produces valid markdown
- `resolve_artifact_path` substitutes variables correctly
- `build_artifact_header` returns expected header

### Definition of Done
- [ ] ClarificationQuestion, ClarificationAnswer, ClarificationRequest, ClarificationResponse models created
- [ ] Pure functions for artifact formatting implemented
- [ ] TaskState extended with pending_action_type and pending_clarification_id
- [ ] GateConfig extended with summary_artifact
- [ ] RoutineConfig extended with clarifications config
- [ ] Unit tests pass

---

## Slice 9.3: Database Schema for Clarifications

### Goal
Create database tables for persisting clarification requests and responses.

### Deliverables

**Files to Create:**
```
src/orchestrator/db/migrations/versions/XXX_add_clarifications.py
```

**Files to Modify:**
```
src/orchestrator/db/models.py           # Add ClarificationRequestModel, ClarificationResponseModel
src/orchestrator/db/repositories.py     # Add clarification repository methods
```

### Implementation

#### db/models.py Additions

```python
class ClarificationRequestModel(Base):
    __tablename__ = "clarification_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    attempt_num: Mapped[int] = mapped_column(Integer, nullable=False)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    run: Mapped["RunModel"] = relationship("RunModel")
    response: Mapped["ClarificationResponseModel | None"] = relationship(
        "ClarificationResponseModel",
        back_populates="request",
        uselist=False,
    )


class ClarificationResponseModel(Base):
    __tablename__ = "clarification_responses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String, ForeignKey("clarification_requests.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )
    answers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    responded_by: Mapped[str] = mapped_column(String, nullable=False)
    responded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    request: Mapped["ClarificationRequestModel"] = relationship(
        "ClarificationRequestModel", back_populates="response"
    )
```

Also add to TaskModel:
```python
class TaskModel(Base):
    # ... existing fields ...
    pending_action_type: Mapped[str | None] = mapped_column(String, nullable=True)
    pending_clarification_id: Mapped[str | None] = mapped_column(String, nullable=True)
```

#### repositories.py Additions

Add to `RunRepository`:

```python
async def create_clarification_request(
    self, request: ClarificationRequest
) -> ClarificationRequest:
    """Create a new clarification request."""
    ...

async def get_clarification_request(
    self, request_id: str
) -> ClarificationRequest | None:
    """Get a clarification request by ID."""
    ...

async def get_pending_clarification(
    self, run_id: str, task_id: str
) -> ClarificationRequest | None:
    """Get the pending clarification request for a task."""
    ...

async def save_clarification_response(
    self, response: ClarificationResponse
) -> None:
    """Save a clarification response and mark request as responded."""
    ...
```

### Migration

Create migration file `XXX_add_clarifications.py`:
- Create `clarification_requests` table
- Create `clarification_responses` table
- Add `pending_action_type` and `pending_clarification_id` to `tasks` table

### Tests

```
tests/integration/test_clarification_repository.py
```

### Definition of Done
- [ ] ClarificationRequestModel and ClarificationResponseModel ORM models created
- [ ] TaskModel extended with pending_action_type fields
- [ ] Migration created and runs successfully
- [ ] Repository methods implemented
- [ ] Integration tests pass

---

## Slice 9.4: Workflow Events for Human Interaction

### Goal
Add event types for clarification and approval actions.

### Deliverables

**Files to Modify:**
```
src/orchestrator/workflow/events.py    # Add clarification and approval events
```

### Implementation

Add to `events.py`:

```python
@dataclass
class ClarificationRequested(WorkflowEvent):
    """Emitted when builder requests clarification."""
    task_id: str = ""
    request_id: str = ""
    question_count: int = 0


@dataclass
class ClarificationResponded(WorkflowEvent):
    """Emitted when human answers clarification questions."""
    task_id: str = ""
    request_id: str = ""


@dataclass
class ApprovalRequested(WorkflowEvent):
    """Emitted when task awaits human approval."""
    task_id: str = ""
    step_id: str = ""
    summary_artifact: str | None = None


@dataclass
class ApprovalDecision(WorkflowEvent):
    """Emitted when human approves or rejects."""
    task_id: str = ""
    step_id: str = ""
    approved: bool = False
    comment: str | None = None
    decided_by: str = ""
```

### Tests

Verify events are correctly serializable for persistence and WebSocket broadcast.

### Definition of Done
- [ ] ClarificationRequested event defined
- [ ] ClarificationResponded event defined
- [ ] ApprovalRequested event defined
- [ ] ApprovalDecision event defined
- [ ] Events serialize/deserialize correctly

---

## Slice 9.5: Transition Functions for Human Interaction

### Goal
Implement pure transition functions for the new status flows.

### Deliverables

**Files to Modify:**
```
src/orchestrator/workflow/transitions.py  # Add human interaction transitions
```

### Implementation

Add new transition functions:

```python
def transition_to_pending_clarification(
    task: TaskState,
    request_id: str,
) -> TransitionResult:
    """Transition to PENDING_USER_ACTION for clarification.

    Valid from: BUILDING
    """
    if task.status != TaskStatus.BUILDING:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot request clarification from {task.status.value}",
        )

    task.status = TaskStatus.PENDING_USER_ACTION
    task.pending_action_type = "clarification"
    task.pending_clarification_id = request_id
    return TransitionResult(success=True, new_status=TaskStatus.PENDING_USER_ACTION)


def transition_from_clarification(
    task: TaskState,
) -> TransitionResult:
    """Resume from clarification - back to BUILDING.

    Valid from: PENDING_USER_ACTION (clarification)
    """
    if task.status != TaskStatus.PENDING_USER_ACTION:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot resume from {task.status.value}",
        )
    if task.pending_action_type != "clarification":
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Not a clarification action: {task.pending_action_type}",
        )

    task.status = TaskStatus.BUILDING
    task.pending_action_type = None
    task.pending_clarification_id = None
    return TransitionResult(success=True, new_status=TaskStatus.BUILDING)


def transition_to_pending_approval(
    task: TaskState,
) -> TransitionResult:
    """Transition to PENDING_USER_ACTION for approval.

    Valid from: VERIFYING (after auto_verify passes)
    """
    if task.status != TaskStatus.VERIFYING:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot await approval from {task.status.value}",
        )

    task.status = TaskStatus.PENDING_USER_ACTION
    task.pending_action_type = "approval"
    return TransitionResult(success=True, new_status=TaskStatus.PENDING_USER_ACTION)


def transition_from_approval(
    task: TaskState,
    approved: bool,
    now: datetime,
) -> TransitionResult:
    """Complete approval - to COMPLETED or back to BUILDING.

    Valid from: PENDING_USER_ACTION (approval)
    """
    if task.status != TaskStatus.PENDING_USER_ACTION:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot complete approval from {task.status.value}",
        )
    if task.pending_action_type != "approval":
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Not an approval action: {task.pending_action_type}",
        )

    task.pending_action_type = None

    if approved:
        task.status = TaskStatus.COMPLETED
        if task.attempts:
            task.attempts[-1].completed_at = now
            task.attempts[-1].outcome = "passed"
        return TransitionResult(success=True, new_status=TaskStatus.COMPLETED)
    else:
        # Rejection - back to building for revision
        if task.current_attempt >= task.max_attempts:
            task.status = TaskStatus.FAILED
            if task.attempts:
                task.attempts[-1].completed_at = now
                task.attempts[-1].outcome = "failed"
            return TransitionResult(
                success=True,
                new_status=TaskStatus.FAILED,
                error=f"Max attempts ({task.max_attempts}) reached",
            )

        # Start new attempt
        new_attempt_num = task.current_attempt + 1
        task.attempts.append(Attempt(attempt_num=new_attempt_num, started_at=now))
        task.current_attempt = new_attempt_num
        task.status = TaskStatus.BUILDING
        return TransitionResult(success=True, new_status=TaskStatus.BUILDING)
```

### Tests

```
tests/unit/test_human_interaction_transitions.py
```

Test cases:
- Valid transitions to/from PENDING_USER_ACTION
- Invalid transition attempts return errors
- Approval rejection increments attempt count
- Max attempts causes failure

### Definition of Done
- [ ] transition_to_pending_clarification implemented
- [ ] transition_from_clarification implemented
- [ ] transition_to_pending_approval implemented
- [ ] transition_from_approval implemented
- [ ] Unit tests cover all paths

---

## Slice 9.6: Workflow Service Integration

### Goal
Integrate human interaction with WorkflowService.

### Deliverables

**Files to Modify:**
```
src/orchestrator/workflow/service.py    # Add clarification and approval methods
```

### Implementation

Add to `WorkflowService`:

```python
async def request_clarification(
    self,
    run_id: str,
    task_id: str,
    questions: list[ClarificationQuestion],
) -> ClarificationRequest:
    """Request clarification from human.

    Transitions task to PENDING_USER_ACTION and creates ClarificationRequest.
    Emits ClarificationRequested event.
    """
    ...

async def respond_to_clarification(
    self,
    run_id: str,
    task_id: str,
    request_id: str,
    answers: list[ClarificationAnswer],
    responded_by: str,
) -> TransitionResult:
    """Submit answers to clarification request.

    Writes to artifact file, transitions task back to BUILDING.
    Emits ClarificationResponded event.
    """
    ...

async def get_pending_clarification(
    self,
    run_id: str,
    task_id: str,
) -> ClarificationRequest | None:
    """Get pending clarification request for a task."""
    ...

async def approve_task(
    self,
    run_id: str,
    task_id: str,
    approved_by: str,
    comment: str | None = None,
) -> TransitionResult:
    """Approve a task awaiting human approval.

    Transitions task to COMPLETED.
    Emits ApprovalDecision event.
    """
    ...

async def reject_task(
    self,
    run_id: str,
    task_id: str,
    rejected_by: str,
    reason: str | None = None,
) -> TransitionResult:
    """Reject a task awaiting human approval.

    Transitions task back to BUILDING for revision.
    Emits ApprovalDecision event.
    """
    ...

async def get_pending_actions(
    self,
    run_id: str,
) -> list[dict[str, Any]]:
    """Get all pending user actions for a run."""
    ...
```

### Artifact Writing

When responding to clarification, the service must:
1. Resolve artifact path using run config
2. Create file if not exists (with header)
3. Append formatted Q&A section
4. Use worktree path if available

### Gate Sequencing

Modify `complete_verification` to check for human_approval gate:
1. Run auto_verify (existing)
2. Evaluate grades (existing)
3. If step has `human_approval` gate AND grades pass:
   - Transition to PENDING_USER_ACTION (approval)
   - Emit ApprovalRequested event
4. Otherwise proceed as normal

### Tests

```
tests/integration/test_clarification_workflow.py
tests/integration/test_approval_workflow.py
```

### Definition of Done
- [ ] request_clarification creates request and transitions task
- [ ] respond_to_clarification writes artifact and resumes building
- [ ] approve_task completes task successfully
- [ ] reject_task returns to building
- [ ] Gate sequencing correct (auto_verify THEN human_approval)
- [ ] Events emitted correctly
- [ ] Integration tests pass

---

## Slice 9.7: API Endpoints for Clarifications

### Goal
Expose clarification operations via REST API.

### Deliverables

**Files to Create:**
```
src/orchestrator/api/routers/clarifications.py   # Clarification endpoints
src/orchestrator/api/schemas/clarifications.py   # API schemas
```

**Files to Modify:**
```
src/orchestrator/api/app.py                      # Register router
```

### Implementation

#### schemas/clarifications.py

```python
from datetime import datetime
from pydantic import BaseModel


class ClarificationQuestionSchema(BaseModel):
    id: str
    question: str
    context: str
    options: list[str]


class ClarificationAnswerSchema(BaseModel):
    question_id: str
    selected_option: str | None = None
    free_text: str | None = None


class CreateClarificationRequest(BaseModel):
    questions: list[ClarificationQuestionSchema]


class ClarificationRequestResponse(BaseModel):
    id: str
    run_id: str
    task_id: str
    attempt_num: int
    questions: list[ClarificationQuestionSchema]
    created_at: datetime
    responded_at: datetime | None


class RespondToClarificationRequest(BaseModel):
    answers: list[ClarificationAnswerSchema]


class PendingActionSchema(BaseModel):
    task_id: str
    step_id: str
    action_type: str  # "clarification" | "approval"
    clarification_request: ClarificationRequestResponse | None = None
    summary_artifact: str | None = None
    approval_prompt: str | None = None
```

#### routers/clarifications.py

```python
router = APIRouter(prefix="/api/runs", tags=["clarifications"])

@router.post("/{run_id}/tasks/{task_id}/clarifications")
async def create_clarification(
    run_id: str,
    task_id: str,
    request: CreateClarificationRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    user: Annotated[str, Depends(get_current_user)],
) -> ClarificationRequestResponse:
    """Builder submits questions needing answers."""
    ...

@router.get("/{run_id}/tasks/{task_id}/clarifications/pending")
async def get_pending_clarification(
    run_id: str,
    task_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> ClarificationRequestResponse | None:
    """Get pending clarification request for a task."""
    ...

@router.post("/{run_id}/tasks/{task_id}/clarifications/{request_id}/respond")
async def respond_to_clarification(
    run_id: str,
    task_id: str,
    request_id: str,
    request: RespondToClarificationRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    user: Annotated[str, Depends(get_current_user)],
) -> TransitionResponse:
    """Human submits answers to clarification questions."""
    ...

@router.get("/{run_id}/pending-actions")
async def get_pending_actions(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> list[PendingActionSchema]:
    """List all pending user actions for a run."""
    ...
```

### Tests

```
tests/integration/test_api_clarifications.py
```

### Definition of Done
- [ ] POST clarifications endpoint creates request
- [ ] GET pending clarification endpoint returns current request
- [ ] POST respond endpoint submits answers
- [ ] GET pending-actions endpoint lists all pending actions
- [ ] Integration tests pass

---

## Slice 9.8: API Endpoints for Approval

### Goal
Expose approval operations via REST API.

### Deliverables

**Files to Modify:**
```
src/orchestrator/api/routers/tasks.py          # Add approval endpoints
src/orchestrator/api/schemas/tasks.py          # Add approval schemas
```

### Implementation

#### schemas/tasks.py Additions

```python
class ApproveTaskRequest(BaseModel):
    comment: str | None = None


class RejectTaskRequest(BaseModel):
    reason: str | None = None
```

#### routers/tasks.py Additions

```python
@router.post("/{run_id}/tasks/{task_id}/approve", response_model=TransitionResponse)
async def approve_task(
    run_id: str,
    task_id: str,
    request: ApproveTaskRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    user: Annotated[str, Depends(get_current_user)],
) -> TransitionResponse:
    """Human approves task verification."""
    result = await service.approve_task(run_id, task_id, user, request.comment)
    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )


@router.post("/{run_id}/tasks/{task_id}/reject", response_model=TransitionResponse)
async def reject_task(
    run_id: str,
    task_id: str,
    request: RejectTaskRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    user: Annotated[str, Depends(get_current_user)],
) -> TransitionResponse:
    """Human rejects task verification."""
    result = await service.reject_task(run_id, task_id, user, request.reason)
    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )
```

### Tests

```
tests/integration/test_api_approval.py
```

### Definition of Done
- [ ] POST approve endpoint completes task
- [ ] POST reject endpoint returns to building
- [ ] Rejection with max attempts fails task
- [ ] Integration tests pass

---

## Slice 9.9: Extended Task/Step Summaries

### Goal
Add pending action information to API response schemas.

### Deliverables

**Files to Modify:**
```
src/orchestrator/api/schemas/runs.py           # Extend TaskSummary, StepSummary
src/orchestrator/api/routers/runs.py           # Populate new fields
```

### Implementation

#### schemas/runs.py Additions

```python
class TaskSummary(BaseModel):
    # ... existing fields ...
    pending_action_type: str | None = None  # "clarification" | "approval" | None
    pending_clarification_count: int | None = None


class StepSummary(BaseModel):
    # ... existing fields ...
    has_approval_gate: bool = False
    approval_status: str | None = None  # "pending" | "approved" | "rejected" | None
```

### Tests

Update existing API tests to verify new fields.

### Definition of Done
- [ ] TaskSummary includes pending_action_type
- [ ] TaskSummary includes pending_clarification_count
- [ ] StepSummary includes has_approval_gate
- [ ] StepSummary includes approval_status
- [ ] Existing tests updated and pass

---

## Slice 9.10: MCP Tool for Clarification

### Goal
Add MCP tool for agents to request clarification.

### Deliverables

**Files to Create:**
```
src/orchestrator/mcp/clarification_tools.py    # request_clarification tool
```

**Files to Modify:**
```
src/orchestrator/mcp/tools.py                  # Add to ORCHESTRATOR_TOOLS
```

### Implementation

#### clarification_tools.py

```python
CLARIFICATION_TOOL = {
    "name": "orchestrator_request_clarification",
    "description": (
        "Request clarification from the human. "
        "The task will pause until the human answers. "
        "Answers will be appended to the clarifications artifact file."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "The run ID"},
            "task_id": {"type": "string", "description": "The task ID"},
            "questions": {
                "type": "array",
                "description": "Questions needing answers",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "The question text"},
                        "context": {"type": "string", "description": "Why this clarification is needed"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "2-4 suggested answers (user can also provide custom)",
                            "minItems": 2,
                            "maxItems": 4,
                        },
                    },
                    "required": ["question", "context", "options"],
                },
            },
        },
        "required": ["run_id", "task_id", "questions"],
    },
}
```

#### tools.py Updates

Add to ORCHESTRATOR_TOOLS list and ToolHandler.handle method.

### Tests

```
tests/integration/test_mcp_clarification.py
```

### Definition of Done
- [ ] orchestrator_request_clarification tool defined
- [ ] ToolHandler dispatches to service method
- [ ] Tool call transitions task to PENDING_USER_ACTION
- [ ] Integration test passes

---

## Slice 9.11: Prompt Integration

### Goal
Add clarifications file path to builder/verifier prompts.

### Deliverables

**Files to Modify:**
```
src/orchestrator/workflow/prompts.py           # Add clarifications section
```

### Implementation

Update `generate_builder_prompt` and `generate_verifier_prompt` to include:

```python
def generate_builder_prompt(
    task_config: TaskConfig,
    task_state: TaskState,
    config: dict[str, Any],
    model: str | None = None,
    step_context: str | None = None,
    clarifications_path: str | None = None,  # NEW
) -> BuilderPrompt:
    # ... existing code ...

    # Add clarifications section if path provided
    clarifications_section = ""
    if clarifications_path:
        clarifications_section = f"""
## Clarifications

Previous clarifications from the human are recorded in:
  {clarifications_path}

Review this file for context on decisions made. If you need additional
clarification, use the request_clarification tool.
"""

    user = ""
    if resolved_step_context is not None:
        user += f"## Step Context\n{resolved_step_context}\n\n"

    if clarifications_section:
        user += clarifications_section + "\n"

    user += f"## Task\n{task_context}\n\n## Requirements\n" + "\n".join(requirements)
    # ... rest of existing code ...
```

### Tests

Update existing prompt tests.

### Definition of Done
- [ ] Builder prompt includes clarifications path when provided
- [ ] Verifier prompt includes clarifications path when provided
- [ ] Existing tests updated and pass

---

## Slice 9.12: CLI Approve Command

### Goal
Implement CLI command for handling pending user actions.

### Deliverables

**Files to Create:**
```
src/orchestrator/cli/approve.py               # runs approve command
```

**Files to Modify:**
```
src/orchestrator/cli/__init__.py              # Register command
```

### Implementation

#### approve.py

```python
"""CLI command for handling pending user actions."""

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt, Confirm

from orchestrator.api.client import OrchestratorClient


@click.command("approve")
@click.argument("run_id")
@click.option("--api-url", default="http://localhost:8000", help="API base URL")
def approve_command(run_id: str, api_url: str) -> None:
    """Handle pending user actions for a run.

    Interactively answers clarification questions and approves/rejects
    tasks awaiting human input.
    """
    console = Console()
    client = OrchestratorClient(api_url)

    # Get pending actions
    actions = client.get_pending_actions(run_id)

    if not actions:
        console.print("[green]No pending actions for this run.[/green]")
        return

    console.print(f"\nRun {run_id} has {len(actions)} pending action(s):\n")

    for action in actions:
        if action["action_type"] == "clarification":
            _handle_clarification(console, client, run_id, action)
        elif action["action_type"] == "approval":
            _handle_approval(console, client, run_id, action)


def _handle_clarification(
    console: Console,
    client: OrchestratorClient,
    run_id: str,
    action: dict,
) -> None:
    """Interactively answer clarification questions."""
    task_id = action["task_id"]
    request = action["clarification_request"]
    questions = request["questions"]

    console.print(f"\n[bold]Clarification Required[/bold] - Task {task_id}")
    console.print(f"Type: Clarification ({len(questions)} question(s))\n")
    console.print("-" * 60)

    answers = []
    for i, q in enumerate(questions, 1):
        console.print(f"\n[bold]Q{i}/{len(questions)}:[/bold] {q['question']}\n")
        console.print(f"[dim]Context: {q['context']}[/dim]\n")
        console.print("Options:")
        for j, opt in enumerate(q["options"], 1):
            console.print(f"  [{j}] {opt}")
        console.print("  [o] Other (provide custom answer)")

        while True:
            choice = Prompt.ask("\nYour choice")
            if choice == "o":
                free_text = Prompt.ask("Custom answer")
                answers.append({
                    "question_id": q["id"],
                    "free_text": free_text,
                })
                break
            elif choice.isdigit() and 1 <= int(choice) <= len(q["options"]):
                answers.append({
                    "question_id": q["id"],
                    "selected_option": q["options"][int(choice) - 1],
                })
                break
            else:
                console.print("[red]Invalid choice. Try again.[/red]")

    console.print("\n" + "-" * 60)
    console.print("\nSubmitting answers...")

    result = client.respond_to_clarification(
        run_id, task_id, request["id"], answers
    )

    if result["success"]:
        console.print("[green]Clarification submitted. Task continuing.[/green]")
    else:
        console.print(f"[red]Error: {result.get('error')}[/red]")


def _handle_approval(
    console: Console,
    client: OrchestratorClient,
    run_id: str,
    action: dict,
) -> None:
    """Interactively approve or reject task."""
    task_id = action["task_id"]

    console.print(f"\n[bold]Approval Required[/bold] - Task {task_id}")

    if action.get("summary_artifact"):
        console.print(f"\nSummary artifact: {action['summary_artifact']}")
        # Could read and display file content here

    if action.get("approval_prompt"):
        console.print(f"\n{action['approval_prompt']}")

    console.print()

    if Confirm.ask("Approve this task?"):
        comment = Prompt.ask("Comment (optional)", default="")
        result = client.approve_task(run_id, task_id, comment or None)
        if result["success"]:
            console.print("[green]Task approved.[/green]")
        else:
            console.print(f"[red]Error: {result.get('error')}[/red]")
    else:
        reason = Prompt.ask("Reason for rejection (optional)", default="")
        result = client.reject_task(run_id, task_id, reason or None)
        if result["success"]:
            console.print("[yellow]Task rejected. Returning to builder.[/yellow]")
        else:
            console.print(f"[red]Error: {result.get('error')}[/red]")
```

### Tests

```
tests/integration/test_cli_approve.py
```

### Definition of Done
- [ ] `orchestrator runs approve <run_id>` command works
- [ ] Clarification questions presented interactively
- [ ] Approval/rejection prompts work correctly
- [ ] Integration tests pass

---

## Slice 9.13: UI TypeScript Types

### Goal
Add TypeScript types for clarification and approval.

### Deliverables

**Files to Create:**
```
ui/src/types/clarifications.ts
```

**Files to Modify:**
```
ui/src/types/index.ts                          # Export new types
ui/src/types/enums.ts                          # Add PENDING_USER_ACTION
```

### Implementation

#### types/clarifications.ts

```typescript
export interface ClarificationQuestion {
  id: string;
  question: string;
  context: string;
  options: string[];
}

export interface ClarificationAnswer {
  question_id: string;
  selected_option: string | null;
  free_text: string | null;
}

export interface ClarificationRequest {
  id: string;
  run_id: string;
  task_id: string;
  attempt_num: number;
  questions: ClarificationQuestion[];
  created_at: string;
  responded_at: string | null;
}

export interface RespondToClarificationRequest {
  answers: ClarificationAnswer[];
}

export interface PendingAction {
  task_id: string;
  step_id: string;
  action_type: 'clarification' | 'approval';
  clarification_request: ClarificationRequest | null;
  summary_artifact: string | null;
  approval_prompt: string | null;
}

export interface ApproveTaskRequest {
  comment?: string;
}

export interface RejectTaskRequest {
  reason?: string;
}
```

#### types/enums.ts Update

```typescript
export type TaskStatus =
  | 'pending'
  | 'building'
  | 'pending_user_action'  // NEW
  | 'verifying'
  | 'completed'
  | 'failed';
```

### Definition of Done
- [ ] ClarificationQuestion type defined
- [ ] ClarificationAnswer type defined
- [ ] ClarificationRequest type defined
- [ ] PendingAction type defined
- [ ] TaskStatus includes pending_user_action
- [ ] Types exported from index.ts

---

## Slice 9.14: UI API Client Extensions

### Goal
Add API methods for clarification and approval.

### Deliverables

**Files to Create:**
```
ui/src/api/clarifications.ts
```

**Files to Modify:**
```
ui/src/api/client.ts                           # Add clarification/approval methods
```

### Implementation

#### api/client.ts Additions

```typescript
export const api = {
  // ... existing methods ...

  getPendingActions(runId: string): Promise<PendingAction[]> {
    return fetchApi('/api/runs/' + runId + '/pending-actions');
  },

  getPendingClarification(runId: string, taskId: string): Promise<ClarificationRequest | null> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/clarifications/pending');
  },

  respondToClarification(
    runId: string,
    taskId: string,
    requestId: string,
    data: RespondToClarificationRequest
  ): Promise<TransitionResponse> {
    return fetchApi(
      '/api/runs/' + runId + '/tasks/' + taskId + '/clarifications/' + requestId + '/respond',
      { method: 'POST', body: JSON.stringify(data) }
    );
  },

  approveTask(runId: string, taskId: string, data: ApproveTaskRequest): Promise<TransitionResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/approve', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  rejectTask(runId: string, taskId: string, data: RejectTaskRequest): Promise<TransitionResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/reject', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
};
```

### Definition of Done
- [ ] getPendingActions method added
- [ ] getPendingClarification method added
- [ ] respondToClarification method added
- [ ] approveTask method added
- [ ] rejectTask method added

---

## Slice 9.15: UI Hooks for Human Interaction

### Goal
Create React hooks for clarification and approval.

### Deliverables

**Files to Create:**
```
ui/src/hooks/useClarifications.ts
ui/src/hooks/useApproval.ts
ui/src/hooks/usePendingActions.ts
```

### Implementation

#### hooks/useClarifications.ts

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { ClarificationAnswer } from '../types';

export function usePendingClarification(runId: string, taskId: string) {
  return useQuery({
    queryKey: ['clarification', runId, taskId],
    queryFn: () => api.getPendingClarification(runId, taskId),
    enabled: !!runId && !!taskId,
  });
}

export function useRespondToClarification(runId: string, taskId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ requestId, answers }: { requestId: string; answers: ClarificationAnswer[] }) =>
      api.respondToClarification(runId, taskId, requestId, { answers }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
      queryClient.invalidateQueries({ queryKey: ['clarification', runId, taskId] });
      queryClient.invalidateQueries({ queryKey: ['pendingActions', runId] });
    },
  });
}
```

#### hooks/useApproval.ts

```typescript
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

export function useApproveTask(runId: string, taskId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comment?: string) => api.approveTask(runId, taskId, { comment }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
      queryClient.invalidateQueries({ queryKey: ['pendingActions', runId] });
    },
  });
}

export function useRejectTask(runId: string, taskId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (reason?: string) => api.rejectTask(runId, taskId, { reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
      queryClient.invalidateQueries({ queryKey: ['pendingActions', runId] });
    },
  });
}
```

#### hooks/usePendingActions.ts

```typescript
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

export function usePendingActions(runId: string) {
  return useQuery({
    queryKey: ['pendingActions', runId],
    queryFn: () => api.getPendingActions(runId),
    enabled: !!runId,
    refetchInterval: 5000,  // Poll for new actions
  });
}
```

### Definition of Done
- [ ] usePendingClarification hook implemented
- [ ] useRespondToClarification hook implemented
- [ ] useApproveTask hook implemented
- [ ] useRejectTask hook implemented
- [ ] usePendingActions hook implemented

---

## Slice 9.16: UI Clarification Modal

### Goal
Create modal component for answering clarification questions.

### Deliverables

**Files to Create:**
```
ui/src/components/detail/ClarificationModal.tsx
ui/src/components/detail/QuestionCard.tsx
```

### Implementation

#### QuestionCard.tsx

```typescript
interface QuestionCardProps {
  question: ClarificationQuestion;
  answer: ClarificationAnswer | null;
  onAnswer: (answer: ClarificationAnswer) => void;
  expanded: boolean;
  onToggle: () => void;
}

export function QuestionCard({
  question,
  answer,
  onAnswer,
  expanded,
  onToggle,
}: QuestionCardProps) {
  // Render question with options and free text input
  // Support expand/collapse
  // Call onAnswer when selection made
}
```

#### ClarificationModal.tsx

```typescript
interface ClarificationModalProps {
  runId: string;
  taskId: string;
  request: ClarificationRequest;
  onClose: () => void;
  onSubmitted: () => void;
}

export function ClarificationModal({
  runId,
  taskId,
  request,
  onClose,
  onSubmitted,
}: ClarificationModalProps) {
  const [answers, setAnswers] = useState<Map<string, ClarificationAnswer>>(new Map());
  const [mode, setMode] = useState<'one-at-a-time' | 'all-at-once'>('one-at-a-time');
  const [currentIndex, setCurrentIndex] = useState(0);

  const respondMutation = useRespondToClarification(runId, taskId);

  // Modal with:
  // - Mode toggle (one-at-a-time / all-at-once)
  // - Question cards with expand/collapse
  // - Submit button (enabled when all answered)
}
```

### Definition of Done
- [ ] QuestionCard renders question with options
- [ ] ClarificationModal manages state for all questions
- [ ] Mode toggle works (one-at-a-time / all-at-once)
- [ ] Submit sends answers to API
- [ ] Modal closes on success

---

## Slice 9.17: UI Approval Modal

### Goal
Create modal component for approving/rejecting tasks.

### Deliverables

**Files to Create:**
```
ui/src/components/detail/ApprovalModal.tsx
```

### Implementation

```typescript
interface ApprovalModalProps {
  runId: string;
  taskId: string;
  summaryArtifact: string | null;
  approvalPrompt: string | null;
  requireComment: boolean;
  onClose: () => void;
  onDecision: () => void;
}

export function ApprovalModal({
  runId,
  taskId,
  summaryArtifact,
  approvalPrompt,
  requireComment,
  onClose,
  onDecision,
}: ApprovalModalProps) {
  const [comment, setComment] = useState('');
  const approveMutation = useApproveTask(runId, taskId);
  const rejectMutation = useRejectTask(runId, taskId);

  // Modal with:
  // - Summary artifact rendered as markdown (if available)
  // - Approval prompt text
  // - Comment input (required for rejection if requireComment)
  // - Approve / Reject buttons
}
```

### Definition of Done
- [ ] ApprovalModal renders summary as markdown
- [ ] Comment field works
- [ ] Approve button completes task
- [ ] Reject button returns to building
- [ ] Modal closes on success

---

## Slice 9.18: UI Dashboard Integration

### Goal
Add pending action indicators to dashboard.

### Deliverables

**Files to Create:**
```
ui/src/components/dashboard/PendingActionsBadge.tsx
```

**Files to Modify:**
```
ui/src/components/dashboard/RunCard.tsx        # Add badge
ui/src/components/dashboard/RunFilters.tsx     # Add "Needs Input" filter
```

### Implementation

#### PendingActionsBadge.tsx

```typescript
interface PendingActionsBadgeProps {
  count: number;
}

export function PendingActionsBadge({ count }: PendingActionsBadgeProps) {
  if (count === 0) return null;

  return (
    <span className="inline-flex items-center rounded-full bg-yellow-100 px-2.5 py-0.5 text-xs font-medium text-yellow-800">
      {count} pending
    </span>
  );
}
```

#### RunCard.tsx Changes

Add badge showing pending action count from task summaries.

#### RunFilters.tsx Changes

Add "Needs Input" filter option that shows runs with any task in PENDING_USER_ACTION status.

### Definition of Done
- [ ] PendingActionsBadge component created
- [ ] RunCard shows badge when actions pending
- [ ] "Needs Input" filter works in dashboard

---

## Slice 9.19: Run Detail Integration

### Goal
Integrate clarification and approval modals into RunDetail page.

### Deliverables

**Files to Modify:**
```
ui/src/pages/RunDetail.tsx                     # Open modals when clicking pending tasks
ui/src/components/detail/TaskCard.tsx          # Show pending action indicator
```

### Implementation

#### TaskCard.tsx Changes

- Show visual indicator for PENDING_USER_ACTION status
- Different icons for clarification vs approval
- Click handler opens appropriate modal

#### RunDetail.tsx Changes

- Track which modal is open (clarification/approval + task)
- Pass pending action data to modals
- Refresh data after modal closes

### Definition of Done
- [ ] TaskCard shows pending action indicator
- [ ] Clicking opens ClarificationModal or ApprovalModal
- [ ] Modals close and refresh data on completion
- [ ] WebSocket events update UI in real-time

---

## Slice 9.20: Testing and Polish

### Goal
Complete test coverage and polish implementation.

### Deliverables

**Unit Tests:**
```
tests/unit/test_clarifications.py
tests/unit/test_human_interaction_transitions.py
tests/unit/test_clarification_artifacts.py
```

**Integration Tests:**
```
tests/integration/test_clarification_workflow.py
tests/integration/test_approval_workflow.py
tests/integration/test_api_clarifications.py
tests/integration/test_api_approval.py
tests/integration/test_mcp_clarification.py
tests/integration/test_cli_approve.py
```

**E2E Tests:**
```
tests/e2e/test_clarification_e2e.py
tests/e2e/test_approval_e2e.py
```

### Test Scenarios

1. **Clarification Flow**
   - Agent requests clarification during build
   - Task transitions to PENDING_USER_ACTION
   - Human answers questions via API/CLI/UI
   - Answers written to artifact file
   - Task resumes building

2. **Approval Flow**
   - Task completes verification with auto_verify pass
   - Human approval gate triggers PENDING_USER_ACTION
   - Human approves -> task COMPLETED
   - Human rejects -> task back to BUILDING (new attempt)

3. **Gate Sequencing**
   - Step with both auto_verify and human_approval
   - auto_verify runs first
   - Only on auto_verify pass, human_approval gate triggers

4. **Edge Cases**
   - Max attempts reached on rejection
   - Multiple clarifications in one run
   - Clarification during revision attempt
   - WebSocket events for status changes

### Definition of Done
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] E2E tests cover main flows
- [ ] Test coverage > 80% for new code
- [ ] No type errors
- [ ] Linting passes

---

## Phase 9 Milestone Verification

```bash
# All tests pass
uv run pytest tests/ -v

# Type checking
uv run pyright

# Linting
uv run ruff check .

# Manual verification - Clarification flow
uv run python -c "
import asyncio
from orchestrator.workflow.clarifications import (
    ClarificationQuestion,
    format_clarification_artifact,
    resolve_artifact_path,
)

# Test artifact path resolution
path = resolve_artifact_path('docs/{{feature}}/clarifications.md', {'feature': 'auth'})
assert path == 'docs/auth/clarifications.md', f'Got: {path}'
print('SUCCESS: Artifact path resolution works')

# Test question format
q = ClarificationQuestion(
    id='q1',
    question='Which auth method?',
    context='Requirements unclear',
    options=['OAuth2', 'Password', 'Both'],
)
print(f'SUCCESS: Question model works: {q.question}')
"

# Manual verification - API endpoints
uv run orchestrator serve &
sleep 2

# Test pending actions endpoint
curl -s http://localhost:8000/api/runs/test-run/pending-actions | jq .

# Stop server
pkill -f "orchestrator serve"

# UI build
cd ui && npm run build

echo "Phase 9 verification complete!"
```

---

## Dependency Graph

```
9.1 Status Enum
 |
 v
9.2 Clarification Models ------> 9.3 Database Schema
 |                                      |
 v                                      v
9.4 Events <----------------------- 9.5 Transitions
 |                                      |
 +-----------+-------------+------------+
             |             |
             v             v
          9.6 Workflow Service
             |
    +--------+--------+--------+
    |        |        |        |
    v        v        v        v
  9.7 API  9.8 API  9.10 MCP  9.11 Prompts
  Clarif.  Approval
    |        |        |
    v        v        v
  9.9 Summaries Extension
    |
    v
  9.12 CLI Approve
    |
    v
  9.13 TypeScript Types
    |
    v
  9.14 API Client
    |
    v
  9.15 Hooks
    |
    +--------+--------+
    |        |        |
    v        v        v
  9.16     9.17     9.18
  Modal    Modal    Dashboard
    |        |        |
    +--------+--------+
             |
             v
          9.19 RunDetail
             |
             v
          9.20 Testing
```

---

## Summary of Files

### Files to Create

| File | Purpose |
|------|---------|
| `src/orchestrator/workflow/clarifications.py` | Clarification models and artifact helpers |
| `src/orchestrator/api/routers/clarifications.py` | Clarification API endpoints |
| `src/orchestrator/api/schemas/clarifications.py` | API request/response schemas |
| `src/orchestrator/db/migrations/versions/XXX_add_clarifications.py` | Database migration |
| `src/orchestrator/mcp/clarification_tools.py` | MCP tool for requesting clarification |
| `src/orchestrator/cli/approve.py` | CLI command for pending actions |
| `ui/src/types/clarifications.ts` | TypeScript types |
| `ui/src/api/clarifications.ts` | API client extensions |
| `ui/src/hooks/useClarifications.ts` | React hooks for clarification |
| `ui/src/hooks/useApproval.ts` | React hooks for approval |
| `ui/src/hooks/usePendingActions.ts` | React hook for pending actions |
| `ui/src/components/detail/ClarificationModal.tsx` | Clarification UI modal |
| `ui/src/components/detail/ApprovalModal.tsx` | Approval UI modal |
| `ui/src/components/detail/QuestionCard.tsx` | Question component |
| `ui/src/components/dashboard/PendingActionsBadge.tsx` | Badge component |

### Files to Modify

| File | Changes |
|------|---------|
| `src/orchestrator/config/enums.py` | Add PENDING_USER_ACTION to TaskStatus |
| `src/orchestrator/state/models.py` | Add pending_action_type, pending_clarification_id to TaskState |
| `src/orchestrator/config/models.py` | Add summary_artifact to GateConfig, clarifications to RoutineConfig |
| `src/orchestrator/db/models.py` | Add ClarificationRequestModel, ClarificationResponseModel, extend TaskModel |
| `src/orchestrator/db/repositories.py` | Add clarification repository methods |
| `src/orchestrator/workflow/transitions.py` | Update VALID_TRANSITIONS, add human interaction transitions |
| `src/orchestrator/workflow/events.py` | Add clarification and approval events |
| `src/orchestrator/workflow/service.py` | Add clarification and approval methods |
| `src/orchestrator/workflow/prompts.py` | Add clarifications path to prompts |
| `src/orchestrator/mcp/tools.py` | Add request_clarification tool |
| `src/orchestrator/api/app.py` | Register clarifications router |
| `src/orchestrator/api/routers/tasks.py` | Add approve/reject endpoints |
| `src/orchestrator/api/schemas/tasks.py` | Add ApproveTaskRequest, RejectTaskRequest |
| `src/orchestrator/api/schemas/runs.py` | Extend TaskSummary, StepSummary |
| `src/orchestrator/api/routers/runs.py` | Populate new summary fields |
| `src/orchestrator/cli/__init__.py` | Register approve command |
| `ui/src/types/index.ts` | Export new types |
| `ui/src/types/enums.ts` | Add pending_user_action status |
| `ui/src/api/client.ts` | Add clarification/approval API methods |
| `ui/src/pages/RunDetail.tsx` | Integrate modals |
| `ui/src/components/detail/TaskCard.tsx` | Show pending action indicator |
| `ui/src/components/dashboard/RunCard.tsx` | Add pending actions badge |
| `ui/src/components/dashboard/RunFilters.tsx` | Add "Needs Input" filter |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Artifact file conflicts | Use append-only writes, include attempt number in section headers |
| WebSocket broadcast delays | Emit events synchronously, let WebSocket layer handle async |
| Modal state complexity | Use controlled components, clear state on close |
| Race conditions in approval | Use database transactions, check status before transition |
| Large clarification files | Implement pagination in artifact display (future) |

---

If Phase 9 is complete, proceed to Phase 10 (future enhancements).
