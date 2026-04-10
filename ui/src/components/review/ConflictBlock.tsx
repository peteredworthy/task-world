import { useState } from 'react';
import type { ConflictBlock as ConflictBlockType, BlockResolution } from '../../types/review';

interface ConflictBlockProps {
  block: ConflictBlockType;
  resolution: BlockResolution | undefined;
  onResolve: (resolution: BlockResolution) => void;
}

export function ConflictBlock({ block, resolution, onResolve }: ConflictBlockProps) {
  const [manualContent, setManualContent] = useState<string>(
    resolution?.choice === 'manual' && resolution.manual_content
      ? resolution.manual_content
      : block.ours_content,
  );
  const [showManualEditor, setShowManualEditor] = useState(
    resolution?.choice === 'manual',
  );

  const isResolved = !!resolution;
  const choice = resolution?.choice;

  function handleKeepOurs() {
    setShowManualEditor(false);
    onResolve({ block_index: block.index, choice: 'ours' });
  }

  function handleKeepTheirs() {
    setShowManualEditor(false);
    onResolve({ block_index: block.index, choice: 'theirs' });
  }

  function handleManualSelection() {
    setShowManualEditor(true);
    if (choice !== 'manual') {
      onResolve({
        block_index: block.index,
        choice: 'manual',
        manual_content: manualContent,
      });
    }
  }

  function handleManualChange(value: string) {
    setManualContent(value);
    onResolve({ block_index: block.index, choice: 'manual', manual_content: value });
  }

  return (
    <div
      className={`rounded-lg border overflow-hidden ${
        isResolved ? 'border-status-success/40' : 'border-amber-500/40'
      }`}
    >
      {/* Block header */}
      <div className="flex items-center justify-between bg-bg-elevated px-3 py-1.5 border-b border-border">
        <span className="text-[11px] font-medium text-text-muted uppercase tracking-wide">
          Conflict block #{block.index + 1}
        </span>
        {isResolved && (
          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-status-success">
            <svg width="10" height="10" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M13 4L6 11L3 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {choice === 'ours' ? 'Kept Run' : choice === 'theirs' ? 'Kept Target' : 'Manual'}
          </span>
        )}
      </div>

      {/* Side-by-side ours/theirs */}
      <div className="grid grid-cols-2 divide-x divide-border">
        {/* Ours — warm tint */}
        <div
          className={`min-w-0 ${
            choice === 'ours' ? 'bg-amber-500/15 ring-1 ring-inset ring-amber-500/40' : 'bg-amber-500/5'
          }`}
        >
          <div className="flex items-center gap-1.5 px-3 py-1 border-b border-amber-500/20">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-400">
              Run (ours)
            </span>
          </div>
          <pre className="overflow-auto p-3 text-xs leading-relaxed text-text-secondary font-mono whitespace-pre-wrap break-all max-h-48">
            {block.ours_content || <span className="italic text-text-muted">(empty)</span>}
          </pre>
        </div>

        {/* Theirs — cool tint */}
        <div
          className={`min-w-0 ${
            choice === 'theirs' ? 'bg-blue-500/15 ring-1 ring-inset ring-blue-500/40' : 'bg-blue-500/5'
          }`}
        >
          <div className="flex items-center gap-1.5 px-3 py-1 border-b border-blue-500/20">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-blue-400">
              Target (theirs)
            </span>
          </div>
          <pre className="overflow-auto p-3 text-xs leading-relaxed text-text-secondary font-mono whitespace-pre-wrap break-all max-h-48">
            {block.theirs_content || <span className="italic text-text-muted">(empty)</span>}
          </pre>
        </div>
      </div>

      {/* Manual editor */}
      {showManualEditor && (
        <div className="border-t border-border bg-bg-muted/40">
          <div className="px-3 py-1.5 border-b border-border">
            <span className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
              Manual content
            </span>
          </div>
          <textarea
            className="w-full bg-bg-primary p-3 text-xs font-mono text-text-primary resize-none outline-none min-h-[80px] focus:ring-1 focus:ring-accent-blue/50"
            value={manualContent}
            onChange={(e) => handleManualChange(e.target.value)}
            placeholder="Enter resolved content…"
            spellCheck={false}
          />
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-2 bg-bg-elevated px-3 py-2 border-t border-border">
        <button
          type="button"
          onClick={handleKeepOurs}
          className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
            choice === 'ours'
              ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
              : 'bg-bg-muted text-text-secondary border border-border hover:bg-amber-500/10 hover:text-amber-400 hover:border-amber-500/30'
          }`}
        >
          Keep Run
        </button>
        <button
          type="button"
          onClick={handleKeepTheirs}
          className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
            choice === 'theirs'
              ? 'bg-blue-500/20 text-blue-400 border border-blue-500/40'
              : 'bg-bg-muted text-text-secondary border border-border hover:bg-blue-500/10 hover:text-blue-400 hover:border-blue-500/30'
          }`}
        >
          Keep Target
        </button>
        <button
          type="button"
          onClick={handleManualSelection}
          className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
            choice === 'manual'
              ? 'bg-accent-blue/20 text-accent-blue border border-accent-blue/40'
              : 'bg-bg-muted text-text-secondary border border-border hover:bg-accent-blue/10 hover:text-accent-blue hover:border-accent-blue/30'
          }`}
        >
          Manual Selection
        </button>
      </div>
    </div>
  );
}
