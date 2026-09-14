# Slice 4B implementation ledger

Status: implemented and independently validated. The first independent review
found final-audit, grade-policy, prompt-evidence, public-artifact, and
product-path gaps inherited from the Slice 4A surface. A fresh builder pass
closed them, and a fresh read-only validator passed all Slice 4B rows. No live
server, paid execution, activation, historical resume, staging, or commit was
performed.

| ID | Required behavior | Acceptance criteria / product-real proof | Regression evidence | Status | Remaining gap |
|---|---|---|---|---|---|
| S4B-1 | Mandatory verifier checks are runtime-owned and executed by the existing check-node command machinery against the exact candidate under judgment. | A disposable Git/SQLite production-dispatch case runs a real shell command after a real worker candidate capture, binds the durable `CheckResult`, restarts, and proves the check is not dispatched twice. | Passing and failing product-path parameters plus the decision unit matrix. | complete | None. |
| S4B-2 | A receipt is acceptable only when candidate, command, environment, policy, and freshness all match the frozen verifier request. | Exact receipts survive replay/restart; wrong candidate, producer, command ID/definition/binding, timeout, snapshot ID/ref, environment, source policy, and stale producer output fail closed. Final acceptance permits only its exact transitive multi-batch evidence closure. | Receipt mutation matrix, replay equality, and independent multi-batch final-audit boundary reproducer. | complete | None. |
| S4B-3 | Missing, failed, timed-out, or incompletely covered mandatory receipts prevent a passing verification report regardless of model prose or grades. | All-A findings cannot override failed or timed-out checks; missing coverage rejects context resolution; multiple failed receipts remain represented. | Unit behavior matrix and real failed-command product path. | complete | None. |
| S4B-4 | Post-answer candidate mutation prevents publication while unrelated graph movement remains admissible. | The product-real verifier test mutates the tracked candidate workspace after durable staging and accepts no verifier report, decision answer, or judgment artifact. Existing shared-boundary tests retain unrelated-tail acceptance. | Direct post-answer verifier mutation parameter plus boundary authority tests. | complete | None. |
| S4B-5 | Work products, semantic judgments, and mechanical receipts remain distinct public evidence with exact attribution across restart. | Public readback exposes separate candidate, `CheckResult`, `DecisionAnswer`, versioned `verification_judgment` semantic artifact, and minimally linked `VerificationReport`. | Product-real restart assertions, artifact compiler tests, and projection replay. | complete | None. |
| S4B-6 | Plan verification check policy is phase-local; batch and final-audit checks do not leak across authorities, and legacy behavior remains unchanged. | Mandatory receipts derive from the exact verifier's required `CheckResult` ports. Final audit selects the dynamic-acceptance candidate while retaining prior-batch evidence. Legacy verifier/tool/schema tests pass. | Macro/compiler cases, final-audit callback reproducer, MCP/schema/prompt regressions. | complete | None. |

## Implementation evidence

- Decision-v1 verifiers now submit one typed `VerificationDecision`; the runtime
  derives outcome from exact A/B/F obligation thresholds and mandatory receipt
  status.
- Check receipts are validated against the producing check node, exact frozen
  command and binding, timeout, candidate/file-state snapshot, environment,
  source policy, phase, and latest accepted result.
- Final-audit candidate identity is anchored by the dynamic final-acceptance
  receipt, while evaluated evidence retains the exact transitive batch closure.
- The detailed judgment is a declared, versioned `verification_judgment`
  `SemanticArtifact`; the canonical `VerificationReport` carries only its
  reference.
- The verifier prompt contains hydrated candidate/check records and mandatory
  receipt status, command, and output rather than opaque record IDs alone.
- Staging dry-runs the compiled callback without publishing it. Witnessed
  finalization recompiles against current authority and accepts the decision,
  judgment artifact, and report atomically.

## Validation evidence

```text
Baseline before Slice 4B:
250 passed, 18 warnings in 121.62s

Tests-first focused Slice 4B run:
14 failed, 1 passed, 72 deselected

Final focused unit + product-real integration:
94 passed in 13.35s

Full decision unit + integration file:
116 passed in 130.33s

Related regression set:
115 passed, 1 deselected in 8.97s

Broader local regression matrix:
371 passed, 1 failed in 147.12s
The only failure was the existing network-dependent disposable-package test;
the sandbox could not resolve PyPI to fetch hatchling.

Scoped Ruff:
All checks passed

Scoped Pyright:
0 errors, 0 warnings, 0 informations

git diff --check:
clean
```

The final independent validator additionally ran 16 focused verifier/final-
audit tests, both real runtime-check parameters, 49 MCP/schema/prompt regressions,
and a read-only multi-batch final-audit stage/finalize reproducer. It reported
PASS for S4B-1 through S4B-6 with no blocking findings. The direct post-answer
typed-verifier mutation case was then added and passed.

## Starting source hashes

```text
667ca2ae54496e5c353627976f84611076d15a345bae80b1d6d8eedeb860284e  src/orchestrator/graph/decisions.py
edae48a4c221aba2aba8e4d3e6c360df67ec77ff550bd4e160450c24eb3637f9  src/orchestrator/graph/models.py
7c6e172b07e25e35605a4eec1a7c422943318830981c40003b22bed35092c196  src/orchestrator/graph/macros.py
8c7d6e130019da3d10149d8d2bdb1404c1603c75a34ef050ba28c8785307c993  src/orchestrator/graph/projection_queries.py
948c1ea4fad95b0c27555009a09259e74aa8969466685a8742617074d43e932f  src/orchestrator/graph_runtime/dispatch.py
c392b64f9970a03722caec1c0bb0dd2e6021c4454c9b42ed369bdd09b14792af  src/orchestrator/graph/commands/boundary.py
261122395d10e8a213bbde63108a86366a2ef05719e225368dc6b5877d119a4f  tests/unit/test_graph_decisions.py
dcaf0f24d74fc7a891b823ad71d032417c76006607c8d6626ed5adab5aa0e9d9  tests/unit/test_graph_dispatch_on_output.py
2dcf7a15df9c52f9414de943336484fb26df439b093d864c2b3d8563047ea86b  tests/integration/test_graph_decision_runtime.py
```

## Final source hashes

```text
9ceecf81c3e0cdbb59b7e22905822197c1da30f004ef657efb79eb61861af267  src/orchestrator/graph/__init__.py
791ced0ee36e8406cdde4a630fea1aca6b687510ec8b6a42baf0d1b943721939  src/orchestrator/graph/_commands.py
01f7003a92c8ba29a3d0d4fa79ed59084142c41325f44f367c6a3fa07b8ad9ac  src/orchestrator/graph/commands/boundary.py
085ca96da1815c102d5ad211e894259a577b3efaf5ec3b2e2fd097738eddb1d2  src/orchestrator/graph/compiler.py
b7360c1ff77cbbb04cabc234720f30459ed47bcb64611e043aa9c2b8c3776d23  src/orchestrator/graph/contracts.py
64d9e3536db75c7c2c89d8694b0f05f6b16e4d81381217f35f9ed42778627532  src/orchestrator/graph/decisions.py
c25864a0b9f457345918d4fc23a4ef87e04eaad484596e2c4acfb41eee9538e3  src/orchestrator/graph/macros.py
7f88dfc949ae68e965076d940e919fc3ce1ad3bf0f57dafe1adadd5beaa6aad8  src/orchestrator/graph/models.py
427314fa209ba8f85a29b3f1ae71a3a16ee36f22f4960b8db9413b3e42b4a96e  src/orchestrator/graph/projection_queries.py
efd3a4cb2055ad60a5dbc27f64a9fef738a582c224b9d6fe92b0399a53c94aa3  src/orchestrator/graph_runtime/dispatch.py
c9e11f681eaee83eabd969978206e816f5c4d808bad4f34657e6d4f87fb491b5  src/orchestrator/graph_runtime/graph_mcp_tools.py
7ed44ffc9489ea63ff09d3d3c307e0b08df27425c3fec812713f02539e6cca7e  src/orchestrator/graph_runtime/prompts.py
679524ea57cdd317afeceee875880f8a30d3f8bddd113173310d38bda5aa9539  tests/unit/test_graph_decisions.py
b96733c28faa8a82326028e75b9615eaf0807dcb3b7c002cbe85a189b2477565  tests/integration/test_graph_decision_runtime.py
```

The complete repository gate is intentionally deferred to the final recovery
slice, per the worktree instructions.
