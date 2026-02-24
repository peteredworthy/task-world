import { useState, useMemo } from 'react';
import { BranchStatusSection } from './BranchStatusSection';
import { FileListSection } from './FileListSection';
import { DiffDialog } from './DiffDialog';
import { HistoryPanel } from './HistoryPanel';
import type { DiffScope } from './HistoryPanel';
import { TaskFilesPanel } from './TaskFilesPanel';
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

function ReviewMergeTabContent({ runId, worktreePath }: ReviewMergeTabProps) {
  const [selectedFile, setSelectedFile] = useState<DiffFileEntry | null>(null);
  const [showPreviewModal, setShowPreviewModal] = useState(false);
  const [historyScope, setHistoryScope] = useState<DiffScope>('aggregate');
  // Responsive left rail — collapsed by default on narrow viewports
  const [isRailOpen, setIsRailOpen] = useState(true);
  const [selectedCommitSha, setSelectedCommitSha] = useState<string | null>(null);
  const [logsResult, setLogsResult] = useState<TestRunResult | null>(null);
  const [showLogsDrawer, setShowLogsDrawer] = useState(false);
  const [agentFixResult, setAgentFixResult] = useState<TestRunResult | null>(null);
  const [showAgentFixModal, setShowAgentFixModal] = useState(false);
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
  const { data: diffFiles } = useDiffFiles(runId);

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
      // Show banner for both cases: merge commit created or already in sync (null sha)
      setBackMergeBanner({ mergeCommitSha: result.merge_commit_sha });
    }
    // conflicts case: ConflictFileList will auto-show via useConflicts query
  };

  const handleConflictFileSelect = (file: ConflictFile) => {
    const idx = (conflictFiles ?? []).findIndex((f) => f.path === file.path);
    setConflictResolverInitialIndex(idx >= 0 ? idx : 0);
    setConflictResolverOpen(true);
  };

  const unresolvedConflictCount = (conflictFiles ?? []).filter(
    (f) => f.status === 'unresolved',
  ).length;

  // Determine if the routine has auto_verify test commands configured
  const hasAutoVerify = useMemo(() => {
    if (!run?.routine_embedded) return true; // assume yes when unknown
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

  // Keyboard shortcuts — active in the Review tab, disabled in text inputs
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

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Tab header */}
      <div className="mb-3 flex items-center justify-end gap-2">
        {/* Rail toggle — visible on narrow viewports only (hidden on md+) */}
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
            {isRailOpen ? (
              <>
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <line x1="9" y1="3" x2="9" y2="21" />
              </>
            ) : (
              <>
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <line x1="9" y1="3" x2="9" y2="21" />
              </>
            )}
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

        {/* Agent Resolve button — only shown when unresolved conflicts exist */}
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

      {/* Prune toolbar (visible when prune mode is active) */}
      {isPruneMode && (
        <div className="mb-3">
          <PruneToolbar onPreview={() => setShowPreviewModal(true)} />
        </div>
      )}

      {/* Back merge banner (clean merge) */}
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

      {/* Final merge success banner */}
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

      <div className="flex h-full min-h-0 gap-4">
        {/* Left rail — always visible on md+, toggleable on narrow screens */}
        <div
          className={`${isRailOpen ? 'flex' : 'hidden'} md:flex w-72 shrink-0 flex-col gap-4 overflow-y-auto`}
        >
          <PanelErrorBoundary label="Branch Status">
            <BranchStatusSection runId={runId} worktreePath={worktreePath} />
          </PanelErrorBoundary>
          <PanelErrorBoundary label="File List">
            <FileListSection
              runId={runId}
              onFileSelect={setSelectedFile}
              onPruneFile={handlePruneFile}
            />
          </PanelErrorBoundary>
          {/* Conflict file list — shown when conflicts exist */}
          <PanelErrorBoundary label="Conflicts">
            <ConflictFileList
              runId={runId}
              onFileSelect={handleConflictFileSelect}
            />
          </PanelErrorBoundary>
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
          <PanelErrorBoundary label="History">
            <HistoryPanel
              runId={runId}
              scope={historyScope}
              selectedCommitSha={selectedCommitSha}
              onScopeChange={setHistoryScope}
              onCommitSelect={setSelectedCommitSha}
            />
          </PanelErrorBoundary>
          {run && (
            <PanelErrorBoundary label="Task Files">
              <TaskFilesPanel runId={runId} run={run} />
            </PanelErrorBoundary>
          )}
          {showLogsDrawer && (
            <TestLogsDrawer
              result={logsResult}
              isOpen={showLogsDrawer}
              onClose={() => setShowLogsDrawer(false)}
            />
          )}
        </div>

        {/* Main panel */}
        <div className="flex-1 min-w-0 rounded-md border border-border bg-bg-elevated p-4">
          {/* On narrow viewports when rail is hidden, show a prompt to open it */}
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
          <p className="text-xs text-text-muted">Select a file to view its diff.</p>
        </div>
      </div>

      <DiffDialog
        runId={runId}
        filePath={selectedFile?.path ?? ''}
        isOpen={selectedFile !== null}
        onClose={() => setSelectedFile(null)}
        initialScope={historyScope === 'commit' && selectedCommitSha ? 'commit' : 'aggregate'}
        initialRef={historyScope === 'commit' && selectedCommitSha ? selectedCommitSha : undefined}
      />

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

      {/* Back Merge Modal */}
      <BackMergeModal
        isOpen={showBackMergeModal}
        onClose={() => setShowBackMergeModal(false)}
        runId={runId}
        branchStatus={branchStatus ?? null}
        onMergeComplete={handleMergeComplete}
      />

      {/* Conflict Resolver Dialog */}
      {conflictFiles && conflictFiles.length > 0 && (
        <ConflictResolverDialog
          runId={runId}
          files={conflictFiles}
          initialFileIndex={conflictResolverInitialIndex}
          isOpen={conflictResolverOpen}
          onClose={() => setConflictResolverOpen(false)}
        />
      )}

      {/* Agent Resolve Conflicts Modal */}
      {run && (
        <AgentResolveConflictsModal
          isOpen={showAgentResolveModal}
          onClose={() => setShowAgentResolveModal(false)}
          runId={runId}
          run={run}
          unresolvedCount={unresolvedConflictCount}
        />
      )}

      {/* Merge Confirm Modal */}
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
