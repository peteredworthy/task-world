import { useState, useEffect, useRef } from 'react';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useRespondToClarification } from '../../hooks/useClarifications';
import { QuestionCard } from './QuestionCard';
import { Spinner } from '../Spinner';
import type { ClarificationRequest, ClarificationAnswer, ClarificationQuestion } from '../../types/clarifications';

interface ClarificationModalProps {
  open: boolean;
  onClose: () => void;
  clarificationRequest: ClarificationRequest;
  runId: string;
  taskId: string;
}

type AnswerMode = 'one-at-a-time' | 'all-at-once';

interface QuestionAnswerState {
  selectedOption: string | null;
  selectedOptions: string[];
  textValue: string;
  otherText: string;
  skipped: boolean;
}

interface AnswerState {
  [questionId: string]: QuestionAnswerState;
}

function createInitialAnswers(questions: ClarificationQuestion[]): AnswerState {
  const initial: AnswerState = {};
  for (const q of questions) {
    initial[q.id] = {
      selectedOption: null,
      selectedOptions: [],
      textValue: '',
      otherText: '',
      skipped: false,
    };
  }
  return initial;
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
  const questions: ClarificationQuestion[] = clarificationRequest.questions.map((question) => ({
    ...question,
    question_type: question.question_type ?? 'single_select',
    allow_other: question.allow_other ?? true,
    required: question.required ?? true,
    min: question.min ?? null,
    max: question.max ?? null,
    placeholder: question.placeholder ?? null,
  }));

  const [mode, setMode] = useState<AnswerMode>('all-at-once');
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [answers, setAnswers] = useState<AnswerState>(() => createInitialAnswers(questions));
  const [showSkip, setShowSkip] = useState(false);
  const [skipReason, setSkipReason] = useState('');

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

  const currentQuestion = questions[currentQuestionIndex];
  const isOneAtATime = mode === 'one-at-a-time';
  const questionById = new Map(questions.map((question) => [question.id, question]));

  function isAnswerComplete(question: ClarificationQuestion, answer: QuestionAnswerState): boolean {
    if (!question.required) return true;
    if (question.question_type === 'single_select') {
      return Boolean(answer.selectedOption) || answer.otherText.trim().length > 0;
    }
    if (question.question_type === 'multi_select') {
      return answer.selectedOptions.length > 0 || answer.otherText.trim().length > 0;
    }
    if (question.question_type === 'free_text') {
      return answer.textValue.trim().length > 0;
    }
    if (question.question_type === 'number') {
      const value = Number.parseFloat(answer.textValue);
      if (Number.isNaN(value)) return false;
      if (question.min != null && value < question.min) return false;
      if (question.max != null && value > question.max) return false;
      return true;
    }
    return false;
  }

  function isQuestionAnswered(question: ClarificationQuestion, answer: QuestionAnswerState): boolean {
    if (question.question_type === 'single_select') {
      return Boolean(answer.selectedOption) || answer.otherText.trim().length > 0;
    }
    if (question.question_type === 'multi_select') {
      return answer.selectedOptions.length > 0 || answer.otherText.trim().length > 0;
    }
    return answer.textValue.trim().length > 0;
  }

  function getCardFreeText(question: ClarificationQuestion, answer: QuestionAnswerState): string {
    if (question.question_type === 'single_select' || question.question_type === 'multi_select') {
      return answer.otherText;
    }
    return answer.textValue;
  }

  function buildAnswers(): ClarificationAnswer[] {
    return questions.map((question) => {
      const answer = answers[question.id];
      if (question.question_type === 'single_select') {
        return {
          question_id: question.id,
          selected_option: answer.selectedOption === 'Other' ? null : answer.selectedOption,
          free_text: answer.selectedOption === 'Other' ? answer.otherText || null : null,
        };
      }
      if (question.question_type === 'multi_select') {
        const selectedOptions = answer.selectedOptions.filter((option) => option !== 'Other');
        const includesOther = answer.selectedOptions.includes('Other');
        return {
          question_id: question.id,
          selected_option: null,
          selected_options: selectedOptions.length > 0 ? selectedOptions : undefined,
          free_text: includesOther ? answer.otherText || null : null,
        };
      }
      return {
        question_id: question.id,
        selected_option: null,
        free_text: answer.textValue.trim().length > 0 ? answer.textValue : null,
      };
    });
  }

  // Check if all questions are answered
  const allAnswered = questions.every((question) => isAnswerComplete(question, answers[question.id]));

  // Check if current question is answered (for one-at-a-time mode)
  const currentAnswered = currentQuestion
    ? isAnswerComplete(currentQuestion, answers[currentQuestion.id])
    : false;

  const canSkip =
    questions.every((question) => !question.required) ||
    questions.some((question) => question.required && isAnswerComplete(question, answers[question.id]));

  const canSubmit = allAnswered && !respondMutation.isPending;
  const canGoNext = isOneAtATime && currentAnswered && currentQuestionIndex < questions.length - 1;
  const canGoPrev = isOneAtATime && currentQuestionIndex > 0;

  function handleOptionChange(questionId: string, option: string | null) {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: {
        ...prev[questionId],
        selectedOption: option,
        otherText: option === 'Other' ? prev[questionId].otherText : '',
      },
    }));
  }

  function handleOptionsChange(questionId: string, values: string[]) {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: {
        ...prev[questionId],
        selectedOptions: values,
        otherText: values.includes('Other') ? prev[questionId].otherText : '',
      },
    }));
  }

  function handleFreeTextChange(questionId: string, text: string) {
    const question = questionById.get(questionId);
    if (!question) return;
    setAnswers((prev) => ({
      ...prev,
      [questionId]: {
        ...prev[questionId],
        ...(question.question_type === 'single_select' || question.question_type === 'multi_select'
          ? { otherText: text }
          : { textValue: text }),
      },
    }));
  }

  function resetForm() {
    setAnswers(createInitialAnswers(questions));
    setCurrentQuestionIndex(0);
    setShowSkip(false);
    setSkipReason('');
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

    const answersArray = buildAnswers();

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

  async function handleSkipSubmit() {
    if (!canSkip || respondMutation.isPending) return;
    try {
      await respondMutation.mutateAsync({
        requestId: clarificationRequest.id,
        data: {
          answers: buildAnswers(),
          skipped: true,
          skip_reason: skipReason.trim() || null,
        },
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
                  selectedOptions={answers[currentQuestion.id].selectedOptions}
                  freeText={getCardFreeText(currentQuestion, answers[currentQuestion.id])}
                  onOptionChange={handleOptionChange}
                  onOptionsChange={handleOptionsChange}
                  onFreeTextChange={handleFreeTextChange}
                  isAnswered={currentAnswered}
                />
              </div>
            ) : (
              // All-at-once mode: show all questions
              <div className="space-y-3">
                {questions.map((question) => {
                  const answer = answers[question.id];
                  return (
                    <QuestionCard
                      key={question.id}
                      question={question}
                      selectedOption={answer.selectedOption}
                      selectedOptions={answer.selectedOptions}
                      freeText={getCardFreeText(question, answer)}
                      onOptionChange={handleOptionChange}
                      onOptionsChange={handleOptionsChange}
                      onFreeTextChange={handleFreeTextChange}
                      isAnswered={isQuestionAnswered(question, answer)}
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
                    return (
                      <div
                        key={idx}
                        className={
                          'h-1 flex-1 rounded-full transition-colors ' +
                          (isQuestionAnswered(q, answer)
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
                    return isQuestionAnswered(q, answers[q.id]);
                  }).length} / {questions.length} answered
                </span>
              )}
            </div>
            <div className="flex flex-col items-end gap-3">
              {canSkip && !showSkip && (
                <button
                  type="button"
                  onClick={() => setShowSkip(true)}
                  disabled={respondMutation.isPending}
                  className="text-xs font-medium text-text-secondary hover:text-text-primary disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Skip remaining
                </button>
              )}
              {showSkip && (
                <div className="w-[280px] rounded-md border border-border bg-bg-card p-3 space-y-2">
                  <textarea
                    value={skipReason}
                    onChange={(e) => setSkipReason(e.target.value)}
                    placeholder="Reason for skipping (optional)"
                    rows={2}
                    className="w-full rounded-md border border-border bg-bg-elevated px-3 py-2 text-xs text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 resize-none"
                  />
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setShowSkip(false);
                        setSkipReason('');
                      }}
                      disabled={respondMutation.isPending}
                      className="px-2.5 py-1 text-xs font-medium text-text-secondary border border-border rounded-md hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={handleSkipSubmit}
                      disabled={respondMutation.isPending}
                      className="px-2.5 py-1 text-xs font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/90 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Confirm skip
                    </button>
                  </div>
                </div>
              )}
              <div className="flex gap-3">
              <button
                type="button"
                onClick={handleClose}
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
          </div>
        </form>
      </div>
    </div>
  );
}
