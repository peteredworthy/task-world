# Runners, Model Routing, Cost Capture, Prompts, Observability — Current System Map

> Provenance: direct code inspection at HEAD `23746c228` (2026-07-07).

## Runner architecture

`AgentRunnerType` (`src/orchestrator/config/enums.py:40`): `OPENHANDS_LOCAL`,
`OPENHANDS_DOCKER`, `CLI_SUBPROCESS` (Claude/Codex CLI), `CODEX_SERVER`,
`CLAUDE_SDK`, plus a `mock`. (`user_managed` survives only as a legacy
normalization case in `db/access/repositories.py:69`.)

`AgentRunner` is a `Protocol` (`runners/interface.py:20`): `execute(context,
on_checklist_update, on_submit, on_output?, on_grade?, on_agent_metadata?,
on_escalation?) -> ExecutionResult`, plus `cancel()`, `info`, `get_quota()`.
Concrete agents self-register into a global registry on import
(`runners/agent_factory.py:41`) — clean, no type-switch.

Execution pipeline: `runners/executor.py` (`AgentRunnerExecutor`) resolves
runner/config/model → `execution/phase_handler.py` dispatches
building/verifying/recovering. Support: `attempt_store.py`,
`event_broadcaster.py`, `output_batcher.py`, carrier-agnostic `usage.py`.
Runtime supervision in `runners/runtime/` (monitor, nudger,
repetition_detector, quota).

### Per-runner status

| Runner | Telemetry | Known issues |
|---|---|---|
| `cli_subprocess` (claude_cli) | Full `ActionLog`: model, cache tokens, sub-agents, rate-limit detection | `CLAUDECODE` env strip workaround |
| `codex_server` | Per-turn `tokenUsage` from NDJSON (`agents/codex/parser.py:123,181`) | Only reliable graph runner (see below) |
| `openhands_*` | `ActionLog` from SDK events, thinner token totals | — |
| `claude_sdk` | **No `ActionLog`** — only flat input/output tokens (`agent.py:689`); no cache, no sub-agent capture → systematically undercounted cost | `request_clarification` is a stub (logs only, `agent.py:225-228`); `get_quota()` always `None`; graph submit broken ("Stream closed" — see memory/incidents); default model `claude-sonnet-4-5` |
| quota (`runtime/quota.py`) | — | Only OpenAI billing implemented; project keys (`sk-proj-*`) 403 → silently `None` |

## Model profile → model resolution

Two-stage:

1. **Agent name** cascade (`profiles/resolution.py:26`): task → step → routine
   → system default ("Builder"/"Verifier").
2. **Model** resolution (`detection/profile_resolution.py:6`): profile →
   `AgentRunnerModelProfileDefault` DB table → `fallback_model` from
   `agent_runner_config["model"]`. Per-run profile overrides are explicitly
   "future — not yet implemented" (`profile_resolution.py:14`).

**The single plug-in point for routing is `executor.py:961-997`** — applied
only when `task_config.profile` is set. Verifier model is separately pinned at
run creation (`Run.verifier_model`, `state/models.py:356`). Any smarter
routing (per-phase, per-work-class, effort levels) attaches at this seam.

## Cost capture

- `model_costs.yaml` (repo root) → `runners/costs.py`: per-1M rates
  (cache_read/cache_creation/input/output), exact-then-prefix matching,
  **zero-cost fallback for unknown models** (`costs.py:73-95`).
- `usage.py:extract_metrics_and_usage` turns `ExecutionResult.action_log`
  into per-model `ModelTokenUsage` (parent + sub-agents summed), recovering
  from per-turn metrics when the aggregate is empty.
- `ModelTokenUsage` **embeds the rate at execution time** so historical costs
  survive price changes (`state/models.py:169`). Persisted per attempt
  (`Attempt.token_usage_by_model`) and aggregated per run.

### Known cost bugs/gaps

1. **$0 in rollups for unmatched models.** The YAML lists few real models
   plus an explicit zero-rate `unknown_model` entry, and `costs.py` documents
   the intent ("frontend shows 'cost unknown'") — so the fallback is
   deliberate at the UI level, but every aggregate (per-run totals, any
   future budget) counts unmatched usage as free with no machine-readable
   flag. Concretely: the claude_sdk default `claude-sonnet-4-5` does not
   exact/prefix-match the YAML key `claude-sonnet-4-6` → the SDK default
   model contributes $0 to totals.
2. **claude_sdk telemetry hole** (above): no cache/sub-agent/dollar figures.
3. No cross-run cost rollup query surface; routing decisions logged only at
   `logger.debug` (`executor.py:993`); no finish_reason or reasoning-token
   capture anywhere.

## Prompt inventory

| Source | Size | Nature |
|---|---|---|
| `workflow/agent/prompts.py` | 455 lines | Hardcoded builder/verifier/recovery system strings (impl + oversight variants); `{{var}}` substitution, requirements, prior verifier feedback, step_context, clarifications |
| `runners/agents/claude_sdk/agent.py::build_claude_sdk_prompt` | ~100 lines | Hardcoded SDK phase section (tool rules, git workflow, graph-node submit) |
| `agent_configs` DB table | 3 seeded rows | Planner/Builder/Verifier system_prompt + default_prompt, editable via API |
| `graph_runtime/prompts.py` | ~1600 lines | Graph-node prompt assembly (see [graph-kernel](graph-kernel.md)) |
| Routine YAML | per-routine | task/step text + `{{var}}` templates |

**Builder/verifier system prompts are triplicated** (hardcoded workflow
strings, hardcoded SDK builder, DB seeds) — the exact drift risk
`docs/token-cost-improvements/04-canonical-tool-guidance.md` warns about.

## Events & observability

- **Event store**: `events_v2` table via `db/access/event_store_v2.py`;
  60+ `WorkflowEvent` subclasses (`workflow/events/types.py`).
- **JSONL journal**: post-commit observer appends every event to
  `.orchestrator/state/history.jsonl` (`db/access/jsonl_outbox.py`).
  Append-only, **no retention/pruning** — unbounded growth (28.8GB incident,
  July 2026, trimmed to 1.77GB; new-event bloat only fully fixed by W5 typed
  payloads).
- **Second durability mechanism**: `state/session.py` `SessionStateManager`
  keeps runs in memory with whole-state JSON snapshots — coexists with, and
  can diverge from, the event store (the "event-driven intent" migration was
  never completed for the legacy carrier; see [design-history](design-history.md)).
- Serving: `EventBroadcaster` persists then best-effort WS-broadcast (errors
  swallowed); activity API `GET /{run_id}/activity`, `/trace`, `/evidence`,
  `/evidence-digest` with payload compaction.

**Operator can answer**: status history, checklist/grade evolution,
per-attempt tokens/cost/duration/actions, raw output, health checks,
clarifications, fan-out lineage.
**Operator cannot answer**: accurate claude_sdk cost; cross-run dollar
rollups; *why* a model was chosen; truncation-caused failures (no
finish_reason); anything requiring distributed tracing.

## token-cost-improvements docs status

All five docs are **proposals, largely unimplemented**: 01 machine ledger,
02 compact child-state handoff, 03 concurrency gating, 04 canonical tool
guidance — no corresponding implementation. 05 model routing is only
partially realized as the static profile-defaults table.

## Solid — do not disturb

- Registry factory pattern (`agent_factory.py`).
- Carrier-agnostic accounting (`execution/usage.py`) — one path shared by
  legacy attempts and graph dispatch.
- Rate-embedding in `ModelTokenUsage`.
- Event store + JSONL outbox as audit substrate.
- Profile resolution as small pure functions with a single chokepoint — the
  right seam for routing work.

See also: [graph-kernel](graph-kernel.md) · [overview](overview.md) ·
[../external/verification-evals-routing.md](../external/verification-evals-routing.md)
