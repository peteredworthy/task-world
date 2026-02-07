import { useState, useEffect, useRef } from 'react';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useRespondToClarification } from '../../hooks/useClarifications';
import { QuestionCard } from './QuestionCard';
import { Spinner } from '../Spinner';
import type { ClarificationRequest, ClarificationAnswer } from '../../types/clarifications';

interface ClarificationModalProps {
  open: boolean;
  onClose: () => void;
  clarificationRequest: ClarificationRequest;
  runId: string;
  taskId: string;
}

type AnswerMode = 'one-at-a-time' | 'all-at-once';

interface AnswerState {
  [questionId: string]: {
    selectedOption: string | null;
    freeText: string;
  };
}

export function ClarificationModal({
  open,
  onClose,
  clarificationRequest,
  runId,
  taskId,
}: ClarificationModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const respondMutation = useRespondToClarification(runId, taskId);

  const [mode, setMode] = useState<AnswerMode>('all-at-once');
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [answers, setAnswers] = useState<AnswerState>(() => {
    // Initialize answer state for all questions
    const initial: AnswerState = {};
    for (const q of clarificationRequest.questions) {
      initial[q.id] = { selectedOption: null, freeText: '' };
    }
    return initial;
  });

  // Escape key to close
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && !respondMutation.isPending) onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose, respondMutation.isPending]);

  // Scroll lock
  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  useFocusTrap(dialogRef, open);

  if (!open) return null;

  const questions = clarificationRequest.questions;
  const currentQuestion = questions[currentQuestionIndex];
  const isOneAtATime = mode === 'one-at-a-time';

  // Check if all questions are answered
  const allAnswered = questions.every((q) => {
    const answer = answers[q.id];
    if (!answer.selectedOption) return false;
    if (answer.selectedOption === 'Other' && !answer.freeText.trim()) return false;
    return true;
  });

  // Check if current question is answered (for one-at-a-time mode)
  const currentAnswered = currentQuestion ? (() => {
    const answer = answers[currentQuestion.id];
    if (!answer.selectedOption) return false;
    if (answer.selectedOption === 'Other' && !answer.freeText.trim()) return false;
    return true;
  })() : false;

  const canSubmit = allAnswered && !respondMutation.isPending;
  const canGoNext = isOneAtATime && currentAnswered && currentQuestionIndex < questions.length - 1;
  const canGoPrev = isOneAtATime && currentQuestionIndex > 0;

  function handleOptionChange(questionId: string, option: string | null) {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: {
        selectedOption: option,
        freeText: option === 'Other' ? prev[questionId].freeText : '',
      },
    }));
  }

  function handleFreeTextChange(questionId: string, text: string) {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: {
        ...prev[questionId],
        freeText: text,
      },
    }));
  }

  function resetForm() {
    const initial: AnswerState = {};
    for (const q of clarificationRequest.questions) {
      initial[q.id] = { selectedOption: null, freeText: '' };
    }
    setAnswers(initial);
    setCurrentQuestionIndex(0);
  }

  function handleClose() {
    if (!respondMutation.isPending) {
      resetForm();
      onClose();
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    // Build answers array
    const answersArray: ClarificationAnswer[] = questions.map((q) => {
      const answer = answers[q.id];
      return {
        question_id: q.id,
        selected_option: answer.selectedOption === 'Other' ? null : answer.selectedOption,
        free_text: answer.selectedOption === 'Other' ? answer.freeText : null,
      };
    });

    try {
      await respondMutation.mutateAsync({
        requestId: clarificationRequest.id,
        data: { answers: answersArray },
      });
      resetForm();
      onClose();
    } catch {
      // Error handled by mutation state
    }
  }

  const titleId = 'clarification-modal-title';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={respondMutation.isPending ? undefined : handleClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-bg-primary border border-border rounded-xl shadow-2xl w-full max-w-[640px] mx-4 max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-border">
          <div className="flex-1">
            <h2
              id={titleId}
              className="text-lg font-semibold text-text-primary"
            >
              Clarification Required
            </h2>
            <p className="text-text-muted text-[13px] mt-0.5">
              Please answer the following questions to help the agent proceed.
            </p>
          </div>
          <button
            type="button"
            onClick={respondMutation.isPending ? undefined : handleClose}
            disabled={respondMutation.isPending}
            className="text-text-muted hover:text-text-primary transition-colors p-1 -mr-1 -mt-0.5 rounded-md hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed"
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

        {/* Mode Toggle */}
        <div className="px-6 pt-4 pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-muted">Answer mode:</span>
            <div className="flex gap-1 bg-bg-elevated rounded-md p-1">
              <button
                type="button"
                onClick={() => setMode('all-at-once')}
                className={
                  'px-3 py-1.5 text-xs font-medium rounded transition-colors ' +
                  (mode === 'all-at-once'
                    ? 'bg-accent-purple text-white'
                    : 'text-text-secondary hover:text-text-primary')
                }
              >
                All at once
              </button>
              <button
                type="button"
                onClick={() => setMode('one-at-a-time')}
                className={
                  'px-3 py-1.5 text-xs font-medium rounded transition-colors ' +
                  (mode === 'one-at-a-time'
                    ? 'bg-accent-purple text-white'
                    : 'text-text-secondary hover:text-text-primary')
                }
              >
                One at a time
              </button>
            </div>
          </div>
        </div>

        {/* Content */}
        <form onSubmit={handleSubmit} className="flex flex-col flex-1 min-h-0">
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {isOneAtATime ? (
              // One-at-a-time mode: show only current question
              <div className="space-y-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-text-muted">
                    Question {currentQuestionIndex + 1} of {questions.length}
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setCurrentQuestionIndex(currentQuestionIndex - 1)}
                      disabled={!canGoPrev}
                      className="px-3 py-1.5 text-xs font-medium text-text-secondary bg-bg-card border border-border rounded-md hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      onClick={() => setCurrentQuestionIndex(currentQuestionIndex + 1)}
                      disabled={!canGoNext}
                      className="px-3 py-1.5 text-xs font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Next
                    </button>
                  </div>
                </div>
                <QuestionCard
                  question={currentQuestion}
                  selectedOption={answers[currentQuestion.id].selectedOption}
                  freeText={answers[currentQuestion.id].freeText}
                  onOptionChange={handleOptionChange}
                  onFreeTextChange={handleFreeTextChange}
                  isAnswered={currentAnswered}
                />
              </div>
            ) : (
              // All-at-once mode: show all questions
              <div className="space-y-3">
                {questions.map((question) => {
                  const answer = answers[question.id];
                  const isAnswered =
                    !!answer.selectedOption &&
                    (answer.selectedOption !== 'Other' || !!answer.freeText.trim());
                  return (
                    <QuestionCard
                      key={question.id}
                      question={question}
                      selectedOption={answer.selectedOption}
                      freeText={answer.freeText}
                      onOptionChange={handleOptionChange}
                      onFreeTextChange={handleFreeTextChange}
                      isAnswered={isAnswered}
                    />
                  );
                })}
              </div>
            )}

            {/* Progress indicator for one-at-a-time mode */}
            {isOneAtATime && (
              <div className="mt-4">
                <div className="flex gap-1">
                  {questions.map((_, idx) => {
                    const q = questions[idx];
                    const answer = answers[q.id];
                    const isAnswered =
                      !!answer.selectedOption &&
                      (answer.selectedOption !== 'Other' || !!answer.freeText.trim());
                    return (
                      <div
                        key={idx}
                        className={
                          'h-1 flex-1 rounded-full transition-colors ' +
                          (isAnswered
                            ? 'bg-status-completed'
                            : idx === currentQuestionIndex
                            ? 'bg-accent-purple'
                            : 'bg-border')
                        }
                      />
                    );
                  })}
                </div>
              </div>
            )}

            {/* Error state */}
            {respondMutation.isError && (
              <div className="mt-4 rounded-md bg-status-failed/10 border border-status-failed/20 px-3 py-2">
                <p className="text-sm text-status-failed">
                  Failed to submit answers. Please try again.
                </p>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-border flex justify-between items-center">
            <div className="text-xs text-text-muted">
              {allAnswered ? (
                <span className="text-status-completed">All questions answered</span>
              ) : (
                <span>
                  {questions.filter((q) => {
                    const a = answers[q.id];
                    return a.selectedOption && (a.selectedOption !== 'Other' || a.freeText.trim());
                  }).length} / {questions.length} answered
                </span>
              )}
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={onClose}
                disabled={respondMutation.isPending}
                className="px-4 py-2 text-sm font-medium text-text-secondary bg-transparent border border-border-hover rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!canSubmit}
                className="px-5 py-2 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
              >
                {respondMutation.isPending ? (
                  <>
                    <Spinner className="h-4 w-4" />
                    <span>Submitting...</span>
                  </>
                ) : (
                  <span>Submit Answers</span>
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
