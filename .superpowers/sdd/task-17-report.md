# Task 17 Report: Phase 3 Offline Review Checkpoint

## Delivered

- Updated `research/ui-foundation/tools/build_review.py` to deterministically generate
  `reviews/phase-3-reality-capability-01.html` (and numbered overflow batches) plus
  the required generated `reviews/index.html`.
- The checkpoint is implementation-grounded from canonical questions, explicit review
  priorities, and the active snapshot. Its five blocking items retain Task 16's
  canonical order: Q-5, Q-4, Q-1, Q-2, Q-3.
- Each item exposes its ID/title, priority-based importance, proposed settlement,
  support, uncertainty, acceptance consequence, options, capability status,
  confidence, note, response controls, copyable ID, and disclosed canonical paths
  plus ranking details.
- Added schema-versioned, batch-scoped local feedback history; JSON exports conform
  to the existing feedback schema shape and concise-text exports preserve response
  history. The artifact has no network dependency and fails closed with a readable
  initialization error when its generated data is malformed.
- Added the isolated Playwright suite at
  `ui/tests/e2e/ui-foundation-review.spec.ts`; no Task 15 artifact or hash-tracked
  foundation test was changed.

## TDD evidence

The new Playwright suite was created before the generated checkpoint existed. The
required command initially failed three times with the expected
`net::ERR_FILE_NOT_FOUND` for the required Phase 3 file. The focused review-tool
test was then changed to require Phase 3 filenames and failed with the expected
legacy `batch-01.html` / `batch-02.html` output mismatch. Both were made green by
the minimal generator and artifact implementation.

## Self-review checklist

- [x] Direct `file://` operation with zero network requests.
- [x] At most 12 deterministic primary items per generated batch.
- [x] Required interpretation, evidence, uncertainty, consequence, and options
  fields; technical paths are inside `<details>`.
- [x] Unresolved, accepted, rejected, revise, and uncertain filters; all response
  states are tested.
- [x] Versioned `localStorage` history, JSON/text download exports, and copyable IDs.
- [x] Semantic controls, visible keyboard focus, 390px no-overflow layout, and
  explicit malformed-data initialization failure.
- [x] Existing Task 16 reconciliation coverage now asserts named Phase 3 batches,
  obsolete batch removal, and generated index links.

## Verification

```text
npm --prefix ui run test:e2e -- tests/e2e/ui-foundation-review.spec.ts
3 passed

uv run pytest tests/integration/test_ui_foundation_review_tools.py -v
13 passed

uv run python research/ui-foundation/tools/validate.py
Deferred until the final post-publication ledger update.
```

The Task 16 and Task 17 ledger entries are deferred to Task 18 final publication.
The shared ledger is hash-tracked by frozen Task 15 evidence, so Task 17 leaves it
exactly at HEAD and does not modify any Task 15 artifact or snapshot. UI
lint/typecheck and targeted Ruff/Pyright pass.

## Important findings remediation

- Feedback activated with Space or Enter now records history, rerenders, and restores
  focus to the same newly rendered response control rather than leaving focus on the
  document body. The new Playwright coverage uses real Tab and Space interaction and
  verifies the response, persisted history, and active response control.
- Copy ID now awaits the Clipboard API, falls back to a selected temporary textarea
  with `document.execCommand('copy')` after unavailable or rejected clipboard access,
  and announces a truthful clipboard, fallback, or failure result in the live region.
  Keyboard-driven Playwright coverage verifies the exact ID and the functional method
  outcome, reading clipboard contents when the browser exposes that capability.
