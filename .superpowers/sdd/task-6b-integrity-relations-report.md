# Task 6b: Projected-record and cross-family integrity report

## Delivered

- Replaced the record-level reflective `getattr` relation sweep with an explicit
  typed visitor covering every concrete member of the public `ProjectedRecord`
  union.  A finite `PROJECTED_RECORD_TYPES` tuple and a finite visitor-policy
  registry are checked for exact equality at import time; each record is either
  handled or documented as relation-neutral.
- Added record validation for source, cited, reused, candidate, file-state,
  verification, evaluated, rationale, task-region, failed-node, lease,
  cleanup, proposer, authority-envelope, and requirement relations where the
  destination store represents the target.
- Added a reviewed finite grouped relation-policy catalog.  It identifies
  resolver families for represented node/task/record/candidate/revision/support/
  lease/cleanup/edge/session relations and explicit `external` policy for git,
  snapshot, command, execution, artifact, and callback identifiers that cannot
  resolve within a projection checkpoint.
- Completed grouped checks for verification candidate indexes and invalid-test
  candidates, callback idempotency-key map identity, environment-failure task
  identity, final-invariant blocker source/proposal/requirement/revision/support
  relations, node authority-request envelopes, and file-state cleanup links.
- Expanded the ordinary nonempty fixture to populate task candidates,
  verification, requirements/support, leases, environment failures, callbacks,
  cleanup, and planner-session relation families coherently.

## TDD and verification

Added malformed checkpoint cases for a file-state cleanup reference and a node
authority-request envelope reference.  They failed before the visitor and
cross-family checks were implemented, then passed after implementation.

Focused verification passed:

```text
uv run pytest tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_models.py \
  tests/integration/test_graph_projection_public_parity.py -q
# 61 passed in 3.96s

uv run ruff check <five changed focused files>
uv run ruff format --check <five changed focused files>
# passed

uv run pyright src/orchestrator/graph/projection_codec.py \
  src/orchestrator/graph/projection_models.py
# 0 errors, 0 warnings
```

## Scope and concerns

No reducer, production cutover, schema, checkpoint-store, compatibility, or
repair behavior changed. Diagnostics remain deterministic and validation does
not mutate input. The progress ledger was deliberately left untouched and will
not be committed.

The relation catalog is intentionally explicit rather than inferred from field
names. New identifier-bearing fields therefore require a conscious resolver or
external-policy review; this is verbose by design and avoids silently treating
new IDs as valid graph references.
