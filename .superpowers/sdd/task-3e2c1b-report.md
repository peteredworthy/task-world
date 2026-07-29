# Task 3e2c1b Report

## Status

Complete and staged. Read recipes and the dedicated fixture mutation pipeline
consumed every non-core physical read and all 71 fixture mutation handoffs.

## Implementation

- `compile_query_replacement_plan` consumes the approved composition partition,
  reuses exact stream reanchoring, and substitutes only collector-proven physical
  descendants inside each original outer LibCST expression.
- Frozen strict recipes retain path/span, original and replacement outer
  expressions, consumed IDs, query imports, and structural rule IDs. Direct
  assignment is represented by a frozen fixture-migration handoff instead of a
  fabricated read query.
- The finite registry is keyed by effective old field, physical access kind,
  and physical method shape. Unknown, ambiguous, stale, overlapping, missing,
  duplicate, residual-physical-access, and mixed read/mutation inputs refuse
  closed.
- Exact collection-view queries return independent copies while preserving old
  map/list, nested default, membership, items, values, and ordering behavior.
  New public calls are exported through `orchestrator.graph`.
- Four test-only fixture helpers round-trip checkpoint storage, recursively
  JSON-normalize values, preserve input projections, and fail closed for unknown
  fields, non-mapping paths, non-string keys, and incompatible containers.
- Frozen fixture mutation recipes accept only writable `Name` receivers and the
  finite replace/set/update/append families. Source apply emits rebinding,
  collision-safe imports, validates every update in memory, and writes atomically.

## Machine Structural Evidence

The first wave produced 186 replacement recipes consuming 200 read IDs. The
second residual wave produced two recipes consuming 10 IDs, and the final
generic-correction wave produced four recipes consuming four diagnostic-backed
read IDs. The final scenario wave produced five recipes consuming one occurrence
and four diagnostic-backed read IDs. Through the scenario wave, source apply
totaled 197 recipes consuming 219 IDs.

The final prompts wave produced six recipes consuming seven IDs. Cumulative
source apply: 203 recipes consuming 226 IDs. Unmatched structural families:
none.

The first fixture wave produced 100 recipes consuming 100 IDs across 14 test
files. Cumulative source apply: 303 recipes consuming 326 IDs.

The fixture mutation wave produced 71 recipes consuming 71 IDs across nine test
files: 58 nested assignments, 12 field replacements/updates, and one finite
literal extend. Cumulative source apply: 374 recipes consuming 397 IDs.

The scenario wave was `mapping_snapshot=3`, `scalar_read=2`, importing
`leases_view`, `node_states_view`, `task_states_view`, and `run_state`.
The prompts wave was `mapping_snapshot=6`, `scalar_read=1`.
The fixture wave was `mapping_snapshot=98`, `scalar_read=1`,
`sequence_snapshot=1`.

## Atomic Source Apply

- The pure apply boundary validates all exact outer spans/expressions in memory,
  merges routed imports with LibCST codemod utilities, parses every result, and
  proves replacement closure before producing write data.
- Conflicting query names receive deterministic aliases derived from lexical
  bindings. The atomic writer validates every original before staging temporary
  files and then uses same-directory `os.replace` operations.
- The final source apply generated five groups/recipes over five IDs and changed
  `graph/scenario.py`. Across all waves, ten distinct consumer files changed.
- The prompts source apply generated six groups/recipes over seven IDs and
  changed `graph_runtime/prompts.py`.
- The fixture read source apply generated 100 groups/recipes over 100 IDs and
  changed 14 test files; the mutation apply changed nine files. Neither wave
  persists fixture identities.
- Post-apply inventory has five physical occurrences, 743 diagnostics, and 748
  anchored sites. Pending sites, query transforms, mutation handoffs, and
  mutation recipes are all zero.
- Generated inventory and ledger artifacts represent the final transformed
  tree. Structural counts are 136 approved-core and 618 neutral, including one
  finite outer helper-rebinding diagnostic and zero reviewed fixture deferrals.

## Focused Verification

- Focused inventory/codemod/query/migration/final-review/command tests — 383
  passed.
- Focused outbox recovery behavior tests — 22 passed.
- Final focused collector/codemod/scenario/query behavior tests — 212 passed.
- Final focused collector/codemod/prompts/query behavior tests — 207 passed.
- Fixture-wave collector/codemod/query tests — 200 passed.
- Representative changed unit tests — 191 passed.
- Representative changed integration tests — 41 passed.
- Fixture mutation helper/codemod and mechanically changed unit tests — 471 passed.
- Focused Ruff — passed.
- Focused Pyright — 0 errors, 0 warnings.
- The final migration gate passed 6 contracts and exposed only five stale
  machine snapshots after the last producer-origin expansion; those five
  corrected contracts then passed together in 113.03s. All 11 migration
  contracts therefore have passing evidence on the final staged code.
- After the final typed-context provenance wave, the complete migration gate
  passed: 11 passed in 246.08s.
- After fixture mutation review corrections, the complete gate passed six
  contracts and the five corrected generated-snapshot contracts passed together
  in 129.06s. All 11 final migration contracts have passing evidence.
- Full pytest remains delegated to the commit hook so it runs once.
