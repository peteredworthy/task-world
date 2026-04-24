# Large Task Delivery: Incremental Oversight Loop

**Date:** 2026-04-19
**Status:** Proposed operating model

## Purpose

This document describes how to handle large, ambiguous, or high-risk tasks without relying on a single "plan the whole thing, then execute the whole thing" pass.

The core conclusion is that the current two-step pattern:

1. create a full implementation plan for a complex unknown
2. execute that plan

works poorly once the task is broad enough that important facts are only discovered during implementation. In those cases, the planning phase is asked to infer too much before any real code, tests, or runtime evidence exist.

The better model is an **oversight loop**:

1. plan one bounded slice
2. implement it
3. verify it with real evidence
4. inspect what was learned
5. plan the next slice using that evidence

The key role of planning changes under this model. Planning is no longer primarily about predicting the full end state. It is primarily about producing:

- a bounded next increment
- executable requirement checks
- explicit stop conditions
- evidence to collect before the next planning cycle

## Why The Current Mode Fails On Large Tasks

The present planning flow is strongest when the work is already well understood and can be decomposed cleanly up front. It weakens when the task contains unknowns in architecture, frontend behavior, integration wiring, testability, or environment constraints.

The common failure modes are:

- The planner decomposes horizontally by area rather than vertically by working slice.
- The planner generates a large amount of YAML before proving that the first slice is executable.
- Verification becomes detached from the running system and confirms existence rather than effective behavior.
- Tests validate a shim, isolated helper, or static assumption rather than the real frontend or live wiring.
- Dead code survives because the plan optimizes for "complete all areas" instead of "prove one real path end-to-end."
- The implementation routine continues even when observed behavior suggests the assumed bug may not exist.

For large tasks, those are not incidental failures. They are the predictable result of forcing too much certainty into the initial planning pass.

## Design Principles

Any improved large-task workflow should enforce these principles.

### 1. Slice Before Area

The first unit of delivery should be a narrow end-to-end slice that exercises the real path. Do not start with "frontend area," "backend area," and "tests area" as independent streams unless a working vertical slice already exists.

### 2. Real Verification Before Expansion

Each slice must end with a real verification point. For frontend work, that means checking actual UI behavior, not only a shim or abstraction around it. For integration work, that means confirming live wiring, not only helper existence.

### 3. Evidence Must Change The Next Plan

If implementation reveals that:

- the bug is not reproducible
- the behavior is correct
- the environment cannot support the planned verification
- the chosen seam is wrong

then the next planning cycle must change. A planning system that merely continues the original decomposition is not learning from evidence.

### 4. Planning Should Produce Checks, Not Predictions

The most valuable output of a planning phase is not a complete forecast of all future work. It is a precise set of checks for the next increment:

- what user-visible behavior should change
- what test should fail first
- what evidence counts as success
- what would invalidate the assumption behind the slice

### 5. Escalate Unknowns Early

A slice should be allowed to end in "need clarification," "bug not confirmed," or "environment gap" rather than forcing implementation to proceed as if the premise were already validated.

## Use What Already Exists

The current orchestrator already has useful primitives for this style of work.

### Existing Strengths

- Runs already execute in isolated worktrees.
- Routines already support steps, tasks, gates, retries, transitions, and auto-verify behavior.
- The system already supports pause, clarification, approval, and resume flows.
- The platform already separates builder and verifier phases, which is useful if the verifier is given better evidence requirements.

These features are enough to support an initial oversight loop without a large architectural rewrite.

### Current Gaps

The current system does not yet give first-class support to a parent controller that can:

- create a child run
- wait for completion or pause
- inspect produced evidence in a structured way
- decide what the next routine should be
- iterate automatically across multiple plan and implementation cycles

That means the near-term solution should not depend on a single long-lived LLM session holding the full strategy in memory. It should use short, bounded runs coordinated by an external driver.

## Recommended Operating Model

The recommended near-term operating model is:

1. use the current routine system to generate or execute one bounded slice at a time
2. use a strong external LLM as a meta-review layer between slices
3. have an external script coordinate the handoff between planning and implementation runs
4. only add first-class in-product parent/child orchestration after this approach has proven itself

This is better than a single long-running session because it keeps context small, makes evidence inspection explicit, and avoids having one agent improvise a multi-hour strategy without disciplined checkpoints.

## Phased Delivery Plan

The phases below are ordered so that each stage can be completed and tested before the next one is attempted.

## Phase 1: Strengthen The Planning Contract

### Goal

Adjust the planning routine so it produces **bounded, evidence-driven increments** rather than a full decomposition of the entire problem.

### What Changes

The "Idea to Implementation Plan (YAML Step File)" routine should be changed so that for large or uncertain tasks it does not attempt to fully author the entire implementation routine in one go. Instead, it should produce a first executable slice plus the checks needed to validate whether that slice was the right choice.

The planning routine should explicitly require:

- a single next slice with a small blast radius
- the exact assumption being tested
- the specific failing behavior or missing proof being targeted
- the minimum real verification needed
- the conditions that should stop further execution and trigger replanning
- the evidence artifacts to capture for the next planning cycle

### What The Planner Should Stop Doing

- Do not pre-split the whole problem into broad areas unless the first slice already proves the decomposition is valid.
- Do not emit many step YAML files before one path has been executed successfully.
- Do not assume a bug exists unless the slice includes a way to confirm it.
- Do not accept shim-only or helper-only tests as proof of frontend correctness.

### Best Mechanism

This phase should be done by **improving the existing planning routine**. That is the cheapest place to change behavior and the best place to establish the new contract.

For especially complex requests, a **powerful external LLM can draft the YAML directly** for the first slice, but the target should still be that the planning routine can produce a good bounded slice on its own.

### Success Criteria

- Given a large task, the planner produces one small vertical slice rather than a broad area split.
- The plan includes explicit "replan if..." conditions.
- The plan defines how to tell whether the reported bug is real, absent, or already fixed.
- The plan names the real execution surface to test, especially for frontend work.

## Phase 2: Introduce Plan -> Implement -> Evaluate Cycling

### Goal

Replace the single monolithic plan/execute flow with repeated plan/implement/evaluate pairs.

### What Changes

Instead of:

1. create the whole plan
2. execute the whole plan

the process becomes:

1. create a routine for slice N
2. execute slice N
3. collect results and evidence
4. review the results
5. generate slice N+1 only after that review

This keeps planning grounded in implementation evidence and prevents the system from continuing down a wrong path merely because that path was in the original plan.

### Best Mechanism

This phase should be driven by **an external coordinator script**, not by one long-running LLM session.

The script should:

- invoke Codex, Claude Code, or another strong model to draft or review a slice routine
- create or start the corresponding orchestrator run
- poll until the run completes, fails, or pauses
- gather run artifacts, outputs, and verification results
- invoke the strong model again to critique outcomes and decide the next slice

This is the cleanest short-term way to achieve iterative oversight with the current toolset.

### Why An External Script Is Preferred

- It gives durable control flow without relying on one model session staying coherent.
- It can wait on long-running routines safely.
- It can enforce stage boundaries between planning, execution, and review.
- It makes each model invocation narrow and evidence-based.

### Success Criteria

- A second slice is materially different when the first slice reveals new facts.
- The loop can stop and reframe the problem when the original assumption is wrong.
- The process never requires pre-authoring the entire implementation routine.

## Phase 3: Add Meta-Review Before Wider Rollout

### Goal

Use an external strong LLM as a deliberate quality gate on both the planning routine and the generated slice routines.

### What Changes

Before trusting the execution of a newly generated routine, have a large-capability model review:

- whether the slice is actually incremental
- whether the checks hit the real behavior
- whether the plan can detect "bug not found" as a valid outcome
- whether the routine tries to do too much before proving anything
- whether the verification is likely to produce dead-code false positives

This is effectively a meta-layer that tunes the planning routine by reviewing its outputs against real execution outcomes.

### Best Mechanism

This phase is best handled by **the external oversight script plus a strong external LLM**. The review can feed back in two ways:

- revise the generated slice routine before execution
- revise the planning routine itself when repeated failures show a systematic planning flaw

### Why This Matters

A planning routine usually does not fail because it cannot write YAML. It fails because it encodes the wrong planning heuristics. The fastest way to improve those heuristics is to compare planned slices with actual execution outcomes and revise the planner accordingly.

### Success Criteria

- Repeated plan reviews converge toward smaller, better verified slices.
- The planner becomes less likely to generate area-based decomposition for uncertain tasks.
- Dead code and non-real verification become less frequent in downstream runs.

## Phase 4: Standardize Evidence And Evaluation

### Goal

Make the output of each slice predictable enough that later planning can consume it without needing to reconstruct what happened from scratch.

### What Changes

Each slice should produce a standard evidence bundle, for example:

- summary of the assumption tested
- commands run
- test results
- whether the target bug was reproduced
- whether the real frontend path was exercised
- files changed
- open uncertainties
- recommendation for next slice

The important point is not the exact schema. The important point is that the next planning cycle receives structured evidence rather than a loose natural-language summary.

### Best Mechanism

This can start as **convention in the planning and implementation routines**. It does not require new core features initially.

Later, if it proves useful, this can become a formal artifact type in the orchestrator.

### Success Criteria

- A reviewer can understand why the slice passed or failed without rereading the entire run.
- The next planner can consume the evidence directly.
- The system can distinguish "verified fix," "bug not reproduced," and "environment blocked."

## Phase 5: Add First-Class Parent/Child Orchestration Only After The Loop Proves Itself

### Goal

Once the external oversight loop has shown good results, add native support for orchestrating multiple plan/implementation cycles inside the platform.

### What Changes

Potential future additions include:

- create child run tool
- wait for child run completion tool
- structured evidence retrieval APIs
- promotion of review artifacts to first-class run outputs
- parent run state that tracks slice history and next-action decisions

These are valuable features, but they should not be built first. They should follow proven operating practice rather than guesswork.

### Best Mechanism

This phase should be done by **new orchestrator features**, informed by what worked in the external script.

### Success Criteria

- Native orchestration reproduces the successful behavior of the external loop.
- The product now supports large-task execution as a series of supervised increments rather than one large speculative plan.

## What Should Perform Each Phase

The table below gives the practical recommendation for who or what should carry each phase.

| Phase | Primary mechanism | Why |
|---|---|---|
| Phase 1: strengthen planning contract | Existing "Idea to Implementation Plan ..." routine | Lowest-cost change; fixes the planning heuristic directly |
| Phase 2: plan/implement/evaluate cycling | External script coordinating routine runs | Current platform lacks first-class child-run orchestration |
| Phase 3: meta-review and planner tuning | Strong external LLM reviewing routines and outcomes | Best way to tune planning behavior from evidence |
| Phase 4: standardize evidence | Existing routines first, later platform support if justified | Can start with conventions before adding product complexity |
| Phase 5: native oversight orchestration | New orchestrator features | Only worth building after the external loop proves the model |

## How To Test Whether This New Way Of Working Is Effective

The process itself must be tested, not only the code it produces.

### Test 1: Planning Shape Test

Feed the planner several large, uncertain tasks and inspect the generated routines.

Pass criteria:

- the first output is a bounded slice
- the routine contains explicit disconfirmation checks
- the routine avoids broad area decomposition before proving a working path

Fail criteria:

- it produces a full many-step implementation plan immediately
- it assumes bug existence without proof
- it uses indirect tests as the main evidence for real behavior

### Test 2: First-Slice Execution Test

Run the first slice and inspect what it proves.

Pass criteria:

- it reaches a real yes/no result on one key assumption
- it produces enough evidence to choose the next slice
- it can stop with "assumption wrong" rather than forcing progress

Fail criteria:

- it makes broad code changes without resolving a key uncertainty
- it passes verification while still leaving real behavior unknown

### Test 3: Replanning Responsiveness Test

After slice 1 finishes, compare slice 2 to slice 1's outcomes.

Pass criteria:

- slice 2 is clearly shaped by observed evidence
- the approach changes when the first assumption is invalidated

Fail criteria:

- slice 2 looks like a prewritten continuation of the original plan
- the system ignores evidence that the chosen seam or bug hypothesis was wrong

### Test 4: Dead-Code Resistance Test

Intentionally choose tasks where dead code is a plausible failure mode and check whether the plan demands wiring verification and real-path confirmation.

Pass criteria:

- verification checks require live-path confirmation
- frontend tasks verify the actual frontend behavior
- helper-only tests are treated as insufficient unless explicitly framed as preparatory work

### Test 5: Cost And Throughput Test

Measure whether the iterative loop is affordable in time and model cost.

Pass criteria:

- each cycle is small and explainable
- failures are contained within one slice
- the total cost of reaching a correct solution is lower than repeated rework from a bad monolithic plan

## Practical External Script Design

The external coordinator does not need to be complicated. It mainly needs to provide durable sequencing.

### Minimum Behavior

1. read the current task, constraints, and known evidence
2. invoke a strong model to generate or review the next slice routine
3. create and start the run
4. poll the run until it completes, fails, or pauses
5. collect outputs, artifacts, logs, and verification evidence
6. invoke the strong model again to judge:
   - was the slice incremental enough
   - did it test the real behavior
   - what should the next slice be
   - should the planning routine itself be adjusted
7. repeat until the objective is met or reframed

### Important Guardrails

- The script should cap the scope of any single slice.
- The script should refuse to continue if the previous slice did not produce usable evidence.
- The script should preserve the review output so planner-tuning decisions are traceable.
- The script should distinguish execution failure from assumption failure.

### Why This Is Better Than A Long-Running Session

- The model does not need to remember the entire campaign.
- Each review starts from artifacts and evidence, not stale conversational context.
- Long waits are handled by the script, not by a model session drifting over time.
- Planner changes can be introduced between slices cleanly.

## Concrete Changes Needed In The Planning Routine

If the goal is to improve the existing "Idea to Implementation Plan (YAML Step File)" routine, the main adjustments are:

### Add A Task Classification Gate

The planner should first classify the work as:

- small and well understood
- medium but decomposable
- large or uncertain

Only the first two categories should permit broad up-front decomposition. Large or uncertain work should default to a first-slice routine.

### Require An Assumption Ledger

For each slice, the planner should state:

- what is assumed
- how it will be tested
- what result would invalidate it

### Require Real-Surface Verification

The planner should name the real execution surface being verified:

- real frontend interaction
- live prompt path
- actual service wiring
- concrete API response path

This prevents "tests exist" from being treated as enough.

### Require A Replan Trigger

The routine should explicitly define conditions like:

- bug not reproduced
- expected seam not present
- environment cannot support intended verification
- helper proved correct but user-visible behavior still not checked

If one of these occurs, the workflow should stop and produce evidence for a new planning cycle.

### Forbid Full Fan-Out Until A Slice Passes

For large or uncertain work, the routine should not generate a full set of execution step files up front. It should unlock wider decomposition only after the first slice has:

- executed successfully
- produced real evidence
- shown that the decomposition is valid

## Recommendation

The best near-term path is:

1. adjust the current planning routine so it emits first-slice, evidence-driven routines for large or uncertain tasks
2. use an external script to coordinate plan -> run -> review cycles
3. use a strong external LLM as the meta-review layer that critiques both produced routines and the planning routine itself
4. standardize evidence artifacts from each slice
5. only then consider adding native parent/child orchestration support

This keeps changes incremental, testable, and grounded in real execution results. It also avoids building new platform machinery before there is confidence in the operating model it is meant to support.
