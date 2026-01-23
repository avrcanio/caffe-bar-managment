type EmptyStateProps = {
  message: string;
  className?: string;
};

export default function EmptyState({
  message,
  className = "",
}: EmptyStateProps) {
  return (
    <div
      className={`rounded-2xl border border-black/10 bg-white/70 px-4 py-4 text-sm text-black/60 ${className}`}
    >
      {message}
    </div>
  );
}
