You are auditing slice 1.8 (command applier + §14 task projection formula) implemented in the CURRENT WORKING TREE (uncommitted changes; see `git diff` and `git status` — ignore pre-existing modifications outside `src/orchestrator/graph/`, `tests/unit/`, `tests/fixtures/graph/`).

You are the AUDITOR in a builder→auditor→fixer pattern. You must NOT fix anything — only audit and report. Do not edit any file. Read-only plus running tests.

Ground truth documents (read these FIRST, before the diff or any summary):
- docs/graph-approach/execution-graph-prd-plus.md — sections §10.1, §14, §19, §27.2, §27.3
- docs/graph-approach/execution-graph-evaluation.md (where it amends the PRD)
- The slice definition: docs/graph-approach/phase-1-punch-list.md items P1-1, P1-2, P1-3, P1-7 and the "Slice 1.8" disposition paragraph.

Protocol — do these in order, do not skip steps:

1. RE-DERIVE acceptance criteria for this slice from the PRD sections above,
   ignoring the builder's summary entirely. Write them as a numbered list.

2. MAP each criterion to specific evidence: file:line for the implementation,
   and the exact test(s) that exercise it. A criterion with no test evidence
   is UNMET even if code exists.

3. RUN the test suite fresh (do not trust reported results):
   - uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py tests/unit/test_scheduler.py tests/unit/test_patch_validator.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py tests/unit/test_scenario_harness.py tests/unit/test_graph_commands.py -q
   (If uv cache permission errors occur, set UV_CACHE_DIR=/private/tmp/task-world-uv-cache.)

4. ADVERSARIAL pass — attempt one violation per invariant the slice claims.
   Specifically probe:
   - Edit nothing, but construct in a scratch python (run via `uv run python -c ...` or a throwaway file under /tmp, NOT in the repo) calls to apply_command that try: illegal run transition, callback with revoked lease, callback duplicate key different payload, patch with stale invalidating read-set, schedule_tick with expired lease, schedule_tick with future-expiry lease.
   - §14 formula: latest-candidate selection (attempt_number tie → event position), verdict with mismatched candidate_id must be ignored, gate unapproved → not accepted, invalid-test appeal accepted then replacement verification passes → state leaves blocked_invalid_test.
   For each, state the attack and observed result.

5. LAZINESS check — work avoided:
   - Fixtures still asserting events they injected in given_events (echo pattern). Count how many scenarios across ALL fixture files still have their then_events satisfiable purely by given_events with when_command: null. Distinguish legitimate pure-projection scenarios (assert then_projection of derived state) from theater.
   - then_projection keys asserting nothing or {} where the slice required real derivation.
   - Stubbed branches in commands.py (e.g. commands that emit success events without calling the kernel validators).
   - Error paths that emit accepted events instead of rejections.

6. LIES check — claims unsupported by the diff:
   - Builder claims "96 passed in 1.08s" and full fixture rewrite — verify by fresh run and by diffing the fixtures (git diff tests/fixtures/graph/).
   - Determinism: grep src/orchestrator/graph for datetime.now/time.time/random/uuid usage outside injected clock/id_gen.

7. TESTING-STANDARDS check (project convention, non-negotiable):
   - NO mocks, NO monkeypatching anywhere in new/changed tests
   - Tests pure/in-memory; kernel suite under 5 seconds
   - Commits not required (work is uncommitted by design)

8. VERDICT — exactly one of:
   - ACCEPT — every criterion evidenced, fresh run green, no laziness/lies findings
   - ACCEPT-WITH-PUNCHLIST — minor gaps; list them; none touches a core invariant
   - BOUNCE — gap list returned to the builder; slice is not done

Output format:
- Criteria table: # | criterion | code evidence | test evidence | status
- Findings list: severity | laziness/lie/standards | description | location
- Verdict with one-paragraph justification.

Write your full report to /tmp/codex-graph/audit-1.8-report.md (this is the ONE file you may write, outside the repo). End your reply with the verdict line only.
