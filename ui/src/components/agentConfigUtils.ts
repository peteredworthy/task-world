import type { AgentOption } from '../types/agents';

const AGENT_MODEL_DEFAULTS_KEY = 'agent-model-defaults';
const AGENT_FIELD_DEFAULTS_KEY = 'agent-field-defaults';

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

/** Load all saved field overrides for a specific agent. */
export function loadAgentFieldDefaults(agentName: string): Record<string, string> {
    try {
        const stored = localStorage.getItem(AGENT_FIELD_DEFAULTS_KEY);
        const all = stored ? (JSON.parse(stored) as Record<string, Record<string, string>>) : {};
        return all[agentName] ?? {};
    } catch {
        return {};
    }
}

/** Persist a single field override for an agent. */
export function saveAgentFieldDefault(agentName: string, fieldName: string, value: unknown): void {
    try {
        const stored = localStorage.getItem(AGENT_FIELD_DEFAULTS_KEY);
        const all = stored ? (JSON.parse(stored) as Record<string, Record<string, unknown>>) : {};
        // Store as-is to preserve type (arrays stay arrays, strings stay strings)
        all[agentName] = { ...(all[agentName] ?? {}), [fieldName]: value };
        localStorage.setItem(AGENT_FIELD_DEFAULTS_KEY, JSON.stringify(all));
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
    // Apply any other field overrides saved via the Agents page.
    const fieldOverrides = loadAgentFieldDefaults(agent.name);
    for (const [key, val] of Object.entries(fieldOverrides)) {
        if (val !== '') {
            config[key] = val;
        }
    }
    // CLI backends share agent_type, so pin the selected command explicitly.
    if (agent.agent_type === 'cli_subprocess' && typeof config.command !== 'string') {
        config.command = agent.name;
    }
    return config;
}
