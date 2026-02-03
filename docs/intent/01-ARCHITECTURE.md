# Orchestrator Architecture Document

## Executive Summary

**Orchestrator** is a workflow management system that coordinates LLM-powered coding agents through structured, multi-step software development tasks. It supports multiple execution backends (OpenHands, CLI agents, MCP-connected agents) and provides a web UI for monitoring, debugging, and intervention.

The system is designed to:
1. Manage multiple concurrent runs across multiple projects
2. Support context-fresh execution (clear LLM context between phases)
3. Enable both autonomous and human-in-the-loop workflows
4. Provide comprehensive observability through a web dashboard
5. Support reusable routines with git-based versioning

---

## 1. Core Concepts & Terminology

### 1.1 Hierarchy

```
Project
  └── Run
        ├── Routine (embedded or referenced, git-versioned)
        │     └── Step
        │           └── Task
        └── Attempt (Builder → Verifier cycle)
```

| Term | Description |
|------|-------------|
| **Project** | A git repository or workspace where work is performed |
| **Routine** | A reusable definition of steps. Must be in git repo, committed before use. |
| **Run** | A single execution with referenced or embedded routine definition. |
| **Step** | A sequential phase within a routine containing one or more tasks |
| **Task** | An atomic unit of work within a step |
| **Attempt** | One builder→verifier cycle for a task (includes retries) |

### 1.2 Routine Storage and Versioning

Routines must be stored in git and committed before use. Git SHA provides version snapshot.

| Location | Path | Use Case |
|----------|------|----------|
| **Local** | `~/.orchestrator/routines/` (git repo) | Personal routines |
| **Project** | `{project}/routines/` | Project-specific routines |
| **External** | Allowlisted git URLs | Shared routine libraries |

### 1.3 Run Types

| Type | Routine | Use Case |
|------|---------|----------|
| **Referenced** | Points to committed routine by ID + SHA | Reusable workflows |
| **Embedded** | Contains inline routine definition | One-shot tasks, planning outputs |

### 1.4 Execution Modes

User explicitly chooses execution mode based on available tools:

| Mode | Description | Detection |
|------|-------------|-----------|
| **OpenHands Local** | In-process agent via SDK's LocalConversation | SDK import check (`openhands.sdk`) |
| **OpenHands Docker** | Ephemeral container agent via DockerWorkspace | Docker daemon + package import (`openhands.workspace`) |
| **CLI Subprocess** | Orchestrator manages CLI process | CLI tool detected |
| **User Managed** | External actor (human, Cursor, CLI) connects via REST/MCP | Always available |

No auto-selection - user chooses from detected available options.

### 1.5 Personas

| Persona | Role | Actions |
|---------|------|---------|
| **Builder** | Implements tasks | Updates checklist, runs verification, submits work |
| **Verifier** | Grades work | Reviews against rubric, grades requirements, routes/revises |
| **Orchestrator** | Coordinates workflow | Manages state, triggers agents, handles routing |
| **Human Operator** | Oversees process | Monitors UI, intervenes when needed |

---

## 2. System Architecture

### 2.1 High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Web UI (React)                              │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐│
│  │  Dashboard  │ │     Run     │ │    Task     │ │  Agent Guidance     ││
│  │   (list)    │ │   Detail    │ │   Detail    │ │  (prompts/status)   ││
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘│
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │ WebSocket + REST
┌───────────────────────────────────┴─────────────────────────────────────┐
│                           API Server (FastAPI)                           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐│
│  │   Project   │ │     Run     │ │  Workflow   │ │    Agent           ││
│  │   Manager   │ │   Manager   │ │   Engine    │ │    Gateway          ││
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘│
│                         │                                                │
│            ┌────────────┼────────────┐                                  │
│            │            │            │                                  │
│     ┌──────┴──────┐ ┌───┴────┐ ┌─────┴─────┐                           │
│     │   Routine   │ │  Tool  │ │   Agent   │                           │
│     │   Resolver  │ │Detector│ │  Nudger   │                           │
│     └─────────────┘ └────────┘ └───────────┘                           │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   OpenHands   │         │  CLI Subprocess │         │   MCP Server    │
│   (sandbox)   │         │  (managed)      │         │   (external)    │
└───────────────┘         └─────────────────┘         └─────────────────┘
        │                           │                           │
        └───────────────────────────┴───────────────────────────┘
                                    │
                                    ▼
                          ┌─────────────────┐
                          │   Target Repo   │
                          │   (worktree)    │
                          └─────────────────┘
```

### 2.2 Core Components

#### 2.2.1 API Server (`orchestrator.server`)

FastAPI application providing:
- REST endpoints for CRUD operations
- WebSocket endpoint for real-time updates (throttled, batched)
- SSE endpoint for streaming agent output

#### 2.2.2 Workflow Engine (`orchestrator.workflow`)

State machine managing:
- Run lifecycle (draft → queued → active → complete/failed)
- Pessimistic locking for task state
- Checklist gate enforcement
- Auto-verification execution (sandboxed when using OpenHands)
- Builder ↔ Verifier transitions with fresh context
- Retry logic with attempt tracking

#### 2.2.3 Routine Resolver (`orchestrator.routines`)

Routine management:
- Loading from git repositories (local, project, allowlisted external)
- Git SHA versioning - routines must be committed
- Simplified schema (no ref/use inheritance)
- Validating routine definitions

#### 2.2.4 Tool Detector (`orchestrator.agents.detector`)

Detects available execution options:
- OpenHands Local (SDK import check for `openhands.sdk`)
- OpenHands Docker (Docker daemon running + `openhands.workspace` importable)
- CLI tools: claude, codex, etc. (via `shutil.which()`)
- User Managed (always available)
- Presents options to user for selection

#### 2.2.5 Agent Nudger (`orchestrator.agents.nudger`)

For CLI agents in interactive mode:
- Monitor output for stuck-at-prompt patterns
- Inject nudge messages encouraging continuation
- Track nudge count, kill after threshold

#### 2.2.6 Project Manager (`orchestrator.projects`)

Git operations:
- Worktree creation/management (default: per-run, configurable)
- Branch tracking per run
- Completion actions (MR, merge, cleanup)

#### 2.2.7 State Persistence (`orchestrator.state`)

Storage layer:
- SQLite for relational data (migrations deferred until stable)
- JSON files for session state
- JSONL for history/audit (event sourcing for recovery)
- File-based artifacts (option to store in repo)

---

## 3. Data Model

### 3.1 Entity Relationship

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│   Project    │───┬───│     Run      │───────│   Routine    │
│              │   │   │              │       │  (versioned) │
│ id           │   │   │ id           │       │              │
│ name         │   │   │ project_id   │       │ id           │
│ repo_path    │   │   │ routine_id   │──────▶│ git_sha      │
│              │   │   │ routine_sha  │       │ source       │
│              │   │   │ config       │       │ steps        │
│              │   │   │ status       │       └──────────────┘
│              │   │   │ agent_type   │
│              │   │   │ completion   │
└──────────────┘   │   └──────┬───────┘
                   │          │
                   │   ┌──────┴───────┐
                   │   │     Step     │
                   │   │  (resolved)  │
                   │   └──────┬───────┘
                   │          │
                   │   ┌──────┴───────┐
                   │   │     Task     │
                   │   └──────┬───────┘
                   │          │
                   │   ┌──────┴───────┐
                   └───│   Attempt    │
                       │              │
                       │ tokens_read  │
                       │ tokens_write │
                       │ duration_ms  │
                       └──────────────┘
```

### 3.2 Status Enums

```python
class RunStatus(Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"

class AgentType(Enum):
    OPENHANDS_LOCAL = "openhands_local"
    OPENHANDS_DOCKER = "openhands_docker"
    CLI_SUBPROCESS = "cli_subprocess"
    USER_MANAGED = "user_managed"

class CompletionAction(Enum):
    KEEP_WORKTREE = "keep_worktree"
    DELETE_WORKTREE = "delete_worktree"
```

### 3.3 Run Configuration

```python
class Run(BaseModel):
    id: str
    project_id: str
    status: RunStatus
    config: dict[str, Any]
    
    # Agent selection (user choice)
    agent_type: AgentType
    agent_config: dict[str, Any]  # Model overrides, etc.
    
    # Routine reference with version
    routine_id: str | None
    routine_sha: str | None  # Git SHA for versioning
    routine_source: RoutineSource | None
    routine_embedded: RoutineDefinition | None
    
    # Worktree (default enabled, configurable)
    worktree_enabled: bool = True
    worktree_path: str | None
    
    # Completion behavior
    completion_action: CompletionAction = CompletionAction.NONE
    
    # Metrics
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_duration_ms: int = 0
```

---

## 4. Workflow State Machine

### 4.1 Run Lifecycle

```
                         create run
                              │
                              ▼
                        ┌───────────┐
                        │   DRAFT   │ ← select agent type
                        └─────┬─────┘
                              │ queue
                              ▼
                        ┌───────────┐
                        │  QUEUED   │
                        └─────┬─────┘
                              │ start (acquire lock)
                              ▼
                        ┌───────────┐
             ┌─────────▶│  ACTIVE   │◀─────────┐
             │          └─────┬─────┘          │
             │                │                │
          resume              │              pause
             │          ┌─────┴─────┐          │
        ┌────┴────┐     │           │     ┌────┴────┐
        │ PAUSED  │◀────┘           └────▶│         │
        └─────────┘                       │         │
                              │           │         │
                        ┌─────┴─────┐     │         │
                        │           │     │         │
                        ▼           ▼     ▼         │
                ┌───────────┐ ┌───────────┐         │
                │ COMPLETED │ │  FAILED   │         │
                └─────┬─────┘ └───────────┘         │
                      │                             │
                      ▼                             │
               [completion action]                  │
                      │                             │
                      └─────────────────────────────┘
```

### 4.2 Task Lifecycle (Fresh Context Each Phase)

```
                              ┌─────────────┐
                              │   PENDING   │
                              └──────┬──────┘
                                     │ start (fresh context)
                                     ▼
                              ┌─────────────┐
                    ┌────────▶│  BUILDING   │◀────────┐
                    │         └──────┬──────┘         │
                    │                │                │
                    │         task_submit()           │
                    │                │                │
                    │    ┌───────────┴───────────┐    │
                    │    │ gates pass?           │    │
                    │    └───────────┬───────────┘    │
                    │         ┌──────┴──────┐        │
                    │    fail │             │ pass   │
                    │         ▼             ▼        │
                    │  (stay building) ┌─────────────┐│
                    │                  │  VERIFYING  ││ (fresh context)
                    │                  └──────┬──────┘│
                    │                         │       │
                    │              grade each req,    │
                    │             complete_verification│
                    │                         │       │
                    │           ┌─────────────┴───────┤
                    │           │             │       │
                    │      pass │        revision     │ max attempts
                    │           ▼             │       ▼
                    │    ┌─────────────┐      │ ┌───────────┐
                    │    │  COMPLETED  │      │ │  FAILED   │
                    │    └─────────────┘      │ └───────────┘
                    │                         │
                    └─────────────────────────┘
                         (fresh context for revision)
```

### 4.3 CLI Agent Nudge Flow

When using CLI in interactive mode:

```
┌─────────────────────────────────────────────┐
│           CLI Agent Running                  │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
         ┌─────────────────┐
         │ Monitor Output  │◀──────────────────┐
         └────────┬────────┘                   │
                  │                            │
         ┌────────┴────────┐                   │
         │ Output received │──yes──▶ Reset timer
         └────────┬────────┘                   │
                  │ no (60s timeout)           │
                  ▼                            │
         ┌─────────────────┐                   │
         │ Check: stuck?   │──no───────────────┘
         └────────┬────────┘
                  │ yes
                  ▼
         ┌─────────────────┐
         │ Nudge count < 3?│
         └────────┬────────┘
            yes   │   no
              ▼       ▼
    ┌──────────────┐ ┌─────────────┐
    │ Send nudge   │ │ Kill agent  │
    │ Wait 30s     │ │ Mark failed │
    └──────┬───────┘ └─────────────┘
           │
           └──────────▶ Monitor Output
```

---

## 5. Agent Integration

### 5.1 Tool Detection

```python
class ToolDetector:
    """Detects available execution options."""

    async def detect_all(self) -> list[AgentOption]:
        options = []

        # Check OpenHands Local (SDK import check)
        options.append(self._detect_openhands_local())

        # Check OpenHands Docker (Docker daemon + package import)
        options.append(self._detect_openhands_docker())

        # Check CLI tools (shutil.which)
        options.extend(self._detect_cli_tools())

        # Always offer user-managed option
        options.append(self._detect_user_managed())

        return options
```

### 5.2 Agent Interface

```python
class AgentInterface(Protocol):
    async def start_session(self, context: SessionContext) -> str: ...
    async def send_message(self, session_id: str, message: str) -> AsyncIterator[str]: ...
    async def get_status(self, session_id: str) -> AgentStatus: ...
    async def end_session(self, session_id: str) -> None: ...
    
    # Metrics
    def get_token_counts(self, session_id: str) -> TokenCounts: ...
```

### 5.3 User-Managed Agent UX

For USER_MANAGED mode, the orchestrator waits for an external actor (human, Cursor, third-party CLI) to interact via REST API or MCP tools:

```python
class UserManagedAgentGuidance(BaseModel):
    prompt: str                    # Full prompt to give agent
    mcp_server_url: str           # MCP SSE endpoint (e.g. /mcp/sse)
    rest_api_url: str             # REST API base URL
    expected_actions: list[str]   # What agent should do
    started_at: datetime | None   # When user clicked "started"
    timeout_minutes: int = 60

class UserManagedAgentStatus(Enum):
    WAITING_START = "waiting_start"    # Show "I've started" button
    WAITING_SUBMIT = "waiting_submit"  # Waiting for submit via REST/MCP
    SUBMITTED = "submitted"            # Agent submitted work
    TIMED_OUT = "timed_out"           # No submission in time
    CANCELLED = "cancelled"           # User cancelled
```

---

## 6. Configuration

### 6.1 Simplified YAML Schema

No `ref:` or `use:` inheritance. Explicit and flat.

```yaml
# Routine definition
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
        task_context: "Default instructions for {{feature_name}}..."
        
        # Model-specific overrides (optional)
        model_overrides:
          "claude-sonnet-4-20250514":
            task_context: "Claude-specific instructions..."
        
        requirements:
          - id: "R1"
            desc: "Create requirements.md"
            must: true
            priority: critical
        
        auto_verify:
          items:
            - id: "check"
              cmd: "test -f requirements.md"
              must: true
        
        verifier:
          rubric:
            - id: "quality"
              text: "Are requirements clear?"
          submission_template:
            grade_scale: [A, B, C, D, F]
            require_reason_if_below: A
            require_remediation_if_below: B
        
        retry:
          max_attempts: 3
```

### 6.2 Project Configuration

```yaml
# {project}/orchestrator.yaml
project:
  name: "my-project"

routines:
  dir: "routines"  # Must be git-tracked

worktree:
  enabled: true  # Default
  base_dir: ".worktrees"

completion:
  default_action: "none"  # none, cleanup, merge_request, etc.
```

---

## 7. Observability

### 7.1 Metrics Collected

Per attempt:
- `tokens_read`: Input tokens
- `tokens_write`: Output tokens  
- `tokens_cache`: Cached tokens (if available)
- `duration_ms`: Time taken

Aggregated per run:
- Total tokens (all types)
- Total duration
- Attempt counts per task

### 7.2 Cost Display

```
Tokens: 15,234 read / 3,456 write / 8,901 cache
Est. Cost: $0.45 ⓘ
           └─ "Estimate only. Hidden costs may exist for some providers."
```

---

## 8. Directory Structure

```
orchestrator/
├── src/orchestrator/
│   ├── server/
│   │   ├── app.py
│   │   ├── routes/
│   │   │   ├── projects.py
│   │   │   ├── routines.py
│   │   │   ├── runs.py
│   │   │   └── tasks.py
│   │   └── websocket.py
│   ├── workflow/
│   │   ├── engine.py
│   │   ├── gates.py
│   │   └── transitions.py
│   ├── agents/
│   │   ├── base.py
│   │   ├── openhands.py
│   │   ├── cli.py
│   │   ├── nudger.py
│   │   └── prompts.py
│   ├── routines/
│   │   ├── resolver.py
│   │   └── versioning.py
│   ├── tools/
│   │   └── detector.py
│   ├── projects/
│   │   ├── registry.py
│   │   └── worktree.py
│   ├── config/
│   │   ├── loader.py
│   │   └── models.py
│   └── state/
│       ├── database.py
│       ├── session.py
│       └── history.py
├── ui/
│   └── src/
│       ├── components/
│       │   ├── Dashboard/
│       │   ├── Run/
│       │   ├── Routine/
│       │   └── AgentGuidance/
│       └── hooks/
├── tests/
│   ├── unit/
│   └── integration/  # Requires real API keys
└── examples/
    └── routines/
```

---

## 9. Technology Stack

### Backend
- **Python 3.11+**
- **FastAPI** - Web framework
- **SQLite** - Storage (migrations deferred)
- **Pydantic** - Validation
- **httpx** - Async HTTP
- **GitPython** - Git operations

### Frontend
- **React 18+** with TypeScript
- **Vite** - Build tool
- **TailwindCSS** - Styling
- **Zustand** - State management

### Development
- **uv** - Package management
- **pytest** - Testing
- **ruff** - Linting/formatting
- **pyright** - Type checking
