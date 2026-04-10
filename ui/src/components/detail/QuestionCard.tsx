import { useState } from 'react';
import type { ClarificationQuestion } from '../../types/clarifications';

interface QuestionCardProps {
  question: ClarificationQuestion;
  selectedOption: string | null;
  selectedOptions?: string[];
  freeText: string;
  onOptionChange: (questionId: string, option: string | null) => void;
  onOptionsChange?: (questionId: string, options: string[]) => void;
  onFreeTextChange: (questionId: string, text: string) => void;
  isAnswered: boolean;
}

export function QuestionCard({
  question,
  selectedOption,
  selectedOptions,
  freeText,
  onOptionChange,
  onOptionsChange,
  onFreeTextChange,
  isAnswered,
}: QuestionCardProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  const multiValues = selectedOptions ?? [];
  const showSingleOtherText = selectedOption === 'Other';
  const isSingleOtherSelected = selectedOption === 'Other';
  const isMultiOtherSelected = multiValues.includes('Other');

  const parsedValue = parseFloat(freeText);
  const hasNumberValue = freeText.trim().length > 0 && !Number.isNaN(parsedValue);
  const isBelowMin = question.min != null && parsedValue < question.min;
  const isAboveMax = question.max != null && parsedValue > question.max;
  const hasNumberError = question.question_type === 'number' && hasNumberValue && (isBelowMin || isAboveMax);

  let numberErrorMessage = '';
  if (question.min != null && question.max != null) {
    numberErrorMessage = `Value must be between ${question.min} and ${question.max}.`;
  } else if (question.min != null) {
    numberErrorMessage = `Value must be at least ${question.min}.`;
  } else if (question.max != null) {
    numberErrorMessage = `Value must be at most ${question.max}.`;
  }

  return (
    <div
      className={
        'rounded-lg border transition-colors ' +
        (isAnswered
          ? 'bg-accent-purple/5 border-accent-purple/30'
          : 'bg-bg-card border-border')
      }
    >
      {/* Header */}
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-start justify-between px-4 py-3 text-left hover:bg-bg-hover transition-colors rounded-t-lg"
      >
        <div className="flex-1 pr-4">
          <h3 className="text-sm font-medium text-text-primary mb-1">
            {question.question}
            {question.required && <span className="text-status-failed ml-1">*</span>}
          </h3>
          {question.context && (
            <p className="text-xs text-text-muted">
              {question.context}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isAnswered && (
            <svg
              className="h-4 w-4 text-status-completed"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2.5}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          )}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={
              'transition-transform text-text-muted ' +
              (isExpanded ? 'rotate-90' : '')
            }
          >
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </div>
      </button>

      {/* Options */}
      {isExpanded && (
        <div className="px-4 pb-4 space-y-2">
          {question.question_type === 'single_select' && (
            <>
              {question.options.map((option) => (
                <label
                  key={option}
                  className="flex items-start gap-3 p-3 border border-border rounded-lg cursor-pointer hover:bg-bg-hover transition-colors"
                >
                  <input
                    type="radio"
                    name={`question-${question.id}`}
                    value={option}
                    checked={selectedOption === option}
                    onChange={() => onOptionChange(question.id, option)}
                    className="mt-0.5 accent-accent-purple shrink-0"
                  />
                  <div className="flex-1">
                    <div className="text-sm text-text-primary">
                      {option}
                    </div>
                  </div>
                </label>
              ))}

              {/* Other option with text input */}
              {question.allow_other && (
                <label className="flex items-start gap-3 p-3 border border-border rounded-lg cursor-pointer hover:bg-bg-hover transition-colors">
                  <input
                    type="radio"
                    name={`question-${question.id}`}
                    value="Other"
                    checked={isSingleOtherSelected}
                    onChange={() => onOptionChange(question.id, 'Other')}
                    className="mt-0.5 accent-accent-purple shrink-0"
                  />
                  <div className="flex-1">
                    <div className="text-sm text-text-primary mb-2">
                      Other
                    </div>
                    {showSingleOtherText && (
                      <textarea
                        value={freeText}
                        onChange={(e) => onFreeTextChange(question.id, e.target.value)}
                        placeholder="Please specify..."
                        rows={3}
                        className="w-full rounded-md border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 resize-none"
                        onClick={(e) => e.stopPropagation()}
                      />
                    )}
                  </div>
                </label>
              )}
            </>
          )}

          {question.question_type === 'multi_select' && (
            <>
              {question.options.map((option) => (
                <label
                  key={option}
                  className="flex items-start gap-3 p-3 border border-border rounded-lg cursor-pointer hover:bg-bg-hover transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={multiValues.includes(option)}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...multiValues, option]
                        : multiValues.filter((o) => o !== option);
                      onOptionsChange?.(question.id, next);
                    }}
                    className="mt-0.5 accent-accent-purple shrink-0"
                  />
                  <div className="flex-1">
                    <div className="text-sm text-text-primary">
                      {option}
                    </div>
                  </div>
                </label>
              ))}

              {question.allow_other && (
                <label className="flex items-start gap-3 p-3 border border-border rounded-lg cursor-pointer hover:bg-bg-hover transition-colors">
                  <input
                    type="checkbox"
                    checked={isMultiOtherSelected}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...multiValues, 'Other']
                        : multiValues.filter((o) => o !== 'Other');
                      onOptionsChange?.(question.id, next);
                    }}
                    className="mt-0.5 accent-accent-purple shrink-0"
                  />
                  <div className="flex-1">
                    <div className="text-sm text-text-primary mb-2">
                      Other
                    </div>
                    {isMultiOtherSelected && (
                      <textarea
                        value={freeText}
                        onChange={(e) => onFreeTextChange(question.id, e.target.value)}
                        placeholder="Please specify..."
                        rows={3}
                        className="w-full rounded-md border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 resize-none"
                        onClick={(e) => e.stopPropagation()}
                      />
                    )}
                  </div>
                </label>
              )}
            </>
          )}

          {question.question_type === 'free_text' && (
            <textarea
              value={freeText}
              onChange={(e) => onFreeTextChange(question.id, e.target.value)}
              placeholder={question.placeholder ?? ''}
              rows={4}
              className="w-full rounded-md border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 resize-none"
            />
          )}

          {question.question_type === 'number' && (
            <div className="space-y-2">
              <input
                type="number"
                min={question.min ?? undefined}
                max={question.max ?? undefined}
                placeholder={question.placeholder ?? ''}
                value={freeText}
                onChange={(e) => onFreeTextChange(question.id, e.target.value)}
                className={
                  'w-full rounded-md border bg-bg-elevated px-3 py-2 text-sm text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 ' +
                  (hasNumberError ? 'border-status-failed' : 'border-border')
                }
              />
              {hasNumberError && numberErrorMessage && (
                <p role="alert" className="text-xs text-status-failed">
                  {numberErrorMessage}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
