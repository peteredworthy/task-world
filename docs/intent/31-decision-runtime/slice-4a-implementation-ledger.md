# Slice 4A implementation ledger

Status: implementation complete; focused validation complete. Independent
review and the complete repository gate remain for the later integrated review
checkpoint.

| ID | Required behavior | Acceptance evidence | Status |
|---|---|---|---|
| S4A-1 | A decision-v1 verifier exposes one generated `VerificationDecision` schema through the graph-owned resolver and submit boundary. | `decision_answer_schema("verification_decision")`; runtime submission contract; typed verifier prompt; Codex/MCP decision catalogs. | validated |
| S4A-2 | The verifier receives a frozen ordered obligation table and evidence aliases scoped to the exact request. | `ResolvedVerificationDecisionContext` freezes requirement → acceptance → rubric order and stable evidence aliases. | implemented-unproven |
| S4A-3 | A valid answer has exact obligation coverage; code derives grades/outcome/candidate/provenance and produces the canonical verification report. | `compile_verification_decision` validates exact aliases and emits `VerificationReportRecord` plus the canonical answer record. | implemented-unproven |
| S4A-4 | Empty, missing, duplicate, unknown, and cross-candidate findings are rejected; verifier and final-audit authorities remain separate. | Strict model tests cover extra fields, duplicate findings, unknown aliases, and empty reasons; resolver keeps semantic stage in frozen context. | partial |
| S4A-5 | Legacy verifier grade/submit and custom schemas remain unchanged. | Existing graph decision, graph MCP, reliable-plan exposure, verifier prompt, and decision-runtime compatibility tests pass. | validated |

## Implementation and validation record

Changed source/test files: `src/orchestrator/graph/decisions.py`,
`src/orchestrator/graph/models.py`, `src/orchestrator/graph/__init__.py`,
`src/orchestrator/graph/commands/boundary.py`,
`src/orchestrator/graph_runtime/dispatch.py`,
`src/orchestrator/graph_runtime/prompts.py`,
`src/orchestrator/graph_runtime/graph_mcp_tools.py`, and
`tests/unit/test_graph_decisions.py`.

The implementation removes verifier dependence on model-authored `grade(...)`
for decision-v1, adds no graph mutation operations, and retains the old report
shape for legacy callbacks. The detailed typed judgment is carried in the
canonical report evidence; requirement grades are derived from requirement
obligations rather than authored IDs.

Commands and results:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff format <changed files>
3 files reformatted
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check <changed files>
All checks passed!
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright <changed source>
0 errors, 0 warnings, 0 informations
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/unit/test_graph_decisions.py tests/unit/test_graph_mcp_tools.py \
  tests/unit/test_reliable_plan_tool_exposure.py tests/unit/test_decision_schema_consumers.py \
  tests/unit/test_graph_verifier_prompt.py tests/integration/test_graph_decision_runtime.py \
  --override-ini='addopts='
passed; no failures reported
git diff --check
exit 0
```

No live server, paid execution, activation, historical resume, or commit was
performed. This slice has not yet run the complete repository gate or received
the independent 4A review. The remaining proof gap is production-path coverage
for a generated verifier answer with several disjoint obligations and a
cross-candidate negative; it is intentionally left for the 4A review/follow-up
rather than claimed by model-only tests.

No live server, paid execution, activation, historical resume, or commit is part
of this slice. Product-real proof will use the existing disposable graph
dispatch/controller path with injected scripted transports.
