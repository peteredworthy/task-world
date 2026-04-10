# Implementation Slices: Phase 7 - Git Integration

**Goal:** Implement git worktree management and routine versioning.

**End state:** Runs execute in isolated worktrees; routines have git-based versioning.

**Prerequisites:** Phase 4 complete.

---

## Slice 7.1: Worktree Manager

### Goal
Manage git worktrees for run isolation.

### Deliverables

```
src/orchestrator/
├── git/
│   ├── __init__.py
│   ├── worktree.py    # Worktree management
│   └── errors.py      # Git-related errors
tests/integration/test_worktree.py
```

### Architecture Constraints

1. **One worktree per run** - Complete isolation
2. **Named by run ID** - Easy to find and clean up
3. **Configurable location** - Default to `.worktrees/` in repo root
4. **Cleanup on completion** - If configured

### Implementation

```python
import subprocess
from pathlib import Path
from dataclasses import dataclass

@dataclass
class WorktreeInfo:
    path: Path
    branch: str
    commit: str

class WorktreeManager:
    def __init__(self, repo_path: Path, worktree_dir: Path | None = None):
        self._repo = repo_path
        self._worktree_dir = worktree_dir or repo_path / ".worktrees"
    
    def create(self, run_id: str, base_branch: str = "main") -> WorktreeInfo:
        """Create a new worktree for a run."""
        worktree_path = self._worktree_dir / f"run-{run_id}"
        branch_name = f"orchestrator/run-{run_id}"
        
        # Create worktree with new branch
        subprocess.run([
            "git", "worktree", "add",
            "-b", branch_name,
            str(worktree_path),
            base_branch,
        ], cwd=self._repo, check=True)
        
        # Get commit SHA
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True,
        )
        
        return WorktreeInfo(
            path=worktree_path,
            branch=branch_name,
            commit=result.stdout.strip(),
        )
    
    def delete(self, run_id: str, force: bool = False) -> None:
        """Remove worktree for a run."""
        worktree_path = self._worktree_dir / f"run-{run_id}"
        
        args = ["git", "worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(worktree_path))
        
        subprocess.run(args, cwd=self._repo, check=True)
    
    def list(self) -> list[WorktreeInfo]:
        """List all orchestrator worktrees."""
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self._repo,
            capture_output=True,
            text=True,
            check=True,
        )
        
        worktrees = []
        current = {}
        for line in result.stdout.split("\n"):
            if line.startswith("worktree "):
                current["path"] = Path(line.split(" ", 1)[1])
            elif line.startswith("branch "):
                current["branch"] = line.split(" ", 1)[1]
            elif line.startswith("HEAD "):
                current["commit"] = line.split(" ", 1)[1]
            elif line == "" and current:
                # Filter to orchestrator worktrees
                if current.get("branch", "").startswith("refs/heads/orchestrator/"):
                    worktrees.append(WorktreeInfo(**current))
                current = {}
        
        return worktrees
    
    def cleanup_stale(self, active_run_ids: set[str]) -> int:
        """Remove worktrees for runs that no longer exist."""
        removed = 0
        for wt in self.list():
            run_id = wt.branch.replace("refs/heads/orchestrator/run-", "")
            if run_id not in active_run_ids:
                self.delete(run_id, force=True)
                removed += 1
        return removed
```

### Verification

#### Integration Tests
```bash
uv run pytest tests/integration/test_worktree.py -v
```

**Test scenarios:**
1. Create worktree for run
2. Verify isolation (changes don't affect main)
3. Delete worktree
4. Cleanup stale worktrees

### Definition of Done
- [ ] Create worktree works
- [ ] Delete worktree works
- [ ] List worktrees works
- [ ] Cleanup stale works

---

## Slice 7.2: Routine Git Versioning

### Goal
Track routine versions via git SHA.

### Deliverables

```
src/orchestrator/routines/
├── versioning.py      # Git versioning for routines
```

### Architecture Constraints

1. **Warn on uncommitted** - Allow but warn if routine has uncommitted changes
2. **SHA as version** - Use git commit SHA as routine version
3. **Dirty flag** - Track if routine was modified but not committed

### Implementation

```python
import subprocess
from pathlib import Path
from dataclasses import dataclass

@dataclass
class RoutineVersion:
    sha: str
    dirty: bool
    path: Path

def get_routine_version(routine_path: Path) -> RoutineVersion:
    """Get git version information for a routine file."""
    repo_root = find_git_root(routine_path)
    if repo_root is None:
        raise ValueError(f"Routine {routine_path} is not in a git repository")
    
    # Get SHA of last commit touching this file
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", str(routine_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    sha = result.stdout.strip()
    
    if not sha:
        raise ValueError(f"Routine {routine_path} has no git history")
    
    # Check if file is dirty
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", str(routine_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    dirty = len(result.stdout.strip()) > 0
    
    return RoutineVersion(sha=sha, dirty=dirty, path=routine_path)

def find_git_root(path: Path) -> Path | None:
    """Find the git repository root containing the given path."""
    current = path.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None
```

### Verification

#### Integration Tests
Test with a git repo containing routines.

### Definition of Done
- [ ] SHA extraction works
- [ ] Dirty detection works
- [ ] Warning logged when dirty

---

## Slice 7.3: Completion Actions

### Goal
Implement worktree cleanup on run completion.

### Deliverables

```
src/orchestrator/workflow/
├── completion.py      # Completion handling
```

### Architecture Constraints

1. **Orchestrator only handles worktree** - Keep/delete worktree
2. **Git operations in routine** - MR creation, merge, etc. are agent tasks
3. **Configurable per run** - `delete_worktree_on_completion` flag

### Implementation

```python
from orchestrator.git.worktree import WorktreeManager
from orchestrator.state.models import Run

async def handle_run_completion(
    run: Run,
    worktree_manager: WorktreeManager,
) -> None:
    """Handle cleanup when a run completes."""
    if not run.worktree_path:
        return
    
    if run.delete_worktree_on_completion:
        worktree_manager.delete(run.id)
```

### Verification

#### Integration Tests
1. Complete run with delete_worktree=True
2. Verify worktree removed
3. Complete run with delete_worktree=False
4. Verify worktree remains

### Definition of Done
- [ ] Worktree deleted when configured
- [ ] Worktree kept when configured

---

## Phase 7 Milestone Verification

```bash
# All tests pass
uv run pytest tests/ -v

# Manual verification
uv run python -c "
from pathlib import Path
from orchestrator.git.worktree import WorktreeManager
import tempfile
import subprocess

# Create test repo
with tempfile.TemporaryDirectory() as tmpdir:
    repo = Path(tmpdir) / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init'], cwd=repo, check=True)
    (repo / 'file.txt').write_text('test')
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-m', 'initial'], cwd=repo, check=True)
    
    # Test worktree manager
    manager = WorktreeManager(repo)
    
    # Create worktree
    wt = manager.create('test-run-1')
    print(f'Created worktree at {wt.path}')
    assert wt.path.exists()
    
    # List worktrees
    worktrees = manager.list()
    print(f'Found {len(worktrees)} worktrees')
    assert len(worktrees) == 1
    
    # Cleanup
    manager.delete('test-run-1')
    assert not wt.path.exists()
    print('SUCCESS!')
"
```

If git integration works, Phase 7 is complete. Proceed to Phase 8.
