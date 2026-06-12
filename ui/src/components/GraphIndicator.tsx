interface GraphIndicatorProps {
  isGraphBacked: boolean;
  onOpen: () => void;
}

export function GraphIndicator({ isGraphBacked, onOpen }: GraphIndicatorProps) {
  if (!isGraphBacked) {
    return null;
  }

  return (
    <button
      type="button"
      onClick={onOpen}
      className="inline-flex items-center rounded border border-accent-purple/40 bg-accent-purple/10 px-2 py-1 text-xs font-semibold text-accent-purple hover:bg-accent-purple/20 transition-colors"
      aria-label="Open graph projection"
    >
      [Graph]
    </button>
  );
}
