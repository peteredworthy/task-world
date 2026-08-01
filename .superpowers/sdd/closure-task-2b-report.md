# Closure Task 2b Report

## Status

`COMPLETE` — the authorized focused reducer cleanup resolved the isolated
codec defect; the complete matrix and focused regression suite are green.

## RED inventory and evidence

Replaced the two narrow regressions with a model-derived matrix in
`tests/unit/test_graph_projection_flexible_json.py`.

The recursive walker follows `Annotated`, unions, type aliases, tuples, and
`FrozenMap` values; it stops at `FrozenJsonValue` and walks reachable frozen
projection models. It discovers exactly the brief's 29 declaring fields, and
the independent event-backed case-key registry has the same 29 keys.

Command:

```text
uv run pytest tests/unit/test_graph_projection_flexible_json.py::test_flexible_json_cases_exactly_match_reachable_model_fields -q
```

Result:

```text
1 passed in 3.93s
```

The full six-probe run was intentionally RED:

```text
uv run pytest tests/unit/test_graph_projection_flexible_json.py -q
51 failed, 124 passed in 4.25s
```

Among that output, the following is an isolated production failure with a
relationship-valid stream (a unique node followed by
`authority_decision_recorded`) and no checkpoint modification:

```text
AuthorityDecisionValue.scope-array
pydantic ValidationError: scope
Value error, expected a canonical JSON scalar, list, tuple, or dictionary;
got FrozenMap [input_value=(1, FrozenMap({'nested': (False, None)}))]
```

The reducer first calls `freeze_json` on the event's valid JSON array, then
`AuthorityDecisionValue`'s before-validator calls `_freeze_json_input` again.
That input is the canonical frozen tuple/FrozenMap representation, which the
validator rejects. The identical shape affects approval and oversight scope
array probes. This is a real model-boundary/reducer codec defect, not a probe
or relationship-integrity failure.

## Scope preserved

The matrix retains the semantic coverage of commit `48cf1b55f`'s approval
scope and oversight decider nested-JSON regressions. It uses the required
direct, map-value, and tuple-map-value adapters, plain checkpoint JSON
assertions, restored-projection equality, selected-value equality, and deep
immutability assertions.

## Files

- Modified (uncommitted): `tests/unit/test_graph_projection_flexible_json.py`
- Added (uncommitted, task report):
  `.superpowers/sdd/closure-task-2b-report.md`
- No production files changed.

## Authorized focused production fix

After reproducing the isolated `AuthorityDecisionValue.scope-array` failure
directly, removed only the redundant `freeze_json()` calls for decision scope
and non-string oversight decider from `_decision_value()` in
`src/orchestrator/graph/projections.py`. The existing model validators are now
the single boundary for both live reduction and checkpoint decoding. The
separate callback-payload `freeze_json()` use remains unchanged.

The decision-only probe group then passed except for expected checkpoint
omission of explicit `None`; producers now read omitted optional checkpoint
fields as `None`. The remaining failures were all case construction issues:

- `accepted_record_selector` and callback payloads require an outer object in
  canonical event models, so their probes use the required `map-value`
  adapter;
- fan-out `value` requires an outer object and is read directly from the
  record value rather than as a nested model attribute;
- check/verification streams now create their unique task/candidate
  prerequisites; graph-patch producers reference their own unique producer
  node; and routine-snapshot producers use `graph_record`.

No additional production codec defect was found.

## GREEN / verification evidence

Complete model-derived matrix:

```text
uv run pytest tests/unit/test_graph_projection_flexible_json.py -q
175 passed in 3.38s
```

Requested focused suite:

```text
uv run pytest tests/unit/test_graph_projection_flexible_json.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_models.py -q
232 passed in 4.65s
```

Static checks:

```text
uv run ruff format tests/unit/test_graph_projection_flexible_json.py
uv run ruff check tests/unit/test_graph_projection_flexible_json.py \
  src/orchestrator/graph/projections.py
uv run pyright tests/unit/test_graph_projection_flexible_json.py \
  src/orchestrator/graph/projections.py
```

All passed (`pyright`: 0 errors, 0 warnings, 0 informations).

## Commit evidence

Implementation commit:

```text
5020f4757 test(graph): cover flexible projection json matrix
```

Normal hooks passed: ruff, ruff format, secrets, pyright,
graph-projection-boundaries, pytest, module-imports, signal-routing, ui-lint,
and ui-typecheck (enum-drift skipped because no matching files). The commit
includes exactly the matrix test, the authorized reducer cleanup, and this
report; the pre-existing `.superpowers/sdd/progress.md` edit is excluded.
