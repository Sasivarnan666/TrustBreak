import { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { RiskAssessmentView } from "./RiskAssessmentCard.jsx";
import { RiskBadge, Tag } from "./StatusBadge.jsx";
import { Card } from "./ui.jsx";
import { formatDateTime } from "../lib/format.js";

/** Case decisions that were based on a given assessment (matched by the server-recorded assessment_id). */
function decisionsFor(caseHistory, assessmentId) {
  return (caseHistory ?? []).filter((c) => c.assessment_id === assessmentId && c.decision !== "CASE_OPENED");
}

/**
 * Assessment History: every risk run is kept as an immutable version (v1, v2, ...). Selecting one loads its stored
 * evidence read-only. Nothing here can change a score or a decision.
 * Props: incidentId; history (summaries, oldest first); caseHistory (audit rows, to mark the decided version).
 */
export default function AssessmentHistoryCard({ incidentId, history, caseHistory }) {
  const [open, setOpen] = useState(null); // version_number
  const [loaded, setLoaded] = useState({}); // version_number -> { status, data, error }
  const controller = useRef(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function toggle(version) {
    if (open === version) return setOpen(null);
    setOpen(version);
    if (loaded[version]?.status === "done") return;
    controller.current?.abort();
    controller.current = new AbortController();
    setLoaded((p) => ({ ...p, [version]: { status: "loading" } }));
    try {
      const res = await api.getAssessment(incidentId, version, controller.current.signal);
      setLoaded((p) => ({ ...p, [version]: { status: "done", data: res.data } }));
    } catch (error) {
      if (error?.name === "AbortError") return;
      setLoaded((p) => ({ ...p, [version]: { status: "error", error } }));
    }
  }

  const rows = history ?? [];
  return (
    <Card
      title="Assessment history"
      aside={<span className="text-xs text-slate-500">{rows.length} {rows.length === 1 ? "version" : "versions"} · immutable</span>}
    >
      {rows.length === 0 ? (
        <p className="text-sm text-slate-600" data-testid="no-history">
          No assessment has been run yet. Each run is kept as its own version; earlier versions are never overwritten.
        </p>
      ) : (
        <ol className="space-y-2" data-testid="assessment-history" aria-label="Assessment history">
          {rows.map((a) => {
            const decided = decisionsFor(caseHistory, a.assessment_id);
            const isOpen = open === a.version_number;
            const slot = loaded[a.version_number];
            return (
              <li key={a.assessment_id} className="rounded-md border border-slate-200" data-testid="assessment-history-entry">
                <button
                  type="button"
                  onClick={() => toggle(a.version_number)}
                  aria-expanded={isOpen}
                  className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-left hover:bg-slate-50"
                >
                  <span className="font-mono text-sm font-semibold text-slate-900">v{a.version_number}</span>
                  <span aria-hidden="true">→</span>
                  <span className="text-sm font-semibold tabular-nums text-slate-900">{a.risk_score}</span>
                  <RiskBadge level={a.risk_level} />
                  <span className="text-xs text-slate-600">{a.recommended_action_label}</span>
                  {a.is_latest && <Tag tone="brand">Current</Tag>}
                  {decided.map((d) => (
                    <Tag key={d.created_at} tone="amber">Decision {d.decision.toLowerCase()} based on this version</Tag>
                  ))}
                  <span className="ml-auto text-xs text-slate-500">{formatDateTime(a.assessed_at)}</span>
                </button>
                {isOpen && (
                  <div className="border-t border-slate-200 px-3 py-3" data-testid="assessment-history-detail">
                    {slot?.status === "loading" && <p role="status" className="text-sm text-slate-600">Loading stored evidence…</p>}
                    {slot?.status === "error" && (
                      <p role="alert" className="text-sm text-red-800">{slot.error?.message || "Could not load this assessment."}</p>
                    )}
                    {slot?.status === "done" && (
                      <>
                        <p className="mb-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                          Read-only snapshot of assessment v{a.version_number}, exactly as it was stored
                          {a.is_latest ? "." : "; a newer assessment now represents this incident."}
                        </p>
                        <RiskAssessmentView assessment={slot.data} />
                      </>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
