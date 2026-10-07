"""Printable incident report (0.13.0): one self-contained HTML document (no scripts, no external assets).

Pure rendering of data the API already holds. EVERY dynamic value is HTML-escaped: the message, sender names and
analyst notes are untrusted text. The report contains no secrets and no API keys; it only repeats persisted evidence.
Print it from the browser ("Save as PDF").
"""

from datetime import datetime, timezone
from html import escape as _e

from .risk_correlation import rules

METHODOLOGY = (
    "TrustBreak provides deterministic prototype decision support. Risk scores are heuristic and are not probabilities of fraud.",
    "Attachment analysis is static structural analysis and does not establish malware presence. Files are never executed or opened.",
    "The behavioural baseline is synthetic demo data, not a record of real activity.",
    "The system assessment, the independent verification record and the analyst's final case decision are separate records. "
    "TrustBreak never blocks, approves or executes a payment.",
    "AI (when available) only extracts structured fields from the message; all scoring is done by the deterministic Risk Engine. "
    "The extraction mode used is shown in the evidence section.",
    "Counterfactuals are deterministic simulations using the same Risk Engine. They do not modify the incident or assessment history.",
)
ACTION_TEXT = {"PROCEED": "Proceed", "VERIFY": "Verify before paying", "HOLD_PAYMENT": "Hold payment"}
AI_STATE = {"ai": "AI analysis", "fallback": "Deterministic fallback (AI unavailable)", "mock": "Deterministic demo mode (not AI)",
            "skipped": "Skipped"}

_CSS = """
:root{color-scheme:light}*{box-sizing:border-box}
body{font:14px/1.5 -apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#0f172a;background:#f1f5f9;margin:0}
main{max-width:900px;margin:24px auto;background:#fff;padding:36px 44px;border:1px solid #cbd5e1}
h1{font-size:22px;margin:0 0 2px}h2{font-size:15px;margin:26px 0 8px;padding-bottom:4px;border-bottom:1px solid #cbd5e1;text-transform:uppercase;letter-spacing:.06em;color:#1e293b}
.sub{color:#475569;font-size:12px}.banner{border:1px solid #f59e0b;background:#fffbeb;color:#78350f;padding:8px 12px;margin:14px 0;font-size:13px}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px}
table{border-collapse:collapse;width:100%;margin:6px 0;font-size:12.5px}th,td{border:1px solid #cbd5e1;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#f1f5f9;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#475569}
.kv td:first-child{width:200px;color:#475569;background:#f8fafc}
blockquote{margin:6px 0;padding:8px 12px;border-left:3px solid #94a3b8;background:#f8fafc;white-space:pre-wrap}
.pill{display:inline-block;padding:1px 8px;border:1px solid #94a3b8;font-weight:600;font-size:12px}
.CRITICAL{border-color:#dc2626;color:#991b1b;background:#fef2f2}.HIGH{border-color:#ea580c;color:#9a3412;background:#fff7ed}
.MEDIUM{border-color:#d97706;color:#92400e;background:#fffbeb}.LOW{border-color:#16a34a;color:#166534;background:#f0fdf4}
.note{color:#475569;font-size:12px;margin:4px 0}.bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
button{font:inherit;padding:6px 12px;border:1px solid #1e3a5f;background:#1e3a5f;color:#fff;cursor:pointer}
@media print{body{background:#fff}main{margin:0;border:0;padding:0;max-width:none}.noprint{display:none}h2{break-after:avoid}table,blockquote{break-inside:avoid}}
"""


def _t(headers, rows):
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _kv(pairs):
    return "<table class='kv'><tbody>" + "".join(f"<tr><td>{_e(k)}</td><td>{v}</td></tr>" for k, v in pairs) + "</tbody></table>"


def _inr(n):
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return "INR " + s


def _pill(level):
    return f"<span class='pill {_e(str(level))}'>{_e(str(level))}</span>"


def _when(ts):
    return _e(ts) if ts else "no timestamp recorded"


def render_report(d: dict) -> str:
    inc, a = d["incident"], d.get("assessment")
    synthetic = bool(inc.get("is_synthetic"))
    sender = inc["sender"]
    sigs = (a or {}).get("signals") or []
    se = [s for s in sigs if s.get("category") == rules.SOCIAL_ENGINEERING]
    beh = [s for s in sigs if s.get("analyzer") == "behaviour" or s.get("category") in (rules.BEHAVIOUR,)]
    att = [s for s in sigs if s.get("category") == rules.ATTACHMENT]
    dims = sorted({s["category"] for s in sigs if s.get("points", 0) > 0}) if a and a["risk_level"] != "LOW" else []
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>TrustBreak incident report {_e(inc['reference'])}</title><style>{_CSS}</style></head><body><main>"]
    out.append("<div class='bar noprint'><span class='sub'>Printable report - use your browser's Print / Save as PDF.</span>"
               "<button type='button' onclick='window.print()'>Print / Save as PDF</button></div>")
    out.append("<h1>TRUSTBREAK INCIDENT REPORT</h1><div class='sub'>Trust &amp; Transaction Risk Intelligence · Detect the Trust Break — before the payment.</div>")
    out.append(_kv([("Incident reference", f"<span class='mono'>{_e(inc['reference'])}</span>"),
                    ("Incident title", _e(inc["title"])),
                    ("Incident created", _when(inc["created_at"])),
                    ("Report generated (UTC)", _e(d["generated_at"])),
                    ("TrustBreak version", _e(d["version"]))]))
    if synthetic:
        out.append(f"<div class='banner'><b>SYNTHETIC / DEMO DATA.</b> This incident was created from the demo scenario "
                   f"<span class='mono'>{_e(str(inc.get('scenario_id')))}</span>. All people, organisations, amounts, messages and files are fictional. "
                   "It is not a real incident.</div>")
    else:
        out.append("<div class='banner'>Prototype data. The behavioural baseline used for comparison is synthetic.</div>")

    out.append("<h2>1. Executive summary</h2>")
    if a:
        trust = "TRUST BREAK DETECTED. " if a["trust_break_detected"] else ""
        out.append(f"<p><b>{_e(trust)}</b>{_e(a['explanation'])}</p>")
        out.append(_kv([("System risk assessment", f"{_pill(a['risk_level'])} &nbsp;{_e(str(a['risk_score']))} / {_e(str(a['max_score']))} (prototype heuristic score)"),
                        ("Recommended action", f"{_e(ACTION_TEXT.get(a['recommended_action'], a['recommended_action']))} - independent verification recommended"
                         if a["recommended_action"] != "PROCEED" else "Proceed - follow your normal approval process"),
                        ("Trust dimensions affected", _e(f"{len(dims)}: " + ", ".join(rules.CATEGORY_LABELS[c] for c in dims)) if dims else "None"),
                        ("Analyst case status", _e(inc["workflow_status_label"]))]))
    else:
        out.append("<p>No risk assessment has been run for this incident. Sections that depend on it are marked unavailable.</p>")

    out.append("<h2>2. Trusted identity</h2>")
    ident = (d.get("trust_graph") or {}).get("identity")
    if ident:
        out.append(_kv([("Name / ID", _e(f"{ident['display_name']} / {ident['identity_id']}")), ("Role", _e(ident["role"])),
                        ("Organisation", _e(ident.get("organization") or "—")),
                        ("Trusted channels", _e(", ".join(ident.get("trusted_channels", [])) or "—")),
                        ("Resolved by", _e(str(d["trust_graph"]["identity_source"]).replace("_", " ")))]))
    else:
        out.append(f"<p>{_e(sender['name'])} is not linked to a trusted identity, so no baseline comparison was possible.</p>")

    out.append("<h2>3. Observed request</h2>")
    pay = inc["payment"]
    out.append(_kv([("Sender", _e(f"{sender['name']} ({sender['role']})")), ("Channel", _e(inc["channel"])),
                    ("Amount", _e(_inr(pay["amount"]))),
                    ("Beneficiary", _e(pay["beneficiary_name"]) + (" (new)" if pay["beneficiary_is_new"] else " (existing)")),
                    ("Received (as reported)", _when(inc.get("received_at")))]))
    out.append("<p class='note'>Original message, unaltered:</p>")
    out.append(f"<blockquote>{_e(inc['message'])}</blockquote>")

    out.append("<h2>4. Behaviour baseline</h2>")
    rows = (d.get("trust_graph") or {}).get("comparison") or []
    if rows:
        out.append(_t(["Aspect", "Expected (synthetic baseline)", "Observed", "Status"],
                      [[_e(r["aspect"].title()), _e(str(r["expected"])), _e(str(r["observed"])), _e(str(r["status"]).replace("_", " "))] for r in rows]))
    if beh:
        out.append(_t(["Baseline deviation", "Points", "Evidence"],
                      [[_e(s["title"]), _e(f"+{s['points']}"), _e(s.get("evidence") or s["message"])] for s in beh]))
    elif a:
        out.append("<p>No behavioural deviations were scored.</p>")

    out.append("<h2>5. Social-engineering indicators</h2>")
    out.append(_t(["Indicator", "Points", "Source", "Evidence"],
                  [[_e(s["title"]), _e(f"+{s['points']}"), _e(rules.SOURCE_LABELS.get(s["source"], s["source"])), _e(s.get("evidence") or s["message"])] for s in se])
                if se else "<p>No social-engineering indicators were scored.</p>")

    out.append("<h2>6. Attachment findings</h2>")
    att_meta = inc.get("attachment")
    if att_meta:
        out.append(_kv([("File", f"<span class='mono'>{_e(att_meta['name'])}</span>"), ("Type", _e(att_meta.get("content_type") or "—")),
                        ("Reported size (bytes)", _e(str(att_meta.get("size_bytes") if att_meta.get("size_bytes") is not None else "—")))]))
        if d.get("scenario_archive"):
            out.append("<p class='note'>Synthetic archive listing (demo scenario): " + ", ".join(f"<span class='mono'>{_e(n)}</span>" for n in d["scenario_archive"]) + "</p>")
        out.append(_t(["Finding", "Points", "Detail"], [[_e(s["title"]), _e(f"+{s['points']}"), _e(s["message"] + (" Files: " + ", ".join(s["details"]) if s.get("details") else ""))] for s in att])
                    if att else "<p>No attachment findings were scored (the file may not have been analysed in the assessment run).</p>")
    else:
        out.append("<p>No attachment was reported with this request.</p>")
    out.append("<p class='note'>Static structural analysis only. Nothing was executed, extracted or stored, and no malware verdict is made.</p>")

    out.append("<h2>7. Risk assessment</h2>")
    if a:
        out.append(_kv([("Score / level", f"{_e(str(a['risk_score']))} / {_pill(a['risk_level'])}"), ("Raw points", _e(str(a["raw_points"]))),
                        ("Recommended action", _e(a["recommended_action_label"])), ("Engine version", _e(str(a.get("engine_version")))),
                        ("Assessment", _e(f"v{a.get('version_number')} at {a.get('assessed_at')}"))]))
        out.append(_t(["Category", "Points"], [[_e(rules.CATEGORY_LABELS.get(k, k)), _e(f"+{v}")] for k, v in (a.get("category_points") or {}).items()]))
        for n in a.get("notes") or []:
            out.append(f"<p class='note'>{_e(n)}</p>")
        out.append(f"<p class='note'>{_e(a['disclaimer'])}</p>")
    else:
        out.append("<p>Unavailable: no assessment has been run.</p>")

    out.append("<h2>8. Evidence and provenance</h2>")
    if a:
        msg = (a.get("inputs") or {}).get("message") or {}
        out.append(f"<p class='note'>Message extraction: {_e(AI_STATE.get(msg.get('analysis_state'), msg.get('status', 'unknown')))}"
                   f"{' - ' + _e(msg['detail']) if msg.get('detail') else ''}</p>")
        out.append(_t(["Signal", "Category", "Points", "Severity", "Source", "Evidence", "Why it matters"],
                      [[_e(s["title"]), _e(rules.CATEGORY_LABELS.get(s["category"], s["category"])), _e(f"+{s['points']}"), _e(s["severity"]),
                        _e(rules.SOURCE_LABELS.get(s["source"], s["source"])), _e(s.get("evidence") or "—"), _e(s.get("why") or s["message"])] for s in sigs]))
    else:
        out.append("<p>Unavailable.</p>")

    out.append("<h2>9. Counterfactual analysis</h2>")
    cf = d.get("counterfactuals") or {}
    if cf.get("available"):
        cur = cf["current"]
        out.append(f"<p>Current: <b>{_e(str(cur['risk_score']))} {_e(cur['risk_level'])}</b></p>")
        out.append(_t(["What-if", "Score", "Delta", "Level", "Raw points"],
                      [[_e(c["label"]), _e(f"{c['original_score']} → {c['new_score']}"), _e(f"{c['score_delta']:+d}"),
                        _e(f"{c['original_level']} → {c['new_level']}"), _e(f"{c['original_raw_points']} → {c['new_raw_points']}")] for c in cf["counterfactuals"]]))
        if cf.get("largest_reduction"):
            lr = cf["largest_reduction"]
            out.append(f"<p>Largest single reduction: <b>{_e(lr['label'])}</b> (score {_e(f'{lr['score_delta']:+d}')}, raw points {_e(f'{lr['raw_delta']:+d}')}).</p>")
        if cf.get("smallest_downgrade"):
            sd = cf["smallest_downgrade"]
            out.append(f"<p>Smallest combination that lowers the level: {_e(' + '.join(sd['labels']))} → {_e(str(sd['new_score']))} {_e(sd['new_level'])}.</p>")
        for n in cf.get("notes") or []:
            out.append(f"<p class='note'>{_e(n)}</p>")
    else:
        out.append(f"<p>Unavailable: {_e(cf.get('reason') or 'no assessment')}</p>")
    out.append(f"<p class='note'>{_e(cf.get('disclaimer') or 'Counterfactuals are deterministic simulations using the same Risk Engine. They do not modify the incident or assessment history.')}</p>")

    out.append("<h2>10. Verification history</h2>")
    ver = d.get("verification") or {}
    out.append(f"<p>Current state: <b>{_e(ver.get('state_label', 'Not started'))}</b>. Recorded separately from the risk assessment and from the final case decision.</p>")
    out.append(_t(["Time", "Event", "Method", "Analyst", "Reason"],
                  [[_when(v["created_at"]), _e(v["event_label"]), _e(v.get("method_label") or "—"), _e(v["analyst_name"]), _e(v["reason"])] for v in ver.get("events", [])])
                if ver.get("events") else "<p>No verification has been recorded.</p>")

    out.append("<h2>11. Forensic timeline</h2>")
    out.append(_t(["Timestamp", "Event", "Source", "Explanation"],
                  [[_when(e["timestamp"]), _e(e["event"]), _e(e["source"]), _e(e["explanation"])] for e in d.get("timeline", [])]))
    out.append("<p class='note'>Built only from persisted records; no timestamp is invented.</p>")

    out.append("<h2>12. Assessment history</h2>")
    out.append(_t(["Version", "Assessed at", "Score", "Level", "System recommendation", "Engine"],
                  [[_e(f"v{h['version_number']}"), _e(h["assessed_at"]), _e(str(h["risk_score"])), _pill(h["risk_level"]),
                    _e(h["recommended_action_label"]), _e(h["engine_version"])] for h in d.get("history", [])])
                if d.get("history") else "<p>No assessments recorded.</p>")
    out.append("<p class='note'>Every run is an immutable version. These are system assessments, not analyst decisions.</p>")

    out.append("<h2>13. Analyst decision</h2>")
    decisions = [c for c in inc["case_history"] if c["decision"] != "CASE_OPENED"]
    if decisions:
        out.append(_t(["Time", "Decision", "Analyst", "Reason", "Based on"],
                      [[_when(c["created_at"]), _e(c["new_status"]), _e(c.get("analyst_name") or "—"), _e(c["reason"]),
                        _e(f"assessment v{c['assessment_number']} ({c['assessment_risk_score']} {c['assessment_risk_level']})" if c.get("assessment_number") else "no assessment")]
                       for c in decisions]))
    else:
        out.append("<p>No analyst decision has been recorded. The case is open.</p>")

    out.append("<h2>14. Limitations / methodology</h2><ul>" + "".join(f"<li>{_e(m)}</li>" for m in METHODOLOGY) + "</ul>")
    out.append("</main></body></html>")
    return "".join(out)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
