/**
 * Application state.
 *
 * Zustand rather than context because the Studio workspace reads a lot of
 * slices and re-rendering the whole tree on every slider move would be
 * noticeable. The store owns the shared library catalogue (models, drugs,
 * references) and the current simulation setup; workspaces own their own
 * local view state.
 */
import { create } from "zustand";
import { api, ApiError } from "./api";
import type {
  ComparisonResponse,
  DatasetSummary,
  Drug,
  Experiment,
  Meta,
  ModelSpec,
  Patient,
  PopulationResponse,
  Reference,
  Regimen,
  SensitivityResponse,
  SimulationRequest,
  SimulationResponse,
  SolverSettings,
} from "./types";

export type WorkspaceId =
  | "studio"
  | "patient"
  | "drug"
  | "systems"
  | "analytics"
  | "experiments"
  | "evidence"
  | "reports";

export interface LogEntry {
  id: number;
  at: Date;
  level: "info" | "ok" | "warn" | "error";
  source: string;
  message: string;
  detail?: string;
}

interface Setup {
  label: string;
  modelId: string;
  drugId: string | null;
  patientId: number | null;
  applyCovariates: boolean;
  parameters: Record<string, number>;
  regimen: Regimen;
  horizonH: number;
  outputPoints: number;
  solver: SolverSettings;
  bandLow: number | null;
  bandHigh: number | null;
  yLogScale: boolean;
}

interface State {
  // ---- catalogue
  meta: Meta | null;
  models: ModelSpec[];
  drugs: Drug[];
  references: Reference[];
  originLegend: Record<string, string>;
  datasets: DatasetSummary[];
  patients: Patient[];
  experiments: Experiment[];
  catalogueLoaded: boolean;
  catalogueError: string | null;
  backendOnline: boolean;

  // ---- navigation
  workspace: WorkspaceId;
  commandPaletteOpen: boolean;
  consoleOpen: boolean;
  inspectorOpen: boolean;

  // ---- current work
  setup: Setup;
  activeExperimentId: number | null;

  // ---- results
  lastRun: SimulationResponse | null;
  comparison: ComparisonResponse | null;
  population: PopulationResponse | null;
  sensitivity: SensitivityResponse | null;
  running: null | "simulate" | "compare" | "population" | "sensitivity";

  // ---- scenario bench (Studio)
  scenarios: { id: string; label: string; setup: Setup; enabled: boolean }[];

  // ---- console
  log: LogEntry[];

  // ---- actions
  bootstrap: () => Promise<void>;
  refreshPatients: () => Promise<void>;
  refreshExperiments: () => Promise<void>;
  setWorkspace: (w: WorkspaceId) => void;
  toggleCommandPalette: (open?: boolean) => void;
  toggleConsole: (open?: boolean) => void;
  toggleInspector: (open?: boolean) => void;
  patchSetup: (p: Partial<Setup>) => void;
  setParameter: (name: string, value: number) => void;
  selectModel: (modelId: string) => void;
  selectDrug: (drugId: string | null) => void;
  resetParametersToDrugDefaults: () => void;
  setActiveExperiment: (id: number | null) => void;
  pushLog: (e: Omit<LogEntry, "id" | "at">) => void;
  clearLog: () => void;
  run: () => Promise<SimulationResponse | null>;
  snapshotScenario: (label?: string) => void;
  removeScenario: (id: string) => void;
  toggleScenario: (id: string) => void;
  clearScenarios: () => void;
  runComparison: () => Promise<void>;
  runPopulation: (opts: {
    nSubjects: number;
    seed: number;
    randomEffects: { parameter: string; cv_percent: number }[];
    includeResidual: boolean;
    residual: { proportional_cv_percent: number; additive_sd: number };
  }) => Promise<void>;
  runSensitivity: (opts: {
    method: "local" | "morris" | "sobol";
    metric: "auc_0_last" | "cmax" | "tmax" | "cmin" | "auc_0_inf" | "t_half";
    targets: string[];
    relativeRange: number;
    morrisTrajectories: number;
    sobolBaseSamples: number;
  }) => Promise<void>;
  modelSpec: () => ModelSpec | null;
  drugSpec: () => Drug | null;
  toRequest: (overrides?: Partial<SimulationRequest>) => SimulationRequest;
}

const DEFAULT_REGIMEN: Regimen = {
  route: "oral",
  dose_mg: 300,
  n_doses: 1,
  interval_h: 12,
  start_h: 0,
  infusion_duration_h: 0,
};

const DEFAULT_SOLVER: SolverSettings = {
  method: null,
  rtol: 1e-8,
  atol: 1e-10,
  max_step_h: null,
  check_tolerance_refinement: true,
};

const DEFAULT_SETUP: Setup = {
  label: "Untitled run",
  modelId: "pk_1cmt_foa",
  drugId: "theophylline",
  patientId: null,
  applyCovariates: true,
  parameters: {},
  regimen: DEFAULT_REGIMEN,
  horizonH: 25,
  outputPoints: 601,
  solver: DEFAULT_SOLVER,
  bandLow: null,
  bandHigh: null,
  yLogScale: false,
};

/**
 * Extract a Regimen from a drug's `default_regimen` block.
 *
 * The library's default_regimen also carries `simulation_horizon_h` and a
 * human-readable `note`, which are not part of the regimen itself. The API
 * schema forbids extra keys, so those must be picked out explicitly rather
 * than spread in — spreading them produces a 422 that is easy to miss.
 */
function regimenFromDrug(d: Drug): Regimen {
  const r = d.default_regimen;
  return {
    route: r.route ?? DEFAULT_REGIMEN.route,
    dose_mg: r.dose_mg ?? DEFAULT_REGIMEN.dose_mg,
    n_doses: r.n_doses ?? DEFAULT_REGIMEN.n_doses,
    interval_h: r.interval_h ?? DEFAULT_REGIMEN.interval_h,
    start_h: DEFAULT_REGIMEN.start_h,
    infusion_duration_h:
      r.route === "iv_infusion" ? Math.max(DEFAULT_REGIMEN.infusion_duration_h, 1) : 0,
  };
}

let logSeq = 0;
let scenarioSeq = 0;

export const useStore = create<State>((set, get) => ({
  meta: null,
  models: [],
  drugs: [],
  references: [],
  originLegend: {},
  datasets: [],
  patients: [],
  experiments: [],
  catalogueLoaded: false,
  catalogueError: null,
  backendOnline: false,

  workspace: "studio",
  commandPaletteOpen: false,
  consoleOpen: false,
  inspectorOpen: true,

  setup: DEFAULT_SETUP,
  activeExperimentId: null,

  lastRun: null,
  comparison: null,
  population: null,
  sensitivity: null,
  running: null,

  scenarios: [],
  log: [],

  // -------------------------------------------------------------- bootstrap
  bootstrap: async () => {
    try {
      const [meta, models, drugsRes, refsRes, datasets, patients, experiments] = await Promise.all([
        api.meta(),
        api.models(),
        api.drugs(),
        api.references(),
        api.datasets(),
        api.patients(),
        api.experiments(),
      ]);
      const defaultDrug = drugsRes.drugs.find((d) => d.drug_id === "theophylline") ?? drugsRes.drugs[0];
      const setup: Setup = defaultDrug
        ? {
            ...DEFAULT_SETUP,
            label: `${defaultDrug.name} ${defaultDrug.default_regimen.dose_mg} mg`,
            modelId: defaultDrug.default_model_id,
            drugId: defaultDrug.drug_id,
            regimen: regimenFromDrug(defaultDrug),
            horizonH: defaultDrug.default_regimen.simulation_horizon_h,
            bandLow: defaultDrug.reference_concentration_band?.low ?? null,
            bandHigh: defaultDrug.reference_concentration_band?.high ?? null,
          }
        : DEFAULT_SETUP;

      set({
        meta,
        models,
        drugs: drugsRes.drugs,
        originLegend: drugsRes.parameter_origin_legend,
        references: refsRes.references,
        datasets,
        patients,
        experiments,
        catalogueLoaded: true,
        catalogueError: null,
        backendOnline: true,
        setup,
      });
      get().pushLog({
        level: "ok",
        source: "startup",
        message: `Connected to ${meta.software_name} ${meta.software_version} (${meta.engine_revision})`,
        detail: `${models.length} models · ${drugsRes.drugs.length} compounds · ${refsRes.references.length} references · ${datasets.length} validation datasets`,
      });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      set({ catalogueLoaded: true, catalogueError: msg, backendOnline: false });
      get().pushLog({ level: "error", source: "startup", message: "Could not load the catalogue", detail: msg });
    }
  },

  refreshPatients: async () => {
    try {
      set({ patients: await api.patients() });
    } catch (e) {
      get().pushLog({ level: "error", source: "patients", message: String(e) });
    }
  },

  refreshExperiments: async () => {
    try {
      set({ experiments: await api.experiments() });
    } catch (e) {
      get().pushLog({ level: "error", source: "experiments", message: String(e) });
    }
  },

  // ------------------------------------------------------------- navigation
  setWorkspace: (workspace) => set({ workspace }),
  toggleCommandPalette: (open) =>
    set((s) => ({ commandPaletteOpen: open ?? !s.commandPaletteOpen })),
  toggleConsole: (open) => set((s) => ({ consoleOpen: open ?? !s.consoleOpen })),
  toggleInspector: (open) => set((s) => ({ inspectorOpen: open ?? !s.inspectorOpen })),

  // ------------------------------------------------------------------ setup
  patchSetup: (p) => set((s) => ({ setup: { ...s.setup, ...p } })),

  setParameter: (name, value) =>
    set((s) => ({ setup: { ...s.setup, parameters: { ...s.setup.parameters, [name]: value } } })),

  selectModel: (modelId) => {
    const spec = get().models.find((m) => m.model_id === modelId);
    if (!spec) return;
    const s = get().setup;
    // Keep the route if the new model supports it, otherwise fall back.
    const route = spec.routes.includes(s.regimen.route) ? s.regimen.route : spec.routes[0]!;
    set({
      setup: {
        ...s,
        modelId,
        parameters: {}, // parameters are model-specific; start from defaults
        regimen: {
          ...s.regimen,
          route,
          infusion_duration_h: route === "iv_infusion" ? Math.max(s.regimen.infusion_duration_h, 1) : 0,
        },
      },
    });
    get().pushLog({
      level: "info",
      source: "studio",
      message: `Model set to ${spec.name}`,
      detail: `Validation status: ${spec.validation_status}. Parameters reset to this model's library or schema defaults.`,
    });
  },

  selectDrug: (drugId) => {
    if (!drugId) {
      set((s) => ({ setup: { ...s.setup, drugId: null, parameters: {} } }));
      return;
    }
    const d = get().drugs.find((x) => x.drug_id === drugId);
    if (!d) return;
    const s = get().setup;
    const modelId = d.available_model_ids.includes(s.modelId) ? s.modelId : d.default_model_id;
    set({
      setup: {
        ...s,
        drugId,
        modelId,
        parameters: {},
        label: `${d.name} ${d.default_regimen.dose_mg} mg`,
        regimen: regimenFromDrug(d),
        horizonH: d.default_regimen.simulation_horizon_h,
        bandLow: d.reference_concentration_band?.low ?? null,
        bandHigh: d.reference_concentration_band?.high ?? null,
      },
    });
    get().pushLog({
      level: "info",
      source: "studio",
      message: `Compound set to ${d.name}`,
      detail: d.is_synthetic_demonstration
        ? "This is a SYNTHETIC demonstration compound. Every parameter is invented and no output means anything pharmacologically."
        : `${d.validation_note}`,
    });
  },

  resetParametersToDrugDefaults: () => {
    set((s) => ({ setup: { ...s.setup, parameters: {} } }));
    get().pushLog({
      level: "info",
      source: "studio",
      message: "Parameters reset to library defaults",
    });
  },

  setActiveExperiment: (id) => set({ activeExperimentId: id }),

  // ---------------------------------------------------------------- console
  pushLog: (e) =>
    set((s) => ({
      log: [...s.log.slice(-399), { ...e, id: ++logSeq, at: new Date() }],
    })),
  clearLog: () => set({ log: [] }),

  // -------------------------------------------------------------- requests
  modelSpec: () => get().models.find((m) => m.model_id === get().setup.modelId) ?? null,
  drugSpec: () => get().drugs.find((d) => d.drug_id === get().setup.drugId) ?? null,

  toRequest: (overrides) => {
    const s = get().setup;
    return {
      label: s.label,
      model_id: s.modelId,
      drug_id: s.drugId,
      parameters: s.parameters,
      regimen: s.regimen,
      simulation_horizon_h: s.horizonH,
      n_output_points: s.outputPoints,
      patient_id: s.patientId,
      apply_patient_covariates: s.applyCovariates,
      solver: s.solver,
      experiment_id: get().activeExperimentId,
      persist: true,
      reference_band_low: s.bandLow,
      reference_band_high: s.bandHigh,
      ...overrides,
    };
  },

  // -------------------------------------------------------------------- run
  run: async () => {
    const req = get().toRequest();
    set({ running: "simulate" });
    try {
      const res = await api.simulate(req);
      set({ lastRun: res, running: null, backendOnline: true });
      const warn = res.diagnostics.warnings.length;
      get().pushLog({
        level: warn ? "warn" : "ok",
        source: "solver",
        message: `${res.label}: Cmax ${res.nca.cmax.toPrecision(4)} ${
          res.observable_units[res.primary_observable] ?? ""
        } at ${res.nca.tmax_h.toPrecision(3)} h`,
        detail: [
          `${res.diagnostics.method} · rtol ${res.diagnostics.rtol.toExponential(0)} · ${
            res.diagnostics.n_rhs_evaluations
          } RHS evals · ${(res.diagnostics.wall_time_s * 1000).toFixed(1)} ms`,
          res.diagnostics.mass_balance_relative_error != null
            ? `mass balance ${res.diagnostics.mass_balance_relative_error.toExponential(2)}`
            : "",
          ...res.diagnostics.warnings,
          ...res.nca.warnings,
        ]
          .filter(Boolean)
          .join(" · "),
      });
      if (req.persist) void get().refreshExperiments();
      return res;
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      set({ running: null, backendOnline: !(e instanceof ApiError && e.status === 0) });
      get().pushLog({ level: "error", source: "solver", message: "Simulation failed", detail: msg });
      return null;
    }
  },

  // -------------------------------------------------------------- scenarios
  snapshotScenario: (label) => {
    const s = get().setup;
    const id = `sc${++scenarioSeq}`;
    const auto =
      label ??
      `${s.regimen.dose_mg} mg ${
        s.regimen.n_doses > 1 ? `q${s.regimen.interval_h}h ×${s.regimen.n_doses}` : "single"
      } ${s.regimen.route.replace("_", " ")}`;
    set((st) => ({
      scenarios: [...st.scenarios, { id, label: auto, setup: { ...s }, enabled: true }],
    }));
    get().pushLog({ level: "info", source: "bench", message: `Scenario captured: ${auto}` });
  },

  removeScenario: (id) => set((s) => ({ scenarios: s.scenarios.filter((x) => x.id !== id) })),
  toggleScenario: (id) =>
    set((s) => ({
      scenarios: s.scenarios.map((x) => (x.id === id ? { ...x, enabled: !x.enabled } : x)),
    })),
  clearScenarios: () => set({ scenarios: [], comparison: null }),

  runComparison: async () => {
    const active = get().scenarios.filter((s) => s.enabled);
    if (active.length < 2) {
      get().pushLog({
        level: "warn",
        source: "bench",
        message: "Need at least two enabled scenarios to compare",
      });
      return;
    }
    // Labels must be distinct for the backend; de-duplicate here with a suffix.
    const seen = new Map<string, number>();
    const scenarios: SimulationRequest[] = active.map((sc) => {
      const n = (seen.get(sc.label) ?? 0) + 1;
      seen.set(sc.label, n);
      const label = n > 1 ? `${sc.label} (${n})` : sc.label;
      return {
        label,
        model_id: sc.setup.modelId,
        drug_id: sc.setup.drugId,
        parameters: sc.setup.parameters,
        regimen: sc.setup.regimen,
        simulation_horizon_h: sc.setup.horizonH,
        n_output_points: sc.setup.outputPoints,
        patient_id: sc.setup.patientId,
        apply_patient_covariates: sc.setup.applyCovariates,
        solver: sc.setup.solver,
        persist: false,
        reference_band_low: sc.setup.bandLow,
        reference_band_high: sc.setup.bandHigh,
      };
    });
    set({ running: "compare" });
    try {
      const res = await api.compare({
        label: "Scenario comparison",
        scenarios,
        persist: false,
        experiment_id: get().activeExperimentId,
      });
      set({ comparison: res, running: null });
      get().pushLog({
        level: "ok",
        source: "bench",
        message: `Compared ${res.scenarios.length} scenarios`,
        detail: res.notes.join(" "),
      });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      set({ running: null });
      get().pushLog({ level: "error", source: "bench", message: "Comparison failed", detail: msg });
    }
  },

  runPopulation: async (o) => {
    const s = get().setup;
    set({ running: "population" });
    try {
      const res = await api.population({
        label: `${s.label} · population n=${o.nSubjects}`,
        model_id: s.modelId,
        drug_id: s.drugId,
        parameters: s.parameters,
        regimen: s.regimen,
        simulation_horizon_h: s.horizonH,
        n_output_points: Math.min(s.outputPoints, 401),
        n_subjects: o.nSubjects,
        seed: o.seed,
        random_effects: o.randomEffects,
        residual_error: o.residual,
        include_residual_error: o.includeResidual,
        patient_id: s.patientId,
        apply_patient_covariates: s.applyCovariates,
        percentiles: [5, 25, 50, 75, 95],
        reference_band_low: s.bandLow,
        reference_band_high: s.bandHigh,
        experiment_id: get().activeExperimentId,
        persist: true,
      });
      set({ population: res, running: null });
      const cm = res.exposure_distribution?.cmax;
      get().pushLog({
        level: res.result.n_failures ? "warn" : "ok",
        source: "population",
        message: `${res.result.n_subjects_simulated} virtual subjects simulated in ${res.result.wall_time_s.toFixed(
          2,
        )} s`,
        detail: cm
          ? `Cmax median ${cm.median.toPrecision(3)} (5th–95th ${cm.p5.toPrecision(3)}–${cm.p95.toPrecision(
              3,
            )}), between-subject CV ${cm.cv_percent.toFixed(0)}%${
              res.result.n_failures ? ` · ${res.result.n_failures} subject(s) failed` : ""
            }`
          : undefined,
      });
      void get().refreshExperiments();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      set({ running: null });
      get().pushLog({
        level: "error",
        source: "population",
        message: "Population simulation failed",
        detail: msg,
      });
    }
  },

  runSensitivity: async (o) => {
    const s = get().setup;
    set({ running: "sensitivity" });
    try {
      const res = await api.sensitivity({
        label: `${s.label} · ${o.method} SA`,
        model_id: s.modelId,
        drug_id: s.drugId,
        parameters: s.parameters,
        regimen: s.regimen,
        simulation_horizon_h: s.horizonH,
        method: o.method,
        metric: o.metric,
        targets: o.targets.map((name) => ({ name, relative_range: o.relativeRange })),
        morris_trajectories: o.morrisTrajectories,
        sobol_base_samples: o.sobolBaseSamples,
      });
      set({ sensitivity: res, running: null });
      const top = res.analysis.results[0];
      get().pushLog({
        level: "ok",
        source: "sensitivity",
        message: `${o.method} analysis of ${o.metric}: ${res.n_model_evaluations} model evaluations in ${res.wall_time_s.toFixed(
          2,
        )} s`,
        detail: top ? `Most influential parameter: ${top.parameter}` : undefined,
      });
      for (const n of res.notes) {
        get().pushLog({ level: "warn", source: "sensitivity", message: n });
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      set({ running: null });
      get().pushLog({
        level: "error",
        source: "sensitivity",
        message: "Sensitivity analysis failed",
        detail: msg,
      });
    }
  },
}));

/** Effective parameter values: library/schema defaults merged with overrides. */
export function effectiveParameters(
  spec: ModelSpec | null,
  drug: Drug | null,
  overrides: Record<string, number>,
  weightKg: number,
): Record<string, number> {
  if (!spec) return {};
  const out: Record<string, number> = {};
  for (const p of spec.parameters) out[p.name] = p.default;
  const block = drug?.pk_parameters?.[spec.model_id];
  if (block) {
    for (const [name, entry] of Object.entries(block.values)) {
      if (name.endsWith("_per_kg")) {
        const base = name.slice(0, -"_per_kg".length);
        if (base in out) out[base] = entry.value * weightKg;
      } else if (name in out) {
        out[name] = entry.value;
      }
    }
  }
  for (const [k, v] of Object.entries(overrides)) if (k in out) out[k] = v;
  return out;
}

/** Where a parameter's current value came from, for the inspector. */
export function parameterOriginFor(
  spec: ModelSpec | null,
  drug: Drug | null,
  overrides: Record<string, number>,
  name: string,
): { origin: import("./types").ParameterOrigin; entry?: import("./types").ParamEntry } {
  if (name in overrides) return { origin: "user" };
  const block = drug?.pk_parameters?.[spec?.model_id ?? ""];
  if (block) {
    const direct = block.values[name];
    if (direct) return { origin: direct.origin, entry: direct };
    const perKg = block.values[`${name}_per_kg`];
    if (perKg) return { origin: perKg.origin, entry: perKg };
  }
  return { origin: "illustrative" };
}
