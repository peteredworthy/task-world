# Routine Files: Environment Mismatch Gap

## Status: Open / Future Work

## Problem

Script tasks (`script:` field) and auto-verify commands (`auto_verify.items[].cmd`) currently execute in the **orchestrator server's environment** via `asyncio.create_subprocess_shell()` with `cwd=worktree_path`. This means they run on the host machine, using the host's Python, system packages, and filesystem access.

Meanwhile, managed agents (OpenHands Docker, Claude CLI sandbox, Codex, Claude SDK) run commands in **their own isolated environments** — Docker containers, sandboxes, or SDK-managed shells. These environments may have different packages installed, different Python versions, or different filesystem layouts.

## Why This Matters

Today this works because:
1. The orchestrator server has direct filesystem access to the worktree
2. Routine files are copied to `.orchestrator/routine-files/` in the worktree, which both the server and agent can reach
3. Most auto-verify commands are simple checks (file existence, grep patterns) that don't depend on environment-specific packages

But it breaks when:
- An auto-verify command needs a package only installed in the agent's Docker container
- A script task needs to run in the same virtualenv the agent is using
- The orchestrator host doesn't have the right Python version or toolchain
- The agent environment has network restrictions the host doesn't (or vice versa)

## Current Architecture

```
Routine YAML
  |
  +-- script: tasks -------> orchestrator subprocess (cwd=worktree)
  |
  +-- auto_verify cmds ----> orchestrator subprocess (cwd=worktree)
  |
  +-- builder prompt ------> agent environment (agent runs its own commands)
```

## Ideal Architecture

```
Routine YAML
  |
  +-- script: tasks -------> agent environment (via agent's command tool)
  |
  +-- auto_verify cmds ----> agent environment (via agent's command tool)
  |
  +-- builder prompt ------> agent environment (agent runs its own commands)
```

## Implementation Considerations

Running commands through the agent's environment requires different invocation per agent type:

| Agent Type | How to Execute |
|-----------|---------------|
| CLI_SUBPROCESS (Claude) | Send command as a message/tool call via stdin |
| OPENHANDS_LOCAL | Use SDK's bash tool executor |
| OPENHANDS_DOCKER | Use SDK's bash tool (runs inside container) |
| CODEX_SERVER | Send via JSON-RPC tool call |
| CLAUDE_SDK | Use SDK's built-in command execution |
| USER_MANAGED | Cannot execute — would need an API callback model |

Key challenges:
1. **Agent may not be running** during auto-verify (it runs between phases)
2. **Script tasks bypass agents entirely** — they'd need a lightweight agent session or a direct container exec
3. **Timeout/output capture** semantics differ across agent SDKs
4. **USER_MANAGED** agents have no execution capability — verification would need to be external

## Workaround (Current)

Routine files are copied to `.orchestrator/routine-files/` in the worktree. Since both the server subprocess and the agent operate with the worktree as their root, path references like `python .orchestrator/routine-files/scripts/check.py` resolve correctly in both contexts. The gap is only about which *environment* (host vs container) executes the command, not about file availability.
