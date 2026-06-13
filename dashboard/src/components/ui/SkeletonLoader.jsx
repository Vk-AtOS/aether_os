export function Skeleton({ className = '' }) {
  return <div className={`animate-pulse bg-white/[0.04] rounded-lg ${className}`} />;
}

export function SkeletonCard() {
  return (
    <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-6 space-y-3">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-8 w-16" />
      <Skeleton className="h-3 w-32" />
    </div>
  );
}
