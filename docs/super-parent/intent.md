# Super Parent Orchestration

## Job To Be Done

The Super Parent capability lets a user give one high-level instruction, then have the orchestrator turn that instruction into a sequence of bounded, verifiable child runs until the original job is complete or the system has a clear reason to stop.

Example input:

```text
Fix all of the bugs in docs/better-tests/test-strategy-improvements.md
```

The user should not have to manually decompose that instruction into routines, start each routine, inspect every child result, and decide the next slice. The Super Parent owns that loop. It plans the next useful slice, creates a temporary embedded child routine, starts the child run, waits for a terminal or paused outcome, collects evidence, evaluates whether the evidence changed the remaining work, and either continues, replans, asks for human input, or stops.

This is a specification for the desired behavior and contracts. It is not an implementation plan.

## Scope

The Super Parent is responsible for orchestration-level control flow, not direct feature implementation. Child runs perform implementation and local verification. The parent decides what work should happen next and whether completed child work is sufficient evidence for the broader goal.

The capability must support:

- High-level intake from a user instruction and optional source documents.
- Conversion of the instruction into an explicit target inventory.
- Creation of temporary embedded child routines with verifiable requirements.
- Durable parent/child run tracking.
- Waiting on child completion, pause, failure, or cancellation.
- Evidence collection from child worktrees and run metadata.
- Parent evaluation of whether to continue, replan, stop, or ask for human input.
- Final validation against the original instruction, not only against child-local requirements.

The capability should not require child routines to be added to the normal reusable routine library. Generated child routines are execution artifacts attached to child runs.

The first version should be driven by a reusable parent routine using MCP/API tools. Long term, the valuable capability is not one fixed internal parent controller; it is the ability to author routines that cover different parent orchestration patterns. This specification assumes the parent routine is the reusable policy layer and the orchestrator provides deterministic mechanics that make that policy dependable.

The first version is scoped to one repository per parent job. That repository does not have to be Task-World.

## Core Concepts

### Parent Run

The parent run is the durable orchestration record for the high-level job. It stores the original instruction, current target inventory, child run links, evidence summaries, decisions, and remaining work.

The parent run may have few or no code changes itself. Its primary artifact is the orchestration state and final report.

The parent run has its own branch. Accepted child branches merge into the parent branch as they complete, so the parent branch represents the accumulated accepted work for the overall job.

The branch model must support multiple orchestration levels. If a child is itself an orchestration parent, its accepted children merge into that child-parent branch first; that branch then merges upward into its parent when accepted. Each parent level owns the integrated state for its direct children.

### Child Run

A child run is a normal orchestrator run created by the parent with an embedded routine. It executes in its own worktree and follows the existing builder/verifier mechanics.

Each child run must be bounded. It should target one slice, one assumption, or one coherent group of closely related requirements. A child run must not silently expand into an unbounded implementation project.

Child runs must remain visible in the UI without taking significant visual space by default. They should appear grouped under their parent and be expandable on demand. When opened, a child run should reuse the normal routine/run rendering with a clear visual indication that it is a child and with navigation back to the parent group.

### Slice

A slice is the next bounded unit of work selected by the parent. A slice includes:

- The assumption under test.
- The target behavior, bug, or missing proof.
- The expected files or subsystems touched.
- Verifiable requirements.
- Auto-verify commands and/or verifier rubrics.
- Stop or replan conditions.
- Evidence artifacts the child must produce.

### Evidence Bundle

Every child run must leave structured evidence for the parent. The baseline schema is `run.evidence.v1`, with enough information for the parent to decide whether the broader task should proceed, replan, or stop.

Evidence must distinguish:

- verified fix
- bug not reproduced
- behavior already correct
- environment blocked
- needs revision
- partial progress
- unrelated failure

Those outcomes must not be collapsed into a generic pass/fail result.

## Required Components

### 1. Intake And Target Inventory

The parent must read the user instruction and relevant source artifacts, then produce a target inventory. For `docs/better-tests/test-strategy-improvements.md`, the inventory would include the known bugs, planned improvements, and gaps listed in the document.

The inventory must separate:

- Concrete bugs to fix.
- Missing tests or coverage gaps.
- Design improvements that need implementation.
- Meta or policy gaps that may need separate tooling.
- Items that require reproduction before implementation.
- Items that are out of scope or need human clarification.

Each inventory item must get a stable ID so future child slices and evidence can refer to it without relying on prose matching.

### 2. Slice Selector

The parent needs a slice-selection component that chooses the next child run. The selector should prefer slices that reduce uncertainty and produce real evidence early.

The selector should consider:

- Dependency order.
- Risk and blast radius.
- Whether the target bug has been reproduced.
- Whether a real verification surface exists.
- Whether a previous child already attempted related work.
- Whether related work should be queued for later slices or deferred to v2 parallel execution.
- Whether the remaining work is still aligned with the original instruction.

The selector should not decompose the whole job into many executable children before the first evidence is available unless the job is already mechanically well understood.

The initial default maximum is 20 child runs per parent job. This limit is a guardrail, not the primary progress signal. The parent must focus more strongly on detecting lack of progress, repeated failure modes, and ineffective retries than on simply counting children.

For the first version, stall detection is a parent judgment with one hard trigger: if the parent has tried to complete the same step through three child attempts without succeeding, the parent must declare that issue stalled and ask the human for guidance instead of continuing to create replacement children.

### 3. Temporary Routine Generator

The parent needs a generator that turns a selected slice into an embedded child routine. The generated routine must include:

- Clear builder context.
- Explicit requirements with stable IDs.
- Auto-verify checks where possible.
- Verifier rubric entries whose IDs match requirement IDs.
- Artifacts the child must produce.
- Evidence bundle requirements.
- Retry limits.
- Stop or replan conditions.

Generated child routines must be stored on the child run as `routine_embedded`. They should not be written into `routines/` unless the user explicitly requests promotion into the reusable routine library.

### 4. Child Run Manager

The parent needs a durable child-run manager. It must be able to:

- Create child runs linked to the parent.
- Start child runs.
- Poll or subscribe until each child reaches a meaningful state.
- Detect server restarts and recover waiting state.
- Record parent decisions before and after each child.
- Preserve child run IDs, slice IDs, and evidence paths.

Existing child-run APIs and MCP tools provide part of this surface. A dependable Super Parent should make this control flow owned by the orchestrator, not only by an LLM remembering to call tools correctly.

The parent and all children should use the user-selected runner. The first version should not auto-select a separate coordinator runner or force a different runner profile for parent orchestration.

### 5. Deterministic Parent Orchestration Mechanics

The reusable parent routine expresses policy and judgment. It must not be responsible for remembering every wait, enforcing every legal state combination, or reconstructing child progress from conversation. Those responsibilities belong to deterministic orchestrator machinery.

The engine-owned mechanics must include:

- Durable child-run creation, start, pause, resume, and stop operations.
- Durable wait or subscription behavior for child run and task state changes.
- A parent reducer that consumes existing child run/task states and parent integration records.
- Illegal state and transition guards.
- Parent pause propagation to active children.
- Evidence collection and validation from child run state, worktrees, and artifacts.
- Parent/child merge operations through service-owned APIs.
- Terminal guards that prevent parent completion or failure while blocking child work remains unresolved.
- Recovery after server restart by reading durable run state, events, and evidence records rather than relying on LLM memory.

The parent routine may decide what action it wants next, but the engine must validate and carry out that action through these mechanics.

### 6. Evidence Collector

The evidence collector gathers structured outputs from each child run:

- Evidence bundles.
- Auto-verify results.
- Verifier grades and feedback.
- Changed files and commits.
- Test command outputs.
- Screenshots or traces for frontend behavior.
- Open uncertainties.
- Child pause/failure reasons.

If structured evidence is missing, malformed, or contradicted by run state, the parent must treat that as a verification failure or replan condition.

### 7. Parent Evaluator

The evaluator compares child evidence against the parent inventory and original instruction. It must decide one of:

- `continue`: select another slice.
- `replan`: revise the target inventory or slice strategy.
- `ask_user`: request clarification or approval.
- `stop_success`: all required targets are satisfied.
- `stop_blocked`: the job cannot proceed with current information or environment.
- `stop_failed`: child results show the current strategy is ineffective or unsafe.

The evaluator must be allowed to conclude that a reported bug does not exist or has already been fixed, but only when the evidence directly supports that conclusion.

If the evaluator reaches `bug_not_reproduced`, it must ask the human before stopping or marking the target closed. The human-facing message must include a short list of what was tried and enough context for the human to suggest another reproduction path.

### 8. Merge And Integration Coordinator

If child runs make code changes, the parent must coordinate how those changes are integrated. The coordinator must know:

- Which child branches contain accepted changes.
- Whether changes are independent or conflict-prone.
- Whether child results should be merged immediately or held until review.
- Whether final validation should run before or after each merge.
- How to recover when one child succeeds and another fails.

The parent must not declare success based only on isolated child worktrees. Final success requires validation on the integrated target state.

Accepted child branches should merge into the parent branch as soon as they are complete and accepted. If a child fails, its branch and run record may remain for audit, but the parent must not merge it. The parent may create a replacement child to try a different approach.

Because the parent is only merging into its own branch, automatic merge into the parent branch is the expected behavior for accepted children. Human review happens on the final integrated product, not before every child merge.

The parent owns its branch and has authority to handle merge conflicts on that branch. Conflict resolution must remain scoped to the parent worktree and parent branch.

By default, the parent should carry out merge conflict resolution itself because the parent branch is the integrated state that needs to be made coherent. A dedicated conflict-resolution child run may be introduced later, but it is not required for the first version.

After a merge or conflict resolution, the parent should create a validation child or validation phase that repeats the relevant validations performed before the merge against the integrated parent branch. That validation must include the merged child's verification surface and any conflict-affected files or behaviors.

Git operations must be constrained so the parent cannot accidentally alter the source branch or main checkout:

- Parent merges must run only in the parent run worktree.
- Child merges must target only the parent run branch.
- No Super Parent operation may merge directly to `main`, `master`, or the configured source branch.
- No Super Parent operation may run git commands from the main project checkout.
- Commands that change branches, reset state, delete branches, or rewrite history require explicit policy support and must be blocked unless the operation targets the parent/child worktree and branch.
- Final merge from the parent branch back to the source branch is a separate completion action and requires human review.

The final merge should use the existing completion/review path. Once the parent is complete, the user can inspect the accumulated changes and click merge through the existing UI.

### 9. Final Report

At completion or stop, the parent must write a final report. The report must include:

- Original instruction.
- Target inventory and final status for each target.
- Child runs created.
- Evidence consumed.
- Files changed.
- Commands run for final validation.
- Remaining risks.
- Human decisions requested or applied.
- Summarized failures, including what impact each failure has on the final result.
- Clear success, blocked, or failed outcome.

## Verification Model

Super Parent verification must operate at two levels: child-local verification and parent-level validation.

### Child-Local Verification

Each child must verify the slice it was assigned. Good child verification includes:

- Contract-level unit or integration tests.
- Static checks when relevant.
- Real UI or API exercise for user-visible behavior.
- Reproduction checks for reported bugs.
- Auto-verify commands that fail when the intended behavior is absent.
- Verifier rubric checks that inspect behavior and evidence, not only file existence.

Child verification is necessary but not sufficient. A child can pass while the broader job remains incomplete.

### Parent-Level Validation

The parent must verify the original job after integrating accepted child changes. Parent-level validation includes:

- Re-running the relevant global test suites.
- Re-checking the original target inventory.
- Confirming no accepted child invalidated earlier evidence.
- Confirming each known bug is fixed, not merely covered by a new test.
- Confirming remaining skipped or blocked items are explicitly justified.

For the better-tests example, parent-level validation would require more than "new tests were added." It would need to show that the known bugs are fixed or proven not present, and that the new tests would catch the relevant regressions.

Running the full test suite is sufficient for broad repository regression coverage. Validation for the work itself, and for features likely to have been impacted by the work, should be more focused and behavior-specific.

### Evidence Quality Rules

Effective verification must follow these rules:

- Real execution surfaces outrank shims.
- A passing existence check is not behavior proof.
- A mocked test can support diagnosis, but it cannot be the only proof of live integration.
- A child that cannot reproduce the target bug must stop or replan instead of guessing a fix.
- Failing verification is parent input, not merely child failure.
- Evidence must be specific enough for a later planner to act without rediscovering everything.
- Final validation must run on the integrated state, not only on child worktrees.

## Principles

### Bounded Work Before Broad Work

The parent should prefer one useful vertical slice over many speculative horizontal slices. It should broaden only after evidence confirms the direction.

### Evidence Changes The Plan

The next slice must be shaped by observed evidence. If child work reveals a wrong assumption, the parent must adapt.

### Temporary By Default

Generated child routines are temporary execution artifacts. Promote a child routine into the reusable routine library only when a human explicitly wants that pattern saved.

### Fresh Context At Boundaries

Each child run should use fresh builder and verifier contexts. The parent supplies distilled evidence and target state, not full conversational history.

### Explicit Stop Conditions

The parent must stop or ask for help when:

- The target cannot be reproduced.
- The environment cannot verify the real behavior.
- Children repeatedly fail for the same reason.
- Merge conflicts make the next step unsafe.
- Costs or iteration limits are reached.
- Evidence contradicts the original instruction.

### Integrated Success

Success means the original job is satisfied in the integrated repository state. Passing child runs are evidence toward success, not success by themselves.

### Human Control Points

The system should support human review before high-risk actions, including broad refactors, destructive migrations, large dependency additions, and final merge decisions.

Adding dependencies is allowed at the parent and child layers. Dependency additions still need to satisfy the normal repository standards: they must be justified by the slice, captured in evidence, and validated by the relevant checks.

### Durable Orchestration

The parent loop must survive server restarts and agent failures. The current decision, active child waits, evidence already consumed, and next action must be persisted.

## V2 Deferred Scope

The first version should prove the sequential parent loop before adding parallel child execution. Parallel children, fan-in batches, concurrency limits, conflict prediction, and multi-child invalidation handling are specified separately in [v2.md](v2.md).

V1 may queue future slices, but it should run at most one child implementation run at a time. The parent can still continue parent-side analysis, update its understanding, and prepare queued slices while waiting.

## Relationship To Existing Orchestrator Mechanics

The current system already has several required primitives:

- Runs execute in isolated worktrees.
- Routines can be embedded in run creation.
- Child runs can be linked to a parent run.
- MCP tools and REST APIs can create/list child runs.
- Runs can expose structured evidence bundles.
- Builder and verifier phases already use fresh context.
- Auto-verify and verifier rubrics already exist.

The missing capability is not only a reusable parent routine. A parent routine can describe the policy, but reliable Super Parent behavior also needs mechanical orchestration semantics for waiting, evidence aggregation, merge coordination, iteration limits, pause propagation, illegal-state rejection, and recovery. Parallel fan-in semantics are deferred to v2.

For the first version, the parent routine is the primary reusable mechanism. The engine should provide enough generic mechanics for routines to express different parent orchestration strategies rather than enforcing a single built-in strategy.

## Initial Product Decisions

- Parent orchestration starts as a reusable parent routine, not a fixed internal workflow.
- Child runs are visible in the UI but compact until opened.
- Child run details reuse normal routine rendering with child/parent visual context.
- The parent owns an accumulation branch.
- Accepted child branches merge into the parent branch as soon as they are accepted.
- The parent branch is created at parent start.
- Accepted children merge automatically into the parent branch.
- Human review happens on the final integrated product.
- Final merge uses the existing review and merge UI.
- The parent has authority to resolve merge conflicts on its branch.
- The parent carries out merge conflict resolution by default.
- Git operations must stay scoped to the relevant run worktree and branch.
- Failed child branches remain unmerged; replacement children may be created.
- Initial maximum child runs per parent job is 20.
- Replacement children count against the 20-child limit.
- Lack-of-progress detection is more important than total child count.
- Three failed child attempts to complete the same step means the issue is stalled and needs human guidance.
- V1 runs at most one child implementation run at a time. Parallel child execution, fan-in, and the default maximum of 4 parallel children are v2 concerns.
- `bug_not_reproduced` requires human interaction and a short list of attempted reproduction paths.
- Dependency additions are allowed, subject to evidence and validation.
- Final broad regression coverage may be the full test suite.
- Work-specific validation must be focused on the changed behavior and impacted features.
- Scope is a single repository for now, though not necessarily the Task-World repository.
- Parent and children use the user-selected runner.
- Parent-level UI should emphasize what the user needs to do and what the parent currently understands.
- Parent-level UI should surface children needing human interaction or paused children; queued, failed, and accepted child counts are secondary detail.
- Final reports summarize failed children and explain their impact on the final result.
- The parent may continue parent-side analysis, update understanding, and prepare queued slices while a child waits for human input.
- Parent understanding is not an independent lifecycle state. It is a status-scoped oversight payload that is meaningful while the parent is active, and as resume context while the parent is paused.
- Pausing the parent must pause active children before the parent reaches a steady paused state.
- Child state changes are events consumed by the parent state machine. The event vocabulary should use existing child run and task states rather than introducing a separate external child-event enum.
- Git guardrails for v1 combine service-owned parent/child merge APIs, worktree/repository isolation, and existing human-triggered final merge. Shell-level git command restrictions are defense in depth, not the only safety layer.
- The git wrapper must use strict per-command allowlists from v1.
- PATH precedence is sufficient for v1 git-wrapper enforcement. Blocking direct absolute-path access to the real git binary is optional future hardening, not a v1 requirement.
- A readable parent-understanding artifact should be updated when the parent's understanding materially changes. It must be updated before human input is requested and before the parent reaches a terminal outcome.
- Routine parent-understanding artifact updates may be batched, but mandatory updates before human input and terminal outcomes must not be batched past those decision points.

## Parent And Child State Semantics

Super Parent should extend the existing run state model rather than create an independent lifecycle for parent understanding. The parent run's durable lifecycle remains `draft`, `active`, `paused`, `stopping`, `completed`, or `failed`.

`current_understanding` is not a state that can be freely combined with those statuses. It is an oversight payload derived from parent decisions and child-transition events. Its meaning depends on the parent run status:

| Parent status | Meaning of current understanding | Required behavior |
| --- | --- | --- |
| `draft` | Not meaningful beyond intake notes or the original instruction. | No child work should be running. |
| `active` | Live orchestration summary: current hypothesis, ready work, blocking child questions, paused children, what has been tried, and next intended action. | The parent may keep working if at least one useful non-blocked action remains. |
| `paused` | Resume context and human-facing explanation. It is meaningful for deciding what to do on resume, not as evidence of live progress. | The parent must not launch new children while paused, and active children must already be paused. |
| `stopping` | Transitional shutdown context only. | No new children should launch; active child work must be drained, paused, or cancelled according to policy. |
| `completed` | Superseded by the final report. | No pending child attention, unmerged accepted child, or active child work may remain. |
| `failed` | Superseded by the failure report. | Remaining child branches are unmerged and their impact is recorded. |

The parent can therefore have a structured `oversight_state`, but the UI and engine must interpret it through the parent lifecycle state. A terminal parent should show the final or failure report, not a "current" understanding. A paused parent should show the required human action and what was tried. An active parent should show whether progress is continuing, whether human input is needed for a non-blocking child, and which work is currently blocked.

### Parent And Child Cross-Product

Child runs have their own lifecycle, but child transitions are inputs to the parent state machine. The parent must maintain a legal parent/child combination rather than treating every status pair as valid.

Legal steady-state combinations:

- `active` parent with one active child, queued child slices, a completed accepted child waiting for merge, a failed unmerged child being evaluated, or a paused child that does not block parent-side analysis.
- `active` parent with a child waiting for human input while the parent updates understanding, prepares queued slices, or performs other parent-side work that does not require another child implementation run.
- `paused` parent with no newly launched child work and a clear resume action. Child work must be paused or terminal before the parent reaches a steady paused state.
- `completed` parent only when all accepted children are merged into the parent branch, all required validation has run on the integrated state, and unresolved child failures are documented as non-blocking or out of scope.
- `failed` parent only when active child work has been stopped or made irrelevant and the failure report explains the impact.

Illegal steady-state combinations:

- `completed` or `failed` parent with active children, stopping children, or queued child slices.
- `completed` parent with an accepted child branch that has not been merged into the parent branch.
- `completed` parent with an unresolved child human-action request that affects an in-scope target.
- `active` parent with all remaining useful work blocked by child human input. In that case the parent must pause and ask the human.
- `active` parent with more than one child implementation run active in v1.
- `paused` parent that keeps launching new child runs or allows active children to keep running.
- A failed child branch merged into the parent branch.
- A child branch merged directly into `main`, `master`, the configured source branch, or a sibling child branch.

The parent does not have to pause merely because one child pauses. It must pause when the paused child blocks all useful parent-side work or when continuing would violate the current slice. Otherwise, the child pause creates a parent attention item while the parent remains active. Starting additional child implementation work while another child remains paused is a v2 parallel-orchestration concern unless the paused child has been rejected, abandoned, or made terminal.

When the parent itself pauses, that pause propagates to active children. This avoids a state where the parent is paused but child work continues changing evidence, branches, or pending human context behind the paused parent.

### Child Transition Events

The parent should consume child state changes as events, but those events should use the existing child state vocabulary. Super Parent should not introduce a separate external enum such as `child_completed` or `child_needs_human`.

A child-state event should include:

- Child run ID.
- Slice ID.
- Affected inventory IDs.
- Source state type, such as child `Run.status`, child `Run.pause_reason`, child `TaskStatus`, child pending-action fields, or child evidence outcome.
- Old value and new value where the transition is known.
- Evidence reference.
- Dependency impact.

The primary event inputs are existing states:

- Child `Run.status`: `draft`, `active`, `paused`, `stopping`, `completed`, `failed`.
- Child `Run.pause_reason` and `last_error`.
- Child task statuses: `pending`, `building`, `pending_user_action`, `verifying`, `recovering`, `fan_out_running`, `completed`, `failed`.
- Child pending-action fields, including action type and clarification ID.
- Child evidence bundle outcomes, such as verified fix, bug not reproduced, environment blocked, partial progress, or unrelated failure.
- Parent-owned integration records, such as accepted merge, rejected child, replacement child created, or stalled issue.

The parent reducer must be deterministic: current parent state, child event, target inventory, dependency graph, and oversight state produce the next parent action. Possible next actions include continue, launch child, queue child, merge accepted child, create replacement child, pause for human input, stop success, stop blocked, or stop failed.

The reducer must reject illegal transitions rather than relying on the LLM to remember them. Examples:

- A child `Run.status = completed` transition may enqueue merge or evaluation, but it cannot by itself mark the parent complete.
- A child `TaskStatus.PENDING_USER_ACTION` transition creates an attention item; it pauses the parent only if no independent ready work remains.
- A child `Run.status = failed` transition may create a replacement child; after three failed child attempts for the same step, it must produce a stalled parent outcome requiring human guidance.
- A parent-owned accepted-merge record updates the integrated state and may unlock dependent slices.
- A terminal parent transition must first verify there are no active, queued, or unresolved blocking children.

### Oversight State

The parent should store a structured oversight payload for UI and recovery. The payload should be derived from durable events, not used as an independent source of lifecycle truth.

The oversight payload should include:

- Current understanding summary.
- Attention items requiring human input.
- Child run summaries grouped by slice and inventory ID.
- Blocked and ready slices.
- Attempt counts by inventory item or step.
- Merge queue and accepted merge records.
- What was tried for any stalled or unreproduced bug.
- Next intended parent action.

The engine should be able to recompute or validate this payload from durable child events and parent decisions. If the payload and child state disagree, the parent must treat the mismatch as a recovery issue and rebuild the payload before continuing.

## Remaining Design Options

### Parent-Level Human Interaction Representation

The existing state model offers several ways to represent parent-level "needs human interaction" when one or more children are waiting. These are representation choices, not separate lifecycle states.

Option A: derive from child run state only.

- Use existing child `Run.status`, `Run.pause_reason`, task `TaskStatus.PENDING_USER_ACTION`, `TaskState.pending_action_type`, and step `human_approval`.
- Parent remains `ACTIVE` if it can continue parent-side analysis or queued-slice preparation.
- UI computes parent attention needs by listing children and pending actions.
- Lowest schema cost, but parent state is less explicit and may require repeated child aggregation.

Option B: store an explicit parent attention summary in `Run.oversight_state`.

- Parent remains `ACTIVE` unless all useful parent-side work is blocked.
- `oversight_state` records attention items with child run ID, task ID, action type, blocking scope, summary, and what was tried.
- UI can render a parent-level "needs human input" summary without overloading task status.
- Best fit for continuing parent-side analysis and queued-slice preparation while one child waits.

Option C: create a synthetic parent task in `PENDING_USER_ACTION`.

- Reuses existing pending-action UI and task status semantics.
- The parent routine would contain a task representing child attention.
- More visible in existing surfaces, but it pollutes the parent routine with synthetic tasks and may confuse task progression.

Option D: pause the parent run with a child-attention pause reason.

- Use `RunStatus.PAUSED` plus a pause reason such as `child_waiting_for_human`.
- Simple and consistent with existing pause flows.
- Not the default fit because the parent should be allowed to continue parent-side analysis and queued-slice preparation.
- Useful only when the waiting child blocks all remaining parent-side work.

Decision: use Option B as the primary representation, with Option A as a derivation fallback and Option D only when no parent-side work can continue. The parent lifecycle state remains authoritative; `oversight_state` explains the active or paused parent state but does not replace it.

### Git Guardrails

The LLM may be able to run shell commands inside the run worktree, so git safety cannot rely only on prompt instructions.

Option A: prompt and policy only.

- Tell the parent and children to use git only in their worktrees and never merge to source branches.
- Easy to add, but weak. It does not secure behavior when an LLM can run shell commands.

Option B: orchestrator-owned merge API for parent/child merges.

- Parent asks the orchestrator to merge an accepted child into the parent branch.
- The service validates run IDs, worktree path, current branch, target branch, and source branch before merging.
- Strong for official merge paths, but raw shell git commands could still bypass it inside writable worktrees unless paired with other controls.

Option C: shell command interception and git allowlist.

- Runner command execution rejects unsafe git commands or commands run outside the current run worktree.
- Blocks obvious mistakes such as `git checkout main`, `git merge main`, `git reset --hard`, or merges from the main checkout.
- Medium strength. It is useful defense-in-depth, but must be paired with environment restrictions because shell commands can use absolute git paths, scripts, aliases, or indirect invocations.

Option D: worktree and repository isolation.

- Agents only receive access to their run worktree, not the main checkout.
- The source branch/main checkout is not writable from the agent environment.
- The parent worktree is the only place child merges can land.
- Stronger than command filtering because it narrows what the shell can affect, but it still needs service-level validation for final merge.

Option E: final merge remains server-side and human-triggered.

- Parent and children may manipulate only run branches.
- The source branch merge is performed only by the orchestrator completion action after human review.
- Service checks that the run branch is the expected parent branch and that validation is current.
- Strong protection for `main`/`master`/source branch even if an agent makes mistakes in its own worktree.

Decision: combine B, D, and E for v1, with C as defense-in-depth. Prompt-only rules are documentation, not security. The git wrapper is a feedback and accident-prevention layer inside the v1 trust boundary; it is not the sole protection against an agent that deliberately bypasses `PATH`.

#### Git Wrapper Requirements

The agent environment should put a git wrapper first in `PATH` so ordinary `git` invocations use the wrapper instead of the system binary. The wrapper must validate that the command is running inside the current run worktree and on the expected run branch before delegating to the real git binary.

The wrapper's v1 purpose is to prevent accidental unsafe git use and provide clear feedback when the agent attempts a blocked operation. Worktree isolation and service-owned merge APIs protect the source branch and official merge paths.

The wrapper must allow only these operations within the current worktree:

- `git status`
- `git diff`
- `git add`
- `git restore`
- `git commit`
- `git log`
- `git show`
- `git rev-parse`
- `git ls-files`

The wrapper must block commands that can alter branches, refs, remotes, repository structure, or history outside the narrow "commit on the current run branch" path:

- `git checkout`
- `git switch`
- `git branch`
- `git merge`
- `git rebase`
- `git cherry-pick`
- `git reset`
- `git revert`
- `git push`
- `git fetch`
- `git pull`
- `git tag`
- `git worktree`
- `git update-ref`
- Direct ref manipulation or history rewriting.

The wrapper must use a strict per-command allowlist for flags, environment, and path arguments. Unknown flags, unknown argument forms, and paths outside the current worktree must be rejected even when the subcommand itself is allowed.

The strict allowlist must reject unsafe options on otherwise allowed commands. Examples include:

- `git commit --amend`
- `git diff --output=<path>`
- any command using `--git-dir`, `--work-tree`, or a path outside the current worktree
- environment overrides such as `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, or alternate object directories

The wrapper and runner isolation should make intended git operations predictable:

- The agent should not have writable access to the main checkout or sibling worktrees.
- The wrapper is enforced by PATH precedence for v1.
- Direct absolute-path blocking of the real git binary is not required for v1.
- The runner may log direct absolute-path git invocations as future hardening, but v1 behavior relies on PATH precedence plus worktree isolation.
- The worktree `.git` file or `.git/HEAD` path, and the underlying gitdir `HEAD` for linked worktrees, must not be directly writable by the agent.
- Committing is allowed only because it updates the current run branch through the wrapper after validation.
- Parent/child branch merges must go through the orchestrator-owned merge API, not shell git.

Local git hooks should provide a second layer of protection:

- `pre-push` blocks all pushes, or restricts pushes to explicitly safe run branches.
- `pre-rebase` blocks all rebases.
- `update` on the receiving repository, when applicable, rejects modifications to protected branches such as `main` and `master`.

These guardrails assume each agent operates in a dedicated git worktree tied to a single branch. The agent should not be able to switch branches, alter other worktrees, or directly affect protected source branches.

### Parent Understanding Evidence Format

When the parent pauses or needs human input, it should explain what it currently understands and what it needs from the user.

Option A: structured `oversight_state.current_understanding`.

- Store a JSON object with summary, active hypothesis, attempted paths, blockers, children involved, recommended next choices, and dependency impact.
- Best for UI rendering and resumable control flow.
- Requires schema discipline around `oversight_state`.

Option B: human-readable markdown artifact.

- Write a file such as `docs/<job>/super-parent-status.md` or a run artifact with current understanding, tried attempts, and requested input.
- Easy for humans and agents to read.
- Less reliable for UI and automation unless paired with structured state.

Option C: pending action payload.

- Extend the pending-action/clarification surface with parent-level context and suggested next actions.
- Reuses existing human response flow.
- Best when the parent needs a direct answer, but not sufficient as the durable parent memory.

Option D: event log only.

- Rely on child events, parent decisions, and activity history.
- No new state, but too hard for users to understand and too expensive for the parent to reconstruct repeatedly.

Preferred direction: Option A plus Option B, interpreted through the parent lifecycle state. Use structured state for UI/control flow and markdown for readable audit context. Use Option C when a direct human answer is needed. In `completed` or `failed`, the final or failure report replaces "current" understanding.

The readable markdown artifact should be updated whenever the parent's understanding materially changes. Routine progress updates may be batched if frequent writes are too costly. The artifact must still be updated before the parent asks for human input and before the parent completes, fails, or stops blocked; those mandatory writes must happen before the decision is surfaced as final or waiting on the human.
