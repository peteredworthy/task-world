"""Agent runner model-profile default resolution utilities."""

from orchestrator.config.enums import ModelProfile


def resolve_model_for_profile(
    profile: ModelProfile | None,
    model_profile_defaults: dict[str, str],
    fallback_model: str | None = None,
) -> str | None:
    """Resolve model for a task profile using the fallback chain.

    Resolution order:
    1. Per-run profile overrides (future — not yet implemented)
    2. Agent runner model defaults (model_profile_defaults, keyed by profile.value)
    3. Runner built-in default model (fallback_model from agent_runner_config)

    Args:
        profile: The task's assigned cognitive profile, if any.
        model_profile_defaults: Map of profile.value -> model string from runner DB defaults.
        fallback_model: The model from agent_runner_config or the agent's hard-coded default.

    Returns:
        Resolved model string, or None if no model is set anywhere.
    """
    if profile is not None:
        resolved = model_profile_defaults.get(profile.value)
        if resolved:
            return resolved
    return fallback_model
