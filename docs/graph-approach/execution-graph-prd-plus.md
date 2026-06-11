# Task-World Execution Graph PRD+

## 1. Document Purpose

This document defines a clean-sheet architecture for the next Task-World execution model.

It is a PRD+ rather than a normal PRD: it includes product intent, domain definitions, architecture rules, reducer/scheduler semantics, failure behavior, file-state policy, role permissions, and test strategy. The goal is to make the system concrete enough that the design can be iterated without repeatedly re-litigating the basic model.

The core architectural claim is:

> Agents are effectful workers. The graph controller is the deterministic authority. Agents may propose outputs, file-state, decisions, appeals, and graph patches; the controller validates and accepts or rejects them.

This keeps the value of agent autonomy while making correctness primarily a unit-testable property of reducers, policy functions, and scheduler decisions.

## 2. Current Baseline

Task-World currently has these important capabilities:

- Git-versioned routine YAML templates with steps, tasks, requirements, gates, auto-verify commands, context inputs, fan-out, agents, and model profiles.
- Runs instantiated from a routine snapshot against a target repository.
- Per-run worktrees and run branches.
- Agent runners including OpenHands, CLI subprocesses, Codex server, Claude SDK, and user-managed external agents.
- Named agent configurations: system prompt plus model profile, resolved from task, step, routine, then default.
- Builder and verifier phases with fresh LLM context per phase.
- Human clarification and approval flow.
- Recovery and pause/resume/cancel flow through signals.
- Event-backed projections in `events_v2`, with run/task read models rebuilt from events.
- Current compatibility mutation paths, so the system is event-backed but not yet a purely event-sourced graph kernel.
- Review workbench for diff inspection, test runs, conflict resolution, pruning, agent fixes, and merge-back.

The clean-sheet model should retain the useful product capabilities while replacing implicit task mutation and runner callbacks with an explicit execution graph, controller-owned event log, and deterministic scheduler.

## 3. Product Goals

1. Represent the run as a dynamic execution graph that can be inspected, replayed, tested, and modified under explicit authority rules.
2. Allow agents to process the graph and, when authorized, propose changes to future graph structure.
3. Support retained agent sessions for token efficiency without making session memory authoritative.
4. Reduce race-condition risk from independent agent runtimes through leases, snapshots, event ordering, and single-controller graph mutation.
5. Make the orchestration core testable primarily with unit tests over pure reducers and policy functions.
6. Preserve traceability for routine compilation, planning, building, verification, appeals, human decisions, recovery, review, and merge-back.
7. Make file-state dependencies explicit enough that downstream work does not depend on implicit dirty worktree state.
8. Provide a path from current routines to future dynamic planning without discarding the routine authoring model.

## 4. Non-Goals

1. Do not try to make agents pure functions. Agents will modify files, call tools, and make mistakes.
2. Do not build a free-form multi-agent blackboard where any agent can mutate any graph state.
3. Do not require distributed consensus, multiple scheduler leaders, or a general Temporal replacement in the first version.
4. Do not require perfect replay of every untracked cache file. The architecture must classify and control non-Git state, but v1 can be conservative.
5. Do not make parallel writes the default. Correctness and traceability are more valuable than maximum throughput initially.
6. Do not move business logic into agent prompts when it can be expressed as controller policy.
7. Do not replace all current UI/API surfaces at once. The graph model can be introduced behind compatibility views.

## 5. Design Principles

- **Event log is authoritative.** Accepted events are the source of truth. Projections and database rows are derived caches.
- **Controller is the only graph writer.** Agents submit proposals and callbacks; the controller accepts or rejects.
- **Historical facts are immutable.** Attempt nodes, callback receipt records, accepted output records, and file-state records are never edited in place.
- **Projections are disposable.** Run status, task progress, active leases, and ready-node views are derived and can be rebuilt.
- **Sessions are context containers.** A retained agent session can hold conversation context, but it has no authority without a valid lease.
- **Edges are input bindings.** Use one edge model. Typed meaning lives in output, file-state, and graph records referenced by ports.
- **Default to single writer.** v1 should allow many read nodes over stable snapshots, but only one write node per run worktree.
- **Unit tests own correctness.** The reducer, scheduler, patch validator, resource checker, readiness evaluator, and file-state classifier are pure or nearly pure.

## 6. Canonical Terms

| Term | Definition |
|---|---|
| Run | One execution instance for a routine snapshot against a repository and worktree. |
| Graph | The durable execution structure for a run: nodes, input bindings, accepted records, and derived projections. |
| Node | Addressable unit of planned work, historical activity, decision, gate, artifact, projection, or review action. |
| Port | Named output or input slot on a node. Ports carry typed records by reference. |
| Edge | A dependency binding from a source output port to a target input port. There is one edge model. |
| Record | Immutable accepted fact emitted by a node or controller. Records include output, file-state, and graph records. |
| Artifact | A semantic output record, often backed by a file or structured JSON payload. |
| Snapshot | Stable file-state plus graph-input view used by a node. |
| File-state | Explicit description of tracked, untracked, ignored, deleted, and external files for a snapshot. |
| Lease | Time-bounded authority token granting a session permission to act on a node and resource set. |
| Projection | Derived read model computed from accepted events, such as task progress or active leases. |
| Command | Requested action that may produce accepted events, such as pause, resume, schedule, or callback handling. |
| Event | Append-only accepted fact in the authoritative event log. |
| Agent session | Runtime conversation/process context for an agent. It may be resumed, but it is not the source of truth. |
| Graph patch | Structured request to change graph topology, authority, resource claims, or input bindings. |
| Controller | Deterministic application service that validates commands, appends events, updates projections, and schedules work. |

Events and records are related but not identical. An event is the ordered durable envelope. A record is an addressable domain payload created by an accepted event and consumed through ports. For example, `callback_received` may store raw callback metadata, while `output_record_accepted` creates the accepted semantic output that downstream nodes can consume. A `file_state_accepted` event creates a `file_state` record; a `verification_completed` event may create a `verification_report` output record plus graph decision payloads.

## 7. Source of Truth and State Layers

The system has four state layers.

| Layer | Role | Mutability | Recovery Rule |
|---|---|---|---|
| Event log | Authoritative history of accepted facts | Append-only | Rebuild everything else from this. |
| Projection tables | Query/read-model cache | Disposable | Drop and rebuild from event log. |
| Agent sessions | Runtime context cache | Ephemeral or resumable | Reattach if possible; otherwise resume from graph packet. |
| Worktree/filesystem | Effect surface for agents | Mutable during leased execution | Captured or rejected at node boundary through file-state records. |

The event log wins after crash/replay. If a projection disagrees with the event log, the projection is wrong. If an agent session disagrees with the event log, the session is stale. If the worktree contains undeclared residue, the controller must classify, capture, reject, or clean it before accepting downstream work.

## 8. Mutability Rules

| Object | Can Change? | How |
|---|---|---|
| Accepted event | No | Never edited or deleted by normal operation. |
| Accepted output record | No | Supersede with a new record if needed. |
| Accepted file-state record | No | Supersede with a new snapshot/manifest record. |
| Worker/verifier/check execution node | No direct rewrite after terminal state | Create retry/revision/recovery node. |
| Requirement node | Versioned, not overwritten | Add new requirement version or accepted amendment record. |
| Input binding edge | Append/supersede | Add new edge version or retire old edge through graph patch. |
| Graph topology | Append/supersede | Controller accepts graph patch events. |
| Lease | State changes only through lease events | Grant, suspend, revoke, expire, renew. |
| Projection | Yes | Recomputed from events. |
| Agent session | Yes, ephemeral | Runtime may attach/suspend/detach/dead; never authoritative. |
| Worktree | Yes during active write lease | Captured, rejected, or cleaned at boundary. |

The system should prefer "add a new fact and derive a new projection" over "change an old fact."

## 9. High-Level Architecture

```text
API / UI / Agent Callback
        |
        v
Command Parser and Boundary Validation
        |
        v
Graph Controller
  - validates command ordering
  - validates leases and snapshots
  - validates graph patch authority
  - classifies file-state boundaries
  - emits accepted events
        |
        v
Event Store append transaction
        |
        +--> Projection reducers
        +--> Outbox side-effect records
        +--> WebSocket/activity feed
        |
        v
Scheduler pure decision
        |
        v
Agent Runtime Adapter
```

The controller must never rely on process-local runner state as authoritative. Active work is represented by accepted lease events and node states.

## 10. Core Data Model

### 10.1 Run

Required fields:

```json
{
  "run_id": "run-123",
  "routine_snapshot_id": "routine-snap-456",
  "repo_id": "repo-abc",
  "worktree_path": "worktrees/run-run-123",
  "run_branch": "orchestrator/run-run-123",
  "lifecycle_state": "active",
  "root_snapshot_id": "S0",
  "event_position": 128
}
```

Run lifecycle projection states:

| State | Meaning |
|---|---|
| `draft` | Run exists but has not been scheduled. |
| `queued` | Run is accepted and awaiting start. |
| `active` | Controller may schedule work. |
| `pausing` | Pause command accepted; controller is reaching a boundary. |
| `paused` | No new work scheduled. Active leases are suspended or revoked. |
| `resuming` | Resume command accepted; scheduler will re-evaluate. |
| `cancelling` | Cancel accepted; active leases are being revoked. |
| `cancelled` | Terminal cancellation. |
| `completed` | Terminal success. |
| `failed` | Terminal failure requiring human/actionable recovery outside normal graph flow. |

Run lifecycle transitions:

| From | To | Trigger | Notes |
|---|---|---|---|
| `draft` | `queued` | Run accepted | Routine snapshot and initial graph created. |
| `queued` | `active` | Start command accepted | Root snapshot/worktree ready. |
| `active` | `pausing` | Pause command accepted | No new leases granted. |
| `pausing` | `paused` | Active lease policy resolved | Leases suspended or revoked. |
| `paused` | `resuming` | Resume command accepted | Scheduler will re-evaluate from projection. |
| `resuming` | `active` | Resume applied | Ready nodes may be leased. |
| `active`/`paused` | `cancelling` | Cancel command accepted | Active leases revoked. |
| `cancelling` | `cancelled` | Cancellation complete | Terminal. |
| `active` | `completed` | Completion invariants pass | Terminal success. |
| Any nonterminal | `failed` | Unrecoverable controller/system error | Terminal unless explicit repair flow later reopens via new run. |

### 10.2 Node

Required fields:

```json
{
  "node_id": "build-A-1",
  "run_id": "run-123",
  "kind": "worker",
  "role": "builder",
  "state": "ready",
  "created_by_event": "evt-10",
  "authority": {
    "allowed_actions": ["submit_records", "request_clarification", "raise_appeal"],
    "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["src/**", "tests/**"]}]
  },
  "inputs": [{"port": "requirements", "required": true}],
  "outputs": [{"port": "candidate", "schema": "ImplementationCandidate"}]
}
```

Node kinds for v1:

| Kind | Purpose | Executable |
|---|---|---|
| `root` | Run root and routine identity. | No |
| `task_projection` | Derived progress for a user-visible task. | No |
| `worker` | Builder or implementation agent activity. | Yes |
| `verifier` | Verification agent activity. | Yes |
| `check` | Deterministic command/test/auto-verify activity. | Yes |
| `planner` | Planning activity that may propose graph patches. | Yes |
| `oversight` | Authority node for appeals, scope disputes, invalid tests, or recovery decisions. | Yes or human |
| `appeal` | Request for higher authority. | No, routed to oversight |
| `gate` | Human or policy approval gate. | No, resolved by decision |
| `recovery` | Classifies or repairs environment/tool failures. | Yes |
| `review` | Review workbench action or gate. | Yes or human |
| `artifact` | Immutable semantic output. | No |
| `requirement` | Durable requirement/constraint record. | No |
| `file_state` | Snapshot/manifest record. | No |
| `session` | Retained agent context handle. | No authority by itself |
| `command` | Serialized lifecycle or scheduling command. | No |

### 10.3 Identity and Lineage

A node is the planned graph unit. An execution is one runtime attempt to complete that node under a lease. An attempt is the product-facing try number for a task region. A candidate is a worker-produced output/file-state pair that may be verified.

V1 identity rules:

- Runtime retry after infrastructure failure creates a new execution for the same node if no accepted file-state boundary was crossed.
- Builder/verifier revision after accepted verification failure creates new revision nodes in the same task region.
- Every worker candidate has `candidate_id`, `attempt_number`, `producer_node_id`, and `file_state_record_id`.
- Verifier/check nodes reference the `candidate_id` they evaluate.
- Candidate ordering is by `attempt_number`, then creation event position.
- A verifier result applies only to the candidate id it references.
- Task projections aggregate nodes by `task_region_id`.

Required membership fields for executable nodes:

```json
{
  "task_region_id": "task-A",
  "attempt_number": 2,
  "candidate_id": "candidate-A-2",
  "execution_id": "exec-build-A-2-1"
}
```

`task_region_id` is the stable user-visible task grouping. It may contain multiple worker, verifier, check, appeal, and recovery nodes over time.

### 10.4 Port

A port is a named typed interface on a node.

```json
{
  "node_id": "verify-A-1",
  "port": "verification_report",
  "direction": "output",
  "schema": "VerificationReport",
  "record_layers": ["output", "graph_record"]
}
```

Ports, not node titles, define what downstream nodes may consume.

### 10.5 Edge

An edge binds one output port to one input port.

```json
{
  "edge_id": "edge-verify-A",
  "from_node_id": "build-A-1",
  "from_port": "candidate",
  "to_node_id": "verify-A-1",
  "to_port": "candidate_under_test",
  "required": true,
  "accepted_record_selector": {
    "record_kinds": ["output", "file_state"],
    "schema": "ImplementationCandidate"
  }
}
```

There are not separate data/control/policy edge types in v1. Instead:

- Data flows as output records referenced by ports.
- Files flow as file-state records referenced by ports.
- Controller decisions flow as graph records appended to the event log.

Edges are immutable topology. Runtime binding is separate. When a source record becomes accepted and satisfies an edge selector, the controller may append an `input_bound` event that records:

```json
{
  "edge_id": "edge-verify-A",
  "to_node_id": "verify-A-1",
  "to_port": "candidate_under_test",
  "record_ids": ["rec-output-1", "rec-file-S1"],
  "bound_at_position": 43
}
```

Readiness is computed from input bindings, not by mutating the edge.

## 11. Record Model

All records are immutable once accepted.

### 11.1 Output Record

Used for typed semantic data.

```json
{
  "record_id": "rec-output-1",
  "record_kind": "output",
  "producer_node_id": "build-A-1",
  "port": "candidate",
  "schema": "ImplementationCandidate",
  "value": {
    "summary": "Implemented validation path",
    "changed_paths": ["src/foo.py", "tests/unit/test_foo.py"],
    "requirements_addressed": ["R1", "R4"]
  }
}
```

### 11.2 File-State Record

Used for filesystem state produced or consumed by nodes.

```json
{
  "record_id": "rec-file-S1",
  "record_kind": "file_state",
  "snapshot_id": "S1",
  "base_snapshot_id": "S0",
  "producer_node_id": "build-A-1",
  "git": {
    "commit_sha": "abc123",
    "tree_sha": "def456",
    "no_commit_reason": null
  },
  "tracked": [{"path": "src/foo.py", "status": "modified"}],
  "untracked": [],
  "ignored": [{"path": ".pytest_cache", "classification": "tool_cache", "policy": "ephemeral_allowed"}],
  "external": []
}
```

If no Git commit exists, the file-state record must still provide one of:

- `patch_bundle_id`: patch against the base snapshot.
- `tree_snapshot_id`: captured filesystem tree for tracked and declared untracked files.
- `no_commit_reason`: accepted reason such as `commit_hooks_failed`, `verification_only`, or `empty_change`.

`no_commit_reason` alone is acceptable only when there is no filesystem delta to pass downstream. If a downstream node must consume changed files, the file-state record must include a commit, patch bundle, or tree capture.

V1 decision: any file-state record consumed by a downstream executable node must reference either a Git commit or an accepted patch bundle. Dirty worktree state is never a valid downstream input. If commit hooks fail and patch bundle support is unavailable, the producing node cannot complete successfully; it must route to recovery, revision, or failed outcome with evidence.

The downstream consumer must not depend on a dirty worktree reference without an accepted file-state record.

### 11.3 Graph Record

Used for accepted controller decisions.

Examples:

- `node_created`
- `edge_created`
- `node_retired`
- `node_state_changed`
- `lease_granted`
- `lease_suspended`
- `lease_revoked`
- `callback_received`
- `callback_accepted`
- `callback_rejected_stale`
- `verification_passed`
- `verification_failed`
- `revision_created`
- `appeal_opened`
- `oversight_decision_recorded`
- `approval_decision_recorded`
- `graph_patch_accepted`
- `file_state_accepted`

Graph records are controller-decision payloads inside accepted graph events. They are not a third mutable store. Agents may propose graph actions, but only the controller can append the accepted graph event carrying the graph record payload.

## 12. Events, Commands, and Atomicity

### 12.1 Event Envelope

Every accepted event has:

```json
{
  "event_id": "evt-123",
  "run_id": "run-123",
  "position": 42,
  "event_type": "node_state_changed",
  "schema_version": 1,
  "actor": {"kind": "controller"},
  "causation_id": "callback-789",
  "correlation_id": "build-A-1",
  "timestamp": "2026-06-10T10:00:00Z",
  "payload": {}
}
```

Ordering rules:

1. Events are totally ordered per run by `position`.
2. Commands are processed against the projection at a known `position`.
3. A command that depends on stale `expected_position` is rejected or retried by the caller.
4. Projection reducers apply events in position order.
5. Scheduler decisions must include the projection position they were computed from.

### 12.2 Command Handling

Command handling has this shape:

```text
validate boundary input
load projection at position P
run pure policy/reducer planning
append accepted events in one transaction
enqueue side effects in outbox records in same transaction
publish projection/activity updates after commit
```

If event append fails, no side effect may start. Only durable side-effect intent is written inside the controller transaction. The transaction may write events and outbox rows, but it must not start agents, run tests, touch Git, or call external processes before commit. If writing the outbox row fails, the transaction fails. If runtime dispatch fails after commit, recovery is modeled by dispatch failure events and outbox retry policy, not by rewriting state.

### 12.3 Starting Agent Side Effects

Agent dispatch is a side effect caused by accepted lease events. The safe sequence is:

1. Controller accepts `lease_granted` and `agent_dispatch_requested` events.
2. Same transaction writes an outbox item keyed by event id.
3. Outbox worker starts or resumes the agent.
4. Agent callbacks include the lease identity.

Crash cases:

| Crash Point | Recovery |
|---|---|
| Before append | No lease exists; scheduler may decide again. |
| After append, before outbox starts agent | Outbox item is pending; restart starts agent. |
| After agent starts, before start acknowledgement | Lease exists; runtime recovery reattaches or waits for callback/expiry. |
| Agent dies | Controller accepts `agent_died`, revokes lease, creates retry/recovery according to policy. |

Scheduling itself is a command:

```text
ScheduleTick(run_id, expected_position, now)
```

The controller handles a schedule tick by loading the projection at `expected_position`, computing ordered scheduling decisions, and appending `node_ready`, `lease_granted`, `agent_dispatch_requested`, and outbox rows in one transaction. A scheduler process may request ticks, but the controller owns the accepted scheduling events.

## 13. Runtime Recovery Policy

On startup, the controller rebuilds projections from the event log and then reconciles in-flight side effects.

| Rebuilt State | Runtime Check | Recovery |
|---|---|---|
| Active lease with known managed process | Process alive and adapter can reattach | Reattach session and continue waiting for callback. |
| Active lease with missing process | Managed process absent | Accept `agent_died`, revoke lease, create retry/recovery if policy allows. |
| Active lease for user-managed runtime | No direct process ownership | Keep lease until expiry or callback; expose pending external action. |
| Suspended lease with retained session | Session available | Keep suspended; resume requires new generation. |
| Outbox dispatch pending | Outbox item not completed | Retry dispatch idempotently. |
| Callback received but not accepted | Has callback receipt event only | Re-run callback validation against rebuilt projection. |

The controller must not infer success from a live process or from files on disk. Success requires an accepted callback and accepted boundary/file-state records.

## 14. Projection Rules

Projection categories:

- Run lifecycle projection.
- Node state projection.
- Task projection over worker/verifier/check attempts.
- Active lease projection.
- Ready-node projection.
- File-state summary.
- Review readiness.
- Pending human decisions.
- Activity timeline.

Projection reducers must be deterministic. They may not call time, random, network, filesystem, or agent APIs. Time and IDs appear only as event payload fields.

Task projection formula for v1:

```text
accepted if latest candidate has accepted verifier pass and all configured gates passed
needs_revision if latest candidate has accepted verifier failure and no active appeal overrides it
blocked_invalid_test if oversight accepted invalid-test appeal and no replacement verification has passed
blocked_environment if latest check failed as environment/tool error
in_progress if a worker/verifier/check lease is active for the task region
pending if no candidate attempt has started
```

This means a task is not itself the mutable source of truth. It is a projection over attempt, verification, gate, appeal, and file-state facts.

`latest candidate` is selected by highest `attempt_number`, then candidate creation event position. A verifier/check result is ignored by the task projection unless its referenced `candidate_id` matches the candidate being evaluated.

## 15. Node Lifecycle and Transitions

Common node states:

| State | Meaning |
|---|---|
| `planned` | Exists but not yet eligible to run or resolve. |
| `blocked` | Waiting on unmet dependency, gate, lifecycle state, resource, or decision. |
| `ready` | Eligible for scheduling or decision. |
| `leased` | Authority granted but agent/check has not confirmed running. |
| `running` | Agent/check side effect is active. |
| `suspended` | Runtime context may be retained, but current authority is paused. |
| `completed` | Node produced accepted outputs. |
| `failed` | Node ended in accepted failure. |
| `retired` | Node was superseded before completion and is retained for audit. |
| `cancelled` | Node was actively cancelled. |

Any executable node in `leased`, `running`, or `suspended` may transition to `cancelled` when a cancel command is accepted for its run or graph region. Cancellation revokes active leases and rejects later mutating callbacks as stale.

### 15.1 Worker

| From | To | Trigger | Authority |
|---|---|---|---|
| `planned` | `ready` | Readiness evaluator | Controller |
| `ready` | `leased` | Scheduler grants lease | Controller |
| `leased` | `running` | Agent start accepted | Runtime adapter via controller |
| `running` | `completed` | Callback accepted with output/file-state | Controller |
| `running` | `suspended` | Clarification, appeal, pause | Controller |
| `suspended` | `leased` | Resume/renew lease | Controller |
| `running` | `failed` | Agent death or accepted failure | Controller |
| `planned`/`ready` | `retired` | Planner/oversight patch accepted | Controller |

### 15.2 Verifier

| From | To | Trigger | Authority |
|---|---|---|---|
| `planned` | `ready` | Candidate file-state bound | Controller |
| `ready` | `leased` | Scheduler grants verifier lease | Controller |
| `leased` | `running` | Verifier starts | Runtime adapter via controller |
| `running` | `completed` | Verification passed or failed as valid result | Controller |
| `running` | `failed` | Verifier runtime error | Controller |

Verification failure is a valid completed verifier result if the verifier ran correctly and found requirement failure. Verifier runtime error is `failed` or `recovery_required`. An invalid-test appeal does not mutate the completed verifier node; it creates an appeal node and the task projection derives `disputed` or `blocked_invalid_test`.

### 15.3 Check and Recovery

| From | To | Trigger | Authority |
|---|---|---|---|
| `planned` | `ready` | Inputs and command definition available | Controller |
| `ready` | `leased` | Scheduler grants check lease | Controller |
| `leased` | `running` | Check command starts | Runtime adapter via controller |
| `running` | `completed` | Command exits and result classified | Controller |
| `running` | `failed` | Command runner crashes or result cannot be classified | Controller |
| `failed` | `failed` plus recovery node created | Environment/tool failure accepted | Controller creates recovery path |

A failing test result is not automatically a failed check node. It may be a completed check node with `passed=false`. A check node fails only when the check itself could not produce a valid result.

### 15.4 Gate

| From | To | Trigger | Authority |
|---|---|---|---|
| `planned` | `ready` | All gate inputs present | Controller |
| `ready` | `blocked` | Waiting for human/policy decision | Controller |
| `blocked` | `completed` | Approval/rejection decision accepted | Human or policy authority via controller |

Gate result is in the decision record. A completed gate may be approved or rejected.

### 15.5 Appeal/Oversight

| From | To | Trigger | Authority |
|---|---|---|---|
| `planned` | `ready` | Appeal accepted as well formed | Controller |
| `ready` | `completed` | Oversight decision accepted | Oversight/human via controller |
| `ready` | `failed` | Appeal invalid or rejected as malformed | Controller |

Appeal nodes do not rewrite the appealed node. They add a decision path.

### 15.6 Planner

| From | To | Trigger | Authority |
|---|---|---|---|
| `planned` | `ready` | Planning inputs available | Controller |
| `ready` | `leased` | Scheduler grants planner lease | Controller |
| `leased` | `running` | Planner starts | Runtime adapter via controller |
| `running` | `completed` | Graph patch proposal received and processed | Controller |
| `running` | `failed` | Planner runtime failure | Controller |

Planner completion does not imply its patch was accepted. Patch acceptance is a separate graph record.

### 15.7 Review

| From | To | Trigger | Authority |
|---|---|---|---|
| `planned` | `ready` | Review inputs available | Controller |
| `ready` | `leased`/`blocked` | Scheduler or human gate | Controller |
| `leased` | `running` | Review action starts | Runtime adapter via controller |
| `running` | `completed` | Review record/file-state accepted | Controller |
| `running` | `failed` | Review action cannot complete | Controller |

### 15.8 Non-Executable Record Nodes

Artifact, requirement, file-state, session, command, and projection nodes do not follow the full executable lifecycle. They are created by accepted events and then superseded, retired, or recomputed according to their mutability rules. They are never leased to agents.

## 16. Graph Patch Model

Planner, oversight, and human operations modify the graph through domain-specific patch operations.

Patch envelope:

```json
{
  "patch_id": "patch-123",
  "proposed_by_node_id": "planner-1",
  "base_graph_position": 42,
  "ops": [
    {
      "op": "create_node",
      "node": {"node_id": "build-A2-1", "kind": "worker", "role": "builder"}
    },
    {
      "op": "create_edge",
      "from_node_id": "read-tests",
      "from_port": "findings",
      "to_node_id": "synthesis",
      "to_port": "context"
    }
  ],
  "rationale_record_id": "rec-plan-rationale-1"
}
```

Allowed v1 operations:

| Operation | Meaning |
|---|---|
| `create_node` | Add planned node. |
| `create_edge` | Add input binding. |
| `retire_node` | Retire not-running node. |
| `create_revision_attempt` | Add new worker/verifier pair after failed verification. |
| `create_appeal` | Add appeal plus oversight route. |
| `create_gate` | Add human/policy gate. |
| `set_resource_claims` | Set or narrow node resource claims. |
| `set_allowed_actions` | Set or narrow allowed actions. |
| `mark_plan_region_suspect` | Mark future region for review after context change. |

`bind_input` is controller-only in v1. The controller may append an `input_bound` record only after an accepted record satisfies an immutable edge selector and schema. Planner/user patches cannot bind arbitrary records to inputs.

Patch validation rules:

1. Patch base position must be current or mergeable by deterministic revalidation.
2. Actor role must have permission for every operation.
3. Patch cannot modify immutable records.
4. Patch cannot retire or replace a running node unless a cancellation operation is accepted first.
5. Patch cannot grant authority broader than actor's delegation scope unless gated by oversight/human approval.
6. Patch cannot create executable nodes without required role, resource, and input-port declarations.
7. Patch cannot remove evidence required for audit; it can supersede or invalidate support edges/projections.
8. Patch must leave graph acyclic for execution dependencies, except explicitly declared feedback loops such as revision cycles represented by new attempt nodes.

For v1, a graph patch whose `base_graph_position` is stale is rejected unless every operation is append-only and all referenced nodes, ports, records, and authority scopes are unchanged since the base position. The controller determines this by revalidating the patch against the current projection. If revalidation changes the meaning of the patch, the patch is rejected and the planner must replan.

## 17. Readiness and Scheduling

The scheduler must be a pure deterministic function:

```text
schedule(graph_projection, active_leases, resource_policy, lifecycle_state, now) -> SchedulingDecision[]
```

`now` is an injected value, not read from global time.

A planned or blocked node becomes a ready candidate when:

1. Run lifecycle permits scheduling.
2. Node state is `planned` or `blocked`.
3. All required input ports have accepted records.
4. No upstream required dependency is failed, cancelled, or pending appeal unless policy explicitly allows recovery.
5. Any human gate input is approved.
6. Resource claims are valid and compatible with active leases.
7. Node has not been retired.
8. Node-specific preconditions pass.

The scheduler grants leases only to nodes whose projected state is `ready`. A schedule tick may append `node_ready` events for eligible nodes and `lease_granted` events for the selected subset in the same transaction.

When multiple nodes are ready, the scheduler orders candidates by:

1. Explicit priority.
2. Graph region order.
3. Creation event position.
4. Node id lexical order.

The scheduler emits decisions with the projection position and ordered candidate list so tests can assert both selected and deferred nodes.

Optional inputs:

- Missing optional inputs do not block readiness.
- If present, optional inputs must still satisfy schema and snapshot compatibility.

Failed dependencies:

- A failed dependency blocks successors by default.
- Recovery/oversight nodes may consume failed dependency records.
- Revision nodes consume failed verification records as input.

Retired predecessors:

- A retired predecessor satisfies dependencies only if the edge explicitly accepts `retired` as a terminal planning outcome.

## 18. Resource and Parallelism Policy

### 18.1 Resource Claims

Resource claim shape:

```json
{
  "mode": "read",
  "scope": "repo",
  "paths": ["src/**", "tests/**"],
  "snapshot_id": "S0"
}
```

Modes:

- `read`
- `write`
- `graph_write`
- `review_write`
- `external`

External claims must include an `external_resource_key`, for example `github:repo:owner/name`, `mcp:server:name`, or `service:database:alias`. Two external claims conflict when they have the same key and either claim has mode `write` or an exclusive policy flag. Read-only external claims with the same key are compatible unless the resource declaration marks them exclusive.

Path normalization rules:

1. Paths are repository-relative POSIX paths.
2. Normalize `.` and `..`; reject paths escaping repo root.
3. Follow a deterministic glob implementation.
4. Directory claims expand recursively.
5. Symlinks are resolved for conflict checking when possible; unresolved symlinks are treated as conflicting with the containing directory.
6. Case sensitivity follows repository platform policy, recorded in the run.

Conflict matrix:

| Existing \ Requested | `read` | `write` | `graph_write` | `review_write` | `external` |
|---|---|---|---|---|---|
| `read` | Compatible if same snapshot or immutable snapshot | Conflict on overlapping live-worktree paths | Compatible; controller serializes graph write | Conflict if review touches same live paths | Compatible unless external declaration says exclusive |
| `write` | Conflict unless requested read uses immutable snapshot | Conflict on same run worktree in v1 | Compatible; controller serializes graph write | Conflict | Compatible unless external declaration says exclusive |
| `graph_write` | Compatible | Compatible unless patch touches active writer lease | Conflict; controller serializes | Compatible unless review graph is being patched | Compatible |
| `review_write` | Conflict if live paths overlap | Conflict | Compatible unless patch touches review region | Conflict | Compatible unless external declaration says exclusive |
| `external` | Compatible unless external declaration says exclusive | Compatible unless external declaration says exclusive | Compatible | Compatible unless external declaration says exclusive | Conflict by matching `external_resource_key` when either side writes or is exclusive |

`graph_write` is not a runner lease in v1. It is controller serialization over graph patch application. It is included in resource policy so patch validation can reject operations that would touch active leases.

### 18.2 Default v1 Policy

Default policy is conservative:

1. Many read nodes may run concurrently if they read the same stable snapshot.
2. A write node requires exclusive write lease for the run worktree.
3. No reader may inspect the mutable worktree while a writer is running.
4. A reader may run during a writer only if it reads an immutable snapshot copy, not the live worktree.
5. Graph patch application is single-threaded through the controller.
6. Review destructive operations require exclusive write authority.

Reader during writer is not a runtime shrug of "wait or snapshot." It is a deterministic policy decision:

```text
if reader has immutable snapshot source:
    grant read lease over that snapshot
else:
    wait until writer releases lease and new snapshot is available
```

## 19. Lease and Callback Semantics

Every agent/check callback must include:

- `run_id`
- `node_id`
- `execution_id`
- `lease_id`
- `lease_generation`
- `base_snapshot_id`
- `observed_graph_position`
- idempotency key

`attempt_number` is derived from node lineage and may be included for diagnostics, but `execution_id` is the required runtime identity for callback validation.

Lease record:

```json
{
  "lease_id": "lease-1",
  "generation": 3,
  "run_id": "run-123",
  "node_id": "build-A-1",
  "session_id": "session-W7",
  "base_snapshot_id": "S0",
  "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["**"]}],
  "expires_at": "2026-06-10T10:20:00Z",
  "state": "active"
}
```

Lease states:

| State | Meaning | Callback Behavior |
|---|---|---|
| `active` | Current authority is valid. | Mutating callbacks may be accepted after validation. |
| `suspended` | Runtime context may exist but authority is paused. | Mutating callbacks are rejected stale; non-mutating logs may be accepted. |
| `revoked` | Authority ended before normal completion. | Mutating callbacks are rejected stale. |
| `expired` | Controller accepted expiry. | Mutating callbacks are rejected stale. |
| `released` | Node reached accepted boundary. | Duplicate idempotent callback returns prior result; new mutating callback rejected. |

Resume never reactivates the same suspended generation. It emits a new lease generation or a new lease id.

Stale callback behavior:

| Callback Case | Required Outcome |
|---|---|
| Duplicate callback with same idempotency key and same payload | Return prior accepted/rejected result. |
| Duplicate callback with same key and different payload | Reject as idempotency conflict. |
| Callback for revoked lease | Append `callback_rejected_stale`; do not change node outcome. |
| Callback for old lease generation | Append `callback_rejected_stale`; do not change node outcome. |
| Success after node already retried | Reject stale; retry node remains authoritative. |
| Failure after node completed | Reject stale unless it is output-log-only and non-mutating. |
| Approval after cancellation | Reject; cancellation terminal state wins. |
| Resume after cancel | Reject; cancel is terminal. |
| Pause and callback race | Event position decides. If callback accepted first, pause applies after boundary. If pause accepted first and lease revoked/suspended, callback is stale. |

Lease expiry is event-driven. Projections do not silently change state by reading wall-clock time. A controller tick with injected `now` may append `lease_expired` events for leases whose `expires_at` is in the past. Until that event exists, expiry is only a schedulable controller decision, not an unrecorded mutation.

Agent sessions:

- A session can be `attached`, `suspended`, `detached`, or `dead`.
- Session state may be retained for efficiency.
- Session state never grants permission.
- Resuming a session always requires a new active lease generation.

## 20. File-State and Snapshot Policy

### 20.1 Snapshot Types

| Type | Meaning | v1 Support |
|---|---|---|
| `git_commit` | Commit on run branch. | Required when hooks pass and change is committable. |
| `patch_bundle` | Patch against base snapshot plus manifest. | Required v1 fallback when no commit exists but state must be consumed downstream. |
| `tree_capture` | Captured filesystem tree for declared paths. | Deferred; useful for non-Git tracked files. |
| `external_manifest` | Pointer and hash for files outside repo. | Required for external artifacts passed downstream. |

### 20.2 Boundary Check

Before a worker/check/verifier output can be accepted:

1. Collect `git status --porcelain` equivalent for tracked/untracked files.
2. Collect ignored files matching routine/project declared policies.
3. Classify every untracked and ignored file.
4. Reject undeclared untracked residue by default.
5. Accept declared ignored tool caches only as `ephemeral_allowed`.
6. Produce a file-state record.
7. Bind file-state record to downstream inputs.

If boundary check rejects the worktree, the controller records `file_state_rejected` with paths, classifications, and reason. Any cleanup must be represented by a `cleanup_requested` and `cleanup_applied` event with authority and affected paths. Hidden cleanup is not allowed because it destroys evidence needed to explain why a boundary failed.

### 20.3 `.gitignore` Policy

Ignored files are not automatically safe.

Classifications:

| Classification | Policy |
|---|---|
| `tool_cache` | Allowed if known cache pattern; not restored downstream. |
| `build_output` | Allowed only if routine declares it or it is ephemeral. |
| `test_artifact` | Allowed if declared by check/verifier node. |
| `secret` | Never captured; must be declared as external input or rejected. |
| `unknown_ignored` | Rejected by default. |
| `external_artifact` | Captured by manifest with path, hash, origin, retention. |

V1 default classification policy:

1. Unknown ignored files are rejected.
2. Routine/project-declared ignored patterns are accepted only under their configured classification.
3. Built-in known tool caches may be classified as `tool_cache` and treated as `ephemeral_allowed`; they are never restored downstream.
4. Secret-like files are rejected by configured detectors and are never captured into snapshot storage.
5. External artifacts require explicit declaration with path or URI, hash, origin, retention, and redaction policy.

### 20.4 Downstream Consumption

Downstream node execution receives an explicit file-state input packet:

- Base commit/tree.
- Patch bundle or commit to apply.
- Manifest files to restore or mount.
- Ignored/cache policy.
- Paths considered ephemeral and unavailable.

For v1, the simplest implementation may run downstream nodes in the same run worktree after boundary acceptance. Even then, the downstream node must bind to the accepted file-state record so replay/test logic does not depend on implicit worktree state.

### 20.5 Retention

Durable:

- Accepted git commits.
- Accepted patch bundles.
- External artifacts referenced by downstream nodes.
- Verification evidence.

Garbage-collectable:

- Tool caches.
- Failed attempt tree captures not referenced by accepted records.
- Agent logs after configured retention if summarized and not needed for audit.

User-visible:

- File-state summary.
- Residue rejection reason.
- Snapshot lineage.
- Manifest entries that affect reproducibility.

## 21. Agents, Roles, and Permissions

| Role | Can Produce | Can Request | Cannot Do |
|---|---|---|---|
| Planner | Plan, graph patch proposal, rationale | Create/retire future nodes, add edges, add gates | Mutate completed facts, grant itself broader authority, cancel active work without permission |
| Builder | Implementation output, file-state, requirement-addressed claims | Clarification, appeal, scope expansion | Mark itself accepted, change verifier result, alter requirements directly |
| Verifier | Verification report, grades, evidence | Recovery if environment/test system failed | Modify implementation files, silently change requirements |
| Oversight | Decision records, scoped patches | Retry, test fix, scope change, human escalation | Rewrite history, bypass approval policy |
| Check | Test result, command output, file-state if it writes | Recovery classification on crash | Interpret requirements beyond configured check semantics |
| Human | Approval, rejection, clarification, override | Any explicitly exposed operation | Implicitly mutate graph without recorded decision |
| Reviewer | Review records, prune proposals, conflict/test-fix outputs | Merge-back, fix tests, resolve conflicts | Merge without readiness gates |

Permissions are data, not prompt text. Prompt text may explain permissions, but the controller enforces them.

Authority is evaluated from structured data, not role names alone:

```json
{
  "role": "builder",
  "allowed_callback_actions": ["submit_records", "request_clarification", "raise_appeal"],
  "allowed_patch_ops": [],
  "allowed_target_node_kinds": ["worker", "appeal"],
  "allowed_resource_modes": ["read", "write"],
  "allowed_path_scopes": ["src/**", "tests/**"],
  "escalation_targets": ["oversight", "human"]
}
```

Role names select default authority templates. The controller enforces the resolved authority object attached to the node/lease.

## 22. Human Interaction, Appeals, and Oversight

### 22.1 Clarification

Clarification flow:

1. Worker emits `clarification_requested` proposal with questions.
2. Controller validates question count/schema and suspends or revokes lease.
3. Human answer is accepted as an `answer` artifact.
4. Controller binds answer artifact to the worker input.
5. Controller renews lease or creates retry node according to policy.

Timeout policy:

- If no answer before timeout, controller appends `clarification_expired`, revokes or suspends the active lease, and moves the worker projection to `blocked`.
- The retained session may remain `suspended`, but any later answer requires a new lease generation before the worker resumes.
- Optional policy may escalate to oversight or cancel run.

### 22.2 Human Approval

Human approval is distinct from verification.

```text
verification accepted != human approved
```

Approval gates block successor readiness until an `approval_decision` record is accepted.

### 22.3 Appeal

Appeal is a graph action request, not a generic failure state.

Appeals may be raised by:

- an active lease callback before the worker/verifier/check reaches a terminal boundary, or
- a controller-issued appeal lease/token after a verifier/check result is presented to an affected prior worker session.

A completed worker node does not regain general authority. The appeal lease is narrow: it can submit evidence and request an appeal node for the specific verifier/check result, but it cannot modify files or submit new implementation output.

Appeal types:

- `invalid_test`
- `scope_dispute`
- `requirement_ambiguous`
- `environment_fault`
- `blocked_dependency`
- `policy_exception`

Appeal outcomes:

- `upheld_verifier`
- `amend_test_or_requirement`
- `expand_scope`
- `retry_original_worker`
- `create_recovery_node`
- `escalate_to_human`
- `reject_appeal`

Loop control:

- Each node has a retry/appeal budget.
- Repeated appeal of the same subject and reason requires new evidence.
- Exhausted appeals route to human or terminal blocked state.

## 23. Routine Compilation and Dynamic Planning

### 23.1 Existing Routines

Current routine YAML remains valuable. It provides:

- Initial intent and steps.
- Task descriptions and requirements.
- Builder/verifier agent defaults.
- Available tools and MCP scope.
- Auto-verify/check definitions.
- Human gates.
- Fan-out configuration.
- Context/artifact expectations.

### 23.2 Compilation

A routine compiles into an initial graph:

| Routine Concept | Graph Representation |
|---|---|
| Routine | Root node plus routine snapshot record. |
| Step | Plan region or grouping projection. |
| Task | Task projection plus worker/verifier/check nodes. |
| Requirement | Requirement nodes and edges to worker/verifier ports. |
| Auto-verify | Check nodes. |
| Human approval gate | Gate node. |
| Context/artifact dependency | Input binding edge. |
| Fan-out | Reader nodes plus synthesis/join node. |

### 23.3 Dynamic Planning Rules

Planner agents may refine the graph, but not violate routine constraints unless an authorized patch says so.

Default:

- Planner can split or elaborate unstarted routine tasks.
- Planner can add discovery, validation, oversight, and review nodes within delegated scope.
- Planner can mark future plan regions as suspect after requirement changes.
- Planner cannot remove must requirements from routine/user authority.
- Planner cannot weaken validation without oversight/human decision.

## 24. Review Workbench as Graph Continuation

Review is a graph, not an external special case.

V1 decision: review runs as a linked review graph seeded from the execution run's accepted final file-state. The original execution run can remain `completed` while the review graph records back-merge, conflicts, tests, prune actions, and merge-back readiness. Later versions may fold review into the same run graph if the lifecycle model needs it.

Review nodes:

- `review_summary`
- `back_merge`
- `conflict_detection`
- `resolve_conflicts`
- `test_run`
- `agent_fix_tests`
- `prune_proposal`
- `prune_apply`
- `merge_gate`
- `merge_back`

Merge-back readiness requires:

1. Source execution run lifecycle projection is `completed`.
2. No active write leases.
3. No unresolved required appeals.
4. Accepted final file-state exists.
5. Back-merge is clean or conflicts resolved.
6. Required review tests pass.
7. Prune/destructive actions are recorded as file-state changes.
8. Human approval gate passes if configured.

## 25. API Shape

Representative graph API:

```text
GET  /api/runs/{run_id}/graph
GET  /api/runs/{run_id}/events
GET  /api/runs/{run_id}/nodes/{node_id}
GET  /api/runs/{run_id}/leases
GET  /api/runs/{run_id}/file-state/{snapshot_id}
POST /api/runs/{run_id}/commands/start
POST /api/runs/{run_id}/commands/pause
POST /api/runs/{run_id}/commands/resume
POST /api/runs/{run_id}/commands/cancel
POST /api/runs/{run_id}/nodes/{node_id}/callbacks
POST /api/runs/{run_id}/graph-patches
POST /api/runs/{run_id}/human-decisions
POST /api/runs/{run_id}/review/commands/run-tests
POST /api/runs/{run_id}/review/commands/merge
```

Agent callback body:

```json
{
  "run_id": "run-123",
  "node_id": "build-A-1",
  "execution_id": "exec-1",
  "lease_id": "lease-1",
  "lease_generation": 3,
  "base_snapshot_id": "S0",
  "observed_graph_position": 42,
  "idempotency_key": "callback-uuid",
  "records": [
    {"record_kind": "output", "port": "candidate", "value": {}},
    {"record_kind": "file_state", "port": "file_state", "value": {}}
  ],
  "proposed_graph_patches": []
}
```

Callbacks submit proposed records. They do not set node status directly. If a callback proposes graph changes, each proposal must be a full graph patch envelope and must pass the same validation path as `POST /api/runs/{run_id}/graph-patches`.

Typed API errors for commands and callbacks:

| Error | Meaning |
|---|---|
| `stale_lease` | Lease id/generation is not active. |
| `idempotency_conflict` | Same key used with different payload. |
| `graph_position_conflict` | Command based on stale graph position and cannot revalidate. |
| `authority_denied` | Actor lacks required authority. |
| `resource_conflict` | Requested lease conflicts with active resource claims. |
| `schema_invalid` | Request or proposed record fails schema validation. |
| `snapshot_incompatible` | File-state or reader output snapshot is not acceptable for target. |
| `node_not_ready` | Node cannot be leased or resolved yet. |
| `run_lifecycle_blocked` | Run state blocks command. |
| `terminal_state` | Command targets terminal run/node state. |

## 26. UI and Observability Requirements

The user should be able to inspect:

- Current task projection and underlying attempt graph.
- Raw graph region for a task/run.
- Activity/event timeline.
- Active and suspended leases.
- Node detail: inputs, outputs, file-state, prompt packet, callback history.
- Scheduler view: ready, blocked, waiting resources, waiting gates.
- File-state diff and manifest summary.
- Human decisions pending.
- Appeals and oversight decisions.
- Review readiness and merge blockers.

The UI should make projection vs fact visible. A task card may summarize progress, but it must link to the immutable worker/verifier/check facts underneath.

## 27. Unit-First Testing Strategy

### 27.1 Pure Core APIs

The core should expose pure functions suitable for unit tests:

```text
reduce_event(projection, event) -> projection
evaluate_readiness(graph_projection, node_id) -> Readiness
check_resource_conflicts(active_leases, requested_claims, policy) -> ConflictResult
validate_graph_patch(graph_projection, actor_authority, patch) -> PatchValidation
schedule(graph_projection, active_leases, lifecycle_state, now) -> SchedulingDecision[]
classify_file_state(status, ignore_rules, declarations) -> FileStateClassification
validate_callback(projection, callback) -> CallbackValidation
```

### 27.2 Required Property/Invariants Tests

- Replaying the same event stream produces the same projection.
- No two conflicting write leases can be active.
- No callback without valid lease can alter node outcome.
- Successor cannot be released before required inputs are accepted.
- Retired nodes cannot become running.
- Planner cannot grant authority outside its scope.
- Verification failure does not mutate builder completion facts.
- Reader output bound to `S0` is not consumed by node requiring `S1`.
- Human approval gates block successors until decision.
- File-state acceptance rejects undeclared untracked residue.

### 27.3 Scenario Fixture Format

Pressure-test slides should become executable fixtures.

```yaml
name: verifier_test_is_suspected_wrong
given_events:
  - node_created: {node_id: build-A-1, kind: worker}
  - output_record_accepted: {producer_node_id: build-A-1, record_id: rec-candidate-A1}
  - file_state_accepted: {producer_node_id: build-A-1, snapshot_id: S1}
  - node_state_changed: {node_id: build-A-1, new_state: completed}
  - verification_completed: {node_id: verify-A-1, candidate_id: candidate-A-1, result: failed}
  - lease_suspended: {node_id: build-A-1, lease_id: lease-appeal-A1}
when_command:
  raise_appeal:
    node_id: build-A-1
    lease_id: lease-appeal-A1
    appeal_type: invalid_test
then_events:
  - appeal_opened
  - node_created: {kind: oversight}
  - lease_suspended
then_projection:
  task_A: blocked_invalid_test
  worker_session: suspended
```

### 27.4 Failure Injection Tests

Unit or integration tests must cover:

- Crash after event append but before agent dispatch.
- Crash after agent dispatch but before start acknowledgement.
- Duplicate callback.
- Stale callback after retry.
- Pause/cancel racing with callback.
- Corrupted or incomplete file-state manifest.
- Planner patch based on stale graph position.
- Lease expiry with retained session.

### 27.5 Test Boundaries

Unit tests may use:

- Pure reducers.
- In-memory event store.
- Real Pydantic models.
- Fake injected clock/ID generator.
- Real temporary filesystem only when testing file-state classifier.

Unit tests should not need:

- HTTP server.
- Real LLM.
- Running agent process.
- Browser.
- Git network remotes.

Integration tests cover:

- Git worktree mechanics.
- Real SQLite persistence.
- Runner adapter contract.
- API and WebSocket behavior.
- Review workbench command paths.

## 28. Functional Restrictions for Correctness

These are deliberate restrictions, not missing features:

1. Only the controller can append accepted graph mutation events.
2. All lifecycle commands are serialized by run event position.
3. Active write lease count per run worktree is at most one in v1.
4. Readers during writers must use immutable snapshots or wait.
5. Agents cannot self-expand scope.
6. Agents cannot mark their own work accepted.
7. Planner patches cannot touch active leases without explicit cancellation flow.
8. All callbacks require lease identity and base snapshot.
9. Node completion is accepted only at a boundary after file-state classification.
10. Routine/user must requirements cannot be removed by planner alone.

These restrictions are expected to improve reasoning and unit-test coverage more than they reduce useful agent autonomy.

## 29. Minimum Viable Graph Kernel

V1 should prove the kernel before implementing full dynamic planning.

V1 includes:

1. Compile routine tasks into worker/verifier/check/gate graph nodes.
2. Task projections derived from attempt and verifier nodes.
3. One edge model with typed port bindings.
4. Leases with generation checks.
5. Event log as authority and rebuildable projections.
6. Deterministic readiness and scheduler policy.
7. Single-writer default resource policy.
8. File-state records with Git commit or accepted patch-bundle fallback plus residue classification.
9. Clarification, approval, invalid-test appeal, and recovery nodes.
10. Review workbench represented as a graph region or graph continuation.

V1 defers:

- Arbitrary planner graph rewrites.
- Multiple concurrent writers with path-level merging.
- Perfect environment snapshotting outside Git.
- Distributed scheduler processes.
- Rich visual graph editing.

## 30. Storage Boundaries

| Store | Contents |
|---|---|
| Event store | Accepted events and raw received callbacks/commands where needed for audit. |
| Projection tables | Run, node, task, lease, readiness, review summaries. |
| Artifact store | Large output records, prompt packets, logs, evidence files. |
| Snapshot store | Patch bundles, tree captures, sidecar manifests. |
| Worktree | Mutable execution surface for active write node. |

Large logs should be chunked or summarized, but their accepted record ids must remain stable.

## 31. Implementation Boundaries

The graph kernel should live behind the public `orchestrator.workflow` module API.

Suggested code boundaries:

| Area | Owns | Must Not Import |
|---|---|---|
| `orchestrator.workflow.graph.models` | Pydantic graph command/event/record models | FastAPI, SQLAlchemy sessions, runner adapters, UI schemas |
| `orchestrator.workflow.graph.reducers` | Pure projection reducers | Filesystem, network, clocks, random |
| `orchestrator.workflow.graph.scheduler` | Readiness/resource scheduling decisions | Runner adapters, DB sessions |
| `orchestrator.workflow.graph.patches` | Graph patch validation | FastAPI, runner adapters |
| `orchestrator.workflow.graph.leases` | Lease and callback validation | Runner processes |
| `orchestrator.workflow.graph.file_state` | File-state classification policy | Agent prompts, HTTP |
| `orchestrator.db` | Event store, projection persistence, artifact/snapshot storage adapters | Business policy not already expressed by graph kernel |
| `orchestrator.runners` | Dispatch, reattach, suspend, terminate runtime sessions | Direct graph mutation |
| `orchestrator.api` | Boundary schemas and command translation | Reducer internals beyond public API |

Pure graph code should be importable in unit tests without constructing the FastAPI app, DB engine, runner registry, or worktree.

## 32. Migration Approach

1. Keep current routine authoring and runner adapters.
2. Introduce graph event types and projections behind compatibility APIs.
3. Compile existing runs into a simple graph shape.
4. Route builder/verifier callbacks through graph callback validation.
5. Move task status UI to task projection.
6. Add file-state boundary checks.
7. Add appeal/oversight nodes.
8. Move review actions into graph region.
9. Gradually remove direct compatibility mutation paths.

Old runs:

- Existing event-backed runs may be migrated to graph projections if enough event data exists.
- Runs without sufficient data can remain read-only legacy records.
- Migration must not pretend missing file-state facts exist.

## 33. Risks

| Risk | Mitigation |
|---|---|
| Graph model becomes too general | Keep v1 node kinds small; require schemas and reducers for every kind. |
| Retained sessions become hidden state | Enforce lease identity and graph packet reconstruction. |
| File-state tracking grows too complex | Start with conservative rejection and explicit declarations. |
| Planner authority becomes unsafe | Domain-specific patch ops and authority validation. |
| Event schemas harden too early | Version events and keep v1 patch ops minimal. |
| UI hides immutable facts behind task cards | Always link projections to underlying nodes/events. |
| Scheduler policies become prompt logic | Keep scheduler pure and tested. |

## 34. Open Decisions

These are true design choices, not runtime ambiguities:

Must decide before v1 implementation starts:

1. What is the first UI view: task projection with drill-down, raw graph, or scheduler/lease view?
2. How long should session context be retained after suspension if retained sessions are enabled?

V1 decisions already made in this document:

- Consumable no-commit file-state requires an accepted patch bundle.
- Review is a linked review graph seeded from the completed execution run's final file-state.
- Reader during writer requires an immutable snapshot source or waits.
- The scheduler uses explicit tie-break ordering.

Defer beyond v1:

1. Should retained agent sessions be required behavior, or an optional optimization after graph packets are stable?
2. How much planner authority is safe before human/oversight approval?
3. Should graph patch syntax remain domain-specific only, or allow JSON Patch for projection-like records?

## 35. Acceptance Criteria for This Architecture

The architecture is ready to implement when:

1. The pressure-test scenarios can be represented as executable graph fixtures.
2. The reducer can replay every fixture to the expected projection.
3. The scheduler can explain every ready/blocked decision in fixture output.
4. Stale callback tests cover success, failure, duplicate, pause, cancel, and retry races.
5. File-state classifier has deterministic outcomes for tracked, untracked, ignored, external, and secret-like files.
6. Existing routine YAML can compile into the v1 graph shape without losing builder/verifier/check/gate semantics.
7. The UI can distinguish projections from immutable facts.
8. No runner callback path can mutate run/task/node state without controller acceptance.

A v1 implementation is complete when:

1. An existing routine compiles into graph nodes.
2. One builder/verifier cycle runs through an existing runner adapter.
3. A stale callback is rejected in a unit test.
4. Task projection rebuilds from events without direct task-status mutation.
5. Graph/task projection is exposed through compatibility APIs.
6. A consumable no-commit worker output is either represented by a patch bundle or rejected into recovery/failure.
