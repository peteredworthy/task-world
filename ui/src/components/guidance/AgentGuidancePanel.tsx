import { ApiError, getAuthToken } from '../../api/client';
import { useAgentStarted, useGuidance } from '../../hooks/useApi';
import { PromptCopyBox } from './PromptCopyBox';
import { WaitingIndicator } from './WaitingIndicator';
import { Spinner } from '../Spinner';
import type { RunResponse } from '../../types';

interface AgentGuidancePanelProps {
  run: RunResponse;
}

export function AgentGuidancePanel({ run }: AgentGuidancePanelProps) {
  const { data: guidance, isLoading, error } = useGuidance(run.id);
  const agentStarted = useAgentStarted(run.id);
  const token = getAuthToken();
  const isNotFound = error instanceof ApiError && error.status === 404;

  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <Spinner className="h-4 w-4" />
      </div>
    );
  }

  if (isNotFound) {
    return (
      <div className="bg-status-paused/10 border border-status-paused/30 rounded-lg p-4">
        <p className="text-sm text-text-secondary">No active task guidance available</p>
      </div>
    );
  }

  return (
    <div className="bg-status-paused/10 border border-status-paused/30 rounded-lg p-4 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-status-paused mb-1">Agent Guidance</h3>
        <p className="text-xs text-text-secondary">
          This run uses a user-managed agent. Copy the prompt below and use it with your preferred LLM tool.
          Connect via MCP to submit checklist updates and completion.
        </p>
      </div>

      {guidance && (
        <>
          <PromptCopyBox label="Task Prompt" content={guidance.prompt} />
        </>
      )}

      <div>
        <span className="text-xs font-semibold text-text-muted uppercase tracking-wide">MCP SSE Endpoint</span>
        <div className="mt-1 bg-bg-elevated rounded px-3 py-2 text-sm font-mono text-text-secondary break-all">
          {guidance?.mcp_url ?? 'Not available'}
        </div>
      </div>

      {token && (
        <div>
          <span className="text-xs font-semibold text-text-muted uppercase tracking-wide">Auth Token</span>
          <div className="mt-1 bg-bg-elevated rounded px-3 py-2 text-sm font-mono text-text-secondary break-all">
            Bearer {token}
          </div>
          <p className="text-xs text-text-muted mt-1">
            Use as Authorization header for REST, or ?token= query param for WebSocket.
          </p>
        </div>
      )}

      <div className="flex items-center justify-end">
        <button
          onClick={() => agentStarted.mutate()}
          disabled={agentStarted.isPending}
          className="px-3 py-1.5 text-xs font-medium rounded-md bg-status-active/15 text-status-active border border-status-active/30 hover:bg-status-active/25 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          I've started my agent
        </button>
      </div>

      <WaitingIndicator runId={run.id} startedAt={run.started_at} />
    </div>
  );
}
