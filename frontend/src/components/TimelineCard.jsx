import { api } from "../api/client.js";
import { useAsync } from "../hooks/useAsync.js";
import { formatClock, formatDay } from "../lib/format.js";
import { ErrorState, LoadingState } from "./States.jsx";
import { Card } from "./ui.jsx";

/** Forensic timeline: only persisted events; an event without a timestamp is shown without one. */
export default function TimelineCard({ incidentId, refreshKey = 0 }) {
  const { data, error, loading, reload } = useAsync((signal) => api.getTimeline(incidentId, signal), [incidentId, refreshKey]);
  if (loading && !data) return <LoadingState label="Loading timeline…" rows={4} />;
  if (error) return <ErrorState error={error} onRetry={reload} title="Timeline could not be loaded" />;
  const t = data.data;
  let lastDay = null;
  return (
    <Card title="Forensic timeline" aside={<span className="text-xs text-slate-500">{t.events.length} events</span>}>
      <ol className="relative space-y-0" data-testid="timeline">
        {t.events.map((e) => {
          const day = formatDay(e.timestamp);
          const showDay = day && day !== lastDay;
          if (day) lastDay = day;
          return (
            <li key={e.seq} className="grid grid-cols-[5.5rem_1fr] gap-4 border-l border-slate-200 py-2 pl-4">
              <div>
                {showDay && <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{day}</p>}
                <p className="font-mono text-xs tabular-nums text-slate-700">{formatClock(e.timestamp) ?? "—"}</p>
                {!e.timestamp && <p className="text-[10px] text-slate-400">no timestamp</p>}
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold uppercase tracking-wide text-slate-900">{e.event}</p>
                <p className="text-xs text-slate-500">{e.source}</p>
                <p className="mt-0.5 text-sm leading-relaxed text-slate-700">{e.explanation}</p>
              </div>
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-xs text-slate-500">{t.note}</p>
    </Card>
  );
}
