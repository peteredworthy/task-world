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

## Chunk queue

| # | Name | One-line description | AC |
|---|------|----------------------|----|
| 1 | Typed `FailureClass` on the failure-record path | Add a `FailureClass` `Literal` alias + additive optional `failure_class` on `FailureRecordValue`; make the `_failure_record_payload` helper *require* it; classify all four existing sites `infrastructure_failure`. No behaviour change. | 1 |
| 2 | Classify before retry, and state the retry basis | Emit a classified `FailureRecord` on the two retry paths that emit none today (`_apply_agent_died` retry branch, `handle_complete_runner_recovery`); add `failure_class` / `retry_base_snapshot_id` / `retry_basis` to `RecoveryPlanValue` and populate them. | 1, 2 |
| 3 | Conclusive lease revocation on missing callback | When the per-node orphan-recovery budget is exhausted, terminally revoke the lease and fail the node with a `retryable=False` `infrastructure_failure` record instead of pausing with an active lease; make `project_graph_blocked_reason`'s active-lease branch unreachable-by-construction and rewrite the two tests that pin it. | 3 |
| 4 | Typed failure records at the verification and invalid-plan surfaces | Emit `verification_failure` / `invalid_plan_failure` records at `verification_failed` and `graph_patch_rejected`, so the enum's other two members have real producers. **Deferrable** — see note below. | 1 |
| 5 | Scenario #9 regression coverage | End-to-end: a missing callback terminates in either a healthy classified retry or a conclusively revoked lease with typed recovery state — never a paused run with an active lease. | 4 |

**Ordering rationale.** Chunk 1 is the only chunk with no prerequisite and is
a pure serialize/replay property, so a failed validation is unambiguous.
Chunk 2 must precede chunk 3 because chunk 3's terminal decision consumes the
classification chunk 2 attaches to the retry paths. Chunk 4 is separated
because it touches the callback and patch-acceptance command paths — a much
larger blast radius than the lease paths — and criterion 1 as written asks
only for the *type* to distinguish three classes, which chunk 1 delivers.
**If the loop is running long, defer chunk 4 with a recorded reason rather
than compressing chunk 3 or 5.** Chunk 5 is last because it asserts the
composed behaviour of 1-3.

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
- **R3 (chunk 2, medium).** `handle_complete_runner_recovery`
  (`boundary.py:580`) is guarded by an exact-match idempotency comparison
  (`:592-634`) and a `recovery_proof_hash` (`:617-633`). Adding emitted
  events there is safe; adding *fields to the command payload* would change
  the proof hash and break in-flight recoveries across a restart. Chunk 2
  must add events only.
- **R4 (chunk 2, medium).** Criterion 2's "which snapshot the retry will use"
  is currently a constant (fact C3, `graph_driver.py:837`). Recording it
  honestly means recording `"routine-snapshot"` and a `retry_basis` that says
  the *worktree was restored to baseline*, not that the snapshot differs.
  Resist the temptation to make the retry use a different snapshot in chunk 2
  — that is Slice 4 (candidate/accepted snapshot isolation) territory and is
  an explicit non-goal of this pass.
- **R5 (chunk 4, low).** `_planner_outstanding_failures`
  (`prompts.py:914`) does not read `FailureRecord`s at all (fact B7). If a
  later chunk wants classified failures to reach the planner, that is
  additional wiring, not a free consequence.

---

## Process incident log

*(empty — no chunk built yet)*
