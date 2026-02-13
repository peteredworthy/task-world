# Orchestrator

A workflow management system that coordinates LLM-powered coding agents through structured, multi-step software development tasks. Supports multiple agent backends (OpenHands, CLI subprocess agents, MCP-connected agents) and provides a web UI for monitoring, debugging, and intervention.

## Quick Start

**Backend:**
```bash
uv sync
cp .env.example .env          # configure API keys
uv run orchestrator serve --reload   # http://localhost:8000
```

**Frontend:**
```bash
cd ui
npm install
npm run dev                    # http://localhost:5173
```

## How It Works

**Routines** are git-versioned YAML templates that define multi-step workflows. A **Run** executes a routine against a project in its own git worktree. Each **Task** goes through a builder/verifier cycle with fresh LLM context per phase, checklist gates, and grade-based pass/fail evaluation.

```
Routine → Run → Step → Task → Builder → Gates → Verifier → Pass/Retry
```

## Documentation

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full directory map, API routes, CLI commands, and technology stack.

See [AGENTS.md](AGENTS.md) for coding agent guidance, design constraints, and implementation details.
