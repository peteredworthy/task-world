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

## Visitor coverage

`complete_projection_fixture` still validates one instance of each concrete
`ProjectedRecord` model. Its assertion remains exact set equality against
`PROJECTED_RECORD_TYPES`, including relation-neutral records.

## Focused verification

```text
uv run pytest -q tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_models.py \
  tests/integration/test_graph_projection_public_parity.py
324 passed in 8.68s (11.19s wall)

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
