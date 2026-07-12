# Tasks 4 and 6 implementation report

## Metrics

| Verification | Result |
|---|---|
| Inherited focused baseline | 150 failed, 266 passed |
| Lease codemod `--assert-clean` | pass; no remaining rewrite |
| Lease domain inventory | pass; 44 events / 23 commands |
| Patch codemod `--assert-clean` | pass after final `--apply`; no remaining rewrite |
| Patch domain inventory | pass; 44 events / 23 commands |
| Payload architecture guard | pass |
| Ruff | pass; all checks passed |
| Pyright | pass; 0 errors, 0 warnings |
| Dynamic path and immutability regressions | 2 passed |
| Full suite before final immutability repair | 1 failed, 4732 passed, 5 skipped |
| Final full suite | 4733 passed, 5 skipped, 3 warnings in 81.20s |

## Decisions

- Lease and patch event payloads are strict catalog-owned Pydantic models; removed legacy lease models were not restored and `lease_suspended` remains absent **from the catalog and strict path**. Its branches inside `reduce_legacy_event`, `_planner_generation_state`, and the `GraphRecordKind` enum are deliberately retained until Task 9 (Deferred Compatibility Cleanup Register, entry D1), as is the `graph_patch_proposed` bookkeeping (entry D2) — durable history must replay until the Task 13 database cutover.
- The typed schedule command owns lease scheduling semantics, including lease duration, grant limits, snapshot identity, priorities, region ordering, and lease identifiers. It no longer delegates through `_node_schedule_info` in `_commands.py`.
- Lease grants require complete snapshot, expiry, and resource-claim data. Renewal remains strict and heartbeat validation preserves the existing identity, generation, and TTL policy.
- Lease revocation requires explicit execution identity, reason, and trigger. All lifecycle/cancellation producers now supply those facts; `commands/lease_bridge.py` remains deleted.
- Patch commands and events retain explicit actor role, proposer, operations/macros, diagnostics, read-set differences, and managed-callback metadata. Unknown keys remain forbidden.
- Terminal lease mutations refresh derived task-region state. Projection copies remain isolated while using shallow Pydantic model copies to avoid replay-time blowups.
- Mechanical Python and YAML producer/fixture migration is encoded in the LibCST codemod and was applied before any residual semantic edits. Intentional invalid events use only `append_events(..., allow_invalid_payloads=True)`.
- Task 5 was not modified.

## Outcome

Implementation and every required verification gate are green. The combined Task 4/6 change was committed as `14c32a73c` (single combined commit; the plan prescribed one commit per domain). Independently re-verified 2026-07-12: codemod assert-clean and inventory checks for both domains, architecture guard, 416 targeted tests, Ruff, Pyright 0 errors, full suite 4,733 passed / 5 skipped.
