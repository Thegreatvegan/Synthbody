"""
Typed API contracts.

These Pydantic models are the single source of truth for the HTTP interface.
Validation lives here so a malformed request is rejected before it reaches the
solver, and so the generated OpenAPI schema is accurate enough for the frontend
to be written against.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Route = Literal["oral", "iv_bolus", "iv_infusion"]
SolverMethod = Literal["LSODA", "BDF", "Radau", "RK45", "DOP853"]


# ---------------------------------------------------------------------------
# Virtual patient
# ---------------------------------------------------------------------------
class VirtualPatientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field("Virtual subject", min_length=1, max_length=160)
    age_years: float = Field(35.0, gt=0, le=120)
    weight_kg: float = Field(70.0, ge=1, le=400)
    height_cm: float = Field(175.0, ge=30, le=260)
    sex: Literal["female", "male"] = "male"
    serum_creatinine_mg_dL: float = Field(0.9, ge=0.1, le=25)
    albumin_g_dL: float = Field(4.3, ge=1, le=7)
    hepatic_function: Literal[
        "normal", "mild_impairment", "moderate_impairment", "severe_impairment"
    ] = "normal"
    smoking_status: Literal["non_smoker", "smoker"] = "non_smoker"
    notes: str = Field("", max_length=4000)
    is_synthetic: Literal[True] = Field(
        True,
        description=(
            "Always true. SYNTHBODY stores hypothetical simulated subjects only. "
            "The API rejects any attempt to set this false."
        ),
    )


class VirtualPatientOut(BaseModel):
    id: int
    label: str
    is_synthetic: bool
    age_years: float
    weight_kg: float
    height_cm: float
    sex: str
    serum_creatinine_mg_dL: float
    albumin_g_dL: float
    hepatic_function: str
    smoking_status: str
    notes: str
    derived: dict[str, Any]
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Dosing
# ---------------------------------------------------------------------------
class RegimenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: Route = "oral"
    dose_mg: float = Field(300.0, gt=0, le=1_000_000)
    n_doses: int = Field(1, ge=1, le=2000)
    interval_h: float = Field(12.0, gt=0, le=10_000)
    start_h: float = Field(0.0, ge=0)
    infusion_duration_h: float = Field(0.0, ge=0, le=10_000)

    @model_validator(mode="after")
    def _check(self) -> "RegimenIn":
        if self.route == "iv_infusion":
            if self.infusion_duration_h <= 0:
                raise ValueError("An IV infusion requires infusion_duration_h > 0.")
            if self.n_doses > 1 and self.infusion_duration_h > self.interval_h:
                raise ValueError(
                    "Infusion duration cannot exceed the dosing interval for repeated infusions."
                )
        return self

    @property
    def total_dose_mg(self) -> float:
        return self.dose_mg * self.n_doses


class SolverSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: SolverMethod | None = None
    rtol: float = Field(1e-8, gt=0, le=1e-2)
    atol: float = Field(1e-10, gt=0, le=1e-2)
    max_step_h: float | None = Field(None, gt=0)
    check_tolerance_refinement: bool = True


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field("Untitled run", min_length=1, max_length=200)
    model_id: str = Field(..., min_length=1)
    drug_id: str | None = None
    parameters: dict[str, float] = Field(default_factory=dict)
    regimen: RegimenIn = Field(default_factory=RegimenIn)
    simulation_horizon_h: float = Field(48.0, gt=0, le=24 * 400)
    n_output_points: int = Field(601, ge=11, le=20_000)
    patient_id: int | None = None
    apply_patient_covariates: bool = Field(
        True,
        description=(
            "When a patient is attached, scale clearance and volume by that patient's "
            "covariates. Each applied adjustment is recorded in the provenance with its "
            "evidence origin, including when that origin is `illustrative`."
        ),
    )
    solver: SolverSettingsIn = Field(default_factory=SolverSettingsIn)
    experiment_id: int | None = None
    persist: bool = True
    reference_band_low: float | None = Field(None, ge=0)
    reference_band_high: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _check(self) -> "SimulationRequest":
        if self.reference_band_low is not None and self.reference_band_high is not None:
            if self.reference_band_high <= self.reference_band_low:
                raise ValueError("reference_band_high must exceed reference_band_low.")
        last_dose_end = self.regimen.start_h + max(self.regimen.n_doses - 1, 0) * self.regimen.interval_h
        if last_dose_end >= self.simulation_horizon_h:
            raise ValueError(
                f"The last dose starts at {last_dose_end:g} h but the simulation horizon is "
                f"{self.simulation_horizon_h:g} h. Extend the horizon or reduce the dose count."
            )
        return self


class CovariateApplicationOut(BaseModel):
    parameter: str
    multiplier: float
    basis: str
    origin: str
    reference_ids: list[str]


class SolverDiagnosticsOut(BaseModel):
    method: str
    rtol: float
    atol: float
    success: bool
    message: str
    n_rhs_evaluations: int
    n_jacobian_evaluations: int
    n_lu_decompositions: int
    n_steps_accepted: int
    wall_time_s: float
    mass_balance_relative_error: float | None
    max_negative_state: float | None
    tolerance_refinement_max_rel_diff: float | None
    warnings: list[str]


class SimulationResponse(BaseModel):
    simulation_id: int | None
    label: str
    model_id: str
    model_name: str
    drug_id: str | None
    time_h: list[float]
    observables: dict[str, list[float]]
    observable_units: dict[str, str]
    primary_observable: str
    states: dict[str, list[float]]
    nca: dict[str, Any]
    accumulation: dict[str, Any] | None
    time_in_range: dict[str, Any] | None
    diagnostics: SolverDiagnosticsOut
    provenance: dict[str, Any]
    covariates_applied: list[CovariateApplicationOut]
    effective_parameters: dict[str, float]
    validation_status: str
    validation_summary: str
    disclaimer: str


# ---------------------------------------------------------------------------
# Scenario comparison
# ---------------------------------------------------------------------------
class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field("Scenario comparison", max_length=200)
    scenarios: list[SimulationRequest] = Field(..., min_length=2, max_length=12)
    experiment_id: int | None = None
    persist: bool = False

    @field_validator("scenarios")
    @classmethod
    def _distinct_labels(cls, v: list[SimulationRequest]) -> list[SimulationRequest]:
        labels = [s.label for s in v]
        if len(set(labels)) != len(labels):
            raise ValueError("Each scenario needs a distinct label so results can be told apart.")
        return v


class ComparisonResponse(BaseModel):
    label: str
    scenarios: list[SimulationResponse]
    exposure_table: list[dict[str, Any]]
    relative_to: str
    notes: list[str]


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------
class RandomEffectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parameter: str
    cv_percent: float = Field(..., ge=0, le=500)
    lower_bound: float | None = Field(None, gt=0)
    upper_bound: float | None = Field(None, gt=0)


class ResidualErrorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proportional_cv_percent: float = Field(0.0, ge=0, le=200)
    additive_sd: float = Field(0.0, ge=0)


class PopulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field("Population simulation", max_length=200)
    model_id: str
    drug_id: str | None = None
    parameters: dict[str, float] = Field(default_factory=dict)
    regimen: RegimenIn = Field(default_factory=RegimenIn)
    simulation_horizon_h: float = Field(48.0, gt=0, le=24 * 400)
    n_output_points: int = Field(241, ge=11, le=5000)
    n_subjects: int = Field(200, ge=2, le=5000)
    seed: int = Field(20261012, ge=0, le=2**31 - 1)
    random_effects: list[RandomEffectIn] = Field(default_factory=list)
    correlations: list[tuple[str, str, float]] = Field(default_factory=list)
    residual_error: ResidualErrorIn = Field(default_factory=ResidualErrorIn)
    include_residual_error: bool = False
    patient_id: int | None = None
    apply_patient_covariates: bool = True
    percentiles: list[float] = Field(default=[5.0, 25.0, 50.0, 75.0, 95.0])
    reference_band_low: float | None = Field(None, ge=0)
    reference_band_high: float | None = Field(None, ge=0)
    experiment_id: int | None = None
    persist: bool = True

    @field_validator("percentiles")
    @classmethod
    def _pct(cls, v: list[float]) -> list[float]:
        if not v:
            raise ValueError("At least one percentile is required.")
        if any(not 0.0 <= p <= 100.0 for p in v):
            raise ValueError("Percentiles must lie in [0, 100].")
        return sorted(set(v))

    @model_validator(mode="after")
    def _check(self) -> "PopulationRequest":
        if not self.random_effects:
            raise ValueError(
                "A population simulation needs at least one random effect, otherwise every "
                "subject is identical and the percentiles are meaningless."
            )
        return self


class PopulationResponse(BaseModel):
    simulation_id: int | None
    label: str
    model_id: str
    drug_id: str | None
    result: dict[str, Any]
    exposure_distribution: dict[str, Any]
    target_attainment: dict[str, Any] | None
    provenance: dict[str, Any]
    validation_status: str
    disclaimer: str


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------
class SensitivityParameterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    nominal: float | None = None
    low: float | None = None
    high: float | None = None
    relative_range: float | None = Field(
        0.5, gt=0, le=10, description="If low/high are omitted, use nominal*(1-+r)."
    )


class SensitivityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field("Sensitivity analysis", max_length=200)
    model_id: str
    drug_id: str | None = None
    parameters: dict[str, float] = Field(default_factory=dict)
    regimen: RegimenIn = Field(default_factory=RegimenIn)
    simulation_horizon_h: float = Field(48.0, gt=0, le=24 * 400)
    method: Literal["local", "morris", "sobol"] = "local"
    metric: Literal["auc_0_last", "cmax", "tmax", "cmin", "auc_0_inf", "t_half"] = "auc_0_last"
    targets: list[SensitivityParameterIn] = Field(..., min_length=1, max_length=20)
    morris_trajectories: int = Field(48, ge=4, le=1000)
    sobol_base_samples: int = Field(256, ge=16, le=8192)
    seed: int = Field(20261012, ge=0, le=2**31 - 1)
    experiment_id: int | None = None
    persist: bool = False


class SensitivityResponse(BaseModel):
    label: str
    model_id: str
    metric: str
    method: str
    analysis: dict[str, Any]
    nominal_parameters: dict[str, float]
    n_model_evaluations: int
    wall_time_s: float
    notes: list[str]


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------
class ExperimentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=8000)
    tags: list[str] = Field(default_factory=list, max_length=40)


class ExperimentOut(BaseModel):
    id: int
    name: str
    description: str
    tags: list[str]
    n_simulations: int
    created_at: str
    updated_at: str


class SimulationSummaryOut(BaseModel):
    id: int
    experiment_id: int | None
    patient_id: int | None
    label: str
    model_id: str
    drug_id: str | None
    kind: str
    input_hash: str
    record_hash: str
    validation_status: str
    software_version: str
    engine_revision: str
    solver_success: bool
    solver_warning_count: int
    wall_time_s: float
    created_at: str
    key_metrics: dict[str, Any]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulation_ids: list[int] = Field(..., min_length=1, max_length=50)
    title: str = Field("SYNTHBODY research report", max_length=300)
    author: str = Field("", max_length=200)
    include_validation: bool = True
    include_references: bool = True
    include_limitations: bool = True
    format: Literal["markdown", "json"] = "markdown"
