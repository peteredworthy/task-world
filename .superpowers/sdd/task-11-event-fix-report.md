# Task 11 Event Fix Report

## Status

Complete and ready to commit. The final two canonical graph event names,
`agent_dispatch_requested` and `command_recorded`, now have strict payload
models, explicit four-mode retention specifications, canonical producer
serialization, and focused replay coverage.

## Changes

- Added required `AgentDispatchRequestedPayload` fields with strict scalar
  types and dispatch-only `AgentDispatchResourceClaim` entries.
- Added required `CommandRecordedPayload` fields with the sole dynamic boundary
  at `command_payload: dict[str, Any]`.
- Exported both models and `serialize_event_payload` through
  `orchestrator.graph`.
- Registered both models and added an import-time guard requiring
  `CANONICAL_EVENT_TYPES == EVENT_PAYLOAD_MODELS.keys()`.
- Added explicit projection, light, summary, and node-detail retention for all
  fields on both events.
- Routed the graph runtime controller and scenario harness through canonical
  validation and JSON serialization.
- Replaced flattened `command_recorded` fixtures and expectations with the
  nested canonical shape. No aliases, sparse defaults, or external-event
  exemptions were added.

## TDD Evidence

- Registry RED: canonical/model key equality failed before registration.
- Model/producer/parity RED: 14 expected failures covered absent models,
  strict rejection, missing serializer, flattened scenario output, controller
  parity, and compact-reader field loss.
- Focused GREEN: `72 passed` across registry, model, scenario, controller,
  fixture corpus, allowlist, event-store, and read-model tests.

## Verification

- Full suite: `4748 passed, 3 skipped, 3 warnings` in 132.94 seconds.
- Ruff lint: passed.
- Ruff format check: 700 files formatted.
- Pyright: 0 errors, 0 warnings, 0 informations.
- `git diff --check`: passed.
- Repository hooks: recorded by the implementation commit.

The first full-suite invocation reached 98% without a failure but exceeded the
120-second tool timeout. The definitive rerun above used a 240-second ceiling.
The three suite warnings are existing Python 3.12 `aiosqlite` datetime-adapter
deprecation warnings.

## Self-Review

No findings. Producer fields match current emitted values; all event fields are
required; strict models reject unknown fields and scalar coercion; compact and
full reads preserve both payloads; and `lease_suspended` remains external while
retaining its existing model.

## Concerns

`command_payload` intentionally permits arbitrary nested domain data. It is the
only dynamic boundary in `CommandRecordedPayload`, as required. No other known
concerns remain.

## Commits

- Design: `5fac38e91` (`Design final canonical event payloads`)
- Implementation: `511d88d44` (`Add strict runtime event payloads`)

## Important Finding Follow-Up

The shared `ResourceClaimProjection` contract remains unchanged because it is
used by leases, nodes, authorities, projection checkpoints, and scheduler read
models. Dispatch now uses a dedicated `AgentDispatchResourceClaim` with strict
`mode`, `scope`, and `external_resource_key` strings, plus strict list
containers and strict string elements for `paths`. The top-level
`resource_claims` container is also strict. The controller explicitly converts
its current claim dictionaries through this nested model before canonical event
serialization; no aliases or coercion paths were added.

The new RED matrix demonstrated five prior coercions: byte strings for nested
strings, tuple-to-list coercion for `paths` and `resource_claims`, and byte
coercion for `external_resource_key`. Integer mode/scope and path elements were
already rejected and remain covered.

Follow-up verification:

- Runtime payload tests: `19 passed`.
- Focused runtime event, registry, shared-model, controller, corpus, and
  allowlist tests: `162 passed`.
- Ruff lint: passed.
- Ruff format check: 700 files formatted.
- Pyright: 0 errors, 0 warnings, 0 informations.
- Repository hooks: run by the follow-up commit.

Follow-up self-review found no remaining strictness or scope issues. The only
intentional dynamic boundary remains `command_payload`.
