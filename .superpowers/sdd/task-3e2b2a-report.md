# Task 3e2b2a Report

> Superseded corrective-wave evidence follows. The collector remains the sole
> projection-provenance authority; the compiler only reanchors its frozen facts.

## Corrective Wave

- `ProjectionCallContext` now includes the normalized selected receiver or
  argument expression and rejects negative positional slots. Both `*` and `**`
  expansion are recorded as ambiguous and never accepted as positional.
- An origin is retained only when metadata reports exactly one imported qualified
  name from an exact approved module segment. Foreign, conflicting, local, and
  dynamic callees consequently retain no origin.
- Reanchoring now compares exact callee/type origin, role, slot, selected
  expression, and literal physical-field evidence. It refuses stale argument,
  receiver, and physical-field facts.
- Projection-derived scalar/model values are never recorded as receiver or whole
  projection evidence. The sole finite derived-value sink is imported
  `orchestrator.graph.scheduler.NodeScheduleInfo`.

## Machine-derived structural snapshot

| Rule family | Count |
| --- | ---: |
| `derived_value_sink` | 1 |
| `projector_fixture_flow` | 2 |
| `public_graph_call` | 116 |
| `typed_projection_binding` | 27 |
| `typed_projector_binding` | 6 |

The derived sink origin snapshot is exactly
`orchestrator.graph.scheduler.NodeScheduleInfo: 1`; the remaining origin total
is 151, for 152 neutral operations. The generated-fixture snapshot is exactly
21: `nested_assignment: 17`, `literal_subscript_read` update/mutation: 3, and
`append_extend: 1`. Those IDs union with the reviewed 349 fixture IDs. No
unmatched/pending site remains; total closure is 803.

## Verification

- `uv run pytest tests/unit/test_graph_projection_inventory.py tests/unit/test_migrate_graph_projection_queries.py -q` — `124 passed in 229.04s`.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — `746 files already formatted`.
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv run pytest` — `5008 passed, 3 skipped, 3 warnings in 403.82s`; warnings are existing Python 3.12 `aiosqlite` datetime-adapter deprecations.

## Delivered

- Made `ProjectionCallContext` the authoritative frozen evidence carried by
  inventory occurrences and diagnostics.  It captures exact imported callee
  and type origins, receiver/positional/keyword/ambiguous roles, and physical
  old-field/access facts.
- Extended the collector's existing proven-flow families for typed bindings,
  nested comparison calls, projection-field receivers, approved producer
  returns, pass-throughs, and nested projection-bearing constructor calls.
  Starred positional calls remain ambiguous; unresolved, shadowed, dynamic,
  local-callee, and foreign origins do not gain a callee origin.
- Removed the codemod's duplicate `_structural_evidence` dataflow visitor,
  binding/provenance maps, local-producer synthesis, source-substring gate,
  `ProjectionArgumentEvidence`, and duplicate anchor evidence fields.
  Anchoring now copies stored collector context and only structurally
  revalidates exact callee/type origin and receiver/argument role with LibCST
  qualified-name metadata.
- Structural disposition planning now consumes only stored anchor context.
  It recognizes typed bindings, imported projector results, physical
  projection accesses, and public graph calls without site-level exceptions.

## Focused Coverage

- Added collector coverage for typed binding, one nested comparison call,
  field-update receiver/physical evidence, approved producer return, and bare
  typed pass-through context.
- Updated anchor coverage to assert copied collector context for imported,
  shadowed, wrong-position, dynamic, positional, and keyword calls, plus the
  existing mismatched-inventory-context refusal.

## Exact Evidence

- Programmatic grouping of all reviewed-neutral plus pending sites reported:
  `sites 803 neutral/pending 173 missing 0 {}`.
- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py::test_structural_plan_closes_reviewed_and_public_query_test_sites -q` — passed in 179.82s; asserts 803 identities, 201/80/173/349 disposition partition, and zero pending sites.
- `uv run pytest tests/unit/test_graph_projection_inventory.py tests/unit/test_migrate_graph_projection_queries.py -q` — `120 passed in 224.13s`.
- Generated diagnostic artifact check:
  `uv run python scripts/graph_projection_inventory.py --diagnose | diff -q - docs/graph-projection-inventory-diagnostics.md` — unchanged; no regeneration required.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — `746 files already formatted`.
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv run pytest` — `5004 passed, 3 skipped, 3 warnings in 452.67s`.  The warnings are existing `aiosqlite` Python 3.12 datetime-adapter deprecations.

## Concern

The repository-wide LibCST inventory/compiler tests remain intentionally
bounded by their explicit 300-second per-test timeout; the structural closure
test completed in 179.82 seconds in this verification run.
