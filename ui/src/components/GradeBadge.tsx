import { gradeColor } from '../lib/status';

interface GradeBadgeProps {
  grade: string;
  tooltip?: string;
}

export function GradeBadge({ grade, tooltip }: GradeBadgeProps) {
  if (!grade || grade === '-') {
    return (
      <span
        className="inline-flex w-10 h-8 items-center justify-center rounded-md bg-bg-elevated text-text-muted text-[11px] font-semibold"
        title={tooltip}
      >
        -
      </span>
    );
  }

  return (
    <span
      className={'inline-flex w-10 h-8 items-center justify-center rounded-md text-sm font-bold ' + gradeColor(grade)}
      title={tooltip}
    >
      {grade}
    </span>
  );
}
