# Task 15 UI foundation adjudication handoff

## Status

Task 15 remains **IN PROGRESS** pending independent re-review. Structural findings SV-001 through SV-006 are
being corrected in this pass; SV-008 status locators are intentionally out of scope. The
immutable `research/ui-foundation/agent-reports/11-semantic-verification.md`
was not modified.

## Accepted corrections

- **SV-007:** `ENT-26` is removed from the active entity collection. Its allocation
  remains permanently rejected with the reason and distributed-supersession note;
  it cannot be reused. Artifact-carrier distinctions remain in `EVI-6`, the
  `ENT-22` through `ENT-25` carriers, and `CON-5`.
- **SV-008:** all 35 relationships, 72 active states, 71 actions, 9 evidence
  inventory records, and `INV-2` through `INV-7` now have record-level
  orthogonal statuses and dimension-specific bases. Exercised records name a
  snapshot-resolvable test locator or approved test-index locator; unexercised
  result/action boundaries remain conservative. Carrier existence does not
  bulk-promote product capability status.

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
  rewriting it.

## Verification handoff

Run Phase 2 validation, the report validator for this handoff if its heading
contract is later adopted, focused foundation tests, Ruff, Pyright, and hooks
before closing the task. The historical Task 15 status audit is noncanonical
evidence only and is not a regeneration input. Independent re-review must assess
this application without changing the immutable verifier report.
