# Lifecycle, Callback, Retry, and Audit Event Payloads

## Scope

Type the payloads for `run_lifecycle_changed`, `command_rejected`,
`callback_accepted`, `callback_rejected_stale`, `callback_rejected_conflict`,
`callback_duplicate_returned`, `runtime_retry_scheduled`, `heartbeat_recorded`,
`agent_died`, and `dead_input_detected`.

Every model keeps historical fields optional and has fixed typed fields plus one
`extra: dict[str, Any]`. A `mode="before"` validator moves unknown or malformed
legacy top-level values under `extra`. Callback `payload=None` is an explicit
compatibility value and must remain present in JSON dumps.

## Shapes and Compatibility

- Lifecycle: command/from/to/trigger plus recovery node, patch, record, and reason
  metadata. Sparse history updates run state only for a valid string `to_state`.
- Command rejection: command/reason, invariant blockers, and patch rejection
  identity/position/actor/diagnostic fields. It remains audit-only.
- Callbacks: node/lease/generation/idempotency identity, nested callback payload,
  reason, and duplicate `prior_result`. Only accepted callbacks populate the
  idempotency projection; missing or malformed identity keeps the prior skip.
- Runtime retry: node/lease/generation/policy/reason, integer
  `retry_after_seconds`, and nullable string `retry_not_before`. Sparse or
  malformed node identity keeps the prior skip; invalid retry time clears the
  projected value as before.
- Audit events: heartbeat lease identity/timing, agent-death lease/execution
  identity and reason, and dead-input source/destination routing and reason.
  They never mutate `GraphProjection`.

All current producers validate and JSON-dump through these models. Reducers
parse lifecycle, accepted callback, and runtime retry payloads before reading
fields. No event-log rewrite or projection schema bump is required because the
projection shape and valid-event semantics do not change.

## Compact Read Requirements

`retry_not_before` must be retained in `GRAPH_PROJECTION_PAYLOAD_FIELDS`,
`LIGHT_GRAPH_PAYLOAD_FIELDS`, `SUMMARY_REBUILD_PAYLOAD_FIELDS`, and
`NODE_DETAIL_PAYLOAD_FIELDS`. The newly typed reducer-read fields contain no
booleans, so this slice adds no SQLite integer-to-boolean normalization entry.

## Acceptance

The eight named lifecycle payload tests pass; sparse fixture history remains
replayable; unknown keys are preserved under `extra`; callback explicit `None`
is retained; current producers emit model-valid payloads; audit events are
projection-neutral; retry timing survives every compact reconstruction path;
the fixture corpus, projection/allowlist tests, graph suite, Ruff, Pyright, and
`git diff --check` pass.
