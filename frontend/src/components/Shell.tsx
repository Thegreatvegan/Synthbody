/**
 * Application shell: title bar, activity rail, status bar, command palette and
 * the diagnostics console.
 *
 * The persistent "research software, not a medical device" strip in the title
 * bar is deliberate and non-dismissible. The regulatory posture of this product
 * should be visible in every screenshot anyone takes of it.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useStore, type WorkspaceId } from "../lib/store";
import { Badge, Kbd, cx, IconButton } from "./ui";
import { relativeTime, shortHash } from "../lib/format";

export const WORKSPACES: {
  id: WorkspaceId;
  label: string;
  glyph: string;
  hint: string;
  key: string;
}[] = [
  { id: "studio", label: "Studio", glyph: "◧", hint: "Configure and execute simulations", key: "1" },
  { id: "patient", label: "Patient Builder", glyph: "◉", hint: "Define virtual subjects", key: "2" },
  { id: "drug", label: "Compounds", glyph: "⬢", hint: "Drug library and dosing", key: "3" },
  { id: "systems", label: "Systems", glyph: "⬡", hint: "Modelled compartments and transport", key: "4" },
  { id: "analytics", label: "Analytics", glyph: "◢", hint: "Exposure, variability, sensitivity", key: "5" },
  { id: "experiments", label: "Experiments", glyph: "▤", hint: "Stored runs and reproduction", key: "6" },
  { id: "evidence", label: "Evidence", glyph: "❡", hint: "Reference library and validation", key: "7" },
  { id: "reports", label: "Reports", glyph: "⎙", hint: "Generate research reports", key: "8" },
];

// ---------------------------------------------------------------------------
// Title bar
// ---------------------------------------------------------------------------
export function TitleBar() {
  const meta = useStore((s) => s.meta);
  const online = useStore((s) => s.backendOnline);
  const running = useStore((s) => s.running);
  const toggleCommandPalette = useStore((s) => s.toggleCommandPalette);
  const workspace = useStore((s) => s.workspace);
  const current = WORKSPACES.find((w) => w.id === workspace);

  return (
    <header className="flex h-9 shrink-0 items-center gap-3 border-b border-line bg-panel pl-2.5 pr-2">
      <div className="flex items-center gap-2">
        <Logo />
        <div className="leading-none">
          <div className="text-sm font-semibold tracking-tight text-ink">
            SYNTHBODY
            <span className="ml-1.5 font-normal text-ink-faint">Studio</span>
          </div>
        </div>
      </div>

      <span className="h-4 w-px bg-line" />
      <span className="text-xs text-ink-dim">{current?.label}</span>

      {/* The non-dismissible regulatory strip. */}
      <div className="ml-auto flex items-center gap-2">
        <span className="hidden items-center gap-1.5 rounded-sm border border-warn/30 bg-warn/[0.07] px-2 py-0.5 text-2xs text-warn lg:flex">
          <span className="h-1.5 w-1.5 rounded-full bg-warn" />
          Research simulation software — not a medical device. No output is a diagnosis or a dose
          recommendation.
        </span>

        <button
          onClick={() => toggleCommandPalette(true)}
          className="flex h-6 items-center gap-2 rounded-sm border border-line-strong bg-void px-2 text-xs text-ink-faint hover:border-ink-ghost hover:text-ink-dim"
          title="Open the command palette"
        >
          <span>Search commands</span>
          <Kbd>Ctrl K</Kbd>
        </button>

        <span className="flex items-center gap-1.5 font-mono text-2xs text-ink-faint">
          <span
            className={cx(
              "h-1.5 w-1.5 rounded-full",
              running ? "animate-pulse-soft bg-accent" : online ? "bg-ok" : "bg-danger",
            )}
          />
          {running ? `solving: ${running}` : online ? "engine ready" : "engine offline"}
        </span>
        {meta && (
          <span className="font-mono text-2xs text-ink-ghost" title={meta.engine_revision}>
            v{meta.software_version}
          </span>
        )}
      </div>
    </header>
  );
}

function Logo() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden className="shrink-0">
      {/* Two coupled compartments with a transfer arrow: the actual subject matter. */}
      <circle cx="8" cy="8" r="4.4" fill="none" stroke="#3fd3bd" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="3.4" fill="none" stroke="#5aa9e6" strokeWidth="1.3" />
      <path d="M11 10.5 L13.4 13.2" stroke="#9aa6b1" strokeWidth="1.2" />
      <path d="M13.2 10.8 L10.8 13.4" stroke="#49525b" strokeWidth="1" strokeDasharray="1.5 1.5" />
      <circle cx="8" cy="8" r="1.3" fill="#3fd3bd" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Activity rail
// ---------------------------------------------------------------------------
export function ActivityBar() {
  const workspace = useStore((s) => s.workspace);
  const setWorkspace = useStore((s) => s.setWorkspace);
  const consoleOpen = useStore((s) => s.consoleOpen);
  const toggleConsole = useStore((s) => s.toggleConsole);
  const errors = useStore((s) => s.log.filter((l) => l.level === "error").length);

  return (
    <nav className="flex w-11 shrink-0 flex-col items-center gap-0.5 border-r border-line bg-panel py-1.5">
      {WORKSPACES.map((w) => (
        <button
          key={w.id}
          onClick={() => setWorkspace(w.id)}
          title={`${w.label} — ${w.hint}  (Alt+${w.key})`}
          className={cx(
            "group relative flex h-9 w-9 flex-col items-center justify-center rounded transition-colors duration-120",
            workspace === w.id
              ? "bg-raised text-accent"
              : "text-ink-faint hover:bg-raised hover:text-ink-dim",
          )}
        >
          {workspace === w.id && (
            <span className="absolute left-0 top-1.5 h-6 w-[2px] rounded-r bg-accent" />
          )}
          <span className="text-base leading-none">{w.glyph}</span>
          <span className="mt-0.5 text-[8px] uppercase tracking-wide">{w.key}</span>
        </button>
      ))}

      <div className="mt-auto flex flex-col items-center gap-1">
        <button
          onClick={() => toggleConsole()}
          title="Diagnostics console (Ctrl+`)"
          className={cx(
            "relative flex h-8 w-8 items-center justify-center rounded text-sm transition-colors duration-120",
            consoleOpen ? "bg-raised text-accent" : "text-ink-faint hover:bg-raised hover:text-ink-dim",
          )}
        >
          ▣
          {errors > 0 && (
            <span className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-danger" />
          )}
        </button>
      </div>
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Status bar
// ---------------------------------------------------------------------------
export function StatusBar() {
  const lastRun = useStore((s) => s.lastRun);
  const running = useStore((s) => s.running);
  const setup = useStore((s) => s.setup);
  const spec = useStore((s) => s.models.find((m) => m.model_id === s.setup.modelId));
  const experiments = useStore((s) => s.experiments);
  const activeExperimentId = useStore((s) => s.activeExperimentId);
  const scenarios = useStore((s) => s.scenarios);
  const toggleConsole = useStore((s) => s.toggleConsole);
  const warnings = lastRun?.diagnostics.warnings.length ?? 0;
  const exp = experiments.find((e) => e.id === activeExperimentId);
  const d = lastRun?.diagnostics;

  return (
    <footer className="flex h-6 shrink-0 items-center gap-3 border-t border-line bg-panel px-2.5 font-mono text-2xs text-ink-faint">
      <span className="text-ink-dim">{spec?.short_name ?? setup.modelId}</span>
      <span className="h-3 w-px bg-line" />
      <span>
        {setup.regimen.dose_mg} mg · {setup.regimen.route.replace("_", " ")}
        {setup.regimen.n_doses > 1 ? ` · q${setup.regimen.interval_h}h ×${setup.regimen.n_doses}` : ""}
      </span>
      <span className="h-3 w-px bg-line" />
      <span>horizon {setup.horizonH} h</span>

      {d && (
        <>
          <span className="h-3 w-px bg-line" />
          <span title="Solver method and tolerances">
            {d.method} rtol {d.rtol.toExponential(0)}
          </span>
          <span title="Right-hand-side evaluations">{d.n_rhs_evaluations} rhs</span>
          <span title="Wall-clock solve time">{(d.wall_time_s * 1000).toFixed(1)} ms</span>
          {d.mass_balance_relative_error != null && (
            <span
              title="Relative mass-balance error: amount dosed minus (in body + eliminated)"
              className={d.mass_balance_relative_error < 1e-6 ? "text-ok" : "text-warn"}
            >
              Δm {d.mass_balance_relative_error.toExponential(1)}
            </span>
          )}
        </>
      )}

      <div className="ml-auto flex items-center gap-3">
        {scenarios.length > 0 && <span>{scenarios.length} scenario(s) on bench</span>}
        {exp && <span className="text-ink-dim">exp: {exp.name}</span>}
        {lastRun?.provenance && (
          <span title={`Input hash: ${lastRun.provenance.input_hash}`}>
            hash {shortHash(lastRun.provenance.input_hash, 8)}
          </span>
        )}
        {warnings > 0 && (
          <button onClick={() => toggleConsole(true)} className="text-warn hover:underline">
            {warnings} solver warning{warnings > 1 ? "s" : ""}
          </button>
        )}
        <span className={running ? "text-accent" : ""}>{running ? "running" : "idle"}</span>
      </div>
    </footer>
  );
}

// ---------------------------------------------------------------------------
// Console
// ---------------------------------------------------------------------------
export function ConsolePanel() {
  const log = useStore((s) => s.log);
  const clearLog = useStore((s) => s.clearLog);
  const toggleConsole = useStore((s) => s.toggleConsole);
  const [filter, setFilter] = useState<"all" | "warn" | "error">("all");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [log.length]);

  const shown = log.filter((l) =>
    filter === "all" ? true : filter === "warn" ? l.level === "warn" || l.level === "error" : l.level === "error",
  );

  const colours = {
    info: "text-ink-dim",
    ok: "text-ok",
    warn: "text-warn",
    error: "text-danger",
  };

  return (
    <div className="flex h-full min-h-0 flex-col border-t border-line bg-surface">
      <div className="panel-header">
        <span>Diagnostics console</span>
        <span className="font-normal normal-case tracking-normal text-ink-ghost">
          solver output, provenance events and errors
        </span>
        <div className="ml-auto flex items-center gap-1">
          {(["all", "warn", "error"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cx(
                "rounded-xs px-1.5 py-px text-2xs uppercase",
                filter === f ? "bg-raised text-ink" : "text-ink-faint hover:text-ink-dim",
              )}
            >
              {f}
            </button>
          ))}
          <IconButton title="Clear console" onClick={clearLog}>
            ⌫
          </IconButton>
          <IconButton title="Hide console" onClick={() => toggleConsole(false)}>
            ✕
          </IconButton>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-2 py-1 font-mono text-2xs leading-relaxed">
        {shown.length === 0 ? (
          <div className="p-2 text-ink-ghost">No entries.</div>
        ) : (
          shown.map((l) => (
            <div key={l.id} className="flex gap-2 border-b border-line/30 py-0.5">
              <span className="shrink-0 text-ink-ghost">
                {l.at.toLocaleTimeString(undefined, { hour12: false })}
              </span>
              <span className={cx("w-12 shrink-0 uppercase", colours[l.level])}>{l.level}</span>
              <span className="w-20 shrink-0 text-ink-ghost">{l.source}</span>
              <span className="min-w-0 flex-1 break-words">
                <span className="text-ink-dim">{l.message}</span>
                {l.detail && <span className="text-ink-ghost"> — {l.detail}</span>}
              </span>
            </div>
          ))
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Command palette
// ---------------------------------------------------------------------------
interface Command {
  id: string;
  label: string;
  group: string;
  hint?: string;
  shortcut?: string;
  run: () => void;
}

export function CommandPalette() {
  const open = useStore((s) => s.commandPaletteOpen);
  const toggle = useStore((s) => s.toggleCommandPalette);
  const setWorkspace = useStore((s) => s.setWorkspace);
  const run = useStore((s) => s.run);
  const runComparison = useStore((s) => s.runComparison);
  const snapshotScenario = useStore((s) => s.snapshotScenario);
  const clearScenarios = useStore((s) => s.clearScenarios);
  const toggleConsole = useStore((s) => s.toggleConsole);
  const toggleInspector = useStore((s) => s.toggleInspector);
  const drugs = useStore((s) => s.drugs);
  const models = useStore((s) => s.models);
  const selectDrug = useStore((s) => s.selectDrug);
  const selectModel = useStore((s) => s.selectModel);
  const patchSetup = useStore((s) => s.patchSetup);
  const setup = useStore((s) => s.setup);
  const resetParams = useStore((s) => s.resetParametersToDrugDefaults);

  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const commands = useMemo<Command[]>(() => {
    const cs: Command[] = [
      { id: "run", label: "Run simulation", group: "Execute", shortcut: "Ctrl ⏎", run: () => void run() },
      {
        id: "snapshot",
        label: "Capture current setup as a scenario",
        group: "Execute",
        shortcut: "Ctrl S",
        run: () => snapshotScenario(),
      },
      { id: "compare", label: "Compare bench scenarios", group: "Execute", run: () => void runComparison() },
      { id: "clearbench", label: "Clear the scenario bench", group: "Execute", run: clearScenarios },
      {
        id: "resetparams",
        label: "Reset parameters to library defaults",
        group: "Execute",
        run: resetParams,
      },
      {
        id: "logy",
        label: `${setup.yLogScale ? "Linear" : "Logarithmic"} concentration axis`,
        group: "View",
        shortcut: "Ctrl L",
        run: () => patchSetup({ yLogScale: !setup.yLogScale }),
      },
      { id: "console", label: "Toggle diagnostics console", group: "View", shortcut: "Ctrl `", run: () => toggleConsole() },
      { id: "inspector", label: "Toggle inspector panel", group: "View", shortcut: "Ctrl I", run: () => toggleInspector() },
      ...WORKSPACES.map((w) => ({
        id: `go-${w.id}`,
        label: `Go to ${w.label}`,
        group: "Navigate",
        hint: w.hint,
        shortcut: `Alt ${w.key}`,
        run: () => setWorkspace(w.id),
      })),
      ...drugs.map((d) => ({
        id: `drug-${d.drug_id}`,
        label: `Select compound: ${d.name}`,
        group: "Compounds",
        hint: d.is_synthetic_demonstration ? "SYNTHETIC demonstration compound" : d.therapeutic_area,
        run: () => selectDrug(d.drug_id),
      })),
      ...models.map((m) => ({
        id: `model-${m.model_id}`,
        label: `Select model: ${m.name}`,
        group: "Models",
        hint: `${m.category} · ${m.validation_status.replace(/_/g, " ")}`,
        run: () => selectModel(m.model_id),
      })),
    ];
    return cs;
  }, [
    run, snapshotScenario, runComparison, clearScenarios, resetParams, setup.yLogScale,
    patchSetup, toggleConsole, toggleInspector, setWorkspace, drugs, models, selectDrug, selectModel,
  ]);

  const filtered = useMemo(() => {
    if (!q.trim()) return commands;
    const needle = q.toLowerCase();
    // Simple subsequence match so "gostu" finds "Go to Studio".
    const score = (text: string) => {
      const t = text.toLowerCase();
      if (t.includes(needle)) return 100 - t.indexOf(needle);
      let i = 0;
      for (const ch of needle) {
        i = t.indexOf(ch, i);
        if (i < 0) return -1;
        i++;
      }
      return 10;
    };
    return commands
      .map((c) => ({ c, s: Math.max(score(c.label), score(c.group)) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .map((x) => x.c);
  }, [commands, q]);

  useEffect(() => {
    if (open) {
      setQ("");
      setIdx(0);
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);

  useEffect(() => setIdx(0), [q]);

  if (!open) return null;

  const groups = filtered.reduce<Record<string, Command[]>>((acc, c) => {
    (acc[c.group] ??= []).push(c);
    return acc;
  }, {});
  let flat = 0;

  return (
    <div
      className="fixed inset-0 z-[70] flex items-start justify-center bg-void/60 p-6 pt-[12vh] backdrop-blur-[2px] animate-fade-in"
      onClick={() => toggle(false)}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[62vh] w-full max-w-xl flex-col overflow-hidden rounded-md border border-line-strong bg-surface shadow-float animate-slide-up"
      >
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Run a command, switch workspace, pick a compound…"
          className="h-10 shrink-0 border-b border-line bg-panel px-3 text-sm text-ink placeholder:text-ink-ghost focus:outline-none"
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setIdx((i) => Math.min(i + 1, filtered.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setIdx((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              const c = filtered[idx];
              if (c) {
                c.run();
                toggle(false);
              }
            } else if (e.key === "Escape") {
              toggle(false);
            }
          }}
        />
        <div className="min-h-0 flex-1 overflow-auto py-1">
          {filtered.length === 0 && (
            <div className="px-3 py-4 text-xs text-ink-faint">No matching command.</div>
          )}
          {Object.entries(groups).map(([group, cs]) => (
            <div key={group}>
              <div className="px-3 py-1 text-2xs font-semibold uppercase tracking-wider text-ink-ghost">
                {group}
              </div>
              {cs.map((c) => {
                const mine = flat++;
                return (
                  <button
                    key={c.id}
                    onMouseEnter={() => setIdx(mine)}
                    onClick={() => {
                      c.run();
                      toggle(false);
                    }}
                    className={cx(
                      "flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs",
                      mine === idx ? "bg-accent-wash text-ink" : "text-ink-dim hover:bg-raised",
                    )}
                  >
                    <span className="flex-1 truncate">{c.label}</span>
                    {c.hint && <span className="truncate text-2xs text-ink-ghost">{c.hint}</span>}
                    {c.shortcut && <Kbd>{c.shortcut}</Kbd>}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
        <div className="flex shrink-0 items-center gap-3 border-t border-line bg-panel px-3 py-1.5 text-2xs text-ink-ghost">
          <span>
            <Kbd>↑</Kbd> <Kbd>↓</Kbd> navigate
          </span>
          <span>
            <Kbd>⏎</Kbd> run
          </span>
          <span>
            <Kbd>Esc</Kbd> close
          </span>
          <span className="ml-auto">{filtered.length} commands</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Global keyboard shortcuts
// ---------------------------------------------------------------------------
export function useGlobalHotkeys() {
  const toggleCommandPalette = useStore((s) => s.toggleCommandPalette);
  const toggleConsole = useStore((s) => s.toggleConsole);
  const toggleInspector = useStore((s) => s.toggleInspector);
  const setWorkspace = useStore((s) => s.setWorkspace);
  const run = useStore((s) => s.run);
  const snapshot = useStore((s) => s.snapshotScenario);
  const patchSetup = useStore((s) => s.patchSetup);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing =
        el &&
        (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
      const mod = e.ctrlKey || e.metaKey;

      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        toggleCommandPalette();
        return;
      }
      if (mod && e.key === "`") {
        e.preventDefault();
        toggleConsole();
        return;
      }
      if (mod && e.key.toLowerCase() === "i" && !e.shiftKey) {
        e.preventDefault();
        toggleInspector();
        return;
      }
      if (mod && e.key === "Enter") {
        e.preventDefault();
        void run();
        return;
      }
      if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        snapshot();
        return;
      }
      if (mod && e.key.toLowerCase() === "l") {
        e.preventDefault();
        patchSetup({ yLogScale: !useStore.getState().setup.yLogScale });
        return;
      }
      if (e.altKey && /^[1-8]$/.test(e.key)) {
        e.preventDefault();
        const w = WORKSPACES.find((x) => x.key === e.key);
        if (w) setWorkspace(w.id);
        return;
      }
      if (typing) return;
      if (e.key === "?") {
        e.preventDefault();
        toggleCommandPalette(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleCommandPalette, toggleConsole, toggleInspector, setWorkspace, run, snapshot, patchSetup]);
}

// ---------------------------------------------------------------------------
// Shared helper: the "which model, how validated" header strip
// ---------------------------------------------------------------------------
export function ProvenanceStrip() {
  const lastRun = useStore((s) => s.lastRun);
  if (!lastRun) return null;
  const p = lastRun.provenance;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-panel px-2.5 py-1 font-mono text-2xs text-ink-faint">
      <Badge mono tone="neutral" title="Model identifier and version">
        {p.model_id}@{p.model_version}
      </Badge>
      <span title="Engine revision that produced this result">{p.engine_revision}</span>
      <span title="Deterministic hash of the inputs that produced this result">
        input {shortHash(p.input_hash, 10)}
      </span>
      <span title={p.timestamp_utc}>{relativeTime(p.timestamp_utc)}</span>
      {p.random_seed != null && <span>seed {p.random_seed}</span>}
      <span className="ml-auto">
        {p.parameters.length} parameters · {p.reference_ids.length} references ·{" "}
        {p.assumptions.length} assumptions
      </span>
    </div>
  );
}
