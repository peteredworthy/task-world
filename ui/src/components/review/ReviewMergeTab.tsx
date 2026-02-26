import { useState, useMemo, useEffect, type ReactNode } from 'react';
import { BranchStatusSection } from './BranchStatusSection';
import { FileListSection } from './FileListSection';
import { DiffPanel } from './DiffPanel';
import { HistoryPanel } from './HistoryPanel';
import type { DiffScope } from './HistoryPanel';
import { PruneModeProvider, usePruneMode } from './PruneModeProvider';
import { PruneToolbar } from './PruneToolbar';
import { PrunePreviewModal } from './PrunePreviewModal';
import { TestPanel } from './TestPanel';
import { TestLogsDrawer } from './TestLogsDrawer';
import { AgentFixTestsModal } from './AgentFixTestsModal';
import { BackMergeModal } from './BackMergeModal';
import { BackMergeBanner } from './BackMergeBanner';
import { ConflictFileList } from './ConflictFileList';
import { ConflictResolverDialog } from './ConflictResolverDialog';
import { AgentResolveConflictsModal } from './AgentResolveConflictsModal';
import { MergeReadinessBar } from './MergeReadinessBar';
import { MergeConfirmModal } from './MergeConfirmModal';
import { TaskRangeSelectorBar, type SharedDiffSelection } from './TaskRangeSelectorBar';
import { PanelErrorBoundary } from '../PanelErrorBoundary';
import { useRun } from '../../hooks/useApi';
import { useBranchStatus, useConflicts, useDiffFiles, useRunTests } from '../../hooks/useReview';
import { useReviewKeyboardShortcuts } from '../../hooks/useReviewKeyboardShortcuts';
import type { DiffFileEntry } from '../../types/review';
import type { TestRunResult, BackMergeResponse, ConflictFile, FinalMergeBackResponse } from '../../types/review';

interface ReviewMergeTabProps {
  runId: string;
  worktreePath: string | null;
}

// ── Section collapse state ────────────────────────────────────────────────────

type SectionKey = 'branch' | 'files' | 'conflicts' | 'tests' | 'history';

// ── Collapsible section wrapper ───────────────────────────────────────────────

function CollapsibleSection({
  label,
  isOpen,
  onToggle,
  children,
}: {
  label: string;
  isOpen: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <button
        type="button"
        onClick={onToggle}
        className={`flex items-center gap-1.5 rounded px-2 py-1 text-left transition-colors hover:bg-bg-muted group ${
          isOpen ? '' : 'rounded-md border border-border bg-bg-elevated'
        }`}
        aria-expanded={isOpen}
      >
        <svg
          className={`shrink-0 transition-transform duration-150 ${
            isOpen ? 'text-text-muted' : 'text-text-secondary'
          } ${isOpen ? '' : '-rotate-90'}`}
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M5 7L1 3h8L5 7z" />
        </svg>
        <span
          className={`text-[11px] font-semibold uppercase tracking-wide transition-colors ${
            isOpen
              ? 'text-text-muted group-hover:text-text-secondary'
              : 'text-text-secondary'
          }`}
        >
          {label}
        </span>
      </button>
      {isOpen && children}
    </div>
  );
}

// ── Main content ──────────────────────────────────────────────────────────────

function ReviewMergeTabContent({ runId, worktreePath }: ReviewMergeTabProps) {
  const [sharedDiffSelection, setSharedDiffSelection] = useState<SharedDiffSelection>({
    scope: 'aggregate',
    summary: 'All work',
  });
  const [selectedFile, setSelectedFile] = useState<DiffFileEntry | null>(null);
  const [showPreviewModal, setShowPreviewModal] = useState(false);
  const [historyScope, setHistoryScope] = useState<DiffScope>('aggregate');
  // Responsive left rail — collapsed by default on narrow viewports
  const [isRailOpen, setIsRailOpen] = useState(true);
  const [isRailMinimized, setIsRailMinimized] = useState(false);
  const [selectedCommitSha, setSelectedCommitSha] = useState<string | null>(null);
  const [logsResult, setLogsResult] = useState<TestRunResult | null>(null);
  const [showLogsDrawer, setShowLogsDrawer] = useState(false);
  const [agentFixResult, setAgentFixResult] = useState<TestRunResult | null>(null);
  const [showAgentFixModal, setShowAgentFixModal] = useState(false);

  // Collapsible section state — branch+files+conflicts open by default, rest closed
  const [openSections, setOpenSections] = useState<Record<SectionKey, boolean>>({
    branch: true,
    files: true,
    conflicts: true,
    tests: false,
    history: false,
  });

  const toggleSection = (id: SectionKey) =>
    setOpenSections((prev) => ({ ...prev, [id]: !prev[id] }));

  const expandSection = (id: SectionKey) => {
    setIsRailMinimized(false);
    setOpenSections((prev) => ({ ...prev, [id]: true }));
  };

  const { isPruneMode, togglePruneMode, buildPruneSelection, clearSelections, selectFile } = usePruneMode();
  const { data: run } = useRun(runId);
  const { data: branchStatus } = useBranchStatus(runId);

  // Test run state — lifted here so keyboard shortcuts can trigger tests
  const [testRunId, setTestRunId] = useState<string | null>(null);
  const { mutate: startTests, isPending: isStartingTests } = useRunTests(runId);

  function handleRunTests() {
    startTests(undefined, {
      onSuccess: (response) => {
        setTestRunId(response.test_run_id);
      },
    });
  }

  // Back merge state
  const [showBackMergeModal, setShowBackMergeModal] = useState(false);
  const [backMergeBanner, setBackMergeBanner] = useState<{ mergeCommitSha: string | null } | null>(null);

  // Conflict resolver state
  const [conflictResolverOpen, setConflictResolverOpen] = useState(false);
  const [conflictResolverInitialIndex, setConflictResolverInitialIndex] = useState(0);
  const { data: conflictFiles } = useConflicts(runId);

  // Agent resolve conflicts state
  const [showAgentResolveModal, setShowAgentResolveModal] = useState(false);

  // Merge confirm modal state
  const [showMergeConfirmModal, setShowMergeConfirmModal] = useState(false);
  const [mergeSuccessSha, setMergeSuccessSha] = useState<string | null>(null);

  // Diff file list (for j/k keyboard navigation)
  const { data: diffFiles } = useDiffFiles(
    runId,
    sharedDiffSelection.scope,
    sharedDiffSelection.ref,
  );

  useEffect(() => {
    if (!selectedFile || !diffFiles) return;
    if (!diffFiles.some((f) => f.path === selectedFile.path)) {
      setSelectedFile(null);
    }
  }, [diffFiles, selectedFile]);

  const handlePruneFile = (file: DiffFileEntry) => {
    if (!isPruneMode) {
      togglePruneMode();
    }
    selectFile(file.path);
  };

  const handleApplied = () => {
    clearSelections();
    if (isPruneMode) togglePruneMode();
    setShowPreviewModal(false);
  };

  const handleViewLogs = (result: TestRunResult) => {
    setLogsResult(result);
    setShowLogsDrawer(true);
  };

  const handleAgentFix = (result: TestRunResult) => {
    setAgentFixResult(result);
    setShowAgentFixModal(true);
  };

  const handleMergeComplete = (result: BackMergeResponse) => {
    if (result.status === 'clean') {
      setBackMergeBanner({ mergeCommitSha: result.merge_commit_sha });
    }
  };

  const handleConflictFileSelect = (file: ConflictFile) => {
    const idx = (conflictFiles ?? []).findIndex((f) => f.path === file.path);
    setConflictResolverInitialIndex(idx >= 0 ? idx : 0);
    setConflictResolverOpen(true);
  };

  const unresolvedConflictCount = (conflictFiles ?? []).filter(
    (f) => f.status === 'unresolved',
  ).length;

  const hasAutoVerify = useMemo(() => {
    if (!run?.routine_embedded) return true;
    const steps = run.routine_embedded.steps as Record<string, unknown>[] | undefined;
    if (!Array.isArray(steps)) return true;
    return steps.some((step) => {
      const av = step.auto_verify as Record<string, unknown> | undefined;
      return av != null && Array.isArray(av.items) && (av.items as unknown[]).length > 0;
    });
  }, [run]);

  const handleMergeCommit = () => {
    setShowMergeConfirmModal(true);
  };

  const handleFinalMergeComplete = (result: FinalMergeBackResponse) => {
    setMergeSuccessSha(result.merge_commit);
  };

  useReviewKeyboardShortcuts({
    files: diffFiles ?? [],
    selectedFile,
    onSelectFile: setSelectedFile,
    conflictFiles: conflictFiles ?? [],
    conflictResolverOpen,
    conflictResolverIndex: conflictResolverInitialIndex,
    onSetConflictIndex: setConflictResolverInitialIndex,
    onOpenConflictResolver: () => setConflictResolverOpen(true),
    onTogglePruneMode: togglePruneMode,
    onRunTests: handleRunTests,
  });

  // Show conflicts section during loading (null) or when conflicts exist
  const showConflictsSection = conflictFiles == null || conflictFiles.length > 0;

  // Shared icon button class for the minimized strip
  const iconBtnClass =
    'rounded p-1.5 text-text-muted hover:bg-bg-muted hover:text-text-primary transition-colors';

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Tab header */}
      <div className="mb-3 flex items-center justify-end gap-2">
        {/* Rail toggle — visible on narrow viewports only */}
        <button
          type="button"
          onClick={() => setIsRailOpen((v) => !v)}
          className="md:hidden rounded border border-border p-1.5 text-text-muted hover:bg-bg-muted hover:text-text-primary transition-colors"
          title={isRailOpen ? 'Hide side panel' : 'Show side panel'}
          aria-label={isRailOpen ? 'Hide side panel' : 'Show side panel'}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
            <line x1="9" y1="3" x2="9" y2="21" />
          </svg>
        </button>

        {/* Back Merge button */}
        <button
          type="button"
          onClick={() => setShowBackMergeModal(true)}
          className="rounded border border-border px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-bg-muted hover:text-text-primary transition-colors"
          title="Merge target branch into run branch"
        >
          Back Merge
        </button>

        {unresolvedConflictCount > 0 && run && (
          <button
            type="button"
            onClick={() => setShowAgentResolveModal(true)}
            className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-400 hover:bg-amber-500/20 transition-colors"
            title="Use agent to resolve conflicts"
          >
            Use Agent to Resolve
          </button>
        )}

        <button
          type="button"
          onClick={togglePruneMode}
          className={`rounded border px-3 py-1.5 text-xs font-medium transition-colors ${
            isPruneMode
              ? 'border-amber-500/50 bg-amber-500/15 text-amber-400 hover:bg-amber-500/25'
              : 'border-border text-text-secondary hover:bg-bg-muted hover:text-text-primary'
          }`}
          title={isPruneMode ? 'Exit prune mode (Shift+P)' : 'Enter prune mode to select changes for removal (Shift+P)'}
        >
          {isPruneMode ? 'Exit Prune Mode' : 'Prune Mode'}
        </button>
      </div>

      {isPruneMode && (
        <div className="mb-3">
          <PruneToolbar onPreview={() => setShowPreviewModal(true)} />
        </div>
      )}

      {backMergeBanner && (
        <div className="mb-3">
          <BackMergeBanner
            runId={runId}
            mergeCommitSha={backMergeBanner.mergeCommitSha}
            onDismiss={() => setBackMergeBanner(null)}
            onReverted={() => setBackMergeBanner(null)}
          />
        </div>
      )}

      {mergeSuccessSha && (
        <div className="mb-3 rounded-md border border-status-passed/30 bg-status-passed/8 px-4 py-3 flex items-center justify-between gap-3">
          <p className="text-sm text-status-passed font-medium">
            Merge complete —{' '}
            <code className="font-mono text-xs">{mergeSuccessSha.slice(0, 8)}</code>
          </p>
          <button
            type="button"
            onClick={() => setMergeSuccessSha(null)}
            className="text-text-muted hover:text-text-primary transition-colors p-0.5 rounded"
            aria-label="Dismiss"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="14"
              height="14"
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
      )}

      <TaskRangeSelectorBar
        runId={runId}
        run={run ?? undefined}
        onSelectionChange={setSharedDiffSelection}
      />

      <div className="flex h-full min-h-0 gap-4">
        {/* ── Left rail ─────────────────────────────────────────────────── */}
        {isRailMinimized ? (
          /* Minimized: narrow icon strip */
          <div
            className={`${isRailOpen ? 'flex' : 'hidden'} md:flex w-10 shrink-0 flex-col items-center gap-1 border-r border-border py-2`}
          >
            {/* Expand button */}
            <button
              type="button"
              onClick={() => setIsRailMinimized(false)}
              title="Expand side panel"
              className={iconBtnClass}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </button>

            <div className="my-0.5 h-px w-6 bg-border" />

            {/* Branch Status */}
            <button
              type="button"
              onClick={() => expandSection('branch')}
              title="Branch Status"
              className={iconBtnClass}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <line x1="6" y1="3" x2="6" y2="15" />
                <circle cx="18" cy="6" r="3" />
                <circle cx="6" cy="18" r="3" />
                <path d="M18 9a9 9 0 0 1-9 9" />
              </svg>
            </button>

            {/* Modified Files */}
            <button
              type="button"
              onClick={() => expandSection('files')}
              title="Modified Files"
              className={iconBtnClass}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </button>

            {/* Conflicts */}
            <button
              type="button"
              onClick={() => expandSection('conflicts')}
              title="Conflicts"
              className={iconBtnClass}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            </button>

            {/* Tests */}
            <button
              type="button"
              onClick={() => expandSection('tests')}
              title="Tests"
              className={iconBtnClass}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v11l-2 3h10l-2-3V3" />
              </svg>
            </button>

            {/* History */}
            <button
              type="button"
              onClick={() => expandSection('history')}
              title="History"
              className={iconBtnClass}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
            </button>

          </div>
        ) : (
          /* Full rail */
          <div
            className={`${isRailOpen ? 'flex' : 'hidden'} md:flex w-72 shrink-0 flex-col gap-2 overflow-y-auto`}
          >
            {/* Minimize button */}
            <div className="flex shrink-0 items-center justify-end px-1">
              <button
                type="button"
                onClick={() => setIsRailMinimized(true)}
                title="Minimize side panel"
                className="rounded p-1 text-text-muted hover:bg-bg-muted hover:text-text-primary transition-colors"
              >
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
            </div>

            <CollapsibleSection
              label="Branch Status"
              isOpen={openSections.branch}
              onToggle={() => toggleSection('branch')}
            >
              <PanelErrorBoundary label="Branch Status">
                <BranchStatusSection runId={runId} worktreePath={worktreePath} />
              </PanelErrorBoundary>
            </CollapsibleSection>

            <CollapsibleSection
              label="Modified Files"
              isOpen={openSections.files}
              onToggle={() => toggleSection('files')}
            >
              <PanelErrorBoundary label="File List">
                <FileListSection
                  runId={runId}
                  diffScope={sharedDiffSelection.scope}
                  diffRef={sharedDiffSelection.ref}
                  selectionSummary={sharedDiffSelection.summary}
                  selectedFilePath={selectedFile?.path ?? null}
                  onFileSelect={setSelectedFile}
                  onPruneFile={handlePruneFile}
                />
              </PanelErrorBoundary>
            </CollapsibleSection>

            {showConflictsSection && (
              <CollapsibleSection
                label="Conflicts"
                isOpen={openSections.conflicts}
                onToggle={() => toggleSection('conflicts')}
              >
                <PanelErrorBoundary label="Conflicts">
                  <ConflictFileList
                    runId={runId}
                    onFileSelect={handleConflictFileSelect}
                  />
                </PanelErrorBoundary>
              </CollapsibleSection>
            )}

            <CollapsibleSection
              label="Tests"
              isOpen={openSections.tests}
              onToggle={() => toggleSection('tests')}
            >
              <PanelErrorBoundary label="Tests">
                <TestPanel
                  runId={runId}
                  hasAutoVerify={hasAutoVerify}
                  testRunId={testRunId}
                  isStarting={isStartingTests}
                  onRunTests={handleRunTests}
                  onViewLogs={handleViewLogs}
                  onAgentFix={handleAgentFix}
                />
              </PanelErrorBoundary>
            </CollapsibleSection>

            <CollapsibleSection
              label="History"
              isOpen={openSections.history}
              onToggle={() => toggleSection('history')}
            >
              <PanelErrorBoundary label="History">
                <HistoryPanel
                  runId={runId}
                  scope={historyScope}
                  selectedCommitSha={selectedCommitSha}
                  onScopeChange={setHistoryScope}
                  onCommitSelect={setSelectedCommitSha}
                />
              </PanelErrorBoundary>
            </CollapsibleSection>
          </div>
        )}

        {/* ── Main panel ────────────────────────────────────────────────── */}
        <div className="flex-1 min-w-0 min-h-0">
          {!isRailOpen && (
            <div className="mb-3 flex items-center gap-2 md:hidden">
              <button
                type="button"
                onClick={() => setIsRailOpen(true)}
                className="text-xs text-text-muted underline hover:text-text-secondary transition-colors"
              >
                Show side panel
              </button>
            </div>
          )}
          <DiffPanel
            runId={runId}
            filePath={selectedFile?.path ?? null}
            diffScope={sharedDiffSelection.scope}
            diffRef={sharedDiffSelection.ref}
            selectionSummary={sharedDiffSelection.summary}
          />
        </div>
      </div>

      {/* ── Drawers & modals ──────────────────────────────────────────────── */}

      {showLogsDrawer && (
        <TestLogsDrawer
          result={logsResult}
          isOpen={showLogsDrawer}
          onClose={() => setShowLogsDrawer(false)}
        />
      )}

      <PrunePreviewModal
        isOpen={showPreviewModal}
        onClose={() => setShowPreviewModal(false)}
        runId={runId}
        selection={buildPruneSelection('aggregate')}
        onApplied={handleApplied}
      />

      {run && agentFixResult && (
        <AgentFixTestsModal
          isOpen={showAgentFixModal}
          onClose={() => setShowAgentFixModal(false)}
          runId={runId}
          run={run}
          testResult={agentFixResult}
        />
      )}

      <BackMergeModal
        isOpen={showBackMergeModal}
        onClose={() => setShowBackMergeModal(false)}
        runId={runId}
        branchStatus={branchStatus ?? null}
        onMergeComplete={handleMergeComplete}
      />

      {conflictFiles && conflictFiles.length > 0 && (
        <ConflictResolverDialog
          runId={runId}
          files={conflictFiles}
          initialFileIndex={conflictResolverInitialIndex}
          isOpen={conflictResolverOpen}
          onClose={() => setConflictResolverOpen(false)}
        />
      )}

      {run && (
        <AgentResolveConflictsModal
          isOpen={showAgentResolveModal}
          onClose={() => setShowAgentResolveModal(false)}
          runId={runId}
          run={run}
          unresolvedCount={unresolvedConflictCount}
        />
      )}

      <MergeConfirmModal
        isOpen={showMergeConfirmModal}
        onClose={() => setShowMergeConfirmModal(false)}
        runId={runId}
        onMergeComplete={handleFinalMergeComplete}
      />

      {/* Merge Readiness Bar — sticky bottom of tab */}
      <PanelErrorBoundary label="Readiness Bar">
        <MergeReadinessBar runId={runId} onMergeCommit={handleMergeCommit} />
      </PanelErrorBoundary>
    </div>
  );
}

export function ReviewMergeTab({ runId, worktreePath }: ReviewMergeTabProps) {
  return (
    <PruneModeProvider>
      <ReviewMergeTabContent runId={runId} worktreePath={worktreePath} />
    </PruneModeProvider>
  );
}
