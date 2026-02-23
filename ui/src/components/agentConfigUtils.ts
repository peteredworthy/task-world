import type { AgentOption } from '../types/agents';

const AGENT_MODEL_DEFAULTS_KEY = 'agent-model-defaults';

export function loadAgentModelDefaults(): Record<string, string> {
    try {
        const stored = localStorage.getItem(AGENT_MODEL_DEFAULTS_KEY);
        return stored ? (JSON.parse(stored) as Record<string, string>) : {};
    } catch {
        return {};
    }
}

export function saveAgentModelDefault(agentName: string, model: string): void {
    try {
        const current = loadAgentModelDefaults();
        localStorage.setItem(AGENT_MODEL_DEFAULTS_KEY, JSON.stringify({ ...current, [agentName]: model }));
    } catch {
        // ignore
    }
}

/**
 * Build a default config record from an agent's config schema.
 * Skips secret fields (don't pre-fill passwords).
 */
export function buildDefaultAgentConfig(agent: AgentOption): Record<string, unknown> {
    const config: Record<string, unknown> = {};
    for (const field of agent.config_schema) {
        if (field.default !== null && field.default !== undefined && field.field_type !== 'secret') {
            config[field.name] = field.default;
        }
    }
    // Apply user-configured model override (set via the Agents page).
    const modelOverride = loadAgentModelDefaults()[agent.name];
    if (modelOverride) {
        config.model = modelOverride;
    }
    // CLI backends share agent_type, so pin the selected command explicitly.
    if (agent.agent_type === 'cli_subprocess' && typeof config.command !== 'string') {
        config.command = agent.name;
    }
    return config;
}
