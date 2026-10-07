import { Tag } from "./StatusBadge.jsx";

const LABELS = {
  urgency_pressure: "Urgency Pressure",
  secrecy_pressure: "Secrecy Pressure",
  verification_suppression: "Verification Suppression",
  authority_pressure: "Authority Pressure",
  payment_pressure: "Payment Pressure",
  deadline_pressure: "Deadline Pressure",
  isolation_request: "Isolation Request",
  fear_or_threat: "Fear or Threat",
  credential_pressure: "Credential Pressure",
  impersonation_cue: "Impersonation Cue",
  unusual_instruction: "Unusual Instruction",
};
const ORDER = Object.keys(LABELS);
const LEVEL = {
  high: "border-red-200 bg-red-50 text-red-900",
  medium: "border-amber-300 bg-amber-50 text-amber-900",
  low: "border-slate-200 bg-slate-50 text-slate-800",
};
const SOURCE_LABEL = { AI: "AI-derived", rule: "Rule-derived", fallback: "Fallback-derived (rules, AI unavailable)" };

/** Pure view of `social_engineering` from a message-analysis result. Evidence only: no score, no verdict. */
export default function SocialEngineeringIndicators({ data }) {
  if (!data) return null;
  const byName = Object.fromEntries(data.signals.map((s) => [s.signal, s]));
  const detected = ORDER.map((n) => byName[n]).filter((s) => s?.detected);
  const quiet = ORDER.filter((n) => byName[n] && !byName[n].detected);

  return (
    <section className="mt-4 rounded-lg border border-slate-200 p-3" aria-label="Social engineering indicators">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Social engineering indicators</h3>
        <Tag>Evidence only · not a score</Tag>
        {data.ai_contributed && <Tag tone="brand">AI-derived items present</Tag>}
        {data.rule_source_label === "fallback" && <Tag tone="amber">Fallback rules — AI unavailable</Tag>}
      </div>

      {detected.length === 0 ? (
        <p className="text-sm text-slate-600">No social-engineering indicators were found in this message.</p>
      ) : (
        <ul className="space-y-1.5">
          {detected.map((s) => (
            <li key={s.signal} className={`rounded-md border px-3 py-1.5 text-sm ${LEVEL[s.confidence] ?? LEVEL.low}`}>
              <details>
                <summary className="flex cursor-pointer items-center justify-between gap-2 font-semibold">
                  <span>{LABELS[s.signal]}</span>
                  <span className="text-[11px] font-bold uppercase tracking-wide">{s.confidence}</span>
                </summary>
                <p className="mt-1.5 text-[13px] leading-relaxed">
                  <span className="opacity-70">Evidence: </span>“{s.evidence}”
                </p>
                <p className="mt-1 text-[11px] opacity-70">
                  {s.sources.map((x) => SOURCE_LABEL[x] ?? x).join(" + ")} · confidence {s.confidence}
                </p>
              </details>
            </li>
          ))}
        </ul>
      )}

      {quiet.length > 0 && (
        <p className="mt-2 text-xs text-slate-500">Not detected: {quiet.map((n) => LABELS[n]).join(", ")}.</p>
      )}
      <p className="mt-2 text-xs leading-relaxed text-slate-500">
        Confidence is how clearly the wording matches the indicator. Rule and fallback items come from fixed patterns without
        semantic understanding. Risk is scored separately by the deterministic engine.
      </p>
    </section>
  );
}
