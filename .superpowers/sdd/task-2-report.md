# Task 2 — Canonical OTel Usage Facts and Cost Resolution

## Scope delivered

- Replaced `ModelTokenUsage`'s mutable, rate-embedded representation with the canonical OTel fields: model, input/output/cache/reasoning usage, plural finish reasons, latency, and explicit `rate_missing`.
- Made usage facts frozen and validated every count as nonnegative. A model-level validation rejects cache-read plus cache-creation values greater than input.
- Added `ModelCostResolution` and `resolve_model_costs`. Exact and prefix matches set `rate_missing=False`, including deliberately zero-priced entries; an absent lookup sets it to `True`.
- Updated extraction to append frozen per-execution model facts rather than mutating grouped facts, and copied the resolver's lookup state into each fact.
- Preserved correct cost semantics in the temporary legacy cost accessor: cache components are removed from normal input billing, charged at their own rates, and observable reasoning tokens are not charged a second time.

## TDD evidence

### Required initial RED command

```text
$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py tests/unit/test_cost.py -q -n 0
ERROR collecting tests/unit/test_model_costs.py
ImportError: cannot import name 'resolve_model_costs' from 'orchestrator.runners.costs'
1 error in 2.04s
```

This failed for the intended missing resolver interface before production implementation.

### Additional RED for temporary cost compatibility semantics

After adding the cache/reasoning pricing test and temporarily removing the property under test:

```text
FAILED TestModelTokenUsage.test_prices_cached_input_once_and_does_not_double_charge_reasoning
AttributeError: 'ModelTokenUsage' object has no attribute 'total_cost_usd'
1 failed, 20 passed in 2.08s
```

### Required GREEN command

```text
$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py tests/unit/test_cost.py -q -n 0
22 passed in 2.04s
```

### Broader verification

```text
$ uv run pytest tests/unit -q -n 0
3460 passed, 1 skipped, 3 warnings in 76.20s

$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py tests/unit/test_cost.py tests/integration/test_attempt_store_event_sourcing.py -q -n 0
25 passed in 0.68s
```

The first all-files pre-commit run exposed a legacy aggregation boundary that was not part of Task 2's target surfaces. The bridge now translates old serialized token keys before canonical validation; the directly reproducing integration test passes.

Final mandatory hook verification:

```text
$ uv run pre-commit run --all-files
ruff (legacy alias) Passed
ruff format Passed
Detect hardcoded secrets Passed
pyright Passed
pytest Passed
module-imports Passed
signal-routing Passed
enum-drift Passed
ui-lint Passed
ui-typecheck Passed
```

## Transitional bridge — mandatory Task 3 removal

The full repository still contains untouched readers, constructors, serialized payload aggregation, and presenters using pre-OTel names and embedded rates. To keep the suite committable before Task 3's repository-wide codemod application, `ModelTokenUsage` temporarily provides:

- legacy constructor-key translation;
- computed legacy serialization/read fields (`input_tokens`, cache fields, and `cost_per_m_*`); and
- `get_model_costs`, a legacy dict wrapper around `resolve_model_costs`.

These bridges are explicitly marked in production code. Task 3 **must migrate all callers and remove them**, leaving persisted facts with only canonical OTel fields and consuming `ModelCostResolution.rate_missing` directly.

## Notes

Provider parser wire keys were not renamed or normalized in this task; Task 2 only defines the canonical fact and its extraction boundary, preserving the requested parser-boundary ownership for the later application task.

## Review-fix follow-up

### RED

```text
$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py tests/unit/test_cost.py -q -n 0
8 failed, 14 passed in 2.15s
```

The failures demonstrated mutable finish-reason lists, conflicting canonical and
legacy values being silently overwritten, exclusive cache input rejected before
normalization, zero-parent sub-agent loss, and first-prefix rather than longest
prefix resolution.

### GREEN

```text
$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py tests/unit/test_token_fallback_from_entries.py tests/integration/test_attempt_store_event_sourcing.py -q -n 0
27 passed in 0.68s

$ uv run pytest tests/integration/test_api_runs.py::test_get_run_returns_token_usage_by_model_with_all_fields tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py -q -n 0
17 passed in 0.80s

$ uv run pre-commit run --all-files
all hooks passed (ruff, format, gitleaks, pyright, pytest, module-imports,
signal-routing, enum-drift, ui lint, ui typecheck)
```

### Review fixes

- `ActionLog` and `SubAgentLog` now carry explicit input-includes-cache
  semantics. Claude parser paths mark exclusive raw provider input; Codex paths
  mark inclusive input. Extraction normalizes only exclusive inputs while
  retaining parser wire names.
- Finish reasons remain list-shaped at the public/JSON boundary but are held by
  a mutation-rejecting list implementation internally.
- Cost resolution performs exact lookup before deterministic longest,
  delimiter-valid forward/reverse prefix matching.
- Extraction resolves rates once, calculates `cost_usd` from that same
  resolution, and stores the result on the immutable fact. State has no runners
  import or dynamic rate lookup.
- Mixed canonical/legacy input rejects conflicting values. The narrow legacy
  serializer remains only to keep untouched aggregation/read paths committable;
  its projector keeps both forms synchronized.

### Mandatory Task 3 removal list

Remove all of the following after callers use canonical fields: legacy
constructor translation, computed `input_tokens`/cache/count and
`cost_per_m_*` fields, legacy-rate private storage and legacy-cost initialization,
duplicated bridge serialization, projector synchronization of legacy names, and
`get_model_costs`. Keep `cost_usd`, `rate_missing`, immutable reasons, and
canonical extraction facts.

## Final invariant follow-up

RED evidence:

```text
$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py -q -n 0
11 failed, 28 passed in 0.99s
```

The failures covered remaining list mutators and invalid negative/non-finite
legacy rates.

GREEN evidence:

```text
$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py tests/unit/test_claude_parser.py tests/unit/test_codex_parser.py tests/unit/test_codex_server_common.py tests/unit/test_cost.py -q -n 0
196 passed in 2.65s

$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py tests/unit/test_cost.py -q -n 0
45 passed in 2.09s
```

The bridge projection additionally sums reasoning output and latency, ORs
`rate_missing`, and retains ordered de-duplicated finish reasons. These bridge
aggregation rules are removed with the other Task 3 bridge items.

## Transitional boundary follow-up

RED: `uv run pytest tests/unit/test_model_token_usage.py -q -n 0` produced two failures for nonnumeric legacy rates and overflow-derived cost.

GREEN: `uv run pytest tests/unit/test_model_token_usage.py -q -n 0` produced `33 passed in 0.81s` after rate boundary validation and finite `cost_usd` enforcement.

## Remaining review checklist follow-up

### RED

```text
$ uv run pytest tests/unit/test_model_token_usage.py tests/integration/test_attempt_store_event_sourcing.py -q -n 0
ImportError: cannot import name 'ExecutionMetrics' from 'orchestrator.runners'
2 errors in 0.32s
```

The public runner boundary was absent. Source review also found the legacy-rate
constructor substituted `0.0` for non-`int`/`float` values before Pydantic
validation; a strict typed rate snapshot now validates all four rates before
any float conversion or cost arithmetic. The focused `ExplosiveNumeric` test
would raise if either operation were attempted.

The existing event-sourced merge implementation already satisfied the newly
added complete aggregation assertion, so no artificial RED was manufactured:
the test covers canonical/legacy count synchronization, reasoning and latency
sums, cost sum, `rate_missing` OR behavior, and ordered de-duplicated reasons.

### GREEN

```text
$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py tests/unit/test_cost.py -q -n 0
49 passed in 2.06s

$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py tests/unit/test_cost.py tests/unit/test_claude_parser.py tests/unit/test_codex_parser.py tests/unit/test_codex_server_common.py tests/integration/test_attempt_store_event_sourcing.py -q -n 0
203 passed in 1.15s
```

The Claude sub-agent regression constructs a real `tmp_path` Claude projects
tree and JSONL log, calls `load_sub_agents`, verifies its exclusive-input
marker, then places the returned log in real `ActionLog`/`ExecutionResult`
objects and confirms cache components are added exactly once during extraction.

### Final mandatory hook verification

```text
$ uv run pre-commit run --all-files
ruff (legacy alias)......................................................Passed
ruff format..............................................................Passed
Detect hardcoded secrets.................................................Passed
pyright..................................................................Passed
pytest...................................................................Passed
module-imports...........................................................Passed
signal-routing...........................................................Passed
enum-drift...............................................................Passed
ui-lint..................................................................Passed
ui-typecheck.............................................................Passed
```

## Narrow transitional bridge follow-up

### RED

```text
$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py -q -n 0
2 failed, 43 passed in 0.98s
```

Without legacy rate keys, the bridge validated an all-default rate model and
entered its `int()`-based legacy cost calculation. The new regressions showed a
malformed canonical token count escaping as raw `ValueError` and an explosive
canonical numeric reaching that legacy arithmetic instead of Pydantic
validation.

### GREEN

```text
$ uv run pytest tests/unit/test_model_token_usage.py tests/unit/test_model_costs.py tests/unit/test_cost.py -q -n 0
51 passed in 2.07s
```

The bridge now validates/stores rates and computes a legacy-derived cost only
when at least one legacy rate key is supplied. Canonical construction therefore
reaches normal Pydantic validation without legacy conversion or arithmetic.
`test_model_costs.py` imports all public cost symbols through
`orchestrator.runners`; its only private cost-table access is local to the
reset fixture.

The first repository-wide hook run exposed an existing xdist interaction:
Alembic migration setup disabled the bootstrap logger with `fileConfig`'s
default `disable_existing_loggers=True`, causing an existing warning-capture
test to fail only after file-backed migration tests. The migration setup now
preserves existing loggers; the bootstrap regression passes in the focused and
full hook runs.

### Final mandatory hook verification — narrow bridge follow-up

```text
$ uv run pre-commit run --all-files
ruff (legacy alias)......................................................Passed
ruff format..............................................................Passed
Detect hardcoded secrets.................................................Passed
pyright..................................................................Passed
pytest...................................................................Passed
module-imports...........................................................Passed
signal-routing...........................................................Passed
enum-drift...............................................................Passed
ui-lint..................................................................Passed
ui-typecheck.............................................................Passed
```
