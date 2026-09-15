# Decisions and runtime execution

## Integrated verification, September 15

Final review replaced a qualification wrapper that could report completion while
stored work remained active. The closure uses production joined execution,
exact committed products, durable failure evidence and terminal ownership checks.
The original slice 6B success cases were found in the main checkout and preserved.
[The final review and closure ledger](slice-6f-final-review.md) records the fixes,
independent review, source manifest and gate evidence. The
[rollout and evaluation card](slice-6f-rollout-card.md) keeps model evaluation
unexecuted. Earlier ledgers below describe historical passes.

## Historical preparation and intermediate status

Prepared September 11, 2026 for implementation by supervised Sol builders.
This package specifies proposed changes. It does not claim they are implemented.

Implementation status, September 12: slices 1–3 have implementation ledgers.
The [slice 3 review](slice-3-review.md) found validation defects and an unresolved
rejected-plan recovery contract. Its verdict and the slice 4 prerequisites in
[implementation.md](implementation.md) govern the next assignment. The
preparation record below remains historical design evidence.

The model should answer the substantive question in each step. The runtime
should perform the mechanical consequences, including in steps that mix judgment
with bookkeeping. Code authoring and evidence inspection remain substantive
work; graph wiring, identity selection, candidate bookkeeping and lifecycle
transitions belong to the runtime.

Read [architecture.md](architecture.md), then [contracts.md](contracts.md). They
fix ownership, durability, answer shapes and failure accounting so builders do
not independently invent competing designs.
[implementation.md](implementation.md) contains the ordered Sol prompts and
acceptance criteria. [review-prompt.md](review-prompt.md) is the separate review
assignment used after each implementation slice.

Start a Sol builder with this prompt:

> Work in `/Users/peter/code/task-world/worktrees/recovery-stabilization`.
> Read `AGENTS.md`, `docs/intent/31-decision-runtime/architecture.md`,
> `docs/intent/31-decision-runtime/contracts.md`, and
> `docs/intent/31-decision-runtime/implementation.md`. Execute only the first
> uncompleted slice, including its prerequisites and validation. Follow the
> shared execution rules in that document. Preserve existing changes and
> evidence. Report exact changes, checks, remaining gaps and source hashes;
> do not activate anything or run a paid orchestration probe.

Use `gpt-5.6-sol` with high reasoning for implementation and a fresh Sol context
for review. Keep one builder editing shared graph/runtime files at a time. The
architect should resolve a contract change before dependent builders proceed.
These instructions prepare future work; no builder has been dispatched to make
the implementation changes by this documentation pass.

[preparation-result.json](preparation-result.json) records the source-integrity
check, independent design reviews and final document hashes. The reviews assess
the proposed contracts; they do not certify implementation or model reliability.

The implementation baseline is
[`recovery-successor-validation-result.json`](../../reviews/recovery-successor-validation-result.json):
49 source/regression/document hashes, complete pre-commit exit 0, 6,082 passing
tests and five skips. Its hashes and all 85 historical artifact hashes still
matched during this preparation. The existing initial/successor probes and
seven-phase deterministic lifecycle are evidence and regression fixtures, not
the specification for the new model-facing interaction.

The previously prepared paid successor experiment remains unauthorized. It
exercises the old construct-then-submit interaction. It cannot qualify the
proposed decision interface. Preserve its results; give new-contract experiments
separate identities and obtain explicit authorization before any model run.

## Completion standard

The work is complete when mixed steps retain their useful model judgment while
the runtime enforces their mechanical consequences; ordinary decision-field
changes have one schema owner; fresh and historical graphs keep explicit
compatible behavior; and joined deterministic evidence proves candidate,
recovery and finalization behavior. Real-model reliability is a separate,
authorized evaluation with a fixed denominator, correctness criteria and budget.
