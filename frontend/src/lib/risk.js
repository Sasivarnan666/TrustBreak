/** Display metadata for the persisted risk state returned by the API (v0.6.0).
 *  "Risk level" is TrustBreak's deterministic heuristic assessment; the recommended action is decision support
 *  for a human. Neither is a fraud verdict and nothing is blocked. Incidents without an assessment are
 *  "Not assessed" - the legacy placeholder status is never shown as a risk classification. */
const LEVELS = {
  CRITICAL: { label: "CRITICAL", tone: "red" },
  HIGH: { label: "HIGH", tone: "orange" },
  MEDIUM: { label: "MEDIUM", tone: "amber" },
  LOW: { label: "LOW", tone: "emerald" },
};
const NOT_ASSESSED = { label: "Not assessed", tone: "slate" };

export function riskLevelMeta(level) {
  return LEVELS[level] ?? NOT_ASSESSED;
}

const ACTIONS = {
  PROCEED: { label: "Proceed", icon: "🟢" },
  VERIFY: { label: "Verify before paying", icon: "🟠" },
  HOLD_PAYMENT: { label: "Hold payment", icon: "🔴" },
};

export function recommendedActionMeta(action) {
  return ACTIONS[action] ?? null;
}

export const CHANNELS = ["WhatsApp", "Email", "SMS", "Phone call", "Other"];
