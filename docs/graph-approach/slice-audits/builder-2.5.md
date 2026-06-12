# Slice 2.5 — LLM gatekeeper (BUILDER)

You are the BUILDER agent for slice 2.5 of the task-world execution-graph kernel (Phase 2, size S — keep it tight).

## Ground truth (read first, in order)

1. `docs/graph-approach/execution-graph-evaluation.md` §6.3 — the governing design: deterministic classifier first; gatekeeper consulted ONLY on misses; calls capped per boundary check; verdict recorded as an accepted classification event (replay reads the recorded decision, NEVER re-asks the model); gatekeeper sees path/size/entropy/shape METADATA only — never raw content; accepted classifications feed the pattern library so the deterministic hit rate rises and gatekeeper traffic decays. §6.5 — cost records per execution as graph-model requirement.
2. `docs/graph-approach/execution-graph-prd-plus.md` — §20.3 taxonomy (gatekeeper classifies INTO it: tool_cache, build_output, test_artifact, secret, external_artifact, unknown_ignored), §14 (projection reducers deterministic — no model calls in reducers), §27.5 (no real LLM in tests)
3. The slice definition (sequencing deck): "2.5 LLM gatekeeper — Small-model classification of unmatched residue; verdict recorded as event (replay never re-asks); metadata-only for secret-suspects; verdicts seed pattern library. Done when: Gatekeeper hit-rate and pattern-library growth visible in cost reports."
4. Slice 2.4 implementation: `src/orchestrator/graph/file_state.py` (classifier, FileStatePolicy, needs_gatekeeper flags), `src/orchestrator/graph_runtime/file_state.py` (boundary), `src/orchestrator/graph_runtime/dispatch.py` (where the boundary runs), `project_residue_report` in projections.
5. Cost context: legacy `cost_records` table (src/orchestrator/db/orm/models.py CostRecordModel) is FK-bound to legacy runs/tasks — graph runs should NOT write it. Carry gatekeeper cost facts as graph EVENTS (per evaluation §6.5) and report via projection.

## Scope — what to build

### 1. Gatekeeper protocol + deterministic-first flow (graph_runtime)

`src/orchestrator/graph_runtime/gatekeeper.py`:

- `ResidueClassifier` Protocol: `classify(items: list[ResidueMetadata]) -> list[GatekeeperVerdict]` where `ResidueMetadata` carries path, size_bytes, entropy (when present), source kind, matched-nothing context — NEVER file content. One batched call per boundary, capped: at most `max_items_per_boundary` (configurable, default ~20) items consulted; beyond the cap items stay `unknown_*` with needs_gatekeeper still true (next boundary can retry).
- Production adapter: a thin implementation that calls a small model (use the project's existing Claude SDK adapter conventions — check `src/orchestrator/runners/agents/claude_sdk/` for how API access is done; model configurable, default a small/cheap model id). Keep it import-isolated so tests never load it. If wiring a real API client cleanly exceeds this slice's S size, ship the Protocol + a documented stub adapter raising NotImplementedError with the wiring TODO recorded in the module docstring — the contract and event flow are the slice's substance; flag this choice in your summary.
- Flow wiring: after the 2.4 boundary produces a file_state record with needs_gatekeeper residue, the dispatch flow consults the classifier (when one is injected; absent classifier → skip, residue stays flagged) and submits the verdicts through the controller as a command.

### 2. Pure kernel: verdict events + pattern library projection

- New command `record_gatekeeper_verdicts` in `apply_command`: payload carries the file_state record id + verdict list (path, classification from the §20.3 taxonomy, confidence, rationale string, model id, token/cost metadata). Validation: referenced file_state record must exist in the projection with matching unresolved needs_gatekeeper paths; verdict classifications must be valid taxonomy values; reject otherwise. Accepted → `gatekeeper_verdict_recorded` events (one per path or one batch event — pick and document) + a `gatekeeper_cost_recorded` event carrying model/tokens/wall-time per consult.
- Pattern library = pure projection `project_pattern_library(events)`: aggregates accepted verdicts into patterns (derive a glob per verdict — e.g. dirname/*.ext — document the derivation; identical patterns merge with occurrence counts). `FileStatePolicy` construction in the boundary flow consumes the projection so the NEXT boundary's deterministic classifier hits what the gatekeeper already decided (same-path AND derived-pattern matches classify deterministically with matched_rule="pattern_library:<pattern>").
- Replay determinism: rebuilding projections from events involves zero classifier calls. The verdict events are the only source.

### 3. Hit-rate + growth visibility (the done-when)

Pure projection `project_gatekeeper_report(events)`: per run — deterministic classifications count, gatekeeper consults count, gatekeeper-resolved count, hit rate (deterministic / total classified), pattern-library size over time (per boundary), token/cost totals from gatekeeper_cost_recorded events. This is the "visible in cost reports" artifact: also expose it from the residue/cost reporting path (a function the future API/UI slice can call; no API endpoint in this slice).

### 4. Tests

`tests/unit/test_graph_gatekeeper.py` (pure):
- record_gatekeeper_verdicts accept path: events emitted, projection shows resolved classifications, needs_gatekeeper cleared for verdict paths.
- Rejections: unknown record id, path not in the record's residue, invalid taxonomy value, duplicate verdict for already-resolved path (replay safety).
- project_pattern_library: derivation, merging, counts.
- project_gatekeeper_report: hit-rate math over a synthetic event sequence, growth across two boundaries.

`tests/integration/test_graph_gatekeeper_flow.py` (real git tmp repo + tmp SQLite, deterministic fake classifier class — a hand-written ResidueClassifier implementation, NO unittest.mock):
- Boundary with unmatched residue → fake classifier consulted with METADATA ONLY (assert the fake received no content fields), verdicts recorded through controller, events in store.
- Second boundary in the same run with the same residue pattern → deterministic classifier hits via pattern library, classifier NOT consulted again (fake's call count unchanged), hit rate rises in the report.
- Cap respected: more residue items than max_items_per_boundary → consulted batch ≤ cap, remainder still flagged.
- Replay: rebuild projection from stored events with NO classifier available → identical classifications.
- Secret-suspects: never sent to the classifier (they were hard-rejected in 2.4 — assert the fake never sees a secret-classified path even when present alongside residue).

## Done when

1. Gatekeeper verdicts recorded as events; replay never consults the classifier (test proves rebuilding with no classifier yields identical state).
2. Pattern library grows from verdicts and the deterministic classifier consumes it (second-boundary test: no repeat consult).
3. Hit-rate + pattern growth + token/cost visible via project_gatekeeper_report (the cost-report artifact).
4. Metadata-only contract enforced and tested; cap enforced and tested; secret-suspects never reach the classifier.
5. Kernel purity (no IO/model imports in src/orchestrator/graph/), kernel suite <5s; graph_runtime imports no FastAPI.
6. Fresh green: `uv run pytest tests/unit -q`, `uv run pytest tests/integration -q`, `uv run ruff check src tests`, `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`.

## Hard constraints

- NO unittest.mock / monkeypatching; NO real LLM calls in any test. Hand-written fake classifier classes via constructor injection.
- Real git tmp repos + tmp SQLite only; never main orchestrator.db / main repo git state; no server.
- Touch ONLY: `src/orchestrator/graph/` (commands.py, projections.py, models.py, file_state.py, __init__.py — minimal), `src/orchestrator/graph_runtime/` (gatekeeper.py new, file_state.py, dispatch.py, __init__.py), `tests/unit/test_graph_gatekeeper.py` (new), `tests/integration/test_graph_gatekeeper_flow.py` (new), existing graph test files only if a shared helper needs extension, `tests/fixtures/graph/**` + COVERAGE.md if fixtures added. Nothing else.

When done: summary (verdict-event shape, pattern derivation rule, cap mechanics, production-adapter status), fresh test output.
