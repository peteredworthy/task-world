# Task 6b2: all-resolver public outcome matrix

## Evidence

- `complete_projection_fixture()` remains valid and retains exact
  `PROJECTED_RECORD_TYPES` coverage. It now populates every executable resolver
  path, including optional grouped state and every relation-bearing projected
  record visitor field.
- The parameterized matrix expands normalized wildcard and map-role policies to
  deterministic concrete fixture locations. Each case persistently updates a
  real public immutable projection, validates the malformed projection through
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

- Dispatcher prefix fallback is removed. Runtime dispatch now requires one
  exact normalized policy pattern; wildcards and map roles must be explicit.
  Scalar policies reject appended segments, collection members dispatch through
  trailing `.*`, map identities use `.*.key`, and scalar map values retain
  `.*.value`. Container aliases were removed where an explicit key/member policy
  now owns the identity. The exhaustive matrix proves exact static resolver
  parity after materializing tuple members, nested map/tuple members, scheduling
  members, cleanup keys, and adjacency members.
- `EdgeValue` has no creation position or other authoritative ordering fact.
  The event reducer owns edge insertion order, while `FrozenMap` iteration is a
  persistent-map layout detail. Integrity therefore checks exact adjacency key
  sets, rejects duplicate IDs, and compares exact edge-ID membership as sets
  without changing the stored tuple order. Replay and golden tests remain the
  authority for adjacency ordering. Multi-edge tests prove validation is stable
  across different edge-map construction orders and assert exact diagnostics
  for duplicate, missing, and extra IDs. Adjacency policies now use explicit
  `topology.<field>.*.*` patterns, preserving diagnostics at
  `topology.<field>.<node-id>[<index>]`; repeated invalid IDs in separate tuples
   produce separate concrete diagnostics.
- Runtime static-policy matching now treats diagnostic strings as opaque concrete
  paths: escaped literals and anchored wildcard patterns preserve dotted and
  bracketed node, task, record, candidate, edge, and session identifiers.
  Explicit map role (and nested map depth where required) remains separate from
  identifier text; equally specific patterns still fail closed.
- The reviewed catalog now includes planner-session, callback, blocker-revision,
  nested gate, record-bound-position, adjacency, and structural nested-index key
  roles. Blocker keys resolve as revisions and must equal `revision_id`; callback
  keys retain explicit idempotency equality; represented gate keys resolve as nodes.
- Candidate ownership is checked consistently for node runtime state, verification
  results, invalid-test blocks, oversight decisions, and record visitors. Missing,
  ambiguous, and cross-task oversight candidates have exact diagnostics. Record
  index tuples retain replay order while integrity rejects duplicate, missing,
  and extra members; outer node keys must exactly match nodes with canonical indexes.

## Focused performance repair

- Before optimization, integrity plus codec took 33.87s. Profiling ten complete
  validations took 2.671s and attributed 2.514s cumulative to 681,450 runtime
  policy matcher calls, dominated by rebuilding and escaping every static regex.
- Runtime policy regexes are now compiled once per injected dispatcher and candidate
  policies are limited by the literal path root before matching. Ten profiled complete
  validations fell to 0.133s. The matrix also reuses one module-scoped immutable
  complete projection and creates malformed cases with persistent model/map updates,
  retaining every resolver-policy outcome and original-value unchanged assertion.
- After optimization, integrity plus codec took 2.11s. The exact requested four-file
  command completed 358 tests in 5.03s pytest time and 8.02s measured wall time.

## Visitor coverage

`complete_projection_fixture` still validates one instance of each concrete
`ProjectedRecord` model. Its assertion remains exact set equality against
`PROJECTED_RECORD_TYPES`, including relation-neutral records.

## Focused verification

```text
uv run pytest tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_models.py \
  tests/unit/test_graph_public_exports.py -q -n 0
# 358 passed in 5.03s; 8.02s measured wall time

uv run pyright
0 errors, 0 warnings, 0 informations

uv run ruff check tests/unit/test_graph_projection_integrity.py \
  src/orchestrator/graph/projection_codec.py
All checks passed!

uv run ruff format --check tests/unit/test_graph_projection_integrity.py \
  src/orchestrator/graph/projection_codec.py
2 files already formatted
```

The requested focused suite remains below 15 seconds wall time. No broad or full
suite was run manually.
