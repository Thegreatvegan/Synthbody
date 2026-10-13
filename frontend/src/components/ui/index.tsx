/**
 * UI primitives.
 *
 * A small, consistent component set. Everything is dense, flat, and keyboard
 * reachable. No component invents colour meaning: severity and evidence colours
 * come from the shared tokens so a yellow badge means the same thing in every
 * workspace.
 */
import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ORIGIN_META, VALIDATION_META, prettyUnit, sig } from "../../lib/format";
import type { ParameterOrigin, ValidationStatus } from "../../lib/types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------
export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = "",
  bodyClassName = "",
  scroll = false,
  dense = false,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  scroll?: boolean;
  dense?: boolean;
}) {
  return (
    <section
      className={cx(
        "flex min-h-0 min-w-0 flex-col overflow-hidden rounded border border-line bg-surface shadow-panel",
        className,
      )}
    >
      {title !== undefined && (
        <header className="panel-header">
          <span className="truncate text-ink-dim">{title}</span>
          {subtitle && <span className="truncate font-normal normal-case tracking-normal text-ink-ghost">{subtitle}</span>}
          {actions && <div className="ml-auto flex items-center gap-1">{actions}</div>}
        </header>
      )}
      <div
        className={cx(
          "min-h-0 flex-1",
          scroll && "overflow-auto",
          dense ? "p-0" : "p-2.5",
          bodyClassName,
        )}
      >
        {children}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------
type ButtonVariant = "primary" | "default" | "ghost" | "danger" | "subtle";

export function Button({
  children,
  onClick,
  variant = "default",
  size = "sm",
  disabled,
  loading,
  title,
  type = "button",
  shortcut,
  className = "",
  icon,
  full,
}: {
  children?: ReactNode;
  onClick?: () => void;
  variant?: ButtonVariant;
  size?: "xs" | "sm" | "md";
  disabled?: boolean;
  loading?: boolean;
  title?: string;
  type?: "button" | "submit";
  shortcut?: string;
  className?: string;
  icon?: ReactNode;
  full?: boolean;
}) {
  const v: Record<ButtonVariant, string> = {
    primary:
      "bg-accent-dim/90 text-void border-accent-dim hover:bg-accent font-semibold disabled:bg-accent-dim/30",
    default: "bg-raised text-ink border-line-strong hover:bg-hover hover:border-ink-ghost",
    ghost: "bg-transparent text-ink-dim border-transparent hover:bg-raised hover:text-ink",
    danger: "bg-danger/15 text-danger border-danger/40 hover:bg-danger/25",
    subtle: "bg-panel text-ink-dim border-line hover:bg-raised hover:text-ink",
  };
  const s = {
    xs: "h-5 px-1.5 text-2xs gap-1",
    sm: "h-6 px-2 text-xs gap-1.5",
    md: "h-7 px-2.5 text-sm gap-1.5",
  }[size];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      title={title ? `${title}${shortcut ? `  (${shortcut})` : ""}` : shortcut}
      className={cx(
        "inline-flex items-center justify-center whitespace-nowrap rounded-sm border transition-colors duration-120",
        "disabled:cursor-not-allowed disabled:opacity-45",
        s,
        v[variant],
        full && "w-full",
        className,
      )}
    >
      {loading ? (
        <span className="inline-block h-2.5 w-2.5 animate-pulse-soft rounded-full bg-current" />
      ) : (
        icon
      )}
      {children}
      {shortcut && (
        <kbd className="ml-1 rounded-xs border border-current/25 px-1 text-[9px] opacity-60">
          {shortcut}
        </kbd>
      )}
    </button>
  );
}

export function IconButton({
  children,
  onClick,
  title,
  active,
  disabled,
}: {
  children: ReactNode;
  onClick?: () => void;
  title: string;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      disabled={disabled}
      aria-label={title}
      className={cx(
        "inline-flex h-5 w-5 items-center justify-center rounded-sm border text-2xs transition-colors duration-120",
        active
          ? "border-accent/40 bg-accent-wash text-accent"
          : "border-transparent text-ink-faint hover:bg-raised hover:text-ink",
        disabled && "cursor-not-allowed opacity-40",
      )}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Form fields
// ---------------------------------------------------------------------------
export function Field({
  label,
  hint,
  unit,
  children,
  inline = true,
  warn,
}: {
  label: ReactNode;
  hint?: string;
  unit?: string;
  children: ReactNode;
  inline?: boolean;
  warn?: string;
}) {
  return (
    <label className={cx("block", inline ? "grid grid-cols-[1fr_auto] items-center gap-2" : "space-y-1")}>
      <span className="flex min-w-0 items-center gap-1 text-xs text-ink-dim" title={hint}>
        <span className="truncate">{label}</span>
        {unit && <span className="shrink-0 font-mono text-2xs text-ink-ghost">{prettyUnit(unit)}</span>}
        {hint && (
          <span className="shrink-0 cursor-help text-2xs text-ink-ghost" title={hint}>
            ⓘ
          </span>
        )}
      </span>
      <div className={inline ? "justify-self-end" : ""}>{children}</div>
      {warn && <span className="col-span-2 text-2xs text-warn">{warn}</span>}
    </label>
  );
}

export function NumberInput({
  value,
  onChange,
  min,
  max,
  step,
  disabled,
  width = "w-[84px]",
  mono = true,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  width?: string;
  mono?: boolean;
}) {
  const [text, setText] = useState(String(value));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setText(String(value));
  }, [value]);

  const commit = (raw: string) => {
    const n = Number(raw);
    if (!Number.isFinite(n)) {
      setText(String(value));
      return;
    }
    let v = n;
    if (min != null) v = Math.max(v, min);
    if (max != null) v = Math.min(v, max);
    setText(String(v));
    if (v !== value) onChange(v);
  };

  const outOfRange =
    Number.isFinite(Number(text)) &&
    ((min != null && Number(text) < min) || (max != null && Number(text) > max));

  return (
    <input
      type="number"
      value={text}
      min={min}
      max={max}
      step={step ?? "any"}
      disabled={disabled}
      onFocus={() => (focused.current = true)}
      onBlur={(e) => {
        focused.current = false;
        commit(e.target.value);
      }}
      onChange={(e) => setText(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          commit((e.target as HTMLInputElement).value);
          (e.target as HTMLInputElement).blur();
        }
      }}
      className={cx(
        "h-6 rounded-sm border bg-void px-1.5 text-right text-xs text-ink tnum",
        mono && "font-mono",
        width,
        outOfRange ? "border-danger" : "border-line-strong focus:border-accent",
        "focus:outline-none disabled:opacity-50",
      )}
    />
  );
}

export function Slider({
  value,
  onChange,
  min,
  max,
  step,
  disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  disabled?: boolean;
}) {
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step ?? (max - min) / 200}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-full"
    />
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  disabled,
  mono,
  className = "",
  onEnter,
  autoFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
  mono?: boolean;
  className?: string;
  onEnter?: () => void;
  autoFocus?: boolean;
}) {
  return (
    <input
      type="text"
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      autoFocus={autoFocus}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && onEnter?.()}
      className={cx(
        "h-6 w-full rounded-sm border border-line-strong bg-void px-1.5 text-xs text-ink",
        "placeholder:text-ink-ghost focus:border-accent focus:outline-none disabled:opacity-50",
        mono && "font-mono",
        className,
      )}
    />
  );
}

export function TextArea({
  value,
  onChange,
  rows = 3,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  return (
    <textarea
      value={value}
      rows={rows}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="w-full resize-y rounded-sm border border-line-strong bg-void px-1.5 py-1 text-xs text-ink placeholder:text-ink-ghost focus:border-accent focus:outline-none"
    />
  );
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  disabled,
  width = "w-full",
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; disabled?: boolean }[];
  disabled?: boolean;
  width?: string;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as T)}
      className={cx(
        "h-6 rounded-sm border border-line-strong bg-void px-1 text-xs text-ink",
        "focus:border-accent focus:outline-none disabled:opacity-50",
        width,
      )}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "inline-flex items-center gap-1.5 text-xs transition-colors duration-120",
        disabled ? "cursor-not-allowed opacity-50" : "hover:text-ink",
        checked ? "text-ink" : "text-ink-dim",
      )}
    >
      <span
        className={cx(
          "relative h-3 w-6 shrink-0 rounded-full border transition-colors duration-120",
          checked ? "border-accent-dim bg-accent-dim/60" : "border-line-strong bg-void",
        )}
      >
        <span
          className={cx(
            "absolute top-[1px] h-2 w-2 rounded-full transition-all duration-120",
            checked ? "left-[13px] bg-accent" : "left-[2px] bg-ink-ghost",
          )}
        />
      </span>
      {label}
    </button>
  );
}

export function Checkbox({
  checked,
  onChange,
  label,
  colour,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  colour?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex w-full items-center gap-1.5 rounded-sm px-1 py-0.5 text-left text-xs text-ink-dim hover:bg-raised hover:text-ink"
    >
      <span
        className={cx(
          "flex h-3 w-3 shrink-0 items-center justify-center rounded-xs border text-[8px] leading-none",
          checked ? "border-transparent text-void" : "border-line-strong text-transparent",
        )}
        style={checked ? { background: colour ?? "#3fd3bd" } : undefined}
      >
        ✓
      </span>
      {colour && !checked && (
        <span className="h-[2px] w-2.5 shrink-0" style={{ background: colour }} />
      )}
      <span className="truncate">{label}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------
export function Badge({
  children,
  tone = "neutral",
  title,
  mono,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "ok" | "warn" | "danger" | "info" | "violet";
  title?: string;
  mono?: boolean;
}) {
  const tones = {
    neutral: "bg-raised text-ink-dim border-line-strong",
    accent: "bg-accent/12 text-accent border-accent/30",
    ok: "bg-ok/12 text-ok border-ok/30",
    warn: "bg-warn/12 text-warn border-warn/30",
    danger: "bg-danger/12 text-danger border-danger/30",
    info: "bg-info/12 text-info border-info/30",
    violet: "bg-violet/12 text-violet border-violet/30",
  };
  return (
    <span
      title={title}
      className={cx(
        "inline-flex shrink-0 items-center gap-1 rounded-xs border px-1 py-px text-[9px] font-semibold uppercase tracking-wide",
        mono && "font-mono tracking-normal",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

/** Evidence-origin chip. Used anywhere a number is shown. */
export function OriginBadge({ origin, full }: { origin: ParameterOrigin; full?: boolean }) {
  const m = ORIGIN_META[origin];
  if (!m) return null;
  return (
    <span
      title={`${m.label}: ${m.explain}`}
      className={cx(
        "inline-flex shrink-0 cursor-help items-center rounded-xs border px-1 py-px text-[9px] font-semibold uppercase tracking-wide",
        m.tone,
      )}
    >
      {full ? m.label : m.short}
    </span>
  );
}

/** Model validation-status chip. */
export function ValidationBadge({
  status,
  full,
}: {
  status: ValidationStatus;
  full?: boolean;
}) {
  const m = VALIDATION_META[status];
  if (!m) return null;
  return (
    <span
      title={`${m.label}: ${m.explain}`}
      className={cx(
        "inline-flex shrink-0 cursor-help items-center gap-1 rounded-xs border px-1 py-px text-[9px] font-semibold uppercase tracking-wide",
        m.tone,
      )}
    >
      <span className={cx("h-1.5 w-1.5 rounded-full", m.dot)} />
      {full ? m.label : m.short}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Notices
// ---------------------------------------------------------------------------
export function Notice({
  tone = "info",
  title,
  children,
  compact,
}: {
  tone?: "info" | "warn" | "danger" | "ok" | "neutral" | "violet";
  title?: ReactNode;
  children?: ReactNode;
  compact?: boolean;
}) {
  const tones = {
    info: "border-info/30 bg-info/[0.07] text-info",
    warn: "border-warn/30 bg-warn/[0.07] text-warn",
    danger: "border-danger/35 bg-danger/[0.08] text-danger",
    ok: "border-ok/30 bg-ok/[0.07] text-ok",
    neutral: "border-line-strong bg-raised text-ink-dim",
    violet: "border-violet/30 bg-violet/[0.07] text-violet",
  };
  return (
    <div
      className={cx(
        "rounded border text-xs leading-relaxed",
        compact ? "px-2 py-1" : "px-2.5 py-2",
        tones[tone],
      )}
    >
      {title && <div className="mb-0.5 font-semibold">{title}</div>}
      {children && <div className="text-ink-dim">{children}</div>}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex h-full min-h-[120px] flex-col items-center justify-center gap-2 p-6 text-center">
      <div className="text-sm text-ink-dim">{title}</div>
      {children && <div className="max-w-md text-xs leading-relaxed text-ink-faint">{children}</div>}
      {action}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------
export interface TableHeader {
  label: ReactNode;
  align?: "left" | "right";
  hint?: string;
}

function isTableHeader(h: unknown): h is TableHeader {
  return typeof h === "object" && h !== null && "label" in h;
}

export function Table({
  headers,
  children,
  compact,
  stickyHeader = true,
}: {
  headers: (ReactNode | TableHeader)[];
  children: ReactNode;
  compact?: boolean;
  stickyHeader?: boolean;
}) {
  return (
    <div className="min-w-full overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead className={stickyHeader ? "sticky top-0 z-10" : ""}>
          <tr className="bg-panel">
            {headers.map((h, i) => {
              const header = isTableHeader(h) ? h : null;
              const label: ReactNode = header ? header.label : (h as ReactNode);
              const align = header?.align ?? "left";
              const hint = header?.hint;
              return (
                <th
                  key={i}
                  title={hint}
                  className={cx(
                    "border-b border-line px-2 py-1 text-2xs font-semibold uppercase tracking-wide text-ink-faint",
                    align === "right" ? "text-right" : "text-left",
                    hint && "cursor-help",
                  )}
                >
                  {label}
                  {hint && <span className="ml-1 text-ink-ghost">ⓘ</span>}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className={compact ? "[&_td]:py-0.5" : "[&_td]:py-1"}>{children}</tbody>
      </table>
    </div>
  );
}

export function Row({
  children,
  onClick,
  selected,
  tone,
}: {
  children: ReactNode;
  onClick?: () => void;
  selected?: boolean;
  tone?: "warn" | "danger";
}) {
  return (
    <tr
      onClick={onClick}
      className={cx(
        "border-b border-line/60 transition-colors duration-120",
        onClick && "cursor-pointer",
        selected ? "bg-accent-wash/70" : onClick && "hover:bg-raised",
        tone === "warn" && "bg-warn/[0.04]",
        tone === "danger" && "bg-danger/[0.05]",
      )}
    >
      {children}
    </tr>
  );
}

export function Cell({
  children,
  align = "left",
  mono,
  dim,
  title,
  span,
  className = "",
}: {
  children: ReactNode;
  align?: "left" | "right" | "center";
  mono?: boolean;
  dim?: boolean;
  title?: string;
  span?: number;
  className?: string;
}) {
  return (
    <td
      colSpan={span}
      title={title}
      className={cx(
        "px-2 align-middle",
        align === "right" && "text-right",
        align === "center" && "text-center",
        mono && "font-mono tnum",
        dim ? "text-ink-faint" : "text-ink-dim",
        className,
      )}
    >
      {children}
    </td>
  );
}

/** A labelled numeric readout, used throughout the inspector panes. */
export function Metric({
  label,
  value,
  unit,
  hint,
  tone,
  origin,
  digits = 4,
}: {
  label: ReactNode;
  value: number | string | null | undefined;
  unit?: string;
  hint?: string;
  tone?: "ok" | "warn" | "danger" | "accent";
  origin?: ParameterOrigin;
  digits?: number;
}) {
  const text = typeof value === "number" ? sig(value, digits) : (value ?? "—");
  const tones = {
    ok: "text-ok",
    warn: "text-warn",
    danger: "text-danger",
    accent: "text-accent",
  };
  return (
    <div
      className="flex items-baseline justify-between gap-2 border-b border-line/40 py-1 last:border-0"
      title={hint}
    >
      <span className="flex min-w-0 items-center gap-1 text-xs text-ink-faint">
        <span className="truncate">{label}</span>
        {origin && <OriginBadge origin={origin} />}
      </span>
      <span className="flex shrink-0 items-baseline gap-1">
        <span className={cx("font-mono text-xs tnum", tone ? tones[tone] : "text-ink")}>{text}</span>
        {unit && <span className="font-mono text-2xs text-ink-ghost">{prettyUnit(unit)}</span>}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  right,
}: {
  tabs: { id: T; label: ReactNode; badge?: ReactNode; title?: string }[];
  value: T;
  onChange: (v: T) => void;
  right?: ReactNode;
}) {
  return (
    <div className="flex h-7 shrink-0 items-stretch border-b border-line bg-panel">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          title={t.title}
          className={cx(
            "relative flex items-center gap-1.5 whitespace-nowrap border-r border-line px-2.5 text-xs transition-colors duration-120",
            value === t.id
              ? "bg-surface text-ink"
              : "text-ink-faint hover:bg-raised hover:text-ink-dim",
          )}
        >
          {value === t.id && <span className="absolute inset-x-0 top-0 h-[1.5px] bg-accent" />}
          {t.label}
          {t.badge}
        </button>
      ))}
      {right && <div className="ml-auto flex items-center gap-1 px-2">{right}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collapsible
// ---------------------------------------------------------------------------
export function Collapsible({
  title,
  children,
  defaultOpen = false,
  badge,
  dense,
}: {
  title: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  badge?: ReactNode;
  dense?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-line last:border-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left text-xs text-ink-dim hover:bg-raised hover:text-ink"
      >
        <span className={cx("text-ink-ghost transition-transform duration-120", open && "rotate-90")}>
          ▸
        </span>
        <span className="flex-1 truncate font-medium">{title}</span>
        {badge}
      </button>
      {open && (
        <div className={cx("animate-fade-in", dense ? "" : "px-2.5 pb-2.5")}>{children}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-void/70 p-6 backdrop-blur-[2px] animate-fade-in"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={cx(
          "flex max-h-[85vh] w-full flex-col overflow-hidden rounded-md border border-line-strong bg-surface shadow-float animate-slide-up",
          wide ? "max-w-4xl" : "max-w-lg",
        )}
      >
        <header className="flex h-8 shrink-0 items-center border-b border-line bg-panel px-3 text-xs font-semibold text-ink">
          {title}
          <button
            onClick={onClose}
            className="ml-auto text-ink-faint hover:text-ink"
            aria-label="Close"
          >
            ✕
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-3">{children}</div>
        {footer && (
          <footer className="flex shrink-0 items-center justify-end gap-2 border-t border-line bg-panel px-3 py-2">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Splitter
// ---------------------------------------------------------------------------
/**
 * Draggable split between two panes. Stores its size in local state; the
 * workspace layout decides the initial fraction.
 */
export function Splitter({
  direction = "horizontal",
  initial = 0.5,
  min = 0.15,
  max = 0.85,
  first,
  second,
  storageKey,
}: {
  direction?: "horizontal" | "vertical";
  initial?: number;
  min?: number;
  max?: number;
  first: ReactNode;
  second: ReactNode;
  storageKey?: string;
}) {
  const key = storageKey ? `synthbody.split.${storageKey}` : null;
  const [frac, setFrac] = useState(() => {
    if (!key) return initial;
    const v = Number(localStorage.getItem(key));
    return Number.isFinite(v) && v > 0 ? v : initial;
  });
  const ref = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  useEffect(() => {
    if (key) localStorage.setItem(key, String(frac));
  }, [frac, key]);

  useEffect(() => {
    const move = (e: MouseEvent) => {
      if (!dragging.current || !ref.current) return;
      const r = ref.current.getBoundingClientRect();
      const f =
        direction === "horizontal"
          ? (e.clientX - r.left) / r.width
          : (e.clientY - r.top) / r.height;
      setFrac(Math.min(Math.max(f, min), max));
    };
    const up = () => {
      dragging.current = false;
      document.body.style.cursor = "";
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, [direction, min, max]);

  const horiz = direction === "horizontal";
  return (
    <div ref={ref} className={cx("flex min-h-0 min-w-0 flex-1", horiz ? "flex-row" : "flex-col")}>
      <div
        className="flex min-h-0 min-w-0 flex-col"
        style={horiz ? { width: `${frac * 100}%` } : { height: `${frac * 100}%` }}
      >
        {first}
      </div>
      <div
        onMouseDown={() => {
          dragging.current = true;
          document.body.style.cursor = horiz ? "col-resize" : "row-resize";
        }}
        className={cx(
          "group shrink-0 bg-base transition-colors duration-120 hover:bg-accent-dim/40",
          horiz ? "w-1 cursor-col-resize" : "h-1 cursor-row-resize",
        )}
      >
        <div
          className={cx(
            "bg-line transition-colors duration-120 group-hover:bg-accent",
            horiz ? "mx-auto h-full w-px" : "my-auto h-px w-full",
          )}
        />
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">{second}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------
export interface Toast {
  id: number;
  tone: "info" | "ok" | "warn" | "danger";
  title: string;
  detail?: string;
}

const ToastCtx = createContext<{ push: (t: Omit<Toast, "id">) => void }>({ push: () => {} });
export const useToast = () => useContext(ToastCtx);

export function ToastHost({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const seq = useRef(0);
  const push = (t: Omit<Toast, "id">) => {
    const id = ++seq.current;
    setItems((xs) => [...xs, { ...t, id }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), t.tone === "danger" ? 12000 : 5500);
  };
  const tones = {
    info: "border-info/40 bg-info/10",
    ok: "border-ok/40 bg-ok/10",
    warn: "border-warn/40 bg-warn/10",
    danger: "border-danger/50 bg-danger/10",
  };
  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-7 right-3 z-[60] flex w-80 flex-col gap-1.5">
        {items.map((t) => (
          <div
            key={t.id}
            className={cx(
              "pointer-events-auto rounded border bg-surface px-2.5 py-2 text-xs shadow-float animate-slide-up",
              tones[t.tone],
            )}
          >
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-ink">{t.title}</div>
                {t.detail && (
                  <div className="mt-0.5 break-words leading-relaxed text-ink-dim">{t.detail}</div>
                )}
              </div>
              <button
                onClick={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}
                className="text-ink-faint hover:text-ink"
                aria-label="Dismiss"
              >
                ✕
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

// ---------------------------------------------------------------------------
// Misc
// ---------------------------------------------------------------------------
export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-ink-faint">
      <span className="inline-block h-2.5 w-2.5 animate-pulse-soft rounded-full bg-accent" />
      {label ?? "Working…"}
    </div>
  );
}

export function ProgressSweep({ label }: { label: string }) {
  return (
    <div className="space-y-1">
      <div className="text-2xs text-ink-faint">{label}</div>
      <div className="sweep-bar h-0.5 w-full bg-raised" />
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded-xs border border-line-strong bg-raised px-1 py-px font-mono text-[9px] text-ink-faint">
      {children}
    </kbd>
  );
}

export function Hint({ children }: { children: ReactNode }) {
  return <p className="text-2xs leading-relaxed text-ink-faint">{children}</p>;
}

export function SectionLabel({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-1.5 mt-3 flex items-center gap-2 first:mt-0">
      <span className="text-2xs font-semibold uppercase tracking-wider text-ink-faint">{children}</span>
      <span className="h-px flex-1 bg-line" />
      {right}
    </div>
  );
}

/** A tiny inline bar used to show a fraction inside a table cell. */
export function MiniBar({
  value,
  max = 1,
  colour = "#3fd3bd",
  width = 48,
}: {
  value: number;
  max?: number;
  colour?: string;
  width?: number;
}) {
  const f = Math.max(0, Math.min(1, max === 0 ? 0 : value / max));
  return (
    <span
      className="inline-block h-1.5 shrink-0 rounded-xs bg-raised align-middle"
      style={{ width }}
      title={`${(f * 100).toFixed(1)}%`}
    >
      <span
        className="block h-full rounded-xs"
        style={{ width: `${f * 100}%`, background: colour }}
      />
    </span>
  );
}

/** Signed bar centred on zero, for sensitivity coefficients. */
export function SignedBar({
  value,
  max,
  width = 110,
}: {
  value: number;
  max: number;
  width?: number;
}) {
  const half = width / 2;
  const f = max === 0 ? 0 : Math.max(-1, Math.min(1, value / max));
  const w = Math.abs(f) * half;
  const pos = value >= 0;
  return (
    <span
      className="relative inline-block h-2 shrink-0 align-middle"
      style={{ width }}
      title={value.toExponential(3)}
    >
      <span className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
      <span
        className="absolute inset-y-[1px] rounded-xs"
        style={{
          left: pos ? half : half - w,
          width: w,
          background: pos ? "#3fd3bd" : "#e0a34a",
        }}
      />
    </span>
  );
}

export function useStableId(prefix: string): string {
  const id = useId();
  return `${prefix}${id.replace(/:/g, "")}`;
}
