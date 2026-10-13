/**
 * Number, unit and label formatting.
 *
 * Scientific software earns trust partly through how it prints numbers:
 * consistent significant figures, no spurious precision, explicit units, and a
 * visible marker when a value is absent rather than zero.
 */
import type { ParameterOrigin, ValidationStatus } from "./types";

export const ABSENT = "—"; // em dash: "not available", never confused with 0

/** Fixed significant figures, falling back to exponential for extreme values. */
export function sig(v: number | null | undefined, digits = 4): string {
  if (v == null || !Number.isFinite(v)) return ABSENT;
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e6 || a < 1e-4) return v.toExponential(Math.max(digits - 1, 1)).replace("e", "e");
  return Number(v.toPrecision(digits)).toString();
}

/** Fixed decimal places. Use when a column must align on the decimal point. */
export function fixed(v: number | null | undefined, places = 2): string {
  if (v == null || !Number.isFinite(v)) return ABSENT;
  return v.toFixed(places);
}

export function pct(v: number | null | undefined, places = 1): string {
  if (v == null || !Number.isFinite(v)) return ABSENT;
  return `${(v * 100).toFixed(places)}%`;
}

export function pctRaw(v: number | null | undefined, places = 1): string {
  if (v == null || !Number.isFinite(v)) return ABSENT;
  return `${v.toFixed(places)}%`;
}

/** Scientific notation with a proper multiplication sign, for tolerances etc. */
export function sci(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return ABSENT;
  if (v === 0) return "0";
  const exp = Math.floor(Math.log10(Math.abs(v)));
  const mant = v / 10 ** exp;
  return `${mant.toFixed(digits)}×10${superscript(exp)}`;
}

function superscript(n: number): string {
  const map: Record<string, string> = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "-": "⁻",
  };
  return String(n)
    .split("")
    .map((c) => map[c] ?? c)
    .join("");
}

export function withUnit(v: number | null | undefined, unit: string, digits = 4): string {
  const s = sig(v, digits);
  if (s === ABSENT) return ABSENT;
  return unit ? `${s} ${prettyUnit(unit)}` : s;
}

/** Render unit strings with proper typography. */
export function prettyUnit(u: string): string {
  if (!u) return "";
  return u
    .replace(/\bug\b/g, "µg")
    .replace(/\bmcg\b/g, "µg")
    .replace(/1\/h/g, "h⁻¹")
    .replace(/1\/min/g, "min⁻¹")
    .replace(/\bm2\b/g, "m²")
    .replace(/kg\^?\(?3\/4\)?/g, "kg^0.75");
}

export function duration(hours: number | null | undefined): string {
  if (hours == null || !Number.isFinite(hours)) return ABSENT;
  if (hours < 1) return `${(hours * 60).toFixed(0)} min`;
  if (hours < 48) return `${sig(hours, 3)} h`;
  const d = hours / 24;
  return `${sig(d, 3)} d`;
}

export function timestamp(iso: string | null | undefined): string {
  if (!iso) return ABSENT;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return ABSENT;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return ABSENT;
  const s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function shortHash(h: string | null | undefined, n = 10): string {
  if (!h) return ABSENT;
  const bare = h.replace(/^sha\d+:/, "");
  return bare.slice(0, n);
}

/** Humanise a snake_case identifier for display. */
export function humanise(s: string): string {
  return s
    .replace(/_/g, " ")
    .replace(/\b([a-z])/g, (m) => m.toUpperCase())
    .replace(/\bAuc\b/g, "AUC")
    .replace(/\bCmax\b/gi, "Cmax")
    .replace(/\bCmin\b/gi, "Cmin")
    .replace(/\bTmax\b/gi, "Tmax")
    .replace(/\bRmse\b/g, "RMSE")
    .replace(/\bMae\b/g, "MAE")
    .replace(/\bAfe\b/g, "AFE")
    .replace(/\bAafe\b/g, "AAFE")
    .replace(/\bPbpk\b/g, "PBPK")
    .replace(/\bNca\b/g, "NCA")
    .replace(/\bCl\b/g, "CL")
    .replace(/\bGfr\b/g, "GFR");
}

// ---------------------------------------------------------------------------
// Evidence presentation
// ---------------------------------------------------------------------------
export const ORIGIN_META: Record<
  ParameterOrigin,
  { label: string; short: string; colour: string; tone: string; explain: string }
> = {
  measured: {
    label: "Measured",
    short: "MEAS",
    colour: "text-origin-measured",
    tone: "bg-origin-measured/12 text-origin-measured border-origin-measured/30",
    explain: "A directly measured or reported population value from a cited primary source.",
  },
  fitted: {
    label: "Fitted here",
    short: "FIT",
    colour: "text-origin-fitted",
    tone: "bg-origin-fitted/12 text-origin-fitted border-origin-fitted/30",
    explain:
      "Estimated by SYNTHBODY's own regression against a named observed dataset shipped with the platform. Reproducible by re-running the validation script.",
  },
  literature_fitted: {
    label: "Fitted in literature",
    short: "LIT",
    colour: "text-origin-literature",
    tone: "bg-origin-literature/12 text-origin-literature border-origin-literature/30",
    explain: "A fitted estimate reported by a cited publication; not re-estimated here.",
  },
  derived: {
    label: "Derived",
    short: "DERIV",
    colour: "text-origin-derived",
    tone: "bg-origin-derived/12 text-origin-derived border-origin-derived/30",
    explain: "Computed from other parameters by an explicit, documented equation.",
  },
  inferred: {
    label: "Inferred",
    short: "INFER",
    colour: "text-origin-inferred",
    tone: "bg-origin-inferred/12 text-origin-inferred border-origin-inferred/30",
    explain:
      "Reasoned from related data or a widely quoted value whose primary source was not retrieved. Treat with caution.",
  },
  illustrative: {
    label: "Illustrative",
    short: "ILLUS",
    colour: "text-origin-illustrative",
    tone: "bg-origin-illustrative/12 text-origin-illustrative border-origin-illustrative/30",
    explain:
      "A plausible default chosen to make the software demonstrable. NOT evidence. Any conclusion resting on it is unsupported.",
  },
  user: {
    label: "Operator",
    short: "USER",
    colour: "text-origin-user",
    tone: "bg-origin-user/12 text-origin-user border-origin-user/30",
    explain: "Supplied by the operator at run time.",
  },
};

export const VALIDATION_META: Record<
  ValidationStatus,
  { label: string; short: string; tone: string; dot: string; explain: string; rank: number }
> = {
  independently_validated: {
    label: "Independently validated",
    short: "VALIDATED",
    tone: "bg-ok/12 text-ok border-ok/30",
    dot: "bg-ok",
    explain:
      "Compared against observed data that was NOT used to estimate its parameters, within the population and design of that dataset only.",
    rank: 0,
  },
  calibrated_only: {
    label: "Calibrated only",
    short: "CALIBRATED",
    tone: "bg-info/12 text-info border-info/30",
    dot: "bg-info",
    explain:
      "Reproduces the dataset its own parameters were fitted to. This is weak evidence: it shows the fit worked, not that the model generalises.",
    rank: 1,
  },
  structurally_verified: {
    label: "Structurally verified",
    short: "STRUCTURAL",
    tone: "bg-violet/12 text-violet border-violet/30",
    dot: "bg-violet",
    explain:
      "Numerics verified against analytic solutions, limiting cases and mass balance. No comparison against clinical observations has been performed.",
    rank: 2,
  },
  research_only: {
    label: "Research only",
    short: "RESEARCH",
    tone: "bg-warn/12 text-warn border-warn/30",
    dot: "bg-warn",
    explain:
      "Implemented from published equations with traceable parameters, but no quantitative comparison against observed data. Do not read quantitative predictions from it.",
    rank: 3,
  },
  not_validated: {
    label: "Not validated",
    short: "UNVALIDATED",
    tone: "bg-danger/12 text-danger border-danger/30",
    dot: "bg-danger",
    explain: "No validation of any kind has been performed.",
    rank: 4,
  },
};

// ---------------------------------------------------------------------------
// Series colours
// ---------------------------------------------------------------------------
/**
 * Categorical series palette. Chosen for separability at 1px line weight on a
 * dark background, and ordered so the first few are maximally distinct.
 */
export const SERIES = [
  "#3fd3bd",
  "#e0a34a",
  "#5aa9e6",
  "#e2655f",
  "#a98bdc",
  "#6bc777",
  "#d978b4",
  "#8fb8c9",
  "#c9c35e",
  "#ef9a63",
  "#7fa5e3",
  "#b0d17a",
];

export function seriesColour(i: number): string {
  return SERIES[i % SERIES.length]!;
}

/** Colour for a tissue in the PBPK diagram and plots, stable across views. */
const TISSUE_COLOURS: Record<string, string> = {
  lung: "#8fb8c9",
  liver: "#e0a34a",
  kidney: "#5aa9e6",
  brain: "#a98bdc",
  heart: "#e2655f",
  muscle: "#6bc777",
  adipose: "#c9c35e",
  skin: "#d978b4",
  gut: "#ef9a63",
  spleen: "#b0d17a",
  bone: "#9aa6b1",
  rest: "#67727c",
};

export function tissueColour(name: string): string {
  return TISSUE_COLOURS[name] ?? "#67727c";
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi);
}

/** Download a text blob. Used for CSV, Markdown and SVG export. */
export function downloadText(filename: string, text: string, mime = "text/plain"): void {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Build a CSV from a header row and data rows, quoting correctly. */
export function toCsv(headers: string[], rows: (string | number | null | undefined)[][]): string {
  const esc = (v: string | number | null | undefined) => {
    if (v == null) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [headers.map(esc).join(","), ...rows.map((r) => r.map(esc).join(","))].join("\n");
}

export function slug(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
}
