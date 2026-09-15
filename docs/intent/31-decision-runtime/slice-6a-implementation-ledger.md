# Slice 6A implementation ledger

> Historical implementation pass. The September 15 integrated review found
> required gaps; [the final closure ledger](slice-6f-final-review.md) supersedes
> the completion status and qualification claims below. Original evidence is preserved.

Status: validated. This slice extends qualification identity and deterministic
probe evidence only. It does not execute a model or activate decision-v1.

## Functional requirements

| ID | Requirement | Acceptance/evidence | Status | Remaining gap |
|---|---|---|---|---|
| S6A-1 | Qualification identity distinguishes legacy from decision-v1 and binds the generated implementation-plan schema plus compiler contract. | `ReliablePlanContractIdentity` validates legacy omission/round-trip and the exact generated decision-v1 schema/compiler identity; mismatches fail closed in manifest, receipt, authority facts, and comparison artifacts. | validated | None. |
| S6A-2 | Existing legacy qualification semantics and replay remain valid. | Historical legacy manifest hashes intentionally exclude the newly added identity; focused legacy qualification, authorization, replay, and lifecycle tests pass. | validated | None. |
| S6A-3 | The current sequential product-path infrastructure can produce separate deterministic decision-v1 qualification cases/results. | The existing `run_reliable_plan_product_path_scenarios` runner accepts a decision-v1 manifest and emits separately bound receipt/qualification identity; the slow product-path test passes with no model transport. | validated | Full joined decision-v1 planning remains Slice 6B. |
| S6A-4 | Recovery probes preserve old source-bound evidence while recording new-contract identity separately. | Deterministic lifecycle and successor probe result models record the legacy identity; successor replay preserves old missing-field compatibility and validates the identity when present. Historical result files were not rewritten. | validated | New-contract runtime lifecycle cases remain Slice 6B. |

## Baseline

Baseline was captured before implementation edits in
`/Users/peter/code/task-world/worktrees/recovery-stabilization`.

- Worktree status: clean before this ledger was added.
- Baseline focused command: `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_reliable_plan_evaluation.py tests/integration/test_recovery_deterministic_lifecycle.py --override-ini='addopts=' --tb=short` — 7 passed in 19.37s.
- No model evaluation, live server, activation, or paid probe is authorized.

## Decisions

- Legacy serialized manifests and receipts omit the new identity and decode as
  the legacy interaction. This preserves historical replay.
- Decision-v1 qualification binds the generated built-in implementation-plan
  schema (`decision_plan_schema`) and `DECISION_COMPILER_CONTRACT_VERSION`.
- Existing source-bound result JSON under `docs/reviews/` is historical evidence
  and will not be rewritten. New deterministic results use separate metadata.

## Changed files and source hashes

The starting hash is the clean `HEAD` file hash immediately before the slice
edits (the ledger itself is new and is not included below).

| File | Starting SHA-256 | Final SHA-256 |
|---|---|---|
| `src/orchestrator/graph/reliable_plan_evaluation.py` | `b33732664839ef9c6dd1f7279001ed1377b16a75588f2c06713f524673943a51` | `a3759b2c2055dd59b419877c0096bc32a8a953b5b4c811d457709d29973ab90b` |
| `src/orchestrator/graph/__init__.py` | `1ca1b823ff2cceb22ab1c39ba1ab37830c346e047cba73aaf592fb77a796afa7` | `8207bf2468136a4afa61582d0e4f7f601c2b9c5f4c36d90238faff4915fbda63` |
| `src/orchestrator/graph_runtime/reliable_plan_scenarios.py` | `4c79e4170dbad19ff5e64411b26d71a9637f4238b78250ff736696bd5f7f1abd` | `c35b898cdce3f6959758673c28a0ee300d624186a5f2228f04d472549c60d897` |
| `examples/recovery/deterministic_lifecycle.py` | `5eb69b221fc50c8758ba99744cf67272cfcd659abaaa049e150bfeed412b4be6` | `ad886caf89ab8e3c90fd961ea05740aa2d8234fbdce2fbb77e06ca6aa4a4eceb` |
| `examples/recovery/successor_planner_probe.py` | `82bbc9aaf99a6a8b766f6ebd018a78d245128ff6cd3bb7daa23c2b7a07347e50` | `533b9c1f091a933555f0551c449f637ebe5319c74bcdb4edbe2fa2312f8ba284` |
| `examples/recovery/replay_successor_probe.py` | `e3f2988987f0b80667b34eb7efcd1d75de5edfa3c67708be33ad40dfc129c94b` | `f073baa37d2431ebf94887c064c01d97d497eb6ffd88b48a5264038853b0c04c` |
| `tests/unit/test_reliable_plan_evaluation.py` | `7b73044a14a3133f297b507470cc31c7f55f75f2b2294aa9856f029865d0f3fe` | `256be4c1f541bc73e30dfdc002f58c681137b4eb8bed148fc3d495ce74973b00` |
| `tests/integration/test_reliable_plan_product_path_qualification.py` | `f64722e283221bfe0be121ef603624bbbd33f00f3caffc6bedbecb8f0ea5ac89` | `0b7f84b6b5799a44e083f2d7a50872b37bd965b2242c9a7cbe272f22b4611f89` |
| `tests/integration/test_recovery_deterministic_lifecycle.py` | `598059db0f388184fe52d0cc748bdd628c4e4b5e9a35b9b0907b649bb9cbc781` | `5039d6864e1ec1b00421618761323afc28c840d6be221e5c70b26a47dcb37716` |

## Validation evidence

- `tests/unit/test_reliable_plan_evaluation.py`: 11 passed.
- Focused compatibility set (unit evaluation, lifecycle, successor replay/probe,
  and qualification integration): 30 passed, 3 skipped in 89.29s.
- Decision-v1 product-path qualification: 1 passed in 3.96s; it used the same
  sequential SQLite/controller runner and no model transport.
- `examples/recovery/deterministic_lifecycle.py`: passed; exact
  `stage3-smoke.txt` candidate, clean checkout, seven finalized executions,
  zero active leases/processes/outbox entries.
- Graph projection boundary check: passed (`files_checked=254`).
- Ruff check/format and focused Pyright: passed with zero diagnostics.

No live server, activation, paid model execution, historical result rewrite, or
commit was performed. Decision-v1 joined planning/execution remains out of
scope for this slice and is the next Slice 6B target.

## Validation log

To be filled with exact commands, results, source hashes, independent review,
and remaining concerns before handoff.
