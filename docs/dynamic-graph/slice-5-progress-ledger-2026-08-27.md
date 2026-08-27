# Slice 5 progress ledger — recovery semantics

Durable state for the `mind-the-gap` loop implementing the
"Slice 5 target: recovery semantics" section of
`slice-1-and-5-target-2026-08-27.md`. Updated after every validated chunk.

**Baseline at loop start.** Branch `slice-5-recovery-semantics`, freshly
branched from `main` at `c52362c0d` ("test(graph): close admission-to-prompt
seam, complete Slice 1"). Full suite measured by this planner on this branch:

```
uv run pytest tests/ -q -n auto --dist worksteal
5513 passed, 5 skipped, 4 warnings in 45.39s
```

## Verified chunks

- **Chunk 1 — Typed `FailureClass` on the failure-record path.** Additive
  `failure_class: FailureClass | None` on `FailureRecordValue`; `error_class`
  untouched. `_failure_record_payload` gained a non-defaulted keyword-only
  `failure_class` param; all 4 current call sites pass
  `"infrastructure_failure"` (correct — the other two classes have no
  producer yet, deferred to chunk 4). Independent Validator confirmed by
  EXECUTION, not just reading: (a) omitting `failure_class` raises
  `TypeError: missing 1 required keyword-only argument`; (b) a legacy
  payload with `error_class` set and no `failure_class` key survives the
  real `reduce_event` reduction path unchanged, `failure_class` lands
  `None`; (c) an unknown `failure_class` value raises `ValidationError`.
  `record_id` derivation unchanged. Full suite **5518 passed, 5 skipped**
  (5513 + 5 new tests, zero regressions), schema version 15 unchanged,
  ruff/format/pyright clean.

This — not the target doc's stale **5454** (which predates Slice 1's six
chunks) — is the regression baseline every Slice 5 chunk must preserve.
`PROJECTION_CHECKPOINT_SCHEMA_VERSION = 15` (`graph/projection_codec.py:40`);
no chunk below is expected to change it.

Source incident: failed dogfood run `fff4f6b7-bf33-475f-8280-31ff5e1ef7ca`.
Diagnosis: `reliable-plan-execution-contract.md` §7 ("Make callback and lease
recovery conclusive") — *"rapidly recreating the same execution against the
same repository state is not recovery."*

---

## Verified facts from planning pass 1 (2026-08-27)

Established by reading `c52362c0d`. A Builder may rely on these without
re-deriving them. Line numbers are as of `c52362c0d`.

### A. What `80d74390f` actually did (read the diff, not the message)

The target doc says lease revocation "was hardened in `80d74390f`". Read in
full (`git show 80d74390f`, 13 files, +913/-96), that commit did **four**
things, none of which is failure classification and only one of which touches
lease conclusiveness — and that one covers a *different* path than the one
Slice 5 is about:

1. **Lease TTL unification and proactive renewal.** New shared constant
   `MANAGED_LEASE_TTL_SECONDS = 3600` (`graph_runtime/dispatch.py:118`), used
   by both the runner's start heartbeat (`dispatch.py:1068`) and the driver's
   `schedule_tick` (`graph_driver.py:835`). `_renew_running_expired_leases`
   was renamed to `_renew_running_leases_near_expiry`
   (`graph_driver.py:1072`) and now renews leases within
   `MANAGED_LEASE_RENEWAL_LEAD_SECONDS = 60` of expiry
   (`graph_driver.py:72`) rather than after expiry, and is called *before*
   the schedule tick as well as after the wait (`graph_driver.py:815`,
   `graph_driver.py:860`). **Effect: a demonstrably-live runner no longer
   loses its lease to a boundary race.** This is availability hardening; it
   makes spurious missing-callback events rarer but says nothing about what
   happens when a callback is genuinely missing.
2. **Server-shutdown lease revocation.** New
   `apply_graph_server_shutdown_pause` (`graph_driver.py:204`) walks
   `snapshot.active_leases`, issues `agent_died` with
   `reason="server_shutdown"` for each, and only then records the recoverable
   row pause; `SignalConsumer.stop()` marks its runs
   (`workflow/signals/consumer.py:92`, `:122`) so the driver's
   `CancelledError` handler runs it (`consumer.py:704-723`). **This is a
   conclusive revocation path — for server shutdown only.** It is *not*
   reached by the missing-callback / orphaned-execution path Slice 5
   targets.
3. **Forensic diagnostic before recovery.** `_record_managed_runner_error`
   (`dispatch.py:900`) persists an `AgentErrorEvent` carrying the original
   transport exception before recovery mutates the attempt; `AgentErrorEvent`
   gained `node_id` / `execution_id` (`workflow/events/types.py:191-193`).
   This is a free-form `error_type`/`error_message` string pair on the
   *legacy workflow* event stream — it is **not** a graph `FailureRecord`,
   carries no class, and is not read by any recovery decision.
4. **Reconciliation deadlock fix + logging.** `reconcile_execution_attempts`
   classifies current-runtime owners before taking
   `_worktree_execution_lock` (`dispatch.py:660-676`), plus ~8 new
   `logger.info` breadcrumbs in the drive loop.

**Conclusion — what `80d74390f` did NOT do, i.e. the real Slice 5 gap:**

- It introduced **zero** failure classification. Repo-wide, the commit adds no
  new `error_class` value and no typed class of any kind.
- It did **not** make missing-callback lease revocation conclusive. Fact D
  below shows the exact surviving state where a paused run reports an active
  lease with no callback and no pending recovery action — and fact E shows an
  existing test that *pins that state as expected behaviour*.
- It did **not** touch the retry decision. Fact C shows the retry still
  reuses the same base snapshot with no stated rationale.

So: nothing in Slice 5's four acceptance criteria is already satisfied.
Criterion 3 is *partially* satisfied for one unrelated trigger
(server shutdown). Everything else is unbuilt.

### B. What `error_class` actually is today

1. **`FailureRecordValue.error_class` is a free `str`**
   (`graph/models.py:2442`), on a `StrictNestedModel` (`extra="forbid"`,
   `models.py:107-110`). Sibling `phase` (`models.py:2441`) is also a free
   `str` and is `"runtime"` at every emission site.
2. **The target doc's claim that `"verification_failure"` appears once at
   `graph/scheduler.py:408` is true but misleading — that literal is a
   *port name*, not an error class.** It sits in
   `_upstream_failure_allowed` (`scheduler.py:403-410`), in the set
   `{"failed_verification", "verification_failure", "failed_candidate"}` of
   `edge.to_port` values a node may consume from a failed upstream. It has
   nothing to do with `error_class`, leases, callbacks, or recovery.
   **Do not treat it as prior art for the enum; do not rename it.**
3. **`error_class` has exactly four production values, all produced by one
   helper.** `_failure_record_payload` (`graph/_commands.py:4335`) is called
   from exactly four sites:
   | site | `error_class` | `retryable` | node outcome |
   |---|---|---|---|
   | `_commands.py:4171` (`_apply_agent_died`, rate-limit branch) | `agent_rate_limited` | `False` | `failed` |
   | `_commands.py:4210` (`_apply_agent_died`, non-retryable-runtime branch) | `runtime_configuration_error` | `False` | `failed` |
   | `_commands.py:4251` (`_apply_agent_died`, attempts-exhausted branch) | `max_attempts_exhausted` | `False` | `failed` |
   | `_commands.py:5511` (`_expired_lease_events`) | `lease_expired_without_callback` | `False` | `failed` |
   All four are infrastructure-class. `infrastructure_failure` and
   `invalid_plan_failure` appear **nowhere** in `src/` or `tests/`.
   Test-only values also exist in journal fixtures (`agent_error`,
   `process_exit`, `lease_expired`) — see fact B5.
4. **Three failure paths emit no `FailureRecord` at all**, which is why the
   enum currently looks degenerate:
   - **The retryable `agent_died` branch** (`_commands.py:4276-4332`) emits
     `agent_died` + `lease_revoked` + `runtime_retry_scheduled` +
     a `RecoveryPlan` record + `node_state_changed`, but **no
     `FailureRecord`**. The single most common infrastructure failure is
     therefore unclassified and unrecorded.
   - **`handle_complete_runner_recovery`** (`graph/commands/boundary.py:580`,
     the durable managed-runner path) emits `runner_recovery_completed` +
     `lease_revoked` (`boundary.py:635-646`) and then either
     `node_state_changed→completed`, `→failed` (max attempts), or
     `runtime_retry_scheduled` + `→ready` (`boundary.py:648-701`) —
     **no `FailureRecord` and no `RecoveryPlan`**. The two recovery paths are
     asymmetric in what typed records they leave behind.
   - **Graded verification failure** (`_commands.py:1754`, emits
     `verification_failed`) and **plan/patch rejection**
     (`_commands.py:2388`, `:2402`, emit `graph_patch_rejected`) produce no
     `FailureRecord` either.
5. **`error_class` cannot be retyped to a `Literal` without breaking
   replay.** `graph/projections.py:1473-1479` looks up
   `OUTPUT_RECORD_MODELS_BY_TYPE` (`models.py:2695`, entry
   `"failure_record": FailureRecord` at `models.py:2707`) and calls
   `record_model.model_validate(event.payload)` on **every** historical
   `output_record_accepted` event during every projection rebuild. Journals
   and test fixtures already contain `error_class` values outside any
   candidate enum: `tests/graph_fr17_fixture.py:185` (`agent_error`),
   `tests/unit/test_graph_models.py:303` (`process_exit`),
   `:1589`/`:1613` and `tests/unit/test_output_record_event_payloads.py:181`
   (`lease_expired`), plus live `orchestrator.db` histories. Narrowing the
   existing field in place would make those journals unreplayable.
   **Therefore the typed class must be an additive field.** (Same reasoning,
   same conclusion, as Slice 1 chunk 2's `access_mode` decision.)
6. **`Literal[...]` classification fields are the established house
   pattern**, so a `FailureClass` alias is idiomatic, not novel:
   `LeaseProjectionState: TypeAlias = Literal[...]` (`models.py:777`),
   `CheckResultValue.classification: Literal[...]` (`models.py:1888`),
   `GapClassificationValue.classification: Literal[...]` (`models.py:2095`),
   `EnvironmentFailureProjection.classification` (`models.py:1990`).
7. **Nothing consumes `FailureRecord`s today; they are write-only.** The
   `recovery` node contract declares a `failure_record` input port
   (`graph/contracts.py:1038`) and agent nodes declare an
   `outstanding_failures` input port (`contracts.py:654`), but the planner
   packet that fills `outstanding_failures`
   (`graph_runtime/prompts.py:914 _planner_outstanding_failures`, wired at
   `prompts.py:730`) reads **only** `environment_failures_view` — never
   `FailureRecord`s. **Consequence: adding a field to `FailureRecordValue`
   has no prompt-surface blast radius**, and conversely a Builder must not
   assume a classified record reaches any agent without new wiring.
8. **No payload-registry edit is needed for fields inside the record
   `value`.** The `output_record_accepted` spec
   (`graph/payload_registry.py:298-305`) retains `value` wholesale in its
   `projection=` string, so a new key nested under `value` survives both the
   live-append and the SQLite-rebuild paths automatically. (Contrast Slice 1
   chunk 1, which added *top-level* `node_created` keys and did need the
   registry edit.)

### C. Criterion 2 — the retry decision states nothing, and reuses the same snapshot

1. **`RecoveryPlanValue`** (`models.py:2470-2476`) is
   `action: Literal["retry","supersede","cancel","cleanup"]`,
   `responsible_actor: str`, `graph_changes: list[dict]`, `reason: str|None`,
   `retry_after_seconds`, `retry_not_before`. There is **no snapshot field
   and no field expressing why a repeat attempt should behave differently.**
2. **`_recovery_plan_record_payload`** (`_commands.py:4377-4411`) fills
   `reason` from the death reason (e.g.
   `runtime_execution_missing_no_callback`) and `graph_changes` with a single
   `set_node_state` op. That is the entirety of the recorded rationale.
3. **The retry provably reuses the same repository state.** The driver passes
   a constant `"base_snapshot_id": "routine-snapshot"` in every
   `schedule_tick` payload (`graph_driver.py:837`), and
   `_base_snapshot_id_for_node` (`_commands.py:3945`) returns that override
   first (`:3956-3957`), before ever consulting the node's
   `base_snapshot`/`root_snapshot`/`routine_snapshot` input bindings. So the
   re-granted lease for a retried node carries a byte-identical
   `base_snapshot_id` to the one that just failed. This is the literal
   mechanism behind the contract doc's sentence.
   *Caveat a Builder must respect:* the managed path does restore the
   worktree — `handle_request_runner_recovery` (`boundary.py:486`) records
   baseline/recovery snapshot identity and `_dispatch_runner_recovery`
   (`dispatch.py:1892`) runs the restorer before
   `complete_runner_recovery`. So a managed retry runs against a *restored*
   worktree at the *same* base snapshot. Neither fact is stated anywhere in
   the emitted recovery plan; criterion 2 is about recording it.

### D. Criterion 3 — the forbidden state exists, by construction

1. `_recover_orphaned_active_leases` (`graph_driver.py:1127`) is the
   missing-callback handler. It synthesizes
   `agent_died` with `reason="runtime_execution_missing_no_callback"`
   (`graph_driver.py:1197`) for each active lease whose execution is not live
   on this executor. Called at `graph_driver.py:882` (leased-state pass) and
   `graph_driver.py:941` (no-progress pass).
2. It is bounded three ways (docstring at `graph_driver.py:1136-1168`):
   per-`lease_id` dedup, the kernel's `max_attempts`, and a per-node budget
   `MAX_NODE_RECOVERIES_PER_DRIVE = 3` (`graph_driver.py:67`, checked at
   `:1191`). **When the per-node budget is exhausted the function `continue`s
   — it does not revoke the lease, does not fail the node, and does not
   record anything.** It returns `False`.
3. The caller then falls through to
   `return project_graph_outcome(run_id, projection)`
   (`graph_driver.py:950`), and `drive_to_quiescence`'s bridge calls
   `await self._apply_pause(run_id, "graph_blocked", outcome.blocked_reason)`
   (`graph_driver.py:693`).
4. `project_graph_blocked_reason` (`graph/projections.py:4954`) has a
   dedicated branch for exactly this case
   (`projections.py:4964-4970`):
   ```python
   if projection.active_leases:
       ...
       return f"graph has active lease(s) without callback: {', '.join(leased_nodes[:3])}"
   ```
   **That string is a verbatim description of the state criterion 3 forbids**,
   and it is a first-class, intentional outcome today.
5. The operator surface reflects the same non-conclusiveness:
   `api/routers/graph.py:2296` renders expired-lease health rows defaulting to
   `reason="lease_expired_without_callback"`.
6. Note the asymmetry that makes this fixable: the *time-based* path
   (`_expired_lease_events`, `_commands.py:5481`) **is** conclusive — it emits
   `lease_expired`, a `retryable=False` `FailureRecord`, and
   `node_state_changed → failed`. Only the *executor-liveness* path
   (missing callback with an unexpired lease, which `80d74390f`'s 3600s TTL
   + proactive renewal made the **dominant** path) is inconclusive.

### E. Criterion 4 — an existing test pins the wrong behaviour

`tests/unit/test_graph_driver_logic.py:1314
test_driver_stops_recovering_node_when_fresh_lease_ids_keep_orphaning` is
already a faithful reproduction of the `fff4f6b7` shape: a dynamically
created node with no `max_attempts`, orphaned repeatedly with a fresh
`lease_id` each time. Its final assertion is

```python
assert outcome.blocked_reason == "graph has active lease(s) without callback: dynamic-worker-1"
```

(`test_graph_driver_logic.py:1370`). The sibling test at `:1240` likewise
ends with an active lease after one recovery attempt. **These tests must be
rewritten, not merely added to** — chunk 3 below owns that, and the Validator
must confirm the rewrite tightens rather than loosens the assertion.

Other existing coverage a Builder should not duplicate:
`test_graph_driver_logic.py:1061`/`:1128` (agent_died payload shape for the
orphan path), `tests/unit/test_callbacks.py:234-243`
(`lease_expired_without_callback` callback rejection),
`tests/unit/test_graph_commands.py:1295`, `:5443`, `:8268`, `:8478`, `:8537`
(the four `error_class` emission sites),
`tests/integration/test_graph_runner_recovery_dispatch.py`,
`tests/integration/test_graph_run_driver.py`.

---

## Verified facts from planning pass 2 (2026-08-27, post-chunk-1)

Established by reading `a42c27c97` (chunk 1 landed). Line numbers below are as
of `a42c27c97` and **supersede** the pass-1 numbers where they differ.

### F. Citation drift from chunk 1 (re-confirmed, all still accurate)

| thing | pass-1 line | now |
|---|---|---|
| `FailureClass` alias | *(new)* | `models.py:2439` |
| `FailureRecordValue` | `models.py:2439` | `models.py:2455` (`failure_class` at `:2465`) |
| `RecoveryPlanValue` | `models.py:2470` | `models.py:2493` |
| `_base_snapshot_id_for_node` | `_commands.py:3945` | `_commands.py:3946` (override branch `:3957-3958`) |
| `_apply_agent_died` | `_commands.py:4092` | `_commands.py:4092` (unchanged) |
| retry branch | `_commands.py:4276-4332` | `_commands.py:4277-4336` |
| `_failure_record_payload` | `_commands.py:4335` | `_commands.py:4339` |
| `_recovery_plan_record_payload` | `_commands.py:4377-4411` | `_commands.py:4383-4417` |
| `_expired_lease_events` | `_commands.py:5481` | `_commands.py:5487` (record at `:5517`) |
| driver constant snapshot | `graph_driver.py:837` | `graph_driver.py:837` (unchanged) |

`FailureClass` is imported into `_commands.py` at `:84` and is **not** exported
from `graph/__init__.py`. Chunk 2 keeps that convention (no `__init__.py` edit).

### G. Chunk 1's `failure_class` is not read by any decision — confirmed

Repo-wide, `failure_class` appears only at `models.py:2465` (the field),
`_commands.py:4343` (the required producer parameter) and the four emission
sites. **No branch anywhere reads it.** In particular `_apply_agent_died`
still decides retry-vs-terminal purely by string sniffing the death `reason`
(`_is_rate_limit_death` `_commands.py:4420`, `_is_non_retryable_runtime_death`
`_commands.py:4430`) and by the attempt budget (`:4234`), and the four
`failure_class="infrastructure_failure"` literals sit *inside* the already-taken
branches (`:4172`, `:4212`, `:4254`, `:5514`). So today classification happens
**after** the retry decision, at four independent sites. Criterion 2's "before
deciding on retry" is a real, structural, currently-false statement about the
code — not a documentation nicety.

### H. What the kernel actually knows at the retry decision point

Inside `_apply_agent_died`, before any branch:

- `lease.base_snapshot_id` — `LeaseProjection.base_snapshot_id`
  (`models.py:1269`), populated from `lease_granted`
  (`projections.py:2772`). Always a real string for a granted lease, because
  `schedule_tick` defers a node with no resolvable snapshot rather than
  fabricating one (`_commands.py:2711-2720`).
- `attempt_number` = `node_attempts_view(projection).get(node_id, 0)`
  (`_commands.py:4233`).
- `payload.max_attempts` — **`AgentDiedCommand.max_attempts` defaults to `0`**
  (`command_models.py:540`), and `0` means *unbounded*. The driver only fills
  it when the node has a compiled budget (`graph_driver.py:1205-1209`);
  dynamically created planner nodes have none. **This is the exact `fff4f6b7`
  pathology, and it is currently invisible in every emitted record.**
- `retry_backoff_seconds` = `payload.retry_backoff_seconds` (default `0`).

### I. `80d74390f` gives no usable "why will this differ" signal

Checked directly: `lease_renewed` is reduced at `projections.py:2785-2796` and
updates only `state`, `node_id`, `generation`, `execution_id`, `expires_at`.
**`LeaseValue` carries no renewal counter, no renewal timestamps, and no
renewal history**, and `payload_registry.py:257-258` retains only
`execution_id expires_at generation lease_id node_id`. So "previous attempt's
lease was renewed T times before disappearing" is **not derivable** without
adding projection state — which would bump
`PROJECTION_CHECKPOINT_SCHEMA_VERSION` off 15 and is out of scope.

**Therefore the honest answer to "why is a repeat attempt expected to behave
differently?" on the kernel `agent_died` path is: it is not.** Nothing is
health-checked, nothing is probed, the worktree is untouched, and the base
snapshot is identical. The only thing that can differ is a backoff delay. The
design consequence is recorded as decision D2 below.

*(The managed boundary path is the one exception and does have a real
differentiator — see fact J.)*

### J. The managed boundary path *does* take a differentiating action

`handle_complete_runner_recovery` (`boundary.py:580`) runs after
`_dispatch_runner_recovery` has restored the worktree, and the attempt
(`ExecutionAttemptValue`, `projection_models.py:648`) carries typed proof of
exactly what was restored: `baseline_snapshot_id`, `baseline_tree_sha`,
`recovery_scope` (`"selective"`/`"full_baseline"`), `restored_paths`,
`removed_paths`, `lease_base_snapshot_id`, `recovery_reason`,
`recovery_max_attempts`. Its retry branch (`boundary.py:678-702`) emits
`runtime_retry_scheduled` + `node_state_changed→ready` and **no typed record at
all**. So the one path that *can* honestly say "the repeat attempt differs
because the worktree was restored to baseline tree `abc…`, 4 paths restored,
1 removed" says nothing, while the path that cannot differentiate at least
emits a `RecoveryPlan`. This asymmetry is real but is **not** on the
missing-callback path criterion 2 names, so it is split into its own chunk
(new chunk 4).

### K. Record-id collision is a hard replay error, not a silent overwrite

`insert_record` (`projections.py:1257-1278`) **raises
`ProjectionReplayConflictError` on any non-identical reuse of a `record_id`**.
Any new `FailureRecord`/`RecoveryPlan` emission site must therefore prove its
`record_id` cannot collide with an existing one:

- `_failure_record_payload` id is `f"failure-{node_id}-{lease_id or error_class}"`
  (`_commands.py:4371`); `_recovery_plan_record_payload` id is
  `f"recovery-plan-{node_id}-{lease_id}"` (`_commands.py:4408`).
- Within `_apply_agent_died` the five branches are mutually exclusive, and a
  second `agent_died` for the same lease is rejected `"lease not active"`
  (`:4104`). A revoked lease is also invisible to `_expired_lease_events`
  (`_lease_is_expired` returns `False` unless `state == "active"`,
  `_commands.py:5554`). **So a new failure record on the retry branch keyed by
  `lease_id` is collision-free** — but the Validator must confirm this
  empirically (see verification condition 5), not take it on this argument.
- A *later* chunk emitting from `boundary.py` for the same `node_id`+`lease_id`
  **would** collide. New chunk 4 must namespace its ids by `recovery_id`
  (`f"recovery:{execution_id}:{reason}"`, `boundary.py:534`).

### L. Neither record type has projection side effects

`_apply_record_side_effects` (`projections.py:1317-1341`) special-cases only
`RoutineSnapshotRecord`, `CompletionDecisionRecord`, `CandidateRecord` and
`OutputRecord`. `FailureRecord` and `RecoveryPlanRecord` fall through
untouched. Adding fields or emissions cannot perturb derived projection state.

---

## Chunk queue

| # | Name | One-line description | AC |
|---|------|----------------------|----|
| 1 | Typed `FailureClass` on the failure-record path | Add a `FailureClass` `Literal` alias + additive optional `failure_class` on `FailureRecordValue`; make the `_failure_record_payload` helper *require* it; classify all four existing sites `infrastructure_failure`. No behaviour change. | 1 |
| 2 | Classify before retry, and state the retry basis | **Revised in pass 2 — kernel path only.** Hoist the classification to a single point above every branch in `_apply_agent_died`; emit a `retryable=True` classified `FailureRecord` on the retry branch (which emits none today); add `failure_class` / `retry_base_snapshot_id` / `retry_basis` / `attempt_number` / `max_attempts` to `RecoveryPlanValue` and populate them. | 1, 2 |
| 3 | Conclusive lease revocation on missing callback | When the per-node orphan-recovery budget is exhausted, terminally revoke the lease and fail the node with a `retryable=False` `infrastructure_failure` record instead of pausing with an active lease; make `project_graph_blocked_reason`'s active-lease branch unreachable-by-construction and rewrite the two tests that pin it. | 3 |
| 4 | Boundary-path recovery symmetry | **New in pass 2 (split out of the old chunk 2).** `handle_complete_runner_recovery` (`boundary.py:580`) emits the same typed pair — a classified `FailureRecord` and a `RecoveryPlan` with `retry_basis="worktree_restored_to_baseline"` populated from the attempt's `baseline_tree_sha` / `restored_paths` / `removed_paths` (fact J). Ids namespaced by `recovery_id` (fact K). Events only, never command-payload fields (risk R3). **Deferrable.** | 2 |
| 5 | Typed failure records at the verification and invalid-plan surfaces | Emit `verification_failure` / `invalid_plan_failure` records at `verification_failed` and `graph_patch_rejected`, so the enum's other two members have real producers. **Deferrable** — see note below. | 1 |
| 6 | Scenario #9 regression coverage | End-to-end: a missing callback terminates in either a healthy classified retry or a conclusively revoked lease with typed recovery state — never a paused run with an active lease. | 4 |

**Ordering rationale (revised in pass 2).** Chunk 1 is the only chunk with no
prerequisite and is a pure serialize/replay property, so a failed validation is
unambiguous. Chunk 2 must precede chunk 3 because chunk 3's terminal decision
consumes the classification and the `retry_basis` vocabulary chunk 2 attaches
to the retry path.

The old chunk 2 bundled three things; pass 2 splits the boundary-path half out
as the new chunk 4, for three evidenced reasons: (i) criterion 2 scopes itself
to "missing-callback / disappeared-execution handling", and that path is
`_recover_orphaned_active_leases` → `agent_died` → `_apply_agent_died`
(fact D1) — `handle_complete_runner_recovery` handles the *dispatch-exception*
reasons `runner_died` / `boundary_mismatch` (`boundary.py:648`), a different
trigger; so the kernel half alone fully satisfies criterion 2 and the boundary
half is symmetry/completeness. (ii) It is a different file, a different command
handler, and a different (integration) test surface —
`tests/integration/test_graph_runner_recovery_dispatch.py` has 12 references to
that path. (iii) It carries risk R3 (`recovery_proof_hash`), which the kernel
half does not. Bundling would make a failed validation unattributable, which is
the same reasoning that produced the chunk 1 / chunk 2 split.

Chunk 5 (was 4) stays separated because it touches the callback and
patch-acceptance command paths — a much larger blast radius than the lease
paths — and criterion 1 as written asks only for the *type* to distinguish
three classes, which chunk 1 delivers. **If the loop is running long, defer
chunks 4 and 5 with a recorded reason rather than compressing chunk 3 or 6.**
Chunk 6 is last because it asserts the composed behaviour of 1-3.

**Non-goal, explicitly deferred (target doc's own carve-out).**
Health-check-based runner probing before retry (contract doc §7.3). Fact A1
shows `80d74390f` already added proactive lease renewal keyed to
`executor.is_running(...)`, which is a liveness signal in the same family;
adding a *separate* probe would need a runner-capability contract that
does not exist yet (see `re-evaluation-2026-07-18.md`). Deferred with reason.

---

## Chunk 1 — Typed `FailureClass` on the failure-record path (SPECIFIED, not built)

**Goal.** Make it possible — and, at every producer, *mandatory* — to state
which class of failure a `FailureRecord` describes. No recovery-decision
changes, no new emission sites, no lease-lifecycle changes, no prompt
changes. Independently verifiable: after this chunk every newly emitted
`FailureRecord` carries `value.failure_class`, historical records without it
still replay, and no test outside the ones listed below changes behaviour.

**Why this split and not "types + classification logic together".** Deciding
*which* class a given death is (fact B4: the retry branch currently records
nothing, and `handle_complete_runner_recovery` records nothing either) is a
judgement about recovery semantics that belongs with the code that acts on
it. Declaring the vocabulary and forcing existing producers to name
themselves is mechanical. Splitting keeps a failed validation attributable.

**Why additive and not a retype of `error_class`.** Fact B5: every historical
`output_record_accepted` payload is re-validated through
`FailureRecord.model_validate` on every projection rebuild
(`projections.py:1473-1479`), and journals already contain `agent_error`,
`process_exit`, `lease_expired`. Narrowing `error_class` in place makes those
runs unreplayable. `error_class` therefore stays a free string and is
**demoted, by docstring, to a fine-grained detail code**; `failure_class` is
the typed carrier. Criterion 1's "replacing the single untyped `error_class`
string" is satisfied *as the decision surface* — after chunk 3 no recovery
decision reads `error_class`.

### Files touched (exactly these)

Production (2):

1. `src/orchestrator/graph/models.py`
2. `src/orchestrator/graph/_commands.py`

Tests (3):

3. `tests/unit/test_graph_models.py`
4. `tests/unit/test_graph_commands.py`
5. `tests/unit/test_output_record_event_payloads.py`

**Do not touch** (each is a later chunk's or another slice's territory):
`graph/payload_registry.py` (fact B8 — no edit needed), `graph/projections.py`,
`graph/projection_codec.py` (schema version must stay 15),
`graph/commands/boundary.py` (chunk 2), `workflow/graph_driver.py` (chunk 3),
`graph/scheduler.py` (fact B2 — the `"verification_failure"` literal there is
a port name; leave it alone), `graph_runtime/prompts.py`,
`graph/contracts.py`, `api/routers/graph.py`.

### Exact production edits

**1. `graph/models.py` — new type alias.** Place immediately above
`class FailureRecordValue` (currently `models.py:2439`), following the
`LeaseProjectionState` convention at `models.py:777`:

```python
FailureClass: TypeAlias = Literal[
    "infrastructure_failure",
    "verification_failure",
    "invalid_plan_failure",
]
```

Docstring/comment must state the discriminant, in these terms:

- `infrastructure_failure` — the execution or runner disappeared, died, was
  rate-limited, or was misconfigured; **no graded result was produced**.
- `verification_failure` — the work ran to completion and produced a graded
  failure (a verifier or check said no).
- `invalid_plan_failure` — the patch or plan itself was rejected; no
  execution was ever attempted against it.

`TypeAlias` and `Literal` are already imported (`models.py:6`).

**2. `graph/models.py` — additive field on `FailureRecordValue`.** Add, after
`error_class` (`models.py:2442`):

```python
failure_class: FailureClass | None = None
```

`error_class: str` **stays exactly as it is**; add a comment marking it the
free-form detail code and `failure_class` the typed decision carrier.
`StrictNestedModel` is `extra="forbid"` (`models.py:110`) — this addition is
strictly widening, so historical payloads with only `error_class` still
validate, and `GraphBaseModel.model_dump`'s `exclude_unset=True` default
(`models.py:103`) keeps the key absent from records that do not set it.

**3. `graph/_commands.py` — required parameter on the producer.** Change
`_failure_record_payload` (`_commands.py:4335`) to take a keyword-only,
**non-defaulted** `failure_class: FailureClass` (place it immediately before
`error_class`), and write it into `value` unconditionally:

```python
value: dict[str, Any] = {
    "failed_node_id": node_id,
    "phase": phase,
    "failure_class": failure_class,
    "error_class": error_class,
    "retryable": retryable,
}
```

This is the enforcement point: the model field is optional for replay, but no
new call site can compile-or-run without naming a class. Import
`FailureClass` from `orchestrator.graph.models` in the existing import block
(`_commands.py:64-...`, alphabetically adjacent to `FailureRecord` at
`_commands.py:84`).

**4. `graph/_commands.py` — classify the four existing sites.** All four are
infrastructure-class (fact B3); pass `failure_class="infrastructure_failure"`
at `_commands.py:4171`, `:4210`, `:4251`, and `:5511`. **Change nothing else
at those sites** — same `error_class` strings, same `retryable`, same `phase`,
same event ordering, same `record_id` derivation
(`f"failure-{node_id}-{lease_id or error_class}"`, `_commands.py:4365` —
leave `error_class` in the id so record identity is unchanged).

### Exact test additions

`tests/unit/test_graph_models.py` (3 new tests, adjacent to
`test_failure_record_round_trips` at `:1576`):

- `test_failure_record_round_trips_with_failure_class` — a record whose
  `value` carries `failure_class="infrastructure_failure"` round-trips
  through `assert_round_trips` with the key preserved.
- `test_failure_record_accepts_legacy_value_without_failure_class` — the
  existing `:1576` fixture body (`error_class="lease_expired"`, no
  `failure_class`) validates, and `record.value.failure_class is None`. This
  is the replay-compatibility pin; name it so its purpose is unmistakable.
- `test_failure_record_rejects_unknown_failure_class` —
  `failure_class="something_else"` raises `ValidationError`.

`tests/unit/test_graph_commands.py` (assertions added to existing tests, no
new test functions needed for three of the four; one new test for the
fourth):

- Extend the existing assertions at `:8324` (`runtime_configuration_error`),
  `:8594` (`agent_rate_limited`), and the `max_attempts_exhausted` fixture at
  `:8478` to also assert
  `payload["value"]["failure_class"] == "infrastructure_failure"`.
- Add one test asserting the same for the `_expired_lease_events` path,
  alongside the existing `lease_expired_without_callback` fixture at `:1295`.

`tests/unit/test_output_record_event_payloads.py`: extend the
`FailureRecord` fixture at `:177-181` to carry `failure_class` and assert it
survives whatever round-trip that module performs; **also leave one
`failure_class`-free `FailureRecord` case in place** so the payload-level
legacy path stays covered.

### Verification conditions (what a Validator must independently confirm)

1. **Non-vacuity by direct execution, not by reading the tests.** Delete
   `failure_class` from the `value` dict in `_failure_record_payload` and
   confirm the four call-site assertions FAIL with a `KeyError`/assertion
   naming `failure_class`; restore. Separately, add a fifth caller that omits
   the argument and confirm it is a hard `TypeError` at call time (the
   parameter is genuinely non-defaulted), then remove it.
2. **Replay compatibility, empirically.** Build a `FailureRecord` payload
   with only `error_class` (no `failure_class`) — the shape at
   `tests/graph_fr17_fixture.py:185` — and drive it through
   `graph/projections.py`'s `output_record_accepted` reduction
   (`projections.py:1473-1479`), confirming it validates and lands in
   `state.records`. A model-level `model_validate` alone is **not** sufficient
   evidence; the reduction path is what runs on rebuild.
3. **Record identity unchanged.** Confirm the `record_id` produced at each of
   the four sites is byte-identical to `c52362c0d`'s (fixtures at
   `test_graph_commands.py:8268`, `:8478`, `:8537` and
   `:1295` should need no id edits).
4. **No checkpoint-shape change.** `PROJECTION_CHECKPOINT_SCHEMA_VERSION`
   still `15`; no edit to `payload_registry.py` (fact B8 says none is needed
   — if the Builder edited it, that is a signal the change went wider than
   specified and must be justified or reverted).
5. **Anti-weakening audit.** No existing assertion about `error_class`,
   `retryable`, `phase`, event ordering, or event count was relaxed or
   deleted to accommodate the new key.
6. **Suite.** Full suite ≥ **5513 passed, 5 skipped** with zero regressions
   (expect 5513 + the new test IDs). `ruff check`, `ruff format --check`, and
   `pyright` clean.

### Explicitly out of scope for chunk 1

- Any change to which branch of `_apply_agent_died` is taken.
- Any new `FailureRecord` emission site (chunks 2 and 4).
- Any change to `RecoveryPlanValue` (chunk 2).
- Any change to lease revocation, `_recover_orphaned_active_leases`,
  `MAX_NODE_RECOVERIES_PER_DRIVE`, or `project_graph_blocked_reason`
  (chunk 3).
- Making `failure_class` required on the *model* (it must stay optional —
  fact B5).
- Touching `phase`, which is also an untyped string. Typing it is a
  reasonable follow-up but is not in any Slice 5 acceptance criterion; if a
  Builder wants it, record the request here rather than bundling it.

---

## Chunk 2 — Classify before retry, and state the retry basis (SPECIFIED, not built)

**Goal.** Make two currently-false statements true of the kernel's
missing-callback path, `_apply_agent_died` (`_commands.py:4092`):

1. the failure is classified **once, above every branch**, before the code
   chooses retry-vs-terminal (criterion 2, first half — today classification
   happens *inside* four already-taken branches, fact G); and
2. the emitted recovery decision **states the base snapshot the retry will run
   against, and states — as a typed value, not prose — what if anything
   differentiates the repeat attempt** (criterion 2, second half).

Plus the missing record: the retry branch (`_commands.py:4277-4336`) is the
single most common infrastructure failure and emits **no `FailureRecord` at
all** (fact B4). It gets one, and it is the first `retryable=True` failure
record in the system.

No lease-lifecycle change, no change to which branch is taken, no change to
node states, no driver change, no `boundary.py` change.

### Scope decision — the two halves of criterion 2 are ONE chunk

They are the same edit to the same function. Half (a) on its own would be a
hoisted local variable whose four consumers all receive the identical value
they already hardcode — an edit with **no observable output change**, hence no
non-vacuous validation. Half (b) is the observable consequence that proves the
hoist happened (the `RecoveryPlanValue.failure_class` on the retry branch can
only be populated *because* the class is computed before the branch). Splitting
would produce one unvalidatable chunk and one that re-does its work.

What *is* split off is the third item the pass-1 queue bundled here —
`handle_complete_runner_recovery`. See the revised ordering rationale above.

### Decision D1 — the classification point is a single assignment, not a dispatcher

Add, in `_apply_agent_died` immediately after `reason = payload.reason`
(`_commands.py:4118`) and **above** the `non_gap_planner_has_accepted_patch`
check at `:4127`:

```python
# Criterion 2: the class is fixed here, before any branch below chooses
# retry vs terminal failure.  Every `agent_died` reason is by definition an
# execution or runner death with no graded result, so there is nothing to
# dispatch on yet; when `invalid_plan_failure` gains a producer (chunk 5)
# this is the seam that grows a classifier.
failure_class: FailureClass = "infrastructure_failure"
```

Then **delete all four hardcoded `failure_class="infrastructure_failure"`
literals inside the branches** (`:4172`, `:4212`, `:4254`) and pass
`failure_class=failure_class` instead. `_commands.py:5514`
(`_expired_lease_events`) is a *different* function and keeps its literal.

**Do not** introduce a `_classify_agent_death(reason)` helper with one arm.
A single-armed dispatcher that always returns the same constant looks like
classification without being any, and would make the chunk untestable except
against itself. The single assignment is the honest form: it is one place, it
is above the branches, and the comment names the extension point.

### Decision D2 — `retry_basis` is a typed `Literal`, and there is deliberately NO free-text rationale field

Fact I establishes that on this path **nothing differentiates a retry**: no
health check, no probe, no worktree restore, no renewal history to cite, and
(fact C3 / question 4 below) a byte-identical base snapshot. The only thing
that can differ is a backoff delay.

So the field must be able to say *that*, explicitly and greppably:

```python
RetryBasis: TypeAlias = Literal[
    "no_differentiating_action",
    "retry_backoff_only",
    "worktree_restored_to_baseline",
]
```

- `no_differentiating_action` — same base snapshot, same worktree, no delay,
  no probe. **The retry is expected to behave identically.** This is the value
  the kernel path emits today with `retry_backoff_seconds == 0`, and it is
  precisely the state `reliable-plan-execution-contract.md` §7 calls "not
  recovery". Making it a first-class, assertable value is the point of the
  field.
- `retry_backoff_only` — the only difference is elapsed time
  (`retry_backoff_seconds > 0`). Honest for transient rate/resource pressure,
  and honestly weak.
- `worktree_restored_to_baseline` — a real filesystem action was taken. **No
  producer in chunk 2**; it is declared now so chunk 4 (`boundary.py`, fact J)
  adds a producer rather than the vocabulary, and so chunk 3 can already
  distinguish "a retry that did something" from "a retry that did nothing".

**A `retry_rationale: str` free-text field is rejected.** Everything a prose
sentence could say here is already fully determined by
`retry_basis` + `retry_base_snapshot_id` + `attempt_number` + `max_attempts` +
the existing `reason`. A string assembled from those four values adds no
information, cannot be asserted on without pinning English, and — given that
the honest content is "nothing differs" — would be the exact "canned string
with no real differentiation" the brief warns against. If an operator surface
later wants a sentence, it renders one from the typed fields; the kernel does
not store prose. **Record any later request for this field here rather than
adding it.**

### Decision D3 — `base_snapshot_id: "routine-snapshot"` being a constant is OUT OF SCOPE

Confirmed still live at `graph_driver.py:837` and mirrored at
`api/routers/graph.py:3943`. `"routine-snapshot"` is not a placeholder — it is
`_ROUTINE_SNAPSHOT_NODE_ID` (`graph/compiler.py:1047`), the compiler-created
snapshot node whose identity every node in every run resolves to, forever,
because `_base_snapshot_id_for_node` (`_commands.py:3946`) honours the command
override at `:3957-3958` *before* consulting the node's
`base_snapshot`/`root_snapshot`/`routine_snapshot` bindings at `:3960-3967`.

Changing it would alter the `base_snapshot_id` on **every** `lease_granted`
payload, every `agent_dispatch_requested`, every runner baseline capture and
every boundary/recovery proof in the system, and would require deciding *what*
per-attempt snapshot identity replaces it — which is Slice 4
(candidate/accepted snapshot isolation), an explicit non-goal of this pass.
That is categorically larger than "add typed fields to a record", and it is the
same call chunk 4 of Slice 1 made about not fixing an upstream design while
adding a typed field downstream.

**Chunk 2 records the constant honestly and does not change it.** That is
exactly what criterion 2 asks for: it says the decision must *state* which
snapshot the retry will use, not that the snapshot must be new. A
`RecoveryPlan` reading
`retry_base_snapshot_id="routine-snapshot", retry_basis="no_differentiating_action"`
is a true and damning statement, and it is the machine-readable evidence a
future Slice 4 needs to justify itself.

### Files touched (exactly these)

Production (2):

1. `src/orchestrator/graph/models.py`
2. `src/orchestrator/graph/_commands.py`

Tests (3):

3. `tests/unit/test_graph_models.py`
4. `tests/unit/test_graph_commands.py`
5. `tests/unit/test_output_record_event_payloads.py`

**Do not touch:** `graph/commands/boundary.py` (chunk 4),
`workflow/graph_driver.py` (chunk 3; and D3 — the constant stays),
`api/routers/graph.py` (D3), `graph/payload_registry.py` (fact B8 — `value` is
retained wholesale, no edit needed), `graph/projections.py`,
`graph/projection_codec.py` (schema version stays 15), `graph/__init__.py`
(fact F — `FailureClass` is unexported; `RetryBasis` matches),
`graph/contracts.py`, `graph/scheduler.py`, `graph_runtime/prompts.py`,
`tests/graph_fr17_fixture.py` (its `recovery-plan-1` payload at `:214` is a
legacy-replay pin and **must keep** its three-key `value`).

### Exact production edits

**1. `graph/models.py` — new `RetryBasis` alias.** Place immediately above
`class RecoveryPlanValue` (`models.py:2493`), with the three members and the
discriminants spelled out as in D2. `TypeAlias` and `Literal` are already
imported (`models.py:6`).

**2. `graph/models.py` — five additive fields on `RecoveryPlanValue`**
(`models.py:2493-2499`). All optional with `None` defaults — `RecoveryPlanValue`
is a `StrictNestedModel` (`extra="forbid"`), so widening is safe for replay and
`exclude_unset=True` (`models.py:103`) keeps unset keys out of dumps, which is
what preserves the `graph_fr17_fixture.py:214` and
`test_output_record_event_payloads.py:229` legacy shapes:

```python
    failure_class: FailureClass | None = None
    retry_base_snapshot_id: str | None = None
    retry_basis: RetryBasis | None = None
    attempt_number: StrictInt | None = None
    max_attempts: StrictInt | None = None
```

`retry_base_snapshot_id` needs a comment stating exactly what it is and is not:
*the failed lease's `base_snapshot_id`, which is what the retry resolves to
unless the node's snapshot input bindings change before the next
`schedule_tick` — and which the driver's constant override
(`graph_driver.py:837`) makes invariant today.* `max_attempts` needs a comment
that `None` means **unbounded**, the dynamically-created-node case
(fact H) that produced `fff4f6b7`.

**3. `graph/_commands.py` — hoist the classification.** As specified in D1.

**4. `graph/_commands.py` — new `FailureRecord` on the retry branch.** Insert
into the returned list at `:4306-4336`, **between `lease_revoked` and
`runtime_retry_scheduled`**, so the event stream itself orders
classify-then-retry and the three terminal branches and the retry branch share
one ordering shape:

```python
make_event(
    "output_record_accepted",
    _failure_record_payload(
        node_id=node_id,
        phase="runtime",
        failure_class=failure_class,
        error_class="runtime_death_retry_scheduled",
        retryable=True,
        lease_id=lease_id,
        execution_id=event_payload.get("execution_id"),
        generation=generation,
        reason=reason,
        metadata={
            "attempt_number": attempt_number,
            **({"max_attempts": max_attempts} if max_attempts > 0 else {}),
        },
    ),
),
```

Resulting retry-branch order: `agent_died`, `lease_revoked`,
`output_record_accepted`(failure_record), `runtime_retry_scheduled`,
`output_record_accepted`(recovery_plan), `node_state_changed`.

Notes the Builder must respect:
- `error_class="runtime_death_retry_scheduled"` is a **new** free-form detail
  code and must not reuse any of the four existing ones — `record_id` is
  `f"failure-{node_id}-{lease_id}"` and reuse would risk fact K.
- `retryable=True` is deliberate and is the first such record in the system.
  Do not "fix" it to `False` for consistency with the other four.
- `max_attempts` is conditionally included precisely so an unbounded
  (`0`) budget produces an **absent** key rather than a misleading `0`; the
  unboundedness is then carried by `RecoveryPlanValue.max_attempts is None`.

**5. `graph/_commands.py` — populate the recovery plan.** Extend
`_recovery_plan_record_payload` (`:4383`) with four new keyword-only params —
`failure_class: FailureClass`, `base_snapshot_id: str | None`,
`attempt_number: int`, `max_attempts: int` — all **non-defaulted** (same
enforcement pattern chunk 1 used on `_failure_record_payload`; it has exactly
one call site, so this is free). Derive `retry_basis` inside the helper from
data already passed, never from a caller-supplied string:

```python
    value["failure_class"] = failure_class
    if base_snapshot_id is not None:
        value["retry_base_snapshot_id"] = base_snapshot_id
    value["retry_basis"] = (
        "retry_backoff_only" if retry_backoff_seconds > 0 else "no_differentiating_action"
    )
    value["attempt_number"] = attempt_number
    if max_attempts > 0:
        value["max_attempts"] = max_attempts
```

Order the new keys after `reason` and before the existing
`retry_after_seconds`/`retry_not_before` block so the emitted dict order stays
stable and readable. At the call site (`:4326-4330`) pass
`failure_class=failure_class`, `base_snapshot_id=lease.base_snapshot_id`,
`attempt_number=next_attempt_number` (the number of the attempt the plan
*schedules*, matching `node_state_payload["attempt_number"]` at `:4293`), and
`max_attempts=max_attempts`.

`record_id` stays `f"recovery-plan-{node_id}-{lease_id}"` — unchanged.

### Exact test additions

`tests/unit/test_graph_models.py`:

- `test_recovery_plan_record_round_trips_with_retry_basis` — adjacent to
  `test_recovery_plan_record_round_trips` (`:1691`); a `value` carrying all
  five new keys round-trips through `assert_round_trips` with every key
  preserved.
- `test_recovery_plan_record_accepts_legacy_value_without_retry_basis` — the
  existing `:1691` three-key `value` still validates and all five new
  attributes are `None`. Name it so its replay-pin purpose is unmistakable.
- `test_recovery_plan_record_rejects_unknown_retry_basis` —
  `retry_basis="probed_runner"` raises `ValidationError`. (Pairs with the
  existing `rejects_invalid_action` test at `:1731`.)

`tests/unit/test_graph_commands.py` — **extend, never relax**, the two
exact-equality assertions on the recovery-plan `value`, and shift the
positional indices that the inserted event moves:

- `:8236-8273` (`test_agent_died_...` retry, no backoff): the event-type list
  gains `"output_record_accepted"` at index 2; `output[2]`→`output[3]`,
  `output[3]`→`output[4]`, `output[4]`→`output[5]`. The recovery-plan
  exact-equality `value` gains
  `"failure_class": "infrastructure_failure"`,
  `"retry_base_snapshot_id": <the lease's base snapshot>`,
  `"retry_basis": "no_differentiating_action"`, `"attempt_number": 1`.
  *(The fixture's `lease_granted` at `:8230` may carry no `base_snapshot_id`;
  if so the key is legitimately absent — assert its absence explicitly rather
  than adding a snapshot to the fixture, and add the base-snapshot assertion in
  the new dedicated test below.)*
- `:8404-8420` (backoff variant): same index shift; `value` gains
  `"retry_basis": "retry_backoff_only"` alongside the existing
  `retry_after_seconds`/`retry_not_before`.
- `:8748-8756` (accepted-patch-then-death variant): event-type list and
  `output[3]`/`output[4]` indices shift.
- New `test_agent_died_retry_records_classified_failure_before_scheduling_retry`
  — a fixture whose `lease_granted` carries an explicit
  `base_snapshot_id="routine-snapshot"`, asserting: the failure record's
  `output_record_accepted` appears at a **lower index** than
  `runtime_retry_scheduled`; its `value["failure_class"] ==
  "infrastructure_failure"`, `value["retryable"] is True`,
  `value["error_class"] == "runtime_death_retry_scheduled"`,
  `value["attempt_number"] == 0`; and the recovery plan's
  `value["retry_base_snapshot_id"] == "routine-snapshot"` — i.e. the retry's
  stated snapshot is byte-identical to the failed lease's.
- New `test_agent_died_retry_plan_omits_max_attempts_when_unbounded` — with
  `max_attempts` absent from the command (the dynamic-node case, fact H),
  `"max_attempts"` is absent from both the failure record's and the recovery
  plan's `value`; with `max_attempts=3` it is present and equal to `3`.

`tests/unit/test_output_record_event_payloads.py`: extend the `recovery_plan`
fixture at `:229-237` to carry the five new keys and assert they survive the
round-trip, and **leave one bare three-key `recovery_plan` case in place** so
the payload-level legacy path stays covered (mirroring what chunk 1 did for
`failure_record`).

### Verification conditions (what a Validator must independently confirm)

1. **The hoist is real, by execution.** Change the single assignment to
   `failure_class: FailureClass = "verification_failure"` and confirm that
   **all five** emission sites in `_apply_agent_died` change together — the
   three terminal `FailureRecord`s, the new retry `FailureRecord`, and the
   `RecoveryPlan`'s `failure_class` — while `_expired_lease_events`
   (`:5514`) is unaffected. Restore. If any site still says
   `infrastructure_failure`, a literal survived and the hoist is incomplete.
2. **Classification precedes the retry decision in the emitted stream.** In
   the retry branch, assert by index that `output_record_accepted`
   (failure_record) is emitted before `runtime_retry_scheduled` — not merely
   that both are present.
3. **Non-vacuity of `retry_basis`.** Confirm by execution that the *same*
   fixture produces `"no_differentiating_action"` with
   `retry_backoff_seconds=0` and `"retry_backoff_only"` with
   `retry_backoff_seconds=60`. A field that returns one value for every input
   is theatre; this must be shown to discriminate.
4. **The stated snapshot is the failed lease's, empirically.** Grant a lease
   with `base_snapshot_id="snap-A"`, kill it, and confirm the recovery plan
   says `snap-A` — then confirm from the real driver payload
   (`graph_driver.py:837`) that production always supplies
   `"routine-snapshot"`, so the recorded value is invariant across retries.
   **This is the evidence for criterion 2 and must be produced, not asserted
   from the doc.**
5. **Fact K, empirically.** Drive a full sequence through the real reduction
   path — `lease_granted` → `agent_died`(retry) → `schedule_tick` (re-grant) →
   `agent_died`(retry) — and confirm no `ProjectionReplayConflictError` from
   `insert_record` (`projections.py:1257`), i.e. the two
   `failure-{node}-{lease}` ids genuinely differ. Also confirm that a lease
   revoked by the retry branch is never picked up by `_expired_lease_events`.
6. **Legacy replay compatibility.** Reduce the `graph_fr17_fixture.py:214`
   `recovery-plan-1` payload (three-key `value`) through
   `graph/projections.py`'s `output_record_accepted` reduction
   (`projections.py:1473-1479`) and confirm it validates with all five new
   attributes `None`. Model-level `model_validate` alone is **not** sufficient
   evidence.
7. **No checkpoint-shape change.** `PROJECTION_CHECKPOINT_SCHEMA_VERSION` still
   `15`; no `payload_registry.py` edit; no `boundary.py`, `graph_driver.py` or
   `api/routers/graph.py` edit (any of these means the chunk exceeded D3 and
   must be justified or reverted).
8. **Anti-weakening audit.** The two exact-equality `value` assertions at
   `test_graph_commands.py:8252` and `:8412` are still exact-equality — they
   must have grown keys, not been downgraded to subset/`in` checks or to
   `assert payload["record_type"] == "recovery_plan"`. No assertion about
   `error_class`, `retryable`, `phase`, event ordering or event count was
   deleted; index shifts (`output[3]`→`output[4]`) are expected and legitimate,
   deletions are not.
9. **Suite.** Full suite ≥ **5518 passed, 5 skipped** with zero regressions
   (expect 5518 + the new test IDs). `ruff check`, `ruff format --check`, and
   `pyright` clean.

### Explicitly out of scope for chunk 2

- Changing `graph_driver.py:837`'s constant `"routine-snapshot"`, or making a
  retry resolve a *different* snapshot (decision D3; Slice 4 territory).
- Any change to `boundary.py` / `handle_complete_runner_recovery` (chunk 4),
  including the `worktree_restored_to_baseline` producer — chunk 2 declares
  that `RetryBasis` member but must emit **no** record from that file.
- Any change to which branch of `_apply_agent_died` is taken, to lease
  revocation, to `_recover_orphaned_active_leases`,
  `MAX_NODE_RECOVERIES_PER_DRIVE`, or `project_graph_blocked_reason` (chunk 3).
- Any consumer of `failure_class` / `retry_basis` — chunk 2 makes the decision
  *stated*, chunk 3 makes it *acted on*. No branch may read the new fields yet.
- Adding a renewal counter to `LeaseValue` to enable a richer rationale
  (fact I) — that is a projection-shape change and would move
  `PROJECTION_CHECKPOINT_SCHEMA_VERSION` off 15.
- A free-text `retry_rationale` field (decision D2).
- Typing `phase`, still deferred from chunk 1.

---

## Open risks carried into later chunks

- **R1 (chunk 3, high).** Terminally failing a node when the orphan-recovery
  budget is exhausted changes a *pause* into a *node failure*, which may
  cascade into run failure for graphs with no recovery node. The chunk must
  decide, and record, whether the run outcome becomes `failed` or stays a
  pause with a **revoked** lease and a typed failure record. Criterion 3 only
  forbids "active lease + no pending recovery action" — a pause whose lease is
  revoked and whose node carries an `infrastructure_failure` record satisfies
  it. Prefer that (smaller blast radius) unless evidence says otherwise.
- **R2 (chunk 3, medium).** `project_graph_blocked_reason`'s active-lease
  branch (`projections.py:4964-4970`) is reachable from paths other than
  orphan-budget exhaustion (e.g. an externally paused run mid-execution).
  Deleting the branch outright would degrade an unrelated diagnostic. Prefer
  narrowing it and adding an assertion/invariant test that the *orphan*
  path can no longer reach it.
- **R3 (now chunk 4, medium).** `handle_complete_runner_recovery`
  (`boundary.py:580`) is guarded by an exact-match idempotency comparison
  (`:592-634`) and a `recovery_proof_hash` (`:617-633`). Adding emitted
  events there is safe; adding *fields to the command payload* would change
  the proof hash and break in-flight recoveries across a restart. Chunk 4
  must add events only. *Re-pointed in pass 2 (chunk 2 no longer touches this
  file), and extended: chunk 4's new record ids must be namespaced by
  `recovery_id` (`boundary.py:534`), because `insert_record` raises
  `ProjectionReplayConflictError` on non-identical id reuse (fact K) and the
  naive `failure-{node_id}-{lease_id}` scheme would collide with the record
  chunk 2 emits from `_apply_agent_died` for the same lease.*
- **R4 — RESOLVED in pass 2 as decision D3 (chunk 2 spec).** Criterion 2's
  "which snapshot the retry will use" is a constant (fact C3,
  `graph_driver.py:837`), and `"routine-snapshot"` is the compiler's
  `_ROUTINE_SNAPSHOT_NODE_ID` (`compiler.py:1047`), not a placeholder. Chunk 2
  records it honestly via `retry_base_snapshot_id` + a typed
  `retry_basis="no_differentiating_action"` and **does not change it**;
  changing it is Slice 4 territory. See D3 for the full argument and D2 for
  why no prose rationale field is added.
- **R6 (chunk 3, medium — new in pass 2).** Chunk 2 deliberately adds no
  consumer of `failure_class`/`retry_basis`. If chunk 3 or 4 slips or is
  deferred, the slice ends with a second write-only field family (fact B7's
  problem, repeated). Criterion 2 as written only requires the decision to be
  *stated*, so this is acceptable at the criterion level — but if chunks 3-4
  are deferred, that fact must be recorded here explicitly rather than left
  implied.
- **R5 (chunk 4, low).** `_planner_outstanding_failures`
  (`prompts.py:914`) does not read `FailureRecord`s at all (fact B7). If a
  later chunk wants classified failures to reach the planner, that is
  additional wiring, not a free consequence.

---

## Process incident log

*(empty — no chunk built yet)*
