"""Pure ``{{key}}`` placeholder substitution against a flat variables dict.

Deliberately dependency-free (no IO, no subprocess) so the graph kernel
(``src/orchestrator/graph/`` — see AGENTS.md kernel-purity rule) can import
it directly instead of hand-rolling its own copy. For file-content
interpolation (``{{file:path}}``) use
``orchestrator.workflow.agent.templates.resolve_template`` instead, which
layers that IO-based behavior on top of the same plain-variable pass.
"""

from __future__ import annotations

from typing import Any


def resolve_plain_variables(template: str, variables: dict[str, Any] | None) -> str:
    """Replace every ``{{key}}`` with ``str(variables[key])``.

    Keys with no matching entry in *variables* are left as literal
    ``{{key}}`` text rather than raising, so partially-configured run
    contexts don't crash command resolution.
    """
    if not variables:
        return template
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result
