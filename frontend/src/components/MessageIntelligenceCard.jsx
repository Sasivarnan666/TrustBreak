import { highlightSegments } from "../lib/messageHighlights.js";
import { Card } from "./ui.jsx";

/** The original message with grounded social-engineering evidence marked. Text is rendered as-is. */
export default function MessageIntelligenceCard({ message, signals }) {
  const se = (signals ?? []).filter((s) => s.category === "SOCIAL_ENGINEERING");
  const segments = highlightSegments(message, se);
  const tags = [...new Set(segments.flatMap((s) => s.tags))];
  return (
    <Card title="Message intelligence" aside={tags.length > 0 && <span className="text-xs text-slate-500">{tags.length} pattern{tags.length === 1 ? "" : "s"} marked</span>}>
      <blockquote className="whitespace-pre-wrap border-l-2 border-slate-300 pl-4 text-sm leading-7 text-slate-800" data-testid="message-text">
        {segments.map((seg, i) =>
          seg.tags.length ? (
            <mark key={i} title={seg.tags.join(" · ")} className="rounded-sm bg-amber-100 px-0.5 text-slate-900 underline decoration-amber-500 decoration-2 underline-offset-4">
              {seg.text}
              <sup className="ml-1 select-none text-[9px] font-bold tracking-wide text-amber-800">{seg.tags.join(" / ")}</sup>
            </mark>
          ) : (
            <span key={i}>{seg.text}</span>
          ),
        )}
      </blockquote>
      <p className="mt-3 text-xs text-slate-500">
        {se.length === 0
          ? "No social-engineering evidence was scored for this message (or no assessment has been run)."
          : "Marked passages are verbatim evidence behind scored social-engineering signals. The message itself is unchanged."}
      </p>
    </Card>
  );
}
