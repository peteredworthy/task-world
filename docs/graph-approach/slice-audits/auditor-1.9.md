You are auditing slice 1.9 (readiness completion + resource matrix + planner/review fixtures) implemented in the CURRENT WORKING TREE (uncommitted; slice 1.8 changes are also present and already audited — your focus is the 1.9 delta, but regressions in 1.8 behavior are in scope).

You are the AUDITOR in a builder→auditor→fixer pattern. Do NOT fix anything. Do not edit any repo file. Read-only plus running tests. You may write exactly one file: /tmp/codex-graph/audit-1.9-report.md.

Ground truth (read FIRST):
- docs/graph-approach/execution-graph-prd-plus.md — §10.5, §15.6, §15.7, §17, §18 (path rules, conflict matrix, §18.2 default policy)
- docs/graph-approach/phase-1-punch-list.md — items P1-4, P1-5, P1-6 (P1-8 was closed in 1.8)
- Slice definition: the "Slice 1.9" disposition paragraph in the punch list.

Protocol — in order, no skipping:

1. RE-DERIVE acceptance criteria from §17 (readiness criteria 1–8), §18 (every matrix cell + path rules 1–4 + §18.2 reader-during-writer policy), §15.6 and §15.7 (every transition table row), ignoring the builder's summary. Numbered list.

2. MAP each criterion to file:line implementation evidence and exact test/fixture evidence. No test evidence = UNMET.

3. RUN fresh:
   uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py tests/unit/test_scheduler.py tests/unit/test_patch_validator.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py tests/unit/test_scenario_harness.py tests/unit/test_graph_commands.py -q
   Record count and wall time. (UV_CACHE_DIR=/private/tmp/task-world-uv-cache if perms issue.)

4. ADVERSARIAL pass — scratch python under /tmp (never in the repo), one probe per claim:
   - required input port unbound → node not ready, reason missing_required_input
   - optional input unbound → node ready
   - upstream required dependency failed → blocked, reason upstream_failed; recovery/oversight node consuming the same failure → ready
   - gate undecided → blocked; gate rejected → blocked; gate approved → ready
   - glob overlap: write src/** vs read src/foo.py live → conflict; vs read with snapshot_id → compatible; src/** vs docs/** → no conflict
   - path escape: claim with ../outside → treated conflicting/rejected
   - external same key, one exclusive → conflict; different keys → compatible
   - review_write vs write → conflict; graph_write vs graph_write → conflict (serialized); graph_write vs write → compatible
   - planner completes but its patch is rejected → planner node stays completed, patch rejection event present
   - 1.8 regression spot-check: configured undecided gate still blocks §14 accepted; snapshot_incompatible still rejects
   For each: attack, observed result.

5. LAZINESS check:
   - Matrix cells without a dedicated test (count vs the 25-cell §18 table; name missing cells)
   - §15.6/§15.7 table rows without a fixture (count rows vs scenarios)
   - Readiness reasons asserted only as truthy rather than exact reason strings
   - node_deferred/node_ready events emitted but never reduced or asserted
   - Glob implementation shortcuts (e.g. fnmatch on raw strings without normalization; '**' handling that fails 'src/**' vs 'src/a/b/c.py')
   - COVERAGE.md rows not matching actual fixtures (spot-check 5)

6. LIES check:
   - Builder claims "133 passed in 1.27s", matrix completion, criteria 3–5 with explicit reasons — verify each by fresh run, grep, and the adversarial probes
   - Determinism: grep src/orchestrator/graph for filesystem/glob.glob/os.walk/datetime.now/random/uuid (posixpath/fnmatch pure use is fine)

7. TESTING-STANDARDS: no mocks/monkeypatching in new tests; suite under 5s; pure/in-memory.

8. VERDICT — exactly one of ACCEPT / ACCEPT-WITH-PUNCHLIST / BOUNCE.

Output format: criteria table (# | criterion | code evidence | test evidence | status), findings list (severity | type | description | location), verdict + one-paragraph justification. Write the full report to /tmp/codex-graph/audit-1.9-report.md and end your reply with the verdict line only.
