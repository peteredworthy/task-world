# Graph-Runner Capability Contract + claude_cli as a Second Graph Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `SUPPORTED_GRAPH_RUNNER_TYPES` frozenset with a declared per-runner capability, and make `claude_cli` a real, working second graph-capable runner by giving it a way to deliver `submit_graph_patch`/macro-tool/`grade` calls into the graph dispatcher's in-process callback closures.

**Architecture:** A new per-execution MCP tool server is created fresh inside `GraphDispatchExecutor._run_agent` for every claude_cli-dispatched planner/verifier execution, with tool handlers that close directly over that execution's `on_submit_graph_patch`/`on_grade` callables. It's registered under an unguessable token in a small in-memory `GraphMcpExecutionRegistry`, exposed over HTTP by a single long-lived ASGI dispatcher (`GraphMcpDispatcher`, mirroring the existing `_ScopedMcpDispatcher` pattern already in `api/app.py`) mounted once at app startup, and unregistered in a `finally` when the execution ends. `CLIAgent` is told the resulting per-execution URL via a new `ExecutionContext.graph_mcp_url` field and adds it to the `--mcp-config` it already writes.

**Tech Stack:** Python, FastAPI/Starlette, the `mcp` Python SDK's `FastMCP`, pytest, httpx `AsyncClient` for integration tests.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-21-graph-runner-capability-contract-design.md` exactly; where this plan and the spec conflict on a factual codebase detail (see the correction note below), this plan wins because it was written against the actual code.
- **Spec correction:** the spec's §1/§4.3 reference "13 macro tools." The actual count in `GRAPH_MACRO_TOOL_NAMES` (`runners/agents/codex/common.py:43-54`) is **8**: `create_work_region`, `create_corrective_region`, `attach_verifier`, `attach_check`, `create_gap_planner`, `create_join`, `request_gate`, `retire_or_supersede`. Plus `submit_graph_patch` itself, that's 9 graph-patch-related tools. Task 0 below fixes the spec's wording to match.
- `codex exec` via `cli_subprocess` stays graph-incapable in practice even though the capability flag makes `CLI_SUBPROCESS` nominally eligible — the MCP wiring is gated on `Path(command).name == "claude"`. Do not try to "fix" this; it's an accepted, documented gap (spec §2).
- No change to `codex_server`'s own runtime behavior. It keeps using its existing JSON-RPC in-process callback path untouched.
- `uv run pytest`, `uv run ruff check .`, `uv run pyright` must all stay green after every task (this repo's pre-commit hooks already enforce this on `git commit`, per `AGENTS.md`).
- Use `uv run` for every Python command, never bare `python`/`pytest`.

---

## Task 0: Fix the macro-tool count in the design spec

**Files:**
- Modify: `docs/superpowers/specs/2026-07-21-graph-runner-capability-contract-design.md`

**Interfaces:** none — documentation only.

- [ ] **Step 1: Correct the tool count**

Replace every occurrence of "13 macro tools"/"13 'macro' tools" in the spec with "8 macro tools", and replace "`submit_graph_patch` plus 13 macro tool names" (§4.3) with "`submit_graph_patch` plus the 8 macro tool names (`create_work_region`, `create_corrective_region`, `attach_verifier`, `attach_check`, `create_gap_planner`, `create_join`, `request_gate`, `retire_or_supersede`)".

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-07-21-graph-runner-capability-contract-design.md
git commit -m "docs: correct macro-tool count in graph-runner spec (8, not 13)"
```

---

## Task 1: Capability contract — declared `graph_capable` flag on the runner registry

**Files:**
- Modify: `src/orchestrator/runners/agent_factory.py`
- Modify: `src/orchestrator/runners/agents/codex/__init__.py`
- Modify: `src/orchestrator/runners/agents/claude_cli/__init__.py`
- Modify: `src/orchestrator/workflow/graph_driver.py:60-70,355-358`
- Test: `tests/unit/test_agent_factory.py` (new)
- Test: `tests/unit/test_graph_driver_capability.py` (new)

**Interfaces:**
- Produces: `agent_factory.register(agent_runner_type, factory, *, graph_capable=False)`, `agent_factory.get_graph_capable_agent_runner_types() -> frozenset[AgentRunnerType]`.
- Consumes (later tasks): nothing new consumes this beyond `graph_driver.py`.

The existing registry (`agent_factory.py:38`) is `_REGISTRY: dict[AgentRunnerType, AgentFactory]`, populated by `register()` calls in each agent sub-package's `__init__.py` when `discover_agents()` imports them. There is no agent *class* reference in the registry, only factory functions — so the capability flag has to live alongside the factory registration, not as a class attribute (this differs slightly from spec §3's "declared flag on each agent class" framing; functionally equivalent, but implemented against the registry's actual shape).

- [ ] **Step 1: Write the failing unit tests for the registry extension**

Create `tests/unit/test_agent_factory.py`:

```python
"""Unit tests for the graph-capability extension to the agent factory registry."""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.config.enums import AgentRunnerType
from orchestrator.runners import agent_factory


@pytest.fixture(autouse=True)
def _clear_registry() -> Any:
    agent_factory.clear_registry()
    yield
    agent_factory.clear_registry()


def _noop_factory(agent_runner_config: dict[str, Any], **kwargs: Any) -> Any:
    return object()


def test_register_defaults_to_not_graph_capable() -> None:
    agent_factory.register(AgentRunnerType.OPENHANDS_LOCAL, _noop_factory)
    assert AgentRunnerType.OPENHANDS_LOCAL not in agent_factory.get_graph_capable_agent_runner_types()


def test_register_graph_capable_true_is_tracked() -> None:
    agent_factory.register(AgentRunnerType.CODEX_SERVER, _noop_factory, graph_capable=True)
    assert AgentRunnerType.CODEX_SERVER in agent_factory.get_graph_capable_agent_runner_types()


def test_get_graph_capable_agent_runner_types_is_a_snapshot() -> None:
    agent_factory.register(AgentRunnerType.CODEX_SERVER, _noop_factory, graph_capable=True)
    snapshot = agent_factory.get_graph_capable_agent_runner_types()
    agent_factory.register(AgentRunnerType.CLI_SUBPROCESS, _noop_factory, graph_capable=True)
    assert AgentRunnerType.CLI_SUBPROCESS not in snapshot
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_agent_factory.py -v`
Expected: FAIL — `register() got an unexpected keyword argument 'graph_capable'` (or `AttributeError` on `get_graph_capable_agent_runner_types`).

- [ ] **Step 3: Implement the registry extension**

In `src/orchestrator/runners/agent_factory.py`, replace:

```python
# Global registry: AgentRunnerType -> factory callable
_REGISTRY: dict[AgentRunnerType, AgentFactory] = {}


def register(agent_runner_type: AgentRunnerType, factory: AgentFactory) -> None:
    """Register an agent factory for a given type."""
    _REGISTRY[agent_runner_type] = factory
    logger.debug("Registered agent factory for %s", agent_runner_type.value)
```

with:

```python
# Global registry: AgentRunnerType -> factory callable
_REGISTRY: dict[AgentRunnerType, AgentFactory] = {}

# Runner types whose adapter implements the graph callback contract (patch
# submission, grade). Declared at registration time alongside the factory,
# rather than a hand-maintained frozenset elsewhere — see graph_driver.py's
# get_supported_graph_runner_types().
_GRAPH_CAPABLE: dict[AgentRunnerType, bool] = {}


def register(
    agent_runner_type: AgentRunnerType,
    factory: AgentFactory,
    *,
    graph_capable: bool = False,
) -> None:
    """Register an agent factory for a given type.

    Args:
        graph_capable: Whether this runner's adapter can deliver graph
            callback tool calls (submit_graph_patch and friends, grade) into
            the graph dispatcher's in-process closures. Defaults to False.
    """
    _REGISTRY[agent_runner_type] = factory
    _GRAPH_CAPABLE[agent_runner_type] = graph_capable
    logger.debug(
        "Registered agent factory for %s (graph_capable=%s)",
        agent_runner_type.value,
        graph_capable,
    )
```

Then add, after `get_registered_agent_runner_types`:

```python
def get_graph_capable_agent_runner_types() -> frozenset[AgentRunnerType]:
    """Return an immutable snapshot of runner types declared graph-capable."""
    return frozenset(
        runner_type for runner_type, capable in _GRAPH_CAPABLE.items() if capable
    )
```

And update `clear_registry` to also clear `_GRAPH_CAPABLE`:

```python
def clear_registry() -> None:
    """Clear all registered factories (for testing)."""
    _REGISTRY.clear()
    _GRAPH_CAPABLE.clear()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_agent_factory.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Mark codex_server and claude_cli as graph-capable at their registration call sites**

In `src/orchestrator/runners/agents/codex/__init__.py`, change:

```python
register(AgentRunnerType.CODEX_SERVER, create_codex_agent)
```

to:

```python
register(AgentRunnerType.CODEX_SERVER, create_codex_agent, graph_capable=True)
```

In `src/orchestrator/runners/agents/claude_cli/__init__.py`, change:

```python
register(AgentRunnerType.CLI_SUBPROCESS, create_cli_agent)
```

to:

```python
register(AgentRunnerType.CLI_SUBPROCESS, create_cli_agent, graph_capable=True)
```

- [ ] **Step 6: Write the failing test for `graph_driver.py`'s derived set**

Create `tests/unit/test_graph_driver_capability.py`:

```python
"""Unit tests for graph_driver's capability-derived supported runner set."""

from __future__ import annotations

from orchestrator.config.enums import AgentRunnerType
from orchestrator.runners.agents import discover as discover_agents
from orchestrator.workflow.graph_driver import get_supported_graph_runner_types

discover_agents()


def test_codex_server_is_supported() -> None:
    assert AgentRunnerType.CODEX_SERVER in get_supported_graph_runner_types()


def test_cli_subprocess_is_supported() -> None:
    assert AgentRunnerType.CLI_SUBPROCESS in get_supported_graph_runner_types()


def test_openhands_local_is_not_supported() -> None:
    assert AgentRunnerType.OPENHANDS_LOCAL not in get_supported_graph_runner_types()
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_graph_driver_capability.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_supported_graph_runner_types'`

- [ ] **Step 8: Replace the hardcoded frozenset with a function**

In `src/orchestrator/workflow/graph_driver.py`, replace (around line 66):

```python
SUPPORTED_GRAPH_RUNNER_TYPES = frozenset(
    {
        AgentRunnerType.CODEX_SERVER,
    }
)
```

with:

```python
def get_supported_graph_runner_types() -> frozenset[AgentRunnerType]:
    """Return runner types the graph carrier can dispatch to right now.

    Derived from each runner's declared capability at registration time
    (``agent_factory.register(..., graph_capable=True)``), not a
    hand-maintained list — see ``runners/agent_factory.py``.
    """
    from orchestrator.runners.agent_factory import get_graph_capable_agent_runner_types

    return get_graph_capable_agent_runner_types()
```

Then update the one call site (around line 355):

```python
        if run.agent_runner_type not in SUPPORTED_GRAPH_RUNNER_TYPES:
            supported = ", ".join(
                sorted(runner_type.value for runner_type in SUPPORTED_GRAPH_RUNNER_TYPES)
            )
```

to:

```python
        supported_graph_runner_types = get_supported_graph_runner_types()
        if run.agent_runner_type not in supported_graph_runner_types:
            supported = ", ".join(
                sorted(runner_type.value for runner_type in supported_graph_runner_types)
            )
```

This must be evaluated at call time, not at module import time — `discover_agents()` (which populates the registry) is called during app startup, and a module-level constant computed at import time could run before that, silently yielding an empty set.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_graph_driver_capability.py tests/unit/test_agent_factory.py -v`
Expected: PASS (6 tests total)

- [ ] **Step 10: Run the full existing graph_driver test suite to check for regressions**

Run: `uv run pytest tests/unit/test_graph_driver*.py tests/integration/test_graph_fr*.py -q`
Expected: PASS, no regressions (these exercise the "unsupported runner" pause-with-message behavior, which is unchanged in shape, just computed differently)

- [ ] **Step 11: Commit**

```bash
git add src/orchestrator/runners/agent_factory.py \
        src/orchestrator/runners/agents/codex/__init__.py \
        src/orchestrator/runners/agents/claude_cli/__init__.py \
        src/orchestrator/workflow/graph_driver.py \
        tests/unit/test_agent_factory.py \
        tests/unit/test_graph_driver_capability.py
git commit -m "feat: derive graph-capable runner set from declared registry capability"
```

---

## Task 2: Extract graph-tool routing/normalization into a runner-agnostic module

**Files:**
- Create: `src/orchestrator/runners/graph_tool_routing.py`
- Modify: `src/orchestrator/runners/agents/codex/common.py:43-54,1171-1321`
- Test: `tests/unit/test_graph_tool_routing.py` (new — moved assertions from wherever `route_tool_call`/`_normalize_macro_tool_payload` are exercised today via `codex/common.py`)

**Interfaces:**
- Produces: `graph_tool_routing.GRAPH_MACRO_TOOL_NAMES: frozenset[str]`, `graph_tool_routing.route_tool_call(...)` (same signature as today), `graph_tool_routing.normalize_macro_tool_payload(tool_name, args) -> dict[str, Any]` (renamed from private `_normalize_macro_tool_payload` since it's now a public cross-module API), `graph_tool_routing.normalize_patch_payload(args) -> dict[str, Any]` (renamed from `_normalize_patch_payload`).
- Consumes (Task 6): claude_cli's per-execution MCP tool handlers call `graph_tool_routing.route_tool_call(...)` directly.

This is a mechanical move — no behavior change. `codex/common.py` keeps working by importing from the new location and re-exporting under the same (private, underscore) names it used before, so nothing else in `codex/common.py` or its callers needs to change.

- [ ] **Step 1: Confirm current behavior with existing tests before moving anything**

Run: `uv run pytest tests/unit/test_codex_server_parity.py tests/integration/test_codex_server_callbacks.py -q`
Expected: PASS (these already exercise `route_tool_call` indirectly through `CodexServerAgent._route_tool_call`)

- [ ] **Step 2: Create the new module with the moved code**

Create `src/orchestrator/runners/graph_tool_routing.py`. Copy the following from `codex/common.py` verbatim, renaming the two previously-private functions to public names:

```python
"""Graph tool call routing and payload normalization.

Shared by every graph-capable runner adapter (codex_server, claude_cli).
All graph tools an LLM can call — ``submit_graph_patch`` plus 8 "macro"
tools that create/attach graph nodes and regions — normalize through the
same ``GraphPatchCallback`` (a single closure the graph dispatcher builds
per in-flight execution). This module owns that normalization so no
adapter has to duplicate it.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from orchestrator.config.enums import ChecklistStatus
from orchestrator.runners.types import (
    ChecklistUpdateCallback,
    CompleteRecoveryCallback,
    GradeCallback,
    GraphPatchCallback,
    SubmitCallback,
)

logger = logging.getLogger(__name__)

GRAPH_MACRO_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "create_work_region",
        "create_corrective_region",
        "attach_verifier",
        "attach_check",
        "create_gap_planner",
        "create_join",
        "request_gate",
        "retire_or_supersede",
    }
)

CODEX_SERVER_TOOL_ALLOWLIST_PLACEHOLDER = None  # not moved — stays in codex/common.py


def is_allowed_tool(tool_name: str, allowlist: frozenset[str]) -> bool:
    return tool_name in allowlist


def enforce_tool_allowlist(tool_name: str, allowlist: frozenset[str]) -> None:
    if not is_allowed_tool(tool_name, allowlist):
        raise ValueError(f"Tool '{tool_name}' is not on the allow-list")


async def route_tool_call(
    tool_name: str,
    args: dict[str, Any],
    on_checklist_update: ChecklistUpdateCallback,
    on_submit: SubmitCallback,
    on_submit_graph_patch: GraphPatchCallback | None = None,
    on_grade: GradeCallback | None = None,
    on_complete_recovery: CompleteRecoveryCallback | None = None,
    *,
    allowlist: frozenset[str],
    agent_label: str = "GraphRunner",
) -> str:
    """Route an allow-listed callback tool call to the appropriate callback.

    Tool routing:
    - ``update_checklist`` -> ``on_checklist_update(req_id, status, note)``
    - ``submit``           -> ``on_submit()``
    - ``submit_graph_patch`` -> ``on_submit_graph_patch(payload)``
    - a name in ``GRAPH_MACRO_TOOL_NAMES`` -> ``on_submit_graph_patch(payload)``
      after macro-specific normalization
    - ``grade``            -> ``on_grade(req_id, grade, grade_reason)`` (verifier only)
    - ``request_clarification`` -> logged; no callback
    - ``complete_recovery`` -> ``on_complete_recovery(outcome, notes)``

    Raises:
        ValueError: If ``tool_name`` is not on ``allowlist``.
    """
    enforce_tool_allowlist(tool_name, allowlist)

    if tool_name == "update_checklist":
        req_id: str = str(args.get("req_id", "")).strip()
        if not req_id:
            raise ValueError("update_checklist requires a non-empty 'req_id'")
        raw_status: str = str(args.get("status", "done"))
        note: str | None = args.get("note")
        status = ChecklistStatus(raw_status)
        await on_checklist_update(req_id, status, note)
        return ""

    if tool_name == "submit":
        await on_submit()
        return ""

    if tool_name == "submit_graph_patch":
        if on_submit_graph_patch is None:
            raise ValueError("submit_graph_patch is not registered for this session")
        payload = normalize_patch_payload(args)
        return await on_submit_graph_patch(payload)

    if tool_name in GRAPH_MACRO_TOOL_NAMES:
        if on_submit_graph_patch is None:
            raise ValueError(f"{tool_name} is not registered for this session")
        payload = normalize_macro_tool_payload(tool_name, args)
        return await on_submit_graph_patch(payload)

    if tool_name == "grade":
        if on_grade is not None:
            req_id = str(args.get("req_id", "")).strip()
            grade: str = str(args.get("grade", "")).strip()
            if not req_id:
                raise ValueError("grade requires a non-empty 'req_id'")
            if not grade:
                raise ValueError("grade requires a non-empty 'grade'")
            grade_reason: str | None = args.get("grade_reason")
            await on_grade(req_id, grade, grade_reason)
        else:
            logger.warning("%s: 'grade' tool called in builder phase — ignoring", agent_label)
        return ""

    if tool_name == "request_clarification":
        question: str = str(args.get("question", ""))
        logger.info("%s: request_clarification received — question=%r", agent_label, question)
        return ""

    if tool_name == "complete_recovery":
        outcome: str = str(args.get("outcome", "retry"))
        notes: str | None = args.get("notes")
        if on_complete_recovery is not None:
            await on_complete_recovery(outcome, notes)
        else:
            logger.info(
                "%s: complete_recovery called (outcome=%r) but no callback registered — ignoring",
                agent_label,
                outcome,
            )
        return ""

    return ""


def normalize_macro_tool_payload(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    patch_id = args.get("patch_id")
    base_graph_position = args.get("base_graph_position")
    if not isinstance(patch_id, str) or not patch_id.strip():
        raise ValueError(f"{tool_name} requires a non-empty patch_id")
    if not isinstance(base_graph_position, int):
        raise ValueError(f"{tool_name} requires integer base_graph_position")

    macro_args = {
        key: value
        for key, value in args.items()
        if key not in {"patch_id", "base_graph_position", "rationale_record_id"}
    }
    payload: dict[str, Any] = {
        "patch_id": patch_id,
        "base_graph_position": base_graph_position,
        "macro_invocations": [{"macro": tool_name, "args": macro_args}],
    }
    rationale_record_id = args.get("rationale_record_id")
    if isinstance(rationale_record_id, str):
        payload["rationale_record_id"] = rationale_record_id
    return payload


def normalize_patch_payload(args: dict[str, Any]) -> dict[str, Any]:
    """Normalize planner patch arguments into a top-level PatchEnvelope payload."""
    if "patch" in args:
        if len(args) != 1:
            raise ValueError("submit_graph_patch accepts either `patch` or patch fields, not both")
        raw_patch = args.get("patch")
        if not isinstance(raw_patch, dict):
            raise ValueError("submit_graph_patch requires `patch` to be an object")
        patch = cast(dict[str, Any], raw_patch)
        patch_id = patch.get("patch_id")
        base_graph_position = patch.get("base_graph_position")
        ops = patch.get("ops")
        rationale_record_id = patch.get("rationale_record_id")
    else:
        patch_id = args.get("patch_id")
        base_graph_position = args.get("base_graph_position")
        ops = args.get("ops")
        rationale_record_id = args.get("rationale_record_id")

    if not isinstance(patch_id, str) or not patch_id.strip():
        raise ValueError("submit_graph_patch requires a non-empty patch_id")
    if not isinstance(base_graph_position, int):
        raise ValueError("submit_graph_patch requires integer base_graph_position")
    if not isinstance(ops, list):
        raise ValueError("submit_graph_patch requires an ops list")

    payload: dict[str, Any] = {
        "patch_id": patch_id,
        "base_graph_position": base_graph_position,
        "ops": ops,
    }
    if isinstance(rationale_record_id, str):
        payload["rationale_record_id"] = rationale_record_id
    return payload
```

Delete the stray `CODEX_SERVER_TOOL_ALLOWLIST_PLACEHOLDER` line above before saving — it was a note-to-self while drafting this step, not real code.

- [ ] **Step 3: Update `codex/common.py` to import from the new module instead of defining these itself**

In `src/orchestrator/runners/agents/codex/common.py`, remove the `GRAPH_MACRO_TOOL_NAMES` definition (lines 43-54) and the `route_tool_call`, `_normalize_macro_tool_payload`, `_normalize_patch_payload` function bodies (lines 1171-1321), replacing them with imports and thin wrappers that preserve `codex/common.py`'s existing public signature (which passes no `allowlist` param — it always used `CODEX_SERVER_TOOL_ALLOWLIST` implicitly):

```python
from orchestrator.runners.graph_tool_routing import (
    GRAPH_MACRO_TOOL_NAMES,
    normalize_macro_tool_payload as _normalize_macro_tool_payload,
    normalize_patch_payload as _normalize_patch_payload,
    route_tool_call as _route_tool_call_impl,
)


async def route_tool_call(
    tool_name: str,
    args: dict[str, Any],
    on_checklist_update: ChecklistUpdateCallback,
    on_submit: SubmitCallback,
    on_submit_graph_patch: GraphPatchCallback | None = None,
    on_grade: GradeCallback | None = None,
    on_complete_recovery: CompleteRecoveryCallback | None = None,
    *,
    agent_label: str = "CodexServer",
) -> str:
    """Route an allow-listed callback tool call to the appropriate callback.

    Thin wrapper over ``graph_tool_routing.route_tool_call`` binding the
    codex-server-specific ``CODEX_SERVER_TOOL_ALLOWLIST``.
    """
    return await _route_tool_call_impl(
        tool_name,
        args,
        on_checklist_update,
        on_submit,
        on_submit_graph_patch=on_submit_graph_patch,
        on_grade=on_grade,
        on_complete_recovery=on_complete_recovery,
        allowlist=CODEX_SERVER_TOOL_ALLOWLIST,
        agent_label=agent_label,
    )
```

Place this where the old `route_tool_call` function was (after `CODEX_SERVER_TOOL_ALLOWLIST` is defined, since the wrapper references it — `CODEX_SERVER_TOOL_ALLOWLIST` is already defined earlier in the file at line 898, before line 1171, so no reordering is needed). Remove the now-unused `enforce_tool_allowlist`/`is_allowed_tool` definitions from `codex/common.py` if nothing else in that file calls them directly (check with the grep in Step 4 below before deleting).

- [ ] **Step 4: Check for other direct importers of the moved private names**

Run: `grep -rn "_normalize_macro_tool_payload\|_normalize_patch_payload\|GRAPH_MACRO_TOOL_NAMES\|enforce_tool_allowlist\|is_allowed_tool" src/ tests/`

Expected: all remaining references are either the new `graph_tool_routing.py` module itself, `codex/common.py`'s wrapper/import lines from Step 3, or test files importing from `codex.common` — those test imports must keep working unchanged since `codex/common.py` still exposes `GRAPH_MACRO_TOOL_NAMES` (re-imported) and `_normalize_macro_tool_payload`/`_normalize_patch_payload` (aliased on import in Step 3).

- [ ] **Step 5: Run the full existing codex test suite to confirm zero behavior change**

Run: `uv run pytest tests/unit/test_codex_server_parity.py tests/unit/test_executor_codex.py tests/integration/test_codex_server_callbacks.py tests/integration/test_codex_lifecycle.py -q`
Expected: PASS, identical to before the move (58 passed, per the deletion-sweep session's earlier run of this exact set)

- [ ] **Step 6: Write new direct unit tests for the extracted module**

Create `tests/unit/test_graph_tool_routing.py`:

```python
"""Unit tests for the runner-agnostic graph tool routing module."""

from __future__ import annotations

import pytest

from orchestrator.config import ChecklistStatus
from orchestrator.runners.graph_tool_routing import (
    GRAPH_MACRO_TOOL_NAMES,
    normalize_macro_tool_payload,
    normalize_patch_payload,
    route_tool_call,
)

_ALLOWLIST = frozenset({"submit_graph_patch", "grade", "update_checklist", "submit"} | GRAPH_MACRO_TOOL_NAMES)


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


def test_normalize_patch_payload_raw_fields() -> None:
    payload = normalize_patch_payload(
        {"patch_id": "p1", "base_graph_position": 3, "ops": []}
    )
    assert payload == {"patch_id": "p1", "base_graph_position": 3, "ops": []}


def test_normalize_patch_payload_nested_patch() -> None:
    payload = normalize_patch_payload(
        {"patch": {"patch_id": "p1", "base_graph_position": 3, "ops": []}}
    )
    assert payload == {"patch_id": "p1", "base_graph_position": 3, "ops": []}


def test_normalize_macro_tool_payload_wraps_as_macro_invocation() -> None:
    payload = normalize_macro_tool_payload(
        "create_work_region",
        {"patch_id": "p1", "base_graph_position": 3, "region_id": "r1"},
    )
    assert payload == {
        "patch_id": "p1",
        "base_graph_position": 3,
        "macro_invocations": [{"macro": "create_work_region", "args": {"region_id": "r1"}}],
    }


async def test_route_tool_call_rejects_disallowed_tool() -> None:
    with pytest.raises(ValueError, match="not on the allow-list"):
        await route_tool_call(
            "bash",
            {},
            _noop_checklist,
            _noop_submit,
            allowlist=_ALLOWLIST,
        )


async def test_route_tool_call_submit_graph_patch_calls_callback() -> None:
    calls: list[dict[str, object]] = []

    async def on_submit_graph_patch(payload: dict[str, object]) -> str:
        calls.append(payload)
        return "accepted"

    result = await route_tool_call(
        "submit_graph_patch",
        {"patch_id": "p1", "base_graph_position": 1, "ops": []},
        _noop_checklist,
        _noop_submit,
        on_submit_graph_patch=on_submit_graph_patch,
        allowlist=_ALLOWLIST,
    )
    assert result == "accepted"
    assert calls == [{"patch_id": "p1", "base_graph_position": 1, "ops": []}]


async def test_route_tool_call_macro_tool_calls_callback_with_normalized_payload() -> None:
    calls: list[dict[str, object]] = []

    async def on_submit_graph_patch(payload: dict[str, object]) -> str:
        calls.append(payload)
        return "accepted"

    await route_tool_call(
        "create_work_region",
        {"patch_id": "p1", "base_graph_position": 1, "region_id": "r1"},
        _noop_checklist,
        _noop_submit,
        on_submit_graph_patch=on_submit_graph_patch,
        allowlist=_ALLOWLIST,
    )
    assert calls == [
        {
            "patch_id": "p1",
            "base_graph_position": 1,
            "macro_invocations": [{"macro": "create_work_region", "args": {"region_id": "r1"}}],
        }
    ]
```

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `uv run pytest tests/unit/test_graph_tool_routing.py -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Full regression check**

Run: `uv run pytest tests/unit tests/integration -q`
Expected: PASS, no regressions
Run: `uv run ruff check .`
Expected: no issues
Run: `uv run pyright`
Expected: 0 errors

- [ ] **Step 9: Commit**

```bash
git add src/orchestrator/runners/graph_tool_routing.py \
        src/orchestrator/runners/agents/codex/common.py \
        tests/unit/test_graph_tool_routing.py
git commit -m "refactor: extract graph tool routing out of codex/common.py"
```

---

## Task 3: Add `ExecutionContext.graph_mcp_url`

**Files:**
- Modify: `src/orchestrator/runners/types.py:84-102`
- Test: `tests/unit/test_execution_context_graph_mcp_url.py` (new)

**Interfaces:**
- Produces: `ExecutionContext.graph_mcp_url: str | None = None`.
- Consumes (Task 6): `GraphDispatchExecutor._execution_context` sets this.
- Consumes (Task 7): `CLIAgent` reads this.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_execution_context_graph_mcp_url.py`:

```python
"""Unit test for the graph_mcp_url field on ExecutionContext."""

from __future__ import annotations

from orchestrator.runners.types import ExecutionContext


def test_graph_mcp_url_defaults_to_none() -> None:
    ctx = ExecutionContext(
        run_id="r1",
        task_id="t1",
        working_dir="/tmp",
        prompt="do the thing",
        requirements=[],
    )
    assert ctx.graph_mcp_url is None


def test_graph_mcp_url_can_be_set() -> None:
    ctx = ExecutionContext(
        run_id="r1",
        task_id="t1",
        working_dir="/tmp",
        prompt="do the thing",
        requirements=[],
        graph_mcp_url="http://localhost:8000/mcp-graph/abc123/sse",
    )
    assert ctx.graph_mcp_url == "http://localhost:8000/mcp-graph/abc123/sse"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_execution_context_graph_mcp_url.py -v`
Expected: FAIL — pydantic rejects the unexpected `graph_mcp_url` kwarg (or the first test trivially passes since accessing a missing attribute raises `AttributeError` — either way, at least one assertion fails before the field exists)

- [ ] **Step 3: Add the field**

In `src/orchestrator/runners/types.py`, in the `ExecutionContext` class, add after `graph_patch_callback`:

```python
    graph_patch_callback: GraphPatchCallback | None = None
    graph_mcp_url: str | None = None
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_execution_context_graph_mcp_url.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/runners/types.py tests/unit/test_execution_context_graph_mcp_url.py
git commit -m "feat: add ExecutionContext.graph_mcp_url field"
```

---

## Task 4: `GraphMcpExecutionRegistry`

**Files:**
- Create: `src/orchestrator/graph_runtime/graph_mcp_registry.py`
- Test: `tests/unit/test_graph_mcp_registry.py` (new)

**Interfaces:**
- Produces: `class GraphMcpExecutionRegistry` with `register(token: str, asgi_app: Any) -> None`, `unregister(token: str) -> None`, `get(token: str) -> Any | None`.
- Consumes (Task 5): `GraphMcpDispatcher` calls `.get(token)`.
- Consumes (Task 6): `GraphDispatchExecutor._run_agent` calls `.register(...)`/`.unregister(...)`.

Plain in-memory dict wrapper, deliberately with zero framework imports (no Starlette/FastAPI types) so `graph_runtime` stays decoupled from the web layer, matching `build_graph_runtime`'s own docstring ("Assemble graph controller and dispatch executor without API imports").

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_graph_mcp_registry.py`:

```python
"""Unit tests for GraphMcpExecutionRegistry."""

from __future__ import annotations

from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry


def test_get_returns_none_for_unknown_token() -> None:
    registry = GraphMcpExecutionRegistry()
    assert registry.get("unknown-token") is None


def test_register_then_get_returns_the_same_app() -> None:
    registry = GraphMcpExecutionRegistry()
    sentinel = object()
    registry.register("tok1", sentinel)
    assert registry.get("tok1") is sentinel


def test_unregister_removes_the_entry() -> None:
    registry = GraphMcpExecutionRegistry()
    registry.register("tok1", object())
    registry.unregister("tok1")
    assert registry.get("tok1") is None


def test_unregister_unknown_token_is_a_no_op() -> None:
    registry = GraphMcpExecutionRegistry()
    registry.unregister("never-registered")  # must not raise
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_graph_mcp_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.graph_runtime.graph_mcp_registry'`

- [ ] **Step 3: Implement**

Create `src/orchestrator/graph_runtime/graph_mcp_registry.py`:

```python
"""In-memory registry of live per-execution graph MCP ASGI apps.

Populated by ``GraphDispatchExecutor`` for the lifetime of one claude_cli
graph-node execution and read by ``api.mcp.graph_dispatcher`` to forward
incoming HTTP requests to the right execution's tool handlers. Deliberately
framework-free (no Starlette/FastAPI imports) so ``graph_runtime`` stays
decoupled from the web layer.
"""

from __future__ import annotations

from typing import Any


class GraphMcpExecutionRegistry:
    """Maps an unguessable per-execution token to its live ASGI MCP app."""

    def __init__(self) -> None:
        self._apps: dict[str, Any] = {}

    def register(self, token: str, asgi_app: Any) -> None:
        self._apps[token] = asgi_app

    def unregister(self, token: str) -> None:
        self._apps.pop(token, None)

    def get(self, token: str) -> Any | None:
        return self._apps.get(token)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_graph_mcp_registry.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/graph_runtime/graph_mcp_registry.py tests/unit/test_graph_mcp_registry.py
git commit -m "feat: add GraphMcpExecutionRegistry"
```

---

## Task 5: `GraphMcpDispatcher` ASGI wrapper mounted at `/mcp-graph`

**Files:**
- Create: `src/orchestrator/api/mcp/graph_dispatcher.py`
- Modify: `src/orchestrator/api/app.py:872-990` (the `_mount_mcp_sse` function and its call site at line 825)
- Test: `tests/integration/test_graph_mcp_dispatcher.py` (new)

**Interfaces:**
- Produces: `class GraphMcpDispatcher` (ASGI callable), `_mount_mcp_sse(app, auth_config, graph_mcp_registry)` (signature change — one new required param).
- Consumes: `GraphMcpExecutionRegistry` from Task 4.

Mirrors the existing `_ScopedMcpDispatcher` in `app.py` (path-segment parsing, `root_path`/`path` rewriting for SSE, 404 on miss) but keys off a registry lookup instead of a lazily-cached dict of scope-name-to-server.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_graph_mcp_dispatcher.py`:

```python
"""Integration tests for the per-execution graph MCP dispatcher route."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from orchestrator.api.mcp.graph_dispatcher import GraphMcpDispatcher
from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry


def _fake_sub_app() -> Starlette:
    async def handler(request: object) -> PlainTextResponse:
        return PlainTextResponse("ok-from-fake-sub-app")

    return Starlette(routes=[Route("/sse", handler)])


async def test_unknown_token_returns_404() -> None:
    registry = GraphMcpExecutionRegistry()
    dispatcher = GraphMcpDispatcher(registry)
    transport = ASGITransport(app=dispatcher)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/mcp-graph/unknown-token/sse")
    assert resp.status_code == 404


async def test_registered_token_forwards_to_its_app() -> None:
    registry = GraphMcpExecutionRegistry()
    registry.register("tok1", _fake_sub_app())
    dispatcher = GraphMcpDispatcher(registry)
    transport = ASGITransport(app=dispatcher)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/mcp-graph/tok1/sse")
    assert resp.status_code == 200
    assert resp.text == "ok-from-fake-sub-app"


async def test_unregistering_then_calling_returns_404() -> None:
    registry = GraphMcpExecutionRegistry()
    registry.register("tok1", _fake_sub_app())
    registry.unregister("tok1")
    dispatcher = GraphMcpDispatcher(registry)
    transport = ASGITransport(app=dispatcher)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/mcp-graph/tok1/sse")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_graph_mcp_dispatcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.api.mcp.graph_dispatcher'`

- [ ] **Step 3: Implement the dispatcher**

Create `src/orchestrator/api/mcp/graph_dispatcher.py`:

```python
"""ASGI dispatcher forwarding /mcp-graph/{token}/... to per-execution MCP apps.

Mirrors the existing ``_ScopedMcpDispatcher`` pattern in ``api/app.py``, but
looks up its sub-apps in a ``GraphMcpExecutionRegistry`` (populated by
``GraphDispatchExecutor`` for exactly the lifetime of one graph-node
execution) instead of lazily building and caching them by tool-allowlist.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry


class GraphMcpDispatcher:
    """Serve per-execution graph MCP servers under ``/mcp-graph/{token}``."""

    def __init__(self, registry: GraphMcpExecutionRegistry) -> None:
        self._registry = registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            response = JSONResponse(
                status_code=404,
                content={"detail": "Graph MCP only supports HTTP transport"},
            )
            await response(scope, receive, send)
            return

        raw_path = str(scope.get("path", "")).strip("/")
        if raw_path.startswith("mcp-graph/"):
            raw_path = raw_path.removeprefix("mcp-graph/")
        token, _, rest = raw_path.partition("/")

        sub_app = self._registry.get(token) if token else None
        if sub_app is None or not rest:
            response = JSONResponse(
                status_code=404,
                content={"detail": "Unknown or expired graph MCP execution token"},
            )
            await response(scope, receive, send)
            return

        root_path = str(scope.get("root_path") or "").rstrip("/")
        if root_path.endswith("/mcp-graph"):
            token_root_path = f"{root_path}/{token}"
        else:
            token_root_path = f"{root_path}/mcp-graph/{token}"
        scoped_scope = dict(scope)
        if rest == "messages":
            scoped_scope["root_path"] = ""
            scoped_scope["path"] = "/messages/"
        elif rest.startswith("messages/"):
            scoped_scope["root_path"] = ""
            scoped_scope["path"] = f"/{rest}"
        else:
            scoped_scope["root_path"] = token_root_path
            scoped_scope["path"] = f"{token_root_path}/{rest}"
        await sub_app(scoped_scope, receive, send)
```

- [ ] **Step 4: Run to verify the new tests pass**

Run: `uv run pytest tests/integration/test_graph_mcp_dispatcher.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Wire the dispatcher into `api/app.py`**

In `src/orchestrator/api/app.py`, find the block that constructs `app.state.signal_consumer` (around line 512-527, right before the `from orchestrator.api.deps import make_graph_runner` import). Add, immediately before that block:

```python
    from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry

    app.state.graph_mcp_registry = GraphMcpExecutionRegistry()
```

Then change the `make_graph_runner(...)` call (around line 520) to pass it through:

```python
        graph_runner=make_graph_runner(
            session_factory,
            service_factory,
            connection_manager=app.state.connection_manager,
            artifact_stores=app.state.artifact_store_resolver,
            journal_max_bytes=app.state.global_config.journal.max_bytes,
            graph_mcp_registry=app.state.graph_mcp_registry,
        ),
```

Change `_mount_mcp_sse`'s signature (around line 872) to accept the registry and mount the new route:

```python
def _mount_mcp_sse(
    app: FastAPI,
    auth_config: AuthConfig,
    graph_mcp_registry: "GraphMcpExecutionRegistry",
) -> None:
```

Inside `_mount_mcp_sse`, after `scoped_mcp_asgi = _ScopedMcpDispatcher(handler)`, add:

```python
    from orchestrator.api.mcp.graph_dispatcher import GraphMcpDispatcher

    graph_mcp_asgi = GraphMcpDispatcher(graph_mcp_registry)
```

And extend both branches of the `if auth_config.auth_disabled:` block to also mount it:

```python
    if auth_config.auth_disabled:
        app.mount("/mcp", mcp_asgi)  # type: ignore[arg-type]
        app.mount("/mcp-scoped", scoped_mcp_asgi)  # type: ignore[arg-type]
        app.mount("/mcp-graph", graph_mcp_asgi)  # type: ignore[arg-type]
    else:
        # _McpAuthMiddleware's class body (defined a few lines above this
        # branch, inside _mount_mcp_sse) is unchanged by this task — only
        # the three app.mount(...) calls below it change.
        app.mount("/mcp", _McpAuthMiddleware(mcp_asgi))  # type: ignore[arg-type]
        app.mount("/mcp-scoped", _McpAuthMiddleware(scoped_mcp_asgi))  # type: ignore[arg-type]
        app.mount("/mcp-graph", _McpAuthMiddleware(graph_mcp_asgi))  # type: ignore[arg-type]
```

Finally, update the call site at line 825 to pass the registry:

```python
    _mount_mcp_sse(app, auth_config, app.state.graph_mcp_registry)
```

Add the `TYPE_CHECKING`-guarded import for `GraphMcpExecutionRegistry` near the top of `app.py` alongside its other `TYPE_CHECKING` imports, or import it directly if `app.py` already imports concrete types elsewhere at module scope (check the existing import block style in `app.py` and match it).

- [ ] **Step 6: Update `make_graph_runner`'s signature in `api/deps.py` to accept and forward the registry**

In `src/orchestrator/api/deps.py`, change `make_graph_runner`'s signature (around line 401) to:

```python
def make_graph_runner(
    session_factory: async_sessionmaker[AsyncSession],
    service_factory: Callable[[AsyncSession], Awaitable[WorkflowService]],
    connection_manager: ConnectionManager | None = None,
    artifact_stores: ArtifactStoreResolver | None = None,
    journal_max_bytes: int = 64 * 1024 * 1024,
    graph_mcp_registry: "GraphMcpExecutionRegistry | None" = None,
) -> Callable[[str], Awaitable[None]]:
```

And forward it into the `partial(build_graph_runtime, ...)` call inside `_run`:

```python
        driver = GraphRunDriver(
            session_factory,
            service_factory,
            on_agent_output=on_agent_output,
            artifact_stores=artifact_stores,
            journal_max_bytes=journal_max_bytes,
            runtime_builder=partial(
                build_graph_runtime,
                journal_max_bytes=journal_max_bytes,
                graph_mcp_registry=graph_mcp_registry,
            ),
        )
```

(`build_graph_runtime` gains this parameter in Task 6.)

- [ ] **Step 7: Full regression check**

Run: `uv run pytest tests/integration/test_mcp.py tests/integration/test_mcp_sse.py tests/integration/test_graph_mcp_dispatcher.py -q`
Expected: PASS, no regressions to the existing `/mcp` and `/mcp-scoped` mounts
Run: `uv run pyright`
Expected: 0 errors (this task touches typed constructor signatures — watch for the `GraphMcpExecutionRegistry` forward-reference string annotations resolving correctly)

- [ ] **Step 8: Commit**

```bash
git add src/orchestrator/api/mcp/graph_dispatcher.py \
        src/orchestrator/api/app.py \
        src/orchestrator/api/deps.py \
        tests/integration/test_graph_mcp_dispatcher.py
git commit -m "feat: mount per-execution graph MCP dispatcher at /mcp-graph"
```

---

## Task 6: Build and register the per-execution graph MCP tool server in `GraphDispatchExecutor`

**Files:**
- Create: `src/orchestrator/graph_runtime/graph_mcp_tools.py`
- Modify: `src/orchestrator/graph_runtime/dispatch.py:175-355,430-451,885-916` (`GraphDispatchExecutor.__init__`, `_run_agent`, `_execution_context`, `build_graph_runtime`)
- Test: `tests/unit/test_graph_mcp_tools.py` (new)
- Test: `tests/integration/test_graph_dispatch_mcp_lifecycle.py` (new)

**Interfaces:**
- Produces: `graph_mcp_tools.build_graph_mcp_server(on_submit_graph_patch, on_grade) -> FastMCP` (`on_grade` may be `None` for builder/planner nodes, in which case the `graph_grade` tool is omitted).
- Consumes: `graph_tool_routing.route_tool_call` (Task 2), `GraphMcpExecutionRegistry` (Task 4).

This is the biggest task. `build_graph_mcp_server` registers 10 tools with explicit typed parameters (FastMCP introspects function signatures — confirmed via `inspect.signature(FastMCP.add_tool)`, there is no way to pass an explicit JSON schema instead, so each tool needs its own real Python function, matching the existing style already used in `api/mcp/server.py`): `submit_graph_patch`, the 8 macro tools, and `graph_grade`.

- [ ] **Step 1: Write the failing unit tests for the tool server builder**

Create `tests/unit/test_graph_mcp_tools.py`:

```python
"""Unit tests for the per-execution graph MCP tool server builder."""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from orchestrator.graph_runtime.graph_mcp_tools import build_graph_mcp_server


def _tool_names(mcp: FastMCP) -> set[str]:
    # FastMCP's tool manager keeps registered tools in _tool_manager._tools.
    return set(mcp._tool_manager._tools.keys())  # noqa: SLF001 -- test-only introspection


async def test_builder_server_has_submit_graph_patch_and_macro_tools_but_not_grade() -> None:
    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        return "ok"

    mcp = build_graph_mcp_server(on_submit_graph_patch, None)
    names = _tool_names(mcp)
    assert "submit_graph_patch" in names
    assert "create_work_region" in names
    assert "attach_verifier" in names
    assert "graph_grade" not in names


async def test_verifier_server_has_graph_grade_tool() -> None:
    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        return "ok"

    async def on_grade(req_id: str, grade: str, grade_reason: str | None) -> None:
        return None

    mcp = build_graph_mcp_server(on_submit_graph_patch, on_grade)
    assert "graph_grade" in _tool_names(mcp)


async def test_submit_graph_patch_tool_calls_the_closure() -> None:
    calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        calls.append(payload)
        return "graph patch p1 accepted"

    mcp = build_graph_mcp_server(on_submit_graph_patch, None)
    result = await mcp.call_tool(
        "submit_graph_patch",
        {"patch_id": "p1", "base_graph_position": 1, "ops": []},
    )
    assert calls == [{"patch_id": "p1", "base_graph_position": 1, "ops": []}]
    assert any("accepted" in str(item) for item in result)


async def test_create_work_region_tool_normalizes_and_calls_the_closure() -> None:
    calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        calls.append(payload)
        return "graph patch p1 accepted"

    mcp = build_graph_mcp_server(on_submit_graph_patch, None)
    await mcp.call_tool(
        "create_work_region",
        {"patch_id": "p1", "base_graph_position": 1, "region_id": "r1"},
    )
    assert calls == [
        {
            "patch_id": "p1",
            "base_graph_position": 1,
            "macro_invocations": [{"macro": "create_work_region", "args": {"region_id": "r1"}}],
        }
    ]


async def test_graph_grade_tool_calls_the_closure() -> None:
    calls: list[tuple[str, str, str | None]] = []

    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        return "ok"

    async def on_grade(req_id: str, grade: str, grade_reason: str | None) -> None:
        calls.append((req_id, grade, grade_reason))

    mcp = build_graph_mcp_server(on_submit_graph_patch, on_grade)
    await mcp.call_tool("graph_grade", {"req_id": "R-01", "grade": "A", "grade_reason": "Good"})
    assert calls == [("R-01", "A", "Good")]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_graph_mcp_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.graph_runtime.graph_mcp_tools'`

- [ ] **Step 3: Implement `graph_mcp_tools.py`**

Create `src/orchestrator/graph_runtime/graph_mcp_tools.py`:

```python
"""Builds a per-execution FastMCP tool server for a graph-dispatched node.

Each graph-dispatched claude_cli execution gets a fresh instance of this
server (see ``GraphDispatchExecutor._run_agent``), with every tool handler
closing directly over that execution's ``on_submit_graph_patch``/``on_grade``
callables — the same closures codex_server's in-process JSON-RPC session
already awaits directly today. All 9 graph-patch tools funnel through the
shared ``graph_tool_routing.route_tool_call`` so the normalization logic
(macro-tool -> patch envelope) is identical to codex_server's.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from orchestrator.runners.graph_tool_routing import route_tool_call
from orchestrator.runners.types import GradeCallback, GraphPatchCallback

_GRAPH_MCP_ALLOWLIST = frozenset(
    {
        "submit_graph_patch",
        "create_work_region",
        "create_corrective_region",
        "attach_verifier",
        "attach_check",
        "create_gap_planner",
        "create_join",
        "request_gate",
        "retire_or_supersede",
        "graph_grade",
    }
)


async def _noop_checklist(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _noop_submit() -> None:
    return None


def build_graph_mcp_server(
    on_submit_graph_patch: GraphPatchCallback,
    on_grade: GradeCallback | None,
) -> FastMCP:
    """Build a fresh MCP server exposing the graph tools for one execution.

    Args:
        on_submit_graph_patch: Closure the graph dispatcher built for this
            specific execution; every graph-patch tool call routes here
            after normalization.
        on_grade: The verifier-phase grade closure, or ``None`` for
            planner/builder executions (in which case ``graph_grade`` is
            not registered at all).
    """
    mcp = FastMCP(
        name="orchestrator-graph-exec",
        instructions=(
            "Graph tools for this single execution. Use submit_graph_patch "
            "or one of the macro tools to propose graph mutations."
        ),
    )

    async def _route(tool_name: str, args: dict[str, Any]) -> str:
        return await route_tool_call(
            tool_name,
            args,
            _noop_checklist,
            _noop_submit,
            on_submit_graph_patch=on_submit_graph_patch,
            on_grade=on_grade,
            allowlist=_GRAPH_MCP_ALLOWLIST | {"grade"},
            agent_label="claude_cli-graph-exec",
        )

    async def submit_graph_patch(
        patch_id: str,
        base_graph_position: int,
        ops: list[dict[str, Any]],
        rationale_record_id: str | None = None,
    ) -> str:
        """Submit a graph patch envelope of raw ops."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "ops": ops,
        }
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("submit_graph_patch", args)

    mcp.add_tool(
        submit_graph_patch,
        name="submit_graph_patch",
        description=(
            "Submit a graph patch envelope of validated low-level ops. "
            "Prefer the macro tools; use this only when no macro expresses "
            "the mutation you need."
        ),
    )

    async def create_work_region(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        worker_id: str | None = None,
        verifier_id: str | None = None,
        candidate_id: str | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create a work region in the graph."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
        }
        if worker_id is not None:
            args["worker_id"] = worker_id
        if verifier_id is not None:
            args["verifier_id"] = verifier_id
        if candidate_id is not None:
            args["candidate_id"] = candidate_id
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("create_work_region", args)

    mcp.add_tool(
        create_work_region,
        name="create_work_region",
        description="Create a work region in the graph.",
    )

    async def create_corrective_region(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        worker_id: str | None = None,
        verifier_id: str | None = None,
        candidate_id: str | None = None,
        classified_gap_source_node_id: str | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create a corrective region in the graph."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
        }
        if worker_id is not None:
            args["worker_id"] = worker_id
        if verifier_id is not None:
            args["verifier_id"] = verifier_id
        if candidate_id is not None:
            args["candidate_id"] = candidate_id
        if classified_gap_source_node_id is not None:
            args["classified_gap_source_node_id"] = classified_gap_source_node_id
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("create_corrective_region", args)

    mcp.add_tool(
        create_corrective_region,
        name="create_corrective_region",
        description="Create a corrective region in the graph.",
    )

    async def attach_verifier(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        verifier_id: str,
        candidate_source_node_id: str | None = None,
        candidate_id: str | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Attach a verifier to the current graph region."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
            "verifier_id": verifier_id,
        }
        if candidate_source_node_id is not None:
            args["candidate_source_node_id"] = candidate_source_node_id
        if candidate_id is not None:
            args["candidate_id"] = candidate_id
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("attach_verifier", args)

    mcp.add_tool(
        attach_verifier,
        name="attach_verifier",
        description="Attach a verifier to the current graph region.",
    )

    async def attach_check(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        check_id: str,
        evidence_source_node_id: str | None = None,
        command_binding: str | None = None,
        hidden_oracle_command: str | None = None,
        command_definition: dict[str, Any] | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Attach a check to the current graph region."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
            "check_id": check_id,
        }
        if evidence_source_node_id is not None:
            args["evidence_source_node_id"] = evidence_source_node_id
        if command_binding is not None:
            args["command_binding"] = command_binding
        if hidden_oracle_command is not None:
            args["hidden_oracle_command"] = hidden_oracle_command
        if command_definition is not None:
            args["command_definition"] = command_definition
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("attach_check", args)

    mcp.add_tool(
        attach_check,
        name="attach_check",
        description="Attach a check to the current graph region.",
    )

    async def create_gap_planner(
        patch_id: str,
        base_graph_position: int,
        node_id: str,
        region_id: str,
        evidence_source_node_id: str | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create a gap planner node for the graph."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "node_id": node_id,
            "region_id": region_id,
        }
        if evidence_source_node_id is not None:
            args["evidence_source_node_id"] = evidence_source_node_id
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("create_gap_planner", args)

    mcp.add_tool(
        create_gap_planner,
        name="create_gap_planner",
        description="Create a gap planner node for the graph.",
    )

    async def create_join(
        patch_id: str,
        base_graph_position: int,
        join_id: str,
        source_ids: list[str] | None = None,
        sources: list[dict[str, Any]] | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create a join node in the graph."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "join_id": join_id,
        }
        if source_ids is not None:
            args["source_ids"] = source_ids
        if sources is not None:
            args["sources"] = sources
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("create_join", args)

    mcp.add_tool(
        create_join,
        name="create_join",
        description="Create a join node in the graph.",
    )

    async def request_gate(
        patch_id: str,
        base_graph_position: int,
        node_id: str,
        kind: str | None = None,
        reason: str | None = None,
        requested_authority: list[str] | None = None,
        target_node_id: str | None = None,
        target_region_id: str | None = None,
        expires_at: str | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Request a human gate or authority decision for the current graph node."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "node_id": node_id,
        }
        if kind is not None:
            args["kind"] = kind
        if reason is not None:
            args["reason"] = reason
        if requested_authority is not None:
            args["requested_authority"] = requested_authority
        if target_node_id is not None:
            args["target_node_id"] = target_node_id
        if target_region_id is not None:
            args["target_region_id"] = target_region_id
        if expires_at is not None:
            args["expires_at"] = expires_at
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("request_gate", args)

    mcp.add_tool(
        request_gate,
        name="request_gate",
        description="Request a human gate or authority decision for the current graph node.",
    )

    async def retire_or_supersede(
        patch_id: str,
        base_graph_position: int,
        target_id: str,
        action: str,
        replacement_ops: list[dict[str, Any]] | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Retire or supersede an existing graph node."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "target_id": target_id,
            "action": action,
        }
        if replacement_ops is not None:
            args["replacement_ops"] = replacement_ops
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("retire_or_supersede", args)

    mcp.add_tool(
        retire_or_supersede,
        name="retire_or_supersede",
        description="Retire or supersede an existing graph node.",
    )

    if on_grade is not None:

        async def graph_grade(req_id: str, grade: str, grade_reason: str | None = None) -> str:
            """Set a grade on a requirement (verifier phase only)."""
            return await _route(
                "grade", {"req_id": req_id, "grade": grade, "grade_reason": grade_reason}
            )

        mcp.add_tool(
            graph_grade,
            name="graph_grade",
            description="Set a grade on a requirement (verifier phase only).",
        )

    return mcp
```

Note `_route` passes `"grade"` (not `"graph_grade"`) to `route_tool_call`, since `graph_tool_routing.route_tool_call` only recognizes the canonical tool name `"grade"` — `graph_grade` is purely the MCP-facing name chosen in Task's spec §6 to avoid colliding with the legacy `orchestrator_set_grade` tool; the routing layer doesn't need to know about that renaming.

- [ ] **Step 4: Run to verify the tests pass**

Run: `uv run pytest tests/unit/test_graph_mcp_tools.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Wire per-execution mount/unmount into `GraphDispatchExecutor`**

In `src/orchestrator/graph_runtime/dispatch.py`, add to `GraphDispatchExecutor.__init__` (around line 178-205) two new optional parameters:

```python
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        controller: GraphController,
        agent_factory: GraphAgentFactory,
        *,
        worktree_path: str | Path,
        artifact_store: ArtifactStore,
        running_executions: dict[str, asyncio.Task[None]] | None = None,
        process_registry: GraphProcessRegistry | None = None,
        residue_classifier: ResidueClassifier | None = None,
        max_gatekeeper_items_per_boundary: int = 20,
        on_agent_output: Callable[[GraphDispatchContext, list[str]], Awaitable[None]] | None = None,
        on_agent_usage: Callable[[GraphDispatchContext, Any], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] = perf_counter,
        graph_mcp_registry: "GraphMcpExecutionRegistry | None" = None,
        base_url: str = "http://localhost:8000",
    ) -> None:
```

adding the two new attribute assignments alongside the existing ones:

```python
        self._graph_mcp_registry = graph_mcp_registry
        self._base_url = base_url.rstrip("/")
```

Add the import near the top of `dispatch.py`, alongside its other `graph_runtime` imports:

```python
from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry
```

- [ ] **Step 6: Mount/unmount around `runner.execute()` in `_run_agent`**

In `_run_agent` (around line 269-335), the current shape is:

```python
            async def on_submit_graph_patch(patch_payload: dict[str, Any]) -> str:
                nonlocal graph_patch_submitted, graph_patch_accepted
                graph_patch_submitted = True
                feedback = await self._submit_graph_patch_callback(context, patch_payload)
                if _graph_patch_feedback_accepted(feedback):
                    graph_patch_accepted = True
                    patch_has_ops = _patch_payload_has_ops(patch_payload)
                    if context.node_role == "gap_planner":
                        context.node_payload["_accepted_gap_planner_patch_had_ops"] = patch_has_ops
                    if patch_has_ops:
                        context.node_payload["_accepted_graph_patch_had_ops"] = True
                return feedback

            async def on_grade(req_id: str, grade: str, grade_reason: str | None) -> None:
                grades.append((req_id, grade, grade_reason))

            async def on_output(lines: list[str]) -> None:
                if self._on_agent_output is not None:
                    await self._on_agent_output(context, lines)

            started = self._monotonic()
            result = await runner.execute(
                self._execution_context(
                    context,
                    graph_patch_callback=(
                        on_submit_graph_patch if _can_submit_graph_patch(context) else None
                    ),
                ),
                on_checklist_update,
                on_submit,
                on_output=on_output,
                on_grade=on_grade if context.node_kind == "verifier" else None,
            )
```

Change it to mount a per-execution graph MCP server when this node can submit patches (or grade) and a registry was configured, and to unmount it once `runner.execute()` returns or raises:

```python
            async def on_output(lines: list[str]) -> None:
                if self._on_agent_output is not None:
                    await self._on_agent_output(context, lines)

            graph_mcp_token: str | None = None
            graph_mcp_url: str | None = None
            can_submit_patch = _can_submit_graph_patch(context)
            is_verifier = context.node_kind == "verifier"
            if self._graph_mcp_registry is not None and (can_submit_patch or is_verifier):
                import secrets

                from orchestrator.graph_runtime.graph_mcp_tools import build_graph_mcp_server

                graph_mcp_server = build_graph_mcp_server(
                    on_submit_graph_patch,
                    on_grade if is_verifier else None,
                )
                graph_mcp_token = secrets.token_urlsafe(24)
                self._graph_mcp_registry.register(
                    graph_mcp_token, graph_mcp_server.sse_app(mount_path="/")
                )
                graph_mcp_url = f"{self._base_url}/mcp-graph/{graph_mcp_token}/sse"

            try:
                started = self._monotonic()
                result = await runner.execute(
                    self._execution_context(
                        context,
                        graph_patch_callback=(on_submit_graph_patch if can_submit_patch else None),
                        graph_mcp_url=graph_mcp_url,
                    ),
                    on_checklist_update,
                    on_submit,
                    on_output=on_output,
                    on_grade=on_grade if is_verifier else None,
                )
            finally:
                if graph_mcp_token is not None:
                    self._graph_mcp_registry.unregister(graph_mcp_token)
```

The rest of `_run_agent` (metrics extraction, `_agent_died` handling, the outer `try`/`except Exception` around the whole method body) stays exactly as it is today — this `try`/`finally` nests inside that existing outer `try`, so an exception during `runner.execute()` still unmounts the route before propagating to the outer handler.

- [ ] **Step 7: Add `graph_mcp_url` to `_execution_context`**

In `_execution_context` (around line 430-451), add the new parameter and forward it:

```python
    def _execution_context(
        self,
        context: GraphDispatchContext,
        graph_patch_callback: Callable[[dict[str, Any]], Awaitable[str]] | None = None,
        graph_mcp_url: str | None = None,
    ) -> ExecutionContext:
        node = context.node_payload
        prompt = _prompt_for_node(context)
        return ExecutionContext(
            run_id=context.run_id,
            task_id=str(node.get("task_id") or node.get("task_region_id") or context.node_id),
            working_dir=context.worktree_path,
            prompt=prompt,
            requirements=context.requirements,
            step_id=cast(str | None, node.get("step_id")),
            node_id=context.node_id,
            node_kind=context.node_kind,
            node_role=context.node_role,
            graph_patch_callback=graph_patch_callback,
            graph_mcp_url=graph_mcp_url,
            available_tools=_available_tools_for_context(context),
            mcp_servers=cast(Any, node.get("mcp_servers")),
            work_mode=_work_mode(node.get("work_mode")),
        )
```

- [ ] **Step 8: Thread the new params through `build_graph_runtime`**

In `build_graph_runtime` (around line 885-916), add the two new parameters and forward them to `GraphDispatchExecutor`:

```python
def build_graph_runtime(
    session_factory: async_sessionmaker[AsyncSession],
    clock: Clock,
    id_gen: IdGenerator,
    *,
    worktree_path: str | Path,
    artifact_store: ArtifactStore,
    runner_type: AgentRunnerType,
    runner_config: dict[str, Any] | None = None,
    journal_max_bytes: int = 64 * 1024 * 1024,
    on_agent_output: Callable[[GraphDispatchContext, list[str]], Awaitable[None]] | None = None,
    on_agent_usage: Callable[[GraphDispatchContext, Any], Awaitable[None]] | None = None,
    graph_mcp_registry: "GraphMcpExecutionRegistry | None" = None,
    base_url: str = "http://localhost:8000",
) -> tuple[GraphController, GraphDispatchExecutor]:
    """Assemble graph controller and dispatch executor without API imports."""

    controller = GraphController(
        session_factory,
        clock,
        id_gen,
        auto_dispatch=False,
        journal_max_bytes=journal_max_bytes,
    )
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        StaticGraphAgentFactory(runner_type, runner_config),
        worktree_path=worktree_path,
        artifact_store=artifact_store,
        on_agent_output=on_agent_output,
        on_agent_usage=on_agent_usage,
        graph_mcp_registry=graph_mcp_registry,
        base_url=base_url,
    )
    return controller, executor
```

- [ ] **Step 9: Run the existing dispatch test suite to confirm no regressions**

Run: `uv run pytest tests/unit/test_graph_dispatch*.py tests/integration/test_graph_fr*.py -q`
Expected: PASS — `graph_mcp_registry` defaults to `None`, so every existing call site (which doesn't pass it) gets the exact old behavior: no MCP server is built, `graph_mcp_url` stays `None`.

- [ ] **Step 10: Write a test proving the mount/unmount lifecycle, using the existing `RecordingExecutor` harness**

`tests/unit/test_graph_dispatch_on_output.py` already has exactly the right harness for this: `RecordingExecutor` (a `GraphDispatchExecutor` subclass built with `cast(Any, object())` stand-ins for the session factory/controller/agent factory, stubbing `_acknowledge_start`/`_record_start_heartbeat`/`_submit_callback`/`_submit_graph_patch_callback`) and the module-level `_context(...)` helper that builds a `GraphDispatchContext` directly — no app, no DB, no HTTP needed. Add to that file (it already imports `GraphDispatchExecutor`, `GraphDispatchContext`, `ExecutionContext`, `ExecutionResult`, the `OutputAgent`/`PatchThenSubmitAgent` fake-agent style, etc.):

```python
from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry


class GraphMcpUrlCapturingAgent(OutputAgent):
    """Fake agent that asserts the per-execution graph MCP route is live
    during execute() and records the token for the caller to check
    afterward."""

    def __init__(self, registry: GraphMcpExecutionRegistry, captured_tokens: list[str]) -> None:
        super().__init__([])
        self._registry = registry
        self._captured_tokens = captured_tokens

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        assert context.graph_mcp_url is not None
        assert context.graph_mcp_url.startswith("http://test-base:9000/mcp-graph/")
        token = context.graph_mcp_url.removeprefix("http://test-base:9000/mcp-graph/").removesuffix(
            "/sse"
        )
        self._captured_tokens.append(token)
        assert self._registry.get(token) is not None, "route must be mounted during execute()"
        await on_submit()
        self.submitted = True
        return ExecutionResult(success=True)


class RecordingExecutorWithGraphMcp(RecordingExecutor):
    def __init__(self, registry: GraphMcpExecutionRegistry) -> None:
        super().__init__()
        self._graph_mcp_registry = registry
        self._base_url = "http://test-base:9000"


@pytest.mark.asyncio
async def test_graph_mcp_route_mounted_during_execute_and_unmounted_after() -> None:
    registry = GraphMcpExecutionRegistry()
    context = _context(node_id="planner-1", node_kind="planner", node_role="planner")
    captured_tokens: list[str] = []
    agent = GraphMcpUrlCapturingAgent(registry, captured_tokens)
    executor = RecordingExecutorWithGraphMcp(registry)

    await executor._run_agent(context, agent)

    assert executor.submitted == [context]
    assert executor.failures == []
    assert len(captured_tokens) == 1
    assert registry.get(captured_tokens[0]) is None, "route must be unmounted after execute()"


@pytest.mark.asyncio
async def test_verifier_node_gets_graph_mcp_route_too() -> None:
    registry = GraphMcpExecutionRegistry()
    context = _context(node_id="verifier-1", node_kind="verifier", node_role="verifier")
    captured_tokens: list[str] = []
    agent = GraphMcpUrlCapturingAgent(registry, captured_tokens)
    executor = RecordingExecutorWithGraphMcp(registry)

    await executor._run_agent(context, agent)

    assert executor.submitted == [context]
    assert len(captured_tokens) == 1


@pytest.mark.asyncio
async def test_no_registry_configured_means_no_graph_mcp_url() -> None:
    """Every existing call site that doesn't pass graph_mcp_registry (the
    default in Task 6 Step 5) gets exactly the pre-Task-6 behavior."""
    context = _context(node_id="planner-1", node_kind="planner", node_role="planner")
    executor = RecordingExecutor()  # no graph_mcp_registry — the plain existing class

    execution_context = executor._execution_context(context, graph_patch_callback=None)

    assert execution_context.graph_mcp_url is None
```

- [ ] **Step 11: Run to verify it passes**

Run: `uv run pytest tests/unit/test_graph_dispatch_on_output.py -k "graph_mcp" -v`
Expected: PASS (3 tests)

- [ ] **Step 12: Full regression check**

Run: `uv run pytest tests/unit tests/integration -q`
Expected: PASS, no regressions
Run: `uv run pyright`
Expected: 0 errors

- [ ] **Step 13: Commit**

```bash
git add src/orchestrator/graph_runtime/graph_mcp_tools.py \
        src/orchestrator/graph_runtime/dispatch.py \
        tests/unit/test_graph_mcp_tools.py \
        tests/integration/test_graph_dispatch_mcp_lifecycle.py
git commit -m "feat: mount per-execution graph MCP tool server around graph node execution"
```

---

## Task 7: Wire `CLIAgent` to use `context.graph_mcp_url`

**Files:**
- Modify: `src/orchestrator/runners/agents/claude_cli/agent.py` (`build_prompt`, `_write_mcp_json`)
- Test: `tests/unit/test_cli_agent.py` (extend)

**Interfaces:**
- Consumes: `ExecutionContext.graph_mcp_url` (Task 3).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_cli_agent.py` (following the file's existing `_make_context` helper pattern — extend it with a `graph_mcp_url` parameter):

```python
def test_build_prompt_with_graph_mcp_url_mentions_graph_tools() -> None:
    ctx = _make_context(graph_mcp_url="http://localhost:8000/mcp-graph/tok1/sse")
    result = CLIAgent.build_prompt("Plan the graph", ctx)
    assert "submit_graph_patch" in result
    assert "http://localhost:8000/mcp-graph/tok1/sse" in result


def test_write_mcp_json_adds_graph_mcp_url_as_sse_server() -> None:
    agent = CLIAgent(command="claude")
    ctx = _make_context(graph_mcp_url="http://localhost:8000/mcp-graph/tok1/sse")
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = agent._write_mcp_json(tmp, ctx.mcp_servers or [], ctx.available_tools, ctx)
        config = json.loads(path.read_text())
    assert config["mcpServers"]["orchestrator-graph"] == {
        "type": "sse",
        "url": "http://localhost:8000/mcp-graph/tok1/sse",
    }
```

Update `_make_context` at the top of `tests/unit/test_cli_agent.py` to accept and forward a `graph_mcp_url: str | None = None` parameter into the `ExecutionContext(...)` it builds, matching the existing pattern used for `graph_patch_callback` (removed in the earlier deletion sweep, so this file currently has no `graph_mcp_url`/`graph_patch_callback` param on `_make_context` — add just `graph_mcp_url`).

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_cli_agent.py -k "graph_mcp_url" -v`
Expected: FAIL — `_write_mcp_json` doesn't accept a 4th positional arg yet, and the prompt has no graph-tool text

- [ ] **Step 3: Add the prompt section**

In `src/orchestrator/runners/agents/claude_cli/agent.py`, in `build_prompt` (the same method whose graph-patch-bridge branch was deleted in the earlier deletion sweep), add back a graph-tools prompt section — but keyed on `context.graph_mcp_url` instead of `context.graph_patch_callback`, and describing native MCP tool calls instead of a stdout sentinel:

```python
        graph_tools_section = ""
        if context.graph_mcp_url is not None:
            graph_tools_section = (
                "\n\n## Graph Tools\n"
                "You are connected to an orchestrator-graph MCP server exposing "
                "submit_graph_patch and the graph macro tools (create_work_region, "
                "attach_verifier, attach_check, create_gap_planner, create_join, "
                "request_gate, retire_or_supersede, create_corrective_region). Use "
                "them directly as native tool calls — prefer the macro tools; use "
                "submit_graph_patch with raw ops only when no macro expresses the "
                "mutation you need. The MCP endpoint for this execution is "
                f"{context.graph_mcp_url}."
            )

        if context.api_base_url is None:
            return prompt + git_section + graph_tools_section
```

(This lives at the same point in `build_prompt` where the deleted `graph_patch_bridge_section` used to sit — right before the `if context.api_base_url is None: return ...` early-return branch introduced in the deletion sweep. Since graph dispatch never sets `api_base_url` today, this early-return branch is exactly the one that fires for graph-dispatched claude_cli executions, so `graph_tools_section` must be appended there, not only in the later `api_base_url is not None` branch.)

- [ ] **Step 4: Add the MCP config wiring**

Change `_write_mcp_json`'s signature to accept the execution context (or just the URL — pass the whole `context` for future extensibility, matching how other methods in this file already take `context: ExecutionContext`):

```python
    def _write_mcp_json(
        self,
        working_dir: str,
        mcp_servers: list[Any],
        available_tools: list[str] | None = None,
        context: ExecutionContext | None = None,
    ) -> Path:
```

Inside the method, after the existing `for mcp in scoped_mcp_servers or []:` loop that populates `mcp_config["mcpServers"]`, add:

```python
        if (
            context is not None
            and context.graph_mcp_url is not None
            and Path(self._command).name == "claude"
        ):
            mcp_config["mcpServers"]["orchestrator-graph"] = {
                "type": "sse",
                "url": context.graph_mcp_url,
            }
```

Update the one call site inside `execute()` (around line 655-659) to pass `context`:

```python
                mcp_json_path = self._write_mcp_json(
                    context.working_dir,
                    context.mcp_servers or [],
                    context.available_tools,
                    context,
                )
```

- [ ] **Step 5: Run to verify the tests pass**

Run: `uv run pytest tests/unit/test_cli_agent.py -v`
Expected: PASS, including the 2 new tests and all pre-existing ones in this file

- [ ] **Step 6: Full regression check**

Run: `uv run pytest tests/unit tests/integration -q`
Expected: PASS, no regressions
Run: `uv run ruff check .`
Expected: no issues
Run: `uv run pyright`
Expected: 0 errors

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/runners/agents/claude_cli/agent.py tests/unit/test_cli_agent.py
git commit -m "feat: wire CLIAgent to the per-execution graph MCP endpoint"
```

---

## Task 8: End-to-end smoke test — the real per-execution route serves a real graph MCP server over HTTP

**Files:**
- Test: `tests/integration/test_graph_mcp_second_runner_smoke.py` (new)

**Interfaces:** none new — this exercises the full chain built in Tasks 4-6 together for the first time (Tasks 4-6 each tested their own piece in isolation; this proves they compose).

Scope check against this codebase's own existing rigor: `tests/integration/test_mcp_sse.py`'s tests for the already-shipped `/mcp` and `/mcp-scoped` mounts (`test_mcp_sse_endpoint_exists`, `test_mcp_messages_endpoint_exists`) do not perform a full SSE-session-handshake-then-JSON-RPC-call round trip either — they check the route resolves, returns `200`/`text/event-stream` for `GET /sse`, and doesn't 404 for `POST /messages/`. This task matches that same level for `/mcp-graph`, composed with a *real* `build_graph_mcp_server(...)` instance (not a fake sub-app, unlike Task 5's dispatcher-only tests) so the test proves the real tool server's `.sse_app()` output is actually servable through the real dispatcher and registry together.

- [ ] **Step 1: Write the test**

Create `tests/integration/test_graph_mcp_second_runner_smoke.py`:

```python
"""End-to-end smoke test: a real per-execution graph MCP tool server,
registered under a real token in GraphMcpExecutionRegistry, served through
the real GraphMcpDispatcher.

This composes Tasks 4-6, each already unit-tested in isolation:
- Task 4: GraphMcpExecutionRegistry
- Task 5: GraphMcpDispatcher (tested there only against a fake sub-app)
- Task 6: build_graph_mcp_server (tested there only via mcp.call_tool
  in-process, never served over HTTP)

Matches the existing rigor level this codebase already accepts for its
shipped /mcp and /mcp-scoped mounts (see test_mcp_sse.py): confirms the
route resolves and serves the SSE transport, not a full JSON-RPC
handshake-and-call round trip (which none of the existing MCP integration
tests in this repo attempt either).
"""

from __future__ import annotations

from typing import Any

import anyio
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.mcp.graph_dispatcher import GraphMcpDispatcher
from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry
from orchestrator.graph_runtime.graph_mcp_tools import build_graph_mcp_server


async def _noop_submit_graph_patch(payload: dict[str, Any]) -> str:
    return "accepted"


async def test_real_graph_mcp_server_is_reachable_through_the_real_dispatcher() -> None:
    registry = GraphMcpExecutionRegistry()
    mcp = build_graph_mcp_server(_noop_submit_graph_patch, None)
    token = "smoke-test-token"
    registry.register(token, mcp.sse_app(mount_path="/"))
    dispatcher = GraphMcpDispatcher(registry)

    transport = ASGITransport(app=dispatcher)
    async with AsyncClient(
        transport=transport, base_url="http://localhost:8000"
    ) as client:
        with anyio.move_on_after(0.2):
            async with client.stream("GET", f"/mcp-graph/{token}/sse") as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers.get("content-type", "")

        messages_response = await client.post(f"/mcp-graph/{token}/messages/", content=b"{}")
        assert messages_response.status_code != 404


async def test_unknown_token_is_never_reachable() -> None:
    registry = GraphMcpExecutionRegistry()
    dispatcher = GraphMcpDispatcher(registry)
    transport = ASGITransport(app=dispatcher)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
        resp = await client.get("/mcp-graph/never-registered/sse")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify it passes**

Run: `uv run pytest tests/integration/test_graph_mcp_second_runner_smoke.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Full regression check**

Run: `uv run pytest -q`
Expected: PASS, no regressions across the whole suite
Run: `uv run ruff check .`
Expected: no issues
Run: `uv run pyright`
Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_graph_mcp_second_runner_smoke.py
git commit -m "test: add end-to-end smoke test for the real per-execution graph MCP route"
```

---

## Task 9: Update project docs to record this closure

**Files:**
- Modify: `docs/dynamic-graph/re-evaluation-2026-07-18.md` §5

**Interfaces:** none — documentation only.

- [ ] **Step 1: Add a resolution note to §5**

Following the same style already used for the Priority 1/2/3 "Update — <date>" notes earlier in this document, add a note to the top of the document and mark §5's heading "Priority 4 — Graph-runner capability contract and a second graph runner" as done, briefly summarizing: the capability contract is now derived from `agent_factory`'s `graph_capable` registration flag (not a hand-maintained frozenset); `claude_cli` is graph-capable via a per-execution MCP tool server mounted at `/mcp-graph/{token}`, closing directly over that execution's callbacks; `codex exec` via `cli_subprocess` remains a documented gap (capability flag says yes, no MCP wiring happens for it).

- [ ] **Step 2: Commit**

```bash
git add docs/dynamic-graph/re-evaluation-2026-07-18.md
git commit -m "docs: mark graph-runner capability contract (Priority 4) resolved"
```
