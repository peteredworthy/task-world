# Idea-to-Plan Improvements: Complete Implementation Guide

**Version**: 1.0
**Status**: Ready for Implementation
**Date**: 2026-02-14
**Scope**: Sub-agent infrastructure + Dry-run refactor + Task reset + Feedback loop

This is the complete, self-contained guide for implementing all improvements to the idea-to-plan routine. All context needed is included here.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Design Decisions](#design-decisions)
4. [Phase 1: Sub-Agent Infrastructure](#phase-1-sub-agent-infrastructure)
5. [Phase 2: Dry-Run Task Generation](#phase-2-dry-run-task-generation)
6. [Phase 3: Task Reset on Re-Entry](#phase-3-task-reset-on-re-entry)
7. [Phase 4: Update Routine Instructions](#phase-4-update-routine-instructions)
8. [Phase 5: Integration Testing](#phase-5-integration-testing)
9. [Testing Strategy](#testing-strategy)
10. [File Manifest](#file-manifest)
11. [Success Criteria](#success-criteria)

---

## Executive Summary

### Problem Statement

The idea-to-plan routine has three gaps:

1. **Backward transitions don't clean up task state** - When returning to S-02 (Human Review) from later steps, downstream tasks remain in partial states
2. **Dry-run has context limitations** - 4000-token limit truncates artifacts, making gap detection incomplete for small models
3. **Dry-run gaps aren't integrated into remaining work** - Steps 5+ don't actively resolve identified gaps; dry-run notes are informational only

### Solution Overview

- **Sub-agents for task decomposition**: Break complex tasks (like dry-run) into focused sub-agents, each with full context
- **Living dry-run-notes**: Steps 5+ explicitly resolve gaps from `dry-run-notes.md` and mark them resolved
- **Task state cleanup on re-entry**: Reset checklist items when re-entering a step, but preserve repo state (git history)

### Key Design Principles

1. **Repo state evolves continuously** - Git history/changes never reverted, only task status resets
2. **Sub-agents are blocking** - Sequential context switch, not concurrent (simpler for now)
3. **Dry-run-notes is the feedback loop** - Gap severity (REQUIRED/EXPECTED/OPTIONAL) drives S-05+ work
4. **Manual gap resolution tracking** - LLM marks gaps resolved; re-runs detect false positives

---

## Architecture Overview

### Sub-Agent Execution Model

```
Main Agent (OpenHands/Codex)
    ↓
    ├─ Execute normal task
    ├─ Need sub-task? → Call execute_sub_agent(prompt)
    │  ↓
    │  Sub-Agent Context (same agent type)
    │  ├─ Standard tools (file ops, bash, git, etc.)
    │  ├─ return_message(message: str) tool
    │  └─ Waits for return_message call
    │      ↓
    │      Returns message to parent
    ├─ Continue with returned message/results
    └─ Complete task
```

**Key Points:**
- No concurrency - main agent blocks until sub-agent returns
- Sub-agents are temporary - created, used, destroyed per invocation
- Errors from sub-agent propagate to main agent like command failures
- Sub-agents have no access to task-world tools (keeps them focused)

### Dry-Run Flow (Current vs Proposed)

**Current (S-06):**
```
S-06 T-01: Simulate Execution
  ├─ Build limited context (4000 tokens, truncated)
  ├─ Call LLM with monolithic prompt
  └─ Return single dry-run result
  └─ → dry-run-notes.md (informational, not applied)
```

**Proposed (S-06 with sub-agents):**
```
S-06 T-01: Simulate Execution with Sub-Agents
  ├─ Sub-Agent Task 1: Analyze Step Plans
  │  ├─ Full context: all step files, intent, architecture
  │  └─ → dry-run-step-analysis.md (per-task gaps)
  ├─ Sub-Agent Task 2: Intent Coverage
  │  ├─ Full context: intent, design-questions, step analysis
  │  └─ → dry-run-intent-coverage.md (uncovered requirements)
  ├─ Sub-Agent Task 3: Routine YAML Validation
  │  ├─ Full context: routine.yaml, step files, design-questions
  │  └─ → dry-run-routine-validation.md (schema/mapping errors)
  └─ Sub-Agent Task 4: Synthesis
     ├─ Aggregate all results
     └─ → dry-run-notes.md (Gap Resolution Table)
         ├─ Gap | Severity | Affected Step/Task | Functionality | Resolution
         ├─ Missing error handling | REQUIRED | S-02 T-01 | API comm | (blank initially)
         └─ Unclear validation rules | EXPECTED | S-03 T-02 | Input validation | (blank initially)

S-04 to S-09 (revised):
  └─ Each task now includes:
     ├─ Read dry-run-notes.md if exists
     ├─ For each gap in table:
     │  └─ Update artifacts to address it
     │  └─ Mark with "Resolution: Updated step-XX-plan.md..."
     └─ Checklist: All REQUIRED/EXPECTED gaps must have resolutions
```

### Task State Reset on Re-Entry

```
Scenario: S-04 Step Planning detects conflicts → S-02 Human Review → S-05 Task Breakdown

Step Execution:
  S-04 (Step Planning)
    ├─ T-01: Create Step Plans
    │  ├─ Status: VERIFYING (verifier grades it as "revision needed")
    │  ├─ Checklist: Some items CLOSED, some OPEN
    │  └─ Attempts: [Attempt 1, Attempt 2]
    │
    ├─ Transition check: has_unresolved_conflicts = true
    │  └─ Call reset_step_on_re_entry(step_id="S-03", S-04, S-05)
    │     For each downstream step (S-03, S-04, S-05):
    │       ├─ For each task in step:
    │       │  ├─ Status: ← PENDING (was BUILDING/VERIFYING)
    │       │  ├─ Checklist items: status ← OPEN (was CLOSED)
    │       │  ├─ Current attempt: ← 0
    │       │  └─ Attempts: ← [] (clear history)
    │       └─ Step: entry_count += 1, completed ← false
    │
    ├─ Transition: current_step ← S-02
    │
    S-02 (Human Review)
      └─ Human adds feedback to plan artifacts
      └─ Approves gate
    │
    └─ Transition: current_step ← S-03 (or jump to S-05 as configured)
      S-05 (Task Breakdown)
        └─ All tasks are PENDING with empty attempt history
        └─ Checklist items reset to OPEN
        └─ But: All previous file changes in repo are still there!
        └─ Builder has full context: previous attempts + git history + human feedback

Repo State (Git):
  Before reset: commit history includes all S-04, S-05 attempts
  After reset:  commit history unchanged (git never reverted)
  Builder can: git log, git diff, understand previous attempts
```

---

## Design Decisions

### 1. Sub-Agent Error Handling

**Decision**: When a sub-agent fails (timeout, crash, error), stop execution and return error to parent agent like a failed command.

**Rationale**:
- Simplifies error propagation
- Parent agent can decide to retry, adjust, or fail
- Consistent with other command execution failures

**Implementation**:
```python
async def execute_sub_agent(config, agent_backend) -> SubAgentResult:
    try:
        result = await agent_backend.run_in_sub_agent_mode(
            prompt=config.prompt,
            timeout=config.timeout_seconds,
        )
        # Sub-agent called return_message
        return SubAgentResult(success=True, message=result.message)
    except SubAgentTimeoutError as e:
        return SubAgentResult(success=False, error=f"Timeout: {e}")
    except SubAgentCrashedError as e:
        return SubAgentResult(success=False, error=f"Crashed: {e}")
```

### 2. Return Message Format

**Decision**: Just a plain string. If structured output is needed, requirements go in the sub-agent prompt.

**Rationale**:
- Keeps sub-agent protocol simple
- Prompt can specify format (e.g., "Return JSON with fields x, y, z")
- Parent agent parses based on what it asked for

**Example Prompt**:
```
Return your analysis in this format:
{
  "found_gaps": true,
  "gap_count": 3,
  "gaps": [{"description": "...", "severity": "REQUIRED"}, ...]
}
```

### 3. Concurrent Sub-Agents

**Decision**: No. Sub-agents are sequential/blocking (context switch, not fork).

**Rationale**:
- OpenHands simpler to implement (no threading needed)
- Sequential is sufficient for dry-run use case (Tasks 1-4 are ordered anyway)
- Can add parallelization later if performance needs it

### 4. Gap Severity Levels

**Decision**: REQUIRED, EXPECTED, OPTIONAL based on functionality criticality.

**Definitions**:
- **REQUIRED**: Critical functionality; must be included and resolved (blocks task completion)
- **EXPECTED**: Important functionality; should be included and resolved (failure if multiple unresolved)
- **OPTIONAL**: Nice-to-have; can be deferred with justification (does not block)

**Where This Matters**:
- S-05+: Checklist includes "All REQUIRED/EXPECTED gaps resolved" as verifier rubric
- Dry-run-notes.md: Gap Resolution Table has Severity column
- S-07 Final Check: Verify unresolved REQUIRED/EXPECTED gaps have justification

### 5. Gap Resolution Tracking & Re-Validation

**Decision**: Manual marking by LLM. Re-run of dry-run detects false positives.

**Workflow**:
1. Initial dry-run identifies gaps, marks Resolution column as blank
2. S-04/S-05/S-09 update artifacts, mark gaps resolved with specific action taken
3. (Optional) Re-run dry-run:
   - LLM searches for same gaps using same approach as first run
   - If gap is marked "resolved" but LLM finds it still present → re-add with more specificity
   - Creates iterative refinement loop

**Example in dry-run-notes.md**:
```
| Gap | Severity | Affected Task | Resolution |
|-----|----------|---------------|-----------|
| Missing error handling for timeouts | REQUIRED | S-02 T-01 | Updated task context with specific retry logic |
| Unclear validation rules | EXPECTED | S-03 T-02 | (blank - found again on re-run) |
```

---

## Phase 1: Sub-Agent Infrastructure

### Objective
Create the sub-agent execution protocol and integrate with OpenHands and Codex CLI agents.

### Deliverables
1. Sub-agent models and execution function
2. OpenHands sub-agent support
3. Codex CLI sub-agent support
4. Unit tests

### Implementation

#### 1.1 Create `src/orchestrator/agents/sub_agent.py`

```python
"""Sub-agent protocol and execution.

A sub-agent is a temporary agent spawned to complete a specific task.
Key characteristics:
- Blocking: Parent agent waits for sub-agent to return
- Limited tools: Standard tools + return_message only
- Sequential: No concurrency (context switch, not fork)

Sub-Agent Execution Flow:
1. Parent calls execute_sub_agent(config)
2. Main agent context switches to sub-agent mode
3. Sub-agent receives:
   - Provided prompt
   - Standard tools (file I/O, bash, git, etc.)
   - return_message(message: str) tool
4. Sub-agent executes until:
   - Calls return_message() → parent receives the message
   - Times out → parent receives timeout error
   - Crashes → parent receives error
5. Parent resumes with the returned message
"""

from typing import Protocol
from pydantic import BaseModel, Field
from datetime import datetime

from orchestrator.config.enums import AgentType
from orchestrator.agents.types import ExecutionContext


class SubAgentConfig(BaseModel):
    """Configuration for spawning a sub-agent."""

    prompt: str
    """The task/instructions for the sub-agent to execute."""

    agent_type: AgentType
    """Which agent type to use (OPENHANDS, CODEX_CLI, etc.)."""

    timeout_seconds: int = 300
    """Maximum execution time before killing sub-agent."""

    context_limit: int | None = None
    """Optional token context limit (agent may still exceed for standard tools)."""


class SubAgentResult(BaseModel):
    """Result from a sub-agent execution."""

    success: bool
    """True if sub-agent called return_message, False if error/timeout."""

    message: str | None = None
    """What the sub-agent passed to return_message tool (if success=True)."""

    output: str | None = None
    """Captured output from sub-agent execution."""

    error: str | None = None
    """Error message if sub-agent failed (if success=False)."""

    started_at: datetime | None = None
    """When sub-agent started."""

    completed_at: datetime | None = None
    """When sub-agent completed or timed out."""


class SubAgentBackend(Protocol):
    """Protocol for agent backends to support sub-agent execution."""

    async def execute_as_sub_agent(
        self,
        prompt: str,
        timeout_seconds: int,
    ) -> SubAgentResult:
        """Execute in sub-agent mode.

        Blocks until sub-agent calls return_message or times out.
        """
        ...


async def execute_sub_agent(
    config: SubAgentConfig,
    agent_backend: SubAgentBackend,
) -> SubAgentResult:
    """Execute a sub-agent with a specific prompt.

    Args:
        config: Sub-agent configuration
        agent_backend: The agent backend (OpenHands, Codex, etc.)

    Returns:
        SubAgentResult with success, message, or error

    The sub-agent receives:
    - The provided prompt
    - Standard tools: file operations, bash, git, etc.
    - One special tool: return_message(message: str)

    Execution blocks until:
    - Sub-agent calls return_message → return success=True with message
    - Sub-agent times out → return success=False with timeout error
    - Sub-agent crashes → return success=False with error
    """
    return await agent_backend.execute_as_sub_agent(
        prompt=config.prompt,
        timeout_seconds=config.timeout_seconds,
    )
```

#### 1.2 Update `src/orchestrator/agents/openhands.py`

Add sub-agent support to OpenHands agent.

**Changes needed:**

1. Add `execute_as_sub_agent` method:
```python
async def execute_as_sub_agent(
    self,
    prompt: str,
    timeout_seconds: int,
) -> SubAgentResult:
    """Execute in sub-agent mode (blocking context switch).

    Switches from main agent context to sub-agent context.
    Sub-agent runs with:
    - Provided prompt
    - Standard tools only + return_message
    - No task-world tools

    Blocks main agent loop until sub-agent calls return_message.
    """
    from orchestrator.agents.sub_agent import SubAgentResult

    try:
        # Create sub-agent context
        sub_context = ExecutionContext(
            run_id=self.context.run_id,
            task_id=self.context.task_id,
            prompt=prompt,
            sub_agent_mode=True,  # Flag to disable task-world tools
        )

        # Add return_message tool to tool registry
        tools = self._get_standard_tools()  # No task-world tools
        tools.append(self._build_return_message_tool())

        # Execute in sub-agent mode (blocks)
        result = await self._run_with_tools(
            prompt=prompt,
            tools=tools,
            timeout_seconds=timeout_seconds,
            sub_agent_mode=True,
        )

        # If we reach here with result, sub-agent called return_message
        if result.get("tool_name") == "return_message":
            return SubAgentResult(
                success=True,
                message=result.get("message", ""),
                output=result.get("output"),
            )
        else:
            # Sub-agent completed without calling return_message
            return SubAgentResult(
                success=False,
                error="Sub-agent did not call return_message",
                output=result.get("output"),
            )

    except asyncio.TimeoutError:
        return SubAgentResult(
            success=False,
            error=f"Sub-agent timeout after {timeout_seconds}s",
        )
    except Exception as e:
        return SubAgentResult(
            success=False,
            error=f"Sub-agent failed: {str(e)}",
        )

def _get_standard_tools(self) -> list[dict]:
    """Get standard tools (no task-world tools).

    Includes:
    - File operations (read/write/search)
    - Bash execution
    - Git operations
    - etc.

    Excludes:
    - Task-world specific tools (artifact registry, orchestrator commands, etc.)
    """
    # Return list of standard tool definitions
    # (Implementation details depend on current tool structure)
    pass

def _build_return_message_tool(self) -> dict:
    """Build return_message tool definition.

    This tool ends sub-agent execution and returns message to parent.
    """
    return {
        "type": "function",
        "function": {
            "name": "return_message",
            "description": "Return result to parent agent. This ends sub-agent execution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Message to return to parent agent",
                    }
                },
                "required": ["message"],
            },
        },
    }
```

2. Modify main `execute()` method to handle return_message:
```python
async def execute(self, context: ExecutionContext) -> ExecutionResult:
    """Execute agent task.

    If context.sub_agent_mode is True, run in sub-agent mode with limited tools.
    """
    # ... existing code ...

    # Check if sub-agent mode
    if context.sub_agent_mode:
        # Run sub-agent specific execution path
        tools = self._get_standard_tools()
        tools.append(self._build_return_message_tool())
        # ... rest of sub-agent execution
    else:
        # Normal execution (with all tools)
        tools = self._get_all_tools()
        # ... rest of normal execution
```

#### 1.3 Update `src/orchestrator/agents/cli.py`

Add sub-agent support to Codex CLI agent.

**Changes needed:**

1. Add `execute_as_sub_agent` method that:
   - Passes `--sub-agent` flag to Codex CLI
   - Waits for `return_message` tool call in output
   - Returns SubAgentResult

2. Modify subprocess call:
```python
async def execute_as_sub_agent(
    self,
    prompt: str,
    timeout_seconds: int,
) -> SubAgentResult:
    """Execute as sub-agent via Codex CLI.

    Passes --sub-agent flag to enable sub-agent mode.
    """
    from orchestrator.agents.sub_agent import SubAgentResult

    cmd = [
        "uv", "run", "claude", "--json",
        "--sub-agent",  # Enable sub-agent mode in Codex
        "--timeout", str(timeout_seconds),
    ]

    try:
        result = await self._run_subprocess(
            cmd,
            stdin=prompt,
            timeout_seconds=timeout_seconds,
        )

        # Parse output for return_message tool call
        message = self._extract_return_message(result.stdout)
        if message is not None:
            return SubAgentResult(
                success=True,
                message=message,
                output=result.stdout,
            )
        else:
            return SubAgentResult(
                success=False,
                error="Sub-agent did not call return_message",
                output=result.stdout,
            )
    except asyncio.TimeoutError:
        return SubAgentResult(
            success=False,
            error=f"Sub-agent timeout after {timeout_seconds}s",
        )
    except Exception as e:
        return SubAgentResult(
            success=False,
            error=f"Sub-agent failed: {str(e)}",
        )

def _extract_return_message(self, output: str) -> str | None:
    """Extract return_message value from tool call output.

    Looks for: {"name": "return_message", "arguments": {"message": "..."}}
    """
    import json
    import re

    # Find tool call pattern
    pattern = r'"name":\s*"return_message".*?"message":\s*"([^"]*)"'
    match = re.search(pattern, output)
    if match:
        return match.group(1)
    return None
```

#### 1.4 Create `tests/unit/test_sub_agents.py`

```python
"""Unit tests for sub-agent infrastructure."""

import pytest
from datetime import datetime, timezone

from orchestrator.agents.sub_agent import (
    SubAgentConfig,
    SubAgentResult,
    execute_sub_agent,
)
from orchestrator.config.enums import AgentType


def test_sub_agent_config_validation():
    """Test SubAgentConfig model."""
    config = SubAgentConfig(
        prompt="Do something specific",
        agent_type=AgentType.OPENHANDS,
        timeout_seconds=120,
    )

    assert config.prompt == "Do something specific"
    assert config.agent_type == AgentType.OPENHANDS
    assert config.timeout_seconds == 120


def test_sub_agent_config_defaults():
    """Test SubAgentConfig defaults."""
    config = SubAgentConfig(
        prompt="Task",
        agent_type=AgentType.CODEX_CLI,
    )

    assert config.timeout_seconds == 300
    assert config.context_limit is None


def test_sub_agent_result_success():
    """Test successful SubAgentResult."""
    result = SubAgentResult(
        success=True,
        message="Analysis complete. Found 3 gaps.",
        output="Tool output captured",
    )

    assert result.success is True
    assert result.message == "Analysis complete. Found 3 gaps."
    assert result.error is None


def test_sub_agent_result_error():
    """Test failed SubAgentResult."""
    result = SubAgentResult(
        success=False,
        error="Timeout: sub-agent exceeded 300s limit",
    )

    assert result.success is False
    assert result.error == "Timeout: sub-agent exceeded 300s limit"
    assert result.message is None


@pytest.mark.asyncio
async def test_execute_sub_agent_success(mock_agent_backend):
    """Test successful sub-agent execution."""
    mock_agent_backend.execute_as_sub_agent.return_value = SubAgentResult(
        success=True,
        message="Task completed",
    )

    config = SubAgentConfig(
        prompt="Analyze the plan",
        agent_type=AgentType.OPENHANDS,
    )

    result = await execute_sub_agent(config, mock_agent_backend)

    assert result.success is True
    assert result.message == "Task completed"


@pytest.mark.asyncio
async def test_execute_sub_agent_timeout(mock_agent_backend):
    """Test sub-agent timeout."""
    mock_agent_backend.execute_as_sub_agent.return_value = SubAgentResult(
        success=False,
        error="Timeout: exceeded 300s",
    )

    config = SubAgentConfig(
        prompt="Long-running task",
        agent_type=AgentType.OPENHANDS,
        timeout_seconds=300,
    )

    result = await execute_sub_agent(config, mock_agent_backend)

    assert result.success is False
    assert "Timeout" in result.error
```

### Testing Checklist

- [ ] `test_sub_agent_config_validation` passes
- [ ] `test_sub_agent_result_success` passes
- [ ] `test_sub_agent_result_error` passes
- [ ] `test_execute_sub_agent_success` passes
- [ ] `test_execute_sub_agent_timeout` passes
- [ ] All unit tests pass: `uv run pytest tests/unit/test_sub_agents.py -v`
- [ ] Type checking passes: `uv run pyright src/orchestrator/agents/sub_agent.py`
- [ ] Format passes: `uv run ruff format src/orchestrator/agents/sub_agent.py`

---

## Phase 2: Dry-Run Task Generation

### Objective
Generate 4 focused sub-agent prompts for dry-run validation and update S-06 routine to use them.

### Deliverables
1. Dry-run task prompt generator
2. Updated S-06 routine structure
3. Aggregation logic for dry-run results
4. Unit tests

### Implementation

#### 2.1 Create `src/orchestrator/workflow/dry_run_tasks.py`

```python
"""Generate and execute dry-run sub-agent tasks.

The dry-run process uses 4 focused sub-agent tasks to thoroughly validate
the planning artifacts without truncation:

1. Step Plan Analysis: Simulate each task, identify gaps
2. Intent Coverage: Verify all intent requirements addressed
3. Routine YAML Validation: Check routine matches step definitions
4. Synthesis: Aggregate all results into dry-run-notes.md
"""

from dataclasses import dataclass
from typing import Any
from pathlib import Path


@dataclass
class DryRunSubAgentTask:
    """Definition of a sub-agent task for dry-run."""

    task_id: str  # "dry-run-1", "dry-run-2", etc.
    title: str
    prompt: str
    output_path: str  # Relative path where results go


def generate_dry_run_sub_agent_prompts(
    feature: str,
    intent_content: str,
    plan_content: str,
    architecture_content: str | None,
    design_questions_content: str | None,
    step_plans: dict[str, str],  # step_id -> content
    routine_yaml_content: str | None = None,
    existing_dry_run_notes: str | None = None,
) -> list[DryRunSubAgentTask]:
    """Generate sub-agent prompts for comprehensive dry-run validation.

    Args:
        feature: Feature name
        intent_content: Content of intent.md
        plan_content: Content of plan.md
        architecture_content: Content of architecture.md (optional)
        design_questions_content: Content of design-questions.md (optional)
        step_plans: Map of step_id to step-XX-plan.md content
        routine_yaml_content: Content of routine.yaml (optional, generated after S-08)
        existing_dry_run_notes: Existing dry-run-notes.md for re-validation

    Returns:
        List of 4 DryRunSubAgentTask objects to be executed sequentially
    """
    tasks = []

    # Task 1: Step Plan Analysis
    task1_prompt = f"""You are validating implementation step plans.

INTENT:
{intent_content}

PLAN:
{plan_content}

ARCHITECTURE:
{architecture_content or "(not provided)"}

DESIGN QUESTIONS:
{design_questions_content or "(none)"}

STEP PLANS:
{_format_step_plans(step_plans)}

TASK: Simulate execution of each step plan's tasks.

For each task in each step plan:
1. Describe what you would do to execute it (with full context)
2. Identify any gaps, unclear requirements, or missing context
3. Note any assumptions being made
4. Identify where functionality might be incomplete

Output as JSON:
{{
  "analysis": [
    {{
      "step_id": "S-02",
      "task_id": "T-01",
      "task_title": "Generate Initial Artifacts",
      "simulation": "What would be done...",
      "gaps": [
        {{
          "description": "Missing error handling for...",
          "severity": "REQUIRED|EXPECTED|OPTIONAL",
          "reasoning": "Why this is important"
        }}
      ],
      "unclear_requirements": ["Requirement 1", "Requirement 2"],
      "assumptions": ["Assumption 1"],
      "missing_context": ["Context 1"]
    }}
  ]
}}"""

    tasks.append(
        DryRunSubAgentTask(
            task_id="dry-run-1",
            title="Step Plan Analysis",
            prompt=task1_prompt,
            output_path=f"docs/{feature}/dry-run-step-analysis.md",
        )
    )

    # Task 2: Intent Coverage Check
    task2_prompt = f"""You are checking if implementation step plans cover all intent requirements.

INTENT (what must be accomplished):
{intent_content}

DESIGN QUESTIONS:
{design_questions_content or "(none)"}

STEP PLANS:
{_format_step_plans(step_plans)}

TASK: Verify that all intent requirements are addressed by the step plans.

1. Extract all functional requirements from intent.md
2. For each requirement, trace it to step plans
3. Identify any uncovered requirements
4. Identify any edge cases not addressed
5. Identify any assumptions that might be risky

Output as JSON:
{{
  "requirements_analysis": [
    {{
      "requirement_id": "REQ-001",
      "requirement": "The system must...",
      "covered_by": ["S-02 T-01", "S-04 T-03"],
      "coverage_quality": "FULL|PARTIAL|MISSING",
      "gaps": "What is missing if partially covered"
    }}
  ],
  "uncovered_requirements": ["Req text 1", "Req text 2"],
  "edge_cases": ["Edge case 1: ..."],
  "risky_assumptions": ["Assumption 1: ..."]
}}"""

    tasks.append(
        DryRunSubAgentTask(
            task_id="dry-run-2",
            title="Intent Coverage",
            prompt=task2_prompt,
            output_path=f"docs/{feature}/dry-run-intent-coverage.md",
        )
    )

    # Task 3: Routine YAML Validation (only if routine exists)
    if routine_yaml_content:
        task3_prompt = f"""You are validating a generated routine.yaml against its source step plans.

ROUTINE YAML:
{routine_yaml_content}

STEP PLANS (source of truth):
{_format_step_plans(step_plans)}

DESIGN QUESTIONS:
{design_questions_content or "(none)"}

TASK: Verify the routine.yaml correctly encodes the step plans.

1. For each step in routine.yaml, check it matches the step plan
2. For each task in routine.yaml, check it matches the task in step plan
3. Verify task contexts include sufficient detail
4. Check that requirements are properly encoded
5. Identify any mapping errors or missing details

Output as JSON:
{{
  "validation_results": [
    {{
      "step_id": "S-02",
      "status": "VALID|ISSUES|CRITICAL",
      "issues": [
        {{
          "location": "step S-02, task T-01",
          "issue": "Missing requirement for error handling",
          "severity": "REQUIRED|EXPECTED|OPTIONAL",
          "fix": "Add requirement to routine YAML"
        }}
      ]
    }}
  ],
  "critical_issues": ["Issue 1: ...", "Issue 2: ..."],
  "schema_errors": [],
  "mapping_gaps": []
}}"""

        tasks.append(
            DryRunSubAgentTask(
                task_id="dry-run-3",
                title="Routine YAML Validation",
                prompt=task3_prompt,
                output_path=f"docs/{feature}/dry-run-routine-validation.md",
            )
        )

    # Task 4: Synthesis (always last)
    task4_prompt = f"""You are synthesizing dry-run analysis results.

INTENT:
{intent_content}

DRY-RUN STEP ANALYSIS:
{_placeholder_or_content("Step analysis from previous task")}

DRY-RUN INTENT COVERAGE:
{_placeholder_or_content("Intent coverage from previous task")}

{f'DRY-RUN ROUTINE VALIDATION:' + '\n' + _placeholder_or_content('Routine validation from previous task') if routine_yaml_content else ''}

EXISTING DRY-RUN NOTES (if re-validating):
{existing_dry_run_notes or "(first run)"}

TASK: Synthesize all dry-run findings into a consolidated Gap Resolution Table.

1. Collect all gaps from analysis tasks
2. Deduplicate and categorize by severity
3. Prioritize by functionality importance (REQUIRED > EXPECTED > OPTIONAL)
4. For re-runs: if gap is marked "resolved" but found again, re-add with more specificity
5. Create Gap Resolution Table with columns:
   - Gap Description
   - Severity (REQUIRED|EXPECTED|OPTIONAL)
   - Affected Step/Task
   - Functionality Area
   - Resolution (blank for new gaps, filled as steps 4-9 resolve them)

Output: Markdown-formatted dry-run-notes.md file with:
- Summary section (overall assessment)
- Gap Resolution Table
- Recommendations section

Format each gap entry clearly for tracking resolution."""

    tasks.append(
        DryRunSubAgentTask(
            task_id="dry-run-4",
            title="Synthesis",
            prompt=task4_prompt,
            output_path=f"docs/{feature}/dry-run-notes.md",
        )
    )

    return tasks


def _format_step_plans(step_plans: dict[str, str]) -> str:
    """Format step plans for inclusion in prompts."""
    if not step_plans:
        return "(no step plans provided)"

    parts = []
    for step_id in sorted(step_plans.keys()):
        content = step_plans[step_id]
        parts.append(f"\n## {step_id}\n{content}")

    return "\n".join(parts)


def _placeholder_or_content(text: str) -> str:
    """Placeholder for content from previous sub-agent."""
    # In actual execution, this will be replaced with real content from file
    return f"[{text} will be provided here]"
```

#### 2.2 Update `routines/idea-to-plan.yaml` - S-06 Task

Replace the current S-06 task context with new version that uses sub-agents:

```yaml
- id: "S-06"
  title: "Dry Run"
  type: dry_run
  step_context: |
    Stage 6 from docs/plan-runner/idea_to_plan_stripped.md.
    Simulate execution and identify gaps using focused sub-agent tasks.

    This step generates docs/{{feature}}/dry-run-notes.md with a Gap Resolution
    Table that tracks all identified gaps and their resolutions.

  dry_run:
    target_steps: ["S-05"]  # Validate up to task breakdown
    context_limit: null     # No limit (sub-agents manage their own context)
    report_path: "docs/{{feature}}/dry-run-notes.md"

  tasks:
    - id: "T-01"
      title: "Simulate Execution with Sub-Agents"
      task_context: |
        Execute comprehensive dry-run validation using 4 focused sub-agent tasks.

        The dry-run process will:
        1. Generate 4 focused sub-agent prompts (Step Plan Analysis, Intent Coverage, Routine Validation, Synthesis)
        2. Execute each sub-agent sequentially
        3. Each sub-agent analyzes specific artifacts with full context (no truncation)
        4. Aggregate all results into docs/{{feature}}/dry-run-notes.md

        You should:
        1. Load all planning artifacts:
           - docs/{{feature}}/intent.md
           - docs/{{feature}}/plan.md
           - docs/{{feature}}/design-questions.md
           - docs/{{feature}}/architecture.md (if exists)
           - docs/{{feature}}/step-*-plan.md files
           - routines/{{feature}}/routine.yaml (if exists - created in S-09)

        2. Use invoke_sub_agent() to execute each task:
           - Task 1: Step Plan Analysis (simulate each task, identify gaps)
           - Task 2: Intent Coverage (verify all requirements addressed)
           - Task 3: Routine YAML Validation (if routine.yaml exists)
           - Task 4: Synthesis (aggregate into dry-run-notes.md)

        3. Each sub-agent should return JSON-structured results

        4. Aggregate results into docs/{{feature}}/dry-run-notes.md following template:
           - Summary section (overall assessment, list critical gaps)
           - Gap Resolution Table (Gap | Severity | Affected Step/Task | Functionality | Resolution)
           - Recommendations section

        Reference:
        - docs/planner/templates/dry-run-notes.md
        - docs/plan-runner/dry_run_tasks.py (for task generation)
        - Severity: REQUIRED (critical, must resolve) | EXPECTED (important) | OPTIONAL (nice-to-have)

      requirements:
        - id: "R1"
          desc: "All 4 sub-agent dry-run tasks complete successfully"
          priority: critical
        - id: "R2"
          desc: "Sub-agent results aggregated into docs/{{feature}}/dry-run-notes.md"
          priority: critical
        - id: "R3"
          desc: "Gap Resolution Table includes severity, affected tasks, and blank resolutions"
          priority: critical
        - id: "R4"
          desc: "All REQUIRED/EXPECTED severity gaps are documented"
          priority: expected
        - id: "R5"
          desc: "Recommendations section includes actionable improvements"
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

      auto_verify:
        items:
          - id: "dry_run_exists"
            cmd: "test -f docs/{{feature}}/dry-run-notes.md"
            must: true

      verifier:
        rubric:
          - id: "thoroughness"
            text: "Does dry run identify realistic gaps with concrete severity levels?"
          - id: "coverage"
            text: "Are all REQUIRED/EXPECTED gaps documented?"
          - id: "gap_resolution_table"
            text: "Is Gap Resolution Table clear and well-structured?"
          - id: "recommendations"
            text: "Are recommendations specific and actionable?"

      retry:
        max_attempts: 2

  transitions:
    on_complete: "S-07"
```

#### 2.3 Update `src/orchestrator/workflow/service.py`

Add method to invoke sub-agents from task execution:

```python
async def invoke_sub_agent(
    self,
    run_id: str,
    prompt: str,
    timeout_seconds: int = 300,
) -> SubAgentResult:
    """Invoke a sub-agent from within task execution.

    Uses the run's configured agent type unless overridden.

    Args:
        run_id: The run ID
        prompt: The sub-agent prompt/instructions
        timeout_seconds: How long to wait for sub-agent

    Returns:
        SubAgentResult with success flag and message/error
    """
    from orchestrator.agents.sub_agent import (
        SubAgentConfig,
        execute_sub_agent,
    )

    run = await self._state.get_run(run_id)
    if not run.agent_type:
        raise ValueError(f"Run {run_id} has no agent_type configured")

    config = SubAgentConfig(
        prompt=prompt,
        agent_type=run.agent_type,
        timeout_seconds=timeout_seconds,
    )

    # Get the agent backend
    agent_backend = self._get_agent_backend(run.agent_type)

    # Execute sub-agent
    result = await execute_sub_agent(config, agent_backend)

    return result
```

#### 2.4 Create `tests/unit/test_dry_run_tasks.py`

```python
"""Unit tests for dry-run task generation."""

import pytest

from orchestrator.workflow.dry_run_tasks import (
    DryRunSubAgentTask,
    generate_dry_run_sub_agent_prompts,
)


def test_generate_dry_run_tasks_minimal():
    """Test task generation with minimal inputs."""
    intent = "Build a feature"
    plan = "Step 1: Design\nStep 2: Implement"
    step_plans = {"S-02": "Task 1: ...", "S-03": "Task 2: ..."}

    tasks = generate_dry_run_sub_agent_prompts(
        feature="test-feature",
        intent_content=intent,
        plan_content=plan,
        architecture_content=None,
        design_questions_content=None,
        step_plans=step_plans,
    )

    # Should generate 3 tasks (no routine.yaml = no validation task)
    assert len(tasks) == 3
    assert tasks[0].task_id == "dry-run-1"
    assert tasks[1].task_id == "dry-run-2"
    assert tasks[2].task_id == "dry-run-4"  # Synthesis


def test_generate_dry_run_tasks_with_routine():
    """Test task generation with routine.yaml."""
    intent = "Build feature"
    plan = "Steps"
    step_plans = {"S-02": "Task"}
    routine = "routine:\n  steps: ..."

    tasks = generate_dry_run_sub_agent_prompts(
        feature="test-feature",
        intent_content=intent,
        plan_content=plan,
        architecture_content=None,
        design_questions_content=None,
        step_plans=step_plans,
        routine_yaml_content=routine,
    )

    # Should generate 4 tasks (with validation)
    assert len(tasks) == 4
    assert tasks[2].task_id == "dry-run-3"
    assert "Routine YAML Validation" in tasks[2].title


def test_dry_run_sub_agent_task_structure():
    """Test DryRunSubAgentTask structure."""
    task = DryRunSubAgentTask(
        task_id="dry-run-1",
        title="Analysis",
        prompt="Analyze this",
        output_path="docs/test/output.md",
    )

    assert task.task_id == "dry-run-1"
    assert task.title == "Analysis"
    assert "Analyze this" in task.prompt
    assert task.output_path == "docs/test/output.md"


def test_dry_run_tasks_output_paths():
    """Test that output paths are correctly set."""
    intent = "Build"
    plan = "Plan"
    step_plans = {"S-02": "Tasks"}

    tasks = generate_dry_run_sub_agent_prompts(
        feature="my-feature",
        intent_content=intent,
        plan_content=plan,
        architecture_content=None,
        design_questions_content=None,
        step_plans=step_plans,
    )

    assert tasks[0].output_path == "docs/my-feature/dry-run-step-analysis.md"
    assert tasks[1].output_path == "docs/my-feature/dry-run-intent-coverage.md"
    assert tasks[2].output_path == "docs/my-feature/dry-run-notes.md"
```

### Testing Checklist

- [ ] `test_generate_dry_run_tasks_minimal` passes
- [ ] `test_generate_dry_run_tasks_with_routine` passes
- [ ] `test_dry_run_sub_agent_task_structure` passes
- [ ] `test_dry_run_tasks_output_paths` passes
- [ ] All tests pass: `uv run pytest tests/unit/test_dry_run_tasks.py -v`
- [ ] Type checking passes: `uv run pyright src/orchestrator/workflow/dry_run_tasks.py`
- [ ] Routine YAML validates: `uv run orchestrator --json routines validate routines/idea-to-plan.yaml`

---

## Phase 3: Task Reset on Re-Entry

### Objective
Implement task state cleanup when transitioning backward while preserving repo state.

### Deliverables
1. Task reset logic in state models
2. Reset method in workflow service
3. Backward transition handling in engine
4. Unit and integration tests

### Implementation

#### 3.1 Update `src/orchestrator/state/models.py`

Add entry tracking to `StepState`:

```python
class StepState(BaseModel):
    """Runtime state of a step."""

    id: str = Field(default_factory=generate_id)
    config_id: str
    title: str = ""
    tasks: list[TaskState] = Field(default_factory=lambda: [])
    completed: bool = False
    human_approval: HumanApproval | None = None

    # Entry tracking for cleanup on re-entry
    entry_count: int = 0  # Incremented each time step is entered
    last_entry_at: datetime | None = None
```

#### 3.2 Add to `src/orchestrator/workflow/service.py`

```python
async def reset_step_on_re_entry(
    self,
    run_id: str,
    step_config_id: str,
) -> None:
    """Reset task state when re-entering a step after human feedback.

    This is called when transitioning backward to a step (e.g., S-04 → S-02 → S-05).

    Resets:
    - Task status to PENDING
    - Checklist items to OPEN status
    - Attempt counts to 0
    - Clears attempt history
    - Clears verifier comments and grades
    - Clears pending action/clarification state

    Preserves:
    - Git history (all commits remain)
    - File changes (can be inspected via git)
    - Step entry history (entry_count incremented)

    Purpose: Allow re-work without losing previous context from git.
    """
    run = await self._state.get_run(run_id)
    step_state = next(
        (s for s in run.steps if s.config_id == step_config_id),
        None,
    )

    if not step_state:
        return

    # Reset each task in the step
    for task in step_state.tasks:
        # Reset checklist items back to OPEN
        for item in task.checklist:
            item.status = ChecklistStatus.OPEN
            item.note = None
            item.grade = None
            item.grade_reason = None

        # Reset attempt tracking
        task.current_attempt = 0
        task.attempts.clear()

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

    # Emit event
    self._event_emitter.emit(
        StepResetOnReEntry(
            run_id=run_id,
            step_config_id=step_config_id,
            entry_count=step_state.entry_count,
        )
    )
```

#### 3.3 Update `src/orchestrator/workflow/engine.py`

Add backward transition handling:

```python
async def _evaluate_conditions(
    self,
    run: Run,
    step_config: StepConfig,
) -> tuple[bool, str | None, int]:
    """Evaluate conditional transitions.

    Returns:
        (should_transition, target_step_id, max_iterations)
    """
    if not step_config.transitions or not step_config.transitions.on_condition:
        return False, None, 0

    for condition in step_config.transitions.on_condition:
        # TODO: Implement condition evaluation (has_unresolved_conflicts, etc.)
        # For now, return basic check
        if self._check_condition(condition.condition, run):
            return True, condition.target, condition.max_iterations

    return False, None, 0


async def handle_step_completion(
    self,
    run: Run,
    step_config: StepConfig,
) -> str | None:
    """Handle step completion and conditional transitions.

    Returns:
        Next step_id to transition to, or None if normal progression.
    """
    # Check for conditional transitions (backward)
    should_transition, target_step_id, max_iterations = await self._evaluate_conditions(
        run, step_config
    )

    if should_transition and target_step_id:
        # Check transition limit
        if run.transition_tracker:
            current_step_id = step_config.id
            if not run.transition_tracker.can_transition(
                current_step_id,
                target_step_id,
                max_iterations,
            ):
                raise InvalidTransitionError(
                    f"Cannot transition {current_step_id} → {target_step_id}: "
                    f"max_iterations ({max_iterations}) exceeded"
                )
            run.transition_tracker.record_transition(current_step_id, target_step_id)

        # If backward transition, reset downstream steps
        if self._is_backward_transition(step_config.id, target_step_id, run):
            await self._reset_downstream_steps(run, target_step_id)

        return target_step_id

    # Normal progression
    return None


def _is_backward_transition(
    self,
    current_step_id: str,
    target_step_id: str,
    run: Run,
) -> bool:
    """Check if transition is backward (earlier step in sequence)."""
    current_idx = next(
        (i for i, s in enumerate(run.steps) if s.config_id == current_step_id),
        None,
    )
    target_idx = next(
        (i for i, s in enumerate(run.steps) if s.config_id == target_step_id),
        None,
    )

    if current_idx is None or target_idx is None:
        return False

    return target_idx < current_idx


async def _reset_downstream_steps(
    self,
    run: Run,
    target_step_id: str,
) -> None:
    """Reset all steps from target_step_id forward (after backward transition).

    This clears task state but preserves repo history.
    """
    target_idx = next(
        (i for i, s in enumerate(run.steps) if s.config_id == target_step_id),
        None,
    )

    if target_idx is None:
        return

    # Reset all steps from target_idx onward
    for step_state in run.steps[target_idx:]:
        await self._service.reset_step_on_re_entry(run.id, step_state.config_id)
```

#### 3.4 Create `tests/unit/test_backward_transitions.py`

```python
"""Unit tests for backward transition and step reset logic."""

import pytest
from datetime import datetime, timezone

from orchestrator.config.enums import ChecklistStatus, TaskStatus
from orchestrator.state.models import (
    ChecklistItem,
    Priority,
    Run,
    StepState,
    TaskState,
    Attempt,
)


def test_step_state_entry_count():
    """Test entry count tracking on StepState."""
    step = StepState(
        config_id="S-01",
        title="Test",
    )

    assert step.entry_count == 0
    assert step.last_entry_at is None

    step.entry_count += 1
    step.last_entry_at = datetime.now(timezone.utc)

    assert step.entry_count == 1
    assert step.last_entry_at is not None


def test_transition_tracker_backward():
    """Test TransitionTracker for backward transitions."""
    from orchestrator.state.models import TransitionTracker

    tracker = TransitionTracker()

    # First backward transition S-04 → S-02
    assert tracker.can_transition("S-04", "S-02", max_iterations=3)
    tracker.record_transition("S-04", "S-02")

    # Second time
    assert tracker.can_transition("S-04", "S-02", max_iterations=3)
    tracker.record_transition("S-04", "S-02")

    # Third time
    assert tracker.can_transition("S-04", "S-02", max_iterations=3)
    tracker.record_transition("S-04", "S-02")

    # Fourth time should fail
    assert not tracker.can_transition("S-04", "S-02", max_iterations=3)


@pytest.mark.asyncio
async def test_reset_step_on_re_entry(async_state_manager):
    """Test resetting step state on re-entry."""
    # Create run with task in VERIFYING state
    run = Run(repo_name="test-repo")

    task = TaskState(
        config_id="T-01",
        title="Build",
        status=TaskStatus.VERIFYING,
        current_attempt=2,
    )

    # Add attempt
    task.attempts.append(
        Attempt(
            attempt_num=1,
            started_at=datetime.now(timezone.utc),
        )
    )

    # Add checklist item
    task.checklist.append(
        ChecklistItem(
            req_id="R1",
            desc="Complete",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.CLOSED,
            grade="A",
        )
    )

    step = StepState(
        config_id="S-04",
        title="Step Planning",
        tasks=[task],
    )
    run.steps.append(step)

    # Reset the step
    await reset_step_on_re_entry(run, "S-04")

    # Verify reset
    assert step.entry_count == 1
    assert task.status == TaskStatus.PENDING
    assert task.current_attempt == 0
    assert len(task.attempts) == 0
    assert task.checklist[0].status == ChecklistStatus.OPEN
    assert task.checklist[0].grade is None
```

### Testing Checklist

- [ ] `test_step_state_entry_count` passes
- [ ] `test_transition_tracker_backward` passes
- [ ] `test_reset_step_on_re_entry` passes
- [ ] All tests pass: `uv run pytest tests/unit/test_backward_transitions.py -v`
- [ ] Type checking passes: `uv run pyright src/orchestrator/workflow/engine.py`

---

## Phase 4: Update Routine Instructions

### Objective
Update S-04, S-05, S-09 task instructions to reference and resolve dry-run-notes.md gaps.

### Implementation

#### 4.1 Update S-04 T-01 (Create Step Plans)

In `routines/idea-to-plan.yaml`, update task_context:

```yaml
task_context: |
  Create docs/{{feature}}/step-XX-plan.md files from the implementation plan.

  PLAN:
  {{context.plan}}

  ARCHITECTURE:
  {{context.architecture}}

  Each step plan must include:
  - Purpose and functionality
  - Prerequisites/dependencies
  - Functional contract (inputs/outputs/errors)
  - Verification strategy

  Follow docs/planner/templates/step-plan.md.

  ## Resolve Dry-Run Gaps (NEW)

  If docs/{{feature}}/dry-run-notes.md exists:

  1. **Read the Gap Resolution Table** from dry-run-notes.md
  2. **For each gap in the table**:
     - If severity is REQUIRED or EXPECTED:
       - Update your step plans to address this gap
       - Add requirements, clarifications, or context as needed
       - Be specific: reference which step/task you updated
     - If severity is OPTIONAL:
       - Consider whether to address now or defer
       - If deferring, add justification to plan artifacts
  3. **Mark gaps as resolved** in the Gap Resolution Table:
     - Update the "Resolution" column with specific action taken
     - Example: "Updated step-04-plan.md: Added R3 for error handling"
  4. **Track unresolved gaps**: Any gap without a resolution entry will block task completion

  This ensures dry-run feedback is incorporated into step planning and tracked.
```

#### 4.2 Update S-05 T-01 (Create Step Files)

```yaml
task_context: |
  Convert step plans into docs/{{feature}}/steps/step-XX.md files.

  ... [existing content] ...

  ## Resolve Dry-Run Gaps (NEW)

  If docs/{{feature}}/dry-run-notes.md exists:

  1. **Read identified gaps** from the Gap Resolution Table
  2. **For unresolved gaps from step plan analysis**:
     - Ensure your task breakdowns address them
     - Add more specific implementation guidance
     - Include error handling and edge cases mentioned
     - Add context references for unclear areas
  3. **Mark gaps as resolved**:
     - Update Gap Resolution Table with: "Updated step-XX-plan.md: Added task T-X with specific error handling"
  4. **Verify coverage**: All REQUIRED/EXPECTED gaps must be addressed or explicitly deferred

  This ensures task breakdowns fully address dry-run findings.
```

#### 4.3 Update S-07 T-01 (Cross-Check All Artifacts)

```yaml
task_context: |
  Verify alignment across intent, plan, step files, and dry run output.

  ... [existing content] ...

  ## Dry-Run Notes Verification (NEW)

  If docs/{{feature}}/dry-run-notes.md exists:

  1. **Review Gap Resolution Table**
  2. **For each gap**:
     - Verify it has a "Resolution" entry (not blank)
     - Check that the resolution is concrete (references specific artifact updates)
     - If gap is marked resolved but you suspect it may still be missing:
       - Note this in verification-report.md
       - This may be caught if dry-run is re-run
  3. **Check for unresolved REQUIRED/EXPECTED gaps**:
     - If any lack a resolution entry, add to verification-report.md
     - This should block task completion unless explicitly deferred with justification
  4. **Add to verification-report.md**:
     - "Dry-run gap coverage: X/Y gaps resolved (X REQUIRED, Y EXPECTED, Z OPTIONAL)"

  This ensures accountability for dry-run findings.
```

#### 4.4 Update S-09 T-02 (Create and Validate Routine YAML)

```yaml
task_context: |
  Create execution routine files for this feature:
  - routines/{{feature}}/routine.yaml
  - docs/{{feature}}/routine-yaml-format.md

  Use docs/plan-runner/routine-yaml-format.md as the source format guide.

  The routine must encode the generated steps so another run can execute them.
  Include clear step/task contexts, requirements, artifacts, and verification hooks.

  ## Apply Dry-Run Feedback (NEW)

  If docs/{{feature}}/dry-run-notes.md exists:

  1. **Read the Gap Resolution Table**
  2. **Identify any routine-specific issues**:
     - Check dry-run-routine-validation.md for schema/mapping errors
     - Review if gaps were about task context clarity
  3. **Incorporate feedback into routine.yaml**:
     - Make task contexts more explicit
     - Add requirements if gaps mentioned missing specs
     - Include all resolutions applied in earlier steps
  4. **Mark gaps as resolved**:
     - Update Gap Resolution Table: "Incorporated into routine.yaml with more explicit task context"

  This ensures the generated routine reflects all dry-run feedback.

  After writing routine.yaml, validate it and fix errors until it passes:
  uv run orchestrator --json routines validate routines/{{feature}}/routine.yaml

  If validation fails, use exact error output to correct the YAML structure.
```

### Testing Checklist

- [ ] Updated routines/idea-to-plan.yaml is syntactically valid
- [ ] Run validator: `uv run orchestrator --json routines validate routines/idea-to-plan.yaml`
- [ ] Review all task contexts for dry-run references are clear
- [ ] Updated template dry-run-notes.md matches expectations in task contexts

---

## Phase 5: Integration Testing

### Objective
Test complete flow with all components working together.

### Deliverables
1. E2E integration test
2. Documentation of test scenarios

#### 5.1 Create `tests/integration/test_idea_to_plan_full_cycle.py`

```python
"""Integration tests for complete idea-to-plan cycle with all improvements.

This tests:
1. Sub-agent infrastructure
2. Dry-run with sub-agents generating dry-run-notes.md
3. Task reset on backward transitions
4. Dry-run-notes feedback integration into S-04, S-05, S-09
5. Full E2E workflow from S-01 through S-09
"""

import pytest
import json
from pathlib import Path

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.state.models import Run
from orchestrator.workflow.service import WorkflowService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dry_run_with_sub_agents(
    workflow_service: WorkflowService,
    test_repo: Path,
):
    """Test dry-run generates detailed gaps via sub-agents."""
    # Create run with all artifacts
    run = await workflow_service.create_run(
        routine_id="idea-to-plan",
        config={"feature": "test-feature"},
    )

    # Create test artifacts
    feature_dir = test_repo / "docs" / "test-feature"
    feature_dir.mkdir(parents=True, exist_ok=True)

    (feature_dir / "intent.md").write_text("Build a feature")
    (feature_dir / "plan.md").write_text("Step 1: Design\nStep 2: Implement")
    (feature_dir / "design-questions.md").write_text("Q1: TBD")
    (feature_dir / "architecture.md").write_text("Architecture plan")

    # Create step plans
    (feature_dir / "step-01-plan.md").write_text("Step 1 details")
    (feature_dir / "step-02-plan.md").write_text("Step 2 details")

    # Execute dry-run (S-06)
    await workflow_service.start_task(run.id, "S-06", "T-01")

    # Verify dry-run-notes.md was created
    dry_run_notes = feature_dir / "dry-run-notes.md"
    assert dry_run_notes.exists()

    content = dry_run_notes.read_text()
    assert "Gap Resolution Table" in content or "Gap" in content
    assert "Severity" in content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backward_transition_resets_task_state(
    workflow_service: WorkflowService,
):
    """Test that backward transitions reset task state but preserve repo."""
    run = await workflow_service.create_run(
        routine_id="idea-to-plan",
        config={"feature": "test-feature"},
    )

    # Move to S-04
    await workflow_service.advance_step(run.id, "S-04")

    # Mark some tasks as complete
    step_state = run.steps[3]  # S-04
    for task in step_state.tasks:
        task.status = TaskStatus.VERIFYING
        task.current_attempt = 2

    # Trigger backward transition
    await workflow_service.evaluate_transitions(run.id, "S-04")

    # Verify task state was reset
    for task in step_state.tasks:
        assert task.status == TaskStatus.PENDING
        assert task.current_attempt == 0
        assert len(task.attempts) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dry_run_notes_guide_step_resolution(
    workflow_service: WorkflowService,
    test_repo: Path,
):
    """Test that dry-run-notes.md gaps guide S-04, S-05, S-09 work."""
    run = await workflow_service.create_run(
        routine_id="idea-to-plan",
        config={"feature": "test-feature"},
    )

    feature_dir = test_repo / "docs" / "test-feature"
    feature_dir.mkdir(parents=True, exist_ok=True)

    # Create dry-run-notes.md with gaps
    dry_run_notes = feature_dir / "dry-run-notes.md"
    dry_run_notes.write_text("""# Dry Run Notes

## Gap Resolution Table

| Gap | Severity | Affected Task | Functionality | Resolution |
|-----|----------|---------------|---------------|-----------|
| Missing error handling | REQUIRED | S-02 T-01 | Error handling | |
| Unclear validation rules | EXPECTED | S-03 T-02 | Input validation | |
""")

    # Execute S-04 (should reference dry-run-notes)
    await workflow_service.start_task(run.id, "S-04", "T-01")

    # Verify S-04 context mentions dry-run feedback
    task_context = await workflow_service.get_task_context(run.id, "S-04", "T-01")
    assert "dry-run-notes" in task_context.lower() or "Dry-Run" in task_context

    # Simulate builder marking gaps resolved
    updated_notes = dry_run_notes.read_text()
    updated_notes = updated_notes.replace(
        "| Missing error handling | REQUIRED | S-02 T-01 | Error handling | |",
        "| Missing error handling | REQUIRED | S-02 T-01 | Error handling | Updated step-02-plan.md with error handling |"
    )
    dry_run_notes.write_text(updated_notes)

    # Verify gap was marked resolved
    content = dry_run_notes.read_text()
    assert "Updated step-02-plan.md" in content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_cycle_s01_to_s09(
    workflow_service: WorkflowService,
    test_repo: Path,
):
    """Test complete flow from S-01 Initial Plan through S-09 Execution Ready."""
    run = await workflow_service.create_run(
        routine_id="idea-to-plan",
        config={
            "feature": "e2e-test-feature",
            "idea": "Build a test feature",
            "codebase_context": "Test repo structure",
        },
    )

    assert run.status == RunStatus.DRAFT

    # S-01: Generate initial artifacts
    await workflow_service.execute_step(run.id, "S-01")
    feature_dir = test_repo / "docs" / "e2e-test-feature"
    assert (feature_dir / "intent.md").exists()
    assert (feature_dir / "plan.md").exists()
    assert (feature_dir / "design-questions.md").exists()

    # S-02: Human approval (mock)
    await workflow_service.approve_human_gate(run.id, "S-02", comment="Looks good")

    # S-03: Refine plan
    await workflow_service.execute_step(run.id, "S-03")

    # S-04: Create step plans
    await workflow_service.execute_step(run.id, "S-04")
    assert (feature_dir / "step-01-plan.md").exists()

    # S-05: Task breakdown
    await workflow_service.execute_step(run.id, "S-05")
    assert (feature_dir / "steps").exists()

    # S-06: Dry run
    await workflow_service.execute_step(run.id, "S-06")
    assert (feature_dir / "dry-run-notes.md").exists()

    # S-07: Final check
    await workflow_service.execute_step(run.id, "S-07")
    assert (feature_dir / "verification-report.md").exists()

    # S-08: Final approval
    await workflow_service.approve_human_gate(run.id, "S-08", comment="Approved")

    # S-09: Execution ready
    await workflow_service.execute_step(run.id, "S-09")
    assert (test_repo / "routines" / "e2e-test-feature" / "routine.yaml").exists()
    assert (feature_dir / "plan-summary.md").exists()

    # Verify routine YAML is valid
    routine_path = test_repo / "routines" / "e2e-test-feature" / "routine.yaml"
    result = await workflow_service.validate_routine(routine_path)
    assert result.valid
```

### Testing Checklist

- [ ] Create test environment with minimal routine setup
- [ ] `test_dry_run_with_sub_agents` passes
- [ ] `test_backward_transition_resets_task_state` passes
- [ ] `test_dry_run_notes_guide_step_resolution` passes
- [ ] `test_full_cycle_s01_to_s09` passes
- [ ] All integration tests pass: `uv run pytest tests/integration/test_idea_to_plan_full_cycle.py -v`

---

## Testing Strategy

### Unit Tests (Fast, Isolated)

**Phase 1 Sub-Agents:**
- `tests/unit/test_sub_agents.py` - Sub-agent models, config, result structures

**Phase 2 Dry-Run:**
- `tests/unit/test_dry_run_tasks.py` - Prompt generation, task structure

**Phase 3 Reset:**
- `tests/unit/test_backward_transitions.py` - Step reset logic, transition tracking

### Integration Tests (Slow, Real Dependencies)

**Phase 5:**
- `tests/integration/test_idea_to_plan_full_cycle.py` - End-to-end workflow

### Manual Testing

After implementation, manually test:
1. Create idea-to-plan run with a test feature
2. Progress through S-01 to S-06 (dry-run)
3. Verify dry-run-notes.md is generated
4. Check that gaps are identified with severity levels
5. Progress to S-04 and verify task context mentions dry-run feedback
6. Mark gaps as resolved and continue to S-09
7. Verify routine.yaml is created and valid

---

## File Manifest

### New Files to Create

```
src/orchestrator/agents/sub_agent.py
src/orchestrator/workflow/dry_run_tasks.py
tests/unit/test_sub_agents.py
tests/unit/test_dry_run_tasks.py
tests/unit/test_backward_transitions.py
tests/integration/test_step_reset.py
tests/integration/test_idea_to_plan_full_cycle.py
```

### Files to Modify

```
src/orchestrator/agents/openhands.py
  - Add execute_as_sub_agent() method
  - Add _get_standard_tools() helper
  - Add _build_return_message_tool() helper
  - Modify execute() to handle sub_agent_mode

src/orchestrator/agents/cli.py
  - Add execute_as_sub_agent() method
  - Add --sub-agent flag support
  - Add _extract_return_message() helper

src/orchestrator/state/models.py
  - Add entry_count to StepState
  - Add last_entry_at to StepState

src/orchestrator/workflow/engine.py
  - Add _evaluate_conditions() method
  - Add handle_step_completion() method
  - Add _is_backward_transition() helper
  - Add _reset_downstream_steps() method

src/orchestrator/workflow/service.py
  - Add invoke_sub_agent() method
  - Add reset_step_on_re_entry() method

routines/idea-to-plan.yaml
  - Update S-06 type and dry_run config
  - Update S-06 T-01 task context (use sub-agents)
  - Update S-04 T-01 task context (resolve dry-run gaps)
  - Update S-05 T-01 task context (resolve dry-run gaps)
  - Update S-07 T-01 task context (verify gaps resolved)
  - Update S-09 T-02 task context (apply dry-run feedback)

docs/planner/templates/dry-run-notes.md
  - Updated with Gap Resolution Table structure
  - Added severity levels and example entries

docs/ARCHITECTURE.md
  - Add Sub-Agent section explaining blocking model
  - Update Dry-Run section referencing new sub-agent approach
```

---

## Success Criteria

### Phase 1: Sub-Agent Infrastructure
- ✅ SubAgentConfig, SubAgentResult models defined
- ✅ execute_sub_agent() function implemented
- ✅ OpenHands has execute_as_sub_agent() with return_message tool
- ✅ Codex CLI has --sub-agent flag support
- ✅ All unit tests pass
- ✅ Type checking clean
- ✅ Format checking clean

### Phase 2: Dry-Run Task Generation
- ✅ 4 focused sub-agent prompts generated (Analysis, Coverage, Validation, Synthesis)
- ✅ S-06 routine updated to use sub-agents
- ✅ dry-run-notes.md generated with Gap Resolution Table
- ✅ All gaps have severity levels
- ✅ All unit tests pass
- ✅ Routine YAML validates

### Phase 3: Task Reset on Re-Entry
- ✅ StepState tracks entry_count
- ✅ reset_step_on_re_entry() resets checklist items only
- ✅ Backward transitions trigger reset
- ✅ TransitionTracker enforces max_iterations
- ✅ Git history preserved (no repo state revert)
- ✅ All unit tests pass
- ✅ Integration tests pass

### Phase 4: Update Routine Instructions
- ✅ S-04 T-01 references dry-run-notes.md
- ✅ S-05 T-01 references dry-run-notes.md
- ✅ S-07 T-01 verifies gaps resolved
- ✅ S-09 T-02 applies dry-run feedback
- ✅ Routine YAML validates
- ✅ Task contexts mention gap resolution requirement

### Phase 5: Integration Testing
- ✅ E2E test S-01 through S-09 passes
- ✅ Dry-run creates gaps with severity
- ✅ Backward transitions reset state properly
- ✅ Dry-run notes guide S-04/S-05/S-09 work
- ✅ Manual testing confirms end-to-end workflow
- ✅ System runnable and tests pass after each phase

---

## Quick Reference

**To implement Phase 1 right now, start with:**
1. Create `src/orchestrator/agents/sub_agent.py` (models + execute function)
2. Update `src/orchestrator/agents/openhands.py` (add execute_as_sub_agent)
3. Update `src/orchestrator/agents/cli.py` (add --sub-agent support)
4. Create `tests/unit/test_sub_agents.py` (unit tests)
5. Run tests: `uv run pytest tests/unit/test_sub_agents.py -v`
6. Type check: `uv run pyright src/orchestrator/agents/sub_agent.py`
7. Format: `uv run ruff format src/orchestrator/agents/`

Then move to Phase 2, 3, 4, 5 following the same pattern.

**All decisions finalized. All context included. Ready to code.**
