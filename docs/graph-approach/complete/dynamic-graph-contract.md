# Dynamic Graph Contract

Frozen contract for the dynamic execution graph. This is the spec the DG-5.1
saga discovered one expensive live run at a time. It is now asserted by:

- `tests/unit/test_graph_dynamic_contract.py` — table-driven kernel rules.
- `tests/integration/test_graph_dynamic_e2e.py` — deterministic, in-process,
  scripted-runner end-to-end runs (zero LLM, runs in CI).

**Rule of engagement:** a new failure found by a live run must be reproduced as
a case in one of those two files *before* it is fixed. Do not debug the dynamic
carrier by spending tokens on live runs; spend them only on the final
comparison.

---

## 1. Canonical output ports and record kinds

The dispatch executor synthesises every output record from the node kind/role at
submit time (`graph_runtime/dispatch.py:_output_records_for_submit`). A scripted
runner only has to call the callbacks; it never hand-builds records.

| Node kind / role            | Trigger                         | Output port(s)                                  | record_kind / matchers                          |
| --------------------------- | ------------------------------- | ----------------------------------------------- | ----------------------------------------------- |
| worker (any role)           | `on_submit()`                   | `candidate`                                      | record_kind `output`, port `candidate`          |
| verifier                    | `on_grade(...)` + `on_submit()` | `verification_report`                            | record_kind `verification`, verdict pass/fail   |
| check / invariant_gate      | `on_submit()`                   | `check_result`                                   | record_kind `output`, port `check_result`       |
| planner role `gap_planner`* | accepted non-empty patch + submit | `gap_plan`, `gap_classification`, `classified_gap` | value.milestone_kind `gap_analysis`          |

\* The gap records are emitted **only** after the gap planner has an accepted
patch with non-empty `ops` (`_accepted_graph_patch_had_ops`). A gap planner that
plain-submits without an accepted non-empty patch emits nothing and starves its
corrective successors.

**Edge selector matching** (`graph/commands.py:_record_matches_selector`): a
record binds an edge if `accepted_record_selector.record_kinds` intersects
`{record_kind, schema, port, value.milestone_kind}`. So the selector
`{"record_kinds": ["candidate"]}` binds a worker output via its **port**
`candidate`; `["gap_analysis"]` binds a gap record via `value.milestone_kind`.
Use the verifier output port `verification_report` (not the alias
`verification_result`).

## 2. Required edges per dynamic region (patch validation)

`graph/patch_validator.py:validate_patch` rejects structurally unsafe patches.
The dynamic-region dependency rules (`_validate_dynamic_region_dependencies`):

- A created **`gap_planner`** node requires a required, selector-bound incoming
  edge on `verification_evidence` / `verification_report`.
- A created **corrective worker** (role `fixer`, or id/region containing
  `corrective`) requires a required incoming edge on `classified_gap` — **unless
  the patch actor is itself a `gap_planner`** (its patch *is* the classification).
- A created **`invariant_gate` check** requires a required incoming edge on
  `verification_evidence` / `verification_report`.

An edge only counts toward these rules if `required` is not `false` **and** it
carries an `accepted_record_selector` dict.

## 3. Check command requirement

A created `check` node must carry one of (`_validate_check_command`):

- a dict `command_definition`, or
- a non-empty string `hidden_oracle_command`, or
- `command_binding: "dynamic_feature_hidden_oracle"` (resolved at apply time
  from `routine-snapshot.dynamic_feature.hidden_oracle_command`).

The hidden-oracle command string is kept out of planner packets/prompts; planners
reference it only through the opaque binding (DG-5.2b).

## 4. Role authority

`ALLOWED_BY_ROLE`: `planner` and `gap_planner` may use all `PLANNER_OPS`
(everything except `create_gate`). Additional `gap_planner` restrictions:

- cannot create a `planner` successor node;
- executable nodes (`worker`/`verifier`/`check`) it creates must target
  `task_region_id == "corrective_work_region"`;
- cannot `retire_node` an executable node;
- a **no-op patch (`ops: []`) is rejected** while a required `classified_gap`
  successor edge from the gap planner is unsatisfied
  (`_validate_gap_planner_no_op`).

Per-runner tool exposure: `submit_graph_patch` is exposed to planner nodes whose
role is `planner` **or** `gap_planner` (`_can_submit_graph_patch`). Both the
Codex Server and Claude SDK/CLI runners must expose the tool to both roles and
accept `ops: []`.

## 5. Submit discipline

`_requires_graph_patch_before_submit` (planner + gap_planner): plain `on_submit()`
is rejected unless the node has an **accepted** `submit_graph_patch` first. A
merely *rejected* patch is not enough — the node must submit a corrected patch
(DG-5.1p). A non-gap planner that already has an accepted patch but dies without
plain-submit is completed, not re-leased for duplicate writes (DG-5.1m).

## 6. Lease recovery

A graph runner that returns without calling `on_submit` records
`agent_died("agent exited without submit")` and the lease is recovered/retried;
it must never leave an active lease and quiesce silently (DG-5.1d). Runner
rate-limit errors transition the node to `failed` with trigger
`agent_rate_limited` rather than being treated as retryable process death
(DG-5.1o).

## 7. Task-region acceptance — the completion footgun

This is the trap that the per-purpose horizon-template region names invite, and
it blocks completion silently.

`final_invariant_blockers_for_events` blocks completion while **any** task region
is not `accepted`. A task region's set is the union of every node's
`task_region_id` plus regions that own candidates/gates/leases
(`_derive_task_states`). A region is `accepted` **only** if it owns a candidate
whose verifier verdict is `passed`.

Therefore:

- A verifier, planner, gap planner, or check given its **own distinct**
  `task_region_id` creates a region that owns no candidate and is **pending
  forever** → the run can never complete.
- Group a worker with the verifier(s) that grade its candidate under **one**
  `task_region_id`. Planner/gap-planner nodes either share that region or carry
  no `task_region_id`. Corrective `worker`/`verifier`/`check` share
  `corrective_work_region` (required by §4); that region reaches `accepted` via
  the corrective worker's candidate.

The standard horizon templates parameterise `region_id`; instantiate them with a
**single shared** id for one feature's worker+verifier+gap, and
`corrective_work_region` for the corrective set. Do not use the purpose names
(`implementation_region`, `validation_region`, …) as distinct `task_region_id`s.

## 8. Final completion invariants

`project_run_state` stays `active` (lifecycle `complete` is refused) while any of
these hold (`final_invariant_blockers_for_events`): pending planner/gap nodes,
pending planner-generation-budget gate, **pending `check` nodes** (so a final
invariant check that is merely input-bound does not let the run complete —
DG-5.1t), open proposals, suspect active nodes, stale/unsupported active
requirement evidence, unresolved authority revisions, blocked must/expected
requirement nodes, and any non-`accepted` task region (§7).
