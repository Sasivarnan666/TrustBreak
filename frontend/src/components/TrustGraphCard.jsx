import { Card } from "./ui.jsx";

const NODE_W = 150;
const NODE_H = 56;
const GAP_X = 18;
const GAP_Y = 54;

const FILL = {
  normal: { box: "#ecfdf5", stroke: "#10b981", text: "#064e3b" },
  anomalous: { box: "#fef2f2", stroke: "#dc2626", text: "#7f1d1d" },
  info: { box: "#f8fafc", stroke: "#94a3b8", text: "#0f172a" },
  unknown: { box: "#ffffff", stroke: "#94a3b8", text: "#475569", dash: "5 4" },
  verdict: { box: "#7f1d1d", stroke: "#450a0a", text: "#ffffff" },
};
const EDGE = { deviation: "#dc2626", evidence: "#ea580c", verdict: "#7f1d1d", observed: "#10b981", baseline: "#94a3b8" };

const clip = (text, n) => (text && text.length > n ? `${text.slice(0, n - 1)}…` : text ?? "");

/** Deterministic layered layout from backend ranks (compacted so missing ranks leave no empty rows). */
export function layoutGraph(nodes, edges) {
  const ranks = [...new Set(nodes.map((n) => n.rank))].sort((a, b) => a - b);
  const rows = ranks.map((r) => nodes.filter((n) => n.rank === r));
  const widest = Math.max(1, ...rows.map((row) => row.length));
  const width = Math.max(560, widest * (NODE_W + GAP_X) + GAP_X);
  const pos = {};
  rows.forEach((row, i) => {
    const rowW = row.length * NODE_W + (row.length - 1) * GAP_X;
    const x0 = (width - rowW) / 2;
    row.forEach((n, j) => {
      pos[n.id] = { x: x0 + j * (NODE_W + GAP_X), y: GAP_Y / 2 + i * (NODE_H + GAP_Y) };
    });
  });
  const height = rows.length * (NODE_H + GAP_Y);
  return { pos, width, height, edges: edges.filter((e) => pos[e.source] && pos[e.target]) };
}

/** Pure view: renders backend nodes/edges as SVG plus an accessible text outline. */
export function TrustGraphView({ graph }) {
  const { pos, width, height, edges } = layoutGraph(graph.nodes, graph.edges);
  return (
    <div>
      <div className="overflow-x-auto rounded-md border border-slate-200 bg-white" data-testid="trust-graph">
        <svg role="img" aria-label="Evidence graph" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
          <defs>
            {Object.entries(EDGE).map(([k, c]) => (
              <marker key={k} id={`arrow-${k}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
                <path d="M0 0 L8 4 L0 8 z" fill={c} />
              </marker>
            ))}
          </defs>
          {edges.map((e, i) => {
            const a = pos[e.source];
            const b = pos[e.target];
            const x1 = a.x + NODE_W / 2, y1 = a.y + NODE_H, x2 = b.x + NODE_W / 2, y2 = b.y;
            const my = (y1 + y2) / 2;
            return (
              <g key={`${e.source}-${e.target}-${i}`}>
                <path d={`M${x1} ${y1} C${x1} ${my}, ${x2} ${my}, ${x2} ${y2 - 2}`} fill="none" stroke={EDGE[e.kind]}
                  strokeWidth={e.kind === "baseline" ? 1 : 1.75} strokeDasharray={e.kind === "baseline" ? "3 3" : undefined}
                  markerEnd={`url(#arrow-${e.kind})`} />
                {e.label && (
                  <text x={(x1 + x2) / 2 + 4} y={my - 3} fontSize="10" fill={EDGE[e.kind]} fontWeight="600">{e.label}</text>
                )}
              </g>
            );
          })}
          {graph.nodes.filter((n) => pos[n.id]).map((n) => {
            const p = pos[n.id];
            const f = FILL[n.status] ?? FILL.info;
            return (
              <g key={n.id} transform={`translate(${p.x},${p.y})`} data-node={n.id} data-status={n.status}>
                <title>{[n.label, n.sublabel, n.detail].filter(Boolean).join(" — ")}</title>
                <rect width={NODE_W} height={NODE_H} rx="8" fill={f.box} stroke={f.stroke} strokeWidth={n.status === "verdict" ? 2.5 : 1.5}
                  strokeDasharray={f.dash} />
                <text x={NODE_W / 2} y={n.sublabel ? 24 : 33} textAnchor="middle" fontSize="12.5" fontWeight="700" fill={f.text}>
                  {clip(n.label, 20)}
                </text>
                {n.sublabel && (
                  <text x={NODE_W / 2} y={41} textAnchor="middle" fontSize="10" fill={f.text} opacity="0.85">{clip(n.sublabel, 26)}</text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-600">
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-red-500" />Deviation / suspicious</span>
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-emerald-500" />Matches baseline</span>
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-slate-400" />Baseline / info</span>
        <span><span className="mr-1 inline-block size-2 rounded-sm border border-dashed border-slate-500" />Unknown (not evaluated)</span>
      </div>
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-xs font-semibold text-slate-700">Graph as text</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-700">
          {graph.nodes.map((n) => (
            <li key={n.id}>
              <span className="font-semibold">{n.label}</span>
              {n.sublabel ? ` · ${n.sublabel}` : ""} <span className="text-slate-500">[{n.status}]</span>
            </li>
          ))}
        </ul>
      </details>
      {graph.notes.map((note) => (
        <p key={note} className="mt-2 text-xs text-slate-500">{note}</p>
      ))}
    </div>
  );
}

export default function TrustGraphCard({ graph }) {
  const aside =
    graph.version_number != null ? (
      <span className="text-xs text-slate-500">From assessment v{graph.version_number}</span>
    ) : (
      <span className="text-xs text-slate-500">No assessment yet</span>
    );
  return (
    <Card title="Evidence Graph" aside={aside}>
      <p className="mb-3 text-sm text-slate-700">
        Why this request departs from the trusted identity. The graph explains stored evidence; the risk level and the
        decision come from the deterministic engine and the analyst.
      </p>
      <TrustGraphView graph={graph} />
    </Card>
  );
}
