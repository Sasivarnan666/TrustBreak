import { Card, DataRow } from "./ui.jsx";
import { Tag } from "./StatusBadge.jsx";
import { formatINR } from "../lib/format.js";

const ROW_LABEL = { channel: "Channel", beneficiary: "Beneficiary", amount: "Amount" };
const SOURCE_TEXT = {
  explicit: "Linked by stable identity ID",
  name_match: "Matched by exact name (fallback; no ID stored)",
  unknown_id: "Identity ID not recognised",
  none: "No trusted identity linked",
};

function Cell({ tone, label, children }) {
  const tones = {
    expected: "border-slate-200 bg-slate-50",
    bad: "border-red-300 bg-red-50",
    ok: "border-emerald-300 bg-emerald-50",
    neutral: "border-slate-200 bg-white",
  };
  return (
    <div className={`rounded-md border px-3 py-2 ${tones[tone]}`}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <p className="mt-0.5 break-words text-sm font-medium text-slate-900">{children}</p>
    </div>
  );
}

/** Pure view: the trusted identity and EXPECTED vs OBSERVED for this event. All values come from the backend. */
export function IdentityContextView({ graph }) {
  const { identity, comparison, identity_source: source } = graph;
  return (
    <div className="space-y-5">
      {identity ? (
        <dl className="divide-y divide-slate-100">
          <DataRow label="Identity">{identity.display_name}</DataRow>
          <DataRow label="Employee ID"><span className="font-mono text-[13px]">{identity.employee_id}</span></DataRow>
          <DataRow label="Role">{identity.role}</DataRow>
          <DataRow label="Department">{identity.department}</DataRow>
          <DataRow label="Organization">{identity.organization}</DataRow>
          <DataRow label="Normal financial channels">{identity.normal_channels.map((c) => c.toUpperCase() === "ERP" ? "ERP" : c[0].toUpperCase() + c.slice(1)).join(", ")}</DataRow>
          <DataRow label="Trusted beneficiaries">{identity.known_beneficiaries.join(", ")}</DataRow>
          <DataRow label="Typical transaction range">
            <span className="tabular-nums">{formatINR(identity.typical_amount_min)} – {formatINR(identity.typical_amount_max)}</span>
          </DataRow>
          <DataRow label="Profile status"><Tag tone="brand">{identity.profile_status}</Tag></DataRow>
        </dl>
      ) : (
        <p className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-700">
          No trusted identity is linked to this sender, so there is no baseline to compare against. TrustBreak does not
          guess an identity from the role or a partial name.
        </p>
      )}
      <p className="text-xs text-slate-500">{SOURCE_TEXT[source] ?? source}</p>

      <div>
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-600">Current event</h3>
        <div className="mt-2 space-y-3" data-testid="expected-vs-observed">
          {comparison.map((row) => {
            const tone = row.status === "anomalous" ? "bad" : row.status === "normal" ? "ok" : "neutral";
            return (
              <div key={row.aspect}>
                <p className="mb-1 text-xs font-semibold text-slate-600">{ROW_LABEL[row.aspect]}</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  <Cell tone="expected" label="Expected">{row.expected}</Cell>
                  <Cell tone={tone} label="Observed">
                    {row.observed}
                    {row.detail && <span className="ml-2 text-xs font-semibold text-red-800">{row.detail}</span>}
                    {row.status === "anomalous" && <span className="ml-2 text-xs font-semibold text-red-800">· deviates</span>}
                    {row.status === "normal" && <span className="ml-2 text-xs font-semibold text-emerald-800">· matches</span>}
                  </Cell>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default function IdentityContextCard({ graph }) {
  return (
    <Card title="Trusted Identity" aside={<span className="text-xs text-slate-500">Synthetic demo data</span>}>
      <IdentityContextView graph={graph} />
    </Card>
  );
}
