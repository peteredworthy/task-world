# Server-Managed Repos & Enhanced Routine System

## Overview

This plan transforms the orchestrator to use server-managed git repositories with proper branch validation, project-local routine discovery, scaffolding support, and commit tracking between builder/verifier stages.

## Goals

1. **Server-managed repos** - Repos live in `{project-root}/repos/`, manually managed by user/devops
2. **Branch validation** - Glob pattern-filtered branch selection with 100+ threshold messaging
3. **Project routines** - Discover routines from `{repo}/routines/` alongside embedded templates
4. **Directory-based routines** - Support `routines/X/routine.yaml` with `scaffolding/` folder
5. **Scaffolding** - Copy scaffolding files to `.orchestrator/scaffolding/` on run start
6. **Commit tracking** - Builder commits changes, hash passed to verifier for checkout
7. **Separate worktrees directory** - Worktrees in `{project-root}/worktrees/`

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Migration strategy | Delete existing runs | Clean slate, no legacy data |
| API compatibility | Clean break | Remove `project_id` entirely from API, UI, MCP, CLI |
| Routine reference | Both embed + path/SHA | Embed for execution, path+SHA for traceability |
| Branch pattern matching | Glob patterns | Supports `feat*`, `*/auth`, `feature/*` |

---

## Phase 1: Repository Management

### 1.1 Configuration

**New settings in `config/settings.py`:**

```python
class OrchestratorSettings(BaseSettings):
    repos_dir: Path = Field(default_factory=lambda: Path.cwd() / "repos")
    worktrees_dir: Path = Field(default_factory=lambda: Path.cwd() / "worktrees")
```

**Files to modify:**
- `src/orchestrator/config/settings.py` - Add new settings
- `src/orchestrator/api/deps.py` - Expose settings

### 1.2 Repo Discovery API

**New module: `src/orchestrator/repos/`**

```
src/orchestrator/repos/
├── __init__.py
├── discovery.py    # Scan repos_dir for git repos
├── models.py       # RepoInfo, BranchInfo
└── errors.py       # RepoNotFoundError
```

**Models:**
```python
class RepoInfo(BaseModel):
    name: str                    # Directory name
    path: Path                   # Full path
    default_branch: str          # HEAD branch

class BranchInfo(BaseModel):
    name: str
    is_remote: bool
    commit: str                  # HEAD commit
```

**Discovery functions:**
```python
def list_repos(repos_dir: Path) -> list[RepoInfo]
def get_repo(repos_dir: Path, name: str) -> RepoInfo
def list_branches(repo_path: Path, pattern: str = "") -> list[BranchInfo]
def branch_count(repo_path: Path, pattern: str = "") -> int
```

**Glob pattern matching for branches:**
```python
import fnmatch

def match_branches(branches: list[str], pattern: str) -> list[str]:
    """Match branches using glob patterns.

    Examples:
        "feat*" matches "feature/auth", "feat-123"
        "*/auth" matches "feature/auth", "bugfix/auth"
        "release-*" matches "release-1.0", "release-2.0"
    """
    if not pattern:
        return branches
    return [b for b in branches if fnmatch.fnmatch(b, pattern)]
```

### 1.3 API Endpoints

**New router: `src/orchestrator/api/routers/repos.py`**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/repos` | GET | List all repos in repos_dir |
| `/api/repos/{name}` | GET | Get repo details |
| `/api/repos/{name}/branches` | GET | List branches (with `?pattern=` glob filter) |
| `/api/repos/{name}/branches/count` | GET | Count matching branches |

**Query params for branches:**
- `pattern` - Glob filter pattern (e.g., `feat*`, `*/auth`, `release-*`)
- Returns `{"branches": [...], "total": N, "truncated": bool}`

### 1.4 Replace project_id with repo_name

**State model changes (`state/models.py`):**

```python
class Run(BaseModel):
    # REMOVED: project_id: str
    repo_name: str                    # Name of repo in repos_dir
    source_branch: str                # Branch to base worktree on

    # Routine traceability (NEW)
    routine_path: str | None = None   # Path within repo (e.g., "routines/feature.yaml")
    routine_commit: str | None = None # Commit SHA when routine was read

    # ... rest unchanged
```

**Clean removal of project_id:**
- Remove from `Run` model in `state/models.py`
- Remove from `RunModel` ORM in `db/models.py`
- Remove from API schemas in `api/schemas/runs.py`
- Remove from factory functions in `state/factory.py`
- Update CLI commands in `cli/`
- Update MCP tools in `mcp/tools.py`
- Update UI components

### 1.5 Database Migration

**Create migration to:**
1. Delete all existing runs (clean slate)
2. Drop `project_id` column
3. Add `repo_name` column (required)
4. Add `routine_path` column (nullable)
5. Add `routine_commit` column (nullable)

```python
# migrations/versions/xxx_replace_project_id.py
def upgrade():
    # Delete all runs
    op.execute("DELETE FROM runs")
    op.execute("DELETE FROM events")

    # Modify schema
    op.drop_column("runs", "project_id")
    op.add_column("runs", sa.Column("repo_name", sa.String, nullable=False))
    op.add_column("runs", sa.Column("routine_path", sa.String, nullable=True))
    op.add_column("runs", sa.Column("routine_commit", sa.String, nullable=True))
```

---

## Phase 2: Branch Selection UI

### 2.1 Branch Filter Component

**New UI component: `ui/src/components/BranchSelector.tsx`**

Behavior:
1. Text input for glob pattern with debounced matching
2. If `branch_count(pattern) > 100`: Show "100+ branches match - refine pattern"
3. If `branch_count(pattern) <= 100`: Show dropdown list
4. If `branch_count(pattern) == 0`: Show "No branches match"
5. Validation: Selected branch must exist

**Glob pattern examples shown in UI:**
```
Pattern examples:
  main, develop     - exact match
  feat*             - starts with "feat"
  */auth            - ends with "/auth"
  release-*         - release branches
```

**API calls:**
```typescript
// On pattern change (debounced 300ms)
GET /api/repos/{name}/branches/count?pattern={pattern}

// When count <= 100
GET /api/repos/{name}/branches?pattern={pattern}
```

### 2.2 Run Creation Flow Update

**Modify: `ui/src/pages/CreateRun.tsx`**

New flow:
1. Select repository (dropdown of available repos)
2. Enter branch glob pattern / select branch
3. Select routine (grouped: Templates vs Project)
4. Configure routine inputs
5. Create run

---

## Phase 3: Project Routine Discovery

### 3.1 Routine Discovery from Repo

**Extend `routines/discovery.py`:**

```python
def discover_routines_in_repo(
    repo_path: Path,
    branch: str,
) -> list[DiscoveredRoutine]:
    """Discover routines from {repo}/routines/ at specified branch.

    Uses git to read files without checkout.
    Returns routines with both embedded config and path+commit reference.
    """
```

**Git commands:**
```bash
# Get commit SHA for branch
git rev-parse {branch}

# List routine files at branch
git ls-tree -r --name-only {branch} -- routines/

# Read file content at branch
git show {branch}:routines/feature.yaml
```

### 3.2 Directory-Based Routines

**Support structure:**
```
routines/
├── simple.yaml                    # Flat file
└── feature-x/                     # Directory-based
    ├── routine.yaml               # Required
    └── scaffolding/               # Optional
        └── templates/
            └── intent.md
```

**Discovery logic:**
1. Find `*.yaml` and `*.yml` files in `routines/`
2. Find `*/routine.yaml` patterns in `routines/*/`
3. For directory-based: record scaffolding path if exists

**Extended `DiscoveredRoutine`:**
```python
@dataclass
class DiscoveredRoutine:
    config: RoutineConfig
    source: RoutineSource           # EMBEDDED, PROJECT
    path: str                       # Relative path within repo (e.g., "routines/feature.yaml")
    commit: str                     # Commit SHA where routine was read
    scaffolding_path: str | None    # Path to scaffolding/ if exists
```

### 3.3 API Endpoint for Repo Routines

**Add to `repos.py` router:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/repos/{name}/routines` | GET | List routines at branch |
| `/api/repos/{name}/routines/{id}` | GET | Get routine config |

**Query params:**
- `branch` - Branch to read from (required)

**Response includes both embedded config and reference:**
```json
{
  "id": "feature-auth",
  "name": "Auth Feature Implementation",
  "source": "PROJECT",
  "path": "routines/feature-auth/routine.yaml",
  "commit": "abc123def456", <!-- pragma: allowlist secret -->
  "config": { ... },
  "has_scaffolding": true
}
```

---

## Phase 4: Scaffolding

### 4.1 Scaffolding Module

**New module: `src/orchestrator/scaffolding/`**

```
src/orchestrator/scaffolding/
├── __init__.py
├── models.py       # ScaffoldingSpec
├── copier.py       # Copy scaffolding to worktree
└── errors.py       # ScaffoldingError
```

**Models:**
```python
class ScaffoldingSpec(BaseModel):
    source_path: str        # Relative path in routine directory
    target_dir: str = ".orchestrator/scaffolding"
```

### 4.2 Copy on Run Start

**Modify `workflow/service.py` `start_run()`:**

After worktree creation:
1. If routine has scaffolding_path:
   - Extract scaffolding from git at `routine_commit`
   - Copy to `{worktree}/.orchestrator/scaffolding/`
2. Ensure `.orchestrator/` in `.gitignore`

**Implementation:**
```python
async def _copy_scaffolding(
    self,
    repo_path: Path,
    routine_path: str,
    routine_commit: str,
    worktree_path: Path,
) -> None:
    """Extract scaffolding from routine at specific commit."""
    target = worktree_path / ".orchestrator" / "scaffolding"
    target.mkdir(parents=True, exist_ok=True)

    # Get scaffolding directory path
    routine_dir = str(Path(routine_path).parent)
    scaffolding_prefix = f"{routine_dir}/scaffolding/"

    # List files in scaffolding
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", routine_commit, "--", scaffolding_prefix],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    for file_path in result.stdout.strip().split("\n"):
        if not file_path:
            continue
        # Extract relative path within scaffolding
        rel_path = file_path[len(scaffolding_prefix):]

        # Get file content
        content = subprocess.run(
            ["git", "show", f"{routine_commit}:{file_path}"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )

        # Write to target
        target_file = target / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_bytes(content.stdout)

    # Ensure gitignore
    _ensure_gitignore(worktree_path, ".orchestrator/")


def _ensure_gitignore(worktree_path: Path, entry: str) -> None:
    gitignore = worktree_path / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if entry not in content:
            with gitignore.open("a") as f:
                f.write(f"\n{entry}\n")
    else:
        gitignore.write_text(f"{entry}\n")
```

### 4.3 Update idea-to-plan Routine

**Move routine to directory structure:**

```
routines/idea-to-plan/
├── routine.yaml
└── scaffolding/
    └── docs/planner/templates/
        ├── intent.md
        ├── plan.md
        ├── design-questions.md
        ├── architecture.md
        ├── CONFLICTS.md
        ├── step-plan.md
        ├── step-tasks.md
        ├── dry-run-notes.md
        ├── verification-report.md
        └── plan-summary.md
```

**Update routine.yaml to reference scaffolding:**
```yaml
task_context: |
  Use templates from .orchestrator/scaffolding/docs/planner/templates/
```

---

## Phase 5: Commit Tracking

### 5.1 Extend Attempt Model

**Modify `state/models.py`:**

```python
class Attempt(BaseModel):
    # ... existing fields ...

    # Git tracking
    start_commit: str | None = None     # Commit at attempt start
    end_commit: str | None = None       # Commit at attempt end (after builder)
```

### 5.2 Capture Commits in Workflow

**Modify `workflow/service.py`:**

**On `start_task()`:**
```python
# Get current HEAD commit
attempt.start_commit = get_head_commit(worktree_path)
```

**On `submit_for_verification()`:**
```python
# Capture commit after builder work
attempt.end_commit = get_head_commit(worktree_path)
```

**Helper function in `git/utils.py`:**
```python
def get_head_commit(path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()
```

### 5.3 Builder Prompt Enhancement

**Modify `workflow/prompts.py`:**

Add to builder system prompt:
```
IMPORTANT: Before submitting for verification:
1. Stage all relevant changes: git add <files>
2. Commit with descriptive message: git commit -m "..."
3. Then call submit

The verifier may run in a separate environment and can only see committed changes.
```

### 5.4 Verifier Checkout (for Docker agents)

**Modify `agents/openhands_docker.py`:**

Before starting verifier in container:
```python
if attempt.end_commit:
    # Checkout specific commit in container workspace
    subprocess.run(
        ["git", "checkout", attempt.end_commit],
        cwd=container_workspace,
        check=True,
    )
```

---

## Phase 6: Worktree Directory

### 6.1 Update WorktreeManager

**Modify `git/worktree.py`:**

```python
class WorktreeManager:
    def __init__(
        self,
        repo_path: Path,
        worktree_dir: Path,    # Now required, from settings
    ):
        self._repo = repo_path
        self._worktree_dir = worktree_dir  # No default
```

### 6.2 Update Service Integration

**Modify `workflow/service.py`:**

```python
def _get_worktree_manager(self, repo_name: str) -> WorktreeManager:
    repo_path = self._settings.repos_dir / repo_name
    return WorktreeManager(
        repo_path=repo_path,
        worktree_dir=self._settings.worktrees_dir,
    )
```

### 6.3 Worktree Path Format

```
worktrees/
└── run-{run_id}/          # Worktree for each run
```

---

## Phase 7: CLI Updates

### 7.1 Update Run Commands

**Modify `cli/commands/run.py`:**

Replace `--project` with `--repo` and `--branch`:

```python
@click.command()
@click.option("--repo", required=True, help="Repository name in repos/")
@click.option("--branch", required=True, help="Branch to use")
@click.option("--routine", required=True, help="Routine ID")
def create(repo: str, branch: str, routine: str):
    """Create a new run."""
```

### 7.2 Add Repo Commands

**New command group `cli/commands/repo.py`:**

```bash
orchestrator repo list                    # List repos in repos/
orchestrator repo show <name>             # Show repo details
orchestrator repo branches <name> [pattern]  # List branches
```

---

## Phase 8: MCP Updates

### 8.1 Update MCP Tools

**Modify `mcp/tools.py`:**

Update tool schemas to use `repo_name` instead of `project_id`:

```python
ORCHESTRATOR_TOOLS = [
    {
        "name": "orchestrator_create_run",
        "description": "Create a new run",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Repository name"},
                "branch": {"type": "string", "description": "Branch to use"},
                "routine_id": {"type": "string", "description": "Routine ID"},
                # ...
            },
            "required": ["repo_name", "branch", "routine_id"],
        },
    },
    # ...
]
```

### 8.2 Add Repo Tools

```python
{
    "name": "orchestrator_list_repos",
    "description": "List available repositories",
},
{
    "name": "orchestrator_list_branches",
    "description": "List branches in a repository",
    "inputSchema": {
        "properties": {
            "repo_name": {"type": "string"},
            "pattern": {"type": "string", "description": "Glob pattern filter"},
        },
    },
},
```

---

## Phase 9: UI Updates

### 9.1 Repository List Page

**New page: `ui/src/pages/Repos.tsx`**

- List repos from `/api/repos`
- Show default branch, last commit
- Link to create run with repo pre-selected

### 9.2 Enhanced Run Creation

**Modify: `ui/src/pages/CreateRun.tsx`**

Steps:
1. **Repo Selection** - Dropdown or navigate from Repos page
2. **Branch Selection** - Glob pattern-filtered input
3. **Routine Selection** - Grouped list (Templates / Project)
4. **Inputs** - Dynamic form from routine inputs
5. **Review & Create**

### 9.3 Routine Selector Component

**New component: `ui/src/components/RoutineSelector.tsx`**

```typescript
interface RoutineSelectorProps {
  repoName: string;
  branch: string;
  onSelect: (routine: DiscoveredRoutine) => void;
}
```

Display:
```
── Templates ──────────────────
  idea-to-plan
  fullstack-feature
  demo-task

── Project Routines ───────────
  auth-implementation (6 steps)
  api-refactor (3 steps)
```

### 9.4 Update Existing UI

Remove all references to `project_id`:
- `ui/src/api/runs.ts`
- `ui/src/components/RunCard.tsx`
- `ui/src/pages/RunDetail.tsx`
- Any other components using project_id

---

## Implementation Order

| Phase | Priority | Est. Effort | Dependencies |
|-------|----------|-------------|--------------|
| 1.1 Configuration | High | S | - |
| 1.2 Repo Discovery | High | M | 1.1 |
| 1.3 API Endpoints | High | M | 1.2 |
| 1.4-1.5 Replace project_id + Migration | High | L | 1.3 |
| 6.1-6.3 Worktree Dir | High | S | 1.1 |
| 5.1-5.4 Commit Tracking | High | M | 1.4 |
| 3.1-3.3 Project Routines | Medium | M | 1.4 |
| 4.1-4.3 Scaffolding | Medium | M | 3.2 |
| 7.1-7.2 CLI Updates | Medium | S | 1.4 |
| 8.1-8.2 MCP Updates | Medium | S | 1.4 |
| 2.1-2.2 Branch UI | Medium | M | 1.3 |
| 9.1-9.4 UI Updates | Medium | L | All API |

**Recommended sequence:**
1. Phase 1.1-1.3 + Phase 6 (Repo Management + Worktree Dir) - Foundation
2. Phase 1.4-1.5 (Replace project_id) - Core model change
3. Phase 5 (Commit Tracking) - Critical for correctness
4. Phase 7 + 8 (CLI + MCP Updates) - Complete API surface
5. Phase 3 (Project Routines) - Enable project-local routines
6. Phase 4 (Scaffolding) - Complete routine support
7. Phase 2 + 9 (UI) - User-facing changes

---

## Testing Strategy

### Unit Tests
- Repo discovery with mock filesystem
- Glob branch pattern matching
- Scaffolding extraction logic
- Commit capture

### Integration Tests
- Real git repos in temp directories
- Worktree creation/deletion
- Routine discovery from branches
- End-to-end run with scaffolding

### Test Fixtures
```python
@pytest.fixture
def sample_repo(tmp_path):
    """Create a git repo with branches and routines."""
    repo = tmp_path / "repos" / "sample"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=repo)

    # Add routine
    routines = repo / "routines"
    routines.mkdir()
    (routines / "test.yaml").write_text("routine:\n  id: test\n  name: Test")

    subprocess.run(["git", "add", "."], cwd=repo)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo)

    # Create feature branch
    subprocess.run(["git", "checkout", "-b", "feature/auth"], cwd=repo)

    return repo
```

---

## Files to Modify/Create Summary

### New Files
```
src/orchestrator/repos/__init__.py
src/orchestrator/repos/discovery.py
src/orchestrator/repos/models.py
src/orchestrator/repos/errors.py
src/orchestrator/scaffolding/__init__.py
src/orchestrator/scaffolding/models.py
src/orchestrator/scaffolding/copier.py
src/orchestrator/scaffolding/errors.py
src/orchestrator/git/utils.py
src/orchestrator/api/routers/repos.py
src/orchestrator/api/schemas/repos.py
src/orchestrator/cli/commands/repo.py
ui/src/pages/Repos.tsx
ui/src/components/BranchSelector.tsx
ui/src/components/RoutineSelector.tsx
```

### Modified Files
```
src/orchestrator/config/settings.py
src/orchestrator/state/models.py
src/orchestrator/db/models.py
src/orchestrator/db/repositories.py
src/orchestrator/state/factory.py
src/orchestrator/workflow/service.py
src/orchestrator/workflow/prompts.py
src/orchestrator/git/worktree.py
src/orchestrator/routines/discovery.py
src/orchestrator/agents/openhands_docker.py
src/orchestrator/api/deps.py
src/orchestrator/api/app.py
src/orchestrator/api/schemas/runs.py
src/orchestrator/api/routers/runs.py
src/orchestrator/cli/commands/run.py
src/orchestrator/mcp/tools.py
ui/src/api/runs.ts
ui/src/pages/CreateRun.tsx
ui/src/pages/RunDetail.tsx
ui/src/components/RunCard.tsx
routines/idea-to-plan.yaml → routines/idea-to-plan/routine.yaml
```

### Database Migration
```
src/orchestrator/db/migrations/versions/xxx_replace_project_id.py
```
