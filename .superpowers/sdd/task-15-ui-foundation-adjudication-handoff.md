# Task 15 UI foundation adjudication handoff

## Purpose

Record the canonical SV-008 adjudication correction while preserving Phase 1 immutability.

## Scope inspected

The 35 REL, 72 active STA, 71 ACT, 9 EVI, and INV-2 through INV-7 records.
`research/ui-foundation/catalog/status-scope.yaml` now enumerates all 193 records and their exact
declaration paths; rejected `STA-28` is explicitly outside that closed set.

## Key findings

The record-level audit is applied without family-wide downgrades. Its 113 unique exact pytest locators
(107 qualifying plus bounded nonqualifying carrier locators) resolve against the active snapshot.

## Important uncertainties

Task 15 remains pending independent re-review; unexercised boundaries remain conservative.

## Conflicts found

Existing canonical documentation conflicts remain recorded on their affected records.

## Decisions required

No new product decision is required; independent re-review is required before closure.

## Artifact paths

`research/ui-foundation/catalog/evidence.yaml` and canonical reality/catalog records contain the adjudication.

## Evidence pointers

See each record's five-field `status_basis`, `implementation_locators`, `test_locators`, optional
`bounded_test_locators`, and the active Task 15 snapshot. The resulting test-status distributions are
REL 23/12, STA 67/5, ACT 58/13, EVI 5/4, and INV 6/0 exercised/unexercised.

## Recommended next delegation

Independently re-review canonical statuses and validator enforcement without editing the immutable verifier report.

## Action/evidence findings 2 and 3 remediation

In progress: ACT-75/76/80/81/82 now use typed carrier-specific transition variants,
including exact accepted/rejected TaskStatus partitions and ACT-81's PAUSED run-carrier
accepted no-op without task mutation. EVD-116 remains engine-only; REST and MCP
escalation registration/handler/test evidence has distinct direct IDs. Broad projection
text cleanup remains deferred to the final pass; this handoff does not claim closure.

## Status

Task 15 remains **IN PROGRESS** pending independent re-review. Structural findings SV-001 through SV-008 are
corrected in this pass; SV-008 canonical status locators were re-adjudicated against current source. The
immutable `research/ui-foundation/agent-reports/11-semantic-verification.md`
was not modified.

Snapshot-lineage follow-up remains in progress: `snapshot-2026-07-23-phase-0` is a detached historical root,
the active adjudication chain must root at `snapshot-2026-07-24-phase-1`, and the only supported bounded delta
recorder is `research/ui-foundation/tools/record_snapshot_lineage.py`.

## Accepted corrections

- **SV-007:** `ENT-26` is removed from the active entity collection. Its allocation
  remains permanently rejected with the reason and distributed-supersession note;
  it cannot be reused. Artifact-carrier distinctions remain in `EVI-6`, the
  `ENT-22` through `ENT-25` carriers, and `CON-5`.
- **SV-008:** all 35 relationships, 72 active states, 71 actions, 9 evidence
  inventory records, and `INV-2` through `INV-7` now have record-level
  orthogonal statuses and dimension-specific bases. Exercised records name an
  exact active-snapshot pytest AST symbol; arbitrary suffixes, missing methods,
  stale hashes, and generic carrier boundaries are rejected. Unexercised
  result/action boundaries remain conservative. Carrier existence does not
  bulk-promote product capability status.
- **Audit deviations:** none. Every audited implementation and exact pytest locator still resolves;
  explicit unexercised recommendations, including bounded EVI carrier evidence, remain unexercised.

- **SV-003:** `CON-1` and `Q-1` now target the actual attempt-reference
  relationships, `REL-26` (cost) and `REL-29` (interaction), with reciprocal
  links. `REL-27` remains only run attribution. `CAP-71` now retains the same
  identity uncertainty because its another-attempt cost input relies on that
  attribution boundary.
- **SV-004:** `Q-4` no longer targets resolved model `ENT-28`; it now covers
  backup metadata, copied DB, journal segment, and the copy/marker/import
  relationships `REL-33` through `REL-35`. The records continue to prohibit
  claims of a live-WAL-consistent backup.
- **SV-005:** `Q-6` is resolved against `CMD-13`, not `CMD-16`. The
  execution-bound MCP server is per-runner execution tooling routed through a
  dispatcher closure, so it is not a standalone UI/operator action. REST patch
  `ACT-13`/`CMD-12` and merge-back `CMD-16` remain distinct. The command ledger
  locates MCP registration in `graph_mcp_tools.py` and both merge commands in
  `api/routers/runs.py`.
- **SV-006:** open blocking question links now fail closed for current
  capabilities even if the question omits the capability from `affected_ids`.
  `Q-5` now covers every permission boundary `PER-1` through `PER-7`, its
  linked authority-sensitive capabilities and actions, while preserving the
  distinction between authentication, domain eligibility, tool exposure, and
  enforced product authorization. `CAP-86` remains unknown after SV-002.
- **Snapshot lineage:** immutable `snapshot-2026-07-24-phase-1` is restored to
  its Task 14 membership, hashes, timestamps, and 902-file count. Current
  rechecks use `snapshot-2026-07-24-task-15-adjudication`, explicitly parented
  to Phase 1; the validator digest-checks the historical snapshot instead of
  rewriting it. The active Task 15 snapshot now contains the 98 current source/test members needed by
  this adjudication; the immutable Phase 1 digest remains
  `a5081f732fc02989b1e04ca5bca6f03d55ba11d5975542ab3c7816747944b8a0`.

## Bounded mechanical unit 1

All 193 SV-008 records now pass through one fail-closed status validator, including actions. Exact
Python top-level/class-member/enum-member locators and exact YAML `id`/`canonical_id` locators must
full-match and resolve against current active-snapshot bytes; prose, arbitrary YAML fields, canonical
self IDs, evidence records, and partial-list rescue are not accepted. Test locators retain the Task 15
AST/current-hash check; no pytest collection manifest was added.

The migration removed non-implementation evidence/self-field locators from `REL-1`, `REL-5`,
`REL-6`, `REL-14`, `REL-31`, `REL-35`, the affected review/repository/graph state records,
`INV-7`, and present action records. `ACT-4`, `ACT-5`, and `ACT-56` now name their existing
`back_merge_endpoint`/`merge_back_endpoint` source symbols, and `ACT-59` names
`agent_resolve_conflicts`. No implementation status required downgrade. `ACT-27`'s existing
conflicting status is now reciprocal with open authorization question `Q-5`; semantic status choices
and the immutable verifier report were not changed.

## Verification handoff

Phase 2 validation and focused foundation tests have passed for bounded mechanical unit 1. Ruff,
Pyright, and hooks are part of its commit gate. The historical Task 15 status audit is
noncanonical reviewed evidence only and is not parsed by shipped tools or used
as a regeneration input. Independent re-review must assess this application
without changing the immutable verifier report.

## Bounded mechanical unit 2

`catalog/status-test-nodes.yaml` is now the deterministic, pytest-collected
authority for the 113 canonical status-test bases and 113 concrete nodes. Its
collector executes one `pytest --collect-only` subprocess with xdist worker
count zero, records the active Task 15 snapshot identity and source hashes, and
does not parse audit Markdown. The validator retains the AST resolver only as
defense in depth and fail-closes on missing, duplicate, malformed, stale,
inactive, unknown, or uncollected manifest entries. No semantic status, Phase
1 snapshot, or verifier-report content changed.

## SV-001 reconciliation retirement correction

The executable reconciliation guards return when `ready_nodes` is non-empty and also
require no active lease. Therefore the reconciliation retirement source set is exactly
`STA-71`, `STA-72`, and `STA-32`; the impossible `STA-29 -> STA-73` reconciliation
edge was removed. `STA-29 -> STA-73` remains in the separate accepted `CMD-12`
`retire_node` patch mapping, whose source set remains `STA-71`, `STA-72`, `STA-29`,
and `STA-32`. The 72 active-state count and the REL/STA/ACT/EVI/INV status
projections are unchanged because no state carrier was removed. The validator now
enforces both mechanism-to-command mapping and source eligibility, with a regression
covering ready-node reconciliation recurrence.
