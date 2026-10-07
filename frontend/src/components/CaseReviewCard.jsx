import { useState } from "react";
import { api } from "../api/client.js";
import { CaseBadge, RiskBadge } from "./StatusBadge.jsx";
import { Button, Card } from "./ui.jsx";
import {
  ANALYST_MAX,
  REASON_MAX,
  REASON_MIN,
  caseEventTitle,
  caseStatusMeta,
  validateDecision,
} from "../lib/caseWorkflow.js";
import { formatDateTime } from "../lib/format.js";
import { recommendedActionMeta } from "../lib/risk.js";

const DOT = { OPEN: "bg-sky-500", VERIFIED: "bg-teal-600", REJECTED: "bg-violet-600" };

/** Chronological audit trail, oldest first. Entries are read-only: history is never edited. */
export function CaseTimeline({ history }) {
  return (
    <ol className="relative space-y-5 border-l border-slate-200 pl-6" data-testid="case-history" aria-label="Case history">
      {history.map((entry, index) => (
        <li key={`${entry.created_at}-${index}`} className="relative" data-testid="case-history-entry">
          <span
            className={`absolute -left-[1.9rem] top-1 size-3 rounded-full ring-4 ring-white ${DOT[entry.new_status] ?? "bg-slate-400"}`}
            aria-hidden="true"
          />
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-700">{caseEventTitle(entry)}</p>
          <p className="mt-0.5 text-xs text-slate-500">{formatDateTime(entry.created_at)}</p>
          {entry.analyst_name && <p className="mt-1 text-sm text-slate-800">Analyst: {entry.analyst_name}</p>}
          {entry.decision !== "CASE_OPENED" && (
            <p className="mt-1 text-xs font-medium text-slate-700" data-testid="decision-basis">
              {entry.assessment_number
                ? `Decision based on Assessment v${entry.assessment_number} (${entry.assessment_risk_score}/100 ${entry.assessment_risk_level})`
                : "No assessment existed when this decision was recorded."}
            </p>
          )}
          {entry.decision !== "CASE_OPENED" && (
            <p className="mt-1 whitespace-pre-wrap border-l-2 border-slate-200 pl-3 text-sm leading-relaxed text-slate-700">
              <span className="block text-xs font-medium text-slate-500">Reason</span>
              {entry.reason}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

/**
 * Case Review: the human step AFTER TrustBreak's risk assessment.
 * The decision is a workflow/audit record only - it does not change the risk assessment and no payment is
 * approved, rejected, blocked, cancelled or executed.
 *
 * Props: incidentId; assessment (persisted risk assessment or null); caseState { workflow_status, case_history };
 * onCaseChange(state) receives the persisted state returned by the server; onReload() re-fetches after a conflict.
 */
export default function CaseReviewCard({ incidentId, assessment, caseState, onCaseChange, onReload }) {
  const [analystName, setAnalystName] = useState("");
  const [reason, setReason] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitting, setSubmitting] = useState(null); // "VERIFIED" | "REJECTED" | null
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const status = caseState.workflow_status;
  const meta = caseStatusMeta(status);
  const closed = status !== "OPEN";
  const action = recommendedActionMeta(assessment?.recommended_action);

  async function submit(decision) {
    setNotice(null);
    setError(null);
    const errors = validateDecision({ reason, analystName });
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(decision);
    try {
      const res = await api.recordDecision(incidentId, {
        decision,
        reason: reason.trim(),
        analyst_name: analystName.trim(),
        ...(assessment?.assessment_id ? { assessment_id: assessment.assessment_id } : {}),
      });
      onCaseChange(res.data);
      setReason("");
      setNotice(
        decision === "VERIFIED"
          ? "Recorded: analyst verified the request. The risk assessment is unchanged."
          : "Recorded: analyst rejected the case. The risk assessment is unchanged.",
      );
    } catch (err) {
      setError(err);
      if (err?.status === 409) onReload?.(); // closed elsewhere, or a newer assessment exists: re-read persisted state
      if (err?.status === 422 && err.details?.length) {
        setFieldErrors(Object.fromEntries(err.details.map((d) => [d.field, d.message])));
      }
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <Card title="Case review" aside={<CaseBadge status={status} />}>
      <dl className="grid gap-4 sm:grid-cols-3" data-testid="case-review-summary">
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Case status (analyst)</dt>
          <dd className="mt-1.5 text-sm font-semibold text-slate-900" data-testid="case-status">
            {meta.label}
            <span className="mt-0.5 block text-xs font-normal text-slate-500">{meta.meaning}</span>
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">TrustBreak risk level</dt>
          <dd className="mt-1.5">
            <RiskBadge level={assessment?.risk_level} />
            <span className="mt-0.5 block text-xs text-slate-500">Calculated by TrustBreak; never changed by a decision</span>
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Recommended action</dt>
          <dd className="mt-1.5 text-sm font-semibold text-slate-900">
            {assessment ? `${action?.icon ?? ""} ${assessment.recommended_action_label}` : "No risk assessment yet"}
            <span className="mt-0.5 block text-xs font-normal text-slate-500">Decision support only</span>
          </dd>
        </div>
      </dl>

      <form
        className="mt-5 border-t border-slate-200 pt-5"
        noValidate
        onSubmit={(e) => e.preventDefault()}
        aria-label="Record an analyst decision"
      >
        <fieldset disabled={closed || submitting !== null} className="space-y-4 disabled:opacity-60">
          <legend className="text-sm font-semibold text-slate-900">Analyst decision</legend>

          <div>
            <label htmlFor="case-analyst" className="block text-sm font-medium text-slate-800">
              Analyst name
            </label>
            <input
              id="case-analyst"
              type="text"
              value={analystName}
              maxLength={ANALYST_MAX}
              onChange={(e) => setAnalystName(e.target.value)}
              aria-invalid={Boolean(fieldErrors.analyst_name)}
              aria-describedby={fieldErrors.analyst_name ? "case-analyst-error" : undefined}
              placeholder="e.g. Security Analyst"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm placeholder:text-slate-400 sm:max-w-sm"
            />
            {fieldErrors.analyst_name && (
              <p id="case-analyst-error" className="mt-1 text-xs text-red-700">
                {fieldErrors.analyst_name}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="case-reason" className="block text-sm font-medium text-slate-800">
              Reason for the decision
            </label>
            <textarea
              id="case-reason"
              rows={3}
              value={reason}
              maxLength={REASON_MAX + 200}
              onChange={(e) => setReason(e.target.value)}
              aria-invalid={Boolean(fieldErrors.reason)}
              aria-describedby={fieldErrors.reason ? "case-reason-error" : "case-reason-hint"}
              placeholder="e.g. Confirmed the request with the sender through the corporate directory number."
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm placeholder:text-slate-400"
            />
            {fieldErrors.reason ? (
              <p id="case-reason-error" className="mt-1 text-xs text-red-700">
                {fieldErrors.reason}
              </p>
            ) : (
              <p id="case-reason-hint" className="mt-1 text-xs text-slate-500">
                Required, at least {REASON_MIN} characters. Saved permanently in the case history.
              </p>
            )}
          </div>

          <p className="text-xs font-medium text-slate-700" data-testid="decision-will-be-based-on">
            {assessment?.version_number
              ? `This decision will be recorded against Assessment v${assessment.version_number} (${assessment.risk_score}/100 ${assessment.risk_level}).`
              : "No risk assessment exists yet; this decision will be recorded without one."}
          </p>

          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={() => submit("VERIFIED")} data-testid="mark-verified">
              {submitting === "VERIFIED" ? "Recording…" : "Mark verified"}
            </Button>
            <Button type="button" variant="secondary" onClick={() => submit("REJECTED")} data-testid="reject-case">
              {submitting === "REJECTED" ? "Recording…" : "Reject case"}
            </Button>
          </div>
        </fieldset>

        {closed && (
          <p className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700" data-testid="case-closed-note">
            This case is closed ({meta.label.toLowerCase()}). Decisions cannot be changed or repeated in this version.
          </p>
        )}
        {notice && (
          <p role="status" className="mt-3 rounded-md border border-teal-200 bg-teal-50 px-3 py-2 text-sm text-teal-900" data-testid="case-notice">
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" data-testid="case-error">
            {error.message}
          </p>
        )}
        <p className="mt-4 text-xs leading-relaxed text-slate-500">
          This is a case-management record only. “Verified” means an analyst recorded that the request was independently
          verified; “Rejected” means an analyst declined the case. TrustBreak does not approve, block, cancel or execute any
          payment.
        </p>
      </form>

      <div className="mt-6 border-t border-slate-200 pt-5">
        <h3 className="mb-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Case history</h3>
        <CaseTimeline history={caseState.case_history} />
      </div>
    </Card>
  );
}
