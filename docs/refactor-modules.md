# Module Consolidation: 19 → 9

Refactoring guide to consolidate the `src/orchestrator/` package from 19 top-level
modules down to 9, using shell tools and `sed` rather than manual file editing.

**Target architecture:**

| Module | Absorbs | LOC |
|--------|---------|-----|
| `config` | + `routines` | ~1,260 |
| `state` | — | ~530 |
| `db` | — | ~2,010 |
| `git` | + `repos` + `cache` + `review` | ~3,220 |
| `envfiles` | — | ~910 |
| `workflow` | + `artifacts` | ~5,430 |
| `runners` | + `scaffolding` + `agents` | ~12,040 |
| `api` | + `metrics` + `mcp` | ~7,460 |
| `cli` | — | ~1,450 |

**Conventions used below:**

- `SRC=src/orchestrator` — all paths relative to project root
- Run each phase's verification step before proceeding to the next phase
- Each move is independent within its phase — order within a phase doesn't matter
- All `find` + `sed` commands use `sed -i ''` (macOS). On Linux, use `sed -i` instead

---

## Phase 1: Zero-risk absorptions

These modules have no external consumers beyond their single parent.

### M1: Delete `routers` (dead code)

The `routers/` package is a 6-line re-export shim. Nothing in the codebase imports from it.

```bash
# Verify nothing imports from it
grep -r "from orchestrator\.routers" src/ tests/ scripts/ --include="*.py" | grep -v "api/routers"

# If the above returns nothing, delete it
rm -rf src/orchestrator/routers/
```

### M2: `scaffolding` → `runners/scaffolding`

**Current consumers (1 external):**
- `src/orchestrator/runners/executor.py` — `from orchestrator.scaffolding.copier import copy_scaffolding`

**Test files (1):**
- `tests/integration/test_scaffolding.py` — `from orchestrator.scaffolding import copy_scaffolding, ensure_gitignore`

```bash
# 1. Move the package
mv src/orchestrator/scaffolding/ src/orchestrator/runners/scaffolding/

# 2. Update internal imports within the moved package
find src/orchestrator/runners/scaffolding/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.scaffolding\./from orchestrator.runners.scaffolding./g' {} +

# 3. Update the single external consumer
sed -i '' 's/from orchestrator\.scaffolding\./from orchestrator.runners.scaffolding./g' \
  src/orchestrator/runners/executor.py

# 4. Update tests
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.scaffolding/from orchestrator.runners.scaffolding/g' {} +

# 5. Remove from runners' top-level deps (if listed in __init__.py)
# Check: grep "scaffolding" src/orchestrator/runners/__init__.py
```

### M3: `cache` → `git/cache.py`

**Current consumers (2 external):**
- `src/orchestrator/git/cached_diff_ops.py` — `from orchestrator.cache.lru_cache import Cache`
- `src/orchestrator/api/routers/review.py` — `from orchestrator.cache.lru_cache import LRUCache`

**Test files (2):**
- `tests/unit/cache/test_cached_diff_ops.py`
- `tests/unit/cache/test_lru_cache.py`

```bash
# 1. Move the LRU cache implementation into git
cp src/orchestrator/cache/lru_cache.py src/orchestrator/git/cache.py

# 2. Update imports in source
sed -i '' 's/from orchestrator\.cache\.lru_cache import/from orchestrator.git.cache import/g' \
  src/orchestrator/git/cached_diff_ops.py \
  src/orchestrator/api/routers/review.py

# 3. Update imports in tests
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.cache\.lru_cache import/from orchestrator.git.cache import/g' {} +

# 4. Delete old package
rm -rf src/orchestrator/cache/

# 5. Move test files
mkdir -p tests/unit/git/
mv tests/unit/cache/test_lru_cache.py tests/unit/git/test_lru_cache.py
mv tests/unit/cache/test_cached_diff_ops.py tests/unit/git/test_cached_diff_ops.py
rmdir tests/unit/cache/ 2>/dev/null || true
```

### M4: `artifacts` → `workflow/artifacts`

**Current consumers (3 external):**
- `src/orchestrator/runners/executor.py` — `from orchestrator.artifacts.registry import ArtifactRegistry`
- `src/orchestrator/workflow/context_builder.py` — `from orchestrator.artifacts.registry import ArtifactRegistry`
- `src/orchestrator/api/routers/tasks.py` — `from orchestrator.artifacts.registry import ArtifactRegistry`

**Test files (3):**
- `tests/unit/test_artifact_registry.py`
- `tests/unit/test_context_builder.py`
- `tests/unit/test_summary_cache.py`

```bash
# 1. Move the package
mv src/orchestrator/artifacts/ src/orchestrator/workflow/artifacts/

# 2. Update internal imports within the moved package
find src/orchestrator/workflow/artifacts/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.artifacts\./from orchestrator.workflow.artifacts./g' {} +

# 3. Update all external consumers
find src/orchestrator/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.artifacts/from orchestrator.workflow.artifacts/g' {} +

# 4. Update tests
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.artifacts/from orchestrator.workflow.artifacts/g' {} +
```

**Verify Phase 1:**

```bash
# Should return zero results for deleted/moved modules
grep -r "from orchestrator\.scaffolding\b" src/ tests/ --include="*.py" | grep -v "runners/scaffolding"
grep -r "from orchestrator\.cache\b" src/ tests/ --include="*.py" | grep -v "git/cache"
grep -r "from orchestrator\.artifacts\b" src/ tests/ --include="*.py" | grep -v "workflow/artifacts"
grep -r "from orchestrator\.routers\b" src/ tests/ --include="*.py" | grep -v "api/routers"

# Run tests
uv run pytest tests/ -x -q
```

---

## Phase 2: Semantic consolidations

These modules have 1–3 external consumers and belong semantically inside their target parent.

### M5: `review` → `git/review`

**Current consumers (5 external files):**
- `src/orchestrator/git/diff_ops.py` — `from orchestrator.review.models import CommitInfo, FileStatus, ModifiedFile`
- `src/orchestrator/api/app.py` — `from orchestrator.review.test_runner import TestRunner`
- `src/orchestrator/api/deps.py` — `from orchestrator.review.test_runner import TestRunner`
- `src/orchestrator/api/routers/runs.py` — `from orchestrator.review.test_runner import TestRunner`
- `src/orchestrator/api/routers/review.py` — `from orchestrator.review.test_runner import TestRunResult, TestRunner`

**Test files (4):**
- `tests/integration/test_review_test_api.py`
- `tests/integration/test_merge_readiness.py`
- `tests/integration/test_review_test_runner.py`
- `tests/unit/test_diff_ops.py`

```bash
# 1. Move the package
mv src/orchestrator/review/ src/orchestrator/git/review/

# 2. Update internal imports
find src/orchestrator/git/review/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.review\./from orchestrator.git.review./g' {} +

# 3. Update all source consumers
find src/orchestrator/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.review\./from orchestrator.git.review./g' {} +
find src/orchestrator/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.review import/from orchestrator.git.review import/g' {} +

# 4. Update tests
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.review\./from orchestrator.git.review./g' {} +
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.review import/from orchestrator.git.review import/g' {} +

# 5. Update api/errors.py if it references review errors
grep -l "orchestrator\.review" src/orchestrator/api/errors.py && \
  sed -i '' 's/from orchestrator\.review/from orchestrator.git.review/g' src/orchestrator/api/errors.py
```

### M6: `repos` → `git/repos`

**Current consumers (4 external files):**
- `src/orchestrator/api/errors.py` — `from orchestrator.repos.errors import RepoNotFoundError`
- `src/orchestrator/api/routers/repos.py` — `from orchestrator.repos import branch_count, get_repo, ...`
- `src/orchestrator/cli/repos.py` — `from orchestrator.repos.discovery import ...`
- `src/orchestrator/mcp/tools.py` — `from orchestrator.repos.discovery import ...`

**Test files (1):**
- `tests/unit/repos/test_discovery.py`

```bash
# 1. Move the package
mv src/orchestrator/repos/ src/orchestrator/git/repos/

# 2. Update internal imports
find src/orchestrator/git/repos/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.repos\./from orchestrator.git.repos./g' {} +
find src/orchestrator/git/repos/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.repos import/from orchestrator.git.repos import/g' {} +

# 3. Update all source consumers
find src/orchestrator/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.repos\./from orchestrator.git.repos./g' {} +
find src/orchestrator/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.repos import/from orchestrator.git.repos import/g' {} +

# 4. Update tests
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.repos\./from orchestrator.git.repos./g' {} +
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.repos import/from orchestrator.git.repos import/g' {} +

# 5. Move test directory
mv tests/unit/repos/ tests/unit/git/repos/ 2>/dev/null || true
```

### M7: `metrics` → `api/metrics.py`

**Current consumers (1 external file):**
- `src/orchestrator/api/routers/runs.py` — `from orchestrator.metrics.cost import estimate_cost`

**Test files (1):**
- `tests/unit/test_cost.py`

```bash
# 1. Copy the implementation (it's a single file)
cp src/orchestrator/metrics/cost.py src/orchestrator/api/metrics.py

# 2. Update imports in source
sed -i '' 's/from orchestrator\.metrics\.cost import/from orchestrator.api.metrics import/g' \
  src/orchestrator/api/routers/runs.py

# 3. Update tests
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.metrics\.cost import/from orchestrator.api.metrics import/g' {} +

# 4. Delete old package
rm -rf src/orchestrator/metrics/
```

### M8: `mcp` → `api/mcp`

**Current consumers (1 external file):**
- `src/orchestrator/api/app.py` — `from orchestrator.mcp.tools import ToolHandler` and `from orchestrator.mcp.server import OrchestratorMCPServer`

**Test files (3):**
- `tests/unit/test_mcp_tool_definitions.py`
- `tests/unit/test_cli_agent.py`
- `tests/unit/mcp/test_phase_filtering.py`
- `tests/integration/test_mcp_tools.py`
- `tests/integration/test_mcp_server.py`

```bash
# 1. Move the package
mv src/orchestrator/mcp/ src/orchestrator/api/mcp/

# 2. Update internal imports within the moved package
find src/orchestrator/api/mcp/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.mcp\./from orchestrator.api.mcp./g' {} +

# 3. Update all source consumers
find src/orchestrator/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.mcp\./from orchestrator.api.mcp./g' {} +
find src/orchestrator/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.mcp import/from orchestrator.api.mcp import/g' {} +

# 4. Update tests
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.mcp\./from orchestrator.api.mcp./g' {} +
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.mcp import/from orchestrator.api.mcp import/g' {} +

# 5. Move test directory
mv tests/unit/mcp/ tests/unit/api/mcp/ 2>/dev/null || true
mkdir -p tests/unit/api/mcp/ && touch tests/unit/api/__init__.py tests/unit/api/mcp/__init__.py
```

### M9: `agents` → `runners/profiles`

The `agents` module handles agent *configuration* (CRUD, profiles, seeding defaults).
Renamed to `profiles` to avoid collision with the existing `runners/agents/` sub-package
which contains agent *implementations*.

**Current consumers (4 external files):**
- `src/orchestrator/api/app.py` — `from orchestrator.agents.service import seed_default_agents`
- `src/orchestrator/api/routers/tasks.py` — `from orchestrator.agents.resolution import ...`
- `src/orchestrator/api/routers/agents.py` — `from orchestrator.agents.errors import ...`, `.schemas`, `.service`
- `src/orchestrator/api/errors.py` (if it references agent errors)

**Test files (3):**
- `tests/unit/test_agent_resolution.py`
- `tests/unit/test_agent_service.py`
- `tests/integration/test_e2e_agent_overrides.py`
- `tests/integration/test_api_agent_configs.py`

```bash
# 1. Move and rename the package
mv src/orchestrator/agents/ src/orchestrator/runners/profiles/

# 2. Update internal imports within the moved package
find src/orchestrator/runners/profiles/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.agents\./from orchestrator.runners.profiles./g' {} +
find src/orchestrator/runners/profiles/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.agents import/from orchestrator.runners.profiles import/g' {} +

# 3. Update all source consumers
find src/orchestrator/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.agents\./from orchestrator.runners.profiles./g' {} +
find src/orchestrator/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.agents import/from orchestrator.runners.profiles import/g' {} +

# 4. Update tests
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.agents\./from orchestrator.runners.profiles./g' {} +
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.agents import/from orchestrator.runners.profiles import/g' {} +
```

### M10: `routines` → `config/routines`

This is the largest move by import count (~35 files reference it).
The `sed` commands are straightforward — all imports follow the pattern
`from orchestrator.routines.X import Y`.

**Current consumers (7 external source files + ~15 test files):**
- `src/orchestrator/config/loader.py`
- `src/orchestrator/api/errors.py`
- `src/orchestrator/api/routers/runs.py`
- `src/orchestrator/api/routers/routines.py`
- `src/orchestrator/api/routers/repos.py`
- `src/orchestrator/api/routers/tasks.py`
- `src/orchestrator/cli/runs.py`
- `src/orchestrator/cli/routines.py`
- `scripts/seed_db.py`

```bash
# 1. Move the package
mv src/orchestrator/routines/ src/orchestrator/config/routines/

# 2. Update internal imports within the moved package
find src/orchestrator/config/routines/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.routines\./from orchestrator.config.routines./g' {} +
find src/orchestrator/config/routines/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.routines import/from orchestrator.config.routines import/g' {} +

# 3. Update ALL source consumers (broad sweep)
find src/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.routines\./from orchestrator.config.routines./g' {} +
find src/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.routines import/from orchestrator.config.routines import/g' {} +

# 4. Update scripts
find scripts/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.routines\./from orchestrator.config.routines./g' {} +
find scripts/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.routines import/from orchestrator.config.routines import/g' {} +

# 5. Update ALL test files
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.routines\./from orchestrator.config.routines./g' {} +
find tests/ -name "*.py" -exec \
  sed -i '' 's/from orchestrator\.routines import/from orchestrator.config.routines import/g' {} +
```

**Verify Phase 2:**

```bash
# Should return zero results for each absorbed module
for mod in review repos metrics mcp agents routines; do
  echo "--- $mod ---"
  grep -r "from orchestrator\.$mod\b" src/ tests/ scripts/ --include="*.py" \
    | grep -v "runners/profiles" \
    | grep -v "git/review" \
    | grep -v "git/repos" \
    | grep -v "api/metrics" \
    | grep -v "api/mcp" \
    | grep -v "config/routines"
done

# Run full test suite
uv run pytest tests/ -x -q

# Type check
cd ui && npx tsc --noEmit; cd ..
```

---

## Phase 3: Internal cleanup (optional, higher effort)

These are code extractions, not file moves. They require reading the source
and creating new service classes. These are best done by an engineer or LLM
with full context of the business logic.

### M11: Extract `ReviewService`

**Goal:** Reduce `api/routers/review.py`'s direct imports from ~8 modules to 1–2.

**Current imports in `api/routers/review.py`:**
```
git.branch_ops, git.conflict_ops, git.cached_diff_ops, git.prune_ops, git.errors
git.cache (after M3)
git.review.test_runner (after M5)
workflow.event_logger, workflow.service
```

**Steps:**
1. Create `src/orchestrator/git/review_service.py`
2. Move orchestration logic (diff assembly, prune coordination, test dispatch,
   conflict resolution) out of the router and into `ReviewService`
3. The router keeps only HTTP concerns: parse request, call service, format response
4. ~400 LOC to extract

### M12: Extract `RunService`

**Goal:** Reduce `api/routers/runs.py`'s direct imports from ~15 modules to 2–3.

**Steps:**
1. Create `src/orchestrator/workflow/run_service.py`
2. Move run lifecycle orchestration (creation, start, pause, resume, cancel,
   recovery, activity assembly, branch status) out of the router
3. The router keeps only HTTP request/response mapping
4. Largest single refactor — highest payoff for boundary health

---

## Verification checklist

After all phases, run these checks to confirm nothing is broken:

```bash
# 1. No stale imports remain
grep -r "from orchestrator\.\(scaffolding\|cache\|artifacts\|review\|repos\|metrics\|mcp\|agents\|routines\|routers\)\." \
  src/ tests/ scripts/ --include="*.py" \
  | grep -v "runners/scaffolding" \
  | grep -v "runners/profiles" \
  | grep -v "git/cache" \
  | grep -v "git/review" \
  | grep -v "git/repos" \
  | grep -v "workflow/artifacts" \
  | grep -v "api/metrics" \
  | grep -v "api/mcp" \
  | grep -v "config/routines"
# Expected: no output

# 2. No orphaned directories remain
for d in scaffolding cache artifacts review repos metrics mcp agents routines routers; do
  test -d "src/orchestrator/$d" && echo "ORPHAN: src/orchestrator/$d"
done
# Expected: no output

# 3. Module count
ls -d src/orchestrator/*/ | grep -v __pycache__ | wc -l
# Expected: 9

# 4. All tests pass
uv run pytest tests/ -x -q

# 5. Import graph is clean
python3 -c "
import importlib, pkgutil
pkg = importlib.import_module('orchestrator')
mods = [m.name for m in pkgutil.iter_modules(pkg.__path__)]
print(f'{len(mods)} top-level modules: {sorted(mods)}')
"
# Expected: 9 top-level modules: [api, cli, config, db, envfiles, git, runners, state, workflow]
```

---

## Edge cases and gotchas

### `__init__.py` re-exports

Several absorbed modules have `__init__.py` files that re-export public symbols.
After moving, you may want to add compatibility re-exports in the parent's
`__init__.py` so that existing imports like `from orchestrator.config import routines`
or `from orchestrator.git import repos` work naturally. This is optional — the `sed`
commands above update all imports to use the full path.

### Alembic migrations

The migration files in `src/orchestrator/db/migrations/versions/` do **not** import
from any of the absorbed modules. The `env.py` only imports from `db.connection`
and `db.models`. No migration file changes needed.

### Test directory structure

Some test directories mirror the source structure (e.g. `tests/unit/cache/`,
`tests/unit/repos/`). After moving source modules, consider moving test
directories to match, or leave them flat — both work as long as imports are updated.
The `sed` commands above handle import rewriting regardless of test file location.

### Routine YAML files

Routine YAML files in `routines/` do not contain Python import paths.
No changes needed to any `.yaml` files.

### `pyproject.toml` / package config

If `pyproject.toml` has any module-specific configuration (e.g. `[tool.pytest.ini_options]`
test paths, `[tool.mypy]` per-module overrides), update those references too:

```bash
grep -n "orchestrator\.\(scaffolding\|cache\|artifacts\|review\|repos\|metrics\|mcp\|agents\|routines\|routers\)" \
  pyproject.toml setup.cfg tox.ini .flake8 .mypy.ini 2>/dev/null
```
