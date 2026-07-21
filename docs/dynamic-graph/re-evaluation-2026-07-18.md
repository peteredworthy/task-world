# Post-Closeout Re-evaluation — 2026-07-18

> Compiled at main HEAD `3cbc824b8` immediately after the backlog-closeout
> merge (41 commits, `60ca04f96` → `3cbc824b8`; full suite 4792 passed,
> 3 skipped). Every "still standing" claim below was re-verified against this
> tree on 2026-07-18 — none are carried forward from the 2026-07-07 sweep on
> trust. This document supersedes the priority ordering in
> `dynamic-graph-implementation-review.html` §4 and re-sequences the
> `research/recommendations/` roadmap now that R01 is closed.
>
> **Update — 2026-07-20, HEAD `9568ca23d` (+working tree):** Priority 1 (§2)
> is done — 47 direct-to-main commits landed R04 phase 1 telemetry
> (`7de8c6e56` → `9568ca23d`), re-verified against the tree, not carried on
> trust from commit messages. Priority 2 (§3, all of 3a/3b/3c) is also done,
> implemented and verified in this working tree on top of `9568ca23d` — see
> §3 for what shipped and what the original "cheap PR" framing got wrong
> about 3a's actual blast radius. Priorities 3–6 (§§4–7) were re-checked and
> are untouched — still open exactly as described. Full suite after both
> closures: 4971 passed, 3 skipped; ruff and pyright clean. §8's R08 deferred
> entry was stale after these two closures (it cited Priority 1 and Priority
> 3a as blockers) and has been corrected below.
>
> **Update — 2026-07-20, later same day:** Priority 3 (§4, the deletion
> sweep) is mostly done — see §4 for what shipped, what was intentionally
> **not** deleted, and why the "5 diagnostic endpoints" line item's evidence
> was incomplete in the same way 3a's was: a "zero consumers" check that only
> looked at UI/CLI/MCP missed a real consumer (the FR-acceptance test suite).
> Full suite after this pass: 4892 passed, 3 skipped (down from 4971 — dead
> tests were deleted alongside dead code, not just dead source); ruff and
> pyright clean.
>
> **Update — 2026-07-21, HEAD `447196950`:** Priority 4 (§5, the graph-runner
> capability contract) is done — the capability contract is now derived from
> `agent_factory`'s `graph_capable` registration flag (no hand-maintained
> frozenset); `claude_cli` is graph-capable via a per-execution MCP tool
> server mounted at `/mcp-graph/{token}`, closing directly over that
> execution's callbacks; `codex exec` via `cli_subprocess` remains a
> documented gap (capability flag says yes, no MCP wiring for it). Full suite
> green: 4926 passed, 3 skipped; ruff and pyright clean.

## 1. What the closeout already resolved (no action)

For orientation — these items from the 2026-07-07 review are done and need no
further work:

- All P0s: allowlist AST guard, stale-seed refusal, W6 outbox hardening.
- W5 typed payloads + W5.5 artifact CAS; four payload allowlists are now
  *generated* from typed models (`payload_registry.py`).
- W7 glob overlap; W8 drive-loop cleanup (recovery no-op and progress
  signatures deleted, pure outcome policy relocated into the kernel,
  projection-fold reimplementations now delegate to `build_projection`,
  graph exports pruned 180 → 165 with an AST guard).
- Claude SDK runner removed (decision doc:
  `claude-sdk-runner-removal-decision.md`); the four selectable runners are
  `openhands_local`, `openhands_docker`, `cli_subprocess`, `codex_server`.
- The four triaged bugs, each pinned RED→GREEN: scheduler-view snapshot
  drift, graph human-gate approval (UI + API + CLI), codex CLI `--model`
  routing, July-4 supersession incident replay (closes research R01(a)).
- The original `apply_command` if-chain dispatcher is deleted.
- Guard dispositions are recorded in `guard-retirement-ledger.md`.

## 2. Priority 1 — Cost/token telemetry (research R04, phase 1) — RESOLVED 2026-07-20

**What was done.** `tokens_by_node`/`tokens_by_node_kind` are now populated
by the projection fold (`graph/projections.py:2105-2109`, accumulated per
`usage.node_id`/`usage.node_kind` from graph usage events), not just
scaffolding. `codex_server` persists OTel-vocabulary usage fields
(`gen_ai_usage_input_tokens`, `_output_tokens`, `_cache_read_input_tokens`,
`_cache_creation_input_tokens`, `_reasoning_output_tokens`) per action log
(`runners/agents/codex/agent.py`). A dedicated cost-rollup API landed —
`api/routers/cost_rollup.py` + `api/schemas/cost_rollup.py` +
`api/presenters/cost_rollup.py` — with filterable dimensions (`day`,
`node_kind`, `model`, `profile`, `run`) and predicates on status, runner
type, and time range. Flat legacy token counters were migrated to the OTel
vocabulary (`refactor: cut token accounting to OTel vocabulary`,
`b88a3f7d8`; `refactor: migrate usage facts and remove flat counters`,
`356c78cf3`), with historical usage preserved across the cutover and a
codemod (`scripts/codemods/r04_otel_vocab.py`) enforcing the new vocabulary
boundary. Alongside this, the event journal gained rotation/crash recovery
(segment rotate+recover, restart-safe and bounded reconciliation) as a
durability dependency of the usage event stream.

**Evidence (2026-07-20, HEAD `9568ca23d`).** 47 direct-to-main commits,
`7de8c6e56` → `9568ca23d`, spanning the codemod, canonical usage facts,
OTel cutover, runner metadata capture, graph usage persistence, cost
rollups, and journal rotation. Re-verified in this tree (not taken from
commit messages): `tokens_by_node` accumulation logic present and exercised;
`gen_ai_usage_*` fields present and set in the codex agent's completion
path; `cost_rollup` router/schema/presenter present with the filters
described above. Full suite green: 4965 passed, 3 skipped.

**What this unblocks, now that it's real:**

1. *Budgets and effort tiers* (R04 phase 2) now have a real aggregate to
   enforce against.
2. *The eval harness* (R07) can make cost assertions.
3. *Revision/escalation policy* (R03) can be tuned on evidence.
4. *Legacy retirement* (R08) is no longer blocked on cost visibility — the
   graph cost-rollup API is now an independent aggregate, not a legacy-only
   view. (R08 remains blocked on the `service.py` ↔ `graph_driver` coupling;
   see §8.)

**Not yet done — still open, not part of this closure:** machine-visible
unmatched-model accounting for the four selectable runners (the R01
residue named in the original "what") was not verified as part of this
pass; re-check before treating that sub-item as closed too. Budget
enforcement policy itself (R04 phase 2) is deliberately not started — this
closes the *measurement* half only, per the OQ-8 human steer (collect
accurate data now, design enforcement later).

## 3. Priority 2 — Boundary and mirror hardening — RESOLVED 2026-07-20

All three sub-items shipped and are re-verified against HEAD (full suite
4971 passed, 3 skipped; ruff and pyright clean). This section was originally
scoped as "three cheap changes" — 3a turned out to be a 22-file, 119-test
blast radius, not a cheap PR. The mis-scoping and what it revealed is worth
keeping on record below.

### 3a. Explicit `execution_mode` guards on legacy task endpoints — done

**What shipped.** All 13 route handlers in `api/routers/tasks.py` now
depend on a new `require_legacy_execution_mode` guard (default-`None`
parameter so direct in-process calls — e.g. `test_fan_out.py` calling
`get_task`/`get_attempt_logs` as plain functions — are unaffected) that
fetches the run and raises `409` with an explicit message when
`execution_mode == "graph"`, pointing callers at the graph-native
equivalent (`/graph/nodes/{node_id}` etc.).

**What the original "cheap PR" framing missed.** The test environment's
*effective default* `execution_mode` is `"graph"` (the `ExecutionConfig`
pydantic default, inherited by every test fixture that doesn't override
`execution=`) — matching production's "graph is the default carrier"
decision. Before this guard existed, that didn't matter: legacy task
endpoints mechanically worked against graph-mode runs too, because
`run.steps` is populated at creation regardless of `execution_mode` and
`WorkflowService`'s legacy methods don't check it — undefined-but-tolerated
behavior, exactly as flagged. Once the guard went in, **22 integration test
files / 119 individual tests** broke, because none of them pinned
`execution_mode: "legacy"` on run creation — they'd been silently exercising
the legacy lifecycle against implicitly-graph-mode runs the whole time. Fix:
added `"execution_mode": "legacy"` to every run-creation call site across
those 22 files (mechanical, scripted where the JSON body shape allowed it,
by hand for the two outlier call sites — a `**extra`-spread helper and a
`json=body` variable reference). This is real, load-bearing signal for
anyone touching `api/routers/tasks.py` or run-creation test helpers next:
the legacy-lifecycle test suite was never actually pinned to legacy mode
before this pass.

### 3b. Align the ORM `execution_mode` default with the app default — done

**What shipped.** `db/orm/models.py:48` now defaults to `"graph"`, matching
`ExecutionConfig.default_execution_mode`. Verified the one production write
path (`db/access/repositories.py`) always passes `execution_mode` explicitly
from the domain `Run` object, so this default only ever mattered for rows
constructed outside that path (test fixtures, scripts) — none of which
asserted on the old `"legacy"` default, so this was a safe flip.

### 3c. Guard or generate the remaining hand-maintained mirrors — done

**What shipped.** New file `tests/unit/test_graph_runtime_store_mirror_guards.py`
adds five reflective parity guards, one per hand-maintained mirror in
`graph_runtime/store.py`, each comparing against the canonical typed
model(s) that actually own the fields (no second hand-maintained list):

- `BOOLEAN_PAYLOAD_FIELDS` — bool-typed fields ∩ fields read through the
  SQLite 0/1→bool coercion path.
- `DECISION_RECORD_VALUE_FIELDS` — union of `DecisionRecordValue`,
  `AuthorityDecisionValue`, `DecisionRequestValue`, `AuthorityRequestValue`.
- `_RECORD_PAYLOAD_BASE_FIELDS` ∪ `_LEGACY_RECORD_METADATA_FIELDS` —
  `TypedRecordBase`'s fields plus the fields common to every one of its 22
  subclasses (reflectively discovered, not hardcoded).
- `_lease_from_grant` — AST-extracts every `payload["k"]`/`payload.get("k")`
  literal the function reads and compares against `LeaseGrantedPayload`'s
  field set.
- `SUMMARY_PAYLOAD_FIELDS` — a coverage-floor check (every event type must
  intersect the summary field set or be a documented, deliberate exception)
  rather than exact-match, since this list is a display/UX curation choice,
  not a strict derivation from one model.

**Building the guards found two live bugs, fixed as part of this change.**
`BOOLEAN_PAYLOAD_FIELDS` carried four dead entries — `approved`,
`stale_only`, `supported`, `unsupported` — none of which corresponds to any
field anywhere in the current schema (`approved` was likely confused with
the `decision` enum's `"approved"` literal value); and was missing two live
boolean fields that need coercion and weren't getting it:
`deleted_snapshot_ref`, `rate_missing`. Also found (and documented, not
fixed — a display/product decision, not a bug) three event types whose
compact event-timeline summary is permanently empty today:
`edge_created`, `input_bound`, `support_evidence_recorded`.

Added `TypedRecordBase`, `DecisionRecordValue`, `DecisionRequestValue`,
`AuthorityDecisionValue`, `AuthorityRequestValue` to `orchestrator.graph`'s
public exports (`__init__.py` + `__all__`) per the module's own
import-from-top-level rule — they weren't previously exported.

**Benefit realized.** This is the exact defect class that shipped the
scheduler-view snapshot drift bug — an unguarded mirror silently diverging
from canonical kernel policy — and the review's Entropy 1 card predicted precisely that the
unguarded mirrors would diverge first. It was right. Completing the rule
("a derived read model either calls the canonical kernel function, is
generated from the typed schema, or carries a parity/AST guard — never a
bare copy") converts future drift from a production incident into a test
failure at commit time.

## 4. Priority 3 — Deletion sweep — MOSTLY DONE 2026-07-20

4 of 5 items shipped as scoped. The 5th (diagnostic endpoints) turned up a
real consumer the original evidence missed, so 3 of those 5 endpoints were
kept instead of deleted — see the item's own row below for the corrected
finding.

| Item | Evidence (2026-07-18) | Outcome (2026-07-20) |
| --- | --- | --- |
| `workflow/dry_run.py` (286 lines) | Only consumers are the `workflow/__init__.py` re-export and its own unit test; no CLI/API/MCP wiring; the `DRY_RUN` config enum is never compared. | **Deleted.** File, re-export, and `tests/unit/test_dry_run.py` (728 lines) all removed. `DryRunConfig`/`DRY_RUN` enum member left in place — out of scope, not re-verified as dead. |
| claude_cli graph-patch bridge (`claude_cli/agent.py:365,465,716`) | Gated on `context.graph_patch_callback`, set only by graph dispatch — and `SUPPORTED_GRAPH_RUNNER_TYPES` (`graph_driver.py:66`) is `{CODEX_SERVER}`, so the branch cannot execute. Deleting it does **not** foreclose making claude_cli graph-capable — that is Priority 4 below, and it should be built against the current kernel's callback contract, not by resurrecting this incident-era sentinel mechanism. | **Deleted.** Sentinel constant, the 4 payload-extraction helpers, `_graph_patch_bridge_section`, `_submit_graph_patch_sentinels`, and all 4 call sites removed from `claude_cli/agent.py`. `GraphPatchCallback`/`context.graph_patch_callback` themselves are untouched — still real, still used by `codex_server`. Two behavior tests exercising the deleted bridge removed from `test_cli_agent.py` and `test_cli_agent_commit_retry.py`. |
| `callback_channel` knob on codex_server (`codex/agent.py:254,263`) | Assigned to `self._callback_channel`, never read anywhere; `test_codex_server_parity.py` parametrizes both values and proves behavior identical. **Scope note: this deletes only the do-nothing config field. The codex_server runner itself is the supported graph runner and is not in question.** | **Deleted**, full chain: constructor param, `AgentConfigField` entry, `factory.py` extraction. Bigger than "one field" implied: `test_codex_server_parity.py` and `tests/integration/test_codex_server_callbacks.py` were both structured as a REST×MCP parametrized matrix across the *entire* file (prompt parity, callback dispatch, allow-list enforcement) — de-parametrizing both (~470 lines combined) was needed to keep them compiling, not just deleting two assertions. `callback_channel` on **cli_subprocess/claude_cli is a separate, live, unrelated feature** (real REST-vs-MCP prompt branching) — not touched. |
| 3 byte-identical test files (`test_clarification_repository.py`, `test_routine_loading.py`, `test_run_creation.py`) | Identical between `tests/unit/` and `tests/integration/` — copied, not moved, during the W-series reorganization. Keep one canonical copy each (choose by what the test actually exercises). | **Deduped.** All 3 still byte-identical at time of sweep. Each file's own docstring self-declares `"""Integration tests..."""` and exercises a real (in-memory) DB session or multi-component run creation, so the `tests/integration/` copy was kept and the `tests/unit/` copy deleted in each case. |
| 5 diagnostic endpoints (`api/routers/graph.py`: topology, patches, final-blockers, regions, outbox/requeue) | Zero UI/CLI consumers. Decide per endpoint: **wire `final-blockers` and `outbox/requeue` into an operator surface** — they are the W6 operator story and genuinely useful — and delete the HTTP layer for the other three (the projections behind them stay). | **Corrected, not deleted.** The "zero consumers" check only looked at UI/CLI/MCP, the same blind spot 3a's "cheap PR" framing had. `topology`, `patches`, and `regions` are the actual HTTP surface for ~25 assertions across 9 FR-acceptance test files (`test_graph_fr01_fr13_fr18_acceptance.py` through `fr17`, plus `test_graph_api.py`) — e.g. FR-13's "rejected patch must appear in /graph/patches". That is real, load-bearing consumption of the graph kernel's own correctness-verification suite, not a dead path. Given the choice between (a) leaving them, (b) migrating ~25 call sites to call the builder functions directly and losing route-wiring regression coverage, or (c) deleting and stripping the acceptance assertions, the human steer on record was to leave all 5 endpoints as-is and correct the record instead of weakening FR acceptance coverage. `final-blockers` and `outbox/requeue` were never in question (doc already recommended keeping+wiring them). **No code changed for this item; wiring `final-blockers`/`outbox/requeue` into an operator surface remains open, unscoped, product-shaped work.** |

**Benefit.** Dead paths are currently indistinguishable from live ones
without re-deriving the reachability argument, so every reader pays a tax
and the next contributor risks extending a carcass (or the UI keeps offering
a knob that does nothing). After the sweep, "reachable" and "live" mean the
same thing again, and the retirement guard tests remain as the safety net.
~1400 lines left the maintenance surface (dry_run.py + its test, the
claude_cli bridge, the callback_channel chain including two de-parametrized
test files, and 3 deduped test files) — more than the "600+ lines, one PR"
estimate, mostly because dead-test removal wasn't counted in the original
line estimate. Full suite after the sweep: 4892 passed, 3 skipped (down from
4971 pre-sweep — expected, since dead tests were deleted alongside dead
source); ruff and pyright clean.

**Lesson, same shape as 3a's:** "zero consumers" checks that stop at
UI/CLI/MCP will miss a test suite that uses the HTTP layer as its access
path. Grep the test suite before scoping a deletion as cheap — the size of
that blast radius is the real cost, not the size of the source diff.

## 5. Priority 4 — Graph-runner capability contract and a second graph runner — RESOLVED 2026-07-21

**What.** Today a run can *select* four runner types, but the graph carrier
*dispatches* exactly one: `SUPPORTED_GRAPH_RUNNER_TYPES` is the hard-coded
frozenset `{CODEX_SERVER}` (`graph_driver.py:66`). Replace the hard-coded
list with a declared capability: a runner type is graph-dispatchable if and
only if its adapter implements the graph callback contract (patch
submission, submit/grade callbacks, usage reporting). The driver derives the
supported set from declared capabilities instead of naming runners. Then
onboard a second graph-capable runner — claude_cli (via `cli_subprocess`) is
the natural first candidate, implemented against the current kernel's
callback contract; openhands needs a capability assessment first, since its
executor loop never had a graph submit path. `retired` stays structurally
non-dispatchable.

**Evidence (2026-07-18).** The dispatch layer is already runner-agnostic —
`StaticGraphAgentFactory` goes through the generic `create_agent_runner`
registry — so the frozenset is the *only* gate. What the excluded runners
actually lack is the callback channel: claude_cli has only the unreachable
incident-era sentinel bridge (deleted by Priority 3), and the openhands
agent loop (~1,600 lines) predates the graph carrier entirely.

**Benefit.**

1. *Removes a single-vendor operational dependency.* Every graph run today
   rides one runner from one vendor; codex quota exhaustion (already
   observed as spark quota errors) or a codex CLI regression stalls the
   entire graph carrier. A second runner turns that from an outage into a
   routing decision.
2. *Unblocks OQ-1 (verifier model diversity).* The self-preference-bias
   evidence says the verifier should be a different model from the builder,
   and the planned A/B (codex builds / claude verifies) is untestable until
   a second graph-capable runner exists. This feeds directly into the R02/R07
   verification work.
3. *Makes future additions a bounded task.* A written capability contract
   with a definition-of-done (implement these callbacks, pass this conformance
   suite) replaces archaeology through the codex adapter as the onboarding
   path — the same "policy as data" principle the kernel already follows,
   applied to dispatchability.

**Sequencing.** Defining the contract and deriving the set from it is cheap
and can ride the Priority 2 hardening batch. Onboarding the second runner is
real work; Priority 1 (§2) closed 2026-07-20, so the cost-rollup telemetry
this gate was waiting on now exists — the second runner's cost is
measurable from day one and the OQ-1 comparison has real telemetry behind
it. No remaining sequencing blocker; still ranked after Priorities 2–3
because those are cheaper and close known bug classes first.

## 6. Priority 5 — Execution-first verification (research R02)

**What.** Oracle-classify requirements at compile time; feed the verifier
deterministic environment facts and executed-test results before any LLM
judgment; reduce rubrics to one-requirement binary verdicts.

**Benefit.** Verification is the system's product — and it currently leans
on the weakest oracle (LLM judgment) even where deterministic facts and test
execution are available. External evidence says LLM judges flag correct code
as non-compliant and richer prompts make it worse; our own verifier
false-fail rate is unmeasured (OQ-2). Moving authority down the hierarchy
(deterministic facts → executed tests → minimal binary rubric) architects
out both failure directions: false PASS (defect ships) and false FAIL
(revision-loop churn burning agent spend). This is the largest lever on run
*quality*, as Priority 1 is on run *economics*.

## 7. Priority 6 — Eval harness, then revision policy (R07 → R03)

**What.** R07: a 10–20 frozen-task suite with trajectory assertions read
from the event log. Then R03: cap in-place repairs at 2, escalate model tier
with fresh context, emit a typed `revision_exhausted` blocker, and
short-circuit duplicate diffs.

**Benefit.** R07 is the instrument that says whether any change — including
Priorities 1–4 — made runs better; without it every improvement claim is
anecdote. R03 then converts the failure mode observed in incident history
(identical retries burning ~25-minute sessions into the same wall) into a
bounded, typed outcome. The ordering is deliberate: measurement before
policy, because tuning retry caps and escalation targets without R04/R07
data would be guesswork.

## 8. Deliberately deferred (and why)

| Item | Reason |
| --- | --- |
| Legacy disposition/retirement (R08) | No longer blocked on cost visibility (Priority 1 closed 2026-07-20 — cost-rollup API is an independent aggregate, not legacy-only) or on endpoint ambiguity (Priority 3a closed 2026-07-20 — `require_legacy_execution_mode` guard landed on all 13 legacy task routes). Sole remaining blocker: the bidirectional `service.py` ↔ `graph_driver` coupling. The boundary inventory in review §4 P1 #6 remains valid. |
| `isinstance`/`dict[str, Any]` long tail | Down from 526 to 401 guards across the two kernel files post-W5; remaining reduction is per-family opportunistic work, no longer a headline lever. |
| Batch/parallel outbox claiming | Performance only; explicitly split from W6 correctness scope. |
| Polling → event-triggered driver | Explicitly not a prerequisite for anything (guard-retirement ledger); revisit only if drive-loop latency becomes a measured problem. |
| Steering directive (operator context-injection) | Real gap, but product-shaped; belongs to the UI-v2 / JTBD track, not this hardening roadmap. |
| SQLite scaling (OQ-4) | Human steer on record: file-payload removal (W5.5) bought enough headroom for now. |
