# Task 2 UI Foundation Handoff

## Status

Complete. Phase 0 has a closed source-demand manifest, immutable source snapshot,
coordination projections, explicitly incomplete Phase 1–3 typed shells, bounded
delegation report, and static review index shell.

## Files

Created:

- `research/ui-foundation/index.md`
- `research/ui-foundation/status.md`
- `research/ui-foundation/source-map.md`
- `research/ui-foundation/decision-log.md`
- `research/ui-foundation/open-questions.md`
- `research/ui-foundation/catalog/{scope,ids,claims,invariants,conflicts,questions,decisions,evidence}.yaml`
- `research/ui-foundation/reality/{domain-model,relationships,state-model,permissions}.yaml`
- `research/ui-foundation/reality/evidence/inventory.yaml`
- `research/ui-foundation/capabilities/registry.yaml`
- `research/ui-foundation/capabilities/gaps.md`
- `research/ui-foundation/agent-reports/00-delegation-plan.md`
- `research/ui-foundation/reviews/index.html`
- `.superpowers/sdd/task-2-ui-foundation-report.md`

The five JTBD documents and approved design were read but not modified. No action
contract, derivation, Phase 3 review batch, product UI, or Phase 1 finding was
created.

## Commands and output

1. Red acceptance check:
   `uv run python research/ui-foundation/tools/validate.py --phase 0`
   failed with the expected 14 `REQUIRED_FILE_MISSING` issues before creation.
2. Snapshot generation:
   `uv run python -c '<SHA-256 calculation>'` recorded six source hashes;
   `git rev-parse HEAD` returned
   `d34fb47e3759124f7fc641118aad3947a511ecc2` as snapshot metadata.
3. Green acceptance check:
   `uv run python research/ui-foundation/tools/validate.py --phase 0`
   exited 0 with no diagnostics.
4. Delegation report check:
   `uv run python research/ui-foundation/tools/validate.py --report research/ui-foundation/agent-reports/00-delegation-plan.md`
   exited 0 with no diagnostics.
5. Scope audit script reported:
   `demands=130 unique_keys=130 owners=7`; all five JTBD sources are represented,
   every owner is a scalar member of the declared seven-owner set, and every
   declared owner owns at least one demand.
6. Source preservation check:
   `git diff -- docs/jtbd/jobs.md docs/jtbd/journeys.md docs/jtbd/decision-information.md docs/jtbd/information-architecture.md docs/jtbd/evaluation-rubric.md`
   produced no diff.
7. Commit hooks passed: secret detection, full pytest, UI lint, and UI typecheck;
   non-applicable hooks were skipped normally.

## Commit

Artifact commit: `d9ad39638` (`docs: establish UI foundation phase 0 scope`).
This handoff file is committed separately so it can cite the artifact commit;
the final handoff commit SHA is returned to the caller.

## Self-review

- The 62 atomic `Must know` fields are represented.
- All 10 decision-inventory rows are represented as eight implemented-action
  candidates and two absent interventions.
- All seven honesty rules and all six action-feedback requirements are present.
- Named initial claims are explicit: health class, current constraint, blast
  radius, final-gate effect, planner horizon, evidence convergence, retry
  information delta, comparable cohort, prompt pressure, repeated work, budget
  pace, and causal gap.
- Journey continuity, health-model, and evaluation demands keep all five JTBD
  documents in the closed scope without asserting implementation truth.
- Every demand has exactly one audit owner; keys are unique.
- Snapshot hashes validate against current content and are the drift authority.
- Phase 1–3 shells use `phase_status: incomplete`; no missing collection is
  presented as completed.
- The review shell says “Semantic foundation, not a product mockup.” and contains
  status only.
- The pre-existing `.superpowers/sdd/progress.md` modification was preserved and
  excluded from both Task 2 commits.

## Concerns

No Task 2 defect is known. Downstream readiness remains intentionally blocked on
all seven Phase 1 audits; Phase 0 completion must not be read as evidence that any
source capability claim is current or derived.
