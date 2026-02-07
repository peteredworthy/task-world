import { Link } from 'react-router-dom';
import { useAgents } from '../hooks/useApi';
import { Spinner } from '../components/Spinner';
import { EmptyState } from '../components/EmptyState';
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

      {agent.available && agent.config_schema.length > 0 && (
        <div className="mt-3 pt-3 border-t border-border/50">
          <p className="text-xs font-medium text-text-muted mb-1">
            Configuration fields:
          </p>
          <ul className="text-xs text-text-secondary space-y-0.5">
            {agent.config_schema.slice(0, 3).map((field) => (
              <li key={field.name} className="flex items-center gap-1">
                <span className="text-text-muted">•</span>
                <span className="font-mono">{field.name}</span>
                <span className="text-text-muted">
                  ({field.field_type})
                </span>
              </li>
            ))}
            {agent.config_schema.length > 3 && (
              <li className="text-text-muted italic">
                +{agent.config_schema.length - 3} more
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
