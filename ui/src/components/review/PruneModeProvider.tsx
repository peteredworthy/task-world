/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { PruneSelection, FilePrune, LineRange } from '../../types/review';

// Selection state keys
// - selectedFiles: set of file paths selected for full-file prune
// - selectedHunks: map of filePath -> set of hunk indices
// - selectedLines: map of filePath -> map of hunkIndex -> LineRange[]

interface PruneModeContextValue {
  isPruneMode: boolean;
  selectedFiles: Set<string>;
  selectedHunks: Map<string, Set<number>>;
  selectedLines: Map<string, Map<number, LineRange[]>>;
  selectionCount: number;
  togglePruneMode: () => void;
  selectFile: (filePath: string) => void;
  deselectFile: (filePath: string) => void;
  selectHunk: (filePath: string, hunkIndex: number) => void;
  deselectHunk: (filePath: string, hunkIndex: number) => void;
  selectLine: (filePath: string, hunkIndex: number, range: LineRange) => void;
  deselectLine: (filePath: string, hunkIndex: number, range: LineRange) => void;
  clearSelections: () => void;
  buildPruneSelection: (scope: string) => PruneSelection;
}

const PruneModeContext = createContext<PruneModeContextValue | null>(null);

export function usePruneMode(): PruneModeContextValue {
  const ctx = useContext(PruneModeContext);
  /* v8 ignore next 3 -- outside-provider misuse guard; unreachable in correct usage */
  if (!ctx) {
    throw new Error('usePruneMode must be used within a PruneModeProvider');
  }
  return ctx;
}

/**
 * Returns the prune mode context value, or null if not inside a PruneModeProvider.
 * Use this in components that may be rendered both inside and outside the provider.
 */
export function useOptionalPruneMode(): PruneModeContextValue | null {
  return useContext(PruneModeContext);
}

interface PruneModeProviderProps {
  children: ReactNode;
}

export function PruneModeProvider({ children }: PruneModeProviderProps) {
  const [isPruneMode, setIsPruneMode] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [selectedHunks, setSelectedHunks] = useState<Map<string, Set<number>>>(new Map());
  const [selectedLines, setSelectedLines] = useState<Map<string, Map<number, LineRange[]>>>(new Map());

  const togglePruneMode = useCallback(() => {
    setIsPruneMode((prev) => {
      if (prev) {
        // Exiting prune mode: clear all selections
        setSelectedFiles(new Set());
        setSelectedHunks(new Map());
        setSelectedLines(new Map());
      }
      return !prev;
    });
  }, []);

  const selectFile = useCallback((filePath: string) => {
    setSelectedFiles((prev) => new Set([...prev, filePath]));
    // Remove any hunk/line selections for this file since full file is selected
    setSelectedHunks((prev) => {
      const next = new Map(prev);
      next.delete(filePath);
      return next;
    });
    setSelectedLines((prev) => {
      const next = new Map(prev);
      next.delete(filePath);
      return next;
    });
  }, []);

  const deselectFile = useCallback((filePath: string) => {
    setSelectedFiles((prev) => {
      const next = new Set(prev);
      next.delete(filePath);
      return next;
    });
  }, []);

  const selectHunk = useCallback((filePath: string, hunkIndex: number) => {
    // Cannot select hunk if full file is already selected
    setSelectedHunks((prev) => {
      const next = new Map(prev);
      const hunks = new Set(next.get(filePath) ?? []);
      hunks.add(hunkIndex);
      next.set(filePath, hunks);
      return next;
    });
    // Remove line-level selections for this hunk since full hunk is selected
    setSelectedLines((prev) => {
      const next = new Map(prev);
      const fileLines = next.get(filePath);
      if (fileLines) {
        const updatedFileLines = new Map(fileLines);
        updatedFileLines.delete(hunkIndex);
        if (updatedFileLines.size === 0) {
          next.delete(filePath);
        } else {
          next.set(filePath, updatedFileLines);
        }
      }
      return next;
    });
  }, []);

  const deselectHunk = useCallback((filePath: string, hunkIndex: number) => {
    setSelectedHunks((prev) => {
      const next = new Map(prev);
      const hunks = next.get(filePath);
      if (hunks) {
        const updated = new Set(hunks);
        updated.delete(hunkIndex);
        if (updated.size === 0) {
          next.delete(filePath);
        } else {
          next.set(filePath, updated);
        }
      }
      return next;
    });
  }, []);

  const selectLine = useCallback((filePath: string, hunkIndex: number, range: LineRange) => {
    setSelectedLines((prev) => {
      const next = new Map(prev);
      const fileLines = new Map(next.get(filePath) ?? []);
      const hunkRanges = [...(fileLines.get(hunkIndex) ?? [])];
      // Avoid duplicate ranges
      const exists = hunkRanges.some((r) => r.start === range.start && r.end === range.end);
      if (!exists) {
        hunkRanges.push(range);
        fileLines.set(hunkIndex, hunkRanges);
        next.set(filePath, fileLines);
      }
      return next;
    });
  }, []);

  const deselectLine = useCallback((filePath: string, hunkIndex: number, range: LineRange) => {
    setSelectedLines((prev) => {
      const next = new Map(prev);
      const fileLines = next.get(filePath);
      if (!fileLines) return next;
      const updatedFileLines = new Map(fileLines);
      const hunkRanges = updatedFileLines.get(hunkIndex) ?? [];
      const updated = hunkRanges.filter((r) => !(r.start === range.start && r.end === range.end));
      if (updated.length === 0) {
        updatedFileLines.delete(hunkIndex);
      } else {
        updatedFileLines.set(hunkIndex, updated);
      }
      if (updatedFileLines.size === 0) {
        next.delete(filePath);
      } else {
        next.set(filePath, updatedFileLines);
      }
      return next;
    });
  }, []);

  const clearSelections = useCallback(() => {
    setSelectedFiles(new Set());
    setSelectedHunks(new Map());
    setSelectedLines(new Map());
  }, []);

  const selectionCount = useMemo(() => {
    let count = selectedFiles.size;
    for (const hunks of selectedHunks.values()) {
      count += hunks.size;
    }
    for (const fileLines of selectedLines.values()) {
      for (const ranges of fileLines.values()) {
        count += ranges.length;
      }
    }
    return count;
  }, [selectedFiles, selectedHunks, selectedLines]);

  const buildPruneSelection = useCallback(
    (scope: string): PruneSelection => {
      const files: FilePrune[] = [];

      // Full-file selections
      for (const filePath of selectedFiles) {
        files.push({ path: filePath, mode: 'file', hunks: null, lines: null });
      }

      // Collect all file paths that have hunk or line selections
      const hunkFilePaths = new Set([...selectedHunks.keys()]);
      const lineFilePaths = new Set([...selectedLines.keys()]);
      const mixedFilePaths = new Set([...hunkFilePaths, ...lineFilePaths]);

      for (const filePath of mixedFilePaths) {
        // Skip files already covered by file-level selection
        if (selectedFiles.has(filePath)) continue;

        const hunks = selectedHunks.get(filePath);
        const fileLines = selectedLines.get(filePath);

        if (hunks && hunks.size > 0 && !fileLines) {
          // Pure hunk selection
          files.push({ path: filePath, mode: 'hunk', hunks: [...hunks].sort((a, b) => a - b), lines: null });
        } else if (fileLines && fileLines.size > 0 && !hunks) {
          // Pure line selection
          const allRanges: LineRange[] = [];
          for (const ranges of fileLines.values()) {
            allRanges.push(...ranges);
          }
          files.push({ path: filePath, mode: 'line', hunks: null, lines: allRanges });
        } else {
          // Mixed hunk + line selections: emit hunk entries first, then lines for the rest
          const hunkList = hunks ? [...hunks].sort((a, b) => a - b) : [];
          const allRanges: LineRange[] = [];
          if (fileLines) {
            for (const [hunkIdx, ranges] of fileLines.entries()) {
              // Only include line ranges for hunks NOT already selected as full hunks
              if (!hunks || !hunks.has(hunkIdx)) {
                allRanges.push(...ranges);
              }
            }
          }
          if (hunkList.length > 0 && allRanges.length > 0) {
            // Represent as hunk mode with additional line ranges — use two entries
            files.push({ path: filePath, mode: 'hunk', hunks: hunkList, lines: null });
            files.push({ path: filePath, mode: 'line', hunks: null, lines: allRanges });
          } else if (hunkList.length > 0) {
            files.push({ path: filePath, mode: 'hunk', hunks: hunkList, lines: null });
          } else if (allRanges.length > 0) {
            files.push({ path: filePath, mode: 'line', hunks: null, lines: allRanges });
          }
        }
      }

      return { files, scope };
    },
    [selectedFiles, selectedHunks, selectedLines],
  );

  const value = useMemo<PruneModeContextValue>(
    () => ({
      isPruneMode,
      selectedFiles,
      selectedHunks,
      selectedLines,
      selectionCount,
      togglePruneMode,
      selectFile,
      deselectFile,
      selectHunk,
      deselectHunk,
      selectLine,
      deselectLine,
      clearSelections,
      buildPruneSelection,
    }),
    [
      isPruneMode,
      selectedFiles,
      selectedHunks,
      selectedLines,
      selectionCount,
      togglePruneMode,
      selectFile,
      deselectFile,
      selectHunk,
      deselectHunk,
      selectLine,
      deselectLine,
      clearSelections,
      buildPruneSelection,
    ],
  );

  return <PruneModeContext.Provider value={value}>{children}</PruneModeContext.Provider>;
}
