import { useState } from 'react';
import type { ClarificationAnswer, ClarificationHistoryItem } from '../../types/clarifications';

interface Props {
  item: ClarificationHistoryItem;
  roundNumber: number;
}

function findAnswer(
  answers: ClarificationAnswer[] | undefined,
  questionId: string,
): ClarificationAnswer | undefined {
  return answers?.find(answer => answer.question_id === questionId);
}

function formatQuestionAnswer(answer: ClarificationAnswer | undefined): string {
  if (!answer) {
    return '--';
  }

  if (answer.skipped) {
    return answer.skip_reason ? `Skipped: ${answer.skip_reason}` : 'Skipped';
  }

  if (answer.selected_options && answer.selected_options.length > 0) {
    return answer.selected_options.join(', ');
  }

  if (answer.selected_option) {
    return answer.selected_option;
  }

  if (answer.free_text) {
    return answer.free_text;
  }

  return '--';
}

export function ClarificationHistoryCard({ item, roundNumber }: Props) {
  const [expanded, setExpanded] = useState(false);
  const { request, response } = item;

  const isPending = response === null;
  const isSkipped = response?.skipped ?? false;

  const statusLabel = isPending ? 'Pending' : isSkipped ? 'Skipped' : 'Answered';
  const statusClass = isPending
    ? 'bg-status-pending/15 text-status-pending border-status-pending/40'
    : isSkipped
      ? 'bg-status-paused/15 text-status-paused border-status-paused/40'
      : 'bg-status-completed/15 text-status-completed border-status-completed/40';

  const createdAt = request.created_at ? new Date(request.created_at) : null;
  const timestamp =
    createdAt && !Number.isNaN(createdAt.getTime())
      ? createdAt.toLocaleString()
      : null;

  return (
    <article className="rounded-lg border border-border bg-bg-card">
      <button
        type="button"
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left hover:bg-bg-hover"
        onClick={() => setExpanded(value => !value)}
        aria-expanded={expanded}
      >
        <span
          className="inline-flex h-5 w-5 items-center justify-center rounded border border-border text-[10px] text-text-muted"
          aria-hidden="true"
        >
          {expanded ? 'v' : '>'}
        </span>
        <span className="text-sm font-medium text-text-primary">
          Clarification {roundNumber}
        </span>
        <span
          className={`ml-auto inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusClass}`}
        >
          {statusLabel}
        </span>
        {timestamp && (
          <time
            className="text-[11px] whitespace-nowrap text-text-muted"
            dateTime={request.created_at}
          >
            {timestamp}
          </time>
        )}
      </button>

      {expanded && (
        <div className="space-y-2 border-t border-border px-3 py-3">
          {isPending ? (
            <p className="text-xs text-text-muted">Awaiting response...</p>
          ) : (
            <>
              {request.questions?.map(question => {
                const answer = findAnswer(response?.answers, question.id);
                return (
                  <div
                    key={question.id}
                    className="rounded-md border border-border bg-bg-secondary/20 px-2.5 py-2"
                  >
                    <p className="text-xs font-medium text-text-primary">
                      {question.question}
                    </p>
                    <p
                      className={
                        'mt-1 text-xs ' +
                        (answer?.skipped
                          ? 'text-status-paused'
                          : 'text-text-secondary')
                      }
                    >
                      {formatQuestionAnswer(answer)}
                    </p>
                  </div>
                );
              })}
              {isSkipped && response?.skip_reason && (
                <p className="text-xs text-status-paused">
                  Skip reason: {response.skip_reason}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </article>
  );
}
