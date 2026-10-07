"""Evidence / trust graph builder (pure, stdlib only, deterministic).

Turns STRUCTURED evidence that already exists (trusted identity, behaviour checks, the stored risk assessment's
signals) into nodes and edges the UI can draw. It decides nothing: it never computes a score, level or action; the
verdict node only repeats what the stored assessment says. Missing evidence is shown as "unknown", never invented.

Ranks are layout hints (0 = top). Statuses: normal | anomalous | info | unknown | verdict.
"""

from typing import Any, Mapping, Optional

_CHANNEL_NAMES = {"email": "Email", "erp": "ERP", "phone call": "Phone call", "whatsapp": "WhatsApp", "sms": "SMS"}


def _origin(signal: dict):
    """Which analyzer a signal came from: `analyzer` (Risk Engine 2.0), else the pre-2.0 `source` value."""
    return signal.get("analyzer") or signal.get("source")


def _inr(amount: int) -> str:
    s = str(abs(int(amount)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return "₹" + s


def _channels(keys) -> str:
    return " / ".join(_CHANNEL_NAMES.get(k, k.title()) for k in keys) or "—"


def _get(obj: Any, *path: str) -> Any:
    for key in path:
        obj = obj.get(key) if isinstance(obj, Mapping) else None
    return obj


def build_comparison(identity: Any, behaviour: Optional[Mapping], channel: str, amount: int, beneficiary: str) -> list[dict]:
    """EXPECTED vs OBSERVED rows. Statuses come from the behaviour checks (the deterministic comparison)."""
    checks = _get(behaviour, "checks") or {}
    if identity is None:
        none = "No trusted identity linked"
        return [
            {"aspect": "channel", "expected": none, "observed": channel, "status": "not_evaluated", "detail": None},
            {"aspect": "beneficiary", "expected": none, "observed": beneficiary, "status": "not_evaluated", "detail": None},
            {"aspect": "amount", "expected": none, "observed": _inr(amount), "status": "not_evaluated", "detail": None},
        ]

    def status(check: str, bad: set) -> str:
        s = _get(checks, check, "status")
        if s in bad:
            return "anomalous"
        return "normal" if s in {"normal", "known", "within_baseline"} else "not_evaluated"

    ratio = f"{amount / identity.typical_amount_max:.2f}× the typical maximum" if identity.typical_amount_max else None
    amount_status = status("amount", {"above_baseline"})
    return [
        {"aspect": "channel", "expected": _channels(identity.normal_channels), "observed": channel,
         "status": status("channel", {"unusual"}), "detail": None},
        {"aspect": "beneficiary", "expected": ", ".join(identity.known_beneficiaries) or "—", "observed": beneficiary,
         "status": status("beneficiary", {"new"}), "detail": None},
        {"aspect": "amount", "expected": f"≤ {_inr(identity.typical_amount_max)}", "observed": _inr(amount),
         "status": amount_status, "detail": ratio if amount_status == "anomalous" else None},
    ]


def build_trust_graph(
    *,
    incident_id: int,
    identity: Any,
    identity_source: str,
    behaviour: Optional[Mapping],
    assessment: Optional[Mapping],
    channel: str,
    amount: int,
    beneficiary: str,
    attachment_name: Optional[str],
) -> dict:
    comparison = build_comparison(identity, behaviour, channel, amount, beneficiary)
    by_aspect = {row["aspect"]: row for row in comparison}
    nodes: list[dict] = []
    edges: list[dict] = []
    notes: list[str] = ["Derived from stored evidence for explanation only; the risk engine and the analyst decide."]

    def node(id_, kind, rank, label, status, source, sublabel=None, detail=None):
        nodes.append({"id": id_, "kind": kind, "rank": rank, "label": label, "sublabel": sublabel,
                      "status": status, "source": source, "detail": detail})

    def edge(src, dst, kind, label=None):
        edges.append({"source": src, "target": dst, "label": label, "kind": kind})

    # ---- rank 0: identity ------------------------------------------------ #
    if identity is not None:
        node("identity", "identity", 0, identity.display_name, "info", "identity_registry",
             sublabel=f"{identity.identity_id} · {identity.role}")
    else:
        node("identity", "identity", 0, "No trusted identity", "unknown", "incident",
             sublabel="Sender not linked to a profile", detail="No baseline exists, so no behavioural comparison was made.")
        notes.append("No trusted identity is linked to this sender, so expected values are unavailable.")

    # ---- rank 1: expected (baseline) ------------------------------------ #
    if identity is not None:
        node("exp_channel", "expected_channel", 1, "Normal channel", "info", "identity_registry", _channels(identity.normal_channels))
        node("exp_amount", "expected_amount", 1, "Typical amount", "info", "identity_registry",
             f"{_inr(identity.typical_amount_min)} – {_inr(identity.typical_amount_max)}")
        node("exp_beneficiary", "expected_beneficiary", 1, "Known beneficiaries", "info", "identity_registry",
             ", ".join(identity.known_beneficiaries))
        for n in ("exp_channel", "exp_amount", "exp_beneficiary"):
            edge("identity", n, "baseline")

    # ---- rank 2: observed ------------------------------------------------ #
    def obs_status(aspect: str) -> str:
        return {"anomalous": "anomalous", "normal": "normal"}.get(by_aspect[aspect]["status"], "unknown")

    node("obs_channel", "observed_channel", 2, channel, obs_status("channel"), "incident", "Observed channel")
    amount_sub = by_aspect["amount"]["detail"] or "Observed amount"
    node("obs_amount", "observed_amount", 2, _inr(amount), obs_status("amount"), "incident", amount_sub)
    ben_sub = {"new": "NEW beneficiary", "known": "Known beneficiary"}.get(_get(behaviour, "checks", "beneficiary", "status"), "Observed beneficiary")
    node("obs_beneficiary", "observed_beneficiary", 2, beneficiary, obs_status("beneficiary"), "incident", ben_sub)
    for exp, obs, aspect in (("exp_channel", "obs_channel", "channel"), ("exp_amount", "obs_amount", "amount"),
                             ("exp_beneficiary", "obs_beneficiary", "beneficiary")):
        st = obs_status(aspect)
        if identity is not None:
            edge(exp, obs, "deviation" if st == "anomalous" else "observed", "deviates" if st == "anomalous" else "matches")
        else:
            edge("identity", obs, "observed", "claimed")

    signals = list(_get(assessment, "signals") or []) if assessment else []
    msg_signals = [s for s in signals if _origin(s) == "message"]
    for s in msg_signals:
        node(f"sig_{s['code']}", "message_signal", 2, s.get("title") or s["code"], "anomalous", "risk_assessment",
             "Message signal", s.get("message"))

    # ---- rank 3: the request -------------------------------------------- #
    any_dev = any(r["status"] == "anomalous" for r in comparison) or bool(msg_signals)
    evaluated = any(r["status"] != "not_evaluated" for r in comparison) or assessment is not None
    node("request", "request", 3, "Payment request", "anomalous" if any_dev else ("normal" if evaluated else "unknown"),
         "incident", f"{_inr(amount)} via {channel}")
    for n in ("obs_channel", "obs_amount", "obs_beneficiary"):
        edge(n, "request", "deviation" if next(x for x in nodes if x["id"] == n)["status"] == "anomalous" else "observed")
    for s in msg_signals:
        edge(f"sig_{s['code']}", "request", "evidence")

    # ---- ranks 4-6: attachment ------------------------------------------ #
    verdict_from = "request"
    if attachment_name:
        att_signals = [s for s in signals if _origin(s) == "attachment"]
        att_used = _get(assessment, "inputs", "attachment", "status") == "used" if assessment else False
        if att_signals:
            att_status, att_sub = "anomalous", "Suspicious content found"
        elif att_used:
            att_status, att_sub = "normal", "Analyzed: no attachment findings"
        else:
            att_status, att_sub = "unknown", "File not analyzed in the latest assessment"
            notes.append("The attachment file was not part of the latest assessment (only metadata is stored).")
        node("attachment", "attachment", 4, attachment_name, att_status, "incident", att_sub)
        edge("request", "attachment", "evidence", "attached")
        verdict_from = "attachment"
        exec_signal = next((s for s in att_signals if s.get("code") == "EXECUTABLE_ATTACHMENT"), None)
        if exec_signal:
            files = [str(d) for d in (exec_signal.get("details") or [])][:10]
            for i, fname in enumerate(files):
                node(f"file_{i}", "executable_file", 5, fname, "anomalous", "risk_assessment", "Executable entry")
                edge("attachment", f"file_{i}", "evidence", "contains")
            node("exec_content", "executable_content", 6, "Executable content", "anomalous", "risk_assessment",
                 "Executable inside a document-like attachment", exec_signal.get("message"))
            for i in range(len(files)):
                edge(f"file_{i}", "exec_content", "evidence")
            if not files:
                edge("attachment", "exec_content", "evidence")
            verdict_from = "exec_content"
        elif att_signals:
            for s in att_signals:
                node(f"att_{s['code']}", "attachment_signal", 5, s.get("title") or s["code"], "anomalous", "risk_assessment",
                     "Attachment signal", s.get("message"))
                edge("attachment", f"att_{s['code']}", "evidence")

    # ---- last rank: the stored verdict (repeated, never computed) -------- #
    if assessment is None:
        node("verdict", "verdict", 7, "Not assessed", "unknown", "risk_assessment", "Run a risk assessment to see the verdict")
        edge("request", "verdict", "verdict")
        out = {"assessment_id": None, "version_number": None, "risk_level": None, "trust_break_detected": None}
    else:
        tb = bool(assessment.get("trust_break_detected"))
        level = assessment.get("risk_level")
        node("verdict", "verdict", 7, "TRUST BREAK" if tb else "No trust break detected", "verdict" if tb else "normal",
             "risk_assessment", f"Risk {level} · {assessment.get('recommended_action_label') or assessment.get('recommended_action')}")
        edge(verdict_from, "verdict", "verdict")
        if verdict_from != "request":
            edge("request", "verdict", "verdict")
        out = {"assessment_id": assessment.get("assessment_id"), "version_number": assessment.get("version_number"),
               "risk_level": level, "trust_break_detected": tb}
    return {"incident_id": incident_id, "identity_source": identity_source, "comparison": comparison,
            "nodes": nodes, "edges": edges, "notes": notes, "is_final_decision": False, **out}
