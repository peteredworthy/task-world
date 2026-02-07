import { gradeColor } from '../lib/status';
import type { GradeSummaryItem } from '../types';

const PRIORITY_ORDER: Record<string, number> = {
  critical: 0,
  expected: 1,
  nice: 2,
};

interface CompactGradeRowProps {
  grades: GradeSummaryItem[];
}

export function CompactGradeRow({ grades }: CompactGradeRowProps) {
  if (grades.length === 0) return null;

  const sorted = [...grades].sort(
    (a, b) => (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9)
  );

  return (
    <div className="flex items-center gap-0.5">
      {sorted.map((item, i) => {
        const letter = item.grade ?? '-';
        const colorClass = item.grade ? gradeColor(item.grade) : 'bg-bg-elevated text-text-muted';

        return (
          <span
            key={i}
            className={
              'inline-flex w-5 h-5 items-center justify-center rounded text-[9px] font-bold ' +
              colorClass
            }
            title={item.priority}
          >
            {letter}
          </span>
        );
      })}
    </div>
  );
}
