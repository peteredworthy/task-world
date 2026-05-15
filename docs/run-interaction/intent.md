# Intent: Run Interaction

## Goal

Make active and historical runs understandable and steerable enough that a user can diagnose cost, compare orchestration strategies, and intervene without breaking the run model.

The immediate motivation is the high cost of Super-Parent runs and the need to compare that behavior with the newest `idea-to-plan` flow. The system should expose what the parent, child, builder, verifier, and sidecar agents did; what each phase cost; and where human guidance could have reduced wasted work.

## Problem

The orchestrator already captures run activity, attempt logs, action logs, and aggregate token usage, but those surfaces are mostly output-only and after-the-fact. A user can inspect what happened, pause a run, or resume a run, but cannot consistently interact with the active agent session.

Current runner behavior is also uneven:

- The generic runner contract is phase-oriented: `execute()` performs a builder, verifier, or recovery phase and `cancel()` stops it.
- Codex Server has a thread and turn protocol that can support richer interaction, including interruption, but the orchestrator currently wraps it as one phase execution.
- CLI subprocess runners usually receive one prompt on stdin and then close stdin, so live follow-up depends on runner-specific support.
- OpenHands and SDK runners expose their own conversation mechanisms, but those are not normalized through the orchestrator.

Run interaction needs to be honest about those differences instead of pretending every runner can support the same live chat semantics.

## Scope

### In Scope

1. **Observe a run while it is executing.** Users should be able to see a live timeline of agent output, tool activity, task transitions, child-run events, clarifications, approvals, errors, and cost updates.

2. **Inspect a normalized run transcript.** Historical and active attempts should present a coherent transcript across runner types: prompts, user interventions, assistant messages, tool calls, tool results, phase boundaries, and terminal outcomes.

3. **Queue guidance for the next safe control point.** A user should be able to attach guidance to a run, task, or phase so the next newly spawned agent receives it in its prompt. This should work even for runners that cannot accept live input.

4. **Interrupt an active run when supported.** Users should be able to request an interrupt with an optional message. The system must distinguish hard cancel/pause from soft interruption, and must report whether the active runner supports the requested behavior.

5. **Start a clean sidecar agent in run context.** Users should be able to launch a separate agent in the run worktree for investigation, comparison, summarization, or debugging without automatically moving checklist, submit, or grade state.

6. **Continue a paused run interactively.** When a run is paused, the user should be able to inspect the current state, provide resume guidance, select a runner/config, and choose whether to continue current task state or restart from a phase boundary.

7. **Explain cost by execution unit.** The system should break cost down by run, parent run, child run, step, task, attempt, phase, model, and sub-agent where available.

8. **Support Super-Parent comparison.** Run interaction should make it possible to compare Super-Parent behavior against `idea-to-plan`: number of agents spawned, child runs created, total turns, tool calls, verifier passes, retries, clarifications, wall time, token usage, and estimated cost.

### Out of Scope

- Replacing routine execution semantics with a free-form chat loop.
- Assuming all runner types can receive live messages during a phase.
- Silent mutation of workflow state from sidecar sessions.
- Direct database editing or private runner state access from API handlers.
- UI-only changes that do not establish durable interaction records.

## Required Concepts

### Interaction Modes

**Observe** is read-only. It streams activity and exposes transcript, action-log, and cost details.

**Guide** persists a human message that will be injected at the next safe control point. Delivery must be explicit: pending, delivered, superseded, or canceled.

**Interrupt** attempts to stop or redirect active work. The request must record whether the runner performed a soft interrupt, fell back to cancel-and-pause, or rejected the operation as unsupported.

**Sidecar** starts a clean agent in the run worktree. By default it should not have workflow callback tools that can submit, grade, or update checklist state. Any write access must be explicit.

**Resume with guidance** restarts paused workflow execution with a persisted human message and a chosen resume strategy.

### Runner Capability Matrix

Each runner should advertise capabilities instead of relying on hidden assumptions:

- `observe_output`: streams user-readable output during execution.
- `structured_actions`: emits normalized tool/action logs.
- `token_usage`: reports token usage and model identity.
- `subagent_usage`: reports spawned sub-agent usage.
- `soft_interrupt`: can interrupt an active turn without killing the whole run.
- `live_user_message`: can accept a user message during an active session.
- `queued_guidance`: can receive additional prompt context on the next execution.
- `resume_session`: can continue an existing provider session.
- `sidecar_session`: can run outside workflow callbacks in the run worktree.

The UI and API should use this matrix to present supported actions and explain fallbacks.

### Durable Interaction Records

Every user interaction must be persisted with:

- run ID, optional step ID, optional task ID, optional attempt ID
- target mode: observe, guide, interrupt, sidecar, resume
- author and timestamp
- message body
- requested runner behavior
- actual delivery behavior
- status and terminal result
- related activity event IDs or transcript ranges

This keeps user intervention auditable and allows cost analysis to account for human steering.

## Desired User Scenarios

### Jump Into A Running Run

The user opens an active run and sees the current task, phase, live agent output, recent tool calls, child-run status, and current cost estimate. The user can decide whether to keep observing, queue guidance, or interrupt.

### Queue A Message For The Next User Control Point

The user writes guidance such as "do not launch another child until the verifier explains the failing browser path." The system stores it and injects it into the next newly spawned parent, builder, verifier, or recovery prompt according to the selected target.

### Interrupt Active Work

The user sends "stop expanding this slice; summarize what you found and pause." If the runner supports soft interrupt, the system sends it. If not, the system cancels the active agent, pauses the run, records the fallback, and offers resume-with-guidance.

### Start A Clean Agent In Run Context

The user launches a sidecar agent to inspect cost, compare Super-Parent against `idea-to-plan`, or investigate a failing child run. The sidecar can read run artifacts and the worktree. It does not update workflow state unless explicitly granted scoped tools.

### Continue A Paused Run Interactively

The user opens a paused run, reviews why it paused, sees active task state and transcript, writes resume guidance, chooses a runner, and resumes. The resumed agent receives the guidance and the transcript explicitly records that intervention.

## Cost And Comparison Requirements

Run interaction should support cost questions such as:

- How much did the Super-Parent parent loop cost separately from child implementation runs?
- Which child runs, tasks, phases, or verifier attempts consumed the most tokens?
- How much cost came from sub-agents spawned inside Claude Code?
- How many turns happened before the parent learned useful evidence?
- How many child runs ended in replan, environment block, needs revision, or unrelated failure?
- Did queued guidance or interruption reduce later cost?
- How does the same intent behave under `idea-to-plan` in total cost, latency, artifact quality, and intervention count?

## Completion Criteria

1. Users can open a run and view live activity plus historical transcript data in one place.
2. User-authored guidance can be queued, persisted, delivered into a later agent prompt, and shown in the transcript.
3. Interrupt requests are capability-aware and record whether they soft-interrupted, canceled, paused, or failed.
4. Sidecar agents can be launched in run context without implicitly mutating workflow state.
5. Paused runs can be resumed with explicit guidance and runner selection.
6. Cost can be grouped by parent run, child run, step, task, attempt, phase, model, and sub-agent where data exists.
7. Super-Parent and `idea-to-plan` runs can be compared using the same metrics and transcript model.
8. All interactions are durable, auditable, and exposed through API responses suitable for UI rendering.

## Open Questions

- Should soft interruption be a best-effort runner method on `AgentRunner`, or a separate optional protocol implemented only by capable runners?
- Should queued guidance target the run globally, the next task, the current task, or a specific phase by default?
- Should sidecar sessions be allowed to write files by default, or start read-only and require explicit elevation?
- How should sidecar output be represented in run activity without confusing it with workflow progress?
- What is the minimum normalized transcript schema that can represent Claude CLI, Codex Server, Claude SDK, OpenHands, and user-authored interventions?
- How should we compare runs with different routine structures while still producing fair Super-Parent versus `idea-to-plan` metrics?
