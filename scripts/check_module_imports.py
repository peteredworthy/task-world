#!/usr/bin/env python3
"""
Enforce module sub-package import discipline.

External callers must not reach into a module's sub-packages (directories).
Importing from a root-level .py file within another module is fine.

WRONG: from orchestrator.config.routines.discovery import discover_routines
RIGHT: from orchestrator.config import discover_routines   (or config.routines)

WRONG: from orchestrator.runners.profiles.service import AgentService
RIGHT: from orchestrator.runners import AgentService   (or runners.profiles)

FINE:  from orchestrator.config.models import RunConfig  (models.py is a root file)
FINE:  from orchestrator.state.models import Run         (models.py is a root file)

Intra-module imports (within the same top-level module) are always allowed.

The rule: if the import path crosses into a sub-package directory of another
module, that's a violation. Importing from a root-level .py file is not.
"""

import ast
import sys
from pathlib import Path

TOP_LEVEL_MODULES = {
    "api",
    "cli",
    "config",
    "db",
    "envfiles",
    "git",
    "runners",
    "state",
    "workflow",
}


def get_file_module(filepath: Path) -> str | None:
    """Return the top-level orchestrator module this file belongs to, or None."""
    parts = filepath.parts
    try:
        idx = next(i for i, p in enumerate(parts) if p == "orchestrator")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except StopIteration:
        pass
    return None


def find_src_root(filepath: Path) -> Path | None:
    """Return the directory that directly contains the orchestrator/ package."""
    parts = filepath.resolve().parts
    try:
        idx = next(i for i, p in enumerate(parts) if p == "orchestrator")
        return Path(*parts[:idx])
    except StopIteration:
        return None


def find_src_root_from_script() -> Path | None:
    """Return src_root by looking for orchestrator/ relative to this script."""
    script_dir = Path(__file__).resolve().parent  # scripts/
    project_root = script_dir.parent
    candidate = project_root / "src"
    if (candidate / "orchestrator").is_dir():
        return candidate
    if (project_root / "orchestrator").is_dir():
        return project_root
    return None


def goes_through_subpackage(import_parts: list[str], src_root: Path) -> bool:
    """
    Return True if the import path goes through a sub-package directory.

    import_parts = ['orchestrator', 'config', 'routines', 'discovery']
    We check whether parts[2] (the component after the top-level module) is a
    sub-package (a directory with __init__.py). If it is, that's a violation.
    Root-level .py files (parts length == 3, no sub-directory) are fine.
    """
    if len(import_parts) < 3:
        return False
    # Path to the component immediately after the top-level module
    # e.g. src/orchestrator/config/routines
    candidate = src_root.joinpath(*import_parts[:3])
    return candidate.is_dir() and (candidate / "__init__.py").exists()


def check_file(filepath: Path, src_root: Path | None) -> list[str]:
    violations = []
    file_module = get_file_module(filepath)

    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, OSError):
        return violations

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        parts = node.module.split(".")
        # Must be: orchestrator.<module>.<something>.<possibly more>
        if len(parts) < 3 or parts[0] != "orchestrator":
            continue
        import_module = parts[1]
        if import_module not in TOP_LEVEL_MODULES:
            continue
        # Same top-level module — intra-module import, always allowed
        if file_module == import_module:
            continue
        # Only flag if the import goes through a sub-package directory
        if src_root and not goes_through_subpackage(parts, src_root):
            continue
        violations.append(
            f"{filepath}:{node.lineno}: "
            f"`from {node.module} import ...` — "
            f"reaches into sub-package of `orchestrator.{import_module}`; "
            f"use `from orchestrator.{import_module} import ...` instead"
        )

    return violations


def main(paths: list[str]) -> int:
    all_violations: list[str] = []
    # Try to find src_root from the script location first (works even when
    # all input files are test files outside the orchestrator/ package).
    src_root: Path | None = find_src_root_from_script()
    if src_root is None:
        for p in paths:
            src_root = find_src_root(Path(p))
            if src_root is not None:
                break

    for path_str in paths:
        path = Path(path_str)
        if path.suffix == ".py" and path.exists():
            all_violations.extend(check_file(path, src_root))

    if all_violations:
        print("Module sub-package import violations found:", file=sys.stderr)
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nDo not reach into a module's sub-packages from outside that module. "
            "Use the module top-level (e.g. `from orchestrator.config import X`). "
            "If the symbol is missing from __init__.py, add it there.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
