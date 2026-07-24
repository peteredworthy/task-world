# Evidence Inventory Synthesis

## Purpose

Normalize the approved Phase 1 evidence findings into a provisional inventory for
Task 13. This is an evidence-carrier inventory, not a canonical evidence catalog
and not a capability classification. `EVI-P-*` keys are local to this synthesis;
they intentionally do not allocate `EVD-*` identifiers.

## Scope inspected

- Task 12 brief, approved Phase 0-3 design, `AGENTS.md`, and the closed scope
  manifest.
- Phase 0 snapshot at `catalog/evidence.yaml`.
- Approved bounded reports `01-domain-persistence.md` through
  `07-tests-documentation.md`; the latter confirms that those report findings
  need fresh source qualification rather than treating static test inventory as a
  current pass result.
- `reality/evidence/inventory.yaml` and `tools/validate.py`.

## Key findings

1. The inventory contains **9 provisional evidence carriers**: workflow event,
   graph event, accepted graph record, prompt packet, transcript/tool trace,
   artifact reference, file-state boundary, decision evidence, and cost/usage
   fact. Similar names do not establish identity equivalence.
2. Workflow events use global SQL `position` and aggregate `(aggregate_id,
   version)` identity; graph events additionally retain `event_id` and a distinct
   graph aggregate namespace. Activity is a selected projection, not a complete
   combined ledger.
3. Records are typed accepted snapshots with node/port provenance; prompts,
   transcripts, artifacts, file-state, decisions, and usage each have
   carrier-specific persistence and query guarantees. The inventory records their
   missing behavior and prohibited inferences rather than deriving a unified
   trace.
4. Cost evidence is honest only when `rate_missing`, returned-execution coverage,
   and graph-only rollup scope remain visible. Absent usage and numeric zero are
   not equivalent.
5. All **6/6** Phase 0 source-document/design hashes were recomputed. Each equals
   its snapshot hash: **0 drifted, 6 unchanged**. This confirms only the snapshot
   source set; implementation and test sources cited by the reports were never
   hash-snapshotted and remain drift-unguarded.

## Important uncertainties

- No canonical cross-stream chronology, universal record/artifact identity, or
  persistent selection chain is implemented.
- Graph prompt summaries do not prove exact packet bytes, delivery, model
  ingestion, prompt size, truncation accounting, or directive binding.
- Graph transcript/tool evidence is incomplete; legacy structured action logs do
  not fill that graph gap.
- Whole-worktree file-state is observed at a node callback, not established as a
  node-exclusive causal delta.
- Returned-execution usage does not cover exact-zero/absent telemetry or provider
  use followed by runner exception; price coverage has no complete denominator.
- Decision attribution is carrier- and transport-specific and is not uniformly
  authenticated authorization evidence.

## Conflicts found

1. Required documentation says JSONL-first recovery, while the approved domain,
   workflow, graph, and telemetry reports establish SQL-event transactional
   authority with post-commit JSONL and conditional empty-database bootstrap.
2. The activity endpoint is described as activity history but includes only a
   selected graph subset; graph events must be queried separately for that ledger.
3. “Artifact” spans verified CAS content, unverified declarations, expected paths,
   interaction-log rows, and record payloads; it has no one integrity contract.
4. Per-model/graph-rollup `rate_missing` preserves unpriced status, while some
   run-level/UI/legacy projections can present known subtotals or estimates as
   totals.

## Decisions required

1. Task 13 must allocate canonical IDs only after preserving these carrier
   boundaries and registering the SQL/JSONL authority conflict.
2. Decide whether implementation/test sources supporting admitted evidence must
   receive a content-hash snapshot before Phase 1 normalization treats them as
   non-stale.
3. Retain prompt delivery, transcript completeness, directive binding,
   node-exclusive file causality, universal action receipts, and complete usage
   coverage as explicit gaps/unknowns unless new qualifying evidence is added.
4. Do not use activity, artifact declarations, absent usage, or price subtotals as
   broader evidence than their carrier contract permits.

## Artifact paths

- `research/ui-foundation/reality/evidence/inventory.yaml`
- `research/ui-foundation/agent-reports/10-evidence-synthesis.md`
- `.superpowers/sdd/task-12-synthesis-report.md`

No canonical catalog or source file was edited by this task.

## Evidence pointers

- `research/ui-foundation/catalog/evidence.yaml::snapshot` for the Phase 0
  baseline hashes.
- `research/ui-foundation/agent-reports/01-domain-persistence.md` for event,
  record, artifact, and persistence distinctions.
- `research/ui-foundation/agent-reports/02-graph-runtime.md` for graph events,
  accepted records, bindings, and projection limits.
- `research/ui-foundation/agent-reports/03-workflow-state.md` and
  `04-api-actions-authority.md` for queued acceptance/result and decision
  boundaries.
- `research/ui-foundation/agent-reports/05-evidence-telemetry.md` for all nine
  carrier contracts, telemetry coverage, and cost honesty limits.
- `research/ui-foundation/agent-reports/06-ui-projections.md` for surfaced
  query/freshness/coverage limitations.
- `research/ui-foundation/agent-reports/07-tests-documentation.md` for test
  qualification and unguarded-source drift limits.

## Recommended next delegation

Task 13 should allocate canonical evidence IDs, resolve only demonstrated
duplicates, register conflicts and questions, and carry forward every listed
prohibited interpretation. Task 14 should classify only evidence-supported
capabilities and require derivation contracts for any aggregate, freshness,
coverage, causal, or cost claim.
