# Orchestrator recovery — restart plan

Updated September 9, 2026. This is the entry point for continuing in a clean
context. It supersedes the **future execution plan and trial budgets** in
`recovery-strategy-2026-09-09.md`; that document and its evidence directory remain
historical records. Do not restart the old campaign or repeat its completed work.

## Objective

Get to dependable, affordable delivery, then determine whether dynamic graphs
provide enough quality or adaptability to justify their overhead. Keep the fixed
workflow usable throughout. Reduce duplicated contracts and fragile boundaries
through small, incident-backed changes. Do not assume keeping or reverting the
whole graph implementation is the only choice.

The immediate change in method is: **no-model boundary tests → isolated model
phase probes → tiny end-to-end smoke → representative value experiment**.
Full feature runs must not serve as the first test of basic validation, prompt
wiring, API responsiveness, diagnostics, or test-gate duration.

## User direction and authority

The user requested a strategy, implementation/hardening, cheap agents where
possible, and orchestrator runs with Luna once the system is capable. They
explicitly said: “you have my permission, keep going”. Subsequently they
challenged the cost of the full runs and requested this restart document.

On being told to continue from this document, carry out the stages below without
repeated confirmation for already authorized scoped repairs, tests, or bounded
experiments. No new runs are started by writing this document. Do not interpret
prior authorization as permission for unlimited retries, destructive database
changes, a wholesale revert, or bypassing checks. Preserve unrelated changes.

## Current state — verify cheaply before changing anything

Repository: `/Users/peter/code/task-world`.

Repair worktree: `/Users/peter/code/task-world/worktrees/recovery-stabilization`.
Branch: `codex/recovery-stabilization`.
Last known repair HEAD: `98ca9f6cb74cebd527540dc9a9207c661eaa89cc`.

Two completed source commits:

| Commit | Implemented repair |
|---|---|
| `751d3a72491c439bf78768fc21571cdf4954cbbc` | Central executable-command admission/dispatch validation; complete fresh-verifier contract; asynchronous exclusive worktree mutation with cancellation draining; bounded fixed routine. |
| `98ca9f6cb74cebd527540dc9a9207c661eaa89cc` | Typed safe macro argument/domain/binding diagnostics and correct omitted-versus-null raw `ops` handling; actual MCP/dispatcher/controller regressions. |

Both passed every configured commit hook, including the default test suite,
type/lint checks, boundaries and UI checks. Do not rerun the entire suite merely
to rediscover that recorded result on unchanged source. Run focused tests for
new work; the required commit gate remains mandatory.

The live main checkout received a guarded overlay of these repairs. **Main Git
HEAD was not advanced**, so its commit alone does not identify the running code.
Activation manifests and before-image backups were retained. The development
reloader restarted successfully. Documentation/evidence added after the commits
remain uncommitted and have copies in main and the repair worktree. Do not reset
or discard either checkout to make it look clean.

Last campaign state: all campaign runs are completed or paused. The final probe
was confirmed paused at 14:48:42 UTC, with zero active leases. This is a historical
observation, not permission to assume the server is still idle in a new context.

Live API: `http://localhost:8000`. Use REST for operational run state. Do not
read/write the live database directly. Check `/health`, active runs, and the
specific probe below before activation. Do not resume any historical run as a
shortcut. If the server is unavailable, report that fact; existing local work
and no-model tests can continue independently.

## What actually happened

| Run / candidate | Finding and correct interpretation |
|---|---|
| Original `d20ff4dd-9cd1-4f29-9df1-d344a0582907`, `r215` | Paused after 57m44s when a required check used a blank optional hidden-oracle binding (position 486). Its artifact passes original and supplemental Unicode oracles. No safe supported immutable-command replacement was found. Preserve it. |
| Fixed Luna baseline `2a78847f-cc61-46db-b8f0-ce0203a9a85b`, `r216` | Completed in 12m58s with A/A/A, but independent Unicode probe found a bug. Submission hooks blocked API reads on the old runtime. Grades alone were insufficient. |
| Unicode correction `7a03f18c-02b1-43f7-b7a1-c3e0e22372c5`, `r217` | Following runtime repair and operator recovery, attempt 2 completed in 113.6s; both independent oracles passed. Candidate `2fa1ab156b009d05cc4fdb33ad3755a1d5e01154`. Working fixed delivery demonstrated; not autonomous first-pass success. |
| Diagnostic utility `330e0347-41b4-4aa5-9fef-6ab2e2f39f70`, `r218` | Verifier caught one real defect; a guided correction passed, but independent review still found a false complete/exit-0 response when graph `{}` lacks `node_states`. Candidate `ad46b7f0e661b9e469e68fbb0f477e0558519361` is not fully validated. Do not launch another full run to test this edge case. |
| Graph trial `ccf06b57-8b96-4c07-a5af-fbee16a948a3`, `r219` | Paused after repeated planning rejection in about five minutes; no expansion accepted. False omitted-ops feedback hid the actual cause. Original arguments were not retained; do not claim their precise defect is known. |
| Latest probe `4f89c845-3f82-4b79-856d-41b52bf0ff53`, `r220` | Planner self-corrected rejections at positions 25, 28, 134 and 137; patches 31 and 140 accepted. Position 137 still has only a generic malformed-patch reason. Discovery and plan verification completed. Baseline gate passed in 488,081 ms (8m08s); Luna implementation began roughly 16 minutes after run start. Operator paused at 20 minutes without an accepted candidate or final verification. |

The latest probe retained 971,302 input tokens, including 798,336 cached, plus
21,184 output tokens and 445,679 ms model duration for four completed phases.
Interrupted implementation usage is missing. Prices are missing: do not infer
zero cost from stored `cost_usd: 0`, or publish dollar savings from raw tokens.

Pause cleanup restored the unsubmitted worker to baseline (`restored_unwitnessed`).
Accepted planning/history remain; do not claim the interrupted edits are a saved
candidate. The 20-minute cap limited spending, but was too restrictive to test
completion given the measured gate cost. It establishes a latency/budget outcome,
not a platform dead end or proof that the graph cannot eventually finish.

## Stage 1 — close the cheap evidence gaps, without model runs

First inventory existing coverage and identify genuinely missing assertions.
Several regressions were already added; do not duplicate them. Exercise the
actual public paths with real Pydantic models, SQLite, Git repositories, files,
subprocesses and HTTP/MCP calls. No mocks or monkeypatching. Tests that call only
internal helpers are insufficient where the incident was caused by wiring.

| Question | Minimum evidence before any live phase probe |
|---|---|
| Can unusable checks be installed? | Blank, missing, wrong-shaped and valid explicit/bound commands traverse authoritative admission and dispatch. Invalid contracts reject before a worker; final acceptance is never substituted for an absent optional oracle. |
| Does the verifier get the actual contract? | Actual executor/prompt path includes full requirements, exact commands and bounded current-attempt evidence; stale receipts do not count as current proof. |
| Can submission freeze or race the API? | Existing real-hook concurrent API, duplicate submission, reset and cancellation/draining regressions remain valid. Test a short controlled hook, not a full feature build. |
| Are macro/tool contracts consistent and errors useful? | Valid and malformed requests cross each supported exposed tool entry point, dispatcher and controller. Cover initial and successor stages, omitted/null fields, nested checks, unavailable bindings and requirements. Rejections have safe typed codes/paths; no raw secret values. |
| Can diagnostics report missing data as success? | Real HTTP/CLI fixtures for missing `node_states`, malformed graph shape, mismatched run ID, absent failure events, empty valid state and bounded/truncated data. Missing required evidence yields unknown/partial, not complete. |
| How much time is unavoidable before a result? | Map baseline, submission, explicit checks, verifier checks and final audit to their commands and source identities. Reuse retained timings first; run a command once only if needed to fill a material gap. |

Start with macro contract/diagnostic coverage and gate accounting: these directly
blocked or dominated the graph experiments. The diagnostic utility is a useful
local fixture exercise; its completion is not a prerequisite for the graph.
Do not grow that utility into a new observability subsystem.

Source starting points in the repair worktree:

- `src/orchestrator/graph/command_bindings.py`
- `src/orchestrator/graph/macros.py` and `graph/_commands.py`
- `src/orchestrator/graph_runtime/dispatch.py` and `graph_mcp_tools.py`
- `src/orchestrator/runners/agents/codex/common.py`
- `src/orchestrator/workflow/worktree_mutations.py`
- `src/orchestrator/graph_runtime/submission_gate.py`
- `tests/unit/test_command_bindings.py`
- `tests/unit/test_graph_dispatch_on_output.py`
- `tests/integration/test_graph_patch_acknowledgement_recovery.py`
- `tests/unit/test_worktree_commit_events.py` and `test_worktree_reset_events.py`

Codex already advertises nested check fields; the MCP wrapper is looser. Do not
claim simply adding a schema will prevent model mistakes. Derive duplicated
schemas from the canonical Pydantic contract where practical and test parity.
The cause of generic rejection 137 is unknown because exact arguments were not
retained. Reproduce the error class using valid/minimally-invalid fixtures; do
not call a guessed input an exact historical reproduction. Retain safe, bounded
reproduction data going forward without exposing credentials or arbitrary values.

Use existing test infrastructure. A small fixture/helper is acceptable; a new
simulation platform, planning framework or projection redesign is not.

Exit: a concise coverage ledger records each question, actual path exercised,
passing evidence or specific remaining gap, and focused command. Repair only
observed defects. Commit cohesive source changes with all existing hooks enabled.
Do not activate untested source or interrupt unrelated live runs.

## Stage 2 — isolate model behavior, use Luna sparingly

Only after relevant Stage 1 checks pass, test questions that require a model:
can it use the supported contract, recover from a specific rejection, or verify
actual feature behavior? Prefer an existing single-phase executor/test entry
point with prepared inputs and a real isolated worktree. Do not launch the full
feature workflow merely because the isolated entry point needs a small fixture.

Initial allowance: **at most four paid phase executions across this stage**,
one active at a time. Begin with one planning/tool-use probe and one verifier
probe. Reserve the other two for a specific correction/retest. Each invocation
must have one question and a bounded input packet. Use a native token/action
limit if supported; otherwise record that the bound is operator enforced.
Target at most three minutes of model execution per probe, excluding separately
measured deterministic setup. A budget expiry is incomplete evidence, not proof
of model incapability. Do not restart unchanged failures.

- Planning: use a prepared qualified graph state and the exact supported tool
  schema. Stop after the required accepted decision/callback, not after building
  a feature. Exercise successor planning separately if that is the remaining gap.
- Verification: use a prepared candidate and independent acceptance cases,
  including a deliberately defective **test fixture**, to establish that a
  verifier can detect the known class of bug. Keep this separate from real
  delivery trials; never inject defects into a user feature to manufacture a win.
- Tool transport: do not substitute a helper-only test when the question concerns
  actual runner tool exposure. Clearly label deterministic tests versus real
  runner/model observations.

Use Luna medium by default, high only for a demonstrated reasoning gap. Keep
fresh context per phase. Stronger-model comparison is justified only by one
specific failed Luna question; it must fit the remaining probe allowance. Do not
silently change sealed routine/model contracts or global runner defaults.

Before each invocation record: hypothesis, why deterministic tests cannot answer
it, source/model/role, expected evidence, budget, stop condition and next decision.
Record result immediately afterward, including failed calls and incomplete usage.
If four executions do not answer the questions, stop model spending and report
what local engineering or contract clarification is still required.

## Stage 3 — one tiny end-to-end smoke

Admission requires the relevant deterministic paths and isolated model behaviors
to pass. Use a purpose-built tiny fixture repository with a real fast declared
check, one bounded change and a fresh verifier. Exercise normal worktree creation,
submission, check/candidate binding, terminal completion and cleanup through the
real orchestrator. Record exactly which graph stages this small smoke covers.
Do not claim it proves sequential adaptation if it does not exercise that path.

One smoke run, no automatic reruns. Budget it from measured phase and gate times
before starting. Retain normal controls. A tiny fixture repository's own checks
are legitimate; removing this repository's required checks to make a benchmark
pass is not. Clearly label the result as a platform smoke, not production feature
quality or a graph value comparison.

If it fails, capture the smallest input/transition and return to Stage 1 or 2.
Do not restart the whole workflow to investigate one deterministic failure.

## Stage 4 — representative runs only for remaining end-to-end questions

A full run is admitted only when its experiment card names a question that the
prior stages cannot answer. The first should establish representative completion
with candidate-bound gates, independent verification, final receipt/audit, and
no manual repair. Use the existing public contract and unchanged required gates.
Calculate the critical-path gate cost first; predeclare a realistic wall/model
budget and do not extend it after seeing the result.

After clean completion, establish **one matched fixed/graph pair**, not an
immediate three-task campaign. Reuse that completed graph result as its arm if
source, contract, gates and measurements meet the predeclared comparison; do not
rerun it merely to label the experiment a pair. Keep source, public contract, acceptance, gate policy and
retry bounds equal; record actual role/model differences. Start with the task
class for which dynamic planning has the strongest plausible benefit. Preserve
failures and interventions. Expand to two additional task classes only if that
first pair gives a concrete positive signal worth investigating.

Compare accepted quality, adaptation to new evidence, manual interventions,
wall time, model time, check time, actions, and cached/uncached/output tokens by
model. Get actual rates before claiming dollar savings. A simple-task volume/time
ratio is descriptive; it cannot establish model-normalized cost or statistical
reliability. Do not treat A grades or a single local oracle as terminal graph proof.

## Spending and engineering discipline

- Keep the existing fixed workflow as the delivery fallback. No broad graph
  feature development while these reliability/affordability gaps remain.
- Use cheap agents only for concrete bounded independent subtasks; do not create
  agents merely to summarize information already available to the coordinator.
  Prefer local deterministic checks for deterministic questions.
- Run focused tests during edits. Run the mandatory full commit gate at its
  intended boundary, not redundantly immediately before it on unchanged source.
- Do not remove gates, weaken acceptance, bypass hooks, skip failures or claim
  baseline failures are harmless. Investigate before proposing any check reuse.
- Evidence reuse needs identical source/tree, command, relevant configuration
  and environment, trustworthy provenance, and invalidation tests. Gate timing
  alone does not authorize a caching implementation or prove it will be safe.
- Preserve the repository's immutability, injection, module-boundary, signal-queue
  and fresh-context rules. No database migration or direct database state repair.
- Python commands use `uv run`; for this environment the established prefix is
  `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync`.
- Do not perform Git mutations in main. Work in the isolated repair worktree and
  inspect its status first. Read applicable AGENTS.md and skill instructions.
- If using the mind-the-gap skill for implementation, read it and maintain a
  compact requirements/gaps/validation ledger; do not translate its cycles into
  repeated full live runs.

## Keep, freeze or revert

The fixed path already works, so a wholesale revert is not currently needed for
delivery. Keep dynamic graph experimental until it finishes cleanly and earns a
specific use case through matched evidence. If cheap validation repeatedly finds
cross-boundary instability, favor reducing supported paths and duplicated
contracts over adding more orchestration machinery.

If shared graph changes break fixed delivery, identify a pre-graph revision and
test it in a separate isolated checkout against the same acceptance before
preparing a concrete revert proposal. Preserve current source and run history.
Never point old code at the live database without verified compatibility.

## Durable outputs and first actions in the new context

1. Read this document, repository instructions and the latest repair-worktree
   status. Verify source identity and live state through the API; do not resume
   old runs. Note any changes since this handoff.
2. Create a compact `recovery-cheap-validation-ledger.md` beside this document.
   Inventory Stage 1 coverage, the remaining generic diagnostic and gate timing.
3. Complete the first bounded missing no-model reproduction, then make the
   smallest necessary repair. Use existing evidence before running new checks.
4. Proceed through stage admission rules. Record every model invocation before
   starting it. Stop at the explicit allowances rather than silently increasing
   the experiment size.
5. Update the ledger with implemented changes, checks, spending/usage, unresolved
   gaps and the exact next action. Report progress without making the user read
   long raw logs. No expectation that the user remember this prior conversation.

Historical evidence: `docs/reviews/recovery-strategy-2026-09-09.md` and
`docs/reviews/recovery-2026-09-09/` (including `graph-probe/campaign-result.json`,
`runtime-final.json`, `successor-rejections-full.json`, diagnostic reproduction
files and activation manifests). Original operator oracle:
`/private/tmp/qualification-20260907/task1_oracle.py`; supplemental oracle text is
retained in `unicode-oracle.py.txt`. Verify temporary files still exist before use;
never recreate or alter acceptance silently.

Suggested restart instruction:

> Read `docs/reviews/recovery-restart-plan-2026-09-09.md` and continue from it.
> Start with the no-model validation stage. Use cheap agents where useful and
> follow the document's admission and spending limits before any live runs.
