# Grounded UI/UX Foundation

This package records semantic evidence and capability truth for Phases 0–3. It
does not define product screens, view contracts, or future command behavior.

## Current entry points

- [Phase status](status.md)
- [Source snapshot](source-map.md)
- [Open questions](open-questions.md)
- [Decision log](decision-log.md)
- [Static review index](reviews/index.html)

Canonical records live in `catalog/`, `reality/`, and `capabilities/`. Phases 0–2
are complete; Phase 3 is published as `complete-blocked` pending the human checkpoint.

## Task 15 active semantic-status snapshot

`snapshot-2026-07-26-post-merge-main` is the active bounded Phase 3 publication child
snapshot. It records the post-merge hash re-audit, deleted-test and superseded-scratch tombstones,
and the required generated status manifests. The current 210-record Task 15 projection
contains 512 SER rows (454 admitted, 50 bounded, 8 rejected), 1,050 SDR rows, 137 exact and
50 bounded test locators, and a 117-base/117-node collected-test manifest. These are qualifying
collected coverage records, not evidence of test execution. The canonical
SER/SDR review catalog and typed action-variant authority catalog are validation inputs.
Task 15 is COMPLETE following material independent semantic review and a full passing verification gate.
Task 16 supplied deterministic review selection and feedback import; Task 17 supplied the
offline review checkpoint; Task 18 rebuilt and published it. The five open blocking questions
make the Phase 3 result `complete-blocked`; see `reviews/phase-3-reality-capability-01.html`.
