# Codebase Discovery: Per-Model Token Accounting

*Generated for the per-model-yaml feature implementation.*

---

## Source File Signatures

### `src/orchestrator/state/models.py`

**Status of touched symbols: ALL ALREADY EXIST**

```python
class ModelTokenUsage(BaseModel):
    model: str
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_per_m_cache_read: float = 0.0
    cost_per_m_cache_creation: float = 0.0
    cost_per_m_input: float = 0.0
    cost_per_m_output: float = 0.0

    @property
    def total_cost_usd(self) -> float: ...
    # Returns (cache_read * rate + cache_creation * rate + input * rate + output * rate) / 1_000_000
```

```python
class Attempt(BaseModel):
    id: str                                          # Field(default_factory=generate_id)
    attempt_num: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    paused_at: datetime | None = None
    builder_prompt: str | None = None
    verifier_prompt: str | None = None
    verifier_comment: str | None = None
    outcome: str | None = None
    metrics: AttemptMetrics = Field(default_factory=AttemptMetrics)
    grade_snapshot: list[GradeSnapshotItem] = Field(default_factory=lambda: [])
    auto_verify_results: list[dict[str, Any]] = Field(default_factory=lambda: [])
    agent_type: AgentRunnerType | None = None
    agent_model: str | None = None
    agent_settings: dict[str, Any] = Field(default_factory=dict)
    agent_output: str | None = None
    error: str | None = None
    token_usage_by_model: list[ModelTokenUsage] = Field(default_factory=lambda: [])  # ← NEW
    action_log: ActionLog | None = None
    start_commit: str | None = None
    end_commit: str | None = None
```

```python
class Run(BaseModel):
    # ... (many fields) ...
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_tokens_cache: int = 0
    total_duration_ms: int = 0
    total_num_actions: int = 0
    token_usage_by_model: list[ModelTokenUsage] = Field(default_factory=lambda: [])  # ← NEW
```

```python
class ActionLog(BaseModel):
    entries: list[ActionLogEntry] = []
    session_id: str | None = None
    agent_model: str | None = None
    tools_available: list[str] = []
    total_turns: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    sub_agents: list[SubAgentLog] = []
    # ... sub_agent aggregate totals ...
    rate_limit_hit: bool = False
    rate_limit_resets_at: datetime | None = None
```

```python
class SubAgentLog(BaseModel):
    agent_id: str = ""
    agent_type: str = ""
    description: str = ""
    model: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    entries: list[ActionLogEntry] = []
```

---

### `src/orchestrator/runners/costs.py`

**Status: ALREADY EXISTS AND COMPLETE**

```python
_cost_table: dict[str, dict[str, float]] = {}   # module-level, mutable
_ZERO_COSTS: dict[str, float]                    # keys: cost_per_m_{cache_read,cache_creation,input,output}

def _find_cost_file() -> Path | None:
    # Walks up from __file__ 3 levels to find model_costs.yaml; falls back to CWD

def load_cost_table(path: Path | None = None) -> None:
    # Loads (or reloads) YAML from path. Populates _cost_table.
    # YAML format: {"models": {"<name>": {"cache_read": float, "cache_creation": float, "input": float, "output": float}}}
    # Called automatically on first access by get_model_costs.

def get_model_costs(model_name: str | None) -> dict[str, float]:
    # Returns cost-rate kwargs dict with keys: cost_per_m_{cache_read,cache_creation,input,output}
    # Tries exact match, then prefix match (both directions), then returns _ZERO_COSTS copy.
    # Never raises; returns zero dict for unknown/None models.
```

**Cost file location (current):** `model_costs.yaml` at project root (4 levels up from `runners/`). The step plans say `config/model_costs.yaml` but the actual file is at project root. The `_find_cost_file()` looks 3 levels up from `runners/` which resolves to project root (`task-world/`).

---

### `src/orchestrator/runners/execution/phase_handler.py`

**Status: ALREADY EXISTS AND COMPLETE**

```python
class PhaseHandler:
    def __init__(
        self,
        attempt_store: AttemptStore,
        event_broadcaster: EventBroadcaster,
        api_base_url: str = "http://localhost:8000",
    ) -> None: ...

    @staticmethod
    def _extract_metrics_and_usage(
        result: Any,   # ExecutionResult
    ) -> tuple[ExecutionMetrics, list[ModelTokenUsage]]:
        # Builds ModelTokenUsage for parent model + groups sub-agents by model name.
        # Falls back to result.metrics if action_log is None.
        # Builds legacy flat metrics as sum across all per-model entries.

    async def execute_phase(
        self,
        *,
        phase: str,           # "building" | "verifying" | "recovering"
        run: Run,
        task_state: TaskState,
        service: WorkflowService | None,
        agent: AgentRunner,
        context: ExecutionContext,
        req_desc_to_id: dict[str, str],
        agent_type_value: str = "",
        session: Any = None,
    ) -> None: ...
    # Dispatches to _execute_building / _execute_verifying / _execute_recovering

    async def _execute_building(self, run, task_state, service, agent, context,
                                req_desc_to_id, *, agent_type_value="", session=None) -> None: ...
    async def _execute_verifying(self, run, task_state, service, agent, context,
                                 req_desc_to_id) -> None: ...
    async def _execute_recovering(self, run, task_state, service, agent, context) -> None: ...
```

**Token extraction flow (already wired):**
1. `_extract_metrics_and_usage(result)` reads `result.action_log` (an `ActionLog`)
2. Creates parent `ModelTokenUsage` from `al.agent_model` + `al.total_*_tokens`
3. Iterates `al.sub_agents`, groups by model, sums tokens per group
4. Legacy flat metrics = sum across all models
5. Result passed to `attempt_store.store_attempt_metrics(..., token_usage_by_model=...)`

---

### `src/orchestrator/runners/execution/attempt_store.py`

**Status: ALREADY EXISTS AND COMPLETE**

```python
class AttemptStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None: ...

    async def store_attempt_output(
        self,
        run_id: str,
        task_id: str,
        output_lines: list[str],
        error: str | None = None,
        action_log: Any = None,
    ) -> None: ...

    async def store_attempt_prompt(
        self,
        run_id: str,
        task_id: str,
        builder_prompt: str | None = None,
        verifier_prompt: str | None = None,
        session: AsyncSession | None = None,
    ) -> None: ...

    async def store_attempt_metrics(
        self,
        run_id: str,
        task_id: str,
        metrics: ExecutionMetrics,
        *,
        token_usage_by_model: list[ModelTokenUsage] | None = None,
    ) -> None: ...
    # Delegates to repo.update_latest_attempt(task_id, metrics=metrics, token_usage_by_model=...)

    async def persist_agent_metadata(
        self,
        run_id: str,
        agent_metadata: dict[str, Any],
    ) -> None: ...

    @staticmethod
    def _merge_action_logs(first: ActionLog, second: ActionLog) -> ActionLog: ...
```

---

### `src/orchestrator/db/orm/models.py`

**Status: ALREADY INCLUDES `token_usage_by_model` COLUMNS**

`AttemptModel` columns relevant to this feature:
```
token_usage_by_model: JSON | None  (nullable=True, default=None)
```

`RunModel` columns relevant to this feature:
```
token_usage_by_model: JSON | None  (nullable=True, default=None)
```

Full `RunModel` flat-metrics columns:
```
total_tokens_read: Integer, default=0
total_tokens_write: Integer, default=0
total_tokens_cache: Integer, default=0
total_duration_ms: Integer, default=0
total_num_actions: Integer, default=0
```

Full `AttemptModel` flat-metrics columns:
```
tokens_read: Integer, default=0
tokens_write: Integer, default=0
tokens_cache: Integer, default=0
duration_ms: Integer, default=0
num_actions: Integer, default=0
```

---

### `src/orchestrator/db/access/repositories.py`

**Status: SERIALIZATION/DESERIALIZATION ALREADY IMPLEMENTED**

Key function signatures:

```python
def _to_domain(model: RunModel, *, action_logs_loaded: bool = True) -> Run:
    # Deserializes token_usage_by_model from JSON list of dicts → list[ModelTokenUsage]
    # Gracefully handles corrupt/invalid items (try/except per item)

def _to_model(run: Run) -> RunModel:
    # Serializes token_usage_by_model: list[ModelTokenUsage] → JSON list of dicts via model_dump(mode="json")
    # Returns None (not []) when list is empty
```

Key method in `RunRepository`:
```python
async def update_latest_attempt(
    self,
    task_id: str,
    builder_prompt: Any = _UNSET,
    verifier_prompt: Any = _UNSET,
    output_lines: list[str] | None = None,
    error: Any = _UNSET,
    action_log: Any = _UNSET,
    metrics: Any = _UNSET,
    token_usage_by_model: list[ModelTokenUsage] | None = None,
    outcome: Any = _UNSET,
    completed_at: Any = _UNSET,
    auto_verify_results: Any = _UNSET,
    status: TaskStatus | None = None,
) -> None:
    # When token_usage_by_model is provided:
    #   1. Accumulates into attempt.token_usage_by_model (merge by model name, sum tokens)
    #   2. Accumulates into run.token_usage_by_model (merge by model name, sum tokens)
    # Both builder and verifier contribute to the same attempt entry.
```

---

### `src/orchestrator/api/schemas/tasks.py`

**Status: SCHEMA ALREADY EXISTS**

```python
class ModelTokenUsageSchema(ApiModel):
    model: str
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_per_m_cache_read: float = 0.0
    cost_per_m_cache_creation: float = 0.0
    cost_per_m_input: float = 0.0
    cost_per_m_output: float = 0.0
    total_cost_usd: float = 0.0  # ← stored field (NOT a computed property; must be set explicitly)

class AttemptSchema(ApiModel):
    id: str
    attempt_num: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    builder_prompt: str | None = None
    verifier_prompt: str | None = None
    verifier_comment: str | None = None
    outcome: str | None = None
    metrics: dict[str, Any] = {}
    grade_snapshot: list[GradeSnapshotItemSchema] = []
    auto_verify_results: list[dict[str, Any]] = []
    token_usage_by_model: list[ModelTokenUsageSchema] = []  # ← ALREADY PRESENT
    agent_type: str | None = None
    agent_model: str | None = None
    agent_settings: dict[str, Any] = {}
    error: str | None = None
    has_output: bool = False
    has_action_log: bool = False
    start_commit: str | None = None
    end_commit: str | None = None
```

**NOTE:** `ModelTokenUsageSchema.total_cost_usd` is a plain field (not a `@property`), unlike the domain `ModelTokenUsage` class which has a computed property. The router must compute and pass this value explicitly.

---

### `src/orchestrator/api/schemas/runs.py`

**Status: SCHEMA ALREADY EXISTS**

```python
class RunResponse(ApiModel):
    # ... (many fields) ...
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_tokens_cache: int = 0
    total_duration_ms: int = 0
    total_num_actions: int = 0
    token_usage_by_model: list[ModelTokenUsageSchema] = []  # ← ALREADY PRESENT
    estimated_cost_usd: float | None = None
    cost_disclaimer: str | None = None
```

```python
def get_agent_display_name(agent_type: AgentRunnerType | None, agent_config: dict[str, Any] | None = None) -> str: ...
def get_agent_icon(agent_type: AgentRunnerType | None) -> str: ...
```

---

### `src/orchestrator/api/routers/runs.py`

**Key function already implemented:**

```python
def _run_to_response(run: Run) -> RunResponse:
    # Already builds token_usage_schemas from run.token_usage_by_model.
    # Computes estimated_cost_usd via three-tier fallback:
    #   1. If token_usage_by_model present → sum(u.total_cost_usd for u in schemas)
    #   2. Else if action_log has cost → action_log.total_cost_usd
    #   3. Else flat estimate via estimate_cost() with gpt-4o default
    # Sets cost_disclaimer string accordingly.
```

---

### `src/orchestrator/runners/types.py`

```python
class ExecutionMetrics(BaseModel):
    tokens_read: int = 0
    tokens_write: int = 0
    tokens_cache: int = 0
    duration_ms: int = 0
    num_actions: int = 0

class ExecutionResult(BaseModel):
    success: bool
    error: str | None = None
    metrics: ExecutionMetrics = ExecutionMetrics()
    agent_metadata: dict[str, Any] = {}
    output_lines: list[str] = []
    action_log: Any = None   # ActionLog | None
```

---

### `ui/src/types/runs.ts`

**Status: TYPES ALREADY DEFINED**

```typescript
export interface ModelTokenUsage {
  model: string;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost_per_m_cache_read: number;
  cost_per_m_cache_creation: number;
  cost_per_m_input: number;
  cost_per_m_output: number;
  total_cost_usd: number;
}

export interface RunResponse {
  // ... (many fields) ...
  token_usage_by_model: ModelTokenUsage[];   // ← ALREADY PRESENT
  estimated_cost_usd: number | null;
  cost_disclaimer: string | null;
}
```

---

### `ui/src/components/detail/MetricsBar.tsx`

**Status: EXISTS; does NOT yet use `token_usage_by_model` for rendering**

```typescript
function estimateCost(tokensRead: number, tokensWrite: number): string
// Rough estimate: $3/1M input, $15/1M output — used as fallback

export function MetricsBar({ run }: MetricsBarProps): JSX.Element
// Props: { run: RunResponse }
// Currently renders 3 cards: Tokens, Duration, Est. Cost
// Uses run.estimated_cost_usd if not null, else calls estimateCost()
// Uses run.cost_disclaimer to decide label ("Cost" vs "Est. Cost")
// Does NOT yet render per-model cost breakdown table
```

---

## Test Coverage Map

### `src/orchestrator/runners/costs.py`
- **Test file:** `tests/unit/test_model_costs.py`
- **Fixtures:** `_reset_cost_table` (autouse, resets `costs_mod._cost_table = {}` before/after each test)
- **Pattern:** Direct import of module internals (`costs_mod._cost_table`); loads YAML from `tmp_path`
- **Mocking:** None — tests use real YAML files in `tmp_path`

### `src/orchestrator/state/models.py` (ModelTokenUsage)
- **Test file:** `tests/unit/test_model_token_usage.py`
- **Fixtures:** `_reset_cost_table` (autouse), `cost_file` (writes deterministic YAML to `tmp_path`, calls `load_cost_table`)
- **Pattern:** Tests `ModelTokenUsage.total_cost_usd` + `PhaseHandler._extract_metrics_and_usage` together

### `src/orchestrator/runners/execution/phase_handler.py`
- **Test file:** `tests/unit/test_model_token_usage.py` (same file as above)
- **Fixtures:** `cost_file` writes YAML and calls `load_cost_table`
- **Pattern:** Constructs `ActionLog`, `SubAgentLog`, `ExecutionResult` directly; calls static method `PhaseHandler._extract_metrics_and_usage(result)`

### `src/orchestrator/db/access/repositories.py`
- **Test files:** `tests/integration/test_api_full_lifecycle.py`, `tests/integration/test_api_tasks.py`
- **Fixtures in test_api_full_lifecycle.py:**
  - `client_and_drain` → creates `AsyncClient` against an in-memory app with `create_app(settings=...)`
  - `client` → unwraps above
- **Pattern:** HTTP client against in-memory FastAPI app; no direct DB mocking; uses `StaticPool` in-memory SQLite
- **No token_usage_by_model coverage exists yet** in integration tests (confirmed by grep)

### `src/orchestrator/api/schemas/tasks.py` / `runs.py`
- **Test files:** `tests/integration/test_api_full_lifecycle.py`, `tests/integration/test_api_tasks.py`
- **Pattern:** JSON responses from HTTP client checked for field presence

### `ui/src/components/detail/MetricsBar.tsx`
- **Test file:** None found (no `MetricsBar.test.tsx` exists)
- **Related test with RunResponse fixture:** `ui/src/components/detail/__tests__/RecoveryPanel.test.tsx`
  - Uses `makeRun(status)` factory that constructs full `RunResponse`; **does NOT include `token_usage_by_model` field** (would need adding for new tests)

### Frontend test patterns (`ui/src/components/detail/__tests__/`)
- **Framework:** `vitest` + `@testing-library/react`
- **Pattern:** `render(<Component .../>)` inside `QueryClientProvider`; `screen.getBy*` assertions
- **Cleanup:** `afterEach(cleanup)` from `@testing-library/react`
- **No mocking of API** — tests pass data as props directly

---

## Import Reference Table

| Symbol | Import statement |
|--------|-----------------|
| `ModelTokenUsage` | `from orchestrator.state.models import ModelTokenUsage` |
| `ActionLog` | `from orchestrator.state.models import ActionLog` |
| `SubAgentLog` | `from orchestrator.state.models import SubAgentLog` |
| `Attempt` | `from orchestrator.state.models import Attempt` |
| `Run` | `from orchestrator.state.models import Run` |
| `get_model_costs` | `from orchestrator.runners.costs import get_model_costs` |
| `load_cost_table` | `from orchestrator.runners.costs import load_cost_table` |
| `PhaseHandler` | `from orchestrator.runners import PhaseHandler` |
| `AttemptStore` | `from orchestrator.runners import AttemptStore` |
| `ExecutionMetrics` | `from orchestrator.runners.types import ExecutionMetrics` |
| `ExecutionResult` | `from orchestrator.runners.types import ExecutionResult` |
| `ModelTokenUsageSchema` | `from orchestrator.api.schemas.tasks import ModelTokenUsageSchema` |
| `AttemptSchema` | `from orchestrator.api.schemas.tasks import AttemptSchema` |
| `RunResponse` | `from orchestrator.api.schemas.runs import RunResponse` |
| `AttemptModel` | `from orchestrator.db.orm.models import AttemptModel` |
| `RunModel` | `from orchestrator.db.orm.models import RunModel` |
| `RunRepository` | `from orchestrator.db import RunRepository` |
| `_run_to_response` | (internal to `src/orchestrator/api/routers/runs.py`) |
| `ModelTokenUsage` (TS) | `import type { ModelTokenUsage } from '../../types'` |
| `RunResponse` (TS) | `import type { RunResponse } from '../../types'` |

---

## Database Schema Snapshot

### Table: `attempts`

Relevant columns (full set of token/cost related):

| Column | Type | Constraints |
|--------|------|-------------|
| `tokens_read` | `INTEGER` | default 0 |
| `tokens_write` | `INTEGER` | default 0 |
| `tokens_cache` | `INTEGER` | default 0 |
| `duration_ms` | `INTEGER` | default 0 |
| `num_actions` | `INTEGER` | default 0 |
| `token_usage_by_model` | `JSON` | nullable=True, default=None |
| `agent_model` | `STRING` | nullable=True |

### Table: `runs`

Relevant columns:

| Column | Type | Constraints |
|--------|------|-------------|
| `total_tokens_read` | `INTEGER` | default 0 |
| `total_tokens_write` | `INTEGER` | default 0 |
| `total_tokens_cache` | `INTEGER` | default 0 |
| `total_duration_ms` | `INTEGER` | default 0 |
| `total_num_actions` | `INTEGER` | default 0 |
| `token_usage_by_model` | `JSON` | nullable=True, default=None |

### Migration: `p1a2b3c4d5e6_add_token_usage_by_model.py`

Adds `token_usage_by_model JSON nullable` to both `attempts` and `runs`. Revises `o1a2b3c4d5e6`. **This migration already exists and has been applied.**

---

## Constants & Enums

### `model_costs.yaml` (project root: `task-world/model_costs.yaml`)

Models defined:

| Model key | input $/M | output $/M | cache_read $/M | cache_creation $/M |
|-----------|-----------|------------|----------------|--------------------|
| `claude-sonnet-4-6` | 3.00 | 15.00 | 0.30 | 6.00 |
| `claude-sonnet-4-5-20250514` | 3.00 | 15.00 | 0.30 | 6.00 |
| `claude-haiku-4-5-20251001` | 1.00 | 5.00 | 0.10 | 2.00 |
| `claude-opus-4-6` | 5.00 | 25.00 | 0.50 | 10.00 |
| `gpt-4o` | 2.50 | 10.00 | 1.25 | 2.50 |
| `gpt-4o-mini` | 0.15 | 0.60 | 0.075 | 0.15 |
| `unknown_model` | 0 | 0 | 0 | 0 |

Note: `unknown_model` in YAML is **not** used by `get_model_costs()` as a fallback — the code uses `_ZERO_COSTS` directly. The YAML entry is documentation only.

### `_ZERO_COSTS` (in `costs.py`)

```python
_ZERO_COSTS = {
    "cost_per_m_cache_read": 0.0,
    "cost_per_m_cache_creation": 0.0,
    "cost_per_m_input": 0.0,
    "cost_per_m_output": 0.0,
}
```

### Important implementation notes

1. **`ModelTokenUsageSchema.total_cost_usd` is a stored field**, not a computed property. When building the API response in `_run_to_response()`, the router explicitly passes `total_cost_usd=round(u.total_cost_usd, 6)` (calling the domain model's computed property and storing the result).

2. **Run-level aggregation happens in `update_latest_attempt`** (repository layer), not in the service layer. Both attempt-level and run-level JSON blobs are updated in the same DB write by merging dictionaries keyed by model name.

3. **The `cost_file` location**: Step 1 plan says `config/model_costs.yaml` but the actual implementation uses project root `model_costs.yaml`. The `_find_cost_file()` function looks 3 levels up from `src/orchestrator/runners/` = project root. No `config/` directory exists yet.

4. **Frontend test factory gap**: `ui/src/components/detail/__tests__/RecoveryPanel.test.tsx` `makeRun()` does not include `token_usage_by_model` field. Any new frontend tests for the cost breakdown component must add this field to their `RunResponse` factories.

5. **M6 remaining work**: The `MetricsBar.tsx` component uses `estimated_cost_usd` from the API but does not display a per-model breakdown table. Steps 1–5 implementations are complete; **only the frontend per-model cost breakdown table (M6) remains to be built**.
