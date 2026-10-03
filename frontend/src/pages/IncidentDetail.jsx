import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import AttachmentAnalysisCard from "../components/AttachmentAnalysisCard.jsx";
import BehaviourAnalysisCard from "../components/BehaviourAnalysisCard.jsx";
import CaseReviewCard from "../components/CaseReviewCard.jsx";
import MessageAnalysisCard from "../components/MessageAnalysisCard.jsx";
import RiskAssessmentCard from "../components/RiskAssessmentCard.jsx";
import { ErrorState, LoadingState } from "../components/States.jsx";
import { CaseBadge, RiskBadge, Tag } from "../components/StatusBadge.jsx";
import { ButtonLink, Card, DataRow } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { formatBytes, formatDateTime, formatINR } from "../lib/format.js";
import { recommendedActionMeta } from "../lib/risk.js";

function SummaryCell({ label, children, sub }) {
  return (
    <div className="px-5 py-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <p className="mt-1.5 text-lg font-semibold tracking-tight text-slate-900">{children}</p>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

/** Pure view of one incident. */
export function IncidentView({ incident }) {
  const { sender, payment, attachment, analysis } = incident;
  const isPlaceholder = analysis.mode === "placeholder";
  // The persisted risk assessment (if any) is the incident's real security status; it updates here when re-run.
  const [assessment, setAssessment] = useState(incident.risk_assessment ?? null);
  const action = recommendedActionMeta(assessment?.recommended_action);
  const [attachmentFile, setAttachmentFile] = useState(null); // shared by Attachment Analysis and the risk assessment
  // The human case workflow is separate state from the risk assessment: a decision never touches `assessment`.
  const [caseState, setCaseState] = useState({
    workflow_status: incident.workflow_status,
    case_history: incident.case_history ?? [],
  });
  // After a conflict (e.g. the case was closed elsewhere) re-read the persisted workflow state in place.
  const syncCase = () =>
    api
      .getIncident(incident.id)
      .then((res) => setCaseState({ workflow_status: res.data.workflow_status, case_history: res.data.case_history }))
      .catch(() => {});

  return (
    <>
      <nav className="mb-4 text-xs text-slate-500" aria-label="Breadcrumb">
        <Link to="/incidents" className="hover:text-slate-800 hover:underline">
          Incidents
        </Link>
        <span className="mx-1.5">/</span>
        <span className="font-mono text-slate-700">{incident.reference}</span>
      </nav>

      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{incident.title}</h1>
          <p className="mt-1 text-sm text-slate-600">
            <span className="font-mono">{incident.reference}</span> · Reported {formatDateTime(incident.created_at)}
          </p>
        </div>
        <div className="flex flex-col items-start gap-1 sm:items-end" data-testid="incident-status">
          <div className="flex flex-wrap items-center gap-2">
            <RiskBadge level={assessment?.risk_level} size="lg" />
            <CaseBadge status={caseState.workflow_status} size="lg" />
          </div>
          <span className="text-xs font-medium text-slate-600">
            {assessment ? `${action?.icon ?? ""} ${assessment.recommended_action_label}` : "No risk assessment yet"}
          </span>
          <span className="text-[11px] text-slate-500">Risk = TrustBreak assessment · Case = analyst review</span>
        </div>
      </header>

      <div className="grid divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 lg:divide-x">
        <SummaryCell label="Amount requested" sub="Indian rupees">
          <span className="tabular-nums">{formatINR(payment.amount)}</span>
        </SummaryCell>
        <SummaryCell label="Beneficiary" sub={payment.beneficiary_is_new ? <Tag tone="amber">New beneficiary</Tag> : "Existing beneficiary"}>
          {payment.beneficiary_name}
        </SummaryCell>
        <SummaryCell label="Channel" sub="How the request arrived">
          {incident.channel}
        </SummaryCell>
        <SummaryCell label="Sender" sub={sender.known ? <Tag tone="brand">Known contact</Tag> : <Tag>Not a known contact</Tag>}>
          {sender.name}
        </SummaryCell>
      </div>

      <div className="mt-6">
        <RiskAssessmentCard
          incidentId={incident.id}
          attachmentFile={attachmentFile}
          hasAttachment={Boolean(attachment)}
          assessment={assessment}
          onAssessed={setAssessment}
        />
      </div>

      <div className="mt-6">
        <CaseReviewCard
          incidentId={incident.id}
          assessment={assessment}
          caseState={caseState}
          onCaseChange={(state) =>
            setCaseState({ workflow_status: state.workflow_status, case_history: state.case_history })
          }
          onReload={syncCase}
        />
      </div>

      {!assessment && (
        <section aria-labelledby="intake-note" className="mt-6 rounded-lg border border-slate-200 bg-slate-50 p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="intake-note" className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-600">
              Intake note
            </h2>
            {isPlaceholder && <Tag>Placeholder · not a risk assessment</Tag>}
          </div>
          <p className="mt-2 text-sm leading-relaxed text-slate-800">{analysis.recommended_action}</p>
          <p className="mt-2 text-xs leading-relaxed text-slate-600">{analysis.summary}</p>
        </section>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card title="Message">
            <blockquote className="whitespace-pre-wrap border-l-2 border-slate-300 pl-4 text-sm leading-relaxed text-slate-800">
              {incident.message}
            </blockquote>
          </Card>

          <MessageAnalysisCard incidentId={incident.id} />

          <BehaviourAnalysisCard incidentId={incident.id} />

          {attachment && <AttachmentAnalysisCard incidentId={incident.id} attachmentName={attachment.name} onFileChange={setAttachmentFile} />}

          <Card title="Evidence" padded={false} aside={<span className="text-xs text-slate-500">{analysis.evidence.length} items</span>}>
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-500">
                <tr>
                  <th className="px-5 py-2.5">Item</th>
                  <th className="px-3 py-2.5">Recorded value</th>
                  <th className="px-5 py-2.5">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {analysis.evidence.map((item) => (
                  <tr key={item.label}>
                    <td className="whitespace-nowrap px-5 py-3 text-slate-500">{item.label}</td>
                    <td className="px-3 py-3 font-medium text-slate-900">{item.value}</td>
                    <td className="px-5 py-3">
                      <Tag>{item.source}</Tag>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="Sender">
            <dl className="divide-y divide-slate-100">
              <DataRow label="Name">{sender.name}</DataRow>
              <DataRow label="Role">{sender.role}</DataRow>
              <DataRow label="Status">{sender.known ? "Known contact" : "Not a known contact"}</DataRow>
              <DataRow label="Contact">{sender.contact ? <span className="font-mono text-[13px]">{sender.contact}</span> : "—"}</DataRow>
            </dl>
          </Card>

          <Card title="Payment">
            <dl className="divide-y divide-slate-100">
              <DataRow label="Amount">
                <span className="tabular-nums">{formatINR(payment.amount)}</span>
              </DataRow>
              <DataRow label="Beneficiary">{payment.beneficiary_name}</DataRow>
              <DataRow label="Beneficiary status">{payment.beneficiary_is_new ? "New" : "Existing"}</DataRow>
              <DataRow label="Channel">{incident.channel}</DataRow>
            </dl>
          </Card>

          <Card title="Attachment">
            {attachment ? (
              <dl className="divide-y divide-slate-100">
                <DataRow label="File name">
                  <span className="font-mono text-[13px]">{attachment.name}</span>
                </DataRow>
                <DataRow label="Type">{attachment.content_type ?? "—"}</DataRow>
                <DataRow label="Size">{formatBytes(attachment.size_bytes)}</DataRow>
              </dl>
            ) : (
              <p className="text-sm text-slate-600">No attachment was reported with this request.</p>
            )}
            <p className="mt-3 text-xs text-slate-500">Metadata only. The file itself is never stored; use Attachment Analysis to inspect a copy.</p>
          </Card>
        </div>
      </div>
    </>
  );
}

export default function IncidentDetail() {
  const { id } = useParams();
  const { data, error, loading, reload } = useAsync((signal) => api.getIncident(id, signal), [id]);

  if (loading) return <LoadingState label="Loading incident…" rows={6} />;
  if (error) {
    const notFound = error.status === 404;
    return (
      <div className="space-y-4">
        <ErrorState
          error={error}
          onRetry={notFound ? undefined : reload}
          title={notFound ? "Incident not found" : "Could not load this incident"}
        />
        <ButtonLink to="/incidents" variant="secondary">
          Back to incidents
        </ButtonLink>
      </div>
    );
  }
  return <IncidentView incident={data.data} />;
}
