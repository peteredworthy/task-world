# Grounded UI/UX Foundation, Phases 0-3

## Objective

Establish an implementation-grounded semantic foundation for Task World's UI
and UX before producing view contracts, interaction architectures, or polished
screens. This work package covers orientation, repository reality, capability
truth, and the first human review checkpoint. It ends after Phase 3.

The package must prevent downstream interfaces from inventing entities, fields,
relationships, actions, states, causal claims, or capabilities. It must also
keep current, derived, proposed, gap, and unknown capabilities distinct.

## Scope

### Included

1. Phase 0 project orientation and coordination artifacts.
2. Phase 1 implementation-reality investigations.
3. Phase 2 field-level capability and derivation classification.
4. Independent semantic falsification.
5. A concise static HTML review of the highest-impact Phase 3 decisions.
6. Human-feedback capture and export.

### Excluded

1. Rewriting the existing jobs or journeys.
2. Scenario matrices and executable fixtures.
3. View contracts and semantic admission for interface concepts.
4. Interaction-architecture exploration.
5. Component-bound prototypes or polished screens.
6. Product UI or backend implementation changes.

Those activities require later work packages informed by the Phase 3 decisions.

## Source Authority

Resolve disagreements using this order:

1. Executable schemas, types, commands, APIs, event definitions, and invariant
   checks.
2. Tests demonstrating behavior.
3. Current implementation.
4. Explicit architecture and protocol documentation.
5. Current product documentation.
6. Jobs and journey documents.
7. Design hypotheses.
8. Model inference.

The hierarchy compares sources capable of establishing the same proposition; a
higher-ranked source is not used to answer a claim it cannot establish. A schema
or type proves an accepted shape, not reachability. Command wiring and current
implementation prove availability; tests prove exercised behavior; persisted
records prove observed operation. A capability is `current` only when the
relevant evidence kinds agree. Declared but unwired types, endpoints, commands,
or events remain documented implementation material rather than current product
capabilities. Disagreement among relevant evidence creates an explicit conflict;
the hierarchy then decides which qualifying evidence controls.

The existing source documents remain unchanged:

- `docs/jtbd/jobs.md`
- `docs/jtbd/journeys.md`
- `docs/jtbd/decision-information.md`
- `docs/jtbd/information-architecture.md`
- `docs/jtbd/evaluation-rubric.md`

Their user intent, narratives, decision policy, hypotheses, and evaluation
criteria are inputs. They do not prove that implementation capabilities exist.
The new package assesses their claims without silently modifying their meaning.

Phase 0 records an audit snapshot in the canonical evidence catalog. The
snapshot includes audit time, repository revision metadata when safely
available, and SHA-256 content hashes for every cited source file. Content hashes
are authoritative for drift detection, including dirty or concurrently changing
worktrees. Before Phase 3 generation, changed hashes invalidate affected claims
until their evidence is rechecked.

## Repository Conventions

The foundation lives at `research/ui-foundation/`. This follows the existing
`research/` convention for durable, evidence-tagged system understanding while
keeping the new semantic contracts isolated from older commit-anchored research.

The validated design and implementation plan live under
`docs/superpowers/specs/` and `docs/superpowers/plans/`, respectively.

Review artifacts follow the repository's strongest standalone prototype
convention: static, offline HTML with inline or local CSS and minimal JavaScript,
directly usable through `file://`, with no build step or network dependency.

## Work Package Architecture

### Phase Boundaries

| Phase | Inputs | Outputs | Gate |
|---|---|---|---|
| 0: Orient and plan | This design, repository conventions, five JTBD documents | Coordination files, audit snapshot, closed scope manifest, ID policy, review index shell | Every investigation has a bounded owner and source scope |
| 1: Establish reality | Phase 0 scope and current source snapshot | Seven evidence reports, normalized evidence, entities, relationships, states, actions, permissions, invariants, conflicts | Required audit scopes are complete or explicitly blocked; evidence drift is resolved |
| 2: Build capability truth | Accepted Phase 1 evidence and source-document demands | Capability registry and complete admitted derivation contracts | Every in-scope demand has exactly one capability classification |
| 3: Review reality and capability | Checked Phase 1-2 contracts and verifier findings | One or more concise HTML review batches, feedback export, canonical decisions | Outcome is recorded as `complete-ready` or `complete-blocked` |

Phase 2 may begin for settled claims while independent Phase 1 investigations
continue, but it cannot classify a claim whose required reality evidence is
missing, stale, or disputed. Such a claim remains `unknown` and is blocked from
downstream use.

### Reality Investigations

Seven bounded investigations run in parallel where their source scopes do not
overlap materially:

| Investigation | Primary scope | Required findings |
|---|---|---|
| Domain and persistence | ORM models, Pydantic schemas, repositories, stored identities | Entities, aliases, identity boundaries, cardinality, ownership, persistence |
| Graph kernel and runtime | Graph models, records, events, commands, validator, scheduler, leases | Topology, dependency direction, dynamic expansion, legal commands, invariants |
| Workflow and state | Run/task/attempt state, signals, reducers, executor transitions | Lifecycle states, legal transitions, race behavior, resulting evidence |
| API, actions, and authority | REST/MCP/CLI boundaries, request validation, action surfaces | Command contracts, actor assumptions, preconditions, failures, stale handling |
| Evidence and telemetry | Events, prompt packets, traces, artifacts, usage, costs | Evidence identity, attribution, freshness, coverage, missing and stale states |
| UI projections | API clients, query types, routes, selection, rendered fields/actions | What the current UI consumes, projection gaps, implicit semantic assumptions |
| Tests and documentation | Unit/integration tests, intent and architecture documents | Tested behavior, documented-only claims, stale conflicts, decisive invariants |

Each investigation writes a full report under
`research/ui-foundation/agent-reports/` and returns a concise handoff containing:

```text
Purpose
Scope inspected
Key findings
Important uncertainties
Conflicts found
Decisions required
Artifact paths
Evidence pointers
Recommended next delegation
```

Reports distinguish `implemented`, `tested`, `documented-only`, `inferred`, and
`unclear`. Findings cite source paths and symbols; line numbers may be included
as navigation aids but are not stable identities.

### Synthesis

Separate synthesis responsibilities consume the bounded reports:

1. Domain synthesis builds the entity and typed relationship model.
2. Capability and derivation synthesis classifies claims demanded by the source
   jobs, journeys, and decision-information contract.
3. Action and state synthesis builds action contracts, permissions, and legal
   transitions.

The same agent must not author and independently verify the merged semantic
model. An independent semantic verifier attempts to falsify the synthesis.

### Orchestrator Responsibilities

The main orchestrator preserves context for:

- stable ID allocation;
- project status and artifact indexing;
- open-question and conflict registration;
- claim normalization across agent reports;
- targeted adjudication when reports disagree;
- dependency and blocking decisions;
- selection of the small Phase 3 review set;
- communication with the human reviewer.

The orchestrator does not silently merge incompatible claims into generalized
prose. A disagreement becomes a conflict item and is settled by decisive source
inspection, targeted adjudication, or human review.

## Artifact Model

Only artifacts needed for Phases 0-3 are created in this work package.
Downstream directories are added when their work packages begin.

```text
research/ui-foundation/
  index.md
  status.md
  source-map.md
  decision-log.md
  open-questions.md

  catalog/
    scope.yaml
    ids.yaml
    claims.yaml
    invariants.yaml
    conflicts.yaml
    questions.yaml
    decisions.yaml
    evidence.yaml

  reality/
    domain-model.yaml
    relationships.yaml
    state-model.yaml
    permissions.yaml
    actions/
    evidence/

  capabilities/
    registry.yaml
    derivations/
    gaps.md

  reviews/
    index.html
    phase-3-reality-capability-01.html
    phase-3-reality-capability-NN.html
    feedback/

  schemas/
    semantic-item.schema.json
    review-feedback.schema.json

  tools/
    validate.py
    import_feedback.py

  agent-reports/
```

`catalog/scope.yaml` is the closed Phase 0 inventory of source-document demands,
claims, and actions to audit. `catalog/ids.yaml` is the allocation registry.
Claims, invariants, conflicts, questions, decisions, and evidence each have the
corresponding canonical catalog file. Detailed domain, relationship, state,
permission, action, derivation, and evidence contracts remain canonical in their
typed files under `reality/` and `capabilities/` and are referenced from the
catalog rather than duplicated.

`index.md`, `status.md`, `source-map.md`, `decision-log.md`,
`open-questions.md`, agent handoffs, and HTML are projections. They summarize or
link to canonical IDs and do not create competing semantic definitions.

Scope is finite: every audited claim or action maps to a specific information or
action demand in the five source documents. New demands require a recorded scope
decision. Unrelated future-product analysis remains out of scope.

## Stable IDs

Use durable, readable IDs with monotonically allocated numeric suffixes:

```text
ENT-04  entity
REL-07  relationship
CAP-12  capability
DRV-03  derivation
ACT-05  action
INV-02  invariant
Q-09    open question
DEC-05  human decision
CON-02  source conflict
```

IDs are never reused or renumbered because display order changes. Deleted or
rejected items remain recorded with their terminal status.

Parallel investigations use scoped provisional keys in their reports. Canonical
IDs are allocated only during normalization and recorded atomically in
`catalog/ids.yaml`; agents do not independently mint canonical IDs.

## Semantic Item Contract

Every important semantic item records orthogonal evidence dimensions:

- stable ID and title;
- concise definition;
- implementation status: `present`, `absent`, `partial`, or `unknown`;
- test status: `exercised`, `unexercised`, `contradicted`, or `unknown`;
- documentation status: `documented`, `undocumented`, `stale`, `conflicting`, or
  `unknown`;
- capability status where applicable: `current`, `derived`, `proposed`, `gap`,
  or `unknown`;
- epistemic status where applicable: `observed`, `deterministically-derived`,
  `inferred`, `operator-asserted`, `proposed`, or `unknown`;
- confidence and its basis;
- evidence pointers with source kind, path, and symbol;
- conflicts and open questions;
- limitations and prohibited interpretations;
- timestamps or freshness semantics when the claim can become stale.

Capability status is the exclusive product classification. `Current` requires
reachable implementation evidence and no decisive contradiction. `Derived`
requires current inputs and a complete deterministic derivation contract.
`Proposed` is an intentionally designed future capability. `Gap` is demanded but
missing or insufficiently defined. `Unknown` means the audit cannot determine
reality. Epistemic status describes a claim's knowledge basis and does not
replace any implementation, test, or documentation field.

Slash-separated terms are not aliases. Region/step, node/task, and
record/event/requirement remain distinct until implementation evidence proves
an equivalence or defines a conversion.

## Domain And Relationship Contracts

The domain model identifies each entity's identity boundary, lifecycle,
ownership, persistence, public representations, and known aliases.

Every relationship records:

- source and target entity IDs;
- direction;
- relationship type;
- source and target cardinality;
- ownership or reference semantics;
- temporal behavior;
- dependency behavior;
- whether it is observed, derived, inferred, or proposed;
- evidence and counter-evidence;
- prohibited causal interpretations.

Temporal ordering is not causal evidence. A causal relationship requires an
explicit mechanism or evidence contract beyond sequence.

## Capability And Derivation Contracts

The capability registry evaluates each important claim demanded by the source
documents. Initial coverage includes health class, current constraint, blast
radius, final-gate effect, planner horizon, evidence convergence, retry
information delta, comparable cohort, prompt pressure, repeated work, budget
pace, and causal gap.

Every claim is classified as `current`, `derived`, `proposed`, `gap`, or
`unknown`. A derived claim is admitted only when its derivation contract defines:

- required inputs and their capability IDs;
- deterministic algorithm or decision rule;
- output type;
- unknown and failure conditions;
- freshness and recomputation behavior;
- supporting implementation evidence;
- known limitations;
- prohibited interpretations.

Availability of inputs alone does not make a claim derived. If the algorithm or
unknown behavior is not defined, the claim remains a gap or unknown.

## Action Contracts

Every implemented UI-relevant action binds to an implemented command. Its action
contract records:

- stable identifier;
- actor and permission requirements;
- preconditions and expected source version;
- required input;
- validation;
- durable effect;
- resulting state;
- failure modes;
- stale-state and race behavior;
- idempotency and retry behavior;
- reversibility;
- audit evidence.

Absent interventions demanded by the five source documents are mapped as gap or
proposed-action requirements, not completed command contracts. Each records the
required outcome, source demand, known implementation constraints, required
evidence, and unresolved command-design decisions. Detailed future permissions,
validation, effects, transitions, stale behavior, idempotency, reversibility, and
audit semantics require a separately approved capability-design work package.
Until that exists, no downstream target UI action may represent the intervention
as executable. No future action is introduced merely because comparable products
commonly offer it.

Authority is recorded in three separate fields: enforced authentication or
authorization, implemented domain eligibility and preconditions, and proposed
product-role policy. Missing enforcement is reported as absent; an assumed
operator role never becomes an implemented permission.

Retries, lifecycle signals, clarification answers, decision recording, raw graph
patches, requeue operations, and typed steering are distinct unless decisive
implementation evidence proves otherwise.

## Data Flow

The semantic data flow is one-way:

```text
Code, tests, and documentation
-> bounded evidence reports
-> normalized claim and conflict ledgers
-> typed reality, action, and capability contracts
-> deterministic consistency checks
-> independent semantic challenge
-> compact Phase 3 HTML checkpoint
-> exported human feedback
-> decision log
```

Human review may resolve terminology, user intent, risk tolerance, product-role
policy, and treatment of non-blocking unknowns. It cannot change observed facts
or classify a capability as `current` or `derived` without qualifying
implementation evidence. Evidence corrections and product decisions are stored
as distinct records. An accepted decision identifies affected canonical
contracts and regenerates only their projections.

## Unknown, Conflict, And Failure Handling

Unknown is a valid output:

- missing implementation evidence remains `unknown`;
- partial or stale inputs produce an unknown derivation result where defined;
- contradictory sources create a `CON-*` item preserving both claims;
- ambiguous lineage remains ambiguous rather than selecting a convenient parent;
- unpriced usage remains unpriced and is not treated as zero;
- unresolved causality remains ordered evidence without a causal label;
- unavailable repository areas remain visible scope gaps.

Agent failures are also explicit. A failed or incomplete investigation leaves
its scope unverified and blocks dependent synthesis. A replacement or targeted
investigation may resume the same bounded scope. Other independent audits may
continue.

Human deferral may record `proceed-with-explicit-assumption` only when the item
does not invalidate dependent semantic contracts. Blocking entity identity,
relationship, capability, authority, or state-transition disputes cannot be
silently deferred into interface work.

## Phase 3 Review Artifact

The first substantial human-facing artifact is
`research/ui-foundation/reviews/phase-3-reality-capability-01.html`. Additional
blocking batches increment the suffix. These files are not product mockups.

Each primary view contains no more than 12 high-leverage review items, grouped
across:

- disputed entity distinctions;
- relationship or cardinality disputes;
- consequential capability classifications;
- current-versus-target boundaries;
- actor and authority questions.

Review selection is deterministic: blocking items sort before non-blocking
items, then by downstream dependency count, authority risk, capability impact,
and stable ID. Every blocking item must be reviewed. If more than 12 blockers
exist, Phase 3 produces numbered batches of at most 12 and remains blocked until
all blocking batches are decided. Non-blocking items may remain in the searchable
evidence index without consuming the first checkpoint.

Each item shows a compact initial summary:

```text
ID and title
Why this matters
Proposed interpretation or decision
What supports it
What remains uncertain
Consequence of accepting it
Options
Feedback controls
```

Repository evidence, schemas, and extended reasoning are behind disclosure
controls. Filters cover unresolved, accepted, rejected, revise, and uncertain
items. Capability status and confidence are visible without expansion.

Each item provides accept, reject, revise, and uncertain controls, an optional
note, and a copyable ID. Feedback persists in `localStorage` and exports as JSON
or concise text. The artifact needs no local save endpoint.

The local-storage key includes the foundation schema version and review-batch
ID. JSON export conforms to `schemas/review-feedback.schema.json` and records the
review version, batch ID, item ID, response, note, source snapshot, and an
optional reviewer label without collecting authentication data. Allowed
response transitions retain prior values in export history.

The repository-side procedure is explicit: save an exported file under
`reviews/feedback/`, run `uv run python
research/ui-foundation/tools/import_feedback.py <export-path>`, validate its
schema and source snapshot, then generate candidate decision records for human
confirmation. Import never changes observed evidence or capability status
directly. Confirmed decisions are written to `catalog/decisions.yaml`, projected
to `decision-log.md`, and trigger regeneration of affected review projections.

The review index summarizes progress, source coverage, unresolved conflicts, and
links to the checkpoint. It clearly states that no reviewed item is a product UI
screen or evidence of a future capability.

## Verification

### Deterministic Semantic Checks

`research/ui-foundation/tools/validate.py` is the mandatory validator for all
canonical YAML, schemas, source hashes, cross-references, and review
projections. It runs as:

```bash
uv run python research/ui-foundation/tools/validate.py
```

It verifies:

1. YAML parses and required fields are present.
2. Status values belong to their declared enums.
3. Stable IDs are unique and references resolve.
4. Every `current` claim has implementation evidence.
5. Every `derived` claim references a complete derivation contract.
6. Every derivation defines unknown and freshness behavior.
7. Every current action references an implemented command contract and reachable
   current-state transition; every absent intervention references a gap or
   proposed-action requirement and no executable current action.
8. Current and target capability classifications do not leak into each other.
9. Every causal claim records an epistemic type and evidence.
10. Every named state exists in the state model.
11. No unproven slash-separated entity equivalence is encoded as an alias.
12. Every review item resolves to canonical semantic IDs and evidence.

All 12 checks are mandatory. A malformed file, unresolved required reference,
stale evidence hash, invalid status, incomplete derivation, or contradictory
current classification fails validation. Contradictions represented by a valid
`CON-*` record are allowed only when the affected claim is not classified as
current, derived, or ready for downstream use.

### Independent Semantic Verification

An independent verifier attempts to find:

- invented fields or relationships;
- false entity equivalences;
- unsupported causal claims;
- impossible transitions;
- actions without commands;
- current/future leakage;
- missing unknown states;
- violations of documented invariants;
- claims that cannot be traced to evidence;
- overfitting to the repeated-verifier-failure scenario.

Verifier findings are accepted, rejected with evidence, or registered as open
conflicts. Plausibility alone does not pass the model.

### Review Artifact Verification

`ui/tests/e2e/ui-foundation-review.spec.ts` checks the static HTML directly with
the repository's existing Playwright setup:

```bash
npm --prefix ui run test:e2e -- tests/e2e/ui-foundation-review.spec.ts
```

It verifies:

- direct `file://` operation without network requests;
- keyboard navigation and visible focus;
- semantic controls and readable disclosure behavior;
- narrow-viewport integrity;
- feedback persistence across reload;
- JSON and concise-text export;
- stable filter behavior;
- clear rendering when data initialization fails.

Both validation commands must pass. Environmental inability to execute either
command is a blocked verification outcome, not a skipped check.

## Completion Gate

This work package reaches an artifact-complete state when:

- bounded repository audits cover the declared implementation areas;
- important entities and relationships have evidence or explicit unknown status;
- important JTBD information claims have capability classifications;
- admitted derivations define unknown and freshness behavior;
- implemented UI-relevant actions have permission and transition contracts, and
  absent interventions have validated gap or proposed-action requirement records;
- conflicts and missing evidence are visible;
- deterministic checks pass;
- the independent semantic verifier's findings are resolved or registered with
  explicit blocking status;
- the Phase 3 HTML checkpoint is usable and concise;
- human feedback is exportable and accepted decisions are recorded.

The terminal outcome is one of:

- `complete-ready`: all artifact conditions pass and no blocking conflict,
  unknown, verifier finding, or human decision remains. This authorizes planning
  the jobs-and-journeys reconciliation work package.
- `complete-blocked`: durable artifacts and review are complete, but one or more
  blocking items remain. No downstream reconciliation, view contract, or
  interface work may rely on those items.

Neither outcome authorizes interface concepts. The next work package begins
with reconciliation of jobs and journeys only after a `complete-ready` Phase 3
reality and capability boundary.
