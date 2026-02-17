# The Backbone

This is the journey map for Orchestrator. It traces the path from "I have a routine and a repo" to "the code is merged and done," marking every major system capability along the way.

Read this first. Then pick a story.

---

## The Timeline

### 1. Discovery

Before anything runs, the user needs to know what's available.

| Capability | What happens | Key paths |
|---|---|---|
| **List routines** | Browse available workflow templates. Routines live in git repos and are versioned by commit SHA. | `GET /api/routines` |
| **Inspect a routine** | See steps, tasks, requirements, gates, auto-verify commands. Understand what the workflow will do before committing to it. | `GET /api/routines/{id}` |
| **Detect agents** | Find out which agent backends are available on this machine. OpenHands installed? Docker running? Claude CLI on PATH? | `GET /api/agents`, CLI `agents detect` |
| **Browse repos** | See which repositories are registered and their branch state. | `GET /api/repos` |

### 2. Creation

The user commits to a specific routine + repo + branch combination.

| Capability | What happens | Key paths |
|---|---|---|
| **Create a run** | Routine is resolved (git SHA pinned), config variables interpolated, run enters DRAFT. Nothing has touched the filesystem yet. | `POST /api/runs` |
| **Configure** | Set agent type, environment files, merge strategy, custom config variables. All optional, all changeable while in DRAFT. | Run creation payload |
| **Validate** | Routine YAML is validated against schema. Config values checked for length, control characters, prompt injection patterns. | `POST /api/routines/validate` |

### 3. Activation

The run leaves the planning phase and enters the real world.

| Capability | What happens | Key paths |
|---|---|---|
| **Start a run** | Git worktree created at `worktrees/run-<id>/`. New branch `orchestrator/run-<id>` cut from source. First task enters PENDING. Run status: ACTIVE. | `POST /api/runs/{id}/start` |
| **Worktree isolation** | All agent work happens in the worktree, not the main checkout. Multiple runs can execute concurrently against the same repo without conflicts. | `git/worktree.py` |
| **Agent spawning** | The selected agent backend starts: subprocess for CLI agents, in-process for OpenHands Local, container for OpenHands Docker, or nothing for user-managed (agent polls). | `agents/executor.py` |

### 4. Building

The agent does the actual work.

| Capability | What happens | Key paths |
|---|---|---|
| **Fresh context** | Agent receives a builder prompt with task requirements, checklist items, and step context. No memory of previous attempts. | `workflow/prompts.py` |
| **Checklist updates** | Agent marks requirements as DONE, NOT_APPLICABLE, or BLOCKED. Each update is an event. | `PATCH .../checklist/{req}` |
| **Git commits** | Agent makes commits in the worktree branch. Start and end commits are tracked per attempt. | Worktree git operations |
| **Clarification requests** | Agent can ask the human a question. Task pauses (PENDING_USER_ACTION), human responds, agent resumes with the answer. | `POST .../clarifications` |
| **Submission** | Agent declares "I'm done building." Checklist gate evaluates: all CRITICAL items must be DONE. If gate fails, agent is told what's missing. | `POST .../submit` |

### 5. Verification

A fresh phase that evaluates the builder's work.

| Capability | What happens | Key paths |
|---|---|---|
| **Verifier prompt** | Agent gets a new prompt (no builder context) with the requirements, a grade scale, and instructions to evaluate. | `workflow/prompts.py` |
| **Auto-verify** | Shell commands run in the worktree (tests, linters, type checks). Must-pass items that fail send the task back to BUILDING with feedback. | `workflow/auto_verify.py` |
| **Grading** | Agent assigns a grade (PASS, NEEDS_REVISION, FAIL, etc.) and reason to each requirement. | `PUT .../checklist/{req}/grade` |
| **Grade threshold** | Average grade must meet the configured threshold. If not, task goes back to BUILDING (new attempt, fresh context, feedback from verifier). | `workflow/grades.py` |
| **Attempt tracking** | Each builder/verifier cycle is an attempt. Tokens, duration, and commit ranges recorded. Max attempts enforced. | `state/models.py` Attempt |

### 6. Human Intervention

The points where humans get involved (by choice or necessity).

| Capability | What happens | Key paths |
|---|---|---|
| **Step approval gates** | Some steps require human sign-off before proceeding. Run pauses, human reviews, approves or rejects. | `POST .../steps/{id}/approve` |
| **Task approval** | Human can approve or reject individual task results. Rejection sends it back to BUILDING. | `POST .../tasks/{id}/approve` |
| **Clarification responses** | Human answers agent's questions. Agent resumes with the answer injected into context. | `POST .../clarifications/{id}/respond` |
| **Pause / resume** | Human can pause an active run (agent finishes current action, then stops) and resume later, optionally with a different agent. | `POST .../pause`, `POST .../resume` |
| **Cancel** | Kill the run. Agent is cancelled, run enters FAILED. | `POST .../cancel` |

### 7. Completion

The run finishes and its work re-enters the main codebase.

| Capability | What happens | Key paths |
|---|---|---|
| **Run completion** | All steps done. Run status → COMPLETED. | Automatic on last task completion |
| **Merge-back** | Run branch merged into source branch. Strategy: SQUASH (clean single commit) or MERGE (preserve history). | `POST .../merge-back` |
| **Back-merge** | Pull source branch changes into the run branch mid-flight. Useful for long-running runs against active repos. | `POST .../back-merge` |
| **Branch status** | Check how far ahead/behind the run branch is relative to source. | `GET .../branch-status` |

### 8. Monitoring (Throughout)

These capabilities are available at any point during execution.

| Capability | What happens | Key paths |
|---|---|---|
| **Activity log** | Every state transition, checklist update, grade, clarification, and error is an event. Paginated query or SSE stream. | `GET .../activity`, `GET .../activity/stream` |
| **WebSocket** | Real-time push of events to connected frontends. Per-run subscriptions. | `ws://` via ConnectionManager |
| **Guidance** | External agents poll for their current prompt and expected actions. | `GET .../guidance` |
| **Cost tracking** | Tokens used and estimated cost per attempt, per task, per run. | Attempt metrics |
| **Run listing** | Filter runs by status, repo, routine. See what's active, what's stuck, what's done. | `GET /api/runs` |

---

## Coverage Map

Stories written so far and what they cover. **Bold** = primary coverage, *italic* = incidental.

| Capability | Story 01 | Story 02 | Story 03 | Story 04 |
|---|---|---|---|---|
| List routines | **yes** | | | |
| Inspect routine | **yes** | | | |
| Detect agents | **yes** | | | |
| Create run | **yes** | | | |
| Start run | **yes** | | | |
| Worktree isolation | *yes* | | | |
| Fresh context | *yes* | | | |
| Checklist updates | **yes** | | | |
| Submission | **yes** | | | |
| Auto-verify | | **yes** | | |
| Grading | | **yes** | | |
| Grade threshold | | **yes** | | |
| Attempt tracking | | **yes** | | |
| Revision loop | | **yes** | | |
| Clarification requests | | | **yes** | |
| Clarification responses | | | **yes** | |
| Step approval gates | | | **yes** | |
| Task approval | | | *yes* | |
| Pause / resume | | | | **yes** |
| Cancel | | | | *yes* |
| Merge-back | | | | **yes** |
| Back-merge | | | | **yes** |
| Branch status | | | | **yes** |
| Activity log | *yes* | | | *yes* |
| WebSocket | | | | *yes* |
| Guidance endpoint | | | | |
| Cost tracking | | *yes* | | |
| Run listing | | | | *yes* |
| Browse repos | | | | |
| Validate routine | | | | |
| Env file management | | | | |
| MCP tools | | | | |
| CLI commands | | | | |
| Conditional transitions | | | | |
| Run deletion | | | | |

Gaps to fill in future stories: guidance endpoint, MCP integration, CLI workflows, env file management, conditional step transitions, routine validation, repo browsing.
