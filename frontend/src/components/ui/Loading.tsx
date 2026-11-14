/** Skeleton rows in `field`, shaped like the list they stand in for. */
export function Loading({ label, rows = 4 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-label={label} className="rounded-card border border-line bg-surface">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          aria-hidden="true"
          className="flex flex-col gap-2 border-b border-line-soft px-6 py-5 last:border-b-0"
        >
          <div className="h-4 w-1/2 rounded bg-field motion-safe:animate-pulse" />
          <div className="h-3 w-1/3 rounded bg-field motion-safe:animate-pulse" />
        </div>
      ))}
    </div>
  );
}
