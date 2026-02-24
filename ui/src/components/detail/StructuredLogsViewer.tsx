import { useState } from 'react';
import { formatTokens } from '../../lib/format';
import type { ActionLog, ActionLogEntry } from '../../types';

interface StructuredLogsViewerProps {
  actionLog: ActionLog;
}

function ToolIcon({ name }: { name: string }) {
  const icons: Record<string, string> = {
    bash: '$',
    Bash: '$',
    read: 'R',
    Read: 'R',
    write: 'W',
    Write: 'W',
    edit: 'E',
    Edit: 'E',
    glob: 'G',
    Glob: 'G',
    grep: '?',
    Grep: '?',
    WebSearch: 'S',
    WebFetch: 'F',
    Task: 'T',
  };
  return (
    <span className="inline-flex w-5 h-5 items-center justify-center rounded bg-bg-hover text-[10px] font-bold text-text-muted shrink-0">
      {icons[name] || name.charAt(0).toUpperCase()}
    </span>
  );
}

function ToolCallPair({ entry, result }: { entry: ActionLogEntry; result?: ActionLogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const tu = entry.tool_use!;
  const tr = result?.tool_result;
  const statusLabel = tr ? (tr.success ? 'Success' : 'Failed') : null;

  return (
    <div className="rounded border border-border-hover bg-bg-card overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="w-full text-left px-2.5 py-1.5 flex items-center gap-2 hover:bg-bg-hover transition-colors"
      >
        <ToolIcon name={tu.tool_name} />
        <span className="text-xs text-text-secondary font-mono truncate flex-1">
          {tu.summary || tu.tool_name}
        </span>
        {statusLabel && (
          <span className={`inline-flex min-w-14 items-center justify-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${tr?.success ? 'bg-status-completed/15 text-status-completed' : 'bg-status-failed/15 text-status-failed'}`}>
            {statusLabel}
          </span>
        )}
        <svg
          className={`h-3 w-3 text-text-muted shrink-0 transition-transform ${expanded ? 'rotate-90' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </button>
      {expanded && (
        <div className="border-t border-border-hover">
          {/* Arguments */}
          {Object.keys(tu.arguments).length > 0 && (
            <div className="px-2.5 py-2 border-b border-border-hover">
              <span className="text-[10px] font-semibold text-text-muted uppercase block mb-1">Arguments</span>
              <pre className="text-[11px] text-text-secondary font-mono whitespace-pre-wrap max-h-40 overflow-y-auto">
                {JSON.stringify(tu.arguments, null, 2)}
              </pre>
            </div>
          )}
          {/* Result output */}
          {tr && tr.output && (
            <div className="px-2.5 py-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-semibold text-text-muted uppercase">Output</span>
                {tr.output_length > 5120 && (
                  <span className="text-[10px] text-text-muted">
                    truncated ({(tr.output_length / 1024).toFixed(1)}KB)
                  </span>
                )}
              </div>
              <pre className={`text-[11px] font-mono whitespace-pre-wrap max-h-60 overflow-y-auto ${tr.success ? 'text-text-secondary' : 'text-status-failed'}`}>
                {tr.output}
              </pre>
              {tr.exit_code !== null && tr.exit_code !== undefined && (
                <span className="text-[10px] text-text-muted mt-1 block">exit code {tr.exit_code}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EntryRenderer({ entry, resultMap }: { entry: ActionLogEntry; resultMap: Map<string, ActionLogEntry> }) {
  switch (entry.kind) {
    case 'system_init':
      return (
        <div className="text-[10px] text-text-muted italic py-1">
          {entry.text || 'Session started'}
        </div>
      );

    case 'assistant_text':
      return (
        <div className="rounded bg-bg-elevated border border-border px-3 py-2">
          <p className="text-xs text-text-primary whitespace-pre-wrap">{entry.text}</p>
          {entry.metrics && (entry.metrics.input_tokens > 0 || entry.metrics.output_tokens > 0) && (
            <div className="text-[10px] text-text-muted mt-1">
              {entry.metrics.input_tokens > 0 && <span>{formatTokens(entry.metrics.input_tokens)} in</span>}
              {entry.metrics.input_tokens > 0 && entry.metrics.output_tokens > 0 && ' / '}
              {entry.metrics.output_tokens > 0 && <span>{formatTokens(entry.metrics.output_tokens)} out</span>}
            </div>
          )}
        </div>
      );

    case 'thinking':
      return (
        <ThinkingBlock text={entry.text || ''} />
      );

    case 'tool_use': {
      const toolUseId = entry.tool_use?.tool_use_id || '';
      const result = toolUseId ? resultMap.get(toolUseId) : undefined;
      return <ToolCallPair entry={entry} result={result} />;
    }

    case 'tool_result':
      // Rendered as part of tool_use pair — skip standalone rendering
      return null;

    case 'result':
      return (
        <div className="rounded bg-bg-elevated border border-accent-purple/30 px-3 py-2">
          {entry.text && (
            <p className="text-xs text-text-primary whitespace-pre-wrap">{entry.text}</p>
          )}
          {entry.metrics && (
            <div className="text-[10px] text-text-muted mt-1 flex gap-3">
              {entry.metrics.input_tokens > 0 && <span>{formatTokens(entry.metrics.input_tokens)} input</span>}
              {entry.metrics.output_tokens > 0 && <span>{formatTokens(entry.metrics.output_tokens)} output</span>}
              {entry.metrics.cost_usd > 0 && <span>${entry.metrics.cost_usd.toFixed(4)}</span>}
            </div>
          )}
        </div>
      );

    case 'error':
      return (
        <div className="rounded bg-status-failed/10 border border-status-failed/30 px-3 py-2">
          <span className="text-[10px] font-semibold text-status-failed uppercase block mb-0.5">Error</span>
          <p className="text-xs text-status-failed whitespace-pre-wrap">{entry.text}</p>
        </div>
      );

    default:
      return null;
  }
}

function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const preview = text.length > 100 ? text.slice(0, 100) + '...' : text;

  return (
    <div className="rounded border border-border-hover bg-bg-card/50 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full text-left px-2.5 py-1.5 flex items-center gap-2 hover:bg-bg-hover transition-colors"
      >
        <span className="text-[10px] text-text-muted italic flex-1 truncate">
          {open ? 'Thinking...' : preview}
        </span>
        <svg
          className={`h-3 w-3 text-text-muted shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </button>
      {open && (
        <div className="border-t border-border-hover px-2.5 py-2">
          <p className="text-xs text-text-muted whitespace-pre-wrap">{text}</p>
        </div>
      )}
    </div>
  );
}

export function StructuredLogsViewer({ actionLog }: StructuredLogsViewerProps) {
  // Build a map from tool_use_id -> tool_result entry for pairing
  const resultMap = new Map<string, ActionLogEntry>();
  for (const entry of actionLog.entries) {
    if (entry.kind === 'tool_result' && entry.tool_result?.tool_use_id) {
      resultMap.set(entry.tool_result.tool_use_id, entry);
    }
  }

  // Filter out tool_result entries (they're rendered with their tool_use pair)
  const displayEntries = actionLog.entries.filter(e => e.kind !== 'tool_result');

  return (
    <div className="space-y-2">
      {/* Session header */}
      {actionLog.agent_model && (
        <div className="text-[10px] text-text-muted flex items-center gap-2 mb-1">
          <span>Model: {actionLog.agent_model}</span>
          {actionLog.total_turns > 0 && <span>| {actionLog.total_turns} turns</span>}
          {actionLog.total_cost_usd > 0 && <span>| ${actionLog.total_cost_usd.toFixed(4)}</span>}
          {actionLog.total_input_tokens > 0 && (
            <span>
              | {formatTokens(actionLog.total_input_tokens)} in
              {' / '}{formatTokens(actionLog.total_output_tokens)} out
              {(actionLog.total_cache_read_tokens + actionLog.total_cache_creation_tokens) > 0 && (
                <> / {formatTokens(actionLog.total_cache_read_tokens + actionLog.total_cache_creation_tokens)} cache</>
              )}
            </span>
          )}
        </div>
      )}

      {/* Entries */}
      {displayEntries.map((entry, index) => (
        <EntryRenderer
          key={`${entry.sequence_num}-${entry.kind}-${index}`}
          entry={entry}
          resultMap={resultMap}
        />
      ))}
    </div>
  );
}
