import type { RenderGutter, GutterOptions } from 'react-diff-view';
import { useOptionalPruneMode } from './PruneModeProvider';
import type { HunkData } from 'react-diff-view';

interface PruneGutterOptions {
  filePath: string;
  hunks: HunkData[];
}

/**
 * Creates a renderGutter function for react-diff-view that shows hunk-level
 * and line-level checkboxes when prune mode is active.
 *
 * Safe to call outside of a PruneModeProvider — returns a passthrough gutter
 * when no provider is found.
 *
 * Usage:
 *   const renderGutter = usePruneGutter({ filePath, hunks });
 *   <Diff renderGutter={renderGutter} ... />
 */
export function usePruneGutter({ filePath, hunks }: PruneGutterOptions): RenderGutter {
  const ctx = useOptionalPruneMode();

  const renderGutter: RenderGutter = (options: GutterOptions) => {
    if (!ctx?.isPruneMode) {
      return options.renderDefault();
    }

    const { selectedHunks, selectedLines, selectedFiles, selectHunk, deselectHunk, selectLine, deselectLine } = ctx;
    const { change, side } = options;

    // In unified view side is always 'old'; in split view we only render on 'old' side
    // to avoid duplicate checkboxes.
    if (side === 'new') {
      return null;
    }

    // Determine which hunk this change belongs to
    const hunkIndex = hunks.findIndex((h) =>
      h.changes.some((c) => c === change),
    );

    if (hunkIndex === -1) {
      return options.renderDefault();
    }

    const hunk = hunks[hunkIndex];
    const isFileSelected = selectedFiles.has(filePath);
    const fileHunks = selectedHunks.get(filePath);
    const isHunkSelected = fileHunks?.has(hunkIndex) ?? false;

    // Determine if this change is the first change of the hunk (show hunk checkbox)
    const isFirstInHunk = hunk.changes[0] === change;

    if (isFirstInHunk) {
      // Hunk-level checkbox
      const checked = isFileSelected || isHunkSelected;
      const disabled = isFileSelected;

      const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        e.stopPropagation();
        if (e.target.checked) {
          selectHunk(filePath, hunkIndex);
        } else {
          deselectHunk(filePath, hunkIndex);
        }
      };

      return (
        <span
          className="flex items-center justify-center w-full h-full"
          title={disabled ? 'Whole file selected' : isHunkSelected ? 'Deselect hunk' : 'Select hunk'}
        >
          <input
            type="checkbox"
            checked={checked}
            disabled={disabled}
            onChange={handleChange}
            onClick={(e) => e.stopPropagation()}
            className="h-3 w-3 cursor-pointer accent-amber-500 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={`Select hunk ${hunkIndex + 1}`}
          />
        </span>
      );
    }

    // Line-level checkbox for non-first lines in the hunk
    // Only show for insert/delete changes (not normal context lines)
    if (change.type === 'normal') {
      return options.renderDefault();
    }

    // Determine line number for this change
    const lineNumber = change.type === 'insert' ? change.lineNumber : change.lineNumber;

    const fileLineMap = selectedLines.get(filePath);
    const hunkRanges = fileLineMap?.get(hunkIndex) ?? [];
    const isLineSelected = hunkRanges.some(
      (r) => r.start <= lineNumber && lineNumber <= r.end,
    );

    const checked = isFileSelected || isHunkSelected || isLineSelected;
    const disabled = isFileSelected || isHunkSelected;

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      e.stopPropagation();
      const range = { start: lineNumber, end: lineNumber };
      if (e.target.checked) {
        selectLine(filePath, hunkIndex, range);
      } else {
        deselectLine(filePath, hunkIndex, range);
      }
    };

    return (
      <span
        className="flex items-center justify-center w-full h-full"
        title={disabled ? (isHunkSelected ? 'Hunk selected' : 'File selected') : isLineSelected ? 'Deselect line' : 'Select line'}
      >
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={handleChange}
          onClick={(e) => e.stopPropagation()}
          className="h-3 w-3 cursor-pointer accent-amber-500 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label={`Select line ${lineNumber}`}
        />
      </span>
    );
  };

  return renderGutter;
}
