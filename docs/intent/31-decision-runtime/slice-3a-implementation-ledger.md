# Slice 3A implementation ledger

Status: complete

Scope: consolidate every `decision-v1` schema and authored-shape consumer across
runtime prompts, planner tool routing, Codex dynamic tools, Claude/FastMCP graph
tools, and the shared submission boundary. This slice adds no decision lifecycle
or new runner support and preserves all legacy catalogs and schemas.

## Functional requirements

| ID | Required behavior | Acceptance / product-real proof | Regression evidence | Status | Remaining gap |
|---|---|---|---|---|---|
| S3A-1 | Decision packets describe the substantive question, frozen evidence, available choices, and the generated answer schema from the canonical graph-owned model. | The real compiled successor fixture produces a `decision_packet` containing the question, aliased requirement/batch/check evidence, available dispositions and generated `BatchDecision` schema, without internal record/node IDs or legacy constructor fields. | Focused prompt and decision-model suites. | Pass | None for Slice 3A. |
| S3A-2 | The canonical submission schema is the sole authored-value shape consumed by prompts, Codex dynamic tools, and Claude/FastMCP submit validation. | One generated sentinel contract reaches the prompt, Codex catalog and FastMCP catalog; an in-memory MCP client/server round trip advertises the exact schema, accepts the valid value and rejects missing/unknown/extra values before callback. | Schema propagation, five-case rejection parity, valid parity and real MCP protocol tests. | Pass | None for Slice 3A. |
| S3A-3 | Decision-v1 prompts and catalogs remove constructor/raw-patch/finalization sequencing and mutation tools while preserving useful task/evidence guidance. | Production Codex and Claude prompts retain the question/evidence guidance and one typed `submit` workflow; stale constructor/raw-patch allowlists and required-tool flags cannot expose a graph mutation callback in either catalog. | Prompt isolation, shared dispatch routing, Codex transport and FastMCP catalog tests. | Pass | Slice 4A must apply the same precedence when typed verifier decisions are activated. |
| S3A-4 | Legacy schemas, tool catalogs, and submit sequencing remain byte-for-behavior compatible, and unsupported reliable-plan runner preflight remains unchanged. | Legacy contracts default explicitly to `legacy`; legacy constructor/catalog behavior, legacy FastMCP handling and unsupported runner controls remain at the reviewed Slice 2 boundary. | Focused legacy tool-routing, runner-capability and unsupported-preflight suites. | Pass | None for Slice 3A. |
| S3A-5 | The consolidation removes demonstrated duplicated shape/sequence ownership without introducing a second registry, lifecycle, runner capability, or cross-module boundary violation. | Providers classify only the trusted `SubmissionContract.interaction_contract`; shared renderer/validator helpers replace semantic-role sniffing; FastMCP parity uses public `list_tools`/`call_tool`, and all new imports use module public APIs. | Three independent review passes; Ruff, Pyright, graph projection boundary checker and `git diff --check`. | Pass | None for Slice 3A. |

## Starting source hashes

Captured before Slice 3A edits. These match the reviewed Slice 2 final hashes
where recorded; `planner_tools.py` and the current dispatch test are included as
additional Slice 3A baselines. Historical recovery evidence is not modified.

```text
cc16813af097c5e40ccbed1e9a1dce91c7067eac4eb22adaad89ebd669c1a43e  src/orchestrator/graph_runtime/prompts.py
685f9f51ae76d51b5295a88882d78e80fea77dd7d68f9527427afcea5e02a8c8  src/orchestrator/runners/planner_tools.py
aa75c45c6c77c481b22f4690bf0858a10c91bd3d5b60138595383872c8ee0104  src/orchestrator/runners/agents/codex/common.py
5999cb3ad2a645a537e85be5b2453fb151e2bdacddac7fbda1f6f4e109b4f1c8  src/orchestrator/graph_runtime/graph_mcp_tools.py
20438bd0f80345e3feffe64bd65b5988eb615115ff6ada24597d74e2e231eb8d  src/orchestrator/runners/submission.py
4e2dcd19f97bb81900a8f8d4712215bab257c90a17c92afcc9575f736816ab54  src/orchestrator/runners/types.py
129de17ed6df1a04b18fd54595af6902977f6058375ec56abf22a9f5dde10a3a  src/orchestrator/graph_runtime/dispatch.py
d8c04a1230db139a4bc4c0ec7711645fd5b6cec3cec7c14349297a17f5932e43  src/orchestrator/runners/agents/codex/agent.py
bcd9fea5368f434dab3fe009ce5cba7e50230f226a6e82dfc556f5cc58724427  src/orchestrator/runners/agents/claude_cli/agent.py
ed98c64cb3af3ffb5a12fd519def3585e14c73a8b48a087cf066f49321d69d96  src/orchestrator/runners/__init__.py
adb0837f1d36ba1f1f9cd9f663982a69fce91a8f150e85d5590aab0d890a09b5  tests/unit/test_graph_mcp_tools.py
d077db5abe8adb88a0e93f42a0cbe13786f542d128c69df17c3955aae80c3521  tests/unit/test_codex_server_transport.py
8103481a95fa5d3e4b6450bbe2fedcebce4415cc9bac2041fa37d408e344e25c  tests/unit/test_cli_agent.py
dcaf0f24d74fc7a891b823ad71d032417c76006607c8d6626ed5adab5aa0e9d9  tests/unit/test_graph_dispatch_on_output.py
cf1c183dbae7b87f087da5ad03bc7c3fc84bd5f39b4e7694e56ad7156dcbe19f  tests/unit/test_graph_decisions.py
```

The additional production baselines come from the reviewed Slice 2 final
ledger and, for unchanged `runners/__init__.py`, the Slice 1 final ledger.

## Implementation record

Slice 3A consolidated the shared decision consumers without adding a new
decision family, lifecycle or runner capability:

- `SubmissionContract` now carries an explicit, default-legacy
  `interaction_contract`. Production dispatch sets `decision-v1` only after the
  graph-owned applicability resolver accepts the frozen snapshot and successor.
- `runners/submission.py` owns the shared decision predicate, self-contained
  submit schema, complete-argument validator and schema-derived prompt
  instruction. Providers no longer infer the interaction from semantic role,
  schema name or payload shape.
- The runtime prompt and durable prompt summary share a decision packet derived
  from the resolved batch context and generated `BatchDecision` schema. It
  exposes the substantive question, bounded evidence and choices while omitting
  graph/record identities and legacy mutation sequencing.
- Decision mode takes precedence over stale reliable-plan tool flags. Codex and
  FastMCP expose only the typed `submit` callback, and both provider prompts
  retain evidence guidance without constructor, patch, checklist or separate
  finalization instructions.
- A decision-specific FastMCP adapter overrides the public `list_tools` and
  `call_tool` boundaries so the real protocol advertises and enforces the
  canonical root schema. It does not access FastMCP private fields. Legacy
  FastMCP registration and validation behavior remains unchanged.
- `route_graph_tool_call` is exported as the unambiguous public name for the
  existing graph router; the existing Codex `route_tool_call` export and legacy
  routing remain intact.

Changed files for Slice 3A:

```text
src/orchestrator/graph_runtime/dispatch.py
src/orchestrator/graph_runtime/graph_mcp_tools.py
src/orchestrator/graph_runtime/prompts.py
src/orchestrator/runners/__init__.py
src/orchestrator/runners/agents/claude_cli/agent.py
src/orchestrator/runners/agents/codex/agent.py
src/orchestrator/runners/agents/codex/common.py
src/orchestrator/runners/planner_tools.py
src/orchestrator/runners/submission.py
src/orchestrator/runners/types.py
tests/unit/test_cli_agent.py
tests/unit/test_codex_server_transport.py
tests/unit/test_decision_schema_consumers.py
tests/unit/test_graph_mcp_tools.py
```

Final source/test hashes:

```text
a03953c16eacdb05f77cd7c24de18bf5a7f27dbe219be15407d9e3c8f0d80bdb  src/orchestrator/graph_runtime/prompts.py
2e4c607564b77dd8a6f96b608c3d75aea61c074ebb6df6d848eaab9ea8e8d3c1  src/orchestrator/runners/planner_tools.py
f04cfdde5623a24c2338e9043f974918b47d46ca143e74395b5e61fe7373f98e  src/orchestrator/runners/agents/codex/common.py
4a4cf8df695b9ee317a4052b62740d982c8cd0bf8b4ed786ede334958dd01eda  src/orchestrator/graph_runtime/graph_mcp_tools.py
d76b6cf3957c70a2168754cc3021c213cd472ba7dd83b779ed49a69e78abae08  src/orchestrator/runners/submission.py
0a3c25806da96828b093947a63aa8612b6d5978f1deeab0b866f48f9f738009f  src/orchestrator/runners/types.py
097eb1522cb357a3aad3a2c8911b0765d88efde1e39248ecd03ad8b9543d2a7e  src/orchestrator/graph_runtime/dispatch.py
5f2351f44b69561dc64fdc8c87fbfca1bbc1b8bd96805c7bd1938dfca2865ea4  src/orchestrator/runners/agents/codex/agent.py
7647398d0366414b9feaf9a80755f9148fa3c24f26b2f85901c75217101ceba4  src/orchestrator/runners/agents/claude_cli/agent.py
a1f3bdc34ef0f202a5991c4ee0e673cf5ad3a1fc0384384260f76be2d5fb08a9  src/orchestrator/runners/__init__.py
7b8ca368329226fe808e48a2d6fd527239ed7dc7db3443c79efdffc3bc230e9e  tests/unit/test_decision_schema_consumers.py
42b9308324c9a5a6b615d6016be2bef449ca1f31eb602726ca1c9f0a634cc8d2  tests/unit/test_graph_mcp_tools.py
0286a98bd8ded7f1f8bcc785b24ab904aa3548321ef23d7beb28a5456d0d5a6e  tests/unit/test_codex_server_transport.py
e3cd57e7eb08c75aa1a2c64ca270811f78f17ed0f3ac0b3bdb4676ec43a7be52  tests/unit/test_cli_agent.py
```

## Validation evidence

All Python commands used the required
`UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync` prefix and only
disposable/injected state.

Baseline before Slice 3A source edits:

```text
pytest -n 0 -q <decision/schema/catalog/prompt/legacy focused bundle>
302 passed, 1 deselected, 9 warnings
```

Behavior-first Slice 3A test:

```text
pytest -q -n 0 tests/unit/test_decision_schema_consumers.py
8 failed, 1 passed
```

The failures demonstrated the missing explicit interaction marker, constructor
precedence in decision prompts/catalogs, and FastMCP root-schema drift. A later
boundary test failed on private FastMCP tool-manager access before the public
adapter replaced it. An intermediate correction run found six legacy routing
failures caused by an ambiguous router export; the explicit
`route_graph_tool_call` alias corrected all six.

Primary builder regression bundle:

```text
pytest -q -n 0 tests/unit/test_decision_schema_consumers.py \
  tests/unit/test_graph_mcp_tools.py \
  tests/unit/test_codex_server_transport.py \
  tests/unit/test_cli_agent.py \
  tests/unit/test_graph_dispatch_on_output.py \
  tests/unit/test_graph_planner_packet.py \
  tests/unit/test_graph_decisions.py \
  tests/unit/test_reliable_plan_tool_exposure.py \
  tests/integration/test_graph_decision_runtime.py \
  tests/integration/test_graph_run_driver.py -k 'not slow'
325 passed, 25 deselected, 9 warnings
```

Correction passes additionally recorded `244 passed, 1 deselected` for the
focused decision/MCP/legacy unit bundle, `4 passed` for decision-runtime and
dispatcher integrations, and `14 passed` for the final import-only correction.

Fresh final-validator bundle:

```text
pytest -n 0 -q tests/unit/test_decision_schema_consumers.py \
  tests/unit/test_graph_mcp_tools.py tests/unit/test_cli_agent.py \
  tests/unit/test_codex_server_transport.py \
  tests/unit/test_reliable_plan_tool_exposure.py \
  tests/unit/test_graph_tool_routing.py \
  tests/unit/test_graph_dispatch_on_output.py::test_reliable_plan_codex_cli_rejected_before_runner_creation
147 passed, 1 deselected, 8 warnings

pytest -n 0 -q tests/unit/test_graph_driver_capability.py \
  tests/integration/test_graph_run_driver.py::test_driver_rejects_unsupported_graph_runner_before_seeding
3 passed, 2 deselected
```

Static validation:

```text
ruff check <Slice 3A production and test files>
# All checks passed

ruff format --check <Slice 3A production and test files>
# All files already formatted

pyright
# 0 errors, 0 warnings, 0 informations

python scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

The retained warnings are Pydantic JSON-schema warnings from existing FastMCP
tool-model defaults. No new warning category was introduced.

## Independent review

Three fresh validator passes were completed. The first found that the initial
FastMCP parity implementation mutated private FastMCP fields and imported a
runner type through a submodule; both were corrected. A proposed legacy
regression was withdrawn after comparing the recorded Slice 3A starting hashes
with the reviewed Slice 2 final state rather than git HEAD.

The second pass verified the public FastMCP adapter and all behavior, then found
one remaining public-import violation in the new test. A fresh builder corrected
that import without changing source behavior. The final independent verdict is
**PASS**: S3A-1 through S3A-5 and applicable review criteria 1–5 and 8–10 pass,
with no blocking finding.

## Remaining concerns

- The complete repository gate remains reserved for the final integrated slice.
- Slice 4A must explicitly apply the shared decision precedence when it activates
  typed verifier submissions so legacy `graph_grade` is not exposed there.
- `tests/unit/test_decision_schema_consumers.py` is intentionally untracked until
  an eventual separately authorized commit; it is present and included in all
  recorded Slice 3A validation.
- No live server, paid model execution, activation, historical resume, commit,
  or live database mutation is authorized for this slice.
