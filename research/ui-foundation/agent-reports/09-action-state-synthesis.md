# Action, State, And Permission Synthesis

## Purpose

Provide Task 11's provisional shared vocabulary for state carriers, authority
boundaries, concrete command declarations, and evidence anchors. It is
infrastructure for later action-file remapping, not a claim that action contracts
are complete or normalized.

## Scope inspected

- Task 11 brief, approved Phase 0-3 design, closed scope, current Task 11
  artifacts, and `research/ui-foundation/tools/validate.py` models.
- Approved audits `01` through `07`, especially workflow state, graph runtime,
  API/action authority, UI routing, and test qualification.
- Task 12's approved evidence-carrier synthesis and its carrier-boundary limits.
- The four current Task 11 action-group reports and their lifecycle, legacy,
  graph, review, environment, and administration action files, read only to
  identify the remaining legal-vocabulary gaps.

## Key findings

- The prior universal `STA-927` applied and `STA-928` rejected carriers were
  removed. A result belongs to the row, legacy task, graph run/node/decision,
  outbox, review job, git conflict/merge, filesystem, routine, agent, runner
  default, repository, clarification, approval, or graph patch carrier that
  actually records it.
- Graph run cancellation is now graph-local (`cancelling` then graph-local
  cancelled node/run outcomes). The later legacy row cancellation is an observed
  synchronization relationship, not a graph-to-row transition.
- Graph-local node pending/completed/failed/cancelled and decision
  pending/recorded states are explicit. Decision recording and node outcomes are
  intentionally separate carriers.
- Concrete provisional `CMD-*` declarations identify each routed endpoint/domain
  command, its route/function/tool identity, reachability, and acceptance versus
  application timing. REST lifecycle acceptance remains separate from later
  signal-consumer application; CLI direct start is separately declared.
- Fine-grained provisional `EVI-*` records anchor each state/permission claim to
  a report section, source behavior, or named test rather than four broad labels.
- `PER-*` entries preserve optional authentication, absent enforced
  authorization, domain eligibility, and tool exposure as different concepts.
  Graph role/context checks are domain eligibility only unless an authenticated
  subject policy is actually checked.
- The vocabulary now represents row absence/create/delete, fan-out child and
  parent effects, transition-back and recovery multi-carrier resets, git and
  environment operation sources/results, routine YAML validation, repository
  absence/add/remove, and administrative result self-loops. These are
  carrier-local transitions, not a universal receipt.
- Route inspection confirms separate concrete commands for routine YAML
  validation, review-test start, and agent conflict-resolution dispatch. The UI
  `agent-fix-tests` call has no inspected backend route, so it remains a gap and
  has no present `CMD-*` declaration.
- REST resume and paused-row cancellation now have the observed
  `STA-903 -> STA-903` queued-acceptance transition. It records row preservation
  before later signal-consumer application and is not a paused-state no-op claim.
- The complete local corpus audit parsed all 63 current action YAML roots through
  `ActionContract`: 59 present contracts and 4 absent gap contracts. All local
  command, evidence, permission, state, immediate transition/result,
  eventual-applied transition, and carrier-relationship references resolve; the
  absent gaps expose no completed action semantics.

## Important uncertainties

- The action-group repairs are only partially normalized. Their next action-file
  pass must consume the new source/result paths and split the former shared
  review command into review-test and agent-conflict-dispatch identities.
- Most REST routes lack client expected versions and idempotency keys. A shared
  retry or rejection receipt is not established.
- Review-job, git, filesystem, administrative, and some graph-resuming states
  are approved-audit inventory findings, not a fresh run of their implementation
  or test suites.
- Graph failed reopen remains mode-qualified. It cannot redefine row or task
  terminality.
- REST pause, resume, cancel, and recover routes explicitly reject `STOPPING`.
  No stopping-to-stopping acceptance self-loop is evidence-grounded despite the
  workflow-level applied `stopping -> cancelled` edge.

## Conflicts found

1. REST lifecycle commands commonly acknowledge queued acceptance while CLI
   direct start applies synchronously.
2. Graph cancellation reaches graph-local terminal work before the consumer
   separately applies legacy row cancellation; the carriers are not aliases.
3. Caller/fixed actor strings and graph decider/context fields are persisted or
   validated without being bound to authenticated-subject authorization.
4. Documentation's JSONL-first wording conflicts with the audited SQL-event
   transactional authority and secondary JSONL sink.

## Decisions required

1. Remap the now-enabled action groups: lifecycle create/delete and queued
   acceptance; fan-out retry; transition-back; run recovery; review test and
   agent conflict dispatch; routine validation; git/environment/admin results.
2. Define and enforce an authenticated-subject product-role policy before
   changing `enforced_authorization` from absent.
3. Decide whether CLI lifecycle must conform to the queued REST contract.
4. Design a common action receipt only if product requirements need one; do not
   infer it from the carrier-local vocabulary.

## Artifact paths

- `research/ui-foundation/reality/state-model.yaml`
- `research/ui-foundation/reality/permissions.yaml`
- `research/ui-foundation/agent-reports/09-action-state-synthesis.md`
- `.superpowers/sdd/task-11-synthesis-report.md`

## Evidence pointers

- `agent-reports/02-graph-runtime.md`: graph lifecycle, node/decision, patch,
  cancellation, and outbox command effects.
- `agent-reports/03-workflow-state.md`: legacy row/task transitions, signal
  timing, cancellation ordering, and mode boundary.
- `agent-reports/04-api-actions-authority.md`: route/function/tool surfaces,
  authority absence, asynchronous review timing, and administrative effects.
- `agent-reports/07-tests-documentation.md`: qualification limits for static
  test inventory; this synthesis asserts no fresh implementation test result.
- `agent-reports/10-evidence-synthesis.md`: evidence carrier non-equivalence.
- `.superpowers/sdd/task-11-lifecycle-actions-report.md`,
  `task-11-legacy-actions-report.md`, `task-11-graph-actions-report.md`, and
  `task-11-review-admin-actions-report.md`: bounded current action evidence and
  vocabulary follow-ups.

## Recommended next delegation

Assign action-file implementers to consume this vocabulary one routed family at
a time: use `STA-954 -> STA-955 -> STA-900` and eligible row deletion paths;
use active/paused acceptance self-loops, including `STA-903 -> STA-903`, but no
stopping acceptance; map fan-out
child `STA-914 -> STA-907` alongside parent `STA-912 -> STA-912`; map
transition-back/recovery task resets independently from run preservation or
pause; use `CMD-932`/`EVI-939`/`PER-905` for routine validation and
`CMD-933`/`CMD-934` for the distinct review routes. Use `PER-906` only for the
route-specific review/admin eligibility boundary, never as authorization. This
infrastructure update does not claim that all action edits are complete.
