# Slice 1 / Slice 5 progress ledger

Durable state for the `mind-the-gap` loop implementing
`slice-1-and-5-target-2026-08-27.md`. Updated after every validated chunk.
Baseline at loop start: main `2553748e3`, full suite 5454 passed / 5 skipped
/ 75s.

## Slice 1 — worker contracts and prompt hydration

Status: chunk 1 of 6 verified. Chunks 2-6 not started.

### Verified chunks

- **Chunk 1 — Typed worker-contract fields on the node payload.** Builder
  implemented; independent Validator confirmed exactly the 4 specified files
  changed (`src/orchestrator/graph/models.py`,
  `src/orchestrator/graph/payload_registry.py`,
  `tests/unit/test_node_created_event_payloads.py`,
  `tests/unit/test_graph_payload_field_allowlists.py`), all 6 fields present
  with correct types/defaults, `work_mode` untouched, `payload_registry.py`
  change isolated to `projection=`, new tests assert the right things
  (round-trip, dispatch propagation via `node_payload_view`, negative type
  case, projection-retention membership), full suite **5458 passed, 5
  skipped** (baseline 5454 + 4 new tests, zero regressions, zero existing
  tests modified), ruff/format/pyright clean, `PROJECTION_SCHEMA_VERSION`
  unchanged. To be committed as a standalone commit on
  `slice-1-worker-contracts`.

### Verified facts from planning pass 1 (2026-08-27)

Established by reading merged main `2553748e3`; a Builder may rely on these
without re-deriving them.

1. **`NodeCreatedPayload` (`src/orchestrator/graph/models.py:1586`) is
   `extra="forbid"`** (via `StrictEventPayload`, `models.py:778`). Verified by
   execution: `NodeCreatedPayload.model_validate({"node_id": "w1", "kind":
   "worker", "objective": "do x"})` raises
   `objective  Extra inputs are not permitted [type=extra_forbidden]`.
   *Consequence:* today a planner physically cannot put an `objective` on a
   node. This is the root mechanism behind the dogfood finding "worker packets
   with no bounded objective" — not a prompt bug.
2. **`graph_runtime/prompts.py:347-372` reads nine node keys that no writer
   ever sets and the payload model would reject**: `objective`,
   `corrective_requirement`, `corrective_evidence_required`, `expected_gap`,
   `expected_artifact`, `feature_spec_path`, `acceptance_command`,
   `expected_outputs`, `invariants`. Repo-wide grep: `objective` appears in
   `src/` only at `prompts.py:347` and `prompts.py:352`. These are dead
   branches, not working features.
3. **Field-flow path for any new `NodeCreatedPayload` field is already wired
   end to end** — no plumbing needed beyond declaring the field:
   `NodeCreatedPayload` → `projections.py:791`
   `dispatch_payload = payload.model_dump(mode="json", exclude_none=True)`
   (inherits `exclude_unset=True` from the model's `model_dump` override, so
   unset fields stay absent) → `NodeSpecProjection.dispatch_payload` →
   `projection_queries.py:282 node_payload_view` → `dispatch.py:2166
   _node_payload` → `GraphDispatchContext.node_payload` → `prompts.py`.
4. **`payload_registry.py:272` `projection` retention is load-bearing, not
   cosmetic.** `graph_runtime/store.py:6347 _projection_event` filters appended
   event payloads to `EVENT_PAYLOAD_SPECS[type].projection` before reducing, and
   `store.py:4245` selects only those columns when rebuilding from SQLite. A
   field present on the model but absent from the `projection` set produces a
   `dispatch_payload` that differs between the live-append path and the rebuild
   path — the exact checkpoint-divergence class called out in the docstring at
   `store.py:6347`. Retention sets are derived automatically into
   `GRAPH_PROJECTION_PAYLOAD_FIELDS` etc. (`payload_registry.py:437-447`), so
   only the `_spec("node_created", ...)` strings need editing.
5. **`work_mode` is already taken and means something else.**
   `NodeCreatedPayload.work_mode: str | None` (`models.py:1676`) currently
   carries `"implementation" | "oversight"`, written by
   `graph/compiler.py:533` from `TaskConfig.work_mode`
   (`config/models.py:237`) and read by `graph_runtime/dispatch.py:1160`
   → `_work_mode()` (`dispatch.py:3006`) → `ExecutionContext.work_mode`
   (`runners/types.py:104`), which drives oversight-vs-implementation prompt
   selection in `runners/agents/codex/common.py:1133`,
   `openhands/common.py:362`, `claude_cli/agent.py:239` and the `mode_tag` in
   `runners/execution/phase_handler.py`. The target doc's
   `work_mode: Literal["read_only","write"]` is a **different concept on the
   same key**, and historical journals already contain
   `work_mode: "implementation"` on every compiler-seeded worker. Retyping the
   key in place would break replay of existing runs. Resolving this is its own
   chunk (chunk 2) — deliberately excluded from chunk 1.
6. **Three sites hardcode repo-wide write authority for every `kind="worker"`
   node, regardless of `role`** (this, not the field label, is criterion 3's
   real enforcement point):
   - `graph/_commands.py:5433 _ensure_default_node_authority` — every
     patch-created worker without explicit claims gets
     `[{"mode": "write", "scope": "repo", "paths": ["."]}]`.
   - `graph/macros.py:457 _worker_node` — every macro-created worker gets the
     same literal claim.
   - `graph/compiler.py:544-551` — compiler-seeded workers get
     `{"mode": "write", "scope": "repo", "paths": _worker_write_paths(task)}`.
   `"discovery"` is an existing declared worker role
   (`graph/contracts.py:810`: `builder, discovery, implementer, fixer,
   reviewer, summarizer`), so a discovery node gets repo write by default at
   all three sites.
7. **Resource claims are not a filesystem sandbox today.** They are consumed by
   (a) scheduler mutual exclusion (`graph/scheduler.py:170-227`), (b) patch
   validation against escalation (`patch_validator.py:826
   _resource_claim_escalation_reason`, `MODE_RANK`), and (c) an advisory
   `worker_authority` prompt packet (`prompts.py:_worker_authority_packet`).
   The runner sandbox mode is a **global runner config**
   (`runners/agents/codex/agent.py:615-636`, `restrictions` →
   `workspace-write` / `danger-full-access`), never per-node. So criterion 3
   cannot be satisfied by claims alone; the durable enforcement surface is the
   file-state boundary (`capture_file_state_boundary`,
   `runner_boundary_mismatch`) — a read-only node's accepted boundary must be
   empty. Chunk 4 owns this decision.
8. **Patch validation entry points** for criterion 2:
   `patch_validator.py:166 validate_patch` → `create_node` branch calls
   `contracts.py:101 validate_node_payload(typed_node)` with the **raw op
   dict**, then applies extra checks (`_validate_gap_planner_node`,
   `executable node requires role`, `_validate_check_command`).
   `EXECUTABLE_NODE_KINDS = {"worker", "verifier", "check", "planner"}`
   (`patch_validator.py:62`). Because the validator sees the raw dict, presence
   checks are decoupled from the model's optionality — chunk 1 can add purely
   optional fields and chunk 3 can still demand explicit presence.
9. **Compiler-seeded nodes bypass `validate_patch`.** `seed_compiled_events`
   (`_commands.py:735-790`) only runs `NodeCreatedPayload.model_validate`.
   Criterion-2 enforcement therefore lands only on planner/agent-proposed
   patches, which limits chunk 3's blast radius but does **not** exempt the
   compiler from populating the fields later.
10. **Error-message convention set by `ce9e43c7c`** (read the diff before
    chunk 3): pydantic-shaped failures go through
    `graph/_error_rendering.py` — `safe_validation_diagnostics(exc)` returns
    `{"error_count", "errors": [{"path", "code", "message"}], "omitted_error_count"}`
    with static per-`type` messages and value-free paths, attached as
    `rejected_payload["diagnostics"]`; `safe_exception_reason` renders
    `"{message} [{code}]: payload [{code}] at {path}: {message}; ..."`.
    Hand-written (non-pydantic) validator rejections keep the pre-existing
    `patch_validator` style: a lowercase phrase plus the offending id, e.g.
    `f"executable node requires role: {kind}"`,
    `f"gap planner cannot retire executable node: {node_id}"`,
    `f"check node requires command_definition, hidden_oracle_command, or command_binding: {node_id}"`.
    Chunk 3 must follow the **hand-written** style (one field per message,
    naming the node), not invent a new convention.

### Chunk queue

| # | Name | One-line description |
|---|------|----------------------|
| 1 | Typed worker-contract fields on the node payload | Declare `objective`/`scope`/`bound_requirement_ids`/`acceptance`/`invariants`/`prohibited_actions` on `NodeCreatedPayload` + projection retention, all optional, zero enforcement. |
| 2 | `work_mode` collision resolution | Free the `work_mode` key for `Literal["read_only","write"]` by moving the legacy `implementation`/`oversight` node-payload key to its own name, with backward-compatible replay of existing journals. |
| 3 | Patch-validator contract enforcement (criterion 2) | Reject `create_node` of executable worker nodes missing `objective`/`work_mode`/`acceptance` with one precise per-field message naming the node. |
| 4 | Discovery nodes read-only by default (criterion 3) | Derive default authority from role/`work_mode` at the three claim-granting sites; require an explicit separately-flagged override for `role="discovery"` + `work_mode="write"`; decide and wire the boundary-level enforcement. |
| 5 | Worker prompt hydration from typed fields (criterion 4) | Replace the dead loose-dict reads at `prompts.py:347-372` with a distinct typed work-contract section in the worker packet and prompt summary; add the fields to `node_detail` retention. |
| 6 | Regression coverage (criterion 5) | Contract-doc scenarios #1 (read-only discovery cannot obtain write authority) and #4 (worker prompts contain bound requirement/objective). Scenario #3 is stretch — defer with a recorded reason if chunk 6 grows past one sitting. |

Ordering rationale: chunk 1 is the only one with no prerequisite, and chunks
3-6 all read the fields it declares. Chunk 2 is separated from chunk 1 because
it is a *migration* with replay-compatibility risk (fact 5), whereas chunk 1 is
purely additive; bundling them would make a failed validation ambiguous about
which half broke.

### Chunk 1 — Typed worker-contract fields on the node payload (VERIFIED)

**Goal.** Make it *possible* to express a bounded worker contract on a node.
No validator enforcement, no prompt changes, no authority changes, no
`work_mode` changes. Independently verifiable: after this chunk a `create_node`
patch carrying the new fields is accepted, the fields survive both live append
and checkpoint rebuild, and they are visible in `node_payload_view`.

**Why this split and not "fields + enforcement together".** Enforcement
(criterion 2) requires deciding *which* node kinds/roles are in scope, and
`EXECUTABLE_NODE_KINDS` includes `verifier`, `check`, and `planner`, for which
`acceptance` is meaningless. It also requires the `work_mode` migration (fact
5) to have landed, since `work_mode` is one of the three enforced fields. Both
of those are judgement-heavy; the field declaration is not. Splitting keeps the
risky decisions out of a chunk whose correctness is a mechanical
serialize/replay property.

#### Files touched (exactly these)

1. `src/orchestrator/graph/models.py`
2. `src/orchestrator/graph/payload_registry.py`
3. `tests/unit/test_node_created_event_payloads.py`
4. `tests/unit/test_graph_payload_field_allowlists.py`

Six fields added to `NodeCreatedPayload`, all `None`-defaulted:
`acceptance: list[str] | None`, `bound_requirement_ids: list[str] | None`,
`invariants: list[str] | None`, `objective: str | None`,
`prohibited_actions: list[str] | None`, `scope: str | None`. All six added to
the `node_created` spec's `projection=` retention string only (not `light`,
`summary`, or `node_detail` — chunk 5 adds `node_detail` when the prompt
surface needs them).

#### Do not touch in later chunks' prerequisite reasoning

- `work_mode` anywhere (chunk 2).
- `graph/patch_validator.py`, `graph/contracts.py` (chunk 3).
- `_ensure_default_node_authority`, `macros.py`, `compiler.py` (chunk 4).
- `graph_runtime/prompts.py` (chunk 5).
- `NodeCreationProjection` / `NodeSpecProjection` in `models.py` — the free-form
  `dispatch_payload` already carries the new fields; adding typed columns there
  is unnecessary and would touch checkpoint shape.

### Open risks carried into later chunks

- **R1 (chunk 2, high).** Retyping or renaming `work_mode` interacts with
  already-persisted journals (`.orchestrator/state/history.jsonl` is
  git-tracked) and with `tests/unit/test_fixture_corpus.py` JSON fixtures.
  Chunk 2 must state its back-compat strategy before implementing.
- **R2 (chunk 3, medium).** `EXECUTABLE_NODE_KINDS` is broader than the doc's
  "executable node" (it includes `check` and `planner`). Chunk 3 must pick an
  explicit narrower predicate — most likely `kind == "worker"` — and record it.
- **R3 (chunk 4, medium).** There is no per-node filesystem sandbox (fact 7),
  so "read-only" can only be enforced at the file-state boundary or by refusing
  to grant the write claim. Chunk 4 must choose one and justify it; a
  field-label-only change would not satisfy criterion 3.
- **R4 (chunk 5, low).** `prompts.py:347-372` also reads six other dead keys
  (`corrective_requirement`, `expected_gap`, `expected_artifact`,
  `feature_spec_path`, `acceptance_command`, `expected_outputs`). Chunk 5
  should either declare or delete them rather than leaving dead branches.

## Slice 5 — recovery semantics

Status: not started.

### Chunks

(populated by Planner/Gap-Finder)

## Process incident log

- **2026-08-27, after chunk 1 build/validate.** This ledger file's
  Planner-pass-1 content (verified facts, chunk queue, chunk 1 detail, risks)
  was found reverted to the empty scaffold on disk after the chunk-1 Builder
  and Validator agents ran in the same working tree — despite neither being
  instructed to touch this file, and despite `git status` showing it as
  *not* modified (i.e. some process ran an actual git revert of it, not just
  an overwrite). Recovered verbatim from the orchestrator's own conversation
  context (the content had already been read back in full across two prior
  tool calls) with no data loss, but this is a real process gap: a Builder
  told to "confirm nothing outside your N files changed" may interpret that
  as license to revert other dirty files rather than just report them.
  Going forward, Builder/Validator prompts must explicitly say "do not run
  any git command that discards or reverts changes in this working tree,
  including on files outside your scope" and the orchestrator should commit
  ledger updates immediately after writing them, before dispatching the next
  sub-agent, rather than leaving them uncommitted across a chunk's
  build/validate cycle.
