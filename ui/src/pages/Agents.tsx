import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAgents } from '../hooks/useApi';
import { Spinner } from '../components/Spinner';
import { EmptyState } from '../components/EmptyState';
import { AgentConfigForm } from '../components/AgentConfigForm';
import {
  loadAgentModelDefaults,
  saveAgentModelDefault,
  loadAgentFieldDefaults,
  saveAgentFieldDefault,
} from '../components/agentConfigUtils';
import type { AgentOption } from '../types/agents';

export function Agents() {
  const { data, isLoading, error } = useAgents();

  const agents = data ?? [];
  const available = agents.filter((a) => a.available);
  const unavailable = agents.filter((a) => !a.available);

  return (
    <div className="p-6 max-w-[1200px]">
      {/* Breadcrumb */}
      <nav className="mb-2 text-text-muted text-xs" aria-label="Breadcrumb">
        <ol className="flex items-center gap-1">
          <li>
            <Link
              to="/"
              className="hover:text-text-secondary transition-colors"
            >
              Home
            </Link>
          </li>
          <li aria-hidden="true">/</li>
          <li className="text-text-secondary" aria-current="page">
            Agents
          </li>
        </ol>
      </nav>

      {/* Title row */}
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-text-primary">Agents</h1>
        <p className="text-text-secondary text-sm mt-1">
          Available agent backends for executing tasks. Configure agents to
          integrate different coding tools and LLM providers.
        </p>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex justify-center py-16">
          <Spinner className="h-6 w-6" />
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="rounded-md bg-red-900/20 border border-red-800/50 p-4 mb-6">
          <p className="text-sm text-red-300">
            Failed to load agents. Is the backend running?
          </p>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && agents.length === 0 && (
        <EmptyState message="No agents configured." />
      )}

      {/* Available agents section */}
      {!isLoading && !error && available.length > 0 && (
        <section className="mb-8" aria-label="Available Agents">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-sm font-semibold text-text-primary">
              Available
            </h2>
            <span className="text-text-muted font-normal text-xs">
              ({available.length})
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {available.map((agent) => (
              <AgentCard key={agent.name} agent={agent} />
            ))}
          </div>
        </section>
      )}

      {/* Unavailable agents section */}
      {!isLoading && !error && unavailable.length > 0 && (
        <section className="mb-8" aria-label="Unavailable Agents">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-sm font-semibold text-text-primary">
              Unavailable
            </h2>
            <span className="text-text-muted font-normal text-xs">
              ({unavailable.length})
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {unavailable.map((agent) => (
              <AgentCard key={agent.name} agent={agent} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function AgentCard({ agent }: { agent: AgentOption }) {
  // Promote model and restrictions to interactive controls; hide secrets and those two from the bullet list
  const modelField = agent.config_schema.find((f) => f.name === 'model');
  const restrictionsField = agent.config_schema.find((f) => f.name === 'restrictions');
  const otherFields = agent.config_schema.filter(
    (f) => f.name !== 'model' && f.name !== 'restrictions' && f.field_type !== 'secret',
  );

  const savedFieldDefaults = loadAgentFieldDefaults(agent.name);

  const storedModel = loadAgentModelDefaults()[agent.name];
  const initialModel = storedModel ?? (modelField?.default != null ? String(modelField.default) : '');
  const [modelValue, setModelValue] = useState(initialModel);

  const initialRestrictions =
    savedFieldDefaults['restrictions'] ??
    (restrictionsField?.default != null ? String(restrictionsField.default) : '');
  const [restrictionsValue, setRestrictionsValue] = useState(initialRestrictions);

  const [showFullConfig, setShowFullConfig] = useState(false);
  const [fullConfigValues, setFullConfigValues] = useState<Record<string, unknown>>(() => {
    const values: Record<string, unknown> = {};
    agent.config_schema.forEach((field) => {
      values[field.name] = savedFieldDefaults[field.name] ?? field.default;
    });
    return values;
  });

  const handleFullConfigChange = (values: Record<string, unknown>) => {
    setFullConfigValues(values);
    // Persist each field (preserve type: arrays stay arrays, strings stay strings)
    agent.config_schema.forEach((field) => {
      if (values[field.name] !== undefined && values[field.name] !== null) {
        saveAgentFieldDefault(agent.name, field.name, values[field.name]);
      }
    });
  };

  const selectClass =
    'w-full rounded border border-border bg-bg-elevated px-2 py-1 text-xs font-mono text-text-primary focus:outline-none focus:border-accent-purple/50 appearance-none cursor-pointer';

  return (
    <div
      className={
        'rounded-lg border p-4 transition-all ' +
        (agent.available
          ? 'bg-bg-card border-border hover:border-accent-purple/40 hover:shadow-md hover:shadow-accent-purple/10'
          : 'bg-bg-elevated/50 border-border/50 opacity-60')
      }
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-md bg-bg-elevated flex items-center justify-center text-lg">
            <span aria-hidden="true">&#x1f916;</span>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-text-primary">
              {agent.title || agent.name}
            </h3>
          </div>
        </div>
        {agent.available ? (
          <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-green-900/30 border border-green-700/40 text-xs font-medium text-green-300">
            Ready
          </span>
        ) : (
          <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-bg-elevated border border-border text-xs font-medium text-text-muted">
            Not Available
          </span>
        )}
      </div>

      <p className="text-xs text-text-secondary mb-3 line-clamp-2">
        {agent.description}
      </p>

      <div className="text-xs text-text-muted mb-3">
        <p className="font-mono">{agent.detail}</p>
      </div>

      {!agent.available && agent.install_hint && (
        <div className="text-xs text-text-secondary bg-bg-elevated/50 border border-border/50 rounded-md p-2">
          <p className="font-medium text-text-primary mb-1">
            Installation hint:
          </p>
          <p className="font-mono">{agent.install_hint}</p>
        </div>
      )}

      {agent.available && (
        <div className="mt-3 pt-3 border-t border-border/50 space-y-2">
          {/* Model — combobox: free-text with dropdown suggestions from discovered models */}
          {modelField && (
            <div>
              <p className="text-[10px] font-medium text-text-muted uppercase tracking-wide mb-1">
                Default model
              </p>
              <input
                type="text"
                list={`${agent.name}-model-list`}
                value={modelValue}
                onChange={(e) => {
                  setModelValue(e.target.value);
                  saveAgentModelDefault(agent.name, e.target.value);
                }}
                placeholder={modelField.default != null ? String(modelField.default) : 'Select or type model…'}
                className="w-full rounded border border-border bg-bg-elevated px-2 py-1 text-xs font-mono text-text-primary focus:outline-none focus:border-accent-purple/50"
                autoComplete="off"
              />
              {modelField.options && modelField.options.length > 0 && (
                <datalist id={`${agent.name}-model-list`}>
                  {modelField.options.map((opt) => (
                    <option key={opt} value={opt} />
                  ))}
                </datalist>
              )}
            </div>
          )}

          {/* Restrictions — interactive select for agents that expose it */}
          {restrictionsField && restrictionsField.options && restrictionsField.options.length > 0 && (
            <div>
              <p className="text-[10px] font-medium text-text-muted uppercase tracking-wide mb-1">
                Restrictions
              </p>
              <select
                className={selectClass}
                value={restrictionsValue}
                onChange={(e) => {
                  setRestrictionsValue(e.target.value);
                  saveAgentFieldDefault(agent.name, 'restrictions', e.target.value);
                }}
              >
                {restrictionsField.options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
              {restrictionsField.description && (
                <p className="mt-0.5 text-[10px] text-text-muted">{restrictionsField.description}</p>
              )}
            </div>
          )}

          {/* Toggle button for full configuration */}
          {agent.config_schema.length > 0 && (
            <button
              onClick={() => setShowFullConfig(!showFullConfig)}
              className="mt-2 text-xs font-medium text-accent-purple hover:text-accent-purple/80 transition-colors"
            >
              {showFullConfig ? '▼ Hide all options' : '▶ Show all options'}
            </button>
          )}

          {/* Full configuration form (expandable) */}
          {showFullConfig && (
            <div className="mt-3 pt-3 border-t border-border/50">
              <AgentConfigForm
                agent={agent}
                values={fullConfigValues}
                onChange={handleFullConfigChange}
                disabled={!agent.available}
              />
            </div>
          )}

          {/* Other visible config fields (read-only summary) — only when not expanded */}
          {!showFullConfig && otherFields.length > 0 && (
            <div>
              <p className="text-[10px] font-medium text-text-muted uppercase tracking-wide mb-1">
                Config fields
              </p>
              <ul className="text-xs text-text-secondary space-y-0.5">
                {otherFields.slice(0, 3).map((field) => (
                  <li key={field.name} className="flex items-center gap-1">
                    <span className="text-text-muted">•</span>
                    <span className="font-mono">{field.name}</span>
                    <span className="text-text-muted">
                      ({field.field_type})
                    </span>
                    {field.default != null && (
                      <span className="text-text-muted truncate max-w-[80px]">
                        = {String(field.default)}
                      </span>
                    )}
                  </li>
                ))}
                {otherFields.length > 3 && (
                  <li className="text-text-muted italic">
                    +{otherFields.length - 3} more
                  </li>
                )}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
