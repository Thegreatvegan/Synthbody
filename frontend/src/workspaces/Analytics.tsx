/**
 * Simulation Analytics: population variability and parameter sensitivity.
 *
 * Both tools are real computations run by the backend. The population tab runs
 * a Monte Carlo cohort through the ODE solver one subject at a time; the
 * sensitivity tab runs local finite differences, Morris screening or Sobol
 * variance decomposition, each with the model evaluation count shown so the
 * cost is visible.
 */
import { useEffect, useMemo, useState } from "react";
import { Plot, type PlotBand, type PlotRibbon, type PlotSeries } from "../components/charts/Plot";
import {
  Badge,
  Button,
  Cell,
  EmptyState,
  Field,
  Hint,
  IconButton,
  Metric,
  Notice,
  NumberInput,
  Panel,
  Row,
  SectionLabel,
  Select,
  SignedBar,
  Slider,
  Splitter,
  Table,
  Tabs,
  Toggle,
  cx,
} from "../components/ui";
import { downloadText, pct, sig, slug, toCsv } from "../lib/format";
import { useStore } from "../lib/store";

export function Analytics() {
  const [tab, setTab] = useState<"population" | "sensitivity">("population");
  const population = useStore((s) => s.population);
  const sensitivity = useStore((s) => s.sensitivity);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          {
            id: "population",
            label: "Population variability",
            badge: population ? <Badge tone="accent">{population.result.n_subjects_simulated}</Badge> : undefined,
          },
          {
            id: "sensitivity",
            label: "Parameter sensitivity",
            badge: sensitivity ? <Badge tone="accent">{sensitivity.method}</Badge> : undefined,
          },
        ]}
      />
      <div className="flex min-h-0 flex-1">
        {tab === "population" ? <PopulationTab /> : <SensitivityTab />}
      </div>
    </div>
  );
}

// ===========================================================================
// Population
// ===========================================================================
function PopulationTab() {
  const setup = useStore((s) => s.setup);
  const models = useStore((s) => s.models);
  const drugs = useStore((s) => s.drugs);
  const population = useStore((s) => s.population);
  const running = useStore((s) => s.running);
  const runPopulation = useStore((s) => s.runPopulation);
  const spec = models.find((m) => m.model_id === setup.modelId);
  const drug = drugs.find((d) => d.drug_id === setup.drugId);

  const [nSubjects, setNSubjects] = useState(250);
  const [seed, setSeed] = useState(20261012);
  const [includeResidual, setIncludeResidual] = useState(false);
  const [propCv, setPropCv] = useState(15);
  const [addSd, setAddSd] = useState(0.1);
  const [effects, setEffects] = useState<Record<string, number>>({});

  // Seed the random-effect table from the drug library whenever the model or
  // compound changes, so the defaults are the fitted CV% where one exists.
  useEffect(() => {
    const next: Record<string, number> = {};
    const names = new Set((spec?.parameters ?? []).map((p) => p.name));
    for (const re of drug?.population_variability.random_effects ?? []) {
      if (names.has(re.parameter)) next[re.parameter] = re.cv_percent;
    }
    if (Object.keys(next).length === 0 && spec) {
      // Fall back to the first clearance-like and volume-like parameter.
      const cl = spec.parameters.find((p) => ["CL", "Vmax", "CLint_H"].includes(p.name));
      const v = spec.parameters.find((p) => ["V", "V1"].includes(p.name));
      if (cl) next[cl.name] = 30;
      if (v) next[v.name] = 20;
    }
    setEffects(next);
    const r = drug?.population_variability.residual_error;
    if (r) {
      setPropCv(r.proportional_cv_percent);
      setAddSd(r.additive_sd);
    }
  }, [spec, drug]);

  const run = () =>
    void runPopulation({
      nSubjects,
      seed,
      randomEffects: Object.entries(effects)
        .filter(([, cv]) => cv > 0)
        .map(([parameter, cv_percent]) => ({ parameter, cv_percent })),
      includeResidual,
      residual: { proportional_cv_percent: propCv, additive_sd: addSd },
    });

  const activeEffects = Object.values(effects).filter((v) => v > 0).length;

  return (
    <Splitter
      storageKey="analytics-pop"
      initial={0.25}
      min={0.18}
      max={0.4}
      first={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          <Panel title="Cohort definition" className="min-h-0 flex-1" scroll>
            <div className="space-y-2.5">
              <Notice tone="info" compact>
                The cohort inherits the current Studio setup: {spec?.short_name}, {setup.regimen.dose_mg} mg{" "}
                {setup.regimen.route.replace("_", " ")}
                {setup.regimen.n_doses > 1 ? ` ×${setup.regimen.n_doses} q${setup.regimen.interval_h}h` : ""}, {setup.horizonH} h.
              </Notice>

              <Field label="Number of subjects">
                <NumberInput value={nSubjects} min={2} max={5000} step={50} onChange={setNSubjects} />
              </Field>
              <Slider min={10} max={2000} step={10} value={nSubjects} onChange={setNSubjects} />
              <Hint>
                Each subject is a separate ODE solve, so cost grows linearly. 250 subjects is
                usually enough to see the 5th–95th percentile band stabilise.
              </Hint>

              <Field label="Random seed">
                <NumberInput value={seed} min={0} step={1} width="w-[104px]" onChange={setSeed} />
              </Field>
              <Hint>
                The seed is recorded in the provenance, so a cohort can be reproduced exactly.
              </Hint>

              <SectionLabel>Between-subject variability</SectionLabel>
              <Hint>
                Log-normal random effects on structural parameters: P_i = P_typical · exp(η_i).
                Set a CV to zero to remove the effect.
              </Hint>
              <div className="space-y-1.5">
                {(spec?.parameters ?? []).map((p) => {
                  const lib = drug?.population_variability.random_effects.find(
                    (r) => r.parameter === p.name,
                  );
                  const cv = effects[p.name] ?? 0;
                  return (
                    <div key={p.name}>
                      <div className="flex items-center gap-1.5">
                        <span className="min-w-0 flex-1 truncate text-xs text-ink-dim" title={p.description}>
                          {p.name}
                        </span>
                        {lib && (
                          <Badge
                            tone={cv === lib.cv_percent ? "accent" : "neutral"}
                            title={`Library value: ${lib.cv_percent}% (${lib.origin}). ${lib.note}`}
                          >
                            lib {lib.cv_percent}%
                          </Badge>
                        )}
                        <NumberInput
                          value={cv}
                          min={0}
                          max={300}
                          step={1}
                          width="w-[62px]"
                          onChange={(v) => setEffects((e) => ({ ...e, [p.name]: v }))}
                        />
                        <span className="w-4 shrink-0 text-2xs text-ink-ghost">%</span>
                      </div>
                      {lib && lib.cv_percent > 80 && cv > 0 && (
                        <div className="text-[9px] leading-snug text-warn">{lib.note}</div>
                      )}
                    </div>
                  );
                })}
              </div>

              <SectionLabel>Residual error</SectionLabel>
              <Toggle
                checked={includeResidual}
                onChange={setIncludeResidual}
                label="Add measurement error to the bands"
              />
              <Field label="Proportional CV" unit="%">
                <NumberInput value={propCv} min={0} max={200} step={1} width="w-[62px]" onChange={setPropCv} />
              </Field>
              <Field label="Additive SD" unit="mg/L">
                <NumberInput value={addSd} min={0} step={0.01} width="w-[62px]" onChange={setAddSd} />
              </Field>
              <Hint>
                Residual error widens what you would <em>observe</em>, not what the underlying
                exposure <em>is</em>. Turn it on when comparing against raw observed scatter; leave
                it off when describing exposure variability.
              </Hint>

              <Button
                variant="primary"
                full
                size="md"
                loading={running === "population"}
                disabled={activeEffects === 0}
                onClick={run}
                title={activeEffects === 0 ? "Set at least one non-zero CV%" : undefined}
              >
                Simulate {nSubjects} subjects
              </Button>
              {activeEffects === 0 && (
                <Notice tone="warn" compact>
                  With no non-zero random effect every subject would be identical and the
                  percentiles would be meaningless. The engine rejects that.
                </Notice>
              )}
            </div>
          </Panel>
        </div>
      }
      second={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          {!population ? (
            <Panel title="Population simulation" className="min-h-0 flex-1">
              <EmptyState title="No cohort simulated yet">
                Define the between-subject variability on the left and run. SYNTHBODY will solve the
                ODE system once per virtual subject and report the percentile envelope of the
                resulting exposure, plus the distribution of Cmax, Tmax, AUC and half-life across
                the cohort.
              </EmptyState>
            </Panel>
          ) : (
            <PopulationResults />
          )}
        </div>
      }
    />
  );
}

function PopulationResults() {
  const population = useStore((s) => s.population)!;
  const setup = useStore((s) => s.setup);
  const patchSetup = useStore((s) => s.patchSetup);
  const r = population.result;
  const [showObs, setShowObs] = useState(false);

  const pctSrc = showObs && r.observation_percentiles ? r.observation_percentiles : r.structural_percentiles;

  const ribbons: PlotRibbon[] = useMemo(() => {
    const out: PlotRibbon[] = [];
    if (pctSrc["p5"] && pctSrc["p95"]) {
      out.push({
        id: "p5-95",
        x: r.time_h,
        lower: pctSrc["p5"]!,
        upper: pctSrc["p95"]!,
        colour: "#3fd3bd",
        opacity: 0.12,
        label: "5th–95th percentile",
      });
    }
    if (pctSrc["p25"] && pctSrc["p75"]) {
      out.push({
        id: "p25-75",
        x: r.time_h,
        lower: pctSrc["p25"]!,
        upper: pctSrc["p75"]!,
        colour: "#3fd3bd",
        opacity: 0.22,
        label: "25th–75th percentile",
      });
    }
    return out;
  }, [pctSrc, r.time_h]);

  const series: PlotSeries[] = [
    {
      id: "median",
      label: "Median subject",
      x: r.time_h,
      y: pctSrc["p50"] ?? [],
      colour: "#3fd3bd",
      width: 1.9,
    },
    {
      id: "typical",
      label: "Typical-value profile",
      x: r.time_h,
      y: r.typical_value_profile,
      colour: "#e0a34a",
      width: 1.4,
      dash: "5 3",
    },
  ];

  const bands: PlotBand[] =
    setup.bandLow != null && setup.bandHigh != null && setup.bandHigh > setup.bandLow
      ? [
          {
            id: "ref",
            axis: "y",
            from: setup.bandLow,
            to: setup.bandHigh,
            colour: "#e0a34a",
            label: `Reference band ${setup.bandLow}–${setup.bandHigh}`,
            opacity: 0.08,
          },
        ]
      : [];

  const metricOrder = ["cmax", "tmax_h", "cmin", "auc_0_last", "terminal_half_life_h"];
  const ta = population.target_attainment;

  return (
    <>
      <Panel
        title={`Cohort exposure envelope — ${r.n_subjects_simulated} virtual subjects`}
        subtitle={`seed ${r.seed} · solved in ${r.wall_time_s.toFixed(2)} s`}
        className="min-h-[320px] flex-1"
        actions={
          <>
            {r.observation_percentiles && (
              <Toggle
                checked={showObs}
                onChange={setShowObs}
                label={<span className="text-2xs">+ residual error</span>}
              />
            )}
            <Toggle
              checked={setup.yLogScale}
              onChange={(v) => patchSetup({ yLogScale: v })}
              label={<span className="text-2xs">log y</span>}
            />
            <IconButton
              title="Export percentile envelope as CSV"
              onClick={() => {
                const keys = Object.keys(pctSrc);
                downloadText(
                  `${slug(population.label)}-envelope.csv`,
                  toCsv(
                    ["time_h", "typical", ...keys],
                    r.time_h.map((t, i) => [
                      t,
                      r.typical_value_profile[i] ?? "",
                      ...keys.map((k) => pctSrc[k]?.[i] ?? ""),
                    ]),
                  ),
                  "text/csv",
                );
              }}
            >
              ⤓
            </IconButton>
          </>
        }
      >
        <div className="group/plot">
          <Plot
            series={series}
            ribbons={ribbons}
            bands={bands}
            xLabel="Time"
            xUnit="h"
            yLabel="Plasma concentration"
            yUnit="mg/L"
            yScale={setup.yLogScale ? "log" : "linear"}
            height={320}
            onExportName={slug(population.label)}
          />
        </div>
        <Notice tone="info" compact>
          {r.interpretation}
        </Notice>
        {r.n_failures > 0 && (
          <Notice tone="warn" compact title={`${r.n_failures} subject(s) failed to simulate`}>
            {r.failures.slice(0, 3).map((f) => f.error).join(" · ")}
          </Notice>
        )}
        {r.n_parameter_draws_truncated > 0 && (
          <Notice tone="warn" compact>
            {r.n_parameter_draws_truncated} parameter draw(s) hit a bound and were truncated, which
            biases the sampled distribution.
          </Notice>
        )}
      </Panel>

      <div className="grid min-h-0 shrink-0 grid-cols-1 gap-1 lg:grid-cols-2" style={{ maxHeight: "46%" }}>
        <Panel title="Exposure distribution across the cohort" scroll>
          <Table
            compact
            headers={[
              "Metric",
              { label: "Median", align: "right" },
              { label: "Geo. mean", align: "right" },
              { label: "CV%", align: "right" },
              { label: "5th", align: "right" },
              { label: "95th", align: "right" },
              { label: "Spread", align: "right", hint: "95th / 5th percentile ratio" },
            ]}
          >
            {metricOrder
              .filter((k) => population.exposure_distribution[k])
              .map((k) => {
                const m = population.exposure_distribution[k]!;
                const spread = m.p5 > 0 ? m.p95 / m.p5 : null;
                return (
                  <Row key={k}>
                    <Cell>
                      <span className="text-ink">{k.replace(/_/g, " ")}</span>
                    </Cell>
                    <Cell align="right" mono>
                      {sig(m.median, 4)}
                    </Cell>
                    <Cell align="right" mono dim>
                      {sig(m.geometric_mean, 4)}
                    </Cell>
                    <Cell align="right" mono>
                      {m.cv_percent.toFixed(1)}
                    </Cell>
                    <Cell align="right" mono dim>
                      {sig(m.p5, 3)}
                    </Cell>
                    <Cell align="right" mono dim>
                      {sig(m.p95, 3)}
                    </Cell>
                    <Cell align="right" mono className={spread && spread > 3 ? "text-warn" : ""}>
                      {spread ? `${spread.toFixed(1)}×` : "—"}
                    </Cell>
                  </Row>
                );
              })}
          </Table>

          <SectionLabel>Random effects applied</SectionLabel>
          <Table compact headers={["Parameter", { label: "CV%", align: "right" }, { label: "σ (log scale)", align: "right" }]}>
            {r.random_effects.map((re) => (
              <Row key={re.parameter}>
                <Cell mono>{re.parameter}</Cell>
                <Cell align="right" mono>
                  {re.cv_percent.toFixed(1)}
                </Cell>
                <Cell align="right" mono dim>
                  {re.sigma.toFixed(4)}
                </Cell>
              </Row>
            ))}
          </Table>
          <Notice tone="warn" compact>
            Where these CV% values were estimated by SYNTHBODY's two-stage fit they are an upper
            bound on true between-subject variability: two-stage estimation absorbs each
            individual's estimation error into the variance.
          </Notice>
        </Panel>

        <Panel title="Cohort distributions" scroll>
          {population.exposure_distribution["cmax"] && r.subject_metrics && (
            <Histogram
              values={r.subject_metrics.map((m) => m["cmax"]!).filter(Number.isFinite)}
              label="Cmax"
              unit="mg/L"
              bandLow={ta ? (ta["band_low"] as number) : undefined}
              bandHigh={ta ? (ta["band_high"] as number) : undefined}
            />
          )}
          {r.subject_metrics && (
            <div className="mt-2">
              <Histogram
                values={r.subject_metrics.map((m) => m["auc_0_last"]!).filter(Number.isFinite)}
                label="AUC"
                unit="mg·h/L"
              />
            </div>
          )}
          {ta && ta["n"] ? (
            <div className="mt-2">
              <SectionLabel>Cohort position relative to the reference band</SectionLabel>
              <Metric label="Below band" value={pct(ta["fraction_below_band"] as number)} />
              <Metric label="Within band" value={pct(ta["fraction_within_band"] as number)} tone="ok" />
              <Metric
                label="Above band"
                value={pct(ta["fraction_above_band"] as number)}
                tone={(ta["fraction_above_band"] as number) > 0 ? "warn" : undefined}
              />
              <Notice tone="warn" compact>
                {String(ta["note"] ?? "")}
              </Notice>
            </div>
          ) : null}
        </Panel>
      </div>
    </>
  );
}

/** Simple histogram drawn from the per-subject metric values the backend returned. */
function Histogram({
  values,
  label,
  unit,
  bandLow,
  bandHigh,
}: {
  values: number[];
  label: string;
  unit: string;
  bandLow?: number;
  bandHigh?: number;
}) {
  const { bins, lo, hi, max } = useMemo(() => {
    if (values.length === 0) return { bins: [] as number[], lo: 0, hi: 1, max: 1 };
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    // Freedman–Diaconis would be better but needs a quantile; Sturges is fine here.
    const n = Math.max(8, Math.min(28, Math.ceil(Math.log2(values.length) + 1) * 2));
    const bins = new Array(n).fill(0);
    const w = (hi - lo) / n || 1;
    for (const v of values) {
      const i = Math.min(n - 1, Math.max(0, Math.floor((v - lo) / w)));
      bins[i]! += 1;
    }
    return { bins, lo, hi, max: Math.max(...bins) };
  }, [values]);

  if (values.length === 0) return null;
  const w = (hi - lo) / bins.length || 1;

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-2xs font-semibold uppercase tracking-wider text-ink-faint">
          {label} distribution ({values.length} subjects)
        </span>
        <span className="font-mono text-2xs text-ink-ghost">
          {sig(lo, 3)} – {sig(hi, 3)} {unit}
        </span>
      </div>
      <div className="flex h-20 items-end gap-px">
        {bins.map((c, i) => {
          const centre = lo + (i + 0.5) * w;
          const inBand = bandLow != null && bandHigh != null && centre >= bandLow && centre <= bandHigh;
          const above = bandHigh != null && centre > bandHigh;
          return (
            <div
              key={i}
              className={cx(
                "flex-1 rounded-t-sm transition-colors duration-120",
                above ? "bg-danger/70" : inBand ? "bg-ok/70" : "bg-accent/55",
              )}
              style={{ height: `${(c / max) * 100}%` }}
              title={`${sig(centre, 4)} ${unit}: ${c} subject${c === 1 ? "" : "s"}`}
            />
          );
        })}
      </div>
      {bandLow != null && bandHigh != null && (
        <div className="mt-1 flex gap-3 text-[9px] text-ink-ghost">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-accent/55" /> below band
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-ok/70" /> within band
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-danger/70" /> above band
          </span>
        </div>
      )}
    </div>
  );
}

// ===========================================================================
// Sensitivity
// ===========================================================================
function SensitivityTab() {
  const setup = useStore((s) => s.setup);
  const models = useStore((s) => s.models);
  const sensitivity = useStore((s) => s.sensitivity);
  const running = useStore((s) => s.running);
  const runSensitivity = useStore((s) => s.runSensitivity);
  const spec = models.find((m) => m.model_id === setup.modelId);

  const [method, setMethod] = useState<"local" | "morris" | "sobol">("local");
  const [metric, setMetric] = useState<"auc_0_last" | "cmax" | "tmax" | "cmin" | "auc_0_inf" | "t_half">(
    "auc_0_last",
  );
  const [range, setRange] = useState(0.5);
  const [trajectories, setTrajectories] = useState(48);
  const [baseSamples, setBaseSamples] = useState(256);
  const [targets, setTargets] = useState<string[]>([]);

  useEffect(() => {
    // Default to every parameter that can plausibly move exposure.
    const names = (spec?.parameters ?? [])
      .filter((p) => !["F", "t_lag", "BW"].includes(p.name))
      .map((p) => p.name);
    setTargets(names.slice(0, 8));
  }, [spec]);

  const estCost =
    method === "local"
      ? targets.length * 4 + 1
      : method === "morris"
        ? trajectories * (targets.length + 1)
        : baseSamples * (targets.length + 2);

  return (
    <Splitter
      storageKey="analytics-sa"
      initial={0.25}
      min={0.18}
      max={0.4}
      first={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          <Panel title="Sensitivity configuration" className="min-h-0 flex-1" scroll>
            <div className="space-y-2.5">
              <Field label="Method" inline={false}>
                <Select
                  value={method}
                  onChange={setMethod}
                  options={[
                    { value: "local", label: "Local — normalised finite differences" },
                    { value: "morris", label: "Morris — elementary effects screening" },
                    { value: "sobol", label: "Sobol — variance decomposition" },
                  ]}
                />
              </Field>
              <Notice tone="info" compact>
                {method === "local" &&
                  "Exact at the nominal parameter set and very cheap, but blind to interactions and only valid locally. The engine also halves the step and reports whether the coefficient changed, so you can see if the derivative is converged."}
                {method === "morris" &&
                  "Ranks influence across the whole input space at modest cost. Use it to decide which parameters deserve a Sobol run. It does not quantify variance shares."}
                {method === "sobol" &&
                  "Attributes output variance to each parameter alone (S1) and including all its interactions (ST). The gap between them is the interaction strength. Cost grows with both sample size and parameter count."}
              </Notice>

              <Field label="Output metric" inline={false}>
                <Select
                  value={metric}
                  onChange={setMetric}
                  options={[
                    { value: "auc_0_last", label: "AUC" },
                    { value: "cmax", label: "Cmax" },
                    { value: "cmin", label: "Cmin" },
                    { value: "tmax", label: "Tmax" },
                    { value: "auc_0_inf", label: "AUC(0–∞)" },
                    { value: "t_half", label: "Terminal half-life" },
                  ]}
                />
              </Field>

              <Field label="Parameter range" unit="± fraction">
                <NumberInput value={range} min={0.01} max={5} step={0.05} onChange={setRange} />
              </Field>
              <Slider min={0.05} max={2} step={0.05} value={range} onChange={setRange} />
              <Hint>
                Each parameter is varied over nominal × (1 ± {range.toFixed(2)}), clipped to the
                model's declared bounds.
              </Hint>

              {method === "morris" && (
                <Field label="Trajectories">
                  <NumberInput value={trajectories} min={4} max={500} step={4} onChange={setTrajectories} />
                </Field>
              )}
              {method === "sobol" && (
                <Field label="Base samples" hint="Rounded up to a power of two.">
                  <NumberInput value={baseSamples} min={16} max={4096} step={16} onChange={setBaseSamples} />
                </Field>
              )}

              <SectionLabel>Parameters to vary</SectionLabel>
              <div className="space-y-0.5">
                {(spec?.parameters ?? []).map((p) => (
                  <label
                    key={p.name}
                    className="flex cursor-pointer items-center gap-1.5 rounded-sm px-1 py-0.5 text-xs text-ink-dim hover:bg-raised"
                    title={p.description}
                  >
                    <input
                      type="checkbox"
                      checked={targets.includes(p.name)}
                      onChange={(e) =>
                        setTargets((t) => (e.target.checked ? [...t, p.name] : t.filter((x) => x !== p.name)))
                      }
                      className="accent-accent"
                    />
                    <span className="flex-1 truncate font-mono">{p.name}</span>
                    <span className="text-2xs text-ink-ghost">{p.unit}</span>
                  </label>
                ))}
              </div>

              <Notice tone={estCost > 20000 ? "warn" : "neutral"} compact>
                Estimated cost: about {estCost.toLocaleString()} ODE solves.
                {estCost > 20000 && " That will take a while — reduce the sample size or parameter count."}
              </Notice>

              <Button
                variant="primary"
                full
                size="md"
                loading={running === "sensitivity"}
                disabled={targets.length === 0}
                onClick={() =>
                  void runSensitivity({
                    method,
                    metric,
                    targets,
                    relativeRange: range,
                    morrisTrajectories: trajectories,
                    sobolBaseSamples: baseSamples,
                  })
                }
              >
                Run {method} analysis
              </Button>
            </div>
          </Panel>
        </div>
      }
      second={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          {!sensitivity ? (
            <Panel title="Sensitivity analysis" className="min-h-0 flex-1">
              <EmptyState title="No analysis run yet">
                Pick a method and an output metric, choose which parameters to vary, and run. Each
                evaluation is a complete ODE solve followed by non-compartmental analysis, so the
                result reflects the actual model rather than a linearised approximation.
              </EmptyState>
            </Panel>
          ) : (
            <SensitivityResults />
          )}
        </div>
      }
    />
  );
}

function SensitivityResults() {
  const s = useStore((st) => st.sensitivity)!;
  const rows = s.analysis.results;
  const method = s.analysis.method;

  const key: "normalised_sensitivity" | "mu_star" | "ST" =
    method.startsWith("local") ? "normalised_sensitivity" : method.startsWith("morris") ? "mu_star" : "ST";
  const maxAbs = Math.max(...rows.map((r) => Math.abs((r[key] as number) ?? 0)), 1e-12);

  return (
    <>
      <Panel
        title={`${method.replace(/_/g, " ")} — sensitivity of ${s.metric.replace(/_/g, " ")}`}
        subtitle={`${s.n_model_evaluations.toLocaleString()} model evaluations in ${s.wall_time_s.toFixed(2)} s`}
        className="min-h-0 flex-1"
        scroll
        actions={
          <IconButton
            title="Export as CSV"
            onClick={() => {
              const headers = Object.keys(rows[0] ?? {});
              downloadText(
                `${slug(s.label)}-sensitivity.csv`,
                toCsv(
                  headers,
                  rows.map((r) => {
                    const rec = r as unknown as Record<string, unknown>;
                    return headers.map((h) => {
                      const v = rec[h];
                      return v == null ? "" : typeof v === "number" ? v : String(v);
                    });
                  }),
                ),
                "text/csv",
              );
            }}
          >
            ⤓
          </IconButton>
        }
      >
        {/* Tornado plot */}
        <div className="space-y-1">
          {rows.map((r) => {
            const v = (r[key] as number) ?? 0;
            return (
              <div key={r.parameter} className="flex items-center gap-2">
                <span className="w-20 shrink-0 truncate font-mono text-xs text-ink-dim" title={r.description}>
                  {r.parameter}
                </span>
                <SignedBar value={v} max={maxAbs} width={200} />
                <span className="w-20 shrink-0 text-right font-mono text-xs text-ink tnum">
                  {sig(v, 4)}
                </span>
                {r.interaction_strength != null && (
                  <span
                    className="w-24 shrink-0 text-right font-mono text-2xs text-ink-ghost"
                    title="ST − S1: variance explained only through interactions"
                  >
                    int {r.interaction_strength.toFixed(3)}
                  </span>
                )}
                {r.sigma != null && r.mu_star != null && (
                  <span
                    className="w-20 shrink-0 text-right font-mono text-2xs text-ink-ghost"
                    title="σ/μ* — a high ratio means the effect depends on the other parameters"
                  >
                    σ/μ* {(r.sigma / Math.max(r.mu_star, 1e-12)).toFixed(2)}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        <div className="mt-3">
          <Table
            headers={
              method.startsWith("local")
                ? [
                    "Parameter",
                    { label: "Nominal", align: "right" },
                    "Unit",
                    { label: "Normalised S", align: "right", hint: "Percent change in output per percent change in the parameter." },
                    { label: "Step", align: "right" },
                    { label: "Step-halving Δ", align: "right", hint: "Relative change when the finite-difference step is halved. Large values mean the derivative is not converged." },
                    "Note",
                  ]
                : method.startsWith("morris")
                  ? [
                      "Parameter",
                      { label: "μ*", align: "right", hint: "Mean absolute elementary effect: overall influence." },
                      { label: "μ", align: "right", hint: "Mean signed elementary effect." },
                      { label: "σ", align: "right", hint: "Spread of elementary effects: interaction or non-linearity." },
                      { label: "μ* 95% CI", align: "right" },
                      "Unit",
                    ]
                  : [
                      "Parameter",
                      { label: "S1", align: "right", hint: "First-order index: variance explained by this parameter alone." },
                      { label: "S1 CI", align: "right" },
                      { label: "ST", align: "right", hint: "Total index: includes all interactions involving this parameter." },
                      { label: "ST CI", align: "right" },
                      { label: "Interaction", align: "right", hint: "ST − S1" },
                      "Unit",
                    ]
            }
          >
            {rows.map((r) => (
              <Row key={r.parameter}>
                <Cell mono>
                  <span className="text-ink">{r.parameter}</span>
                </Cell>
                {method.startsWith("local") ? (
                  <>
                    <Cell align="right" mono>
                      {sig(r.nominal, 4)}
                    </Cell>
                    <Cell dim mono>
                      {r.unit || "—"}
                    </Cell>
                    <Cell align="right" mono>
                      {r.normalised_sensitivity != null ? sig(r.normalised_sensitivity, 4) : "—"}
                    </Cell>
                    <Cell align="right" mono dim>
                      {r.step_used_relative != null ? r.step_used_relative.toExponential(1) : "—"}
                    </Cell>
                    <Cell
                      align="right"
                      mono
                      className={
                        (r.step_halving_relative_change ?? 0) > 0.05 ? "text-warn" : "text-ink-faint"
                      }
                    >
                      {r.step_halving_relative_change != null
                        ? pct(r.step_halving_relative_change, 2)
                        : "—"}
                    </Cell>
                    <Cell dim>{r.note || "—"}</Cell>
                  </>
                ) : method.startsWith("morris") ? (
                  <>
                    <Cell align="right" mono>
                      {sig(r.mu_star, 4)}
                    </Cell>
                    <Cell align="right" mono dim>
                      {sig(r.mu, 4)}
                    </Cell>
                    <Cell align="right" mono dim>
                      {sig(r.sigma, 4)}
                    </Cell>
                    <Cell align="right" mono dim>
                      ±{sig(r.mu_star_conf, 3)}
                    </Cell>
                    <Cell dim mono>
                      {r.unit || "—"}
                    </Cell>
                  </>
                ) : (
                  <>
                    <Cell align="right" mono>
                      {sig(r.S1, 4)}
                    </Cell>
                    <Cell align="right" mono dim>
                      ±{sig(r.S1_conf, 3)}
                    </Cell>
                    <Cell align="right" mono>
                      {sig(r.ST, 4)}
                    </Cell>
                    <Cell align="right" mono dim>
                      ±{sig(r.ST_conf, 3)}
                    </Cell>
                    <Cell align="right" mono className={(r.interaction_strength ?? 0) > 0.1 ? "text-warn" : ""}>
                      {sig(r.interaction_strength, 3)}
                    </Cell>
                    <Cell dim mono>
                      {r.unit || "—"}
                    </Cell>
                  </>
                )}
              </Row>
            ))}
          </Table>
        </div>

        <div className="mt-2 space-y-1.5">
          <Notice tone="info" compact title="How to read this">
            {s.analysis.interpretation}
          </Notice>
          {s.analysis.sum_first_order != null && (
            <Notice
              tone={s.analysis.sum_first_order < 0.8 ? "warn" : "ok"}
              compact
            >
              First-order indices sum to {s.analysis.sum_first_order.toFixed(3)}.
              {s.analysis.sum_first_order < 0.8
                ? " Well below 1, so interactions between parameters dominate this output and single-parameter reasoning will mislead."
                : " Close to 1, so the output is close to additive in these parameters."}
            </Notice>
          )}
          {s.notes.map((n, i) => (
            <Notice key={i} tone="warn" compact>
              {n}
            </Notice>
          ))}
          <Notice tone="neutral" compact>
            Nominal parameter set:{" "}
            <span className="font-mono">
              {Object.entries(s.nominal_parameters)
                .map(([k, v]) => `${k}=${sig(v, 4)}`)
                .join("  ")}
            </span>
          </Notice>
        </div>
      </Panel>
    </>
  );
}
