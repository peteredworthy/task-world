# Slice 4C implementation ledger

Status: implemented and independently self-reviewed. No live server, live
database/history operation, paid execution, activation, historical resume, or
commit was performed. The worktree already contained the reviewed Slice 4A
and 4B changes; those changes were preserved.

| ID | Required behavior | Acceptance evidence | Status | Remaining gap |
|---|---|---|---|---|
| S4C-1 | A decision-v1 worker submits one typed `WorkResult` answer with `ready` or `blocked`. | Pure compiler/schema tests plus the product-real worker dispatch test cover both branches. `ready` completes only after trusted terminal closure; `blocked` records the blocker and fails the worker. | complete | None identified. |
| S4C-2 | Runtime owns candidate, checks, file-state snapshots, commits, and completion. | Disposable Git/SQLite dispatch changes a real checkout, stages a snapshot, runs the existing worker submission quality gate, finalizes one callback, and proves the candidate/file-state records are runtime-created and committed. | complete | The broader repository gate is deferred to the final recovery slice as required by the worktree instructions. |
| S4C-3 | Required custom semantic products remain model-authored sibling outputs. | Product-real `semantic_artifact` output uses the declared `decision-plan` schema and is preserved with the runtime-owned decision, candidate, and file-state records. | complete | None identified. |
| S4C-4 | Missing semantic outputs and invalid authored ports fail closed. | Product-real missing-required-output case receives the normal `submission_format_rejected` acknowledgement, creates `runner_recovery_requested`, and publishes no decision, semantic product, candidate, or file-state record. | complete | Recovery application itself remains owned by the existing recovery consumer. |
| S4C-5 | A worker cannot announce the same result through a second model pass. | The worker answer is compiled once at submit and rebuilt from durable staged facts during finalization; terminal closure is requested from the runner after the first accepted submission. | complete | None identified. |

## Implementation evidence

- Added the graph-owned `WorkResult` discriminated schema, generated answer
  schema/hash, frozen worker context, canonical compiler, and public exports.
- Activated `work_result` for effectful and corrective workers while retaining
  candidate and `FileStateRecord` output declarations as controller-owned
  ports. The worker prompt describes the typed result contract without moving
  lifecycle ownership into the model.
- Extended the shared decision-v1 submission contract to include declared
  `SemanticArtifact` siblings. Authored semantic content is validated against
  the graph-declared schema and cannot author trusted record identity fields.
- Stage and finalization use transient controller-owned output records. The
  existing callback command remains the sole authority for lease, snapshot,
  output-record, node-state, completion, and event/outbox effects.
- Ready results run the existing submission quality gate against the exact
  staged candidate before staging. Blocked results do not create candidate or
  file-state records, and retain the typed blocker reason on the failed state
  transition.

## Validation evidence

```text
Focused Slice 4C product-real worker cases:
4 passed, 26 deselected in 7.42s

Focused worker + submission-quality-gate regression cases:
5 passed, 8 deselected in 9.30s

Focused decision unit/dispatch/integration suite:
229 passed, 10 warnings in 143.04s

Scoped Ruff:
All checks passed!

Scoped Pyright:
0 errors, 0 warnings, 0 informations

Graph projection boundary checker:
passed

git diff --check:
clean
```

The pre-Slice-4C baseline for the broader decision/product-path selection was
`222 passed, 10 warnings, 7 errors in 136.87s`. All seven errors were the known
pre-existing product-qualification final-audit conflict:
`candidate_record_ids does not match bound records: ['batch-report',
'candidate-batch'] != ['candidate-batch']`. The focused Slice 4C suite does not
reproduce that unrelated baseline failure.

## Slice 4C source hashes

For files already recorded by the preceding Slice 4B ledger, the starting
hash is its final hash. `command_models.py` and `contracts.py` were not listed
as Slice 4B final files, so their starting hashes use the current worktree's
HEAD content before this slice's edits. Final hashes were computed after the
last validation run.

| File | Starting SHA-256 | Final SHA-256 |
|---|---|---|
| `src/orchestrator/graph/__init__.py` | `9ceecf81c3e0cdbb59b7e22905822197c1da30f004ef657efb79eb61861af267` | `8be5e947448b47c314d84ad0d1cf366401ae8e7c5dc7dc46bf4abf5e2612dc68` |
| `src/orchestrator/graph/command_models.py` | `7b33d444d5b2285df16adbaac579fcc252b23c2c49b618a690d8f1e6678b09c5` | `4f5650b7e1779008b747db52225c73454d56c6fb2b890c8bee1b072541ba7ae6` |
| `src/orchestrator/graph/commands/boundary.py` | `01f7003a92c8ba29a3d0d4fa79ed59084142c41325f44f367c6a3fa07b8ad9ac` | `5db438336fd2f6fc0a2e15d4474ff92ef26552172a3d9fec0ee02845d83bd616` |
| `src/orchestrator/graph/contracts.py` | `a52fd09b9cf88ecc53f90626bd97e9b09db56b045123efe485e9a15c6d4d9c91` | `4fd4c55aa08cc8818d0901fda77297e1035351fa6ff834d165b3cf9db94dccd3` |
| `src/orchestrator/graph/decisions.py` | `64d9e3536db75c7c2c89d8694b0f05f6b16e4d81381217f35f9ed42778627532` | `936a57a081522358e280ff004def27c52e2da109c11665d3423dd9dd5ef88302` |
| `src/orchestrator/graph/macros.py` | `c25864a0b9f457345918d4fc23a4ef87e04eaad484596e2c4acfb41eee9538e3` | `7b2d4f18a3f6c95fc20c1394828a9b146269ee6d894d1ac5cd9f818775905cbc` |
| `src/orchestrator/graph/models.py` | `7f88dfc949ae68e965076d940e919fc3ce1ad3bf0f57dafe1adadd5beaa6aad8` | `58e18a9147aa7cab24f71ae61b2ec18ce7f183bf22f51946251f8bf6d59e38eb` |
| `src/orchestrator/graph_runtime/dispatch.py` | `efd3a4cb2055ad60a5dbc27f64a9fef738a582c224b9d6fe92b0399a53c94aa3` | `c740ea3e70f5413a12094c639e1ca5cde148d598e88b79b7c5c683008beb8b54` |
| `src/orchestrator/graph_runtime/prompts.py` | `7ed44ffc9489ea63ff09d3d3c307e0b08df27425c3fec812713f02539e6cca7e` | `846d5555e7e0421da57409eb4bb438dcebac1990f5e52674b6f6eca489622b97` |
| `tests/integration/test_graph_decision_runtime.py` | `b96733c28faa8a82326028e75b9615eaf0807dcb3b7c002cbe85a189b2477565` | `3a8766fc99ccf0f2113ee0711b003790e80466d3640a73dd2dea280a102ed4f1` |
| `tests/unit/test_graph_decisions.py` | `679524ea57cdd317afeceee875880f8a30d3f8bddd113173310d38bda5aa9539` | `8bbf36f3db3bc9c2e18181d5ea9bc669eb0d86c7add9bbf1379f635e4890333f` |

## Independent review and remaining concerns

Read-only self-review checked the Slice 4C diff for duplicate runtime paths,
transient command fields leaking into strict event payloads, public graph
imports, debug output, and whitespace errors. The boundary/type/lint checks
were then rerun successfully. The only known repository-level residual is the
pre-existing seven-case final-audit qualification conflict recorded above; no
Slice 4C-specific blocking concern remains.
