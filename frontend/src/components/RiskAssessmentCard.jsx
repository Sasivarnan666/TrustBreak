import { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { Tag } from "./StatusBadge.jsx";
import { Button, Card } from "./ui.jsx";
import { formatDateTime } from "../lib/format.js";
import { SOURCE_LABELS, SOURCE_TONE, confidenceLabel, groupSignalsByCategory } from "../lib/riskSignals.js";

const SEVERITY = {
  high: { icon: "🔴", cls: "border-red-200 bg-red-50 text-red-900" },
  medium: { icon: "🟠", cls: "border-amber-300 bg-amber-50 text-amber-900" },
  low: { icon: "🟡", cls: "border-slate-200 bg-slate-50 text-slate-800" },
};

const LEVEL = {
  LOW: { cls: "border-emerald-300 bg-emerald-50 text-emerald-900", bar: "bg-emerald-500" },
  MEDIUM: { cls: "border-amber-300 bg-amber-50 text-amber-900", bar: "bg-amber-500" },
  HIGH: { cls: "border-orange-300 bg-orange-50 text-orange-900", bar: "bg-orange-500" },
  CRITICAL: { cls: "border-red-300 bg-red-50 text-red-900", bar: "bg-red-600" },
};

const ACTION = {
  PROCEED: { icon: "🟢", cls: "border-emerald-300 bg-emerald-50", title: "PROCEED" },
  VERIFY: { icon: "🟠", cls: "border-amber-300 bg-amber-50", title: "VERIFY" },
  HOLD_PAYMENT: { icon: "🔴", cls: "border-red-300 bg-red-50", title: "HOLD PAYMENT" },
};

const INPUT_LABELS = { message: "Message", behaviour: "Behaviour", attachment: "Attachment" };
const INPUT_STATUS = {
  used: "Used",
  not_provided: "Not provided",
  not_evaluated: "Not evaluated",
  unavailable: "Unavailable",
};

function Stat({ label, children }) {
  return (
    <div className="px-5 py-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <div className="mt-1.5 text-xl font-semibold tracking-tight text-slate-900">{children}</div>
    </div>
  );
}

/** One scored signal: WHAT happened, WHY it matters, WHERE the evidence came from, HOW confident it is. */
function SignalRow({ s }) {
  const sev = SEVERITY[s.severity] ?? SEVERITY.low;
  const related = s.related_signal_codes ?? [];
  const confidence = confidenceLabel(s.confidence);
  return (
    <li className={`rounded-md border px-3 py-2.5 text-sm ${sev.cls}`} data-testid={`signal-${s.code}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold uppercase tracking-wide">
          {sev.icon} {s.title}
        </p>
        <span className="flex items-center gap-1.5">
          <Tag tone={SOURCE_TONE[s.source]}>{SOURCE_LABELS[s.source] ?? s.source}</Tag>
          <span className="rounded-full bg-white/70 px-2 py-0.5 text-xs font-semibold tabular-nums">+{s.points}</span>
        </span>
      </div>
      <p className="mt-1 text-[13px] leading-relaxed">{s.message}</p>
      {s.why && (
        <p className="mt-1 text-[12px] leading-relaxed text-slate-700">
          <span className="font-semibold text-slate-600">Why it matters: </span>
          {s.why}
        </p>
      )}
      {s.evidence && s.evidence !== s.message && (
        <p className="mt-1.5 border-l-2 border-current/30 pl-2 text-[13px] italic leading-relaxed text-slate-800">
          <span className="not-italic font-semibold text-slate-600">Evidence: </span>
          {s.evidence}
        </p>
      )}
      {s.details?.length > 0 && <p className="mt-1 font-mono text-xs text-slate-700">{s.details.join(", ")}</p>}
      <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-600">
        <span>Severity: {s.severity}</span>
        <span>{confidence ? `Confidence: ${s.confidence}` : "Deterministic comparison"}</span>
        {s.capped && s.base_points != null && <span>Category cap applied (+{s.base_points} before cap)</span>}
        {related.length > 0 && (
          <span title="Overlapping indicators describing the same evidence. They are listed, not scored again.">
            Same evidence, counted once: {related.join(", ")}
          </span>
        )}
        {(s.corroborating_sources ?? []).length > 0 && (
          <span>Also reported by: {s.corroborating_sources.map((x) => SOURCE_LABELS[x] ?? x).join(", ")}</span>
        )}
      </p>
    </li>
  );
}

/** Pure view of one risk-correlation result (no fetching). */
export function RiskAssessmentView({ assessment }) {
  const level = LEVEL[assessment.risk_level] ?? LEVEL.MEDIUM;
  const action = ACTION[assessment.recommended_action] ?? ACTION.VERIFY;
  const signals = assessment.signals ?? [];
  const inputs = assessment.inputs ?? {};
  const notes = assessment.notes ?? [];
  const pct = Math.max(0, Math.min(100, (assessment.risk_score / (assessment.max_score || 100)) * 100));

  return (
    <div>
      {assessment.assessed_at && (
        <p className="mb-3 text-xs text-slate-500" data-testid="assessed-at">
          {assessment.version_number ? <strong className="font-semibold text-slate-700">Assessment v{assessment.version_number}</strong> : "Assessment"}{" "}
          · assessed {formatDateTime(assessment.assessed_at)} · engine {assessment.engine_version ?? assessment.assessment_version}
          {assessment.is_latest === false ? " · superseded by a newer assessment" : " · saved with this incident"}
        </p>
      )}
      <div className={`rounded-lg border px-4 py-3 ${level.cls}`}>
        <p className="text-sm font-bold uppercase tracking-[0.1em]">
          {assessment.trust_break_detected ? "🔴 " : ""}
          {assessment.headline}
        </p>
        <p className="mt-1 text-[13px] leading-relaxed">{assessment.explanation}</p>
      </div>

      <div className="mt-4 grid divide-y divide-slate-200 rounded-lg border border-slate-200 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <Stat label="Prototype heuristic risk score">
          <span className="tabular-nums" data-testid="risk-score">
            {assessment.risk_score}
          </span>
          <span className="text-sm font-medium text-slate-500"> / {assessment.max_score} risk points</span>
          <div className="mt-2 h-1.5 w-full rounded-full bg-slate-100" aria-hidden="true">
            <div className={`h-1.5 rounded-full ${level.bar}`} style={{ width: `${pct}%` }} />
          </div>
          {assessment.raw_points > assessment.max_score && (
            <p className="mt-1.5 text-xs font-normal text-slate-500">
              {assessment.raw_points} raw points; displayed score capped at {assessment.max_score}
            </p>
          )}
          <p className="mt-1.5 text-xs font-normal text-slate-500">Score is not a probability of fraud.</p>
        </Stat>
        <Stat label="Risk level">
          <span data-testid="risk-level">{assessment.risk_level}</span>
        </Stat>
        <Stat label="Recommended action">
          <span data-testid="recommended-action">{action.icon} {action.title}</span>
        </Stat>
      </div>

      <h3 className="mb-2 mt-5 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Why this was flagged: evidence by category</h3>
      {signals.length === 0 ? (
        <p className="text-sm text-slate-600">No risk indicators were found in the evidence that was used.</p>
      ) : (
        <div className="space-y-4">
          {groupSignalsByCategory(signals).map((g) => (
            <section key={g.key} aria-label={g.label} data-testid={`category-${g.key}`}>
              <p className="mb-1.5 flex items-center justify-between text-xs font-semibold uppercase tracking-[0.1em] text-slate-600">
                <span>{g.label}</span>
                <span className="tabular-nums text-slate-500">+{g.points}</span>
              </p>
              <ul className="space-y-2">
                {g.signals.map((sig) => (
                  <SignalRow key={sig.code} s={sig} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      <section className={`mt-5 rounded-lg border border-l-4 p-4 ${action.cls}`} aria-label="Recommended action">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-600">Recommended action</h3>
        <p className="mt-1.5 text-base font-bold text-slate-900">
          {action.icon} {action.title}
        </p>
        <p className="mt-1 text-sm leading-relaxed text-slate-800">{assessment.recommended_action_guidance}</p>
        <p className="mt-2 text-xs text-slate-600">
          The risk assessment is TrustBreak’s deterministic heuristic; the recommended action is decision support for a
          person. It does not confirm fraud, and no payment is blocked or executed.
        </p>
      </section>

      <div className="mt-4 flex flex-wrap gap-2">
        {Object.entries(inputs).map(([name, i]) => (
          <span key={name} title={i.detail}>
            <Tag tone={i.status === "used" && i.analysis_state !== "fallback" ? "brand" : "amber"}>
              {INPUT_LABELS[name] ?? name}: {INPUT_STATUS[i.status] ?? i.status}
              {name === "message" && i.status === "used" && i.analysis_state === "fallback" && " · fallback, not AI"}
              {name === "message" && i.status === "used" && i.analysis_state === "ai" && " · AI-extracted"}
            </Tag>
          </span>
        ))}
      </div>
      {notes.length > 0 && (
        <ul className="mt-3 list-disc space-y-0.5 pl-5 text-xs text-slate-500">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}

      <p className="mt-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
        Risk assessment is deterministic prototype decision support. It is not proof of fraud and the score is not a
        probability. Weights and thresholds (LOW 0–19, MEDIUM 20–39, HIGH 40–69, CRITICAL 70+) are uncalibrated
        prototype values; AI may extract evidence but never scores, grades or recommends.
      </p>
    </div>
  );
}

/** Card: shows the persisted assessment (if any) and runs/re-runs the correlation on demand.
 *  Optionally includes the attachment file chosen in Attachment Analysis (never stored by the server). */
export default function RiskAssessmentCard({
  incidentId,
  attachmentFile = null,
  hasAttachment = false,
  assessment = null,
  onAssessed = () => {},
}) {
  const [state, setState] = useState({ status: "idle", unsaved: null, error: null });
  const controller = useRef(null);

  useEffect(() => () => controller.current?.abort(), []);

  async function run() {
    controller.current?.abort();
    controller.current = new AbortController();
    setState((prev) => ({ ...prev, status: "loading", error: null }));
    try {
      const res = await api.analyzeRisk(incidentId, attachmentFile, controller.current.signal);
      if (res.data.persisted === false) {
        // Incomplete evidence: shown, but not saved and not the incident's status.
        setState({ status: "done", unsaved: res.data, error: null });
      } else {
        onAssessed(res.data);
        setState({ status: "done", unsaved: null, error: null });
      }
    } catch (error) {
      if (error?.name === "AbortError") return;
      // Keep showing the stored assessment; just report the failure.
      setState((prev) => ({ ...prev, status: "error", error }));
    }
  }

  const busy = state.status === "loading";
  const shown = state.unsaved ?? assessment;
  return (
    <Card
      title="TrustBreak Risk Assessment"
      aside={
        <Button onClick={run} disabled={busy}>
          {busy ? "Assessing…" : assessment ? "Run again" : "Run risk assessment"}
        </Button>
      }
    >
      {!assessment && !state.unsaved && (
        <div data-testid="not-assessed">
          <p className="text-base font-semibold text-slate-800">Not assessed</p>
          <p className="mt-1 text-sm leading-relaxed text-slate-600">
            This incident has not yet received a TrustBreak risk assessment. Running it correlates the message, behaviour
            and attachment evidence into one explainable result and saves it with the incident. Deterministic rules only; no
            AI decides the score.
          </p>
        </div>
      )}
      {hasAttachment && (
        <p className="mt-2 text-xs text-slate-500" data-testid="risk-attachment-hint">
          {attachmentFile ? (
            <>
              Attachment evidence will use <span className="font-mono">{attachmentFile.name}</span> (analyzed in memory, never
              stored).
            </>
          ) : (
            "No attachment file selected: choose it in Attachment Analysis below to include attachment evidence."
          )}
        </p>
      )}
      {busy && (
        <p role="status" className="mt-3 text-sm text-slate-600">
          Correlating evidence…
        </p>
      )}
      {state.status === "error" && (
        <div role="alert" className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {state.error?.message || "The risk assessment could not be produced."}
          {state.error?.code && <span className="ml-2 font-mono text-xs text-red-700/80">code: {state.error.code}</span>}
          {assessment && <p className="mt-1 text-xs">The previously saved assessment is unchanged.</p>}
        </div>
      )}
      {state.unsaved && (
        <div role="alert" className="mt-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          This result was <strong>not saved</strong> because some evidence was unavailable.
          {assessment ? " The earlier saved assessment is unchanged and still the incident’s status." : ""}
        </div>
      )}
      {shown && (
        <div className="mt-3">
          <RiskAssessmentView assessment={shown} />
        </div>
      )}
    </Card>
  );
}
