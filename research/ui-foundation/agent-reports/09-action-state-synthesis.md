# Action, State, And Permission Synthesis

## Purpose

Normalize only the audited, UI-relevant command reality into provisional
mode-aware state, permission, and action contracts. This synthesis does not
allocate canonical IDs, change shared catalogs, or turn source demands into
executable commands.

## Scope inspected

- Task 11 brief, approved Phase 0-3 design, `AGENTS.md`, closed scope manifest,
  and `research/ui-foundation/tools/validate.py` action/report contract.
- Approved Phase 1 reports `01` through `07`, especially workflow-state,
  graph-runtime, API/actions/authority, evidence/telemetry, and UI projections.
- Existing empty reality placeholders to preserve their file boundaries.

## Key findings

- `reality/state-model.yaml` distinguishes run rows, legacy tasks/step approval,
  graph runs/nodes, and graph outbox rows. It intentionally does not equate graph
  node state with legacy task state.
- Lifecycle contracts preserve acceptance versus application: REST start,
  pause, resume, and cancel can enqueue a signal before their applied state is
  visible. Pause uniquely exposes `stopping` immediately.
- Implemented contracts use the routed UI-mutation selection rule from the UI
  audit: controls mounted by `App.tsx` that issue a write request, plus its
  explicitly distinct CLI direct-start path. Contracts cover lifecycle/run,
  task/step/clarification/recovery/fan-out, graph decision type/value families,
  patch/requeue, merge/review, environment, and administrative mutations. Each lists
  actor/auth boundary, domain eligibility, source-version reality, input,
  validation, durable effects, result carrier, rejection/race behavior,
  idempotency/retry, reversibility, and durable evidence.
- Authentication, authorization, graph domain eligibility, and proposed role
  policy are separate in `permissions.yaml`. There is optional global JWT
  authentication, no enforced product-role authorization, and no invented role
  policy.
- Typed steering, steering patch, and ignore/watch are source demands only. They
  are non-executable gap requirements with no command semantics.

## Important uncertainties

- Graph failed reopen is mode-qualified and must not make failed universally
  nonterminal.
- Most REST actions lack expected versions/idempotency keys. Their conflict and
  duplicate behavior is command-specific, so a generic UI retry promise is not
  supported.
- The full endpoint rollback assertion for an outbox requeue stale audit append
  is inferred from its transaction; the helper race is directly tested.
- Clarification artifact writing precedes DB conflict resolution, so exactly-once
  artifact content is not established.

## Conflicts found

1. REST queued lifecycle semantics and CLI direct start are not one action-result
   contract.
2. Caller/fixed actor strings are persisted while JWT claims are not bound to
   those values; attribution must not be called authorization.
3. A legacy CLI reject-looking answer still invokes approve, so it cannot support
   a true deny action contract.
4. Required documentation says JSONL-first while audited current implementation
   is SQL-event-first with a secondary JSONL sink.

## Decisions required

1. Define a product-role policy and bind it to authentication before claiming
   per-action authorization.
2. Decide whether CLI lifecycle must conform to queued REST semantics.
3. Design typed steering and its packet-binding evidence in a separately approved
   capability package.
4. Decide a common action-result receipt if UI must show accepted/rejected,
   durable identity, resulting state, next activity, and recovery consistently.

## Artifact paths

- `research/ui-foundation/reality/state-model.yaml`
- `research/ui-foundation/reality/permissions.yaml`
- `research/ui-foundation/reality/actions/{lifecycle,human-decisions,graph-commands,absent-interventions}.yaml`
- `research/ui-foundation/agent-reports/09-action-state-synthesis.md`
- `.superpowers/sdd/task-11-synthesis-report.md`

## Evidence pointers

- `research/ui-foundation/agent-reports/02-graph-runtime.md`: graph command
  legality, positions, decision effects, and outbox behavior.
- `research/ui-foundation/agent-reports/03-workflow-state.md`: legacy states,
  signal application, cancellation, retries, and mode boundary.
- `research/ui-foundation/agent-reports/04-api-actions-authority.md`: transport,
  authority, request, audit, stale, and reversal findings.
- `research/ui-foundation/agent-reports/06-ui-projections.md`: routed current UI
  writing controls and discarded result evidence.
- `research/ui-foundation/agent-reports/07-tests-documentation.md`: qualifying
  action/idempotency evidence and authority limits.

## Recommended next delegation

Have the canonical normalizer allocate IDs and command/evidence references only
after resolving authority and transport conflicts. An independent verifier should
challenge state-carrier separation, rejection preservation, UI action coverage,
and any claim that a gap requirement is executable.
