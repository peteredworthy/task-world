# Slices 3B-3D implementation ledger

Status: implementation and independent review complete; single repository gate pending.

Scope: implement the reviewed decision-v1 planning sequence in strict order:
initial discovery-brief planning (3B), discovery plan creation and independent
plan-verifier handoff (3C), then successor amendment and blocker decisions (3D).
Legacy interaction, unsupported runner behavior, historical evidence, and live
state remain unchanged.

## Functional requirements

| ID | Required behavior | Acceptance / product-real proof | Regression evidence | Status | Remaining gap |
|---|---|---|---|---|---|
| S3B-1 | A decision-v1 initial planner answers with the canonical strict `DiscoveryBrief`; runtime binds scope, requirements, available evidence, schema, and authority. | Disposable Git/SQLite production dispatch exposes only bounded aliases and accepts a valid brief without model-authored graph identity or requirement replacement. | Focused resolver, compiler, dispatch, restart, and schema tests. | Independently validated | None in the explicit-planner path. |
| S3B-2 | Missing, duplicate, and unknown choices fail closed; stale authority cannot be rebound after restart. | Negative production-path submissions publish no successor effects; exact duplicate delivery is idempotent and restart reconstructs the same request. | Boundary and replay tests. | Independently validated | The focused invalid-answer cases are pure ingress/compiler negatives; the shared staged/finalization replay suite supplies the production boundary and stale-read-set coverage. |
| S3B-3 | Fully supplied discovery input resolves deterministically only when frozen routine policy permits it; an explicitly independent step is preserved. | A controller-owned deterministic fixture bypasses no requested judgment and creates the same bounded downstream topology without a model start when allowed. | Deterministic-policy and independent-step tests. | Partial, architecture gap recorded | The frozen routine contract has no field that explicitly authorizes deterministic initial-brief bypass. This slice therefore preserves the explicit planner even when every dynamic feature input is supplied. Adding a bypass without that policy would violate contracts.md; architect review must choose and name the policy before controller-only resolution can be implemented. |
| S3C-1 | Discovery emits exactly the built-in `ImplementationPlan` semantic artifact through the existing assembler, with controller-owned provenance and a read-only candidate boundary. | A disposable production dispatch accepts a typed plan while workspace mutation and invalid/stale plan outputs fail before publication. | Artifact assembler, candidate-boundary, shape, alias, check, and restart tests. | Independently validated | None in the built-in decision-v1 path. |
| S3C-2 | The exact accepted plan, requirements, schema/version, and independent verifier are bound before successor dispatch. | Real discovery to plan-verifier handoff shows fresh executions/contexts and exact record bindings; successor remains unavailable until a passing verifier record exists. | Handoff, verification failure, post-answer mutation, and graph topology tests. | Independently validated | None in the built-in decision-v1 path. |
| S3C-3 | Invalid requirement aliases, dangling/cyclic dependencies, unknown checks, failed verification, and post-answer mutation publish no successor work. | Each negative case leaves no eligible successor region/effect and drains exact ownership. | Focused integration negatives plus immutable graph checks. | Independently validated | Slice 4A typed verification-decision aliases remain deliberately out of scope. |
| S3D-1 | `revise_plan` constructs a full prospective amendment from the accepted plan, preserving accepted work, requirements, acceptance, checks, authority, and supersession rules. | Disposable production path routes a valid amendment through an independent verifier before replacement work; rejected/cyclic/stale amendments publish no effects. | Pure amendment compiler, graph, replay, stale-authority, and integration tests. | Independently validated | None in the activated successor decision path. |
| S3D-2 | `blocked` routes the existing blocker/human-action path and never completes the decision or grants another execution. | Production-path blocker submission records bounded evidence/reason, blocks the lineage, and exposes the existing required action with no successor effects. | Blocker routing, replay, cancellation, and final/non-final horizon tests. | Independently validated | None in the activated successor decision path. |
| S3D-3 | Existing `proceed` behavior and legacy execution remain unchanged across final/non-final horizons, dependency ordering, replay, and cancellation. | Reviewed successor fixture plus joined 3D cases retain one atomic effect set and exact ownership cleanup. | Existing Slice 2/3A suites and new 3D regression bundle. | Independently validated | None in the activated successor decision path. |

## Evidence log

Starting hashes, behavior-first failures, changed files, product-real commands,
review verdicts, final hashes, and remaining concerns will be appended after each
lettered slice. No row is marked validated without both product-real proof and
supporting regression evidence.

## Slice 3B builder record

Status: implementation complete for S3B-1 and S3B-2, and for the safe provable
half of S3B-3; independent review pending.

The initial planner now uses the same decision submission, CAS staging,
controlled terminal closure, witness, and atomic finalization lifecycle already
reviewed for successor decisions. The compiler binds the exact frozen routine
snapshot and dynamic-feature acceptance requirement to the initial planner,
declares only the canonical decision output, and keeps graph mutation tools out
of the authored interaction. `graph/decisions.py` owns the generated
`DiscoveryBrief` schema/hash, immutable protected context, exact input resolver,
focus-subset validation, deterministic consequence compiler, answer record, and
read set. The consequence compiler reuses the existing reliable-plan macro seam
to construct discovery, exact built-in plan verification, first successor, and
recovery topology; competing custom implementation-plan declarations cannot
substitute for `orchestrator.reliable-plan.decision-plan@1`.

The shared dispatch and boundary consumers were generalized only across the two
activated families (`discovery_brief` and `batch_decision`). They still decode
from frozen applicability, use one `submit(outputs=...)`, publish no downstream
effects at staging, require `terminal_answer_completed`, re-resolve exact inputs
at finalization, and commit the answer, patch, completion, and outbox effects
atomically. The requirement-selector validator now recognizes the canonical
`requirement_record` selector for numbered successor requirement ports.

Changed files for Slice 3B:

```text
src/orchestrator/graph/__init__.py
src/orchestrator/graph/commands/boundary.py
src/orchestrator/graph/compiler.py
src/orchestrator/graph/decisions.py
src/orchestrator/graph/macros.py
src/orchestrator/graph/models.py
src/orchestrator/graph/patch_validator.py
src/orchestrator/graph_runtime/dispatch.py
src/orchestrator/graph_runtime/prompts.py
tests/integration/test_graph_decision_runtime.py
tests/unit/test_initial_planning_decision.py
```

Starting hashes captured before Slice 3B implementation source edits:

```text
f682ddf8201bcec97b4bee67397aca4c9bbe9e53ddac3100be585d6ff0f31344  src/orchestrator/graph/decisions.py
26e63053af71144f458b6f6c90bc4186185666f144a9597f1890ec259e04bb95  src/orchestrator/graph/models.py
096022acecf0bad081b92e8b8aa9565f8b84ac9685e24b56a02dfc56dbf6c30e  src/orchestrator/graph/macros.py
6b86a9b1d769e665448ca6d4e6c0e166f6c967595568e0ed32c714c92c813e86  src/orchestrator/graph/compiler.py
b570e08bc54600c64e9e86ab36471abd777581d78cbffe6d91f36949b5fe45d6  src/orchestrator/graph/commands/boundary.py
097eb1522cb357a3aad3a2c8911b0765d88efde1e39248ecd03ad8b9543d2a7e  src/orchestrator/graph_runtime/dispatch.py
a03953c16eacdb05f77cd7c24de18bf5a7f27dbe219be15407d9e3c8f0d80bdb  src/orchestrator/graph_runtime/prompts.py
0240f217707c032d23106c725be409035921d06f74a46e842502f6034ca1fcb7  src/orchestrator/graph/__init__.py
```

Final hashes after Slice 3B builder validation:

```text
1ae283ebf1c180e08bbae6d492e826ea06f42f57dd5df0b07862c552a23c4e19  src/orchestrator/graph/decisions.py
0e7713936bf6c0620a6f4d24695180a115b6fe407b764face6d8cf75717b5155  src/orchestrator/graph/models.py
90aa1cc47b384ff6145191c39d827645380ddb1420d8b4da0930a1d037272757  src/orchestrator/graph/macros.py
c57aa9cc75afbdadc246821c470f73365f23213356f7cb342e163aa7dea8bf4d  src/orchestrator/graph/compiler.py
4895fff9eacd5739ce405e1ef1d736182f2f7cde4b66e16e2498dbb1c5d5b90b  src/orchestrator/graph/patch_validator.py
d413007c5ddd963a5d22177606e119da0808e2ed69b7a6a1e7ef4ac02aaaedd8  src/orchestrator/graph/commands/boundary.py
037fdb36b13a037de1ac6337116ceef04bcc1b13519c7661f78902e4468826d1  src/orchestrator/graph_runtime/dispatch.py
8853a9597d3a1702a3c5233a2529a04bb96a338a5b802df8830e02bde6206bca  src/orchestrator/graph_runtime/prompts.py
1a6dd1d9135248107e987b77dde1a0c743dc0ab4ec9f1f6caf720dd969838696  src/orchestrator/graph/__init__.py
5ab418f9c9fb6d9c7e46a962f8b1c75bc2cfc9235a8e2624b94dc5908bc9d262  tests/unit/test_initial_planning_decision.py
bb932115647e0c5e47b88b4ebc40ba777e0d9ded962a28bcb7966292d2d189e7  tests/integration/test_graph_decision_runtime.py
```

Behavior-first evidence:

```text
pytest -q -n 0 tests/unit/test_initial_planning_decision.py
# 2 failed
# - the initial planner had no controller-owned requirement binding
# - applicability fell through to a legacy submission contract
```

Focused builder regression:

```text
pytest -q -n 0 tests/unit/test_initial_planning_decision.py \
  tests/unit/test_graph_decisions.py tests/unit/test_decision_schema_consumers.py \
  tests/unit/test_reliable_plan_region_constructor.py \
  tests/unit/test_graph_dispatch_on_output.py \
  tests/unit/test_graph_runner_boundary_commands.py \
  tests/unit/test_reliable_plan_tool_exposure.py tests/unit/test_graph_mcp_tools.py \
  tests/unit/test_codex_server_transport.py tests/unit/test_cli_agent.py \
  tests/integration/test_graph_decision_runtime.py -k 'not slow'
# 377 passed, 1 deselected, 10 retained warnings

pytest -q -n 0 tests/integration/test_graph_routine_compile.py \
  tests/unit/test_graph_compiler.py tests/unit/test_graph_planner_packet.py \
  -k 'dynamic_graph_feature or decision or reliable_plan or planner'
# 23 passed, 72 deselected
```

Product-real disposable proof:

```text
pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py::test_initial_discovery_brief_runs_through_production_dispatch_and_finalization
# 1 passed
```

That fixture uses a real disposable Git repository, SQLite event/outbox store,
filesystem CAS, production controller/dispatch routing, and an injected scripted
Codex Server transport. It proves effect-free staging, duplicate delivery,
conflicting valid answer rejection, trusted terminal closure, atomic initial
topology publication, exact answer/binding readback, and restart reconstruction.
It is infrastructure proof, not a model-reliability claim.

Static validation:

```text
ruff check <Slice 3B files>
# All checks passed
ruff format --check <Slice 3B files>
# 11 files already formatted
pyright
# 0 errors, 0 warnings, 0 informations
python scripts/check_graph_projection_boundaries.py
# exit 0
git diff --check
# exit 0
```

All Python commands used the required
`UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync` prefix. No live
server, live database, paid probe, activation, historical resume, commit, or
automatic model retry was performed.

### Exact remaining Slice 3B architecture gap

The snapshot can select `decision-v1`, but no current routine model or frozen
snapshot field says that an already supplied discovery brief may replace the
explicit initial planner. `contracts.md` permits controller-only resolution only
when the routine author explicitly supplies that policy and forbids silently
removing an independent judgment. Therefore fully supplied dynamic feature
inputs continue to dispatch the canonical `DiscoveryBrief` planner. A future
architect decision must define the policy name, configuration validation,
snapshot representation, and exact supplied-brief source before the
no-model-start half of S3B-3 can be implemented safely.

## Slice 3B frozen-authority correction pass

Status: builder correction complete; fresh independent validation pending.

Finding: the prompt and submission contract were rendered from the immutable
dispatch `GraphDispatchContext.graph_projection`, but first-time decision
staging re-read the latest projection and used its current position for the
protected question context, bound-input request, consequence compilation, and
staleness base. A matching requirement or authority revision between dispatch
and submit could therefore be absorbed into a new request that the model had
never received.

Behavior-first failure:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py::test_initial_discovery_brief_rejects_authority_changed_after_dispatch
# 1 failed: the runner received no rejection after recording the exact bound
# dynamic_feature_acceptance revision immediately before submit.
```

Fix: `_submit_decision_callback` now resolves the protected context, bound
inputs, schema family, consequence compilation, and decision base position from
the dispatch snapshot. The runtime boundary command still executes against the
latest controller position, but retains that frozen decision base across
optimistic-concurrency retries. Existing `DecisionSubmissionRequest.bound_inputs`
comparison and decision read-set validation now reject changed exact inputs or
authority. No state, lifecycle, or deterministic-bypass policy was added.

Product-real and regression proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py::test_initial_discovery_brief_freezes_dispatch_authority_without_blocking_unrelated_tail
# 2 passed
# - exact bound authority revision: rejected, no runner_submission_staged,
#   decision_answer, planner graph patch, or downstream semantic stages
# - unrelated requirement revision: original request stages and atomically
#   finalizes with one answer/effect set

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py \
  tests/unit/test_initial_planning_decision.py tests/unit/test_graph_decisions.py \
  tests/unit/test_graph_runner_boundary_commands.py -k 'not slow'
# 132 passed, 1 retained serializer warning

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check \
  src/orchestrator/graph_runtime/dispatch.py \
  tests/integration/test_graph_decision_runtime.py
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

Correction starting hashes:

```text
037fdb36b13a037de1ac6337116ceef04bcc1b13519c7661f78902e4468826d1  src/orchestrator/graph_runtime/dispatch.py
bb932115647e0c5e47b88b4ebc40ba777e0d9ded962a28bcb7966292d2d189e7  tests/integration/test_graph_decision_runtime.py
f0db5352747e3b34b6fefda099c371d390e8d370f8a47b08e4cb6ce6f6228a93  docs/intent/31-decision-runtime/slice-3b-3d-implementation-ledger.md
```

Correction final source/test hashes:

```text
015c6ba9a8d919f109323a0e109e6c9f8900544488b40e800fcc4cf8020289d5  src/orchestrator/graph_runtime/dispatch.py
c1f8feab6ddd14c873f1d0577429373037e3fb77840e536d7143c049aaecab98  tests/integration/test_graph_decision_runtime.py
```

No live server, paid probe, commit, Slice 3C/3D implementation, or
deterministic-bypass policy was used in this correction pass.

## Slice 3C builder record

Status: implementation complete for S3C-1 through S3C-3; fresh independent
review pending.

The generated discovery worker is now an `implementation_plan` decision-v1
family. Its protected packet binds the exact routine snapshot, numbered
requirement aliases, canonical built-in schema ID/version/hash, frozen maximum
batch horizon, available check bindings, and permitted explicit command
definitions. The canonical `ImplementationPlan` model remains the schema owner:
it rejects malformed batches, duplicate keys, dangling dependencies, dependency
cycles, and invalid command definitions. The decision resolver additionally
rejects unknown or missing requirement aliases and unavailable check bindings.

Plan submission reuses `_semantic_output_records_from_submit_args` and the
existing semantic callback validator. The controller, not the model, assembles
the accepted `SemanticArtifactRecord`, including exact source record IDs,
requirement IDs, schema identity, task region, and execution provenance. Staging
performs the established callback-plan dry run but publishes neither the record
nor downstream effects. Finalization requires the trusted terminal completion,
re-resolves frozen authority, rejects stale or mutated authoritative state, and
atomically publishes the exact plan and completion. Discovery has no model-authored
graph patch.

The existing reliable-plan topology supplies a distinct plan-verifier node and
a direct plan-gated successor. The product fixture dispatches discovery and the
existing independent grade/submit verifier in fresh execution contexts. The
successor remains `planned` without a passing report and becomes schedulable
only after that report evaluates both the feature requirement and the exact plan
record. Slice 4A `verification_decision` and obligation aliases were not added.

Changed files for Slice 3C:

```text
src/orchestrator/graph/__init__.py
src/orchestrator/graph/commands/boundary.py
src/orchestrator/graph/decisions.py
src/orchestrator/graph/macros.py
src/orchestrator/graph_runtime/dispatch.py
src/orchestrator/graph_runtime/prompts.py
tests/integration/test_graph_decision_runtime.py
tests/unit/test_initial_planning_decision.py
docs/intent/31-decision-runtime/slice-3b-3d-implementation-ledger.md
```

Starting source/test hashes are the Slice 3B correction endpoint:

```text
1ae283ebf1c180e08bbae6d492e826ea06f42f57dd5df0b07862c552a23c4e19  src/orchestrator/graph/decisions.py
90aa1cc47b384ff6145191c39d827645380ddb1420d8b4da0930a1d037272757  src/orchestrator/graph/macros.py
d413007c5ddd963a5d22177606e119da0808e2ed69b7a6a1e7ef4ac02aaaedd8  src/orchestrator/graph/commands/boundary.py
015c6ba9a8d919f109323a0e109e6c9f8900544488b40e800fcc4cf8020289d5  src/orchestrator/graph_runtime/dispatch.py
8853a9597d3a1702a3c5233a2529a04bb96a338a5b802df8830e02bde6206bca  src/orchestrator/graph_runtime/prompts.py
1a6dd1d9135248107e987b77dde1a0c743dc0ab4ec9f1f6caf720dd969838696  src/orchestrator/graph/__init__.py
5ab418f9c9fb6d9c7e46a962f8b1c75bc2cfc9235a8e2624b94dc5908bc9d262  tests/unit/test_initial_planning_decision.py
c1f8feab6ddd14c873f1d0577429373037e3fb77840e536d7143c049aaecab98  tests/integration/test_graph_decision_runtime.py
```

Behavior-first evidence:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_initial_planning_decision.py \
  tests/integration/test_graph_decision_runtime.py -k 'initial_discovery'
# 3 passed, 9 deselected (pre-change baseline)

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_initial_planning_decision.py -k 'discovery_uses or rejects_unbound'
# collection failed: resolve_implementation_plan_context did not exist

# After adding the resolver but before activating dispatch:
# 1 failed, 3 passed: discovery still received the legacy submission contract.
```

Product-real disposable proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py::test_initial_discovery_brief_runs_through_production_dispatch_and_finalization
# 3 passed in 15.76s
# - passing plan: controller-owned record -> independent verifier -> successor eligible
# - failed plan: failing report retained and successor remained planned
# - post-answer mutation: finalization rejected, plan unpublished, successor planned
```

The fixture uses a disposable real Git repository, SQLite event/outbox store,
filesystem CAS, production controller/dispatch/finalization, and injected
scripted Codex Server transports. It also proves the discovery candidate runs
outside the authoritative worktree, leaves the source repository clean in the
accepted case, records distinct discovery/verifier execution IDs, and binds the
verifier report to the exact plan plus feature requirement. This is lifecycle
and authority proof, not a model-reliability claim.

Focused negative and regression proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_initial_planning_decision.py tests/unit/test_graph_decisions.py \
  tests/unit/test_decision_schema_consumers.py \
  tests/unit/test_graph_runner_boundary_commands.py \
  tests/unit/test_graph_dispatch_on_output.py -k 'not slow'
# 251 passed, 2 retained warnings

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py -k 'not slow'
# 7 passed in 27.07s
```

The focused negatives cover unknown requirement aliases, dangling and cyclic
dependencies, unavailable check bindings, a failing independent verification,
and authoritative mutation after answer staging. Existing strict model tests
continue to cover invalid explicit command definitions and duplicate/invalid
batch shapes. Because validation precedes callback acceptance, the pure ingress
failures cannot publish a plan record or unlock the successor.

Static validation:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check \
  <Slice 3C source/test files>
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

Final source/test hashes:

```text
28c871e10b4f141a0b29dbd403c9240ac534dc826ea236a3d85ce7eb2413958d  src/orchestrator/graph/decisions.py
d82727a1482cbbc152d371784eecec28913059bfda777c1a8e60092a3821910a  src/orchestrator/graph/macros.py
282c635e713fce54da1c9c30a65a7bc32d4f2c4f88d3fb55a43024b34404de49  src/orchestrator/graph/commands/boundary.py
226eace43e70472953ceddce34cff41cea56af8712d0e9adce7cbdbea6754a17  src/orchestrator/graph_runtime/dispatch.py
f3c3e77fee39b489191413ce2d1b11f3ed2d0e3c4d79fe9a0b13234c9d12b5fc  src/orchestrator/graph_runtime/prompts.py
41bb17d69ebfc794745d9341c6e18e9e4fe0b4b102df7bf4c7ee0d1beade43bf  src/orchestrator/graph/__init__.py
5bb6c29774d2ec364dfaf24c674951b7fd60340f1d09a8c768c8726e2d2999e4  tests/unit/test_initial_planning_decision.py
c0d5686111938011d3cdc4e17073551b05576c190a0b77f56e2ac0e55fcb93cc  tests/integration/test_graph_decision_runtime.py
```

All Python commands used the required prefix. No live server, live database,
paid probe, unsupported-runner change, legacy/custom-schema change, commit,
Slice 3D behavior, or Slice 4A verifier alias was performed.

## Slice 3C command-schema correction

Status: builder correction complete; fresh independent review pending.

Finding: authoritative `CheckChoice` validation delegates to
`check_command_invocation`, which accepts `argv` when its first element contains
non-whitespace text and every element is a string. Therefore `{"argv":
["tool", ""]}` is valid. The generated command-definition schema instead set
`minLength: 1` on every argv element. Both the Codex dynamic-tool catalog and
the Claude/FastMCP submission transport consume that generated schema, so they
rejected an authoritative valid discovery plan before its callback could run.

Fix: `check_command_definition_tool_schema()` remains the single schema owner.
Its argv schema now applies the executable/non-whitespace constraint only to
the first item and permits later string arguments to be empty. Non-string argv
items, an empty argv, and a blank first/executable item remain invalid; cmd,
command, metadata, extension, legacy interaction, and dispatcher behavior are
unchanged. A connected real FastMCP client/server session and the actual Codex
dynamic-tool spec now exercise the same canonical `ImplementationPlan` submit
schema and accepted payload.

Behavior-first proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_decision_schema_consumers.py::test_codex_and_claude_fastmcp_accept_authoritative_legacy_argv
# Before production change: 1 failed because argv[1] "" violated minLength.
# After production change: passed; Codex validation and connected FastMCP
# transport both accepted the payload and FastMCP invoked the callback once.
```

Focused schema, catalog, discovery, and runtime proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_command_bindings.py tests/unit/test_graph_decisions.py \
  tests/unit/test_decision_schema_consumers.py \
  tests/unit/test_reliable_plan_tool_exposure.py \
  tests/unit/test_graph_mcp_tools.py tests/unit/test_initial_planning_decision.py \
  tests/unit/test_graph_runner_boundary_commands.py \
  tests/unit/test_graph_dispatch_on_output.py -k 'not slow'
# 286 passed, 10 retained warnings in 5.62s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py -k 'not slow'
# 7 passed in 26.91s
```

Static and boundary proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check \
  src/orchestrator/graph/command_bindings.py \
  tests/unit/test_decision_schema_consumers.py \
  tests/unit/test_reliable_plan_tool_exposure.py
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

Correction hashes before the ledger update:

```text
55906e4a61b403fc02772457f6829c0d519bd797b262370f2332618c3fc7ccd3  src/orchestrator/graph/command_bindings.py (starting)
dbde7c72974ac5d95f9152e2152a96285d04c4c467589869ea9fb999faf8f26e  src/orchestrator/graph/command_bindings.py (final)
03e94ce47a40c3ab9cdcc7bd9795b3c792c59ce9d8ef1f1b62d75075f02cc88d  tests/unit/test_decision_schema_consumers.py
1802ccceff2e0d9d5f65a60f87bf5c4b41b72ffb7338a74f03ba7c7dbd11c281  tests/unit/test_reliable_plan_tool_exposure.py
```

No live server, paid probe, database mutation, commit, Slice 3D behavior, or
legacy parser/schema narrowing was used in this correction.

## Slice 3D builder record

This record follows completion of every Slice 3C correction; the final 3C
fallback-correction evidence remains below because the durable ledger was
assembled concurrently.

Status: implementation complete for S3D-1 through S3D-3; fresh independent
review pending.

`revise_plan` now applies the authored narrow amendment to the exact accepted
built-in plan in a pure compiler. The compiler preserves the accepted prefix,
all batch keys and requirement aliases, and every existing acceptance, check,
review, and dependency entry. Refinements are limited to unfinished batches and
scope subsets. Added batches must use known frozen requirement aliases, stay
inside the accepted plan's aggregate scope, preserve dependency order, and fit
the frozen dynamic-feature `patch_budget`; model input never supplies or raises
that capacity. Full prospective-plan validation rejects duplicate or dangling
keys, cycles, forward dependencies, unavailable check bindings, and authority
widening before any event is emitted.

An accepted revision produces a deterministic controller-owned built-in plan
artifact that explicitly supersedes the prior accepted plan. Its patch creates
only a fresh independent plan verifier, same-horizon replacement successor, and
failed-verification recovery. Both verifier and successor bind the exact new
record ID; the successor remains unavailable until a passing report evaluates
that record. Accepted work remains intact and no worker, check, final gate, or
automatic new execution is published by the amendment decision.

`blocked` reuses the existing human-gate `DecisionRequest` path. It binds only
resolved evidence aliases, emits no work, successor, or finalization topology,
atomically records the canonical batch decision, and transitions the current
successor planner to `failed` with a bounded blocker diagnostic. This is the
existing non-runnable terminal state, so the scheduler cannot re-lease the
lineage; the human request remains the explicit intervention surface.

The decision boundary now publishes the compiler's complete canonical output
set atomically (decision plus superseding plan for revision) and uses the
compiler-selected terminal state. The original `proceed` compiler and effectful
region topology are unchanged. Same-horizon authority stamping is limited to
the exact amendment topology and bounded frozen capacity.

Changed files for Slice 3D:

```text
src/orchestrator/graph/_commands.py
src/orchestrator/graph/commands/boundary.py
src/orchestrator/graph/decisions.py
src/orchestrator/graph/macros.py
src/orchestrator/graph/patch_validator.py
tests/integration/test_graph_decision_runtime.py
tests/unit/test_graph_decisions.py
tests/unit/test_successor_amendment_decision.py
docs/intent/31-decision-runtime/slice-3b-3d-implementation-ledger.md
```

Behavior-first failure:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_successor_amendment_decision.py
# 9 failed: every valid revise_plan and blocked case stopped at the prior
# "slice-2 successor compiler supports only proceed decisions" rejection.
```

Focused pure and production-real proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_successor_amendment_decision.py
# 11 passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py::test_decision_dispatch_stages_cas_then_atomically_finalizes
# 7 passed in 21.14s
```

The disposable production matrix uses a real Git repository, SQLite event and
outbox store, filesystem CAS, production controller/dispatcher/finalization,
restart reconstruction, and injected scripted Codex Server transports. It
covers proceed finalization and cancellation; non-final amendment verification
pass, cancellation win, and verification failure; final-horizon amendment pass;
and blocker routing. It proves effect-free staging, exact duplicate idempotence,
conflicting valid-answer rejection, one atomic effect set, exact superseding-plan
verification, no successor dispatch after a failed report, and no active lease
after test cleanup.

Focused Slice 3B-3D regression:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_successor_amendment_decision.py \
  tests/unit/test_graph_decisions.py tests/unit/test_initial_planning_decision.py \
  tests/unit/test_graph_runner_boundary_commands.py \
  tests/integration/test_graph_decision_runtime.py -k 'not slow'
# 154 passed, 1 retained serializer warning in 40.25s
```

Static and boundary proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check \
  <Slice 3D source/test files>
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format --check \
  <Slice 3D source/test files>
# 8 files already formatted (after applying the formatter)

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

Final source/test hashes before this ledger update:

```text
672919ef576932973c263ffea9869ed6bc6fdda63fad3b2418330a5a9b0bbb08  src/orchestrator/graph/decisions.py
b22723f970003d505c6b0793197d5d543f6c45498fd9a3dc17ff0018878e651b  src/orchestrator/graph/macros.py
10096d300d8b668b78c6f87a131c720ae8561b4f16625676d045cd9709cf2f55  src/orchestrator/graph/patch_validator.py
defbde9a8d8a80864b1b3c34434241b07085324ba275d626d3347cdd62a5e052  src/orchestrator/graph/_commands.py
3f39e22a0e68c24b7756b150a7e8bc8fd318caca4b6ef8d2fb26acd0b9b651ab  src/orchestrator/graph/commands/boundary.py
84dc64ac8b8a251c2e237e5bf38b657851fd66c7502751c43d7442032b3d4880  tests/unit/test_graph_decisions.py
30ace643147e9ac77b81098862ac37472a290419f3dc4a0a28d07e9b61713b32  tests/unit/test_successor_amendment_decision.py
c5f8eee846fcce3ec5838a3e8848d2d13d34d4ad770b9b025c471eb1aff4a575  tests/integration/test_graph_decision_runtime.py
```

The pure negatives cover accepted-prefix edits, scope widening, over-capacity
additions, additions outside accepted scope, unknown and cyclic dependencies,
unknown requirement and evidence aliases, and deterministic replay. Existing
Slice 2 tests retain stale exact-input/read-set rejection and cancellation on
both sides of finalization. No live server, live database, paid probe,
unsupported-runner change, historical resume, commit, Slice 3E, or Slice 4A
behavior was performed.

## Slice 3C command-schema fallback correction

Status: builder correction pass 3 complete; fresh independent review pending.

Finding: the first command-schema correction aligned valid `argv` elements but
left the `argv`, `cmd`, and `command` value constraints in the root
`properties` object. JSON Schema therefore evaluated every present command
field before `anyOf`: `{"argv": [" ", "arg"], "cmd": "true"}` and
`{"argv": [], "command": "true"}` were rejected even though the authoritative
`check_command_invocation` parser tries `argv`, falls back to `cmd`, and then
falls back to `command`. This affected both generated provider schemas and the
actual Codex decision ingress before the submission callback.

Fix: `check_command_definition_tool_schema()` remains the single generated
schema owner. It now keeps command-field documentation at the root and places
each field's executable constraint inside its own `anyOf` branch. Consequently
any one parser-valid form is sufficient and an invalid earlier field does not
poison a valid fallback. The argv branch still requires a non-empty string
array and a non-whitespace executable while permitting `argv: ["tool", ""]`;
the shell branches require non-whitespace `cmd` or `command`; metadata and
extension fields remain supported. The authoritative parser was not changed or
narrowed.

Behavior-first failure and focused fix proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_reliable_plan_tool_exposure.py::test_reliable_plan_check_schema_matches_command_parser_fallbacks \
  tests/unit/test_decision_schema_consumers.py::test_codex_catalog_and_connected_fastmcp_accept_authoritative_command_forms \
  tests/integration/test_codex_dynamic_tool_receipts.py::test_codex_decision_ingress_invokes_callback_for_command_parser_fallbacks
# Before production change: 6 failed, 1 passed. Both fallback payloads failed
# pure schema validation, generated Codex catalog validation, and actual Codex
# ingress; the callback was not invoked.
# After production change: 7 passed in 0.52s. The connected FastMCP transport
# and the real Codex JSON-RPC dynamic-tool ingress each invoked their callback
# with both exact fallback payloads.
```

Focused 3C schema, catalog, runtime, and product-boundary proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_command_bindings.py tests/unit/test_graph_decisions.py \
  tests/unit/test_decision_schema_consumers.py \
  tests/unit/test_reliable_plan_tool_exposure.py \
  tests/unit/test_graph_mcp_tools.py tests/unit/test_initial_planning_decision.py \
  tests/unit/test_graph_runner_boundary_commands.py \
  tests/unit/test_graph_dispatch_on_output.py \
  tests/unit/test_codex_server_transport.py -k 'not slow'
# 335 passed, 1 deselected, 10 retained warnings in 6.21s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py \
  tests/integration/test_codex_dynamic_tool_receipts.py -k 'not slow'
# 12 passed in 27.09s
```

Static and boundary proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check \
  src/orchestrator/graph/command_bindings.py \
  tests/unit/test_reliable_plan_tool_exposure.py \
  tests/unit/test_decision_schema_consumers.py \
  tests/integration/test_codex_dynamic_tool_receipts.py
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

Correction hashes before this ledger update:

```text
dbde7c72974ac5d95f9152e2152a96285d04c4c467589869ea9fb999faf8f26e  src/orchestrator/graph/command_bindings.py (starting)
8be635c3950d6e73459d56f8628b2a42ebd71b6aab2ba9887581a44b300e74df  src/orchestrator/graph/command_bindings.py (final)
1802ccceff2e0d9d5f65a60f87bf5c4b41b72ffb7338a74f03ba7c7dbd11c281  tests/unit/test_reliable_plan_tool_exposure.py (starting)
99bb848186de832ed5151c3d27f73699544425029d78efff2b2c40e0745e1200  tests/unit/test_reliable_plan_tool_exposure.py (final)
03e94ce47a40c3ab9cdcc7bd9795b3c792c59ce9d8ef1f1b62d75075f02cc88d  tests/unit/test_decision_schema_consumers.py (starting)
cfaf5d74e539a8f5376ffe663cfc2fcb2be98c85fa976ffa5df637a78bb11577  tests/unit/test_decision_schema_consumers.py (final)
2557c4fe95550601e621b15408ba1abccedc0f58673a4955a416f2e83f6625dc  tests/integration/test_codex_dynamic_tool_receipts.py (final)
```

The integration receipt test was already an untracked Slice 3C artifact, so no
stable Git starting blob existed for that file. No live server, paid probe,
database mutation, commit, Slice 3D behavior, or parser change was performed.

## Slice 3D next-horizon and blocker-scheduling correction

Status: builder correction complete; fresh independent review pending.

Independent review found two product-path gaps in the first Slice 3D pass.
First, a non-final decision-v1 `proceed` constructed the horizon-two successor
from the current batch's scope and requirements. The semantic stamping pass
overwrote the successor's scope, and the exact-requirement binder applied the
current batch's records to every numbered requirement edge. The successor
resolver also regenerated aliases locally (`r1`, `r2`, ...) instead of retaining
the accepted plan's frozen global aliases, so a valid disjoint plan whose first
batch uses `r1` and second batch uses `r2` could not resolve horizon two.
Second, the scheduler excluded automatic `gate` nodes but still treated
controller-owned `human_gate` and `authority_request` nodes as dispatchable
agent candidates. A blocked decision therefore exposed the required human
action but could also lease that action node on a later schedule tick.

Behavior-first evidence:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q \
  tests/unit/test_successor_amendment_decision.py::test_nonfinal_proceed_next_horizon_resolves_exact_selected_batch_authority \
  tests/unit/test_scheduler.py::test_scheduler_never_dispatches_controller_owned_decision_gate_kinds \
  --override-ini='addopts='
# Before the production correction: the disjoint r1/r2 case failed in
# resolve_batch_decision_context with "selected batch requirements do not match
# exact supplied aliases"; scheduler candidates incorrectly included both
# human-action and authority-action. The shared-requirement case also exposed a
# test-fixture assumption about the schema selector before reaching resolution;
# the fixture was corrected to bind the exact accepted plan record.

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q \
  tests/integration/test_graph_decision_runtime.py::test_decision_dispatch_stages_cas_then_atomically_finalizes\[blocked\] \
  --override-ini='addopts='
# The production-path case was extended before the scheduler correction to tick
# after finalization and require zero leases/agent dispatches for both the human
# gate and failed planner lineage while retaining its DecisionRequest record.
```

The correction keeps the accepted plan as the single authority for requirement
aliases. `resolve_batch_decision_context` reconstructs the plan's frozen global
`rN -> requirement identity -> exact source record` mapping from the accepted
semantic artifact, then requires the successor's bound records to equal the
selected batch's aliases in order. The pure decision compiler passes the next
selected batch's key, requirement identities, and exact record IDs to the
existing reliable-plan topology compiler. That compiler gives the horizon-two
planner the next scope before semantic stamping, creates only its selected
requirement edges, and applies exact selectors specifically to that node. The
same selected-batch binding is used by a same-horizon amendment successor while
the independent plan verifier continues to receive the complete plan requirement
set. Superseding plan provenance now carries the complete inherited requirement
authority rather than only the current batch subset.

The scheduler's existing `_DECISION_GATE_KINDS` classification is now also the
candidate exclusion rule. `gate`, `human_gate`, and `authority_request` remain
controller decision surfaces: readiness and human-action projection behavior are
unchanged, but none can receive an agent lease or dispatch. The blocked planner
remains terminally failed, and the disposable SQLite/controller test proves that
a post-finalization schedule tick leases neither it nor its human gate while the
canonical `DecisionRequestRecord` remains exposed.

Correction changed files:

```text
src/orchestrator/graph/decisions.py
src/orchestrator/graph/macros.py
src/orchestrator/graph/scheduler.py
tests/unit/test_successor_amendment_decision.py
tests/unit/test_scheduler.py
tests/integration/test_graph_decision_runtime.py
docs/intent/31-decision-runtime/slice-3b-3d-implementation-ledger.md
```

Focused behavior and regression proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q \
  tests/unit/test_successor_amendment_decision.py::test_nonfinal_proceed_next_horizon_resolves_exact_selected_batch_authority \
  tests/unit/test_scheduler.py::test_scheduler_never_dispatches_controller_owned_decision_gate_kinds \
  --override-ini='addopts='
# 3 passed in 0.44s
# Both core->api variants apply the real patch, bind the produced horizon-two
# node, and resolve its decision context. The disjoint variant proves only r2 /
# REQ-2 / requirement-record-2 is present at horizon two.

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q \
  tests/integration/test_graph_decision_runtime.py::test_decision_dispatch_stages_cas_then_atomically_finalizes\[blocked\] \
  tests/unit/test_successor_amendment_decision.py tests/unit/test_scheduler.py \
  --override-ini='addopts='
# 62 passed in 3.36s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q \
  tests/unit/test_graph_decisions.py tests/unit/test_successor_amendment_decision.py \
  tests/unit/test_scheduler.py tests/unit/test_reliable_plan_region_constructor.py \
  tests/integration/test_graph_decision_runtime.py --override-ini='addopts='
# 152 passed in 51.24s
```

Static and boundary proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check \
  <six correction source/test files>
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format --check \
  <six correction source/test files>
# 6 files already formatted

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

Correction starting hashes (the first-pass Slice 3D endpoint, except the two
previously unchanged scheduler files):

```text
672919ef576932973c263ffea9869ed6bc6fdda63fad3b2418330a5a9b0bbb08  src/orchestrator/graph/decisions.py
b22723f970003d505c6b0793197d5d543f6c45498fd9a3dc17ff0018878e651b  src/orchestrator/graph/macros.py
94999567bb8d8277abadcb89748d8b85b2645a21a0183aaea22caa2c117e0dd1  src/orchestrator/graph/scheduler.py
30ace643147e9ac77b81098862ac37472a290419f3dc4a0a28d07e9b61713b32  tests/unit/test_successor_amendment_decision.py
89246227808e6af35607207066fb4e967f26dc55d4973372ba1b4929b0df07e8  tests/unit/test_scheduler.py
c5f8eee846fcce3ec5838a3e8848d2d13d34d4ad770b9b025c471eb1aff4a575  tests/integration/test_graph_decision_runtime.py
```

Correction final source/test hashes before this ledger update:

```text
3a6ee226ab4c57f96063cba1a6624ca74e4dd58822ce9d49a10768ec3b4dc176  src/orchestrator/graph/decisions.py
cb015ba1c8b84815cc0ff3e2d8073a8b1b3adeecc793019f02471ad82d70ff97  src/orchestrator/graph/macros.py
c359473d626aec9c51099db92d2a20b8b7e763a0114575e88014777f6f78befb  src/orchestrator/graph/scheduler.py
8157a81a7de27e1d9bae041291c203fb11ba1f9f2baed618dfe8457f4a682f33  tests/unit/test_successor_amendment_decision.py
bbb7e690d90d0b1a47ccb739c185cb40d893b65fe2034ae87cb8cf190450cd24  tests/unit/test_scheduler.py
28741d74bfc5e78714faad2e8ae50dad4fa1e68042be0251d4ca0c4d38a9f621  tests/integration/test_graph_decision_runtime.py
```

No live server, live database, paid probe, activation, historical resume,
automatic retry, commit, Slice 3E, or Slice 4A behavior was used. Independent
review remains required before Slice 3D can be marked validated.

## Slice 3D durable-authority correction, builder pass 3

Status: builder correction pass 3 complete; fresh independent review pending.

Fresh validation found three related authority failures. A horizon-two successor
bound the prior batch report through `verification_report`, but the decision
compiler also supplied that record as the trusted independent plan verifier; the
resolver could identify the accepted plan and exact selected requirements, yet
the real patch compiler rejected the prior batch verifier because it did not
evaluate the plan. A same-horizon amendment reconstructed global aliases from
`FrozenMap` iteration order, which could reverse `REQ-1, REQ-2` provenance and
remap a disjoint `r2` batch. Finally, the initial successor was materialized
before the accepted plan existed and therefore carried every plan requirement;
a valid first batch containing only `r1` could not satisfy the exact subset
invariant. The realistic amended final-batch submit additionally exposed an
unregistered generated `dependency_verification_N` worker input port.

The correction keeps the authorities independent and explicit. Every decision
successor now has a `plan_verification_report` port for the one passing
`semantic_stage=plan_verification` report that evaluated its exact accepted plan.
The existing `verification_report` port independently gates horizon progress:
horizon one requires the same exact plan report, while later horizons require a
passing verifier from the exact preceding batch key and planning horizon. The
resolved public context preserves the accepted plan's requirement alias order
and ordered source-record provenance instead of deriving either from persistent
map iteration. Same-horizon amendments bind their new independent verifier while
retaining the prior-batch gate, and later successors carry that amendment
verifier unchanged.

For decision-v1 initial planning, discovery now freezes the deterministic first
successor identity but does not materialize the successor before a plan exists.
The controller validates the implementation-plan answer, derives batch one from
the accepted ordered aliases, dry-runs its exact successor patch at stage time,
and atomically publishes that patch with the accepted plan during finalization.
The validator accepts only that predetermined successor topology. Legacy
non-decision construction remains unchanged, exact selectors were not weakened,
and failed/missing/stale/wrong plan or prior-batch authorities produce no
compiled effects. The generated dependency-verification worker ports now have an
explicit `VerificationReport` contract.

Behavior-first and product-real proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_successor_amendment_decision.py \
  tests/unit/test_initial_planning_decision.py \
  tests/unit/test_graph_decisions.py \
  tests/unit/test_decision_schema_consumers.py \
  tests/unit/test_reliable_plan_region_constructor.py
# 130 passed in 3.68s
# Includes shared/disjoint horizon-two resolve+compile, eight negative
# missing/failed/stale/wrong authority cases, ordered disjoint amendment,
# same-horizon exact amendment verification, accepted patch submission, and
# amendment-verifier retention on the generated third horizon.

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py
# 13 passed in 51.64s
# Disposable SQLite + GraphController + real dispatch/finalization proves
# discovery -> plan publication -> exact first successor. The disjoint r1/r2
# case resolves, compiles, and submits batch one through the production command
# boundary; failed verification, post-answer mutation, replay, and cancellation
# cases remain effect-safe.
```

Static and boundary proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format --check \
  <eleven correction source/test files>
# 11 files already formatted

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check \
  <eleven correction source/test files>
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

Correction final source/test hashes before this ledger update:

```text
af3369f7af0411d34406533de17481bb19508a6da12e2ccc6cd16f06d1ca11a2  src/orchestrator/graph/decisions.py
073bfcc705069f05a007194829c4677fc92cdb5da68dd3bf0fda0dc834e020a4  src/orchestrator/graph/macros.py
dac09f78c6b6ec51f021761e370c99c0bdb7b33e027ea1c344e1eea8415e3964  src/orchestrator/graph/contracts.py
47b883652fe871489ddbd101c750bb414fb257c692c5b67649cbac97433b6668  src/orchestrator/graph/patch_validator.py
36882dd92f03cbb03eb0aca55fae3545c6e982b76b44e45305686cda3e024ae7  src/orchestrator/graph/_commands.py
62ccc462ad00709d818a5b16d64c1b5ff16fc22e1e8534975cfe581d8ec75156  src/orchestrator/graph/models.py
7440f8c0128662ebc066a24f3bc713f8d1c95a9a45b304672be89c970d65c824  src/orchestrator/graph/payload_registry.py
48690ae389cbb4d4ce83dce3f7cb29a1d0ab8b959fd920ad01f96fd8b428641a  src/orchestrator/graph/commands/boundary.py
e8dc4729041faa48d4666d7aefdf06d7d1973404870de95d07da492cd5d4f42d  tests/unit/test_successor_amendment_decision.py
2f1fff0faa81963191fd2a9050ae1c96878d597fb377b568c2b6df1fa5a4738c  tests/unit/test_initial_planning_decision.py
46382a6afcf793e9b687954b251fc5d2baaa97712ae5a069a3fb3b72ba3e84b2  tests/integration/test_graph_decision_runtime.py
```

The prior ledger endpoint hashes for `decisions.py`, `macros.py`, the successor
unit test, and the decision-runtime integration test are the starting hashes for
this pass. Other files were already dirty Slice 3B-3D artifacts and did not have
a stable committed correction endpoint. No live server, live database, paid
probe, activation, historical resume, automatic retry, commit, Slice 3E, or
Slice 4A behavior was used. Independent review remains required.

## Full-gate flexible-JSON manifest correction, builder pass 4

Status: narrow builder correction complete; fresh independent review pending.

The final independent repository-readiness review exposed a missing permanent projection-manifest case for
the newly reachable `DecisionAnswerValue.answer` field. The flexible-JSON
manifest now names that field exactly, and its event-backed case constructs a
valid canonical `DecisionAnswerRecord` with `record_kind=graph_record`. The
field's required object root contains each shared nested object, array, string,
integer, boolean, and null probe. The existing parameterized closure therefore
proves recursive freezing before checkpointing, plain-JSON checkpoint
serialization, exact checkpoint restore equality, and recursive immutability of
the restored value. No runtime code changed.

Focused and immutable-projection closure proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_graph_projection_flexible_json.py --override-ini='addopts='
# 217 passed in 0.84s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest --run-slow -n 0 \
  tests/unit/test_graph_projection_behavior.py \
  tests/unit/test_graph_projection_flexible_json.py \
  tests/unit/test_graph_projection_replay_equivalence.py \
  tests/unit/test_graph_projection_immutability.py \
  tests/unit/test_graph_projection_queries.py \
  tests/unit/test_graph_projection_duplicate_ids.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_boundaries.py \
  tests/unit/test_graph_projection_performance.py --override-ini='addopts='
# 803 passed in 11.46s
```

Static and boundary proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format --check \
  tests/unit/test_graph_projection_flexible_json.py
# 1 file already formatted

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check \
  tests/unit/test_graph_projection_flexible_json.py
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

Correction hashes:

```text
9c311efc1eeef2788dda768b1cc535afa4059fd417113f5fd67127e22d69ece7  tests/unit/test_graph_projection_flexible_json.py (starting HEAD)
ae16342bd73dd3a584d5d879bf6286788d7a9f362e98fe77b921545f091e3206  tests/unit/test_graph_projection_flexible_json.py (corrected)
```

No live server, live database, paid probe, activation, historical resume,
automatic retry, commit, Slice 3E, or Slice 4A behavior was used.

## Complete-gate correction, builder pass 7

Status: legacy decision-applicability compatibility corrected; fresh independent
review and the parent-owned complete repository gate remain pending.

The next complete-gate attempt exposed one process-level recovery regression in
`test_schema_two_survives_checkpointed_two_process_dispatch_recovery`. The
fixture compiles a valid legacy routine snapshot and gives its worker the
pre-existing `semantic_stage=effectful_batch` marker used by the crash-barrier
target. Decision applicability resolved the exact snapshot successfully, but
then treated that stage name as if it selected decision-v1 and terminated the
child dispatcher with `legacy snapshot is bound to a malformed
decision-capable role or stage` before the first barrier.

Stage names predate decision-v1 and are not selection authority. The resolver
now validates the canonical target, exact snapshot record, edge, selector,
binding policy and frozen interaction selection through the unchanged
`_resolve_bound_interaction_contract` path, then returns `None` immediately when
the authoritative snapshot omits `agent_interaction_contract`. The obsolete
decision-stage allowlist and its legacy role/stage rejection were removed.
Selected decision-v1 targets still fail closed when their role/stage or
canonical contract is unrecognized, and malformed legacy snapshot/binding
authority still raises during exact binding resolution.

Behavior-first and product-real proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_crash_barriers.py::test_schema_two_survives_checkpointed_two_process_dispatch_recovery \
  --override-ini='addopts='
# before correction: 1 failed in 2.22s; child dispatch exited from
# resolve_decision_applicability before reaching crash-barrier slot 1

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_graph_decisions.py::test_valid_legacy_worker_stage_marker_does_not_activate_decision_contract \
  tests/unit/test_graph_decisions.py::test_selected_decision_contract_rejects_same_unrecognized_worker_role_stage \
  --override-ini='addopts='
# before production correction: 1 failed, 1 passed; the exact legacy worker
# was rejected while the same selected decision-v1 graph failed closed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_graph_decisions.py::test_valid_legacy_worker_stage_marker_does_not_activate_decision_contract \
  tests/unit/test_graph_decisions.py::test_selected_decision_contract_rejects_same_unrecognized_worker_role_stage \
  tests/unit/test_graph_decisions.py::test_resolver_rejects_decision_snapshot_for_invalid_target_role \
  tests/integration/test_graph_crash_barriers.py::test_schema_two_survives_checkpointed_two_process_dispatch_recovery \
  --override-ini='addopts='
# 4 passed in 6.13s after final formatting

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_graph_decisions.py \
  tests/unit/test_decision_schema_consumers.py \
  tests/unit/test_initial_planning_decision.py \
  tests/unit/test_successor_amendment_decision.py \
  tests/integration/test_graph_decision_runtime.py \
  tests/integration/test_graph_crash_barriers.py::test_schema_two_survives_checkpointed_two_process_dispatch_recovery \
  --override-ini='addopts='
# 136 passed in 61.77s
```

Static and boundary proof after final formatting:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format --check \
  src/orchestrator/graph/decisions.py tests/unit/test_graph_decisions.py
# 2 files already formatted

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check \
  src/orchestrator/graph/decisions.py tests/unit/test_graph_decisions.py
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

Stable pre-pass hashes come from the recorded Slice 3D endpoints; no later
correction pass listed either file as changed:

```text
af3369f7af0411d34406533de17481bb19508a6da12e2ccc6cd16f06d1ca11a2  src/orchestrator/graph/decisions.py
84dc64ac8b8a251c2e237e5bf38b657851fd66c7502751c43d7442032b3d4880  tests/unit/test_graph_decisions.py
```

Final source/test hashes before this ledger update:

```text
68257dbe4dc3dff67f7affac4c72aaa55c3ad03fb0add18a2bc2fb60bf5a7c07  src/orchestrator/graph/decisions.py
805d2804ff5c02947baaa374bb9dc299b3f424ca27010dec439a804a446d207f  tests/unit/test_graph_decisions.py
```

No live server, live database, paid probe, activation, historical resume,
automatic retry, commit, Slice 3E, or Slice 4A behavior was used. This pass did
not run the full pre-commit gate.

## Independent review closure

Status: S3B explicit-planner path, S3C, and S3D independently validated. The
single complete repository gate remains pending after this ledger is sealed.

Slice 3B review first found that decision submission could rebase protected
authority between dispatch and staging. The correction bound protected context,
schema, inputs, compilation, and decision base to the immutable dispatch
projection while allowing unrelated tail movement only through command-level
optimistic concurrency. A fresh review passed S3B-1 and S3B-2. S3B-3 remains an
explicit architecture gap rather than an invented policy: the frozen routine
contract does not authorize controller-only initial-brief bypass, so fully
supplied inputs retain the requested independent planner.

Slice 3C review found and corrected two command-schema parity defects. The final
generated schema matches the authoritative parser's `argv` / `cmd` / `command`
fallback behavior through pure schema validation, connected FastMCP, and actual
Codex JSON-RPC ingress. A fresh review passed S3C-1 through S3C-3, including
read-only plan creation, exact independent plan-verifier gating, failed-verifier
closure, and no Slice 4A typed-verification behavior.

Slice 3D required three fresh correction/review cycles. Reviewers found and the
builders corrected next-horizon scope and requirement binding, accidental human
gate scheduling, conflated plan and prior-horizon verifier authority, unstable
requirement alias ordering, premature all-requirement first-successor creation,
and a missing dependency-verification input contract. The final fresh review
passed S3D-1 through S3D-3 and the repository-readiness projection closure:

```text
focused decision compiler and plan tests: 130 passed
disposable SQLite/controller/dispatch decision runtime: 13 passed
scheduler, legacy boundary, macro, and acknowledgement recovery: 125 passed
deterministic successor/replay/lifecycle integrations: 13 passed
flexible-JSON manifest: 217 passed
full immutable-projection closure including performance: 803 passed
fresh final high-value Slice 3D/runtime/scheduler sample: 36 passed
ruff check .: passed
ruff format --check .: 784 files already formatted
pyright: 0 errors, 0 warnings
graph projection boundary checker: passed
git diff --check: passed
```

All final review passes were read-only and verified stable recorded hashes. No
tracked files will be edited after this point; the complete repository gate
result will be reported directly to the user.

## Complete-gate correction, builder pass 5

Status: two narrow gate failures corrected; complete repository gate rerun pending.

The first complete-gate attempt exposed two integration defects rather than a
decision-lifecycle failure:

- `test_discovery_and_plan_verification_macros_preserve_read_only_typed_handoff`
  failed because the direct legacy `create_discovery_region` macro had started
  requiring an internal `scope` argument which its public legacy argument model
  does not expose. The macro again defaults omitted legacy scope to
  `repository analysis`. Internal decision-v1 compilation still supplies its
  exact frozen scope, proven as `docs/spec.md` by the initial-planning test.
- the `module-imports` hook rejected `tests/unit/test_cli_agent.py` for importing
  a private helper through `orchestrator.runners.agents.claude_cli.agent`. The
  helper is now the public, documented `is_owned_terminal_answer_stop`, exported
  from `orchestrator.runners`; its production caller and test use that one API.
  A scan of all Python files under `src`, `tests`, `scripts`, and `examples`
  found no other import-boundary violations.

Behavior-first and focused proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q \
  tests/unit/test_reliable_plan_execution_semantics.py::test_discovery_and_plan_verification_macros_preserve_read_only_typed_handoff \
  tests/unit/test_cli_agent.py::test_terminal_answer_stop_requires_owned_sigterm_observation
# before correction: 1 failed, 1 passed; legacy discovery rejected missing scope

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_module_imports.py tests/unit/test_cli_agent.py
# before correction: private runners subpackage import rejected

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_reliable_plan_execution_semantics.py::test_discovery_and_plan_verification_macros_preserve_read_only_typed_handoff \
  tests/unit/test_initial_planning_decision.py::test_discovery_brief_compiles_exact_bound_inputs_into_complete_initial_topology \
  tests/unit/test_cli_agent.py::test_terminal_answer_stop_requires_owned_sigterm_observation \
  --override-ini='addopts='
# 3 passed in 0.38s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_reliable_plan_execution_semantics.py \
  tests/unit/test_initial_planning_decision.py \
  tests/unit/test_cli_agent.py --override-ini='addopts='
# 108 passed in 1.37s
```

Static and boundary proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format --check \
  <five corrected source/test files>
# 5 files already formatted

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check \
  <five corrected source/test files>
# All checks passed

rg --files src tests scripts examples -g '*.py' | xargs env \
  UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_module_imports.py
# exit 0

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

Pre-correction and corrected hashes:

```text
073bfcc705069f05a007194829c4677fc92cdb5da68dd3bf0fda0dc834e020a4 -> edec4816b01f12c409cae2746973c347957d478c7818b1b8069fe495b97eeb8d  src/orchestrator/graph/macros.py
7647398d0366414b9feaf9a80755f9148fa3c24f26b2f85901c75217101ceba4 -> de6ce0f55720859b95690a30cc7fd070ef212cecbdbbe8638a23683c15bb4ece  src/orchestrator/runners/agents/claude_cli/agent.py
a1f3bdc34ef0f202a5991c4ee0e673cf5ad3a1fc0384384260f76be2d5fb08a9 -> 0d7f6e96d7b0eacf7480ac76ce281a4a5588e2184879dc1a583c5f9072817b18  src/orchestrator/runners/__init__.py
e3cd57e7eb08c75aa1a2c64ca270811f78f17ed0f3ac0b3bdb4676ec43a7be52 -> 52f1ea52a4c00712402e1015717e8acb01c0b21b76fbd4b875171976d31d2113  tests/unit/test_cli_agent.py
0d6438445a2d73520efc70327a375ec01fa23439155637b4736a85c801f5246a -> a1ebb4c1fcd1ccffd3e95125d6d1d51d02315ec91f487e7474b8261a69965667  tests/unit/test_reliable_plan_execution_semantics.py
```

No live server, live database, paid probe, activation, historical resume,
automatic retry, commit, Slice 3E, or Slice 4A behavior was used. The parent
supervisor owns the single complete repository gate rerun.

## Complete-gate correction, builder pass 6

Status: canonical decision-answer event coverage corrected; complete repository
gate rerun remains pending with the parent supervisor.

The second complete-gate attempt exposed a test-manifest omission. The canonical
`OUTPUT_RECORD_MODELS_BY_TYPE` registry includes `decision_answer`, but the
shared `OUTPUT_RECORD_CASES` fixture and its independent canonical-record type
set had not been extended when that record became an accepted output. The
fixture now contains a valid explicit `DecisionAnswerRecord` specimen with its
graph-record ownership, decision port, matching schema versions, canonical
discovery schema and answer hashes, consequence patch, and bound input IDs. The
canonical-record ownership set now names the same type. Runtime behavior was
not changed.

Behavior-first and focused proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_output_record_event_payloads.py::test_output_record_matrix_tracks_explicit_record_type_map \
  --override-ini='addopts='
# before correction: 1 failed; decision_answer was missing from OUTPUT_RECORD_CASES

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_output_record_event_payloads.py --override-ini='addopts='
# 30 passed in 0.26s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_output_record_event_payloads.py \
  tests/unit/test_graph_projected_records.py \
  tests/unit/test_graph_projection_flexible_json.py \
  tests/unit/test_graph_decisions.py --override-ini='addopts='
# intermediate: 319 passed, 1 failed; the independent canonical-record set had
# the same missing decision_answer member
# corrected: 320 passed in 2.09s
```

Static and boundary proof:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format --check \
  tests/unit/test_output_record_event_payloads.py \
  tests/unit/test_graph_projected_records.py
# 2 files already formatted

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check \
  tests/unit/test_output_record_event_payloads.py \
  tests/unit/test_graph_projected_records.py
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

Pre-correction and corrected hashes:

```text
16cb57b49880ca01d075e2425eed260a5567f1cf4d2b0097aa4cd21932fc7adb -> e52e0234fd2251c4fdc38d260c29e70a1d51d4443854933053884491cd9bd4b2  tests/unit/test_output_record_event_payloads.py
2205a57fb30ddd9a34ebb9c970cf652fdc5789ae7be131092587795268381680 -> d362595496a5a3ed64c579cac4091c184f1bf7560558d445eaa4c820f60029de  tests/unit/test_graph_projected_records.py
```

The same sandboxed gate attempt also encountered a DNS-resolution failure while
trying to obtain `hatchling`. That is an environment/network failure unrelated
to the decision runtime or this test-manifest correction; the parent supervisor
will rerun the complete gate with the required escalation. This pass did not run
the full pre-commit gate.

No live server, live database, paid probe, activation, historical resume,
automatic retry, commit, Slice 3E, or Slice 4A behavior was used.
