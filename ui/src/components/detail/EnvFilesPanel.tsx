import { useMemo, useState } from 'react';
import { ApiError } from '../../api/client';
import {
  useCopyBackEnvFiles,
  useEnvDefaultTarget,
  useEnvFiles,
  useEnvSnapshots,
  useRevertEnvSnapshot,
} from '../../hooks/useApi';
import { ConfirmDialog } from '../ConfirmDialog';
import type { EnvSnapshot } from '../../types';

interface EnvFilesPanelProps {
  runId: string;
}

function formatSnapshotTimestamp(timestamp: string): string {
  if (!timestamp) return '-';
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return timestamp;
  return parsed.toLocaleString();
}

export function EnvFilesPanel({ runId }: EnvFilesPanelProps) {
  const { data: envFiles, isLoading: envFilesLoading, isError: envFilesError } = useEnvFiles(runId);
  const { data: snapshots, isLoading: snapshotsLoading, isError: snapshotsError } = useEnvSnapshots(runId);
  const { data: defaultTarget } = useEnvDefaultTarget(runId);
  const revertSnapshot = useRevertEnvSnapshot(runId);
  const copyBack = useCopyBackEnvFiles(runId);

  const [selectedSnapshot, setSelectedSnapshot] = useState<EnvSnapshot | null>(null);
  const [copyBackSnapshotId, setCopyBackSnapshotId] = useState<string | null>(null);
  const [copyBackOpen, setCopyBackOpen] = useState(false);
  const [copyBackPath, setCopyBackPath] = useState('');
  const [copyBackError, setCopyBackError] = useState<string | null>(null);

  const activeCopyBackSnapshot = useMemo(
    () => snapshots?.find(snapshot => snapshot.id === copyBackSnapshotId) ?? null,
    [copyBackSnapshotId, snapshots],
  );

  const openCopyBackDialog = (snapshotId: string) => {
    setCopyBackSnapshotId(snapshotId);
    setCopyBackPath(defaultTarget?.target_path ?? '');
    setCopyBackError(null);
    setCopyBackOpen(true);
  };

  const closeCopyBackDialog = () => {
    if (copyBack.isPending) {
      return;
    }
    setCopyBackOpen(false);
    setCopyBackError(null);
    setCopyBackSnapshotId(null);
  };

  const onConfirmCopyBack = () => {
    const targetPath = copyBackPath.trim();
    if (!targetPath) {
      setCopyBackError('Target path is required.');
      return;
    }

    setCopyBackError(null);
    copyBack.mutate(targetPath, {
      onSuccess: () => {
        setCopyBackOpen(false);
        setCopyBackSnapshotId(null);
      },
      onError: (error: Error) => {
        if (error instanceof ApiError) {
          setCopyBackError(error.message);
          return;
        }
        setCopyBackError(error.message || 'Failed to copy env files.');
      },
    });
  };

  const onConfirmRevert = () => {
    if (!selectedSnapshot) {
      return;
    }
    revertSnapshot.mutate(selectedSnapshot.id, {
      onSuccess: () => setSelectedSnapshot(null),
    });
  };

  return (
    <div className="mb-6 rounded-md border border-border bg-bg-elevated p-4">
      <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide">Env Files</h2>

      <section className="mt-3">
        <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wide">Current Env Files</h3>
        {envFilesLoading && (
          <p className="mt-2 text-sm text-text-muted">Loading current env files...</p>
        )}
        {envFilesError && (
          <p className="mt-2 text-sm text-status-failed">Failed to load current env files.</p>
        )}
        {!envFilesLoading && !envFilesError && (
          envFiles && envFiles.length > 0 ? (
            <ul className="mt-2 space-y-2">
              {envFiles.map((file, index) => (
                <li key={`${file.path}-${file.key}-${index}`} className="rounded-md border border-border bg-bg-card px-3 py-2">
                  <p className="text-xs text-text-muted">Path</p>
                  <p className="font-mono text-sm text-text-primary break-all">{file.path}</p>
                  <p className="mt-1 text-xs text-text-muted">Masked Value</p>
                  <p className="font-mono text-sm text-text-secondary break-all">{file.masked_value || '-'}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-text-muted">No current env files found.</p>
          )
        )}
      </section>

      <section className="mt-5">
        <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wide">Snapshot History</h3>
        {snapshotsLoading && (
          <p className="mt-2 text-sm text-text-muted">Loading snapshot history...</p>
        )}
        {snapshotsError && (
          <p className="mt-2 text-sm text-status-failed">Failed to load snapshot history.</p>
        )}
        {!snapshotsLoading && !snapshotsError && (
          snapshots && snapshots.length > 0 ? (
            <div className="mt-2 overflow-x-auto">
              <table className="min-w-full border-collapse">
                <thead>
                  <tr className="border-b border-border text-left">
                    <th className="px-2 py-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Timestamp</th>
                    <th className="px-2 py-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Agent</th>
                    <th className="px-2 py-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshots.map((snapshot) => (
                    <tr key={snapshot.id} className="border-b border-border/70">
                      <td className="px-2 py-2 text-sm text-text-primary">{formatSnapshotTimestamp(snapshot.timestamp)}</td>
                      <td className="px-2 py-2 text-sm text-text-secondary">{snapshot.agent || '-'}</td>
                      <td className="px-2 py-2">
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setSelectedSnapshot(snapshot)}
                            disabled={revertSnapshot.isPending}
                            className="rounded-md border border-status-failed/40 px-2.5 py-1 text-xs font-medium text-status-failed hover:bg-status-failed/10 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            Revert
                          </button>
                          <button
                            type="button"
                            onClick={() => openCopyBackDialog(snapshot.id)}
                            disabled={copyBack.isPending}
                            className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-text-primary hover:bg-bg-muted disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            Copy Back
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-2 text-sm text-text-muted">No snapshots found.</p>
          )
        )}
      </section>

      <ConfirmDialog
        open={selectedSnapshot !== null}
        title="Revert env snapshot"
        message={
          selectedSnapshot
            ? `Revert current managed env files to snapshot ${selectedSnapshot.id.slice(0, 8)}?`
            : ''
        }
        confirmLabel={revertSnapshot.isPending ? 'Reverting...' : 'Revert'}
        onCancel={() => {
          if (revertSnapshot.isPending) return;
          setSelectedSnapshot(null);
        }}
        onConfirm={onConfirmRevert}
      />

      {copyBackOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={closeCopyBackDialog}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="copy-back-dialog-title"
            className="mx-4 w-full max-w-lg rounded-lg border border-border bg-bg-card p-6 shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <h3 id="copy-back-dialog-title" className="text-lg font-semibold text-text-primary">
              Copy env files back
            </h3>
            <p className="mt-2 text-sm text-text-secondary">
              Provide destination path for managed env files
              {activeCopyBackSnapshot ? ` (snapshot ${activeCopyBackSnapshot.id.slice(0, 8)})` : ''}.
            </p>
            <label htmlFor="copy-back-path" className="mt-4 block text-xs font-semibold uppercase tracking-wide text-text-muted">
              Target path
            </label>
            <input
              id="copy-back-path"
              type="text"
              value={copyBackPath}
              onChange={(event) => setCopyBackPath(event.target.value)}
              placeholder="Enter destination path"
              className="mt-1 w-full rounded-md border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-purple"
            />
            {copyBackError && (
              <p className="mt-2 text-xs text-status-failed">{copyBackError}</p>
            )}
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={closeCopyBackDialog}
                disabled={copyBack.isPending}
                className="rounded-md bg-bg-elevated px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={onConfirmCopyBack}
                disabled={copyBack.isPending}
                className="rounded-md border border-border px-4 py-2 text-sm font-medium text-text-primary transition-colors hover:bg-bg-muted disabled:cursor-not-allowed disabled:opacity-60"
              >
                {copyBack.isPending ? 'Copying...' : 'Copy Back'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
