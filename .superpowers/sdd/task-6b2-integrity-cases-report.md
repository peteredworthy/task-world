# Task 6b2: all-resolver public outcome matrix

## Evidence

- `complete_projection_fixture()` remains valid and retains exact
  `PROJECTED_RECORD_TYPES` coverage. It now populates every executable resolver
  path, including optional grouped state and every relation-bearing projected
  record visitor field.
- The parameterized matrix expands normalized wildcard and map-role policies to
  deterministic concrete fixture locations. Each case mutates a real public
  checkpoint, validates a model-valid malformed projection through
  `validate_projection_integrity`, and asserts the exact concrete path and
  family reason. Key/embedded consistency cases also assert their exact
  structural reason.
- Every case verifies that the original valid immutable projection is unchanged.
- Record-scope policies retain one case per concrete relation-bearing record
  visitor type rather than collapsing shared fields to one representative.

## Policy classification

The matrix's policy-path set is exactly equal to the packaged static policies
whose validation is `resolver`; this is set equality, not count evidence. No
resolver policy lacks a populated executable fixture location. External and
derived policies remain nonresolver and are excluded from malformed-reference
expectations. The canonical task-owned candidate declaration is now explicitly
derived rather than incorrectly describing a self-resolution as resolver
evidence.

## Validator paths exposed

The red matrix exposed and the implementation now covers canonical embedded
identities, record summaries, topology adjacency values and binding targets,
planning map key/value roles, verification embedded identities, and governance
decision target regions. Canonical key families resolve against embedded
identities so key mutations cannot validate themselves. Existing explicit
same-parent requirement/revision and candidate/task semantic cases remain.

## Final Important findings

- Non-wildcard dispatcher fallback now accepts only the reviewed direct-map-key
  shape: exactly one concrete segment below the static policy path. A public
  dispatcher test proves that shape dispatches and that deeper unreviewed
  descendants fail without invoking a resolver. Existing ambiguous,
  wrong-family, nonresolver, and missing-validation-path behavior remains
  covered.
- `EdgeValue` has no creation position or other authoritative ordering fact.
  The event reducer owns edge insertion order, while `FrozenMap` iteration is a
  persistent-map layout detail. Integrity therefore checks exact adjacency key
  sets, rejects duplicate IDs, and compares exact edge-ID membership as sets
  without changing the stored tuple order. Replay and golden tests remain the
  authority for adjacency ordering. Multi-edge tests prove validation is stable
  across different edge-map construction orders and assert exact diagnostics
  for duplicate, missing, and extra IDs.

## Visitor coverage

`complete_projection_fixture` still validates one instance of each concrete
`ProjectedRecord` model. Its assertion remains exact set equality against
`PROJECTED_RECORD_TYPES`, including relation-neutral records.

## Focused verification

```text
uv run pytest -q tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_codec.py
300 passed in 8.42s (11.13s wall)

uv run pyright
0 errors, 0 warnings, 0 informations

uv run ruff check tests/unit/test_graph_projection_integrity.py \
  src/orchestrator/graph/projection_codec.py
All checks passed!

uv run ruff format --check tests/unit/test_graph_projection_integrity.py \
  src/orchestrator/graph/projection_codec.py
2 files already formatted
```

The requested focused suite remains below 15 seconds wall time. No broad or
full suite was run.
