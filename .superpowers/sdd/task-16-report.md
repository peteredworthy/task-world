# Task 16 Report: Review Projection and Feedback Import

## Scope delivered

- Added `research/ui-foundation/tools/build_review.py`.
- Added `research/ui-foundation/tools/import_feedback.py`.
- Added self-contained, real-file integration coverage in
  `tests/integration/test_ui_foundation_review_tools.py`.
- Kept hash-tracked `tests/integration/test_ui_foundation_tools.py` and
  `.superpowers/sdd/progress.md` byte-identical to Task 15 HEAD.
- Did not modify Task 15 validation, provenance, snapshot records, product backend, or product UI.

## Implementation

### Review projection

`ReviewItem` is a frozen Pydantic model with the required five fields.
`select_review_items(root)` loads canonical `catalog/questions.yaml`, constructs typed review
items, and applies the required stable ordering:

1. blocking before non-blocking;
2. descending downstream dependency count;
3. descending authority risk;
4. descending capability impact;
5. stable ID.

When blockers exist, only blockers are selected and all are emitted in deterministic batches of
at most 12. When no blockers exist, the highest-impact 12 non-blockers form the checkpoint batch.
Canonical questions predate the explicit ranking fields, so their deterministic projection derives
dependency count from `affected_ids`, authority risk from affected `PER-*` IDs, and capability
impact from affected `CAP-*` IDs. Explicit ranking values remain authoritative when present.

`build_review(root)` reads the canonical `active_snapshot_id` and writes one deterministic static
HTML file per selected batch under `reviews/batch-NN.html`. It returns those generated paths.

### Feedback import

`CandidateDecision` is a frozen Pydantic model with the required four fields.
`import_feedback(root, export_path)`:

1. parses the export as JSON;
2. validates it with the checked-in Draft 2020-12
   `schemas/review-feedback.schema.json`, including date-time formats;
3. requires an exact match with the canonical active snapshot ID;
4. maps every response-history entry, in original order, to a candidate decision.

The importer performs no canonical writes. In particular, it cannot alter evidence records or
capability status. The CLI prints candidate decisions as JSON for subsequent human confirmation;
it does not promote them into `catalog/decisions.yaml`.

## Requirement self-review

| Requirement | Evidence |
|---|---|
| Required `ReviewItem` interface | Frozen Pydantic model in `build_review.py` |
| Required `CandidateDecision` interface | Frozen Pydantic model in `import_feedback.py` |
| Deterministic blocker-first ordering | Exact five-part sort key plus focused ordering test |
| Batches contain at most 12 | Shared batch size and 13-blocker integration test |
| Blockers exclude non-blockers while unresolved | Blocker-only selection and integration assertions |
| Highest-impact non-blockers when unblocked | 14-item integration test selects the first 12 in impact order |
| Static review projection | Two-batch real-file generation test checks paths and snapshot binding |
| Feedback validated against existing schema | Draft 2020-12 validator uses the root schema file |
| Exact active snapshot required | Stale-snapshot subprocess test checks `FEEDBACK_SNAPSHOT_STALE` |
| Response history preserved | Two transitions for one item remain two ordered candidate decisions |
| Evidence and capability status immutable | Byte-for-byte before/after integration assertions |
| No unrequested decision promotion or audit machinery | Import returns/prints candidates only |

## Progress

Task 16 is complete: deterministic review projection and safe candidate-decision import are
implemented, focused tests and Phase 2 validation are green, and Task 15 artifacts remain unchanged.

## TDD and verification

The focused integration behavior was authored before the two production tools. The initial red run
exposed an omitted test-helper insertion before reaching the missing-tool boundary; the helper was
restored, and after implementation and type cleanup the Task 16 selection was green:

```text
uv run pytest tests/integration/test_ui_foundation_review_tools.py -v
7 passed
```

Static checks:

```text
uv run ruff check research/ui-foundation/tools/build_review.py \
  research/ui-foundation/tools/import_feedback.py \
  tests/integration/test_ui_foundation_review_tools.py
All checks passed!

uv run pyright research/ui-foundation/tools/build_review.py \
  research/ui-foundation/tools/import_feedback.py \
  tests/integration/test_ui_foundation_review_tools.py
0 errors, 0 warnings, 0 informations
```

Phase 2 validation command:

```text
uv run python research/ui-foundation/tools/validate.py --phase 2
```

The Task 16 tests were isolated after the first commit attempt demonstrated that editing the
hash-tracked monolithic test and progress files correctly triggered immutable Task 15 source-hash
validation. Those files were restored exactly to HEAD; no snapshot, provenance, or validator change
was used to suppress the check.

## Concerns

- None. Task 16 coverage is isolated outside the immutable Task 15 snapshot, and Phase 2 remains
  green without snapshot or provenance changes.
