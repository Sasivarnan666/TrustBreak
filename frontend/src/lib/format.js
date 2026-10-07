const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** 1850000 -> "₹18,50,000" */
export const formatINR = (amount) => `₹${inr.format(amount)}`;

export function formatDateTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

/** 20000 -> "₹20K", 200000 -> "₹2L", 1850000 -> "₹18.5L", 12000000 -> "₹1.2Cr" (display only). */
export function compactINR(amount) {
  if (amount === null || amount === undefined) return "—";
  const trim = (n) => String(Math.round(n * 100) / 100);
  if (amount >= 10_000_000) return `₹${trim(amount / 10_000_000)}Cr`;
  if (amount >= 100_000) return `₹${trim(amount / 100_000)}L`;
  if (amount >= 1_000) return `₹${trim(amount / 1_000)}K`;
  return `₹${amount}`;
}

/** "2026-10-07T09:14:03Z" -> "09:14:03" (local time, 24h). Returns null when there is no usable timestamp. */
export function formatClock(iso) {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function formatDay(iso) {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}
