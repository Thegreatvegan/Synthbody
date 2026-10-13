/**
 * Research Reports.
 *
 * Generates a complete methods-and-results document from stored runs:
 * inputs, parameter provenance, exposure metrics, solver diagnostics,
 * independent validation results, limitations and references. The report is
 * rendered by the backend so what you download is what the engine recorded,
 * not a reconstruction by the browser.
 */
import { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Button,
  Cell,
  EmptyState,
  Field,
  Hint,
  Notice,
  Panel,
  Row,
  SectionLabel,
  Splitter,
  Table,
  TextInput,
  Toggle,
  ValidationBadge,
  cx,
  useToast,
} from "../components/ui";
import type { ReactNode } from "react";
import { api, ApiError } from "../lib/api";
import { downloadText, relativeTime, slug } from "../lib/format";
import { useStore } from "../lib/store";
import type { SimulationSummary } from "../lib/types";

export function Reports() {
  const experiments = useStore((s) => s.experiments);
  const meta = useStore((s) => s.meta);
  const toast = useToast();

  const [sims, setSims] = useState<SimulationSummary[]>([]);
  const [chosen, setChosen] = useState<number[]>([]);
  const [title, setTitle] = useState("SYNTHBODY research report");
  const [author, setAuthor] = useState("");
  const [includeValidation, setIncludeValidation] = useState(true);
  const [includeReferences, setIncludeReferences] = useState(true);
  const [includeLimitations, setIncludeLimitations] = useState(true);
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expFilter, setExpFilter] = useState<number | null>(null);

  useEffect(() => {
    void api
      .simulations(expFilter != null ? { experiment_id: expFilter, limit: 300 } : { limit: 300 })
      .then(setSims)
      .catch(() => setSims([]));
  }, [expFilter]);

  const generate = async () => {
    setBusy(true);
    try {
      const r = await api.report({
        simulation_ids: chosen,
        title,
        author,
        include_validation: includeValidation,
        include_references: includeReferences,
        include_limitations: includeLimitations,
        format: "markdown",
      });
      setMarkdown(r.markdown);
      toast.push({
        tone: "ok",
        title: "Report generated",
        detail: `${r.markdown.length.toLocaleString()} characters covering ${chosen.length} run(s)`,
      });
    } catch (e) {
      toast.push({
        tone: "danger",
        title: "Could not generate report",
        detail: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setBusy(false);
    }
  };

  const statuses = useMemo(() => {
    const s = new Set(sims.filter((x) => chosen.includes(x.id)).map((x) => x.validation_status));
    return Array.from(s);
  }, [sims, chosen]);

  return (
    <Splitter
      storageKey="reports"
      initial={0.34}
      min={0.24}
      max={0.52}
      first={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          <Panel title="Report configuration" className="shrink-0">
            <div className="space-y-2">
              <Field label="Title" inline={false}>
                <TextInput value={title} onChange={setTitle} />
              </Field>
              <Field label="Author" inline={false}>
                <TextInput value={author} onChange={setAuthor} placeholder="Your name or group" />
              </Field>
              <SectionLabel>Sections to include</SectionLabel>
              <Toggle
                checked={includeValidation}
                onChange={setIncludeValidation}
                label="Independent validation results"
              />
              <Toggle checked={includeLimitations} onChange={setIncludeLimitations} label="Limitations" />
              <Toggle checked={includeReferences} onChange={setIncludeReferences} label="References" />
              <Hint>
                The validation section runs the full held-out validation pipeline for every model
                used in the selected runs, so the accuracy figures in the report are produced by
                the engine at generation time rather than copied from a cached claim.
              </Hint>
            </div>
          </Panel>

          <Panel
            title={`Select runs (${chosen.length} of ${sims.length})`}
            className="min-h-0 flex-1"
            scroll
            dense
            actions={
              <>
                <Button size="xs" variant="ghost" onClick={() => setChosen(sims.map((s) => s.id))}>
                  all
                </Button>
                <Button size="xs" variant="ghost" onClick={() => setChosen([])}>
                  none
                </Button>
              </>
            }
          >
            <div className="border-b border-line p-1.5">
              <select
                value={expFilter ?? ""}
                onChange={(e) => setExpFilter(e.target.value ? Number(e.target.value) : null)}
                className="h-6 w-full rounded-sm border border-line-strong bg-void px-1 text-xs text-ink"
              >
                <option value="">All experiments</option>
                {experiments.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name} ({x.n_simulations})
                  </option>
                ))}
              </select>
            </div>
            {sims.length === 0 ? (
              <div className="p-3 text-xs text-ink-faint">
                No stored runs. Execute a simulation in the Studio with an experiment selected, and
                it will appear here.
              </div>
            ) : (
              sims.map((s) => {
                const on = chosen.includes(s.id);
                return (
                  <button
                    key={s.id}
                    onClick={() =>
                      setChosen((c) => (on ? c.filter((x) => x !== s.id) : [...c, s.id]))
                    }
                    className={cx(
                      "flex w-full items-start gap-2 border-b border-line px-2 py-1.5 text-left",
                      on ? "bg-accent-wash" : "hover:bg-raised",
                    )}
                  >
                    <span
                      className={cx(
                        "mt-0.5 flex h-3 w-3 shrink-0 items-center justify-center rounded-xs border text-[8px]",
                        on ? "border-accent bg-accent text-void" : "border-line-strong text-transparent",
                      )}
                    >
                      ✓
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs text-ink">{s.label}</span>
                      <span className="flex items-center gap-1.5 text-[9px] text-ink-ghost">
                        <span className="font-mono">{s.model_id}</span>
                        <span>·</span>
                        <span>{relativeTime(s.created_at)}</span>
                        {s.solver_warning_count > 0 && <Badge tone="warn">{s.solver_warning_count}</Badge>}
                      </span>
                    </span>
                    <ValidationBadge status={s.validation_status} />
                  </button>
                );
              })
            )}
          </Panel>

          <div className="shrink-0 space-y-1.5 rounded border border-line bg-panel p-1.5">
            {statuses.length > 1 && (
              <Notice tone="warn" compact>
                The selected runs have different validation statuses ({statuses.join(", ")}). The
                report will state each one per run; do not read across them as equally supported.
              </Notice>
            )}
            <Button
              variant="primary"
              size="md"
              full
              loading={busy}
              disabled={chosen.length === 0}
              onClick={() => void generate()}
            >
              Generate report
            </Button>
          </div>
        </div>
      }
      second={
        <div className="flex min-h-0 flex-1 flex-col p-1">
          <Panel
            title="Report preview"
            subtitle={markdown ? `${markdown.length.toLocaleString()} characters` : undefined}
            className="min-h-0 flex-1"
            scroll
            actions={
              markdown && (
                <>
                  <Button
                    size="xs"
                    variant="default"
                    onClick={() => downloadText(`${slug(title)}.md`, markdown, "text/markdown")}
                  >
                    ⤓ Markdown
                  </Button>
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={() => {
                      void navigator.clipboard.writeText(markdown);
                      toast.push({ tone: "ok", title: "Copied to clipboard" });
                    }}
                  >
                    Copy
                  </Button>
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={async () => {
                      try {
                        const j = await api.report({
                          simulation_ids: chosen,
                          title,
                          author,
                          include_validation: includeValidation,
                          include_references: includeReferences,
                          include_limitations: includeLimitations,
                          format: "json",
                        });
                        downloadText(`${slug(title)}.json`, JSON.stringify(j, null, 2), "application/json");
                      } catch (e) {
                        toast.push({ tone: "danger", title: "Export failed", detail: String(e) });
                      }
                    }}
                  >
                    ⤓ JSON
                  </Button>
                </>
              )
            }
          >
            {!markdown ? (
              <EmptyState title="No report generated yet">
                Select the runs to include and press Generate. The report contains the complete
                methods record for each run: every parameter with its evidence origin, the solver
                settings and diagnostics, the exposure metrics, the independent validation results
                for the models used, the declared limitations, and the full reference list with
                PMIDs and access notes.
                {meta && (
                  <div className="mt-3 text-[9px] text-ink-ghost">
                    Reports are stamped {meta.software_name} {meta.software_version} ({meta.engine_revision}).
                  </div>
                )}
              </EmptyState>
            ) : (
              <MarkdownView text={markdown} />
            )}
          </Panel>
        </div>
      }
    />
  );
}

/**
 * Minimal Markdown renderer for the report preview.
 *
 * Deliberately not a full Markdown engine: the backend emits a known, narrow
 * subset (headings, lists, tables, blockquotes, fenced code, bold), and
 * handling exactly that subset avoids pulling in a parser and avoids rendering
 * anything unexpected.
 */
function MarkdownView({ text }: { text: string }) {
  const blocks = useMemo(() => parseMarkdown(text), [text]);
  return (
    <article className="mx-auto max-w-4xl space-y-2 pb-6">
      {blocks.map((b, i) => {
        switch (b.kind) {
          case "h1":
            return (
              <h1 key={i} className="mt-4 border-b border-line pb-1 text-xl font-semibold text-ink first:mt-0">
                {b.text}
              </h1>
            );
          case "h2":
            return (
              <h2 key={i} className="mt-5 border-b border-line pb-1 text-base font-semibold text-ink">
                {b.text}
              </h2>
            );
          case "h3":
            return (
              <h3 key={i} className="mt-4 text-sm font-semibold text-accent">
                {b.text}
              </h3>
            );
          case "quote":
            return (
              <blockquote
                key={i}
                className="rounded border border-warn/30 bg-warn/[0.07] px-2.5 py-2 text-xs leading-relaxed text-warn"
              >
                {b.text}
              </blockquote>
            );
          case "code":
            return (
              <pre
                key={i}
                className="overflow-x-auto rounded border border-line bg-void p-2 font-mono text-[10px] leading-relaxed text-ink-dim"
              >
                {b.text}
              </pre>
            );
          case "list":
            return (
              <ul key={i} className="space-y-1 pl-1">
                {b.items.map((it, j) => (
                  <li key={j} className="flex gap-2 text-xs leading-relaxed text-ink-dim">
                    <span className="shrink-0 text-ink-ghost">·</span>
                    <span>{inline(it)}</span>
                  </li>
                ))}
              </ul>
            );
          case "table":
            return (
              <div key={i} className="overflow-x-auto">
                <Table headers={b.headers}>
                  {b.rows.map((r, j) => (
                    <Row key={j}>
                      {r.map((c, k) => (
                        <Cell key={k} mono={k > 0} align={k > 0 ? "right" : "left"}>
                          {inline(c)}
                        </Cell>
                      ))}
                    </Row>
                  ))}
                </Table>
              </div>
            );
          default:
            return (
              <p key={i} className="text-xs leading-relaxed text-ink-dim">
                {inline(b.text)}
              </p>
            );
        }
      })}
    </article>
  );
}

type Block =
  | { kind: "h1" | "h2" | "h3" | "p" | "quote" | "code"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "table"; headers: string[]; rows: string[][] };

function parseMarkdown(src: string): Block[] {
  const lines = src.split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i]!;
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i]!.startsWith("```")) buf.push(lines[i++]!);
      i++;
      out.push({ kind: "code", text: buf.join("\n") });
      continue;
    }
    if (line.startsWith("### ")) {
      out.push({ kind: "h3", text: line.slice(4) });
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      out.push({ kind: "h2", text: line.slice(3) });
      i++;
      continue;
    }
    if (line.startsWith("# ")) {
      out.push({ kind: "h1", text: line.slice(2) });
      i++;
      continue;
    }
    if (line.startsWith("> ")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i]!.startsWith("> ")) buf.push(lines[i++]!.slice(2));
      out.push({ kind: "quote", text: buf.join(" ") });
      continue;
    }
    // table: | a | b |  followed by | --- | --- |
    if (line.trim().startsWith("|") && lines[i + 1]?.trim().startsWith("|") && /-{2,}/.test(lines[i + 1]!)) {
      const headers = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i]!.trim().startsWith("|")) rows.push(splitRow(lines[i++]!));
      out.push({ kind: "table", headers, rows });
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i]!)) {
        items.push(lines[i++]!.replace(/^\s*[-*]\s+/, ""));
      }
      out.push({ kind: "list", items });
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i]!)) {
        items.push(lines[i++]!.replace(/^\s*\d+\.\s+/, ""));
      }
      out.push({ kind: "list", items });
      continue;
    }
    const buf: string[] = [];
    while (
      i < lines.length &&
      lines[i]!.trim() &&
      !/^(#{1,3} |> |```|\s*[-*]\s+|\s*\d+\.\s+)/.test(lines[i]!) &&
      !lines[i]!.trim().startsWith("|")
    ) {
      buf.push(lines[i++]!);
    }
    out.push({ kind: "p", text: buf.join(" ") });
  }
  return out;
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.trim());
}

/** Render bold and inline code; everything else stays literal text. */
function inline(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-ink">
          {p.slice(2, -2)}
        </strong>
      );
    }
    if (p.startsWith("`") && p.endsWith("`")) {
      return (
        <code key={i} className="rounded-xs bg-raised px-1 font-mono text-[10px] text-accent">
          {p.slice(1, -1)}
        </code>
      );
    }
    return <span key={i}>{p}</span>;
  });
}
