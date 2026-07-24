# Task 14 UI foundation report

## Purpose

Adjudicate every closed Phase 2 source demand, admit only evidence-qualified
current and deterministic derived capabilities, and project the canonical
registry without losing classification distinctions.

## Scope inspected

The 132-demand scope manifest, canonical Phase 1 evidence and ID ledgers,
action/state contracts, the superseded derivation ledger, Phase 2 validator,
claims/status/gaps projections, and focused integration tests.

## Key findings

- `CAP-1` through `CAP-132` map one-to-one to unique immutable scope-demand
  keys and matching order-independent `ids.yaml` allocations.
- The corrected classifications are **2 current, 0 derived, 25 proposed, 49
  gap, and 56 unknown**.
- No derivation is active. The eleven historical `DRV` ledger allocations are
  retained as superseded semantic records, rather than using unrelated
  CAP-69/EVD-105 evidence to manufacture derived capability claims.
- `CAP-69` and `CAP-86` are current only within their explicit evidence and
  limitation boundaries. Both have direct reachable implementation evidence,
  direct exercised test evidence, present implementation, and exercised tests.
- Typed steering (`CAP-92`) and steering patch (`CAP-93`) are not current.
- `capabilities/registry.yaml` is the sole canonical source for all 49 gap and
  56 unknown adjudications. The persisted `task-14-gap-carrier-audit.md` is a
  historical review artifact and is never parsed to create or update YAML. The
  49 gaps are **42 partial** and **7 absent**; all unknown records are partial.
- Partial carriers are now typed demand bindings with an explicit role,
  semantic type, and cited evidence support. This prevents activity evidence
  from standing in for action reversibility, permission authority, or usage
  telemetry.

## Important uncertainties

Unknown records preserve split or incomplete carrier evidence and their
conflicts without asserting absence. Every partial gap names an audited Phase 1
carrier; the seven absent gaps have an explicit demand-specific absence basis.
Proposed records remain future contracts.

## Conflicts found

No decisive unresolved conflict or blocking question is bypassed by a current
or derived classification. The review correction prevents a classification
basis that claims a conflict or question from omitting its canonical link.

## Decisions required

No additional Phase 2 decision is required. Later work may implement proposed,
gap, or unknown demands only with new qualifying evidence and contract review.

## Artifact paths

- `research/ui-foundation/capabilities/registry.yaml`
- `research/ui-foundation/capabilities/gaps.md`
- `research/ui-foundation/catalog/ids.yaml`
- `research/ui-foundation/catalog/claims.yaml`
- `research/ui-foundation/status.md`
- `research/ui-foundation/tools/validate.py`
- `tests/integration/test_ui_foundation_tools.py`

## Evidence pointers

`EVD-105`, `EVD-106`, `EVD-111`, and `EVD-112` remain direct current/test
anchors only within their actual output semantics. `EVD-105` supports only
`PatchValidationResult`; it cannot support prompt size or another output merely
because a capability or derivation copies its ID. The Phase 1 snapshot includes
refreshed exact hashes for the validator and focused test.

## Recommended next delegation

Task 15 should falsify the 132 adjudications independently, with special
attention to current evidence reachability and honest partial-versus-absent
classification.

## Independent review correction

This correction reclassifies the invalid derived claims, preserves superseded
derivation history with immutable semantic ledger keys, requires typed future
derivation bindings and relevant evidence chains, validates partial/absent gap
carrier semantics, rejects false absence and forbidden current steering, and
compares all Phase 2 metadata/projections exactly with the canonical registry.

The final review correction additionally requires output contracts for every
current or derived capability, validates derivation output semantics against
canonical direct evidence declarations, requires nonempty carrier-local
evidence on every partial gap or unknown binding, rejects absent/non-executable
implementation carriers and absence-binding overlap, and rejects normalized
duplicate prose and known generic unknown fallback text.

The final Task 14 review correction tightens non-action carrier executability
to present or partial status, binds unpriced share to the graph usage rollup
and repeated work to the structured tool trace, and records both EVI carriers
as partially implemented with bounded coverage. CAP-69 and CAP-86 now declare
all supported graph decision, patch-validation, and patch-route response
variants; each variant has direct implementation and exercised-test evidence.
All 49 gap definitions state their concrete carrier boundary or absent contract
and are projected verbatim from the registry.

The remaining review correction requires every current or derived capability to
declare a nonempty, duplicate-free asserted variant list whose values exactly
match the duplicate-free contract variant semantic types. Contract variants
also reject duplicate fields. CAP-69 and CAP-86 retain their existing variant
sets unchanged.

## Commands and output

- `uv run python research/ui-foundation/tools/validate.py --phase 2` — exited 0
  with no diagnostics.
- `uv run pytest tests/integration/test_ui_foundation_tools.py -q` — focused
  validation coverage passed (**101 passed**), including independent negative
  carrier-role, executable-status, output-variant, asserted/contract variant,
  duplicate-field, and derivation-binding cases.
- `uv run ruff check .` — **All checks passed!**
- `uv run pyright` — **0 errors, 0 warnings, 0 informations** (plus Pyright's
  non-failing update notice).
- `uv run pytest` — **5025 passed, 3 skipped, 3 warnings** in 156.09 seconds.
