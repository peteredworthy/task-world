# Typed Dynamic Work Graph Requirements

This document defines the functionality required for the dynamic graph to become
a true work-execution graph, not only a carrier that can run hand-authored graph
shapes.

The target state is:

- graph nodes have declared, validated I/O contracts;
- edge data is typed, queryable, and hydrated into downstream execution packets;
- planners mutate the graph through constrained tools or macros, not raw
  best-effort JSON;
- scheduling is deterministic, fair, recoverable, and unable to quiesce silently
  while work is still possible;
- deterministic checks and graph invariants, not prompt discipline, determine
  completion.

The current low-level runtime contract discovered during DG-5.1 remains useful
as historical input, but this document is the implementation checklist for the
next version.

Related context:

- `docs/graph-approach/complete/dynamic-graph-contract.md`
- `docs/dynamic-graph/status.md`
- `routines/dynamic-graph-feature/routine.yaml`

## 1. Scope Boundary

The dynamic graph product is the execution system for adaptive coding work.
Comparison oracles, hidden tests, and carrier-evaluation scenarios are useful
measurement harnesses, but they are not product functionality.

The implementation is complete only when a real run can:

1. start from a feature goal and routine snapshot;
2. create a typed graph of planner, worker, verifier, check, and corrective
   nodes;
3. route typed records over edges;
4. schedule ready nodes without deadlock or silent quiescence;
5. execute deterministic checks as runtime commands;
6. allow authorized planner/gap-planner graph modification;
7. complete only when graph invariants, verification, file-state, and checks are
   satisfied.

## 2. Required Node Types

Use a small canonical node taxonomy. Roles can specialize behavior, but every
executable or data-source node must have a declared contract.

### 2.1 Controller/Data Nodes

- [ ] `run_root`
  - Purpose: controller-owned root for one run.
  - Handler: controller only.
  - Inputs: none.
  - Outputs: `run_context`.
  - Completion: created once at run bootstrap.
  - Notes: not schedulable; no agent lease.

- [ ] `routine_snapshot`
  - Purpose: immutable routine inputs, feature spec, acceptance commands, model
    defaults, and run-level policy.
  - Handler: controller only.
  - Inputs: none.
  - Outputs: `routine_snapshot`.
  - Completion: created once at graph bootstrap.
  - Notes: hidden commands may be referenced by opaque binding IDs, not exposed
    verbatim to planner prompts.

- [ ] `requirement`
  - Purpose: immutable or versioned requirement facts extracted from the routine
    or planner analysis.
  - Handler: controller or authorized planner.
  - Inputs: optional `routine_snapshot`, optional `analysis_summary`.
  - Outputs: `requirement_record`.
  - Completion: terminal after accepted creation or amendment.
  - Notes: amendments create new versions; old requirement records are never
    overwritten.

- [ ] `artifact_index`
  - Purpose: controller-owned index of accepted files, patches, reports, and
    semantic outputs.
  - Handler: controller only.
  - Inputs: `candidate`, `file_state`, `check_result`, `verification_report`.
  - Outputs: `artifact_reference`.
  - Completion: updated by accepted records, not manually leased.

### 2.2 Planning Nodes

- [ ] `planner`
  - Purpose: decompose the goal, create initial work regions, and optionally add
    follow-up planning nodes.
  - Handler: agent.
  - Required inputs: `routine_snapshot`.
  - Optional inputs: `requirement_record`, `analysis_summary`,
    `graph_status_summary`, `verification_report`, `check_result`.
  - Outputs: `graph_patch_proposal`, `planning_summary`.
  - Graph tools: `create_work_region`, `attach_verifier`, `attach_check`,
    `create_gap_planner`, `create_join`, `request_gate`, `retire_or_supersede`,
    `submit_graph_patch`.
  - Forbidden effects: direct file writes unless explicitly leased as a worker
    role.
  - Completion: accepted graph mutation plus plain submit, or accepted no-op
    when no safe mutation is required.

- [ ] `gap_planner`
  - Purpose: turn failed verification/check evidence into corrective work.
  - Handler: agent.
  - Required inputs: `verification_report` or `check_result`.
  - Optional inputs: `candidate`, `file_state`, `requirement_record`,
    `graph_status_summary`.
  - Outputs: `gap_plan`, `gap_classification`, `classified_gap`,
    `graph_patch_proposal`.
  - Graph tools: `create_corrective_region`, `attach_verifier`,
    `attach_check`, `request_gate`, `submit_graph_patch`.
  - Forbidden effects: direct file writes, creating unrelated planner
    successors, retiring active executable nodes.
  - Completion: accepted corrective graph mutation plus submit, or accepted
    no-op only when every required gap successor is already satisfied.

### 2.3 Agent Work Nodes

- [ ] `worker`
  - Purpose: perform effectful repository work.
  - Handler: agent.
  - Roles: `discovery`, `implementer`, `fixer`, `reviewer`, `summarizer`.
  - Required inputs: role-specific work packet, usually `routine_snapshot` or
    `classified_gap`.
  - Optional inputs: `requirement_record`, `candidate`, `verification_report`,
    `check_result`, `analysis_summary`, `artifact_reference`.
  - Outputs: `candidate`, `file_state`, optional `analysis_summary`.
  - Tools: filesystem and code tools granted by lease; no graph mutation tools
    unless the node also has planning authority.
  - Completion: required output records accepted and file-state boundary
    accepted or explicitly clean.

- [ ] `verifier`
  - Purpose: evaluate a candidate against typed requirements and evidence.
  - Handler: agent or deterministic checker depending on verifier contract.
  - Required inputs: `candidate`.
  - Optional inputs: `requirement_record`, `file_state`, `check_result`,
    `artifact_reference`.
  - Outputs: `verification_report`.
  - Completion: report includes explicit verdict, per-requirement grades,
    evidence references, and missing-work classification.
  - Invalid completion: no grades, missing verdict, unbound candidate, or grades
    that do not match the declared rubric.

- [ ] `summarizer`
  - Purpose: compress accepted records for bounded prompts without becoming an
    authority on correctness.
  - Handler: agent or controller.
  - Required inputs: one or more accepted records.
  - Outputs: `analysis_summary`.
  - Completion: summary references source record IDs and declares whether it is
    lossy.
  - Notes: summaries are prompt aids only; schedulers and validators must use
    source records for authority.

### 2.4 Deterministic Execution Nodes

- [ ] `check`
  - Purpose: run a deterministic command, script, or built-in predicate.
  - Handler: controller runtime, not an LLM prompt.
  - Required inputs: `candidate` or `verification_report`, plus
    `command_definition` or `command_binding`.
  - Optional inputs: `file_state`, `requirement_record`.
  - Outputs: `check_result`.
  - Completion: command executed in the correct run worktree/snapshot with
    stdout, stderr, exit code, duration, command identity, and environment
    policy recorded.
  - Invalid completion: fabricated pass, missing command identity, missing exit
    code, or command run outside the leased run workspace.

- [ ] `join`
  - Purpose: wait for multiple required branches and emit a deterministic
    aggregate readiness/output record.
  - Handler: controller.
  - Required inputs: declared set of records with cardinality rules.
  - Outputs: `join_result`.
  - Completion: all required inputs satisfied, optional inputs handled according
    to declared policy.
  - Notes: use this instead of relying on implicit prompt-side aggregation.

- [ ] `final_gate`
  - Purpose: deterministic completion gate for a run or major region.
  - Handler: controller.
  - Required inputs: accepted region states, required checks, required
    verification reports, unresolved blockers.
  - Outputs: `completion_decision`.
  - Completion: either `passed` with no blockers or `blocked` with a typed
    blocker list.
  - Notes: not a human gate; it is the runtime invariant checker.

### 2.5 Decision and Recovery Nodes

- [ ] `human_gate`
  - Purpose: request explicit user approval, authority, or decision.
  - Handler: human/controller.
  - Required inputs: `decision_request`.
  - Outputs: `decision_record`.
  - Completion: accepted approve/reject/defer decision with actor and timestamp.

- [ ] `authority_request`
  - Purpose: request expanded graph, file, tool, model, budget, or command
    authority.
  - Handler: human/controller.
  - Required inputs: `authority_request_record`.
  - Outputs: `authority_decision`.
  - Completion: explicit grant/deny with scope and expiry.

- [ ] `recovery`
  - Purpose: controller-created node for retry, resume, cleanup, or manual
    intervention when a node cannot safely continue.
  - Handler: controller, human, or agent depending on recovery kind.
  - Required inputs: `failure_record`.
  - Outputs: `recovery_plan`, optional `graph_patch_proposal`.
  - Completion: retry/supersede/cancel decision recorded.
  - Notes: do not hide recovery as same-node retry when it affects graph
    semantics.

## 3. Record Types

Every output traveling over an edge must be an immutable typed record. Records
are addressed by ID and can be rendered into prompts, inspected in APIs, and
validated by schema.

Base fields for every record:

- [ ] `record_id`
- [ ] `record_type`
- [ ] `schema_version`
- [ ] `producer_node_id`
- [ ] `producer_port`
- [ ] `created_at`
- [ ] `graph_position`
- [ ] `run_id`
- [ ] `payload`
- [ ] `provenance`

Required record types:

- [ ] `routine_snapshot`
  - Feature spec, routine inputs, hidden binding IDs, acceptance command
    bindings, model/profile policy.

- [ ] `requirement_record`
  - Requirement ID, text, priority, acceptance criteria, source, version,
    supersedes.

- [ ] `graph_patch_proposal`
  - Proposed operations or macro invocations, base graph position, actor,
    rationale, expected downstream effects.

- [ ] `graph_patch_result`
  - Accepted/rejected status, validation diagnostics, created IDs, blocker
    reasons, graph position.

- [ ] `candidate`
  - Candidate ID, summary, changed file references, patch/diff references,
    affected requirements, claimed behavior, file-state record ID.

- [ ] `file_state`
  - Base commit/snapshot, changed tracked files, untracked files, ignored files,
    external artifacts, residue classification, clean/rejected verdict.

- [ ] `verification_report`
  - Candidate ID, verdict, per-requirement grades, evidence references,
    missing-work categories, recommended next action.

- [ ] `check_result`
  - Command ID, command binding, command text or opaque command reference,
    worktree snapshot, stdout reference, stderr reference, exit code, duration,
    status, classification.

- [ ] `gap_plan`
  - Failure summary, target requirement IDs, corrective objective, constraints.

- [ ] `gap_classification`
  - Failure class, source evidence, whether graph mutation is required, whether
    human decision is required.

- [ ] `classified_gap`
  - Machine-consumable corrective input for fixer nodes.

- [ ] `analysis_summary`
  - Summary text, source record IDs, lossy/lossless flag, omitted details.

- [ ] `join_result`
  - Joined source records, missing optional inputs, aggregate status.

- [ ] `decision_request`
  - Decision type, options, default, consequence summary.

- [ ] `decision_record`
  - Decision, actor, time, scope, rationale.

- [ ] `authority_request_record`
  - Requested authority, target node/region, reason, expiry.

- [ ] `authority_decision`
  - Granted/denied authority, allowed actions, resources, expiry.

- [ ] `failure_record`
  - Failed node, phase, error class, retryable flag, lease/execution metadata.

- [ ] `recovery_plan`
  - Retry/supersede/cancel/cleanup plan, responsible actor, new graph changes.

- [ ] `completion_decision`
  - Passed/blocked status and full blocker set.

## 4. Node Contract Schema

Each node type must be registered with a contract. The contract is the source of
truth for validation, scheduling, prompt rendering, and tool exposure.

Checklist:

- [ ] Define `node_type`.
- [ ] Define `contract_version`.
- [ ] Define `handler_type`: `controller`, `agent`, `human`, or
  `deterministic_command`.
- [ ] Define legal `roles` if the node type supports roles.
- [ ] Define input ports:
  - name;
  - record type;
  - schema version;
  - required/optional;
  - cardinality: `one`, `many`, `latest`, `all`;
  - freshness policy;
  - accepted upstream node types;
  - prompt hydration policy.
- [ ] Define output ports:
  - name;
  - record type;
  - schema version;
  - required/optional for successful completion;
  - cardinality;
  - terminal-state effect.
- [ ] Define preconditions:
  - required command binding;
  - required worktree snapshot;
  - required authority;
  - required model profile;
  - required external credentials.
- [ ] Define allowed tools:
  - graph tools;
  - file/code tools;
  - network tools;
  - command tools;
  - human-decision tools.
- [ ] Define resource claims:
  - graph write;
  - worktree write;
  - file/path scopes;
  - model/session scopes;
  - command scopes.
- [ ] Define lifecycle:
  - initial state;
  - schedulable states;
  - terminal states;
  - retryable failures;
  - max attempts;
  - timeout and heartbeat policy.
- [ ] Define completion validator.
- [ ] Define prompt template or deterministic handler.
- [ ] Define API/readback shape.

No node may be created if its type is not registered or if its payload violates
the registered contract.

## 5. Edge Contract Schema

Edges are typed input bindings. They do not merely connect port names; they
declare what records may flow, how they are selected, and how downstream nodes
consume them.

Checklist:

- [ ] Validate source node exists.
- [ ] Validate source output port exists in the source contract.
- [ ] Validate target node exists.
- [ ] Validate target input port exists in the target contract.
- [ ] Validate record type compatibility.
- [ ] Validate schema version compatibility.
- [ ] Validate cardinality compatibility.
- [ ] Validate required/optional behavior.
- [ ] Define selection:
  - source node ID or source node type;
  - source port;
  - accepted record type;
  - optional predicate over typed payload fields;
  - freshness/revision policy.
- [ ] Define binding policy:
  - bind first;
  - bind latest;
  - bind all;
  - rebind on superseding record;
  - never rebind after first accepted record.
- [ ] Define prompt hydration policy:
  - inline concise summary;
  - structured JSON;
  - artifact reference only;
  - excluded from prompt, available through tool.
- [ ] Preserve edge metadata in projection/readback.
- [ ] Store bound record IDs and binding graph positions.
- [ ] Support explainable missing-input blockers.

Edges must be rejected if endpoints, ports, record schemas, or cardinality do
not match contracts.

## 6. Graph Mutation Tools

Raw low-level patch operations may remain as an internal representation, but
planner-facing tools should be higher-level and contract checked.

Required planner/gap-planner tools:

- [ ] `create_work_region`
  - Creates a worker, verifier, optional checks, and required edges with one
    valid shared task region.

- [ ] `create_corrective_region`
  - Creates fixer, corrective verifier, optional corrective checks, and required
    edges from `classified_gap`.

- [ ] `attach_verifier`
  - Adds a verifier to an existing candidate-producing region.

- [ ] `attach_check`
  - Adds deterministic check node with command definition or opaque command
    binding.

- [ ] `create_gap_planner`
  - Adds gap planner bound to verification/check evidence.

- [ ] `create_join`
  - Adds controller join over declared records.

- [ ] `request_gate`
  - Creates a human decision or authority request.

- [ ] `retire_or_supersede`
  - Retires inactive nodes/edges or supersedes them with replacement topology.

- [ ] `submit_graph_patch`
  - Submits validated low-level patch expansion for acceptance.

Mutation validation must enforce:

- [ ] actor authority derived from the active lease and node contract, not from
  trusted payload strings;
- [ ] base graph position freshness;
- [ ] unique IDs;
- [ ] endpoint existence;
- [ ] port existence;
- [ ] node contract validity;
- [ ] edge contract validity;
- [ ] no forbidden cycles;
- [ ] task-region completion safety;
- [ ] resource claim safety;
- [ ] no active executable node retirement;
- [ ] no hidden command disclosure;
- [ ] deterministic rejection diagnostics.

## 7. Prompt and Execution Packets

Every executable node receives an execution packet derived from its contract and
bound records.

Checklist:

- [ ] Planner packet includes current graph status, allowed tools, typed bound
  inputs, rejected patch diagnostics, and available graph macros.
- [ ] Worker packet includes objective, bound requirement records, typed gap or
  routine inputs, relevant artifacts, and file-state constraints.
- [ ] Verifier packet includes candidate payload, requirements, relevant
  check/file-state records, rubric, and required report schema.
- [ ] Gap-planner packet includes failed verification/check evidence, candidate
  and file-state references, corrective graph authority, and no-op conditions.
- [ ] Summarizer packet includes source records and required summary schema.
- [ ] Human-gate packet includes options, consequences, default, and expiry.
- [ ] Check nodes do not receive LLM prompts; they receive deterministic command
  execution descriptors.
- [ ] Prompt packets are bounded by policy and preserve references to omitted
  records.
- [ ] All prompt-visible records are hydrated according to edge hydration policy.
- [ ] The runtime rejects completion if required output records do not conform
  to the node output contract.

## 8. Scheduler Requirements

The scheduler must be deterministic, explainable, fair, and progress safe.

### 8.1 Readiness

A node is ready only when:

- [ ] run lifecycle allows scheduling;
- [ ] node state is schedulable;
- [ ] node has no active lease;
- [ ] all required input ports are satisfied according to edge cardinality;
- [ ] required gate/authority decisions are accepted;
- [ ] required deterministic command bindings are resolved;
- [ ] resource claims do not conflict with active leases;
- [ ] max attempts and retry policy allow execution;
- [ ] node contract preconditions are satisfied.

If any condition fails, the scheduler records or exposes the exact blocker.

### 8.2 Ordering and Fairness

- [ ] Ready nodes are sorted deterministically.
- [ ] Priority ties use stable graph position and node ID.
- [ ] Controller-only deterministic nodes may run before agent nodes when they
  unblock downstream work.
- [ ] A ready node cannot be skipped forever unless a higher-priority ready node
  is continuously making accepted progress.
- [ ] Scheduler decisions are reproducible from event log plus configuration.

### 8.3 Lease and Execution State

- [ ] Every scheduled executable node gets a durable lease.
- [ ] Every dispatched execution gets durable execution metadata.
- [ ] Heartbeats renew only valid active leases.
- [ ] Lease expiry produces typed failure/retry events.
- [ ] Agent process death produces typed failure/retry events.
- [ ] Outbox dispatch is idempotent and completion-aware.
- [ ] Retry limits and backoff are explicit.
- [ ] Cancellation revokes leases and records terminal state.

### 8.4 Progress and Non-Locking Guarantees

The graph must never silently stop while work is possible.

Checklist:

- [ ] Graph validation rejects cycles unless a node contract explicitly declares
  bounded iterative behavior.
- [ ] Every non-terminal node is in exactly one of:
  - ready;
  - leased/running;
  - waiting on typed inputs;
  - waiting on gate/authority;
  - retry delayed;
  - blocked by failed upstream;
  - blocked by invalid graph;
  - terminal.
- [ ] Quiescence returns either `completed` or a typed blocker set.
- [ ] A blocker set includes all nodes/regions preventing progress.
- [ ] No task region can be created that can never become accepted.
- [ ] Final completion cannot depend on prompt-only conventions.
- [ ] Every active lease has timeout/recovery behavior.
- [ ] Every retryable failure has max-attempt termination.
- [ ] Every required input has a producer path or an explicit impossible-input
  blocker.
- [ ] Scheduler property tests cover random graph shapes within contract limits.

## 9. Region and Completion Semantics

Task regions are completion groups, not prompt labels.

Checklist:

- [ ] A region that contributes to run completion must have at least one
  candidate-producing worker or an explicit controller contract that marks it
  non-task/control-only.
- [ ] Worker and verifier for a candidate share the same task region.
- [ ] Corrective worker, corrective verifier, and corrective checks share one
  corrective region unless a contract declares otherwise.
- [ ] Planner/gap-planner nodes do not create standalone pending task regions
  unless they also create a candidate path for that region.
- [ ] Check-only regions are invalid unless modeled as `final_gate` or
  controller-only control regions.
- [ ] A task region is accepted only after:
  - candidate record accepted;
  - file-state accepted or explicitly clean;
  - required verifier report passed;
  - required check results passed;
  - no unresolved gate/authority/blocker records apply.
- [ ] Completion produces a `completion_decision` record.
- [ ] Rejected completion includes every blocker required to resume progress.

## 10. File-State and Worktree Semantics

Coding work is effectful; the graph must make repository state explicit.

Checklist:

- [ ] Worker lease declares allowed file/path scopes.
- [ ] Worker completion captures tracked, untracked, ignored, and external
  artifacts.
- [ ] File-state classifier records accepted, rejected, residue, and cleanup
  decisions.
- [ ] Downstream nodes consume candidate/file-state records, not implicit dirty
  worktree state.
- [ ] Parallel write leases conflict unless their path/resource claims are
  proven disjoint.
- [ ] Deterministic checks run against the correct candidate snapshot.
- [ ] Verification reports cite candidate and file-state record IDs.
- [ ] Cleanup is explicit graph work, not hidden side effect.

## 11. Runner Support

Dynamic graph execution requires runners that expose the required graph tools
and callback contract.

Checklist:

- [ ] Supported runner list is explicit.
- [ ] Unsupported runners fail before run start with actionable diagnostics.
- [ ] `submit_graph_patch` is a real tool or MCP capability, not only parsed
  transcript text.
- [ ] Runner callback API includes submit, grade, patch, heartbeat, artifact,
  and failure callbacks.
- [ ] Runtime enforces tool exposure from node contract and authority.
- [ ] Agent cannot complete a node with missing required outputs.
- [ ] Agent cannot mutate graph unless active node contract grants that tool.
- [ ] Agent cannot write files unless active lease grants worktree authority.

## 12. API and Readback Requirements

The graph must be inspectable enough to debug and to prove scheduler progress.

Checklist:

- [ ] Read graph topology with typed node/edge contracts.
- [ ] Read node detail with bound records and blockers.
- [ ] Read scheduler-ready queue and reasons for deferred nodes.
- [ ] Read active leases and execution metadata.
- [ ] Read graph patch proposals and validation diagnostics.
- [ ] Read region completion states and blockers.
- [ ] Read edge data bindings and hydrated record summaries.
- [ ] Read final completion decision.
- [ ] Read APIs from disposable projections rebuildable from event log.

## 13. Implementation Milestones

### Milestone 1: Contract Registry

- [ ] Introduce node contract registry.
- [ ] Register canonical node types from this document.
- [ ] Validate create-node payloads against contracts.
- [ ] Validate output records against schemas.
- [ ] Reject unknown node types and unknown ports.
- [ ] Add unit tests for every node contract.

### Milestone 2: Typed Edge Data

- [ ] Add edge contract validation.
- [ ] Preserve edge purpose/metadata in projection.
- [ ] Store bound record IDs with binding position.
- [ ] Implement cardinality and rebinding policies.
- [ ] Hydrate bound records into execution packets.
- [ ] Add tests for selector/schema/cardinality behavior.

### Milestone 3: Graph Authoring Tools

- [ ] Add graph macros for work region, corrective region, verifier, check,
  gap planner, join, and gates.
- [ ] Keep low-level patch expansion internal.
- [ ] Validate task-region completion safety during mutation.
- [ ] Replace prompt examples that encourage raw fragile topology.
- [ ] Add deterministic tests proving macro-created graphs can complete.

### Milestone 4: Deterministic Check Nodes

- [ ] Implement check command executor.
- [ ] Resolve opaque command bindings at runtime.
- [ ] Capture stdout/stderr/exit code/duration.
- [ ] Store `check_result` records.
- [ ] Remove fabricated check pass behavior.
- [ ] Add tests for pass, fail, timeout, missing command, and hidden binding.

### Milestone 5: Scheduler Progress Safety

- [ ] Add durable execution metadata and heartbeat.
- [ ] Add typed blocker readback.
- [ ] Add retry/backoff/max-attempt policy.
- [ ] Add cycle/deadlock validation.
- [ ] Add property tests for quiescence: completed or explicit blockers only.
- [ ] Add fairness tests for ready queues.

### Milestone 6: Authority and Runner Enforcement

- [ ] Derive graph mutation authority from active lease/node contract.
- [ ] Derive tool exposure from node contract.
- [ ] Fail unsupported runners before execution.
- [ ] Remove transcript-sentinel graph mutation from supported dynamic runners
  unless wrapped as a real tool with equivalent validation.
- [ ] Add tests that planners cannot write files and workers cannot mutate graph.

### Milestone 7: End-to-End Proof

- [ ] Run a real dynamic feature scenario from planner-created topology.
- [ ] Prove typed worker -> verifier -> gap planner -> corrective worker ->
  verifier -> check -> final gate flow.
- [ ] Prove failed verifier/check evidence creates corrective graph work.
- [ ] Prove completion blocks until required typed records exist.
- [ ] Prove no silent quiescence: every stopped non-complete graph has blockers.
- [ ] Record costs and graph metrics separately from comparison-oracle results.

## 14. Definition of Done

The typed dynamic work graph is done when all of the following are true:

- [ ] All canonical node types are registered with typed contracts.
- [ ] Unknown node types, ports, schemas, and malformed records are rejected at
  mutation or callback boundaries.
- [ ] Edge bindings carry typed record references with cardinality, freshness,
  and provenance.
- [ ] Execution packets for every node type are generated from typed bound
  records.
- [ ] Planner/gap-planner graph changes use validated macros or validated patch
  expansions.
- [ ] Check nodes execute commands deterministically and cannot fabricate pass.
- [ ] Verifier completion requires explicit grades and verdict.
- [ ] Scheduler decisions are deterministic and explainable.
- [ ] Leases, retries, heartbeats, cancellations, and recovery are durable.
- [ ] A graph cannot quiesce silently while schedulable or recoverable work
  remains.
- [ ] Final completion is a deterministic invariant decision over typed records.
- [ ] A real dynamic feature run completes through planner-authored topology
  without relying on hand-scripted graph shape.
