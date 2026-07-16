# Final Whole-Branch Review Fix Report

## Status

DONE

Implementation commit: `e97c7a177` (`Harden typed payload contracts`).

W5 remains closed. No W5.5 artifact persistence, hydration, garbage collection,
or truncation-recovery work was added.

## Finding Evidence

### 1. Canonical Event Serialization

- Removed `_RAW_EVENT_PAYLOAD_TYPES` and its original-input return branch.
- Every modeled event now returns `model_dump(mode="json")`, with explicit
  sparse or `exclude_none` policies only for documented wire shapes.
- Made `EdgeProjection.required` a strict boolean.
- Added producer/serializer/reducer coverage for canonical container conversion,
  strict semantic boolean rejection, and lifecycle semantic parity.

RED: canonical cleanup serialization retained a tuple, and edge `required="false"`
was coerced. GREEN: `tests/unit/test_final_review_contracts.py` passes.

### 2. Required Event Contracts

- Required stable producer/reducer fields for run lifecycle, command rejection,
  callback variants, runtime retry, heartbeat, agent death, dead input, appeal,
  decision, and node lifecycle payloads.
- Added callback `execution_id` at the producer boundary.
- Kept genuine variants narrow: callback accepted/rejected/duplicate models own
  their required reason/result fields; retry timing and optional lineage remain
  optional only where producers vary.
- Retained required lifecycle and decision identities in compact rows and taught
  callback reduction to distinguish documented compact rows from full events.
- Canonicalized sparse Python/YAML fixtures through the existing canonical test
  payload builder or explicit payload fields.

RED: 13 missing-critical-field cases accepted incomplete payloads. GREEN: the
focused event/producer/corpus/compact/command/API batch passed `580` tests before
the final two assertion-only fixture updates; the definitive full suite passed.

### 3. Command Identity Constraints

- Added shared strict `CommandIdentifier` (`min_length=1`, no whitespace,
  strict string input).
- Applied it to command context and command record/node/lease/execution,
  idempotency, requirement, support, cleanup, patch, snapshot, and evaluation
  identities, including schedule lease-map keys and values.
- Strengthened API decision identifiers and nonempty decider strings.
- Added a registry-complete 23-command matrix that rejects empty and
  whitespace-only identity values wherever a command owns an identity field.

RED: blank identities validated. GREEN: the matrix and all command/API tests
pass.

### 4. Redacted Validation Errors

- Replaced direct `ValidationError` interpolation with bounded details from
  `errors(include_input=False)`.
- Retains location, error type, and safe message only; caps errors at 8 and the
  reason at 1,000 characters.
- Added a secret-like unknown-field regression proving the value is absent while
  `unexpected_secret` and `extra_forbidden` remain visible.

RED: `sk-super-secret-value` appeared in `command_rejected.reason`. GREEN: the
redaction regression passes.

### 5. Stored Artifact Consistency

- Added an after-validator requiring the SHA-256 digest in `storage_uri` to equal
  the `content_hash` digest.
- Added mismatch rejection coverage.

RED: mismatched valid-looking digests were accepted. GREEN: mismatch raises a
`ValidationError` naming the digest invariant.

### 6. Documentation And Plan

- Updated the closed W5 specification, event inventory, projection-map
  inventory, progress ledger, residual plan, and W5.5 artifact plan.
- Recorded canonical dumping, required event cores, strict identifiers,
  redacted errors, digest consistency, and generated retention counts
  `105/144/160/92`.
- Explicitly states that the correction does not reopen W5 or implement W5.5.

### 7. Tests And Gates

RED command:

```text
uv run pytest tests/unit/test_final_review_contracts.py -q
# 18 failed, 1 passed
```

Focused GREEN:

```text
uv run pytest tests/unit/test_final_review_contracts.py -q
# 19 passed

uv run pytest tests/unit/*event_payloads.py tests/unit/test_final_review_contracts.py \
  tests/unit/test_graph_event_registry.py tests/unit/test_fixture_corpus.py \
  tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_graph_projections.py \
  tests/unit/test_graph_commands.py tests/unit/test_*command_payloads.py \
  tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py \
  tests/integration/test_graph_event_store.py tests/integration/test_graph_read_models.py -q
# 580 passed before two final assertion-only fixture updates
```

Definitive verification:

```text
uv run pytest -q
# 4775 passed, 3 skipped, 3 warnings in 138.22s

uv run ruff check .
# All checks passed

uv run ruff format --check .
# 701 files already formatted

uv run pyright
# 0 errors, 0 warnings, 0 informations

git diff --check
# passed

uv run pre-commit run --all-files
# all hooks passed: Ruff, format, secrets, Pyright, pytest, module imports,
# signal routing, enum drift, UI lint, UI typecheck
```

Compatibility searches found no `_RAW_EVENT_PAYLOAD_TYPES`, direct invalid
command `ValidationError` interpolation, or stale `101/141/159/84` final counts.

## Self-Review

- Reviewed the complete production diff and fixture migration after full-suite
  GREEN.
- Confirmed current producers emit every newly required field.
- Confirmed API subclasses preserve or strengthen domain identity constraints.
- Confirmed the only compact callback exception is explicit: projection, light,
  and node-detail rows omit callback bodies/idempotency state, while full and
  summary-rebuild events retain the canonical contract.
- Confirmed no mocks, suppressions, database deletion, compatibility adapters,
  or W5.5 implementation were introduced.

## Concerns

No blocking concerns. The three full-suite warnings are the existing Python 3.12
`aiosqlite` datetime-adapter deprecation warnings.
