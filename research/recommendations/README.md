# Recommendations — Executive Summary

> Compiled 2026-07-07 at HEAD `23746c228`, from repository inspection
> ([../system/](../system/)) and external research ([../external/](../external/)).
> Each recommendation file carries its own evidence, risks, and validation plan.

## Recommended direction

**Keep the architecture. Add the policy layer, the oracles, and the
instruments.**

The typed, event-sourced, controller-authoritative work graph with
fresh-context builder/verifier phases is the pattern 2025-26 production
evidence converged on (Cognition's review-loop, OpenHands' event-sourced
rewrite, the durable-execution wave, Anthropic's managed agents). Nothing in
the external evidence argues for a topology change, a framework migration, or
more agents. The gaps are:

1. closure of past incidents that is believed-but-not-pinned (and status
   docs stale in both directions),
2. verification that leans on the weakest oracle (LLM judgment) where
   deterministic facts and test execution are available,
3. no evidence-based retry/escalation/budget policy,
4. cost telemetry too holed to steer by, and
5. no instrument that says whether a change made runs better.

## Prioritized roadmap

| # | Recommendation | Priority | Size | Depends on |
|---|---|---|---|---|
| [R01](01-close-known-safety-gaps.md) | Incident-replay regression pinning supersession closure · machine-visible unmatched-model cost + rate-table reconciliation · stale W-ledger corrections | **P0** | S | — |
| [R04](04-cost-telemetry-and-budgets.md) | Cost telemetry (OTel vocab, finish_reason, reasoning tokens, rollups) → then budgets + effort tiers at dispatch | **P1** | M | R01c; rides W5 |
| [R02](02-execution-first-verification.md) | Execution-first verification: oracle-classified requirements, deterministic pre-verifier facts, minimal binary rubrics | **P1** | M | — |
| [R07](07-orchestrator-eval-harness.md) | 10-20 frozen-task eval harness with trajectory assertions from the event log | **P1** | M | R04 ph.1 |
| [R03](03-revision-escalation-policy.md) | Cap repairs at 2 → escalate model tier fresh → typed `revision_exhausted` blocker; duplicate-diff short-circuit | **P1** | S-M | R04, R07 to measure |
| [R05](05-context-assembly-hardening.md) | Constraint pinning + recitation (do early — cheap); per-field budgets; pointer-first hydration; cache ordering; assembler tests | **P2** (pinning P1) | M | W5, R07 |
| [R06](06-typed-handoff-contract.md) | Brief completeness at patch admission; decisions register; structured failure records | **P2** | M | R05 budgets |
| [R08](08-consolidation-and-legacy-shrink.md) | Single prompt source; W8 + drive-loop relocation; legacy disposition inventory (not migration phases 3-5); TD-06 | **P2** | M-L | after R01 |

Suggested first month: R01 → R04 phase 1 + R05 item 1 (constraint pinning) →
R02 → R07 seed suite → R03. Everything P2 waits for the instruments to exist.

## Key architectural decisions (settled by this research)

- **No parallel writers, ever.** Parallelism policy derives from read/write
  node annotations; fan out only read-only work (exploration, review,
  research). Already enforced by resource claims incl. the merged W7
  segment-overlap fix.
- **Policy lives in the kernel/runtime as data, not in prompts**: retry caps,
  escalation targets, budgets, brief-completeness, loop guards are all
  patch-admission or dispatch-time checks. This is the system's existing
  principle ("permissions are data") extended to economics.
- **The event log is the single read path everywhere** — the graph stack is
  done; the remaining work is shrinking the legacy surface, not finishing its
  migration (R08).
- **Verification hierarchy**: deterministic environment facts → executed
  tests → minimal binary LLM rubric per requirement, in that order of
  authority (R02). Builder never self-grades; verifier context stays clean
  (only the diff and the contract — already the design).
- **Static profile routing + effort tiers, no learned router** at this scale.

## Prompting & handoff recommendations (condensed)

- Pin acceptance criteria verbatim; recite objective near prompt end (R05).
- Distilled, typed feedback between attempts — never accumulated prose (R03/R06).
- Briefs must carry objective/boundaries/output-contract, enforced at patch
  admission (R06).
- Verifier prompts: one requirement, binary verdict, no "explain and propose
  fixes" (bias evidence, R02).
- Stable→volatile prompt ordering, deterministic serialization (R05).

## Risks & mitigations (cross-cutting)

- **Measurement before policy**: R03/R05 tuning without R04/R07 would be
  guesswork — hence the sequencing.
- **Kernel changes near the incident zone** (projections, drive loop):
  convert incident comments to named regression tests before refactoring
  (R01, R08).
- **Eval overfitting**: held-out tasks + quarterly rotation (R07).
- **Quota reality**: escalation targets and effort knobs resolve per-runner
  and degrade gracefully where unsupported (R03, R04).

## Rejected or deferred options

| Option | Verdict | Why |
|---|---|---|
| Migrate to LangGraph/Temporal/other framework | Rejected | The kernel already implements their core value (durable deterministic orchestration) with better domain typing; migration is pure risk |
| Learned model router (RouteLLM-style) | Rejected | Evidence doesn't transfer to agentic coding; solo scale can't train/maintain it; static profiles + effort tiers capture the win |
| Parallel builder swarms / best-of-n as default | Rejected (deferred for high-stakes nodes only) | Cost multiplier; evidence favors single writer + verifier; revisit via R07 data where a runnable oracle exists |
| Finish legacy event-migration phases 3-5 as written | Deferred → replaced by disposition inventory (R08) | Migrating code that should retire is wasted motion |
| Wholesale OTel/observability platform adoption | Rejected | Adopt the attribute vocabulary only; the event store is already the trace store |
| Scope-reduction invariant as blocking admission rule | Deferred | Sound idea, unproven measure; ship as warning first (OQ-9) |
| New memory/RAG subsystem | Rejected | Typed graph state + filesystem artifacts already implement the memory-block pattern; add budgets/pointers, not a new system |

## Open questions

Tracked in [../open-questions.md](../open-questions.md) — OQ-1 (verifier
diversity), OQ-2 (verifier overcorrection rate), OQ-3 (gap_planner ROI),
OQ-4 (SQLite ceiling), OQ-5 (claude_sdk fate), OQ-6 (planner effort tiers),
OQ-7 (legacy disposition), OQ-8 (budget denomination), OQ-9 (scope
invariant), OQ-10 (cache wins under subscription runners).
