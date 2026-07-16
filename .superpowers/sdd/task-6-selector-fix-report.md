# Task 6 selector compatibility removal

## Result

Removed the historical selector compatibility layer from
`src/orchestrator/graph/models.py`:

- `_LEGACY_SELECTOR_KIND_MAP`
- `_normalize_legacy_selector` and its helper functions
- `RecordSelector`'s `mode="before"` normalization validator

`RecordSelector` now validates only the discriminated canonical selector union.
Legacy `record_kinds` and `value_matches` keys are rejected by the strict nested
models. Canonical selectors, including typed `any_of` selectors, are emitted by
the migrated test producers and fixtures.

The remaining `GapClassification` schema recognition in payload matching is a
current typed-record domain fact. It lets current dynamic gap ports such as
`classified_gap` bind to the canonical `gap_classification` selector without
reintroducing selector aliases.

## Coverage and migration

- Added focused model coverage for legacy-key rejection and canonical
  verification-selector round trips.
- Converted graph command, patch-validator, planner, projection, parent/child,
  acceptance, and integration fixture selectors to canonical `record_type`,
  `schema`, and `any_of` shapes.
- Preserved dynamic gap port names where they are current record-domain fields;
  selectors remain canonical.

## Verification

Passed:

```text
uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_dynamic_contract.py tests/unit/test_graph_planner.py tests/unit/test_patch_validator.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/unit/test_graph_api_projection.py tests/unit/test_graph_parent_child_translation.py tests/unit/test_graph_macros.py tests/unit/test_graph_compiler.py tests/unit/test_fixture_corpus.py -q
# 538 passed

uv run pytest tests/unit/test_w5_compatibility_removal.py tests/unit/test_fixture_corpus.py -q
# 21 passed

uv run pytest tests/integration/test_graph_fr03_acceptance.py tests/integration/test_graph_fr06_acceptance.py tests/integration/test_graph_fr08_acceptance.py tests/integration/test_graph_fr09_acceptance.py tests/integration/test_graph_fr14_final_gate_acceptance.py tests/integration/test_graph_decisions_api.py tests/integration/test_graph_parent_child_flow.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_planner_session_flow.py -q
# 17 passed

uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Static searches confirmed the removed compatibility symbols and selector keys
are absent from production source and graph fixtures.

## Concerns

No implementation concerns found. `.superpowers/sdd/progress.md` was already
modified before this task and is intentionally excluded from the commit.
