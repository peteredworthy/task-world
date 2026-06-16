# True Comparison Results

## Status

Current state: **harness defined, full five-arm comparison pending**.

The completed DG-5.1 dynamic smoke run proves that the production dynamic graph
can perform live planner patching, gap-planner correction, and final invariant
completion on a tiny scenario. It does not yet prove that dynamic graph planning
beats the other carriers, because Arms A-D have not been run against the same
scenario and oracle under the same controls.

## Scenario Ledger

### Scenario S1: Dynamic Smoke

Spec: `docs/graph-approach/dynamic-smoke-feature-spec.md`

Weak acceptance command:

```bash
test -f docs/graph-approach/dynamic-smoke-output.txt && rg -q "dynamic-smoke" docs/graph-approach/dynamic-smoke-output.txt
```

Hidden oracle command:

```bash
test -f docs/graph-approach/dynamic-smoke-output.txt && rg -q "dynamic-smoke" docs/graph-approach/dynamic-smoke-output.txt && rg -q "validation-strengthened: true" docs/graph-approach/dynamic-smoke-output.txt
```

| Arm | Carrier | Run | Status | Oracle | Evidence status |
|---|---|---|---|---|---|
| A | Legacy single-agent | pending | pending | pending | not run |
| B | Fixed 3-agent routine | pending | pending | pending | not run |
| C | Faithful Mind-the-gap | pending | pending | pending | not run |
| D | Static graph carrier | pending | pending | pending | not run |
| E | Dynamic graph | `0c053df6-1702-4d67-94de-628a4e2ee256` | completed | passed | accepted smoke evidence |

## Accepted Arm E Smoke Evidence

Run `0c053df6-1702-4d67-94de-628a4e2ee256` used routine
`dynamic-graph-feature`, execution mode `graph`, runner `cli_subprocess`, and
model `claude-sonnet-4-6`.

Verified graph facts from compact graph events:

- 158 graph events, positions 1 through 158.
- Accepted root planner patch: `patch-dynamic-smoke-full-graph`.
- Rejected gap no-op patch: `no-gap-no-op-dynamic-smoke-01`, reason
  `gap planner no-op leaves required classified_gap successor unsatisfied`.
- Accepted gap-planner patch: `gap-classify-passed-edge-dynamic-smoke-02`.
- Two verifier pass events.
- Final invariant check `check-final-invariant-dynamic-smoke` reached ready at
  position 147, leased at 151, running at 152, callback accepted at 153, and
  completed at 157.
- The artifact in the run worktree contains both required lines:
  `dynamic-smoke` and `validation-strengthened: true`.

Metrics:

```text
approach                 runs compl all-A avg_in  avg_out  avg_cache  avg_tools  avg_cost$
-------------------------------------------------------------------------------------------
dynamic                  1    1     0     79      13278    939866     47.0       0.7653
```

Readback:

- `GET /api/runs/0c053df6-1702-4d67-94de-628a4e2ee256/graph/events?payload_mode=summary`
  returned HTTP 200 in about `0.6s`.
- Invalid `payload_mode=compact` returned HTTP 422.

## Interpretation

Arm E is operational for S1. The run satisfies the dynamic-graph operational
criteria that at least one planner-generated patch creates future work, a
gap-planner decision changes the future graph, corrective work runs after local
verification, and final completion depends on an invariant check.

The comparison claim remains open. S1 is intentionally tiny, and only Arm E has
been executed on it. The next useful result is not another dynamic smoke retry;
it is a controlled Arms A-D run set using the same S1 commands, or a larger
DG-5.2b scenario if S1 is deemed too small for carrier-quality conclusions.

## Harness Update: Hidden Oracle Isolation

DG-5.2b changed the S1 harness so future comparison runs can treat the oracle as
hidden from agents:

- planner packets expose `hidden_oracle_binding:
  dynamic_feature_hidden_oracle`, not the oracle command string;
- dynamic worker prompts no longer include `dynamic_hidden_oracle_command`;
- final invariant check patches can use
  `command_binding: dynamic_feature_hidden_oracle`;
- the graph command applier resolves that binding from the stored routine
  snapshot when the check node is created.

The accepted Arm E smoke run above predates this isolation and remains valid as
operational evidence, not as fair five-arm hidden-oracle comparison evidence.
Run a fresh isolated Arm E smoke before comparing against Arms A-D.

### Isolated Arm E Retry

Run `e4c168ea-d61a-469b-ae92-127c739557ed` was the first Arm E retry after
DG-5.2b.

Outcome: **paused**, `pause_reason=graph_blocked`,
`last_error="graph quiescent without completion"`.

Verified evidence:

- Runtime oracle binding worked: final check node
  `check-final-invariant-dynamic-smoke` carried
  `command_binding: dynamic_feature_hidden_oracle` and a resolved
  `command_definition.source: dynamic_feature_hidden_oracle_binding`.
- The artifact contained only `dynamic-smoke`, so the hidden oracle was not yet
  satisfied.
- The gap planner's first no-op patch was rejected.
- The accepted retry patch retired the corrective worker and verifier, then
  added a late verifier-to-final-check edge.
- The final check remained deferred on
  `missing_required_input:verification_evidence`.

DG-5.2c repaired the two classified gaps: late input-edge backfill and
gap-planner executable-node retirement.

### Isolated Arm E Retry After DG-5.2c

Run `2558d649-d27a-4816-b1f6-a68e33e3c59d` was the isolated Arm E retry after
DG-5.2c.

Outcome: **paused**, `pause_reason=graph_blocked`,
`last_error="graph quiescent without completion"`.

Verified evidence from summary graph events:

- 110 graph events were readable through summary mode.
- Root planner patch `patch-dynamic-smoke-full-plan` was rejected because the
  invariant check lacked a verification input edge.
- Retry patch `patch-ds-full-plan-v3` was accepted.
- Gap no-op patch `patch-ds-gap-no-op` was rejected because a required
  `classified_gap` successor remained unsatisfied.
- Gap retire patch `patch-ds-gap-retire-corrective` was rejected with
  `gap planner cannot retire executable node: worker-ds-corrective`, proving
  the DG-5.2c guard live.
- Final event position 110 re-readied `planner-ds-gap`; the run paused before a
  new gap planner execution completed.

DG-5.2d repaired the immediate code-level signal gaps: ready-node blockers are
reported explicitly, and gap planner packets now carry blocking obligations for
waiting `classified_gap` successors and final invariant checks missing
`verification_evidence`.

### Isolated Arm E Retry After DG-5.2d

Run `abba86e4-5b6e-459c-a074-63118005cb95` was the isolated Arm E retry after
DG-5.2d.

Outcome: **paused**, `pause_reason=graph_blocked`, with classified runner quota
evidence:

```text
graph has failed node(s): verifier-smoke-corrective: Agent runner 'cli_subprocess' hit rate limit (resets at 2026-06-15 19:30:00+01:00)
```

Verified evidence:

- Root planner patch `patch-dynamic-smoke-full-plan` was accepted.
- Gap planner patch `patch-smoke-gap-wire-final-invariant` was accepted,
  proving the obligation signal avoided the previous no-op/retire failure mode.
- Corrective worker ran.
- Corrective verifier `verifier-smoke-corrective` emitted `agent_died` with the
  rate-limit reason above.
- Final invariant check `check-smoke-final-invariant` remained deferred on
  `missing_required_input:verification_evidence`.
- The run worktree artifact contained only `dynamic-smoke`.

Metrics:

```text
approach                 runs compl all-A avg_in  avg_out  avg_cache  avg_tools  avg_cost$
-------------------------------------------------------------------------------------------
isolated3                1    0     0     22      7595     216187     12.0       0.3276
```

## Scenario S2: Live Agent-Output Streaming (real work)

Real repo feature, chosen so the comparison measures cost on *real* work rather
than a toy. Arms reduced to **A (single-agent), C (Mind-the-gap), E (dynamic
graph)** — B (fixed 3-agent) and D (static graph) dropped as low-value.

Feature request: bring the **graph carrier** to parity with the legacy carrier's
live agent-output streaming (graph-node stdout was persisted but never broadcast
to the frontend while running). Root cause: `make_graph_runner` built its
`OutputBatcher` without a `connection_manager`.

Hidden oracle: `docs/graph-approach/oracles/test_stream_output_oracle_v2.py`
(static wiring fact + behavioral: a graph node's streamed lines are broadcast via
the connection manager, attributed by `node_id`). Verified as a real gate — it
FAILS on the pre-feature code and PASSES on a correct implementation.

| Arm | Carrier | Run | Status | Hidden oracle | Cost |
|---|---|---|---|---|---|
| A | Legacy single-agent | `2b7b7410-a950-40c2-990a-00d0bbc579cc` | completed | **passed** | $3.23, 90 tool calls, 35.4k out tok |
| C | Faithful Mind-the-gap | pending | pending | pending | — |
| E | Dynamic graph | pending | pending | pending | — |

### Arm A finding (2026-06-15)

Single-agent (`cli_subprocess`, `claude-sonnet-4-6`, isolated `repos/task-world`
worktree r305) **completed the feature correctly in one pass**: wired
`connection_manager` through `make_graph_runner` + `api/app.py`, added a `node_id`
field to `AgentOutputEvent` for per-node attribution, and added two behavioral
streaming tests (26 related tests green). The corrected hidden oracle (v2) passes
against its worktree and fails against the pre-feature tree.

Process note: the first oracle (v1) returned a false negative because it required
an injectable `runtime_builder` seam on `make_graph_runner` that was never part of
the feature requirement. v2 tests the behavior only. Lesson for the harness
discipline: a hidden oracle must assert the *requirement*, not a preferred test
seam.

**Conclusion for S2:** the task was within single-agent reach, so it does not
differentiate the carriers — a harder scenario (genuinely too large/ambiguous for
one pass, forcing discovery + corrective work) is needed before running Arms C/E.
The feature itself is fixed (in worktree r305; port to main pending).

## Next Slice

After the 2026-06-15 19:30 BST Claude CLI quota reset, resume or retry Arm E
from run `abba86e4-5b6e-459c-a074-63118005cb95`. Then define or launch the
first controlled Arms A-D pass for S1 if Arm E completes under hidden-oracle
discipline:

- select exact routines for legacy, fixed 3-agent, static graph, and faithful
  Mind-the-gap arms;
- use the same weak acceptance and hidden oracle commands;
- record run IDs and metrics in this ledger;
- preserve a clear distinction between smoke-harness validation and broader
  dynamic-planning quality claims.
