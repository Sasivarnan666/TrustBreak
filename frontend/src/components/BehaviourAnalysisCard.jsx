import { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { Tag } from "./StatusBadge.jsx";
import { compactINR, formatINR } from "../lib/format.js";
import { Button, Card } from "./ui.jsx";

const SEVERITY = {
  high: { icon: "🔴", cls: "border-red-200 bg-red-50 text-red-900" },
  medium: { icon: "🟠", cls: "border-amber-300 bg-amber-50 text-amber-900" },
};
const TITLES = {
  amount: "Amount",
  beneficiary: "Beneficiary",
  channel: "Channel",
  frequency: "Frequency",
  velocity: "Velocity",
  time: "Time of day",
  day: "Day of week",
  channel_distribution: "Channel distribution",
};
const NOT_ENOUGH = "NOT_ENOUGH_BASELINE_DATA";

const notChecked = <span className="font-normal text-slate-400">Not evaluated</span>;
const cap = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-[8.5rem_1fr] gap-2 py-1.5 text-sm">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-900">{children}</dd>
    </div>
  );
}

function ChannelBars({ distribution, current }) {
  const entries = Object.entries(distribution ?? {});
  if (entries.length === 0) return null;
  return (
    <ul className="space-y-1" aria-label="Historical channel distribution">
      {entries.map(([name, v]) => (
        <li key={name} className="flex items-center gap-2 text-xs">
          <span className="w-16 shrink-0 text-slate-700">{cap(name)}</span>
          <span className="h-2 flex-1 rounded bg-slate-100">
            <span className="block h-2 rounded bg-slate-400" style={{ width: `${Math.round(v.share * 100)}%` }} />
          </span>
          <span className="w-9 text-right tabular-nums text-slate-600">{Math.round(v.share * 100)}%</span>
        </li>
      ))}
      {current && !(current.toLowerCase() in distribution) && (
        <li className="text-xs font-medium text-red-700">
          Current: {current} — 0% of historical activity
        </li>
      )}
    </ul>
  );
}

function EvidenceList({ evidence }) {
  if (!evidence) return null;
  const rows = [];
  if (evidence.requested !== undefined) rows.push(["Requested", formatINR(evidence.requested)]);
  if (evidence.typical_max !== undefined) rows.push(["Typical maximum", formatINR(evidence.typical_max)]);
  if (evidence.ratio_to_typical_max !== undefined) rows.push(["Deviation", `${evidence.ratio_to_typical_max}× typical maximum`]);
  if (evidence.percentile?.label) rows.push(["Historical rank", evidence.percentile.label]);
  if (evidence.observed !== undefined) rows.push(["Observed", String(evidence.observed)]);
  if (evidence.known_beneficiaries) rows.push(["Known beneficiaries", evidence.known_beneficiaries.join(", ")]);
  if (evidence.normal_channels) rows.push(["Normal channels", evidence.normal_channels.map(cap).join(", ")]);
  if (evidence.absent_from_history) rows.push(["Historical presence", "Not present in this identity's historical activity"]);
  if (evidence.working_hours) rows.push(["Working hours", evidence.working_hours]);
  if (evidence.share !== undefined) rows.push(["Historical share", `${Math.round(evidence.share * 100)}%`]);
  if (evidence.requests_last_7_days !== undefined) rows.push(["Last 7 days", `${evidence.requests_last_7_days} (historical max ${evidence.historical_weekly_max})`]);
  if (evidence.requests_in_window !== undefined) rows.push(["In window", `${evidence.requests_in_window} within ${evidence.window_minutes} min (historical max ${evidence.historical_max_in_window})`]);
  return (
    <dl className="mt-2 space-y-0.5 border-t border-black/10 pt-2 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <dt className="w-32 shrink-0 opacity-70">{k}</dt>
          <dd className="font-medium">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Pure view of one behaviour-analysis result (no fetching). */
export function BehaviourAnalysisView({ analysis }) {
  const { checks = {}, anomalies = [], baseline = null } = analysis;
  const summary = analysis.profile_summary;
  const amount = checks.amount?.status === "within_baseline" || checks.amount?.status === "above_baseline" ? checks.amount : null;
  const channel = checks.channel?.status === "normal" || checks.channel?.status === "unusual" ? checks.channel : null;
  const bene = checks.beneficiary?.status === "known" || checks.beneficiary?.status === "new" ? checks.beneficiary : null;
  const flagged = (type) => anomalies.some((a) => a.type === type);
  const bad = "font-semibold text-red-700";
  const notEnough = ["channel_distribution", "frequency", "velocity"].filter((k) => checks[k]?.status === NOT_ENOUGH);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tag tone="amber">Behavioural signals</Tag>
        <Tag>Synthetic behavioural baseline</Tag>
        {analysis.employee_id && <Tag>{analysis.employee_id}</Tag>}
      </div>

      <p className="mb-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
        Fictional demo history, not real enterprise data. These are deviations from the sender&apos;s usual behaviour, <strong>not</strong> a
        fraud verdict or risk score.
      </p>

      {!analysis.profile_found ? (
        <p className="text-sm text-slate-600">No behaviour profile exists for this sender, so nothing could be compared.</p>
      ) : (
        <>
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Behavioural baseline</h3>
          <dl className="divide-y divide-slate-100">
            <Row label="Typical amount">
              {amount ? `${compactINR(amount.typical_min)}–${compactINR(amount.typical_max)}` : notChecked}
            </Row>
            <Row label="Current amount">
              {amount ? (
                <span className={flagged("amount") ? bad : ""}>
                  {formatINR(amount.requested)}
                  {amount.ratio_to_typical_max > 1 && ` · ${amount.ratio_to_typical_max}× typical maximum`}
                  {amount.percentile?.label && <span className="block text-xs font-normal text-slate-500">{amount.percentile.label}</span>}
                </span>
              ) : (
                notChecked
              )}
            </Row>
            <Row label="Normal channels">{channel ? channel.normal_channels.map(cap).join(", ") : notChecked}</Row>
            <Row label="Current channel">
              {channel ? <span className={channel.status === "unusual" ? bad : ""}>{channel.channel}</span> : notChecked}
              {channel?.absent_from_history && (
                <span className="block text-xs font-normal text-slate-500">
                  {channel.channel} was not present in this identity&apos;s historical financial activity.
                </span>
              )}
            </Row>
            {channel?.historical_distribution && (
              <Row label="Channel history">
                <ChannelBars distribution={channel.historical_distribution} current={channel.status === "unusual" ? channel.channel : null} />
              </Row>
            )}
            <Row label="Known beneficiaries">{bene ? bene.known_beneficiaries.join(", ") : notChecked}</Row>
            <Row label="Current beneficiary">
              {bene ? <span className={bene.status === "new" ? bad : ""}>{bene.beneficiary}</span> : notChecked}
            </Row>
            <Row label="Working hours">{summary?.working_hours ?? notChecked}</Row>
            <Row label="Historical activity">
              {summary?.historical_activity_count ? `${summary.historical_activity_count} synthetic events` : "None available"}
              {baseline?.amount && (
                <span className="block text-xs font-normal text-slate-500">
                  Median {formatINR(baseline.amount.median)} · 95th percentile {formatINR(baseline.amount.p95)} · about{" "}
                  {baseline.frequency.per_week_mean}/week
                </span>
              )}
            </Row>
          </dl>

          <h3 className="mb-2 mt-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Detected deviations</h3>
          {anomalies.length === 0 ? (
            <p className="text-sm text-slate-600">No deviations from the sender&apos;s baseline were found in the checks that ran.</p>
          ) : (
            <ul className="space-y-2">
              {anomalies.map((a) => {
                const s = SEVERITY[a.severity] ?? SEVERITY.medium;
                return (
                  <li key={a.code} className={`rounded-md border px-3 py-2 text-sm ${s.cls}`}>
                    <details>
                      <summary className="cursor-pointer font-semibold">
                        {s.icon} {TITLES[a.type] ?? a.type} <span className="font-mono text-[11px] font-normal opacity-70">{a.code}</span>
                      </summary>
                      <p className="mt-1 text-[13px] leading-relaxed">{a.message}</p>
                      <EvidenceList evidence={a.evidence} />
                      {a.source && <p className="mt-1 text-[11px] opacity-70">Source: {a.source.replace("_", " ")}</p>}
                    </details>
                  </li>
                );
              })}
            </ul>
          )}

          {notEnough.length > 0 && (
            <p className="mt-3 text-xs text-slate-500">
              Not enough baseline data for: {notEnough.map((k) => TITLES[k]).join(", ")}. No anomaly is inferred.
            </p>
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
          Compare the channel, amount, beneficiary and timing with this sender&apos;s synthetic behavioural baseline. Produces
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
