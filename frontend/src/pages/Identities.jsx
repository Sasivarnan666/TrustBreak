import { api } from "../api/client.js";
import { ErrorState, LoadingState } from "../components/States.jsx";
import { Tag } from "../components/StatusBadge.jsx";
import { Card, PageHeader } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { compactINR } from "../lib/format.js";

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-3 py-2 text-sm">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 break-words text-slate-900">{children}</dd>
    </div>
  );
}

export default function Identities() {
  const { data, error, loading, reload } = useAsync((signal) => api.listIdentities(signal), []);
  return (
    <>
      <PageHeader
        eyebrow="Trusted identity registry"
        title="Identities"
        subtitle="Synthetic trusted identities and their expected behaviour. Requests are compared against these baselines; nothing here is real personal data."
      />
      {loading && <LoadingState label="Loading identities…" rows={3} />}
      {error && <ErrorState error={error} onRetry={reload} title="Could not load identities" />}
      {data && (
        <div className="grid gap-5 lg:grid-cols-2">
          {data.data.map((i) => (
            <Card key={i.identity_id} title={i.identity_id} aside={<Tag tone="amber">Synthetic</Tag>}>
              <p className="text-lg font-semibold text-slate-900">{i.display_name}</p>
              <p className="text-sm text-slate-600">{i.role} · {i.department} · {i.organization}</p>
              <dl className="mt-3 divide-y divide-slate-100">
                <Row label="Normal channels">{i.normal_channels.join(", ")}</Row>
                <Row label="Trusted channels">{i.trusted_channels.join(", ")}</Row>
                <Row label="Restricted channels">{i.restricted_channels.join(", ") || "—"}</Row>
                <Row label="Known beneficiaries">{i.known_beneficiaries.join(", ")}</Row>
                <Row label="Typical amount"><span className="tabular-nums">{compactINR(i.typical_amount_min)} – {compactINR(i.typical_amount_max)}</span></Row>
                <Row label="Working hours">{i.typical_working_hours}</Row>
                <Row label="Corporate email"><span className="font-mono text-[13px]">{i.corporate_email}</span></Row>
              </dl>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
