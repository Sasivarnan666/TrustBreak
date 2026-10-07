/** Thin fetch wrapper. Every backend response uses the same JSON envelope:
 *  success: { success: true,  data, meta? }
 *  failure: { success: false, error: { code, message, details: [{ field, message }] } }
 */

export class ApiError extends Error {
  constructor(code, message, status = 0, details = []) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

async function request(path, { method = "GET", body, signal } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      signal,
      // FormData sets its own multipart Content-Type (with boundary).
      headers: body && !(body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
      body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    if (err?.name === "AbortError") throw err;
    throw new ApiError(
      "network_error",
      "Cannot reach the TrustBreak API. Check that the backend is running on port 8000.",
    );
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    /* non-JSON body (e.g. proxy error page) - handled below */
  }

  if (!response.ok || !payload || payload.success !== true) {
    const error = payload?.error;
    throw new ApiError(
      error?.code ?? "http_error",
      error?.message ?? `The server returned an unexpected response (HTTP ${response.status}).`,
      response.status,
      error?.details ?? [],
    );
  }
  return payload;
}

export const api = {
  listIncidents: ({ limit = 500, offset = 0 } = {}, signal) =>
    request(`/api/incidents?limit=${limit}&offset=${offset}`, { signal }),
  riskSummary: (signal) => request("/api/incidents/risk-summary", { signal }),
  caseSummary: (signal) => request("/api/incidents/case-summary", { signal }),
  getIncident: (id, signal) => request(`/api/incidents/${encodeURIComponent(id)}`, { signal }),
  createIncident: (payload) => request("/api/incidents", { method: "POST", body: payload }),
  // Analyst decision: a workflow / audit record only. body = { decision: "VERIFIED"|"REJECTED", reason, analyst_name, assessment_id? }.
  recordDecision: (id, body) =>
    request(`/api/incidents/${encodeURIComponent(id)}/decision`, { method: "POST", body }),
  // v0.8.0: immutable assessment history. The list is summaries (v1..vN); a version returns its full evidence.
  listAssessments: (id, signal) => request(`/api/incidents/${encodeURIComponent(id)}/assessments`, { signal }),
  getAssessment: (id, version, signal) =>
    request(`/api/incidents/${encodeURIComponent(id)}/assessments/${encodeURIComponent(version)}`, { signal }),
  // v0.9.0: synthetic trusted identities (read-only) and the evidence / trust graph of one incident.
  listIdentities: (signal) => request("/api/identities", { signal }),
  getIdentity: (id, signal) => request(`/api/identities/${encodeURIComponent(id)}`, { signal }),
  getTrustGraph: (id, signal) => request(`/api/incidents/${encodeURIComponent(id)}/trust-graph`, { signal }),
  analyzeMessage: (id, signal) =>
    request(`/api/incidents/${encodeURIComponent(id)}/analyze-message`, { method: "POST", signal }),
  analyzeBehaviour: (id, signal) =>
    request(`/api/incidents/${encodeURIComponent(id)}/analyze-behaviour`, { method: "POST", signal }),
  analyzeAttachment: (id, file, signal) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/api/incidents/${encodeURIComponent(id)}/analyze-attachment`, { method: "POST", body: form, signal });
  },
  // The attachment file is optional: without it the assessment has no attachment evidence.
  analyzeRisk: (id, file, signal) => {
    let body;
    if (file) {
      body = new FormData();
      body.append("file", file);
    }
    return request(`/api/incidents/${encodeURIComponent(id)}/analyze-risk`, { method: "POST", body, signal });
  },
  // 0.13.0
  getCounterfactuals: (id, signal) => request(`/api/incidents/${encodeURIComponent(id)}/counterfactuals`, { signal }),
  getVerification: (id, signal) => request(`/api/incidents/${encodeURIComponent(id)}/verification`, { signal }),
  // body = { action: "START"|"CONFIRM"|"FAIL", method?, reason, analyst_name }
  recordVerification: (id, body) =>
    request(`/api/incidents/${encodeURIComponent(id)}/verification`, { method: "POST", body }),
  getTimeline: (id, signal) => request(`/api/incidents/${encodeURIComponent(id)}/timeline`, { signal }),
  listScenarios: (signal) => request("/api/scenarios", { signal }),
  loadScenario: (scenarioId) => request(`/api/scenarios/${encodeURIComponent(scenarioId)}/load`, { method: "POST" }),
  getDashboard: (signal) => request("/api/dashboard", { signal }),
};

/** Printable report (server-rendered HTML; opens in a new tab). */
export const reportUrl = (id) => `/api/incidents/${encodeURIComponent(id)}/report`;
