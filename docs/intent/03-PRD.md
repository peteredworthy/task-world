# Orchestrator - Product Requirements Document

**Version:** 1.1  
**Status:** Decisions Incorporated  
**Target:** Clean-room implementation by Claude Code

---

## 1. Executive Summary

Orchestrator coordinates LLM-powered coding agents through structured, multi-step software development tasks. Key characteristics:

- **Routine/Run model** - Reusable templates with git-based versioning
- **User-selected agents** - OpenHands, CLI tools, or external MCP connections
- **Fresh context per phase** - Builder and verifier get clean context
- **Simplified configuration** - No inheritance, explicit and flat YAML

---

## 2. Goals & Non-Goals

### Goals
1. Define reusable, git-versioned routines
2. Execute runs with user-selected agent
3. Fresh context between builder/verifier phases
4. Provide visibility via dashboard (active + recent runs)
5. Support worktree isolation (default on, configurable)
6. Track token counts and cost estimates

### Non-Goals
1. Auto-selection of agents (user chooses)
2. Complex YAML inheritance (simplified schema)
3. External availability before feature complete
4. Multi-tenant SaaS

---

## 3. Core Concepts

### 3.1 Routine/Run Model

| Concept | Description |
|---------|-------------|
| **Routine** | Git-versioned template with steps/tasks |
| **Run** | Execution of routine with specific config |
| **Embedded** | One-shot routine defined inline in run |

### 3.2 Agent Selection

User explicitly selects from detected available options:
- OpenHands Local (if `openhands-ai` SDK importable — runs in-process)
- OpenHands Docker (if Docker daemon running + `openhands-workspace` importable — ephemeral containers)
- CLI tools (if installed: claude, codex)
- User Managed (always available — external actor via REST/MCP)

No auto-selection algorithm.

### 3.3 Execution Phases

Fresh context for each phase:
```
Builder (context A) → Verifier (context B) → Builder revision (context C)
```

---

## 4. Functional Requirements

### 4.1 Routine Management

#### FR-RM-1: Git-Based Storage
- Routines MUST be stored in git repository
- Routines MUST be committed before use
- Run records git SHA of routine at creation

#### FR-RM-2: Simplified Schema
- No `ref:` or `use:` inheritance
- Explicit IDs everywhere
- Flat catalog structure

#### FR-RM-3: Source Allowlist
- Local routines: `~/.orchestrator/routines/`
- Project routines: `{project}/routines/`
- External: Only from allowlisted git URLs

#### FR-RM-4: Model Overrides
- Tasks MAY have `model_overrides` section
- Override task_context per model
- Default always required

---

### 4.2 Run Management

#### FR-RN-1: Agent Selection
- System SHALL detect available agents on run creation
- System SHALL present options to user
- User MUST explicitly select agent type
- No automatic selection

#### FR-RN-2: Worktree
- Default: Create worktree per run
- Configurable: Can disable worktree
- Configuration at project or run level

#### FR-RN-3: Completion Actions
- `keep_worktree` - Leave worktree after completion (default)
- `delete_worktree` - Delete worktree after completion
- Git operations (MR, merge) are handled by routine instructions to the agent

#### FR-RN-4: State Locking
- Pessimistic locking when agent starts task
- Unlock on complete or timeout (5 minutes)
- Reject concurrent access

---

### 4.3 Workflow Engine

#### FR-WF-1: Fresh Context
- Builder phase gets fresh context
- Verifier phase gets fresh context
- Revision gets fresh context
- No context carryover between phases

#### FR-WF-2: Token Tracking
- Track per attempt: tokens_read, tokens_write, tokens_cache
- Track duration_ms
- Aggregate totals per run

#### FR-WF-3: Auto-Verify Sandboxing
- When using OpenHands: run auto-verify through OpenHands
- Provides sandbox protection for verification commands

---

### 4.4 Agent Integration

#### FR-AG-1: Tool Detection
```python
detect_all() -> list[AgentOption]
```
- Check OpenHands Local (SDK import check)
- Check OpenHands Docker (Docker daemon + package import)
- Check CLI tools: claude, codex (via `shutil.which()`)
- Always offer external MCP option

#### FR-AG-2: CLI Subprocess Mode
- Orchestrator spawns and manages CLI process
- Monitor output for stuck-at-prompt
- Nudge mechanism when stuck

#### FR-AG-3: CLI Nudge Mechanism
- Detect stuck: 60s no output + prompt pattern
- Send nudge message
- Max 3 nudges, 30s apart
- Kill after 3rd nudge ignored

#### FR-AG-4: External Agent Mode
- Show prompt to copy
- "I've started the agent" button
- "Cancel waiting" option
- Status: "Waiting for agent to connect (started 2m ago)"
- Auto-timeout with notification

---

### 4.5 Web UI

#### FR-UI-1: Dashboard
- Show active runs
- Show recently finished (configurable: 1hr, 4hrs, 24hrs, 1 week)
- Filter by project
- Group by project
- Support multi-project view

#### FR-UI-2: Agent Guidance Panel
- Display copyable prompt
- Show MCP server URL
- List expected actions
- Connection status indicator
- Timeout countdown

#### FR-UI-3: Cost Display
- Show token counts (read/write/cache)
- Show cost estimate
- Hover note: "Estimate only. Hidden costs may exist."

#### FR-UI-4: Real-time Updates
- WebSocket with throttling (100ms)
- Batch related updates

---

### 4.6 State & Persistence

#### FR-SP-1: Event Sourcing
- Critical transitions logged to history.jsonl
- Reconstruct state from history on startup
- Recovery from crash

#### FR-SP-2: Artifacts
- Store in `.orchestrator/artifacts/` (default)
- Option to store in repo
- Organized by run/step/task/attempt

#### FR-SP-3: Migrations
- Use Alembic when schema stabilizes
- Defer implementation during rapid development

---

## 5. Configuration Schema

### 5.1 Global Config

```yaml
# ~/.orchestrator/config.yaml
server:
  host: "0.0.0.0"
  port: 8080

database:
  path: "~/.orchestrator/orchestrator.db"

routines:
  local_dir: "~/.orchestrator/routines"
  external_allowlist:
    - "git@github.com:myorg/routines.git"

agents:
  openhands:
    model: "gpt-5-mini"      # Used by both Local and Docker modes
  openhands_docker:
    server_image: "ghcr.io/openhands/agent-server:latest-python"

dashboard:
  recent_hours: 24  # 1, 4, 24, 168 (week)
```

### 5.2 Project Config

```yaml
# {project}/orchestrator.yaml
project:
  name: "my-project"

routines:
  dir: "routines"

worktree:
  enabled: true
  base_dir: ".worktrees"

completion:
  default_action: "none"
```

### 5.3 Routine Schema

```yaml
routine:
  id: "planning"
  name: "Feature Planning"
  
  inputs:
    - name: "feature_name"
      required: true
    - name: "target_branch"
      default: "main"

  steps:
    - id: "S-01"
      title: "Requirements"
      task:
        id: "T-01"
        title: "Create Requirements"
        task_context: |
          Create requirements for {{feature_name}}
        
        model_overrides:
          "claude-sonnet-4-20250514":
            task_context: |
              Claude-specific instructions...
        
        requirements:
          - id: "R1"
            desc: "Create requirements.md"
            must: true
            priority: critical
        
        auto_verify:
          items:
            - id: "check_file"
              cmd: "test -f requirements.md"
              must: true
          tail_lines: 20
        
        verifier:
          rubric:
            - id: "quality"
              text: "Are requirements clear and testable?"
          submission_template:
            grade_scale: [A, B, C, D, F]
            require_reason_if_below: A
            require_remediation_if_below: B
        
        retry:
          max_attempts: 3
```

---

## 6. API Endpoints

### 6.1 Routines

```
GET  /api/routines                    List routines
GET  /api/routines/{id}               Get routine
POST /api/routines/validate           Validate routine YAML
```

### 6.2 Runs

```
GET  /api/runs                        List runs
GET  /api/runs?status=active          Filter by status
GET  /api/runs?recent_hours=24        Recent runs
POST /api/runs                        Create run
GET  /api/runs/{id}                   Get run
GET  /api/runs/{id}/agents            Get available agents

POST /api/runs/{id}/queue             Queue run
POST /api/runs/{id}/start             Start run (with agent selection)
POST /api/runs/{id}/pause             Pause run
POST /api/runs/{id}/resume            Resume run
POST /api/runs/{id}/cancel            Cancel run
```

### 6.3 Tasks

```
GET  /api/runs/{rid}/tasks/{tid}                              Get task
POST /api/runs/{rid}/tasks/{tid}/start                        Start building
POST /api/runs/{rid}/tasks/{tid}/submit                       Builder submit
PATCH /api/runs/{rid}/tasks/{tid}/checklist/{req_id}          Update checklist item
PUT  /api/runs/{rid}/tasks/{tid}/checklist/{req_id}/grade     Grade a requirement
POST /api/runs/{rid}/tasks/{tid}/complete-verification        Trigger grade evaluation
```

### 6.4 External Agent

```
GET  /api/runs/{id}/guidance          Get agent guidance (prompt, MCP URL)
POST /api/runs/{id}/agent-started     Mark agent as started
POST /api/runs/{id}/agent-cancelled   Cancel waiting for agent
```

---

## 7. CLI Interface

```bash
# Server
orchestrator serve

# Routines
orchestrator routine list
orchestrator routine show <id>
orchestrator routine validate <path>

# Runs
orchestrator run list [--status STATUS] [--recent HOURS]
orchestrator run create <routine> --project <path> --config '<json>'
orchestrator run agents <id>           # Show available agents
orchestrator run start <id> --agent <type>
orchestrator run status <id>
orchestrator run pause <id>
orchestrator run resume <id>
orchestrator run cancel <id>
```

---

## 8. Build Order

Not a traditional MVP - build incrementally with full testing:

### Phase 1: Orchestration Core
1. Simplified config models (no inheritance)
2. Routine loading with git versioning
3. State machine for run/task lifecycle
4. Checklist gates
5. Event sourcing for history

### Phase 2: Workflow Engine
1. Auto-verification runner
2. Grade threshold logic
3. Fresh context per phase
4. Token tracking

### Phase 3: Agent Integration
1. Tool detection
2. OpenHands integration
3. CLI subprocess with nudging
4. MCP server for external agents
5. External agent UX (guidance, timeout)

### Phase 4: API & UI
1. REST endpoints
2. WebSocket (throttled, batched)
3. Dashboard (active + recent)
4. Run detail view
5. Agent guidance panel

### Phase 5: Git Integration
1. Worktree management
2. Completion actions
3. Routine versioning (SHA)

### Phase 6: Polish
1. CLI commands
2. Error handling
3. Documentation
4. Full test coverage

---

## 9. Testing Requirements

### Unit Tests
- State machine transitions
- Gate logic
- Config validation
- Nudge mechanism logic

### Integration Tests (Require Credentials)
- OpenHands API (needs running server + OPENAI_API_KEY for LLM)
- CLI tools (need authenticated CLIs)
- Git operations

### E2E Tests
- Full run workflow
- External agent connection
- Recovery from crash

---

## 10. Metrics & Observability

### Per Attempt
- `tokens_read`
- `tokens_write`
- `tokens_cache`
- `duration_ms`

### Per Run
- Total tokens (all types)
- Total duration
- Attempt count per task
- Cost estimate

### Display
```
Run: implement-auth
Duration: 45m 23s
Tokens: 125,432 read / 34,567 write / 89,012 cache
Est. Cost: $4.56 ⓘ
```

---

## Appendix: Glossary

| Term | Definition |
|------|------------|
| **Routine** | Git-versioned workflow template |
| **Run** | Execution instance of a routine |
| **Embedded** | One-shot inline routine in a run |
| **Step** | Phase containing tasks |
| **Task** | Atomic work unit |
| **Attempt** | One builder→verifier cycle |
| **Nudge** | Prompt injected to stuck CLI agent |
| **Worktree** | Git worktree for run isolation |
