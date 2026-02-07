import { useTaskPrompt } from '../../hooks/useApi';
import { getAuthToken } from '../../api/client';
import { PromptCopyBox } from './PromptCopyBox';
import { WaitingIndicator } from './WaitingIndicator';
import { Spinner } from '../Spinner';
import type { RunResponse, TaskSummary } from '../../types';

interface AgentGuidancePanelProps {
  run: RunResponse;
  task: TaskSummary;
  onCancel?: () => void;
}

export function AgentGuidancePanel({ run, task, onCancel }: AgentGuidancePanelProps) {
  const { data: prompt, isLoading } = useTaskPrompt(run.id, task.id);
  const token = getAuthToken();
  const mcpUrl = window.location.origin + '/mcp/sse';

  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <Spinner className="h-4 w-4" />
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

      {prompt && (
        <>
          <PromptCopyBox label="System Prompt" content={prompt.system} />
          <PromptCopyBox label="User Prompt" content={prompt.user} />
        </>
      )}

      <div>
        <span className="text-xs font-semibold text-text-muted uppercase tracking-wide">MCP SSE Endpoint</span>
        <div className="mt-1 bg-bg-elevated rounded px-3 py-2 text-sm font-mono text-text-secondary break-all">
          {mcpUrl}
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

      <WaitingIndicator startedAt={run.started_at} onCancel={onCancel} />
    </div>
  );
}
