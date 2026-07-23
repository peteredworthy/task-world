# Phase 0 Delegation Plan

## Purpose

Bound seven independent implementation-reality audits without allowing agents to
mint canonical IDs or edit shared semantic catalogs.

## Scope inspected

The approved Phase 0–3 design, five unchanged JTBD documents, closed scope
manifest, source snapshot, and validator contracts.

## Key findings

Every source demand in `catalog/scope.yaml` has one scalar `audit_owner`. The
seven owners are `domain-persistence`, `graph-runtime`, `workflow-state`,
`api-actions-authority`, `evidence-telemetry`, `ui-projections`, and
`tests-documentation`. Each audit writes only its numbered report, uses scoped
provisional keys, cites paths and symbols, and distinguishes implemented,
tested, documented-only, inferred, and unclear findings.

## Important uncertainties

Implementation status, reachability, exercised behavior, derivability, action
authority, and source conflicts remain unknown until the bounded audits finish.

## Conflicts found

None are asserted in Phase 0. Source capability statements are demands to audit,
not implementation findings.

## Decisions required

No human decision is required to start the bounded audits. Any new source demand
requires a recorded scope decision before normalization.

## Artifact paths

- `research/ui-foundation/catalog/scope.yaml`
- `research/ui-foundation/catalog/evidence.yaml`
- `research/ui-foundation/status.md`
- `research/ui-foundation/agent-reports/01-domain-persistence.md` through
  `07-tests-documentation.md` (delegated outputs, not yet created)

## Evidence pointers

The authoritative source snapshot is `snapshot-2026-07-23-phase-0`; `EVD-01`
through `EVD-06` identify its documents. Content hashes, not revision metadata,
control drift.

## Recommended next delegation

Run the seven Phase 1 audits independently. Agents may create only their assigned
report and must not create Phase 1 findings in canonical YAML. Normalize reports
only after source hashes are rechecked.
