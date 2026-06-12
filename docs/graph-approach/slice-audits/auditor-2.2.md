You are auditing slice 2.2 (Routine compiler) of the task-world execution-graph kernel, implemented as uncommitted changes on branch main (see `git status`/`git diff`; new: `src/orchestrator/graph/compiler.py`, `src/orchestrator/graph_runtime/seeding.py`, `tests/unit/test_graph_compiler.py`, `tests/integration/test_graph_routine_compile.py`; modified: the two `__init__.py` exports).

Ground truth documents (read FIRST, before the diff or any summary):
- docs/graph-approach/execution-graph-prd-plus.md — §23.1–23.3 (compilation mapping table), §10 (node/edge/port), §11.3 (graph record), §15 (node kinds), §28 (functional restrictions, esp. rule 1: only the controller appends accepted graph mutation events), §29 item 1
- docs/graph-approach/execution-graph-evaluation.md §4.5 (minimal-graph risk this slice must close)
- The slice definition: "2.2 Routine compiler — Routine YAML → initial graph per §23.2 mapping table. Includes the minimal-graph requirement: a single-task routine compiles to the minimum executable graph. Done when: existing routines (incl. demo-task.yaml) compile; minimal-graph test passes; per-node controller overhead measured and bounded."

You are READ-ONLY: modify nothing. Running tests and read-only git is required.

Protocol — in order, no skipping:

1. RE-DERIVE acceptance criteria from the PRD sections + slice definition, ignoring the builder's summary. Numbered list. Include one criterion per §23.2 mapping-table row (8 rows).

2. MAP each criterion to evidence: file:line implementation + exact test(s). No test evidence = UNMET.

3. RUN fresh:
   - uv run pytest tests/unit/test_graph_compiler.py tests/integration/test_graph_routine_compile.py -q
   - uv run pytest tests/unit -q
   - kernel suite timing: uv run pytest tests/unit/test_graph_*.py tests/unit/test_scheduler.py tests/unit/test_patch_validator.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py tests/unit/test_scenario_harness.py -q (must stay under 5s)
   - uv run ruff check src tests

4. ADVERSARIAL pass — one attack per claimed invariant. At minimum:
   - Minimal-graph: is the "exact node set" test really exact (count AND kinds AND no extra edges), and is the minimal graph actually EXECUTABLE (test drives schedule_tick to a lease grant on the worker)? Could the compiler emit a hidden extra node the test doesn't see?
   - Determinism: same routine + same injected id_gen/clock → identical events. Is there any dict-iteration or set ordering that could differ?
   - Step ordering: do cross-step dependency edges actually BLOCK step-2 tasks until step-1 completes, proven through kernel readiness (not just edge existence)?
   - Purity: imports in compiler.py (re/typing/pydantic fine; any IO/YAML/loader/DB import is a violation). Builder decisions to weigh on the merits:
     (a) seeding bypasses GraphController and appends via GraphEventStore directly, justified as "topology/static facts, no outbox rows" — does this violate PRD §28 rule 1 or create a second append path that undermines the 2.1 atomicity invariant? Is the expected-position guard used? Would a compile seeded into a run with existing events corrupt ordering?
     (b) fan-out compiles to ONE reader template node with the worker doubling as synthesis/join — §23.2 says "Reader nodes plus synthesis/join node". Is this a faithful minimal representation or a dropped row? Is glob expansion legitimately runtime work (slice 2.3+) and is that documented?
     (c) task projection from task_region_id without task nodes; steps as edges-not-nodes — faithful to §23.2 "plan region or grouping projection"?
   - Overhead bound: is the assertion real (would fail on a pathological regression) or vacuous (e.g. < 10s per node)? Are the measured numbers recorded?

5. LAZINESS check: mapping rows tested with weaker assertions than the table implies; corpus test that only asserts "no exception" without sanity counts; requirement nodes/edges to worker AND verifier ports per §23.2 vs only worker; routine snapshot record carrying real identity/version vs empty placeholder; gate nodes only-when-configured actually tested both ways.

6. LIES check: summary claims vs diff (e.g. "every routine in routines/ compiles" — count the YAMLs the corpus test actually loads vs what exists in routines/ and examples/routines/; measured overhead numbers reproducible?).

7. TESTING-STANDARDS check: no mocks/monkeypatching; real YAML from repo; real tmp SQLite; main orchestrator.db untouched; new integration files fast.

8. VERDICT — ACCEPT / ACCEPT-WITH-PUNCHLIST / BOUNCE.

Output format:
- Criteria table: # | criterion | code evidence | test evidence | status
- Findings list: severity | type | description | location
- Verdict with one-paragraph justification.
