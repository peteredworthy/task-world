# Open Questions

Questions the research surfaced but did not settle. Each lists what would
settle it. Ranked roughly by decision impact.

## OQ-1: Verifier model diversity vs subscription economics
Evidence says the verifier should be a *different* model from the builder
(self-preference bias), but the project runs on subscription CLIs
(Claude Code, Codex) with quota limits. Is cross-vendor verification
(codex builds / claude verifies) worth the quota split, or is same-vendor
different-tier enough?
**Settle by:** A/B over the frozen eval suite (see recommendation 07):
same-model vs cross-model verifier, measure false-pass/false-fail rates.

## OQ-2: How much revision-loop churn is verifier overcorrection?
External data says LLM judges flag correct code as non-compliant, and richer
judge prompts make it worse. We have no measurement of our own verifier's
false-fail rate.
**Settle by:** sample N completed runs, re-grade failed requirements against
executed tests / human spot-check; instrument "verifier fail overturned on
revision without code change" as a standing metric.

## OQ-3: Does the gap_planner earn its cost?
Docs note gap-planners firing on success and redundant acceptance-suite runs
(pure invariant-satisfaction work). No cost attribution per node kind exists
yet.
**Settle by:** after cost-telemetry fixes, report tokens/$ by node kind across
a month of runs; compare against defects the gap path actually caught.

## OQ-4: Where is the SQLite ceiling?
BUSY_SNAPSHOT incidents were mitigated (BEGIN IMMEDIATE, retries, W3
snapshots), but the single-writer pressure grows with graph size and event
volume. Is the next step per-run DB files, a WAL-tuned single DB, or Postgres?
**Settle by:** load test: replay the largest historical run at 2×/4× event
volume; measure command latency and lock contention before choosing.

## OQ-5: Repair or retire claude_sdk as a graph runner?
Graph submit is broken ("Stream closed"), telemetry is degraded, clarification
is a stub. Its unique value (in-process, OAuth reuse) may not justify the
maintenance.
**Settle by:** timebox one repair attempt against the current SDK version; if
not fixed, gate it to legacy-carrier only and document.

## OQ-6: What is the right horizon-planning effort calibration?
Single-task routines already get minimal graphs, but there is no measured
policy for when a run deserves discovery regions, gap analysis, or
final-invariant regions vs a straight worker+verifier chain.
**Settle by:** tag historical runs by graph shape vs outcome; propose 2-3
planner effort tiers and eval them on the frozen suite.

## OQ-7: Should legacy-carrier event migration (phases 3-5) ever be finished?
The graph carrier already embodies the target architecture. Finishing the
legacy migration may be wasted motion if legacy is destined for deletion —
but legacy still hosts the drive loop and the routine/approval surfaces.
**Settle by:** inventory what still executes only via the legacy engine; if
the list is short, write a deprecation plan instead of migration phases 3-5.

## OQ-8: Per-node budget denominated in what?
Dollars are accurate only after telemetry fixes; tokens are model-relative;
wall-clock is noisy. What unit should kernel-enforced budgets use?
**Settle by:** implement budgets as tokens+dollars both recorded, enforce on
whichever is defined for the node; revisit after a month of data.

## OQ-9: Scope-reduction invariant — enforceable or aspirational?
The loop-safety literature suggests every delegation should declare strictly
smaller scope. Our patch validator could enforce a monotone measure (e.g.
region depth, claimed path width), but a bad measure would block legitimate
replans.
**Settle by:** prototype the measure as a *warning* (event, not rejection) and
observe false-positive rate over real runs before making it blocking.

## OQ-10: Cache-aware prompt assembly — measurable win here?
The caching argument assumes API-metered usage; subscription CLI runners may
see latency wins but no direct dollar wins, and codex_server pricing differs.
**Settle by:** measure cache-read fractions from the runners that report
them (claude_cli action logs) before and after preamble stabilization.
