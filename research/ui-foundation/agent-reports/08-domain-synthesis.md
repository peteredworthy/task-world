# Domain And Relationship Synthesis

## Purpose

Normalize the seven bounded Phase 1 reality audits into a typed, provisional
domain graph for later canonical normalization. This synthesis records only
distinctions and relationships supported by the reports. It does not allocate
canonical `ENT-*` or `REL-*` identifiers, classify capabilities, create action
contracts, or resolve a disagreement merely by using broader prose.

## Scope inspected

- Approved design: `docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md`.
- Closed demand inventory: `research/ui-foundation/catalog/scope.yaml`.
- Reality reports: `agent-reports/01-domain-persistence.md` through
  `agent-reports/07-tests-documentation.md`.
- Typed collection and report-validation rules:
  `research/ui-foundation/schemas/semantic-item.schema.json` and
  `research/ui-foundation/tools/validate.py`.
- Existing incomplete Phase 1 collection shells were read only to avoid
  inventing dependencies on state, permissions, evidence, or capability catalogs.

## Key findings

1. The decisive persistent legacy hierarchy is **Run -> Step -> Task -> Attempt**.
   Template configuration and runtime/config identifiers remain distinct, and a
   task's attempt ordinal is not a durable attempt identity.
2. Graph runtime has a separate typed topology: graph projection, node, directed
   edge, accepted record, input binding, lease, graph event envelope, and outbox
   intent. An explicit graph dataflow mechanism can justify a bounded dependency
   statement, but temporal ordering cannot justify a causal label.
3. Core/graph boundary terms remain distinct: step/region, task/node,
   attempt/graph attempt number, workflow event/graph event envelope,
   requirement/checklist item/graph record, and process-local task lock/graph
   lease. Frontend string joins do not change those boundaries.
4. Artifact is not a safe identity class. CAS references, graph path declarations,
   configured expected paths, interaction-log rows, output records, backups, and
   journal files have different identity, persistence, and integrity semantics.
5. The normal event authority is SQL transactional append plus projections with
   JSONL secondary output; JSONL can import only into an empty event store during
   bootstrap. This executable behavior conflicts with JSONL-first documentation
   and remains explicitly conflicted.
6. The produced graph contains **25 provisional entities** and **26 directed
   provisional relationships**. Each relationship has cardinality, ownership or
   reference semantics, temporal/dependency behavior, epistemic status, evidence,
   counter-evidence where applicable, unknowns, and prohibited causal readings.

## Important uncertainties

- Attempt primary-key `id` versus nullable semantic `attempt_id` is a blocking
  identity conflict; no global alias or canonical selection was made.
- No typed persistent selection chain connects run, region, step, node, task,
  attempt, record, event, requirement, decision, and time.
- Region is not a first-class proven entity; `task_region_id` remains an optional
  string and must not be normalized as a region/task equivalence.
- Graph and legacy state/telemetry have real shared run-row contact but no proven
  common topology, transcript, prompt, cost, or action-result contract.
- Backup metadata and journal marker do not establish a crash-consistent snapshot
  or automated replay procedure.

## Conflicts found

1. **Attempt identity:** migration/documented `attempt_id` claims conflict with
   nullable/non-unique storage and repository use of `attempts.id`.
2. **Event authority:** AGENTS documentation says JSONL-first; event store,
   projections, and recovery code demonstrate SQL-first normal writes with
   conditional JSONL bootstrap.
3. **Run terminality:** failed is generally terminal in the legacy vocabulary but
   can reopen only through qualified graph-mode behavior.
4. **Authority attribution:** JWT authentication, fixed users, caller-supplied
   approvers/deciders, and fixed operator values are not one authenticated actor
   identity contract.
5. **Artifact and evidence coverage:** generic graph artifact declarations are
   not CAS publication, and legacy structured logs have no graph-equivalent
   persistence.

## Decisions required

1. Engineering adjudication must select or migrate the canonical attempt identity
   before Task 13 can map a durable attempt contract.
2. Define typed conversion contracts before joining graph node/record/event or
   region-like data to legacy task/attempt/requirement identities.
3. Reconcile the documented JSONL-first invariant with executable SQL authority;
   do not publish a universal event-authority statement until then.
4. Decide whether artifact receives a future typed supertype or remains explicit
   variant carriers. This synthesis deliberately preserves variants.
5. Decide whether historical model profile, cross-mode selection, and recovery
   snapshot/replay guarantees need new persisted contracts.

## Artifact paths

- `research/ui-foundation/reality/domain-model.yaml`
- `research/ui-foundation/reality/relationships.yaml`
- `research/ui-foundation/agent-reports/08-domain-synthesis.md`
- `.superpowers/sdd/task-10-synthesis-report.md`

## Evidence pointers

- Domain identities/ownership: `agent-reports/01-domain-persistence.md`, notably
  `DP-ENT-*`, ownership tables, temporal boundaries, and `DP-CON-01`/`DP-CON-02`.
- Graph topology/dataflow/leases: `agent-reports/02-graph-runtime.md`, notably
  `NodeModel`, `EdgeModel`, `PortContract`, scheduler, command, and store findings.
- Legacy lifecycle/mode boundary: `agent-reports/03-workflow-state.md`, notably
  `WF-run-*`, `WF-task-*`, signal processing, and legacy-versus-graph comparison.
- Authority/action carrier distinctions: `agent-reports/04-api-actions-authority.md`.
- Evidence, artifact, usage, and journal qualifications: `agent-reports/05-evidence-telemetry.md`.
- Frontend string-join and selection limitations: `agent-reports/06-ui-projections.md`.
- Test/documentation qualification and stale-document conflicts:
  `agent-reports/07-tests-documentation.md`.

## Recommended next delegation

Task 13 should allocate canonical IDs only after preserving the unresolved
attempt, event-authority, region/node/task, artifact, and actor-attribution
conflicts in the canonical conflict/question ledgers. Action/state/capability
synthesis must consume these typed boundaries rather than recreate slash
equivalences or infer causality from event order.
