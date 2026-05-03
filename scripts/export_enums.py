"""
export_enums.py — Generate ui/src/types/generated-enums.ts from Python str enums.

Usage:
  uv run python scripts/export_enums.py              # write to default output path
  uv run python scripts/export_enums.py --out PATH   # write to custom path
  uv run python scripts/export_enums.py --check      # compare without writing; exit 1 if stale
"""

import argparse
import difflib
import importlib.util
import inspect
import os
import sys
from enum import Enum

# Ensure the project root is on sys.path so orchestrator imports work.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SOURCE_REL = "src/orchestrator/config/enums.py"
DEFAULT_OUT_REL = "ui/src/types/generated-enums.ts"

HEADER = """\
// AUTO-GENERATED — do not edit by hand.
// Source: {source}
// Run `uv run python scripts/export_enums.py` to regenerate.
"""


def load_enums_module(project_root: str):
    """Dynamically load the enums module and return it."""
    enums_path = os.path.join(project_root, SOURCE_REL)
    spec = importlib.util.spec_from_file_location("orchestrator.config.enums", enums_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {enums_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def is_str_enum(obj) -> bool:
    """Return True if obj is a class that inherits from both str and Enum."""
    return (
        inspect.isclass(obj) and issubclass(obj, str) and issubclass(obj, Enum) and obj is not Enum
    )


def enum_to_ts_union(enum_cls) -> str:
    """Convert a str-enum class to a TypeScript union type declaration."""
    members = [f"'{member.value}'" for member in enum_cls]
    union = " | ".join(members)
    return f"export type {enum_cls.__name__} = {union};"


def generate_output(module) -> str:
    """Build the full TypeScript file content from the enums module."""
    lines = [HEADER.format(source=SOURCE_REL)]

    # inspect.getmembers sorts alphabetically; use module.__dict__ to preserve
    # source-file definition order (Python 3.7+ dicts are insertion-ordered).
    for _name, obj in module.__dict__.items():
        if is_str_enum(obj):
            lines.append(enum_to_ts_union(obj))
            lines.append("")  # blank line after each type

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export Python str-enums to TypeScript union types."
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output file path (default: ui/src/types/generated-enums.ts)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check mode: exit 1 with diff if output would change; do not write.",
    )
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = args.out or os.path.join(project_root, DEFAULT_OUT_REL)

    module = load_enums_module(project_root)
    expected = generate_output(module)

    if args.check:
        try:
            with open(out_path, "r", encoding="utf-8") as fh:
                current = fh.read()
        except FileNotFoundError:
            current = ""

        if current == expected:
            print(f"OK: {out_path} is up to date.")
            return 0

        diff = difflib.unified_diff(
            current.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=out_path,
            tofile="<expected>",
        )
        sys.stderr.write(
            f"STALE: {out_path} is out of date. "
            "Run `uv run python scripts/export_enums.py` to regenerate.\n\n"
        )
        sys.stderr.writelines(diff)
        return 1

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(expected)
    print(f"Written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
