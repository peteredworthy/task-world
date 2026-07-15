# W5 Continuation — Orchestrator Agent Prompt

> Historical compatibility-first prompt. Its execution queue is superseded and
> complete; use `w5-strict-cutover-continuation-prompt.md` for the final handoff.
> Final closure docs are `1b03d5a05` / `938b87ff7`; final source repair is
> `185f31abc`. The body below remains historical evidence, not current guidance.

You are the orchestrator for completing W5 (typed payloads) in the task-world dynamic graph kernel. You coordinate; sub-agents do the reading and editing. Your job is to keep your own context small, spend tokens only where they buy correctness, and land the work in verifiable slices.

## Mission

Replace the remaining `dict[str, Any]` payload handling in the graph kernel with typed Pydantic models, in this priority order:

1. **Event payload models** — a discriminated set of models, one per event type, replacing `EventEnvelope.payload: dict[str, Any]` consumption in reducers and command handlers.
2. **Allowlist generation** — derive the four hand-maintained store field allowlists (`GRAPH_PROJECTION_PAYLOAD_FIELDS` in `graph/projections.py`, plus `LIGHT_GRAPH_PAYLOAD_FIELDS`, `SUMMARY_REBUILD_PAYLOAD_FIELDS`, `NODE_DETAIL_PAYLOAD_FIELDS` in `graph_runtime/store.py`) from the typed models instead of maintaining them by hand.
3. **Command payload models** — typed models replacing `payload: dict[str, Any]` in `apply_command` (`graph/commands/__init__.py`) and the 23 registered handlers.
4. **`VerificationReportValue.grades`** — a `GradeRow` model with `extra="allow"` for the recurring keys.

**Explicitly out of scope (do not type these):** patch `ops`/`macro_invocations` (patch_validator owns that schema), `command_definition` (provider-specific), `diagnostics`/`read_set_diff`, edge `metadata`/policy fields, decision `scope`/`decider`, `TypedRecordBase.payload`/`provenance`. If a sub-agent proposes typing one of these, reject it.

## Ground rules (non-negotiable)

- **Containment rule:** every payload model = fixed typed fields + at most ONE free-form `extra: dict[str, Any]` sub-field. Where free-form keys currently ride at payload top level, migrate them under `extra`. HTTP/CLI API shape changes are acceptable (single-machine system, no external clients).
- **The event log is the real compatibility surface.** `events_v2` is durable history; old runs replay through new models. Use the existing lenient pattern (`model_config extra="ignore"`, `mode="before"` validators normalizing legacy shapes — see `LegacyOutputRecord` and `VerificationReportRecord` in `graph/models.py` for the house style). Never rewrite the event log.
- **One event-family per slice**, per the closed historical spec at `docs/dynamic-graph/complete/w5-typed-payloads-spec.md`. A slice = models + producer emission + reducer consumption + legacy normalization + tests, merged together.
- **No "done" without named green tests.** Follow the `p1-resolution-ledger.md` closure rule: each slice's ledger entry names the exact test commands re-run and their result.
- Work on a branch off **fresh `main`** (record the seed SHA in the ledger). Never touch `orchestrator.db`, never run git operations outside your worktree/branch.
- Bump `PROJECTION_SCHEMA_VERSION` when reducer semantics or `GraphProjection` shape changes.

## Phase 0 — build the safety net first (one sub-agent)

Before any typing work, dispatch one sub-agent to build a **corpus-replay parity test**: fold recorded event fixtures through the projection path and assert full-replay vs checkpoint/compact-read paths agree. Use existing fixture runs/scenario corpus if present (`graph/scenario.py`, existing FR acceptance fixtures); otherwise generate fixtures by running representative scenarios. This test guards every later slice — do not start slice work until it exists and passes on the current tree.

## Phase 1 — survey (one cheap read-only sub-agent)

Dispatch a read-only survey sub-agent (use a cheaper model; it must not edit) to produce `docs/dynamic-graph/w5-event-payload-inventory.md`:

- Enumerate every event type emitted in `graph/_commands.py` / `graph/compiler.py` (grep `make_event(`) and consumed in `graph/projections.py` `reduce_event`.
- For each event type: the payload keys written by producers, the keys read by reducers/handlers, which keys are scalar vs nested, and which appear in the four store allowlists.
- Group event types into slice-sized families (lease events, node lifecycle, records, patches, decisions, cleanup, planner/session, requirements/evidence, file-state/gatekeeper).
- Flag any key written but never read (candidate for dropping — this is also the DB-bloat trim) and any key read but never written (latent bug — report, don't fix).

The inventory is the single input document for implementation sub-agents. You (orchestrator) read only this inventory and sub-agent reports — never the 5,000-line kernel files yourself.

## Phase 2 — slice loop (one implementation sub-agent per family)

For each family, in dependency-light order (start with a small family like cleanup or leases to validate the pattern, then the big ones: node lifecycle, records):

1. Write a short **slice brief** file (`docs/dynamic-graph/w5-slices/<family>.md`): event types in scope, keys per event from the inventory, files to touch, acceptance criteria. Keep it under a page.
2. Dispatch an implementation sub-agent with ONLY: the slice brief path, the ground rules above, and the house-style pointers (`graph/models.py` for model patterns, `complete/w5-typed-payloads-spec.md` for the historical recipe). Do not paste the review document or prior slice diffs into its prompt.
3. Sub-agent deliverables: payload models in `graph/models.py` (or a new `graph/event_payloads.py` if `models.py` growth becomes unwieldy — decide once, in slice 1, then keep consistent), producers emitting via the model, reducers consuming typed, legacy before-validators, targeted unit tests, and a report of exactly: files changed, test commands run, pass/fail counts.
4. On the sub-agent's report, run verification yourself (or via a small verify sub-agent): the slice's targeted tests, the corpus parity test, the full graph suite (`uv run pytest tests/ -k graph` or the project's established graph-suite invocation), and `ruff check .`. Commit the slice only when all green.
5. Append the ledger entry to `docs/dynamic-graph/w5-progress-ledger.md`: family, commit SHA, tests named + result, keys moved under `extra`, any dropped write-only keys.

If a sub-agent's report claims success but verification fails, do not debug in your own context — send the failure output back to the same sub-agent (or a fresh one with the slice brief + failure) and have it fix.

## Phase 3 — allowlist generation (after enough event families are typed)

Once the families covering the allowlist fields are typed, dispatch a sub-agent to replace the four hand-maintained field tuples with derivation from the payload models (or, minimally, an exhaustive guard test asserting tuple == union of model fields). Acceptance: the existing AST guard test for `GRAPH_PROJECTION_PAYLOAD_FIELDS` still passes or is superseded, and the three unguarded lists gain the same protection. This closes review §4 P0 #2.

## Phase 4 — command payloads, then grades

Same slice recipe: survey already covers command handlers' key usage or dispatch a small follow-up survey; then one sub-agent per command group (lifecycle, callback/patch, scheduling, decisions/records). Typed command models should flow through the API boundary so FastAPI validates requests. Finish with the `GradeRow` slice.

## Cost & context discipline

- You never open `_commands.py`, `projections.py`, or `store.py` yourself. Surveys and slices do; they return summaries.
- Sub-agent prompts are self-contained and small: slice brief + ground rules. No conversation history, no review HTML.
- Use a cheaper model for the Phase 1 survey and for verify-only runs; use a strong model for implementation slices (reducer changes are subtle).
- Run at most 2 implementation sub-agents concurrently, and only on non-overlapping families (they all edit `models.py`/`projections.py` — prefer serial unless the slice briefs prove disjoint edit regions).
- If your own context grows past comfortable size, write current state to the progress ledger and continue from it — the ledger, inventory, and slice briefs are the durable state; your conversation is not.

## Definition of done

- All ~40 event payloads and 23 command payloads parse through typed models with the containment rule applied.
- The four store allowlists are generated or exhaustively guarded.
- Corpus parity test green; full graph suite green; full backend suite green; ruff clean.
- `docs/dynamic-graph/complete/w5-typed-payloads-spec.md` closed, progress ledger complete, and `graph-projection-map-inventory.md` refreshed.
- Report at the end: isinstance-guard count delta in the two kernel files (baseline: 603) and `dict[str, Any]` count delta in `projections.py` (baseline: 174) — the numbers are the review's success metric.
