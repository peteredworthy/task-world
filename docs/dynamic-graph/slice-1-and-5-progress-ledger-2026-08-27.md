# Slice 1 / Slice 5 progress ledger

Durable state for the `mind-the-gap` loop implementing
`slice-1-and-5-target-2026-08-27.md`. Updated after every validated chunk.
Baseline at loop start: main `2553748e3`, full suite 5454 passed / 5 skipped
/ 75s.

## Slice 1 — worker contracts and prompt hydration

Status: chunks 1-5 of 6 verified and committed (`3ac034a7b`, `8565c24f9`,
`4ee76eda8`, `9ca1f26c1`, `e0177275f`). Chunk 6 SPECIFIED (planning pass 6,
2026-08-27), not built — see the chunk 6 section and the Slice 1 completion
summary at the end of this Slice 1 area.

- **Chunk 5 — Worker prompt hydration from typed fields.** New
  `_worker_contract_packet()` renders `objective`/`access_mode`/`acceptance`
  (always present, null when unset on exempt compiler-seeded workers) plus
  `scope`/`bound_requirement_ids`/`invariants`/`prohibited_actions`/resolved
  `bound_requirements` (omitted when absent) as a `work_contract:` line,
  gated to `node_kind == "worker"` only. Deleted 7 dead node-payload-key
  reads with no home; the LIVE `dynamic_feature`-sourced rendering of
  `acceptance_command`/`feature_spec_path` (a different dict, unrelated)
  confirmed intact. Independent Validator re-verified by direct execution
  (not just tests): built a real worker payload, called the prompt function,
  confirmed the exact rendered `work_contract` JSON and confirmed all 7
  retired key names are absent from the string. Confirmed the one permitted
  existing-test deletion only removed coverage for the 7 dead keys, with
  adjacent live-path test blocks byte-identical. `node_detail`/operator
  read-model wiring deferred (R8), as specified. Full suite **5511 passed, 5
  skipped** (5504 + 7 new tests, zero regressions), ruff/format/pyright
  clean.

### Verified chunks (chunk 4)

- **Chunk 4 — Discovery read-only enforcement with real claim derivation.**
  Build attempt 1 failed independent validation (see incident record below,
  kept for audit trail). Fix retry 1: changed the grant-site gate from "is
  `resource_claims` falsy" to "does it contain any *ranked* claim (mode in
  `MODE_RANK`)", appending rather than replacing, so an `external`-only claim
  no longer defeats the mandatory `read` grant. Independent Validator (fresh
  agent, retry) reproduced the original bug's absence by direct execution
  (not just the new test), then adversarially tried 4 more angles (multiple
  external claims, unrecognized claim mode, write-access-mode claim-free
  first-grant, the `_commands.py`→`patch_validator.py` import direction) —
  found no new bypass, confirmed the claim-free first-write-grant case is
  pre-existing unrelated behavior correctly left alone, confirmed
  `macros.py` was never actually vulnerable (no incoming claims to gate on),
  re-ran the full original chunk-4 battery and confirmed it still holds.
  Full suite **5504 passed, 5 skipped** (5481 + 23 new test IDs, zero
  regressions), schema version 15 unchanged, ruff/format/pyright clean.

### Chunk 4 — build attempt 1: FAILED validation (2026-08-27) [historical]

Independent Validator found a genuine escalation-refusal bypass, not a style
nitpick — do not treat this as resolved until a fresh build+validate cycle
passes.

**Bug.** `_ensure_default_node_authority` (`graph/_commands.py`) and
`macros.py`'s `_worker_node` both gate the mandatory `read_only` → `read`
claim injection on `resource_claims` being *falsy* (missing or `[]`). Chunk 4
also added an `"external"` claim-mode carve-out (validator check 9: an
`external` resource claim is not repo write authority, so it's allowed on a
`read_only` worker). Combining the two: a `create_node` op for a
`role="discovery"`, `access_mode="read_only"` worker whose `authority.resource_claims`
is `[{"mode": "external", ...}]` — non-empty, so the falsy check skips
granting a `read` claim — is accepted with **no ranked claim at all**. The
pre-existing (unmodified) escalation guard `_existing_resource_claim_rank`
returns `None` for a node with no ranked claim, and
`_resource_claim_escalation_reason` treats `None` as "no ceiling." A
follow-up `set_resource_claims` op granting full `{"mode": "write", "scope":
"repo", "paths": ["."]}}` on that node is therefore **accepted**, verified by
direct execution against `apply_command` and confirmed live in the replayed
projection. This is not contrived: a discovery worker legitimately declaring
an `external` web-search claim alongside `access_mode: "read_only"` is
ordinary usage, and the chunk's own new tests exercise `authority`-bearing
`create_node` ops as a first-class path — they just never paired the
`external`-only case with a follow-up escalation attempt.

**Required fix (Validator's recommendation, adopted).** Fix the actual
defect at the grant sites, not the general escalation logic: change
`_ensure_default_node_authority`'s and `_worker_node`'s `read_only` branch
condition from "is `resource_claims` falsy" to "does `resource_claims`
contain any claim whose mode is in `MODE_RANK`" (i.e. any *ranked* claim,
`read` or `write`) — if not, append (not replace) a `read` claim, regardless
of whether an `external`-only list is already present. **Do NOT** fix this by
changing `_existing_resource_claim_rank` to treat rank-`None` as rank `0`
globally — that function is the shared escalation-refusal path for every
node in the system, not just chunk-4 discovery nodes, and a claim-free node
receiving its very first (often `write`) claim via
`_ensure_default_node_authority` is the completely ordinary case for every
non-discovery worker (`test_patch_accept_adds_default_worker_write_authority`
pins exactly this). Treating "no ranked claim yet" as rank 0 globally would
make that ordinary first-write-grant look like a 0→1 escalation and reject
it — breaking the whole system, not fixing the hole.

**New required test.** A discovery `read_only` worker admitted with only an
`external` resource claim, followed by a `set_resource_claims` op requesting
`write`, must be rejected by the pre-existing escalation-refusal message —
this is the exact reproduction the Validator used and must become a
permanent regression pin.

### Verified chunks

- **Chunk 3 — Patch-validator contract enforcement.** Builder implemented
  the mandatory-field check (`kind == "worker"`, role-independent, first
  triggered on `objective` → `access_mode` → `acceptance` in order) plus
  threaded the three fields through macros, horizon templates, the prompt
  example patch, codex macro schemas, and MCP tool signatures so the
  planner's own graph tools aren't a bypass. Independent Validator did a
  dedicated anti-weakening audit of all 8 repaired test files and found zero
  instances of the check being loosened, skipped, or opted-out to make a
  fixture pass — every repair was a genuine "add the missing fields to the
  worker node dict" fix. Confirmed: predicate does not reference
  `EXECUTABLE_NODE_KINDS`; error messages match the spec verbatim;
  `test_seed_compiled_events_...` (compiler-seeding exemption) byte-identical;
  new `test_create_revision_attempt_worker_node_is_not_contract_checked`
  genuinely pins the R5 out-of-scope boundary rather than closing it; new
  `test_worker_contract_is_not_required_of_non_worker_kinds` exercises real
  `verifier`/`check`/`planner` nodes. Full suite **5481 passed, 5 skipped**
  (5466 + 15 new test IDs, 27 pre-existing failures repaired, zero other
  regressions), schema version 15 unchanged, `models.py`/`contracts.py`/
  `compiler.py`/`_commands.py`/`payload_registry.py` untouched as required,
  ruff/format/pyright clean.

- **Chunk 2 — `access_mode` field (work_mode collision resolution).**
  Builder added `access_mode: Literal["read_only","write"] | None` as a new,
  fully independent field; `work_mode` untouched. Independent Validator
  confirmed exactly the 5 expected files changed, field types/placement
  correct, `projection=` retention isolated to `access_mode` only, tests
  assert real independence (legacy `work_mode`-only replay still works,
  `access_mode` rejects legacy literal values, no cross-wiring into
  `ExecutionContext.work_mode`), zero scope creep (`access_mode` not
  referenced anywhere in `runners/` or `dispatch.py` yet — that's chunk 4),
  full suite **5466 passed, 5 skipped** (5458 + 8 new test IDs from 5
  logical tests, one parametrized ×3; zero regressions), schema version 15
  unchanged, ruff/format/pyright clean.

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

### Verified facts from planning pass 2 (2026-08-27, chunk 2 research)

11. **The node-payload `work_mode` key has exactly one writer and one reader,
    and is a different namespace from `TaskConfig.work_mode` /
    `ExecutionContext.work_mode`.** Repo-wide grep for `work_mode` in `src/`
    returns 20 hits, which partition cleanly:
    - *Node payload key* (the graph event surface): declared
      `models.py:1682 work_mode: str | None`, retained
      `payload_registry.py:272` (`projection=` **only** — absent from `light`,
      `summary`, and `node_detail`), written **only** at `compiler.py:533`
      (`"work_mode": task.work_mode`), read **only** at `dispatch.py:1160`
      (`work_mode=_work_mode(node.get("work_mode"))`). Nothing else in `src/`,
      `ui/src`, or `tests/` reads the node key. `graph_runtime/prompts.py` does
      **not** read it.
    - *Config/runner namespace* (untouched by any Slice 1 chunk):
      `config/models.py:237 TaskConfig.work_mode`,
      `runners/types.py:104 ExecutionContext.work_mode`,
      `runners/executor.py:1106,1610`, `workflow/agent/prompts.py:107,260`,
      `runners/execution/phase_handler.py:304,455,543` (`mode_tag`), and the
      three prompt-selection consumers `runners/agents/codex/common.py:1133,
      1143,1154`, `runners/agents/openhands/common.py:362,372,383,389`,
      `runners/agents/claude_cli/agent.py:239,290,420`. All of these compare
      against the literal `"oversight"`; `_work_mode()`
      (`dispatch.py:3006`) coerces anything that is not exactly `"oversight"`
      to `"implementation"`, so the node key is a *lossy string* today, not a
      validated enum.
12. **Historical `node_created` payloads are re-validated through the strict
    model on every replay.** `projections.py:906` (`_reduce_slice_a`) calls
    `NodeCreatedPayload.model_validate(event.payload)` for every `node_created`
    event before `merge_node_created`. Combined with fact 1 (`extra="forbid"`),
    this means **deleting or renaming the `work_mode` field on the model would
    make every historical event fail replay with `extra_forbidden`**, and
    **retyping it to `Literal["read_only","write"]` would make every historical
    event fail with `literal_error`**. Verified by execution:
    `NodeCreatedPayload.model_validate({"node_id":"w1","kind":"worker",
    "state":"planned","work_mode":"implementation"})` succeeds today.
13. **`_projection_event` filters raw dicts by field name *before* validation**
    (`store.py:6347`), so any pydantic-level compatibility shim (e.g. a
    `mode="before"` validator translating a legacy key) only ever runs if the
    legacy key is still in the `projection` retention set. A rename strategy
    therefore cannot actually retire the old key from the registry — it must
    keep both forever.
14. **Migration blast radius for a rename is small in *tests* and non-zero in
    *live data*.** `grep -rl work_mode tests/fixtures/` returns **nothing** —
    no graph YAML fixture, and `tests/unit/test_fixture_corpus.py` never
    mentions the key; the only test hits are `tests/unit/test_cli_agent.py`
    and `tests/unit/test_prompt_generation.py`, both of which exercise
    `ExecutionContext`/`TaskConfig`, not the node payload. But the git-tracked
    `.orchestrator/state/history.jsonl` (43 646 lines) contains **15
    `node_created` events carrying `work_mode`** (13 `"implementation"`,
    plus `"oversight"` values), and 2 `run_created` events carry the routine's
    own `TaskConfig.work_mode`. So the fixture corpus would stay green under a
    rename while real replay silently changed shape — the untested-risk case.
15. **`PROJECTION_CHECKPOINT_SCHEMA_VERSION` is 15**
    (`graph/projection_codec.py:40`); `store.py:5091` discards a checkpoint
    whose stored version is not current and rebuilds from events. A rename
    that changes the `dispatch_payload` shape of historical nodes would
    therefore need a schema bump to avoid stored-checkpoint vs
    rebuilt-projection divergence for in-flight runs — a cost the additive
    strategy avoids entirely.
16. **`access_mode` is an unused name.** `grep -rn access_mode src/ tests/
    ui/src` returns zero hits. The adjacent claim vocabulary already uses
    `read` / `write` / `graph_write` / `review_write`
    (`patch_validator.py:61-62 MODE_RANK`, `RESOURCE_CLAIM_MODES`), so the
    node-level declaration deliberately uses the contract doc's `read_only`
    spelling to stay visibly distinct from a claim's `mode`.
17. **The contract doc does not mandate the literal field name.**
    `reliable-plan-execution-contract.md:135` lists ``work_mode``:
    `read_only` or `write`;` as one bullet in a prose list of *concepts* a
    worker contract must carry, alongside `required_inputs` and
    `expected_outputs` which the target doc already drops from criterion 1.
    The semantic is normative; the spelling is not.

### Verified facts from planning pass 3 (2026-08-27, chunk 3 research)

18. **There is no update/patch op that can strip a node's contract fields.**
    `KNOWN_OPS` (`patch_validator.py:42`) is exactly `create_node`,
    `create_edge`, `retire_node`, `create_revision_attempt`, `create_appeal`,
    `create_gate`, `set_resource_claims`, `set_allowed_actions`,
    `mark_plan_region_suspect`. Nothing mutates a node payload after creation:
    `set_resource_claims`/`set_allowed_actions` touch authority only, and
    `retire_node`/`mark_plan_region_suspect` touch state. Criterion 2's phrase
    "`create_node`/`patch` operations" therefore collapses to `create_node`
    alone — the conservative scope is also the complete one, and chunk 3 does
    **not** need a "later op could strip the field" guard.
19. **Macro expansion happens *before* patch validation, in the same command.**
    `_commands.py:2339 expand_patch_macros(...)` runs at the top of the submit
    path; `_commands.py:2380 validate_patch(...)` runs on the expanded op list.
    So macro-produced ops are subject to every `validate_patch` check.
    `macros.py:457 _worker_node` emits a `create_node` worker with **no**
    `objective`/`access_mode`/`acceptance`, and `CreateWorkRegionArgs`
    (`macros.py:30`) is `extra="forbid"` with no such args — meaning a planner
    calling the `create_work_region` / `create_corrective_region` macro today
    physically **cannot** supply them. Enforcement in `validate_patch` without
    macro plumbing would brick the planner's primary graph tool, so the macro
    arg surface is part of chunk 3, not a follow-up.
20. **Three further agent-facing surfaces gate the macro args.** The chain is
    `codex tool schema → graph_tool_routing → macros.py`:
    `runners/agents/codex/common.py:565` (`create_work_region`) and `:643`
    (`create_corrective_region`) declare `inputSchema` with
    `additionalProperties: False`; `graph_runtime/graph_mcp_tools.py:105` /
    `:136` declare typed Python signatures per macro arg;
    `runners/graph_tool_routing.py:168 normalize_macro_tool_payload` is a
    generic pass-through (`{k: v for k, v in args.items() if k not in
    {patch_id, base_graph_position, rationale_record_id}}`) and needs **no**
    change. So exactly two agent-facing files gate new macro args.
21. **Two planner-facing *exemplars* teach the wrong shape.**
    `graph_runtime/horizon_templates.py:44,67,171` (discovery /
    implementation / corrective-work region templates) and
    `graph_runtime/prompts.py:963` (the inline worker+verifier example patch)
    both emit `create_node` worker nodes with none of the three fields. These
    are handed to planners as copyable templates, so leaving them stale after
    enforcement lands would make the validator reject patches the prompt told
    the planner to write.
22. **`create_revision_attempt` worker nodes bypass node-payload validation
    entirely.** Only the `create_node` branch of `validate_patch` calls
    `validate_node_payload`; `create_revision_attempt`'s `worker_node` /
    `verifier_node` keys are only seen by `_validate_typed_topology`
    (`patch_validator.py:244-261`) for duplicate-id registration. Confirmed by
    the probe in fact 23: `tests/unit/test_cache_authority_chain.py:521`
    (`"worker_node": {"node_id": "worker-revision", "kind": "worker", "role":
    "builder"}`) did **not** fail under a `create_node`-scoped worker-contract
    check.
23. **Measured regression blast radius (probe, 2026-08-27).** A
    `kind == "worker"` presence check for `objective` / `access_mode` /
    `acceptance` was applied temporarily to `validate_patch`, the full suite
    run, and the edit reverted (`git status --short` clean afterwards; no git
    revert command used). Result: **29 failed, 5437 passed, 5 skipped** —
    i.e. exactly 29 existing tests break, all with a
    `worker node requires objective: ...` style rejection, none from an
    unrelated cause. Per file: `test_graph_planner.py` 10,
    `test_patch_validator.py` 4, `test_graph_macros.py` 3,
    `test_graph_dynamic_contract.py` 3, `test_graph_commands.py` 3,
    `test_cache_authority_chain.py` 2, `test_graph_horizon_templates.py` 2,
    `test_graph_parent_child_translation.py` 2. Zero integration tests broke.
24. **Compiler-seeded workers are provably exempt, and the pin already
    exists.** `tests/unit/test_graph_commands.py:4963
    test_seed_compiled_events_accepts_topology_and_controller_records_for_empty_run`
    seeds `{"node_id": "worker-1", "kind": "worker", "state": "planned"}` with
    none of the three fields and **passed** under the probe. That test is the
    standing regression pin for fact 9; chunk 3 adds no new test for it.
25. **`horizon_templates.py`'s discovery worker is never validated today.**
    `tests/unit/test_graph_horizon_templates.py:42-51` parametrizes
    `test_instantiated_horizon_templates_validate_as_planner_patches` over
    `implementation_region`, `validation_region`, `gap_analysis_region`,
    `corrective_work_region`, `final_invariant_region` — `discovery_region` is
    absent from the list, even though it is in `HORIZON_REGION_PURPOSES`.
    That is why only 2 of the 3 template worker nodes broke under the probe,
    and it is a pre-existing coverage hole on the exact node type the failed
    dogfood run got wrong.
26. **The per-kind contracts confirm `kind == "worker"` is the right
    predicate.** `contracts.py:807` `worker` is `handler_type="agent"`,
    `fulfillment="task_acceptance"`, required outputs `candidate` +
    `file_state`, roles `builder, discovery, implementer, fixer, reviewer,
    summarizer`. The other three members of `EXECUTABLE_NODE_KINDS` have
    structurally different contracts: `verifier` (`contracts.py:883`) produces
    a `verification_report` and already carries its obligation as `rubric`;
    `check` (`contracts.py:943`) is `handler_type="deterministic_command"` and
    already has a mandatory-command check (`_validate_check_command`);
    `planner` (`contracts.py:628`) produces `graph_patch_proposal` and has no
    acceptance concept at all. "Acceptance" is meaningless for all three.

### Verified facts from planning pass 4 (2026-08-27, chunk 4 research)

Established by reading the branch at `4ee76eda8` (chunks 1-3 landed).

27. **The file-state boundary is strictly post-execution evidence collection,
    not a gate.** `capture_file_state_boundary`
    (`graph_runtime/file_state.py:149`) is called from exactly two places, both
    after the agent has finished: `dispatch.py:1215` in `_submit_callback` (the
    worker has already returned its records) and `dispatch.py:1369` in
    `_finalize_runner_execution`. A third capture,
    `capture_worktree_file_state_baseline` (`dispatch.py:826`), runs *before*
    the agent starts but only records the pre-existing dirt so it can be
    subtracted later — it grants and denies nothing. The function itself is a
    `git status --porcelain=v2` scan plus `classify_file_state`; it has no
    write-blocking capability of any kind.
28. **The policy that boundary capture classifies against is run-scoped, not
    node-scoped, by explicit design.** `_authority_file_state_policy`
    (`dispatch.py:491-500`) derives the `FileStatePolicy` from
    `cache_authority_binding(context.graph_projection)` and its docstring reads
    "Runtime boundary authority comes exclusively from the verified snapshot."
    It re-checks `context.cache_authority_hash` against the binding and raises
    if they diverge. There is no per-node input to it, and adding one would
    mean breaking the property that the policy is bound to the verified routine
    snapshot — i.e. a per-node boundary rule is a *cache-authority* design
    change, not a small addition.
29. **`runner_boundary_mismatch` is a drift detector between two
    post-execution captures, unrelated to access control.**
    `handle_finalize_runner_execution` (`graph/commands/boundary.py:305-311`)
    emits it when `attempt.staged_boundary_hash != payload.boundary_hash`, i.e.
    the worktree changed between staging a submission and finalizing it, and
    pairs it with `runner_recovery_requested`. It cannot express "this node was
    not allowed to write" and it never inspects the node's authority.
30. **There is no per-node filesystem sandbox anywhere in the repo, and the two
    real sandboxes are both scoped wider than a node.** (a) Codex:
    `runners/agents/codex/agent.py:614-630` maps `self._restrictions` to the
    thread-level `sandbox` param (`danger-full-access` / `workspace-write` /
    config-decided); `_restrictions` is set once per agent from the DB agent
    config (`codex/factory.py:29`, default `"managed"`) and is never per-node.
    (b) Claude CLI: `git/worktree.py:173-249 _write_sandbox_settings` writes a
    genuine seatbelt allow/deny-list (`denyRead: ["/"]`, `allowWrite: [wt_abs,
    …]`, `denyWrite: read_only_paths`) — but it is written **once at worktree
    provisioning time**, grants write to the whole worktree, and belongs to a
    runner that graph dispatch does not use. Per-node sandboxing therefore
    requires threading a node-derived restriction through the agent factory,
    `ExecutionContext`, and each adapter: a runner-layer slice, not chunk 4.
31. **Resource claims do have real, kernel-level teeth — two of them —
    even though they are not a filesystem sandbox.**
    - *Scheduler mutual exclusion* (`scheduler.py:89-116 claims_conflict`):
      `write`/`write` conflicts on overlapping paths (106-107); a `read` claim
      with `snapshot_id is None` conflicts with a concurrent `write` over
      overlapping paths and vice versa (108-112); `read`/`read` never conflicts
      (113-114). So a `read`-claiming node is *both* protected from concurrent
      mutation of the shared worktree *and* freely parallelisable with other
      readers — a behavioural difference, not a label.
    - *Escalation refusal* (`patch_validator.py:857-882
      _resource_claim_escalation_reason`, `MODE_RANK` at `:61`): a
      `set_resource_claims` op is rejected when any requested mode outranks the
      node's current maximum rank. `read` is rank 0 and `write` is rank 1, so a
      node holding a `read` claim can **never** be raised to `write` by any
      later patch — `f"resource claim escalation for {node_id}: {mode}"`. This
      is the durable "read-only discovery cannot obtain write authority"
      property contract-doc scenario #1 asks for.
    - *Caveat that must not be glossed over:*
      `_existing_resource_claim_rank` returns `None` when the node holds **no**
      claims, and the escalation check then returns `None` (allows anything).
      A node with an empty claim list is therefore escalatable to `write`.
      Granting an explicit `read` claim — not "no claims" — is what closes
      this.
32. **`_ensure_default_node_authority` is the single chokepoint for every
    patch-created node's authority.** It is called at `_commands.py:5280` (the
    `create_node` branch of `_patch_op_events`) and at `_commands.py:5680`
    inside `_node_payload_for_op`, which is itself used by `create_gate`,
    `create_appeal`, both `worker_node`/`verifier_node` halves of
    `create_revision_attempt`, and `_node_created_event`. Its body
    (`_commands.py:5433-5444`) is `kind != "worker" → return`, then
    `setdefault("allowed_actions", …)`, then
    `if "resource_claims" not in authority: authority["resource_claims"] =
    [{"mode": "write", "scope": "repo", "paths": ["."]}]`. Note the test is
    `not in`, so an explicit `resource_claims: []` yields a claim-free node —
    the fact-31 escalation hole.
33. **The compiler never creates a discovery worker.**
    `graph/compiler.py:424` hardcodes `worker_role = "builder"` and it is the
    only value ever passed to `_create_worker`. Compiler workers also carry no
    `access_mode` (chunk 3 left the compiler exempt, fact 9) and their write
    claim is path-scoped via `_worker_write_paths(task)`
    (`compiler.py:550-556`, `:1109`), not repo-wide, whenever the task declares
    artifacts or `implementation_paths`. So `compiler.py` — the third site in
    fact 6 — is **not** on the discovery path and needs no chunk-4 edit.
34. **The macro *is* a live discovery-with-write path.** `worker_role` is a
    free-form `str | None` macro arg (`macros.py:35`) defaulting to `"fixer"`
    for corrective regions and `"builder"` otherwise (`macros.py:198`), and
    `_worker_node` (`macros.py:463-497`) emits the hardcoded
    `{"mode": "write", "scope": "repo", "paths": ["."]}` claim regardless of
    the `access_mode` chunk 3 threaded into it. A planner can therefore invoke
    `create_work_region` today with `worker_role: "discovery"` and
    `access_mode: "read_only"` and still get a repo-write worker — the field
    is currently decorative at this site.
35. **The canonical read claim already exists in the codebase and is
    runtime-proven.** `{"mode": "read", "scope": "repo", "paths": ["."]}` is
    what the compiler grants to fan-out join nodes (`compiler.py:662`),
    verifiers (`:773`), and check nodes (`:848`). Chunk 4 introduces no new
    claim vocabulary; it reuses this exact literal.
36. **An override flag must be a declared `NodeCreatedPayload` field.**
    `contracts.py:101 validate_node_payload` is hand-written (node_id / kind /
    role / ports) and does **not** model-validate, so an undeclared key
    survives patch validation — but `projections.py:906` re-validates every
    `node_created` payload through the `extra="forbid"` model on every replay
    (fact 12), so an undeclared key would blow up at event-application/replay
    time rather than at admission. There is no "carry it on the op only"
    option.
37. **Blast radius of an `access_mode`-driven authority change is near zero.**
    `grep -rn read_only src tests` returns 26 hits, of which exactly **one**
    `src` site creates a `read_only` node: `horizon_templates.py:51`
    (`discovery_region`). No test applies that template through `submit_patch`,
    and no existing test asserts a `read` claim on a worker. Changing what a
    `read_only` worker is granted therefore cannot regress an existing
    assertion; the `write`/absent path is left byte-identical on purpose so the
    standing pin
    `tests/unit/test_graph_commands.py:4381
    test_patch_accept_adds_default_worker_write_authority` keeps passing
    untouched.

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

### Chunk 2 — `work_mode` collision resolution (SPECIFIED, not built)

**Decision: option (b) — additive new key `access_mode`. The legacy
`work_mode` node key is not renamed, not retyped, and not touched.**

The chunk-queue row 2 one-liner ("Free the `work_mode` key … by moving the
legacy … key to its own name") was written before facts 11-17 were verified
and is **superseded by this section**. The queue table is left as written for
audit continuity; implement what is written here.

**Goal.** Give the "may this node write to the repository?" concept a typed,
unambiguous home on `NodeCreatedPayload` so chunks 3-6 can enforce and read it,
without any migration of persisted events, any pydantic compatibility shim, any
projection-schema bump, or any change to prompt selection. Independently
verifiable: after this chunk a `create_node` patch may carry
`access_mode: "read_only" | "write"`, that value survives live append and
checkpoint rebuild, `access_mode` with any other value is rejected, and a
historical payload carrying `work_mode: "implementation"` still validates and
still reaches `ExecutionContext.work_mode` unchanged.

#### Why (b) and not (a) — justification against the alternatives

Option (a) (rename legacy to `agent_work_mode`, retype `work_mode` to
`Literal["read_only","write"]`) was rejected on four counts:

1. **It is not actually back-compat by construction.** Fact 12: replay
   re-validates every historical `node_created` through the strict model. Old
   events carry `work_mode: "implementation"`, so a `Literal["read_only",
   "write"]` retype fails them with `literal_error`. Making (a) work requires a
   permanent `model_validator(mode="before")` that rewrites legacy values into
   the new key — new forever-code inside a payload model whose whole design
   property is that it is a dumb strict schema.
2. **The shim cannot retire the old key anyway.** Fact 13: retention filtering
   happens on raw dicts before validation, so `work_mode` must stay in the
   `node_created` `projection=` set forever for the shim to ever see it. (a)
   therefore ends with *both* keys in the registry — the same end state as (b),
   but reached through a migration.
3. **It changes the replay shape of live data that no test covers.** Fact 14:
   zero fixtures contain `work_mode`, but 15 real `node_created` events in the
   git-tracked journal do. Under (a) those nodes' `dispatch_payload` silently
   changes key, which is the checkpoint-divergence class `store.py:6347`
   exists to prevent, and would want a `PROJECTION_CHECKPOINT_SCHEMA_VERSION`
   bump (fact 15) to be safe. The full suite would stay green either way — a
   failure mode invisible to validation is the worst kind to accept for a
   naming preference.
4. **It creates a permanent name-crossing.** `TaskConfig.work_mode` and
   `ExecutionContext.work_mode` keep meaning `implementation`/`oversight` under
   every option (they are user-facing routine config and are themselves
   persisted inside `run_created` payloads — fact 14 — so renaming *them* is a
   strictly larger migration and is out of scope for Slice 1). Under (a),
   `dispatch.py:1160` would read node key `agent_work_mode` into
   `ExecutionContext.work_mode` while a *different* `work_mode` on the same
   payload means something else. Under (b) the legacy chain stays a clean 1:1
   identity `node["work_mode"] → ExecutionContext.work_mode` and the new
   concept has a name that is never confusable with it.

Cost of (b): the field is named `access_mode`, not `work_mode`. Fact 17 shows
the contract doc's list is conceptual and the target doc's own criterion 1
already prunes it (`required_inputs`, `expected_outputs` dropped). Criteria
2 and 3 name `work_mode` only as the thing being enforced/defaulted; read
`access_mode` wherever they say `work_mode`.

Option (c) considered and rejected: renaming the *legacy* concept across
`TaskConfig` / `ExecutionContext` / the three agent adapters to free the name
globally — 20 `src/` sites plus persisted `run_created` routine snapshots plus
`tests/unit/test_cli_agent.py` and `tests/unit/test_prompt_generation.py`,
for zero behavioural gain.

#### Files touched (exactly these five)

1. `src/orchestrator/graph/models.py`
2. `src/orchestrator/graph/payload_registry.py`
3. `tests/unit/test_node_created_event_payloads.py`
4. `tests/unit/test_graph_dispatch_on_output.py`
5. `tests/unit/test_graph_payload_field_allowlists.py`

(1-2 are the only `src/` changes. **Do not touch**
`graph/compiler.py`, `graph_runtime/dispatch.py`, `graph/patch_validator.py`,
`graph/contracts.py`, `graph/macros.py`, `graph/_commands.py`,
`graph_runtime/prompts.py`, `config/models.py`, `runners/**`, or any
`.orchestrator/state/*.jsonl`.)

#### 1. `src/orchestrator/graph/models.py`

Add exactly one field to `NodeCreatedPayload`, inserted immediately **above**
the existing `acceptance: list[str] | None = None` line (currently 1646) to
keep that block's alphabetical order:

```python
    access_mode: Literal["read_only", "write"] | None = None
```

`Literal` is already imported (`models.py:6`). Default `None` is required —
the field must stay optional in chunk 2 (chunk 3 owns presence enforcement,
which happens in the patch validator against the raw op dict, per fact 8).

Do **not** modify `work_mode: str | None = None` (currently 1682) — not its
type, not its name, not its position. Add one clarifying comment line directly
above each of the two fields so the split is legible at the point of
definition, e.g.:

```python
    # Repository write authority declared for this node (Slice 1 worker
    # contract). Distinct from ``work_mode`` below.
    access_mode: Literal["read_only", "write"] | None = None
```

```python
    # Legacy builder-vs-oversight prompt selector, mirrored from
    # ``TaskConfig.work_mode`` by the compiler and consumed as
    # ``ExecutionContext.work_mode``. Not repository authority — see
    # ``access_mode``.
    work_mode: str | None = None
```

Comment wording is the Builder's; the two facts each comment must state are
fixed: which concept the field carries, and that the other field is the one
carrying the other concept.

#### 2. `src/orchestrator/graph/payload_registry.py`

In the `_spec("node_created", ...)` call (line 270), add `access_mode` to the
`projection=` string **only**. It sorts first, so the string begins
`"access_mode acceptance allowed_actions appealed_node_id …"`. Leave
`work_mode` at the end of that same string untouched.

Do **not** add `access_mode` to `light=`, `summary=`, or `node_detail=` —
same rationale as chunk 1 (chunk 5 adds `node_detail` entries when the prompt
surface actually needs them; chunk 4 reads authority off the projection).
Retention tuples are derived automatically (`payload_registry.py:437-447`), so
this one string is the whole change. `PROJECTION_SCHEMA_VERSION` must stay at
**15** — a purely additive optional field does not change checkpoint shape for
any existing event.

#### 3. `tests/unit/test_node_created_event_payloads.py`

Add four tests, in the style of the chunk-1 pair at lines 190-235:

- `test_access_mode_and_legacy_work_mode_are_independent_fields` — build a raw
  dict carrying **both** `"access_mode": "read_only"` and
  `"work_mode": "implementation"`; assert
  `NodeCreatedPayload.model_validate(raw).model_dump(mode="json") == raw`, and
  assert the two attributes hold their own values
  (`payload.access_mode == "read_only"`, `payload.work_mode ==
  "implementation"`).
- `test_access_mode_rejects_values_outside_the_read_write_literal` — assert
  `pydantic.ValidationError` for each of `"implementation"`, `"oversight"`,
  and `"read"` (the last one pins the deliberate `read_only`-vs-claim-`read`
  spelling from fact 16). Parametrize if the file's existing negative test at
  line 66 already parametrizes; otherwise three `pytest.raises` blocks.
- `test_legacy_work_mode_payloads_still_replay_without_access_mode` — the
  replay-compatibility pin for fact 12. Build a projection from a single
  `node_created` event carrying `"work_mode": "implementation"` and **no**
  `access_mode`; assert `node_payload_view(projection, "worker-1")["work_mode"]
  == "implementation"` and `"access_mode" not in
  node_payload_view(projection, "worker-1")`. This test must fail if anyone
  later retypes or removes `work_mode`.
- `test_access_mode_reaches_the_dispatch_payload` — mirror of chunk 1's
  `test_worker_contract_fields_reach_the_dispatch_payload`: `build_projection`
  over one `node_created` event with `"access_mode": "read_only"`, then assert
  `node_payload_view(projection, "worker-1")["access_mode"] == "read_only"`.

#### 4. `tests/unit/test_graph_dispatch_on_output.py`

Add one test next to the existing `test_execution_context_*` group (lines
1500-1531), using the file's `_context(...)` helper (line 56, takes
`node_payload=`) and `RecordingExecutor`:

- `test_access_mode_does_not_affect_legacy_execution_context_work_mode` —
  build a context with
  `node_payload={"work_mode": "oversight", "access_mode": "read_only"}`, call
  `executor._execution_context(context)`, and assert
  `execution_context.work_mode == "oversight"`. Then repeat with
  `node_payload={"access_mode": "write"}` only and assert
  `execution_context.work_mode == "implementation"` (the `_work_mode()`
  fallback at `dispatch.py:3006`). This is the regression pin that the two
  concepts never cross-wire at the single read site.

#### 5. `tests/unit/test_graph_payload_field_allowlists.py`

Add one test alongside
`test_node_created_retains_worker_contract_fields_for_projection_replay`:

- `test_node_created_retains_access_mode_and_legacy_work_mode_separately` —
  `spec = EVENT_PAYLOAD_SPECS["node_created"]`; assert
  `"access_mode" in spec.projection` **and** `"work_mode" in spec.projection`
  (the second half pins fact 13: legacy retention may never be dropped), and
  assert `"access_mode"` is absent from `spec.light`, `spec.summary`, and
  `spec.node_detail`.

#### Verification conditions (all must hold)

- Exactly the five files above changed; `git status --short` shows nothing
  else. In particular `.orchestrator/state/*.jsonl` is unmodified.
- `uv run pytest tests/ -q -n auto --dist worksteal` reports **5463 passed, 5
  skipped** — i.e. chunk 1's 5458 plus exactly the 5 new tests, zero
  regressions, **zero existing tests modified**.
- `PROJECTION_CHECKPOINT_SCHEMA_VERSION` still `15`
  (`graph/projection_codec.py:40`).
- `grep -rn "work_mode" src/` still returns the same 20 hits as before the
  chunk (no site renamed, no site added).
- Ruff, ruff format, and pyright clean.
- Sanity check by execution (not a committed test): a payload carrying
  `work_mode: "implementation"` and no `access_mode` still validates, and
  `access_mode: "implementation"` raises.

#### Downstream naming note for chunks 3-6

Chunk-queue rows 3 and 4 and target-doc criteria 1-3 say `work_mode` where
they mean the read-only/write concept. After chunk 2 that concept is
**`access_mode`** everywhere:

- Chunk 3 enforces presence of `objective`, **`access_mode`**, `acceptance`.
- Chunk 4 defaults `role="discovery"` nodes to **`access_mode="read_only"`**
  and requires an explicit flagged override for
  `role="discovery"` + `access_mode="write"`.
- Chunk 5's prompt section renders **`access_mode`**; the legacy `work_mode`
  stays out of the worker packet exactly as it is today.

### Chunk 3 — Patch-validator contract enforcement (SPECIFIED, not built)

**Goal.** Make a bounded worker contract *mandatory* on every planner- or
agent-proposed worker node, with a message that names the missing field and the
node. Independently verifiable: after this chunk a `create_node` op creating a
`kind="worker"` node without `objective`, `access_mode`, or `acceptance` is
rejected with a precise per-field reason; the same op with all three is
accepted; `verifier` / `check` / `planner` nodes are unaffected; compiler-seeded
workers still seed unchanged.

#### Scope decision — the predicate is `kind == "worker"`, role-independent

R2 asked for an explicit narrower predicate than `EXECUTABLE_NODE_KINDS`.
Ruling: **`kind == "worker"`, every role, no exceptions.**

- Not `EXECUTABLE_NODE_KINDS`: fact 26 — `verifier`, `check`, and `planner`
  have structurally different contracts and no acceptance concept, and `check`
  already has its own mandatory-command validation.
- Not narrowed by `role`: all six declared worker roles (`builder`,
  `discovery`, `implementer`, `fixer`, `reviewer`, `summarizer`) are
  agent-executed units of work that need a bounded objective, a declared
  access mode, and an acceptance condition. Exempting any role reopens exactly
  the hole the failed run fell through — its offending node was a *discovery*
  worker. `role` is already independently mandatory for executable nodes
  (`patch_validator.py:185`), so the two checks compose rather than overlap.
- Gap-planner-created corrective workers **are** in scope: they are
  `kind == "worker"` and reach the same `create_node` branch. The existing
  `_validate_gap_planner_node` check (region targeting) is orthogonal and runs
  first; both must pass.

#### Scope decision — `create_node` only, and that is complete

Fact 18: no op in `KNOWN_OPS` can mutate a node payload after creation, so
there is no "later op strips the field" surface to guard. Criterion 2's
"`create_node`/`patch` operations" is fully covered by the `create_node`
branch.

Two adjacent surfaces are **deliberately out of scope** and must be left
alone by the Builder:

- `create_revision_attempt`'s `worker_node` (fact 22) — it bypasses
  `validate_node_payload` today as well, so bringing it under the contract
  check is a strictly larger change (it would also need the revision-attempt
  producers to supply the fields). Recorded as R5.
- `seed_compiled_events` (fact 9) — compiler-seeded workers keep working
  untouched. This is the correct blast radius for chunk 3: the failed dogfood
  run `fff4f6b7` was a *planner*-proposed graph, which is exactly the surface
  this chunk closes. Populating the fields from the compiler is a separate,
  later change.

#### Files touched

Six `src/` files, three test files for new coverage, plus the eight test files
listed under "Existing tests that must be repaired" (two of which overlap:
`test_patch_validator.py` and `test_graph_macros.py` are both edited for new
coverage and repaired).

`src/` (six):

1. `src/orchestrator/graph/patch_validator.py` — the check.
2. `src/orchestrator/graph/macros.py` — macro arg pass-through.
3. `src/orchestrator/graph_runtime/horizon_templates.py` — templates carry the
   fields.
4. `src/orchestrator/graph_runtime/prompts.py` — **only** the example-patch
   dicts around line 963. Do **not** touch `prompts.py:347-372` (chunk 5).
5. `src/orchestrator/runners/agents/codex/common.py` — macro `inputSchema`
   properties.
6. `src/orchestrator/graph_runtime/graph_mcp_tools.py` — macro tool signatures.

`tests/` edited for new coverage (three):

7. `tests/unit/test_patch_validator.py`
8. `tests/unit/test_graph_macros.py`
9. `tests/unit/test_graph_horizon_templates.py`

Do **not** touch: `graph/contracts.py` (the contract registry describes ports
and roles, not payload-field presence — the check belongs next to the other
hand-written `create_node` checks, not in `validate_node_payload`, which is
also called from paths that must stay presence-agnostic), `graph/compiler.py`,
`graph/_commands.py`, `graph/models.py`, `graph/payload_registry.py`,
`graph/macros.py`'s `_verifier_node`/`_attach_check`, or any
`.orchestrator/state/*.jsonl`.

#### 1. `src/orchestrator/graph/patch_validator.py`

Add a module-level helper next to `_validate_check_command` (i.e. after
`_validate_gap_planner_node`, before `_validate_check_command`), and call it
from the `create_node` branch of `validate_patch` immediately **after** the
`executable node requires role` check and **before** the `if kind == "check":`
branch:

```python
                if kind == "worker":
                    worker_contract_error = _validate_worker_contract(typed_node)
                    if worker_contract_error is not None:
                        return PatchValidationResult(
                            accepted=False,
                            rejection_reason=worker_contract_error,
                        )
```

The helper evaluates fields in the fixed order `objective` → `access_mode` →
`acceptance` and returns the **first** failure (`validate_patch` carries a
single `rejection_reason`). `node_id` is already guaranteed a non-empty `str`
here because `validate_node_payload` ran first and rejects a missing one.

**Exact error messages** (fact 10 hand-written convention: lowercase phrase,
colon, offending node id; one field per message, never a bundled list):

| condition | message |
|---|---|
| `objective` absent, `None`, non-`str`, or blank/whitespace-only | `f"worker node requires objective: {node_id}"` |
| `access_mode` absent or `None` | `f"worker node requires access_mode: {node_id}"` |
| `access_mode` present but not `"read_only"`/`"write"` | `f"worker node access_mode must be read_only or write: {node_id}"` |
| `acceptance` absent, `None`, or `[]` | `f"worker node requires acceptance: {node_id}"` |
| `acceptance` present but not a list of non-empty `str` | `f"worker node acceptance must be a list of non-empty strings: {node_id}"` |

The two "must be" variants mirror the existing `resource_claims mode must be
one of ...` style and keep a wrong *value* from being reported as a missing
*field*. Do not add a sixth message, do not bundle fields, and do not route
any of these through `_error_rendering` — these are hand-written rejections,
not pydantic diagnostics.

#### 2. `src/orchestrator/graph/macros.py`

Add three **optional** fields to `CreateWorkRegionArgs` (shared by
`create_work_region` and `create_corrective_region` via `_MACRO_SPECS`):

```python
    objective: str | None = None
    access_mode: Literal["read_only", "write"] | None = None
    acceptance: list[str] | None = None
```

`Literal` is already imported (`macros.py:9`). Thread them through
`_create_work_region` into `_worker_node(...)` as keyword args, and have
`_worker_node` emit each key **only when the value is not `None`**.

They stay optional at the macro layer on purpose: a missing arg must surface
as the validator's precise hand-written message, not as a pydantic
`invalid_macro_arguments` blob from `_validate_invocation`
(`macros.py:161-176`). `_validate_invocation` already does
`model_dump(exclude_none=True)`, so unset args simply do not reach
`_worker_node`. Do not touch `_verifier_node`.

#### 3. `src/orchestrator/graph_runtime/horizon_templates.py`

Add all three fields to the three worker `create_node` nodes (lines 44, 67,
171 — discovery / implementation / corrective-work). Use concrete,
purpose-appropriate placeholder values consistent with each template's
existing `description`, and in particular give the **discovery** template
`"access_mode": "read_only"` — it is the template for the exact node class the
failed run got wrong, and chunk 4 will make that the enforced default.
Implementation and corrective-work templates get `"access_mode": "write"`.

#### 4. `src/orchestrator/graph_runtime/prompts.py`

Add the same three keys to the `worker-example` node in the example patch at
`prompts.py:963` (`"access_mode": "write"`, a one-line `objective`, a
one-entry `acceptance`). Surgical dict edit only. `prompts.py:347-372` is
chunk 5's and must not be touched — there is no overlap between the two
regions.

#### 5. `src/orchestrator/runners/agents/codex/common.py`

Add `objective` (`{"type": "string"}`), `access_mode`
(`{"type": "string", "enum": ["read_only", "write"]}`), and `acceptance`
(`{"type": "array", "items": {"type": "string"}}`) to the `properties` of both
`planner_macro_specs["create_work_region"]` (line 565) and
`planner_macro_specs["create_corrective_region"]` (line 643). Both schemas are
`additionalProperties: False`, so without this an agent cannot pass the fields
at all.

**Do not add them to either schema's `required` list.** Keeping them
schema-optional means the single enforcement point — and the single error
message — is the validator, identical for the macro path and the raw-`ops`
path. Promoting them to schema-`required` is a reasonable follow-up once
chunk 5 also documents them in the planner prompt text
(`common.py:1181-1184`), and should be decided there, not here.

#### 6. `src/orchestrator/graph_runtime/graph_mcp_tools.py`

Add `objective: str | None = None`, `access_mode: str | None = None`,
`acceptance: list[str] | None = None` to the `create_work_region` (line 105)
and `create_corrective_region` (line 136) tool signatures, forwarded into
`args` with the same `if ... is not None` pattern the existing optional params
use. `runners/graph_tool_routing.py` needs no change (fact 20).

#### 7. `tests/unit/test_patch_validator.py`

Add one test group, using the file's existing `validate_patch` helper at
line 95:

- `test_create_node_rejects_worker_without_objective` — assert
  `result.accepted is False` and
  `result.rejection_reason == "worker node requires objective: worker-1"`.
- `test_create_node_rejects_worker_without_access_mode` — objective present;
  expect `"worker node requires access_mode: worker-1"`.
- `test_create_node_rejects_worker_with_invalid_access_mode` — pass
  `"access_mode": "implementation"`; expect
  `"worker node access_mode must be read_only or write: worker-1"`. (This pins
  the chunk-2 `access_mode`-vs-`work_mode` split at the validator layer too.)
- `test_create_node_rejects_worker_without_acceptance` — objective and
  access_mode present; expect `"worker node requires acceptance: worker-1"`.
- `test_create_node_rejects_worker_with_malformed_acceptance` — pass
  `"acceptance": "run the tests"` (a bare string); expect
  `"worker node acceptance must be a list of non-empty strings: worker-1"`.
- `test_create_node_accepts_worker_with_full_contract` — all three present;
  assert `result.accepted is True`.
- `test_worker_contract_is_not_required_of_non_worker_kinds` — parametrized
  over `verifier`, `check`, `planner` (each with its own already-required
  extras: `role`, and for `check` a `command_binding`), none carrying the
  three fields; assert `result.accepted is True`. This is the R2 pin: it must
  fail if anyone later widens the predicate back to `EXECUTABLE_NODE_KINDS`.
- `test_gap_planner_corrective_worker_requires_worker_contract` — actor role
  `gap_planner`, node in `corrective_work_region`, missing `objective`; expect
  the objective message. Pins that corrective workers are in scope.
- `test_create_revision_attempt_worker_node_is_not_contract_checked` — a
  `create_revision_attempt` op whose `worker_node` carries none of the three
  fields is still accepted. This deliberately pins the R5 scope boundary so a
  later chunk that closes it has to change this test on purpose rather than by
  accident.

#### 8. `tests/unit/test_graph_macros.py`

- `test_create_work_region_macro_forwards_worker_contract_fields` — invoke the
  macro with the three new args, assert the expanded worker `create_node`
  node dict carries them verbatim, and assert the expanded patch passes
  `validate_patch`.
- `test_create_work_region_macro_without_contract_fields_is_rejected` — invoke
  the macro with no contract args and assert `validate_patch` rejects with
  `"worker node requires objective: worker-<region_id>"`. This is the pin that
  the macro is not a bypass around the check.

#### 9. `tests/unit/test_graph_horizon_templates.py`

- Add `"discovery_region"` to the `@pytest.mark.parametrize` list at lines
  42-51, closing the pre-existing hole in fact 25. (This adds one test ID.)
- `test_worker_horizon_templates_declare_the_worker_contract` — for every
  purpose in `HORIZON_REGION_PURPOSES`, every `create_node` op with
  `kind == "worker"` carries a non-empty `objective`, an `access_mode` in
  `{"read_only", "write"}`, and a non-empty `acceptance` list; additionally
  assert the `discovery_region` worker's `access_mode == "read_only"`.

#### Existing tests that must be repaired (29, measured — fact 23)

**Rule for the Builder: fix the fixtures, never weaken the check.** Every one
of these is an under-specified worker node — precisely the shape the contract
doc diagnosed in run `fff4f6b7`. Adding a one-line `objective`, an
`access_mode`, and a one-entry `acceptance` to each worker node dict is the
correct repair. Do not add an opt-out flag, do not narrow the predicate, and
do not special-case a test module.

| file | count | how to repair |
|---|---|---|
| `tests/unit/test_graph_planner.py` | 10 | Most flow from the shared `_region_ops` helper (line 558) plus the two inline corrective-worker ops near lines 233 and 289. Fix the helper first and re-run — the count should collapse. |
| `tests/unit/test_patch_validator.py` | 4 | Incidental: three are `create_edge` tests (`..._binding_policy_incompatible_with_target_cardinality`, `..._accepts_known_prompt_hydration_policy`, `..._rejects_unknown_prompt_hydration_policy`) that happen to build a worker as the edge source, plus `test_gap_planner_can_append_corrective_work_region`. Add the three fields to the worker node dicts. |
| `tests/unit/test_graph_macros.py` | 3 | `test_create_work_region_macro_expands_to_valid_patch`, `test_gap_planner_corrective_region_macro_expands_to_valid_patch`, `test_submit_patch_command_accepts_macro_invocations` — pass the three **new macro args** (not node-dict edits; these go through the macro). |
| `tests/unit/test_graph_dynamic_contract.py` | 3 | `test_patch_contract[corrective_worker_without_classified_gap]`, `test_patch_contract[corrective_worker_by_gap_planner_is_exempt]`, `test_authority_request_edge_to_worker_authority_port_is_valid`. The first two share the `_CORRECTIVE_WORKER` constant (near line 247) — one edit fixes both. |
| `tests/unit/test_graph_commands.py` | 3 | `test_patch_accept_adds_default_worker_write_authority`, `test_patch_accepts_authority_request_edge_to_worker_authority_input`, `test_gap_planner_corrective_work_patch_accepts_through_submit_patch`. |
| `tests/unit/test_cache_authority_chain.py` | 2 | `test_dynamic_nodes_inherit_authority_hash[generic]` and `test_dynamic_nodes_reject_explicit_authority_mismatch[generic]` — the `generic` parametrization's worker node (near lines 507/567/587). The `[revision]`-style cases pass untouched (fact 22). |
| `tests/unit/test_graph_horizon_templates.py` | 2 | `[implementation_region]` and `[corrective_work_region]` — repaired by the **src** change in file 3, **not** by editing the test. |
| `tests/unit/test_graph_parent_child_translation.py` | 2 | `test_child_order_is_chain_order`, `test_region_label_names_child_routine` — the worker node dict near line 221. |

Zero integration tests break, and
`tests/unit/test_graph_commands.py::test_seed_compiled_events_accepts_topology_and_controller_records_for_empty_run`
passes untouched (fact 24) — that is the standing proof the compiler-seeding
path stays exempt.

#### Verification conditions (all must hold)

- Exactly the six `src/` files and the test files above changed;
  `git status --short` shows nothing else. In particular
  `.orchestrator/state/*.jsonl`, `graph/models.py`, `graph/contracts.py`, and
  `graph/compiler.py` are unmodified.
- `uv run pytest tests/ -q -n auto --dist worksteal` reports
  **5466 + (new test IDs) passed, 5 skipped**, with all 29 measured failures
  repaired and no other regression. Chunk 2's baseline is 5466 passed / 5
  skipped.
- `grep -rn "EXECUTABLE_NODE_KINDS" src/` still returns only its definition
  (`patch_validator.py:64`) and the single existing use at
  `patch_validator.py:185` — the new check must **not** use it.
- `PROJECTION_CHECKPOINT_SCHEMA_VERSION` still `15`; no event payload or
  retention change in this chunk.
- Ruff, ruff format, and pyright clean.
- Sanity check by execution (not a committed test): submitting a
  `create_work_region` macro invocation with no contract args is rejected with
  `worker node requires objective: worker-<region_id>`, and the same
  invocation with all three args is accepted.

### Chunk 4 — Discovery nodes read-only, with teeth (SPECIFIED, not built)

**Goal.** Make `access_mode` *mean something* — a `read_only` worker is granted
a `read` resource claim instead of repo write, which is a real scheduler and
escalation-refusal property — and forbid a `role="discovery"` worker from
declaring `access_mode="write"` unless it carries an explicit, separately
recorded justification. Independently verifiable: after this chunk a discovery
worker declaring `write` without an override is rejected by name; the same node
with an override is accepted; a `read_only` worker is materialized with a
`read` claim (never the repo-write default) and cannot subsequently be escalated
to `write` by any patch; and non-discovery worker roles are entirely unaffected.

#### Framing correction — there is no "default" left to control

The target doc's criterion 3 and chunk-queue row 4 both say "default discovery
`work_mode` is `read_only`". That framing predates chunk 3. The landed check
(`patch_validator.py:375-396 _validate_worker_contract`) rejects **every**
`kind == "worker"` `create_node` op whose `access_mode` is absent or `None`
with `worker node requires access_mode: {node_id}`, role-independently. There is
therefore no planner-reachable path on which an omitted `access_mode` could be
defaulted — the field is already mandatory and explicit.

Chunk 4 consequently splits into the two things that *are* still open, and the
"default" bullet is satisfied more strongly than by a default: a discovery
worker must state its access mode, and `read_only` is the only value it may
state absent an override.

1. **Authority derivation** — `access_mode` currently has no effect on anything.
   All three fact-6 sites hand out repo write. This is the part that makes
   criterion 3 more than a field label (fact 34: a discovery node declaring
   `read_only` through the macro *still* gets repo write today).
2. **Role policy** — `role == "discovery"` may not declare `access_mode:
   "write"` without an explicit override field.

The queue table row 4 is left as written for audit continuity, exactly as chunk
2's row was; implement what is written here.

#### Decision — option (a′): claim refusal at admission, plus real derivation

Chosen: **(a) admission-time refusal, upgraded to (a′) by also deriving the
resource claim from `access_mode` at the patch-reachable grant sites.** Options
(b) and (c) are rejected.

*Why plain (a) as originally posed is insufficient.* Validating that a discovery
node may not *declare* `write` does not stop it from *receiving* write. Facts 32
and 34: the node still flows through `_ensure_default_node_authority` (or the
macro's hardcoded literal) and is materialized with
`{"mode": "write", "scope": "repo", "paths": ["."]}`. A validator-only chunk 4
would be precisely the "typed field with no teeth" outcome R3 warns against. The
derivation is the load-bearing half.

*Why not (b) boundary-time rejection.* Facts 27-29 settle this by reading the
code path, not by assumption:

- The boundary is captured only **after** the agent has finished
  (`dispatch.py:1215`, `:1369`). It is post-hoc by construction. The
  pre-execution capture (`dispatch.py:826`) is a baseline for subtraction and
  grants nothing.
- Damage lands in shared state before detection. The graph worktree is reused
  across sequential executions (`capture_worktree_file_state_baseline`'s
  docstring: "A graph worktree is shared across sequential task executions"),
  serialized by `_worktree_execution_lock`. A discovery worker's writes are
  already on disk and already in the next node's baseline by the time any
  boundary is classified. That is *literally* the failed dogfood run's
  "corrective work compounded in the same dirty worktree" symptom, so choosing
  a mechanism that only fires afterwards would reproduce it.
- It is not cheap. The classification policy is bound to the verified routine
  snapshot and is documented as run-scoped
  (`_authority_file_state_policy`, fact 28); introducing a per-node policy is a
  cache-authority design change with its own hash-binding consequences.
- `runner_boundary_mismatch` is the wrong instrument regardless (fact 29): it
  compares a staged boundary hash to a final boundary hash to detect drift and
  request recovery. It never reads node authority and cannot express an
  access-control verdict.

*Why not (c) both.* (c) was evaluated as "(a′) plus a cheap boundary-time
assertion". It is not cheap: the assertion needs per-node policy plumbing (fact
28), a new rejection shape distinguishable from `file_state_rejected`, and
integration coverage on the hot callback path. Chunk 4 stays at unit-test cost.
The idea is preserved rather than dropped — recorded as **R6** with the exact
insertion point — so a later chunk can add it deliberately.

*What (a′) actually buys, stated honestly.* It is **not** an OS-level sandbox
and the ledger should not claim otherwise (fact 30: no per-node sandbox exists,
and building one is a runner-layer slice). What it buys is three concrete,
kernel-enforced properties:

1. The node is scheduled under a `read` claim, so it can never be co-scheduled
   with a repo writer over overlapping paths and never blocks other readers
   (fact 31, `scheduler.py:106-114`).
2. The node can never be raised to `write` by any subsequent patch —
   `set_resource_claims` escalation refusal, rank 0 → rank 1 (fact 31,
   `patch_validator.py:857-882`). This is the exact property contract-doc
   scenario #1 names.
3. The `worker_authority` prompt packet (`prompts.py:385-406`) advertises
   `read`, not `write`, so the agent is told its actual authority.

Combined with the admission gate, a discovery worker cannot be *created* with
write authority, cannot be *granted* it by default, and cannot *acquire* it
later. That is a durable authority property rather than a label, which is what
criterion 3 asks for.

#### Files touched (exactly these)

`src/` (seven):

1. `src/orchestrator/graph/models.py` — declare the override field.
2. `src/orchestrator/graph/payload_registry.py` — `projection=` retention.
3. `src/orchestrator/graph/patch_validator.py` — extend
   `_validate_worker_contract`.
4. `src/orchestrator/graph/_commands.py` — `_ensure_default_node_authority`
   derivation.
5. `src/orchestrator/graph/macros.py` — `_worker_node` derivation + the new
   macro arg.
6. `src/orchestrator/runners/agents/codex/common.py` — macro `inputSchema`
   property (both macros).
7. `src/orchestrator/graph_runtime/graph_mcp_tools.py` — macro tool signatures
   (both macros).

`tests/` (five): `tests/unit/test_patch_validator.py`,
`tests/unit/test_graph_commands.py`, `tests/unit/test_graph_macros.py`,
`tests/unit/test_node_created_event_payloads.py`,
`tests/unit/test_graph_payload_field_allowlists.py`.

**Do not touch:** `src/orchestrator/graph/compiler.py` (fact 33 — it never
creates a discovery worker, its workers carry no `access_mode` to derive from,
and its write claim is already path-scoped); `graph_runtime/prompts.py` (chunk
5 owns it; its example patch is a `builder` + `write` worker and stays valid);
`graph_runtime/horizon_templates.py` (the discovery template already declares
`access_mode: "read_only"` from chunk 3 and needs no edit — chunk 4 makes that
declaration bite); `graph/contracts.py`; `graph_runtime/dispatch.py`;
`graph_runtime/file_state.py`; `graph/commands/boundary.py`; `graph/scheduler.py`;
`runners/**` beyond file 6; any `.orchestrator/state/*.jsonl`.

#### 1. `src/orchestrator/graph/models.py`

One field on `NodeCreatedPayload`, inserted immediately **below**
`access_mode` (currently 1648) to keep the block's alphabetical order:

```python
    # Recorded escape hatch: the only way a ``role="discovery"`` worker may
    # declare ``access_mode="write"``. Rejected when present on any node that
    # does not need it, so its presence in the journal is a precise audit
    # marker rather than boilerplate.
    access_mode_override_justification: str | None = None
```

Default `None`, optional at the model layer as always — presence rules live in
the patch validator against the raw op dict (fact 8).

#### 2. `src/orchestrator/graph/payload_registry.py`

Add `access_mode_override_justification` to the `_spec("node_created", …)`
`projection=` string **only** (it sorts directly after `access_mode`). Not
`light=`, not `summary=`, not `node_detail=`. `PROJECTION_SCHEMA_VERSION` stays
at **15** — purely additive optional field, no existing event's shape changes.

#### 3. `src/orchestrator/graph/patch_validator.py`

Extend the existing `_validate_worker_contract` helper (`:375`). **Append** the
new checks after the current `acceptance` checks and return the first failure;
do not reorder or reword any of the five chunk-3 messages, whose exact strings
are asserted by landed tests. No new call site, no new helper, and the
`kind == "worker"` predicate is unchanged (so `EXECUTABLE_NODE_KINDS` stays
unreferenced by this path).

Evaluation order, appended: **(6)** override-field shape → **(7)**
discovery/write policy → **(8)** claim/`access_mode` consistency.

| # | condition | message |
|---|---|---|
| 6 | `access_mode_override_justification` present but not a `str`, or blank/whitespace-only | `f"access_mode_override_justification must be a non-empty string: {node_id}"` |
| 7 | `role == "discovery"` and `access_mode == "write"` and no non-blank `access_mode_override_justification` | `f"discovery worker cannot declare access_mode write; supply access_mode_override_justification: {node_id}"` |
| 8 | a non-blank `access_mode_override_justification` on a node that is not (`role == "discovery"` and `access_mode == "write"`) | `f"access_mode_override_justification is only valid for a discovery worker declaring access_mode write: {node_id}"` |
| 9 | `access_mode == "read_only"` and `authority.resource_claims` contains a claim whose `mode` ranks above `read` in `MODE_RANK` | `f"read_only worker cannot claim {mode} authority: {node_id}"` |

Notes the Builder must respect:

- The semicolon-clause shape of message 7 follows the existing
  `"check node cannot expose hidden_oracle_command; use command_binding:
  {node_id}"` precedent (`patch_validator.py:409`) — it is not a new
  convention.
- Message 9 interpolates the offending `mode` so `write`, `graph_write`, and
  `review_write` each report themselves. Read the claims via the existing
  `resource_claim_dicts(...)` helper off `node.get("authority")`; return on the
  first offending claim. Modes absent from `MODE_RANK` — i.e. `external` — are
  **permitted** on a `read_only` worker: an external-resource claim is not repo
  write authority and gating it here would be unrelated scope.
- Check 8 (rejecting an unnecessary override) is deliberate: without it
  planners will cargo-cult the field onto every worker and it stops being a
  signal. It also makes a `grep` of the journal for the field a complete list
  of every discovery-write exception ever granted.
- The justification requirement is *non-blank*, with no minimum length. No
  other check in this file uses a magic length threshold, and the deterrent is
  that the string is durably recorded on the node and rejected wherever it is
  not needed — not that it is long.

#### 4. `src/orchestrator/graph/_commands.py`

Rewrite the claim branch of `_ensure_default_node_authority` (`:5433-5444`) to
derive from `access_mode`. Everything else in the function — the early
`kind != "worker"` return and the `allowed_actions` `setdefault` — is
unchanged:

```python
    if node_payload.get("access_mode") == "read_only":
        if not authority.get("resource_claims"):
            authority["resource_claims"] = [
                {"mode": "read", "scope": "repo", "paths": ["."]}
            ]
    elif "resource_claims" not in authority:
        authority["resource_claims"] = [
            {"mode": "write", "scope": "repo", "paths": ["."]}
        ]
```

Two properties are load-bearing and must not be "tidied" into symmetry:

- The `read_only` branch tests **falsiness** (`not authority.get(...)`), so an
  explicit `resource_claims: []` is normalized to a `read` claim. This closes
  the fact-31 escalation hole: a claim-free node has no rank and is escalatable
  to `write` by a later `set_resource_claims`, whereas a rank-0 `read` claim is
  not.
- The `write` branch keeps the existing `"resource_claims" not in authority`
  membership test verbatim, so behaviour for every non-`read_only` node —
  including every node that exists today — is byte-identical (fact 37).

This is the single chokepoint (fact 32), so the derivation lands for
`create_node`, `create_gate`, `create_appeal`, `create_revision_attempt`'s
`worker_node`, and `_node_created_event` in one edit.

#### 5. `src/orchestrator/graph/macros.py`

Two edits.

(a) `_worker_node` (`:463`) already receives `access_mode`. Replace the
hardcoded literal in its `authority` dict with the derived claim:

```python
            "resource_claims": [
                {"mode": "read", "scope": "repo", "paths": ["."]}
                if access_mode == "read_only"
                else {"mode": "write", "scope": "repo", "paths": ["."]}
            ],
```

Deliberately *not* deleting the claim and letting file 4 derive it: the
expanded ops are what `validate_patch` sees (fact 19), so check 9 must be able
to inspect the claim the node will actually get, and the macro's emitted patch
stays a faithful, reviewable description of the node it creates.

(b) Add one optional arg to `CreateWorkRegionArgs` (`:30`), beside the chunk-3
trio:

```python
    access_mode_override_justification: str | None = None
```

Thread it through `_create_work_region` into `_worker_node(...)` and emit the
key **only when not `None`**, exactly as the chunk-3 fields are handled. It
stays optional at the macro layer for the chunk-3 reason: a missing value must
surface as the validator's precise hand-written message, not as an
`invalid_macro_arguments` blob. Exposing it at all is required by fact 19's
rule — the macro must be able to express anything the validator will accept, or
`create_work_region` becomes a trap for a planner that legitimately needs a
discovery worker with write. Do not touch `_verifier_node`.

#### 6. `src/orchestrator/runners/agents/codex/common.py`

Add `access_mode_override_justification` (`{"type": "string"}`) to the
`properties` of both `planner_macro_specs["create_work_region"]` (`:565`) and
`["create_corrective_region"]` (`:643`). Both are
`additionalProperties: False`, so without this an agent cannot pass it. **Do
not** add it to either `required` list — same single-enforcement-point rule as
chunk 3.

#### 7. `src/orchestrator/graph_runtime/graph_mcp_tools.py`

Add `access_mode_override_justification: str | None = None` to the
`create_work_region` (`:105`) and `create_corrective_region` (`:136`)
signatures, forwarded into `args` with the existing `if ... is not None`
pattern. `runners/graph_tool_routing.py` needs no change (fact 20).

#### 8. `tests/unit/test_patch_validator.py`

Using the file's `_validate` helper (`:89`):

- `test_create_node_rejects_discovery_worker_declaring_write_access_mode` —
  `role="discovery"`, `access_mode="write"`, no override; expect
  `"discovery worker cannot declare access_mode write; supply access_mode_override_justification: worker-1"`.
- `test_create_node_accepts_discovery_worker_write_access_mode_with_override` —
  same node plus a non-blank justification; `result.accepted is True`.
- `test_create_node_rejects_blank_access_mode_override_justification` —
  justification `"   "`; expect
  `"access_mode_override_justification must be a non-empty string: worker-1"`.
  (Pins that check 6 runs before check 7, so a blank string is never mistaken
  for a valid override.)
- `test_create_node_rejects_unnecessary_access_mode_override_justification` —
  parametrized over `("discovery", "read_only")` and `("builder", "write")`;
  expect
  `"access_mode_override_justification is only valid for a discovery worker declaring access_mode write: worker-1"`.
- `test_create_node_rejects_read_only_worker_with_escalated_resource_claim` —
  parametrized over `write`, `graph_write`, `review_write` on a
  `access_mode="read_only"` worker's `authority.resource_claims`; expect
  `f"read_only worker cannot claim {mode} authority: worker-1"`.
- `test_create_node_accepts_read_only_worker_with_read_resource_claim` — the
  same node carrying `{"mode": "read", "scope": "repo", "paths": ["."]}`;
  accepted. Add an `external` claim case in the same test asserting acceptance,
  pinning the deliberate `external` carve-out.
- `test_non_discovery_worker_roles_may_declare_write_access_mode` —
  parametrized over `builder`, `implementer`, `fixer`, `reviewer`,
  `summarizer` with `access_mode="write"` and no override; all accepted. This
  is the "other roles unaffected" pin and must fail if anyone widens the
  predicate off `role == "discovery"`.
- `test_create_revision_attempt_discovery_worker_is_not_access_mode_gated` — a
  `create_revision_attempt` whose `worker_node` is
  `role="discovery"`/`access_mode="write"` with no override is still accepted.
  The deliberate R7 boundary pin, mirroring chunk 3's R5 pin, so closing it
  later is an intentional edit.

#### 9. `tests/unit/test_graph_commands.py`

The criterion-3 teeth tests, using the file's `_apply` helper:

- `test_patch_accept_grants_read_authority_to_read_only_worker` — submit a
  `create_node` patch for a `role="discovery"`, `access_mode="read_only"`
  worker; assert the emitted `node_created` payload's
  `authority["resource_claims"] == [{"mode": "read", "scope": "repo",
  "paths": ["."]}]`.
- `test_patch_accept_grants_read_authority_when_read_only_worker_declares_empty_claims`
  — same node carrying `authority: {"resource_claims": []}`; assert the `read`
  claim is injected rather than left empty. This is the escalation-hole
  closure and must fail if the `read_only` branch is "simplified" to a
  membership test.
- `test_read_only_worker_cannot_be_escalated_to_write_authority` — apply the
  read_only worker's `node_created`, then submit a `set_resource_claims` op
  requesting `{"mode": "write", "scope": "repo", "paths": ["."]}`; assert the
  patch is rejected with
  `"resource claim escalation for worker-1: write"`. This is contract-doc
  scenario #1 expressed as the property the kernel actually enforces, and it is
  the single most important test in the chunk.

`test_patch_accept_adds_default_worker_write_authority` (`:4381`) must pass
**untouched** — it is the standing pin that the write path did not change.

#### 10. `tests/unit/test_graph_macros.py`

- `test_create_work_region_macro_grants_read_claim_for_read_only_worker` —
  invoke with `access_mode: "read_only"`; assert the expanded worker node's
  `authority.resource_claims` is the `read` claim and that `validate_patch`
  accepts the expanded patch. Pins fact 34's hole closed.
- `test_create_work_region_macro_discovery_write_requires_override` — invoke
  with `worker_role: "discovery"`, `access_mode: "write"` and no
  justification; assert `validate_patch` rejects with the check-7 message.
  Then invoke the same with `access_mode_override_justification` set; assert
  accepted and that the expanded node dict carries the justification verbatim.

#### 11. `tests/unit/test_node_created_event_payloads.py`

- `test_access_mode_override_justification_round_trips_and_reaches_dispatch_payload`
  — mirror of the chunk-1/2 pattern: `model_validate` round-trip equality plus
  `build_projection` over one `node_created` event, asserting
  `node_payload_view(projection, "worker-1")["access_mode_override_justification"]`
  holds the value.

#### 12. `tests/unit/test_graph_payload_field_allowlists.py`

- `test_node_created_retains_access_mode_override_justification_for_projection_replay`
  — `"access_mode_override_justification" in spec.projection`, and absent from
  `spec.light`, `spec.summary`, `spec.node_detail`.

#### Verification conditions (all must hold)

- Exactly the seven `src/` files and five test files above changed;
  `git status --short` shows nothing else. In particular `graph/compiler.py`,
  `graph_runtime/prompts.py`, `graph_runtime/horizon_templates.py`,
  `graph_runtime/dispatch.py`, `graph/scheduler.py`, and
  `.orchestrator/state/*.jsonl` are unmodified.
- `uv run pytest tests/ -q -n auto --dist worksteal` reports
  **5481 + (new test IDs) passed, 5 skipped** with **zero existing tests
  modified**. Chunk 3's baseline is 5481 passed / 5 skipped. Fact 37 predicts
  zero pre-existing failures; if any appear, they are a genuine regression in
  the `write`/absent path and the derivation is wrong — repair the code, not
  the test.
- `tests/unit/test_graph_commands.py::test_patch_accept_adds_default_worker_write_authority`
  passes byte-identical.
- `PROJECTION_CHECKPOINT_SCHEMA_VERSION` still `15`
  (`graph/projection_codec.py:40`).
- `grep -rn "EXECUTABLE_NODE_KINDS" src/` still returns only its definition and
  the single existing use at `patch_validator.py:185`.
- The five chunk-3 rejection messages are unchanged: `grep -n "worker node
  requires\|worker node access_mode\|worker node acceptance"
  src/orchestrator/graph/patch_validator.py` returns the same five strings.
- Ruff, ruff format, and pyright clean.
- Sanity check by execution (not a committed test): submitting a
  `create_work_region` macro invocation with `worker_role: "discovery"` and
  `access_mode: "read_only"` produces a worker whose materialized authority is
  the `read` claim, and a follow-up `set_resource_claims` write patch against
  that node is rejected as an escalation.

### Verified facts from planning pass 5 (2026-08-27, chunk 5 research)

Established by reading the branch at `9ca1f26c1` (chunks 1-4 landed). Line
numbers are current as of that commit.

38. **The dead-key region has moved to `prompts.py:345-382`
    (`_worker_like_prompt`), and it is nine reads in four blocks**, not one:
    - `:347` — `title = str(node.get("title") or node.get("objective") or
      context.node_id)`. This read of `objective` is **no longer dead** (chunk 1
      declared the field, chunk 3 made it mandatory on patch-created workers).
    - `:351-362` — a seven-key `for key in (...)` loop rendering
      `f"{key}: {_bounded_text(value)}"` for any `str` value:
      `objective`, `corrective_requirement`, `corrective_evidence_required`,
      `expected_gap`, `expected_artifact`, `feature_spec_path`,
      `acceptance_command`.
    - `:364-368` — `expected_outputs`, rendered as bounded JSON when a
      non-empty `list`.
    - `:370-372` — `invariants`, rendered as bounded JSON when a non-empty
      `list`. **No longer dead** (chunk 1 field).
39. **`extra` keys are structurally unreachable on `context.node_payload` in
    production, so "no writer sets it" really does mean "always `None`".**
    `_node_payload` (`dispatch.py:2166-2178`) seeds from
    `node_payload_view(projection, node_id)` — the `dispatch_payload` built at
    `projections.py:791` from the validated `extra="forbid"` model — then
    `setdefault`s any remaining keys from the raw `node_created` event payload
    in `context.graph_events`. Those raw payloads were themselves filtered to
    `EVENT_PAYLOAD_SPECS["node_created"].projection` by `_projection_event`
    (`store.py:6347`) and validated on append. The retention string
    (`payload_registry.py:272`) contains **none** of
    `corrective_requirement`, `corrective_evidence_required`, `expected_gap`,
    `expected_artifact`, `feature_spec_path`, `acceptance_command`,
    `expected_outputs`. Both entry paths are therefore closed: those seven keys
    can never appear on a dispatched node payload.
40. **Exactly one existing test keeps the dead branches alive, and it does so by
    hand-building a raw dict that bypasses every one of those guards.**
    `tests/unit/test_graph_planner_packet.py:653-683`
    (inside `test_prompt_routing_for_planner_worker_and_verifier`) constructs a
    `GraphDispatchContext` directly with `node_payload` carrying `objective`,
    `feature_spec_path`, `corrective_evidence_required`, `expected_artifact`,
    `acceptance_command`, `expected_outputs` and asserts five of them appear in
    the prompt. This is the only test coverage the dead keys have; there is no
    other worker-prompt assertion anywhere except `worker_authority:`
    (`:646`, `:876`).
41. **`_dynamic_feature_prompt_lines` (`prompts.py:444-476`) carries a
    *suppression* dependency on two of the dead node keys.** Its loop head
    (`:454-455`) is `if isinstance(node.get(source_key), str) and
    node[source_key]: continue` over source keys `feature_spec_path`,
    `feature_spec_content`, `acceptance_command` — i.e. "skip the
    `dynamic_feature` fallback because the node already rendered this itself."
    All three are dead as *node* keys by fact 39 (`feature_spec_content` is not
    in the retention string either), so the guard never fires in production and
    exists only to avoid double-rendering the lines chunk 5 deletes. The
    `dynamic_feature`-sourced lines themselves (`dynamic_feature_spec_path`,
    `dynamic_feature_spec_content`, `dynamic_acceptance_command`) are **live**
    — they read the `dynamic_feature` dict, which *is* retained — and are
    covered by `test_graph_planner_packet.py:732-740`. They stay.
42. **`prompts.py` builds the full prompt *string*; no runner renders the
    packet.** `dispatch.py:1145` `prompt = _prompt_for_node(context)` →
    `ExecutionContext.prompt` (`:1150`). Every adapter embeds that string
    verbatim: `codex/common.py:1245`
    (`f"{context.prompt}\n\n## Requirements\n{requirements_text}\n\n…"`),
    `openhands/common.py:394,422`, `claude_cli/agent.py:661`. **No runner file
    needs a chunk-5 edit**; the section lands in the worker prompt for every
    runner the moment `prompts.py` emits it.
43. **Codex already appends bound requirement *text* out-of-band.**
    `codex/common.py:1245` adds a `## Requirements` block from
    `context.requirements`. `context.requirements` is
    `["{id}: {text}", …]` produced by `_requirements_for_node`
    (`dispatch.py:2181`) → `requirements_for_node_view`
    (`projection_queries.py:302`), which resolves `RequirementRecord`s bound to
    `requirement_*` input ports. The **graph prompt itself renders requirements
    for verifiers only** (`_verifier_packet`, `prompts.py:100`); the worker
    prompt renders none today, so a non-codex runner's worker sees no
    requirements at all.
44. **There is no requirement-id → record resolver.** `_hydrated_bound_record`
    (`prompts.py:754`) hydrates *output* records by input-port binding under an
    edge's `prompt_hydration_policy`; it is reached only via `_planner_evidence`
    (planner packet, check packet, prompt-summary `bound_records`) and takes a
    `record_payload`, not an id. Nothing maps a free-form
    `bound_requirement_ids` entry to a record. So `bound_requirement_ids`
    can only be rendered verbatim; the *resolved* requirement text available to
    a worker is `context.requirements` (fact 43).
45. **The prompt summary reports packet *keys*, never packet *values*.**
    `_prompt_summary_for_node` (`prompts.py:216-247`) stores
    `"packet_keys": sorted(packet)` plus `prompt_sections`, `input_ports`,
    `bound_records`, `lease`, and a small allow list of schema/contract blocks
    — it never embeds the packet body. The worker branch of
    `_packet_for_prompt_summary` (`:271-275`) returns
    `{node_id, task_region_id, worker_authority}`, and
    `_prompt_sections_for_context`'s fall-through (`:302`) returns
    `["worker_instruction", "worker_authority"]`. Adding a key to the worker
    packet therefore surfaces it in the summary as *evidence that it was
    hydrated*, with zero contract-content leakage into the durable read model —
    which is exactly what contract-doc §5's last paragraph asks for.
46. **Both `_packet_for_prompt_summary` and `_prompt_sections_for_context`
    reach their worker branch by *fall-through*, so they also serve unknown
    kinds.** `_prompt_for_node` routes `verifier`/`summarizer`/`planner`
    explicitly and sends everything else — including `check` — to
    `_worker_like_prompt` (`:213`). `_packet_for_prompt_summary` has an explicit
    `check` branch (`:257`) but `_prompt_sections_for_context` does too
    (`:300`), so the fall-through in both is "worker or an unrecognized kind".
    The new section must gate on `context.node_kind == "worker"`, matching
    chunk 3's predicate, not on the fall-through.
47. **Two existing allowlist tests pin `node_detail` *negatively* for the
    Slice 1 fields.** `tests/unit/test_graph_payload_field_allowlists.py:126`
    (`test_node_created_retains_access_mode_and_legacy_work_mode_separately`)
    asserts `"access_mode" not in spec.node_detail`, and `:135` asserts the
    same for `access_mode_override_justification`. Adding `access_mode` to
    `node_created`'s `node_detail=` retention would require **editing an
    existing chunk-2 pin** — see the scope ruling below.
48. **`node_detail` retention feeds the durable operator read model, not the
    prompt.** `NODE_DETAIL_PAYLOAD_FIELDS` (`payload_registry.py:447`) is
    consumed only by `store.py:4175 read_run_node_detail`, which backs
    `rebuild_node_detail_summaries` (`:5698`) and the read-model rebuild
    (`:5568`), writing `GraphNodeDetailSummaryModel` /
    `GraphNodeDetailCollectionFactModel` rows served by
    `api/routers/graph.py`. It is the surface contract-doc **requirement #9**
    ("expose each node's objective, work mode, and scope in operator read
    models") targets — a *different* requirement from target-doc criterion 4.
49. **The presentation doc transcribes the dead-key prompt shape verbatim.**
    `docs/dynamic-graph/dynamic-graph-how-it-works-presentation.html:920-931`
    reproduces the worker prompt as `objective:` / `corrective_requirement:` /
    … / `invariants:` lines. It becomes false the moment the deletions land.
50. **Macros can only supply three of the six contract fields.** Chunk 3
    threaded `objective`, `access_mode`, `acceptance` through
    `CreateWorkRegionArgs` (`macros.py:43`), `_worker_node` (`:472`),
    `graph_mcp_tools.py:113,157`, and `codex/common.py:578,661`. `scope`,
    `bound_requirement_ids`, `invariants`, and `prohibited_actions` reach a node
    only through a raw `create_node` op. The chunk-5 section must therefore
    treat all four as genuinely optional at render time; widening the macro arg
    surface is **not** chunk 5's job.

### Chunk 5 — Worker prompt hydration from typed fields (SPECIFIED, not built)

**Goal.** Make the worker prompt carry the node's typed work contract as one
distinct, named section, and delete every dead loose-dict read that pretended
to carry it. Independently verifiable: after this chunk a `kind="worker"`
dispatch renders a `work_contract:` line containing `objective`, `access_mode`,
and `acceptance` (plus `scope` / `bound_requirement_ids` / `bound_requirements`
/ `invariants` / `prohibited_actions` when present); the seven orphan keys have
zero references left in `src/`; and the node's `prompt_summary` records
`work_contract` in both `packet_keys` and `prompt_sections`.

#### Ruling on the nine keys (R4's "declare or delete")

Investigated per fact 38-41 and 50. Verdict per key:

| key | verdict | reason |
|---|---|---|
| `objective` | **keep, relocate** | Real typed field since chunk 1, mandatory since chunk 3. Moves out of the loose loop into `work_contract`. The `title` fallback read at `:347` **stays** — it is now a live read of a declared field and is the only thing keeping a title-less patch-created worker from opening with a bare node id. |
| `invariants` | **keep, relocate** | Real typed field since chunk 1. Moves out of the loose block into `work_contract`. |
| `acceptance_command` | **delete** | No typed field, and it is not the singular of `acceptance: list[str]` — it is a *`dynamic_feature`* sub-key (`compiler.py:1101`, `command_bindings.py:199`, `dispatch.py:2252`) whose live rendering already exists as `dynamic_acceptance_command` (fact 41). Rendering the typed `acceptance` list is the replacement; renaming the dead node-level read would create a second, conflicting spelling of the same concept. |
| `feature_spec_path` | **delete** | Same shape as `acceptance_command`: a live `dynamic_feature` sub-key (`compiler.py:1078`, `graph_driver.py:320`) that is dead as a *node payload* key, already rendered live as `dynamic_feature_spec_path`. |
| `expected_outputs` | **delete** | No typed field and deliberately none: fact 17 / chunk 2 record that target-doc criterion 1 pruned `required_inputs` and `expected_outputs` from contract-doc §1's list. Typed output ports are the graph's existing answer. Do **not** invent the field. |
| `corrective_requirement` | **delete** | No typed field, no writer, no home. |
| `corrective_evidence_required` | **delete** | Same. |
| `expected_gap` | **delete** | Same. |
| `expected_artifact` | **delete** | Same. |

The four "no home" keys were re-checked against everything shipped in chunks
1-4 and against the whole repo before deciding (fact 39): none maps to
`scope`, `bound_requirement_ids`, `prohibited_actions`, or any authority or
record concept. Per R4, they are deleted, not declared. **R4 is resolved by
this section.**

#### Ruling on `node_detail` retention — deliberately OUT OF SCOPE

The chunk-queue row-5 one-liner says "add the fields to `node_detail`
retention". That clause is **superseded by this section** (same precedent as
chunk 2's superseded one-liner); the queue table is left as written for audit
continuity. Reasons, stated rather than silently skipped:

1. `node_detail` feeds the durable **operator read model**, not the prompt
   (fact 48). Target-doc criterion 4 — the whole of chunk 5's mandate — is
   about "a distinct section of the worker packet". Nothing in criterion 4
   reads `node_detail`, and the prompt path reads the `projection` retention
   set that chunks 1-2 already populated.
2. The operator-surface requirement it would serve is contract-doc
   **requirement #9**, which is a nine-bullet read-model/UI item (objective,
   work mode, scope, bound requirements, expected outputs, checks, snapshot
   identities, readiness reasoning, horizon, per-node token/hydration
   summaries). Landing one third of one bullet in chunk 5 buys no verifiable
   operator capability and pre-commits the shape of a slice nobody has scoped.
3. It cannot be done additively: `access_mode` in `node_detail` forces an edit
   to the chunk-2 pin `test_node_created_retains_access_mode_and_legacy_
   work_mode_separately` (fact 47), breaking the loop's standing "zero existing
   tests modified" property for a change with no acceptance criterion behind
   it. Adding the six chunk-1 fields but not `access_mode`, to dodge that,
   would ship an incoherent half of requirement #9's first bullet.

Recorded as **R8** below. `ui/` is untouched by chunk 5 for the same reason.

#### The prompt-summary question — no new summary entry needed

Fact 45: the summary stores `packet_keys`, not packet bodies. Adding
`work_contract` to the worker branch of `_packet_for_prompt_summary` and to
`_prompt_sections_for_context` is the *complete* summary change: an operator
reading `prompt_summary` sees that the work contract was hydrated into the
packet, in the same "what was hydrated / summarized / omitted" vocabulary the
existing `bound_records` entries use, without the contract text being copied
into a durable read model. **Do not** add the contract values to
`_prompt_summary_for_node`'s top-level dict — that is the `node_detail` /
requirement-#9 surface ruled out above.

#### Files touched (exactly these five)

`src/` (one):

1. `src/orchestrator/graph_runtime/prompts.py`

`tests/` (two, one of which is a required modification):

2. `tests/unit/test_graph_planner_packet.py` — new coverage **and** the
   fact-40 repair.
3. `tests/unit/test_graph_dispatch_on_output.py` — prompt-summary coverage
   (this file already owns the `_context(...)` + `RecordingExecutor` helpers
   used by chunk 2's cross-wiring pin).

`docs/` (one):

4. `docs/dynamic-graph/dynamic-graph-how-it-works-presentation.html` — fact 49.

Ledger (one):

5. `docs/dynamic-graph/slice-1-and-5-progress-ledger-2026-08-27.md` — chunk 5
   verified-record entry only.

**Do not touch**: `graph/models.py`, `graph/payload_registry.py` (no new field,
no retention change — see the `node_detail` ruling), `graph/patch_validator.py`,
`graph/macros.py`, `graph/_commands.py`, `graph/compiler.py`,
`graph_runtime/dispatch.py`, `graph_runtime/horizon_templates.py`,
`graph_runtime/graph_mcp_tools.py`, anything under `runners/` (fact 42),
`ui/`, or any `.orchestrator/state/*.jsonl`.

#### 1. `src/orchestrator/graph_runtime/prompts.py`

**(a) New helper `_worker_contract_packet`.** Place it immediately *above*
`_worker_authority_packet` (currently `:385`), mirroring that function's shape
and its "always-present core keys, conditionally-present extras" style:

```python
def _worker_contract_packet(context: GraphDispatchContext) -> dict[str, Any]:
    """Render the node's typed work contract as a bounded packet.

    Mandatory-by-validator fields (``objective``/``access_mode``/``acceptance``)
    are always present so a compiler-seeded worker that predates the contract
    reads as an explicit ``null`` rather than a silent omission.
    """
    node = context.node_payload
    objective = node.get("objective")
    access_mode = node.get("access_mode")
    acceptance = node.get("acceptance")
    packet: dict[str, Any] = {
        "objective": (
            _bounded_text(objective)
            if isinstance(objective, str) and objective.strip()
            else None
        ),
        "access_mode": access_mode if isinstance(access_mode, str) else None,
        "acceptance": (
            [item for item in cast(list[Any], acceptance) if isinstance(item, str)]
            if isinstance(acceptance, list)
            else None
        ),
    }
    scope = node.get("scope")
    if isinstance(scope, str) and scope.strip():
        packet["scope"] = _bounded_text(scope)
    for key in ("bound_requirement_ids", "invariants", "prohibited_actions"):
        value = node.get(key)
        if isinstance(value, list) and value:
            packet[key] = [item for item in cast(list[Any], value) if isinstance(item, str)]
    if context.requirements:
        packet["bound_requirements"] = list(context.requirements)
    return packet
```

Rules the Builder may not vary:

- **Key names mirror the typed field names exactly** — `objective`,
  `access_mode`, `acceptance`, `scope`, `bound_requirement_ids`, `invariants`,
  `prohibited_actions`. No renaming, no `work_mode` spelling (chunk 2's
  downstream naming note).
- **The three chunk-3-mandatory keys are always present**, `None` when unset.
  Compiler-seeded workers are exempt from chunk 3 (fact 9), so `None` is a
  reachable value in production and the explicit `null` is the honest
  rendering — it is also the visible marker for the R5 follow-up
  ("populate the contract from `TaskConfig`").
- **The four optional keys are omitted when absent or empty**, matching
  `_worker_authority_packet`'s conditional-key style. Fact 50: today they can
  arrive only through a raw `create_node` op.
- **`bound_requirements`** is the resolved requirement text already on
  `context.requirements` (fact 43) — the same value `_verifier_packet` renders
  at `:100`. It is included so the packet is self-contained for every runner,
  not just codex, and so chunk 6 can assert contract-doc scenario #4 at the
  `_prompt_for_node` level. The resulting duplication with codex's own
  `## Requirements` block (fact 43) is **accepted**; dropping that block is a
  runner-layer change and is explicitly not chunk 5.
- `bound_requirement_ids` is rendered **verbatim**, not resolved — fact 44:
  no id→record resolver exists, and inventing one is out of scope.

**(b) Rewrite `_worker_like_prompt` (`:345-382`).** Final shape:

```python
def _worker_like_prompt(context: GraphDispatchContext) -> str:
    node = context.node_payload
    title = str(node.get("title") or node.get("objective") or context.node_id)
    task_context = node.get("task_context")
    context_lines = [str(task_context)] if isinstance(task_context, str) and task_context else []

    if context.node_kind == "worker":
        context_lines.append(f"work_contract: {_bounded_json(_worker_contract_packet(context))}")

    authority_packet = _worker_authority_packet(context)
    if authority_packet:
        context_lines.append(f"worker_authority: {_bounded_json(authority_packet)}")

    dynamic_feature = _dynamic_feature_from_context(context)
    if dynamic_feature is not None:
        context_lines.extend(_dynamic_feature_prompt_lines(node, dynamic_feature))

    return _bounded_prompt("\n".join([_bounded_text(title), *context_lines]).strip())
```

i.e. **delete** the whole seven-key loop (`:351-362`), the `expected_outputs`
block (`:364-368`) and the `invariants` block (`:370-372`); **insert** the
`work_contract` line in their place, before `worker_authority`. `title` and
`task_context` lines are unchanged. The `work_contract` line is gated on
`context.node_kind == "worker"` (fact 46) so `check` nodes and any future kind
falling through `_prompt_for_node` are unaffected.

**(c) Delete the orphaned suppression guard in `_dynamic_feature_prompt_lines`
(`:454-455`).** Remove exactly:

```python
        if isinstance(node.get(source_key), str) and node[source_key]:
            continue
```

Justification (fact 41): the guard's only purpose was to stop the
`dynamic_feature` fallback from double-rendering the node-level
`feature_spec_path` / `feature_spec_content` / `acceptance_command` lines that
(b) deletes. All three are dead as node keys, so the guard cannot fire in
production either before or after. Leaving it would keep two of R4's named dead
reads alive and defeat the "zero references" verification condition. The rest
of the function — including its `node` parameter, used for `kind`, `role`, and
`node_id` — is unchanged.

**(d) `_packet_for_prompt_summary` (`:271-275`), fall-through branch.** Add
`work_contract` for worker nodes only:

```python
    packet: dict[str, Any] = {
        "node_id": context.node_id,
        "task_region_id": context.node_payload.get("task_region_id", context.node_id),
        "worker_authority": _worker_authority_packet(context),
    }
    if context.node_kind == "worker":
        packet["work_contract"] = _worker_contract_packet(context)
    return packet
```

**(e) `_prompt_sections_for_context` (`:302`), fall-through branch.** Replace
the bare `return ["worker_instruction", "worker_authority"]` with:

```python
    if context.node_kind == "worker":
        return ["worker_instruction", "work_contract", "worker_authority"]
    return ["worker_instruction", "worker_authority"]
```

Section order must match render order from (b): instruction (title +
task_context), then `work_contract`, then `worker_authority`.

**(f) No new module export.** Do **not** add `_worker_contract_packet` to the
`prompt_for_node = …` alias block at `:1543+`; tests reach it through
`_prompt_for_node` / `_prompt_summary_for_node`, which are already re-exported
via `dispatch.py:251-252`.

#### 2. `tests/unit/test_graph_planner_packet.py`

**(a) Required repair — delete the fact-40 dead-key block.** Inside
`test_prompt_routing_for_planner_worker_and_verifier`, delete the
`dynamic_worker_context` construction and its prompt assertions (currently
`:653-683`) in full. Every one of its five assertions targets a key this chunk
deletes; there is nothing in it to preserve. This is the **only** permitted
existing-test modification in chunk 5, and it is a deletion of coverage for
removed behavior, not a loosened assertion — the Validator should confirm that
distinction explicitly. Leave the `worker_context` block (`:617-651`) and the
`fallback_dynamic_worker_context` block (`:685-740`) byte-identical; the latter
is the live `dynamic_feature` path (fact 41) and must keep passing untouched,
which is also the regression pin proving (c) did not break the fallback.

**(b) New tests** (module-level, next to
`test_prompt_routing_for_planner_worker_and_verifier`; reuse its
`GraphDispatchContext` construction style):

- `test_worker_prompt_renders_the_full_typed_work_contract` — a
  `node_kind="worker"` context whose `node_payload` carries all six typed
  fields plus `access_mode`, and `requirements=["REQ-1: ship it"]`. Assert the
  prompt contains `"work_contract:"`, and that the JSON on that line parses to
  a dict equal to the expected packet — i.e. assert the **whole packet**, not
  substrings, so a field silently dropped from the packet fails. Assert
  `work_contract` appears **before** `worker_authority` in the prompt.
- `test_worker_prompt_work_contract_omits_absent_optional_fields_and_nulls_mandatory_ones`
  — a worker payload with none of the fields. Assert the parsed packet is
  exactly `{"objective": None, "access_mode": None, "acceptance": None}`
  (no `scope`/`bound_requirement_ids`/`invariants`/`prohibited_actions`/
  `bound_requirements` keys). This pins both halves of the always/optional
  rule and the compiler-seeded-worker case.
- `test_worker_prompt_no_longer_renders_retired_loose_node_keys` — the
  deletion pin. Build a worker context whose `node_payload` carries all seven
  retired keys (`corrective_requirement`, `corrective_evidence_required`,
  `expected_gap`, `expected_artifact`, `feature_spec_path`,
  `acceptance_command`, `expected_outputs`) with distinctive sentinel values,
  and assert none of the seven key names **and** none of the seven sentinel
  values appears in the prompt. Because production cannot even produce such a
  payload (fact 39), this test's job is purely to fail loudly if someone
  reintroduces the loose reads.
- `test_check_node_prompt_has_no_work_contract_section` — a
  `node_kind="check"` context routed through `_prompt_for_node`; assert
  `"work_contract:"` is absent (fact 46's gate).
- `test_worker_prompt_work_contract_renders_resolved_bound_requirements` — a
  worker context with `bound_requirement_ids=["REQ-1"]` on the payload and
  `requirements=["REQ-1: the bound requirement text"]` on the context; assert
  the packet carries both `bound_requirement_ids == ["REQ-1"]` and
  `bound_requirements == ["REQ-1: the bound requirement text"]`. This is the
  hook chunk 6's contract-doc scenario #4 asserts against.

#### 3. `tests/unit/test_graph_dispatch_on_output.py`

Add two tests near the existing `test_execution_context_*` group, using the
file's `_context(...)` helper and importing `_prompt_summary_for_node` from
`orchestrator.graph_runtime.dispatch` (already re-exported, `dispatch.py:252`):

- `test_worker_prompt_summary_reports_the_work_contract_section` — worker
  context; assert `summary["packet_keys"]` contains `"work_contract"` and
  `summary["prompt_sections"] == ["worker_instruction", "work_contract",
  "worker_authority"]`.
- `test_worker_prompt_summary_does_not_embed_work_contract_values` — the
  same context with a distinctive `objective` string; assert that string does
  **not** appear anywhere in `json.dumps(summary)`. This pins the fact-45
  boundary: the summary is hydration *evidence*, not a copy of the contract,
  and the durable read model stays free of prompt bodies.

#### 4. `docs/dynamic-graph/dynamic-graph-how-it-works-presentation.html`

Update the "Actual prompt: worker and fixer" slide's `<pre>` block
(currently `:920-931`) so the worker prompt shape it transcribes matches
reality: `{title or objective or node_id}` and `{task_context if present}`
stay; the nine `objective:` … `invariants:` lines are replaced by a single
`work_contract: { … }` JSON block showing the packet's keys; the
`worker_authority` and `dynamic_feature_*` blocks below it are unchanged. Text
only — no styling, no other slide.

#### Verification conditions (all must hold)

- Exactly the five files above changed; `git status --short` shows nothing
  else. In particular `graph/models.py`, `graph/payload_registry.py`,
  `graph/patch_validator.py`, `graph/macros.py`, `graph/compiler.py`,
  `graph_runtime/dispatch.py`, `graph_runtime/horizon_templates.py`,
  `runners/**`, `ui/**`, and `.orchestrator/state/*.jsonl` are unmodified.
- **Zero-reference greps** (each must return no `src/` hit):
  `grep -rn "corrective_requirement\|corrective_evidence_required\|expected_gap\|expected_artifact" src/`
  returns nothing at all;
  `grep -rn "expected_outputs" src/` returns nothing at all;
  `grep -rn "feature_spec_path\|acceptance_command" src/orchestrator/graph_runtime/prompts.py`
  returns nothing (the remaining `compiler.py` / `command_bindings.py` /
  `graph_driver.py` / `dispatch.py:2252` hits are the live `dynamic_feature`
  sub-key reads and must be left alone).
- `grep -n "objective\|invariants" src/orchestrator/graph_runtime/prompts.py`
  returns exactly three hits: the `title` fallback, the example patch at
  `:969`, and the new `_worker_contract_packet` body (plus its `invariants`
  loop entry).
- `uv run pytest tests/ -q -n auto --dist worksteal` reports **5504 + (new
  test IDs) passed, 5 skipped**. Chunk 4's baseline is 5504 passed / 5 skipped.
  Exactly **one** existing test is modified —
  `test_prompt_routing_for_planner_worker_and_verifier`, by deletion of the
  dead-key block (2(a)) — and nothing else. Any *other* pre-existing failure is
  a genuine regression: repair the code, not the test.
- `tests/unit/test_graph_planner_packet.py`'s
  `fallback_dynamic_worker_prompt` assertions
  (`dynamic_feature_spec_path:`, `dynamic_feature_spec_content:`,
  `dynamic_acceptance_command:`, `dynamic_worker_instruction:`, and the
  `dynamic_hidden_oracle_command:` / `validation-strengthened` negatives) pass
  byte-identical — the pin that deleting the suppression guard (1(c)) did not
  change the live `dynamic_feature` path.
- `tests/integration/test_graph_fr09_acceptance.py` passes unchanged (it
  asserts exact `packet_keys` / `prompt_sections` for the **summarizer** and
  **gap planner** only, so the worker-branch additions must not touch it).
- `PROJECTION_CHECKPOINT_SCHEMA_VERSION` still `15`
  (`graph/projection_codec.py:40`) — chunk 5 declares no field and changes no
  retention set.
- `EVENT_PAYLOAD_SPECS["node_created"].node_detail` is byte-identical to its
  chunk-4 value, and
  `tests/unit/test_graph_payload_field_allowlists.py` is unmodified.
- Ruff, ruff format, and pyright clean.
- Sanity check by execution (not a committed test): dispatching a worker whose
  payload carries only `objective`/`access_mode`/`acceptance` produces a prompt
  whose `work_contract:` line parses as JSON with exactly those three keys, and
  the same node's `prompt_summary["prompt_sections"]` is
  `["worker_instruction", "work_contract", "worker_authority"]`.

### Verified facts from planning pass 6 (2026-08-27, chunk 6 research)

Established by reading **and executing against** the branch at `e0177275f`
(chunks 1-5 landed, working tree clean). Facts 54-56 and 58 were produced by
running throwaway scratchpad probes, not by inspection.

51. **Contract-doc scenario #1's substance is already covered by chunk 4, at
    unit level, in six places.** `tests/unit/test_graph_commands.py`:
    `test_patch_accept_grants_read_authority_to_read_only_worker` (`:4431`),
    `test_patch_accept_grants_read_authority_when_read_only_worker_declares_empty_claims`
    (`:4448`), `test_read_only_worker_cannot_be_escalated_to_write_authority`
    (`:4470`), `test_read_only_worker_with_external_claim_cannot_be_escalated_to_write`
    (`:4502` — the live-bypass regression pin from the failed chunk-4 build).
    `tests/unit/test_patch_validator.py`:
    `test_create_node_rejects_discovery_worker_declaring_write_access_mode`
    (`:1756`), `test_create_node_rejects_read_only_worker_with_escalated_resource_claim`
    (`:1833`, ×3 modes), plus the macro-path pair in
    `tests/unit/test_graph_macros.py` (`:421`, `:457`). Chunk 6 must **not**
    re-assert any of these; they are solid and specific.
52. **Contract-doc scenario #4's substance is already covered by chunk 5 — but
    only against hand-built payloads.**
    `tests/unit/test_graph_planner_packet.py:855` asserts the whole
    `work_contract` packet and `:978`
    (`test_worker_prompt_work_contract_renders_resolved_bound_requirements`)
    asserts `bound_requirement_ids` + `bound_requirements` together. Both build
    a `GraphDispatchContext` literal whose `node_payload` and `requirements` are
    written by hand.
53. **No test anywhere in the repo crosses the admission → projection → prompt
    seam.** `grep -rln "prompt_for_node" tests/` returns exactly one file,
    `tests/unit/test_graph_planner_packet.py`, and
    `grep -c "build_projection\|apply_command\|submit_patch"` on that file
    returns **0**. Every prompt in the suite is rendered from a
    literal-constructed context; every admission test stops at the emitted
    event or the projection. The two halves of each scenario are therefore
    joined only by the reader, never by an executable assertion. This — not
    duplication of 51/52 — is chunk 6's entire justification.
54. **The seam is real, closable, and closes cheaply: verified end to end by
    execution.** A probe submitted a `role="discovery"`,
    `access_mode="read_only"` worker through `submit_patch`, rebuilt the
    projection with `build_projection`, hydrated the payload with
    `_node_payload(events, node_id, projection=projection)`
    (`dispatch.py:2166`, the production seeder), and rendered
    `_prompt_for_node`. Observed output, verbatim:
    - `work_contract:` line —
      `{"acceptance": ["root cause identified and documented"], "access_mode": "read_only", "bound_requirement_ids": ["REQ-1"], "bound_requirements": ["REQ-1: report the root cause"], "invariants": ["never modify src/"], "objective": "Investigate the failure and report findings.", "prohibited_actions": ["git commit"], "scope": "docs/ and tests/ only"}`
    - `worker_authority:` line — `"resource_claims": [{"mode": "read", "paths": ["."], "scope": "repo"}]`
    The second line is the load-bearing new fact: **the `read` claim chunk 4
    derives is what the agent is actually told it holds**, and *nothing in the
    suite asserts this today*. Chunk 4's own decision record names this as the
    third of the three properties option (a′) buys (chunk 4 §"What (a′)
    actually buys", property 3), and it is the only one of the three with no
    test behind it — properties 1 and 2 are covered by pre-existing scheduler
    tests and by `test_read_only_worker_cannot_be_escalated_to_write_authority`
    respectively.
55. **A real requirement binding is reproducible in a unit test, and needs three
    non-obvious details.** Verified by probe; without all three,
    `_requirements_for_node` returns `[]` and a scenario-#4 test would silently
    assert nothing:
    - the `create_edge` op is **flat**, not nested under an `edge` key:
      `{"op": "create_edge", "edge_id": …, "from_node_id": …, "from_port": …,
      "to_node_id": …, "to_port": …, "required": True,
      "accepted_record_selector": {…}}`. A nested `"edge": {…}` is rejected with
      `malformed patch [malformed_patch]: payload [extra_forbidden] at
      ops[1].edge`.
    - the selector's schema must be **`"Requirement"`**, not `"RequirementRecord"`
      — the `requirement` output port declares `schemas=("Requirement",)`
      (`contracts.py:611`), and `"RequirementRecord"` is rejected with
      `edge edge-req-1 schema selector is incompatible with source output port`
      (`contracts.py:398`). The *accepted record* still carries
      `"schema": "RequirementRecord"`.
    - `edge_created` alone does **not** bind. `requirements_for_node_view`
      (`projection_queries.py:302`) reads `topology.input_bindings`, which is
      populated only by `_reduce_slice_a_binding` (`projections.py:1162`) from
      an **`input_bound`** event. The test must append one explicitly
      (`InputBoundPayload`, `models.py:2784`: `edge_id`, `to_node_id`,
      `to_port`, `record_ids` (min 1), `bound_at_position`). Ordering does not
      rescue it: accepting the record after the edge still yields `[]`.
56. **`tests/unit/graph_test_utils.py` is sufficient; no cross-test-module
    import is needed.** It already exports `event(type, payload, *, position)`
    (whose `canonical_event_payload` has an `input_bound` branch, `:233`),
    `patch_command_context(events, *, proposed_by_node_id, actor_role)`, and
    `apply_command(...)`. The whole probe was re-run against these helpers plus
    `initial_projection`/`reduce_event` and produced byte-identical output. Do
    **not** import `_apply` / `_discovery_read_only_worker_node` from
    `tests/unit/test_graph_commands.py`; that file's helpers are private to it.
57. **Nothing in chunks 1-5 touches contract-doc scenario #3, and the machinery
    it needs does not exist in `src/` at all.** `grep -rn
    "plan_amendment\|plan_verification\|progressive_horizon" src/` returns
    **zero hits**. `grep -rln horizon src/` returns exactly three files —
    `graph_runtime/horizon_templates.py`, `graph_runtime/prompts.py`, and the
    `graph_runtime/__init__.py` re-export — i.e. the horizon exists only as
    *advisory prompt templates* handed to a planner, with no staging,
    amendment, or region-count enforcement anywhere. Slice 1's six chunks are
    all node-local (payload fields, per-node validation, per-node authority,
    per-node prompt); scenario #3 is a property of graph *shape* across
    regions.
58. **`_bounded_json` sorts keys** (`prompts.py:71`,
    `json.dumps(value, sort_keys=True)`). Chunk 6's assertions must parse the
    line and compare dicts, never compare rendered substrings or assume field
    order. (Chunk 5's landed tests already follow this via the
    `_work_contract_json` helper at `test_graph_planner_packet.py:848`.)

### Chunk 6 — Contract-doc regression scenarios (SPECIFIED, not built)

**Goal.** Close criterion 5 by joining the two halves of scenarios #1 and #4 in
executable form: one test per scenario that starts from a real `submit_patch`
admission and ends at the rendered worker prompt. Independently verifiable:
after this chunk, a rename or retention drop anywhere on the
`create_node` → `_ensure_default_node_authority` → `node_created` →
`build_projection` → `node_payload_view` → `_node_payload` → `_prompt_for_node`
chain fails a test, which is not true today.

#### Scope ruling — two tests, no more, and explicitly *not* a re-assertion

Facts 51 and 52 say plainly that the *substance* of both scenarios is already
pinned. The mind-the-gap cost discipline says do not restate solid coverage in
a bigger fixture to make a chunk feel substantial. So chunk 6 is deliberately
small, and each of its two tests must earn its place by asserting something no
existing test asserts:

- **Scenario #1's new assurance** is fact 54's second bullet: the `read` claim
  reaches the agent's `worker_authority` packet, and `write` never appears in
  the prompt. Chunk 4 proved the claim is *materialized on the event*; nothing
  proves it is *communicated*. Plus the end-to-end joining of admission and
  escalation refusal against the same projection.
- **Scenario #4's new assurance** is fact 53: that the six typed contract fields
  survive `projection=` retention and reach the prompt *from a real admitted
  patch*, and that `bound_requirements` is resolved from a **real** requirement
  record bound through a **real** edge (fact 55) rather than injected as a
  literal `requirements=[...]` list.

Anything beyond those two — re-testing the escalation message on its own,
re-testing the validator messages, re-testing packet key presence — is
duplication and must not be added.

#### Scenario #3 — DEFERRED, with reason

Criterion 5 permits deferral of scenario #3 ("a staged feature contract cannot
be represented by one generic worker unless an accepted plan amendment
explicitly changes the stages") with a recorded reason. **Deferred.** The
reason is structural, not budgetary:

1. **It is not a node-level property, and Slice 1 is entirely node-level.**
   Every chunk 1-5 artefact is scoped to one node: six payload fields, a
   per-node `create_node` validator check, per-node authority derivation, one
   node's prompt packet. Scenario #3 is a property of the *shape of the graph
   across regions* — "how many worker nodes represent this staged contract, and
   did an accepted amendment authorise collapsing them". There is no node whose
   admission could reject it.
2. **The machinery it needs does not exist** (fact 57): zero references to
   plan amendments or plan verification in `src/`, and the horizon exists only
   as advisory prompt templates with no staging or region-count enforcement.
   Building it means inventing a staged-plan record, an amendment record, an
   acceptance path for amendments, and a graph-shape check that reads all
   three.
3. **It is already assigned elsewhere.** The reliability contract puts
   progressive-horizon enforcement in **Slice 3**, which the target doc
   (`slice-1-and-5-target-2026-08-27.md`, "Non-goals for this pass") explicitly
   excludes from this pass alongside Slices 2, 4, and 6. Implementing it here
   would be scope theft from an unscoped slice, not a stretch goal.

Recorded as **R9** below so it is picked up deliberately when Slice 3 is
scoped, not rediscovered.

#### Files touched (exactly two)

1. `tests/unit/test_plan_contract_regression_scenarios.py` — **new file**.
2. `docs/dynamic-graph/slice-1-and-5-progress-ledger-2026-08-27.md` — the
   chunk-6 verified-record entry and the completion-summary status flip only.

A new file is correct rather than appending to
`tests/unit/test_graph_commands.py` or `test_graph_planner_packet.py`: the
tests deliberately span both modules' subjects (kernel admission *and* prompt
rendering), and a file named for the contract doc's scenario list is where
Slice 6's dogfood-regression work will later add scenarios #2 and #5-#10. Name
each test after its scenario number so the mapping to
`reliable-plan-execution-contract.md`'s "Required regression scenarios" list is
mechanical.

**Do not touch**: anything under `src/` (chunk 6 adds **zero** production
code — if a test fails, that is a genuine regression in chunks 1-5 and must be
reported, not patched around), any existing test file, `ui/`, or any
`.orchestrator/state/*.jsonl`.

#### 1. `tests/unit/test_plan_contract_regression_scenarios.py`

Module docstring must name the source: these are the numbered scenarios from
`docs/dynamic-graph/reliable-plan-execution-contract.md` §"Required regression
scenarios", and each test's docstring quotes its scenario verbatim.

**Imports** (fact 56 — `graph_test_utils` only, no cross-test-module import):

```python
from orchestrator.graph import (
    FakeClock,
    SequentialIdGenerator,
    build_projection,
    initial_projection,
    reduce_event,
)
from orchestrator.graph_runtime.dispatch import (
    GraphDispatchContext,
    _node_payload,
    _prompt_for_node,
    _requirements_for_node,
)
from tests.unit.graph_test_utils import apply_command, event, patch_command_context
```

**Module-level helpers** (four, all private):

- `_DISCOVERY_WORKER: dict[str, Any]` — the node dict, carrying all six chunk-1
  fields plus `access_mode`: `node_id="worker-1"`, `kind="worker"`,
  `role="discovery"`, `state="planned"`, `task_region_id="region-1"`,
  `candidate_id="candidate-1"`, `attempt_number=1`, a non-empty `objective`,
  `access_mode="read_only"`, a one-entry `acceptance`, a `scope`,
  `bound_requirement_ids=["REQ-1"]`, a one-entry `invariants`, a one-entry
  `prohibited_actions`, and
  `inputs=[{"port": "requirement_1", "schema": "RequirementRecord"}]`. Copy it
  (`dict(...)`) at each use site; never mutate the module constant.
- `_project(events)` — `initial_projection()` folded with `reduce_event`.
- `_submit(events, patch_id, ops)` — `apply_command(_project(events), events,
  "submit_patch", {"patch_id": patch_id, "base_graph_position":
  max((e.position for e in events), default=-1), "ops": ops},
  patch_command_context(events, proposed_by_node_id="planner-1",
  actor_role="planner"), FakeClock(), SequentialIdGenerator())`.
- `_admitted_discovery_graph()` — returns the full event list. Steps, exactly
  as verified by probe (fact 55):
  1. seed `[event("node_created", {"node_id": "requirement-REQ-1", "kind":
     "requirement", "state": "completed"}, position=0)]`;
  2. `_submit(...)` a patch whose ops are the `create_node` for
     `_DISCOVERY_WORKER` **and** the flat `create_edge`
     (`edge_id="edge-req-1"`, `from_node_id="requirement-REQ-1"`,
     `from_port="requirement"`, `to_node_id="worker-1"`,
     `to_port="requirement_1"`, `required=True`,
     `accepted_record_selector={"record_type": "requirement_record",
     "schema": "Requirement"}`);
  3. **assert** the emitted types are
     `["graph_patch_accepted", "node_created", "edge_created"]` — this guards
     the helper itself, so a future validator change that starts rejecting the
     fixture fails loudly instead of silently emptying the assertions;
  4. append an `output_record_accepted` for `requirement-REQ-1`
     (`record_kind="graph_record"`, `record_type="requirement_record"`,
     `producer_node_id="requirement-REQ-1"`, `port="requirement"`,
     `schema="RequirementRecord"`,
     `value={"id": "REQ-1", "text": "report the root cause",
     "source": "routine"}`);
  5. append the `input_bound` event
     (`edge_id="edge-req-1"`, `to_node_id="worker-1"`,
     `to_port="requirement_1"`, `record_ids=["requirement-REQ-1"]`,
     `bound_at_position=<its own position>`).
- `_dispatch_context(events)` — `projection = build_projection(events)`;
  `payload = _node_payload(events, "worker-1", projection=projection)`; build a
  `GraphDispatchContext` with `node_kind`/`node_role` **read off the payload**
  (not hardcoded — that is part of what the chain must deliver),
  `node_payload=payload`,
  `requirements=_requirements_for_node(projection, "worker-1", events)`,
  `graph_projection=projection`, `graph_events=list(events)`, and literal
  `worktree_path`/`lease_id`/`lease_generation`/`execution_id`/
  `base_snapshot_id`/`dispatch_event_id` (those are run-setup state, not graph
  facts — chunk 5's landed tests use literals for them too).
- `_prompt_line_json(prompt, prefix)` — split the prompt into lines, find the
  one starting `f"{prefix}: "`, `json.loads` the remainder, `raise
  AssertionError(f"{prefix} line not found")` otherwise. Fact 58: parse, never
  substring-match.

**Test 1 — `test_scenario_1_read_only_discovery_worker_cannot_obtain_write_authority`.**
Docstring quotes scenario #1. Body:

1. `events = _admitted_discovery_graph()`.
2. `authority = _prompt_line_json(_prompt_for_node(_dispatch_context(events)),
   "worker_authority")`; assert
   `authority["resource_claims"] == [{"mode": "read", "scope": "repo",
   "paths": ["."]}]`. **This is the assertion no existing test makes.**
3. Assert the *rendered prompt string* contains no write grant:
   `'"mode": "write"' not in prompt`. Cheap, and it is the property an agent
   reading the prompt actually depends on.
4. Assert the `work_contract` line's `access_mode` is `"read_only"` — i.e. the
   contract the agent is shown agrees with the authority it is granted. (The
   two come from different code paths, `_worker_contract_packet` and
   `_worker_authority_packet`, so agreement is a real assertion.)
5. Submit a `set_resource_claims` op for
   `{"mode": "write", "scope": "repo", "paths": ["."]}` against **the same
   event list**; assert the emitted types are `["graph_patch_rejected"]` and
   the reason is `"resource claim escalation for worker-1: write"`.

Step 5 does overlap `test_read_only_worker_cannot_be_escalated_to_write_authority`
by design, and that is the one permitted overlap: it is what makes the test the
*scenario* rather than three disconnected properties. Do not also re-test the
admission refusal of `access_mode="write"` — `test_create_node_rejects_discovery_worker_declaring_write_access_mode`
owns that and adding it here buys nothing.

**Test 2 — `test_scenario_4_worker_prompt_carries_its_bound_requirement_and_objective`.**
Docstring quotes scenario #4. Body:

1. `events = _admitted_discovery_graph()`; `context = _dispatch_context(events)`.
2. Assert `context.requirements == ["REQ-1: report the root cause"]` — proves
   the binding chain actually resolved and that the next assertion is not
   vacuous (fact 55's failure mode).
3. `contract = _prompt_line_json(_prompt_for_node(context), "work_contract")`;
   assert `contract ==` the **whole expected packet dict**, all eight keys:
   `objective`, `access_mode`, `acceptance`, `scope`, `bound_requirement_ids`,
   `invariants`, `prohibited_actions`, `bound_requirements`. Whole-dict
   equality, not `in` checks — a field dropped from `projection=` retention or
   renamed anywhere on the chain must fail this.
4. Assert `contract["bound_requirement_ids"] == ["REQ-1"]` **and**
   `contract["bound_requirements"] == ["REQ-1: report the root cause"]` as a
   named, separately-failing assertion even though step 3 covers it — this is
   the literal scenario-#4 sentence ("bound requirement … records") and a
   reader should not have to diff a dict to see it.

Expected packet, verified by execution against `e0177275f` — the Builder should
reproduce it from its own fixture values rather than copying blind, but it must
match this shape:

```json
{"acceptance": ["root cause identified and documented"],
 "access_mode": "read_only",
 "bound_requirement_ids": ["REQ-1"],
 "bound_requirements": ["REQ-1: report the root cause"],
 "invariants": ["never modify src/"],
 "objective": "Investigate the failure and report findings.",
 "prohibited_actions": ["git commit"],
 "scope": "docs/ and tests/ only"}
```

#### Verification conditions (all must hold)

- Exactly the two files above changed; `git status --short` shows nothing else.
  In particular **`src/` is entirely unmodified** — `git diff --stat src/` is
  empty. Chunk 6 is a pure-test chunk; any production edit means the spec was
  misread.
- `uv run pytest tests/ -q -n auto --dist worksteal` reports **5513 passed, 5
  skipped** — chunk 5's 5511 plus exactly 2 new test IDs, zero regressions,
  **zero existing tests modified**.
- Both new tests fail for the right reason if the chain is broken. The Builder
  must demonstrate this by temporary local experiment (reverted, not
  committed, and **not** via any git command that discards changes — edit and
  re-edit by hand): removing `authority` from the `node_created`
  `projection=` retention string breaks test 1, and removing
  `bound_requirement_ids` from it breaks test 2. Report both observed failure
  messages. A test that still passes with the chain cut is worthless and this
  is the only way to know.
- `PROJECTION_CHECKPOINT_SCHEMA_VERSION` still `15`.
- Ruff, ruff format, and pyright clean.

#### Audit of all ten contract-doc regression scenarios (informational)

Requested for the Slice 1 close-out; **not** a work mandate. Verdicts are
against branch `e0177275f` plus this chunk.

| # | Scenario (abbreviated) | Verdict after Slice 1 |
|---|---|---|
| 1 | analysis-only discovery node cannot obtain repo write authority | **Covered.** Chunk 4 (6 unit pins, fact 51) + chunk 6 test 1 (end-to-end, incl. the prompt-advertises-`read` property). |
| 2 | implementation not ready without accepted discovery + plan verification records | **Out of scope — Slice 3.** Generic readiness (`inputs_bound` preconditions, input bindings) is pre-existing and tested, but the *semantic* requirement — a typed discovery→implementation edge and an accepted plan-verification record — has no representation: `grep plan_verification src/` returns zero (fact 57). Real gap, correctly assigned elsewhere. |
| 3 | staged contract cannot collapse to one generic worker without an accepted amendment | **Deferred, reason recorded** (R9 / chunk 6 §"Scenario #3"). Graph-shape property; needs plan-amendment + progressive-horizon machinery that does not exist (fact 57). Slice 3. |
| 4 | worker prompts contain bound requirement and evidence records | **Covered for requirements; partial for evidence.** Chunk 5 + chunk 6 test 2 fully cover the *requirement* half end to end. The *evidence-record* half is not built: `_worker_like_prompt` hydrates no bound output records — `_hydrated_bound_record` (`prompts.py:754`) is reached only from `_planner_evidence` (planner and check packets). Flagged as **R10**. |
| 5 | corrective prompts contain the exact failed grades and check results | **Real gap, newly sharpened by chunk 5.** Corrective workers are `kind="worker"` and now get a `work_contract`, but nothing hydrates the failure record, grades, or check results into their packet. Chunk 5 *deleted* the `corrective_requirement` / `corrective_evidence_required` node keys — correctly, since they were never written by anything (fact 39) — so no capability was lost, but the placeholders that hinted at the intent are gone. Flagged as **R11** so the intent survives the deletion. |
| 6 | generic candidate/file-state cannot substitute for a schema-required artifact | **Out of scope — Slice 2** (semantic artifact envelope; a named non-goal of this pass). Partial pre-existing machinery: edge `accepted_record_selector` schema compatibility is enforced (`contracts.py:398`, exercised incidentally by chunk 6's own fixture, fact 55). The full scenario needs typed artifact schemas per consumer. |
| 7 | failed candidates do not become the implicit base for later batches | **Out of scope — Slice 4** (candidate/accepted snapshot isolation; a named non-goal). Adjacent and relevant: chunk 4's R6 records that the graph worktree is shared across sequential executions, which is the same shared-dirty-state failure mode. |
| 8 | final completion cannot occur with a missing batch verification or final audit | **Pre-existing, not a Slice 1 concern.** Final-check/completion-decision machinery predates this loop (`completion_decision_passed`, final-invariant region, `tests/unit/test_final_review_contracts.py`), and the July-2026 final-check poison-topology incident already produced pins. Not re-verified against this scenario's exact wording in this pass — stated as unaudited rather than green. |
| 9 | missing callback ends with a healthy retry or a conclusively revoked lease + typed recovery state | **Next loop — Slice 5**, criterion 4 of the same target doc. Untouched by Slice 1. |
| 10 | operator read model makes disconnected or semantically incomplete regions visible | **Deliberately deferred — R8.** Chunk 5 ruled `node_detail` retention out of scope with reasons; this is contract-doc requirement #9's surface. |

Net: Slice 1 closes #1 and #4 (requirement half), sharpens #5 into a named
follow-up, and leaves #2/#3/#6/#7 to their assigned later slices, #9 to the
Slice 5 loop, and #10 to R8.

### Open risks carried into later chunks

- **R1 (chunk 2, high) — RESOLVED by design, 2026-08-27 planning pass 2.**
  The risk was real and confirmed sharper than stated: replay re-validates
  every historical `node_created` through the strict model (fact 12), so a
  retype breaks live data, while `tests/unit/test_fixture_corpus.py` and the
  graph YAML fixtures contain **no** `work_mode` at all (fact 14) and so would
  never have caught it. Retired by *not migrating*: chunk 2 adds
  `access_mode: Literal["read_only","write"] | None` and leaves `work_mode`
  untouched, so there is no persisted-event migration, no compatibility shim,
  and no `PROJECTION_CHECKPOINT_SCHEMA_VERSION` bump. Residual risk is naming
  only, mitigated by the two disambiguating comments in `models.py`, the
  cross-wiring pin in `tests/unit/test_graph_dispatch_on_output.py`, and the
  "Downstream naming note" in the chunk 2 section. Later chunks inherit **no**
  replay-compatibility obligation for this field.
- **R2 (chunk 3, medium) — RESOLVED by decision, 2026-08-27 planning pass 3.**
  The predicate is **`kind == "worker"`, role-independent**, not
  `EXECUTABLE_NODE_KINDS`. Justified by fact 26 (`verifier` carries its
  obligation as `rubric`, `check` is a deterministic command with its own
  existing mandatory-command validation, `planner` emits graph patches and has
  no acceptance concept) and by the failed run's offending node being a
  *discovery* worker, which rules out narrowing by `role`. Corrective workers
  created by a gap planner are in scope; `create_revision_attempt` worker
  nodes and compiler-seeded workers are explicitly out of scope (R5, fact 9).
  Pinned by `test_worker_contract_is_not_required_of_non_worker_kinds` and by
  a `grep` verification condition asserting the new check does not reference
  `EXECUTABLE_NODE_KINDS`.
- **R5 (post-chunk-3, medium) — NEW.** Two worker-creation paths remain
  contract-free after chunk 3: `create_revision_attempt`'s `worker_node`
  (fact 22 — it bypasses `validate_node_payload` entirely, not just the new
  check) and `seed_compiled_events` / `graph/compiler.py:519` (fact 9). The
  first is a genuine planner-reachable hole and should be closed once the
  revision-attempt producers can supply the fields; the second needs the
  compiler to populate the contract from `TaskConfig` and is the natural
  companion to chunk 5's prompt work. Chunk 3 pins the boundary deliberately
  with `test_create_revision_attempt_worker_node_is_not_contract_checked` so
  closing it is an intentional edit rather than a silent widening.
- **R3 (chunk 4, medium) — RESOLVED by decision, 2026-08-27 planning pass 4.**
  The choice is **refusing to grant the write claim**, at admission, plus
  deriving the claim from `access_mode` so the refusal is materialized and not
  merely validated (option (a′) in the chunk 4 section). The file-state
  boundary was ruled out on read, not on assumption: it is captured only after
  the agent finishes (fact 27), classified against a policy explicitly bound to
  the verified routine snapshot with no per-node input (fact 28), and
  `runner_boundary_mismatch` is a staged-vs-final drift detector that never
  reads node authority (fact 29). Because the graph worktree is shared across
  sequential executions, a post-hoc verdict would let a discovery worker's
  writes reach the next node's baseline first — the failed dogfood run's exact
  symptom. Claim refusal is not a filesystem sandbox and the ledger does not
  claim it is (fact 30: none exists per-node, and building one is a
  runner-layer slice); what it *is* is two kernel-enforced properties — a
  `read` claim's scheduler conflict semantics, and `set_resource_claims`
  escalation refusal making rank-0 → rank-1 impossible for the node's whole
  life (fact 31). Together with the admission gate, a discovery worker cannot
  be created with write authority, cannot be granted it by default, and cannot
  acquire it later. Pinned by
  `test_read_only_worker_cannot_be_escalated_to_write_authority` and
  `test_patch_accept_grants_read_authority_to_read_only_worker`.
- **R6 (post-chunk-4, medium) — NEW.** Chunk 4 deliberately ships no
  boundary-time detector, so a `read_only` worker that writes anyway — because
  the runner sandbox is global (fact 30) and claims are not a filesystem
  sandbox (fact 7) — is not currently detected, only un-authorized. The
  follow-up, if wanted, is an assertion in
  `graph_runtime/dispatch.py::_submit_callback` (around `:1215`): when
  `context.node_payload.get("access_mode") == "read_only"` and the captured
  boundary's classification is non-empty, take the existing
  `boundary.rejection_record is not None` path with a distinguishable reason.
  It was rejected for chunk 4 because the classification policy is run-scoped
  by design (fact 28) and a per-node rule is a cache-authority change, and
  because it lands on the hot callback path and would need integration
  coverage. Recorded here so a later chunk adds it on purpose rather than
  rediscovering it.
- **R7 (post-chunk-4, low) — NEW, extends R5.** The discovery/write admission
  gate lives in the `create_node` branch only, so a `create_revision_attempt`
  whose `worker_node` declares `role="discovery"` with `access_mode="write"` is
  not gated — the same boundary R5 already records for the chunk-3 contract
  check. Severity is lower than R5's because the *authority derivation* (file 4)
  does reach that path: `create_revision_attempt` flows through
  `_node_payload_for_op` → `_ensure_default_node_authority` (fact 32), so a
  revision worker declaring `read_only` still receives the `read` claim.
  Only the role policy is unenforced there. Pinned by
  `test_create_revision_attempt_discovery_worker_is_not_access_mode_gated`.
  `graph/compiler.py` is *not* part of this risk: it never creates a discovery
  worker (fact 33).
- **R4 (chunk 5, low) — RESOLVED by decision, 2026-08-27 planning pass 5.**
  The answer is **delete, for all seven** — the six R4 named plus
  `corrective_evidence_required`, which R4's own list omitted (fact 38 counts
  the region as nine reads, of which `objective` and `invariants` are now real
  typed fields and are relocated into the new `work_contract` packet rather
  than deleted). Each of the seven was re-checked against everything chunks 1-4
  shipped and against the whole repo before the ruling, per the per-key table
  in the chunk 5 section: `corrective_requirement`,
  `corrective_evidence_required`, `expected_gap`, and `expected_artifact` have
  no corresponding concept anywhere; `expected_outputs` is *deliberately*
  absent (fact 17 — target-doc criterion 1 pruned it from contract-doc §1, and
  typed output ports already carry it); `feature_spec_path` and
  `acceptance_command` are live `dynamic_feature` **sub-keys** whose node-level
  reads are dead and whose live rendering already exists as
  `dynamic_feature_spec_path` / `dynamic_acceptance_command`. No new typed
  field is invented for any of them. The ruling extends one step past R4's
  citation: `_dynamic_feature_prompt_lines`'s suppression guard
  (`prompts.py:454-455`) exists only to avoid double-rendering two of the
  deleted node keys and is deleted with them (fact 41), so no dead branch is
  left behind. Pinned by
  `test_worker_prompt_no_longer_renders_retired_loose_node_keys` (all seven key
  names *and* their values absent from the prompt) and by a zero-reference
  `grep` verification condition over `src/`.
- **R8 (post-chunk-5, low) — NEW.** Chunk 5 deliberately does **not** add the
  typed contract fields to `node_created`'s `node_detail=` retention, so the
  durable operator read model still cannot show a node's objective, access
  mode, or scope. That surface is contract-doc **requirement #9** ("expose plan
  semantics in operator read models"), a nine-bullet item outside the target
  doc's Slice 1 criteria, and landing one third of its first bullet here would
  pre-commit the shape of an unscoped slice while forcing an edit to the
  chunk-2 pin `test_node_created_retains_access_mode_and_legacy_work_mode_
  separately` (fact 47) — breaking the loop's standing "zero existing tests
  modified" property for no verifiable capability. When requirement #9 is
  scoped, the change is: add the six chunk-1 fields **and** `access_mode` to
  the `node_detail=` string (`payload_registry.py:275`), flip the two negative
  assertions in `tests/unit/test_graph_payload_field_allowlists.py:126,135`,
  and surface them through `api/routers/graph.py`'s node-detail response. The
  prompt path is unaffected either way — it reads the `projection` retention
  set, which chunks 1-2 already populated.
- **R9 (chunk 6, medium) — NEW. Contract-doc scenario #3 deferred.** "A staged
  feature contract cannot be represented by one generic worker unless an
  accepted plan amendment explicitly changes the stages" is not implementable
  on Slice 1's foundations: it is a property of graph *shape across regions*,
  whereas every Slice 1 artefact is node-local, and the machinery it needs —
  staged-plan records, plan amendments, an acceptance path for them, and a
  region-shape check reading all three — does not exist anywhere in `src/`
  (fact 57: zero hits for `plan_amendment` / `plan_verification` /
  `progressive_horizon`; the horizon is advisory prompt templates only). It
  belongs to **Slice 3** (progressive horizon enforcement), a named non-goal of
  this pass. When Slice 3 is scoped, this scenario is its acceptance test.
  Target-doc criterion 5 explicitly permits this deferral with a recorded
  reason; this is that record.
- **R10 (post-chunk-6, low) — NEW. Scenario #4's evidence-record half is
  unbuilt.** The scenario reads "worker prompts contain their bound requirement
  **and evidence** records". Chunks 5-6 deliver the requirement half end to end.
  No bound *output* record is hydrated into a worker packet:
  `_hydrated_bound_record` (`prompts.py:754`) is reached only via
  `_planner_evidence`, which serves the planner and check packets. A worker
  consuming an upstream candidate or verification report therefore sees the
  binding in the graph but not the record content in its prompt. Closing it is
  a `_worker_like_prompt` change of roughly chunk-5 size, plus a decision about
  which `prompt_hydration_policy` a worker input port should default to.
- **R11 (post-chunk-6, medium) — NEW. Contract-doc scenario #5 has no home.**
  "Corrective prompts contain the exact failed grades and check results" is
  unimplemented: a corrective worker is `kind="worker"` and now receives a
  `work_contract`, but nothing hydrates the failure record, verifier grades, or
  check results into its packet. Recorded explicitly because chunk 5 *deleted*
  the `corrective_requirement` and `corrective_evidence_required` node keys.
  That deletion was correct — no writer ever set them and the payload model
  would have rejected them (facts 38-39), so they were placeholders for an
  intent, not an implementation — but with them gone the intent would otherwise
  leave no trace in the code. Closely related to R10 (both are "hydrate bound
  records into the worker packet"); the two should be scoped together.

### Slice 1 — completion summary

Written at chunk-6 specification time; **flip the status line and confirm the
final count after chunk 6 is built and validated.** Merge to `main` when the
conditions at the bottom hold.

#### What Slice 1 achieved

A worker node's contract went from unrepresentable to mandatory, enforced, and
communicated:

1. **Representable** (chunk 1, `3ac034a7b`). Six typed fields on
   `NodeCreatedPayload` — `objective`, `scope`, `bound_requirement_ids`,
   `acceptance`, `invariants`, `prohibited_actions` — plus `projection=`
   retention so they survive both live append and checkpoint rebuild. Before
   this, `NodeCreatedPayload` was `extra="forbid"` and a planner *physically
   could not* put an objective on a node (fact 1). That, not a prompt bug, was
   the mechanism behind the dogfood finding "worker packets with no bounded
   objective".
2. **Unambiguous** (chunk 2, `8565c24f9`). The read-only/write concept got its
   own key, `access_mode: Literal["read_only","write"]`, rather than
   overloading the legacy `work_mode` (`implementation`/`oversight`) that 15
   historical `node_created` events in the git-tracked journal already carry.
   No migration, no compatibility shim, no schema bump (R1).
3. **Mandatory** (chunk 3, `4ee76eda8`). `validate_patch` rejects any
   `create_node` for a `kind == "worker"` node missing `objective`,
   `access_mode`, or `acceptance`, with one precise hand-written message per
   field naming the node. Threaded through macros, horizon templates, the
   prompt example patch, the codex tool schemas, and the MCP tool signatures so
   the planner's own tools are not a bypass. 29 pre-existing under-specified
   worker fixtures were repaired, never weakened — the Validator ran a
   dedicated anti-weakening audit across all 8 affected test files.
4. **Enforced with teeth** (chunk 4, `9ca1f26c1`). `access_mode` now determines
   authority: a `read_only` worker is granted
   `{"mode": "read", "scope": "repo", "paths": ["."]}` instead of the repo-write
   default, at both patch-reachable grant sites. Because `read` is rank 0, the
   pre-existing `set_resource_claims` escalation refusal makes the node
   permanently un-escalatable. A `role="discovery"` worker may not declare
   `access_mode="write"` without a durably recorded
   `access_mode_override_justification`, which is itself rejected wherever it is
   not needed, so a journal grep lists every exception ever granted. Build
   attempt 1 shipped a real bypass (an `external`-only claim defeated the
   mandatory `read` grant); independent validation caught it, the fix landed,
   and the reproduction is now a permanent regression pin.
5. **Communicated** (chunk 5, `e0177275f`). The worker prompt carries a single
   typed `work_contract:` section rendered from the declared fields, with the
   three mandatory keys always present (explicit `null` for compiler-seeded
   workers, which stay exempt) and the optional ones omitted when absent. Seven
   dead loose-dict reads that pretended to carry the contract were deleted, and
   the `prompt_summary` records `work_contract` as hydration *evidence* without
   copying contract text into the durable read model.
6. **Pinned end to end** (chunk 6). Two scenario tests joining admission →
   projection → prompt, closing the seam no single test crossed (fact 53),
   including the previously untested property that a `read_only` worker's
   prompt advertises `read` and never `write`.

Target-doc criteria 1-5 are met, with two recorded renamings of the doc's
vocabulary: the read-only/write concept is spelled `access_mode` (chunk 2
§"Downstream naming note"), and criterion 3's "default discovery `work_mode` is
`read_only`" is satisfied more strongly than by a default — the field is
mandatory and explicit for every worker, so there is no planner-reachable path
on which a default could apply (chunk 4 §"Framing correction").

#### What was deliberately deferred

Each with a reason recorded above, not silently skipped:

- **R5** — `create_revision_attempt`'s `worker_node` and `seed_compiled_events`
  remain contract-free. Both bypass `validate_node_payload` entirely, and
  closing them needs their producers to supply the fields (the compiler would
  populate the contract from `TaskConfig`). Pinned by
  `test_create_revision_attempt_worker_node_is_not_contract_checked` so closing
  it is an intentional edit.
- **R6** — no boundary-time detector for a `read_only` worker that writes
  anyway. Claim refusal is authority, not a filesystem sandbox; no per-node
  sandbox exists (fact 30). The exact insertion point is recorded.
- **R7** — the discovery/write *role policy* is not enforced on
  `create_revision_attempt` (the authority *derivation* is). Pinned.
- **R8** — the typed fields are not in `node_detail` retention, so the operator
  read model still cannot show a node's objective, access mode, or scope. That
  is contract-doc requirement #9, an unscoped nine-bullet item; the exact change
  needed is recorded.
- **R9** — contract-doc scenario #3 (staged plan collapse). Slice 3.
- **R10 / R11** — evidence-record hydration into worker packets, and corrective
  prompts carrying failed grades and check results (contract-doc scenario #5).

None of these is a regression: every one is a surface that was equally open
before this branch, now named with an insertion point.

#### Expected final state at merge

- Full suite **5513 passed, 5 skipped** (loop-start baseline on main
  `2553748e3` was 5454 passed / 5 skipped; +59 test IDs across six chunks).
- `PROJECTION_CHECKPOINT_SCHEMA_VERSION` still **15** — every payload change in
  the slice was a purely additive optional field, so no persisted checkpoint or
  historical event changes shape and no replay migration is needed.
- Ruff, ruff format, and pyright clean.
- Exactly one existing test modified across the whole slice
  (`test_prompt_routing_for_planner_worker_and_verifier`, chunk 5 — a deletion
  of coverage for removed dead keys), plus the 29 chunk-3 fixture repairs, which
  added missing contract fields rather than weakening any check.
- `.orchestrator/state/*.jsonl` unmodified.

The slice touches no runner, no UI, and no persisted-event shape. Merge is safe
once chunk 6 is validated and the above hold.

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
