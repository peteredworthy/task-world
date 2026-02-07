# 25 — Agent Flexibility Additions

**Status:** Draft  
**Depends on:** 01-ARCHITECTURE, 03-PRD, 05-IMPLEMENTATION-PLAN, 08-UI-DESCRIPTION  

---

## Overview

Three related changes to how agents interact with runs:

1. **Agent Change on Resume** — A paused run can be resumed with a different agent.
2. **Agent Liveness Detection** — The orchestrator detects when a managed agent has died and transitions the run to paused.
3. **Agent Visibility in UI** — Runs display agent information in both collapsed and detailed views, and each attempt records the agent/model/settings used.

---

## 1. Agent Change on Resume

### Problem

Currently a run is bound to a single `agent_type` selected at creation. If the chosen agent becomes unavailable (e.g., OpenHands Docker daemon stops) or the user simply wants to try a different agent for remaining work, there is no way to change it without creating a new run.

### Design

When resuming a paused run the user is offered the option to change the agent. This is **not** the full "Configure New Agent Run" dialog — the routine, project, configuration, and worktree are all locked. Only the agent selection is changeable.

#### Resume UX Flow

```
User clicks "Resume" on a paused run
         │
         ▼
  ┌─────────────────────────────────┐
  │  Resume Run: implement-auth     │
  │                                 │
  │  Current agent: OpenHands       │
  │                                 │
  │  [Resume with current agent]    │
  │  [Change agent...]              │
  │                                 │
  └─────────────────────────────────┘
         │
         ├── "Resume with current agent" → resume immediately
         │
         └── "Change agent..." → show agent selection panel
                   │
                   ▼
         ┌─────────────────────────────────┐
         │  Select Agent                   │
         │                                 │
         │  ┌──────────┐ ┌──────────┐     │
         │  │ OpenHands │ │Claude CLI│     │
         │  │ ● Avail.  │ │ ● Avail. │     │
         │  └──────────┘ └──────────┘     │
         │  ┌──────────┐                   │
         │  │ External │                   │
         │  │ ● Always │                   │
         │  └──────────┘                   │
         │                                 │
         │  [Cancel]  [Resume with agent]  │
         └─────────────────────────────────┘
```

The agent selection panel reuses the same agent picker component from the "Configure New Agent Run" dialog. The dialog title and action button text change to reflect this is a resume, not a new run.

#### API Changes

The existing resume endpoint gains an optional body:

```
POST /api/runs/{id}/resume
Content-Type: application/json

{
  "agent_type": "cli_subprocess",       // optional — omit to keep current
  "agent_config": { ... }               // optional — omit to keep current
}
```

If `agent_type` is omitted or null, the run resumes with its current agent. If provided, the run's `agent_type` and `agent_config` are updated before resuming.

#### CLI Changes

```bash
# Resume with current agent
orchestrator run resume <id>

# Resume with different agent
orchestrator run resume <id> --agent cli_subprocess
```

#### Backend Behavior

```python
async def resume_run(run_id: str, agent_type: AgentType | None = None,
                     agent_config: dict | None = None) -> Run:
    run = await get_run(run_id)
    assert run.status == RunStatus.PAUSED

    if agent_type is not None:
        # Validate the new agent is available
        detector = ToolDetector()
        available = await detector.detect_all()
        if agent_type not in [a.agent_type for a in available if a.available]:
            raise AgentUnavailableError(agent_type)

        # Log the agent change as an event
        await history.log(AgentChangedEvent(
            run_id=run_id,
            old_agent=run.agent_type,
            new_agent=agent_type,
            reason="user_changed_on_resume",
        ))

        run.agent_type = agent_type
        run.agent_config = agent_config or {}

    run.status = RunStatus.ACTIVE
    await save_run(run)
    return run
```

#### Scope

The agent change applies to the **entire remaining run**. All subsequent tasks use the new agent. Completed tasks retain their original attempt records (which include the agent that was used — see Section 3).

#### Event

A new event type `agent_changed` is emitted when the agent is switched:

```python
class AgentChangedEvent(HistoryEvent):
    event_type: Literal["agent_changed"] = "agent_changed"
    old_agent: AgentType
    new_agent: AgentType
    old_agent_config: dict
    new_agent_config: dict
    reason: str  # "user_changed_on_resume"
```

---

## 2. Agent Liveness Detection

### Problem

If a managed agent process dies (CLI subprocess crashes, OpenHands container is killed, Docker daemon stops), the run remains in `ACTIVE` status with no agent working on it. The user has no signal that work has stopped.

### Design

The orchestrator monitors managed agents and transitions runs to `PAUSED` when the agent is confirmed dead. On startup, any `ACTIVE` runs whose agents are no longer running are moved to `PAUSED`.

#### Detectable vs Non-Detectable Agents

| Agent Type | Detection Method | Detectable |
|---|---|---|
| CLI Subprocess | Check process is alive (`process.poll()` / `process.returncode`) | Yes |
| OpenHands Local | Check in-process thread/task is alive | Yes |
| OpenHands Docker | Check container status (`docker inspect`) | Yes |
| User Managed | Inactivity timeout (no MCP/REST activity for 1 hour) | Timeout only |

#### Runtime Monitoring

For managed agents (CLI Subprocess, OpenHands Local, OpenHands Docker), the agent execution wrapper already monitors the process. The change is that when an agent dies unexpectedly (i.e., not via a normal submit or orchestrator-initiated kill), the run transitions to `PAUSED` instead of `FAILED`:

```python
class AgentMonitor:
    """Watches agent processes and transitions runs on unexpected death."""

    async def on_agent_died(self, run_id: str, agent_type: AgentType,
                            exit_code: int | None = None) -> None:
        run = await get_run(run_id)
        if run.status != RunStatus.ACTIVE:
            return  # Already handled

        await history.log(AgentDiedEvent(
            run_id=run_id,
            agent_type=agent_type,
            exit_code=exit_code,
            reason="agent_process_died",
        ))

        run.status = RunStatus.PAUSED
        await save_run(run)
        await notify_ui(RunStatusChanged(
            run_id=run_id,
            old_status=RunStatus.ACTIVE,
            new_status=RunStatus.PAUSED,
            reason="Agent process died unexpectedly",
        ))
```

Detection specifics per agent type:

**CLI Subprocess:**
The nudger already monitors the subprocess. When `process.poll()` returns a non-None value outside of a normal completion flow, trigger `on_agent_died`.

**OpenHands Local:**
The agent runs via `asyncio.to_thread`. If the thread raises an unexpected exception (not a normal completion), trigger `on_agent_died`.

**OpenHands Docker:**
Periodically check container status. If the container exits unexpectedly, trigger `on_agent_died`. Interval: every 10 seconds while a task is active.

**User Managed:**
Track the timestamp of the last MCP tool call or REST API interaction. If no activity occurs for the configured timeout (default: 1 hour), transition to `PAUSED` and notify the user. The timeout is configurable:

```yaml
# global config
agents:
  user_managed_timeout_minutes: 60  # default
```

#### Startup Recovery

On startup, any `ACTIVE` runs are checked against their agent. If the agent is no longer running, the run is moved to `PAUSED`:

```python
async def recover_on_startup():
    for run in await get_runs_by_status(RunStatus.ACTIVE):
        agent_alive = await check_agent_alive(run)

        if not agent_alive:
            await history.log(AgentDiedEvent(
                run_id=run.id,
                agent_type=run.agent_type,
                reason="agent_not_running_on_startup",
            ))
            run.status = RunStatus.PAUSED
            await save_run(run)
            logger.info(f"Run {run.id}: agent not running, moved to PAUSED")
        else:
            # Agent still alive — re-attach monitoring
            await reattach_agent_monitor(run)
```

```python
async def check_agent_alive(run: Run) -> bool:
    match run.agent_type:
        case AgentType.CLI_SUBPROCESS:
            # Check if PID from run metadata is still alive
            pid = run.agent_config.get("pid")
            if pid is None:
                return False
            return is_process_alive(pid)

        case AgentType.OPENHANDS_DOCKER:
            # Check if container from run metadata is still running
            container_id = run.agent_config.get("container_id")
            if container_id is None:
                return False
            return await is_container_running(container_id)

        case AgentType.OPENHANDS_LOCAL:
            # In-process agent — if server restarted, agent is gone
            return False

        case AgentType.USER_MANAGED:
            # Check if last activity was within timeout
            last_activity = run.agent_config.get("last_activity_at")
            if last_activity is None:
                return False
            timeout = timedelta(minutes=run.agent_config.get(
                "timeout_minutes", 60))
            return datetime.utcnow() - last_activity < timeout
```

Note: `PAUSED` (not `FAILED`) is used because the work done so far is still valid. The user can resume with the same or a different agent (see Section 1). The run only moves to `FAILED` when an explicit failure condition is met (e.g., max attempts exceeded).

#### Agent Metadata Storage

To support liveness checks across restarts, agent runtime metadata is stored in `agent_config`:

```python
# Set when agent starts
run.agent_config["pid"] = process.pid                      # CLI
run.agent_config["container_id"] = container.id            # Docker
run.agent_config["last_activity_at"] = datetime.utcnow()   # User Managed
```

#### New Event Type

```python
class AgentDiedEvent(HistoryEvent):
    event_type: Literal["agent_died"] = "agent_died"
    agent_type: AgentType
    exit_code: int | None = None
    reason: str  # "agent_process_died" | "agent_not_running_on_startup" | "user_managed_timeout"
```

#### Modification to Existing Startup Recovery

The existing `recover_on_startup()` in Phase 8 (Step 8.2) currently attempts to reconstruct state and marks runs as `FAILED` on recovery failure. This is replaced: instead of failing, runs whose agents are dead are moved to `PAUSED`. The event-sourcing state reconstruction remains — only the final status decision changes.

---

## 3. Agent Visibility in UI

### Problem

The current UI does not show which agent is executing a run. In the detailed task view, there is no way to see what agent, model, or settings were used for each attempt. This makes debugging harder and reduces observability.

### Design

Agent information is surfaced at three levels: dashboard (collapsed run cards), run detail view, and per-attempt detail.

#### 3.1 Dashboard — Collapsed Run Cards

Each run card in the dashboard shows an agent icon next to the run title/metadata:

```
┌────────────────────────────────────────────────────────────────┐
│ 🤖 Feat: User Auth Implementation  [ACTIVE]    Started 2m ago │
│ 🖐 ID: #8392-A · Routine: Scaffold-Agent-v4 · OpenHands      │
│     ↑ agent icon                                 ↑ agent name │
└────────────────────────────────────────────────────────────────┘
```

Agent icons:

| Agent Type | Icon | Label |
|---|---|---|
| OpenHands Local | 🖐 (or custom SVG) | OpenHands |
| OpenHands Docker | 🐳 (or custom SVG) | OpenHands Docker |
| CLI Subprocess | ▶ (terminal icon) | Claude CLI / Codex CLI |
| User Managed | 👤 (person icon) | External Agent |

The icon is compact and does not take significant space. The text label (e.g., "OpenHands") is shown in the metadata line alongside routine name and project.

#### 3.2 Run Detail View — Header

The run detail header includes agent information as text:

```
← Runs / implement-auth

implement-auth  ● RUNNING                          ‖ Pause Run

ID: #8821 · Started 2 mins ago
Agent: 🖐 OpenHands Local · Model: claude-sonnet-4-5-20250514
```

If the agent was changed during the run (via resume), a small note is shown:

```
Agent: ▶ Claude CLI · Model: claude-sonnet-4-5-20250514 (changed from OpenHands)
```

#### 3.3 Per-Attempt Detail — Task Inspector / Task Detail Card

Each attempt in the attempt history records and displays the agent, model, and settings used:

**Data model change — Attempt gains agent fields:**

```python
class Attempt(BaseModel):
    attempt_num: int
    # ... existing fields ...

    # NEW: agent snapshot for this attempt
    agent_type: AgentType | None = None
    agent_model: str | None = None          # e.g. "claude-sonnet-4-5-20250514"
    agent_settings: dict[str, Any] = Field(default_factory=dict)
```

These fields are set when the attempt is created, capturing a snapshot of the run's agent configuration at that moment. This means that if the agent is changed between attempts (via resume), each attempt accurately reflects what was used.

**What goes in `agent_settings`:**
- Model name/version
- Temperature (if configurable)
- Max tokens
- Any agent-specific configuration (e.g., nudge interval for CLI, sandbox config for OpenHands)
- Does NOT include secrets or API keys

**UI — Attempt History in Task Detail Card (expanded):**

```
┌─────────────────────────────────────────────────────┐
│ Attempt #1                               FAILED     │
│ 🖐 OpenHands · claude-sonnet-4-5 · 14,204 tokens   │
│ Self-correction triggered: Missing context...        │
├─────────────────────────────────────────────────────┤
│ Attempt #2                               RUNNING    │
│ ▶ Claude CLI · claude-sonnet-4-5 · 8,102 tokens    │
│ Generating markdown structure...                     │
└─────────────────────────────────────────────────────┘
```

Clicking into an attempt shows full details including the complete `agent_settings` as a collapsible JSON/key-value section:

```
Agent Details
  Type:      Claude CLI (cli_subprocess)
  Model:     claude-sonnet-4-5-20250514
  Settings:
    nudge_interval:   30s
    max_nudges:       3
    output_timeout:   60s
```

#### API Schema Changes

**RunSchema** gains:

```python
class RunSchema(BaseModel):
    # ... existing fields ...
    agent_type: AgentType | None
    agent_type_display: str       # Human-readable: "OpenHands Local"
    agent_icon: str               # Icon key for frontend: "openhands", "cli", "docker", "external"
```

**AttemptSchema** gains:

```python
class AttemptSchema(BaseModel):
    # ... existing fields ...
    agent_type: AgentType | None
    agent_model: str | None
    agent_settings: dict[str, Any]
```

---

## Summary of Changes

### New Event Types
- `agent_changed` — Emitted when agent is switched on resume
- `agent_died` — Emitted when a managed agent process dies or times out

### Modified Models
- `Run` — No structural change; `agent_type` and `agent_config` are already present and are now mutable on resume
- `Attempt` — Gains `agent_type`, `agent_model`, `agent_settings` fields
- `Run.agent_config` — Now also stores runtime metadata (`pid`, `container_id`, `last_activity_at`) for liveness checks

### New Backend Components
- `AgentMonitor` — Watches agent processes, triggers `on_agent_died`
- `check_agent_alive(run)` — Checks if a run's agent is still active
- Modified `recover_on_startup()` — Moves agentless `ACTIVE` runs to `PAUSED`

### Modified API Endpoints
- `POST /api/runs/{id}/resume` — Accepts optional `agent_type` and `agent_config` in body

### New Global Config Options
- `agents.user_managed_timeout_minutes` — Inactivity timeout for user-managed agents (default: 60)

### UI Changes
- Dashboard run cards — Agent icon + label in metadata line
- Run detail header — Agent type, model, and change history
- Task detail / Inspector — Per-attempt agent, model, and settings display
- Resume dialog — Option to change agent before resuming

### CLI Changes
- `orchestrator run resume <id> --agent <type>` — Resume with a different agent

---

## Files Affected

### New Files
- `src/orchestrator/agents/monitor.py` — AgentMonitor class
- `src/orchestrator/events/agent.py` — AgentChangedEvent, AgentDiedEvent

### Modified Files
- `src/orchestrator/state/models.py` — Attempt model gains agent fields
- `src/orchestrator/workflow/engine.py` — Set agent snapshot on attempt creation
- `src/orchestrator/workflow/service.py` — Resume accepts agent override
- `src/orchestrator/api/routers/runs.py` — Resume endpoint body, RunSchema changes
- `src/orchestrator/api/schemas.py` — RunSchema, AttemptSchema additions
- `src/orchestrator/agents/cli.py` — Store PID in agent_config, call monitor on death
- `src/orchestrator/agents/openhands.py` — Call monitor on unexpected thread death
- `src/orchestrator/agents/openhands_docker.py` — Store container_id, periodic health check
- `src/orchestrator/config/global_config.py` — user_managed_timeout_minutes
- `src/orchestrator/startup.py` — Modified recover_on_startup
- `ui/src/components/dashboard/RunCard.tsx` — Agent icon + label
- `ui/src/components/detail/RunDetailHeader.tsx` — Agent info display
- `ui/src/components/detail/TaskDetailCard.tsx` — Per-attempt agent info
- `ui/src/components/detail/shared.tsx` — AttemptTimeline gains agent columns
- `ui/src/components/run/ResumeDialog.tsx` — New resume dialog with agent picker
