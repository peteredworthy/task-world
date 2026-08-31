# Reliable plan execution progress ledger

Source contract:
[`reliable-plan-execution-contract.md`](reliable-plan-execution-contract.md).
Slices 1 and 5 were completed before this ledger. This ledger controls the
remaining Slice 2, 3, 4, and 6 work. A row is validated only when both a
product-real graph path and supporting regression evidence exist.

Baseline (2026-08-28):

```text
uv run pytest -q -n 0 tests/unit/test_graph_dynamic_contract.py \
  tests/unit/test_graph_models.py tests/unit/test_graph_planner.py \
  tests/unit/test_graph_dispatch_on_output.py \
  tests/integration/test_graph_planner_flow.py \
  tests/integration/test_graph_read_models.py
223 passed, 2 deselected
```

## Reconciled validated status (2026-08-28)

This section supersedes the original status/remaining-gap cells below for the
named rows. The original cells are retained as the pre-implementation baseline.

| Rows | Status | Product-real proof | Regression/static proof |
|---|---|---|---|
| S2.1-S2.4 | validated | Production compiler/controller/callback/scheduler paths rejected malformed or unauthorized declarations, missing artifact bytes, rejected artifact authority, and mismatched semantic verification; valid declared stored artifacts and exact artifact/requirement citations were accepted, and passing plan verification unlocked the declared consumer. | Standards-compliant JSON Schema validation covers routine and planner boundaries plus content constraints; independent QA passed 44 focused configuration/semantic/controller tests after the final correction. |
| S3.1-S3.4 | validated | Production patch/scheduler/final-gate paths require accepted plan/report evidence, authoritative plan-amendment lineage, distinct batch regions, batch worker/check/verifier topology, exact bound reports, and final audit co-binding. Tag-only/global evidence and fake amendment IDs were rejected. | Independent conformance passes exercised the previously failing cases; staged/final runner regressions passed 38 tests with 9 credential/shape deselections, and the broader semantic/runtime suites remained green. |
| X.0 | validated | Production worker and corrective-worker prompt assembly rendered exact bound evidence; a 50k record was truthfully reported `truncated` and a later absent record `omitted`, with corrective inputs pinned to immutable failed verification/check/gap IDs and shared provenance. | Independent QA passed a 463-test semantic/controller/dispatch/command/projection selection (1 deselected); boundary, Ruff, and Pyright passed. |
| S4.1-S4.4 | validated | Persisted controller/scheduler scenario: S0 baseline; C1/S1 passed; C2/S2 failed; later `latest_accepted` leased S1 despite tick S2; rejected-candidate correction leased S2; accepted-region correction leased S1; verifier `candidate_under_test` leased S2. Actual node/region summaries exposed accepted S1, current/rejected S2 and preserved failed report `vr2` after rebuild. | Independent QA: 78 integration tests, 770 projection-closure tests, boundary script, Ruff, and Pyright all passed. |
| X.1 snapshot fields | validated | Actual durable node-detail summary and archival region readback expose declared/resolved base selection plus accepted/current/rejected snapshot authority before and after rebuild. | Included in the S4 product scenario and 78-test read-model/API matrix. |
| S6.1 | validated | The canonical `fff4f6b7` manifest is executed by the production controller/scheduler/dispatch/read-model scenario runner. Server-side qualification derives its receipt only after all required scenarios 1-10 produce accepted observations; caller-supplied results, JSON, and copied models cannot authorize it. | Independent QA passed the canonical qualification/semantic gate (17 tests) and the selected implementation/recovery/startup suite (751 tests). |
| S6.2 | blocked | The API/live harness creates separate Luna and alternate-model arms with independent planner, discovery, implementation, correction, successor-planner, and verifier assignments, waits for terminal readbacks, and extracts results. The actual credentialed runs were not executed because no authorized server/routine/repository/runner environment was available, and repository policy forbids starting the server without explicit user authorization. | Harness collection and preflight passed; the live test skipped once with its exact missing-environment condition instead of fabricating evidence. |
| S6.3 | validated | `POST /api/runs/reliable-plan-qualification` runs the canonical product-path suite and issues an opaque single-use `rpq_…` grant. Run creation atomically binds it, runtime revalidates the binding, the first successor horizon consumes the capability, a second horizon is rejected, and the selected successor model reaches the production agent factory. Unknown, reused, copied, and self-attested grants are rejected. | Independent adversarial QA passed 17 focused tests, confirmed horizon exhaustion and model override consumption, and found no remaining defect. |
| S6.4 | blocked | The comparison artifact and production event extractor cover correctness, revisions, graph shape, batches/horizons, token/action/duration use, infrastructure/retry/recovery, and lease state across Luna, alternate, and legacy arms. A real three-arm comparison artifact remains unavailable for the same live-environment blocker as S6.2. | Metric/comparison tests are included in the 751-test selected gate; strict arm/run/result identity and computed deltas are validated. |
| X.1 remaining semantic fields | validated | Durable node and region readbacks expose objective, work mode, scope, bound requirements/artifacts, batch/check/verifier obligations, readiness and correction reason, horizon, usage/hydration, and snapshot authority; disconnected or semantically incomplete regions remain visible through public read models and after rebuild. | Independent checkpoint/replay/projection/API/readback closure passed 974 tests. |

Final repository gate (2026-08-28):

```text
uv run pytest
5577 passed, 5 skipped, 4 warnings

uv run ruff check .
All checks passed!

uv run pyright
0 errors, 0 warnings, 0 informations

uv run python scripts/check_graph_projection_boundaries.py
exit 0
```

The five default-suite skips are environment-gated tests. The reliable-plan live
evaluation skip is intentionally retained as blocked evidence for S6.2/S6.4;
no live model result or comparison was inferred from deterministic execution.

| ID | Functional behavior and acceptance invariant | Current evidence | Product-real proof required | Regression evidence required | Status | Remaining gap |
|---|---|---|---|---|---|---|
| S2.1 | A run or authorized planner can declare a versioned semantic-artifact schema; declarations are accepted graph inputs and cannot be silently weakened. | Generic typed record metadata and artifact references exist, but no run-scoped semantic schema authority exists. | Compile/seed a production dynamic routine with schema declarations, then inspect accepted graph records. | Model/config/compiler and replay/codec tests. | not started | Add declaration model, canonical accepted record, compilation/projection/query support, and amendment authorization. |
| S2.2 | A semantic-artifact envelope preserves semantic role, schema identity/version, producer/port, inline content or artifact reference, provenance/source records, requirements/region, validation, and authority/supersession. Content validates against the declared schema. | `ArtifactReferenceRecord` references files but is not the required semantic envelope. | Submit a declared discovery artifact through the normal callback/record-acceptance path and read it back. | Positive/negative model, command, replay, flexible-JSON, and compatibility tests. | not started | Add envelope and declaration-aware acceptance validation. |
| S2.3 | A discovery macro creates a read-only discovery worker whose output uses a supplied declared artifact schema. | Generic `create_work_region` and a discovery prompt template exist. | Apply the macro through the normal planner patch command and inspect authority/output contract. | Macro, patch-validator, and analysis-only authority regression tests. | partial | Add typed macro and enforce schema/authority linkage. |
| S2.4 | A plan-verification macro binds discovery artifact plus requirements, and implementation cannot become ready until a passing verification report explicitly evaluates that artifact. Generic candidate/file state cannot substitute. | Generic verifier edges/readiness exist; no semantic plan-verification invariant exists. | Drive discovery artifact acceptance, plan verification fail/pass, and scheduler readiness through production graph commands. | Patch invariant, selector compatibility, scheduler, and E2E tests. | not started | Add artifact-aware selectors/ports, verification binding, and implementation dependency invariant. |
| S3.1 | A successor-planner macro consumes an accepted plan or accepted batch report and represents one planning horizon. | One-successor planner plumbing and generation budgets already exist. | Apply a successor-planner macro after accepted plan evidence and observe readiness/binding. | Macro, patch validation, prompt, and planner-flow tests. | partial | Add semantic accepted-plan/batch inputs and horizon metadata. |
| S3.2 | Every declared implementation batch is a distinct task region; collapsing batches requires an accepted plan amendment. | Task-region IDs exist, but no declared-batch authority or collapse invariant exists. | Apply a multi-batch plan artifact and show one-region collapse rejected while distinct regions are accepted. | Structural invariant and regression scenario 3 tests. | not started | Project declared batches/amendments and validate created regions. |
| S3.3 | Every effectful batch has deterministic checks and an independent verifier bound to its candidate, requirements, and check evidence. | Generic work/check/verifier macros exist but do not enforce the complete batch shape. | Apply a batch macro and drive its worker/check/verifier records through the scheduler. | Macro/topology/readiness/E2E tests. | partial | Add batch macro and semantic invariant. |
| S3.4 | Final-gate readiness requires every declared batch verification plus final audit; missing evidence blocks completion. | Generic final invariant logic exists. | Drive a two-batch graph to the final gate, proving each missing batch/audit blocks and complete evidence passes. | Final-gate regression scenario 8 and replay tests. | partial | Bind final gate to declared batch set and audit record. |
| S4.1 | Each task region exposes accepted and candidate snapshot identities. Effectful work produces a candidate based on its explicit base selection. | Lease/callback/file-state snapshots exist; region authority is not modeled. | Execute an effectful worker and inspect region snapshot authority before and after verification. | Projection/query/read-model/replay/immutability tests. | not started | Add region snapshot projection and authoritative transitions. |
| S4.2 | Passing verification advances the accepted snapshot; failure preserves a rejected candidate without advancing authority. | Candidate/verdict projection exists, but filesystem snapshot authority is implicit. | Submit pass and fail verification callbacks and inspect accepted/candidate/rejected identities. | Command/reducer/every-split replay tests. | not started | Add typed snapshot-authority events or derive immutable authority from accepted records/verdicts. |
| S4.3 | Later regions default only to the latest accepted snapshot; corrective work explicitly chooses rejected candidate or accepted snapshot. | Node `base_snapshot_id` override exists but no regional selection contract. | Schedule a later batch after failed and passed candidates and inspect the granted lease base. | Scheduler/dispatch regression scenario 7 tests. | not started | Validate `base_snapshot_selection`, resolve it deterministically, and reject silent failed-candidate inheritance. |
| S4.4 | Failed candidates remain inspectable evidence in operator read models. | Failed candidate records remain in projection, but snapshot authority/readback is incomplete. | Read node/region APIs after a failed candidate and see rejected snapshot plus acceptance status. | API/read-contract tests. | partial | Extend public projection queries and API read models. |
| X.0 | Worker and corrective dispatch prompts contain the substantive bound records, including exact grades/check failures and accepted gap analysis; prompt summaries report what was hydrated, summarized, or omitted. | Slice 1 records prompt-hydration summaries and worker contracts, but read-only inspection found worker prompt rendering does not include all bound record payloads and the corrective macro binds only gap classification. | Capture production worker/corrective dispatch packets and match the exact record IDs and payloads against the operator prompt summary. | Prompt/dispatch tests for inline, summarized, artifact-reference, tool-only, grades/check tails, and omissions. | partial | Render the bounded evidence packet for worker-like nodes and bind exact correction evidence. |
| S6.1 | The `fff4f6b7` failed run shape is a durable deterministic regression scenario covering all ten required regressions. | Incident ID appears in implementation comments/docs, not a scenario fixture. | Run the scenario via the production graph compiler/controller/scheduler interfaces. | Dedicated deterministic integration scenario plus focused unit tests. | not started | Add fixture/harness and assertions. |
| S6.2 | The same deterministic graph skeleton can run with Luna workers and independently configured alternate worker/verifier models. | Runners/models are configurable, but no reliable-plan evaluation fixture/report exists. | API-created graph runs for both configurations, with run IDs and terminal evidence. | Deterministic harness remains the non-credential regression gate. | not started | Add evaluation configuration/metrics artifact; execute when runners/credentials are available. |
| S6.3 | One-horizon Luna planning is enabled only after deterministic skeleton execution passes. | No capability gate tied to this scenario exists. | Show deterministic qualification record gates successor-planner authority. | Qualification/gating tests. | not started | Add explicit evaluation/qualification representation or document operator-controlled gate. |
| S6.4 | Evaluation compares correctness, revisions, graph shape, token use, and recovery with the legacy baseline. | Existing carrier metrics cover some graph facts. | Produce a comparison artifact from real run event streams. | Metrics extractor tests. | partial | Extend/reference metrics and record current run evidence without fabricating unavailable model runs. |
| X.1 | Operator read models expose objective/mode/scope, bound requirements/inputs, outputs/checks, accepted/candidate snapshots, readiness/correction reason, horizon, and usage/hydration summaries. | Slice 1 exposed worker/prompt data; snapshot/horizon/semantic authority fields are absent. | Inspect graph node/region APIs for the deterministic scenario. | API/read-contract matrix tests. | partial | Extend node/region read models for new semantics. |

## 2026-08-31 addendum: mandatory topology gate

The 29 Aug live-run incident audit
([`reliable-plan-live-run-instruction-audit-2026-08-29.html`](reliable-plan-live-run-instruction-audit-2026-08-29.html))
found that after the 30 Aug tool-exposure fix (`f87ceba8d`), reliable-plan
authorization still constrained only successor authority, not the complete
patch shape: a no-successor patch bypassed the check, a successor-only patch
could satisfy it, and an unstaged broad implementation patch could still be
accepted. The routine also declared no versioned semantic artifact schemas.

Commit `36424b1e8` closes this gap:

- `_validate_reliable_plan_topology` in `patch_validator.py` now validates the
  horizon-0 skeleton atomically: exactly one read-only discovery node, one
  independent plan verifier, one successor planner, no effectful work, the
  successor bound to the verifier's *passed* `verification_report`, and no
  extra dispatchable nodes (generic worker or oversight) admitted alongside
  the three.
- Effectful batches are rejected unless proposed by a `successor_planning`
  node and bound to a durably passed `verification_report` whose
  `evaluated_record_ids` cite the exact accepted plan artifact the batch
  consumes (`unverified_exact_plan_lineage`).
- `routines/dynamic-graph-feature/routine.yaml` declares
  `reliable-plan-implementation-plan@1` as a versioned
  `semantic_artifact_schemas` input.

Product-real proof: `validate_patch` (the function the real patch command
calls) rejects successor-only patches with
`violation == "missing_or_ambiguous_discovery"`, rejects extra dispatchable
nodes atomically, and rejects effectful batches proposed by non-successor
nodes (`unauthorized_effectful_proposer`) or lacking exact plan lineage. The
compiler and S6.3 qualification path (`reliable_plan_qualification.py`) are
the only production writers of `reliable_plan_skeleton_id` /
`reliable_plan_one_horizon_authorized`, so the gate is live on every
reliable-plan run, not just test fixtures.

Regression evidence: `uv run pytest` 5616 passed, 5 skipped (pre-existing,
unrelated: git-snapshot UTF-8 filename test and 4 docker-agent
environment-gated tests). `ruff check .`, `uv run pyright`, and
`scripts/check_graph_projection_boundaries.py` all clean.

Remaining gap per the audit: S6.2/S6.4 (live Luna and alternate-model graph
arms) are still `blocked` — no rerun has been attempted since this fix
landed. That is the next chunk.

## 2026-08-31 addendum 2: bounded live rerun — gate confirmed live, no clean pass

Ran a bounded live rerun against `36424b1e8` rather than replaying the full
`fff4f6b7` scenario (two prior full replays cost 1.5–10.8M tokens per arm and
both failed for reasons since fixed). Built a small synthetic scenario — a
throwaway two-file "remove the legacy pricing path in 2 batches" task in a
scratch repo (`pricing-widgets`, not task-world), driven through a fresh
scratch server (isolated DB, isolated port, isolated repos dir), using the
real production controller/scheduler/patch-validator/dispatch path and real
`codex-cli 0.144.1` sessions (`gpt-5.6-luna` graph arm,
`comparison-feature-single-agent` legacy arm). Evidence:
`/private/tmp/reliable-plan-e2e-20260831-212409/reliable-plan-live-rerun-result.json`.

**The mandatory-topology gate held live.** The Luna planner proposed roughly
20 horizon-0 patches over the run; `graph_patch_rejected` events include two
direct hits on the new invariant (`"reliable-plan initial skeleton requires
exactly one analysis-only discovery node"`, `"...requires exactly one
independent plan verifier"`) plus a long tail of edge/port/schema rejections
from the pre-existing typed-edge and semantic-stage validators. The planner
eventually produced an **accepted** atomic horizon-0 skeleton (discovery +
plan verification + successor planner nodes all created together, no
effectful work) — direct live proof the gate is satisfiable, not just
restrictive.

**Neither arm reached a clean pass — but not because of the gate.** Root
cause, found by inspecting both worktrees directly: the scratch target repo's
`pyproject.toml` declared no `pytest` dependency and had no `uv.lock`, so
`uv sync --frozen` (run unconditionally per worktree by
`git/worktree.py:_create_worktree_venv`) never installed `pytest` into either
worktree's `.venv`. The `acceptance_command` (`python -m pytest -q`) could
therefore never pass regardless of code correctness. The **legacy arm's
actual code fix was correct** — `widgets/api.py` was rewired to
`widgets.core.compute_price` and `widgets/legacy_shim.py` was deleted, both
batches done right — but it never received a passing acceptance signal, so
it kept retrying: 631 actions, 10.4M read / 233K write tokens over ~67
minutes before I cancelled it as a runaway (this is a scenario-construction
defect, not a legacy-vs-graph finding). A first attempt at this same
scenario also hit an unrelated real infra finding before the `.gitignore`
fix below: the graph's pre-flight file-state boundary rejected
`.venv/bin/python*` (symlinks to the shared uv toolchain cache, outside the
worktree) as `repo_escape`, killing the planner before dispatch, because the
scratch repo's root `.gitignore` — unlike task-world's own — didn't list
`.venv`. Adding one fixed it; this is worth a permanent regression note but
was not investigated further as a product change (out of scope for this
chunk).

The Luna graph arm, after landing the accepted skeleton, stalled: `paused` /
`graph_blocked`, quiescent with `worker-pricing-plan-discovery` reporting
`missing_required_input:requirement_1` even though the source requirement
node shows `completed`. Not yet root-caused — could be the documented
"graph quiescent pauses need an explicit `runs resume`" behavior
([graph-run ops gotchas](project_graph_run_ops_gotchas.md)) rather than a
new defect; not resolved before the scratch environment was torn down.

**S6.2/S6.4 status: still `blocked`**, now for a different, narrower reason
than before — not "no environment available," but "no clean 3-arm pass yet
obtained; the one blocking factor identified (missing pytest dependency in
the synthetic scenario) is fixable and worth a supervised rerun using either
a real `uv.lock`-backed scratch repo or the real `fff4f6b7` scenario once
budget is authorized." The mandatory-topology gate itself has product-real
live evidence and does not block on this.

Runs (scratch server, torn down after this evidence was collected):

| Arm | Run ID | Status | Actions | Tokens (read/write) |
|---|---|---|---:|---|
| Luna graph | `a57f4e62-1396-4be2-a05b-316070c5df1f` | `cancelled` (was `paused`/`graph_blocked`) | 70 | 3.74M / 48.7K |
| Legacy baseline | `aaf615d8-dd23-47d9-8f8f-cbb7e3793182` | `cancelled` (runaway, correct code, unrunnable oracle) | 631 | 10.43M / 233K |

## Validation policy

- Focused tests support each row but do not by themselves validate it.
- Product-real proof uses the production compiler, patch command, controller,
  scheduler, dispatch packet, and API/read-model surfaces as applicable.
- Live model evaluation rows remain `blocked` rather than being marked valid if
  runner availability or credentials are absent; deterministic execution and
  evaluation tooling must still be complete.
- After each builder/validator pass, update the affected rows with exact
  commands, run/record IDs, and remaining gaps.
