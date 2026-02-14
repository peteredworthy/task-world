# Implementation Plan: Idea-to-Plan Routine Improvements

## Overview

This plan addresses three key gaps in the idea-to-plan workflow:
1. **Backward transitions with task list cleanup** - Reset checklist items on re-entry while preserving repo state
2. **Sub-agent-based dry-run task execution** - Break dry-run into focused tasks with full context each
3. **Dry-run notes as living feedback loop** - Steps 5+ require resolving gaps and marking them resolved

---

## Design Principles

- **Repo state continues evolving**: When transitioning backward (S-04 → S-02 → S-05), the git repo keeps all previous work; we only reset the *task status* (checklist items back to OPEN)
- **Dry-run notes drive remaining work**: S-05+ task instructions explicitly require reading and resolving any gaps in `dry-run-notes.md`
- **Sub-agents manage context**: Dry-run is executed by spawning focused sub-agents, each with full context for their specific task
- **No extra tools for sub-agents**: Sub-agents get standard tools + 1 return-message tool only

---

## Phase 1: Sub-Agent Infrastructure

### 1.1 Sub-Agent Protocol (New)

**File**: `src/orchestrator/agents/sub_agent.py`

```python
"""Sub-agent protocol and execution.

A sub-agent is a temporary agent spawned to complete a specific task,
with a return-message tool to communicate back to the parent agent.

Key characteristics:
- Blocking: Parent agent waits for sub-agent to complete
- Limited tools: Standard tools + return_message only (no task-world tools)
- Sequential: No concurrency (simpler implementation, sufficient for now)
"""

class SubAgentConfig(BaseModel):
    """Configuration for spawning a sub-agent."""
    prompt: str  # What the sub-agent should do
    agent_type: AgentType  # OPENHANDS, CODEX_CLI, etc.
    timeout_seconds: int = 300
    context_limit: int | None = None

class SubAgentResult(BaseModel):
    """Result from a sub-agent execution."""
    success: bool  # True if sub-agent called return_message
    message: str  # What the sub-agent passed to return_message tool
    output: str | None  # Captured output (if any)
    error: str | None  # Error message if sub-agent failed

async def execute_sub_agent(
    config: SubAgentConfig,
    agent_backend: AgentBackend,
) -> SubAgentResult:
    """Execute a sub-agent with a specific prompt.

    Execution flow:
    1. Switch to sub-agent mode (context switch, not fork)
    2. Provide sub-agent with:
       - Standard tools (file read/write, bash execution, git, etc.)
       - One extra tool: return_message(message: str)
    3. Block parent agent loop until:
       - Sub-agent calls return_message() → return success with message
       - Sub-agent times out → return error
       - Sub-agent crashes/errors → return error

    Parent agent sees sub-agent errors like command execution failures.
    """
```

### 1.2 OpenHands Sub-Agent Support

**File**: `src/orchestrator/agents/openhands.py`

Changes:
- Add check in `execute()` for special `sub_agent_mode` flag in context
- When true:
  - Load the sub-agent prompt (from `ExecutionContext.sub_agent_prompt`)
  - Add only standard tools + `return_message` tool (no task-world tools)
  - Block the main OpenHands agent loop (switch to sub-agent context)
  - Wait for `return_message` tool call
  - Return `SubAgentResult` with the returned message
  - **No concurrency** - sub-agent runs serially (OpenHands switches context, doesn't fork)

Example tool definition:
```python
return_message_tool = {
    "type": "function",
    "function": {
        "name": "return_message",
        "description": "Return result message to parent agent. This ends sub-agent execution.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Message to return to parent agent. Can include any format needed by parent."
                }
            },
            "required": ["message"]
        }
    }
}
```

**Error handling**:
- If sub-agent times out → stop execution, return error in `SubAgentResult.error`
- If sub-agent crashes → capture error, return in `SubAgentResult.error`
- Parent agent receives the error like a failed command execution

### 1.3 Codex CLI Sub-Agent Support

**File**: `src/orchestrator/agents/cli.py`

Changes:
- Add `--sub-agent` flag support (passed to Codex CLI)
- When `sub_agent_mode`, pass special prompt that mentions return_message tool
- Parse output for `return_message` call
- Return `SubAgentResult`

### 1.4 Sub-Agent Invocation from Task

**File**: `src/orchestrator/workflow/service.py`

New method:
```python
async def invoke_sub_agent(
    self,
    run_id: str,
    prompt: str,
    agent_type: AgentType | None = None,
) -> SubAgentResult:
    """Invoke a sub-agent to complete a specific task.

    Uses the run's configured agent type unless overridden.
    """
```

**Usage in task execution**:
The task context can include special instruction:
```
Use sub-agents to break this down:

## Sub-Agent Task 1: Analyze step plans
(prompt for sub-agent)

## Sub-Agent Task 2: Validate routine structure
(prompt for sub-agent)

Aggregate results and write to output file.
```

---

## Phase 2: Dry-Run Refactored with Sub-Agents

### 2.1 Dry-Run Task Generator

**File**: `src/orchestrator/workflow/dry_run_tasks.py`

```python
def generate_dry_run_sub_agent_prompts(
    feature: str,
    step_plans: dict[str, str],  # step_id -> step-plan.md content
    routine_yaml: str | None = None,
    intent: str | None = None,
    dry_run_notes_existing: str | None = None,
) -> list[SubAgentTask]:
    """Generate focused sub-agent prompts for dry-run validation.

    Returns:
        List of sub-agent tasks, each with:
        - purpose: What this task validates
        - prompt: Full prompt with complete context
        - output_path: Where to write results (e.g., dry-run-step-analysis.md)
    """
```

### 2.2 Dry-Run Task Definitions

Generate these sub-agent tasks:

**Task 1: Step Plan Analysis**
- Purpose: Simulate execution of each step's tasks with full context
- Input: All step-XX-plan.md files, intent.md, design-questions.md
- Prompt: "Simulate executing each task in the step plans. For each, describe what you would do, identify gaps, unclear requirements, and missing context."
- Output: `dry-run-step-analysis.md` (JSON with per-step/per-task results)
- Tools: Standard only + return_message

**Task 2: Intent Coverage Check**
- Purpose: Verify all intent requirements are addressed by step plans
- Input: intent.md, dry-run-step-analysis.md
- Prompt: "Check that all requirements in intent.md are covered by the step plans. Identify any gaps, uncovered edge cases, or assumptions."
- Output: `dry-run-intent-coverage.md`

**Task 3: Routine YAML Validation (if routine.yaml exists)**
- Purpose: Validate generated routine YAML against step definitions
- Input: routine.yaml, step-XX-plan.md files, design-questions.md
- Prompt: "Verify that routine.yaml correctly encodes the step plans. Check for: missing tasks, incomplete context, validation issues, mapping errors."
- Output: `dry-run-routine-validation.md`

**Task 4: Synthesis**
- Purpose: Aggregate all dry-run outputs into final report
- Input: dry-run-step-analysis.md, dry-run-intent-coverage.md, [dry-run-routine-validation.md]
- Prompt: "Read all dry-run outputs and synthesize into final dry-run-notes.md. Prioritize gaps by severity. For each gap, suggest concrete remediation steps."
- Output: `dry-run-notes.md` (structured as per template with gap resolution table)

### 2.3 Updated S-06 Routine Tasks

**S-06 T-01: Simulate Execution (Revised)**

```yaml
tasks:
  - id: "T-01"
    title: "Simulate Execution with Sub-Agents"
    task_context: |
      Execute dry-run validation using sub-agents.

      This task will:
      1. Generate focused sub-agent prompts for dry-run validation
      2. Invoke each sub-agent to analyze step plans, intent coverage, and routine YAML
      3. Aggregate results into docs/{{feature}}/dry-run-notes.md

      Do not manually simulate - use the sub-agent mechanism to break this into
      focused tasks with full context. Each sub-agent will:
      - Analyze specific artifacts (step plans, intent, routine YAML)
      - Identify gaps, unclear requirements, missing context
      - Write results to intermediate files

      Finally, synthesize all sub-agent outputs into dry-run-notes.md
      following the template structure.

      Reference: docs/planner/templates/dry-run-notes.md
      Sub-agent mechanism: Use invoke_sub_agent() for each task.
    requirements:
      - id: "R1"
        desc: "All sub-agent dry-run tasks complete and write results"
        priority: critical
      - id: "R2"
        desc: "Final dry-run-notes.md aggregates all findings with prioritized gaps"
        priority: critical
      - id: "R3"
        desc: "Gap remediation steps are concrete and actionable"
        priority: expected
    artifacts:
      - path: "docs/{{feature}}/dry-run-notes.md"
        required: true
      - path: "docs/{{feature}}/dry-run-step-analysis.md"
        required: false
      - path: "docs/{{feature}}/dry-run-intent-coverage.md"
        required: false
      - path: "docs/{{feature}}/dry-run-routine-validation.md"
        required: false
```

---

## Phase 3: Dry-Run Notes as Feedback Loop

### 3.1 Update S-05+ Task Instructions

Update task contexts for **S-04 Step Planning (T-01)**, **S-05 Task Breakdown (T-01)**, and **S-09 Execution Ready (T-02)** to include:

```markdown
## Resolve Dry-Run Gaps

If docs/{{feature}}/dry-run-notes.md exists, read it and ensure your work
resolves identified gaps:

1. **Read the Gap Resolution Table** in dry-run-notes.md
2. **For each unresolved gap**, update your output to address it:
   - Refine step plans / task definitions with more context
   - Add missing requirements or verification approaches
   - Clarify ambiguous task instructions
3. **Mark gaps as resolved** by updating the Gap Resolution Table:
   - Change "Resolution" column from blank to the specific action taken
   - Reference which artifact was updated (e.g., "Updated step-04-plan.md: Added error handling requirement")
4. **If new gaps discovered**, add them to the table
5. **Final check**: Every gap should have a "Resolution" entry before completing the task

This ensures the dry-run feedback is applied and tracked throughout the planning process.
```

### 3.2 Update S-07 Final Check

Add to **S-07 T-01 (Cross-Check All Artifacts)**:

```yaml
task_context: |
  ... [existing content] ...

  ## Dry-Run Notes Verification

  If docs/{{feature}}/dry-run-notes.md exists:
  1. Review the "Gap Resolution" table
  2. Verify each gap has a concrete resolution entry
  3. For unresolved gaps, add notes about why they're deferred and under what conditions
  4. Add to verification-report.md: "All dry-run gaps addressed or explicitly deferred"

  This ensures accountability for dry-run findings.
```

---

## Phase 4: Backward Transition with Task Reset

### 4.1 Task Status Reset on Step Re-Entry

**File**: `src/orchestrator/state/models.py`

Add to `StepState`:
```python
class StepState(BaseModel):
    # ... existing fields ...

    # Track re-entries for cleanup
    entry_count: int = 0  # Incremented each time step is entered
    last_entry_at: datetime | None = None
```

### 4.2 Reset Logic in Workflow Service

**File**: `src/orchestrator/workflow/service.py`

New method:
```python
async def reset_step_on_re_entry(self, run_id: str, step_config_id: str) -> None:
    """Reset task checklist items when re-entering a step.

    This is called when transitioning backward to a step (e.g., S-04 → S-02 → S-05).

    - Sets all ChecklistItem status back to OPEN
    - Resets attempt count to 0 for each task
    - Clears verifier comments and grades
    - BUT preserves repo state (git history, file changes)

    Purpose: Allow re-work without losing previous context from git.
    """
    run = await self._state.get_run(run_id)
    step_state = next((s for s in run.steps if s.config_id == step_config_id), None)
    if not step_state:
        return

    # Reset each task in the step
    for task in step_state.tasks:
        # Reset checklist items
        for item in task.checklist:
            item.status = ChecklistStatus.OPEN
            item.note = None
            item.grade = None
            item.grade_reason = None

        # Reset attempt tracking
        task.current_attempt = 0
        task.attempts.clear()  # Clear attempt history

        # Set status back to PENDING
        task.status = TaskStatus.PENDING
        task.pending_action_type = None
        task.pending_clarification_id = None

    # Update step entry tracking
    step_state.entry_count += 1
    step_state.last_entry_at = datetime.now(timezone.utc)
    step_state.completed = False

    # Persist
    await self._state.save_run(run)
```

### 4.3 Cleanup on Backward Transition

**File**: `src/orchestrator/workflow/engine.py`

When a conditional transition is triggered (e.g., `has_unresolved_conflicts`):
```python
# After determining target step
if target_step_id < current_step_id:  # Backward transition
    # Reset all downstream steps
    for step in run.steps:
        if step.config_id >= target_step_id:  # This step and all after
            await self._service.reset_step_on_re_entry(run.id, step.config_id)

    # Update current step index
    run.current_step_index = next(
        i for i, s in enumerate(run.steps) if s.config_id == target_step_id
    )

    # Record transition
    if run.transition_tracker:
        run.transition_tracker.record_transition(current_step_config_id, target_step_id)
```

### 4.4 Activate TransitionTracker Enforcement

**File**: `src/orchestrator/workflow/engine.py`

```python
# Before allowing transition
if run.transition_tracker:
    if not run.transition_tracker.can_transition(
        current_step_id,
        target_step_id,
        max_iterations=condition.max_iterations,
    ):
        raise InvalidTransitionError(
            f"Cannot transition {current_step_id} → {target_step_id}: "
            f"max_iterations ({condition.max_iterations}) exceeded"
        )
```

---

## Phase 5: Updated Routine YAML Structure

### 5.1 S-04 Step Planning (Updated)

```yaml
- id: "S-04"
  title: "Step Planning"
  step_context: |
    Stage 4 from docs/plan-runner/idea_to_plan_stripped.md.
    Define contracts and verification per implementation step.

    If docs/{{feature}}/dry-run-notes.md exists, read it and incorporate
    feedback into your step plans.
  tasks:
    - id: "T-01"
      title: "Create Step Plans"
      task_context: |
        Create docs/{{feature}}/step-XX-plan.md files from the implementation plan.

        ... [existing context] ...

        ## Resolve Dry-Run Gaps

        If docs/{{feature}}/dry-run-notes.md exists:
        1. Read the Gap Resolution Table
        2. For each gap, ensure your step plans address it:
           - Add missing requirements
           - Clarify ambiguous specifications
           - Add error handling / edge cases mentioned
        3. Mark gaps as resolved in the Gap Resolution Table with specific updates

        This ensures dry-run feedback is incorporated into step planning.
      # ... rest of task config ...
```

### 5.2 S-05 Task Breakdown (Updated)

```yaml
- id: "S-05"
  title: "Task Breakdown"
  # ... existing ...
  tasks:
    - id: "T-01"
      title: "Create Step Files"
      task_context: |
        Convert step plans into docs/{{feature}}/steps/step-XX.md files.

        ... [existing context] ...

        ## Resolve Dry-Run Gaps

        If docs/{{feature}}/dry-run-notes.md exists:
        1. Review gaps identified in step plan analysis
        2. Ensure your task breakdowns address them:
           - Add more specific implementation guidance
           - Include error handling where gaps were identified
           - Add context references for unclear areas
        3. Mark gaps as resolved in the Gap Resolution Table
```

### 5.3 S-09 T-02 Routine YAML (Updated)

```yaml
- id: "T-02"
  title: "Create and Validate Routine YAML"
  task_context: |
    Create execution routine files for this feature:
    - routines/{{feature}}/routine.yaml
    - docs/{{feature}}/routine-yaml-format.md

    ... [existing context] ...

    ## Apply Dry-Run Feedback

    If docs/{{feature}}/dry-run-notes.md exists:
    1. Read the Gap Resolution Table and identified gaps
    2. Ensure your routine.yaml incorporates addressing for:
       - Missing task context
       - Validation issues
       - Mapping errors between steps and tasks
    3. Update step/task contexts to be more explicit based on dry-run findings
    4. Mark gaps as resolved in the Gap Resolution Table

    This ensures the generated routine incorporates all dry-run feedback.

    After writing routine.yaml, validate it...
```

---

## Implementation Order

### Step 1: Sub-Agent Infrastructure
1. Create `SubAgentConfig` and `SubAgentResult` models
2. Implement `execute_sub_agent()` in `workflow/service.py`
3. Add sub-agent support to OpenHands (blocking sub-agent loop + return_message tool)
4. Add `--sub-agent` flag support to Codex CLI

**Tests**: `tests/unit/test_sub_agents.py`

### Step 2: Dry-Run Task Generation
1. Create `workflow/dry_run_tasks.py` with prompt generator
2. Update `S-06 T-01` task context to use sub-agents
3. Implement aggregation of sub-agent outputs into final `dry-run-notes.md`

**Tests**: `tests/unit/test_dry_run_tasks.py`

### Step 3: Task List Reset on Re-Entry
1. Add `entry_count` to `StepState`
2. Implement `reset_step_on_re_entry()` in service
3. Call reset on backward transition in engine
4. Update `TransitionTracker` enforcement

**Tests**: `tests/unit/test_backward_transitions.py`, `tests/integration/test_step_reset.py`

### Step 4: Update Routine Instructions
1. Update task contexts for S-04 T-01, S-05 T-01, S-09 T-02 to reference dry-run-notes.md
2. Update S-07 T-01 to verify dry-run gaps are resolved
3. Update routines/idea-to-plan.yaml

**Tests**: Integration test with actual routine execution

### Step 5: Final Integration
1. E2E test: S-01 → S-06 (dry-run) → S-05 (with reset) → S-09 (with feedback)
2. Verify repo state continues but task state resets
3. Verify dry-run-notes marks are applied and tracked

**Tests**: `tests/integration/test_idea_to_plan_full_cycle.py`

---

## Key Files to Create/Modify

### New Files
- `src/orchestrator/agents/sub_agent.py`
- `src/orchestrator/workflow/dry_run_tasks.py`
- `tests/unit/test_sub_agents.py`
- `tests/unit/test_dry_run_tasks.py`
- `tests/unit/test_backward_transitions.py`
- `tests/integration/test_step_reset.py`
- `tests/integration/test_idea_to_plan_full_cycle.py`

### Modified Files
- `src/orchestrator/agents/openhands.py`
- `src/orchestrator/agents/cli.py`
- `src/orchestrator/state/models.py`
- `src/orchestrator/workflow/engine.py`
- `src/orchestrator/workflow/service.py`
- `routines/idea-to-plan.yaml`
- `docs/ARCHITECTURE.md` (add sub-agent section)

---

## Success Criteria

1. ✅ Sub-agents can be invoked from task execution with focused prompts
2. ✅ Dry-run uses sub-agents to generate detailed analysis with full context per task
3. ✅ Dry-run-notes.md is generated with Gap Resolution Table
4. ✅ Steps 5+ task instructions explicitly reference and apply dry-run gaps
5. ✅ Backward transitions reset task checklists but preserve repo state
6. ✅ E2E test: Full idea-to-plan cycle with dry-run feedback loop working

---

## Design Decisions (Answered)

1. **Sub-agent error handling**:
   - When a sub-agent fails (timeout, crash, error), stop it and return the error message to the parent agent
   - Treat it like a failed command call - the parent agent sees the error and can decide to retry, adjust, or fail the task

2. **Return message format**:
   - Just a string (plain text)
   - If the calling agent needs structured output, the requirements go in the sub-agent prompt
   - Simple and flexible

3. **Concurrent sub-agents**:
   - No, not for initial implementation
   - OpenHands switches context to run the sub-agent (blocking, sequential)
   - This is simpler and sufficient for now
   - Can add parallelization later if needed

4. **Gap severity levels**:
   - Base severity on functionality importance:
     - **REQUIRED**: Critical functionality, must be included and resolved
     - **EXPECTED**: Important functionality, should be included and resolved
     - **OPTIONAL**: Nice-to-have, can be deferred with justification
   - In dry-run-notes.md Gap Resolution Table:
     - If severity is REQUIRED or EXPECTED, that gap **must** have a resolution entry before task completion
     - OPTIONAL gaps can be noted but don't block completion

5. **Gap resolution tracking**:
   - LLM manually marks gaps as resolved in the Gap Resolution Table
   - When dry-run is re-run (in future iterations), the LLM searches for gaps again same way as first run
   - If a gap is marked as "resolved" but the LLM finds it still present:
     - Re-add it to the Gap Resolution Table
     - Be more specific about what is still missing
     - This catches false resolutions and refines understanding
   - Creates a feedback loop: identified → attempted fix → re-validated → refined if still missing
