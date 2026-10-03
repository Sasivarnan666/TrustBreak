/** Loading / error / empty states shared by every data-driven page. */

export function LoadingState({ label = "Loading…", rows = 4 }) {
  return (
    <div role="status" aria-live="polite" className="rounded-lg border border-slate-200 bg-white p-5">
      <span className="sr-only">{label}</span>
      <div className="animate-pulse space-y-3" aria-hidden="true">
        <div className="h-4 w-1/4 rounded bg-slate-200" />
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="h-9 rounded bg-slate-100" />
        ))}
      </div>
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "Something went wrong" }) {
  const message = error?.message || "An unexpected error occurred.";
  return (
    <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-5">
      <h2 className="text-sm font-semibold text-red-900">{title}</h2>
      <p className="mt-1 text-sm text-red-800">{message}</p>
      {error?.code && <p className="mt-2 font-mono text-xs text-red-700/80">code: {error.code}</p>}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-semibold text-red-800 hover:bg-red-100"
        >
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, description, action }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
      <svg className="mx-auto size-9 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 3 4.5 6v5.5c0 4.4 3.1 7.6 7.5 9.5 4.4-1.9 7.5-5.1 7.5-9.5V6L12 3Z" />
      </svg>
      <h2 className="mt-3 text-sm font-semibold text-slate-900">{title}</h2>
      {description && <p className="mx-auto mt-1 max-w-sm text-sm text-slate-600">{description}</p>}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}
