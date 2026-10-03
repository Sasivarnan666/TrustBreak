import { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { Tag } from "./StatusBadge.jsx";
import { Button, Card, DataRow } from "./ui.jsx";

const INTENT_LABELS = {
  payment_transfer: "Payment transfer",
  invoice_payment: "Invoice payment",
  gift_card_purchase: "Gift card purchase",
  credential_or_otp_request: "Credential / OTP request",
  bank_detail_change: "Bank detail change",
  other_financial: "Other financial",
  none: "No financial intent found",
};

function formatAmount(amount, currency) {
  if (amount == null) return null;
  const n = Number(amount).toLocaleString("en-IN");
  if (currency === "INR") return `₹${n}`;
  return currency ? `${currency} ${n}` : n;
}

const PROVIDER_LABELS = { gemini: "Gemini", anthropic: "Anthropic", mock: "Demo" };
const providerLabel = (p) => PROVIDER_LABELS[p] ?? (p ? p.charAt(0).toUpperCase() + p.slice(1) : "AI");

const dash = <span className="font-normal text-slate-400">Not stated</span>;
const orDash = (value) => (value == null || value === "" ? dash : value);

/** Pure view of one message-analysis result (no fetching). */
export function MessageAnalysisView({ analysis }) {
  const { extraction: x, mode } = analysis;
  const isAi = mode === "ai";
  const isMock = mode === "mock";
  // An AI provider was wanted but the rule-based demo extractor ran instead.
  const isFallback = isMock && analysis.is_fallback === true;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {isAi && <Tag tone="brand">AI analysis · {providerLabel(analysis.provider)}</Tag>}
        {isAi && analysis.model && <Tag>{analysis.model}</Tag>}
        {isFallback && <Tag tone="amber">{providerLabel(analysis.requested_provider)} unavailable · using demo extraction</Tag>}
        {isFallback && <Tag>Rule-based, not AI</Tag>}
        {isMock && !isFallback && <Tag tone="amber">Demo mode · rule-based, not AI</Tag>}
        {mode === "skipped" && <Tag>Nothing to analyze</Tag>}
        <Tag>Extracted information only</Tag>
      </div>

      <p className="mb-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
        These are details extracted from the message text. This is <strong>not</strong> a fraud decision or risk score;
        risk is calculated separately by TrustBreak's deterministic engine.
      </p>

      {analysis.fallback_reason && (
        <p className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
          {analysis.fallback_reason}
        </p>
      )}

      <dl className="divide-y divide-slate-100">
        <DataRow label="Claimed authority">{orDash(x.claimed_authority)}</DataRow>
        <DataRow label="Requested action">{orDash(x.requested_action)}</DataRow>
        <DataRow label="Amount">
          {x.payment_amount != null ? <span className="tabular-nums">{formatAmount(x.payment_amount, x.currency)}</span> : dash}
        </DataRow>
        <DataRow label="Beneficiary">{orDash(x.beneficiary)}</DataRow>
        <DataRow label="Urgency">
          <span className="capitalize">{x.urgency_level}</span>
        </DataRow>
        <DataRow label="Secrecy requested">{x.secrecy_indicator ? "Yes" : "No"}</DataRow>
        <DataRow label="Organization">{orDash(x.organization)}</DataRow>
        <DataRow label="Deadline">{orDash(x.deadline)}</DataRow>
        <DataRow label="Financial intent">{INTENT_LABELS[x.financial_intent] ?? x.financial_intent}</DataRow>
        <DataRow label="Confidence">
          <span className="tabular-nums">{Math.round(x.confidence * 100)}%</span>
          {isMock && <span className="ml-2 text-xs font-normal text-slate-500">(rule coverage, not model certainty)</span>}
        </DataRow>
      </dl>

      {x.extracted_entities.length > 0 && (
        <div className="mt-3">
          <p className="mb-1.5 text-xs text-slate-500">Entities found in the text</p>
          <div className="flex flex-wrap gap-1.5">
            {x.extracted_entities.map((entity, i) => (
              <Tag key={`${entity.type}-${i}`}>
                {entity.type}: {entity.value}
              </Tag>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Card with a button that requests the analysis on demand. */
export default function MessageAnalysisCard({ incidentId }) {
  const [state, setState] = useState({ status: "idle", analysis: null, error: null });
  const controller = useRef(null);

  useEffect(() => () => controller.current?.abort(), []);

  async function run() {
    controller.current?.abort();
    controller.current = new AbortController();
    setState({ status: "loading", analysis: null, error: null });
    try {
      const res = await api.analyzeMessage(incidentId, controller.current.signal);
      setState({ status: "done", analysis: res.data, error: null });
    } catch (error) {
      if (error?.name === "AbortError") return;
      setState({ status: "error", analysis: null, error });
    }
  }

  const busy = state.status === "loading";
  return (
    <Card
      title="Message Analysis"
      aside={
        <Button variant="secondary" onClick={run} disabled={busy}>
          {busy ? "Analyzing…" : state.status === "done" ? "Run again" : "Extract message details"}
        </Button>
      }
    >
      {state.status === "idle" && (
        <p className="text-sm text-slate-600">
          Extract who is asking, what they want paid, to whom, and how much pressure is used. This is extracted information
          only: the message extractor does not decide risk, and the risk score comes from TrustBreak's deterministic engine.
        </p>
      )}
      {busy && (
        <p role="status" className="text-sm text-slate-600">
          Analyzing message…
        </p>
      )}
      {state.status === "error" && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {state.error?.message || "The message could not be analyzed."}
          {state.error?.code && <span className="ml-2 font-mono text-xs text-red-700/80">code: {state.error.code}</span>}
        </div>
      )}
      {state.status === "done" && <MessageAnalysisView analysis={state.analysis} />}
    </Card>
  );
}
