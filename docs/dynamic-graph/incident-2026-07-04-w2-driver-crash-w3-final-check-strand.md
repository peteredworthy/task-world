# Incident: W2 driver crash + W3 final-check strand (2026-07-04)

Two graph runs paused overnight while executing the dynamic-graph weakness specs:

| Run | Spec | Status | Pause reason |
|-----|------|--------|--------------|
| `69ce4f7c-d17f-425a-a524-294cc709e9ae` (W2) | `w2-recovery-at-source-spec.md` | paused 03:25 UTC | `graph_driver_crashed` — `sqlite3.OperationalError: database is locked` |
| `88f46a2e-d094-4b39-9f0c-ba6eb965968e` (W3) | `w3-incremental-snapshots-spec.md` | paused ~08:17 UTC | `graph_blocked` — quiescent with 4 non-terminal `planned` nodes |

These are two distinct root causes. W2 is a residual gap in the SQLite-contention
hardening shipped the previous evening (`d390f6c41`). W3 is a graph-topology design
flaw: the final invariant check is pass-gated on a *specific* verifier node that
failed terminally, so its required input can never bind. W2's graph carries the
same topology and its primary verifier has already failed, so W2 will strand the
same way after resume unless its graph is also repaired.

---

## W2 — driver crash: `database is locked` on lease-renewal heartbeat

### Timeline (UTC, 2026-07-04)

- 00:16 — `d390f6c41` lands: WAL + `busy_timeout=5000` connect hook, `_retry_locked`
  around outbox bookkeeping, crash bridge that pauses `graph_driver_crashed`.
- 02:37 — `f71676e03` lands: re-arm active graph runs on startup.
- 03:20:06 — driver grants lease to `verifier-w2-recovery-at-source`, dispatches it.
- 03:25:35 — driver's lease-renewal path issues `record_heartbeat`; the
  `INSERT INTO events_v2 … heartbeat_recorded` (version 128) fails with
  `database is locked`. The exception escapes the drive loop; the crash bridge
  correctly pauses the run `graph_driver_crashed`.
- 03:55:18 — the still-running verifier agent's REST callback lands anyway
  (callbacks don't need the driver): `verification_failed`, evidence bound to
  `planner-gap` via `edge-w2-verifier-failure-to-gap`, lease released. The gap
  planner is bound-and-ready but there is no driver to schedule it. Run has sat
  paused since.

### Root cause

The previous day's hardening fixed the *outbox bookkeeping* write path and added
`busy_timeout`, but the failure this time is in the **command append path**, and
`busy_timeout` cannot fix it:

1. `GraphController.handle_command` (`graph_runtime/controller.py:59-90`) opens one
   transaction that does `read_run(run_id)` (SELECT) **then** `append_events`
   (INSERT). Under WAL, the SELECT starts a read snapshot; the INSERT upgrades the
   connection to a writer. If any other connection commits a write between the
   SELECT and the INSERT — agent REST callbacks, the second graph run (W3 was
   active in the same DB all night), outbox writes — SQLite returns
   `SQLITE_BUSY_SNAPSHOT`, surfaced as `OperationalError: database is locked`
   **immediately**. `busy_timeout` does not apply to snapshot-upgrade failures:
   waiting cannot make a stale read snapshot writable; the transaction must be
   restarted.
2. The driver's retry wrappers only catch `StaleProjectionError` (the
   UNIQUE-violation flavor of the same race). Both `_handle_command_at_head`
   (`workflow/graph_driver.py:472`) and the retry loop inside
   `_renew_running_expired_leases` (`workflow/graph_driver.py:719`) let
   `OperationalError` escape on the first occurrence.
3. The exception propagates out of `drive_to_quiescence`; the crash bridge does
   its job (pause + visible reason), but recovery is manual — nothing
   auto-resumes a transiently-crashed driver.

So: same race family as the `StaleProjectionError` fix in `d390f6c41`
(driver read-then-write vs. concurrent callback appends), but surfacing as a
different exception type on a different code path, one layer below.

### Work needed

1. **Retry `database is locked` at the command layer.** Treat
   `OperationalError` where `"database is locked"`/`"database is busy"` appears
   the same as `StaleProjectionError` in `_handle_command_at_head` and
   `_renew_running_expired_leases`: the whole `handle_command` transaction rolled
   back, so re-read position and re-issue is safe. Small backoff + bounded
   attempts, mirroring `_retry_locked` in `graph_runtime/outbox.py`. Cheapest fix,
   closes this exact crash.
2. **Eliminate the snapshot-upgrade race at the source: `BEGIN IMMEDIATE` for
   write commands.** `handle_command` always intends to write; starting the
   transaction in immediate mode acquires the write lock before the SELECT, so
   contention becomes an ordinary busy wait that `busy_timeout=5000` *does*
   handle, and `SQLITE_BUSY_SNAPSHOT` disappears. In SQLAlchemy/aiosqlite this is
   a `begin` event hook (`conn.exec_driver_sql("BEGIN IMMEDIATE")`) or connection
   `isolation_level` handling scoped to the controller's session. This also
   retires most `StaleProjectionError` retries, since read-position staleness
   within a command vanishes.
3. **Consider a per-run single-writer gate.** Driver, REST callbacks, and
   heartbeats all live in one process; an `asyncio.Lock` per run_id around
   `handle_command` serializes in-process writers cheaply and makes SQLite
   contention between them structurally impossible. (Cross-process writers —
   e.g. a second uvicorn, see the duplicate-server incident — would still need
   items 1–2.)
4. **Shrink the write transaction.** `handle_command` replays *all* run events
   inside the write transaction (735 events on the W3 run and growing — the log
   inflation W3 was meant to fix). Incremental projection snapshots reduce both
   the lock window and the collision probability. This is literally the W3 spec;
   its priority rises because it also mitigates this crash class.
5. **Auto-resume transient driver crashes.** The crash bridge + startup re-arm
   (`f71676e03`) recover on restart, but a live server leaves the run paused until
   an operator notices. For crash classes known to be transient (locked/busy),
   re-arm the driver in-process with a capped retry counter (e.g. 3 per run per
   hour) before settling into the paused state.

### Recovery for this run

`runs resume 69ce4f7c` re-arms the driver; the gap planner's evidence is already
bound, so the corrective flow proceeds. **But apply the W3 graph repair below
first (or immediately after):** `check-w2-final-invariant-primary` is pass-gated
on `verifier-w2-recovery-at-source`, which has now failed terminally — W2 will
otherwise finish its corrective work and strand exactly like W3.

---

## W3 — stranded: final invariant checks pass-gated on failed verifier nodes

### What the log shows

The run ended quiescent with four nodes stuck `planned`, every scheduler tick
deferring them with `missing_required_input:verification_evidence`:

- `check-w3-final-invariant-initial` — required edge
  `edge-w3-verifier-pass-to-final-initial` from `verifier-w3-incremental-snapshots`
  with selector `{outcome: "passed"}`. That verifier **failed** (06:54,
  position 35004). It will never re-run; the edge can never bind.
- `check-w3-final-invariant-corrective` — same pattern from
  `verifier-w3-corrective`, which **failed** (07:16, position 35198).
- `planner-w3-final-check-gap-initial` / `planner-w3-final-check-gap-corrective` —
  fed by `check_result` from the two checks above, so transitively stuck.

Meanwhile the actual work *succeeded*: the gap-planner → corrective-region chain
ran twice, and `verifier-w3-r1-r6-corrective` (07:42) and
`verifier-w3-hotpath-snapshot-tail-corrective` (08:15) both **passed**. No edge
connects either passing verifier to any final invariant check, so their success
is invisible to the gate.

The driver behaved correctly: quiescence with non-terminal nodes → paused
`graph_blocked` with an accurate (if shallow) reason.

### Root cause

Final invariant checks are wired with a **required, pass-gated edge from a fixed
verifier node id**. The failure path of that same verifier routes to a gap
planner, which spawns a corrective region with a *new* verifier — and neither the
planner nor the templates rewire or recreate the final check against the new
verifier. One verification failure therefore poisons the final gate permanently:

- The pass edge can't bind (source failed terminally).
- The check can't even *fail* usefully (it never becomes ready, so it never
  emits a `check_result` to its own gap planner).

This is systemic, not a one-off planner mistake:

- The `final_invariant_region` template (`graph_runtime/horizon_templates.py:220`)
  itself emits `create_edge` from `verifier-corrective-{region_id}` →
  `check-final-invariant-{region_id}` with the pass-gated selector.
- The planner-authored W2 and W3 graphs both used the identical pattern
  (`edge-w2-primary-pass-to-final-check`, `edge-w3-verifier-pass-to-final-initial`, …).
- It is the same class as the run-`2bed8f2f` recovery (2026-07-03): check
  evidence pinned to a stale node identity instead of "latest passing
  verification in scope". That incident's open gap — "no recovery for
  runtime-failed checks" — is this bug's sibling.

### Node-expectation redesign: what a check should be allowed to require

The strand is not just "wrong edge"; it's that the node input contract has no
way to express what the planner actually means. Today an input expectation can
only be *"a record from node X's port P matching selector S, required"*. The
planner means *"the latest passing verification of the candidate lineage this
gate guards"*. Because the contract can't say that, every graph encodes it as a
brittle node pin, and every recovery re-pins it by hand. Concrete changes to the
expectation model, in dependency order:

1. **Producer-class selectors (unpin evidence).** Let
   `accepted_record_selector` stand alone as a node's input expectation — match
   on `record_type + schema + outcome` scoped to a candidate lineage, task
   region set, or the whole run — with no `from_node_id`. The kernel re-evaluates
   binding whenever a matching record is accepted, so a verifier created three
   corrective rounds later satisfies the same expectation. The final invariant
   check for W3 becomes: *one* node, expectation "latest `VerificationReport`
   with `outcome=passed` in this run's lineage", no rewiring ever needed.
2. **Separate "wait-for" from "trigger" edges.** `required: true` today means
   both "block until present" and "this node is part of the success path".
   Conditional continuations (failure → gap planner) need a different kind:
   a **trigger** edge — the node becomes schedulable *if* the record appears,
   and is auto-retired (`skipped`) when the trigger becomes impossible. A
   required edge whose source can still legitimately produce, blocks; a trigger
   edge never blocks completion.
3. **`skipped` as a kernel-managed terminal state.** When every inbound
   trigger/required edge of a `planned` node is provably dead (source node
   terminal with no matching record, no retry budget), the kernel retires the
   node as `skipped` in the same tick — an audit event, not an agent's job.
   Region acceptance already treats `retired` as non-blocking
   (`_derive_candidate_free_region_state`), so `skipped` slots straight in.
4. **Singleton gate contracts.** `fulfillment_contribution: "final_invariant"`
   should be declarable once per run (or per guarded lineage), not stamped per
   path/region. One gate node with rebindable evidence replaces the
   initial/corrective/per-region clones — which is what removes the entire
   class, not just this instance.

Interim (until the kernel work lands): keep node-pinned edges but make the
corrective-region template (`corrective_work_region`) *also* emit a rewire —
retire the stale pass edge and re-point the final check at
`verifier-corrective-{region}`. Works, but every future region type must
remember to do it; treat it as the stopgap, not the fix.
2. **Kernel dead-input detection.** When a required edge's source node reaches a
   terminal failed state with no retry budget left, the downstream node's input
   is provably unsatisfiable. The kernel should surface that distinctly
   (`node_unsatisfiable` event; route to the node's gap planner if it has one;
   include "source verifier X failed terminally" in the pause reason) instead of
   deferring forever and letting the run die as generic `graph_blocked`. This
   converts hours of stranded runtime into an immediate, self-describing pause —
   or a self-healing gap-planner turn.
3. **Patch-validation lint for the poison pattern.** At `submit_graph_patch`
   time, warn/reject when a *required, pass-gated* edge's source node also has a
   failure continuation (failure edge to a gap planner) and the destination has
   no alternate binding path. Both W2 and W3 graphs would have been flagged at
   planning time.
4. **Operator repair endpoint.** Recovery still requires `submit_patch` as
   `actor_role=human` via a GraphController script — there is no API endpoint
   (known gap from the 2bed8f2f recovery). Add
   `POST /api/runs/{id}/graph/patch` (operator-authenticated) so strand repair
   doesn't need a bespoke script each time.
5. **Blocked-reason depth.** `graph quiescent with non-terminal node(s): …=planned`
   names the nodes but not the cause. Include each stuck node's last deferral
   reason and, for `missing_required_input`, the source node + its state
   (`verifier-w3-incremental-snapshots=failed`). The diagnosis in this doc took
   an event-log excavation that the pause reason could have carried.

### Recovery for this run

Per the cite-latest-candidate rule (check evidence must come from a verifier in
the same task region — see the 2bed8f2f playbook), an operator patch that:

1. Retires the four stuck nodes (`check-w3-final-invariant-initial`,
   `check-w3-final-invariant-corrective`, and their two gap planners).
2. Creates a fresh final invariant check (+ gap planner) in
   `corrective_work_region`, pass-edge from
   `verifier-w3-hotpath-snapshot-tail-corrective` (whose passing report already
   exists, so the edge binds immediately).
3. `runs resume 88f46a2e` — driver re-arms, schedules the check, run can reach
   `complete`.

Apply the same repair shape to W2 once its corrective work has produced a
passing verifier.

---

## Redundant work done only to satisfy graph invariants

Reviewing the W2/W3 graphs against the acceptance rules
(`projections.py:_derive_task_states` / `_derive_candidate_free_region_state`:
a run completes only when every task region's *contributing* nodes are
`completed` or `retired`) exposed a second cost problem: several steps in these
graphs exist purely to keep the topology legal, not to add verification value.

1. **The final check re-runs the acceptance command the verifier just ran.**
   Both runs set no `hidden_oracle_command`, and the
   `dynamic_feature_hidden_oracle` binding falls back to `acceptance_command`
   (`graph/command_bindings.py:130`). The verifier has *already* executed
   `acceptance_command` and graded `dynamic_feature_acceptance` minutes earlier
   against the same candidate and file state. The final invariant check is a
   byte-for-byte duplicate full-suite run whenever no distinct oracle is
   configured. Fix: when the oracle binding resolves to the same command the
   gating verifier ran, the check should accept the verifier's
   `VerificationReport` as its check result (cite, don't re-execute) — or the
   binding should refuse the fallback and force the planner to say what the
   check adds.
2. **Final checks are cloned per path and per corrective round.** The planner
   stamped `check-*-final-invariant-initial` *and* `-corrective` for the same
   invariant, and the `final_invariant_region` template mints another check per
   corrective region. Each clone is another full acceptance run. With a
   singleton gate (redesign item 4 above) the invariant is checked once, after
   the last verification that matters.
3. **Gap planners run on success.** W3's check→gap edge
   (`edge-w3-final-check-initial-to-gap`) has **no status filter** — a *passing*
   check still feeds the gap planner, which must burn an LLM turn to classify
   "no gap" and submit an empty patch (the dispatch layer explicitly tolerates
   empty gap-planner patches: `_accepted_gap_planner_patch_had_ops`). W2's
   edges filter `status: failed`, which avoids the wasted turn but leaves the
   gap planner `planned` forever on success — blocking completion unless
   something retires it. Both variants are workarounds for the same missing
   primitive: conditional nodes that self-retire (`skipped`).
4. **Dead branches must be retired by an agent for the run to complete.** Both
   W3 final checks share `region-w3-final-invariant`, and region acceptance
   requires *all* contributing nodes to complete or be retired — but only one
   path (initial XOR corrective) can ever fire. Even a fully successful W3
   needed some agent to notice and retire the unused check + gap planner, or it
   would have ended `graph_blocked` *on success*. Completion of the happy path
   currently depends on LLM topology bookkeeping.

Net effect per successful run today: at least one duplicate acceptance-suite
execution, one bookkeeping planner turn, and a completion dependency on agents
doing kernel work. Redesign items 2–4 (trigger edges, `skipped`, singleton
gates) eliminate all four; fix 1 (cite-instead-of-rerun) is independent and
immediately cuts wall time and cost.

---

## Cross-cutting observations

- **The fail-safes shipped on 2026-07-03 worked.** Both runs paused with a
  visible reason instead of stranding ACTIVE — the crash bridge and the
  quiescence bridge did exactly what they were added to do. The remaining work
  is (a) one more retry layer / transaction-mode fix so the W2 crash class stops
  firing at all, and (b) topology + kernel changes so a verification failure
  can't permanently poison the final gate.
- **Two concurrent graph runs sharing one SQLite file is now a tested
  configuration** — and it's what surfaced the snapshot-upgrade race. Until
  items W2-1/W2-2 land, assume overnight multi-run batches can crash drivers.
- **Priority note:** W3's own spec (incremental snapshots, log-inflation stop)
  mitigates the W2 crash class by shrinking the write transaction. Finishing W3
  (after repair) pays down both incidents.

## Suggested execution order

| # | Item | Size | Closes |
|---|------|------|--------|
| 1 | Locked-retry in `_handle_command_at_head` + renewal loop (W2-1) | S | W2 crash recurrence |
| 2 | Operator repair patches + resume for both runs | S (ops) | Both stranded runs |
| 3 | `BEGIN IMMEDIATE` write transactions (W2-2) | M | W2 class at the source |
| 4 | Cite-instead-of-rerun when oracle == acceptance command (Redundancy-1) | S | Duplicate suite runs |
| 5 | Producer-class selectors — unpin check evidence (Redesign-1); template rewire as stopgap | M | W3 class at the source |
| 6 | Trigger edges + kernel `skipped` state (Redesign-2/3) | M | Success-path strands, bookkeeping agent turns |
| 7 | Kernel dead-input detection + richer blocked reasons (W3-2, W3-5) | M | Silent strands generally |
| 8 | Singleton final-invariant gate contract (Redesign-4) | M | Check cloning per path/round |
| 9 | Patch lint for poison pattern (W3-3) | S | Planning-time prevention |
| 10 | Operator patch API endpoint (W3-4) | S | Recovery toil |
| 11 | Auto-resume transient driver crashes (W2-5) | S | Overnight resilience |
