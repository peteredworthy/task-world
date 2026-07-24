# Domain And Relationship Synthesis

## Purpose

Normalize the seven bounded reality reports into a provisional typed graph without
canonical IDs, slash equivalences, or unsupported causal claims.

## Scope inspected

- Approved design, closed scope, semantic schema, validator.
- `agent-reports/01-domain-persistence.md` through
  `agent-reports/07-tests-documentation.md`.

## Key findings

1. The legacy hierarchy remains Run -> Step -> Task -> Attempt. Attempt grade
   snapshots are distinct historical entities, never mutable checklist items.
2. A persisted `events_v2` row is distinct from workflow payloads and graph event
   envelopes. Run-to-workflow and run-to-graph aggregate associations are modeled
   separately; JSONL bootstrap targets persisted rows, not payload identities.
3. Graph node, edge, record, binding, lease, projection, and outbox are distinct
   graph carriers. The outbox identity is `outbox_id`; `event_id` is a unique
   association. Cardinality is structurally separated from temporal/context data.
   The graph uses endpoint convention: source multiplicity is source entities per
   target endpoint; target multiplicity is target entities per source endpoint.
4. Artifact carriers are split into verified CAS blob, generic graph declared
   path reference, configured expected path, and interaction-log row. The retained
   artifact taxonomy explicitly has no identity.
5. Backup metadata references exactly one copied DB and records one journal path
   plus scalar marker. Journal scan participation is an observation, not a
   persisted collection of segment references; WAL/live-copy consistency is open.

## Important uncertainties

- `attempts.id` versus nullable `attempt_id` remains a blocking identity conflict.
- Region, node, task, attempt number, record, and requirement have no typed
  cross-mode selection chain.
- SQL-first normal writes and JSONL-first documentation remain conflicting.
- A graph declared artifact path does not prove file existence or CAS publication.

## Conflicts found

1. Attempt identity contracts conflict.
2. Event/journal authority wording conflicts with executable normal writes.
3. Failed terminality is mode-qualified.
4. Recorded action attribution is not one authenticated actor identity.
5. Artifact and telemetry coverage differs materially between graph and legacy.

## Decisions required

1. Select/migrate canonical attempt identity before Task 13 normalization.
2. Define typed cross-mode conversion contracts before joins.
3. Reconcile JSONL authority documentation with executable behavior.
4. Decide whether artifact receives a future supertype; do not turn taxonomy into
   an identity before that design exists.
5. Define a live-WAL-safe snapshot/replay contract if backup metadata is to imply
   recoverability.

## Artifact paths

- `research/ui-foundation/reality/domain-model.yaml`
- `research/ui-foundation/reality/relationships.yaml`
- `research/ui-foundation/agent-reports/08-domain-synthesis.md`
- `.superpowers/sdd/task-10-synthesis-report.md`

## Evidence pointers

All YAML evidence and counter-evidence references resolve to explicit
`agent-reports/<file>#<exact heading>` anchors. Principal anchors are:

- `agent-reports/01-domain-persistence.md#Entity and identity inventory`
- `agent-reports/01-domain-persistence.md#Ownership and cardinality`
- `agent-reports/01-domain-persistence.md#Temporal relationship behavior`
- `agent-reports/01-domain-persistence.md#Conflicts found`
- `agent-reports/02-graph-runtime.md#Key findings`
- `agent-reports/03-workflow-state.md#JSONL authority conflict`
- `agent-reports/04-api-actions-authority.md#CLI database maintenance capability`
- `agent-reports/05-evidence-telemetry.md#Evidence inventory and producer wiring`
- `agent-reports/06-ui-projections.md#Rendered claim trace`
- `agent-reports/07-tests-documentation.md#Evidence qualification`

## Recommended next delegation

Task 13 should allocate canonical identifiers only after registering the attempt,
event-authority, graph/core conversion, artifact, actor, and backup conflicts.
Downstream work must consume these typed boundaries rather than infer equivalence
from matching strings or causality from temporal order.
