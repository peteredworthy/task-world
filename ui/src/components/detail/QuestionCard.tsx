import { useState } from 'react';
import type { ClarificationQuestion } from '../../types/clarifications';

interface QuestionCardProps {
  question: ClarificationQuestion;
  selectedOption: string | null;
  freeText: string;
  onOptionChange: (questionId: string, option: string | null) => void;
  onFreeTextChange: (questionId: string, text: string) => void;
  isAnswered: boolean;
}

export function QuestionCard({
  question,
  selectedOption,
  freeText,
  onOptionChange,
  onFreeTextChange,
  isAnswered,
}: QuestionCardProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  const showFreeText = selectedOption === 'Other';
  const isOtherSelected = selectedOption === 'Other';

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
          <label className="flex items-start gap-3 p-3 border border-border rounded-lg cursor-pointer hover:bg-bg-hover transition-colors">
            <input
              type="radio"
              name={`question-${question.id}`}
              value="Other"
              checked={isOtherSelected}
              onChange={() => onOptionChange(question.id, 'Other')}
              className="mt-0.5 accent-accent-purple shrink-0"
            />
            <div className="flex-1">
              <div className="text-sm text-text-primary mb-2">
                Other
              </div>
              {showFreeText && (
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
        </div>
      )}
    </div>
  );
}
