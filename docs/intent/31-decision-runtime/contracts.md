# Decision-v1 contract decisions

This document fixes the architecture-owned choices identified during independent
review. It is normative for the Sol prompts. The names below are proposed new
contracts, not assertions that these APIs already exist. Use existing enum/model
owners for grades, commands and gap dispositions where they express these facts.

## Authoritative selection and plan

The routine snapshot contains `agent_interaction_contract: "decision-v1"`.
Omission selects legacy. Generated nodes resolve that snapshot through existing
authoritative provenance; an arbitrary copied node field cannot select a contract.
New staged payloads have an explicit format tag as defined below. Both the
snapshot and payload must agree. Unknown/partial combinations fail closed.

For decision-v1 reliable-plan discovery, the authoritative plan is exactly the
generated built-in schema `orchestrator.reliable-plan.decision-plan@1`, semantic
role `implementation_plan`. Discovery emits its content on `semantic_artifact`
through the existing semantic artifact assembler. The successor consumes the
exact accepted record under that schema and its bound passing plan-verification
record. It does not select the first declaration with a matching role.

The old YAML implementation-plan v1 remains valid for legacy/custom use. Its
string-valued checks are descriptive and are never parsed as commands. Custom
domain schemas remain routine-authored. They may be additional outputs; they
cannot silently substitute for the built-in executable plan in decision-v1.
An explicit conversion feature for arbitrary custom plans is outside this scope.
Reject a routine that claims the built-in ID with different content; never
overwrite a user declaration to make it compatible.

## Shared types and bounds

Use strict extra-field rejection for these built-in answers, with the existing
extensible command-definition boundary explicitly preserved below. A nonempty string
must contain non-whitespace text. Reuse the current artifact/callback size limits;
do not invent a second independent set of large-object limits. List cardinality
and total plan size must also respect the existing run capability/horizon budget.

- `RequirementAlias`: a runtime-supplied alias for a bound requirement, never a
  graph record ID. Assign `r1`, `r2`, ... in the exact bound input order, store
  the mapping in the protected request and keep it immutable for that request.
- `EvidenceAlias`: `e1`, `e2`, ... over the exact hydrated evidence records in
  stable record-identity order. An alias cannot refer outside that request.
- `BatchKey`: a model-authored unique local plan label matching the existing
  safe logical-key grammar. It expresses a semantic dependency within the plan,
  not a graph node/region ID. The runtime resolves it to canonical batch identity
  once the plan is accepted. Repeated or dangling keys and cycles are invalid.
- `CheckChoice`: reuse `ReliablePlanCheckDecision`'s field shape: nonempty `name`
  and exactly one of `command_binding` or `command_definition`. The only
  model-selectable binding in this version is `dynamic_feature_hidden_oracle`,
  and only when the frozen policy offers it for the phase. The runtime supplies
  final `dynamic_feature_acceptance` separately; it is not a plan-selectable
  binding. `command_definition` retains the existing extensible command syntax,
  alias normalization and authoritative validator; outer strictness does not
  silently narrow that nested contract. Code supplies command/check IDs and
  execution paths; commands remain subject to current authority. Generate both
  tool schema and validation from these same existing owners.
- `Blocker`: `{reason: nonempty string, needed_information: nonempty string[],
  evidence: EvidenceAlias[]}`. `evidence` may be empty when no relevant evidence
  exists. Code records blocked state and routes the existing clarification/human
  action path. A blocker neither passes the step nor grants a new execution.
- `PlanAmendment`: `{refinements: BatchRefinement[] = [], additional_batches:
  Batch[] = []}`, with at least one actual change. A `BatchRefinement` contains
  a supplied unfinished `batch: BatchKey`, optional nonempty `objective`, and
  optional subset `scope`; it may add `acceptance: string[] = []`,
  `checks: CheckChoice[] = []`, `review_points: string[] = []` and
  `depends_on: BatchKey[] = []`. Reject an empty refinement or repeated target.
  These lists contain additions only. Known obligations and graph facts are not
  repeated. This is a narrow semantic plan proposal, never arbitrary graph ops.

## Exact authored answer families

The Pydantic models implement these shapes and their discriminated branches.
Fields marked optional have the stated default. The enclosing tool arguments
remain `outputs` according to the existing `SubmissionContract` renderer.

| Family and output port | Authored fields |
|---|---|
| `DiscoveryBrief`, `decision` | `questions: nonempty string[]`, `rationale: nonempty string`, `focus: string[] = []`. Focus entries are proposed subsets of the supplied scope. Known requirements, commands and scope authority are bound by runtime. |
| `ImplementationPlan`, `semantic_artifact` | `summary: nonempty string`, `batches: Batch[]` (nonempty). |
| `Batch` within the plan | `key: BatchKey`, `objective: nonempty string`, `scope: nonempty string[]`, `requirements: RequirementAlias[]` (nonempty), `depends_on: BatchKey[] = []`, `acceptance: nonempty string[]`, `checks: CheckChoice[]` (nonempty), `review_points: string[] = []`. |
| `BatchDecision`, `decision` | Discriminator `disposition`. `proceed` requires `implementation_notes: string` (may be empty); `revise_plan` requires `reason: nonempty string`, `amendment: PlanAmendment`; `blocked` requires `blocker: Blocker`. No other branch fields. The current batch is already bound. |
| `CorrectionDecision`, `decision` | Discriminator `disposition`. `no_gap` requires `reason: nonempty string`, `evidence: EvidenceAlias[]` (nonempty); `corrective_work` requires `diagnosis: nonempty string`, `remedy: nonempty string`, `focus: nonempty string[]`, `evidence: EvidenceAlias[]` (nonempty); `plan_revision` requires `reason: nonempty string`, `amendment: PlanAmendment`; `escalate` requires `blocker: Blocker`. |
| `VerificationDecision`, `decision` | `findings: Finding[]` (nonempty). `Finding` is `{obligation: ObligationAlias, grade: ExistingGrade, reason: nonempty string, evidence: EvidenceAlias[]}`. There is no model-authored overall pass, candidate ID or command status. |
| `WorkResult`, `decision` | Discriminator `status`. `ready` requires `summary: nonempty string`; `blocked` requires `blocker: Blocker`. Required custom semantic outputs are sibling entries in `outputs`, derived from their declared schemas. The actual code/artifact candidate comes from the owned checkout. |

Advisory appeal/oversight/recovery roles retain their existing authored semantic
schemas; use the same terminal-answer transport and runtime-owned record envelope.
No new advice union or independent registry is needed. An empty deterministic
question resolves in a controller operation only where the routine author
explicitly supplies that policy. Never ask a model to manufacture uncertainty.

These are separate role schemas, not one large union advertised to every model.
Only the current role's contract and applicable branches are exposed. The new
profile grants no mutation-tool authority through a decision payload.

## Check policy and amendments

Mandatory execution is the union of three explicit sources:

1. Frozen routine/project submission-gate policy for that phase, using its
   existing applicability rules.
2. The selected batch's typed `checks` in the accepted built-in plan. Those
   commands become obligations only after independent plan verification.
3. The frozen dynamic-feature `acceptance_command` at final acceptance, plus an
   optional hidden-oracle binding only where the existing policy declares it
   applicable. Do not run final acceptance against every incomplete batch.

Resolve configured bindings from the frozen run policy. A plan may select
available bindings or propose validated explicit commands. It cannot shadow an
existing binding or override the mandatory policy. Plan admission requires at
least one executable check per batch; a descriptive string does not satisfy it.
The old smoke fixture must be adapted to emit a new typed plan rather than
pretend that its old plan record qualifies. No new live qualification is issued
by this preparation.

For plan revision, the model proposes only changed judgments and added work in
`amendment`. Runtime constructs the full prospective plan from the exact accepted
plan and that proposal. It preserves the accepted prefix, all existing batch
keys and requirements, acceptance obligations and check choices. Refinements
target only unfinished batches. Additional batches and checks must fit the
existing budget and authority. A retained batch's scope cannot expand beyond
its previously authorized scope. Dependency additions must remain acyclic and
refer to accepted or proposed keys. Current frozen aliases identify requirements
for new batches; the runtime resolves them before validation. Existing unchanged
batches, requirements and commands never need to be copied into the answer.

This deliberately conservative first version permits refinement and added work,
but cannot delete obligations or widen authority by calling it an amendment.
Such a request becomes a blocker/human decision. The full prospective plan then
undergoes independent plan verification through existing supersession mechanics.
No replacement becomes executable until it passes. Keep the existing bounded
reliable-plan capability; this project does not expand arbitrary graph planning
or its horizon budget.

Corrective work is limited to the bound failed batch's scope and obligations,
using the exact rejected candidate/evidence and last accepted baseline. Runtime
builds the corrective worker, checks and verifier. A `no_gap` answer is accepted
only when existing deterministic gap applicability rules also permit closure;
it cannot dismiss a failed mandatory check.

## Verifier obligations and outcome

Resolve a frozen ordered obligation table for the specific verification request:

1. One row per exact bound requirement, in bound input order.
2. One row per applicable acceptance entry from the accepted node/plan, in its
   declared order.
3. One row per applicable rubric/review point, in its declared order.

Each row stores `{alias, source_record_or_node_identity, source_field, index,
text, minimum_grade}`. Aliases are `o1`, `o2`, ... in that concatenated order.
Do not deduplicate equal text from different sources: their source obligations
are distinct. Freeze and hash this table with the request. A plan verifier's
table comes from its bound planning obligations; batch and audit tables come
from their own accepted contracts. Reject an empty table before model dispatch
unless the phase is explicitly a deterministic gate rather than a verifier.

The model returns exactly one finding per obligation alias. Missing, duplicate,
unknown or request-mismatched aliases reject the answer. Grade values use the
existing grade enum/order; minimum grades come from the existing bound gate
policy. Evidence aliases resolve only to the offered candidate/plan and check
evidence. Record the table and judgments in a versioned semantic artifact;
do not create one graph node or one fake Requirement record per rubric sentence.
Construct the existing canonical VerificationReport and link to that artifact.
Extend its canonical value with one optional artifact reference if needed,
keeping legacy serialized records valid. Preserve per-requirement grades by
mapping the requirement rows; the overall result additionally covers acceptance
and rubric rows. Public readback must expose the detailed artifact through the
existing authorized artifact path.

Runtime computes pass only if coverage is exact, every finding meets its bound
minimum, all mandatory applicable checks have passing exact-candidate receipts,
and final candidate/authority validation succeeds. Check outcomes are mechanical
facts, not extra gradeable rows. A model cannot downgrade a failed command to a
passing finding. Plan verification applies its own mandatory checks; batch/final
command policies do not leak into phases where they are inapplicable.

## Staged payload and identities

The new internal CAS callback payload has this logical shape:

```text
format: "decision-submission-v1"
request:
  decision_request_id
  execution_id
  routine_snapshot_record_id
  interaction_contract: "decision-v1"
  answer_schema_id
  answer_schema_version
  answer_schema_sha256
  compiler_contract_version: 1
  question_context_ref                 # protected CAS context
  question_context_sha256
  bound_inputs                        # exact port/record/version bindings
answer_attempt_id
answer:                               # exact validated authored outputs
answer_sha256                         # canonical authored outputs
```

The protected question context contains the exact question, aliases, obligations,
available choices and policy/source references. Existing attempt fields continue
to own lease, execution, snapshot, boundary and candidate facts. References in
the payload must agree with that authority; they do not create a second owner.
The outer CAS hash/size binds the whole payload as today. Verify hashes and
bindings on both staging and finalization. Legacy payloads use their existing
decoder only when the frozen interaction is legacy. No shape guessing.

`decision_request_id` derives deterministically from the durable dispatch event
and execution identity. One execution answers one bound request. It survives
redelivery; a separately authorized new execution receives a different request.

`answer_attempt_id` is trusted delivery metadata supplied by the adapter/runtime,
never a model argument. Scope it to execution, transport channel/session and
provider tool-call or MCP request identity. Persist the idempotency outcome even
when authoritative answer validation rejects. Same delivery identity is a
redelivery; a new identity counts as a new attempt even with identical content.
After reconnection, claim duplicate identity only if the transport/runtime can
prove the same call. Otherwise classify as a new attempt. Once accepted staging
exists, identical answer content may return its canonical acknowledgement;
different content conflicts and cannot replace the staged answer.

Carry this metadata in a small typed internal submission-invocation envelope
through the existing SubmitCallback, with legacy calls preserved at the adapter
boundary. The model-facing `submit` JSON Schema still contains only authored
`outputs`. Do not add a model-authored attempt ID, a second callback registry or
an RPC identity field to the decision schema. Persist outcomes using current
command/event/idempotency machinery, not a new job table.

Model execution count records actual runner starts against the durable dispatch
identity and is separate from submission/proposal counts. Local compilation,
transaction conflict retry and evidence replay never create a model execution.

## Terminal answer and failure accounting

There is one successful terminal submission per request. Rejected answers may
be corrected within the explicit allowance. After durable staging and an attempt
to send its acknowledgement, the runtime requests controlled
phase closure at the adapter's safe transport boundary. It prevents further
work tools, drains exact owned processes and returns a trusted completion cause
bound to that staged execution/payload. The model need not generate another
answer, end marker, empty submit, graph command or voluntary completion action.
Lost acknowledgement does not prevent controlled closure: durable staging is the
authority, and later redelivery returns its recorded acknowledgement.

Use the existing execution/witness lifecycle, with a minimal typed completion
cause such as `terminal_answer_completed` carried in ExecutionResult and its
durable witness. This is distinct from an ordinary provider return or generic
interrupt. Successful finalization requires the exact staged answer plus proven
controlled closure and an unchanged permitted final boundary. Natural provider
completion may be the adapter's closure mechanism; it cannot require additional
semantic work or a new model turn. A hanging provider hits the bounded deadline.

Timeout, provider failure or unexpected process loss recorded before controlled
closure is witnessed invalidates success and enters recovery. Cancellation
enacted through the existing signal consumer before finalization commits blocks
publication, even if a closure witness already exists. Revalidate active state
and cancellation authority in the serialized finalization transaction. If
finalization commits first, later cancellation does not undo accepted history.
Do not redefine signal acceptance as application or add another cancellation
store. A local success flag cannot override the authoritative transition.
An expected transport stop can qualify only when initiated for
the matching staged terminal answer and completed without an overriding failure.
Never convert a generic interrupt/cancel into success. Legacy behavior is
unchanged. No graph effects appear until witness plus atomic finalization.

The rejected-answer counter covers arguments that reach the orchestrator-owned
answer ingress, including its own normalization/semantic validation before
compilation. Provider-side or FastMCP schema validation may reject before that
ingress and expose no complete request. Do not promise durable counting or exact
replay of unreceived arguments. Record observable transport diagnostics; wall and
execution bounds still apply, and missing evidence blocks another paid execution.
Transport interception beyond this boundary is separate work.

For the explicit recovery allowance of two rejected answers and one execution:
the first rejected answer permits correction in the same execution; the second
exhausts the allowance, closes the phase and prevents a third authored attempt.
One execution forbids automatic redispatch. Same-delivery replay is free; a new
delivery of identical invalid content consumes another rejection. A validation
failure consumes rejection allowance. A stale binding or environment/process
failure does not become a semantic rejection; it closes/blocks that request
without granting another model execution. Preserve current executable-node
default safety limits independently. New and existing configurable decision
caps remain opt-in; this does not remove any existing default safety limit.
