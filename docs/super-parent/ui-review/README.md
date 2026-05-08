# Super Parent UI Review

This folder is a focused review area for iterating on the Super Parent UI/UX after `docs/super-parent/intent.md` was implemented.

The review compares three things:

- What the frontend currently conveys.
- What information is available in the underlying run and oversight model.
- What jobs users are trying to complete when they use the tool.

The screenshots were captured from a local fixture server on May 4, 2026. The fixture used a Super Parent run with one linked child run so the parent/child oversight surfaces could be inspected without modifying the real development database.

## Resources

- [Current UI](current-ui.md) documents the screens that were inspected and what each screen communicates.
- [Available Model](available-model.md) lists the data already present in the API/model and how much of it is exposed by the UI.
- [JTBD and Workflows](jtbd-and-workflows.md) captures the likely jobs to be done, user journeys, and open questions.
- [Gap Analysis](gap-analysis.md) prioritizes product/UI gaps for future design work.
- [Presentation Outline](presentation-outline.md) is the source outline used for the review deck.
- [HTML review deck](deck/super-parent-ui-review.html) packages the findings for quick review.

## Screenshots

- [Dashboard flat list](screenshots/dashboard-flat-list.png)
- [Dashboard parent expanded](screenshots/dashboard-parent-expanded.png)
- [Parent detail oversight](screenshots/parent-detail-oversight.png)
- [Child detail](screenshots/child-detail.png)

## Scope Notes

This is an observational review, not a UI implementation pass. The review intentionally records both confirmed findings and unresolved JTBD questions so the folder can act as a working area for future UI/UX iterations.

One environment caveat: the real local development database did not start cleanly during this review because an Alembic migration attempted to drop a missing `tasks.phase_outputs` column. I did not modify or delete the real database. Screenshots were captured from an isolated temporary fixture database.
