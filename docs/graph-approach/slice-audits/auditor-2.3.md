You are auditing slice 2.3 (Runner integration) of the task-world execution-graph kernel, implemented as uncommitted changes on branch main (`git status`/`git diff`; new: `src/orchestrator/graph_runtime/dispatch.py`, `tests/integration/test_graph_runner_e2e.py`; modified: `src/orchestrator/graph/commands.py`, `src/orchestrator/graph/projections.py`, `src/orchestrator/graph_runtime/__init__.py`, `src/orchestrator/graph_runtime/controller.py`, `src/orchestrator/runners/__init__.py`, unit test files).

Ground truth (read FIRST):
- docs/graph-approach/execution-graph-prd-plus.md — §12.3 (dispatch side effects, start ack), §13 (runtime recovery table: reattach / missing process / not infer success from live process), §19 (callback lease identity: lease_id, generation, execution_id, base_snapshot_id; stale matrix), §14 (task projection formula — accepted/needs_revision), §15.1–15.2 (worker/verifier lifecycle), §21 (permissions: agents cannot mark their own work accepted), §27.5 (no real LLM in tests)
- The slice definition: "2.3 Runner integration — One real builder/verifier cycle through an existing adapter (Claude SDK or CLI) behind graph callbacks; lease identity in callbacks; reattach-on-restart. Done when: End-to-end run on a real repo: build → boundary → verify → task projection accepted; server-restart mid-run recovers."

You are READ-ONLY. Protocol — in order:

1. RE-DERIVE acceptance criteria from the PRD sections + slice definition (ignore builder summary). Numbered list.

2. MAP each criterion to file:line + exact tests. No test evidence = UNMET.

3. RUN fresh:
   - uv run pytest tests/integration/test_graph_runner_e2e.py -q
   - uv run pytest tests/unit -q
   - uv run pytest tests/integration/test_graph_outbox_crash_points.py tests/integration/test_graph_routine_compile.py tests/integration/test_graph_event_store.py -q
   - kernel suite timing (<5s) + purity grep (no IO imports in src/orchestrator/graph/)
   - uv run ruff check src tests

4. ADVERSARIAL pass — at minimum:
   - §21/§14: can a WORKER's callback smuggle a `record_kind:"verification"` record (self-accepting its own work)? Verify rejected/ignored. Can a verifier verify a candidate NOT bound to its input (forged candidate_id)? Re-run the 2.2-style provenance attacks against the new verification path.
   - §13: does reattach/reconcile infer SUCCESS from a live process anywhere? (It must only keep waiting; success only via accepted callback.) Does the missing-process path go through the kernel's agent_died (lease revoked, reschedule) rather than runtime shortcuts?
   - Restart realism: do the restart tests actually discard all in-memory state and rebuild from the DB file (fresh controller/dispatcher/recovery objects)? Or do they secretly reuse live objects?
   - Lease identity: is the stale-generation rejection tested through the FULL stack (dispatcher→controller→kernel), and does the dispatcher really thread execution_id/base_snapshot_id from the dispatch payload rather than re-deriving?
   - ExecutionContext mapping: is it built from graph facts (routine snapshot/requirement nodes/projection) or hardcoded test strings that would never work for a real routine?
   - acknowledge_start: sent at execution begin and visible as kernel event? What happens if the agent submits before ack (ordering)?
   - agent exception → agent_died: tested? Does a runner raising mid-execute leave a stuck lease?
5. LAZINESS check: e2e drill steps from the slice "done when" each present (build → boundary → verify → accepted; restart recovers — BOTH reattach and dead variants); negative verifier path asserts needs_revision via project_task_states over events READ BACK from SQLite (not in-memory shortcuts); "real repo" actually a git repo used as cwd, not an empty dir.

6. LIES check: summary vs diff; claimed counts vs actual; verifier-only verification enforcement actually in the pure kernel (not just the dispatcher being polite).

7. TESTING-STANDARDS: no unittest.mock/monkeypatching; MockAgent/hand-written fakes via constructor OK; real tmp SQLite + tmp git repos; main orchestrator.db untouched; no real LLM.

8. VERDICT — ACCEPT / ACCEPT-WITH-PUNCHLIST / BOUNCE.

Output: criteria table (# | criterion | code evidence | test evidence | status); findings (severity | type | description | location); verdict + one paragraph.
