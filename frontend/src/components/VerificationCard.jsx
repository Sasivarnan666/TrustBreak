import { useState } from "react";
import { api } from "../api/client.js";
import { useAsync } from "../hooks/useAsync.js";
import { formatDateTime } from "../lib/format.js";
import { ErrorState, LoadingState } from "./States.jsx";
import { Button, Card } from "./ui.jsx";

const STATE_STYLE = {
  NOT_STARTED: "bg-slate-100 text-slate-700 ring-slate-500/20",
  IN_PROGRESS: "bg-sky-50 text-sky-900 ring-sky-600/30",
  CONFIRMED: "bg-emerald-50 text-emerald-900 ring-emerald-600/25",
  FAILED: "bg-amber-50 text-amber-900 ring-amber-600/30",
};
const STATE_TEXT = { NOT_STARTED: "NOT STARTED", IN_PROGRESS: "IN PROGRESS", CONFIRMED: "CONFIRMED", FAILED: "FAILED" };
const ACTION_BUTTON = {
  START: { label: "Start verification", variant: "primary" },
  CONFIRM: { label: "Record: confirmed", variant: "secondary" },
  FAIL: { label: "Record: could not confirm", variant: "secondary" },
};

/** Independent verification. Separate from the system assessment and from the final case decision. */
export default function VerificationCard({ incidentId, assessmentId, onChanged }) {
  const { data, error, loading, reload } = useAsync((signal) => api.getVerification(incidentId, signal), [incidentId, assessmentId ?? 0]);
  const [method, setMethod] = useState("");
  const [reason, setReason] = useState("");
  const [analyst, setAnalyst] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);

  if (loading && !data) return <LoadingState label="Loading verification…" rows={2} />;
  if (error) return <ErrorState error={error} onRetry={reload} title="Verification could not be loaded" />;
  const v = data.data;

  const submit = async (action) => {
    setProblem(null);
    if (action === "START" && !method) return setProblem("Choose an independent verification method.");
    if (reason.trim().length < 5) return setProblem("Describe what you did or found (at least 5 characters).");
    if (analyst.trim().length < 2) return setProblem("Enter the analyst name.");
    setBusy(true);
    try {
      await api.recordVerification(incidentId, { action, method: action === "START" ? method : undefined, reason: reason.trim(), analyst_name: analyst.trim() });
      setReason("");
      reload();
      onChanged?.();
    } catch (err) {
      setProblem(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title="Independent verification"
      aside={
        <span data-testid="verification-state" className={`rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${STATE_STYLE[v.state]}`}>
          {STATE_TEXT[v.state]}
        </span>
      }
    >
      {!v.applicable ? (
        <p className="text-sm text-slate-700">{v.not_applicable_reason}</p>
      ) : (
        <>
          <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900" data-testid="verification-warning">
            {v.warning}
          </p>
          <h3 className="mt-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Recommended independent methods</h3>
          <ul className="mt-2 grid gap-2 sm:grid-cols-2">
            {v.recommended_methods.map((m) => (
              <li key={m.method} className="rounded-md border border-slate-200 px-3 py-2">
                <p className="text-sm font-semibold text-slate-900">{m.label}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-slate-600">{m.description}</p>
                {m.channels.length > 0 && <p className="mt-1 font-mono text-xs text-slate-700">{m.channels.join(" · ")}</p>}
              </li>
            ))}
          </ul>

          {v.allowed_actions.length > 0 && (
            <div className="mt-4 space-y-3 rounded-md bg-slate-50 p-3">
              {v.allowed_actions.includes("START") && (
                <div>
                  <label htmlFor="vf-method" className="block text-xs font-semibold text-slate-700">Method used</label>
                  <select id="vf-method" value={method} onChange={(e) => setMethod(e.target.value)} className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm sm:max-w-sm">
                    <option value="">Select a method…</option>
                    {v.recommended_methods.map((m) => (
                      <option key={m.method} value={m.method}>{m.label}</option>
                    ))}
                  </select>
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-[1fr_14rem]">
                <div>
                  <label htmlFor="vf-reason" className="block text-xs font-semibold text-slate-700">Note / outcome</label>
                  <textarea id="vf-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm" placeholder="e.g. Called the CEO office on the number in our records" />
                </div>
                <div>
                  <label htmlFor="vf-analyst" className="block text-xs font-semibold text-slate-700">Analyst</label>
                  <input id="vf-analyst" value={analyst} onChange={(e) => setAnalyst(e.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
                </div>
              </div>
              {problem && <p role="alert" className="text-sm text-red-700">{problem}</p>}
              <div className="flex flex-wrap gap-2">
                {v.allowed_actions.map((a) => (
                  <Button key={a} type="button" variant={ACTION_BUTTON[a].variant} disabled={busy} onClick={() => submit(a)}>
                    {ACTION_BUTTON[a].label}
                  </Button>
                ))}
              </div>
            </div>
          )}
          {v.allowed_actions.length === 0 && <p className="mt-3 text-sm text-slate-600">Verification is confirmed. No further verification actions are available.</p>}
          {v.events.length > 0 && (
            <ol className="mt-4 divide-y divide-slate-100 border-t border-slate-200" aria-label="Verification audit trail">
              {v.events.map((e, i) => (
                <li key={i} className="py-2 text-sm">
                  <p className="font-semibold text-slate-900">{e.event_label}{e.method_label && <span className="font-normal text-slate-600"> · {e.method_label}</span>}</p>
                  <p className="text-slate-700">{e.reason}</p>
                  <p className="text-xs text-slate-500">{e.analyst_name} · {formatDateTime(e.created_at)}{e.assessment_number ? ` · while assessment v${e.assessment_number} was current` : ""}</p>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
      <p className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-500">{v.note}</p>
    </Card>
  );
}
