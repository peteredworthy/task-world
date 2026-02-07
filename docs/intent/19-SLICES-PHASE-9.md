# Implementation Slices: Phase 9 - Advanced Workflow Features

**Goal:** Enable complex multi-stage workflows with human gates, backward transitions, dry-run verification, and artifact generation — specifically to support planning routines like `idea_to_plan`.

**End state:** Can run planning workflows that produce step files as output, with explicit human review gates and conditional backtracking.

**Prerequisites:** Phases 1-5 complete (core workflow engine with agent integration).

---

## Context: The Planning Routine Pattern

Real-world planning workflows (like `idea_to_plan`) have characteristics our MVP doesn't fully support:

1. **Human-only gates** - Some steps require human approval, not just LLM verification
2. **Backward transitions** - "If conflicts emerge, RETURN to Stage 2" 
3. **Artifact-producing tasks** - Output is structured documents (YAML routines, step files)
4. **Dry-run simulation** - Test execution before real execution
5. **Multi-document context** - Task needs access to multiple prior artifacts

This phase adds the workflow primitives needed to express these patterns.

---

## Slice 9.1: Human-Only Gate Type

### Goal
Add a gate type that requires explicit human approval and cannot be auto-verified or LLM-verified.

### Prerequisites
- Slice 2.1 (checklist gate logic) complete

### Deliverables

```
src/orchestrator/workflow/
├── gates.py           # Extended gate types
tests/unit/test_human_gates.py
```

### Architecture Constraints

1. **Gate types are explicit** - `gate_type` field on step or task
2. **Human gates block automation** - YOLO/auto-verify cannot bypass
3. **UI must support approval** - API endpoint for human approval
4. **Audit trail** - Record who approved and when

### Schema Extension

```yaml
# In routine YAML
steps:
  - id: "S-02"
    title: "Human Review"
    gate:
      type: human_approval  # NEW: requires explicit human action
      approval_prompt: "Review the plan and confirm alignment with intent"
      require_comment: true  # Human must provide feedback
    task:
      # ...
```

### Implementation

```python
from enum import Enum
from pydantic import BaseModel
from datetime import datetime

class GateType(Enum):
    CHECKLIST = "checklist"           # Existing: all CRITICAL done
    GRADE_THRESHOLD = "grade_threshold"  # Existing: grades meet threshold
    HUMAN_APPROVAL = "human_approval"    # NEW: explicit human action
    AUTO_VERIFY = "auto_verify"          # Existing: commands pass

class HumanApproval(BaseModel):
    """Record of human gate approval."""
    approved_by: str  # User identifier
    approved_at: datetime
    comment: str | None
    
class GateConfig(BaseModel):
    """Gate configuration for a step or task."""
    type: GateType
    # For human_approval
    approval_prompt: str | None = None
    require_comment: bool = False
    # For grade_threshold
    critical_threshold: str = "A"
    expected_threshold: str = "B"

def evaluate_gate(
    gate_config: GateConfig,
    checklist: list[ChecklistItem],
    grades: dict[str, str],
    human_approval: HumanApproval | None,
    auto_verify_results: list[AutoVerifyResult],
) -> GateResult:
    """Evaluate gate based on type."""
    
    if gate_config.type == GateType.HUMAN_APPROVAL:
        if human_approval is None:
            return GateResult(
                passed=False,
                blocking_reason="Awaiting human approval",
                gate_type=GateType.HUMAN_APPROVAL,
            )
        if gate_config.require_comment and not human_approval.comment:
            return GateResult(
                passed=False,
                blocking_reason="Human approval requires comment",
                gate_type=GateType.HUMAN_APPROVAL,
            )
        return GateResult(passed=True, gate_type=GateType.HUMAN_APPROVAL)
    
    # ... existing gate logic for other types
```

### API Endpoint

```python
@router.post("/api/runs/{run_id}/steps/{step_id}/approve")
async def approve_step(
    run_id: str,
    step_id: str,
    approval: HumanApprovalRequest,
    current_user: str = Depends(get_current_user),
) -> StepResponse:
    """Human approval for a step gate."""
    # Record approval and re-evaluate gate
```

### Verification

#### Unit Tests
- Human gate blocks without approval
- Human gate passes with approval
- Comment required when configured
- Audit trail recorded

#### Integration Tests
- API endpoint accepts approval
- Run progresses after approval
- YOLO mode skips steps with human gates (pauses run)

### Definition of Done
- [ ] GateType.HUMAN_APPROVAL implemented
- [ ] Approval endpoint works
- [ ] UI shows approval prompt
- [ ] Audit trail persisted

---

## Slice 9.2: Conditional Backward Transitions

### Goal
Enable steps to transition backward to earlier steps based on conditions (e.g., "if conflicts found, return to review").

### Prerequisites
- Slice 9.1 complete
- Slice 2.3 (task state machine) complete

### Deliverables

```
src/orchestrator/workflow/
├── transitions.py     # Extended transition logic
tests/unit/test_backward_transitions.py
```

### Architecture Constraints

1. **Backward transitions are explicit** - Defined in routine, not inferred
2. **Condition-based** - Triggered by specific checklist states or custom conditions
3. **Loop detection** - Prevent infinite loops with max iterations
4. **State preserved** - Prior step results kept, not discarded

### Schema Extension

```yaml
steps:
  - id: "S-03"
    title: "Plan Refinement"
    task:
      # ...
    transitions:
      # Normal: proceed to S-04
      on_complete: "S-04"
      # Conditional backward transition
      on_condition:
        - condition: "has_unresolved_conflicts"
          target: "S-02"  # Back to human review
          max_iterations: 3
          message: "Unresolved conflicts detected, returning to review"
        - condition: "has_open_questions"
          target: "S-02"
          max_iterations: 3
          message: "Open questions remain, returning to review"
```

### Implementation

```python
from pydantic import BaseModel

class TransitionCondition(BaseModel):
    """Condition for a backward transition."""
    condition: str  # Condition identifier
    target: str     # Step ID to transition to
    max_iterations: int = 3
    message: str | None = None

class StepTransitions(BaseModel):
    """Transition configuration for a step."""
    on_complete: str | None = None  # Default: next step
    on_condition: list[TransitionCondition] = []

class TransitionTracker:
    """Track backward transitions to prevent infinite loops."""
    
    def __init__(self):
        self._counts: dict[tuple[str, str], int] = {}  # (from, to) -> count
    
    def record_transition(self, from_step: str, to_step: str) -> None:
        key = (from_step, to_step)
        self._counts[key] = self._counts.get(key, 0) + 1
    
    def can_transition(
        self, 
        from_step: str, 
        to_step: str, 
        max_iterations: int
    ) -> bool:
        key = (from_step, to_step)
        return self._counts.get(key, 0) < max_iterations
    
    def get_count(self, from_step: str, to_step: str) -> int:
        return self._counts.get((from_step, to_step), 0)

def evaluate_transition_conditions(
    step: StepConfig,
    checklist: list[ChecklistItem],
    run_state: RunState,
    tracker: TransitionTracker,
) -> str | None:
    """
    Evaluate transition conditions and return target step ID.
    Returns None if should proceed normally.
    """
    for cond in step.transitions.on_condition:
        if not tracker.can_transition(step.id, cond.target, cond.max_iterations):
            continue  # Max iterations reached, skip this condition
        
        if evaluate_condition(cond.condition, checklist, run_state):
            tracker.record_transition(step.id, cond.target)
            return cond.target
    
    return step.transitions.on_complete

def evaluate_condition(
    condition: str,
    checklist: list[ChecklistItem],
    run_state: RunState,
) -> bool:
    """Evaluate a named condition."""
    
    # Built-in conditions
    if condition == "has_unresolved_conflicts":
        # Check if CONFLICTS.md has unresolved items
        return run_state.has_artifact("CONFLICTS.md") and \
               not run_state.artifact_resolved("CONFLICTS.md")
    
    if condition == "has_open_questions":
        # Check if design-questions.md has unanswered questions
        return run_state.has_artifact("design-questions.md") and \
               run_state.artifact_has_open_items("design-questions.md")
    
    if condition == "checklist_incomplete":
        # Any CRITICAL items not done
        return any(
            item.priority == Priority.CRITICAL and item.status != "done"
            for item in checklist
        )
    
    # Custom conditions via checklist items with special IDs
    if condition.startswith("checklist:"):
        item_id = condition.split(":", 1)[1]
        item = next((i for i in checklist if i.req_id == item_id), None)
        return item is not None and item.status != "done"
    
    return False
```

### Verification

#### Unit Tests
- Condition evaluation logic
- Transition tracking counts
- Max iterations enforcement
- Loop detection

#### Integration Tests
- Run backtracks on condition
- Run proceeds after condition clears
- Max iterations triggers failure (not infinite loop)

### Definition of Done
- [ ] Transition conditions schema defined
- [ ] Condition evaluation works
- [ ] Loop tracking prevents infinite loops
- [ ] Backward transition changes run state correctly

---

## Slice 9.3: Artifact Registry

### Goal
Track generated artifacts (documents, files) across steps so later steps can reference them.

### Prerequisites
- Slice 3.2 (repository pattern) complete

### Deliverables

```
src/orchestrator/
├── artifacts/
│   ├── __init__.py
│   ├── registry.py    # Artifact tracking
│   └── models.py      # Artifact types
tests/unit/test_artifact_registry.py
```

### Architecture Constraints

1. **Artifacts are immutable snapshots** - Each version is preserved
2. **Path-based identification** - Artifacts identified by relative path
3. **Step association** - Each artifact linked to producing step
4. **Content hashing** - Detect changes between versions

### Implementation

```python
from pydantic import BaseModel
from datetime import datetime
import hashlib

class Artifact(BaseModel):
    """A tracked artifact produced by a step."""
    id: str
    run_id: str
    step_id: str
    task_id: str
    path: str  # Relative path within worktree
    content_hash: str
    created_at: datetime
    version: int  # Incremented on updates
    metadata: dict[str, Any] = {}

class ArtifactRegistry:
    """Track artifacts produced during a run."""
    
    def __init__(self, repository: ArtifactRepository):
        self._repo = repository
    
    async def register(
        self,
        run_id: str,
        step_id: str,
        task_id: str,
        path: str,
        content: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Register a new or updated artifact."""
        content_hash = hashlib.sha256(content).hexdigest()
        
        # Check for existing artifact at path
        existing = await self._repo.get_by_path(run_id, path)
        
        if existing and existing.content_hash == content_hash:
            return existing  # No change
        
        version = (existing.version + 1) if existing else 1
        
        artifact = Artifact(
            id=f"{run_id}-{path}-v{version}",
            run_id=run_id,
            step_id=step_id,
            task_id=task_id,
            path=path,
            content_hash=content_hash,
            created_at=datetime.utcnow(),
            version=version,
            metadata=metadata or {},
        )
        
        await self._repo.save(artifact)
        return artifact
    
    async def get_latest(self, run_id: str, path: str) -> Artifact | None:
        """Get the latest version of an artifact."""
        return await self._repo.get_by_path(run_id, path)
    
    async def list_for_step(self, run_id: str, step_id: str) -> list[Artifact]:
        """List all artifacts produced by a step."""
        return await self._repo.list_by_step(run_id, step_id)
    
    async def has_unresolved(self, run_id: str, path: str) -> bool:
        """Check if artifact has unresolved items (for conflict tracking)."""
        artifact = await self.get_latest(run_id, path)
        if not artifact:
            return False
        return artifact.metadata.get("has_unresolved", False)
```

### Schema Extension for Expected Artifacts

```yaml
steps:
  - id: "S-01"
    title: "Initial Plan"
    task:
      # ...
      artifacts:
        - path: "docs/{{feature}}/plan.md"
          required: true
        - path: "docs/{{feature}}/intent.md"
          required: true
        - path: "docs/{{feature}}/design-questions.md"
          required: true
          track_resolution: true  # Monitor for unresolved items
        - path: "docs/{{feature}}/CONFLICTS.md"
          required: false
          track_resolution: true
```

### Verification

#### Unit Tests
- Artifact registration with versioning
- Content hash deduplication
- Resolution tracking

#### Integration Tests
- Artifacts persisted to database
- Step can reference prior artifacts
- Transition conditions use artifact state

### Definition of Done
- [ ] Artifact model and registry implemented
- [ ] Versioning works
- [ ] Resolution tracking works
- [ ] Artifacts available to subsequent steps

---

## Slice 9.4: Dry-Run Verification Mode

### Goal
Enable simulated execution that validates plan coherence without actually running code.

### Prerequisites
- Slice 2.5 (prompt generation) complete
- Slice 5.3 (mock agent) complete

### Deliverables

```
src/orchestrator/workflow/
├── dry_run.py         # Dry-run execution logic
tests/unit/test_dry_run.py
```

### Architecture Constraints

1. **No side effects** - Dry-run doesn't modify files or run commands
2. **Limited context** - Simulates agent with constrained information
3. **Gap detection** - Identifies missing context, unclear requirements
4. **Report generation** - Produces actionable feedback

### Schema Extension

```yaml
steps:
  - id: "S-06"
    title: "Dry Run"
    type: dry_run  # NEW: special step type
    dry_run:
      target_steps: ["S-09"]  # Which steps to simulate
      context_limit: 4000    # Tokens of context for simulation
      report_path: "docs/{{feature}}/dry-run-notes.md"
```

### Implementation

```python
from pydantic import BaseModel

class DryRunConfig(BaseModel):
    """Configuration for a dry-run step."""
    target_steps: list[str]  # Step IDs to simulate
    context_limit: int = 4000  # Token limit for simulation
    report_path: str

class DryRunResult(BaseModel):
    """Result of a dry-run simulation."""
    step_id: str
    task_id: str
    simulated_outcome: str
    identified_gaps: list[str]
    missing_context: list[str]
    unclear_requirements: list[str]
    suggested_improvements: list[str]

async def execute_dry_run(
    run: Run,
    config: DryRunConfig,
    artifact_registry: ArtifactRegistry,
    llm_client: LLMClient,
) -> list[DryRunResult]:
    """
    Execute dry-run simulation for target steps.
    
    The LLM simulates execution with limited context to surface gaps.
    """
    results = []
    
    for step_id in config.target_steps:
        step = get_step(run, step_id)
        
        # Build limited context
        context = build_dry_run_context(
            run=run,
            step=step,
            artifact_registry=artifact_registry,
            token_limit=config.context_limit,
        )
        
        # Generate dry-run prompt
        prompt = f"""
You are simulating execution of a task with LIMITED context.
Your goal is to identify gaps, not to actually complete the task.

CONTEXT (truncated to {config.context_limit} tokens):
{context}

TASK:
{step.task.task_context}

REQUIREMENTS:
{format_requirements(step.task.requirements)}

INSTRUCTIONS:
1. Describe what you WOULD do to complete this task
2. Identify any GAPS in the context that would block you
3. List any UNCLEAR requirements that need clarification
4. Suggest improvements to the task definition

Respond in JSON format:
{{
  "simulated_outcome": "description of what you would do",
  "identified_gaps": ["gap1", "gap2"],
  "missing_context": ["context1", "context2"],
  "unclear_requirements": ["req1", "req2"],
  "suggested_improvements": ["improvement1", "improvement2"]
}}
"""
        
        response = await llm_client.complete(prompt)
        result = DryRunResult(
            step_id=step_id,
            task_id=step.task.id,
            **parse_dry_run_response(response),
        )
        results.append(result)
    
    return results

def build_dry_run_context(
    run: Run,
    step: StepConfig,
    artifact_registry: ArtifactRegistry,
    token_limit: int,
) -> str:
    """Build context for dry-run, deliberately limited."""
    # Include only:
    # - Step's own context
    # - Artifacts from prior steps (truncated)
    # - No full file contents, just summaries
    pass
```

### Verification

#### Unit Tests
- Context building respects token limit
- Prompt generation correct
- Response parsing works

#### Integration Tests
- Dry-run step executes without side effects
- Report generated with gaps
- Gaps can trigger backward transition

### Definition of Done
- [ ] Dry-run step type implemented
- [ ] Context limitation works
- [ ] Gap detection produces useful output
- [ ] Report persisted as artifact

---

## Slice 9.5: Multi-Artifact Context Injection

### Goal
Enable tasks to explicitly request context from multiple prior artifacts.

### Prerequisites
- Slice 9.3 (artifact registry) complete

### Deliverables

```
src/orchestrator/workflow/
├── context_builder.py  # Context assembly from artifacts
tests/unit/test_context_builder.py
```

### Architecture Constraints

1. **Explicit context references** - Task declares which artifacts it needs
2. **Token budget** - Total context limited, artifacts prioritized
3. **Freshness** - Always use latest artifact version
4. **Variable substitution** - Artifact content available as variables

### Schema Extension

```yaml
steps:
  - id: "S-04"
    title: "Step Planning"
    task:
      context_from:
        - artifact: "docs/{{feature}}/plan.md"
          as: "plan"
          required: true
        - artifact: "docs/{{feature}}/design-questions.md"
          as: "questions"
          required: true
          section: "resolved"  # Only include resolved section
        - artifact: "docs/{{feature}}/architecture.md"
          as: "architecture"
          required: false
      task_context: |
        Based on the plan and resolved questions, create detailed step plans.
        
        PLAN:
        {{context.plan}}
        
        RESOLVED QUESTIONS:
        {{context.questions}}
        
        {% if context.architecture %}
        ARCHITECTURE:
        {{context.architecture}}
        {% endif %}
```

### Implementation

```python
class ContextSource(BaseModel):
    """Configuration for context from an artifact."""
    artifact: str  # Path pattern (supports variables)
    as_name: str = Field(alias="as")  # Variable name
    required: bool = True
    section: str | None = None  # Extract specific section
    max_tokens: int | None = None  # Limit for this artifact

class TaskContextBuilder:
    """Build task context from multiple artifacts."""
    
    def __init__(
        self,
        artifact_registry: ArtifactRegistry,
        worktree_path: Path,
    ):
        self._registry = artifact_registry
        self._worktree = worktree_path
    
    async def build_context(
        self,
        run_id: str,
        context_sources: list[ContextSource],
        variables: dict[str, Any],
        total_token_limit: int = 8000,
    ) -> dict[str, str]:
        """
        Build context dict from artifact sources.
        
        Returns dict mapping as_name -> content.
        """
        context = {}
        remaining_tokens = total_token_limit
        
        for source in context_sources:
            # Resolve path with variables
            path = resolve_variables(source.artifact, variables)
            
            # Get artifact content
            content = await self._get_artifact_content(run_id, path)
            
            if content is None:
                if source.required:
                    raise ContextError(f"Required artifact not found: {path}")
                continue
            
            # Extract section if specified
            if source.section:
                content = extract_section(content, source.section)
            
            # Apply token limit
            limit = min(
                source.max_tokens or remaining_tokens,
                remaining_tokens,
            )
            content = truncate_to_tokens(content, limit)
            
            remaining_tokens -= count_tokens(content)
            context[source.as_name] = content
        
        return context
    
    async def _get_artifact_content(
        self, 
        run_id: str, 
        path: str
    ) -> str | None:
        """Get content from registry or filesystem."""
        # First check registry
        artifact = await self._registry.get_latest(run_id, path)
        if artifact:
            # Read from worktree at the artifact's recorded hash
            pass
        
        # Fall back to filesystem
        full_path = self._worktree / path
        if full_path.exists():
            return full_path.read_text()
        
        return None
```

### Verification

#### Unit Tests
- Context sources resolved correctly
- Token budgeting works
- Section extraction works
- Variable substitution in paths

#### Integration Tests
- Task receives multi-artifact context
- Missing required artifact fails
- Optional missing artifact skipped

### Definition of Done
- [ ] ContextSource model implemented
- [ ] Context builder works
- [ ] Token limiting works
- [ ] Integrated with prompt generation

---

## Slice 9.6: Planning Routine Template

### Goal
Create a working `idea_to_plan` routine using all Phase 9 features.

### Prerequisites
- Slices 9.1-9.5 complete

### Deliverables

```
examples/routines/
├── idea_to_plan.yaml   # The planning routine
tests/e2e/test_idea_to_plan.py
```

### Implementation

```yaml
# examples/routines/idea_to_plan.yaml
routine:
  id: "idea-to-plan"
  name: "Idea to Implementation Plan"
  description: |
    Transform an initial idea into a structured, executable plan
    with step files suitable for agent execution.
  
  inputs:
    - name: "feature"
      required: true
      description: "Feature name for directory structure"
    - name: "idea"
      required: true
      description: "Initial idea or prompt"
    - name: "codebase_context"
      required: false
      description: "Brief description of existing codebase"

  steps:
    # Stage 1: Initial Plan
    - id: "S-01"
      title: "Initial Plan"
      step_context: "Create initial plan exposing gaps early"
      task:
        id: "T-01"
        title: "Generate Initial Artifacts"
        task_context: |
          Based on the idea, create initial planning artifacts.
          
          IDEA: {{idea}}
          {% if codebase_context %}
          CODEBASE: {{codebase_context}}
          {% endif %}
          
          Create these files:
          1. docs/{{feature}}/intent.md - Original request summary
          2. docs/{{feature}}/plan.md - High-level iterative plan
          3. docs/{{feature}}/design-questions.md - Unknowns to resolve
          4. docs/{{feature}}/architecture.md - Tech choices & interactions
        
        requirements:
          - id: "R1"
            desc: "Create intent.md summarizing the request"
            priority: critical
          - id: "R2"
            desc: "Create plan.md with iterative steps"
            priority: critical
          - id: "R3"
            desc: "Create design-questions.md with open questions"
            priority: critical
          - id: "R4"
            desc: "Create architecture.md with tech choices"
            priority: expected
        
        artifacts:
          - path: "docs/{{feature}}/intent.md"
            required: true
          - path: "docs/{{feature}}/plan.md"
            required: true
          - path: "docs/{{feature}}/design-questions.md"
            required: true
            track_resolution: true
          - path: "docs/{{feature}}/architecture.md"
            required: false
        
        auto_verify:
          items:
            - id: "files_exist"
              cmd: "test -f docs/{{feature}}/intent.md && test -f docs/{{feature}}/plan.md && test -f docs/{{feature}}/design-questions.md"
              must: true
        
        retry:
          max_attempts: 2

    # Stage 2: Human Review
    - id: "S-02"
      title: "Human Review"
      step_context: "Align plan with user expectations"
      gate:
        type: human_approval
        approval_prompt: |
          Review the generated plan artifacts:
          - docs/{{feature}}/intent.md
          - docs/{{feature}}/plan.md
          - docs/{{feature}}/design-questions.md
          - docs/{{feature}}/architecture.md
          
          Provide feedback by adding [HUMAN] notes to the documents,
          then approve to continue.
        require_comment: true
      task:
        id: "T-01"
        title: "Await Human Feedback"
        task_context: "Human reviews and provides feedback"
        requirements:
          - id: "R1"
            desc: "Human has reviewed all artifacts"
            priority: critical
        # No auto_verify - human gate handles this

    # Stage 3: Plan Refinement
    - id: "S-03"
      title: "Plan Refinement"
      step_context: "Integrate feedback and surface conflicts"
      task:
        id: "T-01"
        title: "Refine Based on Feedback"
        context_from:
          - artifact: "docs/{{feature}}/plan.md"
            as: "plan"
            required: true
          - artifact: "docs/{{feature}}/design-questions.md"
            as: "questions"
            required: true
          - artifact: "docs/{{feature}}/architecture.md"
            as: "architecture"
            required: false
        task_context: |
          Integrate human feedback and resolve conflicts.
          
          Look for [HUMAN] notes in the artifacts and address them.
          
          CURRENT PLAN:
          {{context.plan}}
          
          DESIGN QUESTIONS:
          {{context.questions}}
          
          If you discover conflicts, document them in:
          docs/{{feature}}/CONFLICTS.md
          
          Update the plan and design questions based on feedback.
        
        requirements:
          - id: "R1"
            desc: "Address all [HUMAN] feedback notes"
            priority: critical
          - id: "R2"
            desc: "Update plan.md with refinements"
            priority: critical
          - id: "R3"
            desc: "Mark resolved questions in design-questions.md"
            priority: expected
          - id: "R4"
            desc: "Document any conflicts in CONFLICTS.md"
            priority: expected
        
        artifacts:
          - path: "docs/{{feature}}/CONFLICTS.md"
            required: false
            track_resolution: true
        
        retry:
          max_attempts: 2
      
      transitions:
        on_complete: "S-04"
        on_condition:
          - condition: "has_unresolved_conflicts"
            target: "S-02"
            max_iterations: 3
            message: "Unresolved conflicts - returning to human review"
          - condition: "has_open_questions"
            target: "S-02"
            max_iterations: 3
            message: "Open design questions remain"

    # Stage 4: Step Planning
    - id: "S-04"
      title: "Step Planning"
      step_context: "Define detailed contracts per step"
      task:
        id: "T-01"
        title: "Create Step Plans"
        context_from:
          - artifact: "docs/{{feature}}/plan.md"
            as: "plan"
            required: true
          - artifact: "docs/{{feature}}/architecture.md"
            as: "architecture"
            required: true
        task_context: |
          For each step in the plan, create a detailed step plan.
          
          PLAN:
          {{context.plan}}
          
          ARCHITECTURE:
          {{context.architecture}}
          
          For each step, create: docs/{{feature}}/step-XX-plan.md
          
          Each step plan must include:
          - Purpose and goals
          - Functional contract (inputs, outputs, errors)
          - Verification tests
          - Dependencies on other steps
        
        requirements:
          - id: "R1"
            desc: "Create step-XX-plan.md for each plan step"
            priority: critical
          - id: "R2"
            desc: "Each plan includes functional contract"
            priority: critical
          - id: "R3"
            desc: "Each plan includes verification approach"
            priority: expected
        
        auto_verify:
          items:
            - id: "step_plans_exist"
              cmd: "ls docs/{{feature}}/step-*-plan.md | wc -l | test $(cat) -ge 1"
              must: true
        
        retry:
          max_attempts: 2
      
      transitions:
        on_complete: "S-05"
        on_condition:
          - condition: "has_unresolved_conflicts"
            target: "S-02"
            max_iterations: 2
            message: "New conflicts discovered during step planning"

    # Stage 5: Task Breakdown
    - id: "S-05"
      title: "Task Breakdown"
      step_context: "Produce atomic tasks for execution"
      task:
        id: "T-01"
        title: "Create Step Files"
        task_context: |
          Convert step plans into atomic task files.
          
          For each step-XX-plan.md, create:
          docs/{{feature}}/steps/step-XX.md
          
          Each task must be:
          - Atomic (<5 files, <500 lines changed)
          - Independently verifiable
          - Include context references
          
          Follow the format in docs/step-files.md
        
        requirements:
          - id: "R1"
            desc: "Create step-XX.md for each step plan"
            priority: critical
          - id: "R2"
            desc: "Tasks are atomic and verifiable"
            priority: critical
          - id: "R3"
            desc: "Tasks include context references"
            priority: expected
        
        auto_verify:
          items:
            - id: "step_files_exist"
              cmd: "ls docs/{{feature}}/steps/step-*.md | wc -l | test $(cat) -ge 1"
              must: true
        
        retry:
          max_attempts: 2
      
      transitions:
        on_complete: "S-06"
        on_condition:
          - condition: "has_unresolved_conflicts"
            target: "S-02"
            max_iterations: 2

    # Stage 6: Dry Run
    - id: "S-06"
      title: "Dry Run"
      type: dry_run
      step_context: "Simulate execution to identify gaps"
      dry_run:
        target_steps: ["S-09"]  # Simulate the execution step
        context_limit: 4000
        report_path: "docs/{{feature}}/dry-run-notes.md"
      
      transitions:
        on_complete: "S-07"

    # Stage 7: Final Check
    - id: "S-07"
      title: "Final Check"
      step_context: "Ensure consistency and completeness"
      task:
        id: "T-01"
        title: "Cross-Check All Artifacts"
        context_from:
          - artifact: "docs/{{feature}}/intent.md"
            as: "intent"
            required: true
          - artifact: "docs/{{feature}}/plan.md"
            as: "plan"
            required: true
          - artifact: "docs/{{feature}}/dry-run-notes.md"
            as: "dry_run"
            required: false
        task_context: |
          Cross-check all artifacts for consistency.
          
          Verify:
          1. Step files align with plan
          2. No gaps identified in dry run
          3. Intent is fully addressed
          
          INTENT:
          {{context.intent}}
          
          PLAN:
          {{context.plan}}
          
          {% if context.dry_run %}
          DRY RUN NOTES:
          {{context.dry_run}}
          {% endif %}
        
        requirements:
          - id: "R1"
            desc: "All step files align with plan"
            priority: critical
          - id: "R2"
            desc: "Dry run gaps addressed"
            priority: expected
          - id: "R3"
            desc: "Intent fully covered"
            priority: critical
        
        verifier:
          rubric:
            - id: "completeness"
              text: "Does the plan fully address the original intent?"
            - id: "consistency"
              text: "Are all artifacts internally consistent?"
            - id: "executability"
              text: "Can the step files be executed as-is?"
          submission_template:
            grade_scale: [A, B, C, D, F]
            require_reason_if_below: A
            require_remediation_if_below: B
        
        retry:
          max_attempts: 2

    # Stage 8: Final Plan Review (Human)
    - id: "S-08"
      title: "Final Plan Review"
      gate:
        type: human_approval
        approval_prompt: |
          The plan is complete. Review the final artifacts:
          - docs/{{feature}}/steps/*.md (execution files)
          - docs/{{feature}}/plan.md
          
          Approve to proceed to execution or provide final feedback.
        require_comment: false
      task:
        id: "T-01"
        title: "Human Final Approval"
        task_context: "Human reviews final plan before execution"
        requirements:
          - id: "R1"
            desc: "Human approves final plan"
            priority: critical

    # Stage 9: Ready for Execution
    - id: "S-09"
      title: "Execution Ready"
      step_context: "Plan complete - step files ready for execution"
      task:
        id: "T-01"
        title: "Generate Summary"
        task_context: |
          Generate a summary of the completed plan.
          
          Output: docs/{{feature}}/plan-summary.md
          
          Include:
          - How the intent will be satisfied
          - List of step files generated
          - Any notes or caveats
        
        requirements:
          - id: "R1"
            desc: "Create plan-summary.md"
            priority: critical
        
        auto_verify:
          items:
            - id: "summary_exists"
              cmd: "test -f docs/{{feature}}/plan-summary.md"
              must: true
```

### Verification

#### E2E Test

```python
@pytest.mark.e2e
async def test_idea_to_plan_routine():
    """Full planning routine with human gates."""
    # 1. Create run with idea_to_plan routine
    # 2. Execute S-01 (initial plan)
    # 3. Approve human gate at S-02
    # 4. Execute S-03 (refinement)
    # 5. Verify backward transition if conflicts
    # 6. Continue through remaining steps
    # 7. Verify all artifacts generated
    # 8. Verify step files are valid
```

### Definition of Done
- [ ] Routine validates
- [ ] Human gates work
- [ ] Backward transitions work
- [ ] Artifacts tracked
- [ ] Dry run identifies gaps
- [ ] Full E2E test passes

---

## Phase 9 Milestone Verification

```bash
# All tests pass
uv run pytest tests/ -v

# Validate the planning routine
uv run orchestrator routine validate examples/routines/idea_to_plan.yaml

# Create a test run
uv run orchestrator run create idea-to-plan \
  --project ./test-project \
  --config '{"feature": "test-feature", "idea": "Add user authentication"}'

# Execute with mock agent (human gates will pause)
uv run orchestrator run start <run-id> --agent mock

# Manually approve human gates
uv run orchestrator run approve <run-id> --step S-02 --comment "Looks good"
```

If the planning routine completes successfully, Phase 9 is complete.
