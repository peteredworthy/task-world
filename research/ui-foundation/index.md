# Grounded UI/UX Foundation

Implementation-grounded record of how the orchestrator actually works, produced
as pre-work for the UI design phase. It does not define product screens or view
contracts.

## Contents

- [`agent-reports/01`–`07`](agent-reports/) — the seven reality audits
  (domain/persistence, graph runtime, workflow state, API/actions/authority,
  evidence/telemetry, UI projections, tests/documentation), plus syntheses and
  verification in 08–11. These are the substance: readable findings with exact
  code and test citations.
- [`reviews/decisions-01.html`](reviews/decisions-01.html) — the 17 consolidated
  decisions (D1–D17) distilled from the reports, reviewed by Peter 2026-07-26.
- [`DECISIONS.md`](DECISIONS.md) — the recorded answers and rulings now in
  force. Read this first.

## 2026-07-26 teardown notice

The original Phase 0–3 pipeline also produced a canonical-YAML catalog layer
(`catalog/`, `reality/`, `capabilities/`, `schemas/`, `tools/validate.py`,
generated projections, and the `phase-3-reality-capability-01.html` checkpoint).
That layer inflated far past its value — a 280 KB validator, ~4 MB of YAML, and
review questions that lost their meaning through ID normalization — and was
**deleted** per decision D17 (amended). Git history before this date retains all
of it. Do not rebuild it: audit deliverables here are readable Markdown with
code citations, not machine-validated catalogs.
