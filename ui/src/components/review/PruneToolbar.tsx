import { usePruneMode } from './PruneModeProvider';

interface PruneToolbarProps {
  onPreview: () => void;
}

/**
 * Banner displayed at the top of the diff area when prune mode is active.
 * Shows the current selection count and provides Preview and Cancel actions.
 */
export function PruneToolbar({ onPreview }: PruneToolbarProps) {
  const { isPruneMode, selectionCount, togglePruneMode, clearSelections } = usePruneMode();

  if (!isPruneMode) return null;

  const handleCancel = () => {
    clearSelections();
    togglePruneMode();
  };

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm"
    >
      {/* Mode indicator */}
      <span className="flex items-center gap-1.5 font-medium text-amber-400">
        <svg
          width="14"
          height="14"
          viewBox="0 0 16 16"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
        >
          <path
            d="M8 1L9.5 5.5H14.5L10.5 8.5L12 13L8 10L4 13L5.5 8.5L1.5 5.5H6.5L8 1Z"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        </svg>
        Prune Mode
      </span>

      {/* Selection count */}
      <span className="text-text-secondary">
        {selectionCount === 0
          ? 'No changes selected'
          : selectionCount === 1
            ? '1 change selected'
            : `${selectionCount} changes selected`}
      </span>

      <div className="ml-auto flex items-center gap-2">
        {/* Preview button */}
        <button
          type="button"
          onClick={onPreview}
          disabled={selectionCount === 0}
          title={selectionCount === 0 ? 'Select changes to preview' : 'Preview selected changes'}
          className="rounded border border-amber-500/50 bg-amber-500/15 px-3 py-1 text-xs font-medium text-amber-400 transition-colors hover:bg-amber-500/25 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Preview
        </button>

        {/* Cancel button */}
        <button
          type="button"
          onClick={handleCancel}
          className="rounded border border-border px-3 py-1 text-xs font-medium text-text-secondary transition-colors hover:bg-bg-muted hover:text-text-primary"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
