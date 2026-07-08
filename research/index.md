# Research Wiki — Index

> Created 2026-07-07 at HEAD `23746c228`. Line-number references throughout
> are anchored to that commit.

## Start here

- [system/overview.md](system/overview.md) — synthesis: what the system is,
  what's intentional vs accidental, strength/weakness table, one-paragraph
  thesis.
- [recommendations/README.md](recommendations/README.md) — executive summary,
  roadmap, settled decisions, rejected options.

## Current system understanding

- [system/overview.md](system/overview.md) — orientation synthesis
- [system/graph-kernel.md](system/graph-kernel.md) — event-sourced kernel,
  control loop, dynamic patching, invariants, fragility list, solid list
- [system/runtime-runners-cost.md](system/runtime-runners-cost.md) — runners,
  profile→model resolution, cost capture and its holes, prompt inventory,
  observability inventory
- [system/design-history.md](system/design-history.md) — intent docs,
  chronology, W-spec status table, documented gaps, divergences, design
  principles to preserve

## External evidence digests

- [external/orchestration-topologies.md](external/orchestration-topologies.md)
  — single vs multi-agent, shipped topologies, handoff regimes, loop safety
- [external/context-engineering.md](external/context-engineering.md) —
  context rot, caching economics, memory blocks, compaction failure modes,
  handoff contracts
- [external/verification-evals-routing.md](external/verification-evals-routing.md)
  — LLM-judge biases, execution oracles, revision economics, eval patterns,
  observability vocabulary, routing/cost control
- [external/workflow-frameworks.md](external/workflow-frameworks.md) —
  Superpowers, GSD, Spec Kit, BMAD & co.: what they constrain, the
  (near-total) absence of controlled measurements, and the indirect
  evidence (METR RCT, Agentless, HULA funnel, DORA 2025) that does exist
  *(added 2026-07-07, after the initial pass)*
- [external/reconsider-and-sketch.md](external/reconsider-and-sketch.md) —
  "reconsider" (checkpoint-to-side-branch + pivot) and "sketch" (pre-build
  design model) as candidate first-class agent operations: sunk-cost
  evidence, tree-search systems (SWE-Search/LATS/AIDE), decomposition-sketch
  measurements (Parsel/AlphaCodium/Sketch-and-Verify), and the gap — no
  orchestrator hands either move to the agent *(added 2026-07-07, third
  pass)*
- [external/structural-code-navigation.md](external/structural-code-navigation.md)
  — structural topology navigation over flat-text repo context: dual-process
  architect/worker split (CodeTeam SDS contracts), skeletonization
  (Hydra DAR, OpenClassGen), graph-bounded tooling (CodeCompass Navigation
  Paradox vs LARGER embed-in-search), and what each changes for R05/R06
  *(added 2026-07-07, fourth pass)*

## Recommendations (prioritized)

| | |
|---|---|
| [R01 — close known safety gaps](recommendations/01-close-known-safety-gaps.md) | P0 |
| [R02 — execution-first verification](recommendations/02-execution-first-verification.md) | P1 |
| [R03 — revision & escalation policy](recommendations/03-revision-escalation-policy.md) | P1 |
| [R04 — cost telemetry & budgets](recommendations/04-cost-telemetry-and-budgets.md) | P1 |
| [R05 — context assembly hardening](recommendations/05-context-assembly-hardening.md) | P2 (pinning P1) |
| [R06 — typed handoff contract](recommendations/06-typed-handoff-contract.md) | P2 |
| [R07 — orchestrator eval harness](recommendations/07-orchestrator-eval-harness.md) | P1 |
| [R08 — consolidation & legacy shrink](recommendations/08-consolidation-and-legacy-shrink.md) | P2 |

## Reference

- [sources.md](sources.md) — annotated external source list with caveats
- [open-questions.md](open-questions.md) — unsettled questions + how to
  settle each

## Future research threads

- Best-of-n + agentic verifier for high-stakes nodes (after R07 exists to
  price it) — see verification digest.
- Planner effort calibration tiers (OQ-6).
- SQLite scaling / storage successor decision (OQ-4).
- Scope-reduction invariant field trial (OQ-9).
- Cache-hit instrumentation across runner types (OQ-10).
- Watch for CURRANTE Stage 2 results (SANER 2026) — first controlled test
  of spec-driven workflow claims; see external/workflow-frameworks.md §5.
- Naming / responsibility-assignment / encapsulation-level as isolated
  variables in agent code quality — no measurements exist; see
  external/reconsider-and-sketch.md §2.3.
