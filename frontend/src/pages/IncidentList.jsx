import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.jsx";
import { RiskBadge, Tag } from "../components/StatusBadge.jsx";
import { ButtonLink, PageHeader } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { formatDateTime, formatINR } from "../lib/format.js";
import { recommendedActionMeta } from "../lib/risk.js";

/** Pure view: filtering is local, over the rows already fetched. */
export function IncidentTable({ incidents }) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return incidents;
    return incidents.filter((i) =>
      [i.reference, i.sender_name, i.sender_role, i.beneficiary_name, i.channel].some((v) => v.toLowerCase().includes(q)),
    );
  }, [incidents, query]);

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div className="border-b border-slate-200 p-3">
        <label htmlFor="incident-search" className="sr-only">
          Search incidents
        </label>
        <input
          id="incident-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by reference, sender, beneficiary or channel"
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm placeholder:text-slate-400 sm:max-w-md"
        />
      </div>

      {filtered.length === 0 ? (
        <p className="px-5 py-10 text-center text-sm text-slate-600">No incidents match “{query}”.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[64rem] text-left text-sm">
            <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-500">
              <tr>
                <th className="px-5 py-3">Reference</th>
                <th className="px-3 py-3">Sender</th>
                <th className="px-3 py-3">Channel</th>
                <th className="px-3 py-3 text-right">Amount</th>
                <th className="px-3 py-3">Beneficiary</th>
                <th className="px-3 py-3">Attachment</th>
                <th className="px-3 py-3">Risk</th>
                <th className="px-3 py-3">Recommended action</th>
                <th className="px-5 py-3">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((i) => (
                <tr key={i.id} className="hover:bg-slate-50">
                  <td className="px-5 py-3.5">
                    <Link to={`/incidents/${i.id}`} className="font-mono text-xs font-semibold text-brand-700 hover:underline">
                      {i.reference}
                    </Link>
                  </td>
                  <td className="px-3 py-3.5">
                    <p className="font-medium text-slate-900">{i.sender_name}</p>
                    <p className="text-xs text-slate-500">
                      {i.sender_role} {i.sender_known && <Tag tone="brand">Known</Tag>}
                    </p>
                  </td>
                  <td className="px-3 py-3.5 text-slate-700">{i.channel}</td>
                  <td className="px-3 py-3.5 text-right font-semibold tabular-nums text-slate-900">{formatINR(i.amount)}</td>
                  <td className="px-3 py-3.5 text-slate-700">
                    {i.beneficiary_name} {i.beneficiary_is_new && <Tag tone="amber">New</Tag>}
                  </td>
                  <td className="px-3 py-3.5 text-slate-600">{i.has_attachment ? "Yes" : "—"}</td>
                  <td className="px-3 py-3.5">
                    <RiskBadge level={i.risk_level} />
                    {i.trust_break_detected && <p className="mt-1 text-[11px] font-semibold text-red-700">Trust break</p>}
                  </td>
                  <td className="px-3 py-3.5 text-slate-700" data-testid="row-action">
                    {i.recommended_action ? (
                      <>
                        {recommendedActionMeta(i.recommended_action)?.icon} {i.recommended_action_label}
                      </>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3.5 text-xs text-slate-500">{formatDateTime(i.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function IncidentList() {
  const { data, error, loading, reload } = useAsync((signal) => api.listIncidents({ limit: 500 }, signal), []);

  return (
    <>
      <PageHeader
        eyebrow="Cases"
        title="Incidents"
        subtitle={data ? `${data.meta.total} recorded payment request${data.meta.total === 1 ? "" : "s"}, newest first.` : undefined}
        actions={<ButtonLink to="/incidents/new">New incident</ButtonLink>}
      />
      {loading && <LoadingState label="Loading incidents…" rows={5} />}
      {error && <ErrorState error={error} onRetry={reload} title="Could not load incidents" />}
      {data && data.data.length === 0 && (
        <EmptyState
          title="No incidents yet"
          description="Incidents you create will be listed here."
          action={<ButtonLink to="/incidents/new">Create incident</ButtonLink>}
        />
      )}
      {data && data.data.length > 0 && <IncidentTable incidents={data.data} />}
    </>
  );
}
