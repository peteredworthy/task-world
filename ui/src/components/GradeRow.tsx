import { GradeBadge } from './GradeBadge';

interface GradeRowProps {
  grades: {
    required: string[];
    expected: string[];
    optional: string[];
  };
}

function GradeSection({ label, grades }: { label: string; grades: string[] }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted mr-1">
        {label}
      </span>
      {grades.length === 0 ? (
        <GradeBadge grade="-" tooltip={`No ${label.toLowerCase()} grades`} />
      ) : (
        grades.map((grade, i) => (
          <GradeBadge
            key={`${label}-${i}`}
            grade={grade}
            tooltip={`${label} requirement ${i + 1}`}
          />
        ))
      )}
    </div>
  );
}

export function GradeRow({ grades }: GradeRowProps) {
  return (
    <div
      className="flex items-center gap-0"
      role="group"
      aria-label="Grade summary"
    >
      <GradeSection label="Required" grades={grades.required} />
      <div className="mx-3 h-5 w-px bg-border" aria-hidden="true" />
      <GradeSection label="Expected" grades={grades.expected} />
      <div className="mx-3 h-5 w-px bg-border" aria-hidden="true" />
      <GradeSection label="Optional" grades={grades.optional} />
    </div>
  );
}
