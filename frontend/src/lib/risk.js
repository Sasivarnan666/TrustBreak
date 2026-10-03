/** Display metadata for risk_status values returned by the API.
 *  Only "needs_review" exists in this build; unknown values fall back to a neutral badge. */
const RISK_STATUS = {
  needs_review: { label: "Needs review", tone: "amber", hint: "Awaiting manual verification" },
};

export function riskMeta(status) {
  return RISK_STATUS[status] ?? { label: status || "Unknown", tone: "slate", hint: "" };
}

export const CHANNELS = ["WhatsApp", "Email", "SMS", "Phone call", "Other"];
