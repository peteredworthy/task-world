# Graph-runner capability contract + claude_cli as a second graph runner — design

> Implements Priority 4 of `docs/dynamic-graph/re-evaluation-2026-07-18.md` §5.
> Scope: full onboarding — the capability contract *and* a working
> implementation of the graph callback contract in claude_cli, not just the
> contract definition.

## 1. Problem

`SUPPORTED_GRAPH_RUNNER_TYPES` in `workflow/graph_driver.py:66` is a
hand-maintained frozenset containing exactly `{CODEX_SERVER}`. The dispatch
layer itself (`StaticGraphAgentFactory`, `create_agent_runner`) is already
runner-agnostic — the frozenset is the only gate. Every graph run today rides
one runner from one vendor; a codex quota exhaustion or CLI regression stalls
the entire graph carrier, and the planned builder/verifier model-diversity A/B
(research OQ-1) is untestable without a second graph-capable runner.

The excluded runners lack a *callback delivery mechanism*, not a dispatch
seam. `codex_server` keeps a live in-process JSON-RPC session: when the LLM
calls a tool, the orchestrator directly awaits a Python closure
(`on_submit_graph_patch`, `on_grade`, etc.) in the same event loop as the
dispatch executor. `claude_cli` has no equivalent today — it is fire-and-forget
stdout piping. Its existing "callbacks" for `update_checklist`/`grade` aren't
closures at all: the LLM subprocess makes real HTTP or MCP calls straight to
the orchestrator's REST/MCP API, a path that never touches `runner.execute()`'s
closures. The one exception, `on_submit`, fires automatically when the
subprocess exits — not from a tool call. So making claude_cli graph-capable
requires new plumbing to deliver `graph_patch_callback` (and `grade`, for
verifier nodes) into that closure-based world — not just flipping a flag.

All 14 graph tools an LLM can call (`submit_graph_patch` plus 13 "macro"
tools — `create_work_region`, `attach_verifier`, `attach_check`,
`create_gap_planner`, `create_join`, `request_gate`, `retire_or_supersede`,
`create_corrective_region`, etc.) already normalize through **one** shared
closure, `graph_patch_callback` — `route_tool_call`/`_normalize_macro_tool_payload`
in `runners/agents/codex/common.py` (despite the module name, this logic is
not codex-specific) turn every one of them into a patch envelope before
calling it. The real contract is smaller than "14 tools": it's "can this
runner deliver `graph_patch_callback` and `grade` calls in-process."

## 2. Goals / non-goals

**Goals:**
- Replace the hardcoded frozenset with a declared per-runner capability.
- Give `claude_cli` (the `claude` command specifically, via `cli_subprocess`)
  a real, working implementation of the graph callback contract, so a graph
  run can select it and make progress through planner/builder/verifier/
  gap-planner nodes exactly as it does with `codex_server` today.
- Extract the shared tool-routing/normalization logic out of
  `codex/common.py` into a runner-agnostic module, since claude_cli needs the
  identical normalization codex_server uses (targeted cleanup, not a
  separate project — the misplacement directly blocks reuse).

**Non-goals (explicitly deferred):**
- `codex exec` via `cli_subprocess` becoming graph-capable. Treating
  `cli_subprocess` as one capability unit (per human steer) means it is
  nominally graph-eligible, but the new MCP wiring only activates when the
  underlying command is `claude` (existing `_args_with_mcp_config` gate).
  Running a graph node with `cli_subprocess` configured for `codex exec`
  would pass the capability check but get no tool delivery — a known,
  accepted gap, not solved by this work.
- OpenHands capability assessment (doc explicitly calls this out as separate
  work — its executor loop predates the graph carrier entirely).
- Any change to `codex_server`'s own behavior.
- The REST callback_channel gaining graph-tool support. Graph tool delivery
  for claude_cli is MCP-only in this design.

## 3. Capability contract

Replace `SUPPORTED_GRAPH_RUNNER_TYPES = frozenset({CODEX_SERVER})` with a
value derived from a declared flag on each agent class:

- `CodexServerAgent.GRAPH_CAPABLE = True`
- `CLIAgent.GRAPH_CAPABLE = True`
- Absent on any other agent class → treated as `False` (OpenHands stays
  excluded without change).

`graph_driver.py` derives the supported set from the runner registry
(`create_agent_runner`'s registration mechanism) by reading this flag off
each registered agent class, rather than a hand-maintained frozenset. This
follows the project's existing "capability/policy as data" convention (e.g.
`payload_registry.py`).

## 4. Graph tool delivery for claude_cli

### 4.1 Shared routing logic extraction

Move `route_tool_call`, `_normalize_macro_tool_payload`, `GRAPH_MACRO_TOOL_NAMES`,
and `_normalize_patch_payload` out of `runners/agents/codex/common.py` into a
new `runners/graph_tool_routing.py`. `codex/common.py` imports from there
unchanged — this is a mechanical move (no behavior change), done so
claude_cli's new MCP tool handlers can call the exact same normalization
codex_server already relies on, instead of duplicating it.

### 4.2 Per-execution registry

`GraphDispatchExecutor._run_agent` gains a small in-memory registry:

```python
@dataclass
class GraphNodeCallbacks:
    on_submit_graph_patch: GraphPatchCallback
    on_grade: GradeCallback | None
```

Keyed by `(run_id, node_id)`. Registered immediately before
`runner.execute()`, removed in a `finally` around that call — the registry's
entire lifecycle is contained within one `_run_agent` invocation. No new
cross-request state, no separate cleanup path to get wrong. If the
orchestrator process crashes mid-execution, the whole in-memory registry
disappears with it — consistent with how all other in-flight graph dispatch
state already recovers today, via `agent_died` reconciliation on restart.

Concurrency note: the graph kernel's lease model already guarantees at most
one active execution per node, so `(run_id, node_id)` collisions should not
occur; if the invariant is ever violated elsewhere, last-write-wins on the
registry entry is an acceptable (not silently unsafe) behavior, not something
this layer needs to defend against independently.

### 4.3 New MCP tools

Add to the orchestrator's existing MCP server (`api/mcp/tools.py`):
`submit_graph_patch` plus the 13 macro tool names, plus a graph-scoped
`grade`. Each takes `run_id` and the node's ID as explicit arguments — no new
prompt plumbing needed, since `GraphDispatchExecutor._execution_context`
already sets `ExecutionContext.task_id` to the node ID for graph-dispatched
nodes (`node.get("task_id") or node.get("task_region_id") or context.node_id`),
and that value is already shown to the LLM as "Task ID" in the existing
prompt. Handlers look up the `(run_id, node_id)` registry; a miss (wrong IDs,
or a node that already finished/was reassigned) returns a clean tool-result
error, not a crash, matching how `route_tool_call` already raises `ValueError`
for a disallowed tool name today.

### 4.4 Wiring into CLIAgent

When `context.graph_patch_callback is not None`, `CLIAgent`:
- Adds the orchestrator's own graph-tool MCP endpoint into the
  `--mcp-config` it already writes via `_write_mcp_json`, alongside any
  routine-declared external `context.mcp_servers`.
- Appends prompt instructions describing the graph tools — same spirit as
  the deleted `_graph_patch_bridge_section`, but describing native MCP tool
  calls instead of a stdout sentinel format.

This wiring is gated on `Path(self._command).name == "claude"`, the same
existing check `_args_with_mcp_config` already uses to decide whether to
pass `--mcp-config`/`--tools` at all — consistent with §2's non-goal for
`codex exec`.

### 4.5 Auth

Graph-tool MCP calls carry the same `context.auth_token` bearer mechanism
already used for MCP-mode callbacks. The registry lookup is a second,
natural scope check: even a valid token can't act on a `(run_id, node_id)`
that isn't currently live.

## 5. Testing

- Unit: capability-contract derivation yields the expected supported set
  (`{CODEX_SERVER, CLI_SUBPROCESS}`) given the declared flags.
- Unit: the extracted `graph_tool_routing` module — existing codex tests
  continue to pass against the new import path unchanged.
- Unit: new MCP tool handlers — registry hit invokes the correct closure
  with the correctly normalized payload; registry miss errors cleanly
  without raising an uncaught exception.
- Integration: a claude_cli-dispatched builder node submits a graph patch
  end-to-end through the new MCP path using a fake local MCP transport (no
  live subprocess), landing via `GraphController` exactly as it does for
  codex_server today.
- At least one small "second runner" smoke test per node role (planner,
  builder, verifier) confirming behavioral parity with `codex_server` —
  not a duplication of the full FR-01..18 suite for a second runner.

## 6. Naming decision

The new graph-scoped grade tool is named `graph_grade`, distinct from the
existing legacy-task tool `orchestrator_set_grade`. They back genuinely
different code paths — a DB-backed checklist write versus a registry-routed
closure call — and a single run is always either legacy or graph end-to-end,
so there is no session that would need both. Keeping them as separate,
unambiguous tool names avoids a fallback-through-registry-miss path that
would blur real errors (wrong node ID) with intentional legacy/graph
disambiguation.

## 7. Open questions carried into implementation planning

- Exact MCP tool JSON schemas for the 13 macro tools on claude_cli's side —
  should mirror codex's existing tool specs in `codex/common.py` (now moved)
  as closely as possible for prompt/behavior parity.
