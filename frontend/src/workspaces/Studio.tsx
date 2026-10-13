/**
 * SYNTHBODY Studio — the central simulation environment.
 *
 * Three columns: setup on the left, plots and exposure metrics in the middle,
 * provenance inspector on the right. A scenario bench along the bottom of the
 * setup column captures configurations for comparison.
 *
 * Every number in this workspace comes from the engine. The parameter controls
 * do not pre-compute anything client-side; moving a slider changes the request,
 * and the curve only updates when the solver has run.
 */
import { useEffect, useMemo, useState } from "react";
import { Plot, type PlotBand, type PlotSeries } from "../components/charts/Plot";
import { ProvenanceStrip } from "../components/Shell";
import {
  Badge,
  Button,
  Cell,
  Checkbox,
  Collapsible,
  EmptyState,
  Field,
  Hint,
  IconButton,
  Metric,
  Modal,
  Notice,
  NumberInput,
  OriginBadge,
  Panel,
  Row,
  SectionLabel,
  Select,
  Slider,
  Splitter,
  Table,
  TextInput,
  Toggle,
  ValidationBadge,
  cx,
} from "../components/ui";
import {
  ORIGIN_META,
  VALIDATION_META,
  downloadText,
  prettyUnit,
  pct,
  sci,
  sig,
  seriesColour,
  slug,
  toCsv,
} from "../lib/format";
import { effectiveParameters, parameterOriginFor, useStore } from "../lib/store";
import type { Route, SolverMethod } from "../lib/types";

export function Studio() {
  const inspectorOpen = useStore((s) => s.inspectorOpen);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Splitter
        storageKey="studio-main"
        initial={0.24}
        min={0.17}
        max={0.4}
        first={<SetupColumn />}
        second={
          inspectorOpen ? (
            <Splitter
              storageKey="studio-right"
              initial={0.7}
              min={0.45}
              max={0.85}
              first={<ResultsColumn />}
              second={<InspectorColumn />}
            />
          ) : (
            <ResultsColumn />
          )
        }
      />
    </div>
  );
}

// ===========================================================================
// Setup column
// ===========================================================================
function SetupColumn() {
  const setup = useStore((s) => s.setup);
  const models = useStore((s) => s.models);
  const drugs = useStore((s) => s.drugs);
  const patients = useStore((s) => s.patients);
  const experiments = useStore((s) => s.experiments);
  const activeExperimentId = useStore((s) => s.activeExperimentId);
  const setActiveExperiment = useStore((s) => s.setActiveExperiment);
  const patchSetup = useStore((s) => s.patchSetup);
  const selectModel = useStore((s) => s.selectModel);
  const selectDrug = useStore((s) => s.selectDrug);
  const setParameter = useStore((s) => s.setParameter);
  const resetParams = useStore((s) => s.resetParametersToDrugDefaults);
  const run = useStore((s) => s.run);
  const running = useStore((s) => s.running);
  const snapshot = useStore((s) => s.snapshotScenario);

  const spec = models.find((m) => m.model_id === setup.modelId) ?? null;
  const drug = drugs.find((d) => d.drug_id === setup.drugId) ?? null;
  const patient = patients.find((p) => p.id === setup.patientId) ?? null;
  const weight = patient?.weight_kg ?? 70;

  const effective = useMemo(
    () => effectiveParameters(spec, drug, setup.parameters, weight),
    [spec, drug, setup.parameters, weight],
  );

  const availableModels = drug
    ? models.filter((m) => drug.available_model_ids.includes(m.model_id))
    : models;

  const groups = useMemo(() => {
    const g: Record<string, typeof spec extends null ? never : NonNullable<typeof spec>["parameters"]> = {};
    for (const p of spec?.parameters ?? []) (g[p.group] ??= []).push(p);
    return g;
  }, [spec]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
      <Panel
        title="Experiment setup"
        actions={
          <Badge tone={running === "simulate" ? "accent" : "neutral"} mono>
            {running === "simulate" ? "solving" : "ready"}
          </Badge>
        }
        className="shrink-0"
      >
        <div className="space-y-2">
          <Field label="Run label" inline={false}>
            <TextInput value={setup.label} onChange={(v) => patchSetup({ label: v })} />
          </Field>
          <Field label="Save into experiment" inline={false}>
            <Select
              value={String(activeExperimentId ?? "")}
              onChange={(v) => setActiveExperiment(v ? Number(v) : null)}
              options={[
                { value: "", label: "— not filed —" },
                ...experiments.map((e) => ({ value: String(e.id), label: `${e.name} (${e.n_simulations})` })),
              ]}
            />
          </Field>
        </div>
      </Panel>

      <div className="min-h-0 flex-1 overflow-auto rounded border border-line bg-surface">
        {/* ---- compound ---- */}
        <Collapsible title="Compound" defaultOpen badge={drug && <ValidationBadge status={drug.validation_status} />}>
          <div className="space-y-2">
            <Select
              value={setup.drugId ?? ""}
              onChange={(v) => selectDrug(v || null)}
              options={[
                { value: "", label: "— no compound (raw model) —" },
                ...drugs.map((d) => ({
                  value: d.drug_id,
                  label: d.is_synthetic_demonstration ? `${d.name} (synthetic)` : d.name,
                })),
              ]}
            />
            {drug?.is_synthetic_demonstration && (
              <Notice tone="danger" compact title="Synthetic demonstration compound">
                Every parameter for this compound is invented. It exists to exercise the non-linear
                solver. No result from it means anything pharmacologically.
              </Notice>
            )}
            {drug && !drug.is_synthetic_demonstration && (
              <Hint>{drug.why_this_drug}</Hint>
            )}
          </div>
        </Collapsible>

        {/* ---- model ---- */}
        <Collapsible title="Model structure" defaultOpen badge={spec && <ValidationBadge status={spec.validation_status} />}>
          <div className="space-y-2">
            <Select
              value={setup.modelId}
              onChange={selectModel}
              options={availableModels.map((m) => ({ value: m.model_id, label: m.name }))}
            />
            {spec && (
              <>
                <Hint>{spec.description}</Hint>
                <Notice
                  compact
                  tone={
                    spec.validation_status === "independently_validated"
                      ? "ok"
                      : spec.validation_status === "research_only" ||
                          spec.validation_status === "not_validated"
                        ? "warn"
                        : "info"
                  }
                  title={VALIDATION_META[spec.validation_status].label}
                >
                  {spec.validation_summary}
                </Notice>
              </>
            )}
          </div>
        </Collapsible>

        {/* ---- virtual subject ---- */}
        <Collapsible title="Virtual subject" defaultOpen>
          <div className="space-y-2">
            <Select
              value={String(setup.patientId ?? "")}
              onChange={(v) => patchSetup({ patientId: v ? Number(v) : null })}
              options={[
                { value: "", label: "— reference adult, 70 kg —" },
                ...patients.map((p) => ({
                  value: String(p.id),
                  label: `${p.label} · ${p.weight_kg} kg · ${p.age_years} y`,
                })),
              ]}
            />
            <Toggle
              checked={setup.applyCovariates}
              onChange={(v) => patchSetup({ applyCovariates: v })}
              label="Apply covariate adjustments"
              disabled={!setup.patientId}
            />
            {patient && (
              <div className="rounded border border-line bg-void/50 px-2 py-1.5">
                <div className="mb-1 flex items-center gap-1.5">
                  <Badge tone="violet">Hypothetical subject</Badge>
                  <span className="text-2xs text-ink-ghost">not a patient record</span>
                </div>
                <Metric
                  label="Cockcroft–Gault CrCl"
                  value={patient.derived["creatinine_clearance_cockcroft_gault_mL_min"] as number}
                  unit="mL/min"
                  digits={3}
                />
                <Metric label="BSA (Du Bois)" value={patient.derived["bsa_m2_du_bois"] as number} unit="m2" digits={3} />
                <Metric label="BMI" value={patient.derived["bmi_kg_m2"] as number} digits={3} />
              </div>
            )}
          </div>
        </Collapsible>

        {/* ---- dosing ---- */}
        <Collapsible title="Dosing regimen" defaultOpen>
          <div className="space-y-2">
            <Field label="Route">
              <Select<Route>
                width="w-[118px]"
                value={setup.regimen.route}
                onChange={(route) =>
                  patchSetup({
                    regimen: {
                      ...setup.regimen,
                      route,
                      infusion_duration_h:
                        route === "iv_infusion" ? Math.max(setup.regimen.infusion_duration_h, 1) : 0,
                    },
                  })
                }
                options={(spec?.routes ?? ["oral"]).map((r) => ({
                  value: r,
                  label: r === "iv_bolus" ? "IV bolus" : r === "iv_infusion" ? "IV infusion" : "Oral",
                }))}
              />
            </Field>
            <Field label="Dose per administration" unit="mg">
              <NumberInput
                value={setup.regimen.dose_mg}
                min={0.001}
                step={25}
                onChange={(dose_mg) => patchSetup({ regimen: { ...setup.regimen, dose_mg } })}
              />
            </Field>
            <Slider
              min={0}
              max={Math.max(1200, setup.regimen.dose_mg * 1.5)}
              step={5}
              value={setup.regimen.dose_mg}
              onChange={(dose_mg) => patchSetup({ regimen: { ...setup.regimen, dose_mg } })}
            />
            <Field label="Number of doses">
              <NumberInput
                value={setup.regimen.n_doses}
                min={1}
                max={2000}
                step={1}
                width="w-[64px]"
                onChange={(n_doses) => patchSetup({ regimen: { ...setup.regimen, n_doses } })}
              />
            </Field>
            {setup.regimen.n_doses > 1 && (
              <Field label="Dosing interval" unit="h">
                <NumberInput
                  value={setup.regimen.interval_h}
                  min={0.1}
                  step={1}
                  width="w-[64px]"
                  onChange={(interval_h) => patchSetup({ regimen: { ...setup.regimen, interval_h } })}
                />
              </Field>
            )}
            {setup.regimen.route === "iv_infusion" && (
              <Field label="Infusion duration" unit="h">
                <NumberInput
                  value={setup.regimen.infusion_duration_h}
                  min={0.01}
                  step={0.25}
                  width="w-[64px]"
                  onChange={(infusion_duration_h) =>
                    patchSetup({ regimen: { ...setup.regimen, infusion_duration_h } })
                  }
                />
              </Field>
            )}
            <Field label="Simulation horizon" unit="h">
              <NumberInput
                value={setup.horizonH}
                min={0.1}
                step={6}
                width="w-[72px]"
                onChange={(horizonH) => patchSetup({ horizonH })}
              />
            </Field>
            <DosingAdvice />
          </div>
        </Collapsible>

        {/* ---- parameters ---- */}
        <Collapsible
          title="Model parameters"
          defaultOpen
          badge={
            Object.keys(setup.parameters).length > 0 ? (
              <Badge tone="accent">{Object.keys(setup.parameters).length} overridden</Badge>
            ) : undefined
          }
        >
          <div className="space-y-1">
            {Object.keys(setup.parameters).length > 0 && (
              <Button size="xs" variant="subtle" onClick={resetParams} full>
                Reset to library defaults
              </Button>
            )}
            {Object.entries(groups).map(([group, params]) => (
              <div key={group}>
                <SectionLabel>{group}</SectionLabel>
                <div className="space-y-1.5">
                  {params.map((p) => {
                    const value = effective[p.name] ?? p.default;
                    const { origin, entry } = parameterOriginFor(spec, drug, setup.parameters, p.name);
                    const overridden = p.name in setup.parameters;
                    return (
                      <div key={p.name}>
                        <div className="flex items-center gap-1.5">
                          <span
                            className="min-w-0 flex-1 truncate text-xs text-ink-dim"
                            title={`${p.description}${entry?.caveat ? `\n\nCAVEAT: ${entry.caveat}` : ""}${
                              entry?.corroboration ? `\n\nCORROBORATION: ${entry.corroboration}` : ""
                            }`}
                          >
                            {p.label}
                          </span>
                          <OriginBadge origin={origin} />
                          {overridden && (
                            <IconButton
                              title="Revert this parameter to the library default"
                              onClick={() => {
                                const next = { ...setup.parameters };
                                delete next[p.name];
                                patchSetup({ parameters: next });
                              }}
                            >
                              ↺
                            </IconButton>
                          )}
                          <NumberInput
                            value={Number(value.toPrecision(6))}
                            min={p.minimum}
                            max={p.maximum}
                            step={p.step ?? undefined}
                            width="w-[78px]"
                            onChange={(v) => setParameter(p.name, v)}
                          />
                          <span className="w-10 shrink-0 font-mono text-2xs text-ink-ghost">
                            {prettyUnit(p.unit)}
                          </span>
                        </div>
                        <Slider
                          min={p.minimum}
                          max={Math.min(p.maximum, Math.max(value * 3, p.minimum + 1e-9))}
                          step={p.step ?? undefined}
                          value={value}
                          onChange={(v) => setParameter(p.name, v)}
                        />
                        {entry?.caveat && (
                          <div className="mt-0.5 text-[9px] leading-snug text-warn">{entry.caveat}</div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </Collapsible>

        {/* ---- reference band ---- */}
        <Collapsible title="Reference concentration band">
          <div className="space-y-2">
            {drug?.reference_concentration_band && (
              <Notice tone="warn" compact title={drug.reference_concentration_band.label}>
                {drug.reference_concentration_band.caveat}
              </Notice>
            )}
            <Field label="Lower bound" unit="mg/L">
              <NumberInput
                value={setup.bandLow ?? 0}
                min={0}
                step={1}
                onChange={(bandLow) => patchSetup({ bandLow })}
              />
            </Field>
            <Field label="Upper bound" unit="mg/L">
              <NumberInput
                value={setup.bandHigh ?? 0}
                min={0}
                step={1}
                onChange={(bandHigh) => patchSetup({ bandHigh })}
              />
            </Field>
            <Button
              size="xs"
              variant="ghost"
              full
              onClick={() => patchSetup({ bandLow: null, bandHigh: null })}
            >
              Clear band
            </Button>
          </div>
        </Collapsible>

        {/* ---- solver ---- */}
        <Collapsible title="Numerical solver">
          <div className="space-y-2">
            <Field label="Method" hint="LSODA switches automatically between stiff and non-stiff.">
              <Select<SolverMethod | "auto">
                width="w-[96px]"
                value={(setup.solver.method ?? "auto") as SolverMethod | "auto"}
                onChange={(v) =>
                  patchSetup({ solver: { ...setup.solver, method: v === "auto" ? null : v } })
                }
                options={[
                  { value: "auto", label: "auto" },
                  { value: "LSODA", label: "LSODA" },
                  { value: "BDF", label: "BDF" },
                  { value: "Radau", label: "Radau" },
                  { value: "RK45", label: "RK45" },
                  { value: "DOP853", label: "DOP853" },
                ]}
              />
            </Field>
            <Field label="Relative tolerance">
              <NumberInput
                value={setup.solver.rtol}
                min={1e-14}
                max={1e-2}
                step={undefined}
                onChange={(rtol) => patchSetup({ solver: { ...setup.solver, rtol } })}
              />
            </Field>
            <Field label="Absolute tolerance">
              <NumberInput
                value={setup.solver.atol}
                min={1e-18}
                max={1e-2}
                onChange={(atol) => patchSetup({ solver: { ...setup.solver, atol } })}
              />
            </Field>
            <Field label="Output points">
              <NumberInput
                value={setup.outputPoints}
                min={11}
                max={20000}
                step={100}
                onChange={(outputPoints) => patchSetup({ outputPoints })}
              />
            </Field>
            <Toggle
              checked={setup.solver.check_tolerance_refinement}
              onChange={(v) =>
                patchSetup({ solver: { ...setup.solver, check_tolerance_refinement: v } })
              }
              label="Verify tolerance convergence"
            />
            <Hint>
              When enabled the engine re-solves with 100× tighter tolerances and reports the worst
              relative difference, so you can see whether the answer is actually converged rather
              than trusting the solver's own report. It doubles solve time.
            </Hint>
          </div>
        </Collapsible>
      </div>

      {/* ---- run controls ---- */}
      <div className="shrink-0 space-y-1 rounded border border-line bg-panel p-1.5">
        <div className="flex gap-1">
          <Button
            variant="primary"
            size="md"
            full
            loading={running === "simulate"}
            onClick={() => void run()}
            shortcut="Ctrl ⏎"
          >
            Run simulation
          </Button>
        </div>
        <div className="flex gap-1">
          <Button size="sm" variant="default" full onClick={() => snapshot()} shortcut="Ctrl S">
            Capture scenario
          </Button>
        </div>
      </div>

      <ScenarioBench />
    </div>
  );
}

/** Warn when the horizon is too short for the regimen to be interpretable. */
function DosingAdvice() {
  const setup = useStore((s) => s.setup);
  const lastRun = useStore((s) => s.lastRun);
  const r = setup.regimen;
  const lastDose = r.start_h + (r.n_doses - 1) * r.interval_h;
  const problems: string[] = [];

  if (lastDose >= setup.horizonH) {
    problems.push(
      `The last dose lands at ${lastDose} h but the horizon is ${setup.horizonH} h. The engine will refuse this.`,
    );
  } else if (r.n_doses > 1 && lastDose + r.interval_h > setup.horizonH) {
    problems.push(
      `The horizon ends less than one dosing interval after the last dose, so AUC(τ) will understate interval exposure. Extend to at least ${lastDose + r.interval_h} h.`,
    );
  }
  const thalf = lastRun?.nca.terminal_half_life_h;
  if (thalf && r.n_doses === 1 && setup.horizonH < thalf * 4) {
    problems.push(
      `The horizon is under four terminal half-lives (t½ ≈ ${thalf.toPrecision(3)} h), so AUC(0–∞) will be heavily extrapolated.`,
    );
  }
  if (!problems.length) return null;
  return (
    <Notice tone="warn" compact>
      <ul className="space-y-1">
        {problems.map((p, i) => (
          <li key={i}>{p}</li>
        ))}
      </ul>
    </Notice>
  );
}

function ScenarioBench() {
  const scenarios = useStore((s) => s.scenarios);
  const toggleScenario = useStore((s) => s.toggleScenario);
  const removeScenario = useStore((s) => s.removeScenario);
  const clearScenarios = useStore((s) => s.clearScenarios);
  const runComparison = useStore((s) => s.runComparison);
  const running = useStore((s) => s.running);
  const enabled = scenarios.filter((s) => s.enabled).length;

  if (scenarios.length === 0) return null;
  return (
    <Panel
      title={`Scenario bench (${scenarios.length})`}
      className="max-h-52 shrink-0"
      actions={
        <>
          <IconButton title="Clear the bench" onClick={clearScenarios}>
            ⌫
          </IconButton>
        </>
      }
      scroll
      dense
    >
      <div className="divide-y divide-line/50">
        {scenarios.map((sc, i) => (
          <div key={sc.id} className="flex items-center gap-1 px-1.5 py-1">
            <span className="h-[3px] w-3 shrink-0" style={{ background: seriesColour(i) }} />
            <Checkbox
              checked={sc.enabled}
              onChange={() => toggleScenario(sc.id)}
              label={
                <span className="truncate" title={`${sc.setup.modelId} · ${sc.setup.drugId ?? "no drug"}`}>
                  {sc.label}
                </span>
              }
            />
            <IconButton title="Remove scenario" onClick={() => removeScenario(sc.id)}>
              ✕
            </IconButton>
          </div>
        ))}
      </div>
      <div className="sticky bottom-0 border-t border-line bg-panel p-1.5">
        <Button
          size="sm"
          variant="default"
          full
          disabled={enabled < 2}
          loading={running === "compare"}
          onClick={() => void runComparison()}
          title={enabled < 2 ? "Enable at least two scenarios" : "Run all enabled scenarios and compare"}
        >
          Compare {enabled} scenarios
        </Button>
      </div>
    </Panel>
  );
}

// ===========================================================================
// Results column
// ===========================================================================
function ResultsColumn() {
  const lastRun = useStore((s) => s.lastRun);
  const comparison = useStore((s) => s.comparison);
  const setup = useStore((s) => s.setup);
  const patchSetup = useStore((s) => s.patchSetup);
  const models = useStore((s) => s.models);
  const run = useStore((s) => s.run);
  const spec = models.find((m) => m.model_id === setup.modelId);

  const [extraObs, setExtraObs] = useState<string[]>([]);
  const [showAllObs, setShowAllObs] = useState(false);

  // Reset secondary-observable selection whenever the model changes.
  useEffect(() => setExtraObs([]), [setup.modelId]);

  const band: PlotBand[] =
    setup.bandLow != null && setup.bandHigh != null && setup.bandHigh > setup.bandLow
      ? [
          {
            id: "ref",
            axis: "y",
            from: setup.bandLow,
            to: setup.bandHigh,
            colour: "#e0a34a",
            label: `Reference band ${setup.bandLow}–${setup.bandHigh} mg/L`,
            opacity: 0.09,
          },
        ]
      : [];

  const series: PlotSeries[] = useMemo(() => {
    const out: PlotSeries[] = [];
    if (comparison) {
      comparison.scenarios.forEach((s, i) => {
        out.push({
          id: `cmp-${i}`,
          label: s.label,
          x: s.time_h,
          y: s.observables[s.primary_observable] ?? [],
          colour: seriesColour(i),
          width: 1.5,
        });
      });
      return out;
    }
    if (!lastRun) return out;
    out.push({
      id: "primary",
      label: spec?.observables.find((o) => o.is_primary)?.label ?? lastRun.primary_observable,
      x: lastRun.time_h,
      y: lastRun.observables[lastRun.primary_observable] ?? [],
      colour: "#3fd3bd",
      width: 1.8,
    });
    extraObs.forEach((name, i) => {
      const y = lastRun.observables[name];
      if (!y) return;
      out.push({
        id: `obs-${name}`,
        label: spec?.observables.find((o) => o.name === name)?.label ?? name,
        x: lastRun.time_h,
        y,
        colour: seriesColour(i + 1),
        width: 1.2,
        dash: "4 2",
      });
    });
    return out;
  }, [lastRun, comparison, extraObs, spec]);

  const doseMarkers = useMemo(() => {
    if (comparison || !lastRun) return [];
    const r = setup.regimen;
    const out = [];
    for (let i = 0; i < Math.min(r.n_doses, 60); i++) {
      const t = r.start_h + i * r.interval_h;
      if (t > setup.horizonH) break;
      out.push({ id: `dose-${i}`, axis: "x" as const, value: t, colour: "#49525b", dash: "2 3" });
    }
    return out;
  }, [lastRun, comparison, setup.regimen, setup.horizonH]);

  const yUnit = lastRun?.observable_units[lastRun.primary_observable] ?? "mg/L";
  const secondary = (spec?.observables ?? []).filter((o) => !o.is_primary);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
      <ProvenanceStrip />

      <Panel
        title={comparison ? `Comparison: ${comparison.label}` : "Concentration–time profile"}
        subtitle={comparison ? `relative to ${comparison.relative_to}` : lastRun?.label}
        className="min-h-[300px] flex-1"
        actions={
          <>
            <Toggle
              checked={setup.yLogScale}
              onChange={(v) => patchSetup({ yLogScale: v })}
              label={<span className="text-2xs">log y</span>}
            />
            {lastRun && (
              <IconButton
                title="Export the plotted series as CSV"
                onClick={() => {
                  const cols = series;
                  const headers = ["time_h", ...cols.map((c) => c.label)];
                  const rows = (cols[0]?.x ?? []).map((t, i) => [t, ...cols.map((c) => c.y[i] ?? "")]);
                  downloadText(`${slug(lastRun.label)}-profile.csv`, toCsv(headers, rows), "text/csv");
                }}
              >
                ⤓
              </IconButton>
            )}
          </>
        }
      >
        {!lastRun && !comparison ? (
          <EmptyState title="Nothing solved yet">
            Configure a compound, model and regimen on the left, then run the simulation. Every
            curve SYNTHBODY draws is produced by the Python ODE solver — there is no placeholder
            data and nothing is rendered until the engine returns.
            <div className="mt-3">
              <Button variant="primary" onClick={() => void run()} shortcut="Ctrl ⏎">
                Run simulation
              </Button>
            </div>
          </EmptyState>
        ) : (
          <div className="group/plot flex h-full min-h-0 flex-col">
            <Plot
              series={series}
              bands={band}
              markers={doseMarkers}
              xLabel="Time"
              xUnit="h"
              yLabel={comparison ? "Plasma concentration" : (spec?.observables.find((o) => o.is_primary)?.label ?? "Concentration")}
              yUnit={yUnit}
              yScale={setup.yLogScale ? "log" : "linear"}
              height={340}
              onExportName={slug(lastRun?.label ?? comparison?.label ?? "profile")}
            />

            {secondary.length > 0 && !comparison && (
              <div className="mt-1 border-t border-line pt-1">
                <button
                  onClick={() => setShowAllObs((v) => !v)}
                  className="mb-1 text-2xs text-ink-faint hover:text-ink-dim"
                >
                  {showAllObs ? "▾" : "▸"} Overlay other model outputs ({secondary.length} available)
                </button>
                {showAllObs && (
                  <div className="grid grid-cols-2 gap-x-2 md:grid-cols-3 lg:grid-cols-4">
                    {secondary.map((o) => (
                      <Checkbox
                        key={o.name}
                        checked={extraObs.includes(o.name)}
                        colour={seriesColour(extraObs.indexOf(o.name) + 1)}
                        onChange={(on) =>
                          setExtraObs((xs) => (on ? [...xs, o.name] : xs.filter((x) => x !== o.name)))
                        }
                        label={
                          <span title={`${o.description} (${o.unit})`}>
                            {o.label}
                            <span className="ml-1 text-ink-ghost">{prettyUnit(o.unit)}</span>
                          </span>
                        }
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </Panel>

      {comparison ? <ComparisonTable /> : <ExposurePanel />}
    </div>
  );
}

function ExposurePanel() {
  const lastRun = useStore((s) => s.lastRun);
  if (!lastRun) return null;
  const n = lastRun.nca;
  const a = lastRun.accumulation;
  const tir = lastRun.time_in_range;
  const unit = lastRun.observable_units[lastRun.primary_observable] ?? "mg/L";

  return (
    <Panel
      title="Exposure metrics"
      subtitle="non-compartmental, computed from the simulated profile"
      className="max-h-[42%] shrink-0"
      scroll
      actions={
        <IconButton
          title="Export metrics as CSV"
          onClick={() => {
            const rows = Object.entries(n)
              .filter(([, v]) => typeof v === "number" || v === null)
              .map(([k, v]) => [k, v as number | null]);
            downloadText(`${slug(lastRun.label)}-nca.csv`, toCsv(["metric", "value"], rows), "text/csv");
          }}
        >
          ⤓
        </IconButton>
      }
    >
      <div className="grid grid-cols-1 gap-x-4 md:grid-cols-2 xl:grid-cols-3">
        <div>
          <SectionLabel>Peak and trough</SectionLabel>
          <Metric label="Cmax" value={n.cmax} unit={unit} />
          <Metric label="Tmax" value={n.tmax_h} unit="h" />
          <Metric label="Cmin (in window)" value={n.cmin} unit={unit} />
          <Metric label="Last observed C" value={n.clast} unit={unit} />
        </div>
        <div>
          <SectionLabel>Exposure</SectionLabel>
          <Metric
            label={n.auc_window_h ? "AUC(τ)" : "AUC(0–last)"}
            value={n.auc_0_last}
            unit={`${unit}·h`}
            hint={
              n.auc_window_h
                ? `Integrated over one dosing interval, ${n.auc_window_h[0]}–${n.auc_window_h[1]} h, starting at the last dose.`
                : "Integrated over the whole simulated window using the linear-up / log-down trapezoidal rule."
            }
          />
          <Metric
            label="AUC(0–∞)"
            value={n.auc_0_inf}
            unit={`${unit}·h`}
            tone={n.auc_extrap_percent != null && n.auc_extrap_percent > 20 ? "warn" : undefined}
            hint="Extrapolated to infinity using the terminal rate constant."
          />
          <Metric
            label="Extrapolated fraction"
            value={n.auc_extrap_percent != null ? `${n.auc_extrap_percent.toFixed(1)}%` : null}
            tone={n.auc_extrap_percent != null && n.auc_extrap_percent > 20 ? "warn" : "ok"}
            hint="Above about 20% the AUC(0–∞) and anything derived from it are unreliable."
          />
          <Metric label="AUMC(0–last)" value={n.aumc_0_last} unit={`${unit}·h²`} />
        </div>
        <div>
          <SectionLabel>Disposition</SectionLabel>
          <Metric
            label="Terminal t½"
            value={n.terminal_half_life_h}
            unit="h"
            hint={`Fitted on ${n.terminal_fit_n_points} points, R² = ${sig(n.terminal_fit_r_squared, 4)}`}
            tone={
              n.terminal_fit_r_squared != null && n.terminal_fit_r_squared < 0.95 ? "warn" : undefined
            }
          />
          <Metric label="λz" value={n.terminal_rate_constant_per_h} unit="1/h" />
          <Metric label="CL (dose/AUC∞)" value={n.clearance_L_per_h} unit="L/h" />
          <Metric label="Vz" value={n.volume_terminal_L} unit="L" />
          <Metric label="MRT" value={n.mean_residence_time_h} unit="h" />
        </div>

        {a && (
          <div>
            <SectionLabel>Multiple-dose behaviour</SectionLabel>
            <Metric label="Complete intervals" value={a.n_complete_intervals} digits={3} />
            <Metric
              label="Accumulation ratio"
              value={a.accumulation_ratio_auc}
              hint="AUC over the final interval divided by AUC over the first interval."
            />
            <Metric label="Cmax at last interval" value={a.cmax_ss} unit={unit} />
            <Metric label="Cmin at last interval" value={a.cmin_ss} unit={unit} />
            <Metric label="Average C" value={a.average_concentration_ss} unit={unit} />
            <Metric
              label="Peak–trough fluctuation"
              value={a.peak_trough_fluctuation_percent != null ? `${a.peak_trough_fluctuation_percent.toFixed(0)}%` : null}
            />
          </div>
        )}

        {tir && (
          <div>
            <SectionLabel>Time relative to reference band</SectionLabel>
            <Metric label="Below band" value={pct(tir.fraction_below)} />
            <Metric label="Within band" value={pct(tir.fraction_within)} tone="ok" />
            <Metric
              label="Above band"
              value={pct(tir.fraction_above)}
              tone={tir.fraction_above > 0 ? "warn" : undefined}
            />
            <Metric label="Hours within" value={tir.hours_within} unit="h" digits={3} />
            {tir.band_caveat && (
              <div className="mt-1 text-[9px] leading-snug text-warn">{tir.band_caveat}</div>
            )}
          </div>
        )}

        <div>
          <SectionLabel>Effective parameters</SectionLabel>
          {Object.entries(lastRun.effective_parameters).map(([k, v]) => (
            <Metric key={k} label={k} value={v} />
          ))}
          {lastRun.covariates_applied.length > 0 && (
            <>
              <SectionLabel>Covariate adjustments</SectionLabel>
              {lastRun.covariates_applied.map((c, i) => (
                <div key={i} className="border-b border-line/40 py-1 last:border-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="flex items-center gap-1 text-xs text-ink-faint">
                      {c.parameter} <OriginBadge origin={c.origin} />
                    </span>
                    <span className="font-mono text-xs text-ink tnum">×{sig(c.multiplier, 4)}</span>
                  </div>
                  <div className="text-[9px] leading-snug text-ink-ghost">{c.basis}</div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {(n.warnings.length > 0 || lastRun.diagnostics.warnings.length > 0) && (
        <div className="mt-2 space-y-1">
          {[...lastRun.diagnostics.warnings, ...n.warnings].map((w, i) => (
            <Notice key={i} tone="warn" compact>
              {w}
            </Notice>
          ))}
        </div>
      )}
    </Panel>
  );
}

function ComparisonTable() {
  const comparison = useStore((s) => s.comparison);
  const [open, setOpen] = useState(false);
  if (!comparison) return null;
  const t = comparison.exposure_table;

  return (
    <Panel
      title="Scenario exposure comparison"
      subtitle={`${t.length} scenarios · ratios relative to ${comparison.relative_to}`}
      className="max-h-[42%] shrink-0"
      scroll
      dense
      actions={
        <>
          <IconButton title="Interpretation notes" onClick={() => setOpen(true)}>
            ⓘ
          </IconButton>
          <IconButton
            title="Export comparison as CSV"
            onClick={() => {
              const headers = Object.keys(t[0] ?? {});
              downloadText(
                "synthbody-comparison.csv",
                toCsv(
                  headers,
                  t.map((r) => {
                    const rec = r as unknown as Record<string, unknown>;
                    return headers.map((h) => {
                      const v = rec[h];
                      if (v == null) return "";
                      if (typeof v === "number") return v;
                      return Array.isArray(v) ? v.join("–") : String(v);
                    });
                  }),
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
      <Table
        compact
        headers={[
          "Scenario",
          { label: "Route", align: "left" },
          { label: "Dose", align: "right" },
          { label: "n×τ", align: "right" },
          { label: "Cmax", align: "right" },
          { label: "Cmin", align: "right" },
          { label: "AUC", align: "right", hint: "AUC(τ) over one interval after the last dose for multiple-dose runs; AUC(0–last) for single doses." },
          { label: "AUC ratio", align: "right" },
          { label: "Cmax ratio", align: "right" },
          { label: "R(ac)", align: "right", hint: "Accumulation ratio: last interval AUC / first interval AUC." },
          { label: "Fluct.", align: "right", hint: "Peak-to-trough fluctuation as a percentage of average concentration." },
          { label: "In band", align: "right" },
          { label: "Above", align: "right" },
          { label: "t½", align: "right" },
        ]}
      >
        {t.map((r, i) => (
          <Row key={r.label} tone={r.fraction_time_above_band && r.fraction_time_above_band > 0 ? "warn" : undefined}>
            <Cell>
              <span className="flex items-center gap-1.5">
                <span className="h-[3px] w-3 shrink-0" style={{ background: seriesColour(i) }} />
                <span className="truncate text-ink">{r.label}</span>
                {r.solver_warnings > 0 && (
                  <Badge tone="warn" title="This scenario produced solver warnings">
                    {r.solver_warnings}
                  </Badge>
                )}
              </span>
            </Cell>
            <Cell dim>{r.route.replace("_", " ")}</Cell>
            <Cell align="right" mono>
              {r.dose_mg}
            </Cell>
            <Cell align="right" mono dim>
              {r.n_doses > 1 ? `${r.n_doses}×${r.interval_h}h` : "single"}
            </Cell>
            <Cell align="right" mono>
              {sig(r.cmax, 4)}
            </Cell>
            <Cell align="right" mono dim>
              {sig(r.cmin, 3)}
            </Cell>
            <Cell align="right" mono title={r.auc_window_h ? `window ${r.auc_window_h[0]}–${r.auc_window_h[1]} h` : undefined}>
              {sig(r.auc_0_last, 4)}
            </Cell>
            <Cell align="right" mono className={ratioClass(r.auc_ratio_vs_baseline)}>
              {r.auc_ratio_vs_baseline != null ? `×${sig(r.auc_ratio_vs_baseline, 3)}` : "—"}
            </Cell>
            <Cell align="right" mono className={ratioClass(r.cmax_ratio_vs_baseline)}>
              {r.cmax_ratio_vs_baseline != null ? `×${sig(r.cmax_ratio_vs_baseline, 3)}` : "—"}
            </Cell>
            <Cell align="right" mono dim>
              {r.accumulation_ratio_auc != null ? sig(r.accumulation_ratio_auc, 3) : "—"}
            </Cell>
            <Cell align="right" mono dim>
              {r.peak_trough_fluctuation_percent != null
                ? `${r.peak_trough_fluctuation_percent.toFixed(0)}%`
                : "—"}
            </Cell>
            <Cell align="right" mono>
              {r.fraction_time_in_band != null ? pct(r.fraction_time_in_band, 0) : "—"}
            </Cell>
            <Cell align="right" mono className={r.fraction_time_above_band ? "text-warn" : ""}>
              {r.fraction_time_above_band != null ? pct(r.fraction_time_above_band, 0) : "—"}
            </Cell>
            <Cell align="right" mono dim>
              {sig(r.terminal_half_life_h, 3)}
            </Cell>
          </Row>
        ))}
      </Table>

      <Modal open={open} onClose={() => setOpen(false)} title="How to read this table" wide>
        <div className="space-y-2">
          {comparison.notes.map((n, i) => (
            <Notice key={i} tone="info" compact>
              {n}
            </Notice>
          ))}
          <Notice tone="warn" compact title="A caution about dose comparison">
            For a linear model, doubling the dose doubles exposure exactly; the ratios will show
            that and nothing more. The comparison becomes informative when the model is non-linear,
            when the regimens differ in interval rather than amount, or when you are checking how
            much of the interval sits inside a reference band.
          </Notice>
        </div>
      </Modal>
    </Panel>
  );
}

function ratioClass(v: number | null): string {
  if (v == null) return "";
  if (v > 1.05) return "text-warn";
  if (v < 0.95) return "text-info";
  return "";
}

// ===========================================================================
// Inspector column
// ===========================================================================
function InspectorColumn() {
  const lastRun = useStore((s) => s.lastRun);
  const references = useStore((s) => s.references);
  const setWorkspace = useStore((s) => s.setWorkspace);
  const toggleInspector = useStore((s) => s.toggleInspector);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
      <Panel
        title="Provenance inspector"
        className="min-h-0 flex-1"
        scroll
        dense
        actions={
          <IconButton title="Hide inspector (Ctrl+I)" onClick={() => toggleInspector(false)}>
            ✕
          </IconButton>
        }
      >
        {!lastRun ? (
          <EmptyState title="No run to inspect">
            Run a simulation and this panel will show every parameter that went into it, where each
            value came from, the solver's own diagnostics, and the citations behind the model.
          </EmptyState>
        ) : (
          <div>
            <Collapsible title="Validation status" defaultOpen>
              <div className="space-y-2">
                <ValidationBadge status={lastRun.validation_status} full />
                <Hint>{lastRun.validation_summary}</Hint>
                <Notice tone="neutral" compact>
                  {lastRun.disclaimer}
                </Notice>
              </div>
            </Collapsible>

            <Collapsible title={`Parameters (${lastRun.provenance.parameters.length})`} defaultOpen dense>
              <Table
                compact
                headers={["Parameter", { label: "Value", align: "right" }, "Unit", "Origin"]}
              >
                {lastRun.provenance.parameters.map((p) => (
                  <Row key={p.name}>
                    <Cell title={`${p.description}${p.notes ? `\n${p.notes}` : ""}`}>
                      <span className="text-ink">{p.name}</span>
                    </Cell>
                    <Cell align="right" mono>
                      {sig(p.value, 5)}
                    </Cell>
                    <Cell dim mono>
                      {prettyUnit(p.unit) || "—"}
                    </Cell>
                    <Cell>
                      <OriginBadge origin={p.origin} />
                    </Cell>
                  </Row>
                ))}
              </Table>
              <div className="border-t border-line p-2">
                <SectionLabel>Origin legend</SectionLabel>
                <div className="space-y-1">
                  {Object.entries(ORIGIN_META).map(([k, m]) => (
                    <div key={k} className="flex items-start gap-1.5">
                      <OriginBadge origin={k as never} />
                      <span className="text-[9px] leading-snug text-ink-ghost">{m.explain}</span>
                    </div>
                  ))}
                </div>
              </div>
            </Collapsible>

            <Collapsible title="Solver diagnostics" defaultOpen>
              <SolverDiagnosticsView />
            </Collapsible>

            <Collapsible title={`Assumptions (${lastRun.provenance.assumptions.length})`}>
              <ul className="space-y-1.5">
                {lastRun.provenance.assumptions.map((a, i) => (
                  <li key={i} className="flex gap-1.5 text-xs leading-relaxed text-ink-dim">
                    <span className="text-ink-ghost">·</span>
                    <span>{a}</span>
                  </li>
                ))}
              </ul>
            </Collapsible>

            <Collapsible title={`Limitations (${lastRun.provenance.limitations.length})`}>
              <ul className="space-y-1.5">
                {lastRun.provenance.limitations.map((a, i) => (
                  <li key={i} className="flex gap-1.5 text-xs leading-relaxed text-warn/90">
                    <span className="text-warn">!</span>
                    <span>{a}</span>
                  </li>
                ))}
              </ul>
            </Collapsible>

            <Collapsible title={`References (${lastRun.provenance.reference_ids.length})`}>
              <div className="space-y-2">
                {lastRun.provenance.reference_ids.map((id) => {
                  const r = references.find((x) => x.id === id);
                  if (!r) return null;
                  return (
                    <div key={id} className="rounded border border-line bg-void/40 p-1.5">
                      <div className="text-xs leading-snug text-ink-dim">{r.citation}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        {r.pmid && <Badge mono tone="info">PMID {r.pmid}</Badge>}
                        {r.doi && <Badge mono tone="neutral">DOI</Badge>}
                        {r.url && (
                          <a
                            href={r.url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="text-2xs text-accent hover:underline"
                          >
                            open ↗
                          </a>
                        )}
                      </div>
                    </div>
                  );
                })}
                <Button size="xs" variant="subtle" full onClick={() => setWorkspace("evidence")}>
                  Open the full evidence library
                </Button>
              </div>
            </Collapsible>

            <Collapsible title="Reproducibility record">
              <div className="space-y-1 font-mono text-2xs">
                <KV k="software" v={`${lastRun.provenance.software_name} ${lastRun.provenance.software_version}`} />
                <KV k="engine" v={lastRun.provenance.engine_revision} />
                <KV k="model" v={`${lastRun.provenance.model_id}@${lastRun.provenance.model_version}`} />
                <KV k="schema" v={lastRun.provenance.schema_version} />
                <KV k="timestamp" v={lastRun.provenance.timestamp_utc} />
                <KV k="python" v={lastRun.provenance.python_version} />
                <KV k="platform" v={lastRun.provenance.platform} />
                <KV k="input hash" v={lastRun.provenance.input_hash} wrap />
                <KV k="record hash" v={lastRun.provenance.record_hash} wrap />
                {lastRun.simulation_id != null && <KV k="stored id" v={String(lastRun.simulation_id)} />}
              </div>
              <Hint>
                The input hash covers only what determines the numbers: model, version, engine
                revision, parameters, inputs and seed. Two runs of the same science hash
                identically even though their timestamps differ, which is what makes the
                Experiments workspace able to verify exact reproduction.
              </Hint>
            </Collapsible>
          </div>
        )}
      </Panel>
    </div>
  );
}

function KV({ k, v, wrap }: { k: string; v: string; wrap?: boolean }) {
  return (
    <div className="flex gap-2 border-b border-line/40 py-0.5 last:border-0">
      <span className="w-20 shrink-0 text-ink-ghost">{k}</span>
      <span className={cx("min-w-0 flex-1 text-ink-dim", wrap ? "break-all" : "truncate")} title={v}>
        {v}
      </span>
    </div>
  );
}

function SolverDiagnosticsView() {
  const d = useStore((s) => s.lastRun?.diagnostics);
  if (!d) return null;
  const mbOk = d.mass_balance_relative_error == null || d.mass_balance_relative_error < 1e-6;
  const tolOk =
    d.tolerance_refinement_max_rel_diff == null || d.tolerance_refinement_max_rel_diff < 1e-3;

  return (
    <div className="space-y-2">
      <div>
        <Metric label="Method" value={d.method} />
        <Metric label="Relative tolerance" value={sci(d.rtol)} />
        <Metric label="Absolute tolerance" value={sci(d.atol)} />
        <Metric label="Converged" value={d.success ? "yes" : "no"} tone={d.success ? "ok" : "danger"} />
        <Metric label="RHS evaluations" value={d.n_rhs_evaluations} digits={8} />
        <Metric label="Jacobian evaluations" value={d.n_jacobian_evaluations} digits={8} />
        <Metric label="LU decompositions" value={d.n_lu_decompositions} digits={8} />
        <Metric label="Accepted steps" value={d.n_steps_accepted} digits={8} />
        <Metric label="Wall time" value={`${(d.wall_time_s * 1000).toFixed(2)} ms`} />
      </div>

      <SectionLabel>Independent checks</SectionLabel>
      <div>
        <Metric
          label="Mass balance error"
          value={d.mass_balance_relative_error != null ? sci(d.mass_balance_relative_error) : "n/a"}
          tone={mbOk ? "ok" : "warn"}
          hint="Amount dosed minus (amount in body + amount eliminated), relative to the dose. Computed by the engine, not reported by the solver."
        />
        <Metric
          label="Max negative state"
          value={d.max_negative_state != null ? sci(d.max_negative_state) : "n/a"}
          tone={(d.max_negative_state ?? 0) > 0 ? "warn" : "ok"}
          hint="Largest excursion of any amount below zero. A physically impossible state."
        />
        <Metric
          label="Tolerance refinement Δ"
          value={
            d.tolerance_refinement_max_rel_diff != null
              ? sci(d.tolerance_refinement_max_rel_diff)
              : "not checked"
          }
          tone={d.tolerance_refinement_max_rel_diff == null ? undefined : tolOk ? "ok" : "warn"}
          hint="Worst relative change when the problem is re-solved with 100× tighter tolerances. A small value means the answer is tolerance-converged."
        />
      </div>

      {d.message !== "ok" && (
        <Notice tone="warn" compact title="Solver message">
          {d.message}
        </Notice>
      )}
      {d.warnings.map((w, i) => (
        <Notice key={i} tone="warn" compact>
          {w}
        </Notice>
      ))}
      {d.warnings.length === 0 && mbOk && tolOk && (
        <Notice tone="ok" compact>
          Numerics clean: mass balance closes, no negative states, and the solution is
          tolerance-converged.
        </Notice>
      )}
    </div>
  );
}
