You are auditing slice 2.1 (Event store + outbox) implemented on the current working tree (uncommitted changes on branch main — see `git status`/`git diff` for the diff; new files: `src/orchestrator/graph_runtime/`, `src/orchestrator/db/migrations/versions/ab1c2d3e4f5g_add_graph_outbox_table.py`, `tests/integration/test_graph_event_store.py`, `tests/integration/test_graph_outbox_crash_points.py`; modified: `src/orchestrator/db/__init__.py`, `src/orchestrator/db/orm/models.py`).

Ground truth documents (read these FIRST, before the diff or any summary):
- docs/graph-approach/execution-graph-prd-plus.md — sections §12.1, §12.2, §12.3, §13, §27.4, §27.5, §30, §31
- docs/graph-approach/execution-graph-evaluation.md (where it amends the PRD)
- The slice definition: "2.1 Event store + outbox — Transactional append + outbox rows; dispatch worker; crash-point recovery table (PRD §12.3, §13). Done when: failure-injection tests for all four crash points; no side effect before commit."

You are READ-ONLY: do not modify any file. Running tests and read-only git commands is allowed and required.

Protocol — do these in order, do not skip steps:

1. RE-DERIVE acceptance criteria for this slice from the PRD sections above,
   ignoring the builder's summary entirely. Write them as a numbered list.

2. MAP each criterion to specific evidence: file:line for the implementation,
   and the exact test(s) that exercise it. A criterion with no test evidence
   is UNMET even if code exists.

3. RUN the test suite fresh (do not trust reported results):
   - uv run pytest tests/unit -q
   - uv run pytest tests/integration/test_graph_event_store.py tests/integration/test_graph_outbox_crash_points.py -q
   - the kernel suite: uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py tests/unit/test_scheduler.py tests/unit/test_patch_validator.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py tests/unit/test_scenario_harness.py tests/unit/test_graph_commands.py -q (must stay under 5s, no new IO imports in src/orchestrator/graph/)

4. ADVERSARIAL pass — attempt one violation per invariant the slice claims.
   For each invariant, describe the attack you tried and what happened. At minimum:
   - "No side effect before commit": find any code path where the dispatcher/executor can run before the transaction commits (e.g. auto_dispatch flag, exception ordering). Is there a TEST that fails if someone moves dispatch inside the transaction?
   - Atomicity: can an event be stored without its outbox row, or vice versa, under any failure interleaving the tests don't cover?
   - Idempotency: restart mid-`dispatching`, double dispatch_pending, recovery after partial dispatch — is at-least-once + dedup-by-event_id actually enforced and tested?
   - Stale expected_position: concurrent appenders — does the UNIQUE(aggregate_id, version) guard actually fire, and is the typed error surfaced (not swallowed)?
   - §13: does anything infer success from process/files instead of accepted events?

5. LAZINESS check — work avoided:
   - Stubbed or pass-through implementations hiding behind green tests
   - Crash points "covered" by tests that don't actually model a restart (fresh objects over same DB file)
   - Crash point 4 (agent dies): builder modeled it via lease-expiry schedule_tick because the kernel lacks agent_died — is the equivalence real and documented, or a dodge? Does the §12.3 row's recovery semantics ("revoke lease, create retry/recovery according to policy") have ANY evidence?
   - Recovery report fields asserted weakly (existence vs content)
   - Error paths that log instead of reject
   - Count §12.3 crash table rows (4) and §13 table rows (6) vs test evidence — which §13 rows are testable at this slice's scope and which are legitimately deferred to 2.3? Deferred rows must be named, not silently dropped.

6. LIES check — claims unsupported by the diff:
   - Summary claims a behavior no test exercises
   - Determinism claims with hidden clock/random/IO (controller must use injected Clock/IdGenerator — grep for datetime.now/uuid4 in graph_runtime)
   - "All tests pass" — verify yourself
   - The builder added an `agent_dispatch_requested` event emitted by the runtime controller after lease grants (not by the pure kernel). Is this consistent with PRD §12.3 step 1 ("Controller accepts lease_granted and agent_dispatch_requested events") and §28 rule 1 ("Only the controller can append accepted graph mutation events")? Is the added event present in the event log with correct envelope fields?

7. TESTING-STANDARDS check (project convention, non-negotiable):
   - NO mocks, NO monkeypatching anywhere in new/changed tests
   - Tests use real sqlite DBs (in-memory or tmp-file) and real files in tmp dirs
   - Tests never touch the main orchestrator.db
   - Module-scoped fixtures where appropriate; new integration files stay fast

8. VERDICT — exactly one of:
   - ACCEPT — every criterion evidenced, fresh run green, no laziness/lies findings
   - ACCEPT-WITH-PUNCHLIST — minor gaps; list them; none touches a core invariant
   - BOUNCE — gap list returned to the builder; slice is not done

Output format:
- Criteria table: # | criterion | code evidence | test evidence | status
- Findings list: severity (HIGH/MEDIUM/LOW) | laziness/lie/standards | description | location
- Verdict with one-paragraph justification.

Write the full report to stdout.
