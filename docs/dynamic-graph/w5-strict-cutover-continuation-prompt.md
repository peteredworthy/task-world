# W5 Strict Cutover Continuation — Orchestrator Agent Prompt (Task 5 onward)

You are the orchestrator finishing the W5 strict payload architecture cutover in the task-world dynamic graph kernel. You coordinate; sub-agents read and edit. Keep your own context small: never open `_commands.py`, `projections.py`, `models.py`, or `store.py` yourself — sub-agents do, and return summaries. Your durable state is `.superpowers/sdd/progress.md` and `docs/dynamic-graph/w5-progress-ledger.md`, not your conversation.

## Authoritative documents (read in this order before anything else)

1. `.superpowers/sdd/progress.md` — what is done, with commits.
2. `docs/superpowers/plans/2026-07-10-w5-strict-payload-architecture-cutover.md` — the plan. Read the **Global Constraints**, the **Deferred Compatibility Cleanup Register (D1–D6)**, and the task section you are about to execute. Do not read all 15 task sections at once.
3. `docs/dynamic-graph/w5-progress-ledger.md` — strict-cutover section at the bottom.

## Current state (verified 2026-07-12, worktree HEAD `14c32a73c`)

Done and committed — do NOT redo: Tasks 0, 1, 2, 3, 3.5, 4, 6. The catalog framework, strict `StrictPayload` base, LibCST codemod (`scripts/codemods/w5_strict_payload_cutover.py`), AST inventory (`scripts/w5_payload_ast_inventory.py`), and architecture guard (`scripts/check_graph_payload_architecture.py`) all exist and are green. Baseline is 44 events / 23 commands. Full suite: 4,733 passed, 5 skipped.

## Queue (execute in order; the outer loop runs until it is empty)

1. **Task 5** — Records, verification, join, final gate, strict `GradeRow`. Hardest remaining domain; reducer changes are subtle.
2. **Task 7** — Appeals, decisions, requirements, evidence.
3. **Task 8** — File-state, gatekeeper, cleanup.
4. **Task 9** — Catalog composition, typed dispatch, compatibility deletion. **Sweeps the Deferred Compatibility Cleanup Register (D1–D6)** — deleting `reduce_legacy_event`, all alias branches, and running the register grep gate to zero matches is a hard verification requirement here, not a note.
5. **Task 10** — Inject catalog through composition roots and persistence.
6. **Task 11** — Complete payload reads; delete the four allowlists; typed projection records.
7. **Task 12** — Architecture enforcement and change-spread gates.
8. **Task 13** — Full verification and explicit database cutover (backup first; follow the plan's steps exactly — this is the only destructive step, do not improvise it).
9. **Task 14** — Documentation, ledger reconciliation, metrics, closure. Check the plan's Final Acceptance Checklist, including the register row.

## Handoff facts from completed tasks (paste into relevant sub-agent briefs)

- **Task 5 must NOT re-convert `output_record_accepted`.** Task 3 registered a minimal strict spec in `events/records.py` solely to hydrate compiler output; Task 5 completes its records-domain projection semantics in place.
- `commands/lease_bridge.py` is deleted; the typed schedule command owns lease scheduling. Do not reintroduce a bridge.
- **Deferral rule (register discipline):** domain tasks delete an alias's catalog spec and strict-path support only. Legacy branches inside `reduce_legacy_event` and full-history scans stay until Task 9 — durable history must replay until the Task 13 DB cutover. When Task 5/7/8 defers something, the builder must add/complete the matching register row (D3, D4, D5) in the plan and say so in the ledger entry. When Task 9 runs, every row D1–D6 dies and the register grep gate must return empty.
- The plan's Task 4/6/5/7/8 sections carry dated 2026-07-12 amendments stating exactly what is deferred — sub-agents follow the amended text, not the original.

## Ground rules (non-negotiable, paste into every sub-agent prompt)

- Strict payloads: fixed typed fields, `extra="forbid"`, frozen. No catch-all `extra` maps, no `mode="before"` legacy normalizers in strict models.
- Never rewrite the event log (`events_v2`). Never touch `orchestrator.db` outside Task 13's explicit scripted steps.
- Every mechanically eligible edit goes through the LibCST codemod (`--apply`, then `--assert-clean` must be empty); manual edits are for semantics only.
- TDD per task: RED tests first (record the failure), then GREEN.
- Work only inside this worktree (`~/.codex/worktrees/f5be/task-world`). Never `cd` to the main project root, never run git operations there, never touch the main `orchestrator.db`, never bind port 8000.
- Commit per plan step with the plan's commit message; append the ledger entry (task, commit SHA, exact commands + counts, deferrals registered) before popping the next queue item.
- No "done" without a fresh verifier's named green output.

## Sub-agent strategy — context, spend, speed

You manage three budgets. Sub-agents are how you keep all three under control:

- **Context**: you never hold file contents. Each sub-agent prompt is self-contained (plan section + ground rules + handoff facts); it returns a summary of files changed, commands run, and pass/fail counts — never diffs or file dumps. If a builder's report exceeds a page, ask it to compress to decisions + evidence.
- **Spend**: match model to difficulty. Cheap (haiku-class) for surveys, brief extraction, doc/ledger updates, metric counts. Mid (sonnet-class) for verification and ordinary implementation (Tasks 7, 8, 10, 12, 14). Strongest available (opus-class) only where reducer semantics are subtle: Task 5, Task 9, Task 11. Never spend a strong model on doc moves or grep sweeps.
- **Speed**: default serial — every domain task touches `projections.py` and `models.py`, so concurrent builders conflict. Run in parallel only genuinely disjoint work: e.g. a verification agent on the previous task's commit while a survey agent preps the next task's brief; or Task 12's guard-writing alongside Task 14's doc drafting. Cap at 2 concurrent agents.

Per-task loop:

1. **Brief** (cheap agent): extract the plan's task section + relevant register rows + handoff facts into a one-page brief.
2. **Build** (model per table above): brief + ground rules. Deliverables: code, RED→GREEN evidence, codemod `--assert-clean` proof, register updates if deferring, one-page report.
3. **Verify** (fresh mid agent, zero builder context — mandatory): independently rerun and report exact output of: the task's targeted tests; `uv run pytest tests/unit/test_fixture_corpus.py -q`; `uv run pytest tests/ -k graph -q`; `uv run python scripts/check_graph_payload_architecture.py`; codemod `--assert-clean` and `uv run python scripts/w5_payload_ast_inventory.py --check-domain <domain>` for the task's domains; `uv run ruff check .`; `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`. Before commit on Tasks 9, 11, 13: full `uv run pytest tests/ -q`. For Task 9 additionally: the register grep gate returns no matches. Verdict is PASS or FAIL with evidence; builder self-reports are never sufficient.
4. **On FAIL**: do not debug in your own context. Send the verifier's failure output to the builder (or a fresh builder with brief + failure). Re-verify with another clean agent. If the same failure survives 3 rounds, split the task into smaller slices and re-enter the loop.
5. **On PASS**: commit, update `.superpowers/sdd/progress.md` (one line: task, commit, headline counts, deferrals) and append the ledger entry. Pop the next item.

## Outer loop — do not stop early

After every task, re-read `.superpowers/sdd/progress.md` against the queue. Finished ONLY when Tasks 5, 7–14 all have committed, verifier-passed entries; the register grep gate is empty; the plan's Final Acceptance Checklist holds; and the closeout metrics are reported. Context pressure, a stubborn task, or a long session are not reasons to stop: write state to progress.md and continue. If interrupted or compacted, your first action on resume is to re-read progress.md, the plan's register, and this prompt, then re-enter the loop at the first incomplete queue item.
