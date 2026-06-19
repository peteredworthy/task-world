# Big-task carrier comparison — live results log

Orchestrator: Claude Opus. Worker model: `gpt-5.3-codex-spark`. Target: desktop-test
Versioned File Workspace (`spec.md`, 8 capabilities + interactions). Oracle: 56 hidden
acceptance tests (`acceptance/`). Started 2026-06-14.

## Calibration

| baseline | spec | oracle | one-shot result | wall | tokens(in/out/reason) | ~USD |
|---|---|---|---|---|---|---|
| v1 | 3-capability | 30 tests | **30/30** (too easy) | 110s | 1.14M/30.9k/18.6k | $0.71 |
| v2 | 8-capability + interactions | 56 tests | **51/56** (5 interaction bugs) | 166s | 3.06M/57k/31k | $1.39 |

The v1 one-shot passing 30/30 proved the first cut was within single-shot reach, so the
spec was hardened (move/copy, tags, quota, activity, and cross-feature interactions) and the
oracle grown to 56 tests. A single-agent one-shot landing well below 100% on v2 is the gate
to launch the three strategy arms.

## Arms (status)

| Arm | Strategy | Status | Acceptance | Wall | Agents | ~USD |
|---|---|---|---|---|---|---|
| A | Graph (task-world carrier) | pending | | | | |
| B | Idea-to-plan | pending | | | | |
| C | Mind-the-gap | pending | | | | |

(updated as each arm completes)

## Arm results (graded vs 56-test oracle)

### B — idea-to-plan: 52/56
- 3 agents (plan -> implement -> verify), 632.9s wall, ~$2.23, 56 tool calls, 3.86M in / 103k out tokens.
- Failures (4): trash directory restore + purge-one + empty-all + purge-drops-versions — all NotADirectoryError-class bugs in trash dir handling. The front-loaded plan + single verify pass did not surface these interaction cases (its own tests passed).
- vs naive one-shot (51/56): +1. Front-loading bought little correctness here.

### A' — real task-world graph carrier (grounding datapoint)
- Attempt 1 (cli_subprocess + codex model): the runner launched the *claude* CLI with the codex model id and **no orchestrator MCP**, so the worker had no submit signal; graph went quiescent ("graph quiescent without completion") with zero code written. Finding: cli_subprocess does not route a codex model to the codex CLI, and the graph worker needs a completion signal.
- Attempt 2 (codex_server, native REST callback): dispatched a real codex app-server worker; running.

### A — graph horizon: 56/56 (best correctness)
- 17 agents, 1447s, 292 tool calls, 14.8M in / 220k out, ~$6.28.
- Horizon planner correctly staged all 8 capabilities across 5 regions; an independent verifier node per region. Hit 45/56 first because a verdict-parse bug in MY driver aborted the loop after the final region was *planned* but before it was *built*; running that planned region (verifier passed first try) closed to 56/56. Strategy correctness is 56/56; the 45 was a harness artifact (documented).

### C — mind-the-gap: 48/56 (most cost, below one-shot)
- 29 agents, 1554s, 301 tool calls, 13.4M in / 228k out, ~$6.42.
- 9 chunk cycles, fresh builder+validator each. Finest granularity did NOT win: per-chunk validators passed chunks carrying latent interaction bugs (activity-log response shape, quota no-partial-write, copy-history, collision-rename). Validation only as good as each validator's scope.
- Post-hoc fidelity note: this arm approximated the intended `mind-the-gap` skill
  (`../mind-the-gap-skill.md`) but did not enforce it strongly enough. The skill
  requires an explicit baseline, relevant tests passing for each validated chunk,
  orchestrator review of validator evidence before updating durable state, and
  durable state that records verified behavior, evidence, decisions, risks, and
  remaining gaps. The driver kept compact state and used fresh builder/validator
  agents, but validator prompts were too chunk-local and the orchestrator accepted
  pass verdicts without independently recording detailed evidence. That explains
  why interaction bugs survived repeated validation: the loop granularity was
  high, but validation scope and durable evidence discipline were too weak.

### A' — real task-world graph carrier: 33/56
- Completed via codex_server (native codex worker), 11 graph nodes, ~1201s wall (incl. resume waits). Token usage not captured (codex_server gap).
- Single-task routine -> minimal worker+verifier graph (no horizon planner). Worker one-shot all 8 capabilities from the routine's condensed task_context (561-line main.py); verifier node passed it against the 5 coarse routine requirements, missing quota+activity+interactions. Needed manual `runs resume` to clear transient "graph quiescent" stalls between ready/dispatch.
- Caveat: thinner input context than the other arms (routine task_context vs full spec.md) — its low score partly reflects input asymmetry, not just the carrier.

## Headline findings
1. **Cost scales with planning granularity**, not with correctness: one-shot $1.4 -> idea-to-plan $2.2 -> graph-horizon $6.3 -> mind-the-gap $6.4; agents 1 -> 3 -> 17 -> 29.
2. **Only adaptive horizon planning (graph) reached 100%.** It bought the last 5 interaction bugs that one-shot missed, at ~4.5x one-shot cost.
3. **More iteration is not more correct.** Mind-the-gap cost the most yet scored *below* one-shot — narrow per-chunk validators rubber-stamped buggy chunks. Verification scope matters more than cycle count.
4. **The real carrier on a thin routine degenerates to one-shot + a coarse verifier** (33/56) and adds operational overhead (quiescence stalls). The graph *approach's* value needs real planner nodes and detailed verification to materialise (Arm A), which a single-task routine does not compile to.
5. **The Mind-the-gap result should not be treated as a full skill rejection.** It
   is evidence that a weak implementation of the skill fails: chunk validators
   must carry the full interaction/regression burden for all verified state, or
   the loop can ratify incomplete work faster than it finds global gaps.
