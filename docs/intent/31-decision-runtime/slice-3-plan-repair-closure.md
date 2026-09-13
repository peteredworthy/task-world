# Slice 3 rejected-plan repair closure

Follow-up to `slice-3-review.md`, authorized September 12, 2026. Starting commit:
`2ba1513f1`. Work uses disposable repositories, SQLite and scripted runners.
Historical review evidence remains unchanged; this ledger records the subsequent
closure. A fresh builder implements the repair and a separate validator checks
its behavior through production dispatch.

| ID | Required behavior and acceptance criterion | Status | Evidence / remaining proof |
| --- | --- | --- | --- |
| R1 | A rejected initial plan enters correction with the exact rejected plan, failed independent report and frozen requirements/check policy, without a fabricated accepted baseline or batch. | Validated | Standalone production diagnostic now passes the complete repeated-repair handoff. |
| R2 | A rejected amendment retains the last accepted plan as preservation authority and distinguishes it from the rejected proposal. | Validated | Later-horizon command acceptance, exact successor resolution and joined amendment repair passed. |
| R3 | Applicable correction dispositions preserve authority; repair publishes a new semantic plan and requires independent verification before successor dispatch. | Validated | Phase-specific contract and rejection tests; new verifier gates every replacement. |
| R4 | Stale authority, invalid evidence, cancellation, duplicate submission and failed execution cannot publish unauthorized effects. | Validated | Exact lineage/read-set tests, both-transport mutation rejection and shared transaction regressions passed. |
| R5 | Joined rejected-plan → correction → independent verification → successor works through Codex and Claude execution submission paths, with fresh contexts and released ownership/routes. | Validated | Both transport paths execute repeated repair through finalized successor; independent durable-state proof recorded below. |
| R6 | Existing batch correction, planning and legacy verification remain compatible; slice 4 lessons reflect the repaired contract. | Validated | Existing units/runtime regressions passed; documentation updated; final commit gate pending. |

## Pass 1

Builder must first demonstrate the expected failing behavior, then implement the
full repair using canonical CorrectionDecision and the existing staging,
witness, finalization and graph macro boundaries. The change must not activate
slice 4 typed verification or introduce a second submission protocol.

Baseline before implementation: gap-correction and successor-amendment unit
files passed all 40 tests in 8.68 seconds (`uv run --no-sync pytest -n 0`, with
`UV_CACHE_DIR=/tmp/orchestrator-recovery-uv`). The standalone rejected-plan
handoff remains the expected failing product path.

Independent validation must also inspect repeated repair rejection, unambiguous
plan lineage, completed-prefix preservation, and whether each bound requirement
and policy remains in the decision read set. A passed repair verifier must refer
to the newly published plan; an old passed report cannot authorize it.

Builder progress (pending independent validation): the joined initial rejection
path passes for both runner variants, including rejection of the first repair,
a second repair, a fresh passing plan verifier and an executed/finalized
successor. The real submission exposed an additional defect: generated gap
planners lacked the optional semantic-artifact output that unit fixtures added
by hand. The existing macro binding owner now declares that output. Later
amendment verification also retains its planning horizon, and semantic amendment
provenance retains the exact prior-batch report.

## Builder handoff and parent checks

The builder completed the repair within `graph/decisions.py`, `graph/macros.py`
and `graph/_commands.py`. The full joined sequence additionally exposed missing
horizon stamping on amendment verifiers/failure gaps and stale remaining-horizon
stamping for gap-authored amendments. Both are corrected in the existing owners.
An extended fixture lacked routine cache-authority metadata; repairing that
fixture enabled checkpoint round-trip checks without changing checkpoint policy.

Current focused evidence:

- Existing gap and successor amendment unit files: 40 passed.
- New rejected-plan correction unit file: 12 passed, including later-horizon
  command acceptance and exact repaired successor resolution.
- Full decision-runtime integration file: 23 passed, including both submission
  transports, repeated initial rejection, amendment repair through successor,
  post-answer mutation rejection and shared cancellation/restart cases.
- Ruff and focused Pyright passed. The permanent graph boundary checker passed
  with the new unit file staged, so it was included in the scan.

The combined builder run recorded 74 passes and one fixture-position failure;
the corrected new unit file then passed all 12 cases. The parent reran the
original standalone diagnostic after updating its final inspection to select
completed corrections rather than a dormant recovery node:

```text
PYTHONPATH=. UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  docs/intent/31-decision-runtime/reproduce-rejected-plan-gap.py
# exit 0
# Passed: rejected plan → repeated repair → independent verification → successor
```

This executes production controller/dispatch on disposable Git/SQLite and
reloads the durable projection. It asserts two completed corrections with no
fabricated selected batch or passing baseline report. The joined harness checks
fresh execution identities, exact replacement plan/report bindings, finalized
attempts, released leases and removed Claude MCP routes. Codex uses an injected
runner; this proves deterministic runtime behavior, not provider reliability.

## Independent validation

A separate validator exercised Claude's registered ASGI/SSE MCP path and
inspected reloaded durable state: three semantic plans linked by explicit
supersession; failed, failed and passed reports bound to their respective plans;
two completed initial-plan corrections without a baseline or selected batch;
one completed successor bound to the final passing report; finalized attempts
and no active leases. The 12 focused lineage/command-boundary tests also passed
independently in 1.08 seconds.

Validation requested one additional authority correction. Report acceptance
allows transitive evidence closure, so an ancestor appearing in a passing
report's evaluated IDs is insufficient to establish direct plan authority.
The ancestor lookup must additionally require that verifier's exact semantic
input to be the ancestor plan. Builder correction and independent recheck are
pending; this entry does not claim final validation.


## Closure verdict

R1–R6 passed independent validation. The ancestor correction requires the
passing verifier's single semantic input to equal the ancestor record. Two
behavior-first regressions demonstrated false ambiguity and false authorization
before this correction; both now pass. The validator independently reran the
updated 14-test lineage suite and reviewed the exact predicate. The builder's
final run passed 19 tests (14 authority tests and five affected joined cases)
in 70.86 seconds; Ruff and focused Pyright passed.

No actionable finding remains. The generated initial-plan and rejected-amendment
paths now execute correction, independent plan verification and successor
handoff. Slice 4 guidance includes the discovered output-port, horizon,
record-admission and direct-report-binding lessons. Legacy verification remains
active; no typed slice 4 verifier or live/provider qualification is claimed.

This ledger is sealed before the unmodified commit hooks. The final commit and
hook outcome are reported in the user handoff; a failed gate must be corrected
before committing and is not waived by this verdict.
