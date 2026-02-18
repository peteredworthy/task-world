# Story 04: The Long-Running Run

*Jordan starts a big routine, pauses it overnight, resumes with a different agent, deals with upstream changes, and monitors the whole thing from the CLI.*

---

Jordan is the platform engineer. He prefers the CLI. Today he's running the `full-service-scaffold` routine -- a multi-step beast that generates a complete microservice from a template. It takes 20-30 minutes even with a fast agent.

### Kicking Off

```bash
$ orchestrator runs create full-service-scaffold --repo platform-services \
    --branch main --config '{"service_name": "billing", "port": 8042}'
Created run run-b2e1 (DRAFT)

$ orchestrator runs start run-b2e1 --agent claude_cli
Started run-b2e1 (ACTIVE)
```

Jordan watches the activity stream:

```bash
$ orchestrator runs watch run-b2e1
[16:40:12] Run run-b2e1: ACTIVE
[16:40:13] Task scaffold-structure: BUILDING
[16:40:28] Checklist R1 (Directory structure created): DONE
[16:40:45] Checklist R2 (Dockerfile exists): DONE
...
```

Two steps complete. The agent is working on step 3 (API routes). It's 5:30 PM. Jordan wants to go home.

### Pausing

```bash
$ orchestrator runs pause run-b2e1
Pausing run-b2e1... waiting for agent to finish current action
```

The pause doesn't kill the agent mid-thought. It waits for the current action to complete, then stops:

```
POST /api/runs/run-b2e1/pause
→ 200 { "status": "PAUSED" }
```

```
[17:32:15] Run run-b2e1: status → PAUSED
[17:32:15] Agent: stopped after completing current action
```

The worktree is intact. The branch has all commits from steps 1-2 and the partial work from step 3. The current task is frozen in BUILDING -- it'll pick up where it left off.

Jordan goes home.

### Morning: What Happened Overnight?

Jordan checks in the next morning. His teammates have been busy -- `main` has 4 new commits since he branched.

```bash
$ orchestrator runs list --status paused
ID         Routine                  Repo               Status   Step
run-b2e1   full-service-scaffold    platform-services   PAUSED   3/5
```

He checks the branch status:

```
GET /api/runs/run-b2e1/branch-status
→ 200 {
    "ahead": 12,
    "behind": 4,
    "source_branch": "main",
    "run_branch": "orchestrator/run-run-b2e1"
  }
```

12 commits ahead (his agent's work), 4 behind (his teammates' commits). He wants to pull in the upstream changes before resuming, in case any of them conflict with the scaffold.

### Back-Merge

```
POST /api/runs/run-b2e1/back-merge
→ 200 { "merged": true, "conflicts": false, "commits_merged": 4 }
```

The system merges `main` into `orchestrator/run-run-b2e1` inside the worktree. No conflicts today -- his teammates were working on different services. Had there been conflicts, the response would have said so, and Jordan would have needed to resolve them manually in the worktree before resuming.

### Resuming with a Different Agent

Jordan's been meaning to try OpenHands. His machine has it installed now (he set it up last night, couldn't sleep, don't ask).

```bash
$ orchestrator agents detect
claude_cli        available (claude on PATH)
openhands_local   available (SDK installed, OPENAI_API_KEY set)
openhands_docker  not available (Docker not running)

$ orchestrator runs resume run-b2e1 --agent openhands_local
Resumed run-b2e1 (ACTIVE) with openhands_local
```

```
POST /api/runs/run-b2e1/resume
{ "agent_type": "openhands_local" }
→ 200 { "status": "ACTIVE", "agent_type": "openhands_local" }
```

The run picks up where it left off. The current task is still in BUILDING, still on the same attempt. The new agent gets a fresh builder prompt (as always) with the current state of the checklist. Some items are already marked DONE from before the pause -- the agent sees this and focuses on the remaining work.

The OpenHands agent works differently than Claude CLI -- it uses a different tool set, different output format -- but the orchestrator doesn't care. The agent protocol is the same: receive prompt, update checklist, submit, grade. The agent is a black box that happens to write code.

### Monitoring from the CLI

Jordan keeps an eye on things while doing other work:

```bash
$ orchestrator runs list --status active
ID         Routine                  Repo               Status   Step    Agent
run-b2e1   full-service-scaffold    platform-services   ACTIVE   4/5     openhands_local
```

The activity log is also available via the API:

```
GET /api/runs/run-b2e1/activity?limit=5
→ 200 {
    "events": [
      { "type": "checklist_updated", "task": "build-api", "item": "R3", "status": "DONE", "ts": "..." },
      { "type": "task_status_changed", "task": "build-api", "status": "VERIFYING", "ts": "..." },
      ...
    ],
    "total": 47,
    "has_more": true
  }
```

47 events across the run's lifetime. Every state transition, every checklist update, every grade -- all queryable, all timestamped.

### The Finish

All five steps complete. The run enters COMPLETED. Jordan merges:

```bash
$ orchestrator runs merge-back run-b2e1 --strategy merge
Merged orchestrator/run-run-b2e1 → main (merge commit, 15 commits preserved)
```

He used `merge` instead of `squash` this time -- 15 commits of history showing the scaffold being built step by step. Useful for future archaeologists trying to understand why the billing service looks the way it does.

The billing service exists. It took two sessions, two agents, and one back-merge. Jordan's already thinking about the next one.

---

*This story covers: CLI usage, run creation, pause, resume with different agent, back-merge, branch status, activity log pagination, merge-back (merge strategy vs squash), agent detection, run listing with filters, monitoring, worktree persistence across pause/resume.*
