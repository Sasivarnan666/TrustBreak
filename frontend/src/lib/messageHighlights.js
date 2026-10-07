/** Locate verbatim social-engineering evidence inside the ORIGINAL message (the text itself is never altered).
 *  Returns ordered, non-overlapping segments: [{ text, tags: [] }]. */
const TAG_FOR_CODE = {
  HIGH_URGENCY: "URGENT",
  URGENCY_PRESSURE: "URGENT",
  DEADLINE_PRESSURE: "DEADLINE",
  SECRECY_REQUESTED: "SECRECY",
  SECRECY_PRESSURE: "SECRECY",
  ISOLATION_REQUEST: "SECRECY",
  VERIFICATION_SUPPRESSION: "VERIFICATION SUPPRESSION",
  PAYMENT_PRESSURE: "PAYMENT PRESSURE",
  FEAR_OR_THREAT: "THREAT",
  CREDENTIAL_PRESSURE: "CREDENTIAL REQUEST",
  IMPERSONATION_CUE: "IMPERSONATION CUE",
  UNUSUAL_INSTRUCTION: "UNUSUAL INSTRUCTION",
  AUTHORITY_PRESSURE: "AUTHORITY",
};

export function tagForCode(code) {
  return TAG_FOR_CODE[code] ?? null;
}

export function highlightSegments(message, signals = []) {
  const lower = message.toLowerCase();
  const found = [];
  for (const s of signals) {
    const tag = TAG_FOR_CODE[s.code];
    if (!tag || !s.evidence) continue;
    const quote = s.evidence.trim().replace(/^["“]|["”]$/g, "");
    if (quote.length < 3) continue;
    const at = lower.indexOf(quote.toLowerCase());
    if (at < 0) continue; // only verbatim matches are highlighted
    found.push({ start: at, end: at + quote.length, tag });
  }
  found.sort((a, b) => a.start - b.start || b.end - a.end);
  const ranges = [];
  for (const f of found) {
    const last = ranges[ranges.length - 1];
    if (last && f.start < last.end) {
      if (!last.tags.includes(f.tag)) last.tags.push(f.tag); // overlapping evidence: share the span
      last.end = Math.max(last.end, f.end);
    } else {
      ranges.push({ start: f.start, end: f.end, tags: [f.tag] });
    }
  }
  const out = [];
  let pos = 0;
  for (const r of ranges) {
    if (r.start > pos) out.push({ text: message.slice(pos, r.start), tags: [] });
    out.push({ text: message.slice(r.start, r.end), tags: r.tags });
    pos = r.end;
  }
  if (pos < message.length) out.push({ text: message.slice(pos), tags: [] });
  return out.length ? out : [{ text: message, tags: [] }];
}
