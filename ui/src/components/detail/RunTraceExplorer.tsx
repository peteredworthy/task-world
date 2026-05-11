import { useEffect, useMemo, useRef, useState } from 'react';
import type { WheelEvent } from 'react';
import { useRunTrace } from '../../hooks/useApi';
import { formatDuration, formatTokens } from '../../lib/format';
import { Spinner } from '../Spinner';
import type {
  ActionLogEntry,
  RunTraceAttempt,
  ToolResultDetail,
  ToolUseDetail,
  TurnMetrics,
} from '../../types';

type AccountingMode = 'context' | 'request' | 'delta';

interface TokenBreakdown {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
}

interface TraceBlock {
  rowKey: string;
  sequenceNum: number;
  label: string;
  toolName: string;
  leftPct: number;
  widthPct: number;
  tokens: TokenBreakdown;
  totalTokens: number;
  entry: ActionLogEntry;
  result: ActionLogEntry | null;
  estimated: boolean;
}

interface TraceRow {
  key: string;
  attempt: RunTraceAttempt;
  blocks: TraceBlock[];
  totalTokens: number;
}

interface PreparedTrace {
  rows: TraceRow[];
  totalTokens: number;
  totalToolCalls: number;
}

interface ScrollbarState {
  scrollLeft: number;
  scrollWidth: number;
  clientWidth: number;
}

const TOKEN_LEGEND = [
  { key: 'cacheRead', label: 'Cache read', className: 'bg-rose-700' },
  { key: 'cacheWrite', label: 'Cache write', className: 'bg-amber-500' },
  { key: 'input', label: 'Input', className: 'bg-cyan-700' },
  { key: 'output', label: 'Output', className: 'bg-emerald-200' },
] as const;

const MIN_TRACE_ZOOM = 1;
const MAX_TRACE_ZOOM = 80;

const MODE_LABELS: Record<AccountingMode, string> = {
  context: 'Attempt context',
  request: 'Request charged',
  delta: 'Call delta',
};

const MODE_HELP: Record<AccountingMode, string> = {
  context: 'Repeats the accumulated context at each call to show cache pressure across the attempt.',
  request: 'Uses the token usage reported on each model request and shares it across tool calls in that request.',
  delta: 'Estimates only the input and output caused by the tool call itself, ignoring accumulated context.',
};

function metricTotal(metrics: TurnMetrics | null | undefined): number {
  if (!metrics) return 0;
  return (
    metrics.input_tokens +
    metrics.output_tokens +
    metrics.cache_read_tokens +
    metrics.cache_creation_tokens
  );
}

function hasMetric(metrics: TurnMetrics | null | undefined): metrics is TurnMetrics {
  return metricTotal(metrics) > 0;
}

function divideMetric(metrics: TurnMetrics | null | undefined, divisor: number): TokenBreakdown {
  if (!metrics || divisor <= 0) {
    return { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
  }
  return {
    input: Math.round(metrics.input_tokens / divisor),
    output: Math.round(metrics.output_tokens / divisor),
    cacheRead: Math.round(metrics.cache_read_tokens / divisor),
    cacheWrite: Math.round(metrics.cache_creation_tokens / divisor),
  };
}

function totalBreakdown(tokens: TokenBreakdown): number {
  return tokens.input + tokens.output + tokens.cacheRead + tokens.cacheWrite;
}

function estimateTokensFromText(text: string): number {
  if (!text) return 0;
  return Math.max(1, Math.ceil(text.length / 4));
}

function estimateToolOutputTokens(result: ActionLogEntry | null): number {
  const detail = result?.tool_result;
  if (!detail) return 0;
  return Math.max(1, Math.ceil((detail.output_length || detail.output.length) / 4));
}

function estimateToolUseTokens(toolUse: ToolUseDetail | null | undefined): number {
  if (!toolUse) return 1;
  return estimateTokensFromText(
    [toolUse.tool_name, toolUse.summary, JSON.stringify(toolUse.arguments)].join(' '),
  );
}

function formatToolLabel(toolUse: ToolUseDetail | null | undefined): string {
  if (!toolUse) return 'request';
  return toolUse.summary || toolUse.tool_name || 'tool call';
}

function getAttemptDuration(attempt: RunTraceAttempt): number {
  const value = attempt.metrics.duration_ms;
  return typeof value === 'number' ? value : 0;
}

function buildResultMap(entries: ActionLogEntry[]): Map<string, ActionLogEntry> {
  const resultMap = new Map<string, ActionLogEntry>();
  for (const entry of entries) {
    if (entry.kind === 'tool_result' && entry.tool_result?.tool_use_id) {
      resultMap.set(entry.tool_result.tool_use_id, entry);
    }
  }
  return resultMap;
}

function nearestMetricEntry(
  toolEntry: ActionLogEntry,
  metricEntries: ActionLogEntry[],
): ActionLogEntry | null {
  let candidate: ActionLogEntry | null = null;
  for (const entry of metricEntries) {
    if (entry.sequence_num <= toolEntry.sequence_num) {
      candidate = entry;
      continue;
    }
    return candidate ?? entry;
  }
  return candidate;
}

function accountingTokens(
  mode: AccountingMode,
  metric: TurnMetrics | null | undefined,
  divisor: number,
  contextBefore: number,
  toolUse: ToolUseDetail | null | undefined,
  result: ActionLogEntry | null,
): { tokens: TokenBreakdown; contextAfter: number; estimated: boolean } {
  const shared = divideMetric(metric, divisor);
  const toolUseTokens = estimateToolUseTokens(toolUse);
  const resultTokens = estimateToolOutputTokens(result);

  if (mode === 'request') {
    const fallback = totalBreakdown(shared) > 0
      ? shared
      : { input: resultTokens, output: toolUseTokens, cacheRead: 0, cacheWrite: 0 };
    return {
      tokens: fallback,
      contextAfter: contextBefore + resultTokens + toolUseTokens + shared.cacheWrite,
      estimated: totalBreakdown(shared) === 0,
    };
  }

  if (mode === 'delta') {
    return {
      tokens: { input: resultTokens, output: toolUseTokens, cacheRead: 0, cacheWrite: 0 },
      contextAfter: contextBefore + resultTokens + toolUseTokens,
      estimated: true,
    };
  }

  return {
    tokens: {
      input: shared.input,
      output: shared.output || toolUseTokens,
      cacheRead: Math.max(contextBefore, shared.cacheRead),
      cacheWrite: shared.cacheWrite,
    },
    contextAfter:
      contextBefore +
      resultTokens +
      Math.max(shared.output, toolUseTokens) +
      shared.cacheWrite,
    estimated: shared.cacheRead === 0 || shared.output === 0,
  };
}

function prepareTrace(attempts: RunTraceAttempt[], mode: AccountingMode): PreparedTrace {
  const sortedAttempts = [...attempts].sort((a, b) => {
    const aStarted = a.started_at ? Date.parse(a.started_at) : Number.MAX_SAFE_INTEGER;
    const bStarted = b.started_at ? Date.parse(b.started_at) : Number.MAX_SAFE_INTEGER;
    if (aStarted !== bStarted) return aStarted - bStarted;
    if (a.step_index !== b.step_index) return a.step_index - b.step_index;
    if (a.task_index !== b.task_index) return a.task_index - b.task_index;
    return a.attempt_num - b.attempt_num;
  });

  const pendingRows: Array<Omit<TraceRow, 'blocks'> & { pendingBlocks: Omit<TraceBlock, 'leftPct' | 'widthPct'>[] }> = [];
  let cursor = 0;
  let totalToolCalls = 0;

  for (const attempt of sortedAttempts) {
    const entries = attempt.action_log?.entries ?? [];
    const resultMap = buildResultMap(entries);
    const toolEntries = entries.filter((entry) => entry.kind === 'tool_use');
    const metricEntries = entries.filter((entry) => hasMetric(entry.metrics));
    const metricByToolSeq = new Map<number, ActionLogEntry | null>();
    const countsByMetricSeq = new Map<number, number>();

    for (const toolEntry of toolEntries) {
      const metricEntry = nearestMetricEntry(toolEntry, metricEntries);
      metricByToolSeq.set(toolEntry.sequence_num, metricEntry);
      if (metricEntry) {
        countsByMetricSeq.set(
          metricEntry.sequence_num,
          (countsByMetricSeq.get(metricEntry.sequence_num) ?? 0) + 1,
        );
      }
    }

    const metricSeqsUsedByTools = new Set(
      [...metricByToolSeq.values()]
        .filter((entry): entry is ActionLogEntry => entry !== null)
        .map((entry) => entry.sequence_num),
    );
    const messageMetricEntries = metricEntries.filter(
      (entry) => entry.kind !== 'tool_result' && !metricSeqsUsedByTools.has(entry.sequence_num),
    );
    const fallbackEntries = [...toolEntries, ...messageMetricEntries].sort(
      (a, b) => a.sequence_num - b.sequence_num,
    );
    const initialContext = metricEntries[0]?.metrics?.input_tokens ?? 0;
    let context = mode === 'context' ? initialContext : 0;
    const pendingBlocks: Omit<TraceBlock, 'leftPct' | 'widthPct'>[] = [];
    let rowTokens = 0;

    for (const entry of fallbackEntries) {
      const toolUse = entry.tool_use;
      const result =
        toolUse?.tool_use_id ? resultMap.get(toolUse.tool_use_id) ?? null : null;
      const metricEntry =
        entry.kind === 'tool_use' ? metricByToolSeq.get(entry.sequence_num) : entry;
      const divisor =
        metricEntry && entry.kind === 'tool_use'
          ? Math.max(1, countsByMetricSeq.get(metricEntry.sequence_num) ?? 1)
          : 1;
      const accounting = accountingTokens(
        mode,
        metricEntry?.metrics,
        divisor,
        context,
        toolUse,
        result,
      );
      context = accounting.contextAfter;
      const totalTokens = Math.max(1, totalBreakdown(accounting.tokens));
      rowTokens += totalTokens;
      totalToolCalls += entry.kind === 'tool_use' ? 1 : 0;
      pendingBlocks.push({
        rowKey: `${attempt.task_id}:${attempt.attempt_num}`,
        sequenceNum: entry.sequence_num,
        label: formatToolLabel(toolUse),
        toolName: toolUse?.tool_name || entry.kind,
        tokens: accounting.tokens,
        totalTokens,
        entry,
        result,
        estimated: accounting.estimated || !toolUse,
      });
    }

    pendingRows.push({
      key: `${attempt.task_id}:${attempt.attempt_num}`,
      attempt,
      totalTokens: rowTokens,
      pendingBlocks,
    });
  }

  const totalTokens = Math.max(1, pendingRows.reduce((sum, row) => sum + row.totalTokens, 0));
  const rows: TraceRow[] = pendingRows.map((row) => {
    const blocks = row.pendingBlocks.map((block) => {
      const leftPct = (cursor / totalTokens) * 100;
      cursor += block.totalTokens;
      return {
        ...block,
        leftPct,
        widthPct: Math.max(0.35, (block.totalTokens / totalTokens) * 100),
      };
    });
    return { key: row.key, attempt: row.attempt, totalTokens: row.totalTokens, blocks };
  });

  return { rows, totalTokens, totalToolCalls };
}

function TokenSegments({ tokens }: { tokens: TokenBreakdown }) {
  const total = Math.max(1, totalBreakdown(tokens));
  return (
    <div className="flex h-full w-full overflow-hidden rounded-sm bg-bg-primary">
      {TOKEN_LEGEND.map((item) => {
        const value = tokens[item.key];
        if (value <= 0) return null;
        const width = Math.max(4, (value / total) * 100);
        return (
          <span
            key={item.key}
            className={item.className}
            style={{ width: `${width}%` }}
            title={`${item.label}: ${formatTokens(value)}`}
          />
        );
      })}
    </div>
  );
}

function tokenSummary(tokens: TokenBreakdown): string {
  const parts = [
    tokens.cacheRead > 0 ? `${formatTokens(tokens.cacheRead)} cache read` : null,
    tokens.cacheWrite > 0 ? `${formatTokens(tokens.cacheWrite)} cache write` : null,
    tokens.input > 0 ? `${formatTokens(tokens.input)} input` : null,
    tokens.output > 0 ? `${formatTokens(tokens.output)} output` : null,
  ].filter(Boolean);
  return parts.join(' / ') || '0 tokens';
}

function clip(value: string | null | undefined, max = 220): string {
  if (!value) return '';
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

function toolResultSummary(result: ToolResultDetail | null | undefined): string {
  if (!result) return 'No result recorded';
  const status = result.success ? 'success' : 'failed';
  const size = result.output_length > 0 ? `${(result.output_length / 1024).toFixed(1)} KB` : 'empty';
  return `${status}, ${size}`;
}

function MessageEntry({
  entry,
  result,
  selected,
  onSelect,
}: {
  entry: ActionLogEntry;
  result: ActionLogEntry | null;
  selected: boolean;
  onSelect: () => void;
}) {
  const toolUse = entry.tool_use;
  const resultLabel = result?.tool_result ? toolResultSummary(result.tool_result) : null;
  const label =
    entry.kind === 'tool_use'
      ? formatToolLabel(toolUse)
      : entry.kind === 'tool_result'
        ? toolResultSummary(entry.tool_result)
        : clip(entry.text, 140) || entry.kind;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={
        'w-full rounded border px-2 py-1.5 text-left transition-colors ' +
        (selected
          ? 'border-accent-cyan/50 bg-accent-cyan/10'
          : 'border-border bg-bg-card hover:border-border-hover hover:bg-bg-hover/40')
      }
    >
      <div className="flex items-center gap-2">
        <span className="w-16 shrink-0 font-mono text-[10px] uppercase text-text-muted">
          {entry.kind}
        </span>
        <span className="min-w-0 flex-1 truncate text-xs text-text-secondary" title={label}>
          {label}
        </span>
        {resultLabel && (
          <span
            className="shrink-0 rounded border border-border bg-bg-elevated px-1.5 py-0.5 text-[10px] text-text-muted"
            title={`Result: ${resultLabel}`}
          >
            {resultLabel}
          </span>
        )}
        {entry.metrics && metricTotal(entry.metrics) > 0 && (
          <span className="shrink-0 text-[10px] text-text-muted">
            {formatTokens(metricTotal(entry.metrics))}
          </span>
        )}
      </div>
    </button>
  );
}

function EntryDetail({ entry, result }: { entry: ActionLogEntry; result: ActionLogEntry | null }) {
  return (
    <div className="rounded-md border border-border bg-bg-card p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] uppercase text-text-muted">{entry.kind}</span>
        {entry.tool_use?.tool_name && (
          <span className="rounded border border-border bg-bg-elevated px-1.5 py-0.5 text-[10px] text-text-secondary">
            {entry.tool_use.tool_name}
          </span>
        )}
        {entry.metrics && metricTotal(entry.metrics) > 0 && (
          <span className="text-[11px] text-text-muted">
            {tokenSummary({
              input: entry.metrics.input_tokens,
              output: entry.metrics.output_tokens,
              cacheRead: entry.metrics.cache_read_tokens,
              cacheWrite: entry.metrics.cache_creation_tokens,
            })}
          </span>
        )}
      </div>
      {entry.text && (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded border border-border bg-bg-elevated p-2 font-mono text-xs text-text-secondary scrollbar-dark">
          {entry.text}
        </pre>
      )}
      {entry.tool_use && (
        <div className="space-y-2">
          <pre className="max-h-52 overflow-auto whitespace-pre-wrap rounded border border-border bg-bg-elevated p-2 font-mono text-xs text-text-secondary scrollbar-dark">
            {JSON.stringify(entry.tool_use.arguments, null, 2)}
          </pre>
          {result?.tool_result && (
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded border border-border bg-bg-elevated p-2 font-mono text-xs text-text-secondary scrollbar-dark">
              {result.tool_result.output || 'No output'}
            </pre>
          )}
        </div>
      )}
      {!entry.tool_use && entry.tool_result && (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded border border-border bg-bg-elevated p-2 font-mono text-xs text-text-secondary scrollbar-dark">
          {entry.tool_result.output || 'No output'}
        </pre>
      )}
    </div>
  );
}

function visibleActionEntries(entries: ActionLogEntry[]): ActionLogEntry[] {
  const toolUseIds = new Set(
    entries
      .map((entry) => entry.tool_use?.tool_use_id)
      .filter((toolUseId): toolUseId is string => Boolean(toolUseId)),
  );
  return entries.filter(
    (entry) =>
      entry.kind !== 'tool_result' ||
      !entry.tool_result?.tool_use_id ||
      !toolUseIds.has(entry.tool_result.tool_use_id),
  );
}

function AttemptDetails({
  row,
  selectedSequence,
  shouldScrollSelected,
  onSelectSequence,
}: {
  row: TraceRow | null;
  selectedSequence: number | null;
  shouldScrollSelected: boolean;
  onSelectSequence: (sequence: number) => void;
}) {
  const selectedMessageRef = useRef<HTMLDivElement | null>(null);
  const rowKey = row?.key ?? null;

  useEffect(() => {
    if (!shouldScrollSelected) return;
    selectedMessageRef.current?.scrollIntoView({ block: 'center' });
  }, [rowKey, selectedSequence, shouldScrollSelected]);

  if (!row) {
    return (
      <div className="max-h-[34rem] overflow-y-auto rounded-md border border-border bg-bg-card px-3 py-4 text-sm text-text-muted scrollbar-dark">
        Select an attempt or tool call to inspect messages.
      </div>
    );
  }

  const entries = row.attempt.action_log?.entries ?? [];
  const resultMap = buildResultMap(entries);
  const displayedEntries = visibleActionEntries(entries);
  const selectedEntry =
    displayedEntries.find((entry) => entry.sequence_num === selectedSequence) ??
    displayedEntries[0] ??
    null;
  const selectedResult =
    selectedEntry?.tool_use?.tool_use_id
      ? resultMap.get(selectedEntry.tool_use.tool_use_id) ?? null
      : null;
  const durationMs = getAttemptDuration(row.attempt);

  return (
    <div className="space-y-3">
      {entries.length === 0 ? (
        <div className="rounded-md border border-border bg-bg-card px-3 py-4 text-sm text-text-muted">
          No structured messages are stored for this attempt.
        </div>
      ) : (
        <div className="space-y-3">
          <div className="max-h-[24rem] space-y-1 overflow-auto rounded-md border border-border bg-bg-card p-2 scrollbar-dark">
            {displayedEntries.map((entry) => {
              const selected = selectedEntry?.sequence_num === entry.sequence_num;
              const result =
                entry.tool_use?.tool_use_id ? resultMap.get(entry.tool_use.tool_use_id) ?? null : null;
              return (
                <div
                  key={`${row.key}:${entry.sequence_num}`}
                  ref={selected ? selectedMessageRef : undefined}
                >
                  <MessageEntry
                    entry={entry}
                    result={result}
                    selected={selected}
                    onSelect={() => onSelectSequence(entry.sequence_num)}
                  />
                </div>
              );
            })}
          </div>
          {selectedEntry && (
            <div className="max-h-[28rem] overflow-auto scrollbar-dark">
              <EntryDetail entry={selectedEntry} result={selectedResult} />
            </div>
          )}
        </div>
      )}

      <div className="rounded-md border border-border bg-bg-card px-3 py-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-sm font-semibold text-text-primary">
            Attempt #{row.attempt.attempt_num}
          </span>
          <span className="min-w-0 truncate text-xs text-text-muted">{row.attempt.task_title}</span>
          {row.attempt.outcome && (
            <span className="rounded border border-border bg-bg-elevated px-1.5 py-0.5 text-[10px] uppercase text-text-muted">
              {row.attempt.outcome}
            </span>
          )}
          {durationMs > 0 && (
            <span className="text-xs text-text-muted">{formatDuration(durationMs)}</span>
          )}
          {row.attempt.agent_model && (
            <span className="text-xs text-text-muted">{row.attempt.agent_model}</span>
          )}
        </div>
        {row.attempt.error && (
          <p className="mt-1 truncate text-xs text-status-failed" title={row.attempt.error}>
            {row.attempt.error}
          </p>
        )}
      </div>

      {(row.attempt.phases.length > 0 ||
        row.attempt.builder_prompt ||
        row.attempt.verifier_prompt ||
        row.attempt.verifier_comment) && (
        <details className="rounded-md border border-border bg-bg-card p-2">
          <summary className="cursor-pointer text-xs font-semibold uppercase text-text-muted">
            Attempt context, phases, prompts
          </summary>
          {row.attempt.phases.length > 0 && (
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {row.attempt.phases.map((phase) => (
                <div key={phase.phase} className="rounded border border-border bg-bg-elevated/50 px-2 py-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-semibold uppercase text-text-muted">
                      {phase.phase}
                    </span>
                    <span className="text-[10px] text-text-muted">
                      {phase.message_count > 0 ? `${phase.message_count} messages` : 'prompt/feedback only'}
                    </span>
                  </div>
                  {phase.action_sequence_start !== null && phase.action_sequence_end !== null && (
                    <div className="mt-1 text-[10px] text-text-muted">
                      sequence {phase.action_sequence_start}-{phase.action_sequence_end}
                    </div>
                  )}
                  {phase.note && (
                    <p className="mt-1 max-h-8 overflow-hidden text-xs text-text-secondary">{phase.note}</p>
                  )}
                </div>
              ))}
            </div>
          )}
          <div className="mt-2 grid gap-2 lg:grid-cols-3">
            {row.attempt.builder_prompt && (
              <details className="rounded border border-border bg-bg-elevated/50 p-2">
                <summary className="cursor-pointer text-xs font-semibold uppercase text-text-muted">Builder Prompt</summary>
                <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs text-text-secondary scrollbar-dark">
                  {row.attempt.builder_prompt}
                </pre>
              </details>
            )}
            {row.attempt.verifier_prompt && (
              <details className="rounded border border-border bg-bg-elevated/50 p-2">
                <summary className="cursor-pointer text-xs font-semibold uppercase text-text-muted">Verifier Prompt</summary>
                <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs text-text-secondary scrollbar-dark">
                  {row.attempt.verifier_prompt}
                </pre>
              </details>
            )}
            {row.attempt.verifier_comment && (
              <details className="rounded border border-border bg-bg-elevated/50 p-2">
                <summary className="cursor-pointer text-xs font-semibold uppercase text-text-muted">Verifier Feedback</summary>
                <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs text-text-secondary scrollbar-dark">
                  {row.attempt.verifier_comment}
                </pre>
              </details>
            )}
          </div>
        </details>
      )}
    </div>
  );
}

function Hierarchy({
  rows,
  selectedRowKey,
  onSelectRow,
}: {
  rows: TraceRow[];
  selectedRowKey: string | null;
  onSelectRow: (row: TraceRow) => void;
}) {
  const steps = new Map<string, TraceRow[]>();
  for (const row of rows) {
    const key = row.attempt.step_id;
    steps.set(key, [...(steps.get(key) ?? []), row]);
  }

  return (
    <div className="max-h-[42rem] overflow-auto rounded-md border border-border bg-bg-card p-2 scrollbar-dark">
      {[...steps.entries()].map(([stepId, stepRows]) => {
        const first = stepRows[0].attempt;
        const byTask = new Map<string, TraceRow[]>();
        for (const row of stepRows) {
          byTask.set(row.attempt.task_id, [...(byTask.get(row.attempt.task_id) ?? []), row]);
        }
        return (
          <div key={stepId} className="mb-3 last:mb-0">
            <div className="mb-1 truncate px-1 text-[11px] font-semibold uppercase text-text-muted" title={first.step_title}>
              Step {first.step_index + 1}
            </div>
            <div className="space-y-2">
              {[...byTask.entries()].map(([taskId, taskRows]) => (
                <div key={taskId} className="rounded border border-border bg-bg-elevated/50 p-1.5">
                  <div className="mb-1 truncate px-1 text-xs text-text-secondary" title={`${first.step_title} / ${taskRows[0].attempt.task_title}`}>
                    {taskRows[0].attempt.task_title}
                  </div>
                  <div className="space-y-1">
                    {taskRows.map((row) => (
                      <button
                        key={row.key}
                        type="button"
                        onClick={() => onSelectRow(row)}
                        className={
                          'flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs transition-colors ' +
                          (selectedRowKey === row.key
                            ? 'bg-accent-cyan/15 text-text-primary'
                            : 'text-text-muted hover:bg-bg-hover hover:text-text-secondary')
                        }
                      >
                        <span>Attempt #{row.attempt.attempt_num}</span>
                        <span>{row.blocks.length} calls</span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function RunTraceExplorer({ runId }: { runId: string }) {
  const { data, isLoading, error } = useRunTrace(runId);
  const [mode, setMode] = useState<AccountingMode>('context');
  const [zoom, setZoom] = useState(1);
  const [selectedRowKey, setSelectedRowKey] = useState<string | null>(null);
  const [selectedSequence, setSelectedSequence] = useState<number | null>(null);
  const [shouldScrollActionListToSelection, setShouldScrollActionListToSelection] = useState(false);
  const traceScrollerRef = useRef<HTMLDivElement | null>(null);
  const [scrollbarState, setScrollbarState] = useState<ScrollbarState>({
    scrollLeft: 0,
    scrollWidth: 0,
    clientWidth: 0,
  });

  const trace = useMemo(
    () => prepareTrace(data?.attempts ?? [], mode),
    [data?.attempts, mode],
  );
  const selectedRow =
    trace.rows.find((row) => row.key === selectedRowKey) ?? trace.rows[0] ?? null;

  const selectRow = (row: TraceRow) => {
    setSelectedRowKey(row.key);
    setShouldScrollActionListToSelection(false);
    setSelectedSequence(row.blocks[0]?.sequenceNum ?? row.attempt.action_log?.entries[0]?.sequence_num ?? null);
  };

  const selectBlock = (row: TraceRow, block: TraceBlock) => {
    setSelectedRowKey(row.key);
    setShouldScrollActionListToSelection(true);
    setSelectedSequence(block.sequenceNum);
  };

  const changeZoom = (nextZoom: number, anchorClientX?: number) => {
    const scroller = traceScrollerRef.current;
    const rect = scroller?.getBoundingClientRect();
    const anchorOffset =
      scroller && rect && anchorClientX !== undefined
        ? Math.min(scroller.clientWidth, Math.max(0, anchorClientX - rect.left))
        : null;
    const contentRatio =
      scroller && anchorOffset !== null
        ? (scroller.scrollLeft + anchorOffset) / Math.max(1, scroller.scrollWidth)
        : scroller
          ? scroller.scrollLeft / Math.max(1, scroller.scrollWidth - scroller.clientWidth)
          : 0;
    const next = Math.min(MAX_TRACE_ZOOM, Math.max(MIN_TRACE_ZOOM, nextZoom));
    setZoom(next);
    window.requestAnimationFrame(() => {
      const updatedScroller = traceScrollerRef.current;
      if (!updatedScroller) return;
      const nextLeft =
        anchorOffset !== null
          ? contentRatio * updatedScroller.scrollWidth - anchorOffset
          : contentRatio *
            Math.max(0, updatedScroller.scrollWidth - updatedScroller.clientWidth);
      updatedScroller.scrollLeft = Math.min(
        Math.max(0, nextLeft),
        Math.max(0, updatedScroller.scrollWidth - updatedScroller.clientWidth),
      );
    });
  };

  const handleTraceWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const pinchScale = Math.min(1.8, Math.max(0.55, Math.exp(-event.deltaY * 0.006)));
    changeZoom(zoom * pinchScale, event.clientX);
  };

  useEffect(() => {
    const scroller = traceScrollerRef.current;
    if (!scroller) return;

    const updateScrollbar = () => {
      setScrollbarState({
        scrollLeft: scroller.scrollLeft,
        scrollWidth: scroller.scrollWidth,
        clientWidth: scroller.clientWidth,
      });
    };

    updateScrollbar();
    scroller.addEventListener('scroll', updateScrollbar, { passive: true });
    const resizeObserver =
      typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(updateScrollbar);
    resizeObserver?.observe(scroller);
    window.addEventListener('resize', updateScrollbar);

    return () => {
      scroller.removeEventListener('scroll', updateScrollbar);
      resizeObserver?.disconnect();
      window.removeEventListener('resize', updateScrollbar);
    };
  }, [mode, zoom, trace.rows.length, trace.totalTokens]);

  useEffect(() => {
    if (!selectedRow || selectedSequence === null) return;
    const selectedBlock = selectedRow.blocks.find((block) => block.sequenceNum === selectedSequence);
    const scroller = traceScrollerRef.current;
    if (!selectedBlock || !scroller) return;

    const labelColumnWidth = 220;
    const trackWidth = Math.max(1, scroller.scrollWidth - labelColumnWidth);
    const blockCenter =
      labelColumnWidth +
      ((selectedBlock.leftPct + selectedBlock.widthPct / 2) / 100) * trackWidth;
    scroller.scrollLeft = Math.min(
      Math.max(0, blockCenter - scroller.clientWidth / 2),
      Math.max(0, scroller.scrollWidth - scroller.clientWidth),
    );
  }, [selectedRow, selectedSequence, zoom]);

  if (isLoading) {
    return (
      <div className="mb-6 flex justify-center rounded-lg border border-border bg-bg-card py-8">
        <Spinner />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mb-6 rounded-lg border border-status-failed/30 bg-status-failed/10 px-4 py-3 text-sm text-status-failed">
        Failed to load run trace.
      </div>
    );
  }

  if (!data || data.attempts.length === 0) {
    return (
      <div className="mb-6 rounded-lg border border-border bg-bg-card px-4 py-5 text-sm text-text-muted">
        No attempts have been recorded for this run yet.
      </div>
    );
  }

  const contentWidth = `${Math.max(100, zoom * 100)}%`;
  const hasHorizontalOverflow = scrollbarState.scrollWidth > scrollbarState.clientWidth + 1;
  const thumbWidthPct = hasHorizontalOverflow
    ? Math.max(8, (scrollbarState.clientWidth / scrollbarState.scrollWidth) * 100)
    : 100;
  const thumbTravelPct = Math.max(0, 100 - thumbWidthPct);
  const thumbLeftPct = hasHorizontalOverflow
    ? (scrollbarState.scrollLeft /
        Math.max(1, scrollbarState.scrollWidth - scrollbarState.clientWidth)) *
      thumbTravelPct
    : 0;
  const scrollTraceTo = (clientX: number, target: HTMLElement) => {
    const scroller = traceScrollerRef.current;
    if (!scroller || !hasHorizontalOverflow) return;
    const rect = target.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    scroller.scrollLeft = ratio * (scroller.scrollWidth - scroller.clientWidth);
  };

  return (
    <section className="mb-6 rounded-lg border border-border bg-bg-card">
      <div className="border-b border-border px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Run Trace</h2>
            <p className="mt-1 text-xs text-text-muted">
              {trace.rows.length} attempts / {trace.totalToolCalls} tool calls / {formatTokens(trace.totalTokens)} displayed tokens
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="grid grid-cols-3 rounded-md border border-border bg-bg-elevated p-0.5">
              {(['context', 'request', 'delta'] as AccountingMode[]).map((candidate) => (
                <button
                  key={candidate}
                  type="button"
                  onClick={() => setMode(candidate)}
                  className={
                    'rounded px-2 py-1 text-[11px] transition-colors ' +
                    (mode === candidate
                      ? 'bg-bg-hover text-text-primary'
                      : 'text-text-muted hover:text-text-secondary')
                  }
                  title={MODE_HELP[candidate]}
                >
                  {MODE_LABELS[candidate]}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1 rounded-md border border-border bg-bg-elevated px-1 py-0.5">
              <button
                type="button"
                onClick={() => changeZoom(zoom / 1.5)}
                className="rounded px-3 py-1 text-sm font-semibold text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                aria-label="Zoom out trace"
                title="Zoom out trace"
              >
                -
              </button>
              <span className="w-12 text-center text-[11px] text-text-muted">
                {Math.round(zoom * 100)}%
              </span>
              <button
                type="button"
                onClick={() => changeZoom(zoom * 1.5)}
                className="rounded px-3 py-1 text-sm font-semibold text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                aria-label="Zoom in trace"
                title="Zoom in trace"
              >
                +
              </button>
            </div>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-3">
          {TOKEN_LEGEND.map((item) => (
            <span key={item.key} className="inline-flex items-center gap-1.5 text-[11px] text-text-muted">
              <span className={`h-2.5 w-5 rounded-sm ${item.className}`} />
              {item.label}
            </span>
          ))}
          <span className="text-[11px] text-text-muted">{MODE_HELP[mode]}</span>
        </div>
      </div>

      <div
        id="run-trace-scroll-area"
        ref={traceScrollerRef}
        onWheel={handleTraceWheel}
        className="overflow-x-auto border-b border-border scrollbar-none"
        title="Pinch over the trace to zoom"
      >
        <div className="min-w-[900px]" style={{ width: contentWidth }}>
          <div className="sticky top-0 z-10 grid grid-cols-[220px_1fr] border-b border-border bg-bg-card">
            <div className="border-r border-border px-3 py-2 text-[11px] font-semibold uppercase text-text-muted">
              Attempt
            </div>
            <div className="relative h-8">
              {[0, 25, 50, 75, 100].map((pct) => (
                <div
                  key={pct}
                  className="absolute top-0 h-full border-l border-border/80"
                  style={{ left: `${pct}%` }}
                >
                  <span className="ml-1 text-[10px] text-text-muted">
                    {formatTokens(Math.round(trace.totalTokens * (pct / 100)))}
                  </span>
                </div>
              ))}
            </div>
          </div>
          {trace.rows.map((row) => {
            const active = selectedRow?.key === row.key;
            return (
              <div
                key={row.key}
                className={
                  'grid grid-cols-[220px_1fr] border-b border-border last:border-b-0 ' +
                  (active ? 'bg-accent-cyan/5' : '')
                }
              >
                <button
                  type="button"
                  onClick={() => selectRow(row)}
                  className="border-r border-border px-3 py-2 text-left hover:bg-bg-hover/40"
                >
                  <div className="truncate text-xs font-medium text-text-primary" title={row.attempt.task_title}>
                    {row.attempt.task_title}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[10px] text-text-muted">
                    <span>#{row.attempt.attempt_num}</span>
                    <span>{row.blocks.length} calls</span>
                    {row.attempt.outcome && <span>{row.attempt.outcome}</span>}
                  </div>
                </button>
                <div className="relative h-12">
                  {[0, 25, 50, 75, 100].map((pct) => (
                    <span
                      key={pct}
                      className="absolute top-0 h-full border-l border-border/40"
                      style={{ left: `${pct}%` }}
                    />
                  ))}
                  {row.blocks.length > 0 && (() => {
                    const firstBlock = row.blocks[0];
                    const lastBlock = row.blocks[row.blocks.length - 1];
                    const left = firstBlock.leftPct;
                    const width = Math.max(
                      0.5,
                      lastBlock.leftPct + lastBlock.widthPct - firstBlock.leftPct,
                    );
                    const hasVerifier = row.attempt.phases.some((phase) => phase.phase === 'verifier');
                    return (
                      <>
                        <span
                          className="absolute bottom-1 h-1 rounded-sm bg-border-hover/60"
                          style={{ left: `${left}%`, width: `${width}%` }}
                          title="Builder phase message span"
                        />
                        {hasVerifier && (
                          <span
                            className="absolute bottom-1 right-0 h-1 w-2 rounded-sm bg-accent-purple/70"
                            title="Verifier phase prompt/feedback recorded"
                          />
                        )}
                      </>
                    );
                  })()}
                  {row.blocks.length === 0 ? (
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-text-muted">
                      No tool calls recorded
                    </span>
                  ) : (
                    row.blocks.map((block) => (
                      <button
                        key={`${row.key}:${block.sequenceNum}`}
                        type="button"
                        onClick={() => selectBlock(row, block)}
                        className={
                          'absolute top-2 h-8 min-w-2 overflow-hidden rounded-sm border bg-bg-primary outline-none transition-transform hover:z-20 hover:scale-y-110 focus-visible:ring-2 focus-visible:ring-accent-cyan/50 ' +
                          (selectedRow?.key === row.key && selectedSequence === block.sequenceNum
                            ? 'z-10 border-accent-cyan'
                            : 'border-bg-primary')
                        }
                        style={{
                          left: `${block.leftPct}%`,
                          width: `${block.widthPct}%`,
                        }}
                        title={`${block.label}\n${tokenSummary(block.tokens)}${block.estimated ? '\nEstimated attribution' : ''}`}
                      >
                        <TokenSegments tokens={block.tokens} />
                      </button>
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {hasHorizontalOverflow && (
        <div className="border-b border-border bg-bg-elevated px-4 py-2">
          <div
            className="relative h-3 cursor-pointer rounded-full border border-border bg-bg-card"
            role="scrollbar"
            aria-label="Run trace horizontal scroll"
            aria-controls="run-trace-scroll-area"
            aria-orientation="horizontal"
            aria-valuemin={0}
            aria-valuemax={Math.max(0, scrollbarState.scrollWidth - scrollbarState.clientWidth)}
            aria-valuenow={Math.round(scrollbarState.scrollLeft)}
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId);
              scrollTraceTo(event.clientX, event.currentTarget);
            }}
            onPointerMove={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                scrollTraceTo(event.clientX, event.currentTarget);
              }
            }}
          >
            <span
              className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-border-hover shadow-sm"
              style={{ left: `${thumbLeftPct}%`, width: `${thumbWidthPct}%` }}
            />
          </div>
        </div>
      )}

      <div className="grid gap-3 p-4 min-[1800px]:grid-cols-[260px_minmax(0,1fr)]">
        <Hierarchy rows={trace.rows} selectedRowKey={selectedRow?.key ?? null} onSelectRow={selectRow} />
        <AttemptDetails
          row={selectedRow}
          selectedSequence={selectedSequence}
          shouldScrollSelected={shouldScrollActionListToSelection}
          onSelectSequence={(sequence) => {
            setShouldScrollActionListToSelection(false);
            setSelectedSequence(sequence);
          }}
        />
      </div>
    </section>
  );
}
