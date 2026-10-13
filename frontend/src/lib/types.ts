/**
 * API types.
 *
 * These mirror the Pydantic contracts in backend/synthbody/schemas/api.py and
 * the registry serialisation. Hand-written rather than generated so the shapes
 * the UI actually depends on are explicit and reviewable.
 */

export type ValidationStatus =
  | "independently_validated"
  | "calibrated_only"
  | "structurally_verified"
  | "research_only"
  | "not_validated";

export type ParameterOrigin =
  | "measured"
  | "fitted"
  | "literature_fitted"
  | "derived"
  | "inferred"
  | "illustrative"
  | "user";

export type Route = "oral" | "iv_bolus" | "iv_infusion";
export type SolverMethod = "LSODA" | "BDF" | "Radau" | "RK45" | "DOP853";

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------
export interface Meta {
  software_name: string;
  software_version: string;
  engine_revision: string;
  classification: string;
  intended_use: string;
  not_intended_use: string[];
  regulatory_status: {
    fda_cleared: boolean;
    ce_marked: boolean;
    hipaa_compliant: boolean;
    gdpr_assessed: boolean;
    note: string;
  };
  counts: Record<string, number>;
}

export interface ParameterSchema {
  name: string;
  label: string;
  unit: string;
  default: number;
  minimum: number;
  maximum: number;
  description: string;
  scales_with_weight: boolean;
  allometric_exponent: number | null;
  step: number | null;
  group: string;
}

export interface ObservableSchema {
  name: string;
  label: string;
  unit: string;
  description: string;
  is_primary: boolean;
}

export interface ModelSpec {
  model_id: string;
  name: string;
  short_name: string;
  description: string;
  category: string;
  routes: Route[];
  parameters: ParameterSchema[];
  observables: ObservableSchema[];
  validation_status: ValidationStatus;
  validation_summary: string;
  reference_ids: string[];
  assumptions: string[];
  limitations: string[];
  dose_target_state: Record<string, number>;
  supports_population: boolean;
  supports_sensitivity: boolean;
  has_analytic_solution: boolean;
}

export interface ParamEntry {
  value: number;
  unit: string;
  origin: ParameterOrigin;
  description?: string;
  caveat?: string;
  corroboration?: string;
  note?: string;
  fitted_from_dataset?: string;
  fitted_from_subjects?: string[];
  between_subject_cv_percent?: number;
  reference_ids?: string[];
}

export interface Drug {
  drug_id: string;
  name: string;
  synonyms: string[];
  atc_class: string | null;
  therapeutic_area: string;
  mechanism_summary: string;
  primary_elimination: string;
  why_this_drug: string;
  is_synthetic_demonstration?: boolean;
  identifiers: Record<string, string | number>;
  default_model_id: string;
  available_model_ids: string[];
  validation_status: ValidationStatus;
  validation_note: string;
  pk_parameters: Record<
    string,
    { parameterisation: string; note: string; values: Record<string, ParamEntry> }
  >;
  pd_model:
    | null
    | {
        structure: string;
        response_variable: string;
        validation_status: string;
        values: Record<string, ParamEntry>;
        caveat: string;
        reference_ids: string[];
      };
  reference_concentration_band:
    | null
    | { low: number; high: number; unit: string; label: string; origin: string; caveat: string; reference_ids: string[] };
  covariates: Record<string, Record<string, unknown>>;
  default_regimen: {
    route: Route;
    dose_mg: number;
    n_doses: number;
    interval_h: number;
    simulation_horizon_h: number;
    note: string;
  };
  population_variability: {
    random_effects: { parameter: string; cv_percent: number; origin: string; note: string }[];
    residual_error: { proportional_cv_percent: number; additive_sd: number; origin: string; caveat?: string };
  };
  limitations: string[];
}

export interface Reference {
  id: string;
  citation: string;
  authors: string;
  year: number;
  journal: string;
  pmid: string | null;
  doi: string | null;
  url: string | null;
  kind: string;
  topics: string[];
  license_note: string;
  access_note: string;
  relevance: string;
  used_by_models?: string[];
  used_by_drugs?: string[];
}

export interface TissueInfo {
  name: string;
  volume_L: number;
  volume_fraction_of_body_weight: number;
  blood_flow_L_per_h: number;
  fraction_of_cardiac_output: number;
  f_water: number;
  f_lipid_total: number;
  f_neutral_lipid: number;
  f_phospholipid: number;
  f_protein: number;
  ph: number;
  composition_is_borrowed: boolean;
}

export interface PhysiologyResponse {
  provenance: Record<string, unknown>;
  reference_body_weight_kg: number;
  whole_body: Record<string, number | string>;
  tissues: TissueInfo[];
  portal_drained_tissues: string[];
}

export interface DatasetSubjectSummary {
  subject_id: string;
  n_observations: number;
  dose_mg: number;
  weight_kg: number | null;
  t_last_h: number;
  cmax_observed: number;
}

export interface DatasetSummary {
  dataset_id: string;
  name: string;
  drug: string;
  route: string;
  n_subjects: number;
  n_observations: number;
  concentration_unit: string;
  reference_ids: string[];
  license_note: string;
  provenance: string;
  description: string;
  known_limitations: string[];
  subjects: DatasetSubjectSummary[];
}

// ---------------------------------------------------------------------------
// Patients
// ---------------------------------------------------------------------------
export interface PatientInput {
  label: string;
  age_years: number;
  weight_kg: number;
  height_cm: number;
  sex: "male" | "female";
  serum_creatinine_mg_dL: number;
  albumin_g_dL: number;
  hepatic_function: "normal" | "mild_impairment" | "moderate_impairment" | "severe_impairment";
  smoking_status: "non_smoker" | "smoker";
  notes: string;
  is_synthetic: true;
}

export interface Patient extends Omit<PatientInput, "is_synthetic"> {
  id: number;
  is_synthetic: boolean;
  derived: Record<string, number | string | boolean>;
  created_at: string;
  updated_at: string;
}

export interface PatientPreview {
  derived: Record<string, number | string | boolean>;
  equations: { name: string; citation: string; formula: string; origin: string; note?: string; reference_id?: string }[];
  caveats: string[];
}

// ---------------------------------------------------------------------------
// Simulation
// ---------------------------------------------------------------------------
export interface Regimen {
  route: Route;
  dose_mg: number;
  n_doses: number;
  interval_h: number;
  start_h: number;
  infusion_duration_h: number;
}

export interface SolverSettings {
  method: SolverMethod | null;
  rtol: number;
  atol: number;
  max_step_h: number | null;
  check_tolerance_refinement: boolean;
}

export interface SimulationRequest {
  label: string;
  model_id: string;
  drug_id?: string | null;
  parameters?: Record<string, number>;
  regimen?: Partial<Regimen>;
  simulation_horizon_h: number;
  n_output_points?: number;
  patient_id?: number | null;
  apply_patient_covariates?: boolean;
  solver?: Partial<SolverSettings>;
  experiment_id?: number | null;
  persist?: boolean;
  reference_band_low?: number | null;
  reference_band_high?: number | null;
}

export interface SolverDiagnostics {
  method: string;
  rtol: number;
  atol: number;
  success: boolean;
  message: string;
  n_rhs_evaluations: number;
  n_jacobian_evaluations: number;
  n_lu_decompositions: number;
  n_steps_accepted: number;
  wall_time_s: number;
  mass_balance_relative_error: number | null;
  max_negative_state: number | null;
  tolerance_refinement_max_rel_diff: number | null;
  warnings: string[];
}

export interface NCAResult {
  cmax: number;
  tmax_h: number;
  cmin: number;
  tlast_h: number;
  clast: number;
  auc_0_last: number;
  auc_window_h: [number, number] | null;
  auc_0_inf: number | null;
  auc_extrap_percent: number | null;
  terminal_rate_constant_per_h: number | null;
  terminal_half_life_h: number | null;
  terminal_fit_r_squared: number | null;
  terminal_fit_n_points: number;
  clearance_L_per_h: number | null;
  volume_terminal_L: number | null;
  mean_residence_time_h: number | null;
  aumc_0_last: number;
  dose_mg: number | null;
  units: Record<string, string>;
  warnings: string[];
}

export interface AccumulationMetrics {
  n_complete_intervals: number;
  first_interval_auc: number | null;
  last_interval_auc: number | null;
  accumulation_ratio_auc: number | null;
  cmax_ss: number | null;
  cmin_ss: number | null;
  peak_trough_fluctuation_percent: number | null;
  average_concentration_ss: number | null;
}

export interface TimeInRange {
  hours_below: number;
  hours_within: number;
  hours_above: number;
  fraction_below: number;
  fraction_within: number;
  fraction_above: number;
  total_hours: number;
  band_low: number;
  band_high: number;
  band_origin?: string;
  band_caveat?: string;
}

export interface ProvenanceParameter {
  name: string;
  value: number;
  unit: string;
  origin: ParameterOrigin;
  description: string;
  reference_ids: string[];
  population_range: number[] | null;
  notes: string;
}

export interface Provenance {
  model_id: string;
  model_name: string;
  model_version: string;
  software_name: string;
  software_version: string;
  engine_revision: string;
  schema_version: string;
  timestamp_utc: string;
  python_version: string;
  platform: string;
  parameters: ProvenanceParameter[];
  inputs: Record<string, unknown>;
  assumptions: string[];
  limitations: string[];
  reference_ids: string[];
  validation_status: ValidationStatus;
  validation_summary: string;
  solver: SolverDiagnostics | null;
  random_seed: number | null;
  input_hash: string;
  record_hash: string;
}

export interface CovariateApplication {
  parameter: string;
  multiplier: number;
  basis: string;
  origin: ParameterOrigin;
  reference_ids: string[];
}

export interface SimulationResponse {
  simulation_id: number | null;
  label: string;
  model_id: string;
  model_name: string;
  drug_id: string | null;
  time_h: number[];
  observables: Record<string, number[]>;
  observable_units: Record<string, string>;
  primary_observable: string;
  states: Record<string, number[]>;
  nca: NCAResult;
  accumulation: AccumulationMetrics | null;
  time_in_range: TimeInRange | null;
  diagnostics: SolverDiagnostics;
  provenance: Provenance;
  covariates_applied: CovariateApplication[];
  effective_parameters: Record<string, number>;
  validation_status: ValidationStatus;
  validation_summary: string;
  disclaimer: string;
}

export interface ExposureRow {
  label: string;
  model_id: string;
  drug_id: string | null;
  total_dose_mg: number;
  dose_mg: number;
  n_doses: number;
  interval_h: number;
  route: string;
  cmax: number;
  tmax_h: number;
  cmin: number;
  auc_0_last: number;
  auc_window_h: [number, number] | null;
  auc_0_inf: number | null;
  terminal_half_life_h: number | null;
  cmax_ratio_vs_baseline: number | null;
  auc_ratio_vs_baseline: number | null;
  fraction_time_in_band: number | null;
  fraction_time_above_band: number | null;
  accumulation_ratio_auc: number | null;
  peak_trough_fluctuation_percent: number | null;
  solver_warnings: number;
  validation_status: ValidationStatus;
}

export interface ComparisonResponse {
  label: string;
  scenarios: SimulationResponse[];
  exposure_table: ExposureRow[];
  relative_to: string;
  notes: string[];
}

// ---------------------------------------------------------------------------
// Population
// ---------------------------------------------------------------------------
export interface PopulationRequest {
  label: string;
  model_id: string;
  drug_id?: string | null;
  parameters?: Record<string, number>;
  regimen?: Partial<Regimen>;
  simulation_horizon_h: number;
  n_output_points?: number;
  n_subjects: number;
  seed: number;
  random_effects: { parameter: string; cv_percent: number }[];
  correlations?: [string, string, number][];
  residual_error?: { proportional_cv_percent: number; additive_sd: number };
  include_residual_error?: boolean;
  patient_id?: number | null;
  apply_patient_covariates?: boolean;
  percentiles?: number[];
  reference_band_low?: number | null;
  reference_band_high?: number | null;
  experiment_id?: number | null;
  persist?: boolean;
}

export interface MetricSummary {
  n: number;
  mean: number;
  sd: number;
  cv_percent: number;
  median: number;
  p5: number;
  p95: number;
  min: number;
  max: number;
  geometric_mean: number;
}

export interface PopulationResult {
  n_subjects_requested: number;
  n_subjects_simulated: number;
  n_failures: number;
  failures: { subject: number; parameters: Record<string, number>; error: string }[];
  n_parameter_draws_truncated: number;
  seed: number;
  observable: string;
  time_h: number[];
  typical_value_profile: number[];
  mean: number[];
  structural_percentiles: Record<string, number[]>;
  observation_percentiles?: Record<string, number[]>;
  percentile_levels: number[];
  residual_error_included: boolean;
  random_effects: { parameter: string; cv_percent: number; sigma: number }[];
  interpretation: string;
  subject_metrics?: Record<string, number>[];
  metric_summary?: Record<string, MetricSummary>;
  subject_parameters?: Record<string, number>[];
  wall_time_s: number;
}

export interface PopulationResponse {
  simulation_id: number | null;
  label: string;
  model_id: string;
  drug_id: string | null;
  result: PopulationResult;
  exposure_distribution: Record<string, MetricSummary>;
  target_attainment: Record<string, number | string> | null;
  provenance: Provenance;
  validation_status: ValidationStatus;
  disclaimer: string;
}

// ---------------------------------------------------------------------------
// Sensitivity
// ---------------------------------------------------------------------------
export interface SensitivityRequest {
  label: string;
  model_id: string;
  drug_id?: string | null;
  parameters?: Record<string, number>;
  regimen?: Partial<Regimen>;
  simulation_horizon_h: number;
  method: "local" | "morris" | "sobol";
  metric: "auc_0_last" | "cmax" | "tmax" | "cmin" | "auc_0_inf" | "t_half";
  targets: { name: string; nominal?: number; low?: number; high?: number; relative_range?: number }[];
  morris_trajectories?: number;
  sobol_base_samples?: number;
  seed?: number;
}

export interface SensitivityRow {
  parameter: string;
  unit: string;
  normalised_sensitivity?: number | null;
  nominal?: number;
  step_used_relative?: number;
  step_halving_relative_change?: number | null;
  description?: string;
  note?: string;
  mu_star?: number;
  mu?: number;
  sigma?: number;
  mu_star_conf?: number;
  S1?: number;
  S1_conf?: number;
  ST?: number;
  ST_conf?: number;
  interaction_strength?: number;
}

export interface SensitivityResponse {
  label: string;
  model_id: string;
  metric: string;
  method: string;
  analysis: {
    method: string;
    results: SensitivityRow[];
    interpretation: string;
    baseline_objective?: number;
    n_model_evaluations?: number;
    sum_first_order?: number;
    output_variance?: number;
    trajectories?: number;
    base_samples?: number;
    seed?: number;
  };
  nominal_parameters: Record<string, number>;
  n_model_evaluations: number;
  wall_time_s: number;
  notes: string[];
}

// ---------------------------------------------------------------------------
// Experiments & stored runs
// ---------------------------------------------------------------------------
export interface Experiment {
  id: number;
  name: string;
  description: string;
  tags: string[];
  n_simulations: number;
  created_at: string;
  updated_at: string;
}

export interface SimulationSummary {
  id: number;
  experiment_id: number | null;
  patient_id: number | null;
  label: string;
  model_id: string;
  drug_id: string | null;
  kind: string;
  input_hash: string;
  record_hash: string;
  validation_status: ValidationStatus;
  software_version: string;
  engine_revision: string;
  solver_success: boolean;
  solver_warning_count: number;
  wall_time_s: number;
  created_at: string;
  key_metrics: Record<string, number | null>;
}

export interface StoredSimulation {
  id: number;
  experiment_id: number | null;
  patient_id: number | null;
  label: string;
  model_id: string;
  drug_id: string | null;
  kind: string;
  request: SimulationRequest;
  provenance: Provenance;
  result: Record<string, unknown>;
  input_hash: string;
  record_hash: string;
  validation_status: ValidationStatus;
  created_at: string;
  disclaimer: string;
}

export interface ReproduceResult {
  simulation_id: number;
  input_hash_original: string;
  input_hash_reproduced: string;
  input_hash_matches: boolean;
  engine_revision_original: string;
  engine_revision_now: string;
  engine_revision_matches: boolean;
  max_absolute_curve_difference: number | null;
  bitwise_identical: boolean | null;
  verdict: string;
  result: SimulationResponse;
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------
export interface AgreementMetrics {
  n: number;
  n_excluded_nonpositive: number;
  rmse: number;
  nrmse_percent: number;
  mae: number;
  mean_error: number;
  mean_percent_error: number;
  mean_absolute_percent_error: number;
  median_absolute_percent_error: number;
  average_fold_error: number | null;
  absolute_average_fold_error: number | null;
  fraction_within_1_25_fold: number | null;
  fraction_within_1_5_fold: number | null;
  fraction_within_2_fold: number | null;
  pearson_r: number | null;
  r_squared_vs_identity: number;
  concordance_correlation: number | null;
  observed_mean: number;
  predicted_mean: number;
  units: string;
  notes: string[];
}

export interface ValidationProfile {
  subject_id: string;
  set: "calibration" | "held_out";
  time_h: number[];
  predicted: number[];
  observed_time_h: number[];
  observed: number[];
  dose_mg: number;
  weight_kg: number | null;
}

export interface ValidationReport {
  target_id: string;
  dataset_id: string;
  dataset_name: string;
  model_id: string;
  model_label: string;
  protocol: Record<string, string | boolean>;
  calibration_subject_ids: string[];
  held_out_subject_ids: string[];
  typical_parameters: Record<string, number>;
  between_subject_cv_percent: Record<string, number>;
  individual_estimates: Record<string, Record<string, number>>;
  individual_rse_percent: Record<string, Record<string, number | null>>;
  calibration_metrics: AgreementMetrics;
  held_out_metrics: AgreementMetrics;
  held_out_residuals: {
    residuals: number[];
    weighted_residuals: number[];
    proportional_residuals: (number | null)[];
    predicted: number[];
    observed: number[];
    residual_sd: number;
    residual_mean: number;
    spearman_abs_residual_vs_predicted: number | null;
    interpretation: string;
  };
  per_subject_held_out: Record<string, number | string | null>[];
  observed_vs_predicted: Record<string, number[]>;
  profiles: ValidationProfile[];
  estimation_note: string;
  interpretation: string;
  software_version: string;
  engine_revision: string;
  warnings: string[];
}

export interface ValidationTargets {
  targets: {
    target_id: string;
    dataset_id: string;
    model_id: string;
    model_label: string;
    estimated_parameters: string[];
    notes: string;
  }[];
  protocol: { description: string; why_it_matters: string };
}

export interface PbpkStructuralCheck {
  check: string;
  inputs: Record<string, number | string>;
  predicted_vss_L: number;
  predicted_vss_L_per_kg: number;
  literature_comparison_L_per_kg: number;
  fold_difference: number;
  passes_2_fold: boolean;
  method: string;
  cardiac_output_L_per_h: number;
  hepatic_blood_clearance_L_per_h: number;
  partition_coefficients: Record<string, number>;
  tissue_volumes_L: Record<string, number>;
  tissue_flows_L_per_h: Record<string, number>;
  honest_scope: string;
  validation_status: string;
  reference_ids: string[];
}

export interface AuditEntry {
  id: number;
  at: string;
  action: string;
  entity: string;
  entity_id: string | null;
  detail: Record<string, unknown>;
  software_version: string;
}

// ---------------------------------------------------------------------------
// Benchmarks
// ---------------------------------------------------------------------------
export interface FoldErrorSummary {
  available: boolean;
  reason?: string;
  n: number;
  aafe: number;
  afe: number;
  median_fold_error: number;
  max_fold_error: number;
  fraction_within_1_25_fold: number;
  fraction_within_1_5_fold: number;
  fraction_within_2_fold: number;
  fraction_within_3_fold: number;
  fraction_over_2_fold_error: number;
  predicted: number[];
  observed: number[];
  fold_errors: number[];
}

export interface BenchmarkCaseResult {
  case_id: string;
  drug_name: string;
  dose_mg: number;
  predicted_auc: number;
  predicted_cmax: number;
  predicted_tmax_h: number;
  predicted_fabs: number;
  observed_auc: number | null;
  observed_cmax: number | null;
  observed_tmax_h: number | null;
  mass_balance_error: number;
  solver_warnings: string[];
  time_h: number[];
  concentration: number[];
}

export interface SweepPoint {
  peff_cm_per_s: number;
  mean_predicted_fabs: number;
  evaluation: { n_administrations: number; metrics: Record<string, FoldErrorSummary> };
  case_results: BenchmarkCaseResult[];
}

export interface PhyschemEntry {
  value: number;
  origin: ParameterOrigin;
  source: string;
}

export interface TheophyllineBenchmark {
  benchmark_id: string;
  software_version: string;
  engine_revision: string;
  dataset: DatasetSummary;
  held_out_subject_ids: string[];
  calibration_subject_ids: string[];
  disposition_source: { cl_per_kg_L_per_h: number; v_per_kg_L: number; note: string };
  fitted_ka_for_reference_per_h: number;
  physchem: Record<string, PhyschemEntry>;
  peff_sweep: SweepPoint[];
  prespecified_peff_cm_per_s: number;
  headline_result: SweepPoint | null;
  headline_note: string;
  best_by_cmax_aafe: SweepPoint | null;
  interpretation: string;
  honest_scope: string;
}

export interface OrbitoComparison {
  software_version: string;
  engine_revision: string;
  published_results: Record<string, { auc: number; cmax: number; tmax: number }>;
  published_results_provenance: string;
  access_record: Record<string, string>;
  case_library: { status: string; n_cases?: number; [k: string]: unknown };
  comparison_available: boolean;
  refusal_reason?: string;
  what_would_be_needed?: string[];
  how_to_supply?: string;
  n_administrations?: number;
  equivalent_experiment_count?: boolean;
  synthbody_results?: Record<string, number>;
  comparability_caveat?: string;
}

export interface GIPhysiology {
  provenance: Record<string, unknown>;
  state: string;
  stomach: Record<string, number>;
  small_intestine: {
    n_compartments: number;
    total_transit_min: number;
    transit_rate_per_h: number;
    total_volume_mL: number;
    compartment_volume_mL: number;
    length_cm: number;
    radius_cm: number;
    ph_profile: number[];
    bile_salt_mM: number[];
  };
  colon: Record<string, number>;
  raw_entries: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Oral PBPK concentration-time validation
//
// The first test of the PBPK module against observed human plasma data, as
// opposed to the single-scalar Vss structural check. Shapes mirror
// `synthbody.engine.analysis.pbpk_validation`.
// ---------------------------------------------------------------------------
export interface PbpkSubjectPrediction {
  subject_id: string;
  weight_kg: number;
  dose_mg: number;
  time_h: number[];
  observed_mg_per_L: number[];
  predicted_mg_per_L: number[];
  predicted_fabs: number;
  predicted_f_hepatic: number;
  hepatic_clint_L_per_h: number;
  predicted_vss_L_per_kg: number;
  observed_cmax: number;
  predicted_cmax: number;
  observed_tmax_h: number;
  predicted_tmax_h: number;
  observed_auc: number;
  predicted_auc: number;
  mass_balance_relative_error: number;
}

export interface PbpkFoldSummary {
  aafe: number;
  afe: number;
  fraction_within_2_fold: number;
  n: number;
}

export interface PbpkOralValidation {
  model_id: string;
  protocol: string;
  inputs: {
    physchem: Record<string, { value: number; origin: ParameterOrigin; source: string }>;
    peff_cm_per_s: number;
    particle_radius_um: number;
    renal_fraction_of_clearance: number;
    prespecified: boolean;
  };
  calibration_subject_ids: string[];
  held_out_subject_ids: string[];
  calibrated_clearance_L_per_h_per_kg: number;
  predictions: PbpkSubjectPrediction[];
  pointwise_metrics: Record<string, number>;
  metric_summary: Record<string, PbpkFoldSummary>;
  comparison_to_empirical_model: Record<string, unknown>;
  interpretation: string;
  caveats: string[];
}
