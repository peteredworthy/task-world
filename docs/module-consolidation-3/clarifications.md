# Module Consolidation 3: Design Clarifications

## Status: No Open Questions

After reviewing `intent.md`, `plan.md`, and `architecture.md`, there are no open design questions that require human input for this planning tranche.

## Decisions Already Fixed by the Planning Artifacts

1. The public contract remains the documented nine top-level modules only: `api`, `cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, and `workflow`.
2. The next wave is limited to boundary cleanup, internal consolidation, public export cleanup, and verification sequencing; it does not reopen the prior 19-to-9 consolidation history.
3. Execution must begin with a reality audit before structural refactors, and each later milestone is gated on documented evidence from earlier audits.
4. Work proceeds by domain in the order already defined in `plan.md`, with `workflow`/`state` and `runners` treated as the highest-risk areas.
5. Temporary shims, duplicate module trees, and undocumented top-level API drift are explicitly disallowed.
6. Verification uses real repository checks with `uv run` commands, including import-discipline checks plus relevant test, lint, and type gates.

## Remaining Unknowns

The remaining unknowns are execution-time discovery items, not human design decisions. They concern what the current codebase actually contains, which consumers still import internal paths, and whether documented risks still exist in practice.
