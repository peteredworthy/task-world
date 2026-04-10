import { useEffect } from 'react';
import type { DiffFileEntry, ConflictFile } from '../types/review';

/**
 * Check whether the keyboard event's target is a text input element where
 * shortcut keys should be suppressed (so users can type normally).
 */
function isTextInput(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toUpperCase();
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    target.isContentEditable
  );
}

interface UseReviewKeyboardShortcutsOptions {
  /** List of diff files for j/k navigation. */
  files: DiffFileEntry[];
  /** Currently selected/open diff file. */
  selectedFile: DiffFileEntry | null;
  /** Called when j/k navigates to a new file. */
  onSelectFile: (file: DiffFileEntry) => void;
  /** List of conflict files for [/] navigation. */
  conflictFiles: ConflictFile[];
  /** Whether the conflict resolver dialog is currently open. */
  conflictResolverOpen: boolean;
  /** Current file index shown in the conflict resolver. */
  conflictResolverIndex: number;
  /** Update the conflict resolver file index (navigates while open). */
  onSetConflictIndex: (index: number) => void;
  /** Open the conflict resolver dialog (sets it visible). */
  onOpenConflictResolver: () => void;
  /** Shift+P handler — toggle prune mode. */
  onTogglePruneMode: () => void;
  /** t handler — run tests. */
  onRunTests: () => void;
}

/**
 * Keyboard shortcuts for the Review & Merge tab.
 *
 * | Key     | Action                              |
 * |---------|-------------------------------------|
 * | j       | Next changed file                   |
 * | k       | Previous changed file               |
 * | ]       | Next conflict file (open resolver)  |
 * | [       | Previous conflict file (open resolver) |
 * | Shift+P | Toggle prune mode                   |
 * | t       | Run tests                           |
 *
 * All shortcuts are disabled when the focused element is a text input,
 * textarea, select, or contenteditable element.
 */
export function useReviewKeyboardShortcuts({
  files,
  selectedFile,
  onSelectFile,
  conflictFiles,
  conflictResolverOpen,
  conflictResolverIndex,
  onSetConflictIndex,
  onOpenConflictResolver,
  onTogglePruneMode,
  onRunTests,
}: UseReviewKeyboardShortcutsOptions): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Never fire shortcuts when the user is typing in a text field
      if (isTextInput(e.target)) return;

      switch (e.key) {
        case 'j': {
          // Next changed file
          if (files.length === 0) return;
          const currentIdx = selectedFile
            ? files.findIndex((f) => f.path === selectedFile.path)
            : -1;
          const nextIdx = currentIdx < files.length - 1 ? currentIdx + 1 : 0;
          if (nextIdx !== currentIdx || currentIdx === -1) {
            e.preventDefault();
            onSelectFile(files[nextIdx]);
          }
          break;
        }

        case 'k': {
          // Previous changed file
          if (files.length === 0) return;
          const currentIdx = selectedFile
            ? files.findIndex((f) => f.path === selectedFile.path)
            : 0;
          if (currentIdx <= 0) return;
          e.preventDefault();
          onSelectFile(files[currentIdx - 1]);
          break;
        }

        case ']': {
          // Next conflict file — open or advance resolver
          if (conflictFiles.length === 0) return;
          e.preventDefault();
          if (conflictResolverOpen) {
            onSetConflictIndex(
              Math.min(conflictFiles.length - 1, conflictResolverIndex + 1),
            );
          } else {
            onSetConflictIndex(0);
            onOpenConflictResolver();
          }
          break;
        }

        case '[': {
          // Previous conflict file — open or retreat resolver
          if (conflictFiles.length === 0) return;
          e.preventDefault();
          if (conflictResolverOpen) {
            onSetConflictIndex(Math.max(0, conflictResolverIndex - 1));
          } else {
            onSetConflictIndex(conflictFiles.length - 1);
            onOpenConflictResolver();
          }
          break;
        }

        case 'P': {
          // Shift+P — toggle prune mode (uppercase 'P' means shift is held)
          if (e.shiftKey) {
            e.preventDefault();
            onTogglePruneMode();
          }
          break;
        }

        case 't': {
          // Run tests
          e.preventDefault();
          onRunTests();
          break;
        }

        default:
          break;
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [
    files,
    selectedFile,
    conflictFiles,
    conflictResolverOpen,
    conflictResolverIndex,
    onSelectFile,
    onSetConflictIndex,
    onOpenConflictResolver,
    onTogglePruneMode,
    onRunTests,
  ]);
}
