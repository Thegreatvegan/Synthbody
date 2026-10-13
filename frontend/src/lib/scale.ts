/**
 * Scales and tick generation for the plotting engine.
 *
 * Written rather than pulled from d3 so that tick behaviour on log axes (where
 * pharmacokinetic plots live half the time) is exactly what we want: decade
 * majors with 2/5 minors, and sensible behaviour when the data spans less than
 * one decade.
 */

export type ScaleType = "linear" | "log";

export interface Scale {
  type: ScaleType;
  domain: [number, number];
  range: [number, number];
  /** data value -> pixel */
  to: (v: number) => number;
  /** pixel -> data value */
  from: (px: number) => number;
  ticks: (target?: number) => number[];
  minorTicks: (target?: number) => number[];
  clampDomain: (v: number) => number;
}

const LOG_FLOOR = 1e-12;

export function makeScale(
  type: ScaleType,
  domain: [number, number],
  range: [number, number],
): Scale {
  let [d0, d1] = domain;

  if (type === "log") {
    // A log axis cannot show zero or negatives. Floor the domain at a value
    // small enough to be visually "zero" but finite.
    d0 = Math.max(d0, LOG_FLOOR);
    d1 = Math.max(d1, d0 * 10);
  }
  if (d1 === d0) {
    // Degenerate domain (a flat series). Open it out so something is drawn.
    const pad = Math.abs(d0) > 0 ? Math.abs(d0) * 0.1 : 1;
    d0 -= pad;
    d1 += pad;
  }

  const [r0, r1] = range;

  const fwd =
    type === "log"
      ? (v: number) => {
          const lv = Math.log10(Math.max(v, LOG_FLOOR));
          const l0 = Math.log10(d0);
          const l1 = Math.log10(d1);
          return r0 + ((lv - l0) / (l1 - l0)) * (r1 - r0);
        }
      : (v: number) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);

  const inv =
    type === "log"
      ? (px: number) => {
          const l0 = Math.log10(d0);
          const l1 = Math.log10(d1);
          const t = (px - r0) / (r1 - r0);
          return 10 ** (l0 + t * (l1 - l0));
        }
      : (px: number) => d0 + ((px - r0) / (r1 - r0)) * (d1 - d0);

  return {
    type,
    domain: [d0, d1],
    range: [r0, r1],
    to: fwd,
    from: inv,
    ticks: (target = 6) => (type === "log" ? logTicks(d0, d1) : niceTicks(d0, d1, target)),
    minorTicks: (target = 6) =>
      type === "log" ? logMinorTicks(d0, d1) : minorBetween(niceTicks(d0, d1, target)),
    clampDomain: (v: number) => Math.min(Math.max(v, d0), d1),
  };
}

/**
 * Linear ticks on 1/2/5 x 10^n steps, the convention engineering plots use.
 */
export function niceTicks(lo: number, hi: number, target = 6): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return [lo];
  const raw = (hi - lo) / Math.max(target, 2);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const start = Math.ceil(lo / step) * step;
  const out: number[] = [];
  for (let v = start; v <= hi + step * 1e-9; v += step) {
    // Re-round to kill floating-point dust like 0.30000000000000004.
    out.push(Number(v.toPrecision(12)));
  }
  return out;
}

function minorBetween(majors: number[]): number[] {
  if (majors.length < 2) return [];
  const step = (majors[1]! - majors[0]!) / 2;
  const out: number[] = [];
  for (let i = 0; i < majors.length - 1; i++) out.push(majors[i]! + step);
  return out;
}

/** Decade majors. If the span is under ~1.5 decades, add 2/5 subdivisions. */
export function logTicks(lo: number, hi: number): number[] {
  const l0 = Math.floor(Math.log10(lo));
  const l1 = Math.ceil(Math.log10(hi));
  const decades = l1 - l0;
  const out: number[] = [];
  const mults = decades <= 2 ? [1, 2, 5] : decades <= 5 ? [1, 3] : [1];
  for (let e = l0; e <= l1; e++) {
    for (const m of mults) {
      const v = m * 10 ** e;
      if (v >= lo * 0.999 && v <= hi * 1.001) out.push(Number(v.toPrecision(12)));
    }
  }
  return out.length ? out : [lo, hi];
}

export function logMinorTicks(lo: number, hi: number): number[] {
  const l0 = Math.floor(Math.log10(lo));
  const l1 = Math.ceil(Math.log10(hi));
  const out: number[] = [];
  for (let e = l0; e <= l1; e++) {
    for (let m = 2; m <= 9; m++) {
      const v = m * 10 ** e;
      if (v >= lo && v <= hi) out.push(v);
    }
  }
  return out;
}

/** Format a tick label with the fewest digits that keeps ticks distinct. */
export function tickLabel(v: number, type: ScaleType, allTicks: number[]): string {
  if (type === "log") {
    if (v >= 1e5 || (v < 1e-3 && v > 0)) {
      const e = Math.round(Math.log10(v));
      if (10 ** e === v) return `1e${e}`;
      return v.toExponential(0);
    }
    if (v >= 1) return String(Number(v.toPrecision(3)));
    return String(Number(v.toPrecision(2)));
  }
  const span = allTicks.length > 1 ? Math.abs(allTicks[allTicks.length - 1]! - allTicks[0]!) : Math.abs(v);
  if (span === 0) return String(v);
  if (Math.abs(v) >= 1e5 || (span < 1e-3 && span > 0)) return v.toExponential(1);
  const step = allTicks.length > 1 ? Math.abs(allTicks[1]! - allTicks[0]!) : span;
  const decimals = Math.max(0, Math.min(6, Math.ceil(-Math.log10(step)) + 0));
  return v.toFixed(decimals);
}

/** Expand a data extent by a fractional pad, honouring the scale type. */
export function padExtent(
  lo: number,
  hi: number,
  type: ScaleType,
  frac = 0.06,
): [number, number] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (type === "log") {
    const l = Math.log10(Math.max(lo, LOG_FLOOR));
    const h = Math.log10(Math.max(hi, Math.max(lo, LOG_FLOOR) * 10));
    const d = (h - l) * frac;
    return [10 ** (l - d), 10 ** (h + d)];
  }
  if (hi === lo) {
    const p = Math.abs(hi) > 0 ? Math.abs(hi) * 0.1 : 1;
    return [lo - p, hi + p];
  }
  const d = (hi - lo) * frac;
  return [lo - d, hi + d];
}

export function extentOf(series: (number[] | undefined)[], positiveOnly = false): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const s of series) {
    if (!s) continue;
    for (const v of s) {
      if (!Number.isFinite(v)) continue;
      if (positiveOnly && v <= 0) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return positiveOnly ? [1e-3, 1] : [0, 1];
  return [lo, hi];
}
