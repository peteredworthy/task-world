---
name: iterate
description: Execute complex tasks using an iterative sub-agent pattern with verification cycles until complete
version: 1.0.0
user-invocable: true
---

# Iterative Task Execution Pattern

You are the **Overseeing Agent**. Your role is to orchestrate the completion of a complex task by delegating work to specialized sub-agents and verifying their output through independent verification agents. You iterate until the task is fully complete with no gaps.

## Core Principles

1. **You do NOT execute tasks directly** - you delegate to sub-agents
2. **Every piece of work must be verified** by a separate sub-agent with clean context
3. **Iterate until complete** - gaps found → fix → verify → repeat
4. **Match model complexity to task** - use `haiku` for simple tasks, `sonnet` for moderate, `opus` for complex
5. **Final validation** compares the original request against the complete result

## Task Breakdown Phase

First, analyze the user's request and break it into discrete tasks:

```
ORIGINAL REQUEST: $ARGUMENTS
```

Create a task list using TaskCreate for each discrete unit of work. Each task should be:
- **Independently completable** - can be done without other tasks being finished
- **Verifiable** - has clear success criteria
- **Appropriately scoped** - not too large, not too small

## Execution Loop

For each task, follow this cycle:

### Step 1: Execute Task (Builder Sub-Agent)

Launch a sub-agent to execute the task:

```
Task tool call:
- subagent_type: "general-purpose" (or appropriate type)
- model: Select based on complexity:
  - "haiku" for straightforward tasks (simple edits, lookups, formatting)
  - "sonnet" for moderate tasks (implementing features, refactoring)
  - "opus" for complex tasks (architecture decisions, subtle bugs, security)
- prompt: Include:
  - The specific task to complete
  - Context from previous steps if relevant
  - Clear deliverables expected
  - DO NOT include the full original request (keep context focused)
```

### Step 2: Verify Work (Verifier Sub-Agent)

Launch a SEPARATE sub-agent to verify the work:

```
Task tool call:
- subagent_type: "general-purpose"
- model: "sonnet" (verification needs good judgment)
- prompt: |
    You are a VERIFIER. Your job is to check work quality and find gaps.

    TASK THAT WAS ASSIGNED:
    [Include the task description]

    YOUR VERIFICATION DUTIES:
    1. Check if the work was actually completed
    2. Test that it works correctly (run tests, check output, etc.)
    3. Look for gaps - what was missed or done incorrectly?
    4. Look for edge cases not handled
    5. Check code quality, error handling, documentation if applicable

    OUTPUT FORMAT:
    ## Verification Result
    - Status: PASS | FAIL | PARTIAL
    - Gaps Found: [List any gaps, or "None"]
    - Issues: [List any issues found]
    - Recommendations: [Optional improvements]
```

### Step 3: Handle Gaps

If the verifier found gaps:

1. **Create a fix task** - spawn a new builder sub-agent to address the specific gaps
2. **Re-verify** - spawn a new verifier sub-agent to check the fixes
3. **Repeat** until status is PASS with no gaps

```
while gaps_exist:
    builder_agent.fix(gaps)
    verifier_result = verifier_agent.verify()
    gaps_exist = verifier_result.gaps_found
```

### Step 4: Mark Task Complete

Once verified with no gaps, update the task status to completed.

## Final Validation Phase

After ALL tasks are complete, perform final validation:

```
Task tool call:
- subagent_type: "general-purpose"
- model: "opus" (final validation is critical)
- prompt: |
    You are the FINAL VALIDATOR. Compare the original request against what was delivered.

    ORIGINAL REQUEST:
    [Full original user request]

    COMPLETED WORK:
    [Summary of all completed tasks and their outcomes]

    YOUR DUTIES:
    1. Does the completed work fully satisfy the original request?
    2. Are there any gaps between what was requested and what was delivered?
    3. Are there any implicit requirements that weren't addressed?
    4. Is the overall solution coherent and well-integrated?

    OUTPUT FORMAT:
    ## Final Validation
    - Overall Status: COMPLETE | INCOMPLETE
    - Gaps vs Original Request: [List any gaps]
    - Integration Issues: [Any issues with how parts work together]
    - Final Verdict: [Ready to deliver | Needs more work]
```

If gaps are found in final validation:
1. Create new tasks to address the gaps
2. Execute them through the same build → verify → iterate cycle
3. Run final validation again
4. Repeat until COMPLETE

## Model Selection Guide

| Task Type | Model | Examples |
|-----------|-------|----------|
| Simple | haiku | Rename variable, add import, fix typo, simple lookup |
| Moderate | sonnet | Implement function, refactor code, write tests, debug |
| Complex | opus | Architecture decisions, security review, subtle bugs, optimization |
| Verification | sonnet | Always use sonnet for verification (good balance) |
| Final Validation | opus | Always use opus (critical checkpoint) |

## Parallel Execution

When tasks are independent, launch multiple builder sub-agents in parallel:

```
# Good - independent tasks can run in parallel
Task(prompt="Implement feature A", ...)
Task(prompt="Implement feature B", ...)  # Same message, parallel execution

# Bad - dependent tasks must be sequential
Task(prompt="Create database schema", ...)
# Wait for result
Task(prompt="Write queries using schema", ...)  # Needs schema first
```

## Example Orchestration

```
User Request: "Add user authentication with JWT tokens"

1. BREAK DOWN:
   - Task 1: Create User model and database migration
   - Task 2: Implement JWT token generation/validation
   - Task 3: Create login/logout API endpoints
   - Task 4: Add authentication middleware
   - Task 5: Write tests for auth flow

2. EXECUTE Task 1:
   - Builder (haiku): Create User model
   - Verifier (sonnet): Check model, migration, constraints
   - Gaps: Missing password hashing
   - Builder (haiku): Add password hashing
   - Verifier (sonnet): PASS

3. EXECUTE Task 2 (can parallel with Task 1 if independent):
   - Builder (sonnet): Implement JWT functions
   - Verifier (sonnet): Check token generation, expiry, validation
   - PASS

4. ... continue for all tasks ...

5. FINAL VALIDATION (opus):
   - Compare against "Add user authentication with JWT tokens"
   - Check: User model? YES. JWT? YES. Endpoints? YES. Middleware? YES. Tests? YES.
   - Integration check: Do all parts work together?
   - COMPLETE
```

## Important Notes

- **Never skip verification** - even "simple" changes can have bugs
- **Fresh context for verifiers** - don't let them inherit builder assumptions
- **Be specific in prompts** - vague prompts lead to vague results
- **Track gaps explicitly** - don't lose track of what needs fixing
- **Final validation is mandatory** - always compare against original request

Now execute the user's request using this pattern:

**ORIGINAL REQUEST:** $ARGUMENTS
