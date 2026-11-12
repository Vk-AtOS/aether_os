import { useState, useEffect, useRef, useCallback } from "react";
import * as d3 from "d3";
import {
  Brain, RefreshCw, Loader2, Search, Clock, Tag,
  ArrowRight, Layers, Star, AlertCircle, ZoomIn, ZoomOut, Maximize2,
} from "lucide-react";
import api from "../api";

// ── Similarity match card ─────────────────────────────────────────────────────
function SimilarRunCard({ run }) {
  const sim = run.similarity || 0;
  const simColor = sim >= 0.8 ? "text-green-400" : sim >= 0.6 ? "text-amber-400" : "text-muted";
  const simBg   = sim >= 0.8 ? "bg-green-950/40 border-green-900"
                : sim >= 0.6 ? "bg-amber-950/40 border-amber-900"
                : "bg-surface border-border";
  return (
    <div className={`rounded-xl border p-4 ${simBg}`}>
      <div className="flex items-start justify-between mb-2">
        <div>
          <p className="font-medium text-bright text-sm">{run.project || "Unnamed project"}</p>
          <p className="text-xs text-muted mt-0.5">{run.run_id?.substring(0, 8)}</p>
        </div>
        <div className={`text-lg font-bold ${simColor}`}>{Math.round(sim * 100)}%</div>
      </div>
      {run.domain && (
        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-panel border border-border rounded-full text-muted">
          <Tag size={10} /> {run.domain}
        </span>
      )}
      {run.hint && <p className="text-xs text-muted mt-2 italic">"{run.hint}"</p>}
    </div>
  );
}

// ── D3 force-directed graph ───────────────────────────────────────────────────
const ZoomButton = ({ label, onClick, children }) => (
  <button onClick={onClick} title={label} aria-label={label}
    className="w-7 h-7 flex items-center justify-center rounded-lg bg-panel border border-border text-muted hover:text-bright hover:border-blue-500/50 transition-colors">
    {children}
  </button>
);

function ForceGraph({ nodes, edges, width = 800, height = 520 }) {
  const svgRef  = useRef(null);
  const simRef  = useRef(null);
  const zoomRef = useRef(null);
  const [tooltip, setTooltip] = useState(null);

  const resetZoom = useCallback(() => {
    if (svgRef.current && zoomRef.current)
      d3.select(svgRef.current).transition().duration(500)
        .call(zoomRef.current.transform, d3.zoomIdentity);
  }, []);

  const zoomBy = useCallback((factor) => {
    if (svgRef.current && zoomRef.current)
      d3.select(svgRef.current).transition().duration(300)
        .call(zoomRef.current.scaleBy, factor);
  }, []);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    if (!nodes.length) return;

    // Deep-clone so D3 mutates positions without touching React state
    const nodeData = nodes.map((n) => ({ ...n }));
    const idSet    = new Set(nodeData.map((n) => n.id));
    const linkData = edges
      .filter((e) => idSet.has(e.source) && idSet.has(e.target))
      .map((e) => ({ ...e }));

    // Colour palette — each task_type cluster gets a distinct hue
    const clusterPalette = d3.schemeTableau10;
    const clusterMap = {};
    nodeData.filter((n) => n.type === "task_type").forEach((n, i) => {
      clusterMap[n.id] = clusterPalette[i % clusterPalette.length];
    });
    const nodeColor = (d) => {
      if (d.type === "task_type") return clusterMap[d.id] ?? "#3b82f6";
      return (clusterMap[`task:${d.task_type}`] ?? "#8b5cf6") + "bb";
    };
    const linkColor = (d) => {
      const src = typeof d.source === "object" ? d.source.id : d.source;
      return (clusterMap[src] ?? "#4b5563") + "66";
    };

    // SVG structure
    const defs = svg.append("defs");
    // Glow filter for cluster nodes
    const filt = defs.append("filter").attr("id", "glow-mem");
    filt.append("feGaussianBlur").attr("stdDeviation", "3.5").attr("result", "blur");
    const merge = filt.append("feMerge");
    merge.append("feMergeNode").attr("in", "blur");
    merge.append("feMergeNode").attr("in", "SourceGraphic");
    // Arrowhead marker
    defs.append("marker")
      .attr("id", "mem-arrow")
      .attr("viewBox", "0 -4 8 8")
      .attr("refX", 20).attr("refY", 0)
      .attr("markerWidth", 5).attr("markerHeight", 5)
      .attr("orient", "auto")
      .append("path").attr("d", "M0,-4L8,0L0,4").attr("fill", "#475569");

    const g = svg.append("g").attr("class", "graph-root");

    // Zoom
    const zoom = d3.zoom().scaleExtent([0.1, 8])
      .on("zoom", (ev) => g.attr("transform", ev.transform));
    zoomRef.current = zoom;
    svg.call(zoom).on("dblclick.zoom", null);

    // Force simulation
    const sim = d3.forceSimulation(nodeData)
      .force("link",    d3.forceLink(linkData).id((d) => d.id).distance(95).strength(0.4))
      .force("charge",  d3.forceManyBody().strength((d) => d.type === "task_type" ? -700 : -130))
      .force("center",  d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide().radius((d) => d.type === "task_type" ? 52 : 24).strength(0.85))
      .force("x", d3.forceX(width / 2).strength(0.035))
      .force("y", d3.forceY(height / 2).strength(0.035))
      .alphaDecay(0.022);
    simRef.current = sim;

    // Links
    const link = g.append("g")
      .selectAll("line").data(linkData).join("line")
      .attr("stroke", linkColor)
      .attr("stroke-width", (d) => Math.max(1, Math.sqrt(d.weight || 1)))
      .attr("stroke-linecap", "round")
      .attr("marker-end", "url(#mem-arrow)");

    // Node groups
    const nodeG = g.append("g")
      .selectAll("g").data(nodeData).join("g")
      .attr("cursor", "grab")
      .call(
        d3.drag()
          .on("start", (ev, d) => {
            if (!ev.active) sim.alphaTarget(0.3).restart();
            d.fx = d.x; d.fy = d.y;
          })
          .on("drag",  (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
          .on("end",   (ev, d) => {
            if (!ev.active) sim.alphaTarget(0);
            d.fx = null; d.fy = null;
          }),
      );

    // Circle
    nodeG.append("circle")
      .attr("r",              (d) => d.type === "task_type" ? 34 : 14)
      .attr("fill",           nodeColor)
      .attr("fill-opacity",   (d) => d.type === "task_type" ? 0.88 : 0.65)
      .attr("stroke",         nodeColor)
      .attr("stroke-width",   (d) => d.type === "task_type" ? 2.5 : 1.5)
      .attr("stroke-opacity", 0.95)
      .attr("filter",         (d) => d.type === "task_type" ? "url(#glow-mem)" : null);

    // Primary label
    nodeG.append("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("dy", (d) => d.type === "task_type" ? 0 : -22)
      .attr("font-size",   (d) => d.type === "task_type" ? "10px" : "8px")
      .attr("font-weight", (d) => d.type === "task_type" ? "700" : "400")
      .attr("fill", "#e2e8f0")
      .attr("pointer-events", "none")
      .text((d) =>
        d.type === "task_type" ? d.label
          : d.label?.length > 24 ? d.label.slice(0, 24) + "…" : (d.label ?? ""));

    // Count badge on cluster nodes
    nodeG.filter((d) => d.type === "task_type" && d.count != null)
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "3.0em")
      .attr("font-size", "8px")
      .attr("fill", "#94a3b8")
      .attr("pointer-events", "none")
      .text((d) => `${d.count} records`);

    // Tooltip
    nodeG
      .on("mouseenter", (ev, d) => {
        const rect = svgRef.current.getBoundingClientRect();
        setTooltip({ x: ev.clientX - rect.left, y: ev.clientY - rect.top, data: d });
      })
      .on("mousemove", (ev) => {
        const rect = svgRef.current.getBoundingClientRect();
        setTooltip((t) => t ? { ...t, x: ev.clientX - rect.left, y: ev.clientY - rect.top } : null);
      })
      .on("mouseleave", () => setTooltip(null));

    // Tick
    sim.on("tick", () => {
      link
        .attr("x1", (d) => d.source.x ?? 0).attr("y1", (d) => d.source.y ?? 0)
        .attr("x2", (d) => d.target.x ?? 0).attr("y2", (d) => d.target.y ?? 0);
      nodeG.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    return () => { sim.stop(); };
  }, [nodes, edges, width, height]);

  return (
    <div className="relative w-full" style={{ height }}>
      {/* Zoom controls */}
      <div className="absolute top-3 right-3 z-10 flex flex-col gap-1">
        <ZoomButton label="Zoom in" onClick={() => zoomBy(1.4)}><ZoomIn size={13} /></ZoomButton>
        <ZoomButton label="Zoom out" onClick={() => zoomBy(0.7)}><ZoomOut size={13} /></ZoomButton>
        <ZoomButton label="Reset" onClick={resetZoom}><Maximize2 size={13} /></ZoomButton>
      </div>

      {/* Legend */}
      <div className="absolute bottom-3 left-3 z-10 flex gap-4 bg-panel/80 backdrop-blur-sm border border-border rounded-lg px-3 py-2">
        <span className="flex items-center gap-1.5 text-xs text-muted">
          <span className="w-3 h-3 rounded-full bg-blue-500 inline-block" /> Cluster
        </span>
        <span className="flex items-center gap-1.5 text-xs text-muted">
          <span className="w-2 h-2 rounded-full bg-violet-500 inline-block" /> Memory record
        </span>
        <span className="text-xs text-muted/50">Drag · Scroll to zoom</span>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div className="absolute z-20 pointer-events-none bg-panel border border-border rounded-xl shadow-xl p-3 text-xs max-w-xs"
          style={{ left: tooltip.x + 14, top: tooltip.y - 10 }}>
          <p className="font-semibold text-bright mb-1">{tooltip.data.label}</p>
          <p className="text-muted capitalize">Type: {tooltip.data.type?.replace("_", " ")}</p>
          {tooltip.data.count        != null && <p className="text-muted">Records: {tooltip.data.count}</p>}
          {tooltip.data.success_count != null && <p className="text-muted">Successes: {tooltip.data.success_count}</p>}
          {tooltip.data.task_type    != null && <p className="text-muted">Cluster: {tooltip.data.task_type}</p>}
        </div>
      )}

      <svg ref={svgRef} width="100%" height={height}
        className="rounded-xl bg-surface/30 border border-border" />
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
const GRAPH_LIMIT = 50;

export default function MemoryInspector() {
  const [prefs,        setPrefs]        = useState({});
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState(null);
  const [testInput,    setTestInput]    = useState("");
  const [searching,    setSearching]    = useState(false);
  const [matchResults, setMatchResults] = useState(null);
  const [cacheStats,   setCacheStats]   = useState(null);
  const [graphData,    setGraphData]    = useState({ nodes: [], edges: [], stats: {} });
  const [graphLoading, setGraphLoading] = useState(true);
  const [graphPage,    setGraphPage]    = useState(0);
  const containerRef = useRef(null);
  const [graphWidth,   setGraphWidth]   = useState(800);

  // Measure container for responsive graph sizing
  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver(([entry]) => setGraphWidth(entry.contentRect.width || 800));
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  // Promise chain with no state set before the request: this runs from an effect.
  // Callers that want the spinner set graphLoading themselves.
  const fetchGraph = useCallback((page = 0) => api.client
    .get(`/memory/graph?limit=${GRAPH_LIMIT}&offset=${page * GRAPH_LIMIT}`)
    .catch(() => ({ data: { nodes: [], edges: [], stats: {} } }))
    .then((res) => setGraphData(res.data || { nodes: [], edges: [], stats: {} }))
    .finally(() => setGraphLoading(false)), []);

  useEffect(() => { fetchGraph(graphPage); }, [fetchGraph, graphPage]);

  useEffect(() => {
    Promise.all([
      api.client.get("/settings/preferences").catch(() => ({ data: {} })),
      api.client.get("/system/costs").catch(() => ({ data: {} })),
    ])
      .then(([prefsRes, cacheRes]) => {
        setPrefs(prefsRes.data || {});
        setCacheStats(cacheRes.data?.cache || null);
      })
      .catch(() => setError("Could not load memory data"))
      .finally(() => setLoading(false));
  }, []);

  const handleSearch = async () => {
    if (!testInput.trim()) return;
    setSearching(true);
    setMatchResults(null);
    try {
      const res = await api.client.post("/memory/search", { query: testInput, top_k: 5 })
        .catch(() => ({ data: { matches: [] } }));
      setMatchResults(res.data);
    } finally {
      setSearching(false);
    }
  };

  const prefEntries = Object.entries(prefs).filter(([k]) => k !== "password" && k !== "token");
  const stats = graphData.stats || {};

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <Loader2 size={24} className="animate-spin text-blue-500" />
    </div>
  );

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright">Memory Inspector</h1>
          <p className="text-sm text-muted mt-1">Cross-run learning · Session preferences · Knowledge graph</p>
        </div>
        <button onClick={() => { setGraphLoading(true); fetchGraph(graphPage); }} disabled={graphLoading}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border text-muted hover:text-bright hover:border-blue-500/50 text-xs transition-colors disabled:opacity-50">
          <RefreshCw size={13} className={graphLoading ? "animate-spin" : ""} />
          Refresh graph
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-amber-950/40 border border-amber-900 rounded-lg text-amber-400 text-sm flex items-center gap-2">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Overview cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="bg-panel rounded-xl border border-border p-5">
          <div className="flex items-center gap-2 mb-3 text-purple-400">
            <Brain size={18} />
            <span className="font-semibold text-sm text-bright">Cross-Run Learning</span>
          </div>
          <p className="text-xs text-muted">Patterns extracted from every completed run are injected as context into similar future projects.</p>
          <div className="mt-3 flex items-center gap-2 text-xs flex-wrap">
            <span className="font-bold text-bright">{stats.total_records ?? 0}</span>
            <span className="text-muted">records ·</span>
            <span className="font-bold text-bright">{Object.keys(stats.by_task_type || {}).length}</span>
            <span className="text-muted">task types</span>
          </div>
        </div>

        <div className="bg-panel rounded-xl border border-border p-5">
          <div className="flex items-center gap-2 mb-3 text-blue-400">
            <Layers size={18} />
            <span className="font-semibold text-sm text-bright">Session Memory</span>
          </div>
          <p className="text-xs text-muted">User preferences persisted across sessions — no need to repeat instructions.</p>
          <div className="mt-3 text-xs text-muted">{prefEntries.length} preference{prefEntries.length !== 1 ? "s" : ""} stored</div>
        </div>

        <div className="bg-panel rounded-xl border border-border p-5">
          <div className="flex items-center gap-2 mb-3 text-green-400">
            <RefreshCw size={18} />
            <span className="font-semibold text-sm text-bright">LLM Cache</span>
          </div>
          <p className="text-xs text-muted">Identical LLM calls cached by content hash. Repeated prompts cost $0.</p>
          {cacheStats ? (
            <div className="mt-3 text-xs text-muted space-y-0.5">
              <div>{(cacheStats.total_entries ?? 0).toLocaleString()} cached responses</div>
              <div>{(cacheStats.total_hits ?? 0).toLocaleString()} total hits</div>
            </div>
          ) : <div className="mt-3 text-xs text-muted/50">Cache data unavailable</div>}
        </div>
      </div>

      {/* ── D3 Knowledge Graph ─────────────────────────────────────────────── */}
      <div className="bg-panel rounded-xl border border-border p-6 mb-6" ref={containerRef}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-semibold text-bright flex items-center gap-2">
              <Brain size={16} className="text-purple-400" /> Knowledge Graph
            </h2>
            <p className="text-xs text-muted mt-0.5">
              Force-directed topology of memory clusters and individual records.
            </p>
          </div>
          {graphLoading && <Loader2 size={15} className="animate-spin text-muted" />}
        </div>

        {graphData.nodes.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-muted text-sm gap-3">
            <Brain size={40} className="opacity-20" />
            <p>No memory records yet — graph populates as runs complete.</p>
          </div>
        ) : (
          <ForceGraph nodes={graphData.nodes} edges={graphData.edges} width={graphWidth} height={520} />
        )}
        <div className="flex items-center justify-between mt-3">
          <span className="text-xs text-muted">
            Showing up to {GRAPH_LIMIT} nodes · Page {graphPage + 1}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => { setGraphLoading(true); setGraphPage(Math.max(0, graphPage - 1)); }}
              disabled={graphPage === 0 || graphLoading}
              className="px-3 py-1 text-xs rounded border border-border text-muted hover:text-bright disabled:opacity-40 transition-colors"
            >
              Prev
            </button>
            <button
              onClick={() => { setGraphLoading(true); setGraphPage(graphPage + 1); }}
              disabled={graphData.nodes.length < GRAPH_LIMIT || graphLoading}
              className="px-3 py-1 text-xs rounded border border-border text-muted hover:text-bright disabled:opacity-40 transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      {/* ── Similarity search ──────────────────────────────────────────────── */}
      <div className="bg-panel rounded-xl border border-border p-6 mb-6">
        <h2 className="font-semibold text-bright mb-1 flex items-center gap-2">
          <Search size={16} /> Test Memory Recall
        </h2>
        <p className="text-xs text-muted mb-4">Enter a project description to see what past runs AetherOS would inject as context.</p>
        <div className="flex gap-3">
          <textarea rows={2} value={testInput} onChange={(e) => setTestInput(e.target.value)}
            placeholder="e.g. Build a SaaS app with Stripe subscriptions and user authentication…"
            className="flex-1 px-3 py-2 border border-border rounded-xl text-sm bg-background text-bright focus:outline-none focus:border-blue-400 resize-none" />
          <button onClick={handleSearch} disabled={searching || !testInput.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded-xl text-sm hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2 self-start">
            {searching ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
            Recall
          </button>
        </div>
        {matchResults && (
          <div className="mt-4">
            {matchResults.matches?.length > 0 ? (
              <>
                <p className="text-xs font-semibold text-muted mb-3 uppercase tracking-wide">
                  {matchResults.matches.length} similar past run{matchResults.matches.length !== 1 ? "s" : ""} found
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {matchResults.matches.map((m, i) => <SimilarRunCard key={i} run={m} />)}
                </div>
              </>
            ) : (
              <div className="mt-3 flex items-center gap-2 text-muted text-sm">
                <Clock size={14} /> No similar runs found — memory builds as you complete more projects.
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Stored Preferences ────────────────────────────────────────────── */}
      <div className="bg-panel rounded-xl border border-border p-6">
        <h2 className="font-semibold text-bright mb-4 flex items-center gap-2">
          <Star size={16} /> Stored Preferences
        </h2>
        {prefEntries.length === 0 ? (
          <p className="text-sm text-muted">No preferences stored yet. Settings you configure (preferred framework, domain, etc.) are automatically saved here.</p>
        ) : (
          <div className="divide-y divide-border/40">
            {prefEntries.map(([k, v]) => (
              <div key={k} className="flex items-start py-2">
                <span className="text-sm font-mono text-blue-400 w-48 shrink-0">{k}</span>
                <span className="text-sm text-muted ml-4">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
