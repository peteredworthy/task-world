import type { AgentConfigField, AgentOption } from '../types/agents';

interface AgentConfigFormProps {
    agent: AgentOption;
    /** Current config values (field name → value) */
    values: Record<string, unknown>;
    /** Called with the full updated values map on any change */
    onChange: (values: Record<string, unknown>) => void;
    disabled?: boolean;
}

/** Render an appropriate input control for a single config field. */
function ConfigFieldInput({
    field,
    value,
    onChange,
    disabled,
}: {
    field: AgentConfigField;
    value: unknown;
    onChange: (value: unknown) => void;
    disabled?: boolean;
}) {
    const baseInputClass =
        'w-full rounded-md border border-border bg-bg-card px-3 py-2 text-sm text-text-primary ' +
        'shadow-sm placeholder:text-text-muted focus:border-accent-purple focus:outline-none ' +
        'focus:ring-1 focus:ring-accent-purple/50 disabled:opacity-60 disabled:cursor-not-allowed';

    // Combobox: allow_custom takes precedence — free-text input with dropdown suggestions.
    // Checked before field_type so it works even if field_type is "string" with options.
    if (field.allow_custom && field.options && field.options.length > 0) {
        const listId = `agent-config-${field.name}-list`;
        return (
            <>
                <input
                    id={`agent-config-${field.name}`}
                    type="text"
                    list={listId}
                    value={value != null ? String(value) : ''}
                    onChange={(e) => onChange(e.target.value || undefined)}
                    placeholder={field.default != null ? String(field.default) : `Select or type…`}
                    disabled={disabled}
                    className={baseInputClass}
                    autoComplete="off"
                />
                <datalist id={listId}>
                    {field.options.map((opt) => (
                        <option key={opt} value={opt} />
                    ))}
                </datalist>
            </>
        );
    }

    if (field.field_type === 'select' && field.options && field.options.length > 0) {
        return (
            <select
                id={`agent-config-${field.name}`}
                value={value != null ? String(value) : ''}
                onChange={(e) => onChange(e.target.value)}
                disabled={disabled}
                className={baseInputClass + ' appearance-none cursor-pointer'}
            >
                {value == null && <option value="">Select…</option>}
                {field.options.map((opt) => (
                    <option key={opt} value={opt}>
                        {opt}
                    </option>
                ))}
            </select>
        );
    }

    if (field.field_type === 'boolean') {
        return (
            <label className="flex items-center gap-2 cursor-pointer">
                <input
                    id={`agent-config-${field.name}`}
                    type="checkbox"
                    checked={Boolean(value)}
                    onChange={(e) => onChange(e.target.checked)}
                    disabled={disabled}
                    className="w-4 h-4 rounded border-border accent-accent-purple"
                />
                <span className="text-sm text-text-secondary">Enabled</span>
            </label>
        );
    }

    if (field.field_type === 'number') {
        return (
            <input
                id={`agent-config-${field.name}`}
                type="number"
                value={value != null ? String(value) : ''}
                onChange={(e) => {
                    const num = parseFloat(e.target.value);
                    onChange(isNaN(num) ? '' : num);
                }}
                placeholder={field.default != null ? String(field.default) : ''}
                disabled={disabled}
                className={baseInputClass}
            />
        );
    }

    if (field.field_type === 'secret') {
        return (
            <input
                id={`agent-config-${field.name}`}
                type="password"
                value={value != null ? String(value) : ''}
                onChange={(e) => onChange(e.target.value || undefined)}
                placeholder={field.default != null ? String(field.default) : `Enter ${field.name}…`}
                disabled={disabled}
                className={baseInputClass}
                autoComplete="off"
            />
        );
    }

    // Default: plain string input
    return (
        <input
            id={`agent-config-${field.name}`}
            type="text"
            value={value != null ? String(value) : ''}
            onChange={(e) => onChange(e.target.value || undefined)}
            placeholder={field.default != null ? String(field.default) : `Enter ${field.name}…`}
            disabled={disabled}
            className={baseInputClass}
        />
    );
}

/**
 * Renders a structured form for an agent's config schema.
 *
 * Each field in `agent.config_schema` is rendered with an appropriate
 * control (dropdown for "select", number input for "number", etc.).
 * The parent receives the full updated values map via `onChange`.
 */
export function AgentConfigForm({ agent, values, onChange, disabled }: AgentConfigFormProps) {
    if (agent.config_schema.length === 0) {
        return (
            <p className="text-xs text-text-muted py-1">This agent has no configurable fields.</p>
        );
    }

    function handleFieldChange(name: string, value: unknown) {
        onChange({ ...values, [name]: value });
    }

    return (
        <div className="space-y-3">
            {agent.config_schema.map((field) => {
                const currentValue = values[field.name];

                return (
                    <div key={field.name}>
                        <label
                            htmlFor={`agent-config-${field.name}`}
                            className="flex items-center gap-1 text-xs font-medium text-text-muted mb-1"
                        >
                            <span className="font-mono text-text-secondary">{field.name}</span>
                            {field.required && (
                                <span className="text-status-failed" title="Required">
                                    *
                                </span>
                            )}
                            {field.field_type === 'select' && field.options && (
                                <span className="ml-auto text-[10px] text-accent-purple font-normal uppercase tracking-wide">
                                    select
                                </span>
                            )}
                            {field.field_type === 'secret' && (
                                <span className="ml-auto text-[10px] text-text-muted font-normal uppercase tracking-wide">
                                    secret
                                </span>
                            )}
                        </label>

                        <ConfigFieldInput
                            field={field}
                            value={currentValue != null ? currentValue : field.default}
                            onChange={(val) => handleFieldChange(field.name, val)}
                            disabled={disabled}
                        />

                        {field.description && (
                            <p className="mt-0.5 text-[11px] text-text-muted">{field.description}</p>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

