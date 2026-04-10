"""Config schema for OPENHANDS_LOCAL and OPENHANDS_DOCKER agents.

Extracted from ``detector.py``.
"""

from __future__ import annotations

from orchestrator.runners.types import AgentConfigField

OPENHANDS_LOCAL_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="model",
        field_type="string",
        default="gpt-5-mini",
        description="LLM model to use",
    ),
    AgentConfigField(
        name="max_iterations",
        field_type="number",
        default=100,
        description="Maximum agent iterations per run",
    ),
    AgentConfigField(
        name="max_actions",
        field_type="number",
        default=200,
        description="Hard ceiling on total agent actions (0 = disabled)",
    ),
    AgentConfigField(
        name="reasoning_effort",
        field_type="select",
        default="high",
        description="LLM reasoning effort level",
        options=["low", "medium", "high"],
    ),
    AgentConfigField(
        name="base_url",
        field_type="string",
        description="Local LLM base URL (e.g. http://localhost:1234/v1). Leave blank to use OpenAI.",
    ),
    AgentConfigField(
        name="timeout",
        field_type="number",
        default=1800,
        description="HTTP request timeout in seconds. Local LLMs may need 900-1800+.",
    ),
    AgentConfigField(
        name="model_canonical_name",
        field_type="string",
        description="Canonical model name for capability lookups (e.g. openai/gpt-4o). Required when using a local LLM with a custom model name.",
    ),
]

OPENHANDS_DOCKER_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="model",
        field_type="string",
        default="gpt-5-mini",
        description="LLM model to use",
    ),
    AgentConfigField(
        name="max_iterations",
        field_type="number",
        default=100,
        description="Maximum agent iterations per run",
    ),
    AgentConfigField(
        name="max_actions",
        field_type="number",
        default=200,
        description="Hard ceiling on total agent actions (0 = disabled)",
    ),
    AgentConfigField(
        name="server_image",
        field_type="string",
        default="orchestrator/agent-server:patched",
        description="Docker image for the agent server",
    ),
    AgentConfigField(
        name="reasoning_effort",
        field_type="select",
        default="high",
        description="LLM reasoning effort level",
        options=["low", "medium", "high"],
    ),
    AgentConfigField(
        name="base_url",
        field_type="string",
        description="Local LLM base URL (e.g. http://localhost:1234/v1). Leave blank to use OpenAI.",
    ),
    AgentConfigField(
        name="timeout",
        field_type="number",
        default=1800,
        description="HTTP request timeout in seconds. Local LLMs may need 900-1800+.",
    ),
    AgentConfigField(
        name="model_canonical_name",
        field_type="string",
        description="Canonical model name for capability lookups (e.g. openai/gpt-4o). Required when using a local LLM with a custom model name.",
    ),
]
