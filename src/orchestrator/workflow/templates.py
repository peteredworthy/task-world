"""Template interpolation for fan-out tasks and script execution."""

from __future__ import annotations

import re
from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"\{\{(.+?)\}\}")


def resolve_template(
    template: str,
    variables: dict[str, str] | None = None,
    worktree_path: str | None = None,
) -> str:
    """Resolve ``{{variable}}`` placeholders in a template string.

    Supported patterns:

    * ``{{name}}`` -- lookup in *variables* dict
    * ``{{file:path}}`` -- read file contents (relative to *worktree_path*)
    * ``{{item_content}}``, ``{{item_stem}}``, ``{{output_path}}`` -- aliases
      looked up in *variables*

    Resolution is single-pass: if a substituted value itself contains
    ``{{...}}`` markers they are **not** recursively expanded.
    """

    if not _PLACEHOLDER_RE.search(template):
        return template

    vars_ = variables or {}

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()

        # {{file:some/path.md}} — read file contents
        if key.startswith("file:"):
            rel_path = key[len("file:") :]
            if worktree_path:
                full = Path(worktree_path) / rel_path
            else:
                full = Path(rel_path)
            try:
                return full.read_text()
            except (FileNotFoundError, IsADirectoryError, OSError):
                return f"[File not found: {rel_path}]"

        # Plain variable lookup
        if key in vars_:
            return vars_[key]

        # Unknown placeholder — leave unchanged
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_replace, template)


def derive_output_path(
    output_pattern: str,
    input_path: str,
    variables: dict[str, str] | None = None,
) -> str:
    """Derive output file path from *output_pattern* and *input_path*.

    Replaces ``{{item_stem}}`` with the input filename without its extension,
    then resolves any remaining ``{{variable}}`` placeholders from *variables*.
    """

    stem = Path(input_path).stem
    result = output_pattern.replace("{{item_stem}}", stem)
    if variables:
        result = resolve_template(result, variables)
    return result
