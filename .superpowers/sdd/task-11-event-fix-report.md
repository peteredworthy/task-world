# Task 11 Event Fix Report

## Status

Complete and ready to commit. The final two canonical graph event names,
`agent_dispatch_requested` and `command_recorded`, now have strict payload
models, explicit four-mode retention specifications, canonical producer
serialization, and focused replay coverage.

## Changes

- Added required `AgentDispatchRequestedPayload` fields with strict scalar
  types and strict `ResourceClaimProjection` entries.
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
- Implementation: the commit containing this report
