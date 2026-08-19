# Reliable Plan Execution for Dynamic Graph Runs

## Status and purpose

This document defines the changes needed for dynamic graph runs to carry out
large, staged software-engineering work at least as reliably as the legacy
create-plan-then-execute workflow.

It is an incident-informed extension of
[`typed-work-graph-requirements.md`](typed-work-graph-requirements.md). The
typed graph requirements describe the general node and record system; this
document focuses on preserving plan semantics from discovery through staged
implementation, verification, correction, and completion.

The immediate evidence is run
`fff4f6b7-bf33-475f-8280-31ff5e1ef7ca`, which attempted closure-driven removal
of the live legacy workflow. The run was intentionally a test of dynamic graph
planning with Luna. It failed both as a software change and as a demonstration
of the graph execution model.

## Outcome sought

A dynamic graph run must not reduce a detailed engineering plan to generic
worker nodes connected only by readiness edges. It must preserve and enforce:

- what each stage is intended to establish;
- which accepted evidence a stage consumes;
- whether the stage is read-only or effectful;
- the typed outputs it must produce;
- which requirements and checks determine acceptance;
- which snapshot becomes authoritative after acceptance; and
- what specific evidence a corrective stage must address.

The target execution shape for staged work is:

```text
read-only discovery
    -> independent plan verification
    -> successor planning
    -> implementation batch
    -> deterministic checks
    -> independent batch verification
    -> accepted snapshot
    -> next successor planning horizon
    -> final independent audit
```

The graph may adapt this shape as evidence changes, but it may not omit the
semantic handoffs or collapse explicitly staged work into one unbounded worker.

## What the failed run demonstrated

### The graph preserved scheduling but lost the plan

The accepted graph created one discovery worker, one implementation worker, one
verifier, and a generic correction chain. The repository plan described six
ordered removal batches, but those batches were not represented as separate
task regions with separate acceptance boundaries.

The discovery worker and implementation worker were not connected by a typed
edge. Implementation could become ready without consuming a discovery result or
waiting for independent plan verification. Serialization happened only because
both nodes claimed the same repository write resource.

Resource conflict is not a planning dependency.

### Discovery was not actually analysis-only

The discovery node had write authority over the entire repository. Its role was
named `discovery`, but the runtime contract neither made the node read-only nor
required a discovery-specific output. It modified production files while also
creating planning artifacts.

A role label in a prompt is not an enforceable execution boundary.

### Worker packets were semantically incomplete

The structured worker packet contained a node ID, a task-region ID, and worker
authority. The runtime appended the full feature specification as a generic
instruction, but did not provide the worker with a narrow objective, the
verified stage plan, explicit requirement bindings, expected typed outputs, or
stage-specific acceptance commands.

This made the discovery worker, implementation worker, and corrective worker
different mainly in name. Each was invited to act on the whole mission.

### Edge bindings controlled readiness but not understanding

The corrective worker was made ready by a classified-gap record, but worker
prompt construction did not hydrate the substantive bound evidence into the
worker packet. The verifier's exact failures and the gap planner's reasoning
therefore did not become authoritative corrective instructions.

An input edge must transport useful typed content into execution, not merely
unlock a node.

### Generic candidate records lost useful authority

Discovery and implementation completed through generic candidate and file-state
records. The accepted candidate summary did not carry a closure calculation,
batch definition, test-disposition map, or other plan content that downstream
nodes could validate and consume.

The filesystem happened to contain documents, but the graph did not understand
those documents as typed, authoritative outputs.

### Graph validation was syntactic rather than semantic

Patch validation caught malformed operations, invalid ports, and cycles. It did
not reject a graph that:

- gave a discovery node write authority;
- omitted the discovery-to-plan-verifier handoff;
- made implementation independent of discovery;
- represented six required batches as one implementation node; or
- gave workers no bounded objective and stage acceptance contract.

### Failure recovery compounded the candidate

Verification correctly found hundreds of failures and missing closure evidence.
Corrective work then continued in the same accumulated dirty worktree. Repeated
missing callbacks retried the same corrective node several times before the run
paused with an active lease and no callback.

Failed work remained the implicit baseline for later work instead of being an
evidence-bearing rejected candidate separated from the last accepted snapshot.

## Required design changes

### 1. Make every worker node a complete work contract

Creating a worker node must require the planner to provide:

- `objective`: the single bounded outcome of the node;
- `work_mode`: `read_only` or `write`;
- `scope`: the modules, artifacts, or semantic subsystem in scope;
- `required_inputs`: typed ports and record schemas;
- `expected_outputs`: typed records and required payload fields;
- `bound_requirement_ids`: the requirements the node advances;
- `acceptance`: deterministic commands or verifier obligations;
- `invariants`: behavior that must remain true; and
- `prohibited_actions`: stage-specific exclusions.

The patch validator must reject generic executable nodes that omit these fields.
Defaults may be supplied by a high-level graph macro, but the resulting node
must still contain the resolved contract.

Discovery nodes must be read-only by default. A discovery node that genuinely
needs to create repository artifacts should use a separate, narrowly scoped
artifact-writing node after discovery evidence has been accepted.

### 2. Support schema-declared semantic artifacts

The graph needs to preserve the semantic products of planning without adding
workflow-specific record classes to the graph kernel. Closure calculations,
test dispositions, migration plans, UI designs, incident analyses, and other
engineering artifacts are domain content, not universal graph concepts.

The kernel should provide one general artifact envelope with fields such as:

- record and schema identity, including schema version;
- a semantic role declared by the routine or accepted plan;
- producer node and output port;
- inline structured content or a content-addressed artifact reference;
- provenance and source-record references;
- requirement and task-region associations;
- validation status; and
- authority or supersession status.

Routines and planners then declare the schemas required for their own work. A
legacy-removal run might declare artifacts for an inventory, a dependency
closure, test relevance, and an ordered batch plan. A different run can declare
API-design, benchmark, migration, or research artifacts without requiring new
kernel models.

The graph runtime is responsible only for general behavior:

- validating content against the declared schema;
- enforcing producer-port and consumer-port compatibility;
- preserving provenance and immutable schema identity;
- hydrating or referencing the artifact in downstream packets;
- ensuring that a verifier grades the artifact required by its consumer; and
- preventing a generic candidate or file-state record from satisfying an input
  that declares a different semantic schema.

Schema declarations must themselves be accepted, versioned graph inputs. They
may originate in a routine snapshot or in an authorized planner amendment. A
planner must not silently weaken a consumer's required schema merely to make an
edge bind.

Records should carry references to source artifacts where complete content is
too large for an event. The general envelope remains the authority that
declares what the artifact is, how it was produced, and which later nodes may
consume it; the graph kernel does not need to understand the artifact's domain.

### 3. Validate phase semantics when accepting graph patches

Graph validation must extend beyond valid nodes, ports, and acyclicity. For a
staged feature plan, it must reject graphs with any of the following:

- an effectful discovery node when the stage is declared analysis-only;
- an implementation node without the accepted, verified plan artifact declared
  by its input contract;
- a planning stage without an independent plan-verification successor;
- a plan-verification failure with a path to implementation;
- required phases from the bound feature contract that are not represented;
- multiple declared batches collapsed into one worker without an explicit,
  accepted plan amendment;
- a verifier that is not bound to the candidate and requirements it grades;
- a corrective worker that does not consume the detailed failed verification or
  check evidence; or
- a final gate that can pass without every required batch and audit record.

These validations should be implemented as typed graph invariants or high-level
macro validation, not as planner prompt advice.

### 4. Expand the graph one planning horizon at a time

The initial planner should normally create only:

1. the discovery region;
2. the plan-verification region; and
3. a successor planner that consumes the accepted plan.

After plan verification passes, the successor planner creates the first
implementation batch and its checks and verifier. After that batch is accepted,
another successor planner decides whether to create the next declared batch,
amend the plan based on evidence, or request a decision.

This progressive model has two benefits:

- later graph structure is based on accepted evidence rather than a speculative
  whole-run design; and
- a planner cannot satisfy graph-shape pressure by collapsing a long execution
  into one broad worker.

Planner generation and patch budgets must accommodate successor planning. A
planner should not be encouraged to encode the complete success path, every
possible correction, and final recovery behavior in one initial patch.

### 5. Hydrate bound records into worker execution packets

Worker prompt construction must include an explicit, bounded context packet
containing:

- the node's complete work contract;
- bound requirement records;
- required input records with their substantive typed payloads;
- relevant source-artifact references;
- the accepted snapshot on which work must be based;
- exact acceptance commands or command bindings; and
- for correction, the verifier grades, failed check output, missing evidence,
  and the accepted gap analysis.

Summaries may be used to control prompt size, but they must cite source record
IDs and must not replace authoritative content used by validation or scheduling.

The runtime prompt summary should expose which records were hydrated, summarized,
or omitted so operators can diagnose context loss without reconstructing the
prompt from logs.

### 6. Isolate candidates and advance only accepted snapshots

Every effectful stage should produce a candidate snapshot based on the most
recent accepted snapshot for its task region.

- Verification reads the candidate snapshot.
- Passing verification advances the region's accepted snapshot.
- Failed verification preserves the rejected candidate and evidence but does
  not make it the implicit base for unrelated or later planned work.
- Corrective work declares whether it is based on the rejected candidate or the
  last accepted snapshot. That choice is explicit in its work contract.
- The next implementation batch begins from the latest accepted batch snapshot.

This does not require discarding failed work. It requires distinguishing
evidence-bearing failed candidates from authoritative accepted state.

### 7. Make callback and lease recovery conclusive

When an execution disappears without a callback, the controller must:

1. record an infrastructure failure distinct from a verification failure;
2. revoke the lease conclusively;
3. verify runner health before retrying;
4. retry only according to a bounded recovery policy;
5. create a recovery node or pause when automatic recovery is exhausted; and
6. never leave a paused run reporting an active lease without a callback.

Rapidly recreating the same execution against the same repository state is not
recovery. The recovery decision must state which snapshot will be used and why
another attempt is expected to behave differently.

### 8. Separate model capability evaluation from graph-contract evaluation

Luna can be evaluated fairly only after the graph supplies bounded work
contracts. The recommended sequence is:

1. Run a deterministic graph skeleton with Luna assigned to narrow discovery,
   implementation, and correction workers.
2. Use an independently configured verifier and compare results with the same
   skeleton using a stronger worker model.
3. After bounded execution is reliable, allow Luna to create one successor
   horizon at a time.
4. Only then evaluate Luna as the initial whole-feature planner.

During product hardening, using a stronger model for planning and independent
verification is reasonable. The graph should ultimately make correctness depend
on contracts and evidence rather than on choosing a model capable of inferring
missing structure.

### 9. Expose plan semantics in operator read models

Operators need to see more than node state and lease state. Graph read models
and the UI should expose:

- each node's objective, work mode, and scope;
- bound requirements and input records;
- expected output records;
- deterministic checks and verifier obligations;
- the accepted and candidate snapshot identities;
- why a node is ready, deferred, rejected, or corrective;
- which planning horizon created it; and
- per-node token, action, duration, and prompt-hydration summaries.

This would have made the failed run's disconnected inventory and broad worker
contract visible before the implementation accumulated thousands of deletions.

## Why this proposal excludes hard diff gates

This proposal deliberately does not impose correctness gates based on a maximum
number of changed files, deleted lines, or test files per worker.

Software-engineering tasks vary too much for the orchestrator to estimate those
limits accurately in advance. Large mechanical changes may be correct and
coherent, while a one-line change may be unsafe. Requiring planners or workers
to conform to guessed size limits would encourage artificial task splitting,
repeated replanning, and churn without establishing correctness.

The replacement is semantic control:

- verified closed-subset or batch plans;
- explicit scopes and dependencies;
- explicit plan evidence describing why affected tests are kept, rewritten, or
  retired;
- deterministic checks after each accepted batch;
- independent verification against bound requirements;
- progressive planning based on accepted evidence; and
- candidate isolation with explicit snapshot authority.

Operational time, token, and retry limits may still protect infrastructure and
cost. They should be treated as execution-health policy, not as estimates of how
large a correct software change ought to be.

## Implementation sequence

### Slice 1: worker contracts and prompt hydration

- Add the required worker-contract fields to typed node payloads.
- Reject executable nodes without resolved objectives, inputs, outputs, scope,
  work mode, requirements, and acceptance obligations.
- Hydrate bound typed records into worker packets.
- Add prompt-summary evidence for hydrated, summarized, and omitted records.

### Slice 2: schema-declared discovery and planning handoff

- Add the general semantic-artifact envelope and run-scoped schema declarations.
- Add a read-only discovery macro whose output schema is supplied by the routine
  or planner rather than fixed in the kernel.
- Add a plan-verification macro and invariant that operate on declared artifact
  schemas and bound requirements.
- Prevent implementation readiness until the required plan artifact has an
  accepted verification report bound to it.

### Slice 3: progressive batch horizons

- Add a successor-planner macro that consumes an accepted plan or batch report.
- Represent each declared batch as a separate task region.
- Attach deterministic checks and a verifier to every effectful batch.
- Make final-gate readiness depend on all declared batch records.

### Slice 4: candidate snapshot authority

- Track accepted versus candidate snapshots per task region.
- Make worker base-snapshot selection explicit.
- Prevent failed candidates from silently becoming the base of later regions.
- Preserve failed candidates as inspectable evidence.

### Slice 5: recovery semantics

- Separate infrastructure failure, verification failure, and invalid-plan
  failure records.
- Make lease revocation and paused-run state consistent.
- Require health evidence or a changed recovery action before retrying a missing
  callback.

### Slice 6: dogfood and evaluation

- Convert the failed run into a durable regression scenario.
- Run the deterministic skeleton with Luna workers.
- Run the same graph with alternate worker and verifier models.
- Enable one-horizon Luna planning only after deterministic execution passes.
- Compare correctness, revisions, graph shape, token use, and recovery behavior
  with the legacy plan-then-execute baseline.

## Required regression scenarios

Tests derived from the failed run should prove that:

1. an analysis-only discovery node cannot obtain repository write authority;
2. implementation cannot become ready without accepted discovery and plan
   verification records;
3. a staged feature contract cannot be represented by one generic worker unless
   an accepted plan amendment explicitly changes the stages;
4. worker prompts contain their bound requirement and evidence records;
5. corrective prompts contain the exact failed grades and check results;
6. a generic candidate or file-state record cannot substitute for an artifact
   required by a consumer's declared schema;
7. failed candidates do not become the implicit base for later batches;
8. final completion cannot occur with a missing batch verification or final
   audit;
9. a missing callback ends with either a healthy retry or a conclusively revoked
   lease and typed recovery state; and
10. the operator read model makes disconnected or semantically incomplete work
    regions visible.

## Acceptance criteria

The work described here is complete when:

- the graph rejects the structural defects exhibited by the failed run;
- a detailed staged plan is represented as typed records and progressive task
  regions rather than only text files in a shared worktree;
- every effectful worker consumes an accepted, verified stage contract;
- every verifier grades a bound candidate against bound requirements and check
  evidence;
- correction is driven by the substantive failure record;
- only accepted snapshots advance downstream authority;
- callback loss cannot leave a paused run with an active ghost lease;
- operators can inspect the semantic contract and evidence for every node; and
- a Luna worker run on the deterministic graph completes the reference scenario
  without relying on unstated plan inference.

## Non-goals

- Estimating correct change size from file counts, deleted lines, or test counts.
- Treating a model's ability to infer omitted context as a graph capability.
- Replacing deterministic checks with verifier judgment.
- Requiring the initial planner to predict the entire correction and recovery
  graph before any evidence exists.
- Deleting failed-run evidence; failed candidates and graph events are valuable
  product regression fixtures.
