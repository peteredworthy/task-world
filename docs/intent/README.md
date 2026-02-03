# Orchestrator Documentation Package

Documentation for implementing the Orchestrator system from scratch.

---

## Key Design Decisions

| Decision | Choice |
|----------|--------|
| Template concept | **Routine** (git-versioned) |
| Execution concept | **Run** |
| Agent selection | **User chooses** (no auto-select) |
| Context handling | **Fresh per phase** |
| YAML schema | **Simplified** (no ref/use) |
| State locking | **Pessimistic** |
| Recovery | **Event sourcing** |
| Metrics | **Token counts + cost estimate** |

---

## Document Index

| Doc | Description |
|-----|-------------|
| [01-ARCHITECTURE.md](./01-ARCHITECTURE.md) | System design, components, data model |
| [02-OPEN-QUESTIONS.md](./02-OPEN-QUESTIONS.md) | **All decisions closed** |
| [03-PRD.md](./03-PRD.md) | Requirements reflecting decisions |
| [04-CLAUDE-MD.md](./04-CLAUDE-MD.md) | Implementation guide for Claude Code |
| [05-IMPLEMENTATION-PLAN.md](./05-IMPLEMENTATION-PLAN.md) | Phased build order |
| [06-EXAMPLE-CONFIGS.md](./06-EXAMPLE-CONFIGS.md) | Simplified YAML examples |
| [07-UI-MOCKUP.html](./07-UI-MOCKUP.html) | React component mockup |
| [08-UI-DESCRIPTION.md](./08-UI-DESCRIPTION.md) | UI spec for Stitch |
| [09-COMPETITIVE-ANALYSIS.md](./09-COMPETITIVE-ANALYSIS.md) | Market comparison |

### Implementation Slices

| Doc | Description |
|-----|-------------|
| [10-SLICES-OVERVIEW.md](./10-SLICES-OVERVIEW.md) | **Start here** - Principles, testing, architecture |
| [11-SLICES-PHASE-1.md](./11-SLICES-PHASE-1.md) | Phase 1: Foundation (config, loading, state) |
| [12-SLICES-PHASE-2.md](./12-SLICES-PHASE-2.md) | Phase 2: Workflow Engine (gates, grades, transitions) |
| [13-SLICES-PHASE-3.md](./13-SLICES-PHASE-3.md) | Phase 3: Persistence (database, repositories) |
| [14-SLICES-PHASE-4.md](./14-SLICES-PHASE-4.md) | Phase 4: API Server (REST, WebSocket) |
| [15-SLICES-PHASE-5.md](./15-SLICES-PHASE-5.md) | Phase 5: Agent Integration (OpenHands, CLI, MCP) |
| [16-SLICES-PHASE-6.md](./16-SLICES-PHASE-6.md) | Phase 6: Web UI (React dashboard) |
| [17-SLICES-PHASE-7.md](./17-SLICES-PHASE-7.md) | Phase 7: Git Integration (worktrees, versioning) |
| [18-SLICES-PHASE-8.md](./18-SLICES-PHASE-8.md) | Phase 8: CLI & Polish (commands, E2E tests) |

---

## Core Concepts

### Routine/Run Model

```
Routine (git-versioned template)
├── Must be committed before use
├── SHA recorded for versioning
└── Stored: local, project, or allowlisted external

Run (execution instance)
├── References routine (or embeds one-shot)
├── User selects agent
├── Worktree per run (default)
└── Completion action (MR, merge, cleanup)
```

### Agent Selection

No auto-selection. System detects available options:
- OpenHands Local (if `openhands-ai` SDK importable — runs in-process)
- OpenHands Docker (if Docker daemon running + `openhands-workspace` importable — ephemeral containers)
- CLI tools (claude, codex)
- External MCP (always available)

User explicitly chooses.

### Fresh Context Per Phase

```
Builder (context A) → Verifier (context B) → Revision (context C)
```

Each phase gets a fresh prompt. No context carryover.

---

## Build Order

Per decision 8.1 - incremental with full testing:

1. **Config & Models** - Simplified schema
2. **State Machine** - Locking, gates, events
3. **Agents** - Detection, OpenHands, CLI+nudger, MCP
4. **API** - REST, WebSocket (throttled)
5. **UI** - Dashboard, agent guidance
6. **Git** - Worktrees, completion actions
7. **CLI** - Commands
8. **Polish** - Recovery, docs

---

## Quick Start

```bash
# Create project
mkdir orchestrator && cd orchestrator
uv init --name orchestrator --package

# Copy CLAUDE.md
cp docs/04-CLAUDE-MD.md CLAUDE.md

# Follow Phase 1 in Implementation Plan
```

---

## New Questions (Requiring Decision)

From `02-OPEN-QUESTIONS.md`:

| # | Question |
|---|----------|
| NQ-1 | Git enforcement level for routines |
| NQ-2 | Auto-verify sandboxing scope |
| NQ-3 | CLI nudge parameters |
| NQ-4 | Completion action set |
| NQ-5 | Model override structure |

---

## Architecture Highlights

```
User → Select Agent → Start Run
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
    OpenHands       CLI + Nudger    External MCP
    (sandbox)       (subprocess)    (guidance UI)
         │               │               │
         └───────────────┴───────────────┘
                         │
                    Worktree
                         │
               ┌─────────┴─────────┐
               ▼                   ▼
           Builder            Verifier
        (fresh ctx)         (fresh ctx)
               │                   │
               └───────┬───────────┘
                       ▼
              Completion Action
           (MR, merge, cleanup)
```

---

*Updated with all design decisions incorporated*
