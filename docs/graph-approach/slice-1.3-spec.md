# Slice 1.3 — Fixture Corpus (loop mode, medium)

Phase 1 slice: transcribe every PRD table row into an executable §27.3-format
YAML fixture. No reducers — fixtures only. The harness from slice 1.2 loads them
and runs them; projections may return empty stubs for now (then_projection keys
that can't be resolved yet go into a known-pending list).

Done when: a gap-analyst script confirms 1:1 — every required PRD table row has
a fixture id, and all fixtures parse and load without error.

## Ground truth

`docs/graph-approach/execution-graph-prd-plus.md` — every table row is one
fixture (or at most two if a row has a notable happy-path + error-path variant).

## Scope

### 1. Fixture files

Create `tests/fixtures/graph/` directory with one YAML file per coverage group:

**`run_lifecycle.yaml`** — one scenario per row of the §10.1 run lifecycle
transitions table (9 transitions: draft→queued, queued→active, active→pausing,
pausing→paused, paused→resuming, resuming→active, active/paused→cancelling,
cancelling→cancelled, active→completed, any-nonterminal→failed). Each scenario
has `given_events` and `when_command` that trigger the transition; `then_events`
lists the state-changed event; `then_projection` is left empty or `{}` for now.

**`node_lifecycle_worker.yaml`** — scenarios for §15.1 worker transitions table
(6 rows): planned→ready, ready→leased, leased→running, running→completed,
running→suspended, running→failed, planned/ready→retired.

**`node_lifecycle_verifier.yaml`** — §15.2 verifier transitions (5 rows).

**`node_lifecycle_check.yaml`** — §15.3 check and recovery transitions (5 rows).

**`node_lifecycle_gate.yaml`** — §15.4 gate transitions (3 rows).

**`node_lifecycle_appeal.yaml`** — §15.5 appeal/oversight transitions (3 rows).

**`stale_callbacks.yaml`** — one scenario per row of the §19 stale callback
table (9 cases): duplicate-same-payload, duplicate-different-payload,
revoked-lease, old-generation, success-after-retry, failure-after-completed,
approval-after-cancel, resume-after-cancel, pause-callback-race.

**`task_projection.yaml`** — one scenario per formula state from §14 task
projection formula (6 states): accepted, needs_revision, blocked_invalid_test,
blocked_environment, in_progress, pending.

**`invariants.yaml`** — one scenario per §27.2 invariant (10 invariants). Each
scenario is a `given_events` sequence that should either prove or demonstrate the
invariant. Label each with `invariant_id` in a `meta:` block.

### 2. Coverage index

`tests/fixtures/graph/COVERAGE.md` — a table mapping every PRD section + row to
a fixture name. Format:

```markdown
| PRD Section | Row/Case | Fixture File | Scenario Name |
|---|---|---|---|
| §10.1 run lifecycle | draft→queued | run_lifecycle.yaml | run_draft_to_queued |
| ... | ... | ... | ... |
```

### 3. Loader test

`tests/unit/test_fixture_corpus.py`:

- `test_all_fixtures_parse` — for each YAML file in `tests/fixtures/graph/`,
  load it with `yaml.safe_load`, assert it's a list or dict, assert every
  scenario has `name` and `given_events`.
- `test_all_fixtures_run_through_harness` — for each scenario in each file, call
  `run_scenario(scenario, InMemoryEventStore(), FakeClock(), SequentialIdGenerator())`.
  Collect results. Assert zero `ScenarioParseError` (harness must not crash).
  Projection failures are acceptable (reducers not implemented yet) but must be
  captured in `result.failures`, not exceptions.
- `test_coverage_index_complete` — parse COVERAGE.md, assert at least 40 rows
  present (rough lower bound on PRD table coverage).
- `test_fixture_names_unique` — assert no two scenarios across all files share
  the same `name`.

4 tests total. No mocks, no IO beyond reading YAML files. Tests run from project
root — `yaml` stdlib available via pyyaml already a dependency.

## Done when

- All 4 tests pass.
- `tests/fixtures/graph/` has ≥8 YAML files, ≥40 scenarios total.
- COVERAGE.md has ≥40 rows.
- No fixture crashes the harness (parse errors count as failures).

## Standards

- YAML only for fixtures (no Python in fixture files).
- Fixture `name` values are snake_case, unique, descriptive.
- `then_projection` may be `{}` or omitted where reducers aren't implemented yet.
- NO mocks, NO monkeypatching. Tests use real yaml + real harness.
- No imports from app layer.
- Regular commits; run `uv run pytest tests/unit/test_fixture_corpus.py -v`
  before each commit.
