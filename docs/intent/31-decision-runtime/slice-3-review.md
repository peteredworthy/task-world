# Slice 3 review, September 12, 2026

Verdict: review corrected validation defects; slice 3 still has an
unresolved rejected-plan recovery contract. Slice 4 must wait for that handoff to be implemented and
verified. This review supersedes the completion claim in the 3F ledger without
rewriting its historical test results.

The user authorized review and a commit. Work stays in the
`recovery-stabilization` worktree. Existing recovery evidence and slices 1–3
are preserved; validation uses disposable Git/SQLite and scripted transports.
No live server, paid model execution, activation or historical resume is part
of this review.

## Starting evidence

All six source/test hashes in the 3F ledger matched the starting worktree.
Of the 49 files in the earlier recovery validation manifest, 28 still matched;
the remaining 21 contain later slice changes. The starting hashes for current
source, tests and decision-runtime documents are retained in
`slice-3-review-starting-hashes.json`. Previous unchanged focused results were
read alongside the tests rather than rerun as new evidence.

## Requirements and findings

| Requirement | Review finding | Status |
|---|---|---|
| 3A: one generated schema through prompts and both submit catalogs | Canonical schema consumers and connected MCP validation are present. | Passed independent review |
| 3B: bounded brief, frozen authority, independent judgment | Explicit planner path preserves the frozen request. No routine policy authorizes deterministic bypass. | Supported path passed; bypass policy remains unspecified |
| 3C: read-only discovery and exact independent verifier | Production tests publish the exact semantic plan, use a separate verifier execution and reject post-answer mutation. | Passed independent review |
| 3D: conservative amendments | Repeating the current objective or scope created an identical amendment and 12 unnecessary operations. The compiler now rejects unchanged plans; scope subsets retain canonical ordering. | Corrected with behavior-first regression coverage |
| 3E: evidence aliases in all branches | `no_gap` accepted `e999` despite its absence from the protected evidence map. It now rejects unknown aliases. | Corrected with behavior-first regression coverage |
| 3E: complete failed-check evidence | One failed report citing two failed checks was rejected as multiple failure anchors. All related checks now retain deterministic identity and topology bindings under one report. | Corrected; three-check patch accepted through the command boundary |
| 3E: exact staleness | A new unrelated output invalidated a correction through a global position check. Staleness now uses relevant records and their authority identities, including requirement IDs/versions and producer nodes. | Corrected; unrelated tail accepted and changed bound authority rejected |
| 3F: joined supported transport paths | Prior Claude test checked registration then invoked a callback. The joined harness now submits through registered ASGI/SSE JSON-RPC, checks exact failed-report handoff, fresh contexts, route removal and finalized ownership. | Additional production transport proof passed |
| 3E/3F: rejected plan to correction | Current resolver requires a declared batch/horizon and a passed baseline-plan verifier. A rejected initial plan provides neither. | Required architectural gap; blocks slice 3 completion |

## Rejected-plan contract gap

`graph/macros.py` generates a plan-verification failure gap planner during
initial discovery construction. `resolve_correction_decision_context` in
`graph/decisions.py` interprets every gap as failed work against a verified
batch. It requires a selected batch and a passing verifier of the baseline
plan, so it cannot interpret the generated initial-plan rejection. The earlier
3F correction test seeds a failed batch after accepted plan verification;
the joined failed-plan test stops after checking that no successor dispatches.
The revised harness also schedules the generated gap and checks its exact
failed-report binding. Resolving that node remains blocked.

Reproduce from this worktree:

```text
PYTHONPATH=. UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  docs/intent/31-decision-runtime/reproduce-rejected-plan-gap.py
# exit 1
# DecisionContractResolutionError: correction scope is outside the accepted baseline plan
```

This standalone diagnostic runs initial planning, discovery, failed independent
plan verification and generated gap scheduling on disposable Git/SQLite. It
then reloads the durable projection and attempts correction resolution. It is
kept outside the test suite as an explicit unresolved-contract reproducer;
no required regression was skipped or marked as passing.

The minimal architectural alternative is a phase-specific plan-repair context
within the existing graph decision owner: bind the exact rejected plan, its
failed independent report, frozen requirements/check policy and last accepted
plan when one exists. A plan revision must produce a new semantic plan for
independent verification before any successor can proceed. Define permitted
correction dispositions and preservation rules for initial-plan rejection
separately from rejection of an amendment to an accepted plan. Keep the
existing submission/witness/finalization transaction; do not invent a passing
verification record, batch identity or second protocol to reuse the batch
resolver. This contract must be settled before implementing the affected path,
as required by the shared execution rules in `implementation.md`.

## Slice 4 handoff

`implementation.md` now records the prerequisite and concrete lessons:
dispatch-frozen authority, ordered scoped aliases, separate verifier roles,
semantic validation, multiple mandatory-check failures, real transport calls,
continued rejection-path execution and permanent record/projection inventories.
The remaining gap is required slice 3 behavior, not reassigned to slice 4.

## Corrections and validation

Review changed `graph/decisions.py`, the gap/amendment unit tests, the joined
runtime integration test, and this document package. Existing graph macro,
staging, finalization and transport owners are reused; no new production
protocol or registry was added. Historical recovery artifacts retain their
starting hashes. Final reviewed source/test hashes are in
`slice-3-review-final-hashes.json`.

The behavior-first pass demonstrated unknown evidence and unchanged amendments
being accepted, multiple related checks being rejected, and unrelated graph
movement being treated as stale. Its initial focused run then passed:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -n 0 \
  tests/unit/test_gap_correction_decision.py \
  tests/unit/test_successor_amendment_decision.py --tb=short
# 37 passed in 2.22s
```

The complete joined runtime integration file passed 19 tests in 87.56s.
After adding exact failed-report binding and gap scheduling assertions, the two
affected failed-plan cases passed in 11.51s. Ruff and focused Pyright passed.
These are deterministic transport and lifecycle results, not provider-model
reliability evidence. The Codex joined harness uses an injected runner; existing
Codex ingress tests separately cover its transport boundary.

Fresh independent review also found a scope-order-only amendment that escaped
the initial no-op check. The follow-up preserves original scope order when
applying a subset and adds a regression before accepting the correction.
It also found that correction read sets omitted requirement IDs/versions and
producer identities used by authority-change events. The correction follows
the batch compiler's authority expansion; a production dispatch regression
checks both bound requirement revision and unrelated revision before staging.
Before the fix, the bound-revision case failed later during consequence
validation instead of producing the required stale-authority rejection; this
reproducer did not show incorrect effects being committed.

After both follow-ups, the same two-file unit command passed 40 tests in 2.10s;
Ruff formatting and checks passed for the three affected files. Fresh
independent validation inspected the corrected authority expansion, scope
normalization and real MCP transport proof. It found no further blocker to
committing this checkpoint. The initial and correction authority cases passed
four tests in 7.53s; after strengthening the correction assertions to require
unchanged complete node/record sets, those two cases passed in 4.66s. Ruff and
focused Pyright passed. The rejected-plan contract remains unresolved.

## First commit gate and corrections

The first unmodified commit hook attempt is retained in
`slice-3-review-gate-attempt-1.log`. Pyright, module imports, signal routing and
both UI checks passed. The projection boundary hook found three private storage
reads in newly tracked tests. Its earlier runs only scanned `git ls-files` and
had missed these untracked files. Tests now use public node queries and compare
complete serialized projection state for the no-mutation assertion. The checker
passes with the new files included in the index. Slice 4 instructions now call
out this coverage limitation.
An intermediate direct `model_dump` assertion failed eight cases because it
does not encode the projection's frozen maps. Using the existing public
`projection_to_checkpoint` codec fixed the assertion; the successor test file
then passed all 28 cases in 1.52s. The initial-planning file passed its 12 cases.

Gitleaks classified ten source-manifest entries as credentials. All ten values
equal the SHA-256 computed from `tests/unit/test_api_runs_validation.py`:
`600b8b878da616b3cf5685ea75ca28fc36c5d6b57dc5fb7aafe7b972730d7af4`.
The existing `.gitleaks.toml` non-secret classification now recognizes only that
exact filename/digest line. The historical evidence bytes remain unchanged.
Scanner probes accept that pair but still reject a different value under the
same key and the same value under `api_key`; the full secret hook stays enabled.

The test hook reached 6,272 passes and five skips while its remaining worker
spent several minutes expanding representations in the oversized-discovery
integration case. A one-second host sample captured that activity; the exact
worker was interrupted so the already-failed gate could drain. That attempt
therefore records one interrupted test, not a passing full suite. The isolated
case subsequently passed with normal assertion handling in 16.20s. The entire
unmodified integration file then passed seven tests in 370.38s under one xdist
worker, including its costly replay checks. No behavioral defect was reproduced
and no assertion or timeout was changed for that case.

All edits stop before retrying the unmodified commit hooks. The final commit ID
and gate result are reported in the user handoff; this ledger is sealed before
the test hook to avoid invalidating its source state.

## Second commit gate: collector exit race

The second attempt, retained in `slice-3-review-gate-attempt-2.log`, passed every
non-test hook. Pytest reported 6,265 passed, five skipped and one failure:
`test_relaunch_reclaims_child_orphaned_by_supervisor_sigkill[2]`. Its replacement
supervisor aborted after reclaiming the stale child because a collector identity
inspection returned macOS `AccessDenied` immediately after verified SIGTERM.
The failing disposable lifecycle and supervisor state are preserved in the
adjacent `slice-3-review-gate-2-supervisor-*` files; starting hashes for the
affected supervisor source/tests are in `slice-3-review-gate-2-starting-hashes.json`.

The repair must tolerate unavailable observations only within the existing
post-signal grace period. It must still prove exit before reporting success,
reject changed identity and revalidate identity before any additional signal.
Persistent inspection failure must remain a refusal. This gate finding is
handled separately from the decision-planning contract gap.

The implemented fix distinguishes unavailable inspection from changed identity
and retries only unavailable observations inside the existing post-signal
deadlines. Identity validation before SIGTERM/SIGKILL and mismatch refusal are
unchanged. Six real-process tests with an injected inspector cover temporary
and persistent loss after both signals and refusal before signaling. Integration
failures now retain subprocess output and bounded state/lifecycle diagnostics.

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -n 0 \
  tests/unit/test_server_supervisor.py \
  tests/integration/test_server_supervisor_process.py -k 'reclaim or relaunch'
# 20 passed, 29 deselected in 31.95s
```

This includes three actual supervisor orphan-recovery runs and existing
identity-change refusals. Ruff formatting/checks passed. Fresh independent
review approved the bounded behavior and preserved signal authority. No test
timeout, assertion, hook or recovery ownership check was disabled.
