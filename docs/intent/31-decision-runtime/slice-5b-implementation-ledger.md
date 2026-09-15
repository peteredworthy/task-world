# Slice 5B implementation ledger

Status: implemented and validated.

Scope: durable decision-answer rejection accounting at orchestrator ingress.
The existing execution-attempt lifecycle remains the owner of execution and
runner facts; rejection facts are an additive sequence on that attempt. No
live server, database, paid model execution, or commit was used.

| ID | Required behavior | Acceptance evidence | Status | Remaining gap |
|---|---|---|---|---|
| S5B-1 | First invalid answer is counted at ingress, including normalization failures. | `record_decision_answer_rejection` persists the typed diagnostic, delivery identity, answer hash, and transport metadata before the callback returns its rejection. | complete | None. |
| S5B-2 | Second invalid answer exhausts the explicit two-answer allowance and prevents a third authored attempt. | Durable count is checked before normalization; exhaustion is classified as `budget_exhaustion`, closes recovery without redispatch, and both adapters stop/close the exact decision ingress after the terminal rejection. | complete | None. |
| S5B-3 | Same-delivery redelivery is free; a new delivery with identical content consumes another rejection. | Delivery identity hashes trusted execution/attempt/transport metadata; persisted rejection replay is idempotent by `delivery_id`, while answer content is hashed separately. The Codex transport regression covers the bounded decision path. | complete | None. |
| S5B-4 | Restart, checkpoint rebuild, cancellation, and reconnect do not reset counters. | Rejection count is read from the rebuilt graph projection, not process-local state; execution usage remains sourced from `node_usage_recorded` and is not incremented by rejection facts. | complete | None. |
| S5B-5 | Only failures that truly never reach trusted ingress remain diagnostic-only. | Codex and FastMCP retain the canonical advertised model schema, but complete authored argument objects are routed untouched into a trusted `SubmissionInvocation`; normalization/schema failures there are therefore receipt-captured and durably counted. A provider failure with no complete arguments remains transport-local. | complete | None. |
| S5B-6 | Graph-position-only/stale conflicts and post-staging conflicts do not spend rejection allowance or execution allowance. | Countability excludes stale/authority/position conflicts and skips durable rejection recording after staging; the full decision-runtime integration file passes. | complete | None. |
| S5B-7 | Existing configurable legacy limits remain intact. | Non-decision Codex submissions retain the existing three-rejection repair limit; reliable-plan rejection counting remains on its existing `GraphEventStore` path. | complete | None. |

## Implementation

- Added the typed `decision_answer_rejected` event, command, payload registry
  entry, immutable projection value, and replay/idempotency reducer path.
- Added trusted delivery identity and raw ingress-answer hashing without adding
  model-authored fields to the decision schema.
- Added durable count/exhaustion handling in dispatch, with provider-neutral
  failure diagnostics and recovery closure rather than automatic redispatch.
- Preserved staged-answer acknowledgement behavior: identical staged content
  can return its durable acknowledgement, while a conflicting retransmission
  is rejected without creating a new semantic attempt.
- Kept runner creation/usage observations separate from answer-attempt facts.

## Validation evidence

All commands ran from `worktrees/recovery-stabilization` with the disposable
uv cache `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv`.

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q \
  tests/integration/test_graph_decision_runtime.py --override-ini='addopts=' --tb=short
# 71 passed, 9 warnings in 251.91s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q \
  tests/unit/test_codex_server_transport.py::test_execute_stops_after_two_rejected_decision_submissions \
  tests/unit/test_codex_server_transport.py::test_execute_stops_after_three_rejected_submissions \
  --override-ini='addopts=' --tb=short
# 2 passed

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check src/orchestrator tests/unit/test_codex_server_transport.py
# All checks passed!

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright \
  src/orchestrator/graph src/orchestrator/graph_runtime/dispatch.py \
  src/orchestrator/runners/agents/codex/agent.py
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python \
  scripts/check_graph_projection_boundaries.py
# passed

git diff --check
# passed
```

## Merge-blocker correction pass

- Removed adapter-side pre-validation that prevented complete invalid Codex
  arguments from reaching canonical ingress.
- FastMCP advertises the same strict schema while bypassing its lossy argument
  coercion for the trusted decision callback; after exhaustion its instance
  rejects further calls without invoking the callback.
- Focused adapter/schema regressions are included in the `50 passed` correction
  suite; the complete graph-MCP unit file separately passed `13` tests. Current hashes: `codex/agent.py`
  `c896657c04e0f813f254308e9aa517951d61cd7140fb60cfb823cbd2a629dabd`;
  `graph_mcp_tools.py` `2f4b11caeb896cfa78e8c3834b2db398784e7f9a9d816a4d5d35608ca742ecec`;
  `test_decision_schema_consumers.py` `9d980d97c9e23497fc017a85185613b5be70be46422ff1859e135e3b8076c732`;
  `test_graph_mcp_tools.py` `8143e32a56f9445e5378cbbc1bb7ff4e680b6b0fe94f92f349f2524a24159292`.

## Source hashes

For graph and test files, the starting hashes are the SHA-256 of the matching
`HEAD` blob; the dispatch/error/Codex starting hashes are the final hashes from
the reviewed Slice 5A ledger because those files already contained Slice 5A
changes before this slice began.

```text
START
4f5650b7e1779008b747db52225c73454d56c6fb2b890c8bee1b072541ba7ae6  src/orchestrator/graph/command_models.py
afd728a5099b4fe204ed55f4b625da29bbc3b2db2d71684366360e7d449f82fb  src/orchestrator/graph/commands/boundary.py
746793b9509ac9c2afdfb45947bc461e6380b953b4234a66ceb43b67b94b5bc4  src/orchestrator/graph/event_registry.py
58e18a9147aa7cab24f71ae61b2ec18ce7f183bf22f51946251f8bf6d59e38eb  src/orchestrator/graph/models.py
7440f8c0128662ebc066a24f3bc713f8d1c95a9a45b304672be89c970d65c824  src/orchestrator/graph/payload_registry.py
ed36abbd36f2dce0fa3ee88268b2e173c4e1c7a003a45491c4a85f4076f7128f  src/orchestrator/graph/projection_models.py
2334f16475074a1e004907ff9d73e31f839f1cecf1f08998984a7d100101a651  src/orchestrator/graph/projections.py
4f20cf28bf7b4809d40d876a62e93d068193c811b8834444cc8378d09d7765f9  src/orchestrator/graph_runtime/dispatch.py
5c47d4472f202beef6acd5841888a69f11173799a0b3e8878756b7689ce56757  src/orchestrator/graph_runtime/errors.py
f6eadb701ea7656966704cff3c8527c1f7c4b5ffd042de91c2a2838c20485e12  src/orchestrator/runners/agents/codex/agent.py
0286a98bd8ded7f1f8bcc785b24ab904aa3548321ef23d7beb28a5456d0d5a6e  tests/unit/test_codex_server_transport.py

FINAL
2cf7137bf9a3a8fd5feadbf38ad7ea1a6931d92a27601b7c19c51cab533eecf9  src/orchestrator/graph/command_models.py
a092a513d4564196d638393b65853119835d5f521d4ba85e92cab50c21ae4f8a  src/orchestrator/graph/commands/boundary.py
536538f48dc2c75d2afda5d7a0531d68c8ecd7a4944fa3e986ea61a73da42712  src/orchestrator/graph/event_registry.py
e650c359137ffba427af46cb17e8d51eae72c22f76660f580df96e4359abf4c7  src/orchestrator/graph/models.py
4f70016c6404c1dec16e3ffdb45caadf7f2a3f6a4f6a3e4d5b25a90ad5619b60  src/orchestrator/graph/payload_registry.py
e9fba99073dcc784c4cd9e551ff5ce89b5be45113412021591047eaa1dcb2767  src/orchestrator/graph/projection_models.py
8e32d338e06d36e20fc5f70c34677582a10c32ea55a02c48a87f7bdf59f0623f  src/orchestrator/graph/projections.py
d4a6ae5660971a178d2c0c0b16fa0bc52d44f55852560a10630e4f215ffb874b  src/orchestrator/graph_runtime/dispatch.py
cd1c709d8dde89e80de949ea8466e354d9c045f975c69e40c6130ce6a3c9f8e5  src/orchestrator/graph_runtime/errors.py
34d24f7e84b769dc4df5f545f4c64dc9b88e2c2fd09e9e72a093afd221099723  src/orchestrator/runners/agents/codex/agent.py
7bf05a0c1ae8c254adfe96eb3c012d5ed5064ac491b0eab810c5592d68dfd08d  tests/unit/test_codex_server_transport.py
```

## Builder correction pass 2

- The connected FastMCP adapter now returns its first text content as raw
  `SubmissionAcknowledgement` JSON. Its canonical authored input schema is
  unchanged, fully received malformed arguments still reach trusted ingress
  untouched, and the incompatible inferred `{"result": string}` output schema
  is not advertised.
- The provider-neutral production bridge proves D1 is counted, exact D1
  redelivery is free, a fresh-controller restart retains the count, and a new
  delivery of identical invalid content is D2. D2 closes the session with the
  `stop` next action; recovery retains one execution and no third authored
  callback or runner creation occurs.
- The initial full decision-runtime run exposed this wire regression as exactly
  **15 failed, 58 passed**. The raw-text parsing regression and the complete
  focused adapter/schema bundle pass after correction.

The corrected full decision-runtime file reports **73 passed, 9 warnings**;
the warnings are the existing Pydantic non-serializable sentinel warning.
Current pass-2 hashes:

```text
e527b17be8f7e092049aba87396d107d902ebd18e7d2f48797f25889e74128c2  src/orchestrator/graph_runtime/graph_mcp_tools.py
ddd67d41a084a0097080405cc20476a8097a03d9b2d8fdef31f27ab3ae350fdd  src/orchestrator/graph_runtime/dispatch.py
1124e85c496a1662822a33893c5836e577ae77c1892bd7b04f27e4a651c3a20b  src/orchestrator/runners/__init__.py
30bdac42d9c265be044ae060ecca1c4534c859acfcb053f227491fc24dd243f5  src/orchestrator/runners/errors.py
01305832e5816dd76366db03b2da494b85e1ec34b3878b854bbe157aba62f63c  src/orchestrator/runners/agents/codex/agent.py
cd0ac6e936b2a5c632b530acd9abb572888b449d41f108ae6c35e895fd9a64a6  tests/unit/test_decision_schema_consumers.py
3d11d7c13f78909fb106272387f3893f27b4731953d7e78f96498afb12d6236a  tests/unit/test_codex_server_transport.py
70a81833eaf728c4a8154494859dbfe9b3d45c66cdae76fb29c437946a4b57a9  tests/integration/test_decision_recovery_crash_matrix.py
```
