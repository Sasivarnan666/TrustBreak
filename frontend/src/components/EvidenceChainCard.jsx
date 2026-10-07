import { CATEGORY_LABELS } from "../lib/riskSignals.js";
import { recommendedActionMeta } from "../lib/risk.js";
import { Card } from "./ui.jsx";
import { RiskBadge } from "./StatusBadge.jsx";

const STATUS = { anomalous: "text-red-800", normal: "text-emerald-800", not_evaluated: "text-slate-500" };

function Stage({ label, children, tone = "slate" }) {
  const tones = { slate: "border-slate-200 bg-white", red: "border-red-200 bg-red-50/40", navy: "border-slate-300 bg-slate-50" };
  return (
    <div className={`rounded-md border px-4 py-3 ${tones[tone]}`}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <div className="mt-1.5 text-sm text-slate-900">{children}</div>
    </div>
  );
}

const Arrow = () => (
  <div className="flex justify-center py-1 text-slate-400" aria-hidden="true">
    <svg width="14" height="18" viewBox="0 0 14 18" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M7 1v14M2 10l5 5 5-5" /></svg>
  </div>
);

/** The "why did trust break?" chain, built from the existing evidence-graph response and the stored assessment. */
export default function EvidenceChainCard({ graph, assessment }) {
  const rows = graph?.comparison ?? [];
  const identity = graph?.identity;
  const broken = rows.filter((r) => r.status === "anomalous");
  const categories = Object.entries(assessment?.category_points ?? {}).filter(([, p]) => p > 0);
  const action = recommendedActionMeta(assessment?.recommended_action);
  return (
    <Card title="Why did trust break?" aside={<span className="text-xs text-slate-500">Evidence correlation</span>}>
      <div data-testid="evidence-chain">
        <Stage label="Trusted identity">
          {identity ? (
            <p><span className="font-semibold">{identity.display_name}</span> <span className="font-mono text-xs text-slate-600">{identity.identity_id}</span> · {identity.role}, {identity.organization}</p>
          ) : (
            <p className="text-slate-700">No trusted identity is linked to this sender, so no baseline exists to compare against.</p>
          )}
        </Stage>
        <Arrow />
        <Stage label="Expected (synthetic baseline)">
          <ul className="space-y-0.5">
            {rows.map((r) => (
              <li key={r.aspect}><span className="inline-block w-24 text-slate-500">{r.aspect[0].toUpperCase() + r.aspect.slice(1)}</span>{r.expected}</li>
            ))}
          </ul>
        </Stage>
        <Arrow />
        <Stage label="Observed">
          <ul className="space-y-0.5">
            {rows.map((r) => (
              <li key={r.aspect}>
                <span className="inline-block w-24 text-slate-500">{r.aspect[0].toUpperCase() + r.aspect.slice(1)}</span>
                <span className={`font-semibold ${STATUS[r.status]}`}>{r.observed}</span>
                {r.detail && <span className="text-xs text-slate-500"> ({r.detail})</span>}
              </li>
            ))}
          </ul>
        </Stage>
        <Arrow />
        <Stage label="Broken trust assumptions" tone={broken.length || categories.length ? "red" : "slate"}>
          {assessment ? (
            categories.length > 0 && assessment.risk_level !== "LOW" ? (
              <ul className="flex flex-wrap gap-1.5">
                {categories.map(([k, p]) => (
                  <li key={k} className="rounded bg-white px-2 py-0.5 text-xs font-semibold text-red-900 ring-1 ring-inset ring-red-600/25">
                    {CATEGORY_LABELS[k] ?? k} +{p}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-slate-700">No trust assumptions were broken by scored evidence.</p>
            )
          ) : (
            <p className="text-slate-700">Run the risk assessment to correlate the evidence.</p>
          )}
        </Stage>
        <Arrow />
        <Stage label="Risk correlation" tone="navy">
          {assessment ? (
            <p>
              {categories.length} independent signal group{categories.length === 1 ? "" : "s"} · {assessment.signals.length} scored signal{assessment.signals.length === 1 ? "" : "s"} · prototype heuristic score{" "}
              <span className="font-semibold tabular-nums">{assessment.risk_score}</span> ({assessment.raw_points} raw points)
            </p>
          ) : (
            <p className="text-slate-700">Not assessed</p>
          )}
        </Stage>
        <Arrow />
        <div className="grid gap-2 sm:grid-cols-2">
          <Stage label="Risk level">{assessment ? <RiskBadge level={assessment.risk_level} size="lg" /> : "—"}</Stage>
          <Stage label="Recommended action (decision support)">
            <p className="font-semibold">{assessment ? action?.label ?? assessment.recommended_action_label : "—"}</p>
          </Stage>
        </div>
      </div>
    </Card>
  );
}
