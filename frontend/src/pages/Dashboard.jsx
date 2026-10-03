import { Link } from "react-router-dom";
import { api } from "../api/client.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.jsx";
import { StatusBadge, Tag } from "../components/StatusBadge.jsx";
import { ButtonLink, Card, PageHeader } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { formatDateTime, formatINR } from "../lib/format.js";

function Kpi({ label, value, hint }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-slate-900">{value}</p>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
    </div>
  );
}

function channelCounts(incidents) {
  const counts = new Map();
  for (const incident of incidents) counts.set(incident.channel, (counts.get(incident.channel) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

/** Pure view: everything it needs arrives as props. */
export function DashboardView({ incidents, total }) {
  const needsReview = incidents.filter((i) => i.risk_status === "needs_review");
  const valueUnderReview = needsReview.reduce((sum, i) => sum + i.amount, 0);
  const newBeneficiaries = incidents.filter((i) => i.beneficiary_is_new).length;
  const channels = channelCounts(incidents);
  const maxChannel = Math.max(...channels.map(([, n]) => n), 1);

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Total incidents" value={total} hint="All recorded payment requests" />
        <Kpi label="Needs review" value={needsReview.length} hint="Awaiting manual verification" />
        <Kpi label="Value under review" value={formatINR(valueUnderReview)} hint="Sum of amounts needing review" />
        <Kpi label="New beneficiaries" value={newBeneficiaries} hint="Payees not previously used" />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card
          title="Recent incidents"
          padded={false}
          className="lg:col-span-2"
          aside={
            <Link to="/incidents" className="text-xs font-semibold text-brand-700 hover:underline">
              View all
            </Link>
          }
        >
          <ul className="divide-y divide-slate-100">
            {incidents.slice(0, 5).map((incident) => (
              <li key={incident.id}>
                <Link to={`/incidents/${incident.id}`} className="flex items-center gap-4 px-5 py-3.5 hover:bg-slate-50">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-slate-900">{incident.title}</p>
                    <p className="mt-0.5 truncate text-xs text-slate-500">
                      <span className="font-mono">{incident.reference}</span> · {incident.channel} →{" "}
                      {incident.beneficiary_name} · {formatDateTime(incident.created_at)}
                    </p>
                  </div>
                  <div className="hidden text-right sm:block">
                    <p className="text-sm font-semibold tabular-nums text-slate-900">{formatINR(incident.amount)}</p>
                    {incident.beneficiary_is_new && <Tag tone="amber">New beneficiary</Tag>}
                  </div>
                  <StatusBadge status={incident.risk_status} />
                </Link>
              </li>
            ))}
          </ul>
        </Card>

        <div className="space-y-6">
          <Card title="By channel">
            <ul className="space-y-3">
              {channels.map(([channel, count]) => (
                <li key={channel}>
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="font-medium text-slate-800">{channel}</span>
                    <span className="tabular-nums text-slate-500">{count}</span>
                  </div>
                  <div className="mt-1.5 h-1.5 rounded-full bg-slate-100">
                    <div className="h-1.5 rounded-full bg-brand-600" style={{ width: `${(count / maxChannel) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          <Card title="Analysis engine">
            <div className="flex items-center gap-2">
              <Tag tone="amber">Placeholder</Tag>
              <span className="text-sm font-medium text-slate-800">No detection active</span>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              Incidents are stored and marked for manual review. Submitted details are listed as evidence; no
              fraud analysis is performed in this build.
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}

export default function Dashboard() {
  const { data, error, loading, reload } = useAsync((signal) => api.listIncidents({ limit: 500 }, signal), []);

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Dashboard"
        subtitle="Payment requests checked against sender, channel, payee and attachment."
        actions={<ButtonLink to="/incidents/new">New incident</ButtonLink>}
      />
      {loading && <LoadingState label="Loading dashboard…" />}
      {error && <ErrorState error={error} onRetry={reload} title="Could not load the dashboard" />}
      {data && data.data.length === 0 && (
        <EmptyState
          title="No incidents yet"
          description="Record a suspicious payment request to see it here."
          action={<ButtonLink to="/incidents/new">Create the first incident</ButtonLink>}
        />
      )}
      {data && data.data.length > 0 && <DashboardView incidents={data.data} total={data.meta.total} />}
    </>
  );
}
