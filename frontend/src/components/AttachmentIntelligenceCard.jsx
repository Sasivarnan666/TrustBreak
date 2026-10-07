import { Card } from "./ui.jsx";
import { Tag } from "./StatusBadge.jsx";

const EXEC = /\.(exe|dll|scr|bat|cmd|com|msi|js|vbs|ps1|jar|lnk)$/i;

/** What the stored assessment says about the attachment. Static structural analysis only — never a malware verdict. */
export default function AttachmentIntelligenceCard({ attachment, signals, archiveEntries }) {
  if (!attachment) return null;
  const att = (signals ?? []).filter((s) => s.category === "ATTACHMENT");
  const flagged = new Set(att.flatMap((s) => s.details ?? []));
  return (
    <Card title="Attachment intelligence" aside={<Tag>Static structural analysis</Tag>}>
      <p className="font-mono text-sm font-semibold text-slate-900">{attachment.name}</p>
      {archiveEntries?.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Archive structure (synthetic demo archive)</p>
          <ul className="mt-1.5 divide-y divide-slate-100 rounded-md border border-slate-200 font-mono text-sm" data-testid="archive-structure">
            {archiveEntries.map((name) => {
              const risky = EXEC.test(name) || flagged.has(name);
              return (
                <li key={name} className="flex items-center justify-between px-3 py-1.5">
                  <span className={risky ? "font-semibold text-red-800" : "text-slate-800"}>{name}</span>
                  {risky && <span className="rounded bg-red-50 px-1.5 text-[10px] font-semibold uppercase text-red-800 ring-1 ring-inset ring-red-600/25">executable content</span>}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {att.length > 0 ? (
        <ul className="mt-3 space-y-2">
          {att.map((s) => (
            <li key={s.code} className="rounded-md border border-slate-200 px-3 py-2 text-sm">
              <p className="font-semibold text-slate-900">{s.title} <span className="text-slate-500">· +{s.points}</span></p>
              <p className="text-slate-700">{s.message}</p>
              {s.details?.length > 0 && <p className="mt-0.5 font-mono text-xs text-slate-600">{s.details.join(", ")}</p>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-slate-700">No attachment findings are recorded in the latest assessment. The file may not have been analysed in that run.</p>
      )}
      <p className="mt-3 text-xs font-medium text-slate-600">Static structural analysis only. The file is never executed or opened, and this is not a malware verdict.</p>
    </Card>
  );
}
