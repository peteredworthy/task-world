# Rate Limit Handling

## Problem

When an Anthropic credit or usage limit is reached during a run, the orchestrator
does not detect the condition and blindly retries. Each retry spawns a new Claude Code
subprocess that immediately hits the same limit, dies in a few seconds, and wastes a
retry slot. A single rate-limit event cascades into dozens of wasted subprocess spawns
and can exhaust every child's `max_attempts` budget in under a minute, terminating the
entire run with `fan_out_child_failed`.

This was observed on 2026-04-05 during E8 arm B (run `20139177`). After the rate limit
hit around 20:42 UTC, the orchestrator spawned **9 additional Claude Code subprocesses**
across 3 fan-out children's retry loops (3 retries × 3 children). Each lasted 3–10
seconds, produced 6 jsonl lines containing the rate-limit message, then exited with
code 1. All 9 were pure waste.

---

## How the rate limit manifests in Claude Code

Claude Code does **not** raise an API-level HTTP 429 to the calling process. Instead,
it emits a normal-looking `assistant` message containing the rate-limit text, then
ends the conversation. The pattern, verified from raw session jsonl files:

### Stream-JSON event sequence when rate limit hits

```jsonl
{"type":"user","message":{"content":[{"type":"text","text":"<the prompt>"}]}}
{"type":"assistant","message":{"stop_reason":"stop_sequence","content":[{"type":"text","text":"You've hit your limit · resets 6pm (America/New_York)"}]}}
{"type":"last-prompt","message":{...}}
```

Key observations:
- `stop_reason` is `"stop_sequence"`, NOT `"end_turn"` or an error code
- `is_error` is not set (absent or `null`)
- No `result` event is emitted (no `subtype`, no `num_turns`, no `total_cost_usd`)
- The process exits with code 1

### What the orchestrator currently sees

The parser treats the `assistant` event normally — it captures the text as an
`ActionLogEntry` with `kind=ASSISTANT_TEXT`. The agent runner sees `returncode != 0` and
creates an `ExecutionResult(success=False, error="Process exited with code 1")`. The
executor records `outcome="failed"` and enters the retry loop. Nothing in the pipeline
distinguishes "rate limit" from "agent crashed."

### The text pattern is stable

Across 9 wasted retry sessions in run `20139177` plus the 2 real sessions that hit the
limit mid-work, the message is byte-identical every time:

```
You've hit your limit · resets 6pm (America/New_York)
```

The format appears to be:
```
You've hit your limit · resets <TIME> (<TIMEZONE>)
```

Where `<TIME>` is like `6pm`, `9am`, `Jan 7, 9am` and `<TIMEZONE>` is an IANA-style
name like `America/New_York`. Other variants may include `5-hour limit` or `weekly limit`
based on Anthropic's plan structure — recommend matching generously:

```python
import re
RATE_LIMIT_PATTERN = re.compile(
    r"You've hit your (?:\S+ )?limit"
)
```

And for extracting the reset time:
```python
RATE_LIMIT_RESET_PATTERN = re.compile(
    r"resets?\s+(.+?)\s+\(([^)]+)\)"
)
```

---

## What the orchestrator should do instead

### Slice 1 — Detection + pause (high priority, eliminates cascading retries)

**Goal**: When a rate limit is detected, immediately pause the run with a specific
reason. Do not retry. Do not burn retry slots.

**Changes**:

1. **`src/orchestrator/state/models.py`**
   - Add `rate_limit_hit: bool = False` and
     `rate_limit_resets_at: datetime | None = None` to `ActionLog`

2. **`src/orchestrator/runners/agents/claude_cli/parser.py`**
   - In `_handle_assistant` (or a shared text-scanning helper), after capturing the
     text content of an assistant block, match against `RATE_LIMIT_PATTERN`
   - If matched, set `self._rate_limit_hit = True`
   - Attempt to parse the reset time from the text using `RATE_LIMIT_RESET_PATTERN`
     and a timezone-aware parser (e.g. `dateutil.parser.parse` or manual logic for
     the simple `Xam/Xpm` format). Store as `self._rate_limit_resets_at`
   - In `finalize()`, propagate both fields to the returned `ActionLog`

3. **`src/orchestrator/runners/agents/claude_cli/agent.py`**
   - New exception class: `AgentRateLimitError(session_id, resets_at)`
   - After `action_log = self._parser.finalize()`, check `action_log.rate_limit_hit`
   - If True, raise `AgentRateLimitError(action_log.session_id, action_log.rate_limit_resets_at)`
     instead of returning the normal `ExecutionResult`

4. **`src/orchestrator/runners/executor.py`**
   - Import `AgentRateLimitError`
   - In the fan-out `run_child` retry loop (around line 1110), catch
     `AgentRateLimitError` BEFORE the generic `except Exception`:
     ```python
     except AgentRateLimitError as e:
         # Do NOT consume a retry slot
         # Store the session_id for potential resumption
         logger.warning(
             f"Run {run.id}: child {child_id} hit rate limit "
             f"(resets at {e.resets_at}), pausing run"
         )
         # Save the attempt with outcome="rate_limited" and session data
         async with self._session_factory() as sess:
             svc = await self._create_service(sess)
             await svc.update_child_task_state(
                 run.id, child_id,
                 {
                     "outcome": "rate_limited",
                     "completed_at": datetime.now(timezone.utc),
                     "action_log": action_log,
                 },
             )
         # Propagate to abort the gather and pause the run
         raise
     ```
   - In the fan-out gather exception handling (the `asyncio.gather` wrapper),
     catch `AgentRateLimitError` and pause the run with a specific reason:
     ```python
     run.pause_reason = "rate_limit"
     run.last_error = f"Rate limit hit; resets at {e.resets_at}"
     ```
   - Do the same for the regular (non-fan-out) task execution path in
     `_execute_task`

5. **Add `"rate_limited"` as a valid attempt outcome** alongside the existing
   `"passed"`, `"revision_needed"`, `"failed"`, `"paused"`, `"reverted"`.
   This is just documentation / validation — the field is already a free-form string.

**What this achieves**: When credits run out, the run pauses immediately with a
clear reason. No retry slots are consumed. No additional subprocesses are spawned.
The UI shows "paused: rate_limit" with the reset time. The user can resume when
credits are available.

**What this does NOT achieve**: It does not resume the conversation cheaply. The
next resume will start a fresh Claude Code session. That's slice 2.

---

### Slice 2 — Cheap resumption via `--resume` (medium priority, saves exploration tokens)

**Goal**: When a rate-limited (or any paused) attempt is resumed, continue the
existing Claude Code conversation instead of starting fresh. This preserves all
prior tool calls and file reads as prompt-cache hits, so the resumed session pays
only for the new work.

**Prerequisites**: Slice 1 must be in place (rate_limit_hit detection, attempt
outcome, session_id storage).

**Key mechanism**: Claude Code supports `-r, --resume <session_id>` which loads the
prior conversation from disk and continues it. The session jsonl is stored at
`~/.claude/projects/{project_slug}/{session_id}.jsonl` per worktree. Our `ActionLog`
already captures `session_id`.

**Changes**:

1. **`src/orchestrator/state/models.py`**
   - Add `resumable_session_id: str | None = None` to `Attempt`
   - When an attempt is paused (rate_limited or otherwise), populate this field from
     `action_log.session_id`

2. **`src/orchestrator/runners/agents/claude_cli/factory.py`**
   - Accept an optional `resume_session_id: str | None` parameter
   - When set AND `command == "claude"`, replace the `-p` prompt-mode flag with
     `-p --resume <session_id>` and use a minimal continuation prompt instead of
     the full task prompt. Example: `"Continue from where you were."`
   - Keep all other flags (`--dangerously-skip-permissions`, `--output-format
     stream-json`, `--verbose`, `--max-turns`)

3. **`src/orchestrator/runners/executor.py`**
   - In both the regular and fan-out execution paths, before creating the agent:
     check if the current attempt has `resumable_session_id` set
   - If yes, pass it through to the factory so the CLI gets `--resume`
   - Clear `resumable_session_id` after the attempt completes (success or failure)

4. **Interaction with `--max-turns`**
   - When resuming, the `--max-turns N` flag applies to the RESUMED session's
     remaining turns, not the original session's total. So if the original ran for
     20 turns before pausing, and max_turns=25, the resumed session gets 25 NEW
     turns (not 5). Claude Code does not carry forward the turn count.
   - This is fine for rate-limit recovery (the agent needs room to finish). For
     the turn-budget-as-cost-control use case, consider adjusting the max_turns
     downward on resume to prevent an infinite loop.

5. **Interaction with the nudger**
   - A resumed conversation may start with a thinking pause (Claude processing the
     resumed context) before producing output. The nudger's `output_timeout` should
     be slightly relaxed for the first N seconds of a resumed session, or the nudger
     should be informed that this is a resume (and not count the initial thinking time
     as "stuck").

6. **Interaction with existing worktree state**
   - `--resume` expects the worktree to be in the same state the session left it in.
     For rate-limit pauses this is naturally true (nothing changed between pause and
     resume). For server-shutdown pauses it's also true (worktree persists). For
     manual pauses where the user may have edited files, there's a risk of divergence
     — the resumed Claude session may reference files that have changed. This is a
     known limitation; document it, don't try to detect it programmatically.

**Session file lifecycle**:
- Claude Code stores sessions per project slug, keyed by the worktree path
- Slug = working directory with `/` replaced by `-`
  (e.g. `/Users/peter/code/task-world/worktrees/r66`
  → `-Users-peter-code-task-world-worktrees-r66`)
- Session files persist until manually deleted or `~/.claude` is cleaned
- Worktree cleanup (`git worktree remove`) does NOT delete session files — they
  remain orphaned under the project slug directory. This is fine for our purposes.

---

### Slice 3 — Auto-resume on credit reset (low priority, convenience)

**Goal**: Automatically resume rate-limited runs when the reset time has passed.

**Changes**:

1. **`src/orchestrator/api/app.py` startup hook** (or heartbeat loop)
   - On startup, query for runs with `status=PAUSED` and
     `pause_reason="rate_limit"` that have a stored `rate_limit_resets_at` in the
     past
   - For each, enqueue a RESUME signal via the normal workflow service path
   - The resume signal triggers the executor, which sees `resumable_session_id` on
     the attempt and uses `--resume` per slice 2

2. **Heartbeat/poll loop** (if the server stays running across the reset boundary)
   - Every 5 minutes, check for rate-limited runs whose reset time has passed
   - Resume them

**Why this is lower priority**: Rate limits are infrequent enough that manual
"check the run, click resume" is adequate. Auto-resume is a convenience for
unattended operation. It also requires parsing the reset time correctly (including
timezone), which adds complexity.

---

## Evidence from the E8 arm B runs

### Run `080fe19c` (first arm B, max_turns=25)

This run did NOT hit a rate limit — it hit the max_turns budget. fan_1 attempts 1 and
2 each reached ~25 agent turns and were terminated by Claude Code with exit code 1.
No rate-limit text was present in the session jsonl. The retry loop consumed all 4
attempts normally (each starting a fresh session).

Relevant to this design: if slice 2's `--resume` had been available and these
max_turns-exhausted sessions had been paused instead of failed, the agent could
have been resumed with a higher max_turns setting to finish the work. Currently
there is no mechanism to adjust max_turns between retries.

### Run `20139177` (second arm B, max_turns=100)

This run hit the Anthropic credit limit around 20:42 UTC:

- **fan_0 att1**: Nudger-killed after 2 nudges (10 minutes of silence). Not rate-limit
  related — the agent was stuck in an extended thinking loop. No action_log captured.

- **fan_1 att1**: 10 minutes, 1,472,479 cache_read, 59 tool calls, 0 writes. Rate limit
  hit at 20:42:25. Result text: "You've hit your limit · resets 6pm (America/New_York)".
  Session `3882fbba` is on disk at 90 lines, resumable.

- **fan_2 att1**: 10 minutes, 798,696 cache_read, 37 tool calls, 1 write (step file
  created), 1 API submit call succeeded. Rate limit hit at 20:42:12. Same limit text.
  Session `0d1eca6a` is on disk at 66 lines, resumable. **This session was essentially
  complete** when the limit hit — it had already written its output and submitted to
  the orchestrator API.

- **fan_3 att1**: Passed cleanly before the rate limit, 66,359 cache_read.

**Post-limit retry cascade** (the problem slice 1 would have prevented):
- fan_0 att2-4: 3 subprocess spawns, each 3–10 seconds, 6 jsonl lines, immediate rate-limit exit
- fan_1 att2-4: same
- fan_2 att2-4: same
- Total: **9 wasted subprocess spawns**, all producing the same "You've hit your limit" text

**Session IDs for the wasted retries** (all 6 lines, all starting with the limit message):
```
255c7de0, 465025ca, 4982072c, 4b1a8c51, 7d1fa5e7, a4a47192, c85c2434, e3cac428, e781ca97
```

**Session IDs for real work** (resumable):
```
3882fbba (fan_1 att1, 90 lines, 1.47M cache_read of exploration)
0d1eca6a (fan_2 att1, 66 lines, 798K cache_read, file written, API submitted)
5deef8a3 (fan_0 att1?, 52 lines, identity uncertain)
fdd4d7d8 (unknown, 37 lines)
```

---

## General value of `--resume` beyond rate limits

The `--resume` mechanism is valuable for ANY pause-and-resume scenario, not just
rate limits:

| Scenario | Current behavior | With `--resume` |
|---|---|---|
| Rate limit hit | Fresh session on retry; all exploration re-done | Continue from cached context; pay only for new turns |
| Server shutdown mid-attempt | Fresh session on resume; exploration lost | Continue from cached context |
| Manual pause for investigation | Fresh session on resume | Continue, agent has full history |
| Pre-commit hook failure (C4) | Fresh session on retry; same codebase re-read | Continue with hook failure in context; agent can try a different approach |
| Nudger kill (stuck agent) | Fresh session on retry | Potentially resume with a nudge message; agent might unstick itself. Uncertain — needs testing. |

The biggest win is rate limits because the alternative is "redo 10 minutes of
exploration that was going fine before the limit hit." The second biggest is
server-shutdown recovery, which currently loses all in-progress attempt work.

---

## Implementation priority

1. **Slice 1 — Detection + pause**: Highest priority. Eliminates the cascade.
   ~100 lines across 4 files. Can land independently. Low risk.

2. **Slice 2 — `--resume` continuation**: Medium priority. Saves real tokens on
   every resume. ~80 lines across 3 files plus the nudger interaction. Moderate
   risk (needs testing for edge cases: stale worktree, partial writes, nudger
   behavior on resume).

3. **Slice 3 — Auto-resume on reset**: Low priority. Convenience for unattended
   runs. ~40 lines. Low risk but depends on correct timezone parsing.

---

## References

- E8 arm B run `20139177`: DB data in `orchestrator.db`, session jsonls at
  `~/.claude/projects/-Users-peter-code-task-world-worktrees-r66/`
- E8 arm B run `080fe19c` (max_turns failure): same DB, session jsonls at
  `~/.claude/projects/-Users-peter-code-task-world-worktrees-r65/`
- Claude Code CLI flags: `claude --help` (verified 2026-04-05):
  `-r, --resume [value]`, `--session-id <uuid>`, `--fork-session`
- Existing session_id capture: `ActionLog.session_id` in `state/models.py`
- Rate-limit text pattern: byte-identical across 11 observations in 2 runs
- Sandbox settings: `git/worktree.py:_write_sandbox_settings` (lines 110–172)
- Nudger: `runners/runtime/nudger.py` — `NudgeAction.KILL` after `max_nudges`
- Parser: `runners/agents/claude_cli/parser.py` — `_handle_assistant`, `finalize()`
- Factory: `runners/agents/claude_cli/factory.py` — CLI args assembly (lines 48–67)
- Executor fan-out retry loop: `runners/executor.py` (lines ~1100–1200)
