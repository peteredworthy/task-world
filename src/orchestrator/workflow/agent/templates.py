"""Template interpolation for fan-out tasks and script execution."""

from __future__ import annotations

import re
from pathlib import Path

# Matches innermost {{...}} only — no { or } inside the capture group.
# This ensures nested patterns like {{file:docs/{{feature}}/plan.md}} resolve
# inside-out: {{feature}} first, then {{file:...}} in the next pass.
_INNER_RE = re.compile(r"\{\{([^{}]+)\}\}")

# Broader pattern for detecting any placeholder (including nested).
_ANY_PLACEHOLDER_RE = re.compile(r"\{\{.+?\}\}")


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

    Resolution is two-pass so that nested patterns like
    ``{{file:docs/{{feature}}/plan.md}}`` work correctly:

    1. Resolve innermost non-``file:`` variables (e.g. ``{{feature}}`` inside
       a ``{{file:...}}`` path)
    2. Resolve ``{{file:...}}`` references (paths now have variables filled in)
    """

    if not _INNER_RE.search(template):
        return template

    vars_ = variables or {}

    # Pass 1: resolve innermost plain variables only (leave {{file:...}} for pass 2)
    def _replace_vars(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key.startswith("file:"):
            return match.group(0)  # leave for pass 2
        if key in vars_:
            return vars_[key]
        return match.group(0)

    result = _INNER_RE.sub(_replace_vars, template)

    # Pass 2: resolve {{file:...}} references (variables already substituted)
    if "{{file:" not in result:
        return result

    def _replace_files(match: re.Match[str]) -> str:
        key = match.group(1).strip()
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
        # Leftover variable — leave unchanged
        return match.group(0)

    return _INNER_RE.sub(_replace_files, result)


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
