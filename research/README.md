# research/ — Orchestrator Evolution Research Wiki

Durable research into how this dynamic graph orchestrator should evolve:
current-system understanding, distilled external evidence (2024-2026), and a
prioritized, evidence-tied recommendation set.

**Read [index.md](index.md) for the page map.**
**Decision-makers: start at [recommendations/README.md](recommendations/README.md).**
**Implementation agents: read [system/overview.md](system/overview.md) first,
then the specific recommendation you're executing — each contains repo
evidence (file:line at HEAD `23746c228`), external evidence, risks, and a
validation plan.**

## Method

Produced 2026-07-07 by a multi-agent research pass:

- Three repository-mapping agents (graph kernel; runners/cost/observability;
  design docs vs reality), findings cross-checked against git log and source.
- Three external-research agents (orchestration topologies; context
  engineering; verification/evals/routing), primary sources preferred, every
  claim confidence-tagged.
- Synthesis and recommendation drafting in the main session; a verification
  pass then spot-checked load-bearing repo claims against source. That pass
  materially corrected three initial claims (W7 glob-overlap is merged, not
  open; cross-region supersession handling exists in `projections.py`; the
  $0 unknown-model fallback is intentional at the UI level) — treat other
  status-doc-derived claims with the same suspicion.

## Epistemics

- Repo claims cite file:line at commit `23746c228`; they will drift — trust
  the concept, re-verify the line.
- External claims carry confidence tags (High/Med/Low or
  strong/consensus/anecdote); 2026 arXiv numbers are indicative, directions
  probably robust — see caveats in [sources.md](sources.md).
- Recommendations separate evidence from proposal; where a proposal rests on
  judgment rather than data, the file says so, and unresolved items live in
  [open-questions.md](open-questions.md) with a path to settle each.

## Maintenance

- When a recommendation ships, note the commit in its file and move any
  falsified assumptions into open-questions or a postmortem note.
- New incidents/design docs should update
  [system/design-history.md](system/design-history.md)'s gap list.
- Keep this wiki about *why and what*; the how belongs in specs under
  `docs/`.
