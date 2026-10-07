import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, reportUrl } from "../api/client.js";
import AssessmentHistoryCard from "../components/AssessmentHistoryCard.jsx";
import AttachmentAnalysisCard from "../components/AttachmentAnalysisCard.jsx";
import AttachmentIntelligenceCard from "../components/AttachmentIntelligenceCard.jsx";
import BehaviourAnalysisCard from "../components/BehaviourAnalysisCard.jsx";
import CaseReviewCard from "../components/CaseReviewCard.jsx";
import CounterfactualCard from "../components/CounterfactualCard.jsx";
import EvidenceChainCard from "../components/EvidenceChainCard.jsx";
import IdentityContextCard from "../components/IdentityContextCard.jsx";
import MessageAnalysisCard from "../components/MessageAnalysisCard.jsx";
import MessageIntelligenceCard from "../components/MessageIntelligenceCard.jsx";
import RiskAssessmentCard from "../components/RiskAssessmentCard.jsx";
import { ErrorState, LoadingState } from "../components/States.jsx";
import { CaseBadge, RiskBadge, Tag } from "../components/StatusBadge.jsx";
import TimelineCard from "../components/TimelineCard.jsx";
import TrustGraphCard from "../components/TrustGraphCard.jsx";
import VerificationCard from "../components/VerificationCard.jsx";
import { ButtonLink, Card } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { formatDateTime, formatINR } from "../lib/format.js";
import { recommendedActionMeta } from "../lib/risk.js";

function SummaryCell({ label, children, sub }) {
  return (
    <div className="px-4 py-3.5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <p className="mt-1 text-base font-semibold tracking-tight text-slate-900">{children}</p>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function Section({ id, title, children }) {
  return (
    <section id={id} aria-label={title} className="scroll-mt-20">
      <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">{title}</h2>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

/** Pure view of one incident (analyst workspace). */
export function IncidentView({ incident }) {
  const { sender, payment, attachment } = incident;
  const [assessment, setAssessment] = useState(incident.risk_assessment ?? null);
  const action = recommendedActionMeta(assessment?.recommended_action);
  const [attachmentFile, setAttachmentFile] = useState(null);
  const [caseState, setCaseState] = useState({ workflow_status: incident.workflow_status, case_history: incident.case_history ?? [] });
  const [history, setHistory] = useState(incident.assessment_history ?? []);
  const [refresh, setRefresh] = useState(0); // bumps the timeline after verification / decision changes
  const bump = () => setRefresh((n) => n + 1);

  const syncCase = () =>
    api.getIncident(incident.id).then((res) => {
      setCaseState({ workflow_status: res.data.workflow_status, case_history: res.data.case_history });
      setAssessment(res.data.risk_assessment ?? null);
      setHistory(res.data.assessment_history ?? []);
      bump();
    }).catch(() => {});
  const assessmentId = assessment?.assessment_id ?? 0;
  const graphState = useAsync((signal) => api.getTrustGraph(incident.id, signal), [incident.id, assessmentId]);
  const scenarios = useAsync((signal) => (incident.scenario_id ? api.listScenarios(signal) : Promise.resolve(null)), [incident.scenario_id]);
  const archive = scenarios.data?.data.find((s) => s.id === incident.scenario_id)?.attachment_entries ?? [];
  const onAssessed = (next) => {
    setAssessment(next);
    api.listAssessments(incident.id).then((res) => setHistory(res.data)).catch(() => {});
    bump();
  };
  const signals = assessment?.signals ?? [];
  const dims = new Set(signals.filter((s) => s.points > 0).map((s) => s.category));
  const dimCount = assessment && assessment.risk_level !== "LOW" ? dims.size : 0;

  return (
    <>
      <nav className="mb-3 text-xs text-slate-500 print:hidden" aria-label="Breadcrumb">
        <Link to="/incidents" className="hover:text-slate-800 hover:underline">Incidents</Link>
        <span className="mx-1.5">/</span>
        <span className="font-mono text-slate-700">{incident.reference}</span>
      </nav>

      {incident.is_synthetic && (
        <p className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900" data-testid="synthetic-banner">
          DEMO MODE · synthetic scenario “{incident.scenario_id}”. Fictional data, not a real incident.
        </p>
      )}

      {/* ---- Incident header ---- */}
      <header className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="font-mono text-sm font-semibold text-slate-600">{incident.reference}</p>
            <h1 className="mt-0.5 text-xl font-semibold tracking-tight text-slate-900">{incident.title}</h1>
            <p className="mt-1 text-xs text-slate-500">Reported {formatDateTime(incident.created_at)}</p>
          </div>
          <div className="flex flex-col items-start gap-2 sm:items-end" data-testid="incident-status">
            <div className="flex flex-wrap items-center gap-2">
              {assessment && <span className="text-3xl font-semibold tabular-nums text-slate-900">{assessment.risk_score}</span>}
              <RiskBadge level={assessment?.risk_level} size="lg" />
              <CaseBadge status={caseState.workflow_status} size="lg" />
            </div>
            <p className="text-sm font-semibold uppercase tracking-wide text-slate-800">
              {assessment ? (assessment.trust_break_detected ? `Trust break detected · ${action?.label ?? ""}` : action?.label) : "No risk assessment yet"}
            </p>
            <p className="text-[11px] text-slate-500">System assessment ≠ human case decision</p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2 print:hidden">
          <a href={reportUrl(incident.id)} target="_blank" rel="noreferrer" className="inline-flex items-center rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-800 hover:bg-slate-50">
            EXPORT INCIDENT REPORT
          </a>
        </div>
      </header>

      {/* ---- Trust break summary ---- */}
      <section aria-label="Trust break summary" className="mt-4 grid divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 lg:divide-x xl:grid-cols-4">
        <SummaryCell label="Prototype risk score" sub={assessment ? `${assessment.raw_points} raw points · not a probability` : "Run the assessment"}>
          {assessment ? `${assessment.risk_score} · ${assessment.risk_level}` : "—"}
        </SummaryCell>
        <SummaryCell label="Recommended action" sub={assessment ? `${dimCount} trust dimension${dimCount === 1 ? "" : "s"} violated · ${signals.length} signals` : undefined}>
          {assessment ? action?.label : "—"}
        </SummaryCell>
        <SummaryCell label="Amount / beneficiary" sub={payment.beneficiary_is_new ? <Tag tone="amber">New beneficiary</Tag> : "Existing beneficiary"}>
          <span className="tabular-nums">{formatINR(payment.amount)}</span> → {payment.beneficiary_name}
        </SummaryCell>
        <SummaryCell label="Sender / channel" sub={sender.identity_id ? <span className="font-mono">{sender.identity_id}</span> : <Tag>No trusted identity</Tag>}>
          {sender.name} · {incident.channel}
        </SummaryCell>
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <div className="space-y-8 xl:col-span-2">
          <Section id="why" title="Why did trust break?">
            <EvidenceChainCard graph={graphState.data?.data} assessment={assessment} />
            {graphState.data && (
              <details className="rounded-lg border border-slate-200 bg-white">
                <summary className="cursor-pointer select-none px-5 py-3 text-xs font-semibold uppercase tracking-wide text-slate-600">Evidence graph and identity context</summary>
                <div className="space-y-4 border-t border-slate-200 p-4">
                  <IdentityContextCard graph={graphState.data.data} />
                  <TrustGraphCard graph={graphState.data.data} />
                </div>
              </details>
            )}
            {graphState.error && <p role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">The evidence graph could not be loaded ({graphState.error.message}).</p>}
          </Section>

          <Section id="risk" title="Risk breakdown">
            <RiskAssessmentCard incidentId={incident.id} attachmentFile={attachmentFile} hasAttachment={Boolean(attachment)} assessment={assessment} onAssessed={onAssessed} />
          </Section>

          <Section id="counterfactuals" title="Counterfactuals">
            <CounterfactualCard incidentId={incident.id} assessmentId={assessmentId} />
          </Section>

          <Section id="message" title="Message intelligence">
            <MessageIntelligenceCard message={incident.message} signals={signals} />
            <MessageAnalysisCard incidentId={incident.id} />
            <BehaviourAnalysisCard incidentId={incident.id} />
          </Section>

          {attachment && (
            <Section id="attachment" title="Attachment intelligence">
              <AttachmentIntelligenceCard attachment={attachment} signals={signals} archiveEntries={archive} />
              <AttachmentAnalysisCard incidentId={incident.id} attachmentName={attachment.name} onFileChange={setAttachmentFile} />
            </Section>
          )}
        </div>

        <div className="space-y-8">
          <Section id="verification" title="Verification">
            <VerificationCard incidentId={incident.id} assessmentId={assessmentId} onChanged={bump} />
          </Section>
          <Section id="timeline" title="Forensic timeline">
            <TimelineCard incidentId={incident.id} refreshKey={refresh + assessmentId} />
          </Section>
          <Section id="history" title="Assessment history">
            <AssessmentHistoryCard incidentId={incident.id} history={history} caseHistory={caseState.case_history} />
          </Section>
          <Section id="decision" title="Analyst decision">
            <CaseReviewCard
              incidentId={incident.id}
              assessment={assessment}
              caseState={caseState}
              onCaseChange={(state) => { setCaseState({ workflow_status: state.workflow_status, case_history: state.case_history }); bump(); }}
              onReload={syncCase}
            />
          </Section>
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
        <ErrorState error={error} onRetry={notFound ? undefined : reload} title={notFound ? "Incident not found" : "Could not load this incident"} />
        <ButtonLink to="/incidents" variant="secondary">Back to incidents</ButtonLink>
      </div>
    );
  }
  return <IncidentView key={data.data.id} incident={data.data} />;
}
