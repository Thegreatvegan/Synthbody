/**
 * Scientific Evidence Library.
 *
 * Three jobs:
 *   1. A searchable reference database where every entry states whether its
 *      full text was actually retrieved, what its licence allows, and which
 *      models and drugs depend on it.
 *   2. The validation workspace: the real held-out accuracy numbers, with
 *      predicted-versus-observed and residual plots drawn from the engine's own
 *      validation pipeline.
 *   3. The shipped observed datasets, with their limitations.
 */
import { useEffect, useMemo, useState } from "react";
import { Plot, type PlotSeries } from "../components/charts/Plot";
import {
  Badge,
  Button,
  Cell,
  EmptyState,
  Hint,
  Metric,
  Notice,
  OriginBadge,
  Panel,
  Row,
  SectionLabel,
  Select,
  Splitter,
  Table,
  Tabs,
  TextInput,
  Toggle,
  ValidationBadge,
  cx,
} from "../components/ui";
import { api } from "../lib/api";
import { downloadText, pct, pctRaw, prettyUnit, seriesColour, sig, slug, toCsv } from "../lib/format";
import { useStore } from "../lib/store";
import { BenchmarkTab } from "./BenchmarkTab";
import type {
  DatasetSummary,
  PbpkStructuralCheck,
  Reference,
  ValidationReport,
  ValidationTargets,
} from "../lib/types";

export function EvidenceLibrary() {
  const [tab, setTab] = useState<
    "validation" | "benchmark" | "references" | "datasets" | "feasibility"
  >("validation");
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "validation", label: "Model validation" },
          {
            id: "benchmark",
            label: "Competitive benchmark",
            title: "A-priori absorption benchmark, and the head-to-head comparison that could not be run",
          },
          { id: "references", label: "Reference library" },
          { id: "datasets", label: "Observed datasets" },
          { id: "feasibility", label: "Feasibility assessment" },
        ]}
      />
      <div className="flex min-h-0 flex-1">
        {tab === "validation" && <ValidationTab />}
        {tab === "benchmark" && <BenchmarkTab />}
        {tab === "references" && <ReferencesTab />}
        {tab === "datasets" && <DatasetsTab />}
        {tab === "feasibility" && <FeasibilityTab />}
      </div>
    </div>
  );
}

// ===========================================================================
// Validation
// ===========================================================================
function ValidationTab() {
  const [targets, setTargets] = useState<ValidationTargets | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [pbpk, setPbpk] = useState<PbpkStructuralCheck | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    void api.validationTargets().then((t) => {
      setTargets(t);
      setSelected(t.targets[0]?.target_id ?? null);
    });
    void api.pbpkCheck().then(setPbpk).catch(() => setPbpk(null));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    setReport(null);
    void api
      .validation(selected)
      .then(setReport)
      .finally(() => setLoading(false));
  }, [selected]);

  return (
    <Splitter
      storageKey="evidence-val"
      initial={0.2}
      min={0.15}
      max={0.35}
      first={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          <Panel title="Validation targets" className="shrink-0" dense>
            {(targets?.targets ?? []).map((t) => (
              <button
                key={t.target_id}
                onClick={() => setSelected(t.target_id)}
                className={cx(
                  "w-full border-b border-line px-2 py-1.5 text-left",
                  selected === t.target_id ? "bg-accent-wash" : "hover:bg-raised",
                )}
              >
                <div className="truncate text-xs text-ink">{t.model_label}</div>
                <div className="text-[9px] text-ink-ghost">
                  dataset {t.dataset_id} · estimates {t.estimated_parameters.join(", ")}
                </div>
              </button>
            ))}
          </Panel>

          <Panel title="Protocol" className="shrink-0">
            {targets && (
              <div className="space-y-2">
                <Notice tone="info" compact title="How the split works">
                  {targets.protocol.description}
                </Notice>
                <Notice tone="warn" compact title="Why it matters">
                  {targets.protocol.why_it_matters}
                </Notice>
              </div>
            )}
          </Panel>

          {pbpk && (
            <Panel title="PBPK structural check" className="min-h-0 flex-1" scroll>
              <div className="space-y-1.5">
                <ValidationBadge status="research_only" full />
                <Metric label="Predicted Vss" value={pbpk.predicted_vss_L_per_kg} unit="L/kg" origin="derived" />
                <Metric
                  label="Literature value"
                  value={pbpk.literature_comparison_L_per_kg}
                  unit="L/kg"
                  origin="inferred"
                />
                <Metric
                  label="Fold difference"
                  value={pbpk.fold_difference}
                  tone={pbpk.passes_2_fold ? "ok" : "warn"}
                />
                <Notice tone="warn" compact title="Honest scope">
                  {pbpk.honest_scope}
                </Notice>
              </div>
            </Panel>
          )}
        </div>
      }
      second={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          {loading ? (
            <Panel title="Running validation…" className="min-h-0 flex-1">
              <EmptyState title="Estimating parameters and predicting held-out subjects">
                The engine is fitting the calibration subjects and then predicting the held-out
                subjects. This runs live rather than reading a cached result, so the numbers below
                are always current for the code you are running.
              </EmptyState>
            </Panel>
          ) : report ? (
            <ValidationReportView report={report} />
          ) : (
            <Panel title="Model validation" className="min-h-0 flex-1">
              <EmptyState title="Select a validation target" />
            </Panel>
          )}
        </div>
      }
    />
  );
}

function ValidationReportView({ report }: { report: ValidationReport }) {
  const [showCalib, setShowCalib] = useState(false);
  const [logScale, setLogScale] = useState(true);
  const h = report.held_out_metrics;
  const c = report.calibration_metrics;

  const ovpSeries: PlotSeries[] = useMemo(() => {
    const out: PlotSeries[] = [
      {
        id: "held",
        label: `Held-out (n=${report.observed_vs_predicted["held_out_observed"]?.length ?? 0})`,
        x: report.observed_vs_predicted["held_out_observed"] ?? [],
        y: report.observed_vs_predicted["held_out_predicted"] ?? [],
        colour: "#3fd3bd",
        kind: "points",
        pointRadius: 3,
      },
    ];
    if (showCalib) {
      out.push({
        id: "calib",
        label: `Calibration (n=${report.observed_vs_predicted["calibration_observed"]?.length ?? 0})`,
        x: report.observed_vs_predicted["calibration_observed"] ?? [],
        y: report.observed_vs_predicted["calibration_predicted"] ?? [],
        colour: "#e0a34a",
        kind: "points",
        pointRadius: 3,
        hollow: true,
      });
    }
    return out;
  }, [report, showCalib]);

  const residualSeries: PlotSeries[] = [
    {
      id: "res",
      label: "Held-out residual (observed − predicted)",
      x: report.held_out_residuals.predicted,
      y: report.held_out_residuals.residuals,
      colour: "#5aa9e6",
      kind: "points",
      pointRadius: 3,
    },
  ];

  const profileSeries: PlotSeries[] = useMemo(() => {
    const out: PlotSeries[] = [];
    report.profiles
      .filter((p) => showCalib || p.set === "held_out")
      .forEach((p, i) => {
        const col = p.set === "held_out" ? seriesColour(i) : "#49525b";
        out.push({
          id: `pred-${p.subject_id}`,
          label: `Subject ${p.subject_id} predicted`,
          x: p.time_h,
          y: p.predicted,
          colour: col,
          width: 1.3,
          opacity: p.set === "held_out" ? 1 : 0.5,
          hideInReadout: true,
        });
        out.push({
          id: `obs-${p.subject_id}`,
          label: `Subject ${p.subject_id} observed`,
          x: p.observed_time_h,
          y: p.observed,
          colour: col,
          kind: "points",
          pointRadius: 2.4,
          opacity: p.set === "held_out" ? 1 : 0.5,
          hideInReadout: true,
        });
      });
    return out;
  }, [report, showCalib]);

  return (
    <>
      <Panel
        title={`${report.model_label} vs ${report.dataset_name}`}
        subtitle={`calibration: ${report.calibration_subject_ids.join(",")} · held out: ${report.held_out_subject_ids.join(",")}`}
        className="shrink-0"
      >
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-3">
          <div>
            <SectionLabel>Held-out accuracy (the number that counts)</SectionLabel>
            <Metric label="Observations" value={h.n} digits={4} />
            <Metric label="RMSE" value={h.rmse} unit={h.units} tone="accent" />
            <Metric label="MAE" value={h.mae} unit={h.units} />
            <Metric
              label="Median absolute % error"
              value={pctRaw(h.median_absolute_percent_error)}
              tone={h.median_absolute_percent_error < 30 ? "ok" : "warn"}
            />
            <Metric
              label="Average fold error (bias)"
              value={h.average_fold_error}
              hint="1.0 means unbiased on the log scale."
            />
            <Metric
              label="Absolute AFE (precision)"
              value={h.absolute_average_fold_error}
              hint="1.0 means perfect. 1.3 means a typical 30% error."
              tone={(h.absolute_average_fold_error ?? 9) < 1.5 ? "ok" : "warn"}
            />
            <Metric label="Within 1.25-fold" value={pct(h.fraction_within_1_25_fold)} />
            <Metric label="Within 1.5-fold" value={pct(h.fraction_within_1_5_fold)} />
            <Metric
              label="Within 2-fold"
              value={pct(h.fraction_within_2_fold)}
              tone={(h.fraction_within_2_fold ?? 0) > 0.8 ? "ok" : "warn"}
            />
            <Metric
              label="R² vs line of identity"
              value={h.r_squared_vs_identity}
              hint="Against the 1:1 line, not against a fitted regression. It can go negative, and should when a model is worse than the mean."
            />
            <Metric label="Lin concordance" value={h.concordance_correlation} />
          </div>

          <div>
            <SectionLabel>Calibration set (software check only)</SectionLabel>
            <Metric label="Observations" value={c.n} digits={4} />
            <Metric label="RMSE" value={c.rmse} unit={c.units} />
            <Metric label="Median absolute % error" value={pctRaw(c.median_absolute_percent_error)} />
            <Metric label="Absolute AFE" value={c.absolute_average_fold_error} />
            <Metric label="Within 2-fold" value={pct(c.fraction_within_2_fold)} />
            <Notice tone="warn" compact>
              These numbers only show the fit worked. They are not evidence the model generalises,
              and a product that quoted them as its accuracy would be misleading you.
            </Notice>
          </div>

          <div>
            <SectionLabel>Typical parameters from the calibration set</SectionLabel>
            {Object.entries(report.typical_parameters).map(([k, v]) => (
              <Metric
                key={k}
                label={k}
                value={v}
                origin="fitted"
                hint={`Between-subject CV ${report.between_subject_cv_percent[k]?.toFixed(1) ?? "—"}%`}
              />
            ))}
            <SectionLabel>Between-subject CV%</SectionLabel>
            {Object.entries(report.between_subject_cv_percent).map(([k, v]) => (
              <Metric key={k} label={k} value={pctRaw(v)} tone={v > 80 ? "warn" : undefined} />
            ))}
          </div>
        </div>

        <div className="mt-2 space-y-1.5">
          <Notice tone="info" title="Interpretation">
            {report.interpretation}
          </Notice>
          <Notice tone="warn" title="Estimation method">
            {report.estimation_note}
          </Notice>
          {report.warnings.length > 0 && (
            <Notice tone="warn" title={`${report.warnings.length} warning(s) from the fit`}>
              <ul className="mt-1 space-y-0.5">
                {report.warnings.slice(0, 8).map((w, i) => (
                  <li key={i}>· {w}</li>
                ))}
              </ul>
            </Notice>
          )}
        </div>
      </Panel>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-1 xl:grid-cols-2">
        <Panel
          title="Predicted vs observed"
          subtitle="solid line = identity, dashed = 2-fold envelope"
          actions={
            <>
              <Toggle
                checked={showCalib}
                onChange={setShowCalib}
                label={<span className="text-2xs">show calibration</span>}
              />
              <Toggle checked={logScale} onChange={setLogScale} label={<span className="text-2xs">log</span>} />
            </>
          }
          scroll
        >
          <div className="group/plot">
            <Plot
              series={ovpSeries}
              identityLine
              foldLines={[2]}
              xLabel="Observed"
              yLabel="Predicted"
              xUnit={h.units}
              yUnit={h.units}
              xScale={logScale ? "log" : "linear"}
              yScale={logScale ? "log" : "linear"}
              height={280}
              onExportName={`${slug(report.target_id)}-pred-vs-obs`}
            />
          </div>
        </Panel>

        <Panel
          title="Residuals"
          subtitle="observed − predicted, held-out subjects only"
          scroll
          actions={
            <Button
              size="xs"
              variant="ghost"
              onClick={() =>
                downloadText(
                  `${slug(report.target_id)}-residuals.csv`,
                  toCsv(
                    ["observed", "predicted", "residual", "weighted_residual"],
                    report.held_out_residuals.observed.map((o, i) => [
                      o,
                      report.held_out_residuals.predicted[i] ?? "",
                      report.held_out_residuals.residuals[i] ?? "",
                      report.held_out_residuals.weighted_residuals[i] ?? "",
                    ]),
                  ),
                  "text/csv",
                )
              }
            >
              ⤓ CSV
            </Button>
          }
        >
          <div className="group/plot">
            <Plot
              series={residualSeries}
              zeroLine
              xLabel="Predicted"
              yLabel="Residual"
              xUnit={h.units}
              yUnit={h.units}
              height={280}
              onExportName={`${slug(report.target_id)}-residuals`}
            />
          </div>
          <div className="mt-1 space-y-1">
            <Metric label="Residual mean" value={report.held_out_residuals.residual_mean} unit={h.units} />
            <Metric label="Residual SD" value={report.held_out_residuals.residual_sd} unit={h.units} />
            <Metric
              label="Spearman |residual| vs predicted"
              value={report.held_out_residuals.spearman_abs_residual_vs_predicted}
              tone={
                (report.held_out_residuals.spearman_abs_residual_vs_predicted ?? 0) > 0.4
                  ? "warn"
                  : undefined
              }
            />
            <Hint>{report.held_out_residuals.interpretation}</Hint>
          </div>
        </Panel>

        <Panel
          title="Individual profiles"
          subtitle="lines = model prediction with the single typical parameter set, points = observed"
          className="xl:col-span-2"
          scroll
        >
          <div className="group/plot">
            <Plot
              series={profileSeries}
              xLabel="Time"
              xUnit="h"
              yLabel="Concentration"
              yUnit={h.units}
              height={300}
              showLegend={false}
              onExportName={`${slug(report.target_id)}-profiles`}
            />
          </div>
          <Hint>
            Every line uses the same typical parameters, adjusted only by each subject's recorded
            dose and weight. The scatter of the points around the lines is the between-subject
            variability the typical-value model cannot capture.
          </Hint>

          <div className="mt-2">
            <SectionLabel>Per-subject held-out accuracy</SectionLabel>
            <Table
              compact
              headers={[
                "Subject",
                { label: "Dose", align: "right" },
                { label: "Weight", align: "right" },
                { label: "n", align: "right" },
                { label: "RMSE", align: "right" },
                { label: "Median |%| err", align: "right" },
                { label: "AAFE", align: "right" },
                { label: "Within 2×", align: "right" },
                { label: "Obs Cmax", align: "right" },
                { label: "Pred Cmax", align: "right" },
              ]}
            >
              {report.per_subject_held_out.map((s) => (
                <Row key={String(s["subject_id"])}>
                  <Cell>
                    <span className="text-ink">Subject {String(s["subject_id"])}</span>
                  </Cell>
                  <Cell align="right" mono dim>
                    {sig(s["dose_mg"] as number, 4)}
                  </Cell>
                  <Cell align="right" mono dim>
                    {s["weight_kg"] != null ? sig(s["weight_kg"] as number, 3) : "—"}
                  </Cell>
                  <Cell align="right" mono dim>
                    {String(s["n_observations"])}
                  </Cell>
                  <Cell align="right" mono>
                    {sig(s["rmse"] as number, 3)}
                  </Cell>
                  <Cell align="right" mono>
                    {s["mean_absolute_percent_error"] != null
                      ? pctRaw(s["mean_absolute_percent_error"] as number, 0)
                      : "—"}
                  </Cell>
                  <Cell align="right" mono>
                    {sig(s["absolute_average_fold_error"] as number, 3)}
                  </Cell>
                  <Cell align="right" mono>
                    {s["fraction_within_2_fold"] != null
                      ? pct(s["fraction_within_2_fold"] as number, 0)
                      : "—"}
                  </Cell>
                  <Cell align="right" mono dim>
                    {sig(s["observed_cmax"] as number, 3)}
                  </Cell>
                  <Cell align="right" mono dim>
                    {sig(s["predicted_cmax"] as number, 3)}
                  </Cell>
                </Row>
              ))}
            </Table>
          </div>
        </Panel>
      </div>
    </>
  );
}

// ===========================================================================
// References
// ===========================================================================
function ReferencesTab() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [topic, setTopic] = useState("");
  const [data, setData] = useState<{
    references: Reference[];
    topics: string[];
    kinds: string[];
    n_total: number;
    n_matched: number;
    curation_note: string;
  } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Reference | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      void api
        .references({ q: q || undefined, kind: kind || undefined, topic: topic || undefined })
        .then(setData);
    }, 150);
    return () => clearTimeout(t);
  }, [q, kind, topic]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    void api.reference(selected).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  return (
    <Splitter
      storageKey="evidence-refs"
      initial={0.42}
      min={0.3}
      max={0.65}
      first={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          <Panel title="Search the reference library" className="shrink-0">
            <div className="space-y-2">
              <TextInput value={q} onChange={setQ} placeholder="Search citations, topics, authors, access notes…" />
              <div className="grid grid-cols-2 gap-2">
                <Select
                  value={kind}
                  onChange={setKind}
                  options={[
                    { value: "", label: "All kinds" },
                    ...(data?.kinds ?? []).map((k) => ({ value: k, label: k.replace(/_/g, " ") })),
                  ]}
                />
                <Select
                  value={topic}
                  onChange={setTopic}
                  options={[
                    { value: "", label: "All topics" },
                    ...(data?.topics ?? []).map((t) => ({ value: t, label: t })),
                  ]}
                />
              </div>
              {data && (
                <div className="flex items-center gap-2 text-2xs text-ink-faint">
                  <span>
                    {data.n_matched} of {data.n_total} references
                  </span>
                  {(q || kind || topic) && (
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={() => {
                        setQ("");
                        setKind("");
                        setTopic("");
                      }}
                    >
                      clear
                    </Button>
                  )}
                </div>
              )}
            </div>
          </Panel>

          <Panel title="References" className="min-h-0 flex-1" scroll dense>
            {(data?.references ?? []).map((r) => (
              <button
                key={r.id}
                onClick={() => setSelected(r.id)}
                className={cx(
                  "w-full border-b border-line px-2 py-1.5 text-left",
                  selected === r.id ? "bg-accent-wash" : "hover:bg-raised",
                )}
              >
                <div className="text-xs leading-snug text-ink-dim">{r.citation}</div>
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  <Badge tone="neutral">{r.kind.replace(/_/g, " ")}</Badge>
                  {r.pmid && <Badge mono tone="info">PMID {r.pmid}</Badge>}
                  {!r.pmid && <Badge tone="warn">no PMID</Badge>}
                  <span className="ml-auto font-mono text-[9px] text-ink-ghost">{r.id}</span>
                </div>
              </button>
            ))}
            {data && data.references.length === 0 && (
              <div className="p-3 text-xs text-ink-faint">No references match that query.</div>
            )}
          </Panel>

          {data && (
            <Panel title="Curation note" className="shrink-0">
              <Hint>{data.curation_note}</Hint>
            </Panel>
          )}
        </div>
      }
      second={
        <div className="flex min-h-0 flex-1 flex-col p-1">
          <Panel title={detail ? detail.id : "Reference detail"} className="min-h-0 flex-1" scroll>
            {!detail ? (
              <EmptyState title="Select a reference">
                Each entry records whether SYNTHBODY actually retrieved the full text, what its
                licence permits, and which models and compounds depend on it. Entries whose primary
                source could not be opened say so, rather than implying a depth of verification
                that did not happen.
              </EmptyState>
            ) : (
              <div className="space-y-3">
                <div>
                  <p className="text-sm leading-relaxed text-ink">{detail.citation}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Badge tone="neutral">{detail.kind.replace(/_/g, " ")}</Badge>
                    <Badge>{detail.year}</Badge>
                    {detail.pmid && (
                      <a
                        href={`https://pubmed.ncbi.nlm.nih.gov/${detail.pmid}/`}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="rounded-xs border border-info/30 bg-info/12 px-1 py-px text-[9px] font-semibold uppercase text-info hover:bg-info/20"
                      >
                        PMID {detail.pmid} ↗
                      </a>
                    )}
                    {detail.doi && (
                      <a
                        href={`https://doi.org/${detail.doi}`}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="rounded-xs border border-line-strong bg-raised px-1 py-px font-mono text-[9px] text-ink-dim hover:text-accent"
                      >
                        {detail.doi} ↗
                      </a>
                    )}
                  </div>
                </div>

                <div>
                  <SectionLabel>Why SYNTHBODY cites it</SectionLabel>
                  <p className="text-xs leading-relaxed text-ink-dim">{detail.relevance}</p>
                </div>

                <Notice
                  tone={
                    /NOT USED|NOT INDEPENDENTLY|not retrieved/i.test(detail.access_note) ? "warn" : "info"
                  }
                  title="Access and verification"
                >
                  {detail.access_note}
                </Notice>

                <Notice tone="neutral" title="Licence and reuse">
                  {detail.license_note}
                </Notice>

                <div>
                  <SectionLabel>Topics</SectionLabel>
                  <div className="flex flex-wrap gap-1">
                    {detail.topics.map((t) => (
                      <Badge key={t} tone="neutral">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </div>

                {(detail.used_by_models?.length || detail.used_by_drugs?.length) && (
                  <div>
                    <SectionLabel>What depends on this reference</SectionLabel>
                    {detail.used_by_models && detail.used_by_models.length > 0 && (
                      <div className="mb-1">
                        <span className="text-2xs text-ink-faint">Models: </span>
                        {detail.used_by_models.map((m) => (
                          <Badge key={m} mono tone="accent">
                            {m}
                          </Badge>
                        ))}
                      </div>
                    )}
                    {detail.used_by_drugs && detail.used_by_drugs.length > 0 && (
                      <div>
                        <span className="text-2xs text-ink-faint">Compounds: </span>
                        {detail.used_by_drugs.map((d) => (
                          <Badge key={d} mono tone="violet">
                            {d}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {detail.url && (
                  <a
                    href={detail.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-block text-xs text-accent hover:underline"
                  >
                    Open source ↗
                  </a>
                )}
              </div>
            )}
          </Panel>
        </div>
      }
    />
  );
}

// ===========================================================================
// Datasets
// ===========================================================================
function DatasetsTab() {
  const datasets = useStore((s) => s.datasets);
  const [selected, setSelected] = useState<string | null>(datasets[0]?.dataset_id ?? null);
  const [detail, setDetail] = useState<
    | (DatasetSummary & {
        observations: {
          subject_id: string;
          dose_mg: number;
          weight_kg: number | null;
          time_h: number[];
          concentration: number[];
        }[];
      })
    | null
  >(null);
  const [logScale, setLogScale] = useState(true);

  useEffect(() => {
    if (!selected) return;
    void api.dataset(selected).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  const series: PlotSeries[] = useMemo(
    () =>
      (detail?.observations ?? []).flatMap((o, i) => [
        {
          id: `s-${o.subject_id}`,
          label: `Subject ${o.subject_id}`,
          x: o.time_h,
          y: o.concentration,
          colour: seriesColour(i),
          kind: "both" as const,
          width: 1.1,
          pointRadius: 2.4,
        },
      ]),
    [detail],
  );

  return (
    <Splitter
      storageKey="evidence-data"
      initial={0.24}
      min={0.18}
      max={0.4}
      first={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          <Panel title={`Observed datasets (${datasets.length})`} className="shrink-0" dense>
            {datasets.map((d) => (
              <button
                key={d.dataset_id}
                onClick={() => setSelected(d.dataset_id)}
                className={cx(
                  "w-full border-b border-line px-2 py-1.5 text-left",
                  selected === d.dataset_id ? "bg-accent-wash" : "hover:bg-raised",
                )}
              >
                <div className="truncate text-xs text-ink">{d.name}</div>
                <div className="text-[9px] text-ink-ghost">
                  {d.n_subjects} subjects · {d.n_observations} observations · {d.route.replace("_", " ")}
                </div>
              </button>
            ))}
          </Panel>
          <Panel title="These are real measurements" className="min-h-0 flex-1" scroll>
            <Notice tone="ok" compact>
              Every value in these datasets was measured in a human subject and published. Nothing
              here is synthetic. They are the only reason SYNTHBODY can make any validated claim at
              all.
            </Notice>
            <div className="mt-2">
              <Hint>
                Both datasets ship in the R <span className="font-mono">datasets</span> package
                under GPL-2 | GPL-3 and were obtained programmatically, unmodified. Their
                limitations are listed on the right and are not cosmetic: they bound exactly what
                the validated models can be trusted for.
              </Hint>
            </div>
          </Panel>
        </div>
      }
      second={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          {!detail ? (
            <Panel title="Dataset" className="min-h-0 flex-1">
              <EmptyState title="Select a dataset" />
            </Panel>
          ) : (
            <>
              <Panel
                title={detail.name}
                subtitle={`${detail.n_subjects} subjects · ${detail.n_observations} observations`}
                className="min-h-0 flex-1"
                actions={
                  <>
                    <Toggle checked={logScale} onChange={setLogScale} label={<span className="text-2xs">log y</span>} />
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={() =>
                        downloadText(
                          `${detail.dataset_id}-observed.csv`,
                          toCsv(
                            ["subject_id", "dose_mg", "weight_kg", "time_h", "concentration"],
                            detail.observations.flatMap((o) =>
                              o.time_h.map((t, i) => [o.subject_id, o.dose_mg, o.weight_kg, t, o.concentration[i]]),
                            ),
                          ),
                          "text/csv",
                        )
                      }
                    >
                      ⤓ CSV
                    </Button>
                  </>
                }
              >
                <div className="group/plot">
                  <Plot
                    series={series}
                    xLabel="Time"
                    xUnit="h"
                    yLabel="Observed concentration"
                    yUnit={detail.concentration_unit}
                    yScale={logScale ? "log" : "linear"}
                    height={300}
                    showLegend={false}
                    onExportName={`${detail.dataset_id}-observed`}
                  />
                </div>
                <Hint>{detail.description}</Hint>
              </Panel>

              <Panel title="Provenance, licence and limitations" className="max-h-[48%] shrink-0" scroll>
                <div className="space-y-2">
                  <Notice tone="info" compact title="Provenance">
                    {detail.provenance}
                  </Notice>
                  <Notice tone="neutral" compact title="Licence">
                    {detail.license_note}
                  </Notice>
                  <SectionLabel>Known limitations</SectionLabel>
                  <ul className="space-y-1.5">
                    {detail.known_limitations.map((l, i) => (
                      <li key={i} className="flex gap-2 text-xs leading-relaxed">
                        <span className="shrink-0 text-warn">!</span>
                        <span className="text-ink-dim">{l}</span>
                      </li>
                    ))}
                  </ul>
                  <SectionLabel>Subjects</SectionLabel>
                  <Table
                    compact
                    headers={[
                      "Subject",
                      { label: "n obs", align: "right" },
                      { label: "Dose", align: "right" },
                      { label: "Weight", align: "right" },
                      { label: "t last", align: "right" },
                      { label: "Observed Cmax", align: "right" },
                    ]}
                  >
                    {detail.subjects.map((s, i) => (
                      <Row key={s.subject_id}>
                        <Cell>
                          <span className="flex items-center gap-1.5">
                            <span className="h-[3px] w-3" style={{ background: seriesColour(i) }} />
                            <span className="text-ink">{s.subject_id}</span>
                          </span>
                        </Cell>
                        <Cell align="right" mono dim>
                          {s.n_observations}
                        </Cell>
                        <Cell align="right" mono>
                          {sig(s.dose_mg, 4)}
                        </Cell>
                        <Cell align="right" mono dim>
                          {s.weight_kg != null ? sig(s.weight_kg, 3) : "—"}
                        </Cell>
                        <Cell align="right" mono dim>
                          {sig(s.t_last_h, 3)}
                        </Cell>
                        <Cell align="right" mono>
                          {sig(s.cmax_observed, 3)} {prettyUnit(detail.concentration_unit)}
                        </Cell>
                      </Row>
                    ))}
                  </Table>
                </div>
              </Panel>
            </>
          )}
        </div>
      }
    />
  );
}

// ===========================================================================
// Feasibility
// ===========================================================================
interface FeasRow {
  component: string;
  paperClaim: string;
  status: "implemented" | "simplified" | "unsupported" | "infeasible";
  basis: string;
  validation: string;
}

const FEASIBILITY: FeasRow[] = [
  {
    component: "Compartmental pharmacokinetics (1-cmt, 2-cmt)",
    paperClaim: "Stochastic pharmacokinetics layer covering absorption, distribution, metabolism and excretion",
    status: "implemented",
    basis: "Standard linear ODE systems with analytic solutions available for verification. Solved with SciPy adaptive integrators and verified against the closed forms to better than 1e-8 of peak.",
    validation: "Independently validated on held-out subjects from two published datasets.",
  },
  {
    component: "Non-linear (Michaelis–Menten) elimination",
    paperClaim: "Michaelis–Menten enzyme kinetics throughout the organ modules",
    status: "implemented",
    basis: "Saturable elimination ODE with analytic Jacobian. Verified to reduce to first-order kinetics with CL = Vmax/Km when C << Km, and to show supra-proportional exposure above Km.",
    validation: "Structurally verified only. No licensed non-linear PK dataset is shipped, so no observed-data comparison exists.",
  },
  {
    component: "Whole-body PBPK with organ perfusion",
    paperClaim: "Organ-level simulation with inter-organ transport, portal circulation and hepatic metabolism",
    status: "implemented",
    basis: "Twelve-compartment perfusion-limited model with portal drainage into the liver, well-stirred hepatic clearance, and physiology from the openly licensed US EPA httk dataset. Mass and flow balance both close.",
    validation: "Research only. One external scalar check passes (predicted Vss for theophylline within 1.04-fold of the widely quoted 0.5 L/kg). No concentration-time validation.",
  },
  {
    component: "Tissue partition coefficient prediction",
    paperClaim: "Quantum-mechanical calculation of binding and distribution",
    status: "simplified",
    basis: "Tissue-composition method of Poulin & Theil (2002) from log P, fraction unbound and measured tissue composition. A classical, published, inspectable calculation rather than a quantum one.",
    validation: "Research only, and known to predict poorly for moderate-to-strong bases. Rodgers–Rowland is the appropriate method and is not implemented.",
  },
  {
    component: "Population variability and uncertainty",
    paperClaim: "Probabilistic simulation producing confidence bands rather than single outputs",
    status: "implemented",
    basis: "Log-normal between-subject random effects with optional correlation (projected to the nearest positive semi-definite matrix), plus a separate combined residual error model. Monte Carlo over independent ODE solves.",
    validation: "The sampling machinery is verified to recover the requested CV% and correlation. The variability magnitudes come from two-stage fits and are upper bounds.",
  },
  {
    component: "Parameter sensitivity analysis",
    paperClaim: "Parametric control and intervention testing across every pathway",
    status: "implemented",
    basis: "Local normalised finite differences with a step-halving convergence check, Morris elementary-effects screening, and Sobol variance decomposition via SALib.",
    validation: "Verified against analytic cases (AUC = D/CL gives exactly -1; additive models give S1 summing to 1; multiplicative models show pure interaction).",
  },
  {
    component: "Parameter estimation from observed data",
    paperClaim: "Model calibration logic converting diagnostics into a patient-specific parameter vector",
    status: "simplified",
    basis: "Weighted non-linear least squares on log-transformed parameters with asymptotic standard errors, correlation matrix and a condition-number check for identifiability. Two-stage population summary.",
    validation: "Verified to recover known parameters from noise-free simulated data to 0.1%. This is NOT non-linear mixed-effects estimation, and the platform says so wherever variability is reported.",
  },
  {
    component: "Covariate models (size, renal, hepatic, smoking)",
    paperClaim: "Demographic and diagnostic personalisation of every model parameter",
    status: "simplified",
    basis: "Theory-based allometric scaling and published renal-function equations are implemented and labelled derived. Hepatic-impairment and smoking multipliers are direction-only: the magnitudes are SYNTHBODY defaults, labelled illustrative or inferred in the interface.",
    validation: "The equations are implemented correctly and tested. The multipliers are not evidence and are never presented as such.",
  },
  {
    component: "Reproducibility and lineage",
    paperClaim: "Version-locked containers, input hashing, deterministic re-execution, notarisation",
    status: "implemented",
    basis: "Every run records software version, engine revision, model version, every parameter with its evidence origin, solver settings and diagnostics, under a SHA-256 input hash. Stored runs can be re-executed and compared point by point.",
    validation: "Verified: re-execution reproduces the input hash and the curve bitwise. Blockchain notarisation is deliberately not implemented — it would add no integrity guarantee this product can honour.",
  },
  {
    component: "Pharmacodynamics (Emax, indirect response, effect compartment)",
    paperClaim: "Predictive pharmacodynamics with receptor binding and downstream cascades",
    status: "simplified",
    basis: "Three standard published structures are implemented and numerically verified (baseline stationarity, washout return, effect-site equilibration).",
    validation: "Research only. SYNTHBODY ships no pharmacodynamic dataset, so every PD parameter is illustrative and no effect prediction is supported.",
  },
  {
    component: "Quantum simulation of molecular dynamics",
    paperClaim: "Quantum computing as the only viable substrate; VQE/QAOA for binding energies; Schrödinger-level ligand binding",
    status: "infeasible",
    basis: "Not implementable today at the claimed scale, and not required for the MVP use case. Pharmacokinetic prediction at the exposure level is a differential-equation problem, not an electronic-structure problem. Deliberately excluded rather than simulated for show.",
    validation: "Not applicable. No part of SYNTHBODY claims quantum computation.",
  },
  {
    component: "Immune, endocrine, neurotransmitter and metabolic network simulation",
    paperClaim: "Cytokine cascades, HPA/HPT/HPG axes, synaptic kinetics, glycolysis and ATP accounting",
    status: "unsupported",
    basis: "The equations in the white paper are real and published, but parameterising them for an individual human and validating the result requires data that does not exist in any form SYNTHBODY can access. Implementing them would produce impressive curves with no evidential content.",
    validation: "Not implemented. The Systems workspace lists each one explicitly as absent.",
  },
  {
    component: "Patient-specific calibration from genomic and multi-omic data",
    paperClaim: "Genome, transcriptome, proteome and microbiome input producing a personal chemical twin",
    status: "unsupported",
    basis: "No open, licensed, linked omics-plus-pharmacokinetics dataset was available to train or validate such a mapping. A pharmacogenomic covariate model (for example CYP1A2 or CYP2D6 phenotype on clearance) is a realistic near-term extension and is on the roadmap.",
    validation: "Not implemented.",
  },
  {
    component: "AI copilot making treatment recommendations",
    paperClaim: "Real-time dosing recommendations with explanations, autonomous ICU alerting",
    status: "unsupported",
    basis: "Deliberately excluded. A recommendation engine resting on models validated against twelve healthy adults given a single oral dose would be unsafe regardless of how its reasoning were presented. The platform reports model behaviour and leaves inference to the researcher.",
    validation: "Not implemented, and not a roadmap item until the underlying models carry clinical-grade validation.",
  },
  {
    component: "Disease progression, mutation and recovery simulation",
    paperClaim: "Tumour evolution, viral load mutation, autoimmune misfiring, tissue regeneration",
    status: "unsupported",
    basis: "Published models exist (reaction-diffusion tumour growth, viral dynamics) but none is parameterisable or validatable within this MVP's data access. Implementing them would be visualisation, not prediction.",
    validation: "Not implemented.",
  },
];

const STATUS_META = {
  implemented: { label: "Implemented", tone: "ok" as const },
  simplified: { label: "Simplified", tone: "info" as const },
  unsupported: { label: "Not implemented", tone: "warn" as const },
  infeasible: { label: "Infeasible / excluded", tone: "danger" as const },
};

function FeasibilityTab() {
  const [filter, setFilter] = useState<string>("");
  const rows = filter ? FEASIBILITY.filter((r) => r.status === filter) : FEASIBILITY;
  const counts = FEASIBILITY.reduce<Record<string, number>>((a, r) => {
    a[r.status] = (a[r.status] ?? 0) + 1;
    return a;
  }, {});

  return (
    <div className="min-h-0 flex-1 overflow-auto p-2">
      <Panel
        title="Technical feasibility assessment"
        subtitle="each major component the SYNTHBODY white paper proposes, mapped to what this MVP actually does"
        actions={
          <Select
            width="w-[160px]"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "", label: `All (${FEASIBILITY.length})` },
              ...Object.entries(STATUS_META).map(([k, m]) => ({
                value: k,
                label: `${m.label} (${counts[k] ?? 0})`,
              })),
            ]}
          />
        }
      >
        <Notice tone="info" title="How to read this">
          The white paper's vision is preserved; its unsupported claims are not implemented as if
          they were established. "Infeasible / excluded" means SYNTHBODY deliberately does not do
          it. "Not implemented" means the science exists but the data to parameterise and validate
          it does not — so building it would produce output with no evidential content.
        </Notice>

        <div className="mt-2 space-y-2">
          {rows.map((r) => {
            const m = STATUS_META[r.status];
            return (
              <div key={r.component} className="rounded border border-line bg-void/40 p-2">
                <div className="flex flex-wrap items-start gap-2">
                  <span className="text-xs font-semibold text-ink">{r.component}</span>
                  <Badge tone={m.tone}>{m.label}</Badge>
                </div>
                <div className="mt-1.5 grid grid-cols-1 gap-2 lg:grid-cols-3">
                  <div>
                    <div className="text-[9px] font-semibold uppercase tracking-wider text-ink-ghost">
                      White paper proposes
                    </div>
                    <p className="mt-0.5 text-xs leading-relaxed text-ink-faint">{r.paperClaim}</p>
                  </div>
                  <div>
                    <div className="text-[9px] font-semibold uppercase tracking-wider text-ink-ghost">
                      Implementation basis
                    </div>
                    <p className="mt-0.5 text-xs leading-relaxed text-ink-dim">{r.basis}</p>
                  </div>
                  <div>
                    <div className="text-[9px] font-semibold uppercase tracking-wider text-ink-ghost">
                      Validation status
                    </div>
                    <p className="mt-0.5 text-xs leading-relaxed text-ink-dim">{r.validation}</p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </Panel>

      <div className="mt-2">
        <Panel title="Evidence-origin discipline">
          <Hint>
            Every number in SYNTHBODY carries one of these tags, and they are never upgraded to make
            a model look better supported than it is.
          </Hint>
          <div className="mt-2 space-y-1.5">
            {(
              ["measured", "fitted", "literature_fitted", "derived", "inferred", "illustrative", "user"] as const
            ).map((o) => (
              <div key={o} className="flex items-start gap-2">
                <OriginBadge origin={o} full />
                <span className="text-xs leading-relaxed text-ink-faint">
                  {
                    {
                      measured: "A directly measured or reported population value from a cited primary source.",
                      fitted:
                        "Estimated by SYNTHBODY's own regression against a named observed dataset shipped with the platform, reproducible by running the validation script.",
                      literature_fitted: "A fitted estimate reported by a cited publication, not re-estimated here.",
                      derived: "Computed from other parameters by an explicit, documented equation.",
                      inferred:
                        "Reasoned from related data or a widely quoted value whose primary source SYNTHBODY did not retrieve.",
                      illustrative:
                        "A plausible default chosen to make the software demonstrable. NOT evidence. Any conclusion resting on it is unsupported.",
                      user: "Supplied by the operator at run time.",
                    }[o]
                  }
                </span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
