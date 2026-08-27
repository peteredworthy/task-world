# Slice 1 / Slice 5 progress ledger

Durable state for the `mind-the-gap` loop implementing
`slice-1-and-5-target-2026-08-27.md`. Updated after every validated chunk.
Baseline at loop start: main `2553748e3`, full suite 5454 passed / 5 skipped
/ 75s.

## Slice 1 — worker contracts and prompt hydration

Status: chunks 1-3 of 6 verified and committed (`3ac034a7b`, `8565c24f9`,
`4ee76eda8`). Chunk 4 specified below (planning pass 4), not built. Chunks 5-6
not started.

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
