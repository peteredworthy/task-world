import { useState } from 'react';
import { api } from '../api/client';

const DEFAULT_LOCAL_BASE_URL = 'http://localhost:1234/v1';

const baseInputClass =
    'w-full rounded-md border border-border bg-bg-card px-3 py-2 text-sm text-text-primary ' +
    'shadow-sm placeholder:text-text-muted focus:border-accent-purple focus:outline-none ' +
    'focus:ring-1 focus:ring-accent-purple/50 disabled:opacity-60 disabled:cursor-not-allowed';

interface OpenHandsLLMTabsProps {
    values: Record<string, unknown>;
    onChange: (values: Record<string, unknown>) => void;
    disabled?: boolean;
}

/**
 * Tabbed LLM config UI for OpenHands agents.
 *
 * "API / Cloud" tab: model + api_key. Clears base_url from values.
 * "Local LLM" tab: base_url + Connect → model dropdown + model_canonical_name + optional api_key.
 */
export function OpenHandsLLMTabs({ values, onChange, disabled }: OpenHandsLLMTabsProps) {
    const isLocalTab = Boolean(values['base_url']);
    const [tab, setTab] = useState<'cloud' | 'local'>(isLocalTab ? 'local' : 'cloud');
    const [localBaseUrl, setLocalBaseUrl] = useState<string>(
        (values['base_url'] as string) || DEFAULT_LOCAL_BASE_URL,
    );
    const [discoveredModels, setDiscoveredModels] = useState<string[]>(
        values['base_url'] ? (values['model'] ? [values['model'] as string] : []) : [],
    );
    const [connectError, setConnectError] = useState<string | null>(null);
    const [connecting, setConnecting] = useState(false);

    function switchToCloud() {
        setTab('cloud');
        // Clear base_url from values
        const updated = { ...values };
        delete updated['base_url'];
        onChange(updated);
    }

    function switchToLocal() {
        setTab('local');
        const url = (values['base_url'] as string) || DEFAULT_LOCAL_BASE_URL;
        setLocalBaseUrl(url);
        onChange({ ...values, base_url: url });
    }

    async function handleConnect() {
        setConnecting(true);
        setConnectError(null);
        try {
            const result = await api.discoverLocalModels(localBaseUrl);
            if (result.error) {
                setConnectError(result.error);
                setDiscoveredModels([]);
            } else {
                setDiscoveredModels(result.models);
                // Auto-select first model if none selected or current not in list
                const currentModel = values['model'] as string | undefined;
                if (result.models.length > 0 && (!currentModel || !result.models.includes(currentModel))) {
                    onChange({ ...values, base_url: localBaseUrl, model: result.models[0] });
                } else {
                    onChange({ ...values, base_url: localBaseUrl });
                }
            }
        } finally {
            setConnecting(false);
        }
    }

    const tabClass = (active: boolean) =>
        'px-4 py-2 text-sm font-medium rounded-t-md border-b-2 transition-colors cursor-pointer ' +
        (active
            ? 'border-accent-purple text-accent-purple bg-bg-card'
            : 'border-transparent text-text-muted hover:text-text-secondary hover:border-border');

    return (
        <div className="space-y-3">
            {/* Tab bar */}
            <div className="flex gap-1 border-b border-border">
                <button
                    type="button"
                    className={tabClass(tab === 'cloud')}
                    onClick={switchToCloud}
                    disabled={disabled}
                >
                    API / Cloud
                </button>
                <button
                    type="button"
                    className={tabClass(tab === 'local')}
                    onClick={switchToLocal}
                    disabled={disabled}
                >
                    Local LLM
                </button>
            </div>

            {tab === 'cloud' && (
                <div className="space-y-3">
                    {/* model */}
                    <div>
                        <label className="flex items-center gap-1 text-xs font-medium text-text-muted mb-1">
                            <span className="font-mono text-text-secondary">model</span>
                        </label>
                        <input
                            type="text"
                            value={values['model'] != null ? String(values['model']) : ''}
                            onChange={(e) => onChange({ ...values, model: e.target.value || undefined })}
                            placeholder="gpt-5-mini"
                            disabled={disabled}
                            className={baseInputClass}
                        />
                        <p className="mt-0.5 text-[11px] text-text-muted">LLM model to use</p>
                    </div>
                    {/* api_key */}
                    <div>
                        <label className="flex items-center gap-1 text-xs font-medium text-text-muted mb-1">
                            <span className="font-mono text-text-secondary">api_key</span>
                            <span className="ml-auto text-[10px] text-text-muted font-normal uppercase tracking-wide">
                                secret
                            </span>
                        </label>
                        <input
                            type="password"
                            value={values['api_key'] != null ? String(values['api_key']) : ''}
                            onChange={(e) => onChange({ ...values, api_key: e.target.value || undefined })}
                            placeholder="Enter api_key…"
                            disabled={disabled}
                            className={baseInputClass}
                            autoComplete="off"
                        />
                        <p className="mt-0.5 text-[11px] text-text-muted">
                            OpenAI API key. Falls back to OPENAI_API_KEY env var.
                        </p>
                    </div>
                </div>
            )}

            {tab === 'local' && (
                <div className="space-y-3">
                    {/* base_url + Connect */}
                    <div>
                        <label className="flex items-center gap-1 text-xs font-medium text-text-muted mb-1">
                            <span className="font-mono text-text-secondary">base_url</span>
                        </label>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={localBaseUrl}
                                onChange={(e) => {
                                    setLocalBaseUrl(e.target.value);
                                    onChange({ ...values, base_url: e.target.value || undefined });
                                }}
                                placeholder={DEFAULT_LOCAL_BASE_URL}
                                disabled={disabled}
                                className={baseInputClass}
                            />
                            <button
                                type="button"
                                onClick={handleConnect}
                                disabled={disabled || connecting || !localBaseUrl}
                                className="shrink-0 rounded-md border border-border bg-bg-card px-3 py-2 text-sm text-text-secondary hover:text-text-primary hover:border-accent-purple transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                {connecting ? 'Connecting…' : 'Connect'}
                            </button>
                        </div>
                        {connectError && (
                            <p className="mt-1 text-[11px] text-status-failed">{connectError}</p>
                        )}
                        <p className="mt-0.5 text-[11px] text-text-muted">
                            Base URL of your local OpenAI-compatible server (LM Studio, Ollama, etc.)
                        </p>
                    </div>

                    {/* model dropdown (populated after Connect) */}
                    <div>
                        <label className="flex items-center gap-1 text-xs font-medium text-text-muted mb-1">
                            <span className="font-mono text-text-secondary">model</span>
                            {discoveredModels.length > 0 && (
                                <span className="ml-auto text-[10px] text-accent-purple font-normal uppercase tracking-wide">
                                    select
                                </span>
                            )}
                        </label>
                        {discoveredModels.length > 0 ? (
                            <select
                                value={values['model'] != null ? String(values['model']) : ''}
                                onChange={(e) => onChange({ ...values, model: e.target.value || undefined })}
                                disabled={disabled}
                                className={baseInputClass + ' appearance-none cursor-pointer'}
                            >
                                {values['model'] == null && <option value="">Select model…</option>}
                                {discoveredModels.map((m) => (
                                    <option key={m} value={m}>
                                        {m}
                                    </option>
                                ))}
                            </select>
                        ) : (
                            <input
                                type="text"
                                value={values['model'] != null ? String(values['model']) : ''}
                                onChange={(e) => onChange({ ...values, model: e.target.value || undefined })}
                                placeholder="Click Connect to discover models, or type manually"
                                disabled={disabled}
                                className={baseInputClass}
                            />
                        )}
                        <p className="mt-0.5 text-[11px] text-text-muted">Model ID served by your local LLM</p>
                    </div>

                    {/* model_canonical_name */}
                    <div>
                        <label className="flex items-center gap-1 text-xs font-medium text-text-muted mb-1">
                            <span className="font-mono text-text-secondary">model_canonical_name</span>
                        </label>
                        <input
                            type="text"
                            value={values['model_canonical_name'] != null ? String(values['model_canonical_name']) : ''}
                            onChange={(e) =>
                                onChange({ ...values, model_canonical_name: e.target.value || undefined })
                            }
                            placeholder="e.g. openai/gpt-4o"
                            disabled={disabled}
                            className={baseInputClass}
                        />
                        <p className="mt-0.5 text-[11px] text-text-muted">
                            Canonical model name for capability lookups. Required when using a custom model name.
                        </p>
                    </div>

                    {/* api_key (optional for local) */}
                    <div>
                        <label className="flex items-center gap-1 text-xs font-medium text-text-muted mb-1">
                            <span className="font-mono text-text-secondary">api_key</span>
                            <span className="ml-auto text-[10px] text-text-muted font-normal uppercase tracking-wide">
                                secret · optional
                            </span>
                        </label>
                        <input
                            type="password"
                            value={values['api_key'] != null ? String(values['api_key']) : ''}
                            onChange={(e) => onChange({ ...values, api_key: e.target.value || undefined })}
                            placeholder="API key (optional — most local servers don't require one)"
                            disabled={disabled}
                            className={baseInputClass}
                            autoComplete="off"
                        />
                    </div>
                </div>
            )}
        </div>
    );
}
