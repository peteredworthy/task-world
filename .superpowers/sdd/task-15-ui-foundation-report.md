# Task 15 UI foundation adjudication report

## Scope

Adjudicate semantic-verification finding SV-002 after `9ba4c476d` without
modifying the immutable semantic-verification report.

## Source demand and finding

`journeys.B.validator-result` is the Journey B Judge requirement for a command
validator result. CAP-69 therefore remains current only for
`PatchValidationResult` from `validate_patch`, directly exercised by the invalid
patch matrix. It does not claim a decision response, patch-attempt readback, or
operator patch application.

`decisions.approve-gate-patch` requires approve, deny, and defer for a gate or
patch with proposal, validator, downstream-path, and explicit-next-state
semantics. The repository has separate graph decision fragments, raw patch
validation/application, and attempt readback. It has no human patch approval,
patch defer, or unified gate-or-patch command; CAP-86 is consequently
unknown/partial, not current. Q-5 remains linked because caller attribution is
not product-role authorization.

## Evidence adjudication

- EVD-105: `validate_patch` supports only `PatchValidationResult` for
  `graph.patch-validator`.
- EVD-106: the invalid patch matrix directly exercises patch validation and the
  patch-attempt readback.
- EVD-111: route implementation supports only `RecordGraphDecisionResponse`
  and `SubmitGraphPatchResponse`; the latter is raw patch application, never
  approval.
- EVD-112: authority-denial test directly exercises
  `RecordGraphDecisionResponse`.

`GraphPatchAttemptsResponse` is now attributed only to the actual readback test
evidence, and `SubmitGraphPatchResponse` only to actual route implementation
evidence.

## Validator regressions

The Phase 2 validator now requires every current output variant to identify a
command admitted by that demand and to have direct implementation plus exercised
test evidence for both semantic type and command identity. It rejects a copied
identical current contract when the definition or admitted command identities
differ, and rejects a current CAP-86 unless its required human patch-approval
and patch-defer commands have qualifying evidence.

## Result

Classification counts are **1 current, 0 derived, 25 proposed, 49 gap, and 57
unknown**. This earlier checkpoint adjudicated SV-001 and SV-002 only. The
follow-on adjudication handoff records SV-003 through SV-006 without modifying
the immutable verifier report.

## Current Task 15 closure checkpoint (2026-07-25)

This report's earlier SV-001/SV-002 counts are historical chronology. The current
closure checkpoint covers 210 status-evidence records (35 REL, 74 STA, 86 ACT, 9
EVI, 6 INV), with 513 SER and 1,050 SDR rows (455 admitted, 50 bounded, 8
rejected). It records 138 exact and 50 bounded test locators and a regenerated
119-base/119-node collection manifest. The projected bounded post-Phase1 remediation
snapshot is `snapshot-2026-07-26-task-15-complete`. Qualifying collected
test-coverage classifications, not test-execution results, are REL 13/22, STA 57/17,
ACT 56/30, EVI 2/7, INV 6/0 exercised/unexercised; 62 actions retain Q-5.

The fail-closed validator now requires clause-complete admitted test evidence,
current documentation evidence or typed stale/undocumented boundaries, reciprocal
unresolved CON authority for a documentation contradiction, status-matching
capability authority, and typed epistemic proof. Task 15 is **COMPLETE** following
material independent semantic review and a full passing verification gate; this
closure does not alter Phase 1 or the immutable verifier report.

## Post-adjudication source refresh

The graph projection readback fix is recorded in a post-Phase1 child snapshot for
`src/orchestrator/graph/projections.py`,
`src/orchestrator/graph_runtime/dispatch.py`,
`src/orchestrator/workflow/graph_driver.py`, and
`tests/integration/test_graph_run_driver.py`. The regression uses a real
transactional event store and confirms a persisted materialization produces the
same recovery readback as the full event fold. The immutable Phase 1 snapshot was not rewritten.
