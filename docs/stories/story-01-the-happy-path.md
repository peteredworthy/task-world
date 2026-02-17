# Story 01: The Happy Path

*Maya runs a routine from start to finish with no complications. This is the story everything else is a variation of.*

---

Maya has a routine called `add-api-endpoint` that her team uses whenever they need a new REST endpoint. It lives in a git repo alongside a dozen others. She's done this before. Today she needs a `/api/widgets` endpoint added to the `acme-backend` repo.

She opens the dashboard. The UI fetches the routine list:

```
GET /api/routines
→ 200 [{ "id": "add-api-endpoint", "title": "Add API Endpoint", "source": "git", ... }]
```

She clicks into it to remind herself what it does:

```
GET /api/routines/add-api-endpoint
→ 200 {
    "id": "add-api-endpoint",
    "steps": [{
      "config_id": "implement",
      "title": "Implement endpoint",
      "tasks": [{
        "config_id": "build-endpoint",
        "checklist": [
          { "req_id": "R1", "description": "Route handler exists", "priority": "CRITICAL" },
          { "req_id": "R2", "description": "Request/response schemas defined", "priority": "CRITICAL" },
          { "req_id": "R3", "description": "Unit tests pass", "priority": "EXPECTED" },
          { "req_id": "R4", "description": "Docstring on handler", "priority": "NICE_TO_HAVE" }
        ]
      }]
    }]
  }
```

Two critical requirements, one expected, one nice-to-have. Straightforward.

She checks which agents are available. The UI hits:

```
GET /api/agents
→ 200 [
    { "name": "claude_cli", "available": true },
    { "name": "openhands_local", "available": false, "reason": "SDK not installed" }
  ]
```

Claude CLI it is. She creates the run:

```
POST /api/runs
{
  "routine_id": "add-api-endpoint",
  "repo_name": "acme-backend",
  "source_branch": "main",
  "agent_type": "claude_cli",
  "config": { "endpoint_name": "widgets", "http_method": "GET" }
}
→ 201 { "id": "run-7f3a", "status": "DRAFT", ... }
```

The run exists but hasn't done anything yet. No worktree, no branch, no agent. DRAFT means "I intend to do this." Maya reviews the config one more time in the UI, confirms it looks right, and hits start:

```
POST /api/runs/run-7f3a/start
→ 200 { "status": "ACTIVE", "worktree_path": "worktrees/run-run-7f3a", ... }
```

Three things just happened:

1. A git worktree was created at `worktrees/run-run-7f3a/`, branching from `main` onto `orchestrator/run-run-7f3a`.
2. The first task (`build-endpoint`) moved to PENDING.
3. The Claude CLI agent spawned as a subprocess, working directory set to the worktree.

The agent gets its builder prompt -- a self-contained description of what to build, the four requirements, and the checklist it needs to mark off. No preamble about the system, no history from previous runs. Fresh context.

The agent starts working. Maya watches the activity stream in the UI (events arriving over WebSocket). She sees:

```
[14:02:31] Task build-endpoint: status → BUILDING
[14:02:45] Agent: Reading existing router structure...
[14:03:12] Checklist R1 (Route handler exists): OPEN → DONE
[14:03:28] Checklist R2 (Request/response schemas defined): OPEN → DONE
[14:03:41] Checklist R3 (Unit tests pass): OPEN → DONE
[14:03:52] Checklist R4 (Docstring on handler): OPEN → DONE
[14:03:53] Agent: Submitting for verification
```

The agent marked all four items done (it's thorough today) and called submit. Behind the scenes, the checklist gate runs: are all CRITICAL items DONE? R1 is DONE, R2 is DONE. Gate passes. The task transitions to VERIFYING.

Now the agent gets a verifier prompt. This is a completely new context -- no memory of the building phase. It sees the four requirements, a grade scale (PASS, NEEDS_REVISION, MAJOR_ISSUES, FAIL), and instructions to evaluate the code in the worktree.

```
[14:04:01] Task build-endpoint: status → VERIFYING
[14:04:15] Grade R1 (Route handler exists): PASS
[14:04:22] Grade R2 (Request/response schemas): PASS
[14:04:30] Grade R3 (Unit tests pass): PASS
[14:04:35] Grade R4 (Docstring on handler): PASS
[14:04:36] Verification complete
```

The grade threshold gate evaluates. All PASS. The task moves to COMPLETED. Since this routine only has one step with one task, the step completes, the run completes:

```
[14:04:37] Task build-endpoint: status → COMPLETED
[14:04:37] Step implement: completed
[14:04:37] Run run-7f3a: status → COMPLETED
```

Maya's run is done. The code lives on the `orchestrator/run-run-7f3a` branch in the worktree. She reviews the diff in her git tool, likes what she sees, and triggers the merge:

```
POST /api/runs/run-7f3a/merge-back
{ "strategy": "squash" }
→ 200 { "merged": true, "strategy": "squash", "target_branch": "main" }
```

One clean squash commit on `main`. The widgets endpoint exists. Maya's done. Total elapsed time: about two minutes, most of it the agent thinking.

---

*This story covers: routine discovery, agent detection, run creation, run start, worktree creation, builder phase, checklist updates, submission, checklist gate, verifier phase, grading, grade threshold, run completion, merge-back.*
