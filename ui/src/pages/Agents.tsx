import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Spinner } from '../components/Spinner';
import { EmptyState } from '../components/EmptyState';
import { ConfirmDialog } from '../components/ConfirmDialog';
import {
  fetchAgents,
  createAgent,
  updateAgent,
  deleteAgent,
  resetAgentPrompt,
} from '../lib/agentApi';
import type { Agent, CreateAgentRequest, UpdateAgentRequest } from '../types/agents';
import type { ModelProfile } from '../types/modelProfiles';

const MODEL_PROFILES: { key: ModelProfile; label: string }[] = [
  { key: 'architect', label: 'Architect' },
  { key: 'designer', label: 'Designer' },
  { key: 'coder', label: 'Coder' },
  { key: 'summarizer', label: 'Summarizer' },
];

export function Agents() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ['agent-configs'],
    queryFn: fetchAgents,
  });

  const agents = data ?? [];

  const [editing, setEditing] = useState<Agent | null>(null);
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Agent | null>(null);

  function handleCreated() {
    qc.invalidateQueries({ queryKey: ['agent-configs'] });
    setCreating(false);
  }

  function handleUpdated() {
    qc.invalidateQueries({ queryKey: ['agent-configs'] });
    setEditing(null);
  }

  function handleDelete(agent: Agent) {
    setPendingDelete(agent);
  }

  function handleDeleteConfirmed() {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    setPendingDelete(null);
    deleteAgent(id).then(() => {
      qc.invalidateQueries({ queryKey: ['agent-configs'] });
    });
  }

  function handleDeleteCancelled() {
    setPendingDelete(null);
  }

  return (
    <div className="p-6 max-w-[1200px]">
      {/* Breadcrumb */}
      <nav className="mb-2 text-text-muted text-xs" aria-label="Breadcrumb">
        <ol className="flex items-center gap-1">
          <li>
            <Link to="/" className="hover:text-text-secondary transition-colors">
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
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text-primary">Agents</h1>
          <p className="text-text-secondary text-sm mt-1">
            Manage agent configurations with custom system prompts and model profiles.
          </p>
        </div>
        <button
          onClick={() => { setCreating(true); setEditing(null); }}
          className="px-4 py-2 rounded-md bg-accent-purple text-white text-sm font-medium hover:bg-accent-purple/80 transition-colors"
        >
          + New Agent
        </button>
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
          <p className="text-sm text-red-300">Failed to load agents. Is the backend running?</p>
        </div>
      )}

      {/* Create form */}
      {creating && (
        <div className="mb-6">
          <AgentEditor
            onSave={async (req) => {
              await createAgent(req as CreateAgentRequest);
              handleCreated();
            }}
            onCancel={() => setCreating(false)}
          />
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && agents.length === 0 && !creating && (
        <EmptyState message="No agents configured. Create one to get started." />
      )}

      {/* Agent list */}
      {!isLoading && !error && agents.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map((agent) =>
            editing?.id === agent.id ? (
              <div key={agent.id} className="col-span-full">
                <AgentEditor
                  initialValues={agent}
                  onSave={async (req) => {
                    await updateAgent(agent.id, req as UpdateAgentRequest);
                    handleUpdated();
                  }}
                  onCancel={() => setEditing(null)}
                  onReset={
                    agent.default_prompt
                      ? async () => {
                          await resetAgentPrompt(agent.id);
                          handleUpdated();
                        }
                      : undefined
                  }
                />
              </div>
            ) : (
              <AgentCard
                key={agent.id}
                agent={agent}
                onEdit={() => { setEditing(agent); setCreating(false); }}
                onDelete={() => handleDelete(agent)}
              />
            )
          )}
        </div>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete agent "${pendingDelete?.name}"?`}
        message="This will permanently remove the agent configuration. Any routines that reference this agent by name will fall back to the system default."
        confirmLabel="Delete"
        onConfirm={handleDeleteConfirmed}
        onCancel={handleDeleteCancelled}
      />
    </div>
  );
}

interface AgentCardProps {
  agent: Agent;
  onEdit: () => void;
  onDelete: () => void;
}

function AgentCard({ agent, onEdit, onDelete }: AgentCardProps) {
  const profile = MODEL_PROFILES.find((p) => p.key === agent.model_profile);
  const promptPreview = agent.system_prompt
    ? agent.system_prompt.slice(0, 100) + (agent.system_prompt.length > 100 ? '…' : '')
    : 'No system prompt';

  return (
    <div className="rounded-lg border bg-bg-card border-border hover:border-accent-purple/40 hover:shadow-md hover:shadow-accent-purple/10 transition-all p-4">
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-md bg-bg-elevated flex items-center justify-center text-lg">
            <span aria-hidden="true">&#x1f9e0;</span>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-text-primary">{agent.name}</h3>
            {profile && (
              <span className="text-[10px] text-text-muted uppercase tracking-wide">
                {profile.label}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onEdit}
            className="px-2 py-1 text-xs text-text-secondary hover:text-text-primary transition-colors"
            aria-label={`Edit ${agent.name}`}
          >
            Edit
          </button>
          <button
            onClick={onDelete}
            className="px-2 py-1 text-xs text-red-400 hover:text-red-300 transition-colors"
            aria-label={`Delete ${agent.name}`}
          >
            Delete
          </button>
        </div>
      </div>

      <p className="text-xs text-text-secondary line-clamp-3 font-mono mt-2">{promptPreview}</p>
    </div>
  );
}

interface AgentEditorProps {
  initialValues?: Agent;
  onSave: (req: CreateAgentRequest | UpdateAgentRequest) => Promise<void>;
  onCancel: () => void;
  onReset?: () => Promise<void>;
}

function AgentEditor({ initialValues, onSave, onCancel, onReset }: AgentEditorProps) {
  const [name, setName] = useState(initialValues?.name ?? '');
  const [modelProfile, setModelProfile] = useState<ModelProfile>(
    initialValues?.model_profile ?? 'coder'
  );
  const [systemPrompt, setSystemPrompt] = useState(initialValues?.system_prompt ?? '');
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const isEdit = !!initialValues;

  async function handleSave() {
    if (!name.trim()) {
      setSaveError('Name is required');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await onSave({ name: name.trim(), system_prompt: systemPrompt, model_profile: modelProfile });
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    if (!onReset) return;
    setResetting(true);
    try {
      await onReset();
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="rounded-lg border border-accent-purple/40 bg-bg-card p-5 space-y-4">
      <h2 className="text-sm font-semibold text-text-primary">
        {isEdit ? `Edit Agent: ${initialValues.name}` : 'New Agent'}
      </h2>

      {/* Name */}
      <div>
        <label className="block text-[10px] font-medium text-text-muted uppercase tracking-wide mb-1">
          Name
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. my-custom-agent"
          className="w-full rounded border border-border bg-bg-elevated px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:border-accent-purple/50"
        />
      </div>

      {/* Model Profile */}
      <div>
        <label className="block text-[10px] font-medium text-text-muted uppercase tracking-wide mb-1">
          Model Profile
        </label>
        <select
          value={modelProfile}
          onChange={(e) => setModelProfile(e.target.value as ModelProfile)}
          className="w-full rounded border border-border bg-bg-elevated px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:border-accent-purple/50 appearance-none cursor-pointer"
        >
          {MODEL_PROFILES.map(({ key, label }) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {/* System Prompt */}
      <div>
        <label className="block text-[10px] font-medium text-text-muted uppercase tracking-wide mb-1">
          System Prompt
        </label>
        <textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          rows={8}
          placeholder="Enter the agent's system prompt…"
          className="w-full rounded border border-border bg-bg-elevated px-3 py-2 text-sm font-mono text-text-primary focus:outline-none focus:border-accent-purple/50 resize-y"
        />
      </div>

      {saveError && (
        <p className="text-xs text-red-400">{saveError}</p>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-1.5 rounded bg-accent-purple text-white text-sm font-medium hover:bg-accent-purple/80 transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-1.5 rounded border border-border text-sm text-text-secondary hover:text-text-primary transition-colors"
        >
          Cancel
        </button>
        {onReset && (
          <button
            onClick={handleReset}
            disabled={resetting}
            className="ml-auto px-4 py-1.5 rounded border border-amber-700/50 bg-amber-900/20 text-sm text-amber-300 hover:bg-amber-900/30 transition-colors disabled:opacity-50"
          >
            {resetting ? 'Resetting…' : 'Reset to Default'}
          </button>
        )}
      </div>
    </div>
  );
}
