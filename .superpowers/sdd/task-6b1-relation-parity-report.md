# Task 6b1: Recursive identifier-path relation parity report

## Delivered

- Added deterministic discovery from the public `ImmutableGraphProjection`
  model graph. It resolves `Annotated` and unions, traverses tuples and
  `FrozenMap` key/value roles, descends into public frozen support models, and
  uses active-model cycle protection. Paths use `*` for collection positions
  and map values, and `.key` / `.value` where a map role must remain explicit.
- Defined the finite identifier discovery vocabulary: `_id`, `_ids`, `*_by_*` map values,
  every `FrozenMap` key, and the explicit semantic names for actor/source/
  target identity plus git ref/hash and callback-key fields.
- Replaced the old sample-only catalog assertion with exact set equality:
  discovered paths equal grouped-policy paths union the separately catalogued
  typed-record visitor paths. The negative test supplies a real frozen test
  root with an unreviewed `_id` field and receives that exact missing path.
- Materialized every reviewed entry in the sorted checked
  `scripts/codemods/graph_projection_relation_policy.yaml` artifact. Each entry
  records path, grouped/record scope, semantic family, rationale, and explicit
  resolver/external/derived disposition. The separately authored sorted
  `validation_paths` section mirrors resolver and typed-visitor branches rather
  than being generated from policy entries.
- Added strict frozen Pydantic loading with extra-field, path, scope,
  classification, duplicate, ordering, and resolver-contract validation. The
  runtime catalogs and validation-path API now load only this artifact;
  discovery remains independent and is used only for exact parity/gap audits.

## Classification note

Discovery and the checked artifact are always verified by exact set equality;
this report deliberately does not preserve historical generated counts. Later
Task 6b2 work expanded explicit nested-key roles and candidate ownership checks,
so its evidence is authoritative for current coverage.

## TDD and verification

The strict-loader and validation-contract tests were written first and failed
during collection because `load_projection_relation_policy` did not exist.
After the minimal loader/static-catalog implementation, malformed checked-data
cases and exact discovery/validation parity passed.  The dispatcher-boundary
tests were then added first: the test module initially failed to import the
missing finite resolver-call-site API.  The implementation makes the
dispatcher reject an unknown path, a wrong family, a non-resolver policy, and
a resolver policy omitted from the checked `validation_paths` contract.

Runtime node/task/record/candidate resolver visitors now enter the dispatcher
rather than invoking their family resolver directly.  The runtime bridge
normalizes the concrete diagnostic path to a checked static path before
dispatching, preserving the pre-existing diagnostic path and message.

## Task 6b1a intermediate fail-closed bridge

- Runtime matching now considers the complete static policy catalog before
  dispatch. Unknown and ambiguous normalized paths raise an explicit
  `ProjectionRelationPolicyError` without invoking any resolver. A unique
  match then goes through `resolve()`, so external/derived disposition, absent
  validation-path membership, and caller-family mismatches all fail closed.
- Removed the resolver fallback. Map keys which the integrity traversal sends
  through node, task, or record resolvers are now resolver policies with the
  represented family and explicit validation path. The candidate-key branch
  was already a resolver policy. Added the previously undiscovered node-key
  roles for topology input bindings, governance node-gate decisions, and usage
  recorded keys; calls for absent optional relation fields no longer enter the
  bridge.
- Concrete diagnostics remain unchanged. The bridge accepts only a key/value
  role hint where one concrete map diagnostic represents both roles; this
  keeps the checked paths unique without converting visitor call sites to
  literal policy tokens. Literal call-site conversion remains follow-up work.
- The checked artifact now has 228 policies (155 grouped and 73 record), with
  160 explicit resolver validation paths, 49 external policies, and 19 derived
  policies. Discovery independently reports the same 228 paths.

## Task 6b1b represented-family bridge completion

- Added local dispatcher-backed wrappers for requirement, revision, support,
  lease, cleanup, edge, and session relations. Typed-record visitors and
  grouped validators now use those wrappers for requirement addresses and
  grades, requirement record versions and supersession, failure leases,
  file-state cleanup, authority blocker relations, requirement revisions and
  support, planner and lease sessions, topology bindings, and applied cleanup
  IDs.
- Each branch dispatches represented existence before retaining map-key,
  same-requirement, and edge-target consistency checks. The wrappers return a
  represented object only for those secondary checks; direct membership and
  lookup diagnostics no longer bypass dispatcher policy.
- Reclassified the six executable canonical-key paths for cleanup requests,
  leases, active requirements, revisions, support, and edges from derived to
  resolver and added their validation paths. The artifact remains at 228
  policies (155 grouped and 73 record), now with 166 resolver, 49 external,
  and 13 derived policies.
- Added finite dispatcher tests for all seven families, including wrong-family
  fail-closed behavior without resolver invocation. A temporary AST structural
  guard rejects direct membership/get resolution against canonical family
  targets outside the local resolver closures. Literal static call-site parity
  remains the next subtask.

Focused Task 6b1b verification:

```text
uv run pytest tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_codec.py -q -n 0
# 80 passed in 1.03s

uv run ruff check src/orchestrator/graph/projection_codec.py \
  tests/unit/test_graph_projection_integrity.py
uv run ruff format --check src/orchestrator/graph/projection_codec.py \
  tests/unit/test_graph_projection_integrity.py
# all checks passed; 2 files already formatted

uv run pyright src/orchestrator/graph/projection_codec.py \
  tests/unit/test_graph_projection_integrity.py
# 0 errors, 0 warnings, 0 informations
```

Focused Task 6b1a verification:

```text
uv run pytest tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_codec.py -q -n 0
# 72 passed in 0.97s

uv run ruff check src/orchestrator/graph/projection_codec.py \
  src/orchestrator/graph/__init__.py tests/unit/test_graph_projection_integrity.py
uv run ruff format --check src/orchestrator/graph/projection_codec.py \
  src/orchestrator/graph/__init__.py tests/unit/test_graph_projection_integrity.py
# all checks passed; 3 files already formatted

uv run pyright src/orchestrator/graph/projection_codec.py \
  src/orchestrator/graph/__init__.py tests/unit/test_graph_projection_integrity.py
# 0 errors, 0 warnings, 0 informations
```

Focused verification after the final edits:

```text
uv run pytest tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_models.py -q -n 0
# 89 passed in 0.84s

uv run ruff check src/orchestrator/graph/projection_codec.py \
  src/orchestrator/graph/__init__.py \
  tests/unit/test_graph_projection_integrity.py
uv run ruff format --check src/orchestrator/graph/projection_codec.py \
  src/orchestrator/graph/__init__.py \
  tests/unit/test_graph_projection_integrity.py
# all checks passed; 3 files already formatted

uv run pyright src/orchestrator/graph/projection_codec.py \
  src/orchestrator/graph/__init__.py
# 0 errors, 0 warnings, 0 informations
```

## Scope and concerns

No runtime reducer, checkpoint encoding, migration, or traversal semantics
changed. The progress ledger was intentionally not modified. Canonical
map-key, index, and field-equality checks remain derived only when they do not
invoke a represented-state resolver. Adding an identifier-bearing annotation
changes discovery and fails parity until the checked artifact is deliberately
reviewed; tests never regenerate it. The finite resolver-call-site API is the
checked static contract, while production diagnostics retain their concrete
runtime strings through the normalizing bridge. Task 6b2 remains responsible
for exhaustive malformed checkpoint coverage.

The policy artifact was moved from the codemod location into
`orchestrator.graph`, included as Hatch wheel package data, and verified in a
built wheel. The progress ledger was intentionally not modified.
