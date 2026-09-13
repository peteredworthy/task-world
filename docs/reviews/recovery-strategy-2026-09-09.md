# Recovery strategy: restore delivery, then earn dynamic graph complexity

> Future work is governed by [the restart plan](recovery-restart-plan-2026-09-09.md).
> This document retains the earlier campaign and evidence; its original trial
> sequence and budgets have been superseded.

Decision: deliver bounded work through the fixed builder/check/verifier routine
while dynamic planning remains experimental. Two commits repairing four incident-backed runtime boundaries are active. The preserved Unicode correction has now
completed with A/A/A and independent acceptance passes. The new Luna diagnostic
trial reached independent verification and received a reproducible failure;
one explicitly bounded correction completed. Independent review still finds a
malformed-graph false positive, retained as a delivery limitation. The first fresh
two-batch graph trial stopped at repeated planning rejection. A second repair
now preserves actionable diagnostics for covered errors. The post-repair probe
expanded without operator guidance and launched Luna implementation, but was
paused at its 20-minute budget without an accepted candidate. One generic
rejection remains. Completion and dynamic value remain unproven.

Do not revert the repository wholesale on the current evidence. The old graph
artifact passes a Unicode case that the first fixed Luna candidate missed;
there may be a quality benefit. Completion reliability and cost remain unproven.
Preserve the current implementation and run history while testing that claim.

The original failed run has no safe supported command repair: resume cannot
change its immutable command, and paused repair requires replacement contract
parity. It remains incident evidence. The fresh trial keeps the original public
specification, blank optional hidden oracle, and unchanged final acceptance.

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

1. **Restore delivery. Completed.** Centralize executable command admission,
   deliver the full contract to fresh verifiers, and keep the API responsive
   during exclusive worktree mutation. Commit the fixes with every existing
   hook enabled. Activate only reviewed files when no runs are active.
2. **Exercise useful Luna work. Completed with a retained quality gap.** Use the committed
   `routines/recovery-bounded-task/routine.yaml`, explicit acceptance commands,
   Luna medium builder and fresh verifier. The Unicode correction completed.
   The read-only diagnostic trial found an actual feature defect; allow one
   correction with precise evidence, retaining the failed attempt. Correction
   completed with A/A/A and 13 passing tests, but independent review still
   disproves complete malformed-graph handling. Do not promote this diagnostic
   as fully validated or grant more attempts in this campaign. Record this
   as operator-guided remediation, not an autonomous first-pass success.
3. **Prove dynamic execution once. Budget stopped, incomplete.** The first trial
   from `751d3a7` failed admission; the new probe from `98ca9f6cb` uses the unchanged two-batch JSONL task, with Luna discovery/implementation/correction
   and Sol planner/verifier/successor roles explicitly retained. Require the
   final receipt, bound candidate, both batch verifications, independent audit,
   and terminal completion with no manual graph repair. A local oracle pass
   alone cannot establish this. All ten freshly issued controller qualification
   scenarios passed; they are a prerequisite, not a live-agent result.
4. **Admit value only after matched evidence. Conditional.** If the live graph
   trial succeeds, compare three tasks from identical source snapshots: a small
   utility, a dependent two-batch change, and work where new evidence changes
   the next action. Keep public requirements, oracles, gates and retry caps
   equal. Report the Luna-only baseline separately from stronger graph roles.
   Alternate arm order and retain every failure and manual intervention.

At most one active trial at a time. Inspect each attempt at 15 minutes and
pause through the API at 20 minutes if still active. The baseline allowed two
attempts; the diagnostic allowed one initial attempt and one evidence-backed
correction after its independent rejection. Do not grant repeated blind retries.
Five minutes without an artifact, submitted candidate, check result or
verification triggers diagnosis. The API has no verified run-wide budget field;
these are operator-enforced limits, not runtime-enforced guarantees.

Freeze graph feature development if this bounded trial cannot complete without
manual repair. Deliver through the verified fixed path and use the captured
failure as the next small engineering contract. Do not add another planning
framework, projection redesign or database migration to rescue the experiment.

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
| R1 | A requested feature finishes through the orchestrator | Unicode correction attempt 2 completed in 113.6 seconds, A/A/A, original and supplemental oracles independently pass | Validated with operator recovery; first fixed candidate's false positive is retained |
| R2 | Feedback runs are affordable and bounded | Luna fixed trials report real token/action/time metrics; diagnostic first attempt reached a correct rejection in 14m24s | Bounded feedback validated; price rates absent, no dollar or economy-win claim |
| R3 | Invalid check configuration fails before expensive work | Centralized resolution and typed acceptance rejection; corrected unconditional hidden-binding instructions; focused graph tests and ten fresh controller scenarios pass | Implemented and regression-validated; first graph trial stopped before worker dispatch; post-repair probe corrected typed errors and expanded without guidance |
| R4 | Check failures recover or stop with an actionable cause | Typed nonretryable invalid-contract disposition; diagnostic CLI independently exposes exact original error at position 486 | Core classification tested; diagnostic missing node_states remains a reproduced gap |
| R5 | Changes do not require scattered contract repairs | One parser used by acceptance and dispatch; one verifier context resolver; stateless worktree mutation ownership | Three duplicated assumptions removed; sustained change-resilience remains to be measured |
| R6 | Dynamic planning demonstrates useful value | Original graph artifact passes supplemental Unicode oracle that first fixed candidate fails | Positive quality signal, confounded by model roles; reliable completion and economics unproven |
| R7 | A delivery fallback exists | Fixed create/start, hooks, checks, fresh verifier, failure and completion all exercised on active repair | Validated; use committed bounded routine with task-specific acceptance |
| R8 | Runs remain inspectable during submission checks | Real server-owned diagnostic auto-commit/pytest child chain while health/read calls remain about 12–37 ms; concurrency/cancellation/real-hook regressions pass | Live validated; submission checks still take several minutes |
| R9 | Fresh verifier sees the actual contract | Stored live prompt includes full task, exact commands and current-attempt observations; correction passes and diagnostic verifier reproduces a real defect | Live validated; independent feature probes remain necessary |

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
performance guardrail is no more than twice the fixed-path wall time and total input-plus-output token
volume (summed across all roles, cached input included once) for matched simple work; exceeding that needs a documented quality benefit.
This is a workload-volume guardrail, not a dollar-cost measure; report cached,
uncached and output components by model separately. Three trials are an admission
signal, not statistical proof of reliability.

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
is part of this work. Activation preserved unrelated main-checkout differences. The exact guarded
file manifest and before-image backups are retained; the live source contains
the reviewed repair overlay without a main-checkout Git reset or checkout.

## Live campaign record

| Run | Actual result | Intervention / evidence |
|---|---|---|
| `2a78847f-cc61-46db-b8f0-ce0203a9a85b` (`r216`) | Fixed Luna baseline completed in 12m58s, A/A/A; original oracle passed but independent Unicode probe failed | Retained false positive. Submission blocked API reads for 6m29s on old runtime |
| `7a03f18c-02b1-43f7-b7a1-c3e0e22372c5` (`r217`) | Initial correction had passing configured commands but failed verification whose prompt omitted the contract. After runtime repair, attempt 2 completed at 13:27:03 UTC in 113.6s with A/A/A | API recovery, candidate preserved, one extra Luna medium attempt. Candidate `2fa1ab156b009d05cc4fdb33ad3755a1d5e01154`; both oracles independently rerun, exit 0. Not autonomous qualification |
| `330e0347-41b4-4aa5-9fef-6ab2e2f39f70` (`r218`) | New diagnostic attempt 1 ended 13:43:38 UTC with F/A/A. Exact tests passed; fresh Luna verifier reproduced falsely complete reporting when a failed node has no failure events | Root independently confirmed that defect plus wrong top-level run identity and malformed graph handling. One bounded correction completed 13:55:10 UTC in 8m52s with A/A/A and 13 passing tests. Independent `{}` graph fixture still exits 0 incorrectly; retain as verifier false positive. Candidate `ad46b7f0e661b9e469e68fbb0f477e0558519361` |

The diagnostic CLI already explains the real incident: exact empty-command
reason at graph position 486, preserving the summary separately. Its missing-`node_states`
edge case remains a reproduced blocker to declaring the utility fully validated.
Next bounded feature hardening should validate required response fields with
strict models instead of treating missing fields as empty collections.
Exact API requests, stored task/attempt results, independent probes, activation
manifest and source identities are retained in `recovery-2026-09-09/`.

## Immediate delivery settings

For normal bounded work, select source branch `codex/recovery-stabilization`,
project routine **Bounded Recovery Task**, execution mode **Legacy**, and
**Codex Server / gpt-5.6-luna / medium**. Supply the full task contract and an
operator-owned acceptance command. The routine declares legacy execution, but
the current create dialog explicitly sends its execution-mode selection, so
select Legacy there as well. No global model or execution-mode preference was
changed. Dynamic feature tasks remain explicit experiments.

## First graph trial on the repair

Run `ccf06b57-8b96-4c07-a5af-fbee16a948a3` (`r219`) started from
`751d3a724` at 13:55:47 UTC and was paused via API at 14:00:49 after repeated
planning rejection. Seven macro commands and one raw fallback were rejected;
no expansion was accepted and no Luna worker ran. The first execution recorded
271,774 input / 5,738 output / 234,112 cached input tokens and 12 actions; the
interrupted second execution is incompletely accounted for. Original macro
arguments were not retained. The false omitted-ops error hid the actual cause;
the exact original argument defect is unknown. The new probe cannot erase this
failed trial. Full retained evidence is in `graph-trial-1/`.

## Second repair and bounded probe

Commit `98ca9f6cb74cebd527540dc9a9207c661eaa89cc` preserves typed, value-free
macro argument/domain/check-binding errors and fixes the false omitted-`ops`
diagnostic. A real MCP call now crosses dispatcher and controller in regression
tests for accepted construction, unavailable requirements, unavailable hidden
binding, and invalid/redacted arguments. Explicit `ops: null` remains invalid.
Domain error codes are raised at their source; no error-message parsing was added.

The focused tests and separate review passed; every configured commit hook
passed. Six guarded files were activated with backups at 14:26 UTC, and the
existing reloader started healthy PID 54069. Main source hashes matched the
previous repair exactly before replacement. All ten fresh canonical qualification
scenarios also passed. These do not prove that the original macro cause is fixed.

Fresh probe `4f89c845-3f82-4b79-856d-41b52bf0ff53` started at 14:27:25 UTC from
this commit, with unchanged public specification, final oracle and Luna/Sol
assignments. It retains the first failed graph trial as its parent experiment.
The predeclared inspection was at 14:42 UTC and the stop at 14:47 UTC; the
20-minute budget stop was applied through the API and pause verified at 14:48:42. Manual graph patches or injected agent guidance would disqualify this probe
as an unassisted result. A further platform failure closes this campaign
with fixed delivery enabled and graph feature development frozen.

## Current probe evidence

The post-repair probe produced actionable errors instead of the previous red
herring. At position 25, safe diagnostics identified check fields `cmd`,
`purpose` and `timeout_seconds` in the wrong shape and missing `name`. At
position 28, the controller reported `initial_dependencies_forbidden`. The
planner corrected both without operator guidance and obtained accepted patch
position 31 at 14:29:23 UTC. The initial planning phase then completed; Luna discovery and independent plan verification followed.
The first effectful batch was admitted at about 14:35 UTC. This validates the
diagnostic repair live; it is not yet a completed graph feature.

The next targeted simplification, if graph work continues, is to derive both
runner tool schemas from the controller's Pydantic model and expose stage-specific
dependency constraints. Codex already advertises the nested check shape; the MCP
wrapper uses generic check objects. Do not infer that Codex lacked the schema or
that schema generation alone prevents model errors. Measure schema parity,
rejected calls and time to first accepted expansion; do not add a planning layer.

## Activation and verification record

Commit `751d3a72491c439bf78768fc21571cdf4954cbbc` and successor
`98ca9f6cb74cebd527540dc9a9207c661eaa89cc` passed every configured commit hook:
full default test suite, Ruff, Pyright, secret scanning, graph/import/signal
boundaries, and UI lint/type checks. No checks were bypassed. First activation
installed 35 guarded files at 13:24 UTC; second activation installed six at 14:26.
Both occurred while no runs were active, with before-images and hash manifests
retained. The existing reloader restarted successfully. Main Git HEAD was not
moved; live source contains the reviewed overlay. No database files were changed.

Fixed feedback requests embedded the exact committed routine fetched through
the repository API and retained its source commit in request/config evidence.
The native `routine_commit` is null; do not claim stronger provenance. Graph
submission gates read the unchanged checked-in project test command for effectful
workers. Analysis-only discovery has no executable gate commands by design.
Inspect actual gate audits before claiming candidate acceptance.

## Next small hardening contracts

1. Strict diagnostic response models: real HTTP fixtures for missing
   `node_states`, malformed graph shape, wrong run identity and absent failure
   evidence. Missing required data means partial/unknown with nonzero exit, never
   a false complete result. Preserve valid/live incident behavior. Luna can own
   this bounded task, with independent edge-case verification.
2. One semantic tool contract: derive both runner schemas from the controller's
   Pydantic model, expose stage constraints, and prove parity through both public
   entry points. Measure rejected calls and time to accepted expansion.
3. Gate-time accounting: attribute baseline, submission, checks and verification
   time to the exact candidate. Preserve all checks. Measure duplicate work
   before proposing reuse; any reuse needs exact source/command/environment
   identity and an invalidation regression.
4. Extend bounded failure/correction tests from observed incidents. Do not add
   another planning framework, projection redesign or database migration.

This second bounded probe closes the current live campaign. A budget stop is
different from a platform dead end; neither by itself proves the graph can never
finish. Both leave admission unproven. Three matched value trials are conditional
future work, not work already performed. Retain failed runs and interventions.

Evidence is retained in `recovery-2026-09-09/`; `SHA256SUMS` covers its files
recursively. Token metrics distinguish cached input from output; missing model
prices and interrupted execution usage prevent reliable dollar comparisons.

Independent review retained two distinctions: the current probe self-corrected
mechanical rejections, so it does not satisfy the P1 zero-mechanical-rejection
aspiration; successful diagnosis is narrower than qualification. Also, a leased
batch is admitted but has not necessarily launched its model. At 14:39 UTC the
first effectful worker was still waiting on the real checked-in baseline pytest
command (over four minutes); it had no candidate or model usage yet.

At 14:43:20 UTC the first effectful baseline gate passed (exit 0), with an
authoritative duration of **488,081 ms / 8m08s**. Luna implementation started
afterward. The exact unchanged project command and source tree are retained in
`graph-probe/runtime-final.json`. This measured gate cost makes a 20-minute
two-batch completion cap restrictive even for correct execution. Keep the cap
for this latency experiment, but do not treat its expiry as a platform defect
or proof against eventual completion. Before another completion/value campaign,
measure the necessary gate critical path and predeclare a realistic budget; do
not extend this run after seeing its result. Gate accounting is now the first
performance hardening priority; required checks remain unchanged.

## Final decision and second probe outcome

**Keep fixed delivery available; freeze new dynamic-graph features.** Do not
revert the repository wholesale. The current campaign has restored a working
fixed Luna loop and removed incident-backed fragility, but has not established
dynamic completion or value. Prioritize measured gate cost, remaining unsafe
diagnostic assumptions, and tool-contract consistency before another campaign.

Probe `4f89c845-3f82-4b79-856d-41b52bf0ff53` is now `paused/manual_pause`,
with zero active leases (four released, one revoked). The operator requested
pause at the 20-minute limit; runtime cleanup restored the unsubmitted worker
to its baseline (`restored_unwitnessed`). No implementation candidate was
accepted, no batch verifier completed, and no final oracle/receipt/audit exists.
Run history and accepted planning evidence remain; the clean run worktree does
not establish preservation of the interrupted worker's unsubmitted edits.

Four canonical planner rejections occurred, at positions 25, 28, 134 and 137.
The first three have actionable typed diagnostics. Position 137 still reports
only `malformed patch [malformed_patch]`; its exact cause is unknown. Both
planning phases nevertheless self-corrected without guidance, accepting patches
31 and 140. This is useful recovery evidence, not zero-friction planning.

Recorded totals are 971,302 input tokens (798,336 cached, 172,966 uncached),
21,184 output tokens, 34 actions and 445,679 ms model duration. Those totals
cover four completed executions; the interrupted implementation execution is
missing, so they undercount campaign usage. Model prices remain unavailable.
The effectful baseline project gate passed in 488,081 ms, dominating much of
the twenty-minute window. The stop is a latency/budget outcome, not a new
platform dead end and not proof that this graph could never finish.

Both repair commits are committed and active; all configured commit hooks
passed. Final verification confirms the six second-activation files still
match their tested hashes. The final report and evolving API evidence remain
uncommitted documentation in the isolated repair branch and are copied to the
main checkout for review. No live runs remain from this campaign.
