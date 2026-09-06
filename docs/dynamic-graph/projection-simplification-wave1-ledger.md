# Projection Simplification Wave 1 Requirements Ledger

Updated: 2026-08-13

Target: complete Wave 1 from the projection simplification review by separating
the runtime checkpoint from the bounded public graph snapshot and by producing
an evidence-backed archival-view consumer decision. Events remain authoritative;
runtime command handling remains snapshot+tail.

| ID | Required behavior | Acceptance criteria | Current evidence | Product-real proof | Regression evidence | Status | Remaining gap |
|---|---|---|---|---|---|---|---|
| W1-CP-1 | Runtime checkpoint has a dedicated disposable storage owner. | A fresh database contains a runtime-checkpoint table/owner with run ID, position, schema version, checksum-backed serialized projection, and terminal metadata; it is not response-size packed. | `GraphProjectionCheckpointModel` owns the codec envelope, checksum, position, schema version, and terminal flag and is exported through both DB public surfaces. | Replacement run `8e677613-36c1-4a96-a73e-46b5a678955b` dispatched its real planner and accepted two patches. | Fresh-schema, database, event-store, codec, and dispatch tests. | complete | None. |
| W1-CP-2 | Public `/graph` snapshot is independent and bounded. | `GraphProjectionSnapshotModel` contains only compact API read data and no full runtime checkpoint; existing API response contracts remain bounded and unchanged. | Public snapshots contain bounded read-contract fields only; runtime checkpoint fields are absent. | Public `/graph` remained readable through oversized-history recovery and live dispatch. | Read-contract matrix, oversized-checkpoint, and API projection tests. | complete | None. |
| W1-CP-3 | Runtime recovery uses checkpoint+tail and safely rebuilds disposable corruption. | Valid checkpoints fold only their bounded tail; missing, malformed, checksum-invalid, schema-mismatched, or stale checkpoints rebuild deterministically from events when within the recovery contract. | Explicit resume runs keyset-batched maintenance; dispatch and reattachment are projection-owned and do not read full history from position zero. | Both replacements crossed the real Codex callback boundary; the checkpoint run advanced graph position 21 to 28. | Missing/stale/corrupt/schema/parity tests plus the greater-than-128-event FR-09 dispatch/reattachment proof. | complete | None. |
| W1-CP-4 | Publication and lifecycle behavior stay correct. | Public snapshot, runtime checkpoint, event summaries, archival dirty marker, and node-detail updates preserve transactional/position semantics; cancellation and terminal metadata remain correct. | Snapshot/checkpoint publication is atomic; cancellation, terminal metadata, null parity, and callback identity are covered. The deterministic cache-budget failure was Wave 1 behavior retained only for durable replay; current collection treats recognized cache roots as opaque and spends no budget on their descendants. | Both replacement runs stayed active without read-model errors and recorded real callbacks. | Focused integration tests, full suite, Ruff, Pyright, signal routing, and projection boundary checks. | complete | None. |
| W1-AR-1 | Archival consumers are completely inventoried. | Audit covers UI, API, runtime/store, ORM, workers, docs, CLI/MCP, and tests with file/line evidence and distinguishes internal evidence from unknown external use. | The rebased audit covers every required surface; fresh search found 15 integration consumers, one UI path, and no CLI/MCP consumer. | Replacement archival run inspected the audit through real Codex and issued a graph-patch callback. | Independent citation sampling and repository-wide consumer search. | complete | External REST usage remains an explicit product unknown, not an audit gap. |
| W1-AR-2 | A safe product decision and implementation plan exists. | Audit recommends keep/narrow/retire per surface, protects final invariants and failed-outbox blocking, describes deprecation, slices, conflicts, exit criteria, risks, and rollback. | Recommendation: narrow/conditionally retire topology, keep and decouple final blockers, deprecate then retire regions. | The decision package was accepted by the independent validator as implementation-ready. | Guardrail, sequencing, risk, rollback, and unresolved-decision review. | complete | Product owners still need to resolve the four documented external/compatibility decisions before endpoint retirement. |
| W1-REAL-1 | The repaired system is exercised through its real graph/Codex interface. | Two Wave 1 graph runs use Codex Server `gpt-5.6-luna` / high and record real callbacks or subsequent graph progress. | As-of-Wave-1 evidence: original immutable 10,000-entry snapshots were paused and replacements used a validated 50,000-entry policy. That historical limit remains in v1 fields for replay compatibility; current collection records and checks each recognized cache root without inspecting or charging descendants, while preserving root-symlink and unknown-directory secret/repo-escape checks. | Checkpoint `8e677613-36c1-4a96-a73e-46b5a678955b` accepted two patches; archival `b598c0d2-f8b5-46bd-b037-000ab4132414` recorded a real patch callback that the kernel safely rejected for a forbidden cycle while planning continued. | Live API/activity/graph evidence plus cache-boundary and terminal-failure regressions. | complete | None. |

## Baseline

Baseline commands and results are recorded here before implementation. Known
failures must not be attributed to the change unless the same command passed at
baseline.

- Focused baseline passed before implementation: `UV_CACHE_DIR=/tmp/task-world-uv-cache uv run pytest -n 0 tests/unit/test_graph_projection_codec.py tests/integration/test_graph_event_store.py tests/integration/test_graph_read_contract_matrix.py tests/integration/test_cache_authority_recovery_durability.py` (38 selected passed, 33 deselected by the configured impact selector; 2026-08-13).
- Product-real baseline: both Wave 1 graph runs pause with
  `graph_projection_checkpoint (recovery_tail_exceeds_bounded_cap)` followed by
  `graph has active lease(s) without callback: planner-s-01`.

## Final validation

- Whole-repository gate: `5,481 passed, 4 skipped`.
- Immutable projection closure: `751 passed` with slow/performance coverage.
- Focused Wave 1/cache/file-state/routine validation: `157 passed`; full graph-runner E2E: `24 passed`.
- Ruff, Pyright, signal-routing, and graph-projection boundary checks passed.
- As-of-Wave-1 validation: both replacement runs used `codex_server`,
  `gpt-5.6-luna`, high reasoning, managed restrictions, REST callbacks, and
  snapshots carrying a 50,000-entry / 1-GiB scan budget. Those v1 fields remain
  for replay compatibility; current recognized cache-root descendants are
  uninspected and consume none of that budget.
