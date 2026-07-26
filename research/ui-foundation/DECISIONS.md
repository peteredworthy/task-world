# UI foundation — recorded decisions (2026-07-26)

Peter reviewed `reviews/decisions-01.html` (17 consolidated decisions from agent
reports 01–11) and answered: **D1–D16 agree, D17 amended** (delete the catalog
machinery rather than freeze it in-tree: "If files shouldn't be referenced we
should remove them, otherwise they risk being pulled in again").

## Rulings now in force

**Identity & selection**
- **D1** `attempts.id` is the canonical attempt identity. No migration. The dead
  `AttemptRecord` dataclass was deleted from `src/orchestrator/db/orm/models.py`.
- **D2** Legacy tasks and graph nodes stay distinct — no cross-mode identity
  join; `task_region_id` is an opaque informational string. Revisit only if a
  concrete screen needs the join.
- **D3** One selection identity per route: `run.id` at route root; legacy detail
  by `task.id` (attempt via ordinal); graph detail by `node_id` scoped to run.

**Authority & attribution**
- **D4** Single-operator by design. Actor strings (`user`, `human-operator`,
  caller-supplied `decider`/`approved_by`) are unverified attribution labels:
  the UI renders them as provenance-of-record, never as authenticated identity,
  and builds no permission-gated UI. Unifying the five attribution mechanisms is
  optional cleanup.
- **D5** CLI `runs start` direct application is a documented local-operator
  compatibility path (noted in AGENTS.md Rule 4). The UI binds to REST
  semantics: 202 = accepted, not applied.
- **D6** REST rejection of cancel-while-STOPPING is correct; the internal
  stopping→cancelled transition is the sweep completion path, not an operator
  affordance. UI disables Cancel while stopping.

**State, feedback & honesty**
- **D7** SQL-event-first is the canonical write-authority statement (AGENTS.md
  already said so by review time; its stale `queued` status example was fixed).
- **D8** v1 action feedback = 202 + observe projections/WS. UI shows
  "accepted, applying…" until the projection confirms; never optimistic
  success. A typed command-outcome record is a backend backlog item.
- **D9** `Live` badge means "event stream connected" only; frontend-derived
  values are labeled as estimates.
- **D10** Cost honesty: totals labeled with coverage scope (graph executions);
  unpriced shown as unknown, never zero; estimates visually distinct from
  measured spend.
- **D11** Unimplemented JTBD metrics (health class, prompt pressure, churn,
  convergence, retry delta, causal gap, budget pace, cohorts, exact prompt/
  transcript accounting, node-file causality) stay gaps; v1 UI must not fake
  them with lookalike numbers.
- **D12** Single-process is the supported deployment; the task lock is
  process-local (noted in AGENTS.md).
- **D13** Vocabulary: graph-mode `failed` is reopenable; "review readiness" and
  "merge readiness" stay distinct; artifact variants stay separately named (no
  umbrella concept).

**Ops backlog (not UI-blocking)**
- **D14** Live-DB backup is not crash-consistent (`shutil.copy2`, no WAL/SHM,
  second-resolution id, no lock check in restore). Interim contract: backups
  valid only against a stopped server. Fix when picked up:
  `sqlite3.Connection.backup()`, collision-safe id, lock check.
- **D15** Classify/remove legacy `events`, `replay_checkpoints`, session JSON in
  the next cruft pass.
- **D16** Absent actions (watch/ignore, agent-test-fix, unified gate-or-patch,
  MCP patch-macro contract, steering) stay gaps; the design phase ranks which to
  request. Steering directive proposal is the standing candidate.

**Process**
- **D17 (amended)** The Phase 0–3 catalog machinery was **deleted**, not frozen:
  `catalog/`, `tools/`, `schemas/`, `reality/`, `capabilities/`, the generated
  projections (`status.md`, `source-map.md`, `open-questions.md`,
  `decision-log.md`), the generated review pages (`reviews/index.html`,
  `reviews/phase-3-reality-capability-01.html`), and their test files. History
  remains in git. The foundation deliverable is `agent-reports/01`–`11`,
  `reviews/decisions-01.html`, and this file.

## Remaining follow-ups

- Optional: uniqueness constraint on `attempts (task_id, attempt_num)` (needs an
  Alembic migration; skipped for now).
- Backend backlog: typed command-outcome record (D8), WAL-safe backup (D14),
  legacy persistence classification (D15).
- Design phase consumes: agent reports, `docs/jtbd/`, and these rulings.
