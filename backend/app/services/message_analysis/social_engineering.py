"""Structured social-engineering evidence for one message.

Three origins, always labelled and never blurred:
  AI        a language model (Gemini/Anthropic) reported the indicator AND quoted evidence that really appears in
            the message (ungrounded evidence is discarded, so the model cannot invent a quote).
  rule      deterministic normalized-pattern detection, run on every message (also when AI answered).
  fallback  the same deterministic rules, when an AI provider was wanted but failed. Not semantic understanding.

These are EVIDENCE objects. They carry no risk score, level or recommendation; the model is never asked for
those and any such field in its reply is rejected. Scoring stays in the deterministic risk engine.
Standard library only.
"""

import re
import unicodedata
from typing import Any, Optional

from .mock_extractor import _NEGATION, _amounts
from .schema import MAX_TEXT_LEN

SIGNALS = (
    "authority_pressure",
    "urgency_pressure",
    "secrecy_pressure",
    "verification_suppression",
    "isolation_request",
    "fear_or_threat",
    "deadline_pressure",
    "payment_pressure",
    "credential_pressure",
    "impersonation_cue",
    "unusual_instruction",
)
CONFIDENCE_LEVELS = ("low", "medium", "high")
_RANK = {c: i for i, c in enumerate(CONFIDENCE_LEVELS)}
SOURCE_AI, SOURCE_RULE, SOURCE_FALLBACK = "AI", "rule", "fallback"
MAX_AI_SIGNALS = len(SIGNALS)
_I = re.IGNORECASE

# Each entry: (pattern, confidence). The first strongest match per signal wins.
_TITLE = r"(?:ceo|cfo|md|chairman|chairperson|managing director|chief (?:executive|financial) officer|director|president|owner|founder)"
_RULES = {
    "secrecy_pressure": [
        (r"\bkeep\s+(?:this|it|that|everything)\b.{0,25}\b(?:confidential|private|secret|quiet|between us|to yourself|low[- ]profile)\b", "high"),
        (r"\bdo\s?n[o']?t\s+tell\s+(?:anyone|anybody|a soul|others?)\b", "high"),
        (r"\bbetween\s+(?:us|you and me|the two of us)\b", "high"),
        (r"\b(?:strictly\s+)?confidential\b", "medium"),
        (r"\bno\s+one\s+(?:else\s+)?(?:should|needs?\s+to|must)\s+know\b", "high"),
        (r"\bkeep\s+(?:this|it)\s+(?:a\s+)?secret\b", "high"),
        (r"\bdo\s?n[o']?t\s+(?:share|mention|disclose)\s+(?:this|it|that)\b", "medium"),
    ],
    "verification_suppression": [
        (r"\bdo\s?n[o']?t\s+(?:call|phone|ring|verify|confirm|cross[- ]check|double[- ]check|contact|involve|loop in|ask)\b", "high"),
        (r"\bdo\s+not\s+(?:call|phone|verify|confirm|cross[- ]check|contact|involve|loop in|ask)\b", "high"),
        (r"\bno\s+need\s+to\s+(?:confirm|verify|check|call|get approval|inform|involve)\b", "high"),
        (r"\b(?:skip|bypass|avoid|waive)\s+(?:the\s+)?(?:usual\s+)?(?:verification|approval|approvals|process|checks?|controls?|procedure|callback)\b", "high"),
        (r"\bwithout\s+(?:any\s+)?(?:approval|verification|confirmation|informing|telling|involving)\b", "medium"),
        (r"\b(?:i\s+)?(?:can'?t|cannot)\s+(?:take|answer)\s+(?:calls?|phone)\b|\bno\s+calls?\b|\bonly\s+(?:text|message|whatsapp)\s+me\b", "medium"),
    ],
    "isolation_request": [
        (r"\bdo\s?n[o']?t\s+(?:involve|inform|loop\s+in|consult|discuss\s+(?:this\s+)?with|talk\s+to|tell)\s+(?:anyone|anybody|others?|the\s+team|your\s+(?:manager|team|boss)|colleagues?|finance|accounts?)\b", "high"),
        (r"\bhandle\s+(?:this|it)\s+(?:yourself|personally|alone|directly)\b", "medium"),
        (r"\bjust\s+(?:you\s+and\s+me|between\s+us)\b|\bonly\s+(?:you|us)\s+(?:and\s+me\s+)?(?:should|can|will)\b", "medium"),
        (r"\bdo\s+not\s+(?:involve|inform|loop\s+in|consult|discuss\s+(?:this\s+)?with|talk\s+to|tell)\s+(?:anyone|anybody|others?|the\s+team|your\s+(?:manager|team|boss)|colleagues?|finance|accounts?)\b", "high"),
    ],
    "urgency_pressure": [
        (r"\b(?:urgent(?:ly)?|immediately|asap|right\s+away|right\s+now|at\s+once|without\s+delay|as\s+soon\s+as\s+possible|this\s+instant)\b", "high"),
        (r"\b(?:before|by)\s+\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)\b", "medium"),
        (r"\b(?:today|tonight|this\s+(?:morning|afternoon|evening))\b", "low"),
    ],
    "authority_pressure": [
        (rf"\b(?:i\s+am|i'?m|this\s+is|it'?s)\s+(?:the\s+|your\s+|our\s+)?(?:new\s+)?{_TITLE}\b", "high"),
        (rf"\b{_TITLE}\s+(?:instruction|instructed|ordered|directive|wants|has\s+(?:asked|instructed|approved))\b", "high"),
        (rf"\b(?:as\s+per|on\s+(?:the\s+)?(?:instruction|orders?)\s+of|per)\s+(?:the\s+|our\s+)?{_TITLE}\b", "high"),
        (r"\bas\s+your\s+(?:manager|boss|superior|senior|director|ceo)\b", "high"),
        (r"\b(?:i\s+am|i'?m)\s+(?:your\s+)?(?:boss|manager)\b|\bthis\s+is\s+an?\s+(?:order|directive)\b", "medium"),
    ],
    "payment_pressure": [
        (r"\b(?:release|process|make|send|initiate|clear|disburse|settle|approve)\s+(?:the\s+|this\s+|that\s+|a\s+)?(?:payment|funds|money|amount|transfer)\b", "high"),
        (r"\b(?:transfer|wire|remit)\b", "high"),
        (r"\b(?:neft|rtgs|imps)\b", "medium"),
        (r"\bpay\s+(?:the\s+|this\s+|that\s+|our\s+)?(?:invoice|vendor|supplier|amount|bill)\b", "medium"),
    ],
    "credential_pressure": [
        (r"\b(?:send|share|give|forward|tell|read\s+out|provide|text)\b[^.!?\n]{0,30}\b(?:otp|one[- ]time\s+(?:password|passcode|code)|password|passcode|pin|cvv|credentials?|login\s+details|verification\s+code)\b", "high"),
        (r"\b(?:verify|confirm|update)\s+your\s+(?:account|login|password|credentials)\b", "medium"),
    ],
    "fear_or_threat": [
        (r"\b(?:or\s+else|serious\s+consequences|legal\s+action|face\s+(?:action|consequences)|disciplinary\s+action|held\s+responsible)\b", "high"),
        (r"\b(?:account|access|card|service)s?\s+(?:will\s+be|has\s+been|is\s+being|gets?)\s+(?:blocked|suspended|frozen|closed|terminated|deactivated)\b", "high"),
        (r"\byou\s+(?:will|'ll)\s+be\s+(?:fired|terminated|suspended|penali[sz]ed|reported)\b", "high"),
        (r"\b(?:penalt(?:y|ies)|fine|arrest|police|court\s+case|lawsuit)\b", "medium"),
        (r"\bfailure\s+to\s+(?:comply|respond|act|pay)\b", "high"),
    ],
    "deadline_pressure": [
        (r"\b(?:before|by)\s+\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)(?:\s+(?:today|tomorrow|tonight))?", "high"),
        (r"\bwithin\s+(?:the\s+)?(?:next\s+)?(?:\d+\s+|an?\s+|one\s+|two\s+|three\s+|half\s+an\s+)?(?:minutes?|mins?|hours?|hrs?)\b", "high"),
        (r"\bby\s+(?:end\s+of\s+(?:the\s+)?day|eod|close\s+of\s+business|cob|tonight|tomorrow)\b", "medium"),
        (r"\b(?:end\s+of\s+(?:the\s+)?day|eod|close\s+of\s+business)\b", "medium"),
        (r"\b(?:deadline|cut[- ]?off)\b", "low"),
    ],
    "impersonation_cue": [
        (r"\b(?:this\s+is\s+my|i\s+am\s+(?:using|writing\s+from)\s+(?:my|a))\s+(?:new|personal|private|temporary|different)\s+(?:number|phone|mobile|email|e-?mail|account)\b", "high"),
        (r"\b(?:my|the)\s+(?:new|changed)\s+(?:number|phone|mobile|email|e-?mail)\b|\bsave\s+this\s+(?:new\s+)?number\b|\bchanged\s+my\s+number\b", "high"),
        (r"\b(?:lost|broke|changed)\s+my\s+(?:phone|sim|laptop)\b|\bofficial\s+(?:email|e-?mail|account|line)s?\s+(?:is|are)\s+(?:down|not\s+working|unavailable)\b", "medium"),
        (r"\b(?:i\s+am|i'?m)\s+(?:travel+ing|in\s+a\s+meeting|in\s+a\s+(?:board\s+)?meeting|abroad|on\s+a\s+flight)\b", "low"),
    ],
    "unusual_instruction": [
        (r"\b(?:buy|purchase|get)\b[^.!?\n]{0,25}\b(?:gift\s*cards?|vouchers?|prepaid\s+cards?|bitcoin|crypto(?:currency)?|usdt)\b|\bgift\s*cards?\b", "high"),
        (r"\b(?:new|different|changed|updated)\s+(?:bank\s+)?account(?:\s+(?:number|details))?\b|\b(?:change|update)\s+(?:the\s+|our\s+|my\s+)?(?:bank|account)\s+(?:details|number)\b", "high"),
        (r"\b(?:personal|private|offshore)\s+account\b|\bbitcoin|\busdt\b|\bcrypto(?:currency)?\b", "high"),
        (r"\bsplit\s+(?:the\s+)?(?:payment|amount|transfer)\b|\boff\s+the\s+books\b|\bnot\s+through\s+(?:the\s+)?(?:erp|system|portal)\b|\boutside\s+(?:the\s+)?(?:erp|system|process)\b", "high"),
    ],
}
_COMPILED = {k: [(re.compile(p, _I), c) for p, c in v] for k, v in _RULES.items()}
_NEGATION_BEFORE = re.compile(r"(?:\bnot|n't|\bnever|\bno)\s+(?:\w+\s+)?$", _I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def normalize_text(text: str) -> str:
    """NFKC, curly quotes/apostrophes -> ASCII, zero-width characters removed, whitespace collapsed. Case kept."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x200B: None, 0x200C: None, 0x200D: None, 0xFEFF: None})
    return re.sub(r"\s+", " ", text).strip()


def _fold(text: str) -> str:
    return normalize_text(text).casefold()


def _sentence_around(text: str, start: int, end: int) -> str:
    pos = 0
    for part in _SENTENCE_SPLIT.split(text):
        s = text.find(part, pos)
        if s == -1:
            continue
        pos = s + len(part)
        if s <= start < pos or s < end <= pos:
            sentence = part.strip()
            if len(sentence) > MAX_TEXT_LEN:  # keep the matched phrase inside the clipped window
                lo = max(0, start - s - 60)
                sentence = sentence[lo : lo + MAX_TEXT_LEN].strip()
            return sentence
    return text[start:end]


def _signal(name: str, evidence: Optional[str], source: str, confidence: Optional[str], matched: Optional[str] = None) -> dict:
    return {
        "signal": name,
        "detected": evidence is not None,
        "evidence": evidence,
        "matched_phrase": matched,
        "source": source if evidence is not None else None,
        "sources": [source] if evidence is not None else [],
        "confidence": confidence if evidence is not None else None,
    }


def detect_rule_signals(message: str, source: str = SOURCE_RULE) -> dict:
    """Deterministic detection for every signal. Returns {signal_name: signal_dict} (all 11 keys present)."""
    text = normalize_text(message)
    amounts = _amounts(text)
    out = {}
    for name in SIGNALS:
        best = None
        for pattern, confidence in _COMPILED[name]:
            for m in pattern.finditer(text):
                before = text[max(0, m.start() - 14) : m.start()]
                if name in {"secrecy_pressure", "credential_pressure", "payment_pressure"} and (
                    _NEGATION_BEFORE.search(before) or _NEGATION.search(before)
                ):
                    continue  # "this is not confidential", "do not share your OTP" are not requests
                if best is None or _RANK[confidence] > _RANK[best[0]]:
                    best = (confidence, m)
                break
            if best and best[0] == "high":
                break
        if best is None:
            out[name] = _signal(name, None, source, None)
            continue
        confidence, m = best
        if name == "payment_pressure" and confidence == "medium" and amounts:
            confidence = "high"  # an explicit amount makes a payment instruction concrete
        out[name] = _signal(name, _sentence_around(text, m.start(), m.end()), source, confidence, m.group(0))
    return out


# --------------------------------------------------------------------------- #
# AI-reported indicators: strict validation + evidence grounding
# --------------------------------------------------------------------------- #
def validate_ai_signals(raw: Any, message: str) -> tuple:
    """Validate the optional `social_engineering_signals` list from a model reply.

    Returns (accepted, notes). Never raises: bad structure or ungrounded evidence is dropped and reported, so an
    imperfect model reply can never take the extraction down. An item is accepted only if it has exactly the keys
    signal/evidence/confidence, a known signal, a valid confidence, and evidence that appears in the message.
    """
    notes: list = []
    if raw is None:
        return [], notes
    if not isinstance(raw, list):
        return [], ["AI social-engineering indicators were discarded: not a list."]
    folded = _fold(message)
    accepted, seen, dropped = [], set(), 0
    for item in raw[:MAX_AI_SIGNALS * 2]:
        if (
            not isinstance(item, dict)
            or set(item) != {"signal", "evidence", "confidence"}
            or item["signal"] not in SIGNALS
            or item["confidence"] not in CONFIDENCE_LEVELS
            or not isinstance(item["evidence"], str)
            or item["signal"] in seen
        ):
            dropped += 1
            continue
        evidence = normalize_text(item["evidence"])
        if not evidence or len(evidence) > MAX_TEXT_LEN or evidence.casefold() not in folded:
            dropped += 1
            continue
        seen.add(item["signal"])
        accepted.append({"signal": item["signal"], "evidence": evidence, "confidence": item["confidence"]})
    if dropped:
        notes.append(f"{dropped} AI social-engineering indicator(s) were discarded (invalid shape or evidence not found in the message).")
    return accepted, notes


def build_social_engineering(message: str, *, ai_signals: Optional[list] = None, ai_requested: bool = False, ai_failed: bool = False,
                             extra_notes: Optional[list] = None) -> dict:
    """Merge rule/fallback detections with validated AI indicators into the public result block.

    `ai_failed` (an AI provider was wanted but the deterministic extractor ran) labels the rule hits "fallback".
    """
    rule_source = SOURCE_FALLBACK if ai_failed else SOURCE_RULE
    rules = detect_rule_signals(message, rule_source)
    ai = {s["signal"]: s for s in (ai_signals or [])}
    merged = []
    for name in SIGNALS:
        r, a = rules[name], ai.get(name)
        if a is not None:
            entry = _signal(name, a["evidence"], SOURCE_AI, a["confidence"], r["matched_phrase"])
            if r["detected"]:
                entry["sources"].append(rule_source)
                if _RANK[r["confidence"]] > _RANK[entry["confidence"]]:
                    entry["confidence"] = r["confidence"]
        else:
            entry = r
        merged.append(entry)
    notes = list(extra_notes or [])
    notes.append(
        "Indicators are evidence, not a risk score. AI-derived items quote text found in the message; rule-derived items "
        "come from fixed patterns; fallback-derived items are the same patterns used because the AI provider failed and "
        "have no semantic understanding."
    )
    return {
        "signals": merged,
        "detected_count": sum(1 for s in merged if s["detected"]),
        "ai_requested": ai_requested,
        "ai_contributed": bool(ai),
        "rule_source_label": rule_source,
        "notes": notes,
        "is_final_decision": False,
    }
