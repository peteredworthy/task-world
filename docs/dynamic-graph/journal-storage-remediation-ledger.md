# Journal and event-storage remediation ledger

This ledger tracks the seven functional fixes requested after diagnosing the
large local event database and overlapping JSONL journal. Existing operator
state is immutable for this work: validation uses temporary databases,
journals, and worktrees only.

| ID | Functional behavior | Acceptance criteria / invariant | Product-real usage proof required | Regression evidence required | Status | Remaining gap |
|---|---|---|---|---|---|---|
| J1 | Reconciliation understands overlapping sparse segments. | A position present in any discovered archive or the active journal is never appended again, irrespective of segment ordering or overlap. Missing SQL events are appended exactly once. | Temporary SQLite overlapping-sparse test drains twice and asserts unchanged active bytes and archive names. | `test_journal_drain_uses_union_of_overlapping_sparse_archives`; focused journal suite green. | Validated | None. |
| J2 | Rotation is idempotent for identical content. | Rotating bytes already archived under their content identity reuses the existing immutable archive and does not create `.1`, `.2`, etc.; distinct bytes with the same range remain separately preserved. | Rotation retry test observes one immutable archive for identical bytes; occupied invalid candidate still receives an ordinal. | `tests/unit/test_jsonl_rotation.py`; focused journal suite green. | Validated | None. |
| J3 | Normal startup reconciles only an unapplied journal tail. | A durable journal-delivery checkpoint prevents rescanning SQL position zero and all immutable archives on every restart; recovery after a simulated post-commit journal failure still drains every missing event. | Temporary DB/journal proof adopts legacy 1-2 against SQL 1-3 as `verified=0, tail=3, debt=3`, drains tail 4 without archive scanning, audits position 3, converges to verified/tail 4, and restarts with zero work. | 19 durability tests plus 15 rotation tests pass; v1/invalid and real fsync-failure retry cases included. | Validated | None. |
| F1 | Recognized cache directories are represented as bounded roots. | `.venv`, `node_modules`, and other policy-recognized cache trees do not produce one durable path record per descendant; tracked source under mixed roots and secret/repo-escape safety remain intact. | Isolated 1,500-file `node_modules` proof retains exactly the cache root, nested secret, and escaping symlink. | Large-cache proof and focused file-state/security suites pass. | Validated | None. |
| F2 | A file-state record stores each path fact once. | Canonical durable payload has one path inventory; `tracked`, `untracked`, `ignored`, `classifications`, and `residue` remain available as derived projections/API views where required. Historical payloads still replay. | Historical arrays normalize to a stable canonical `paths` dump; API records materialize compatibility collections only at response time and summaries count canonical paths once. | Updated model round-trip and raw rejected-path tests plus focused projection/file-state suites pass. | Validated | None. |
| F3 | One durable event owns an accepted file-state record. | Accepting file state writes its full payload once. Other graph semantics refer to its record/event identity and replay to the same projection. Historical paired events remain readable without double ownership. | Isolated real runner/dispatcher flow persists `file_state_accepted` and asserts no file-state `output_record_accepted`; historical reducer compatibility remains covered. | Focused dispatcher, command, projection, and file-state suites pass. | Validated | None. |
| F4 | Callback audit events do not copy large payloads. | Accepted, rejected, stale, conflict, and duplicate callback audit events retain bounded metadata, payload hash/size, and record IDs; payload bodies live only in canonical accepted records or content-addressed artifacts. Idempotency behavior is unchanged. | Isolated opt-in runner E2E resolves staged callback bodies through `FilesystemArtifactStore` across unsuccessful-result, boundary-mismatch, and restart recovery flows. Missing and corrupt CAS bodies each produce exactly one recovery request, no callback/finalization, and a completed managed restore. Historical inline staged payload replay remains separately asserted. | Full runner E2E file 23 passed; exact F4 proof set 6 passed; inferred nine-file remediation suite 422 passed; repository ruff and pyright pass. | Validated | None. |

## Baseline and validation log

- Baseline: `uv run pytest --run-slow -n 0 -m 'not e2e'` over the 11 focused
  journal, durability, file-state, callback, replay, and controller files:
  214 passed in 14.60s on 2026-08-11.
- Current implementation pass: J1-J3 and F2-F4 implemented as above; F1 existing
  bounded-root behavior retained and adapted to canonical path storage.
- Focused validation: `207 passed, 23 deselected`; graph commands `168 passed`;
  pyright `0 errors`; ruff green. The real runner integration pair reported
  `30 skipped` in this environment.
- Product-real proof: temporary SQLite journal operations and isolated graph
  runner persistence/restart/recovery flows complete without touching operator
  state.
- Broad quality gates: expanded remediation matrix `722 passed, 23 deselected`;
  full repository gate `5794 passed, 4 skipped` in 57.73s; ruff green; pyright
  `0 errors`.
- Independent validation pass 1: J1 and J2 passed exact temporary-file proofs;
  F3 passed single-owner command and historical paired replay. J3 failed because
  untrusted legacy adoption advanced a checkpoint across a missing SQL event.
  F1/F2 exposed stale compatibility assertions. F4 remains partial because
  `runner_submission_staged` owns the inline body.
- Validation safety incident: a temp-DB lifespan probe inherited the checkout's
  default worktree base and startup cleanup removed 11 run worktrees before it
  was interrupted. No database or `.orchestrator` history was touched. Further
  validation is restricted to isolated component paths; no app lifespan probes.
- Builder correction pass 2: J3 now uses a truthful v2 checkpoint with explicit
  legacy debt and bounded audit. F1-F3 have isolated product-path proofs. F4 is
  artifact-backed in the live runtime and indexed for retention; exact
  restart/missing/corrupt independent validation remains the only proof gap.
- Correction-pass evidence: pyright reported 0 errors; a combined isolated run
  reported 259 passed, and the broader graph/model/store set reported 588
  passed. No app lifespan or existing operator state was accessed.
- Builder pass 3 closed F4 with permanent isolated proofs. The three opt-in
  runner recovery cases now resolve staged callback bodies through the durable
  `payload_ref` using the public `FilesystemArtifactStore` read path and assert
  that new stage events contain no inline `payload`. Parameterized missing and
  corrupt CAS faults each produce one `runner_recovery_requested`, no
  `callback_accepted` or `runner_execution_finalized`, and one completed managed
  restore. A distinct historical replay assertion retains inline compatibility.
- Builder-pass-3 evidence: exact F4 set `6 passed in 10.91s`; full opt-in runner
  E2E file `23 passed in 46.36s`; inferred nine-file remediation suite
  `422 passed in 18.20s`; repository ruff green; pyright `0 errors`. Validation
  used only temporary databases, artifact roots, and git repositories; no app
  lifespan or existing database/journal was accessed.
- Stale-test correction: the manually persisted pre-tail checkpoint now uses
  the public compact events returned by `GraphEventStore.read_run_projection`,
  matching the production snapshot input shape. The exact four-case checkpoint
  proof passed, the full cache-authority durability file passed `23` tests,
  repository ruff passed, and pyright reported `0 errors`.
- Final gap cycle: the broad gate found seven serializer/policy compatibility
  regressions, all corrected while preserving compact new events and historical
  replay. A subsequent corpus case established that callback audit record IDs
  may name attempted outputs rejected before graph acceptance, so they are
  explicitly classified as external audit provenance rather than canonical
  record relations. The focused integrity/corpus proof passed `315` tests, and
  the clean full repository rerun passed `5794` with four credential-dependent
  skips.
