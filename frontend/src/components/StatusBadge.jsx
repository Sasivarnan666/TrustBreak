import { caseStatusMeta } from "../lib/caseWorkflow.js";
import { riskLevelMeta } from "../lib/risk.js";

const TONES = {
  red: { badge: "bg-red-50 text-red-900 ring-red-600/30", dot: "bg-red-600" },
  orange: { badge: "bg-orange-50 text-orange-900 ring-orange-600/30", dot: "bg-orange-500" },
  amber: { badge: "bg-amber-50 text-amber-900 ring-amber-600/25", dot: "bg-amber-500" },
  emerald: { badge: "bg-emerald-50 text-emerald-900 ring-emerald-600/25", dot: "bg-emerald-500" },
  slate: { badge: "bg-slate-100 text-slate-700 ring-slate-500/20", dot: "bg-slate-400" },
};

/** The incident's persisted risk level, or a neutral "Not assessed" when no assessment exists. */
export function RiskBadge({ level, size = "sm" }) {
  const meta = riskLevelMeta(level);
  const tone = TONES[meta.tone] ?? TONES.slate;
  const sizing = size === "lg" ? "px-3 py-1.5 text-sm" : "px-2 py-0.5 text-xs";
  return (
    <span
      data-testid="risk-badge"
      className={`inline-flex items-center gap-1.5 rounded-md font-semibold ring-1 ring-inset ${sizing} ${tone.badge}`}
    >
      <span className={`size-1.5 rounded-full ${tone.dot}`} aria-hidden="true" />
      {meta.label}
    </span>
  );
}

const CASE_TONES = {
  sky: "bg-sky-50 text-sky-900 ring-sky-600/30",
  teal: "bg-teal-50 text-teal-900 ring-teal-600/30",
  violet: "bg-violet-50 text-violet-900 ring-violet-600/30",
  slate: "bg-slate-100 text-slate-700 ring-slate-500/20",
};

/** The human case workflow status. Pill-shaped with a "Case" prefix so it never reads as a risk level. */
export function CaseBadge({ status, size = "sm" }) {
  const meta = caseStatusMeta(status);
  const sizing = size === "lg" ? "px-3 py-1.5 text-sm" : "px-2 py-0.5 text-xs";
  return (
    <span
      data-testid="case-badge"
      title={meta.meaning}
      className={`inline-flex items-center gap-1 rounded-full font-semibold ring-1 ring-inset ${sizing} ${CASE_TONES[meta.tone] ?? CASE_TONES.slate}`}
    >
      <span className="font-medium opacity-70">Case</span>
      <span aria-hidden="true">·</span>
      {meta.label}
    </span>
  );
}

/** Small neutral tag, e.g. "New" beneficiary or "Known" sender. */
export function Tag({ children, tone = "slate" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-600 ring-slate-500/15",
    brand: "bg-brand-50 text-brand-700 ring-brand-600/20",
    amber: "bg-amber-50 text-amber-800 ring-amber-600/25",
  };
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${tones[tone]}`}>
      {children}
    </span>
  );
}
