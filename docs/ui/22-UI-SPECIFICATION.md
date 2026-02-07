# Orchestrator UI Specification

A comprehensive specification for building the Orchestrator UI. This document is designed to be consumed by LLMs building the React-based frontend.

**Reference Screenshots:** See `ui-assets/` folder for visual references:
- `01-run-detail-view.png` - Active run with inspector panel
- `02-dashboard-expanded.png` - Dashboard with expanded run showing step columns
- `03-routine-library.png` - Routine library browser
- `04-configure-new-run.png` - New run configuration modal

---

## 1. Design System

### 1.1 Color Palette

**Background Colors:**
- Primary background: `#0d0f14` (near black)
- Card background: `#151921` (dark slate)
- Elevated surface: `#1c212b` (slightly lighter)
- Hover state: `#252b38`

**Status Colors:**
- Active/Running: `#22c55e` (green) with subtle glow
- Paused: `#eab308` (amber)
- Completed/Success: `#22c55e` (green)
- Failed: `#ef4444` (red)
- Pending: `#6b7280` (gray)

**Grade Colors:**
- Grade A: `#22c55e` (green)
- Grade B: `#3b82f6` (blue)
- Grade C: `#eab308` (amber)
- Grade D: `#f97316` (orange)
- Grade F: `#ef4444` (red)

**Text Colors:**
- Primary text: `#f8fafc` (near white)
- Secondary text: `#94a3b8` (slate gray)
- Muted text: `#64748b` (darker gray)
- Link/accent: `#8b5cf6` (purple)

**Accent Colors:**
- Primary accent: `#8b5cf6` (purple)
- Secondary accent: `#06b6d4` (cyan)

### 1.2 Typography

- Font family: `Inter`, `system-ui`, sans-serif
- Headings: Semi-bold (600)
- Body: Regular (400)
- Monospace (IDs, code): `JetBrains Mono`, monospace

**Scale:**
- Page title: 24px
- Section header: 18px
- Card title: 16px
- Body text: 14px
- Small/meta: 12px
- Tiny (badges): 11px

### 1.3 Spacing & Layout

- Base unit: 4px
- Standard padding: 16px (cards), 24px (sections)
- Card border radius: 8px
- Badge border radius: 4px
- Standard gap: 12px

### 1.4 Component Patterns

**Cards:**
```css
.card {
  background: #151921;
  border: 1px solid #252b38;
  border-radius: 8px;
  padding: 16px;
}
```

**Status Badges:**
```css
.badge {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}
.badge-active { background: #22c55e20; color: #22c55e; }
.badge-paused { background: #eab30820; color: #eab308; }
.badge-failed { background: #ef444420; color: #ef4444; }
```

**Grade Badges:**
- Fixed width: 40px
- Height: 32px
- Border radius: 6px
- Font size: 14px, bold
- Centered text

---

## 2. Dashboard View

### 2.1 Layout Structure

```
┌─────────────────────────────────────────────────────────────────┐
│ HEADER                                                          │
│ [Logo] Orchestrator    [Search bar]           🔔  [+ New Run]   │
├─────────────────────────────────────────────────────────────────┤
│ FILTERS                                                         │
│ [Status: All ▾] [Project: All ▾] [Sort: Recency ▾]   Running: 3 │
├─────────────────────────────────────────────────────────────────┤
│ RUN LIST                                                        │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ [Expanded Run Card - see 2.3]                               │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ [Collapsed Run Card - see 2.2]                              │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ [Collapsed Run Card]                                        │ │
│ └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Collapsed Run Row

A single-line summary of a run with step progress indicators.

```
┌─────────────────────────────────────────────────────────────────┐
│ ✓  Docs: Update Readme                                          │
│    ID: #8390-B • Routine: Doc-Updater • Project: Core-API       │
│                                                    [S1][S2][S3] ⏱ 45s ✓✓ │
└─────────────────────────────────────────────────────────────────┘
```

**Components:**
1. **Status Icon** (left): Checkmark (✓) for completed, colored dot (●) for active, pause icon for paused
2. **Run Name**: Bold, primary text
3. **Status Badge**: `ACTIVE`, `PAUSED`, `COMPLETED` etc.
4. **Meta Line**: ID, Routine name, Project name (secondary text)
5. **Step Indicators** (right-aligned):
   - Small square badges: `S1`, `S2`, `S3`, etc.
   - Completed steps: Filled with accent color
   - Active step: Filled with green, subtle pulse animation
   - Pending steps: Gray/muted, no fill
   - **CRITICAL**: All step badges must be same size and vertically aligned
6. **Duration**: Clock icon + time
7. **Quick Actions**: Resume button (if paused), double-checkmark (if completed)

### 2.3 Expanded Run Card

When a run is clicked/expanded, show the full step-by-step breakdown with tasks and grades.

```
┌─────────────────────────────────────────────────────────────────┐
│ ● Feat: User Auth Implementation  [ACTIVE]      Started 2m 30s  │
│   ID: #8392-A • Routine: Scaffold-Agent-v4 • Project: Core-API  │
│                                              ● Generating Code... │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  INIT          PLAN           ● CODE GEN        REVIEW          │
│  ━━━━━━ S1    ━━━━━━ S2      ━━━━━━ S3        ┄┄┄┄┄┄ S4        │
│  ┌────────┐   ┌────────┐     ┌────────────┐   ┌────────────┐   │
│  │Context │   │Architec│     │Draft Impl  │   │            │   │
│  │Loading │   │ture    │     │            │   │  Pending   │   │
│  │        │   │        │     │[F ][D ][-]│   │            │   │
│  │[A ][A ]│   │[A][B][B]│     │[F ][D ][-]│   │            │   │
│  └────────┘   └────────┘     │            │   └────────────┘   │
│                              │ Retrying...│                     │
│                              └────────────┘                     │
│                                                                 │
│  👁 View Logs                                    [⊘ ABORT RUN]  │
└─────────────────────────────────────────────────────────────────┘
```

**Step Columns:**
- Each step is a vertical column
- Header: Step name + step badge (S1, S2, etc.)
- Progress bar under header: Solid for complete, dotted for pending
- Active step has green dot indicator in header

**Task Cards within Steps:**
- Card shows task name
- Below name: Grade badges in a row
- Multiple attempts stack vertically within the same card (no arrows between retries)

**Grade Badge Layout (Three-Tier System):**
```
┌─────────────────────────┐
│ [Required][Expected][Optional] │
└─────────────────────────┘
```
- **Left position**: Required/Critical grades
- **Center position**: Expected grades  
- **Right position**: Optional/Nice grades
- Empty category shows `-` placeholder
- Grades are letter grades: A, B, C, D, F
- Each badge is colored according to grade

**Retry Attempts:**
- Stack vertically within the task card
- NO arrows between retry attempts
- Each retry row shows its own grade badges
- Active retry shows "Building..." or "Retrying..." text instead of grades
- The retry is visually part of the same task (not a new box)

```
┌─────────────────────┐
│ Draft Implementation│
│                     │
│ [F ][D ][ - ]      │  ← Attempt 1 grades
│ [F ][D ][ - ]      │  ← Attempt 2 grades  
│ Retrying...        │  ← Attempt 3 in progress
└─────────────────────┘
```

**Pending Steps:**
- Dashed border
- "Pending" text centered
- Muted/gray appearance

### 2.4 Filters Bar

```
[Status: All ▾] [Project: Core-API ▾] [Sort: Recency ▾]    Running: 3 / Total: 128
```

- Dropdown filters with dark styling
- Running count highlighted in accent color
- Filters apply immediately (no submit button)

---

## 3. Run Detail View

Full-page view when drilling into a specific run.

### 3.1 Layout Structure

```
┌─────────────────────────────────────────────────────────────────┐
│ ← Runs / implement-auth                                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ implement-auth  ● RUNNING                    [II Pause Run]     │
│ ID: #8821 • Started 2 mins ago                                  │
│                                                                 │
├──────────────────┬──────────────────┬──────────────────────────┤
│ TOKENS (R/W)     │ DURATION         │ EST. COST                │
│ 14,204 / 2,105   │ 00:48s           │ $0.042                   │
├──────────────────┴──────────────────┴──────────────────────────┤
│                                                                 │
│ ⊞ Execution Plan                            [Auto-scroll: ON]  │
│                                                                 │
│ ┌────────────────────────┐  ┌────────────────────────────────┐ │
│ │ CONTEXT LOADING    S1  │  │ ARCHITECTURE PHASE         S2  │ │
│ │ ━━━━━━━━━━━━━━━━━━━━━ │  │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │ │
│ │ ┌──────────────────┐   │  │ ┌──────────────────────────┐   │ │
│ │ │ T-00             │   │  │ │ T-01                     │   │ │
│ │ │ Load System  ✓   │   │  │ │ Write Design Doc         │   │ │
│ │ │ Context          │   │  │ │ [F ][D ]                 │   │ │
│ │ │                  │   │  │ │         ↓                │   │ │
│ │ │ [A ][A ]         │   │  │ │ ┌────────────────────┐   │   │ │
│ │ └──────────────────┘   │  │ │ │ Retry Attempt      │   │   │ │
│ └────────────────────────┘  │ │ │ [C ][B ]           │   │   │ │
│                              │ │ └────────────────────┘   │   │ │
│                              │ │         ↓                │   │ │
│                              │ └──────────────────────────┘   │ │
│                              └────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Metrics Bar

Three metric cards in a row:

```
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ ⚡ TOKENS (R/W)   │ │ ⏱ DURATION       │ │ $ EST. COST      │
│ 14,204 / 2,105   │ │ 00:48s           │ │ $0.042           │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

- Icon + label on top
- Large value below
- Token count shows read/write separated by `/`

### 3.3 Execution Plan

Horizontal layout of step columns (same as expanded dashboard view but with more detail).

**Step Header:**
```
CONTEXT LOADING                                               S1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
- Step name in caps
- Step badge (S1, S2) right-aligned
- Solid progress bar below (or dashed if pending)

**Task Cards:**
- Show task ID (T-00, T-01)
- Task title
- Checkmark if completed
- Grade badges at bottom
- Orange/red left border for tasks with failures

### 3.4 Inspector Panel (Right Sidebar)

Slides in from right when a task is selected.

```
┌─────────────────────────────────────┐
│ ⊟ Inspector                    □ ✕  │
├─────────────────────────────────────┤
│ ☑ SELECTED TASK                     │
│ ┌─────────────────────────────────┐ │
│ │ T-01                      v2.0  │ │
│ │ Write Design Doc for Auth Module│ │
│ └─────────────────────────────────┘ │
│                                     │
│ ⏱ ATTEMPT HISTORY                   │
│ ┌─────────────────────────────────┐ │
│ │ ⊘ Attempt #1           FAILED   │ │
│ │   Self-correction triggered:    │ │
│ │   Missing context for JWT...    │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ ⟳ Attempt #2           RUNNING  │ │
│ │   Generating markdown structure │ │
│ │   based on updated prompts.     │ │
│ └─────────────────────────────────┘ │
│                                     │
│ ★ VERIFIER GRADES (LATEST)          │
│ ┌────────────────┬────────────────┐ │
│ │    SYNTAX      │     LOGIC      │ │
│ │      A+        │      B-        │ │
│ ├────────────────┼────────────────┤ │
│ │   SECURITY     │     PERF       │ │
│ │       -        │       -        │ │
│ └────────────────┴────────────────┘ │
│                                     │
│ 📋 TAIL LOGS                        │
│ ┌─────────────────────────────────┐ │
│ │ [log preview area]              │ │
│ └─────────────────────────────────┘ │
│                                     │
│ ┌─────────────────────────────────┐ │
│ │      ⚙ Debug This Step          │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

**Sections:**
1. **Selected Task**: ID, version, full title
2. **Attempt History**: Timeline of attempts with status and summary
3. **Verifier Grades**: Grid of rubric categories with grades
4. **Tail Logs**: Recent log output preview
5. **Debug Action**: Button to open debugging tools

---

## 4. Routine Library View

### 4.1 Layout Structure

```
┌─────────────────────────────────────────────────────────────────┐
│ SIDEBAR          │ MAIN CONTENT                                 │
│ ┌─────────────┐  │                                              │
│ │ Orchestrator│  │ Home / Routine Library                       │
│ │ Mission Ctrl│  │                                              │
│ │             │  │ Routine Library                              │
│ │ ▣ Dashboard │  │ Browse and manage your automation workflow   │
│ │ 🤖 Agents   │  │ templates. Deploy trusted routines to your   │
│ │ 📋 Routine  │  │ agents instantly.        [+ New Template]    │
│ │    Library  │  │                                              │
│ │ ⏱ History   │  │ [Search templates...]      [All][Local][...] │
│ │             │  │                                              │
│ │             │  │ 📁 Local Routines         ~/user/routines    │
│ │             │  │ ┌─────────────┐ ┌─────────────┐ ┌─────────┐ │
│ │             │  │ │ Planning    │ │ Bug-fix     │ │   +     │ │
│ │             │  │ │ v1.2        │ │ v2.0        │ │ Create  │ │
│ │             │  │ │ ...descr... │ │ ...descr... │ │ Local   │ │
│ │             │  │ │ 5 Steps     │ │ 3 Steps     │ │ Routine │ │
│ │ ⚙ Settings  │  │ │ [Use →]     │ │ [Use →]     │ │         │ │
│ │ 👤 DevUser  │  │ └─────────────┘ └─────────────┘ └─────────┘ │
│ └─────────────┘  │                                              │
│                  │ 🔧 Project Routines    ./.orchestrator/...   │
│                  │ ┌─────────────┐ ┌─────────────┐              │
│                  │ │ Refactor    │ │ Doc-gen     │              │
│                  │ │ beta        │ │ v1.0        │              │
│                  │ │ ...descr... │ │ ...descr... │              │
│                  │ │ 8 Steps     │ │ 4 Steps     │              │
│                  │ │ [Use →]     │ │ [Use →]     │              │
│                  │ └─────────────┘ └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Sidebar Navigation

- Logo + tagline at top
- Navigation items with icons
- Active item highlighted with accent background
- Settings and user profile at bottom

### 4.3 Routine Cards

```
┌─────────────────────────────────────┐
│ 🏗 Planning                    v1.2 │
│                                     │
│ Generates a comprehensive step-by-  │
│ step implementation plan for a      │
│ given feature request or            │
│ architectural change.               │
│                                     │
│ ≡ 5 Steps    📥 2 Inputs            │
│                                     │
│ ┌─────────────────────────────────┐ │
│ │         Use Routine  →          │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

**Components:**
- Icon (varies by routine type)
- Routine name (bold)
- Version badge (top right)
- Description (2-3 lines, secondary text)
- Metadata: step count, input count
- Action button: "Use Routine →"

### 4.4 Source Filters

Tab-style filters: `[All] [Local] [Project] [External]`

Section headers show source path (e.g., `~/user/routines`)

---

## 5. Configure New Run Modal

### 5.1 Layout Structure

```
┌─────────────────────────────────────────────────────────────────┐
│ Configure New Agent Run                                      ✕  │
│ Setup parameters for your next autonomous coding session.       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ 📁 Target Project                                               │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Select repository or project...                          📂 │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ⚙ Configuration                                                 │
│ ┌──────────────────────────┐ ┌──────────────────────────────┐  │
│ │ Feature Name             │ │ Target Branch                │  │
│ │ [e.g. auth-refactor-v2 ] │ │ [🌿 main                   ] │  │
│ └──────────────────────────┘ └──────────────────────────────┘  │
│                                                                 │
│ 🤖 Select Agent                                                 │
│ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐    │
│ │ 🖐 OpenHands    │ │ 🟧 Claude CLI   │ │ 🟪 External     │    │
│ │ ● Available     │ │ ● Available     │ │ ○ Not Found     │    │
│ └─────────────────┘ └─────────────────┘ └─────────────────┘    │
│                                                                 │
│                                                                 │
│                           [Cancel]  [🚀 Create & Start]         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Form Fields

**Target Project:**
- Dropdown/search combo
- Shows folder icon
- Placeholder: "Select repository or project..."

**Configuration:**
- Dynamic fields based on routine inputs
- Text inputs with placeholder examples
- Branch selector with branch icon

### 5.3 Agent Selection

Cards for each detected agent:

```
┌─────────────────────────┐
│ 🖐 OpenHands            │  ← Selected state: purple border
│ ● Available             │  ← Green dot = available
└─────────────────────────┘

┌─────────────────────────┐
│ 🟪 External Agent       │
│ ○ Not Found             │  ← Red dot = unavailable
└─────────────────────────┘
```

- Selected agent has accent border
- Availability indicator (green dot = available, red = not found)
- Unavailable agents are visually muted but still shown

### 5.4 Actions

- Cancel: Secondary button style
- Create & Start: Primary button with rocket icon

---

## 6. Agent Guidance Panel

Shown when using external/MCP agents.

```
┌─────────────────────────────────────────────────────────────────┐
│ Agent Guidance                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Start your agent with this prompt:                              │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ # Task: Write Design Document                               │ │
│ │                                                             │ │
│ │ ## Context                                                  │ │
│ │ Create a design document for user-authentication...         │ │
│ │                                                             │ │
│ │ ## Requirements                                             │ │
│ │ - Create design.md (critical)                               │ │
│ │ - Include architecture diagram (expected)                   │ │
│ │ - Document API endpoints (critical)                         │ │
│ │                                                   [Copy 📋] │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ MCP Server: localhost:8080/mcp                       [Copy 📋]  │
│                                                                 │
│ Auth Token: eyJhbG...                                [Copy 📋]  │
│                                                                 │
│ ─────────────────────────────────────────────────────────────── │
│                                                                 │
│ The agent should:                                               │
│ • Connect to MCP server                                         │
│ • Work on the task in the worktree                              │
│ • Update checklist via orchestrator tools                       │
│ • Submit when complete                                          │
│                                                                 │
│ ─────────────────────────────────────────────────────────────── │
│                                                                 │
│ Status: ⏳ Waiting for connection                               │
│ Started 2m 34s ago • Timeout in 2m 26s                          │
│                                                                 │
│ ┌───────────────────────┐ ┌───────────────────────┐            │
│ │ I've Started Agent    │ │       Cancel          │            │
│ └───────────────────────┘ └───────────────────────┘            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Interaction Patterns

### 7.1 Run Row Expand/Collapse

- Click anywhere on collapsed row → Expand to show step columns
- Click header of expanded row → Collapse
- Expansion is animated (slide down)
- Only one run expanded at a time (accordion behavior)

### 7.2 Task Selection

- Click task card in execution plan → Open inspector panel
- Inspector slides in from right
- Click outside inspector or X → Close inspector

### 7.3 Real-time Updates

- Active runs pulse with subtle green glow
- Token counts update in real-time
- New attempts appear with slide-in animation
- Step progress updates without full refresh

### 7.4 Grade Badge Interactions

- Hover on grade badge → Show tooltip with full rubric text
- Click grade badge → Expand to show grade reason

---

## 8. Responsive Behavior

### Desktop (>1200px)
- Full sidebar navigation
- Side-by-side step columns
- Inspector as slide-over panel

### Tablet (768-1200px)
- Collapsible sidebar
- Step columns may wrap to 2 rows
- Inspector as modal

### Mobile (<768px)
- Bottom navigation
- Single-column step layout
- Full-screen modals for detail views

---

## 9. Empty States

### No Runs
```
┌─────────────────────────────────────┐
│                                     │
│        📋 No runs yet               │
│                                     │
│   Start by creating a run from a    │
│   routine in the library.           │
│                                     │
│        [Browse Routines]            │
│                                     │
└─────────────────────────────────────┘
```

### No Routines
```
┌─────────────────────────────────────┐
│                                     │
│      📁 No routines found           │
│                                     │
│   Add routines to:                  │
│   ~/.orchestrator/routines/         │
│   or your project's routines/       │
│                                     │
│      [View Documentation]           │
│                                     │
└─────────────────────────────────────┘
```

---

## 10. Error States

### Task Failed
```
┌─────────────────────────────────────┐
│ ❌ Task failed after 3 attempts     │
│                                     │
│ The task could not be completed.    │
│ Review the attempt history.         │
│                                     │
│ [View Details] [Retry] [Skip]       │
└─────────────────────────────────────┘
```

### Agent Timeout
```
┌─────────────────────────────────────┐
│ ⚠️ Agent did not connect            │
│                                     │
│ The external agent didn't connect   │
│ within the timeout period.          │
│                                     │
│ [Try Again] [Change Agent] [Cancel] │
└─────────────────────────────────────┘
```

### Routine Not Committed
```
┌─────────────────────────────────────┐
│ ⚠️ Routine has uncommitted changes  │
│                                     │
│ The routine "planning" has changes  │
│ that aren't committed to git.       │
│                                     │
│ Continuing will use working copy.   │
│                                     │
│ [Continue Anyway] [Cancel]          │
└─────────────────────────────────────┘
```

---

## 11. Key Implementation Notes

### 11.1 Grade Display System

**CRITICAL**: The grade display uses a three-tier layout:

```
[Required | Expected | Optional]
```

- Each category can have 0-N grades
- Empty categories show `-` placeholder
- At least one category must have grades
- Grades are colored by letter (A=green, B=blue, C=yellow, D=orange, F=red)

### 11.2 Retry Attempts

**CRITICAL**: Retries are NOT shown as separate steps with arrows.

Retries stack vertically within the same task card:
```
┌─────────────────────┐
│ Task Name           │
│ [F][D][-]          │  ← Attempt 1
│ [F][D][-]          │  ← Attempt 2
│ Retrying...        │  ← Attempt 3
└─────────────────────┘
```

### 11.3 Step Progress Indicators

In collapsed rows, step badges must be:
- Identically sized
- Vertically aligned across all rows
- Consistently positioned (right side of row)

### 11.4 Accessibility

- Minimum contrast ratio: 4.5:1 for text
- All interactive elements must be keyboard accessible
- Status conveyed through color AND icon/text
- Focus states clearly visible

---

## 12. Data Types Reference

```typescript
interface Run {
  id: string;
  name: string;
  status: 'draft' | 'queued' | 'active' | 'paused' | 'completed' | 'failed';
  routine_id: string;
  routine_name: string;
  project_id: string;
  project_name: string;
  agent_type: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  tokens_read: number;
  tokens_write: number;
  duration_ms: number;
  steps: Step[];
}

interface Step {
  id: string;
  title: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped';
  order: number;
  tasks: Task[];
}

interface Task {
  id: string;
  title: string;
  status: 'pending' | 'building' | 'verifying' | 'completed' | 'failed';
  current_attempt: number;
  max_attempts: number;
  attempts: Attempt[];
}

interface Attempt {
  id: string;
  attempt_num: number;
  status: 'building' | 'verifying' | 'passed' | 'revision_needed' | 'failed';
  grades: GradeSet;
  started_at: string;
  completed_at: string | null;
  tokens_read: number;
  tokens_write: number;
  duration_ms: number;
}

interface GradeSet {
  required: Grade[];
  expected: Grade[];
  optional: Grade[];
}

interface Grade {
  requirement_id: string;
  requirement_desc: string;
  grade: 'A' | 'B' | 'C' | 'D' | 'F';
  reason: string | null;
}

interface Routine {
  id: string;
  name: string;
  description: string;
  source: 'local' | 'project' | 'external';
  version: string;
  git_sha: string;
  inputs: RoutineInput[];
  steps: StepConfig[];
}

interface RoutineInput {
  name: string;
  required: boolean;
  default: string | null;
  description: string;
}
```

---

## Appendix: Screenshot Reference Index

| Screenshot | Description | Key Elements |
|------------|-------------|--------------|
| `01-run-detail-view.png` | Active run with inspector | Metrics bar, step columns, inspector panel |
| `02-dashboard-expanded.png` | Dashboard with expanded run | Collapsed rows, expanded step view, grade badges |
| `03-routine-library.png` | Routine browser | Sidebar nav, routine cards, source sections |
| `04-configure-new-run.png` | New run modal | Project selector, config fields, agent cards |
