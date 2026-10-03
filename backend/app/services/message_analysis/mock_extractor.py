"""Deterministic DEMO extractor (regex rules). This is NOT an AI model.

Used when no AI key is configured or the AI call fails. It exists so the app
can be developed and demonstrated offline, and it is always labelled
`mode = "mock"`. It understands a small set of English phrasings only.
The text is only ever matched against patterns - never executed, fetched
or followed.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from .schema import MAX_AMOUNT, MessageExtraction, validate_extraction

_I = re.IGNORECASE

# ---- amounts --------------------------------------------------------------- #
_PRE_CCY = {"₹": "INR", "rs": "INR", "inr": "INR", "usd": "USD", "eur": "EUR", "gbp": "GBP", "$": "USD", "€": "EUR", "£": "GBP"}
_POST_CCY = {"rupees": "INR", "inr": "INR", "usd": "USD", "eur": "EUR", "gbp": "GBP", "dollars": "USD", "euros": "EUR"}
_MULT = {"k": 10**3, "lakh": 10**5, "lakhs": 10**5, "lac": 10**5, "lacs": 10**5, "crore": 10**7, "crores": 10**7, "cr": 10**7, "million": 10**6, "mn": 10**6}
_AMOUNT = re.compile(
    r"(?:(?P<pre>₹|\bRs\.?|\bINR|\bUSD|\bEUR|\bGBP|[$€£])\s*(?P<n1>\d[\d,]*(?:\.\d+)?)\s*(?P<m1>lakhs?|lacs?|crores?|cr\b|k\b|million|mn\b)?"
    r"|(?P<n2>\d[\d,]*(?:\.\d+)?)\s*(?P<m2>lakhs?|lacs?|crores?|k\b|million)?\s*(?P<post>rupees|INR|USD|EUR|GBP|dollars|euros)\b)",
    _I,
)

# ---- authority ------------------------------------------------------------- #
_TITLES = [  # most specific first
    (r"chief executive officer|ceo", "CEO"),
    (r"chief financial officer|cfo", "CFO"),
    (r"managing director|md", "Managing Director"),
    (r"chairman|chairperson", "Chairman"),
    (r"finance (?:head|manager|controller|director)", "Finance head"),
    (r"director", "Director"),
    (r"president", "President"),
    (r"founder|owner", "Founder/Owner"),
]
_INTRO = r"(?:this is|i am|i'm|it's|message from|from|as)\s+(?:the\s+|your\s+|our\s+)?(?:new\s+)?"

# ---- actions (ordered, first match wins) ------------------------------------ #
_ACTIONS = [
    (re.compile(r"\bgift\s*cards?\b", _I), "purchase gift cards", "gift_card_purchase"),
    (re.compile(r"\b(?:share|send|give|forward|tell|read out)\b[^.!?\n]{0,30}\b(?:otp|one[- ]time (?:password|passcode)|password|pin|cvv|credentials|login details)\b", _I), "share OTP or credentials", "credential_or_otp_request"),
    (re.compile(r"\b(?:change|update|new)\s+(?:the\s+|our\s+|my\s+)?(?:bank|account)\s+(?:details|number|account)\b", _I), "change bank details", "bank_detail_change"),
    (re.compile(r"\binvoice\b[^.!?\n]{0,40}\b(?:pay|paid|process|clear|settle|release)\b|\b(?:pay|process|clear|settle|release)\b[^.!?\n]{0,40}\binvoice\b", _I), "pay invoice", "invoice_payment"),
    (re.compile(r"\b(?:transfer|wire|remit|neft|rtgs|imps)\b", _I), "transfer money", "payment_transfer"),
    (re.compile(r"\b(?:release|pay|send|settle|disburse|clear|process)\b[^.!?\n]{0,40}\b(?:payment|funds|money|amount|vendor|₹|rs\b|inr)", _I), "make payment", "payment_transfer"),
]
_NEGATION = re.compile(r"(?:\bnot|n't|\bnever)\s+\w*\s*$", _I)

# ---- beneficiary / organisation ---------------------------------------------- #
_GENERIC_BENEFICIARY = re.compile(
    r"\b(?:to|for)\s+(?:the\s+|our\s+|a\s+|this\s+)?((?:new\s+)?(?:vendor|supplier|contractor|beneficiary|payee)(?:\s+account)?)\b", _I
)
_ORG = re.compile(
    r"\b((?:[A-Z][\w&.-]*\s){1,4}(?:Pvt\.?\s*Ltd\.?|Private Limited|Limited|Ltd\.?|LLP|Inc\.?|Corp\.?|Corporation|Enterprises|Traders|Industries|Bank|Technologies|Solutions|Supplies))"
)
_PAYEE_PREFIX = re.compile(r"(?:\bto|in favou?r of)\s+(?:the\s+)?$", _I)

# ---- urgency / deadline / secrecy -------------------------------------------- #
_URGENT = re.compile(r"\b(?:urgent(?:ly)?|immediately|asap|right away|right now|at once|without delay|emergency|as soon as possible|this instant)\b", _I)
_DEADLINES = [
    re.compile(r"\b(?:today\s+)?(?:before|by)\s+\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)(?:\s+(?:today|tomorrow))?", _I),
    re.compile(r"\bwithin\s+(?:the\s+)?(?:next\s+)?(?:\d+\s+|an?\s+|one\s+|two\s+|three\s+|half an\s+)?(?:minutes?|hours?|hrs?|days?)\b", _I),
    re.compile(r"\bby\s+(?:end of day|eod|close of business|cob|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", _I),
    re.compile(r"\b(?:end of day|eod|close of business|cob)\b", _I),
    re.compile(r"\b(?:today|tonight|tomorrow|this (?:morning|afternoon|evening))\b", _I),
]
_SECRECY = [
    re.compile(p, _I)
    for p in (
        r"\bconfidential(?:ly|ity)?\b",
        r"\bsecret(?:ly)?\b",
        r"\bbetween (?:us|you and me)\b",
        r"\bkeep (?:this|it|that|me)\b.{0,30}\b(?:quiet|private|to yourself|low[- ]profile)\b",
        r"\b(?:do not|don'?t|never)\s+(?:tell|inform|discuss|mention|speak|talk|let anyone|involve|share (?:this|it|that))\b",
        r"\b(?:do not|don'?t)\s+(?:verify|check with)\b",
        r"\bno one (?:else )?(?:should|needs to|must) know\b",
    )
]

_URL = re.compile(r"https?://[^\s<>\"')]+", _I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_GREETING = re.compile(r"^\s*(?:hi|hello|hey|dear)\s+([A-Z][a-z]+)\b")


def _amounts(text: str) -> list:
    found = []
    for m in _AMOUNT.finditer(text):
        number, mult, ccy = (m.group("n1"), m.group("m1"), _PRE_CCY.get((m.group("pre") or "").lower().rstrip("."))) if m.group("pre") else (
            m.group("n2"), m.group("m2"), _POST_CCY.get((m.group("post") or "").lower())
        )
        try:
            value = Decimal(number.replace(",", ""))
        except InvalidOperation:
            continue
        if mult:
            value *= _MULT[mult.lower()]
        if value != value.to_integral_value() or not 0 < value <= MAX_AMOUNT:
            continue
        found.append((int(value), ccy, m.group(0).strip()))
    return found


def _authority(text: str) -> Optional[str]:
    for pattern, label in _TITLES:
        if re.search(rf"\b{_INTRO}(?:{pattern})\b", text, _I):
            return label
    return None


def _action(text: str) -> tuple:
    for pattern, action, intent in _ACTIONS:
        match = pattern.search(text)
        if not match:
            continue
        if intent == "credential_or_otp_request" and _NEGATION.search(text[max(0, match.start() - 20) : match.start()]):
            continue  # "do not share your OTP" is a warning, not a request
        return action, intent
    return None, None


def _organization_and_beneficiary(text: str) -> tuple:
    organization = beneficiary = None
    orgs = []
    for m in _ORG.finditer(text):
        name = m.group(1).strip()
        orgs.append(name)
        if beneficiary is None and _PAYEE_PREFIX.search(text[: m.start()]):
            beneficiary = name
        elif organization is None:
            organization = name
    if beneficiary is None:
        generic = _GENERIC_BENEFICIARY.search(text)
        if generic:
            beneficiary = re.sub(r"\s+", " ", generic.group(1)).lower()
    return organization, beneficiary, orgs


def _deadline(text: str) -> Optional[str]:
    for pattern in _DEADLINES:
        match = pattern.search(text)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).lower()
    return None


def extract(text: str) -> MessageExtraction:
    amounts = _amounts(text)
    amount, currency, _ = max(amounts, key=lambda a: a[0]) if amounts else (None, None, None)
    action, intent = _action(text)
    if intent is None:
        intent = "other_financial" if amount is not None else "none"
    organization, beneficiary, orgs = _organization_and_beneficiary(text)
    authority = _authority(text)
    deadline = _deadline(text)
    secrecy = any(p.search(text) for p in _SECRECY)

    if _URGENT.search(text):
        urgency = "high"
    elif deadline and intent != "none":
        urgency = "medium"  # time pressure on a financial request
    else:
        urgency = "none"

    entities = []
    greeting = _GREETING.match(text)
    if greeting:
        entities.append({"type": "person", "value": greeting.group(1)})
    if authority:
        entities.append({"type": "role", "value": authority})
    entities.extend({"type": "money", "value": raw} for _, _, raw in amounts[:5])
    if beneficiary:
        entities.append({"type": "beneficiary", "value": beneficiary})
    entities.extend({"type": "organization", "value": name} for name in orgs[:3])
    if deadline:
        entities.append({"type": "deadline", "value": deadline})
    entities.extend({"type": "url", "value": u[:200]} for u in _URL.findall(text)[:3])  # recorded as text only
    entities.extend({"type": "email", "value": e[:200]} for e in _EMAIL.findall(text)[:3])

    # Heuristic: how many fields the rules could fill. NOT model certainty.
    if intent == "none":
        confidence = 0.4
    else:
        filled = sum(bool(x) for x in (authority, action, amount, beneficiary, deadline, urgency != "none", secrecy))
        confidence = min(0.9, 0.35 + 0.1 * filled)

    return validate_extraction(
        {
            "claimed_authority": authority,
            "requested_action": action,
            "payment_amount": amount,
            "currency": currency,
            "beneficiary": beneficiary,
            "urgency_level": urgency,
            "secrecy_indicator": secrecy,
            "organization": organization,
            "deadline": deadline,
            "financial_intent": intent,
            "extracted_entities": entities[:25],
            "confidence": round(confidence, 2),
        }
    )
