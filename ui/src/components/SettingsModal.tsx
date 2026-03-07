import { useRef, useEffect } from 'react';
import { useSettings } from '../hooks/useSettings';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { useSettingsModal } from '../hooks/useSettingsModal';
import { useGlobalConfig } from '../hooks/useApi';

export function SettingsModal() {
  const { isOpen, close } = useSettingsModal();
  const { settings, updateSettings } = useSettings();
  const globalConfig = useGlobalConfig();
  const dialogRef = useRef<HTMLDivElement>(null);

  // Escape key to close
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, close]);

  // Scroll lock
  useEffect(() => {
    if (!isOpen) return;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  useFocusTrap(dialogRef, isOpen);

  if (!isOpen) return null;

  const titleId = 'settings-modal-title';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={close}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-bg-primary border border-border rounded-xl shadow-2xl w-full max-w-[520px] mx-4 max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-5 pb-4">
          <div>
            <h2
              id={titleId}
              className="text-lg font-semibold text-text-primary"
            >
              Settings
            </h2>
            <p className="text-text-muted text-[13px] mt-0.5">
              Configure your Orchestrator preferences
            </p>
          </div>
          <button
            type="button"
            onClick={close}
            className="text-text-muted hover:text-text-primary transition-colors p-1 -mr-1 -mt-0.5 rounded-md hover:bg-bg-hover"
            aria-label="Close"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 pb-5">
          <div className="space-y-6">
            <div>
              <h3 className="text-sm font-semibold text-text-primary mb-3">
                Activity Streaming
              </h3>
              <p className="text-sm text-text-secondary mb-4">
                Choose how activity events are delivered to your browser.
              </p>

              <div className="space-y-3">
                <label className="flex items-start gap-3 p-3 border border-border rounded-lg cursor-pointer hover:bg-bg-hover transition-colors">
                  <input
                    type="radio"
                    name="activityStreamMode"
                    value="sse"
                    checked={settings.activityStreamMode === 'sse'}
                    onChange={(e) => updateSettings({ activityStreamMode: e.target.value as 'sse' | 'polling' })}
                    className="mt-0.5 accent-accent-purple"
                  />
                  <div className="flex-1">
                    <div className="font-medium text-text-primary text-sm">
                      SSE (Real-time)
                    </div>
                    <div className="text-xs text-text-muted mt-1">
                      Server-Sent Events provide real-time updates with minimal latency.
                    </div>
                  </div>
                </label>

                <label className="flex items-start gap-3 p-3 border border-border rounded-lg cursor-pointer hover:bg-bg-hover transition-colors">
                  <input
                    type="radio"
                    name="activityStreamMode"
                    value="polling"
                    checked={settings.activityStreamMode === 'polling'}
                    onChange={(e) => updateSettings({ activityStreamMode: e.target.value as 'sse' | 'polling' })}
                    className="mt-0.5 accent-accent-purple"
                  />
                  <div className="flex-1">
                    <div className="font-medium text-text-primary text-sm">
                      Polling (Fallback)
                    </div>
                    <div className="text-xs text-text-muted mt-1">
                      HTTP polling checks for updates at regular intervals. More reliable but higher latency.
                    </div>
                  </div>
                </label>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-text-primary mb-3">
                Server
              </h3>
              <p className="text-sm text-text-secondary mb-4">
                Server-provided configuration values used by this UI.
              </p>

              {globalConfig.isLoading && (
                <div className="p-3 border border-border rounded-lg text-sm text-text-muted">
                  Loading server configuration...
                </div>
              )}

              {globalConfig.isError && (
                <div className="p-3 border border-status-failed/30 rounded-lg bg-status-failed/10">
                  <p className="text-sm text-status-failed">
                    Failed to load server configuration.
                  </p>
                  <button
                    type="button"
                    className="mt-3 px-3 py-1.5 text-xs font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/90 transition-colors"
                    onClick={() => { void globalConfig.refetch(); }}
                  >
                    Retry
                  </button>
                </div>
              )}

              {globalConfig.data && (
                <dl className="p-3 border border-border rounded-lg divide-y divide-border">
                  <div className="py-2 first:pt-0">
                    <dt className="text-xs font-medium uppercase tracking-wide text-text-muted">agents_default_type</dt>
                    <dd className="text-sm text-text-primary mt-1 break-all">{globalConfig.data.agents_default_type ?? 'Not set'}</dd>
                  </div>
                  <div className="py-2 last:pb-0">
                    <dt className="text-xs font-medium uppercase tracking-wide text-text-muted">dashboard_max_recent_runs</dt>
                    <dd className="text-sm text-text-primary mt-1">{globalConfig.data.dashboard_max_recent_runs}</dd>
                  </div>
                </dl>
              )}
            </div>
          </div>

          <div className="mt-6 p-3 bg-bg-elevated border border-border rounded-lg">
            <div className="flex items-start gap-2">
              <svg className="w-4 h-4 text-text-muted shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div className="text-xs text-text-secondary">
                <p className="font-medium mb-1">About Activity Streaming</p>
                <p>
                  SSE mode is recommended for the best experience. Polling mode is available as a fallback.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border flex justify-end">
          <button
            type="button"
            onClick={close}
            className="px-4 py-2 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/90 transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
