# Task 3e2b2a Collector and Anchor Corrective Report

## Current architecture

The inventory collector is the sole provenance authority. Frozen context carries
exact imported callee/type origin, selected receiver or argument expression,
role, slot, star evidence, and physical field/access facts. The codemod only
reanchors and requires exact equality; it never propagates provenance.

## Verification

- Ambiguous star evidence is XOR: direct expansion retains `argument_star`; a
  later unstarred argument retains `preceding_star`; both and neither are
  rejected. Anchoring requires the exact stored form.
- Physical context now retains an operation shape, permits fieldless
  `keys`/`values`/`items`, and independently verifies field, kind, and shape
  before accepting the receiver/call context.
- `uv run pytest tests/unit/test_graph_projection_inventory.py
  tests/unit/test_migrate_graph_projection_queries.py -q` — `125 passed in
  228.48s`.

Full corrective-wave counts are recorded in `task-3e2b2-report.md`.
