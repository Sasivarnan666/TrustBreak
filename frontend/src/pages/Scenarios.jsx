import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client.js";
import { ErrorState, LoadingState } from "../components/States.jsx";
import { Tag } from "../components/StatusBadge.jsx";
import { Button, PageHeader } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { formatINR } from "../lib/format.js";

export function DemoModeBadge() {
  return (
    <span data-testid="demo-mode" className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-white">
      <span className="size-1.5 rounded-full bg-amber-400" aria-hidden="true" />
      Demo mode
    </span>
  );
}

function ScenarioCard({ s, busy, onLoad }) {
  return (
    <article className="flex flex-col rounded-lg border border-slate-200 bg-white p-5" data-testid={`scenario-${s.id}`}>
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-base font-semibold leading-snug text-slate-900">{s.title}</h2>
        <Tag tone="amber">Synthetic</Tag>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{s.illustrates}</p>
      <dl className="mt-4 grid grid-cols-[6.5rem_1fr] gap-x-3 gap-y-1.5 text-sm">
        <dt className="text-slate-500">Sender</dt>
        <dd className="font-medium text-slate-900">{s.sender_name} · {s.sender_role}</dd>
        <dt className="text-slate-500">Organisation</dt>
        <dd className="text-slate-900">{s.organization}</dd>
        <dt className="text-slate-500">Channel</dt>
        <dd className="text-slate-900">{s.channel}</dd>
        <dt className="text-slate-500">Amount</dt>
        <dd className="tabular-nums text-slate-900">{formatINR(s.amount)}</dd>
        <dt className="text-slate-500">Beneficiary</dt>
        <dd className="text-slate-900">{s.beneficiary_name} {s.beneficiary_is_new && <Tag tone="amber">New</Tag>}</dd>
        {s.attachment_name && (
          <>
            <dt className="text-slate-500">Attachment</dt>
            <dd className="font-mono text-[13px] text-slate-900">{s.attachment_name}<span className="block text-xs text-slate-500">{s.attachment_entries.join(" · ")}</span></dd>
          </>
        )}
      </dl>
      <blockquote className="mt-4 line-clamp-4 border-l-2 border-slate-200 pl-3 text-[13px] leading-relaxed text-slate-700">{s.message}</blockquote>
      <div className="mt-auto pt-5">
        <Button type="button" disabled={busy} onClick={() => onLoad(s.id)} className="w-full">
          {busy ? "Running the real pipeline…" : "LOAD SCENARIO"}
        </Button>
      </div>
    </article>
  );
}

export default function Scenarios() {
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync((signal) => api.listScenarios(signal), []);
  const [busyId, setBusyId] = useState(null);
  const [problem, setProblem] = useState(null);

  const load = async (id) => {
    setBusyId(id);
    setProblem(null);
    try {
      const res = await api.loadScenario(id);
      navigate(`/incidents/${res.data.incident_id}`);
    } catch (err) {
      setProblem(err.message);
      setBusyId(null);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Scenario simulator"
        title="Scenarios"
        subtitle="Load a synthetic request. It is created as a normal incident and scored by the real pipeline — no result is shown in advance and none is hardcoded."
        actions={<DemoModeBadge />}
      />
      <p className="mb-5 rounded-md border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
        All scenarios are synthetic: fictional people, organisation, amounts, messages and files. They are never real incidents.
      </p>
      {problem && <p role="alert" className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-800">{problem}</p>}
      {loading && <LoadingState label="Loading scenarios…" rows={4} />}
      {error && <ErrorState error={error} onRetry={reload} title="Could not load scenarios" />}
      {data && (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {data.data.map((s) => (
            <ScenarioCard key={s.id} s={s} busy={busyId === s.id} onLoad={load} />
          ))}
        </div>
      )}
    </>
  );
}
