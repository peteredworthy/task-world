#!/usr/bin/env python3
"""
Enforce signal routing constraints.

Registry functions (register_active_run, unregister_active_run,
has_active_workflow) were removed in the EventSignalTransport migration.
This hook is kept as a placeholder for future signal-routing constraints.

To suppress a line, add:  # noqa: signal-routing
"""

import ast
import sys
from pathlib import Path

# No restricted names after registry functions were removed in the
# EventSignalTransport migration (signals now use events_v2).
RESTRICTED_NAMES: set[str] = set()

# No files need allowlisting when RESTRICTED_NAMES is empty.
ALLOWED_FILE_SUFFIXES: set[str] = set()


def find_project_root(filepath: Path) -> Path | None:
    """Walk up from filepath looking for pyproject.toml as project root marker."""
    candidate = filepath.resolve()
    for parent in [candidate, *candidate.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return None


def find_project_root_from_script() -> Path | None:
    """Return project root by looking relative to this script."""
    script_dir = Path(__file__).resolve().parent  # scripts/
    project_root = script_dir.parent
    if (project_root / "pyproject.toml").exists():
        return project_root
    return None


def is_allowed_file(filepath: Path, project_root: Path | None) -> bool:
    """Return True if this file is in the allowed set."""
    if project_root is None:
        return False
    try:
        rel = filepath.resolve().relative_to(project_root.resolve())
        rel_str = str(rel)
        return any(
            rel_str.endswith(suffix.replace("/", str(Path("/").__class__("/"))))
            or rel_str == suffix
            or rel_str.replace("\\", "/") == suffix
            for suffix in ALLOWED_FILE_SUFFIXES
        )
    except ValueError:
        return False


def get_suppressed_lines(source: str) -> set[int]:
    """Return set of 1-based line numbers that have # noqa: signal-routing."""
    suppressed = set()
    for lineno, line in enumerate(source.splitlines(), start=1):
        if "# noqa: signal-routing" in line:
            suppressed.add(lineno)
    return suppressed


def check_file(filepath: Path, project_root: Path | None) -> list[str]:
    violations = []

    if is_allowed_file(filepath, project_root):
        return violations

    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, OSError):
        return violations

    suppressed = get_suppressed_lines(source)

    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        if lineno in suppressed:
            continue

        # Check: from X import register_active_run / has_active_workflow / ...
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.name
                asname = alias.asname or name
                # Direct name import
                if name in RESTRICTED_NAMES or asname in RESTRICTED_NAMES:
                    violations.append(
                        f"{filepath}:{node.lineno}: "
                        f"`from {node.module} import {name}` — "
                        f"'{name}' is a consumer-internal registry function; "
                        f"only consumer.py and its test files may use it"
                    )
            continue

        # Check: import orchestrator.workflow.signals.consumer (then .has_active_workflow)
        if isinstance(node, ast.Import):
            continue  # module-level imports are not how these are used

        # Check: Name references (calls like has_active_workflow(...))
        if isinstance(node, ast.Name) and node.id in RESTRICTED_NAMES:
            violations.append(
                f"{filepath}:{node.lineno}: "
                f"call to `{node.id}` — "
                f"'{node.id}' is a consumer-internal registry function; "
                f"only consumer.py and its test files may call it"
            )
            continue

        # Check: Attribute access like consumer.has_active_workflow(...)
        if isinstance(node, ast.Attribute) and node.attr in RESTRICTED_NAMES:
            violations.append(
                f"{filepath}:{node.lineno}: "
                f"access to `.{node.attr}` — "
                f"'{node.attr}' is a consumer-internal registry function; "
                f"only consumer.py and its test files may use it"
            )
            continue

    return violations


def main(paths: list[str]) -> int:
    all_violations: list[str] = []

    project_root: Path | None = find_project_root_from_script()
    if project_root is None and paths:
        project_root = find_project_root(Path(paths[0]))

    for path_str in paths:
        path = Path(path_str)
        if path.suffix == ".py" and path.exists():
            all_violations.extend(check_file(path, project_root))

    if all_violations:
        print("Signal routing violations found:", file=sys.stderr)
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nTo suppress a specific line, add:  # noqa: signal-routing",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
