import { useEffect, useRef, useState } from 'react';
import { useValidateRoutine } from '../hooks/useApi';
import type { ValidationResult } from '../api/client';
import { useFocusTrap } from '../hooks/useFocusTrap';

interface RoutineValidatorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreateRun?: (yaml: string) => void;
}

const PLACEHOLDER = 'Paste your routine YAML here...';

function lineNumberFor(errorLine: number): number {
  return errorLine > 0 ? errorLine : 1;
}

export function RoutineValidatorModal({ isOpen, onClose, onCreateRun }: RoutineValidatorModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const validateRoutine = useValidateRoutine();

  const [yamlContent, setYamlContent] = useState('');
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [serviceError, setServiceError] = useState('');

  useFocusTrap(dialogRef, isOpen);

  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) {
      setYamlContent('');
      setResult(null);
      setServiceError('');
    }
  }, [isOpen]);

  if (!isOpen) return null;

  async function handleValidate() {
    setServiceError('');
    setResult(null);
    try {
      const response = await validateRoutine.mutateAsync(yamlContent);
      setResult(response);
    } catch {
      setServiceError('Validation service error. Please try again.');
    }
  }

  function handleCreateRunClick() {
    if (result?.valid) {
      onCreateRun?.(yamlContent);
      onClose();
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="routine-validator-title"
        className="bg-bg-primary border border-border rounded-xl shadow-2xl w-full max-w-[720px] mx-4 max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-border">
          <div>
            <h2 id="routine-validator-title" className="text-lg font-semibold text-text-primary">
              Validate Routine YAML
            </h2>
            <p className="text-text-muted text-[13px] mt-0.5">
              Validate a routine definition before creating a run.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors p-1 -mr-1 -mt-0.5 rounded-md hover:bg-bg-hover"
            aria-label="Close"
          >
            x
          </button>
        </div>

        <div className="px-6 py-5 space-y-4 overflow-y-auto">
          <textarea
            value={yamlContent}
            onChange={e => setYamlContent(e.target.value)}
            placeholder={PLACEHOLDER}
            rows={14}
            className="w-full rounded-md border border-border bg-bg-card px-3 py-2.5 text-sm font-mono text-text-primary shadow-sm placeholder:text-text-muted focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50"
          />

          {serviceError && (
            <div className="text-sm text-status-failed">{serviceError}</div>
          )}

          {result?.valid === false && (
            <div className="rounded-md border border-status-failed/40 bg-status-failed/10 p-3">
              <p className="text-sm font-medium text-status-failed mb-2">Validation errors</p>
              <ul className="space-y-1 text-sm text-status-failed">
                {result.errors.map((error, index) => (
                  <li key={`${index}-${error.line}-${error.message}`}>
                    Line {lineNumberFor(error.line)}: {error.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {result?.valid === true && (
            <div className="rounded-md border border-status-active/40 bg-status-active/10 p-3">
              <p className="text-sm font-medium text-status-active">Valid routine YAML</p>
              <button
                type="button"
                onClick={handleCreateRunClick}
                className="mt-2 inline-flex items-center rounded-md bg-status-active/20 hover:bg-status-active/30 border border-status-active/30 px-3 py-1.5 text-sm text-status-active transition-colors"
              >
                Create run from this routine
              </button>
            </div>
          )}
        </div>

        <div className="px-6 pb-5 pt-1 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 text-sm rounded-md border border-border text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors"
          >
            Close
          </button>
          <button
            type="button"
            onClick={handleValidate}
            disabled={validateRoutine.isPending}
            className="px-3 py-2 text-sm rounded-md bg-accent-purple text-white hover:bg-accent-purple/90 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          >
            {validateRoutine.isPending ? 'Validating...' : 'Validate'}
          </button>
        </div>
      </div>
    </div>
  );
}
