import { api } from "../api/client.js";
import { useAsync } from "../hooks/useAsync.js";
import { RiskBadge } from "./StatusBadge.jsx";
import { ErrorState, LoadingState } from "./States.jsx";
import { Card } from "./ui.jsx";

const sign = (n) => (n > 0 ? `+${n}` : n < 0 ? `−${Math.abs(n)}` : "0");

function Row({ c, maxRaw }) {
  const width = maxRaw > 0 ? Math.round((Math.abs(c.raw_delta) / maxRaw) * 100) : 0;
  const scoreMoved = c.score_delta !== 0;
  return (
    <li className="py-3" data-testid={`cf-${c.id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-sm font-semibold text-slate-900">{c.label}</p>
        <p className="font-mono text-sm tabular-nums text-slate-900">
          {c.original_score} → {c.new_score}{" "}
          <span className={scoreMoved ? "font-semibold text-emerald-700" : "text-slate-500"}>
            {scoreMoved ? `${sign(c.score_delta)} points` : "score unchanged"}
          </span>
        </p>
      </div>
      <div className="mt-1.5 flex items-center gap-3">
        <div className="h-1.5 flex-1 rounded-full bg-slate-100" aria-hidden="true">
          <div className="h-1.5 rounded-full bg-slate-500" style={{ width: `${width}%` }} />
        </div>
        <p className="w-44 shrink-0 text-right text-xs tabular-nums text-slate-600">
          raw points {c.original_raw_points} → {c.new_raw_points} ({sign(c.raw_delta)})
        </p>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-slate-600">
        {c.explanation}
        {c.level_changed && (
          <span className="ml-1 font-semibold text-slate-800">
            Level: {c.original_level} → {c.new_level}.
          </span>
        )}
      </p>
    </li>
  );
}

/** "What would reduce the risk?" — read-only what-ifs computed by the SAME Risk Engine on the stored assessment. */
export default function CounterfactualCard({ incidentId, assessmentId }) {
  const { data, error, loading, reload } = useAsync((signal) => api.getCounterfactuals(incidentId, signal), [incidentId, assessmentId ?? 0]);
  if (loading) return <LoadingState label="Running counterfactual simulations…" rows={3} />;
  if (error) return <ErrorState error={error} onRetry={reload} title="Counterfactuals could not be loaded" />;
  const cf = data.data;
  const maxRaw = Math.max(0, ...cf.counterfactuals.map((c) => Math.abs(c.raw_delta)));
  return (
    <Card title="What would reduce the risk?" aside={<span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Simulation</span>}>
      {!cf.available ? (
        <p className="text-sm text-slate-700">{cf.reason}</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 pb-3">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Current</span>
            <span className="text-2xl font-semibold tabular-nums text-slate-900">{cf.current.risk_score}</span>
            <RiskBadge level={cf.current.risk_level} />
            <span className="text-xs text-slate-500">
              {cf.current.raw_points > cf.current.risk_score && `raw points ${cf.current.raw_points}, displayed score capped at 100`}
            </span>
          </div>
          {cf.counterfactuals.length === 0 ? (
            <p className="mt-3 text-sm text-slate-700">No scored evidence could be removed: nothing in this assessment drives the risk.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {cf.counterfactuals.map((c) => (
                <Row key={c.id} c={c} maxRaw={maxRaw} />
              ))}
            </ul>
          )}
          {cf.largest_reduction && (
            <p className="mt-2 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-800" data-testid="cf-largest">
              <span className="font-semibold">Largest risk reduction: </span>
              {cf.largest_reduction.label} (raw points {sign(cf.largest_reduction.raw_delta)}, score {sign(cf.largest_reduction.score_delta)}).
            </p>
          )}
          {cf.smallest_downgrade && (
            <p className="mt-2 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-800" data-testid="cf-downgrade">
              <span className="font-semibold">Smallest change that lowers the level: </span>
              {cf.smallest_downgrade.labels.join(" + ")} → {cf.smallest_downgrade.new_score} {cf.smallest_downgrade.new_level}.
            </p>
          )}
          {cf.notes.map((n) => (
            <p key={n} className="mt-2 text-xs text-slate-500">{n}</p>
          ))}
        </>
      )}
      <p className="mt-3 border-t border-slate-100 pt-3 text-xs italic leading-relaxed text-slate-500">{cf.disclaimer} These are analytical simulations, not historical facts.</p>
    </Card>
  );
}
