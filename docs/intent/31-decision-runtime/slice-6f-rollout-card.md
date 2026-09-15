# Decision-v1 rollout and evaluation card

## Release scope

New routines may select `agent_interaction_contract: decision-v1`. Omission
preserves legacy interpretation; an existing run keeps its frozen snapshot.
Supported graph runners remain Codex Server and Claude CLI with scoped graph
MCP. OpenHands and CLI Codex graph execution remain unsupported.

This change does not activate a run, convert historical state, select a different
runner/model, or authorize model evaluation. The operator retains those choices.

## Required deterministic qualification

Use the public `run_reliable_plan_joined_cases` entry point and the canonical
decision-v1 joined manifest. It executes disposable Git/SQLite cases over the
existing production graph driver. Completion requires exact committed products,
clean checkouts, independent verification, and drained ownership/outbox state.
The original API-start slice 6B success tests are retained as separate regression
coverage. The legacy lifecycle remains a compatibility control.

| Evaluation case | Deterministic case | Expected product/outcome |
|---|---|---|
| single-batch | single-batch | Only `single.txt`, bytes `single-ok\n`, mode 100644; completed |
| dependent-batches | dependent-batches | `base.txt` = `base-ok\n`, then `dependent.txt` = `dependent-ok\n`; mode 100644; completed after independent dependency acceptance |
| plan-amendment | plan-amendment | Only `amended.txt` = `amended-ok\n`, mode 100644; replacement plan independently verified before work |
| correction | correction | Only `corrected.txt` = `corrected-ok\n`, mode 100644; failed candidate/report retained, bounded correction independently verified |
| verifier-negative | defective-verifier | Intended candidate-check or verification/answer failure; no accepted completion. An unrelated provider outage does not qualify this case. |

The separate smoke requires only `stage3-smoke.txt`, exact bytes
`stage3-smoke-ok\n`, mode 100644 and a clean checkout. Blocker, defective-candidate,
cancellation/restart and compatibility cases must pass their own cause and
ownership checks. Scripted results establish deterministic infrastructure
behavior, not real-model reliability.

## Prepared paid evaluation, not executed

The exact machine-readable card is
[slice-6e-evaluation-manifest.json](slice-6e-evaluation-manifest.json).
The operator must authorize that manifest and its budget before execution.

| Limit | Per phase/node | Per joined case | Five-case batch |
|---|---:|---:|---:|
| Actual runner starts | 1 | 16 | 80 |
| Received rejected answers | 2 | 32 | 160 |
| Wall time, seconds | 180 | 2,880 | 14,400 |

The manifest assigns Sol to the planner and verifiers, and Luna to discovery,
implementation/correction workers and successors, using Codex Server. These are
prepared assignments; this implementation task has made no paid calls.

Stop on false acceptance, unexpected outcome, missing required evidence or budget
exhaustion. Automatic retries and model/runner fallback are disabled. Preserve
partial reports and failed attempts. Missing telemetry remains unknown; missing
wall-time evidence cannot prove a bounded run. Usage and cost remain unknown when
the provider does not report them. Reports retain raw counts and fixed
denominators without inferring a reliability percentage from this small cohort.

## Review and gate

The [integrated review ledger](slice-6f-final-review.md) records initial defects,
closure evidence, compatibility checks and final gate results. Commit and merge
require successful unmodified repository hooks on the reviewed source.
