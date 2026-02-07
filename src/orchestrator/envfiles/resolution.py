"""Environment file resolution logic.

Resolves env file specs from routine config and request overrides.
"""

from typing import Any

from orchestrator.config.models import EnvFileConfig
from orchestrator.envfiles.models import EnvFileSpec


def resolve_env_specs(
    routine_specs: list[EnvFileConfig] | None = None,
    request_specs: list[dict[str, Any]] | None = None,
) -> list[EnvFileSpec]:
    """Resolve env file specs from routine config and request overrides.

    Resolution order: routine provides base, request overrides.
    Request specs completely replace routine specs if provided.

    Args:
        routine_specs: EnvFileConfig items from routine YAML
        request_specs: Override specs from API request (list of {path, promote_on_success})

    Returns:
        Final list of EnvFileSpec to use for the run.
    """
    if request_specs is not None:
        # Request completely overrides
        return [
            EnvFileSpec(
                relative_path=s.get("path", s.get("relative_path", "")),
                promote_on_success=s.get("promote_on_success", False),
            )
            for s in request_specs
        ]

    if routine_specs:
        return [
            EnvFileSpec(
                relative_path=spec.path,
                promote_on_success=spec.promote_on_success,
            )
            for spec in routine_specs
        ]

    return []
