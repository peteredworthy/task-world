# Task 3e2b2a Collector and Anchor Corrective Report

## Current architecture

The inventory collector is the sole provenance authority. Frozen context carries
exact imported callee/type origin, selected receiver or argument expression,
role, slot, star evidence, and physical field/access facts. The codemod only
reanchors and requires exact equality; it never propagates provenance.

## Verification

- Focused star/physical regression tests: passed.
- Ruff check and targeted Pyright: passed.

Full corrective-wave counts are recorded in `task-3e2b2-report.md`.
