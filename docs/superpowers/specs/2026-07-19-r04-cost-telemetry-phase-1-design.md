# R04 Phase 1 — Cost/Token Telemetry (OTel GenAI Vocabulary Cutover)

**Status:** approved design, ready for implementation
**Date:** 2026-07-19
**Baseline:** `main` at `3cbc824b8` (post-closeout)
**Branch:** `feat/r04-cost-telemetry-phase-1`
**Source directive:** `docs/dynamic-graph/re-evaluation-2026-07-18.md` §2 and
`research/recommendations/04-cost-telemetry-and-budgets.md` phase 1

## Goal

Close every phase-1 gap in `research/recommendations/04-cost-telemetry-and-budgets.md`
against the post-closeout tree at `3cbc824b8`, using OTel GenAI canonical attribute
names as the in-model field names so a future exporter is a pass-through, not a
mapping. The seven gaps from the research doc and re-evaluation §2 all land in
this branch:

1. `tokens_by_node` / `tokens_by_node_kind` populated end-to-end.
2. `finish_reason` captured on the per-call usage record.
3. `reasoning_tokens` separated from output tokens for observability.
4. `latency_ms` captured per agent execution.
5. `rate_missing` flag set when the rate table has no entry for a model.
6. Cross-run cost/token rollup query surface (`GET /api/runs/cost-rollup`).
7. Size-based JSONL journal rotation with bounded `_written` set.

R04 phase 2 (`budgets`, `effort tiers`) is out of scope for this branch.

## Architecture

**Approach C — full OTel GenAI vocab rename.** Canonical attribute names
(`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
`gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_creation.input_tokens`,
`gen_ai.usage.reasoning.output_tokens`, `gen_ai.response.finish_reasons`) become
the Python snake_case field names on every token-usage surface in the codebase.
`ModelTokenUsage` is the single per-call record type; the flat aggregate fields
on `AttemptMetrics` and `RunModel` (`tokens_read`/`tokens_write`/`tokens_cache`/
`total_tokens_*`) are dropped, replaced by sums over `ModelTokenUsage` entries.
A new `NodeUsageRecorded` graph event carries per-node, per-call cost facts;
the run projection folds these into `tokens_by_node` / `tokens_by_node_kind`. A
new query surface aggregates run usage across `day` / `node_kind` / `model` /
`profile` / `run`. The JSONL outbox rotates at a configurable size with a
bounded `_written` set.

**Sequencing rationale.** Enriching the per-call record (renames + new metadata)
lands first because every downstream component reads it. Per-node flow lands
next because it produces the `NodeUsageRecorded` events the rollup queries. The
rollup and rotation land last as independent surfaces reading only stable
contracts.

## Tech Stack

- Python 3.12, Pydantic v2, SQLAlchemy 2.0 (async), Alembic, FastAPI
- Pytest, pytest-asyncio (no mocking — real objects per AGENTS.md)
- OTel GenAI semantic conventions v1.41.0 (attribute names; spec is
  pre-stabilization but attribute names are stable enough per the research doc)

## Global Constraints

These project-wide rules bind every task. Exact values copy verbatim from this
section; do not re-derive them.

**No mocking in tests.** Use real `ModelTokenUsage` instances, real in-memory
SQLite, real `JsonlOutboxObserver` against temp files. No `patch`, no
`MagicMock`, no monkeypatch.

**Import from module top-level only.** The 9 top-level modules are `api`,
`cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, `workflow`. Code
within the same module may use direct sub-module imports to avoid circular
imports. If a symbol needed from another module isn't exported from its
`__init__.py`, add it there — do not bypass the public API.

**Async by default.** No blocking I/O. The `JsonlOutboxObserver` already uses
`asyncio.to_thread` for filesystem operations; rotation logic follows the same
pattern.

**Pydantic for all data.** Every event payload and API schema is Pydantic. New
`NodeUsageRecordedPayload` extends `GraphEventPayloadBase` like all other graph
event payloads.

**Validate all inputs at the API boundary.** The rollup endpoint uses
Pydantic `Literal` for `group_by`, `status`, `runner_type` query params.
422 with a message listing valid options on invalid input. `from`/`to` parsed
via Pydantic `datetime` and validated `from <= to`. Date-time strings use
ISO 8601 with `Z` offset.

**Fresh context per phase.** Builder and verifier never share LLM context —
unaffected by this work, listed here for completeness.

**Pessimistic locking.** Unaffected; the graph controller already locks leases
when emitting events. New `NodeUsageRecorded` events enter the same outbox
path as the existing graph events, inheriting the locking contract.

**Event sourcing for recovery.** `NodeUsageRecorded` is a durable event in
the `events_v2` table via the existing outbox path. The JSONL observer appends
it to the audit mirror like any event. Rotation of the JSONL does NOT affect
`events_v2` durability.

**OTel GenAI attribute names** (snake_case Python form on `ModelTokenUsage`):

| OTel canonical | Python field name |
|---|---|
| `gen_ai.usage.input_tokens` | `gen_ai_usage_input_tokens` |
| `gen_ai.usage.output_tokens` | `gen_ai_usage_output_tokens` |
| `gen_ai.usage.cache_read.input_tokens` | `gen_ai_usage_cache_read_input_tokens` |
| `gen_ai.usage.cache_creation.input_tokens` | `gen_ai_usage_cache_creation_input_tokens` |
| `gen_ai.usage.reasoning.output_tokens` | `gen_ai_usage_reasoning_output_tokens` |
| `gen_ai.response.finish_reasons` (singular on per-call record) | `gen_ai_response_finish_reason` |

**Inclusion rules** (from OTel spec notes [16]–[19]):
- `gen_ai.usage.input_tokens` SHOULD include `cache_read` + `cache_creation`.
- `gen_ai.usage.output_tokens` SHOULD include `reasoning`.
- Cost formula charges `cache_read` once at its own rate, `cache_creation`
  once at its own rate, and `(input_tokens - cache_read - cache_creation)` at
  the input rate. `output_tokens` (which already includes reasoning) is
  charged at the output rate. Reasoning is NOT double-charged; it only has the
  observability subfield.

**Drop fields, do not rename:** `AttemptMetrics.tokens_read`,
`AttemptMetrics.tokens_write`, `AttemptMetrics.tokens_cache`,
`RunModel.total_tokens_read`, `RunModel.total_tokens_write`,
`RunModel.total_tokens_cache`,
`AttemptModel.token_usage_by_model` stays (JSON column, round-trips the renamed
`ModelTokenUsage` transparently),
event/command payload fields `total_tokens_read` / `total_tokens_write` /
`total_tokens_cache` are removed. Aggregate views compute as `sum(over usage
entries)`.

**No OTel exporter in this branch.** The attribute names are canonical; the
emitter is post-phase-1. Do not add `opentelemetry-*` dependencies.

**Journal rotation defaults:**
- `ORCHESTRATOR_EVENT_JOURNAL_MAX_BYTES` env var overrides everything.
- `global_config.py` default: 64 MiB.
- Floor: 1 MiB. Below the floor: log a warning, apply the floor.

**Migration policy:** one Alembic migration drops the three
`RunModel.total_tokens_*` columns. SQLite supports `ALTER TABLE DROP COLUMN`
since 3.35; the project's SQLite is newer. Forward-only data movement is
none (the JSON column has the breakdown). Downgrade recreates the three columns
as `Integer NOT NULL DEFAULT 0` — data Loss is acceptable because the
original columns were sums over the JSON and can be recomputed by a
downgrade-time script if needed; the migration does not backfill.

---

## Section 1 — `ModelTokenUsage` OTel vocab rename

`ModelTokenUsage` (state/models.py:169) becomes the single per-call record with
OTel-canonical field names:

```python
class ModelTokenUsage(BaseModel):
    """Per-call token usage and cost rates for a single model.

    Field names follow OpenTelemetry GenAI semantic conventions so a future
    OTel exporter is a pass-through. Cost-rate fields are project-idiomatic;
    OTel has no attribute for them.
    """

    model: str

    # Token counts (OTel GenAI canonical snake_case)
    gen_ai_usage_input_tokens: int = 0           # includes cache_read + cache_creation
    gen_ai_usage_output_tokens: int = 0          # includes reasoning per OTel note [19]
    gen_ai_usage_cache_read_input_tokens: int = 0
    gen_ai_usage_cache_creation_input_tokens: int = 0
    gen_ai_usage_reasoning_output_tokens: int = 0  # observability subfield; already in output_tokens

    # Cost rates (USD per 1M tokens — project-idiomatic, no OTel attribute)
    cost_per_m_cache_read: float = 0.0
    cost_per_m_cache_creation: float = 0.0
    cost_per_m_input: float = 0.0
    cost_per_m_output: float = 0.0

    # Per-call metadata
    gen_ai_response_finish_reason: str | None = None  # "stop", "length", "tool_calls", "content_filter", "cancelled", "error"
    latency_ms: int = 0                                 # round-trip dispatch -> terminal notification
    rate_missing: bool = False                          # True when get_model_costs() returned _ZERO_COSTS for a non-None model

    @property
    def total_cost_usd(self) -> float:
        billable_input = max(
            0,
            self.gen_ai_usage_input_tokens
            - self.gen_ai_usage_cache_read_input_tokens
            - self.gen_ai_usage_cache_creation_input_tokens,
        )
        return (
            self.gen_ai_usage_cache_read_input_tokens * self.cost_per_m_cache_read
            + self.gen_ai_usage_cache_creation_input_tokens * self.cost_per_m_cache_creation
            + billable_input * self.cost_per_m_input
            + self.gen_ai_usage_output_tokens * self.cost_per_m_output
        ) / 1_000_000
```

**`rate_missing` resolution** — set in `extract_metrics_and_usage` (runners execution) after `get_model_costs(model_name)` returns the zero-rate fallback for a non-None `model_name`. The flag is the machine-readable R01(b) signal: rollups filter / expose "cost unknown" instead of silently reporting $0.

**`finish_reason` mapping** (per runner):

| Runner | Source | Mapping |
|---|---|---|
| `codex_server` | `turn.status` from `turn/completed` notification | `"completed"` → `"stop"`, `"interrupted"` → `"cancelled"`, `"systemError"` → `"error"`, `"failed"` → `"error"` |
| `claude_cli` | Anthropic stop reason from ActionLog | pass-through (`"end_turn"`, `"max_tokens"`, `"tool_use"`, etc.) |
| `openhands_*` | SDK exposure unstable | `None` (graceful degradation) |
| mock | test fixture | pass-through |

**`latency_ms` measurement** — `perf_counter()` around `runner.execute(...)` in:

- `GraphDispatchExecutor._run_agent` (graph_runtime/dispatch.py:263) — wraps the production graph dispatch path.
- `AgentRunnerExecutor` (runners/executor.py) — wraps the legacy attempt path.

Same value reported on every `ModelTokenUsage` entry produced by a given
execution (parent + sub-agents), so per-model rollups don't lose latency. Field
comment documents the replication.

**Sites touched (rename + drop):**
- `state/models.py` — `ModelTokenUsage` field rename + `total_cost_usd` formula update; `AttemptMetrics` loses the three token fields; `Attempt`, `TaskState`, `RunResponse` any per-token accessors refactored to `sum(over ModelTokenUsage)`.
- `db/orm/models.py` — `RunModel.total_tokens_*` columns dropped via migration; `RunModel.token_usage_by_model`, `AttemptModel.token_usage_by_model` JSON columns untouched.
- `db/projections/run_state.py` — SQL UPDATE fragments lose the three column writes; per-event-merge of `token_usage_by_model` JSON stays.
- `db/projections/task_state.py:489-490` — `event.token_usage_by_model` field rename is implicit (it's a JSON-deserialized `ModelTokenUsage` list).
- `db/access/mutations.py:48-103` — `merge_token_usage_into_run` signature drops `tokens_read`/`tokens_write`/`tokens_cache` kwargs; only `token_usage_by_model` remains.
- `runners/execution/usage.py` — `extract_metrics_and_usage` constructs renamed `ModelTokenUsage` from `ActionLog`; sets `rate_missing` after `get_model_costs` resolves.
- `runners/execution/attempt_store.py:416-468` — `_dump_token_usage`, `_build_run_metrics` use renamed fields; removed tokens_read/write/cache code paths.
- `runners/execution/phase_handler.py` — `token_usage_by_model` plumbing untouched at the field level (it's a list of `ModelTokenUsage`).
- `workflow/events/types.py:394-399, 595` — `total_tokens_read`/`total_tokens_write`/`total_tokens_cache` removed from `AttemptCompleted` and `RunCompleted` (or whichever events carry them).
- `workflow/commands/run_lifecycle.py:141-146, 212, 346, 437-439, 499-501, 560-565, 641-668` — command and event plumbing drops the three fields.
- `api/presenters/runs.py:35-300` — `token_usage_to_schema`, `summarize_attempt_usage` etc. updated; `ModelTokenUsageSchema` field names renamed OTel.
- `api/routers/runs.py:333, 390-395` — API response schema uses OTel field names.
- `api/presenters/evidence_digest.py:280-286` — drop `total_tokens_*` references.
- `cli/runs.py:601-607` — label "Tokens used" stays (user-facing copy); source values re-derived via `sum(over ModelTokenUsage)`.
- `scripts/compare_carriers.py` — metric keys renamed OTel.
- UI `ui/src/types/runs.ts` — TS field names updated to match the new API schema. UI label copy unchanged.
- Tests: `tests/unit/test_model_token_usage.py`, `test_model_costs.py`, `test_cost_records.py`, `test_api_runs.py:1366+`, every test that constructs a `ModelTokenUsage` with `input_tokens=`/`output_tokens=`/etc. updated to OTel names.

**Codex parser** (`runners/agents/codex/common.py:781, 846`): the existing
`result["tokens_reasoning"]` extraction stays, but the dict returned shifts to
OTel keys (`gen_ai_usage_input_tokens` etc.). Reasoning still folded into
`gen_ai_usage_output_tokens` per OTel note [19]; the separate
`tokens_reasoning` field in the parser dict becomes
`gen_ai_usage_reasoning_output_tokens` for the per-call record's observability
subfield, AND is added to `gen_ai_usage_output_tokens`.

---

## Section 2 — Per-node token flow (`NodeUsageRecorded`)

New graph event records per-call cost facts. The run projection folds them into
the existing `NodeStateChangedPayload.tokens_by_node` /
`NodeStateChangedPayload.tokens_by_node_kind` accumulators (graph/models.py:1165).

**Payload model (new file or in `graph/events/usage.py` if pattern matches):**

```python
class NodeUsageRecordedPayload(GraphEventPayloadBase):
    """Per-call cost record for one agent dispatch on one node.

    Emitted once per `ModelTokenUsage` entry produced by a dispatched agent
    execution (parent + sub-agents). The run projection folds these into
    `tokens_by_node` and `tokens_by_node_kind` aggregations on
    `NodeStateChangedPayload`.
    """

    node_id: str
    node_kind: str
    node_role: str | None = None

    # Per-model facts (copied from one ModelTokenUsage entry)
    model: str | None = None
    gen_ai_usage_input_tokens: int = 0
    gen_ai_usage_output_tokens: int = 0
    gen_ai_usage_cache_read_input_tokens: int = 0
    gen_ai_usage_cache_creation_input_tokens: int = 0
    gen_ai_usage_reasoning_output_tokens: int = 0
    cost_usd: float = 0.0
    gen_ai_response_finish_reason: str | None = None
    latency_ms: int = 0
    rate_missing: bool = False
```

**Event type string:** `node_usage_recorded`.

**Emission point**: extend `on_agent_usage` in `api/deps.py:411`. After the
existing `merge_token_usage_into_run` block, call a new controller method
`GraphController.record_node_usage(context, usage_by_model, finish_reason,
latency_ms)`. The controller emits one `NodeUsageRecorded` event per
`ModelTokenUsage` entry in `usage_by_model`. `latency_ms` is one value for the
whole execution; replicated across the per-model events from that execution.
Each event's `rate_missing` field copies the corresponding
`ModelTokenUsage.rate_missing` (per-model, set in section 1 via
`extract_metrics_and_usage`). An event for a model that resolved cleanly
carries `rate_missing=False`; an event for a model that hit `_ZERO_COSTS`
carries `rate_missing=True`. No propagation across models within the same
execution.

**Why a new event, not piggybacking on `node_state_changed`**: state-transition
events fire on kernel state moves, which can happen 0 times (node abandoned) or
N times (multiple submits) per dispatched agent. Usage happens exactly once per
dispatched agent that reaches a terminal notification. Coupling them forces
either double-counting or state-machine knowledge in the accounting path. The
dedicated event owns its semantics.

**Why keep the fields on `NodeStateChangedPayload`**: the run projection's
`tokens_by_node` / `tokens_by_node_kind` accumulators are a derived read model
populated by folding `NodeUsageRecorded` events during projection. The fields
stay on the payload for readback contract stability; they're populated by the
projection fold, not by the command that emits the state change.

**Projection fold** (`graph/projections.py`):

Add a fold over `NodeUsageRecorded` events into a per-projection
`tokens_by_node: dict[str, int]` and `tokens_by_node_kind: dict[str, int]`.
The sum is over `(gen_ai_usage_input_tokens + gen_ai_usage_output_tokens)` per
event (those fields already include cache and reasoning per OTel notes; no
double-count). When a `node_state_changed` event fires, copy the projection's
`tokens_by_node` and `tokens_by_node_kind` into the emitted payload's
corresponding fields — the readback contract is preserved.

**Projection-internal latency aggregate** (not on the public payload): the
projection also tracks `latency_ms_sum: dict[str, int]` keyed by `node_kind`
for the rollup endpoint in section 3. Internal-only field.

**Codex-specifically**: codex already extracts per-turn usage via
`extract_token_usage_update` (codex/common.py:688). After section 1, the
returned dict has OTel-named keys. `extract_metrics_and_usage` re-pivots into
`ModelTokenUsage` entries. The new event emission works through the same seam
the existing aggregate persistence uses; no codex-specific changes beyond
section 1's rename.

**Tests:**
- Scenario harness: two `NodeUsageRecorded` events for `n1` (kind `worker`):
  - `m1`: input=100, output=50, cache_read=0, cache_creation=0, reasoning=0
  - `m2`: input=200, output=20
  - one event for `n2` (kind `verifier`): input=500, output=10
  Folded projection asserts:
  - `tokens_by_node == {"n1": 370, "n2": 510}`
  - `tokens_by_node_kind == {"worker": 370, "verifier": 510}`
- No `NodeUsageRecorded` for a state-transitioning node leaves the projection's
  `tokens_by_node[n]` equal to its prior value (no spurious empty entry).
- `NodeStateChangedPayload.tokens_by_node` / `tokens_by_node_kind` populated
  from the projection fold (readback contract).
- Projection-internal `latency_ms_sum` incremented per `NodeUsageRecorded`
  event.
- One event per `ModelTokenUsage` entry (parent + sub-agents each produce a
  separate event with the right `model`).
- `rate_missing` per event: an event for a model with `rate_missing=True` on
  its `ModelTokenUsage` carries `rate_missing=True`; an event for a model with
  `rate_missing=False` carries `False`. No propagation across models within
  the same execution.

---

## Section 3 — Cross-run cost rollup `GET /api/runs/cost-rollup`

A new query surface over `RunModel.token_usage_by_model` JSON and
`NodeUsageRecorded` events.

**Route:**

```
GET /api/runs/cost-rollup
    ?from=2026-07-01T00:00:00Z       (ISO 8601, optional; defaults to start-of-time)
    &to=2026-07-31T23:59:59Z         (ISO 8601, optional; defaults to now)
    &group_by=model|node_kind|profile|day|run   (repeatable; default: ["run"])
    ?status=completed|active|failed   (repeatable; default: all)
    ?runner_type=codex_server|cli_subprocess|openhands_local|openhands_docker  (repeatable; default: all selectable)
```

**Response (200):**

```json
{
  "from": "2026-07-01T00:00:00Z",
  "to": "2026-07-31T23:59:59Z",
  "group_by": ["day", "node_kind"],
  "rows": [
    {
      "group_keys": {"day": "2026-07-15", "node_kind": "worker"},
      "gen_ai_usage_input_tokens": 1234567,
      "gen_ai_usage_output_tokens": 234567,
      "gen_ai_usage_cache_read_input_tokens": 100000,
      "gen_ai_usage_cache_creation_input_tokens": 50000,
      "gen_ai_usage_reasoning_output_tokens": 120000,
      "cost_usd": 12.34,
      "rate_missing_cost_usd": 0.0,
      "latency_ms_sum": 145000,
      "execution_count": 42,
      "model_breakdown": [
        {
          "model": "gpt-4o",
          "gen_ai_usage_input_tokens": 600000,
          "gen_ai_usage_output_tokens": 100000,
          "cost_usd": 6.10,
          "rate_missing": false
        }
      ]
    }
  ]
}
```

**Files (new):**
- `src/orchestrator/api/routers/cost_rollup.py` — FastAPI router; Pydantic query-param model with `Literal` for `group_by`, `status`, `runner_type`; datetime parsing for `from`/`to`; calls the presenter.
- `src/orchestrator/api/presenters/cost_rollup.py` — pure function
  `compute_cost_rollup(session, *, group_by, from_dt, to_dt, statuses,
  runner_types) -> dict`. One SQLAlchemy query loads matching `RunModel` rows
  in the window with `status in (...)` and `agent_runner_type in (...)`. For
  each row, deserialize `token_usage_by_model` into `list[ModelTokenUsage]`.
  Group in Python by the requested dimensions, summing OTel fields. For
  `group_by=node_kind`, join with a subquery over `events_v2` filtering on
  event_type=`node_usage_recorded`, grouped by `payload->>'node_kind'`. For
  `group_by=profile`, resolve each run's effective profile via a single lookup
  joining `AttemptModel.verifier_model` and the routine profile-defaults table
  (best-effort; `"unknown"` if no attempts exist for the run).
- `src/orchestrator/api/schemas/cost_rollup.py` — response Pydantic schema.

**Validation:**
- Query params validated via Pydantic `Literal` so invalid `group_by` returns
  422 with the valid options listed (AGENTS.md boundary rule).
- `from > to` if both provided → 422.
- `runner_type` accepts only the four selectable runner names
  (`openhands_local`, `openhands_docker`, `cli_subprocess`, `codex_server`);
  `retired` and `claude_sdk` rejected as invalid.
- Capped result set: if grouped cardinality > 1000 rows, return 400 with a
  hint to narrow `group_by`.

**Auth:** same surface as `GET /api/runs`; operator surface only.

**Migration:** the Alembic migration dropping `RunModel.total_tokens_*`
columns is the only migration required by this section. The rollup reads
`RunModel.token_usage_by_model` JSON; no new columns or tables.

**Tests:**
- Pure-function unit tests (no DB): fixture list of `RunModel` with mixed
  `token_usage_by_model`, assert the rollup groups correctly across each
  `group_by` dimension, model_breakdown maps, rate_missing_cost_usd sums
  correctly.
- Integration tests against an in-memory SQLite with real `RunModel` rows:
  empty rollup, single-dimension rollup, multi-dimension rollup.
- 422 cases: invalid `group_by`, `from > to`, unknown `runner_type`.
- Cap returns 400 when grouped cardinality > 1000.
- One test asserting the rollup resolves correctly from
  `token_usage_by_model` JSON alone after the flat columns are dropped.

---

## Section 4 — JSONL journal rotation

Size-based rotation in `JsonlOutboxObserver` (db/access/jsonl_outbox.py).

**Config:**

```python
# config/global_config.py (extend the journal section)
journal_max_bytes: int = 64 * 1024 * 1024  # 64 MiB default; floor 1 MiB
# Env override: ORCHESTRATOR_EVENT_JOURNAL_MAX_BYTES
```

**Rotation trigger** in `JsonlOutboxObserver.__call__` after `_append_lines`:
1. Check `self._path.stat().st_size`. If `> journal_max_bytes`:
2. Compute `archive_ts = int(time.time() * 1000)` for lexical ordering.
3. Rename `self._path` → `self._path.with_name(f"history.{archive_ts}.jsonl")`.
4. Recreate empty `self._path` (next `__call__` opens with `a`).
5. Reset `self._written` to `{}` — re-read the now-empty active file's
   positions (always empty after rotation; this is a no-op read).

**Atomicity:** rename + recreate runs under `self._lock` (already held during
`__call__`). No new concurrency hazard.

**Crash window:** if the process dies between the rename and the recreate, the
next `__call__` re-reads the (missing) active file's positions (zero), opens it
with `a` (creating an empty file), and continues. No data loss: the rename made
the prior content durable in the archive; the new active file starts empty. No
duplicate write because of the position-skip idempotency check.

**Recovery contract:** `db/bootstrap.py` reads `history.jsonl` on first startup
when `events_v2` is empty. Archives are NOT replayed. Documented explicitly in
`JsonlOutboxObserver`'s class docstring (the rotation logic lives in
`db/access/jsonl_outbox.py`, not a separate module): "the JSONL is an audit
mirror; `events_v2` is the durable store; rotation moves archives out of the
recovery path."

**Retention sweep** (delete archive files older than N days): out of phase-1
scope. Bounded storage is achieved by rotation alone (~2× max_bytes: one
active + one just-rotated archive before the next rotation). Explicit deferral
noted here.

**Sizing evidence:** 64 MiB default chosen against the 28.8 GB incident
(~450× oversized). Roughly one rotation per long session. Configurable down to
1 MiB floor for high-cardinality test environments without unbounded
`_written` re-reads (re-read is on the empty active file post-rotation).

**Tests:**
- Unit test against a temp file: drive observer with `journal_max_bytes=128`,
  append events until rotation fires. Assert:
  1. Active file is empty.
  2. Exactly one archive file `history.<ts>.jsonl` exists with the appended
     events.
  3. `observer._written` is empty (`set()`) post-rotation.
  4. Subsequent append goes to the new active file, not the archive.
- Crash window: rename fails (simulated by a non-writable parent) → next
  `__call__` recovers cleanly with no exception surfaced to the caller and
  no data loss.
- Floor enforcement: `journal_max_bytes=1024` (< 1 MiB) → startup applies
  floor and logs warning; `journal_max_bytes=0` same; `journal_max_bytes=-1`
  same (use `abs()` then floor at 1 MiB).
- Integration test: bootstrap with empty `events_v2` and a rotated archive
  present → bootstrap reads ONLY the active file, NOT the archive. Pins the
  recovery contract.
- Idempotency preserved: same position written twice = one line in active file.

---

## Validation plan

**Repo evidence of done (per research doc R04 phase 1):**
- `grep -rn tokens_by_node src/orchestrator` shows the field populated by the
  `NodeUsageRecorded` fold in `projections.py`, not just declared as
  scaffolding.
- `grep -rn rate_missing src/orchestrator` shows the flag set in
  `extract_metrics_and_usage` and emitted on `NodeUsageRecordedPayload`.
- `grep -rn finish_reason src/orchestrator` shows capture on
  `ModelTokenUsage` and the codex parser.
- `grep -rn gen_ai_usage_reasoning_output_tokens src/orchestrator` shows the
  field separated from `gen_ai_usage_output_tokens` and populated by the codex
  parser.
- `curl -s 'http://localhost:8000/api/runs/cost-rollup?group_by=day'` returns
  a 200 with valid aggregated rows.
- `ls .orchestrator/state/history.*.jsonl` shows archive files after a
  session large enough to rotate.
- `RunModel.total_tokens_*` columns gone from `db/orm/models.py`.

**Test evidence of done:**
- Phase-1 tests pass with no mocking per AGENTS.md.
- The seven renames propagated through every site listed in section 1.
- `test_model_token_usage.py` covers `rate_missing=True` for unmatched models,
  `rate_missing=False` for matches, `finish_reason` round-trip through
  `model_dump` / `model_validate`, `reasoning_output_tokens` stays distinct
  from `output_tokens` through the merge path.
- `test_cost.py` and `test_model_costs.py` updated: `cost_per_m_input` charges
  `(input_tokens - cache_read - cache_creation)`, not the full
  `input_tokens`.
- A new test asserts that codex parser's `gen_ai_usage_output_tokens` equals
  `output + reasoning` (OTel inclusion rule note [19]).
- `pyright` and `ruff` clean.
- All pre-existing tests that depend on the renamed fields updated; no test
  silently breaks.

---

## Risks

- **Migration rollback loses aggregate columns.** Downgrade recreates the
  three columns as `Integer NOT NULL DEFAULT 0`. Aggregate values from before
  the downgrade can be recomputed from the JSON column, but the migration
  does NOT backfill. Acceptable because the columns were redundant. Document
  this in the migration's `downgrade()` docstring.
- **Renaming via JSON columns.** Pydantic `model_dump(mode="json")` includes
  the new field names once added; old rows missing the keys deserialize via
  the zero/None defaults. Existing `token_usage_by_model` JSON rows in the
  production DB carry the old field names and will deserialize with zero /
  None defaults for the new keys, dropping their values. **This is a data
  loss for existing runs' cost telemetry.** Acceptable because:
  - No production graph runs exist yet (per the W5 closeout record).
  - Pre-closeout cost data was already known-broken (rate_missing gap).
  - The R04 phase 1 work's whole point is to start fresh with accurate
    accounting.
  - If preservation is required, a one-time backfill migration can map old
    keys to new; deferred unless explicitly requested.
- **OTel attribute names change post-stabilization.** The research doc
  addresses this: attribute names are stable enough to bet on even though the
  spec is pre-stabilization. If a name changes later, the rename is a
  mechanical codemod over a single Pydantic model.
- **`tokens_by_node` cardinality.** A run with thousands of nodes produces a
  `tokens_by_node` dict with thousands of entries on every node state change.
  The projection fold produces this incrementally (per-event), but the
  `NodeStateChangedPayload` carries a snapshot of the full accumulation. For
  large runs, this could bloat the JSON payload. Mitigation: cap the projection
  "top N" entries, or move the full dict to a separate read endpoint. Out of
  phase-1 scope; flagged here for the next iteration.
- **`worktree_retention_days` analogue.** The journal retention sweep is
  deferred; archive files accumulate indefinitely. Bounded by ~2×
  `journal_max_bytes` per rotation cycle. For long-lived operators, an
  archival policy is needed; deferred per evaluation §8.

---

## Dependencies

- R01(b) partial overlap: `rate_missing` is R01's "machine-visible unmatched
  model" deliverable. R01(b) also requires YAML reconciliation with every
  runner default model string. The YAML reconciliation test (every runner
  default → nonzero rate) is included here as part of phase 1 completeness;
  the rate-missing flag is the larger structural change and lands here too.
- W5 typed-payload slices: complete. The W5 strict-cutover work established
  the AST architecture guard and payload registry; the new
  `NodeUsageRecorded` event must register in the same way (covered in
  section 2 implementation).
- No external dependencies added. OTel Python SDK / OpenTelemetry exporter
  is post-phase-1.

---

## Out of scope

- R04 phase 2: budget enforcement, effort tiers (`research/recommendations/04-cost-telemetry-and-budgets.md` steps 5–6).
- R02 (execution-first verification), R03 (revision/escalation policy), R07 (eval harness) — these consume the telemetry this branch produces; they are downstream.
- OTel exporter / OpenTelemetry SDK integration.
- JSONL archive retention sweep (delete archives older than N days).
- UI changes beyond the renamed `runs.ts` types (no new operator surface for the rollup endpoint in this branch).
- Backfill of existing run cost telemetry (acceptable data loss per Risks).
