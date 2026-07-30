# Task 6b2: immutable projection integrity cases

## Evidence

- `tests/unit/test_graph_projection_integrity.py` now has a coherent valid
  `complete_projection_fixture`.  It contains every concrete member of
  `ProjectedRecord`, including visitor-neutral records, and invokes the public
  `validate_projection_integrity` API successfully.
- The fixture's record index and summary index are rebuilt from its canonical
  records, so validation exercises the normal index/adjacency integrity path
  rather than an isolated model validator.
- Public malformed-projection cases assert exact diagnostics for cleanup,
  failure-node, requirement-version, candidate, and topology relations.
- The runtime dispatcher tests remain outcome tests for unknown, ambiguous,
  wrong-family, external/derived, and missing-validation-path policies.

## Policy classification

The packaged policy catalogue remains the authority for resolver, external,
and derived classifications.  Existing policy-discovery tests retain exact
catalogue/discovery parity and explicit external/derived rationales.  The
removed `projection_relation_resolver_call_sites()` alias was a direct echo of
the catalogue and is no longer exported or presented as executable evidence.

## Visitor coverage

`complete_projection_fixture` validates one instance of each concrete
`ProjectedRecord` model.  Its assertion is exact set equality against
`PROJECTED_RECORD_TYPES`; this includes explicit relation-neutral record
families as well as relation-bearing visitors.

## Focused verification

```text
uv run pytest tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_models.py \
  tests/integration/test_graph_projection_public_parity.py -q
114 passed in 5.62s
```
