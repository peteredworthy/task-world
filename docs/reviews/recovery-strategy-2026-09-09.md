# Recovery strategy: restore delivery, then earn dynamic graph complexity

Decision: use the existing fixed legacy builder/check/verifier workflow as the
delivery path, with explicit operator acceptance for each task. The fresh Luna
baseline completed but exposed a verifier false positive; its correction is
the next trial below. Keep dynamic planning
experimental until it demonstrates a benefit on matched tasks. Preserve the
current implementation and run history; a repository-wide revert is the last
option, not the first recovery step.

This is a working recovery plan, not a claim that the system is repaired.

The original failed run has no safe supported command repair: resume cannot
change its immutable command, and paused repair requires replacement contract
parity. Preserve it as incident evidence and test a corrected binding in a new
run. Do not omit its required check or replace it with a different acceptance
meaning merely to make the graph finish.

## What the evidence says

| Evidence | Result | Implication |
|---|---|---|
| Run `d20ff4dd-9cd1-4f29-9df1-d344a0582907`, source `f6f2d07d690262eb715917f3d25b973b64486219`, worktree `r215` | Paused after 57m44s wall time; 7,141,617 input tokens including 6,678,400 cached, 60,250 output; 123 actions; 41m47s recorded model duration | An expensive live failure despite previous scripted qualification |
| Failed node `check-batch-2-cli-integration--a12aa709ed10615e-1`, graph positions 486–489 | `check command_definition requires non-empty argv or cmd`; bound to `dynamic_feature_hidden_oracle` while run configuration has `hidden_oracle_command: ""` | Invalid executable work was accepted, then discovered only after implementation |
| Unchanged `uv run python /private/tmp/qualification-20260907/task1_oracle.py` run independently in `r215` | Exit 0, `PASS: operator-owned JSONL acceptance checks` | The produced feature works under this oracle; graph completion and final independent verification remain unproven |
| Run `92bcd76c-be8c-426d-820f-8c635fb9425e` on earlier source | API says completed, 84m30s wall time, 4,894,364 input/output tokens | Dynamic execution can finish. This readback alone does not establish intervention-free qualification or acceptable economics |
| August 28 comparison in `docs/dynamic-graph/dogfood-reliable-plan-evaluation.md` | Both graph arms failed; fixed legacy arm completed in 476,686 ms recorded model duration | A simpler fallback already exists; confirm it on today's code and Luna before relying on it |
| New fixed Luna baseline `2a78847f-cc61-46db-b8f0-ce0203a9a85b` | Completed in 12m58s, all three grades A, 2,384,473 input/output tokens, 31 actions, mandatory commit hooks passed | The fixed execution path works; independent review nevertheless found a Unicode bug, so grades alone are insufficient |

Token counts include cached input and are not dollar estimates. Model price
rates are missing in retained run records. Compare wall time, actions, output,
cached and uncached input separately until monetary accounting is reliable.

## Sequence and stop rules

1. **Restore a usable delivery loop now.** Run the same small JSONL public
   contract on source `f6f2d07d...`, through the existing legacy execution mode,
   with Luna medium for builder and fresh verifier, the unchanged external
   oracle, and at most two attempts. Keep the default execution setting and
   existing graph runs unchanged. A passing result must include actual artifact
   inspection, oracle success, independent grades, and a terminal run state.
   The new embedded routine is an uncommitted experiment; retain its exact API
   request and source SHA. Commit a reviewed routine before making this the
   repeatable production default.
2. **Get useful feedback through that path.** After the baseline proves
   terminal completion, independent passing grades, inspected output, and
   unchanged oracle success, run one bounded Luna task that builds a read-only diagnostic
   utility from public API responses. It must expose the root failure,
   distinguish partial/missing evidence from health, and bound all requests.
   This both improves operation and tests whether the fallback can deliver a
   practical tool. Do not launch a five-run dynamic campaign into a known bug.
   If the baseline pauses or fails, retain the evidence and address that cause
   before launching another run. Use one attempt for the diagnostic task.
   Current outcome: the baseline completed but failed independent Unicode
   review. A one-attempt correction on its completed branch is now the next
   feedback run, requiring the unchanged oracle plus a supplemental Unicode
   oracle proven to fail on the seed. The diagnostic task remains conditional
   on verified correction. Record this as operator-discovered remediation, not
   autonomous error recovery or a clean benchmark success.
3. **Repair one connected graph failure chain.** Start with command-binding
   validation, deterministic-check failure handling, and root-cause readback
   described below. Establish the failing reproduction before the change and
   test across actual API acceptance, persistence/replay, dispatch, and failure
   handling. Do not add a new planning layer, generic recovery framework, or
   more agent-authored graph bookkeeping.
4. **Prove the repair live once.** On a reviewed, tested server revision, launch
   one unchanged two-batch dynamic JSONL trial using Luna workers/correction and
   a stronger planner/verifier only where the experiment explicitly calls for
   it. Verify final receipt, candidate identity, independent audit, completion,
   and zero manual graph repair. A plain operator oracle pass cannot substitute
   for these graph claims. Do not modify the old failed run to manufacture a
   clean qualification.
5. **Measure value on matched work.** Only after that success, compare three
   tasks from identical clean source snapshots: a small one-pass utility, a
   dependent two-batch change, and a task where new evidence genuinely changes
   the next action. Use identical public requirements, acceptance commands,
   model assignments where comparable, repository gates, and retry caps.
   Report the Luna-only baseline and any stronger graph roles separately;
   otherwise model quality confounds graph value. Alternate arm order and keep
   all failures in the results.

Operational limits for this recovery campaign: at most one active trial at a
time; at most two attempts for the baseline (one builder/check/verifier cycle
per attempt), one for the diagnostic task; inspect at 15 minutes and pause via API at
20 minutes if it is still active. Five minutes of agent output without a new
artifact, submitted candidate, check result, or verification is a diagnostic
trigger, not evidence of progress. The current API has no verified run-wide
budget field: these wall-time limits require an active operator/monitor and
must not be described as runtime-enforced configuration.

Limit initial graph engineering to two coherent repair passes, with a target of
90 minutes each. If it still cannot complete one bounded task without manual
repair, freeze dynamic feature development and deliver through the verified
fixed path. Do not expand scope to justify previous investment.

## First hardening pass

| Priority | Required behavior | Acceptance evidence |
|---|---|---|
| P0: responsive submission | Commit hooks and other long-running subprocesses must not block the API event loop. Preserve all hooks, exclusive worktree access, commit failure reporting, and truthful run state; expose check progress. | Baseline `2a78847f...` reached auto-commit at 00:51:03 UTC, then 8-second health and 15-second run reads timed out while the real git/pre-commit/pytest child chain ran. Source calls synchronous `subprocess.run` through the submission service. A regression must run a real bounded hook while a concurrent health/read request succeeds, and cover failed hooks and lifecycle signals without a second writer. |
| P0: executable checks at acceptance | A planner cannot install a check bound to an absent/empty optional command. The controller resolves and validates the canonical command before granting executable authority, returns an actionable typed rejection, and preserves explicit final acceptance semantics. It must not silently substitute final acceptance for an optional hidden oracle. | Reproduce the exact blank binding through the public semantic construction path; reject before any worker dispatch or accepted region; valid explicit command and configured binding still execute; replay retains the resolved contract. |
| P0: deterministic failures have defined outcomes | Distinguish a command's nonzero test result from invalid configuration, timeout, and dispatch/infrastructure failure. Each has an explicit bounded correction or actionable pause path. Recovery must not wait for a verification report that can never be produced because its input check died. | Real command exit failure, timeout, and unavailable binding cases cross API/controller/driver; no orphaned required input, active leaked lease, infinite retry, or falsely completed candidate. |
| P0: show the actual blocker | Run diagnostics retain the earliest actionable error, node, command binding, graph position, and recovery disposition. Summary APIs must label unavailable sections as unknown. | The current incident fixture reports the empty binding rather than merely “graph has failed nodes”; bounded live readback and replay agree. |
| P1: reduce planner mechanics | The supported reliable-plan path gives the model a typed semantic decision and the few tools needed for it. Controller code owns identities, evidence wiring, assignments, checks, retries, and finalization. Raw/macro compatibility paths must not make the supported path rely on model-authored mechanics. | Small prompt/tool packet review plus a live semantic planning call with zero mechanical patch rejections. Remove duplicated contract construction only after a regression covers both entry points. |
| P1: cheap regression feedback | Each live incident yields one small permanent product-path reproduction. Relevant tests run during edits; the unchanged commit/release gate runs at its intended boundary. Measure repeated gate time before changing gate frequency. | Tests reproduce real failure boundaries with real files, SQLite, commands and injected dependencies; required checks pass; no test suppression, weakened acceptance, or extra framework. |

Each repair should close a user-visible failure class and remove a duplicated
assumption where possible. Keep immutable graph state and event recovery intact.
Do not undertake a projection redesign, database migration, or wholesale module
reorganization as part of this rescue.

For responsive submission, a bare `asyncio.to_thread()` is insufficient:
cancellation can return while Git still mutates the checkout, and making the
event loop responsive exposes concurrent submit/reset requests previously
serialized accidentally. Keep database session work on the event loop, retain
ownership until the Git worker drains, persist its actual completion/failure,
and prove one mutation owner per worktree across service instances. Reuse the
existing executor/signal ownership model; do not introduce forbidden API-to-
executor shared in-memory state. Cover real hooks, concurrent reads, duplicate
submissions, cancellation, and reset races. Existing worktree commit/reset event
tests and Git hook retry tests are the starting regression set.

## Requirements ledger

| ID | User-visible requirement | Current evidence | Status / next proof |
|---|---|---|---|
| R1 | A small requested feature finishes through the orchestrator | Fixed Luna baseline completed with A/A/A and original oracle pass; independent review found Unicode separator bug | Partial: Unicode correction must pass original plus supplemental oracle and independent review |
| R2 | Feedback runs are affordable and bounded | Actual builder/verifier usage is Luna; baseline finished in 12m58s with 2,384,473 input/output tokens and 31 actions | Partial: one completed measurement; price rates unavailable and quality failure prevents declaring an economy win |
| R3 | Invalid check configuration fails before expensive work | Exact empty-binding live failure retained | Implemented, live proof pending: centralized command resolution/validation and early rejection; corrected unconditional hidden-binding instructions/examples; 588 graph tests, 97 prompt/planner tests and production qualification regression pass |
| R4 | Check failures recover or stop with an actionable cause | Current check has a non-retryable runtime configuration error; its verifier lacks a check result and no corrective execution is scheduled | Partial: typed failure outcomes and actionable pause proof |
| R5 | A routine change does not require scattered contract repairs | Existing controller-owned semantic constructor and regression suite | Unproven: remove one duplicated assumption per incident-backed repair; validate across persistence and dispatch |
| R6 | Dynamic planning demonstrates useful value | One completed graph run, failed comparisons, no established benefit | Unproven: matched trial results, including failures, economics, and manual interventions |
| R7 | The user has a delivery fallback | Legacy create/start, builder, real commit hooks, independent verifier and completion all exercised by the new baseline | Execution path validated; quality must be checked per task, and R8 remains an operational defect |
| R8 | Users can inspect and control runs during submission checks | New baseline exposed health/run API timeouts during synchronous auto-commit hooks | Implemented, live proof pending: real bounded-hook API regression, duplicate submissions, owner/waiter cancellation, reset race, durable SHA/event order; 107 focused workflow/API tests pass |
| R9 | A fresh verifier evaluates the actual contract and configured commands | Correction run's stored verifier prompt omitted task instructions and both passing configured acceptance checks | Implemented, live proof pending: centralized resolved contract and bounded current-attempt observations in dispatch and public prompt API; verify on the existing failed correction after runtime repair |

## Cost and ownership

Luna handles bounded implementation, read-only diagnosis, fixture creation, and
routine verification. Start at medium effort and use high for a demonstrated
reasoning gap. The coordinating agent owns failure classification and admission
to the next phase. Use Sol only for an independent architectural decision or a
specific failed Luna attempt; do not globally promote every role. Start a fresh
builder/verifier context for every correction. Share a short ledger and exact
failure evidence, not the entire event history.

Do not retry an unchanged infrastructure error with a more expensive model.
Track completion, manual interventions, rejected calls, time to first candidate,
check time, time to final completion, and token usage by role. Passing thousands
of tests is supporting evidence; it does not satisfy a live-delivery requirement.

## Keep, freeze, or revert

Keep dynamic planning experimental if it can finish correctly but provides no
clear benefit. Admit it for a named class of work only if the three matched
trials have no platform-caused dead ends or manual repair and demonstrate either
a meaningful quality/adaptation improvement or lower time/cost. An initial
performance guardrail is no more than twice the fixed-path wall time and token
use for matched simple work; exceeding that needs a documented quality benefit.
Three trials are an admission signal, not statistical proof of reliability.

If the two repair passes fail, freeze dynamic work and use the fixed path. If
the fixed path is itself broken by shared graph changes, identify a pre-graph
commit from history, check it out in a separate isolated worktree, and repeat
the same public acceptance test before proposing a revert. Preserve the current
branch and database; older code must not be pointed at the current database
without a separately verified compatibility plan. Reverting is a concrete
reviewed change only after a working fallback is demonstrated.

The user explicitly authorized server repairs, required checks and an idle-run
restart on September 9. Implementation is isolated on
`codex/recovery-stabilization`. Operational run/database interaction remains
through the public API. No database migration, deletion or direct state repair
is part of this work. The main checkout's source matches the repair seed
semantically; four pre-existing differences are formatting only and will be
preserved unless a reviewed repair needs that exact file.

## Live campaign record

- Baseline: `2a78847f-cc61-46db-b8f0-ce0203a9a85b`, worktree `r216`, explicit
  `legacy`, Codex Server `gpt-5.6-luna`, medium effort, verifier model Luna.
- Baseline completed at 01:02:08.675155 UTC with A/A/A; both recorded model
  entries are Luna. Supplemental Unicode acceptance fails on its completed
  commit, proving the verifier false positive without changing that run.
- Correction: `7a03f18c-02b1-43f7-b7a1-c3e0e22372c5`, one attempt, Luna medium
  builder and verifier, seeded from the completed baseline branch. Start
  requested through the public API. Both original and supplemental acceptance
  commands are required. This run corrects utility code, not server code.
- Correction outcome: failed at 01:17:13 UTC with A/F/F. Both configured
  acceptance commands passed and focused verification reported 9 passing tests.
  The verifier ran a separate full suite, reported failures, interrupted its
  teardown and failed R2/R3. Its prompt omitted the original task context and
  actual commands. The full-suite failures are retained as unresolved evidence,
  not dismissed or relabeled as passing. After the prompt/runtime repair,
  recover this exact run through the public API with the corrected candidate
  preserved and one additional attempt; use the original and supplemental
  commands and validate the current candidate. This is an operator recovery,
  not an autonomous qualification success.
- Exact request and evolving evidence: `recovery-2026-09-09/` beside this file.
- Independent baseline review: the oracle passes, but the initial `r216`
  candidate uses `text.splitlines()`. Valid JSON strings containing U+2028 or
  U+0085 incorrectly yield two invalid-JSON issues. This is an unmet Unicode
  requirement beyond the current oracle, so baseline success must not be
  declared without correction. Observe the independent verifier before counting
  any operator intervention or launching the follow-up task.
- Baseline commit hooks passed and produced commit `e328421f9`; auto-commit ran
  from 00:51:03 to 00:57:32 UTC (6m29s). API reads recovered and a fresh Luna
  verifier started at 00:57:39 UTC. This establishes a working submission
  transition, not final feature acceptance.
- Follow-up diagnostic run is conditional on verified Unicode correction; graph trials
  are conditional on the P0 repair and a tested server revision.

## Repair activation and evidence discipline

The isolated repair changes three incident-backed boundaries: executable command
admission, verifier contract delivery, and responsive submission with exclusive
checkout ownership. A stateless coordinator uses a deterministic operating-system
file lock, asynchronous nonblocking acquisition, and cancellation draining. It
does not share an in-memory registry between HTTP requests and execution.

Before activation, run the unchanged commit hooks on the repair branch. Recheck
that the live server has no active runs and that every target source/test file in
the main checkout still matches the seed. Install only the reviewed changes;
retain an exact before/after SHA-256 manifest. Let the existing development
reloader restart, then verify health and the repaired API behavior before
recovering the preserved Unicode candidate. No database files are changed.

The bounded task template is now in
`routines/recovery-bounded-task/routine.yaml`. Subsequent fixed feedback runs use
that committed template and retain its source commit in the request evidence.
The pending graph request preserves the original two-batch public specification,
blank optional hidden-oracle command, final oracle, and explicit model-role
assignments; it requires a newly issued qualification reference before creation.
Do not count preparation of either request as a launched or successful run.
