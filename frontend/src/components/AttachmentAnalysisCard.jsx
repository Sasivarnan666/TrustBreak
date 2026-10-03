import { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { formatBytes } from "../lib/format.js";
import { Tag } from "./StatusBadge.jsx";
import { Button, Card, DataRow } from "./ui.jsx";

const SEVERITY = {
  high: { icon: "🔴", cls: "border-red-200 bg-red-50 text-red-900" },
  medium: { icon: "🟠", cls: "border-amber-300 bg-amber-50 text-amber-900" },
  low: { icon: "🟡", cls: "border-slate-200 bg-slate-50 text-slate-800" },
  info: { icon: "ℹ️", cls: "border-slate-200 bg-slate-50 text-slate-800" },
};

const FILE_TYPE_LABELS = {
  zip: "ZIP archive",
  pdf: "PDF document",
  office_document: "Office document",
  ole_document: "Legacy Office document",
  pe_executable: "Windows executable",
  elf_executable: "Linux executable",
  rar: "RAR archive",
  "7z": "7-Zip archive",
  gzip: "GZIP archive",
  png: "PNG image",
  jpeg: "JPEG image",
  gif: "GIF image",
  unknown: "Unrecognized type",
};

const FINDING_TITLES = {
  executable_inside_archive: "Risky file inside archive",
  double_extension: "Double extension",
  document_with_executable_content: "Document-looking archive",
  path_traversal: "Path traversal indicator",
  content_type_mismatch: "Name and content do not match",
  executable_file: "Executable file",
  risky_extension: "Risky file type",
  invalid_archive: "Unreadable archive",
  nested_archive: "Nested archive",
  encrypted_entries: "Password-protected entries",
  high_compression_ratio: "Unusual compression ratio",
  large_uncompressed_size: "Very large contents",
  too_many_entries: "Many entries",
  long_entry_name: "Very long entry name",
  archive_not_inspected: "Archive not opened",
};

/** Pure view of one attachment-analysis result (no fetching). */
export function AttachmentAnalysisView({ analysis }) {
  const { findings = [], notes = [] } = analysis;
  const typeLabel = FILE_TYPE_LABELS[analysis.file_type] ?? analysis.file_type;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tag tone="amber">Structural analysis</Tag>
        <Tag>Never executed or stored</Tag>
      </div>

      <p className="mb-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
        Structural analysis only — this does <strong>not</strong> prove that the file is malware.
      </p>

      <dl className="divide-y divide-slate-100">
        <DataRow label="File name">
          <span className="font-mono text-[13px]">{analysis.file_name}</span>
        </DataRow>
        <DataRow label="File type">{typeLabel}</DataRow>
        <DataRow label="Archive">{analysis.archive ? (analysis.inspected ? "Yes" : "Yes (contents not inspected)") : "No"}</DataRow>
        {analysis.file_count != null && (
          <DataRow label="File count">
            {analysis.file_count} {analysis.file_count === 1 ? "file" : "files"}
            {analysis.total_uncompressed_bytes != null && (
              <span className="ml-2 font-normal text-slate-500">({formatBytes(analysis.total_uncompressed_bytes)} declared)</span>
            )}
          </DataRow>
        )}
        <DataRow label="Executable content">
          {analysis.contains_executable ? (
            <span className="text-red-700">🔴 Executable content detected</span>
          ) : (
            <span className="text-emerald-700">✓ None detected</span>
          )}
        </DataRow>
      </dl>

      <h3 className="mb-2 mt-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Findings</h3>
      {findings.length === 0 ? (
        <p className="text-sm text-slate-600">No suspicious structural indicators were found in the checks that ran.</p>
      ) : (
        <ul className="space-y-2">
          {findings.map((f, i) => {
            const s = SEVERITY[f.severity] ?? SEVERITY.info;
            return (
              <li key={`${f.type}-${f.entry ?? ""}-${i}`} className={`rounded-md border px-3 py-2 text-sm ${s.cls}`}>
                <p className="font-semibold">
                  {s.icon} {f.entry ? <span className="font-mono text-[13px]">{f.entry}</span> : FINDING_TITLES[f.type] ?? f.type}
                </p>
                <p className="mt-0.5 text-[13px] leading-relaxed">
                  {f.entry && <span className="font-medium">{FINDING_TITLES[f.type] ?? f.type}: </span>}
                  {f.message}
                </p>
              </li>
            );
          })}
        </ul>
      )}

      {notes.length > 0 && (
        <ul className="mt-3 list-disc space-y-0.5 pl-5 text-xs text-slate-500">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Card: pick the file, analyze it on demand. The file is sent once and never kept. */
export default function AttachmentAnalysisCard({ incidentId, attachmentName, onFileChange }) {
  const [file, setFile] = useState(null);
  const [state, setState] = useState({ status: "idle", analysis: null, error: null });
  const controller = useRef(null);

  useEffect(() => () => controller.current?.abort(), []);

  async function run() {
    if (!file) return;
    controller.current?.abort();
    controller.current = new AbortController();
    setState({ status: "loading", analysis: null, error: null });
    try {
      const res = await api.analyzeAttachment(incidentId, file, controller.current.signal);
      setState({ status: "done", analysis: res.data, error: null });
    } catch (error) {
      if (error?.name === "AbortError") return;
      setState({ status: "error", analysis: null, error });
    }
  }

  const busy = state.status === "loading";
  return (
    <Card
      title="Attachment Analysis"
      aside={
        <Button variant="secondary" onClick={run} disabled={busy || !file}>
          {busy ? "Analyzing…" : state.status === "done" ? "Run again" : "Analyze file"}
        </Button>
      }
    >
      <div className="mb-3">
        <label htmlFor="attachment-file" className="block text-sm text-slate-600">
          Choose the copy of <span className="font-mono text-[13px]">{attachmentName}</span> to inspect:
        </label>
        <input
          id="attachment-file"
          type="file"
          className="mt-1.5 block w-full text-sm text-slate-700 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-semibold"
          onChange={(e) => {
            const chosen = e.target.files?.[0] ?? null;
            setFile(chosen);
            onFileChange?.(chosen); // lets the risk assessment reuse the same file
            setState({ status: "idle", analysis: null, error: null });
          }}
        />
        <p className="mt-1.5 text-xs text-slate-500">
          The file is read in memory only to list its structure. It is never opened, executed or stored.
        </p>
      </div>
      {busy && (
        <p role="status" className="text-sm text-slate-600">
          Inspecting file structure…
        </p>
      )}
      {state.status === "error" && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {state.error?.message || "The attachment could not be analyzed."}
          {state.error?.code && <span className="ml-2 font-mono text-xs text-red-700/80">code: {state.error.code}</span>}
        </div>
      )}
      {state.status === "done" && <AttachmentAnalysisView analysis={state.analysis} />}
    </Card>
  );
}
