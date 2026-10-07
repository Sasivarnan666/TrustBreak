/** Display helpers for Risk Engine 2.0 signals (pure; no fetching).
 *  Pre-2.0 stored assessments have no `group`/`analyzer` and use fine-grained category names and the sources
 *  message | behaviour | attachment; they are shown as a single "Indicators" list so they stay readable. */

export const CATEGORY_ORDER = [
  "IDENTITY",
  "COMMUNICATION",
  "FINANCIAL",
  "BENEFICIARY",
  "BEHAVIOUR",
  "SOCIAL_ENGINEERING",
  "ATTACHMENT",
];

export const CATEGORY_LABELS = {
  IDENTITY: "Identity",
  COMMUNICATION: "Communication",
  FINANCIAL: "Financial",
  BENEFICIARY: "Beneficiary",
  BEHAVIOUR: "Behaviour",
  SOCIAL_ENGINEERING: "Social engineering",
  ATTACHMENT: "Attachment",
};

/** Where the evidence came from. Never relabel: "fallback" is deterministic rules used because AI failed. */
export const SOURCE_LABELS = {
  rule: "Rule",
  synthetic_baseline: "Synthetic behavioural baseline",
  AI: "AI",
  fallback: "Fallback (not AI)",
  attachment_static: "Static attachment analysis",
  system: "System",
  // pre-2.0 assessments
  message: "Message",
  behaviour: "Behaviour",
  attachment: "Attachment",
};

export const SOURCE_TONE = {
  AI: "brand",
  fallback: "amber",
};

export function isRiskEngineV2Signal(signal) {
  return CATEGORY_ORDER.includes(signal?.category);
}

/** Group signals by category in a fixed order. Returns [{ key, label, points, signals, legacy }]. */
export function groupSignalsByCategory(signals = []) {
  const known = signals.filter(isRiskEngineV2Signal);
  const legacy = signals.filter((s) => !isRiskEngineV2Signal(s));
  const groups = CATEGORY_ORDER.map((key) => {
    const items = known.filter((s) => s.category === key);
    return { key, label: CATEGORY_LABELS[key], points: items.reduce((n, s) => n + s.points, 0), signals: items, legacy: false };
  }).filter((g) => g.signals.length > 0);
  if (legacy.length > 0) {
    groups.push({
      key: "LEGACY",
      label: "Indicators (assessment from an earlier engine version)",
      points: legacy.reduce((n, s) => n + s.points, 0),
      signals: legacy,
      legacy: true,
    });
  }
  return groups;
}

export function confidenceLabel(confidence) {
  return confidence ? `${confidence} confidence` : null;
}
