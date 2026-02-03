# Orchestrator UI Description

A comprehensive guide for building the Orchestrator UI, designed for use with Stitch or similar LLM UI tools.

---

## 1. Mental Model

### Core Concept

Orchestrator helps developers manage LLM-powered coding agents through structured workflows. Think of it as a **task management system for AI agents** where:

- **Routines** are reusable workflow templates (like "Feature Planning" or "Bug Fix")
- **Runs** are executions of those workflows with specific inputs
- The user **monitors progress** and **intervenes when needed**

### User's Perspective

The user is a developer who:
1. Selects or creates a routine for a task
2. Starts a run with specific configuration
3. Chooses which AI agent to use
4. Monitors the agent's progress
5. Reviews results and intervenes if the agent gets stuck

The UI should feel like a **mission control dashboard** - showing what's happening, what needs attention, and giving control when needed.

---

## 2. Data Model

### Entity Hierarchy

```
Routine (template)
    │
    └── Run (execution)
            │
            ├── Step 1
            │     ├── Task 1.1
            │     │     ├── Attempt 1 (builder → verifier)
            │     │     ├── Attempt 2 (revision)
            │     │     └── Attempt 3 (passed)
            │     └── Task 1.2
            │           └── Attempt 1
            │
            └── Step 2
                  └── Task 2.1
```

### Entity Details

#### Routine
A reusable workflow template stored in git.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (e.g., "planning") |
| `name` | string | Display name |
| `description` | string | What this routine does |
| `source` | enum | Where it's stored: `local`, `project`, `external` |
| `git_sha` | string | Version (commit SHA) |
| `inputs` | array | Required/optional parameters |
| `steps` | array | Step definitions |

**Routine Inputs:**
```
{
  name: "feature_name",
  required: true,
  default: null,
  description: "Name of the feature to plan"
}
```

#### Run
A single execution of a routine.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier |
| `status` | enum | `draft`, `queued`, `active`, `paused`, `completed`, `failed` |
| `routine_id` | string | Which routine (null if embedded) |
| `routine_sha` | string | Version used |
| `config` | object | Input values provided |
| `agent_type` | enum | Selected agent |
| `project_id` | string | Target project |
| `worktree_path` | string | Working directory |
| `created_at` | datetime | When created |
| `updated_at` | datetime | Last activity |
| `current_step` | string | Active step ID |
| `current_task` | string | Active task ID |
| `total_tokens_read` | int | Total input tokens |
| `total_tokens_write` | int | Total output tokens |
| `total_duration_ms` | int | Total time |

**Run Statuses:**
| Status | Meaning | Color |
|--------|---------|-------|
| `draft` | Created, not started | Gray |
| `queued` | Ready, waiting to start | Blue |
| `active` | Currently executing | Green pulse |
| `paused` | Manually paused | Yellow |
| `completed` | Successfully finished | Green |
| `failed` | Error or max attempts | Red |

#### Step
A phase within a run containing tasks.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Step ID (e.g., "S-01") |
| `title` | string | Display title |
| `status` | enum | `pending`, `in_progress`, `completed`, `failed`, `skipped` |
| `order` | int | Sequence number |
| `tasks` | array | Tasks in this step |

#### Task
An atomic unit of work.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Task ID (e.g., "T-01") |
| `title` | string | Display title |
| `task_context` | string | Instructions for agent |
| `status` | enum | `pending`, `building`, `verifying`, `completed`, `failed` |
| `requirements` | array | Checklist items |
| `current_attempt` | int | Which attempt (1-based) |
| `max_attempts` | int | Retry limit |

**Task Statuses:**
| Status | Meaning | Phase |
|--------|---------|-------|
| `pending` | Not started | - |
| `building` | Agent implementing | Builder |
| `verifying` | Agent reviewing | Verifier |
| `completed` | Passed verification | Done |
| `failed` | Max attempts exceeded | Done |

#### Attempt
One builder→verifier cycle.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Attempt ID |
| `attempt_num` | int | Which attempt (1, 2, 3...) |
| `persona` | enum | `builder` or `verifier` |
| `status` | enum | `building`, `verifying`, `passed`, `revision_needed`, `failed` |
| `checklist` | array | Requirement statuses |
| `grades` | object | Verifier grades (if verifying) |
| `tokens_read` | int | Input tokens this attempt |
| `tokens_write` | int | Output tokens this attempt |
| `duration_ms` | int | Time for this attempt |
| `started_at` | datetime | When started |
| `completed_at` | datetime | When finished |

#### Requirement (Checklist Item)
A single requirement to track.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Requirement ID |
| `desc` | string | What must be done |
| `status` | enum | `open`, `done`, `not_applicable`, `blocked` |
| `priority` | enum | `critical`, `expected`, `nice` |
| `note` | string | Justification (if N/A or blocked) |
| `grade` | string | Verifier grade (A-F) |
| `grade_reason` | string | Why this grade |

---

## 3. User Operations

### Routine Operations

| Operation | Description | When Available |
|-----------|-------------|----------------|
| **List routines** | View all available routines | Always |
| **View routine** | See routine details, steps, inputs | Always |
| **Filter by source** | Show only local/project/external | Always |

### Run Operations

| Operation | Description | When Available |
|-----------|-------------|----------------|
| **Create run** | Start a new run from routine | Always |
| **Configure run** | Set input parameters | Status: draft |
| **Select agent** | Choose execution agent | Status: draft |
| **Queue run** | Mark ready to start | Status: draft |
| **Start run** | Begin execution | Status: queued |
| **Pause run** | Temporarily stop | Status: active |
| **Resume run** | Continue paused run | Status: paused |
| **Cancel run** | Abort execution | Status: active/paused |
| **Delete run** | Remove run record | Status: any |
| **View run** | See full details | Always |

### Task Operations

| Operation | Description | When Available |
|-----------|-------------|----------------|
| **View task** | See task details, attempts | Always |
| **View checklist** | See requirement statuses | Always |
| **View grades** | See verifier grades | After verification |
| **View logs** | See verification output | After verify run |
| **Retry task** | Start new attempt | Status: failed |
| **Skip task** | Mark as skipped | Status: any (admin) |

### Agent Operations

| Operation | Description | When Available |
|-----------|-------------|----------------|
| **View available** | List detected agents | Creating run |
| **Copy prompt** | Copy agent prompt | External agent mode |
| **Mark started** | Signal agent started | Waiting for external |
| **Cancel waiting** | Stop waiting for agent | Waiting for external |

---

## 4. Views & Components

### 4.1 Dashboard (Primary View)

**Purpose:** Overview of all runs, quick access to active work.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│ [Orchestrator Logo]    [Search]           [New Run] [⚙️]    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Filters: [All ▾] [Active ▾] [Recent: 24h ▾] [Project ▾]   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 🟢 implement-auth          Active    Step 2/3       │   │
│  │    planning routine • my-project • 12m ago          │   │
│  │    ├─ S-01 Requirements ✓                           │   │
│  │    ├─ S-02 Design ● Building (attempt 2)            │   │
│  │    └─ S-03 Generate ○                               │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 🟡 fix-bug-123             Paused    Step 1/2       │   │
│  │    bug-fix routine • api-service • 1h ago           │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ ✓  plan-feature-x          Completed  3/3 steps     │   │
│  │    planning routine • web-app • 2h ago              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Run Row (Collapsed):**
- Status indicator (colored dot/icon)
- Run name/ID
- Status text
- Progress (Step X/Y)
- Routine name
- Project name
- Time since last activity

**Run Row (Expanded):**
- Step timeline showing status of each step
- Current task info
- Attempt count for active task
- Quick actions (Pause, View Details)

**Filters:**
- Status: All, Active, Completed, Failed
- Recency: 1h, 4h, 24h, 1 week
- Project: All or specific project
- Routine: All or specific routine

---

### 4.2 Run Detail View

**Purpose:** Deep dive into a single run.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│ ← Back    implement-auth                    [Pause] [⋮]     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Status: 🟢 Active          Agent: OpenHands               │
│  Routine: planning (sha: a1b2c3d)                          │
│  Project: my-project        Worktree: .worktrees/run-123   │
│  Started: 12 minutes ago                                    │
│                                                             │
│  Config:                                                    │
│    feature_name: "user-authentication"                      │
│    target_branch: "main"                                    │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│                                                             │
│  Steps                                                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ ✓ S-01: Requirements Gathering                      │   │
│  │   Completed in 5m 23s • 2 attempts                  │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ ● S-02: Design Document           [ACTIVE]          │   │
│  │   T-01: Write Design • Building (attempt 2)         │   │
│  │   ┌─────────────────────────────────────────────┐   │   │
│  │   │ Checklist                                   │   │   │
│  │   │ ✓ Create design.md           critical      │   │   │
│  │   │ ○ Include architecture       expected      │   │   │
│  │   │ ○ Document APIs              critical      │   │   │
│  │   └─────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ ○ S-03: Generate Implementation                     │   │
│  │   Pending                                           │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│                                                             │
│  Metrics                                                    │
│  Tokens: 45,234 read / 12,456 write                        │
│  Duration: 12m 34s                                          │
│  Est. Cost: $1.23 ⓘ                                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Sections:**
1. **Header:** Run name, status, actions
2. **Overview:** Agent, routine, project, config
3. **Steps:** Expandable list with task details
4. **Metrics:** Token counts, duration, cost estimate

---

### 4.3 Task Detail Panel (Slide-over)

**Purpose:** Deep dive into a specific task, especially for debugging.

**Layout:**
```
┌─────────────────────────────────────────┐
│ Task: Write Design Document        [×]  │
├─────────────────────────────────────────┤
│                                         │
│ Status: Building (Attempt 2 of 3)       │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ Context                             │ │
│ │ Create a design document for       │ │
│ │ user-authentication...             │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ Checklist                      3/5  │ │
│ │ ✓ Create design.md         A       │ │
│ │ ✓ Include overview         B       │ │
│ │ ○ Architecture diagram     -       │ │
│ │ ○ Document APIs            -       │ │
│ │ ○ Identify dependencies    -       │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ Attempt History                     │ │
│ │                                     │ │
│ │ Attempt 1 - Revision Needed         │ │
│ │   Builder: 3m 12s, 8.2k tokens      │ │
│ │   Verifier: 1m 05s, 2.1k tokens     │ │
│ │   Grades: R1:B R2:C R3:D R4:-       │ │
│ │   "Missing API documentation"       │ │
│ │                                     │ │
│ │ Attempt 2 - In Progress             │ │
│ │   Builder: 2m 34s (running)         │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ Verification Logs                   │ │
│ │ [View Last Run Output]              │ │
│ └─────────────────────────────────────┘ │
│                                         │
└─────────────────────────────────────────┘
```

**Sections:**
1. **Header:** Task title, status, close button
2. **Context:** Task instructions (collapsible if long)
3. **Checklist:** Requirements with status and grades
4. **Attempt History:** Timeline of attempts with metrics
5. **Verification Logs:** Link to detailed output

---

### 4.4 Agent Guidance Panel

**Purpose:** Help user start external agents.

**Shown when:** `agent_type` is `user_managed`

**Layout:**
```
┌─────────────────────────────────────────┐
│ Agent Guidance                          │
├─────────────────────────────────────────┤
│                                         │
│ Start your agent with this prompt:      │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ # Task: Write Design Document      │ │
│ │                                     │ │
│ │ ## Context                          │ │
│ │ Create a design document for...     │ │
│ │                                     │ │
│ │ ## Requirements                     │ │
│ │ - Create design.md (critical)       │ │
│ │ ...                                 │ │
│ │                            [Copy 📋]│ │
│ └─────────────────────────────────────┘ │
│                                         │
│ MCP Server: localhost:8080/mcp          │
│                            [Copy 📋]    │
│                                         │
│ The agent should:                       │
│ • Work on the task                      │
│ • Update checklist via MCP tools        │
│ • Submit when complete                  │
│                                         │
│ ─────────────────────────────────────── │
│                                         │
│ Status: ⏳ Waiting for connection       │
│         Started 2m 34s ago              │
│         Timeout in 2m 26s               │
│                                         │
│ [I've Started the Agent] [Cancel]       │
│                                         │
└─────────────────────────────────────────┘
```

---

### 4.5 Routine Library View

**Purpose:** Browse and select routines.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│ Routine Library                              [Search]       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Source: [All ▾]  [Local] [Project] [External]              │
│                                                             │
│ Local Routines                                              │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ 📋 planning                                         │    │
│ │    Feature Planning                                 │    │
│ │    Plan a feature and generate implementation       │    │
│ │    3 steps • 2 inputs                    [Use →]   │    │
│ └─────────────────────────────────────────────────────┘    │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ 🐛 bug-fix                                          │    │
│ │    Bug Investigation and Fix                        │    │
│ │    Investigate and fix a bug                        │    │
│ │    2 steps • 3 inputs                    [Use →]   │    │
│ └─────────────────────────────────────────────────────┘    │
│                                                             │
│ Project Routines (my-project)                               │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ 🔧 refactor-module                                  │    │
│ │    Module Refactoring                               │    │
│ │    Refactor a module with tests                     │    │
│ │    4 steps • 1 input                     [Use →]   │    │
│ └─────────────────────────────────────────────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 4.6 Create Run Modal

**Purpose:** Configure and start a new run.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│ Create Run                                            [×]   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Routine: planning (Feature Planning)                        │
│ Version: a1b2c3d (committed)                               │
│                                                             │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│ Project                                                     │
│ [my-project                                           ▾]   │
│                                                             │
│ Configuration                                               │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ feature_name *                                      │    │
│ │ [user-authentication                            ]   │    │
│ │ Name of the feature to plan                         │    │
│ └─────────────────────────────────────────────────────┘    │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ target_branch                                       │    │
│ │ [main                                           ]   │    │
│ │ Default: main                                       │    │
│ └─────────────────────────────────────────────────────┘    │
│                                                             │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│ Agent                                                       │
│ ○ OpenHands (Sandboxed)              ✓ Available           │
│ ○ Claude CLI                         ✓ Available           │
│ ○ External Agent (MCP)               ✓ Available           │
│ ○ Codex CLI                          ✗ Not found           │
│                                                             │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│ Options                                                     │
│ ☑ Create worktree                                          │
│ ☐ Delete worktree on completion                            │
│                                                             │
│                              [Cancel]  [Create & Start]    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 4.7 Agent Selection Panel

**Purpose:** Choose which agent to use.

**Shows:** Detected available agents with status.

**Agent Option Card:**
```
┌─────────────────────────────────────────┐
│ ○ OpenHands (Sandboxed)                 │
│   ✓ Available                           │
│   Containerized execution, best for     │
│   isolation and security                │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ ○ Claude CLI                            │
│   ✓ Available                           │
│   Subprocess execution, uses local      │
│   Claude installation                   │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ ○ Codex CLI                             │
│   ✗ Not found                           │
│   Install: npm install -g @openai/codex │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ ○ External Agent (MCP)                  │
│   ✓ Always available                    │
│   Connect any MCP-compatible agent      │
│   (Cursor, custom tools, etc.)          │
└─────────────────────────────────────────┘
```

---

## 5. Information Display Guidelines

### Status Indicators

| Status | Icon | Color | Animation |
|--------|------|-------|-----------|
| Draft | ○ | Gray | None |
| Queued | ◐ | Blue | None |
| Active | ● | Green | Pulse |
| Paused | ❚❚ | Yellow | None |
| Completed | ✓ | Green | None |
| Failed | ✗ | Red | None |

### Priority Indicators

| Priority | Display | Meaning |
|----------|---------|---------|
| Critical | 🔴 or bold | Must pass |
| Expected | 🟡 or normal | Should pass |
| Nice | 🟢 or muted | Optional |

### Grade Display

| Grade | Color | Meaning |
|-------|-------|---------|
| A | Green | Excellent |
| B | Light Green | Good |
| C | Yellow | Acceptable |
| D | Orange | Poor |
| F | Red | Failed |

### Token/Cost Display

Always show:
- Read tokens (input)
- Write tokens (output)
- Duration

Optionally show:
- Cache tokens (if available)
- Cost estimate with info tooltip

```
Tokens: 45,234 read / 12,456 write / 8,901 cache
Duration: 12m 34s
Est. Cost: $1.23 ⓘ
           └─ "Estimate only. Hidden costs may exist for some providers."
```

---

## 6. Interaction Patterns

### Expandable Rows

Runs in dashboard should be expandable to show step timeline without navigating away.

```
Click row → Expand to show steps
Click step → Navigate to run detail with step focused
Click task → Open task detail panel
```

### Real-time Updates

- Active runs should show live updates
- Use subtle pulse animation for active items
- Update token counts in real-time
- Show elapsed time as live counter

### Confirmation Dialogs

Require confirmation for:
- Cancel run
- Delete run
- Skip task

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `n` | New run |
| `r` | Refresh |
| `Esc` | Close panel/modal |
| `↑↓` | Navigate list |
| `Enter` | Expand/select |

---

## 7. Responsive Behavior

### Desktop (>1024px)
- Full sidebar navigation
- Task panel as slide-over
- Multi-column layouts

### Tablet (768-1024px)
- Collapsible sidebar
- Full-width cards
- Modal for task detail

### Mobile (<768px)
- Bottom navigation
- Single column
- Full-screen modals

---

## 8. Empty States

### No Runs
```
┌─────────────────────────────────────────┐
│                                         │
│           No runs yet                   │
│                                         │
│   Start by creating a run from a        │
│   routine in the library.               │
│                                         │
│        [Browse Routines]                │
│                                         │
└─────────────────────────────────────────┘
```

### No Routines
```
┌─────────────────────────────────────────┐
│                                         │
│        No routines found                │
│                                         │
│   Add routines to:                      │
│   ~/.orchestrator/routines/             │
│   or your project's routines/ folder    │
│                                         │
│   [View Documentation]                  │
│                                         │
└─────────────────────────────────────────┘
```

### Waiting for Agent
```
┌─────────────────────────────────────────┐
│                                         │
│     ⏳ Waiting for agent...             │
│                                         │
│   Copy the prompt and start your        │
│   external agent.                       │
│                                         │
│   [View Prompt]                         │
│                                         │
└─────────────────────────────────────────┘
```

---

## 9. Error States

### Agent Connection Timeout
```
┌─────────────────────────────────────────┐
│ ⚠️ Agent did not connect                │
│                                         │
│ The external agent didn't connect       │
│ within the timeout period.              │
│                                         │
│ [Try Again] [Change Agent] [Cancel Run] │
└─────────────────────────────────────────┘
```

### Task Failed
```
┌─────────────────────────────────────────┐
│ ❌ Task failed after 3 attempts         │
│                                         │
│ The task could not be completed.        │
│ Review the attempt history for details. │
│                                         │
│ [View Details] [Retry] [Skip]           │
└─────────────────────────────────────────┘
```

### Routine Not Committed
```
┌─────────────────────────────────────────┐
│ ⚠️ Routine has uncommitted changes      │
│                                         │
│ The routine "planning" has changes      │
│ that aren't committed to git.           │
│                                         │
│ Continuing will use the working copy.   │
│                                         │
│ [Continue Anyway] [Cancel]              │
└─────────────────────────────────────────┘
```
