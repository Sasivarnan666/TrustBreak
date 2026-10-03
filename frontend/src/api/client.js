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
  // Analyst decision: a workflow / audit record only. body = { decision: "VERIFIED"|"REJECTED", reason, analyst_name }.
  recordDecision: (id, body) =>
    request(`/api/incidents/${encodeURIComponent(id)}/decision`, { method: "POST", body }),
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
};
