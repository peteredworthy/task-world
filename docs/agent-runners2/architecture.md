# Architecture: Agent-Runners, Model Profiles, and Agents

## System Overview After Refactor

```
                          ┌─────────────────────────────┐
                          │         Routine YAML         │
                          │  planner_agent: "Planner"    │
                          │  builder_agent: "Builder"    │
                          │  verifier_agent: "Verifier"  │
                          └──────────┬──────────────────┘
                                     │ references
                          ┌──────────▼──────────────────┐
                          │       Agents (new)           │
                          │  ┌─────────────────────┐    │
                          │  │ Planner              │    │
                          │  │  prompt: "..."       │    │
                          │  │  profile: ARCHITECT  │────┼──┐
                          │  ├─────────────────────┤    │  │
                          │  │ Builder              │    │  │
                          │  │  prompt: "..."       │    │  │
                          │  │  profile: CODER      │────┼──┤
                          │  ├─────────────────────┤    │  │
                          │  │ Verifier             │    │  │
                          │  │  prompt: "..."       │    │  │
                          │  │  profile: CODER      │────┼──┤
                          │  └─────────────────────┘    │  │
                          └─────────────────────────────┘  │
                                                           │ resolves model via
                          ┌────────────────────────────────▼─┐
                          │      Model Profiles              │
                          │  ARCHITECT, DESIGNER,             │
                          │  CODER, SUMMARIZER                │
                          └────────────┬─────────────────────┘
                                       │ per-runner defaults
                          ┌────────────▼─────────────────────┐
                          │     Agent Runners (renamed)       │
                          │  ┌───────────────────────────┐   │
                          │  │ CLI_SUBPROCESS             │   │
                          │  │  ARCHITECT -> claude-opus  │   │
                          │  │  CODER -> claude-sonnet    │   │
                          │  │  DESIGNER -> claude-opus   │   │
                          │  │  SUMMARIZER -> claude-haiku│   │
                          │  ├───────────────────────────┤   │
                          │  │ OPENHANDS_LOCAL            │   │
                          │  │  ARCHITECT -> gpt-4o       │   │
                          │  │  CODER -> gpt-4o           │   │
                          │  │  ...                       │   │
                          │  └───────────────────────────┘   │
                          └──────────────────────────────────┘
```

## New Concepts

### Agent Runner (renamed from Agent)

The execution environment. Unchanged in behavior -- still implements the AgentRunner protocol (renamed from Agent protocol), still detected by ToolDetector, still selected by the user when creating a run. Types: `CLI_SUBPROCESS`, `OPENHANDS_LOCAL`, `OPENHANDS_DOCKER`, `USER_MANAGED`, `CODEX_SERVER`, `CLAUDE_SDK`.

**Naming convention**: All Python classes use prefixed names to avoid confusion with the new Agent concept: `AgentRunnerType` (was `AgentType`), `AgentRunnerExecutor` (was `AgentExecutor`), `AgentRunnerInfo` (was `AgentInfo`), etc.

**Key change**: Each runner now has a mapping of `ModelProfile -> model_string` that determines which model to use when executing a given cognitive profile.

### Model Profile

An enum representing a class of cognitive work:

| Profile | Purpose | Typical Model |
|---------|---------|---------------|
| `ARCHITECT` | High-level planning, system design | Strong reasoning model (opus, o1) |
| `DESIGNER` | UI/UX, visual design decisions | Vision-capable model |
| `CODER` | Implementation, debugging, refactoring | Fast code model (sonnet, gpt-4o) |
| `SUMMARIZER` | Condensing context, writing docs | Cheap/fast model (haiku, gpt-4o-mini) |

Profiles are an enum, not user-extensible (initially). The per-runner mapping is user-configurable.

### Agent

A prompt template paired with a model profile. Agents define *what* to do (via prompt) and *how hard to think* (via profile). The runner determines *where* and *how* to execute.

**Default agents:**
- **Planner** -- profile: ARCHITECT. System prompt for breaking down work into steps/tasks. User-assignable only; no special workflow engine integration (no planning phase exists).
- **Builder** -- profile: CODER. System prompt for implementing requirements.
- **Verifier** -- profile: CODER. System prompt for grading work against requirements.

Users can create custom agents (e.g., a "Security Reviewer" with ARCHITECT profile).

**Factory defaults**: Each agent stores both `system_prompt` (user-editable) and `default_prompt` (factory default). Users can reset their edited prompt back to the factory default via `POST /api/agents/{id}/reset-prompt`.

## Data Model Changes

### New Tables

```
agent_configs
├── id: UUID (PK)
├── name: str (unique)
├── system_prompt: text (user-editable)
├── default_prompt: text (factory default, immutable after seed)
├── model_profile: enum (ARCHITECT|DESIGNER|CODER|SUMMARIZER)
├── created_at: datetime
└── updated_at: datetime

runner_profile_defaults
├── id: UUID (PK)
├── runner_type: enum (CLI_SUBPROCESS|OPENHANDS_LOCAL|...)
├── profile: enum (ARCHITECT|DESIGNER|CODER|SUMMARIZER)
├── model: str
└── UNIQUE(runner_type, profile)
```

### Modified Tables

```
runs (renamed columns)
├── runner_type: enum    (was: agent_type)
├── runner_config: JSON  (was: agent_config)
├── runner_started_at    (was: agent_started_at)
└── (other columns unchanged)
```

### Migration Strategy

- Alembic migrations exclusively (production-grade). No DB recreation fallback.
- Alembic migration renames columns on `runs` table.
- New tables created via migration.
- Seed script creates default agents (Planner, Builder, Verifier) with factory default prompts.

## API Changes

### Renamed Endpoints

| Old | New |
|-----|-----|
| `GET /api/agents` | `GET /api/agent-runners` |
| `GET /api/agents/local-models` | `GET /api/agent-runners/local-models` |

### New Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/model-profiles` | List all profiles (enum values) |
| `GET` | `/api/agent-runners/{type}/profiles` | Get runner's profile-to-model defaults |
| `PUT` | `/api/agent-runners/{type}/profiles` | Set runner's profile-to-model defaults |
| `GET` | `/api/agents` | List agents (the new concept) |
| `POST` | `/api/agents` | Create agent |
| `GET` | `/api/agents/{id}` | Get agent detail |
| `PUT` | `/api/agents/{id}` | Update agent (prompt, profile) |
| `DELETE` | `/api/agents/{id}` | Delete agent |
| `POST` | `/api/agents/{id}/reset-prompt` | Reset system prompt to factory default |

Note: `GET /api/agents` now returns the new Agent concept (prompt + profile), not runners.

### Schemas

```python
# New
class ModelProfileSchema(BaseModel):
    name: str           # e.g. "ARCHITECT"
    description: str

class AgentSchema(BaseModel):
    id: str
    name: str
    system_prompt: str
    model_profile: str  # enum name
    created_at: datetime
    updated_at: datetime

class RunnerProfileDefaultsSchema(BaseModel):
    runner_type: str
    profiles: dict[str, str]  # {profile_name: model_string}

# Renamed
class AgentRunnerOption(BaseModel):       # was AgentOption
    runner_type: str                       # was agent_type
    name: str
    title: str
    description: str
    available: bool
    config_schema: list[AgentRunnerConfigField]
    quota: AgentRunnerQuota | None
    profile_defaults: dict[str, str]  # NEW: current profile->model mapping
```

## Routine Schema Changes

```yaml
routine:
  id: "example"
  name: "Example Routine"

  # Routine-level defaults (optional)
  planner_agent: "Planner"
  builder_agent: "Builder"
  verifier_agent: "Verifier"

  steps:
    - id: "step-1"
      title: "Implementation"

      # Step-level overrides (optional)
      builder_agent: "Security-Aware Builder"

      tasks:
        - id: "task-1"
          title: "Write auth module"

          # Task-level overrides (optional)
          verifier_agent: "Security Reviewer"
```

**Resolution order**: task field -> step field -> routine field -> system default agent.

All fields are optional. Existing routines without these fields use the system default agents.

## File Structure After Refactor

```
src/orchestrator/
├── runners/                    # renamed from agents/
│   ├── __init__.py
│   ├── interface.py            # AgentRunner protocol (was Agent)
│   ├── detector.py             # ToolDetector (runner detection)
│   ├── executor.py             # AgentRunnerExecutor (was AgentExecutor)
│   ├── types.py                # ExecutionContext, callbacks
│   ├── cli.py                  # CLIRunner
│   ├── openhands.py            # OpenHandsRunner
│   ├── codex_server.py         # CodexServerRunner
│   ├── claude_sdk.py           # ClaudeSdkRunner
│   └── user_managed.py         # UserManagedRunner
├── agents/                     # NEW: agent concept
│   ├── __init__.py
│   ├── models.py               # AgentConfig SQLAlchemy model
│   ├── schemas.py              # Pydantic schemas
│   └── service.py              # CRUD logic
├── config/
│   ├── enums.py                # AgentRunnerType (was AgentType), ModelProfile
│   └── models.py               # RoutineConfig with agent fields
├── api/
│   ├── routers/
│   │   ├── runners.py          # renamed from agents.py
│   │   ├── agents.py           # NEW: agent CRUD endpoints
│   │   └── model_profiles.py   # NEW: profile endpoints
│   └── schemas/
│       ├── runners.py          # renamed from agents.py
│       └── agents.py           # NEW
└── db/
    └── models.py               # RunModel (renamed columns), AgentConfigModel, RunnerProfileDefaultModel
```

## Frontend Structure After Refactor

```
ui/src/
├── pages/
│   ├── AgentRunners.tsx        # renamed from Agents.tsx
│   └── Agents.tsx              # NEW: agent management page
├── components/
│   ├── AgentRunnerCard.tsx          # renamed from AgentCard (embedded in page)
│   ├── AgentRunnerConfigForm.tsx    # renamed from AgentConfigForm
│   ├── AgentRunnerIcon.tsx          # renamed from AgentIcon
│   ├── AgentRunnerQuotaBadge.tsx    # renamed from AgentQuotaBadge
│   ├── AgentRunnerGuidancePanel.tsx # renamed from AgentGuidancePanel
│   ├── AgentCard.tsx           # NEW: agent (prompt+profile) card
│   └── AgentEditor.tsx         # NEW: prompt editing component
├── types/
│   ├── agentRunners.ts         # renamed from agents.ts (AgentRunnerOption, etc.)
│   └── agents.ts               # NEW: Agent, ModelProfile types
└── lib/
    ├── agentRunnerConfigUtils.ts    # renamed from agentConfigUtils.ts
    └── agentApi.ts             # NEW: agent CRUD API calls
```

## Integration Points

### Execution Flow (modified)

1. User creates run, selects **runner** type, config, and optional per-profile model overrides.
2. Routine specifies **agents** for each role (or uses defaults).
3. Engine resolves agent for current phase (build/verify) via cascading lookup.
4. Resolved agent provides: system prompt + model profile.
5. Runner resolves model profile to concrete model string. Resolution order: per-run profile overrides -> runner's profile defaults.
6. Runner executes with resolved model and concatenated prompt (agent system prompt + separator + task prompt).

### Prompt Generation (modified)

Current: `GET /api/tasks/{id}/prompt` returns a single prompt.
After: Prompt endpoint resolves the agent for the current phase and prepends the agent's system prompt to the task-specific prompt using simple concatenation (agent prompt + separator + task prompt).

### Backward Compatibility

- Runs created without agent fields use system default agents.
- Per-run model-profile overrides: when creating a run, users can set overrides for each model profile used in the routine (e.g., `profile_overrides: {CODER: "claude-sonnet-4-6", ARCHITECT: "claude-opus-4-6"}`). These take precedence over the runner's default profile-to-model mappings.
- Old routine YAMLs without `*_agent` fields work unchanged.
- API returns runner info at new `/api/agent-runners` path.

## Testing Strategy

### Unit Tests
- Model profile enum and resolution logic.
- Agent cascading resolution (task -> step -> routine -> default).
- Runner profile default CRUD.
- Agent CRUD service.
- Prompt composition with agent system prompts.

### Integration Tests
- Full run lifecycle with agent overrides at different levels.
- Profile default persistence and retrieval.
- Agent creation, update, deletion via API.
- Backward compatibility: run a routine with no agent fields.

### Frontend Tests
- Runner page renders with profile configuration.
- Agent page CRUD operations.
- Agent selection in routine context.
- All existing tests pass with renamed imports.

### Browser Verification (Playwright MCP)
- Navigate to Agent Runners page, verify renamed labels.
- Navigate to Agents page, verify CRUD works.
- Create a run, verify runner selection works.
- Run on non-default ports (8001/5174) to avoid conflicting with production orchestrator.

Step configuration for browser testing:
```yaml
mcp_servers:
  - name: "browser"
    command: "npx"
    args: ["-y", "@playwright/mcp@latest", "--headless"]
```
