# Task 14 UI foundation report

## Purpose

Adjudicate every closed Phase 2 source demand, admit only evidence-qualified
current and deterministic derived capabilities, and project the canonical
registry without losing classification distinctions.

## Scope inspected

The 132-demand scope manifest, canonical Phase 1 evidence and ID ledgers,
action/state contracts, 11 derivation contracts, Phase 2 validator, generated
claims/status/gaps projections, and focused integration tests.

## Key findings

- `CAP-1` through `CAP-132` map one-to-one to unique immutable scope-demand
  keys and matching order-independent `ids.yaml` allocations.
- The corrected classifications are **2 current, 12 derived, 25 proposed, 39
  gap, and 54 unknown**.
- Eleven deterministic derivations are admitted. `DRV-5` intentionally links
  both `CAP-30` and `CAP-48`; every derived CAP and DRV contract now links in
  both directions.
- `CAP-69` and `CAP-86` are current only within their explicit evidence and
  limitation boundaries. Both have direct reachable implementation evidence,
  direct exercised test evidence, present implementation, and exercised tests.
- Typed steering (`CAP-92`) and steering patch (`CAP-93`) are not current.

## Important uncertainties

Unknown records preserve partial carrier evidence without asserting absence.
Gap records assert only demand-specific absence supported by their evidence and
basis. Proposed records remain future contracts, and derived records remain
bounded by typed inputs, unknown/failure behavior, freshness, and prohibited
interpretations.

## Conflicts found

No decisive unresolved conflict or blocking question is bypassed by a current
or derived classification. The review correction prevents a classification
basis that claims a conflict or question from omitting its canonical link.

## Decisions required

No additional Phase 2 decision is required. Later work may implement proposed,
gap, or unknown demands only with new qualifying evidence and contract review.

## Artifact paths

- `research/ui-foundation/capabilities/registry.yaml`
- `research/ui-foundation/capabilities/derivations/DRV-1.yaml` through
  `DRV-11.yaml`
- `research/ui-foundation/capabilities/gaps.md`
- `research/ui-foundation/catalog/ids.yaml`
- `research/ui-foundation/catalog/claims.yaml`
- `research/ui-foundation/status.md`
- `research/ui-foundation/tools/validate.py`
- `tests/integration/test_ui_foundation_tools.py`

## Evidence pointers

`EVD-105`, `EVD-106`, `EVD-111`, and `EVD-112` provide the direct current and
test anchors used by the admitted current/derived boundary. The 902-file Phase
1 snapshot includes refreshed exact hashes for the validator and focused test.

## Recommended next delegation

Task 15 should falsify the 132 adjudications and 11 derivations independently,
with special attention to current evidence reachability, shared `DRV-5`, and
honest partial-versus-absent classification.

## Independent review correction

The prior all-gap report was stale and incorrect after data adjudication. This
correction makes scope-key uniqueness fail closed before set conversion,
requires one registry record and bound CAP allocation per demand, validates
direct current evidence/status, validates complete bidirectional derivations,
rejects false absence and forbidden current steering, and compares all Phase 2
metadata/projections exactly with the canonical registry.

## Commands and output

- `uv run python research/ui-foundation/tools/validate.py --phase 2` — exited 0
  with no diagnostics.
- `uv run pytest tests/integration/test_ui_foundation_tools.py -q` — **68
  passed**.
- `uv run ruff check .` — **All checks passed!**
- `uv run pyright research/ui-foundation/tools/validate.py` — **0 errors, 0
  warnings, 0 informations** (plus Pyright's non-failing update notice).
