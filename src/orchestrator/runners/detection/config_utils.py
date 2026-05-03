"""Shared configuration utilities for agent factories.

Extracted from ``executor.py`` so that individual agent factory modules can
coerce LLM config without importing the full executor.
"""

from __future__ import annotations

from typing import Any

_LLM_CONFIG_KEYS = {
    "reasoning_effort",
    "extended_thinking_budget",
    "temperature",
    "top_p",
    "max_output_tokens",
    "base_url",
    "timeout",
    "num_retries",
    "model_canonical_name",
}

# Keys in _LLM_CONFIG_KEYS that must be numeric (int or float).
# Frontend number inputs produce strings; coerce them here.
_NUMERIC_LLM_KEYS = {"timeout", "num_retries", "temperature", "top_p", "max_output_tokens"}


def coerce_llm_config(agent_runner_config: dict[str, Any]) -> dict[str, Any]:
    """Extract LLM config keys and coerce numeric strings to proper types.

    Args:
        agent_runner_config: The raw agent_runner_config dict from the run.

    Returns:
        A dict containing only LLM-relevant keys with numeric values
        properly coerced from strings.
    """
    result: dict[str, Any] = {}
    for k, v in agent_runner_config.items():
        if k not in _LLM_CONFIG_KEYS:
            continue
        if k in _NUMERIC_LLM_KEYS and isinstance(v, str):
            try:
                result[k] = int(v) if v.isdigit() else float(v)
            except (ValueError, TypeError):
                result[k] = v
        else:
            result[k] = v
    return result
