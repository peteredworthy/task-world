# Parent Oversight Refactor Plan

## Completion Status

Completed in the current implementation:

- `ParentOversightService` owns parent oversight reads, writes, projection hydration, terminal guards, child creation, child acceptance, child resolution, wait observations, and evidence collection.
- `WorkflowService` keeps thin compatibility wrappers for parent oversight APIs and no longer mutates `run.oversight_state` directly.
- Projection is a pure function boundary via `extract_parent_oversight_facts()` and `project_parent_oversight()`.
- The stateless `DelegationCoordinator` facade has been removed; application services now operate on the immutable `DelegationState` value object directly.
- `_run_to_trace_response` moved into `api.presenters.runs` as `run_to_trace_response`.
- `evaluate_merge_readiness_gates` moved into `workflow.merge_readiness`.
- `scripts/check_delegation_boundaries.py` now enforces module-level oversight/delegation ownership instead of old `WorkflowService` method exceptions.

## Goal

Create one real application boundary for parent oversight and delegated work, while keeping policy/reducer code pure and avoiding hand-rewritten code moves.

The target shape is:

```text
WorkflowService
  - generic run/task lifecycle
  - delegates parent oversight operations

ParentOversightService
  - parent/child oversight application workflow
  - child run create/accept/reject/abandon coordination
  - durable oversight fact persistence
  - current oversight projection
  - evidence collection/validation orchestration
  - terminal guard decisions

Pure domain modules
  - reduce_parent_oversight_state
  - DelegationState / apply_delegate_command
  - SuperParentDelegationPolicy / FanOutDelegationPolicy
```

The main rule for this refactor: move code mechanically first, simplify second. Do not manually rewrite large method bodies into the new location.

## Current Problems

1. `WorkflowService` is becoming an omnibus service.
   It now owns generic workflow lifecycle plus parent oversight projection, child-run acceptance, evidence validation, git merge coordination, fan-out decision recording, and terminal guard behavior.

2. `OversightProjectionService` is not yet a meaningful boundary.
   It strips durable facts and delegates to `reduce_parent_oversight_state()`. Callers still collect children, collect evidence, decide persistence, and mutate `Run.oversight_state`.

3. `DelegationCoordinator` is a thin raw-dict adapter.
   It repeatedly converts raw oversight JSON into `DelegationState`, calls one method, and merges raw JSON back. That does not fully hide storage shape from `WorkflowService`.

4. API lazy export wrappers are pass-through layers.
   `src/orchestrator/api/__init__.py` forwards calls to router-private helpers. The pure code should live in importable presenter/domain modules instead.

## Non-Goals

- Do not change super-parent behavior in the first pass.
- Do not redesign evidence schema, child routine generation, or merge policy.
- Do not move all workflow logic. Only parent oversight and delegated-work application workflow should move.
- Do not replace tests wholesale. Keep existing tests as behavior locks while moving code.

## Baseline Checks

Run these before the first move:

```bash
uv run pytest tests/unit/test_delegation_models.py \
  tests/unit/test_delegation_fan_out.py \
  tests/unit/test_super_parent_oversight.py \
  tests/unit/test_super_parent_service_mechanics.py \
  tests/unit/test_merge_readiness.py \
  tests/unit/test_delegation_boundaries.py

uv run pyright
```

Capture the current architectural surface:

```bash
rg -n "oversight_state|ParentOversight|DelegationCoordinator|OversightProjectionService|accept_child_run|resolve_child_run|create_child_run" src/orchestrator tests
```

## Mechanical Move Strategy

Use the safest available tool for each kind of move.

### Tool Preference Order

1. `git mv`
   Use for whole-file moves and renames.

2. Rope
   Use for symbol moves when available, especially module-level classes/functions where import rewrites matter.

3. LibCST
   Use for deterministic import rewrites and targeted call-site transforms. `libcst` is already present in `uv.lock`.

4. AST line-range extraction
   Use for moving large method bodies out of `WorkflowService` without rewriting them. This preserves exact source text and is safer than asking an LLM to reproduce code.

5. Manual edits
   Only for small glue changes: imports, constructor parameters, call forwarding, and obvious `self` dependency fixes.

## Mechanical Move Techniques

### Whole Module Moves

Use `git mv` whenever moving a complete module:

```bash
git mv src/orchestrator/workflow/oversight_projection.py src/orchestrator/workflow/parent_oversight_projection.py
```

Then use LibCST or `ruff --fix` to update imports, not ad hoc search/replace if symbols are ambiguous.

### Rope Symbol Moves

Rope is useful when moving module-level classes/functions and updating imports. If it is not installed, add it to dev dependencies in a separate prep commit:

```bash
uv add --group dev rope
```

Use a small script rather than interactive editor actions. Keep scripts disposable under `/tmp` unless they become generally useful.

Example pattern:

```python
# /tmp/rope_move_symbol.py
from pathlib import Path

from rope.base.project import Project
from rope.refactor.move import create_move

root = Path("/Users/peter/code/task-world")
project = Project(str(root))

source = project.get_file("src/orchestrator/workflow/oversight_projection.py")
dest = project.get_file("src/orchestrator/workflow/parent_oversight.py")

source_text = source.read()
offset = source_text.index("class OversightProjectionService")

mover = create_move(project, source, offset)
changes = mover.get_changes(dest)
project.do(changes)
project.close()
```

Use Rope for moves such as:

- `extract_parent_oversight_facts`
- `project_parent_oversight` if introduced as a standalone pure function
- presenter helpers moved out of API routers

Do not rely on Rope for the large `WorkflowService` method split unless a dry run proves it preserves behavior. Method moves across classes often need semantic constructor wiring that Rope cannot infer cleanly.

### AST Line-Range Extraction

For large `WorkflowService` methods, first copy exact source ranges by AST node name. This avoids transcription errors.

Create a temporary extractor:

```python
# /tmp/extract_methods.py
import ast
from pathlib import Path

source_path = Path("src/orchestrator/workflow/service.py")
source = source_path.read_text()
lines = source.splitlines(keepends=True)
tree = ast.parse(source)

methods = {
    "get_parent_oversight",
    "update_parent_oversight",
    "refresh_parent_oversight",
    "_refresh_parent_oversight_without_commit",
    "_compute_parent_oversight_state",
    "_persist_parent_oversight_state",
    "_hydrate_parent_oversight_state",
    "_apply_oversight_terminal_guard",
    "accept_child_run",
    "resolve_child_run",
    "create_child_run",
}

class_node = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == "WorkflowService"
)

for node in class_node.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in methods:
        print(f"\n# --- {node.name} ---")
        print("".join(lines[node.lineno - 1:node.end_lineno]))
```

Then redirect the extracted output into a scratch file:

```bash
uv run python /tmp/extract_methods.py > /tmp/parent_oversight_methods.py
```

Paste the extracted methods into `ParentOversightService` with minimal edits:

- Keep method bodies intact initially.
- Keep method names intact initially.
- Add constructor dependencies.
- Fix imports.
- Replace only dependency access that must change, such as `self._repo`, `self._clock`, and helper methods that move with the class.

After tests pass, remove the original methods from `WorkflowService` and replace public methods with delegating wrappers.

### LibCST Import Rewrites

Use LibCST for structured import changes. Example tasks:

- Replace `from orchestrator.workflow import OversightProjectionService` with a pure projection function or `ParentOversightService`.
- Move tests from `orchestrator.api import evaluate_merge_readiness_gates` to the new presenter/domain module.
- Remove lazy API wrappers once all call sites are updated.

Suggested temporary script shape:

```python
# /tmp/rewrite_imports.py
from pathlib import Path

import libcst as cst

ROOT = Path("/Users/peter/code/task-world")

class ImportRewriter(cst.CSTTransformer):
    def leave_ImportFrom(self, original_node, updated_node):
        if (
            original_node.module
            and original_node.module.code == "orchestrator.api"
            and "evaluate_merge_readiness_gates" in original_node.code
        ):
            return updated_node.with_changes(
                module=cst.parse_expression("orchestrator.workflow.merge_readiness")
            )
        return updated_node

for path in ROOT.glob("**/*.py"):
    if ".venv" in path.parts:
        continue
    module = cst.parse_module(path.read_text())
    updated = module.visit(ImportRewriter())
    if updated.code != module.code:
        path.write_text(updated.code)
```

Run:

```bash
uv run python /tmp/rewrite_imports.py
uv run ruff format src tests
uv run pyright
```

### Safe Search/Replace

Use plain search/replace only for unique, fully qualified strings. Avoid replacing short symbol names globally.

Acceptable:

```bash
rg -l "orchestrator.workflow.oversight_projection" src tests | xargs perl -pi -e 's/orchestrator\\.workflow\\.oversight_projection/orchestrator.workflow.parent_oversight/g'
```

Avoid:

```bash
perl -pi -e 's/state/facts/g'
```

## Phase 1: Introduce ParentOversightService

Add:

```text
src/orchestrator/workflow/parent_oversight.py
```

Initial class:

```python
class ParentOversightService:
    def __init__(
        self,
        session: AsyncSession,
        repo: RunRepository,
        event_emitter: PersistentEventEmitter,
        clock: Clock,
        *,
        global_config: GlobalConfig | None = None,
        delegation_coordinator: DelegationCoordinator | None = None,
        super_parent_policy: SuperParentDelegationPolicy | None = None,
        fan_out_policy: FanOutDelegationPolicy | None = None,
    ) -> None:
        ...
```

Mechanically move these methods first:

- `get_parent_oversight`
- `update_parent_oversight`
- `refresh_parent_oversight`
- `_refresh_parent_oversight_without_commit`
- `_compute_parent_oversight_state`
- `_persist_parent_oversight_state`
- `_hydrate_parent_oversight_state`
- `_apply_oversight_terminal_guard`

Keep `WorkflowService` wrappers temporarily:

```python
async def get_parent_oversight(self, parent_run_id: str) -> dict[str, Any]:
    return await self._parent_oversight.get_parent_oversight(parent_run_id)
```

Verify:

```bash
uv run pytest tests/unit/test_super_parent_oversight.py \
  tests/unit/test_super_parent_service_mechanics.py \
  tests/unit/test_delegation_boundaries.py
```

## Phase 2: Move Child Run Coordination

Mechanically move:

- `create_child_run`
- `accept_child_run`
- `resolve_child_run`
- child acceptance helpers
- child merge conflict helpers
- child evidence validation helpers
- delegation command key / owner token helpers

Keep thin wrappers on `WorkflowService` until routers and MCP tools can switch directly to `ParentOversightService`.

Do not edit behavior while moving. Any behavior cleanup gets a separate commit.

Verify:

```bash
uv run pytest tests/integration/test_child_run_branch_default.py \
  tests/integration/test_completion_integration.py \
  tests/integration/test_oversight_orchestration.py \
  tests/unit/test_super_parent_service_mechanics.py
```

## Phase 3: Collapse OversightProjectionService

Choose one:

### Preferred

Replace the class with pure functions:

```python
def extract_parent_oversight_facts(...)
def project_parent_oversight(...)
```

`ParentOversightService` owns child/evidence collection and persistence. Projection is pure.

### Alternative

Rename and expand it into `ParentOversightService`.

Do not keep both `ParentOversightService` and `OversightProjectionService` if projection remains a stateless one-method wrapper.

Verify no class references remain:

```bash
rg -n "OversightProjectionService" src tests
```

## Phase 4: Simplify DelegationCoordinator

Pick the lower-risk simplification first: expose `DelegationState` directly inside `ParentOversightService`.

Before:

```python
state = self._delegation_coordinator.record_decision(...)
```

After:

```python
delegation = DelegationState.from_oversight_state(state)
state = delegation.with_decision(...).merge_into(state)
```

Then delete `DelegationCoordinator` if it has no remaining callers.

If that makes call sites noisier, take the opposite approach: make `DelegationCoordinator` a real store that owns raw JSON reads/writes through `RunRepository`. The unacceptable middle ground is a stateless facade that still exposes raw dictionaries everywhere.

Verify:

```bash
rg -n "DelegationCoordinator" src tests
uv run pytest tests/unit/test_delegation_models.py tests/unit/test_delegation_fan_out.py
```

## Phase 5: Move Pure API Helpers Out of Routers

Create presenter/domain modules:

```text
src/orchestrator/api/presenters/runs.py
src/orchestrator/workflow/merge_readiness.py
```

Move:

- `_run_to_trace_response` to `api.presenters.runs`
- `evaluate_merge_readiness_gates` to `workflow.merge_readiness`

Use Rope or LibCST to rewrite imports.

Delete lazy pass-through wrappers from `src/orchestrator/api/__init__.py`.

Verify:

```bash
rg -n "_run_to_trace_response|evaluate_merge_readiness_gates" src tests
uv run pytest tests/unit/test_merge_readiness.py ui/tests/api/client.test.ts
```

## Phase 6: Tighten the Boundary Checker

After oversight writes move out of `WorkflowService`, simplify:

```text
scripts/check_delegation_boundaries.py
```

Replace service function allowlists with module allowlists:

- allowed:
  - `src/orchestrator/workflow/parent_oversight.py`
  - `src/orchestrator/workflow/delegation/*`
  - repository methods that perform locked JSON updates
- disallowed:
  - raw `run.oversight_state` mutation in `WorkflowService`

The checker should enforce the new architecture, not document exceptions to the old one.

Verify:

```bash
uv run python scripts/check_delegation_boundaries.py src/orchestrator scripts
uv run pytest tests/unit/test_delegation_boundaries.py
```

## Measuring Improvement

Track objective coupling/coherence metrics before and after. The goal is not perfect numbers; it is directional evidence that the refactor reduced cross-boundary complexity.

### Suggested Metrics

1. `WorkflowService` size
   - Lines in class
   - Number of methods
   - Number of constructor dependencies
   - Number of `self._...` attributes used

2. Oversight-specific surface in `WorkflowService`
   - Count references to:
     - `oversight_state`
     - `Delegation`
     - `child_run`
     - `parent_oversight`
     - `accept_child_run`
     - `resolve_child_run`

3. Module fan-in/fan-out
   - Efferent coupling: number of internal modules imported by a module.
   - Afferent coupling: number of internal modules importing a module.
   - Instability: `Ce / (Ca + Ce)`.

4. Class dependency graph
   - Constructor dependency count.
   - Number of classes instantiated directly.
   - Number of public methods called by external modules.

5. Boundary crossings
   - Count calls from API/MCP/router layers into `WorkflowService` vs `ParentOversightService`.
   - Count raw `dict[str, Any]` oversight state crossings outside parent oversight/delegation modules.

6. Cohesion proxy
   - For each class, count method clusters by shared `self._` attributes.
   - `WorkflowService` should have fewer oversight-only clusters after the refactor.

### Simple AST Measurement Script

Add or run as a temporary script:

```python
# /tmp/measure_architecture.py
import ast
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/peter/code/task-world")
SRC = ROOT / "src" / "orchestrator"

def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT / "src").with_suffix("")
    return ".".join(rel.parts)

internal_imports: dict[str, set[str]] = defaultdict(set)
imported_by: dict[str, set[str]] = defaultdict(set)
class_metrics: dict[str, dict[str, object]] = {}

for path in SRC.rglob("*.py"):
    mod = module_name(path)
    tree = ast.parse(path.read_text(), filename=str(path))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("orchestrator."):
            internal_imports[mod].add(node.module)
            imported_by[node.module].add(mod)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("orchestrator."):
                    internal_imports[mod].add(alias.name)
                    imported_by[alias.name].add(mod)

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        attrs_by_method: dict[str, set[str]] = {}
        for method in methods:
            attrs: set[str] = set()
            for child in ast.walk(method):
                if (
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "self"
                ):
                    attrs.add(child.attr)
            attrs_by_method[method.name] = attrs
        cls = f"{mod}.{node.name}"
        class_metrics[cls] = {
            "method_count": len(methods),
            "self_attr_count": len(set().union(*attrs_by_method.values()) if attrs_by_method else set()),
            "methods_touching_oversight": sum(
                1 for attrs in attrs_by_method.values()
                if any("oversight" in attr or "delegation" in attr for attr in attrs)
            ),
            "line_count": (node.end_lineno or node.lineno) - node.lineno + 1,
        }

modules = {}
for mod in sorted(set(internal_imports) | set(imported_by)):
    ce = len(internal_imports[mod])
    ca = len(imported_by[mod])
    modules[mod] = {
        "efferent": ce,
        "afferent": ca,
        "instability": round(ce / (ca + ce), 3) if ca + ce else 0,
    }

print(json.dumps({"modules": modules, "classes": class_metrics}, indent=2, sort_keys=True))
```

Run before and after:

```bash
uv run python /tmp/measure_architecture.py > /tmp/arch-before.json
uv run python /tmp/measure_architecture.py > /tmp/arch-after.json
```

Compare:

```bash
uv run python - <<'PY'
import json

before = json.load(open("/tmp/arch-before.json"))
after = json.load(open("/tmp/arch-after.json"))

for cls in [
    "orchestrator.workflow.service.WorkflowService",
    "orchestrator.workflow.parent_oversight.ParentOversightService",
]:
    print(cls)
    print("  before:", before["classes"].get(cls))
    print("  after: ", after["classes"].get(cls))

for mod in [
    "orchestrator.workflow.service",
    "orchestrator.workflow.parent_oversight",
    "orchestrator.workflow.delegation.coordinator",
]:
    print(mod)
    print("  before:", before["modules"].get(mod))
    print("  after: ", after["modules"].get(mod))
PY
```

### Expected Directional Improvements

After the refactor:

- `WorkflowService` line count should drop materially.
- `WorkflowService` methods touching oversight/delegation should approach zero except delegating wrappers.
- Raw `oversight_state` writes in `WorkflowService` should be zero.
- `ParentOversightService` should have high fan-in from routers/MCP/workflow and focused fan-out to repository, projection, delegation, git merge, and evidence helpers.
- `OversightProjectionService` should disappear, or become part of `ParentOversightService`.
- `DelegationCoordinator` should disappear or become a real persistence boundary.

## Commit Strategy

Use small commits:

1. Add measurement script or run temporary measurement and document baseline.
2. Mechanical move: introduce `ParentOversightService` with copied methods and wrappers.
3. Mechanical move: child run coordination into `ParentOversightService`.
4. Collapse `OversightProjectionService`.
5. Simplify `DelegationCoordinator`.
6. Move API presenter/domain helpers out of router lazy exports.
7. Tighten boundary checker.

Each commit should pass:

```bash
uv run ruff format src tests scripts
uv run pyright
uv run pytest tests/unit/test_delegation_models.py \
  tests/unit/test_delegation_fan_out.py \
  tests/unit/test_super_parent_oversight.py \
  tests/unit/test_super_parent_service_mechanics.py \
  tests/unit/test_delegation_boundaries.py
```

Final commit should pass:

```bash
uv run pytest
npm --prefix ui run test
npm --prefix ui run typecheck
npm --prefix ui run lint
```
