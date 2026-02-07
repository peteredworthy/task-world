interface PendingActionsBadgeProps {
  count: number;
}

export function PendingActionsBadge({ count }: PendingActionsBadgeProps) {
  if (count === 0) return null;

  return (
    <span className="inline-flex items-center rounded-full bg-yellow-100 px-2.5 py-0.5 text-xs font-medium text-yellow-800">
      {count} pending
    </span>
  );
}
