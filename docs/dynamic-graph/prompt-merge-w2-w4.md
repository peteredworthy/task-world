# Task: land the dynamic-graph merge backlog (incident fixes + W2 + W3 + W4)

Work in `/Users/peter/code/task-world`, branch `main`. Read `AGENTS.md` first.

## Situation

Four pieces of verified work exist but none of it is on main history:

1. **Main working tree** has ~1,540 uncommitted insertions across 23 files — incident
   fixes from the 2026-07-04/05 recoveries, live-tested, **only copy anywhere**.
2. **W2** (recovery-at-source): implemented + verified by run `69ce4f7c`, sits
   uncommitted in `worktrees/r355`.
3. **W3** (incremental projection snapshots): run `88f46a2e`, uncommitted in
   `worktrees/r356`.
4. **W4** (split monoliths): run `0694df2d`, uncommitted in `worktrees/r357`.

All three run worktrees are checked out at base `f526cd70a` (Jun 29) — 8 commits
behind main (`c02eceadd`). None of the three diffs applies cleanly to main
(`git apply --check` fails for all). W4 additionally deletes
`src/orchestrator/graph/commands.py` into a package, so it conflicts with W2/W3 too.

The intervening main commits the worktree diffs conflict with:
- `c95793889` W1 "Make graph projection the single read path" + `4073a0d4b` W1b —
  rewrote many `commands.py` helpers from raw-event scans to projection fields.
- `d390f6c41` + `6753f244a` — SQLite contention hardening, `BEGIN IMMEDIATE`,
  driver auto-resume, poison-edge patch lint, operator patch endpoint.

Specs for what each W-change must preserve:
`docs/dynamic-graph/w2-recovery-at-source-spec.md`,
`w3-incremental-snapshots-spec.md`, `w4-split-monoliths-spec.md`.
Background: `docs/dynamic-graph/dynamic-graph-implementation-review.html` (section 4,
P0 items) and `docs/dynamic-graph/incident-2026-07-04-w2-driver-crash-w3-final-check-strand.md`.

## Hard safety rules

- **Never** delete or reset `orchestrator.db`. Never run a second uvicorn against it.
- `.orchestrator/state/history.jsonl` is git-tracked; **no `git stash` / `git checkout`**
  that could truncate it. The pytest pre-commit hook does a stash-and-test cycle that is
  unsafe with a dirty tree — skip/bypass the hook (`--no-verify`) and run tests manually
  instead, as was done for the W1b merge (`4073a0d4b`).
- Treat `worktrees/r355`–`r357` as **read-only**: extract diffs/files from them, never
  commit, checkout, or clean inside them. They belong to orchestrator runs.
- The dev server may be running on port 8000. Main-root commits pause active graph runs
  (auto-resumes, but check). Before starting: `curl -s localhost:8000/api/runs?limit=10`
  and prefer to work while no run is `active`.

## Phase 0 — commit the working-tree incident fixes

`git status` shows the 23 modified files. Contents (verify against the diff, don't trust
this list blindly):

- `graph_runtime/controller.py` — read-outside-lock `handle_command`: full event read +
  `rebuild_projection` + `apply_command` moved **before** `BEGIN IMMEDIATE`; cheap
  `current_position` re-check inside the write transaction.
- `graph_runtime/dispatch.py`, `workflow/graph_driver.py` — bounded retry on
  lock-class `OperationalError` ("database is locked"/"busy") in
  `_handle_command_retry_stale` / `_handle_command_at_head` / lease-renewal loop;
  dispatch-side detection of submit-callback rejections.
- `graph/commands.py` — no-successor-sweep supersession
  (`_superseded_by_later_regional_pass`, `_recovery_lineage_superseded`,
  `_recovery_created_executable_successors`) fixing the false positive that wrongly
  failed run W2; `failed → resuming` operator-only lifecycle transition.
- `graph/projections.py` — `_check_result_recovery_superseded` +
  `_failed_check_result_blockers` (check-cite supersession layer).
- `cli/runs.py` — CLI run creation resolves execution mode (flag → routine → global
  default) instead of silently defaulting to legacy.
- `runners/agents/codex/agent.py`, `workflow/service.py`, `workflow/signals/signals.py`,
  `workflow/commands/run_lifecycle.py`, `api/schemas/runs.py`, `state/models.py`,
  `.gitignore`, incident doc addendum, plus test files for all of the above.

Steps:
1. Run the touched suites:
   `uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/unit/test_graph_dispatch_on_output.py tests/integration/test_graph_controller_transactions.py tests/integration/test_cli.py tests/unit/test_codex_server_transport.py tests/unit/test_agent_monitor.py tests/unit/test_run_factory.py tests/unit/test_startup_recovery.py -q`
2. Split into 2–3 logical commits (suggested: contention/driver fixes · kernel
   supersession + lifecycle · CLI/runner/misc). Commit the incident-doc and `.gitignore`
   changes with whichever commit they belong to.
3. Run the full graph suite (`uv run pytest tests -k graph -q`) after the last commit.

## Phase 1 — merge W2 (r355)

W2 = move the five repair sweeps out of `_apply_schedule_tick` to the causing commands,
add an idempotent `reconcile` command as the explicit escape hatch (wired into startup
recovery and the driver's quiescence path). Files changed in r355:
`graph/commands.py`, `graph_runtime/__init__.py`, `graph_runtime/recovery.py`,
`workflow/graph_driver.py`, 4 test files (+519/−64). No untracked files.

Suggested mechanics (gives you real 3-way merges without touching r355):
```
git branch merge/w2 f526cd70a
git worktree add /tmp/merge-w2 merge/w2          # temp worktree, NOT under worktrees/
git -C worktrees/r355 diff > /tmp/w2.patch
git -C /tmp/merge-w2 apply /tmp/w2.patch          # applies cleanly at its own base
git -C /tmp/merge-w2 commit -am "W2: recovery at source (from run 69ce4f7c)"
git merge merge/w2                                # now resolve real conflicts on main
```

Conflict guidance:
- `commands.py` is the battleground. W1/W1b rewrote helpers r355 also touched — when in
  doubt, keep main's projection-based reads (raw-event scans must not come back; there is
  a regression guard test) and W2's *structure* (transitions at source, sweeps demoted to
  `reconcile`).
- Phase 0's supersession fixes (`_superseded_by_later_regional_pass` etc.) were bolted
  onto the sweeps on main. In the merged form they must live wherever the W2 code moved
  that logic — the no-successor terminal-failure decision — not be dropped.
- Driver conflicts: main's `_drive_with_transient_retries`, locked-retry, and richer
  blocked reasons must survive; W2 adds the reconcile-on-quiescence call.

Acceptance gate (from the spec — all must pass before the merge commit):
```
uv run pytest tests/unit/test_graph_commands.py tests/unit/test_command_handlers.py \
  tests/unit/test_graph_recovery_selection.py tests/unit/test_scheduler.py \
  tests/integration/test_graph_fr12_acceptance.py \
  tests/integration/test_graph_fr16_acceptance.py \
  tests/integration/test_graph_dynamic_e2e.py -q
```
plus: `_apply_schedule_tick` contains no repair passes; `reconcile` is idempotent
(second run emits nothing); the dynamic e2e reaches terminal without the driver ever
issuing `reconcile`. Then `uv run pytest tests -k graph -q`.

## Phase 2 — merge W3 (r356), after W2

W3 = snapshot+tail on the write path (`PROJECTION_SCHEMA_VERSION`), deferral dedup
(emit `node_deferred` only on reason change), startup recovery skips terminal runs.
Files: `graph/__init__.py`, `graph/callbacks.py`, `graph/commands.py`,
`graph/projections.py`, `graph_runtime/controller.py`, `graph_runtime/recovery.py`,
`graph_runtime/store.py`, 3 test files (+1,492/−194). No untracked files; the DB already
has a `graph_projection_snapshots` table — check whether r356 added an Alembic migration
inside a tracked file; if schema changes are needed, write a migration (`create_all`
does not add columns).

Same branch-and-merge mechanics as Phase 1 (`merge/w3` at `f526cd70a`).

The one conflict that matters: **`controller.py handle_command`**. Both sides rewrote it.
The merged form must be:
1. Load persisted snapshot + events-after-position, fold only the tail — **outside** any
   write lock (this replaces main's full `read_run` pre-read; keep main's docstring
   intent: expensive work before the lock).
2. `BEGIN IMMEDIATE`, cheap `current_position` re-check inside, `StaleProjectionError`
   on mismatch.
3. Append events + advance/persist the snapshot **in the same transaction** (crash
   between append and snapshot write must not yield a wrong projection later — the
   fallback is version-checked full rebuild).

Acceptance gate (from the spec):
```
uv run pytest tests/integration/test_graph_event_store.py \
  tests/integration/test_graph_outbox_crash_points.py \
  tests/unit/test_projection_rebuild.py tests/unit/test_graph_projections.py \
  tests/integration/test_graph_dynamic_e2e.py -q
```
Key invariants: snapshot+tail == full rebuild field-for-field (parity test); wrong
schema version → ignored + rebuilt; two idle `schedule_tick`s → second appends no
`node_deferred`; crash-point suite green; recovery replays only non-terminal runs.
Then full graph suite.

## Phase 3 — W4 (r357): port the split, don't fight the diff

W4 = dissolve `graph/commands.py` into a `graph/commands/` package (registry dict
replacing the `apply_command` if-chain) and extract prompt/packet assembly from
`dispatch.py` into `graph_runtime/prompts.py`. r357 state: deletes `commands.py`,
modifies `dispatch.py`, adds untracked `graph/_commands.py`, `graph/commands/`,
`graph_runtime/prompts.py`.

Do **not** 3-way merge this one — the base file it split no longer exists in that form
after W1b/Phase-0/W2/W3. Instead re-execute the split against current main, using r357
as the reference for the seams:
1. Copy r357's `graph/commands/` package layout and module boundaries
   (`ls -R worktrees/r357/src/orchestrator/graph/commands/`) and its `prompts.py`.
2. Re-derive each module's content from **main's current** `commands.py` (post-W2/W3),
   moving functions verbatim — this is a mechanical, behavior-neutral refactor; no
   logic edits.
3. Same for the `dispatch.py` → `prompts.py` extraction.
4. `graph/__init__.py` re-exports must keep the public surface identical (import sites
   across the codebase must not need changes beyond what r357 itself changed).

Gate: `uv run pytest tests -q` (full backend suite) — a pure refactor should change no
test outcomes. Also `uv run ruff check` / repo lint per AGENTS.md.

## Commit / finish

- Squash-merge style messages matching precedent (`4073a0d4b`): state the run id the
  work came from, that conflicts were resolved against which commits, and the suite
  counts. End each commit with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- After all phases: update the status banner + W2/W3/W4 status notes in
  `docs/dynamic-graph/dynamic-graph-implementation-review.html` (unmerged → merged, with
  the new commit SHAs), and note completion in the incident doc's addendum.
- Do not push unless asked. Do not delete `worktrees/r355`–`r357` or their branches —
  the orchestrator owns their lifecycle.

## Verification of done

1. `git log --oneline -8` shows Phase 0 commits + W2 + W3 + W4 merges.
2. `git status` clean (except intentionally untracked files).
3. `grep -n "def _apply_schedule_tick" -A 40 src/orchestrator/graph/commands/…` shows no
   repair sweeps; `grep -rn "PROJECTION_SCHEMA_VERSION" src/orchestrator/graph/` hits.
4. Full backend suite green; report the counts.
