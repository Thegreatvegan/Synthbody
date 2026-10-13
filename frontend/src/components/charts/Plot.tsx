/**
 * The plotting engine.
 *
 * One SVG-based component handles every quantitative figure in SYNTHBODY:
 * concentration-time curves, percentile bands, observed-vs-predicted scatter,
 * residuals, tornado charts and reference bands.
 *
 * Design decisions worth knowing:
 *  - SVG, not canvas. The figures need to be exportable as vectors for
 *    publication, and the series counts here (tens, not thousands) are well
 *    inside SVG's comfortable range.
 *  - Drag to zoom on either axis, double-click to reset, shift-drag to pan.
 *    A crosshair reads out every series at the cursor's x position.
 *  - Log axes are first-class. Pharmacokinetic decline is log-linear, and a
 *    linear-only plot hides the terminal phase.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { extentOf, makeScale, padExtent, tickLabel, type ScaleType } from "../../lib/scale";
import { prettyUnit, sig } from "../../lib/format";

export interface PlotSeries {
  id: string;
  label: string;
  x: number[];
  y: number[];
  colour: string;
  /** line | points | both | step */
  kind?: "line" | "points" | "both" | "step";
  width?: number;
  dash?: string;
  opacity?: number;
  pointRadius?: number;
  /** Omit from the crosshair readout (e.g. band edges). */
  hideInReadout?: boolean;
  /** Draw an open rather than filled marker. */
  hollow?: boolean;
}

export interface PlotBand {
  id: string;
  /** Vertical band across y (a concentration range) or horizontal across x. */
  axis: "y" | "x";
  from: number;
  to: number;
  colour: string;
  label?: string;
  opacity?: number;
}

export interface PlotRibbon {
  id: string;
  x: number[];
  lower: number[];
  upper: number[];
  colour: string;
  opacity?: number;
  label?: string;
}

export interface PlotMarker {
  id: string;
  axis: "x" | "y";
  value: number;
  colour: string;
  label?: string;
  dash?: string;
}

export interface PlotProps {
  series: PlotSeries[];
  ribbons?: PlotRibbon[];
  bands?: PlotBand[];
  markers?: PlotMarker[];
  xLabel: string;
  yLabel: string;
  xUnit?: string;
  yUnit?: string;
  xScale?: ScaleType;
  yScale?: ScaleType;
  height?: number;
  /** Force a y domain instead of deriving it from the data. */
  yDomain?: [number, number];
  xDomain?: [number, number];
  showLegend?: boolean;
  showGrid?: boolean;
  /** Draw the 1:1 line (observed vs predicted plots). */
  identityLine?: boolean;
  /** Draw +-2-fold envelopes around identity. */
  foldLines?: number[];
  /** Horizontal rule at zero (residual plots). */
  zeroLine?: boolean;
  onExportName?: string;
  className?: string;
  emptyMessage?: string;
}

const M = { top: 10, right: 14, bottom: 38, left: 62 };

export function Plot({
  series,
  ribbons = [],
  bands = [],
  markers = [],
  xLabel,
  yLabel,
  xUnit,
  yUnit,
  xScale = "linear",
  yScale = "linear",
  height = 320,
  yDomain,
  xDomain,
  showLegend = true,
  showGrid = true,
  identityLine = false,
  foldLines,
  zeroLine = false,
  onExportName,
  className = "",
  emptyMessage = "No data to plot.",
}: PlotProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(640);
  const [hover, setHover] = useState<{ px: number; py: number } | null>(null);
  const [zoom, setZoom] = useState<{ x: [number, number] | null; y: [number, number] | null }>({
    x: null,
    y: null,
  });
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number; pan: boolean } | null>(
    null,
  );

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 640;
      setWidth(Math.max(240, Math.floor(w)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const plotW = Math.max(40, width - M.left - M.right);
  const plotH = Math.max(40, height - M.top - M.bottom);

  const hasData = series.some((s) => s.x.length > 0) || ribbons.some((r) => r.x.length > 0);

  const { sx, sy } = useMemo(() => {
    const xs = [...series.map((s) => s.x), ...ribbons.map((r) => r.x)];
    const ys = [
      ...series.map((s) => s.y),
      ...ribbons.map((r) => r.lower),
      ...ribbons.map((r) => r.upper),
    ];
    let [x0, x1] = xDomain ?? padExtent(...extentOf(xs, xScale === "log"), xScale, 0.02);
    let [y0, y1] = yDomain ?? padExtent(...extentOf(ys, yScale === "log"), yScale, 0.08);

    // Keep a reference band visible even when no series reaches it.
    for (const b of bands) {
      if (b.axis === "y" && !yDomain) {
        y0 = Math.min(y0, yScale === "log" ? Math.max(b.from, 1e-12) : b.from);
        y1 = Math.max(y1, b.to);
      }
      if (b.axis === "x" && !xDomain) {
        x0 = Math.min(x0, b.from);
        x1 = Math.max(x1, b.to);
      }
    }
    if (yScale === "linear" && !yDomain && y0 > 0 && !zeroLine) y0 = 0;
    if (zeroLine && !yDomain) {
      const m = Math.max(Math.abs(y0), Math.abs(y1));
      y0 = -m;
      y1 = m;
    }
    if (identityLine && !xDomain && !yDomain) {
      // Square the axes so the 1:1 line is at 45 degrees and comparisons are fair.
      const lo = Math.min(x0, y0);
      const hi = Math.max(x1, y1);
      x0 = lo;
      x1 = hi;
      y0 = lo;
      y1 = hi;
    }

    const zx = zoom.x ?? [x0, x1];
    const zy = zoom.y ?? [y0, y1];
    return {
      sx: makeScale(xScale, zx, [0, plotW]),
      sy: makeScale(yScale, zy, [plotH, 0]),
    };
  }, [series, ribbons, bands, xDomain, yDomain, xScale, yScale, plotW, plotH, zoom, identityLine, zeroLine]);

  const xTicks = useMemo(() => sx.ticks(Math.max(3, Math.floor(plotW / 78))), [sx, plotW]);
  const yTicks = useMemo(() => sy.ticks(Math.max(3, Math.floor(plotH / 42))), [sy, plotH]);

  const path = useCallback(
    (s: PlotSeries) => {
      const pts: string[] = [];
      let open = false;
      for (let i = 0; i < s.x.length; i++) {
        const xv = s.x[i]!;
        const yv = s.y[i]!;
        const bad =
          !Number.isFinite(xv) ||
          !Number.isFinite(yv) ||
          (yScale === "log" && yv <= 0) ||
          (xScale === "log" && xv <= 0);
        if (bad) {
          open = false;
          continue;
        }
        const px = sx.to(xv);
        const py = sy.to(yv);
        if (!open) {
          pts.push(`M${px.toFixed(2)},${py.toFixed(2)}`);
          open = true;
        } else if (s.kind === "step") {
          const prevY = sy.to(s.y[i - 1]!);
          pts.push(`L${px.toFixed(2)},${prevY.toFixed(2)}L${px.toFixed(2)},${py.toFixed(2)}`);
        } else {
          pts.push(`L${px.toFixed(2)},${py.toFixed(2)}`);
        }
      }
      return pts.join("");
    },
    [sx, sy, xScale, yScale],
  );

  const ribbonPath = useCallback(
    (r: PlotRibbon) => {
      const up: string[] = [];
      const dn: string[] = [];
      for (let i = 0; i < r.x.length; i++) {
        const xv = r.x[i]!;
        const u = r.upper[i]!;
        if (!Number.isFinite(xv) || !Number.isFinite(u)) continue;
        if (yScale === "log" && u <= 0) continue;
        up.push(`${sx.to(xv).toFixed(2)},${sy.to(u).toFixed(2)}`);
      }
      for (let i = r.x.length - 1; i >= 0; i--) {
        const xv = r.x[i]!;
        const l = r.lower[i]!;
        if (!Number.isFinite(xv) || !Number.isFinite(l)) continue;
        const lv = yScale === "log" ? Math.max(l, sy.domain[0]) : l;
        dn.push(`${sx.to(xv).toFixed(2)},${sy.to(lv).toFixed(2)}`);
      }
      if (!up.length) return "";
      return `M${up.join("L")}L${dn.join("L")}Z`;
    },
    [sx, sy, yScale],
  );

  // ---- interaction -------------------------------------------------------
  const toLocal = (e: React.MouseEvent): { px: number; py: number } => {
    const r = svgRef.current!.getBoundingClientRect();
    return { px: e.clientX - r.left - M.left, py: e.clientY - r.top - M.top };
  };

  const onMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const { px, py } = toLocal(e);
    setDrag({ x0: px, y0: py, x1: px, y1: py, pan: e.shiftKey });
  };

  const onMouseMove = (e: React.MouseEvent) => {
    const p = toLocal(e);
    setHover(p);
    if (!drag) return;
    if (drag.pan) {
      const dxData = sx.from(drag.x1) - sx.from(p.px);
      const dyData = sy.from(drag.y1) - sy.from(p.py);
      if (xScale === "linear") {
        setZoom((z) => ({
          ...z,
          x: [(z.x ?? sx.domain)[0] + dxData, (z.x ?? sx.domain)[1] + dxData],
        }));
      }
      if (yScale === "linear") {
        setZoom((z) => ({
          ...z,
          y: [(z.y ?? sy.domain)[0] + dyData, (z.y ?? sy.domain)[1] + dyData],
        }));
      }
      setDrag({ ...drag, x1: p.px, y1: p.py });
      return;
    }
    setDrag({ ...drag, x1: p.px, y1: p.py });
  };

  const onMouseUp = () => {
    if (!drag) return;
    const dx = Math.abs(drag.x1 - drag.x0);
    const dy = Math.abs(drag.y1 - drag.y0);
    if (!drag.pan && (dx > 8 || dy > 8)) {
      const xa = sx.from(Math.min(drag.x0, drag.x1));
      const xb = sx.from(Math.max(drag.x0, drag.x1));
      const ya = sy.from(Math.max(drag.y0, drag.y1));
      const yb = sy.from(Math.min(drag.y0, drag.y1));
      setZoom({
        x: dx > 8 ? [xa, xb] : zoom.x,
        y: dy > 8 ? [ya, yb] : zoom.y,
      });
    }
    setDrag(null);
  };

  const reset = () => setZoom({ x: null, y: null });
  const zoomed = zoom.x !== null || zoom.y !== null;

  // ---- crosshair readout -------------------------------------------------
  const readout = useMemo(() => {
    if (!hover || hover.px < 0 || hover.px > plotW || hover.py < 0 || hover.py > plotH) return null;
    const xv = sx.from(hover.px);
    const rows = series
      .filter((s) => !s.hideInReadout && s.x.length > 0)
      .map((s) => {
        // nearest sample by x
        let best = 0;
        let bestD = Infinity;
        for (let i = 0; i < s.x.length; i++) {
          const d = Math.abs(s.x[i]! - xv);
          if (d < bestD) {
            bestD = d;
            best = i;
          }
        }
        return { label: s.label, colour: s.colour, x: s.x[best]!, y: s.y[best]! };
      })
      .filter((r) => Number.isFinite(r.y));
    return { xv, rows };
  }, [hover, series, sx, plotW, plotH]);

  const exportSvg = () => {
    const svg = svgRef.current;
    if (!svg) return;
    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    // Give the exported figure an opaque background so it is usable on paper.
    const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    bg.setAttribute("width", String(width));
    bg.setAttribute("height", String(height));
    bg.setAttribute("fill", "#0b0e11");
    clone.insertBefore(bg, clone.firstChild);
    const text = new XMLSerializer().serializeToString(clone);
    const blob = new Blob([text], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${onExportName ?? "synthbody-figure"}.svg`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const identityPts = useMemo(() => {
    if (!identityLine) return null;
    const lo = Math.max(sx.domain[0], sy.domain[0]);
    const hi = Math.min(sx.domain[1], sy.domain[1]);
    return { lo, hi };
  }, [identityLine, sx, sy]);

  return (
    <div ref={hostRef} className={`relative w-full select-none ${className}`}>
      {/* toolbar */}
      <div className="absolute right-1 top-1 z-10 flex items-center gap-1 opacity-0 transition-opacity duration-120 hover:opacity-100 group-hover/plot:opacity-100 focus-within:opacity-100">
        {zoomed && (
          <button
            onClick={reset}
            className="rounded-sm border border-line-strong bg-raised px-1.5 py-0.5 text-2xs text-ink-dim hover:bg-hover hover:text-ink"
            title="Reset zoom (or double-click the plot)"
          >
            RESET
          </button>
        )}
        <button
          onClick={exportSvg}
          className="rounded-sm border border-line-strong bg-raised px-1.5 py-0.5 text-2xs text-ink-dim hover:bg-hover hover:text-ink"
          title="Export this figure as SVG"
        >
          SVG
        </button>
      </div>

      {!hasData ? (
        <div
          className="flex items-center justify-center rounded border border-dashed border-line text-xs text-ink-faint"
          style={{ height }}
        >
          {emptyMessage}
        </div>
      ) : (
        <svg
          ref={svgRef}
          width={width}
          height={height}
          className={drag?.pan ? "cursor-grabbing" : "cursor-crosshair"}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={() => {
            setHover(null);
            setDrag(null);
          }}
          onDoubleClick={reset}
        >
          <defs>
            <clipPath id={`clip-${xLabel.replace(/\W/g, "")}-${plotW}-${plotH}`}>
              <rect x={0} y={0} width={plotW} height={plotH} />
            </clipPath>
          </defs>

          <g transform={`translate(${M.left},${M.top})`}>
            {/* plot frame */}
            <rect x={0} y={0} width={plotW} height={plotH} fill="#0e1216" stroke="#232a31" />

            {/* grid */}
            {showGrid && (
              <g>
                {xTicks.map((t) => (
                  <line
                    key={`gx${t}`}
                    x1={sx.to(t)}
                    x2={sx.to(t)}
                    y1={0}
                    y2={plotH}
                    stroke="#1c2328"
                    strokeWidth={1}
                  />
                ))}
                {yTicks.map((t) => (
                  <line
                    key={`gy${t}`}
                    x1={0}
                    x2={plotW}
                    y1={sy.to(t)}
                    y2={sy.to(t)}
                    stroke="#1c2328"
                    strokeWidth={1}
                  />
                ))}
              </g>
            )}

            <g clipPath={`url(#clip-${xLabel.replace(/\W/g, "")}-${plotW}-${plotH})`}>
              {/* reference bands */}
              {bands.map((b) => {
                if (b.axis === "y") {
                  const yTop = sy.to(b.to);
                  const yBot = sy.to(b.from);
                  return (
                    <rect
                      key={b.id}
                      x={0}
                      y={Math.min(yTop, yBot)}
                      width={plotW}
                      height={Math.abs(yBot - yTop)}
                      fill={b.colour}
                      opacity={b.opacity ?? 0.1}
                    />
                  );
                }
                const xA = sx.to(b.from);
                const xB = sx.to(b.to);
                return (
                  <rect
                    key={b.id}
                    x={Math.min(xA, xB)}
                    y={0}
                    width={Math.abs(xB - xA)}
                    height={plotH}
                    fill={b.colour}
                    opacity={b.opacity ?? 0.1}
                  />
                );
              })}

              {/* percentile ribbons, widest first so narrower sit on top */}
              {ribbons.map((r) => (
                <path key={r.id} d={ribbonPath(r)} fill={r.colour} opacity={r.opacity ?? 0.16} />
              ))}

              {/* identity + fold lines for observed-vs-predicted */}
              {identityPts && (
                <>
                  {(foldLines ?? []).map((f) => (
                    <g key={`fold${f}`}>
                      <line
                        x1={sx.to(identityPts.lo)}
                        y1={sy.to(identityPts.lo * f)}
                        x2={sx.to(identityPts.hi)}
                        y2={sy.to(identityPts.hi * f)}
                        stroke="#313b45"
                        strokeDasharray="3 3"
                      />
                      <line
                        x1={sx.to(identityPts.lo)}
                        y1={sy.to(identityPts.lo / f)}
                        x2={sx.to(identityPts.hi)}
                        y2={sy.to(identityPts.hi / f)}
                        stroke="#313b45"
                        strokeDasharray="3 3"
                      />
                    </g>
                  ))}
                  <line
                    x1={sx.to(identityPts.lo)}
                    y1={sy.to(identityPts.lo)}
                    x2={sx.to(identityPts.hi)}
                    y2={sy.to(identityPts.hi)}
                    stroke="#67727c"
                    strokeWidth={1}
                  />
                </>
              )}

              {zeroLine && (
                <line x1={0} x2={plotW} y1={sy.to(0)} y2={sy.to(0)} stroke="#67727c" strokeWidth={1} />
              )}

              {/* markers */}
              {markers.map((m) =>
                m.axis === "x" ? (
                  <line
                    key={m.id}
                    x1={sx.to(m.value)}
                    x2={sx.to(m.value)}
                    y1={0}
                    y2={plotH}
                    stroke={m.colour}
                    strokeWidth={1}
                    strokeDasharray={m.dash ?? "4 3"}
                    opacity={0.8}
                  />
                ) : (
                  <line
                    key={m.id}
                    x1={0}
                    x2={plotW}
                    y1={sy.to(m.value)}
                    y2={sy.to(m.value)}
                    stroke={m.colour}
                    strokeWidth={1}
                    strokeDasharray={m.dash ?? "4 3"}
                    opacity={0.8}
                  />
                ),
              )}

              {/* series */}
              {series.map((s) => {
                const kind = s.kind ?? "line";
                return (
                  <g key={s.id}>
                    {(kind === "line" || kind === "both" || kind === "step") && (
                      <path
                        d={path(s)}
                        fill="none"
                        stroke={s.colour}
                        strokeWidth={s.width ?? 1.4}
                        strokeDasharray={s.dash}
                        opacity={s.opacity ?? 1}
                        strokeLinejoin="round"
                        strokeLinecap="round"
                      />
                    )}
                    {(kind === "points" || kind === "both") &&
                      s.x.map((xv, i) => {
                        const yv = s.y[i]!;
                        if (
                          !Number.isFinite(xv) ||
                          !Number.isFinite(yv) ||
                          (yScale === "log" && yv <= 0) ||
                          (xScale === "log" && xv <= 0)
                        )
                          return null;
                        const px = sx.to(xv);
                        const py = sy.to(yv);
                        if (px < -4 || px > plotW + 4 || py < -4 || py > plotH + 4) return null;
                        return (
                          <circle
                            key={`${s.id}-${i}`}
                            cx={px}
                            cy={py}
                            r={s.pointRadius ?? 2.6}
                            fill={s.hollow ? "#0e1216" : s.colour}
                            stroke={s.colour}
                            strokeWidth={1.2}
                            opacity={s.opacity ?? 1}
                          />
                        );
                      })}
                  </g>
                );
              })}

              {/* crosshair */}
              {hover && hover.px >= 0 && hover.px <= plotW && (
                <line
                  x1={hover.px}
                  x2={hover.px}
                  y1={0}
                  y2={plotH}
                  stroke="#3fd3bd"
                  strokeWidth={1}
                  opacity={0.45}
                  pointerEvents="none"
                />
              )}

              {/* zoom rectangle */}
              {drag && !drag.pan && (Math.abs(drag.x1 - drag.x0) > 4 || Math.abs(drag.y1 - drag.y0) > 4) && (
                <rect
                  x={Math.min(drag.x0, drag.x1)}
                  y={Math.min(drag.y0, drag.y1)}
                  width={Math.abs(drag.x1 - drag.x0)}
                  height={Math.abs(drag.y1 - drag.y0)}
                  fill="#3fd3bd"
                  fillOpacity={0.07}
                  stroke="#3fd3bd"
                  strokeDasharray="3 2"
                  pointerEvents="none"
                />
              )}
            </g>

            {/* axes */}
            <g>
              {xTicks.map((t) => (
                <g key={`xt${t}`}>
                  <line x1={sx.to(t)} x2={sx.to(t)} y1={plotH} y2={plotH + 4} stroke="#49525b" />
                  <text
                    x={sx.to(t)}
                    y={plotH + 15}
                    textAnchor="middle"
                    className="fill-ink-faint font-mono"
                    style={{ fontSize: 10 }}
                  >
                    {tickLabel(t, xScale, xTicks)}
                  </text>
                </g>
              ))}
              {yTicks.map((t) => (
                <g key={`yt${t}`}>
                  <line x1={-4} x2={0} y1={sy.to(t)} y2={sy.to(t)} stroke="#49525b" />
                  <text
                    x={-7}
                    y={sy.to(t) + 3}
                    textAnchor="end"
                    className="fill-ink-faint font-mono"
                    style={{ fontSize: 10 }}
                  >
                    {tickLabel(t, yScale, yTicks)}
                  </text>
                </g>
              ))}
              <text
                x={plotW / 2}
                y={plotH + 32}
                textAnchor="middle"
                className="fill-ink-dim"
                style={{ fontSize: 11 }}
              >
                {xLabel}
                {xUnit ? ` (${prettyUnit(xUnit)})` : ""}
              </text>
              <text
                transform={`translate(${-M.left + 12},${plotH / 2}) rotate(-90)`}
                textAnchor="middle"
                className="fill-ink-dim"
                style={{ fontSize: 11 }}
              >
                {yLabel}
                {yUnit ? ` (${prettyUnit(yUnit)})` : ""}
              </text>
            </g>
          </g>
        </svg>
      )}

      {/* crosshair tooltip */}
      {readout && readout.rows.length > 0 && (
        <div
          className="pointer-events-none absolute z-20 min-w-[150px] rounded border border-line-strong bg-void/95 px-2 py-1.5 shadow-float backdrop-blur-sm"
          style={{
            left: Math.min(hover!.px + M.left + 12, width - 180),
            top: Math.max(M.top, Math.min(hover!.py + M.top - 8, height - 24 - readout.rows.length * 15)),
          }}
        >
          <div className="mb-1 font-mono text-2xs text-ink-faint">
            {xLabel.toLowerCase().startsWith("time") ? "t = " : ""}
            {sig(readout.xv, 4)} {xUnit ? prettyUnit(xUnit) : ""}
          </div>
          {readout.rows.map((r) => (
            <div key={r.label} className="flex items-center gap-1.5 whitespace-nowrap">
              <span className="h-[2px] w-2.5 shrink-0" style={{ background: r.colour }} />
              <span className="flex-1 truncate text-2xs text-ink-dim">{r.label}</span>
              <span className="font-mono text-2xs text-ink tnum">{sig(r.y, 4)}</span>
            </div>
          ))}
        </div>
      )}

      {/* legend */}
      {showLegend && hasData && (
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
          {ribbons.map((r) =>
            r.label ? (
              <span key={r.id} className="flex items-center gap-1.5 text-2xs text-ink-faint">
                <span
                  className="h-2.5 w-3.5 rounded-[1px]"
                  style={{ background: r.colour, opacity: 0.35 }}
                />
                {r.label}
              </span>
            ) : null,
          )}
          {series
            .filter((s) => !s.hideInReadout)
            .map((s) => (
              <span key={s.id} className="flex items-center gap-1.5 text-2xs text-ink-dim">
                {(s.kind ?? "line") === "points" ? (
                  <span
                    className="h-2 w-2 rounded-full border"
                    style={{ borderColor: s.colour, background: s.hollow ? "transparent" : s.colour }}
                  />
                ) : (
                  <span
                    className="h-[2px] w-3.5"
                    style={{
                      background: s.dash ? "transparent" : s.colour,
                      borderTop: s.dash ? `2px dashed ${s.colour}` : undefined,
                    }}
                  />
                )}
                {s.label}
              </span>
            ))}
          {bands.map((b) =>
            b.label ? (
              <span key={b.id} className="flex items-center gap-1.5 text-2xs text-ink-faint">
                <span
                  className="h-2.5 w-3.5 rounded-[1px]"
                  style={{ background: b.colour, opacity: 0.28 }}
                />
                {b.label}
              </span>
            ) : null,
          )}
          <span className="ml-auto text-2xs text-ink-ghost">
            drag = zoom · shift-drag = pan · dbl-click = reset
          </span>
        </div>
      )}
    </div>
  );
}
