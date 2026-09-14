# Slice 4 qualification compatibility gap

Builder status: implementation, focused validation, and integrated sequential
product validation complete. Independent review remains with the orchestrator.

This pass closes the final-audit qualification conflict reported in the Slice
4C ledger. The cause was a Slice 4B compatibility regression: the final-audit
evidence query selected the dynamic-acceptance candidate for every audit,
including legacy callbacks whose contract still uses the historical transitive
candidate list. The existing graph-owned decision applicability resolver now
selects the narrow authority only for `verification_decision` nodes. Prompt
citations and callback validation use the same selection. The decision-v1
query/compiler, old scenario records, and exact citation checks are unchanged.

| Requirement | Acceptance criterion | Product-real proof | Regression evidence | Status |
|---|---|---|---|---|
| S4A-5 / S4B-6 legacy compatibility | A legacy final audit retains its ordered transitive candidate/file-state citations, including when final acceptance is bound. | The unchanged all-ten qualification scenario runner accepts scenario 8's legacy callback and passes final reconciliation; the real ASGI qualification API issues and consumes the resulting grant. | New two-batch prompt parameter reproduces the failure first; full qualification file passes. | Implemented, independently reviewable |
| S4B-2 final-audit authority | Decision-v1 final audit still selects the exact final-acceptance candidate and retains prior-batch evidence. | Existing typed final-audit compiler boundary remains unchanged. | Three focused final-audit decision tests pass. | Preserved; integrated review pending |
| Qualification successor rejection | A raw copied successor cannot advance without its complete bounded batch. | Real qualification API/controller test rejects the patch and proves the new successor is absent from the projection. | Updated obsolete expected reason to the current atomic-region rejection. | Implemented, independently reviewable |

No scenario fixture was rewritten to conceal the compatibility regression. No
new authority path, schema, model call, database migration, or legacy decoder
was introduced. No full repository gate, live service operation, or commit was
performed. All commands ran inside the prescribed recovery worktree with
disposable test state.

## Tests-first evidence

Commands below ran from
`/Users/peter/code/task-world/worktrees/recovery-stabilization`.

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/integration/test_reliable_plan_product_path_qualification.py --override-ini='addopts='
7 passed, 2 skipped in 18.78s (slow qualification excluded)

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 --run-slow tests/integration/test_reliable_plan_product_path_qualification.py -k product_path_runner --override-ini='addopts='
1 failed, 8 deselected in 3.25s
Expected failure: scenario 8 callback rejects candidate_record_ids
['batch-report', 'candidate-batch'] != ['candidate-batch'].

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_graph_verifier_prompt.py -k final_audit --override-ini='addopts='
1 failed, 1 passed, 4 deselected in 0.33s
Expected new-regression failure: legacy two-batch candidate list collapsed
to candidate-batch-2 when dynamic_feature_acceptance is bound.
```

The broader product selection exposed one subsequent stale assertion in the
qualification API test. Isolated diagnostic runs established that the patch was
correctly rejected, with reason `patch copied-horizon-two reliable-plan horizon
must atomically create exactly one complete effectful batch region`. The test
previously expected a different message for the same rejected incomplete patch.
The fix also asserts that the rejected successor was not materialized.

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 --run-slow tests/integration/test_reliable_plan_product_path_qualification.py -k run_api_consumes --override-ini='addopts='
1 failed, 8 deselected in 4.64s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 --run-slow tests/integration/test_reliable_plan_product_path_qualification.py -k run_api_consumes --override-ini='addopts=' --tb=short
Two diagnostic reruns: 1 failed, 8 deselected in 4.74s / 4.93s.
The latter exposed the exact rejection reason above.
```

## Passing focused validation

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 --run-slow tests/integration/test_reliable_plan_product_path_qualification.py -k product_path_runner --override-ini='addopts='
1 passed, 8 deselected in 3.91s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 --run-slow tests/integration/test_reliable_plan_product_path_qualification.py --override-ini='addopts='
9 passed in 26.91s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_graph_decisions.py -k final_audit --override-ini='addopts='
3 passed, 93 deselected in 0.39s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check src/orchestrator/graph/_commands.py src/orchestrator/graph_runtime/prompts.py tests/unit/test_graph_verifier_prompt.py tests/integration/test_reliable_plan_product_path_qualification.py
All checks passed!

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright src/orchestrator/graph/_commands.py src/orchestrator/graph_runtime/prompts.py tests/unit/test_graph_verifier_prompt.py
0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright tests/integration/test_reliable_plan_product_path_qualification.py
0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python scripts/check_graph_projection_boundaries.py
Exit 0

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format --check src/orchestrator/graph/_commands.py src/orchestrator/graph_runtime/prompts.py tests/unit/test_graph_verifier_prompt.py tests/integration/test_reliable_plan_product_path_qualification.py
Initial check requested formatting for the qualification assertion.
Final identical check: 4 files already formatted.

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format tests/integration/test_reliable_plan_product_path_qualification.py
1 file reformatted (assertion line wrapping only).

git diff --check
Exit 0
```

## Integrated selection

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 --run-slow tests/unit/test_graph_verifier_prompt.py tests/integration/test_reliable_plan_product_path_qualification.py tests/integration/test_graph_sequential_product_path.py --override-ini='addopts='
21 passed, 1 failed in 392.63s (0:06:32).
All seven sequential product tests and all six verifier prompt tests passed.
This run began before the qualification API assertion update, so its sole
recorded API assertion failure is superseded by the nine-test passing file above.
```

The seven former fixture errors are now passing production API/controller
scenarios, including two bounded horizons, corrective evidence, failed final
acceptance, environment recovery, cancellation, restart, and retry exhaustion.
No unchanged six-minute sequential run was repeated after the isolated assertion
fix because all seven cases already passed and that fix changes only the
qualification API test.

## Source hashes

Starting hashes were captured before this pass's edits; the qualification test
was unchanged from HEAD before its assertion update. All pre-existing Slice
4A-C edits are retained.

| File | Starting SHA-256 | Final SHA-256 |
|---|---|---|
| `src/orchestrator/graph/_commands.py` | `791ced0ee36e8406cdde4a630fea1aca6b687510ec8b6a42baf0d1b943721939` | `c79470611dea482afd55dbf006ecf1033205ea476046c0ba7d56ef4bacc29942` |
| `src/orchestrator/graph_runtime/prompts.py` | `846d5555e7e0421da57409eb4bb438dcebac1990f5e52674b6f6eca489622b97` | `b10acc8e8c3395b1c9499f9e54f6b4329e3b9f4d6de28422dcaba79455f6edf0` |
| `tests/unit/test_graph_verifier_prompt.py` | `479499439f9b0cbfede8f20e1cca40ef27999bc578df5be1021ac7fe7faf6fc7` | `0b69e6ae1ab23f4f41040fc31b7522628e7f5e4fec17f94bb469c4cf4416a7b8` |
| `tests/integration/test_reliable_plan_product_path_qualification.py` | `eb34788442cdf373c7db49d78fa26b145171107f495ed902a4af62dd33a033f8` | `f64722e283221bfe0be121ef603624bbbd33f00f3caffc6bedbecb8f0ea5ac89` |
