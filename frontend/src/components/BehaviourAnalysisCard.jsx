import { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { Tag } from "./StatusBadge.jsx";
import { Button, Card, DataRow } from "./ui.jsx";

const SEVERITY = {
  high: { icon: "🔴", cls: "border-red-200 bg-red-50 text-red-900" },
  medium: { icon: "🟠", cls: "border-amber-300 bg-amber-50 text-amber-900" },
};
const TITLES = { amount: "Amount anomaly", beneficiary: "New beneficiary", channel: "Channel anomaly" };

function Status({ ok, okText, badText, badIcon = "🔴" }) {
  return ok ? (
    <span className="text-emerald-700">✓ {okText}</span>
  ) : (
    <span className={badIcon === "🔴" ? "text-red-700" : "text-amber-700"}>
      {badIcon === "🔴" ? "🔴" : "⚠"} {badText}
    </span>
  );
}

const notChecked = <span className="font-normal text-slate-400">Not evaluated</span>;

/** Pure view of one behaviour-analysis result (no fetching). */
export function BehaviourAnalysisView({ analysis }) {
  const { checks = {}, anomalies = [] } = analysis;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tag tone="amber">Behavioural signals</Tag>
        <Tag>Synthetic demo profile</Tag>
        {analysis.employee_id && <Tag>{analysis.employee_id}</Tag>}
      </div>

      <p className="mb-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
        These are deviations from the sender&apos;s usual behaviour. They are <strong>not</strong> a fraud verdict or risk score.
      </p>

      {!analysis.profile_found ? (
        <p className="text-sm text-slate-600">No behaviour profile exists for this sender, so nothing could be compared.</p>
      ) : (
        <>
          <dl className="divide-y divide-slate-100">
            <DataRow label="Communication channel">
              {checks.channel?.status === "normal" || checks.channel?.status === "unusual" ? (
                <Status ok={checks.channel.status === "normal"} okText="Normal" badText="Unusual" badIcon="⚠" />
              ) : (
                notChecked
              )}
            </DataRow>
            <DataRow label="Payment amount">
              {checks.amount?.status === "within_baseline" || checks.amount?.status === "above_baseline" ? (
                <Status ok={checks.amount.status === "within_baseline"} okText="Within baseline" badText="Above baseline" />
              ) : (
                notChecked
              )}
            </DataRow>
            <DataRow label="Beneficiary">
              {checks.beneficiary?.status === "known" || checks.beneficiary?.status === "new" ? (
                <Status ok={checks.beneficiary.status === "known"} okText="Known" badText="New" />
              ) : (
                notChecked
              )}
            </DataRow>
          </dl>

          <h3 className="mb-2 mt-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Behaviour signals</h3>
          {anomalies.length === 0 ? (
            <p className="text-sm text-slate-600">No deviations from the sender&apos;s profile were found in the checks that ran.</p>
          ) : (
            <ul className="space-y-2">
              {anomalies.map((a) => {
                const s = SEVERITY[a.severity] ?? SEVERITY.medium;
                return (
                  <li key={a.code} className={`rounded-md border px-3 py-2 text-sm ${s.cls}`}>
                    <p className="font-semibold">
                      {s.icon} {TITLES[a.type] ?? a.type}
                    </p>
                    <p className="mt-0.5 text-[13px] leading-relaxed">{a.message}</p>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}

      {analysis.notes?.length > 0 && (
        <ul className="mt-3 list-disc space-y-0.5 pl-5 text-xs text-slate-500">
          {analysis.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Card with a button that requests the analysis on demand. */
export default function BehaviourAnalysisCard({ incidentId }) {
  const [state, setState] = useState({ status: "idle", analysis: null, error: null });
  const controller = useRef(null);

  useEffect(() => () => controller.current?.abort(), []);

  async function run() {
    controller.current?.abort();
    controller.current = new AbortController();
    setState({ status: "loading", analysis: null, error: null });
    try {
      const res = await api.analyzeBehaviour(incidentId, controller.current.signal);
      setState({ status: "done", analysis: res.data, error: null });
    } catch (error) {
      if (error?.name === "AbortError") return;
      setState({ status: "error", analysis: null, error });
    }
  }

  const busy = state.status === "loading";
  return (
    <Card
      title="Behavioural Analysis"
      aside={
        <Button variant="secondary" onClick={run} disabled={busy}>
          {busy ? "Analyzing…" : state.status === "done" ? "Run again" : "Compare with baseline"}
        </Button>
      }
    >
      {state.status === "idle" && (
        <p className="text-sm text-slate-600">
          Compare the channel, amount and beneficiary with this sender&apos;s usual behaviour (synthetic demo profile). Produces
          signals only, not a fraud decision.
        </p>
      )}
      {busy && (
        <p role="status" className="text-sm text-slate-600">
          Comparing with baseline…
        </p>
      )}
      {state.status === "error" && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {state.error?.message || "The behaviour analysis could not be run."}
          {state.error?.code && <span className="ml-2 font-mono text-xs text-red-700/80">code: {state.error.code}</span>}
        </div>
      )}
      {state.status === "done" && <BehaviourAnalysisView analysis={state.analysis} />}
    </Card>
  );
}
