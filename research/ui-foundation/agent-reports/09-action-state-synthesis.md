# Action, State, And Permission Synthesis

## Purpose

Record the final Task 11 provisional shared vocabulary used by the current action
corpus: carrier-local states, legal transitions, concrete command declarations,
evidence anchors, and authority boundaries. This is a provisional normalization,
not canonical catalog allocation or a claim of product-role authorization.

## Scope inspected

- Task 11 state, permission, action, and shared-report artifacts.
- All 69 current `reality/actions/*.yaml` roots.
- The lifecycle, legacy, graph, and review/admin action-group reports.
- Approved workflow, graph-runtime, API/action-authority, UI, and test audits;
  `tools/validate.py` models; and current routed source anchors already recorded
  in the vocabulary.

## Key findings

- The current corpus contains 65 present action contracts and 4 intentional gap
  contracts. Every root parses through `ActionContract`; every present local
  command, evidence, permission, and state reference resolves.
- `STA-927` and `STA-928` remain absent. Results are carried by their actual
  row, task, graph run/node/decision/patch, outbox, review job, git, filesystem,
  routine, agent, runner-default, repository, clarification, or approval carrier.
- Lifecycle preserves acceptance versus application: start, resume, and active/
  paused cancellation use source-preserving acceptance where observed; pause
  writes stopping; consumer application is a separately declared later edge.
  Ordinary deletion and paused-startup-orphan deletion stay distinct.
- Graph decisions use discriminated `CMD-912` and only
  `decision pending -> decision recorded`. Node outcomes remain
  `node pending -> completed|failed|cancelled`; graph cancellation remains
  `graph run cancelling -> graph run cancelled`. No cross-carrier transition
  connects these pairs.
- Graph patches use `STA-962` submitted before `STA-951` accepted or `STA-952`
  rejected. Graph active preservation and a budget-created ready gate are
  separately documented carrier effects, not patch-result transitions.
- Review/admin routes use `PER-906`, distinct from legacy workflow `PER-902`.
  Agent create, update, delete, and prompt reset now use their carrier-local
  `STA-963` through `STA-967` lifecycle states and concrete `CMD-944` through
  `CMD-947` commands.
- `ACT-986` remains an intentional non-executable gap: no inspected backend
  route implements the UI's agent-test-fix request, so its authority, command,
  evidence, eligibility, and job-result contract remain unresolved.

## Important uncertainties

- Authentication is optional and enforced authorization remains absent. Caller,
  decider, and operator strings are not authenticated-subject policy evidence.
- Most mutation routes lack client expected versions and idempotency keys; no
  universal retry or action-receipt guarantee is established.
- Review-job, git, filesystem, and administrative evidence remains qualified by
  the approved audits rather than a fresh endpoint-by-endpoint execution run.
- `CMD-916` represents execution-bound graph MCP raw patch/macros but has no
  standalone current action contract. It is an uncovered transport declaration,
  not a basis to invent a new UI action.

## Conflicts found

1. REST lifecycle acceptance commonly precedes application, while CLI direct
   start applies synchronously.
2. The workflow audit permits applied `stopping -> cancelled`, while the REST
   route rejects cancellation from a stopping row.
3. Documentation says JSONL-first, while approved audits establish SQL-event
   transactional authority with a secondary JSONL sink.
4. The UI advertises agent-test-fix behavior without an inspected backend route.

## Decisions required

1. Decide whether to implement a backend agent-test-fix capability with an
   authenticated-subject authority policy, job lifecycle, evidence, and route
   test; otherwise retain `ACT-986` as a gap.
2. Decide whether execution-bound graph MCP patch/macros require a standalone
   action contract for `CMD-916`; do not infer one from REST patch coverage.
3. Resolve the stopping-row cancel discrepancy before admitting a stopping-source
   REST cancellation acceptance contract.
4. Define and enforce product-role authorization before changing
   `enforced_authorization: absent`.

## Artifact paths

- `research/ui-foundation/reality/state-model.yaml`
- `research/ui-foundation/reality/permissions.yaml`
- `research/ui-foundation/reality/actions/*.yaml`
- `research/ui-foundation/agent-reports/09-action-state-synthesis.md`
- `.superpowers/sdd/task-11-synthesis-report.md`

## Evidence pointers

- `agent-reports/02-graph-runtime.md`: graph lifecycle, decision, node, patch,
  outbox, and cancellation carrier behavior.
- `agent-reports/03-workflow-state.md`: legacy row/task transitions, signals,
  acceptance/application timing, cancellation, and recovery boundaries.
- `agent-reports/04-api-actions-authority.md`: concrete route/function surfaces,
  authority absence, review/admin effects, and action timing.
- `agent-reports/07-tests-documentation.md`: qualification limits for static
  test inventory.
- `.superpowers/sdd/task-11-{lifecycle,legacy,graph,review-admin}-actions-report.md`:
  current action-family mappings.

## Recommended next delegation

No Task 11 action-remap work remains. Retain the four intentional gap contracts
until their missing capabilities exist, and carry the provisional vocabulary to
canonical normalization only with its carrier boundaries and authority limits
intact.
