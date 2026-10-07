import { Link } from "react-router-dom";
import { api } from "../api/client.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.jsx";
import { CaseBadge, RiskBadge, Tag } from "../components/StatusBadge.jsx";
import { ButtonLink, Card, PageHeader } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { formatDateTime, formatINR } from "../lib/format.js";

const ACTION_TEXT = { PROCEED: "Proceed", VERIFY: "Verify", HOLD_PAYMENT: "Hold payment" };
const VERIFY_TEXT = { NOT_STARTED: "Not started", IN_PROGRESS: "In progress", CONFIRMED: "Confirmed", FAILED: "Failed" };

function Kpi({ label, value, hint, accent }) {
  return (
    <div className={`rounded-lg border bg-white p-4 ${accent ?? "border-slate-200"}`}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <p className="mt-1.5 text-3xl font-semibold tabular-nums tracking-tight text-slate-900">{value}</p>
      <p className="mt-0.5 text-xs text-slate-500">{hint}</p>
    </div>
  );
}

function Bars({ items, color = "bg-slate-600", empty }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  const none = items.every((i) => i.value === 0);
  return (
    <ul className="space-y-2.5">
      {items.map((i) => (
        <li key={i.label} className="grid grid-cols-[8.5rem_1fr_2rem] items-center gap-3 text-sm">
          <span className="text-slate-700">{i.label}</span>
          <span className="h-2 rounded-full bg-slate-100" aria-hidden="true">
            <span className={`block h-2 rounded-full ${i.color ?? color}`} style={{ width: `${(i.value / max) * 100}%` }} />
          </span>
          <span className="text-right font-semibold tabular-nums text-slate-900">{i.value}</span>
        </li>
      ))}
      {none && empty && <li className="pt-1 text-xs text-slate-500">{empty}</li>}
    </ul>
  );
}

const STATUS_DOT = { ok: "bg-emerald-500", fallback: "bg-amber-500", ai: "bg-emerald-500", configured: "bg-slate-400" };

function StatusRow({ name, state, detail }) {
  return (
    <li className="flex items-start gap-3 py-2.5 text-sm">
      <span className={`mt-1.5 size-2 shrink-0 rounded-full ${STATUS_DOT[state] ?? "bg-slate-400"}`} aria-hidden="true" />
      <div className="min-w-0">
        <p className="font-semibold text-slate-900">{name}</p>
        <p className="text-xs leading-relaxed text-slate-600">{detail}</p>
      </div>
    </li>
  );
}

/** Pure view of the /api/dashboard aggregate. */
export function DashboardView({ data }) {
  const { kpis, risk_distribution: dist, trust_break_categories: cats, active_high_risk: active, recent_critical: recent, system_status: sys } = data;
  if (kpis.total_incidents === 0) {
    return (
      <EmptyState
        title="No incidents yet"
        description="Load a synthetic scenario to see TrustBreak correlate identity, channel, behaviour, beneficiary, social-engineering and attachment evidence."
        action={<ButtonLink to="/scenarios">Open scenarios</ButtonLink>}
      />
    );
  }
  const ai = sys.ai_extraction;
  return (
    <>
      <section aria-label="Key figures" className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5" data-testid="kpis">
        <Kpi label="Critical" value={kpis.critical} hint="Hold payment recommended" accent={kpis.critical ? "border-red-300" : undefined} />
        <Kpi label="High" value={kpis.high} hint="Verify before paying" accent={kpis.high ? "border-orange-300" : undefined} />
        <Kpi label="Open cases" value={kpis.open_cases} hint="Awaiting analyst decision" />
        <Kpi label="Verified" value={kpis.verified} hint="Analyst verified the request" />
        <Kpi label="Rejected" value={kpis.rejected} hint="Analyst rejected the case" />
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="Active high-risk incidents" padded={false} aside={<span className="text-xs text-slate-500">{active.length} open</span>}>
            {active.length === 0 ? (
              <p className="px-5 py-8 text-center text-sm text-slate-600">No open high-risk incidents. Closed cases and lower-risk requests are listed under Incidents.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[40rem] text-left text-sm">
                  <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-500">
                    <tr>
                      <th className="px-4 py-2.5">Incident</th>
                      <th className="px-3 py-2.5">Identity</th>
                      <th className="px-3 py-2.5 text-right">Amount</th>
                      <th className="px-3 py-2.5">Risk</th>
                      <th className="px-3 py-2.5 text-center">Trust breaks</th>
                      <th className="px-3 py-2.5">Action</th>
                      <th className="px-4 py-2.5">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {active.map((i) => (
                      <tr key={i.incident_id} className="hover:bg-slate-50">
                        <td className="whitespace-nowrap px-4 py-3">
                          <Link to={`/incidents/${i.incident_id}`} className="font-mono text-[13px] font-semibold text-brand-700 hover:underline">{i.reference}</Link>
                          {i.is_synthetic && <span className="ml-2"><Tag tone="amber">Demo</Tag></span>}
                        </td>
                        <td className="px-3 py-3">{i.identity_name}{i.identity_id && <span className="block font-mono text-[11px] text-slate-500">{i.identity_id}</span>}</td>
                        <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">{formatINR(i.amount)}</td>
                        <td className="whitespace-nowrap px-3 py-3"><RiskBadge level={i.risk_level} /> <span className="ml-1 font-semibold tabular-nums">{i.risk_score}</span></td>
                        <td className="px-3 py-3 text-center tabular-nums">{i.trust_dimensions}</td>
                        <td className="whitespace-nowrap px-3 py-3 text-xs font-medium text-slate-700">{ACTION_TEXT[i.recommended_action]}</td>
                        <td className="whitespace-nowrap px-4 py-3">
                          <CaseBadge status={i.workflow_status} />
                          <span className="mt-1 block text-[11px] text-slate-500">Verification: {VERIFY_TEXT[i.verification_state]}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="Risk distribution">
            <Bars
              items={[
                { label: "Critical", value: dist.critical, color: "bg-red-600" },
                { label: "High", value: dist.high, color: "bg-orange-500" },
                { label: "Medium", value: dist.medium, color: "bg-amber-400" },
                { label: "Low", value: dist.low, color: "bg-emerald-500" },
              ]}
            />
            <p className="mt-3 text-xs text-slate-500">{dist.assessed} assessed · {kpis.not_assessed} not assessed</p>
          </Card>
          <Card title="Trust break categories">
            <Bars items={cats.map((c) => ({ label: c.label, value: c.incidents }))} empty="No broken-trust findings yet." />
            <p className="mt-3 text-xs text-slate-500">Incidents (medium risk or above) with scored evidence in each category.</p>
          </Card>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="Recent critical incidents" padded={false}>
            {recent.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-600">No critical incidents.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {recent.map((i) => (
                  <li key={i.incident_id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-sm">
                    <div className="min-w-0">
                      <Link to={`/incidents/${i.incident_id}`} className="font-mono text-[13px] font-semibold text-brand-700 hover:underline">{i.reference}</Link>
                      <span className="ml-2 text-slate-700">{i.title}</span>
                      <p className="text-xs text-slate-500">Assessed {formatDateTime(i.assessed_at)} · {formatINR(i.amount)}</p>
                    </div>
                    <RiskBadge level={i.risk_level} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <Card title="System status">
          <ul className="divide-y divide-slate-100" data-testid="system-status">
            <StatusRow name="Backend" state="ok" detail={`Online · v${sys.backend.version}`} />
            <StatusRow name="Risk Engine" state="ok" detail={`${sys.risk_engine.engine_version} · ${sys.risk_engine.mode}`} />
            <StatusRow name="AI extraction" state={ai.state} detail={ai.label} />
            <StatusRow name="Attachment analyzer" state="ok" detail={sys.attachment_analyzer.mode} />
          </ul>
        </Card>
      </div>
      <p className="mt-6 text-xs text-slate-500">{data.note}</p>
    </>
  );
}

export default function Dashboard() {
  const { data, error, loading, reload } = useAsync((signal) => api.getDashboard(signal), []);
  return (
    <>
      <PageHeader
        eyebrow="Analyst command center"
        title="Detect the Trust Break — before the payment."
        subtitle="Trust & Transaction Risk Intelligence: correlate identity, channel, financial behaviour, beneficiary, social engineering and attachment evidence, then verify independently before money moves."
        actions={
          <>
            <ButtonLink to="/scenarios" variant="secondary">Load a scenario</ButtonLink>
            <ButtonLink to="/incidents/new">New incident</ButtonLink>
          </>
        }
      />
      {loading && <LoadingState label="Loading dashboard…" rows={5} />}
      {error && <ErrorState error={error} onRetry={reload} title="Could not load the dashboard" />}
      {data && <DashboardView data={data.data} />}
    </>
  );
}
