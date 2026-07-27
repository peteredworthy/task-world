# Task 3b Report: Node, Task, Edge, Binding, and Lease Queries

## Status

Complete. The node/task/edge/binding and lease query boundary is implemented,
exported through `orchestrator.graph`, and represented by reviewed executable
ledger dispositions. No broad consumer was edited and no codemod was applied.
`.superpowers/sdd/progress.md` was left untouched.

## Query Surface

- **27 new query APIs** (30 total query functions, including the three Task 3a
  queries).
- Node APIs cover existence; kind, role, creation position, and task region;
  state, attempt, candidate, failed candidate, deferred reason, and retry
  deadline; action/precondition sequences; command definitions; and resource
  claims.
- Task APIs cover state and ordered candidates.
- Topology APIs cover lookup, ordered iteration, incoming/outgoing adjacency,
  bindings by node/port, and ordered bound record IDs.
- Lease APIs cover lookup, ordered iteration, active selection, and generation.
- Collection results are tuples and projection model results are deep copies,
  so no mutable projection container is exposed.

## Ledger Dispositions

Fresh-inventory targeted-site counts:

| Domain | Sites | `query_transform` | `projection_neutral` |
| --- | ---: | ---: | ---: |
| `node_task_edge_binding` | 64 | 2 | 62 |
| `lease` | 7 | 1 | 6 |
| **Total** | **71** | **3** | **68** |

The approved-core query implementation contains **30** exact physical-storage
sites. The target domains have zero unclassified sites, no stale keys, and no
duplicate keys. Remaining unclassified-domain counts are unchanged:
`test_fixture` 198, `verification_recovery` 150, `planning_session` 16,
`cleanup_callback` 14, `governance_requirements` 11, and `record_file_state`
11.

## Verification

- `uv run pytest tests/unit/test_graph_projection_queries.py -q` — 17 passed.
- `uv run pytest tests/unit/test_graph_projection_queries.py tests/unit/test_graph_projection_inventory.py tests/unit/test_graph_public_exports.py tests/unit/test_graph_projections.py -q` — 243 passed.
- `uv run ruff check .` and `uv run ruff format --check .` — passed.
- `uv run pyright` — 0 errors, 0 warnings.
- `make test` — 4,973 passed, 3 skipped, 3 pre-existing aiosqlite deprecation warnings.

## Review-Finding Follow-up

The disposition classifier now accepts only the committed ledger's exact,
reviewed target-domain site keys. It no longer infers dispositions from source
syntax and no longer contains `_TEST_QUERY_DOMAINS`; an injected matching
lease-shaped site remains unclassified until its exact key is reviewed.

The dispatch `file_state_records` lookup is now explicitly in the
`record_file_state` deferred domain, not the lease domain. The refreshed target
closure is **31** `node_task_edge_binding` sites (all `projection_neutral`) and
**2** lease sites (all `query_transform`): **33** classified target sites with
zero target-domain unclassified sites. Remaining deferred counts are
`test_fixture` 236, `verification_recovery` 150, `planning_session` 16,
`cleanup_callback` 14, `record_file_state` 12, and
`governance_requirements` 11.

Added query behavior coverage for present/missing node creation/runtime fields,
task candidates/state, resource claims, active/absent leases, and
absent edge/binding lookups. Mutation-isolation coverage proves command
definition dictionaries and copied Pydantic models' nested lists remain
independent of projection storage.

Follow-up verification: focused graph suites **245 passed**; Ruff and Pyright
passed; full suite **4,975 passed, 3 skipped** with the same three pre-existing
aiosqlite deprecation warnings.
