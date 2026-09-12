# Slice 2 implementation ledger

Status: complete

Scope: one complete `decision-v1` reliable-plan successor answer through the
existing staged-submission, controlled terminal-closure, witnessed atomic
finalization, graph publication, completion, and outbox lifecycle. Historical
legacy behavior remains unchanged. No live server, live state, paid execution,
historical resume, activation, or commit is authorized for this slice.

## Functional requirements

| ID | Required behavior | Acceptance / product-real proof | Regression evidence | Status | Remaining gap |
|---|---|---|---|---|---|
| S2-1 | Production dispatch resolves a trusted `decision-v1` successor request from the exact routine snapshot, selected batch, accepted built-in plan and verifier evidence, requirements, check policy, and remaining horizon. | A disposable compiled/run graph reaches the successor through normal dispatch and advertises one generated `BatchDecision` submission contract with immutable protected bindings and no model-authored internal identity. | Resolver/compiler tests and the disposable Git/SQLite production dispatch fixture. | Pass | None for Slice 2. |
| S2-2 | A model supplies one strict `BatchDecision` via `submit(outputs=...)`; the graph-owned pure compiler derives deterministic decision record, complete successor region, effect IDs, read set, requirements, checks, continuation, and final horizon by sharing the legacy macro expansion. | A scripted supported transport submits `proceed`; dry-run validates the exact prospective topology without publishing it, and no constructor/raw-patch/finalization tool is exposed. | Determinism, exact-record, 10+ requirement ordering, notes, and topology regressions. | Pass | Amendment and blocker compilation remain Slice 3 scope. |
| S2-3 | Staging uses the tagged `decision-submission-v1` CAS envelope and bounded canonical answer/context; identical delivery/answer is idempotent, a conflicting answer is rejected, and no graph effects or downstream dispatch publish at acknowledgement time. | Inspect disposable store/projection immediately after staging, including lost acknowledgement and duplicate delivery cases. | Real filesystem CAS, context-integrity, duplicate/conflict, and effect-free stage assertions. | Pass | None for Slice 2. |
| S2-4 | Durable staging triggers adapter-controlled terminal closure without another model action; further work is impossible, and only the exact typed terminal-answer completion cause plus unchanged final boundary can authorize success. | Scripted model attempts work after answering and is stopped; lost acknowledgement still closes; generic return, interruption, process loss, failed return, and post-answer mutation do not publish effects. | Codex acknowledgement-loss/post-answer-tool tests and real Claude SIGTERM/timeout process tests. | Pass | No paid provider execution was authorized or run. |
| S2-5 | Witnessed finalization revalidates bindings, cancellation/active authority and prospective planner completion, then atomically publishes the accepted decision, all graph effects, node completion, execution finalization, and outbox work in one controller/store transaction. | Disposable SQLite/event-store observation proves one transaction, exact final horizon, one finalized execution, and no intermediate/downstream publication. | Production controller/outbox fixture plus the existing controller rollback injection. | Pass | None for Slice 2. |
| S2-6 | Replay and races are safe: duplicate finalization yields one effect set; unrelated graph movement can retry locally; changed plan/evidence/authority cannot reuse the staged answer; cancellation on either side of the serialized boundary has the specified winner, including cancellation after witness. | Crash/restart and cancellation fixtures cover pre-stage, post-stage, both sides of finalization, and post-witness; exact input changes reject while unrelated movement completes without another model execution. | Bound/unrelated staleness, fresh-controller replay, duplicate finalization, and finalization-wins/cancellation-wins cases. | Pass | None for Slice 2. |
| S2-7 | `decision-v1` is excluded from `accepted_graph_patch_before_agent_death`; a staged answer, successful tool response, or accepted dry-run alone cannot finish after runner failure. | Unexpected death after each pre-finalization milestone leaves the node incomplete and effects unpublished; a legacy accepted-patch recovery control still passes. | Decision retry negative and legacy completion positive controls. | Pass | None for Slice 2. |
| S2-8 | Supported Codex Server and Claude CLI per-execution graph MCP surfaces use the same shared submit schema and answer semantics; the successor catalog contains no graph constructor, raw patch, or separate finalization tool. Unsupported OpenHands and CLI Codex graph selections remain rejected, while legacy/non-graph behavior remains intact. | Inspect both real generated catalogs and invoke their submit validators in disposable fixtures; run unsupported-runner and legacy constructor+submit controls. | Self-contained FastMCP schema, submit-only Codex catalog, transport, preflight, and legacy suites. | Pass | None for Slice 2. |
| S2-9 | Slice evidence is complete and bounded: starting/final hashes, changed files and removed duplication, exact commands/results, accepted contract changes, independent review, and remaining concerns are recorded without modifying historical evidence. | This ledger is updated after implementation and fresh review; production-real proof uses disposable Git/SQLite and scripted transports only. | Focused ruff, pyright, graph-boundary checker, diff check, and slice regression bundle; no full repository gate at this intermediate slice. | Pass | Full unmodified repository gate remains reserved for Slice 6. |

## Starting source hashes

Captured before Slice 2 source edits. The Slice 1 final hashes and
`docs/reviews/recovery-successor-validation-result.json` are the comparison
baseline; no prior recovery artifact will be rewritten.

```text
affe517dc2a03a57feb4467d5809cfebc394a78f0c25fe45735a31bf877f83d5  src/orchestrator/graph/decisions.py
7f8371106e513c8cd8abe727299315a4bbcb137692dfbab9fa00c1ae9f9a997b  src/orchestrator/graph/macros.py
fed4539453ae6da61dcf9189f61af56bcf61bbc7191a14219a33a4cdcee45b28  src/orchestrator/graph/callbacks.py
6258cdc99cd266aea5cf888e253425288908d52f5117efa48a576365844acf11  src/orchestrator/graph/patch_validator.py
2bacd8ea04d7cd285994052f867b11bf391fc7ad23160e9d1670c0b501c3335e  src/orchestrator/graph/commands/boundary.py
e8da36e7529ddcfc8bb3602a7c2ba455b27fd897e048c2589ea01d29cdc56402  src/orchestrator/graph/commands/__init__.py
76952d78abfa43ef145fc43fb4d7a17f9ee9283c0a5de388eb590b5bd3bcb16a  src/orchestrator/graph/_commands.py
93512fa2e2bf0fe563bb86439ed4aad822dd3a8dcb2e1a6ab49ec890172cbd0b  src/orchestrator/graph/__init__.py
26c87c8dbfe13d520eed47fc3746ead8fe40ef161e1cd0a9e562e50c1bda6982  src/orchestrator/graph_runtime/dispatch.py
df44e8f4197b28d1abc932a7e48f84f583cac160632e624939eaf470eeedc57f  src/orchestrator/graph_runtime/controller.py
a565eeed47e934c636699e28667cef9414b836f88354d1aa2cca76e53da296d6  src/orchestrator/graph_runtime/store.py
579be9260942794528f60c3d2a460908d1a93630ae2b4fd1e32422e5afe6e141  src/orchestrator/graph_runtime/graph_mcp_tools.py
cce9b9b80cc9c2641cb8f9abf29625a6e24d3cdbce9c8516214e12380411c53c  src/orchestrator/graph_runtime/prompts.py
5131df433ed88e74d89db4d1871fc21ec8bbde28231682778e7c1a9e5cc0e5c7  src/orchestrator/graph_runtime/__init__.py
8310eeebae90de12a0bd5342f61c73b6564c97cf2414332965e4af97dbf16a26  src/orchestrator/runners/types.py
803d0b95e57007851a16b91a3b51b55376ec56295a12879ae5ee882e47b29782  src/orchestrator/runners/submission.py
3d93973dcf27f3dc0f29543f7fd5c10fd6150f24a0443a1df33c250b74724e1c  src/orchestrator/runners/agents/codex/agent.py
6fcf9a1292cc771361cdbbca9b884d35a84ec8c5a368805b0599b783faa8d2a5  src/orchestrator/runners/agents/codex/common.py
88287baa11b4d71f44213c068fab2792e26c69e3bb3d9952dd6e78fd9ba5aa49  src/orchestrator/runners/agents/codex/__init__.py
```

## Implementation record

Implemented the first complete `decision-v1` vertical slice for reliable-plan
successor `proceed` decisions:

- `graph/decisions.py` now owns exact successor-context resolution, the generated
  `BatchDecision` schema/hash, deterministic compilation, canonical decision
  records, and an explicit authority read set. It preserves exact bound
  snapshot, plan, verifier, and requirement records and numeric requirement
  order.
- `graph/macros.py` exposes one shared pure expansion seam. The decision compiler
  supplies trusted exact record identities and stamps runtime-owned
  `implementation_notes`; the legacy constructor remains supported.
- Boundary staging chooses the decoder from frozen graph authority, validates the
  tagged envelope, dry-runs the same compiler, and emits only the staging fact.
  Finalization revalidates CAS context and read authority, evaluates completion on
  the prospective graph, and returns one decision/effect/completion event batch.
- Controller/store support loads the bounded decision tail and preserves the
  decision answer schema during replay while retaining the existing single SQL
  event-plus-outbox transaction.
- Codex Server uses a submit-only decision catalog, trusted invocation identity,
  best-effort post-stage acknowledgement delivery, refusal of later tools, and a
  witnessed owned terminal with a 180-second bound. Claude CLI/FastMCP uses the
  same self-contained submission schema and an owned SIGTERM/timeout/SIGKILL
  fail-closed lifecycle.
- Decision-v1 recovery cannot use
  `accepted_graph_patch_before_agent_death`; legacy recovery behavior is retained.

The implementation deliberately does not add OpenHands or CLI Codex graph
support, schema migrations, activation, live-history conversion, or Slice 3
decision branches.

Final source/test hashes:

```text
f682ddf8201bcec97b4bee67397aca4c9bbe9e53ddac3100be585d6ff0f31344  src/orchestrator/graph/decisions.py
096022acecf0bad081b92e8b8aa9565f8b84ac9685e24b56a02dfc56dbf6c30e  src/orchestrator/graph/macros.py
9cf3392642292014f83f83345f5ec3038d2b84e03b940e3966173e0016e52b6a  src/orchestrator/graph/contracts.py
26e63053af71144f458b6f6c90bc4186185666f144a9597f1890ec259e04bb95  src/orchestrator/graph/models.py
ed36abbd36f2dce0fa3ee88268b2e173c4e1c7a003a45491c4a85f4076f7128f  src/orchestrator/graph/projection_models.py
e5bf61fe959fc901f0537b943ca5ea9e64d0960acf344e47376c02ca3525b293  src/orchestrator/graph/payload_registry.py
d8ec4916ab194d2f9a49cca10193fc43d5602b2681dc7a96e4d8abc2533f3e36  src/orchestrator/graph/_commands.py
7b33d444d5b2285df16adbaac579fcc252b23c2c49b618a690d8f1e6678b09c5  src/orchestrator/graph/command_models.py
b570e08bc54600c64e9e86ab36471abd777581d78cbffe6d91f36949b5fe45d6  src/orchestrator/graph/commands/boundary.py
0240f217707c032d23106c725be409035921d06f74a46e842502f6034ca1fcb7  src/orchestrator/graph/__init__.py
e1cc9c73cfbac930f1bbb55245a33a3dd9e7fc7bd24a1c3d38eaada0c307bf37  src/orchestrator/graph_runtime/controller.py
129de17ed6df1a04b18fd54595af6902977f6058375ec56abf22a9f5dde10a3a  src/orchestrator/graph_runtime/dispatch.py
d5396a53eda5ead72d031ec98b9ef089b61e17b07972e53e26e589f27650ceb5  src/orchestrator/graph_runtime/store.py
5999cb3ad2a645a537e85be5b2453fb151e2bdacddac7fbda1f6f4e109b4f1c8  src/orchestrator/graph_runtime/graph_mcp_tools.py
cc16813af097c5e40ccbed1e9a1dce91c7067eac4eb22adaad89ebd669c1a43e  src/orchestrator/graph_runtime/prompts.py
4e2dcd19f97bb81900a8f8d4712215bab257c90a17c92afcc9575f736816ab54  src/orchestrator/runners/types.py
20438bd0f80345e3feffe64bd65b5988eb615115ff6ada24597d74e2e231eb8d  src/orchestrator/runners/submission.py
d8c04a1230db139a4bc4c0ec7711645fd5b6cec3cec7c14349297a17f5932e43  src/orchestrator/runners/agents/codex/agent.py
aa75c45c6c77c481b22f4690bf0858a10c91bd3d5b60138595383872c8ee0104  src/orchestrator/runners/agents/codex/common.py
bcd9fea5368f434dab3fe009ce5cba7e50230f226a6e82dfc556f5cc58724427  src/orchestrator/runners/agents/claude_cli/agent.py
cf1c183dbae7b87f087da5ad03bc7c3fc84bd5f39b4e7694e56ad7156dcbe19f  tests/unit/test_graph_decisions.py
adb0837f1d36ba1f1f9cd9f663982a69fce91a8f150e85d5590aab0d890a09b5  tests/unit/test_graph_mcp_tools.py
d077db5abe8adb88a0e93f42a0cbe13786f542d128c69df17c3955aae80c3521  tests/unit/test_codex_server_transport.py
8103481a95fa5d3e4b6450bbe2fedcebce4415cc9bac2041fa37d408e344e25c  tests/unit/test_cli_agent.py
f15f59766c18cba60182063a4817f0de8fdd96f36a51fd4ca6d7451169de5418  tests/unit/test_graph_runner_boundary_commands.py
ddd271898527f14ab8b9540e2224272f6d500211cd29cb0a93670977297ca866  tests/integration/test_graph_decision_runtime.py
```

## Validation evidence

Baseline before implementation:

```text
353 passed, 2 failed, 1 deselected
```

The two failures were the pre-existing Slice 1 command-diagnostic mismatch for
blank/malformed command definitions. Slice 2 restored the canonical
`invalid_command_definition` code and bracketed `checks[0]` path; the same
baseline files are now green.

Final expanded focused command:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -n 0 -q \
  tests/unit/test_graph_decisions.py \
  tests/unit/test_reliable_plan_region_constructor.py \
  tests/unit/test_graph_dispatch_on_output.py \
  tests/unit/test_graph_runner_boundary_commands.py \
  tests/unit/test_reliable_plan_tool_exposure.py \
  tests/unit/test_graph_mcp_tools.py \
  tests/unit/test_codex_server_transport.py \
  tests/unit/test_cli_agent.py \
  tests/integration/test_codex_dynamic_tool_receipts.py \
  tests/integration/test_graph_patch_acknowledgement_recovery.py \
  tests/integration/test_recovery_deterministic_lifecycle.py \
  tests/integration/test_recovery_successor_planner_probe.py \
  tests/integration/test_graph_decision_runtime.py
```

Result: `379 passed, 1 deselected, 11 warnings in 79.11s`.

The independent final review additionally ran a broader Slice 2 matrix covering
controller rollback/no-effects-before-commit and legacy/unsupported controls:
`470 passed, 10 warnings`.

Static validation:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check <Slice 2 files>
# All checks passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python scripts/check_graph_projection_boundaries.py
# exit 0

git diff --check
# exit 0
```

The 11 focused-suite warnings are the retained Pydantic JSON-schema warning from
legacy tool models and one retained frozen-cache-root serializer warning; neither
is new Slice 2 failure evidence.

## Independent review

Four gap/validation cycles were completed. The first three validator passes
reproduced and drove fixes for authority-selected decoding, requirement
staleness, exact-record compilation, context CAS verification, Claude owned-stop
semantics/deadline, self-contained FastMCP schemas, Pyright complexity, product
transaction/race evidence, Codex acknowledgement loss, and post-answer tool
refusal.

The final independent verdict is **PASS**, with S2-1 through S2-8 all passing and
no required Slice 2 acceptance left unproved. It directly re-ran the prior Codex
acknowledgement-loss and post-answer-tool repros, observed
`terminal_answer_completed`, verified the submit-only decision catalog, and ran
both product integration outcomes (`finalization-wins` and
`cancellation-wins`).

The review found that a decision-specific injected SQL rollback test is not a
blocking omission: decision finalization returns one planned event batch and
uses the same controller transaction already covered by the forced outbox-insert
rollback test. The product fixture independently proves zero partial effect sets
under either serialized winner.

## Remaining concerns

- This was the focused Slice 2 gate. The implementation plan reserves the one
  complete, unmodified repository gate for Slice 6.
- Scripted/injected runner transports and real local subprocesses were used; no
  paid model/provider execution was authorized or performed.
- Slice 3 owns successor amendment/blocker compilation and the remaining mixed
  reliable-plan decision roles.
- The worktree remains intentionally uncommitted and contains the earlier
  recovery slices; no activation or historical-state mutation was performed.
