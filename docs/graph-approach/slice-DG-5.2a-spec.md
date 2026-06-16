# Slice DG-5.2a Spec: True Comparison Harness

## Objective

Make the DG-5.2 comparison runnable and fair before launching expensive
multi-arm runs. This slice defines the comparison scenario, arm mapping,
evidence ledger, and acceptance rules that distinguish an operational dynamic
graph smoke proof from a valid five-arm comparison.

## Baseline Evidence

The completed DG-5.1 dynamic smoke run
`0c053df6-1702-4d67-94de-628a4e2ee256` is accepted as operational smoke
evidence for Arm E:

- the root planner submitted accepted graph patch
  `patch-dynamic-smoke-full-graph`;
- the initial worker produced
  `docs/graph-approach/dynamic-smoke-output.txt`;
- weak local verification passed;
- the gap planner first submitted rejected no-op patch
  `no-gap-no-op-dynamic-smoke-01` with reason
  `gap planner no-op leaves required classified_gap successor unsatisfied`;
- the gap planner then submitted accepted patch
  `gap-classify-passed-edge-dynamic-smoke-02`;
- corrective work and corrective verification completed;
- final invariant check `check-final-invariant-dynamic-smoke` reached
  ready, leased, running, callback accepted, and completed;
- `GET /graph/events?payload_mode=summary` returned HTTP 200 in about `0.6s`;
- `uv run python scripts/compare_carriers.py dynamic=0c053df6-1702-4d67-94de-628a4e2ee256`
  reports `completed=1`, `avg_tools=47.0`, and `avg_cost$=0.7653`.

This is not a full comparison conclusion. It uses the production dynamic graph
routine on the smoke scenario, but Arms A-D have not yet run on the same target
with the same oracle and runner controls.

## Comparison Scenario Contract

The first DG-5.2 comparison scenario should be small enough to finish in one
session but must exercise the properties from `true-comparison-plan.md`:

1. Initially ambiguous or weak validation requirement.
2. Discovery or gap analysis that makes the missing requirement concrete.
3. A weak local acceptance command that can pass before the global oracle.
4. Corrective work that must be appended after local verifier success.
5. A hidden oracle that fails unless the corrective behavior exists.
6. A final acceptance rule that treats stale evidence, open proposals, and
   pending planner/gap/check nodes as blockers.

`docs/graph-approach/dynamic-smoke-feature-spec.md` is an accepted smoke
scenario. It is useful for harness validation, but it is too small to settle the
larger product-quality claim by itself. A later DG-5.2b scenario may adapt the
larger Versioned File Workspace target if budget allows.

## Five Arms

Run each arm from the same repository snapshot and record the exact run ID,
runner, model, commands, final status, oracle result, and comparison metrics.

| Arm | Carrier | Required execution shape |
|---|---|---|
| A | Legacy single-agent | One builder attempt plus configured checks. No dynamic graph patch tools. |
| B | Fixed 3-agent routine | Up-front builder/verifier/fixer style routine; no new work selected after validation except retry feedback. |
| C | Faithful Mind-the-gap | Baseline first, planner/gap-finder chooses one chunk, builder edits only that chunk, validator protects all relevant verified behavior, durable state updated after reviewed evidence. |
| D | Static graph carrier | Fixed graph worker/verifier/check nodes. No planner-created future graph patches. |
| E | Dynamic graph | Production `dynamic-graph-feature`; planner/gap planner patches create or modify future work; final invariant gate controls completion. |

## Runner Controls

- Prefer the same model family and runner for all arms where the carrier allows
  it.
- Claude CLI may be used now that quota is available; record any rate-limit or
  runner fallback explicitly.
- Codex Server remains acceptable when an available Codex model is stable for
  the selected arm.
- Do not mix scenario inputs. The same weak acceptance command and hidden
  oracle command must be used for every arm.

## Evidence Ledger

Maintain `docs/graph-approach/true-comparison-results.md` as the compact
durable ledger. For each arm record:

- run ID and worktree;
- runner type and model;
- final API status, pause reason, and cost/token/action metrics;
- weak acceptance result and hidden oracle result;
- for graph arms, dynamic metrics from `scripts/compare_carriers.py`;
- a short finding that is grounded in verified evidence, not agent prose.

## Validation Commands

For DG-5.2a itself:

```bash
uv run python scripts/compare_carriers.py dynamic=0c053df6-1702-4d67-94de-628a4e2ee256
curl -sS --max-time 20 'http://127.0.0.1:8000/api/runs/0c053df6-1702-4d67-94de-628a4e2ee256/graph/events?payload_mode=summary'
```

For each subsequent comparison arm:

```bash
curl -sS http://127.0.0.1:8000/api/runs/<run-id>
uv run python scripts/compare_carriers.py <arm-label>=<run-id>
```

Then run the weak acceptance command and hidden oracle command in the arm's run
worktree.

## Done When

- DG-5.1 Arm E smoke evidence is preserved in
  `true-comparison-results.md`.
- The ledger clearly says the five-arm comparison is pending, not concluded.
- The next runnable slice is selected with concrete inputs, runner controls, and
  validation commands.
