# Global Config Wiring (Phase Q)

## Overview

Phase Q wires global configuration from `~/.orchestrator/config.yaml` to the running application. Global config is loaded once during app creation and made available throughout the application via dependency injection.

## What Was Implemented

### 1. Global Config Storage in app.state

- **File**: `src/orchestrator/api/app.py`
- **Change**: Added `app.state.global_config = global_cfg` to store the loaded configuration
- Global config is now accessible to all routers and services via dependency injection

### 2. Config Dependency Injection

- **File**: `src/orchestrator/api/deps.py`
- **Added**: `get_global_config(request: Request) -> GlobalConfig` dependency function
- Routes can now inject `GlobalConfig` via `Depends(get_global_config)`

### 3. Dashboard Config API Endpoint

- **File**: `src/orchestrator/api/routers/config.py` (new)
- **Endpoint**: `GET /api/config`
- **Response**:
  ```json
  {
    "dashboard_refresh_interval_seconds": 5,
    "dashboard_max_recent_runs": 50,
    "agents_openhands_url": null,
    "agents_default_type": null
  }
  ```
- Frontend can now query global config settings dynamically

### 4. max_recent_runs Default Limit

- **Files**:
  - `src/orchestrator/db/repositories.py` - Added `limit` parameter to `list_all()`
  - `src/orchestrator/workflow/service.py` - Added `limit` parameter to `list_runs()`
  - `src/orchestrator/api/routers/runs.py` - Applied config default to unfiltered list endpoint
- **Behavior**:
  - `GET /api/runs` now limits to `dashboard.max_recent_runs` (default: 50)
  - `GET /api/runs?limit=N` allows explicit override
  - Filtered queries (by status, project, etc.) ignore the limit

### 5. Nudger Config Conversion

- **File**: `src/orchestrator/config/global_config.py`
- **Added**: `NudgerConfig.to_agent_config()` method
- Converts global config format (seconds as integers) to agent config format (timedeltas)
- Example usage:
  ```python
  from orchestrator.config.global_config import load_global_config

  global_cfg = load_global_config()
  agent = CLIAgent(
      command="claude",
      nudger_config=global_cfg.nudger.to_agent_config(),
  )
  ```

### 6. Documentation for Agent Configuration

- **Files**:
  - `src/orchestrator/agents/cli.py` - Added docstring showing nudger config usage
  - `src/orchestrator/agents/openhands.py` - Added docstring showing openhands_url usage

## Configuration Schema

### Global Config (~/.orchestrator/config.yaml)

```yaml
server:
  host: "0.0.0.0"
  port: 8000

database:
  path: "orchestrator.db"

routines:
  dirs:
    - "~/.orchestrator/routines"

agents:
  default_type: null                    # Agent type to use by default (e.g., "cli_subprocess")
  openhands_url: null                   # OpenHands server URL (for future remote support)
  allowed_types: null                   # List of allowed agent types

dashboard:
  refresh_interval_seconds: 5           # Frontend refresh interval
  max_recent_runs: 50                   # Default limit for GET /api/runs

nudger:
  check_interval_seconds: 60            # How often to check for stuck agents
  nudge_after_seconds: 300              # Time without output before first nudge
  kill_after_seconds: 600               # Time before killing a stuck agent

websocket:
  batching_enabled: true                # Enable event batching
  batch_window_seconds: 0.1             # Batch window duration
```

## Testing

### Integration Tests

1. **test_api_config.py** - Config endpoint returns expected fields and defaults
2. **test_api_max_recent_runs.py** -
   - Default limit applied to unfiltered list
   - Explicit limit overrides default
   - Filters ignore the limit

### Unit Tests

1. **test_global_config_conversion.py** -
   - NudgerConfig conversion to agent format
   - Default values convert correctly
   - Custom values convert correctly

## Usage Notes

### For Agent Instantiation (Future)

Currently, agents are not instantiated automatically by the orchestrator. When agent execution is implemented, use global config as follows:

**CLI Agent with Nudger Config:**
```python
from orchestrator.config.global_config import load_global_config

global_cfg = load_global_config()
agent = CLIAgent(
    command="claude",
    nudger_config=global_cfg.nudger.to_agent_config(),
)
```

**OpenHands Agent with URL:**
```python
from orchestrator.config.global_config import load_global_config

global_cfg = load_global_config()
agent = OpenHandsAgent(
    server_url=global_cfg.agents.openhands_url or "http://localhost:3000",
)
```

### Frontend Integration

The frontend can query configuration via `GET /api/config`:

```typescript
const config = await fetch('/api/config').then(r => r.json());
const refreshInterval = config.dashboard_refresh_interval_seconds * 1000; // ms
const maxRecent = config.dashboard_max_recent_runs;
```

## Architecture Notes

### Why Global Config is in app.state

- **No Global State**: Following the project's "no global state" constraint
- **Dependency Injection**: Config is injected explicitly via FastAPI's `Depends()`
- **Per-App Instance**: Each FastAPI app instance can have its own config (useful for tests)
- **Immutable After Creation**: Config is loaded once and never modified

### Why Nudger Config Conversion is Needed

The global config uses simple integer seconds for YAML simplicity:
```yaml
nudger:
  check_interval_seconds: 60
  nudge_after_seconds: 300
```

The agent nudger uses timedeltas for flexible time arithmetic:
```python
NudgerConfig(
    output_timeout=timedelta(seconds=300),
    nudge_interval=timedelta(seconds=60),
)
```

The `to_agent_config()` method bridges these two representations.

## Remaining Work

### Agent Factory (Future Phase)

Currently, agents are instantiated manually in tests. A future phase should add:

1. **Agent Factory Service** - Centralized agent creation using global config
2. **Agent Registry** - Track running agents per run/task
3. **Agent Runner** - Automatic agent execution based on run.agent_type

Example structure:
```python
class AgentFactory:
    def __init__(self, config: GlobalConfig):
        self._config = config

    def create_agent(self, agent_type: AgentType, agent_config: dict) -> Agent:
        if agent_type == AgentType.CLI_SUBPROCESS:
            return CLIAgent(
                command=agent_config["command"],
                nudger_config=self._config.nudger.to_agent_config(),
            )
        elif agent_type == AgentType.OPENHANDS_LOCAL:
            return OpenHandsAgent(
                server_url=self._config.agents.openhands_url or "http://localhost:3000",
                **agent_config,
            )
        # ...
```

## Files Changed

### New Files
- `src/orchestrator/api/routers/config.py` - Config API endpoint
- `tests/integration/test_api_config.py` - Config endpoint tests
- `tests/integration/test_api_max_recent_runs.py` - Limit behavior tests
- `tests/unit/test_global_config_conversion.py` - Conversion tests
- `docs/intent/24-GLOBAL-CONFIG-WIRING.md` - This document

### Modified Files
- `src/orchestrator/api/app.py` - Store global_config in app.state, register config router
- `src/orchestrator/api/deps.py` - Add get_global_config dependency
- `src/orchestrator/api/routers/runs.py` - Apply max_recent_runs limit
- `src/orchestrator/config/global_config.py` - Add to_agent_config() method
- `src/orchestrator/db/repositories.py` - Add limit parameter to list_all()
- `src/orchestrator/workflow/service.py` - Add limit parameter to list_runs()
- `src/orchestrator/agents/cli.py` - Document nudger config usage
- `src/orchestrator/agents/openhands.py` - Document openhands_url usage

## Definition of Done

- [x] Global config stored in app.state
- [x] Config accessible via dependency injection
- [x] Dashboard config exposed via GET /api/config
- [x] max_recent_runs applied to list_runs endpoint
- [x] Nudger config conversion method implemented
- [x] Documentation added for agent configuration usage
- [x] Integration tests pass (236 tests)
- [x] Unit tests pass (503 tests)
- [x] Type checking passes
