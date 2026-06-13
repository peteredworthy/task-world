# Slice 3.5 — File-state diff, manifest & residue/gatekeeper viewer

Size: M. §26 requires "File-state diff and manifest summary" visibility, and the
warn-and-capture/gatekeeper model (slices 2.4/2.5) produces residue
classifications and gatekeeper verdicts that are currently invisible in the UI.

## Ground truth

- execution-graph-prd-plus.md §26 — "File-state diff and manifest summary".
- §20 File-State and Snapshot Policy (classifications, git_commit/manifest
  snapshots), §20.3 secret/residue taxonomy.
- Existing pure projections: `project_residue_report`,
  `project_gatekeeper_report`; file-state records carry snapshot id, verdict,
  classifications; node-detail (3.3) lists file-state records.

## Scope — what to build

### 1. API — file-state detail + residue/gatekeeper report

- `GET /api/runs/{run_id}/graph/file-state` → `FileStateReportResponse` built
  from `project_residue_report` + `project_gatekeeper_report` + accepted
  file-state records: per node, the snapshot id/type (git_commit / manifest),
  classification counts (tool_cache / build_output / test_artifact / secret /
  external_artifact / unknown_ignored), rejected paths with reasons, and
  gatekeeper verdicts (allow/reject + rationale, replayed from events — never
  re-asks the model).
- Read-only; 200 empty for non-graph runs.

### 2. UI — file-state viewer

- A "File-state" section (in `NodeDetailPanel` from 3.3 and/or `GraphPanel`):
  per accepted boundary, show snapshot id + type, a classification summary
  (counts by taxonomy), the list of captured/rejected paths with classification
  + reason, and any gatekeeper verdict + rationale.
- Where a snapshot is a `git_commit`, show a diff summary affordance (files
  changed / +/- counts) derived from the snapshot metadata already recorded;
  full diff rendering may link out and is not required in v1.
- `useFileStateReport(runId)` hook.

## Tests

### Integration — `tests/integration/test_graph_file_state_report_api.py` (new)

Real SQLite tmp; seed accepted file-state + a gatekeeper verdict
(reuse gatekeeper-flow seeding):
- `test_file_state_report_lists_classifications_and_verdicts()` — the endpoint
  returns classification counts, rejected paths with reasons, and the recorded
  gatekeeper verdict + rationale.
- `test_file_state_report_empty_for_non_graph_run()` — 200, empty.

### Frontend — vitest

- File-state viewer renders snapshot summary, classification counts, rejected
  paths, and gatekeeper verdict from fixture data.

## Done when

1. `GET /graph/file-state` returns per-node snapshot summaries, classification
   counts, rejected paths + reasons, and replayed gatekeeper verdicts (no model
   re-ask), all from existing events/projections.
2. UI file-state viewer renders those, with a diff-summary affordance for
   git_commit snapshots.
3. Empty-but-valid response + UI for non-graph runs.
4. Full suites green (unit/integration/vitest); ruff/pyright clean; kernel
   purity + `graph_runtime` boundary unchanged.

## Hard constraints (same as all slices)

- NO mocks/monkeypatching; hand-written fakes; frontend fixtures only.
- Real SQLite tmp dirs; never touch `orchestrator.db`.
- Read-only projection; replay gatekeeper verdicts from events (never call the
  model from the report path). No graph mutations (§28 rule 1).
