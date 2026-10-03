/** Display metadata for the human case workflow (v0.7.0).
 *
 *  Workflow status is an ANALYST's recorded decision, not something TrustBreak calculated, and it is a different
 *  concept from the risk level. Wording therefore always names the analyst ("Analyst verified the request") and
 *  never says TrustBreak verified, approved, blocked or paid anything. Colours deliberately avoid the red/amber/green
 *  scale used for risk so the two badges are never confused. */
const STATUSES = {
  OPEN: { label: "Open", tone: "sky", meaning: "Awaiting analyst review" },
  VERIFIED: { label: "Verified", tone: "teal", meaning: "Analyst verified the request" },
  REJECTED: { label: "Rejected", tone: "violet", meaning: "Analyst rejected the case" },
};

export function caseStatusMeta(status) {
  return STATUSES[status] ?? { label: status ?? "Unknown", tone: "slate", meaning: "" };
}

const EVENTS = {
  CASE_OPENED: "Case opened",
  VERIFIED: "Analyst verified",
  REJECTED: "Analyst rejected",
};

export function caseEventTitle(entry) {
  return EVENTS[entry.decision] ?? entry.decision_label ?? entry.decision;
}

export const REASON_MIN = 10;
export const REASON_MAX = 1000;
export const ANALYST_MIN = 2;
export const ANALYST_MAX = 80;

/** Mirrors the server rules (the server stays authoritative). Returns { field: message }. */
export function validateDecision({ reason, analystName }) {
  const errors = {};
  const r = reason.trim();
  const a = analystName.trim();
  if (a.length < ANALYST_MIN) errors.analyst_name = `Enter the analyst name (at least ${ANALYST_MIN} characters).`;
  else if (a.length > ANALYST_MAX) errors.analyst_name = `Analyst name must be at most ${ANALYST_MAX} characters.`;
  if (r.length < REASON_MIN) errors.reason = `Explain the decision (at least ${REASON_MIN} characters).`;
  else if (r.length > REASON_MAX) errors.reason = `Reason must be at most ${REASON_MAX} characters.`;
  return errors;
}
