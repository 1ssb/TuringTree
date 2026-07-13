import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Maximize2, Minus, Plus, X } from "lucide-react";

import { getIndexTree, type TreeNode } from "@/lib/api";

/**
 * TreeView — an interactive visualization of the PageIndex reasoning tree.
 *
 * The corpus is laid out as a tidy left-to-right tree (computed here, no deps),
 * rendered as static SVG with smooth bezier links. Pan and zoom are applied
 * imperatively to a single <g transform> via refs, so dragging/zooming never
 * re-renders React — it stays smooth even with a large tree.
 */

const LEVEL_GAP = 240; // horizontal distance between depths
const ROW_GAP = 30; // vertical distance between leaf rows
const FIT_PADDING = 90;
const MIN_K = 0.2;
const MAX_K = 3;

interface Positioned {
  node: TreeNode;
  x: number;
  y: number;
  children: Positioned[];
}

interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

function buildLayout(root: TreeNode) {
  let nextY = 0;
  const all: Positioned[] = [];

  const place = (node: TreeNode, depth: number): Positioned => {
    const p: Positioned = { node, x: depth * LEVEL_GAP, y: 0, children: [] };
    all.push(p);
    const kids = node.children ?? [];
    if (kids.length === 0) {
      p.y = nextY;
      nextY += ROW_GAP;
    } else {
      p.children = kids.map((c) => place(c, depth + 1));
      p.y = (p.children[0].y + p.children[p.children.length - 1].y) / 2;
    }
    return p;
  };

  const rootP = place(root, 0);

  const links: { source: Positioned; target: Positioned }[] = [];
  const collect = (p: Positioned) => {
    for (const c of p.children) {
      links.push({ source: p, target: c });
      collect(c);
    }
  };
  collect(rootP);

  const bounds: Bounds =
    all.length === 0
      ? { minX: 0, minY: 0, maxX: 0, maxY: 0 }
      : {
          minX: Math.min(...all.map((p) => p.x)),
          minY: Math.min(...all.map((p) => p.y)),
          maxX: Math.max(...all.map((p) => p.x)),
          maxY: Math.max(...all.map((p) => p.y)),
        };

  return { nodes: all, links, bounds };
}

function linkPath(s: Positioned, t: Positioned): string {
  const midX = (s.x + t.x) / 2;
  return `M${s.x},${s.y} C${midX},${s.y} ${midX},${t.y} ${t.x},${t.y}`;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function NodeMark({ p }: { p: Positioned }) {
  const { node } = p;
  const isRoot = node.kind === "root";
  const isDoc = node.kind === "doc";
  const r = isRoot ? 8 : isDoc ? 6 : 4;
  const label =
    node.name.length > 36 ? `${node.name.slice(0, 36)}…` : node.name;

  return (
    <g transform={`translate(${p.x},${p.y})`} className="group">
      <title>{node.summary ? `${node.name} — ${node.summary}` : node.name}</title>
      {/* hover halo */}
      <circle
        r={r + 5}
        className="fill-none stroke-accent/0 transition-all duration-150 group-hover:stroke-accent/40"
        strokeWidth={1.5}
      />
      <circle
        r={r}
        className={
          isDoc ? "fill-accent" : isRoot ? "" : "fill-muted/70"
        }
        style={isRoot ? { fill: "url(#treeGrad)" } : undefined}
      />
      <text
        x={r + 10}
        dominantBaseline="middle"
        className={`${
          isRoot || isDoc ? "fill-foreground font-medium" : "fill-foreground/70"
        } pointer-events-none select-none text-[12.5px]`}
        style={{
          paintOrder: "stroke",
          stroke: "hsl(var(--surface-1))",
          strokeWidth: 4,
          strokeLinejoin: "round",
        }}
      >
        {label}
      </text>
    </g>
  );
}

export function TreeView({ onClose }: { onClose: () => void }) {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const view = useRef({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getIndexTree(ctrl.signal)
      .then(setTree)
      .catch((e) => {
        if (!ctrl.signal.aborted)
          setError(e instanceof Error ? e.message : "Failed to load the tree.");
      })
      .finally(() => !ctrl.signal.aborted && setLoading(false));
    return () => ctrl.abort();
  }, []);

  const { nodes, links, bounds } = useMemo(
    () =>
      tree
        ? buildLayout(tree)
        : { nodes: [], links: [], bounds: { minX: 0, minY: 0, maxX: 0, maxY: 0 } },
    [tree],
  );

  const applyTransform = () => {
    const { x, y, k } = view.current;
    gRef.current?.setAttribute("transform", `translate(${x},${y}) scale(${k})`);
  };

  const fit = () => {
    const svg = svgRef.current;
    if (!svg || nodes.length === 0) return;
    const rect = svg.getBoundingClientRect();
    const treeW = bounds.maxX - bounds.minX + 260; // label room
    const treeH = bounds.maxY - bounds.minY + 80;
    const k = clamp(
      Math.min(
        (rect.width - FIT_PADDING * 2) / treeW,
        (rect.height - FIT_PADDING * 2) / treeH,
      ),
      MIN_K,
      1.1,
    );
    view.current.k = k;
    view.current.x =
      FIT_PADDING + (rect.width - FIT_PADDING * 2 - treeW * k) / 2 - bounds.minX * k;
    view.current.y = (rect.height - treeH * k) / 2 - bounds.minY * k + 20 * k;
    applyTransform();
  };

  // Fit before paint whenever the node set changes, and on window resize.
  useLayoutEffect(() => {
    fit();
    const onResize = () => fit();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes.length]);

  // Wheel zoom — attached natively so we can preventDefault (React wheel is passive).
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const k0 = view.current.k;
      const k1 = clamp(k0 * Math.exp(-e.deltaY * 0.0015), MIN_K, MAX_K);
      view.current.x = cx - (cx - view.current.x) * (k1 / k0);
      view.current.y = cy - (cy - view.current.y) * (k1 / k0);
      view.current.k = k1;
      applyTransform();
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, []);

  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    drag.current = { x: e.clientX - view.current.x, y: e.clientY - view.current.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!drag.current) return;
    view.current.x = e.clientX - drag.current.x;
    view.current.y = e.clientY - drag.current.y;
    applyTransform();
  };
  const endDrag = () => {
    drag.current = null;
  };

  const zoomBy = (factor: number) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    const k0 = view.current.k;
    const k1 = clamp(k0 * factor, MIN_K, MAX_K);
    view.current.x = cx - (cx - view.current.x) * (k1 / k0);
    view.current.y = cy - (cy - view.current.y) * (k1 / k0);
    view.current.k = k1;
    applyTransform();
  };

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* backdrop */}
      <button
        aria-label="Close tree"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-background/70 backdrop-blur-sm"
      />

      {/* panel */}
      <div className="relative m-3 flex flex-1 animate-fade-up-sm flex-col overflow-hidden rounded-2xl border border-line/15 bg-surface-1 shadow-[0_40px_120px_-30px_rgba(0,0,0,0.85)] sm:m-6">
        {/* header */}
        <div className="flex items-center gap-3 border-b border-line/10 px-4 py-3">
          <img
            src="/tree-with-hierarchical-network-svgrepo-com.svg"
            alt=""
            className="h-[18px] w-[18px] opacity-80 [filter:invert(1)]"
          />
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-foreground">Reasoning tree</p>
            <p className="truncate text-[11px] text-muted">
              {nodes.filter((p) => p.node.kind === "doc").length} documents · drag
              to pan · scroll to zoom
            </p>
          </div>
          <div className="ml-auto flex items-center gap-1">
            <button
              onClick={() => zoomBy(1 / 1.25)}
              aria-label="Zoom out"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
            >
              <Minus className="h-4 w-4" />
            </button>
            <button
              onClick={() => zoomBy(1.25)}
              aria-label="Zoom in"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
            >
              <Plus className="h-4 w-4" />
            </button>
            <button
              onClick={fit}
              aria-label="Fit to screen"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
            >
              <Maximize2 className="h-[15px] w-[15px]" />
            </button>
            <span className="mx-1 h-5 w-px bg-line/15" />
            <button
              onClick={onClose}
              aria-label="Close"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
            >
              <X className="h-[18px] w-[18px]" />
            </button>
          </div>
        </div>

        {/* canvas */}
        <div className="relative flex-1 overflow-hidden">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center text-[13px] text-muted">
              Loading the tree…
            </div>
          )}
          {error && (
            <div className="absolute inset-0 flex items-center justify-center px-6 text-center text-[13px] text-[#e3866b]">
              {error}
            </div>
          )}
          {!loading && !error && nodes.length <= 1 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center text-[13px] text-muted">
              No index yet — upload a folder and build the index to see its tree.
            </div>
          )}

          <svg
            ref={svgRef}
            className="h-full w-full cursor-grab touch-none select-none active:cursor-grabbing"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerLeave={endDrag}
            onPointerCancel={endDrag}
          >
            <defs>
              <linearGradient id="treeGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#6366f1" />
                <stop offset="0.5" stopColor="#a855f7" />
                <stop offset="1" stopColor="#fcd34d" />
              </linearGradient>
            </defs>
            <g ref={gRef}>
              {links.map((l, i) => (
                <path
                  key={i}
                  d={linkPath(l.source, l.target)}
                  className="fill-none stroke-line/25"
                  strokeWidth={1.3}
                />
              ))}
              {nodes.map((p, i) => (
                <NodeMark key={i} p={p} />
              ))}
            </g>
          </svg>
        </div>
      </div>
    </div>
  );
}
