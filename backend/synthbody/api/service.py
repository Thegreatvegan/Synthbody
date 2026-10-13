"""
Simulation service: the layer between HTTP and the numerical engine.

Responsibilities:
  * resolve a request into a concrete model instance with effective parameters
  * apply virtual-patient covariates, recording every adjustment and its
    evidence origin
  * run the engine, compute exposure metrics, assemble provenance
  * persist when asked

The engine knows nothing about any of this. That separation is what lets the
test suite exercise the numerics without a database or a web server.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from synthbody.config import get_settings
from synthbody.db.models import AuditLogRow, SimulationRow, VirtualPatientRow
from synthbody.engine.analysis.nca import accumulation_metrics, compute_nca, time_within_range
from synthbody.engine.analysis.population import (
    PopulationSpec,
    RandomEffect,
    ResidualError,
    run_population_simulation,
)
from synthbody.engine.analysis.sensitivity import (
    ParameterSpec,
    local_sensitivity,
    morris_screening,
    sobol_indices,
)
from synthbody.engine.core import BaseModel, DoseEvent, expand_regimen, simulate
from synthbody.engine.physiology.covariates import (
    CovariateEffect,
    HepaticFunction,
    Sex,
    SmokingStatus,
    VirtualPatient,
    allometric_clearance_factor,
    allometric_volume_factor,
    hepatic_clearance_factor,
    smoking_cyp1a2_clearance_factor,
)
from synthbody.engine.provenance import ParameterOrigin, ParameterRecord
from synthbody.engine.registry import ModelSpec, build_model, get_drug, get_model_spec
from synthbody.schemas.api import (
    ComparisonRequest,
    PopulationRequest,
    RegimenIn,
    SensitivityRequest,
    SimulationRequest,
)
from synthbody.version import ENGINE_REVISION, SOFTWARE_VERSION

log = logging.getLogger(__name__)
settings = get_settings()

DISCLAIMER = (
    "SYNTHBODY is research simulation software, not a medical device. Output describes the "
    "behaviour of a mathematical model applied to a hypothetical simulated subject. It is not "
    "a diagnosis, not a treatment recommendation, and not a prediction about any real person. "
    "Check the validation status of the model before relying on any number."
)


class ServiceError(ValueError):
    """A request that cannot be fulfilled for a reason the caller should see."""


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
def row_to_patient(row: VirtualPatientRow) -> VirtualPatient:
    return VirtualPatient(
        label=row.label,
        age_years=row.age_years,
        weight_kg=row.weight_kg,
        height_cm=row.height_cm,
        sex=Sex(row.sex),
        serum_creatinine_mg_dL=row.serum_creatinine_mg_dL,
        albumin_g_dL=row.albumin_g_dL,
        hepatic_function=HepaticFunction(row.hepatic_function),
        smoking_status=SmokingStatus(row.smoking_status),
        notes=row.notes,
        is_synthetic=True,
    )


def load_patient(session: Session, patient_id: int | None) -> VirtualPatient | None:
    if patient_id is None:
        return None
    row = session.get(VirtualPatientRow, patient_id)
    if row is None:
        raise ServiceError(f"No virtual patient with id {patient_id}.")
    return row_to_patient(row)


# ---------------------------------------------------------------------------
# Parameter resolution
# ---------------------------------------------------------------------------
@dataclass
class ResolvedModel:
    model: BaseModel
    effective_parameters: dict[str, float]
    base_parameters: dict[str, float]
    covariates: list[CovariateEffect]
    spec: Any
    drug: dict[str, Any] | None


def _drug_defaults(drug_id: str | None, model_id: str) -> dict[str, float]:
    """Pull a drug's stored parameters for a model, if the library has them."""
    if not drug_id:
        return {}
    drug = get_drug(drug_id)
    block = (drug.get("pk_parameters") or {}).get(model_id)
    if not block:
        return {}
    out: dict[str, float] = {}
    for name, entry in (block.get("values") or {}).items():
        out[name] = float(entry["value"])
    # Per-kilogram parameterisations are stored as CL_per_kg / V_per_kg; the model
    # wants CL and V. Resolution happens in _resolve once weight is known.
    return out


def _resolve_per_kg(params: dict[str, float], weight_kg: float) -> dict[str, float]:
    """Expand *_per_kg parameters into their absolute counterparts."""
    out = dict(params)
    for key in list(out):
        if key.endswith("_per_kg"):
            base = key[: -len("_per_kg")]
            out[base] = out.pop(key) * weight_kg
    return out


def resolve_model(
    *,
    model_id: str,
    drug_id: str | None,
    parameters: dict[str, float],
    patient: VirtualPatient | None,
    apply_covariates: bool,
) -> ResolvedModel:
    spec = get_model_spec(model_id)
    drug = get_drug(drug_id) if drug_id else None

    weight = patient.weight_kg if patient else 70.0
    merged = _resolve_per_kg(_drug_defaults(drug_id, model_id), weight)
    # Explicit request parameters always win over library defaults.
    merged.update(parameters)

    # Fill any remaining gaps from the model schema.
    schema_names = {p.name for p in spec.parameters}
    base = {p.name: p.default for p in spec.parameters}
    base.update({k: v for k, v in merged.items() if k in schema_names})

    unknown = set(merged) - schema_names
    if unknown:
        raise ServiceError(
            f"Model {model_id!r} has no parameter(s) {sorted(unknown)}. "
            f"Expected one of: {sorted(schema_names)}"
        )

    effective = dict(base)
    applied: list[CovariateEffect] = []

    if patient and apply_covariates:
        # PBPK takes body weight directly; scaling its CL/V on top would double count.
        if "BW" in schema_names:
            effective["BW"] = patient.weight_kg
        # Only apply size scaling when the drug library did NOT already supply a
        # per-kilogram parameterisation (which has consumed weight already).
        per_kg_used = any(k.endswith("_per_kg") for k in _drug_defaults(drug_id, model_id))
        if not per_kg_used and "BW" not in schema_names:
            cl_f = allometric_clearance_factor(patient.weight_kg)
            v_f = allometric_volume_factor(patient.weight_kg)
            applied.extend([cl_f, v_f])

        if drug:
            cov = drug.get("covariates") or {}
            if "smoking_status" in cov:
                applied.append(smoking_cyp1a2_clearance_factor(patient.smoking_status))
            if "hepatic_function" in cov:
                applied.append(hepatic_clearance_factor(patient.hepatic_function))

        # Apply multipliers to whichever clearance/volume parameters the model has.
        cl_mult = _product(applied, "CL")
        v_mult = _product(applied, "V")
        for name in ("CL", "Vmax", "CLint_H", "Q"):
            if name in effective and cl_mult != 1.0:
                effective[name] *= cl_mult
        for name in ("V", "V1", "V2"):
            if name in effective and v_mult != 1.0:
                effective[name] *= v_mult

    model = build_model(model_id, effective)
    return ResolvedModel(
        model=model,
        effective_parameters=effective,
        base_parameters=base,
        covariates=applied,
        spec=spec,
        drug=drug,
    )


def _product(effects: list[CovariateEffect], parameter: str) -> float:
    out = 1.0
    for e in effects:
        if e.parameter == parameter:
            out *= e.multiplier
    return out


def retag_parameter_origins(
    records: list[ParameterRecord],
    *,
    drug: dict[str, Any] | None,
    model_id: str,
    user_supplied: dict[str, float],
) -> list[ParameterRecord]:
    """Correct the provenance origin of each parameter to where its value came from.

    A model instance cannot know this: it receives plain numbers through its
    constructor and tags them USER. But the value may have come from the drug
    library as a fitted estimate, or from the model schema as a SYNTHBODY
    default. Leaving everything as USER both understates the evidence behind a
    fitted parameter and hides that a default is merely illustrative, which is
    exactly the confusion the origin tags exist to prevent.

    Derived parameters keep their DERIVED tag; the model computed them.
    """
    block = (drug or {}).get("pk_parameters", {}).get(model_id) or {}
    lib: dict[str, dict[str, Any]] = block.get("values") or {}

    out: list[ParameterRecord] = []
    for rec in records:
        if rec.origin is not ParameterOrigin.USER:
            out.append(rec)
            continue

        if rec.name in user_supplied:
            out.append(rec)
            continue

        entry = lib.get(rec.name) or lib.get(f"{rec.name}_per_kg")
        if entry is not None:
            notes = [entry.get("caveat") or "", entry.get("corroboration") or "", entry.get("note") or ""]
            if entry.get("fitted_from_dataset"):
                subjects = entry.get("fitted_from_subjects") or []
                notes.append(
                    f"Estimated from dataset '{entry['fitted_from_dataset']}'"
                    + (f" using subjects {', '.join(subjects)}." if subjects else ".")
                )
            cv = entry.get("between_subject_cv_percent")
            if cv is not None:
                notes.append(f"Between-subject variability: {cv}% CV.")
            out.append(
                ParameterRecord(
                    name=rec.name,
                    value=rec.value,
                    unit=rec.unit,
                    origin=ParameterOrigin(entry["origin"]),
                    description=entry.get("description") or rec.description,
                    reference_ids=list(entry.get("reference_ids") or []),
                    notes=" ".join(n for n in notes if n).strip(),
                )
            )
            continue

        # Neither operator-supplied nor in the library: it is a schema default,
        # which is a SYNTHBODY choice and therefore not evidence.
        out.append(
            ParameterRecord(
                name=rec.name,
                value=rec.value,
                unit=rec.unit,
                origin=ParameterOrigin.ILLUSTRATIVE,
                description=rec.description,
                reference_ids=list(rec.reference_ids),
                notes=(
                    rec.notes
                    + " Value is the model's schema default, chosen by SYNTHBODY for "
                    "demonstrability rather than taken from a source."
                ).strip(),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Dosing
# ---------------------------------------------------------------------------
def build_doses(regimen: RegimenIn, model_id: str) -> list[DoseEvent]:
    spec = get_model_spec(model_id)
    if regimen.route not in spec.routes:
        raise ServiceError(
            f"Model {model_id!r} does not support the {regimen.route!r} route. "
            f"Supported: {list(spec.routes)}"
        )
    target = spec.dose_target_state.get(regimen.route)
    if target is None:
        raise ServiceError(f"No dose target state defined for route {regimen.route!r}.")
    if regimen.n_doses > 1 and not spec.supports_multiple_dosing:
        raise ServiceError(
            f"Model {model_id!r} supports single dosing only. Its dose enters as a "
            "population of solid particles whose shared radius is derived from the "
            "amount initially administered; a second dose arriving mid-dissolution "
            "would make that radius meaningless. Requesting n_doses > 1 is refused "
            "rather than answered with a number the model cannot support."
        )
    return expand_regimen(
        amount_mg=regimen.dose_mg,
        route=regimen.route,
        n_doses=regimen.n_doses,
        interval_h=regimen.interval_h,
        start_h=regimen.start_h,
        duration_h=regimen.infusion_duration_h if regimen.route == "iv_infusion" else 0.0,
        target_state=target,
    )


def notify_dose(model: BaseModel, spec: ModelSpec, dose_mg: float) -> None:
    """Tell a model the administered amount, when it needs to know.

    The absorption models express fraction absorbed and the shared particle
    radius relative to the dose, so they cannot derive either from the state
    vector alone. Every other model ignores this entirely -- the dose reaches
    them as a state increment and nothing downstream depends on knowing it.
    """
    if not spec.requires_dose_notification:
        return
    setter = getattr(model, "set_dose", None)
    if setter is None:
        raise ServiceError(
            f"Model {spec.model_id!r} declares requires_dose_notification but has no "
            "set_dose method. This is a registry/model mismatch, not a user error."
        )
    setter(dose_mg)


# ---------------------------------------------------------------------------
# Deterministic run
# ---------------------------------------------------------------------------
def run_simulation(
    req: SimulationRequest, session: Session | None = None
) -> dict[str, Any]:
    patient = load_patient(session, req.patient_id) if session else None
    resolved = resolve_model(
        model_id=req.model_id,
        drug_id=req.drug_id,
        parameters=req.parameters,
        patient=patient,
        apply_covariates=req.apply_patient_covariates,
    )
    doses = build_doses(req.regimen, req.model_id)
    notify_dose(resolved.model, resolved.spec, req.regimen.dose_mg)
    grid = np.linspace(0.0, req.simulation_horizon_h, req.n_output_points)

    result = simulate(
        resolved.model,
        t_end_h=req.simulation_horizon_h,
        doses=doses,
        output_times_h=grid,
        method=req.solver.method,
        rtol=req.solver.rtol,
        atol=req.solver.atol,
        max_step_h=req.solver.max_step_h,
        check_tolerance_refinement=req.solver.check_tolerance_refinement,
    )

    primary = next(
        (o.name for o in resolved.spec.observables if o.is_primary),
        next(iter(result.observables)),
    )
    conc = result.observable(primary)

    multi = req.regimen.n_doses > 1
    last_dose_h = req.regimen.start_h + (req.regimen.n_doses - 1) * req.regimen.interval_h
    nca = compute_nca(
        result.t_h,
        conc,
        dose_mg=req.regimen.dose_mg,
        concentration_unit=result.observable_units.get(primary, "mg/L"),
        dosing_interval_h=req.regimen.interval_h if multi else None,
        # Anchor AUC(tau) to the interval that follows the LAST dose, not to
        # whatever interval happens to end the simulation window.
        interval_start_h=last_dose_h if multi else None,
    ).to_dict()

    accum = None
    if multi:
        accum = accumulation_metrics(
            result.t_h,
            conc,
            req.regimen.interval_h,
            n_doses=req.regimen.n_doses,
            first_dose_h=req.regimen.start_h,
        )

    band = _resolve_band(req, resolved.drug)
    tir = None
    if band:
        tir = time_within_range(result.t_h, conc, band[0], band[1])
        tir["band_origin"] = band[2]
        tir["band_caveat"] = band[3]

    prov = resolved.model.build_provenance(
        inputs={
            "model_id": req.model_id,
            "drug_id": req.drug_id,
            "regimen": req.regimen.model_dump(),
            "simulation_horizon_h": req.simulation_horizon_h,
            "n_output_points": req.n_output_points,
            "effective_parameters": resolved.effective_parameters,
            "patient": patient.summary() if patient else None,
            "solver_settings": req.solver.model_dump(),
        }
    )
    prov.parameters = retag_parameter_origins(
        prov.parameters,
        drug=resolved.drug,
        model_id=req.model_id,
        user_supplied=req.parameters,
    )
    prov.solver = result.diagnostics
    prov.assumptions = list(prov.assumptions) + [
        f"Covariate adjustment applied: {e.basis} (origin: {e.origin.value})"
        for e in resolved.covariates
    ]
    prov_dict = prov.to_dict()

    payload: dict[str, Any] = {
        "label": req.label,
        "model_id": req.model_id,
        "model_name": resolved.spec.name,
        "drug_id": req.drug_id,
        "time_h": result.t_h.tolist(),
        "observables": {k: v.tolist() for k, v in result.observables.items()},
        "observable_units": result.observable_units,
        "primary_observable": primary,
        "states": {
            n: result.states[i].tolist() for i, n in enumerate(result.state_names)
        },
        "nca": nca,
        "accumulation": accum,
        "time_in_range": tir,
        "diagnostics": result.diagnostics.to_dict(),
        "provenance": prov_dict,
        "covariates_applied": [
            {
                "parameter": e.parameter,
                "multiplier": e.multiplier,
                "basis": e.basis,
                "origin": e.origin.value,
                "reference_ids": e.reference_ids,
            }
            for e in resolved.covariates
        ],
        "effective_parameters": resolved.effective_parameters,
        "validation_status": resolved.spec.validation_status.value,
        "validation_summary": resolved.spec.validation_summary,
        "disclaimer": DISCLAIMER,
        "simulation_id": None,
    }

    if session is not None and req.persist:
        row = SimulationRow(
            experiment_id=req.experiment_id,
            patient_id=req.patient_id,
            label=req.label,
            model_id=req.model_id,
            drug_id=req.drug_id,
            kind="deterministic",
            request=req.model_dump(),
            provenance=prov_dict,
            result=_compact_result(payload),
            input_hash=prov_dict["input_hash"],
            record_hash=prov_dict["record_hash"],
            validation_status=resolved.spec.validation_status.value,
            software_version=SOFTWARE_VERSION,
            engine_revision=ENGINE_REVISION,
            solver_success=result.diagnostics.success,
            solver_warning_count=len(result.diagnostics.warnings),
            wall_time_s=result.diagnostics.wall_time_s,
        )
        session.add(row)
        session.add(
            AuditLogRow(
                action="simulation.run",
                entity="simulation",
                entity_id=None,
                detail={
                    "model_id": req.model_id,
                    "drug_id": req.drug_id,
                    "input_hash": prov_dict["input_hash"],
                },
                software_version=SOFTWARE_VERSION,
            )
        )
        session.commit()
        payload["simulation_id"] = row.id
    return payload


def _compact_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Store the full curve for the primary observable and summaries for the rest.

    Keeping every state trajectory for every run would bloat the database for
    no benefit; the run is reproducible from `request` anyway.
    """
    primary = payload["primary_observable"]
    return {
        "time_h": payload["time_h"],
        "primary_observable": primary,
        "observable_units": payload["observable_units"],
        "primary_curve": payload["observables"][primary],
        "nca": payload["nca"],
        "accumulation": payload["accumulation"],
        "time_in_range": payload["time_in_range"],
        "diagnostics": payload["diagnostics"],
        "effective_parameters": payload["effective_parameters"],
        "covariates_applied": payload["covariates_applied"],
        "available_observables": sorted(payload["observables"]),
    }


def _resolve_band(
    req: SimulationRequest, drug: dict[str, Any] | None
) -> tuple[float, float, str, str] | None:
    if req.reference_band_low is not None and req.reference_band_high is not None:
        return (req.reference_band_low, req.reference_band_high, "user", "Operator-supplied band.")
    if drug:
        band = drug.get("reference_concentration_band")
        if band:
            return (
                float(band["low"]),
                float(band["high"]),
                band.get("origin", "unknown"),
                band.get("caveat", ""),
            )
    return None


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def run_comparison(req: ComparisonRequest, session: Session | None = None) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for scenario in req.scenarios:
        s = scenario.model_copy(
            update={
                "persist": req.persist,
                "experiment_id": scenario.experiment_id or req.experiment_id,
            }
        )
        runs.append(run_simulation(s, session))

    baseline = runs[0]
    table: list[dict[str, Any]] = []
    for r in runs:
        nca = r["nca"]
        base_nca = baseline["nca"]

        def ratio(key: str) -> float | None:
            a, b = nca.get(key), base_nca.get(key)
            if a is None or b in (None, 0):
                return None
            return a / b

        row = {
            "label": r["label"],
            "model_id": r["model_id"],
            "drug_id": r["drug_id"],
            "total_dose_mg": r["provenance"]["inputs"]["regimen"]["dose_mg"]
            * r["provenance"]["inputs"]["regimen"]["n_doses"],
            "dose_mg": r["provenance"]["inputs"]["regimen"]["dose_mg"],
            "n_doses": r["provenance"]["inputs"]["regimen"]["n_doses"],
            "interval_h": r["provenance"]["inputs"]["regimen"]["interval_h"],
            "route": r["provenance"]["inputs"]["regimen"]["route"],
            "cmax": nca["cmax"],
            "tmax_h": nca["tmax_h"],
            "cmin": nca["cmin"],
            "auc_0_last": nca["auc_0_last"],
            "auc_window_h": nca.get("auc_window_h"),
            "auc_0_inf": nca["auc_0_inf"],
            "terminal_half_life_h": nca["terminal_half_life_h"],
            "cmax_ratio_vs_baseline": ratio("cmax"),
            "auc_ratio_vs_baseline": ratio("auc_0_last"),
            "fraction_time_in_band": (r["time_in_range"] or {}).get("fraction_within"),
            "fraction_time_above_band": (r["time_in_range"] or {}).get("fraction_above"),
            "accumulation_ratio_auc": (r["accumulation"] or {}).get("accumulation_ratio_auc"),
            "peak_trough_fluctuation_percent": (r["accumulation"] or {}).get(
                "peak_trough_fluctuation_percent"
            ),
            "solver_warnings": len(r["diagnostics"]["warnings"]),
            "validation_status": r["validation_status"],
        }
        table.append(row)

    notes = [
        f"Ratios are relative to the first scenario, {baseline['label']!r}.",
        "For single-dose scenarios AUC is taken over the whole simulated window, so "
        "comparing scenarios with different horizons on that column is not meaningful - "
        "match the horizons or compare AUC(0-inf) instead.",
        "For multiple-dose scenarios AUC is taken over one dosing interval starting at the "
        "LAST dose, and the window used is reported in auc_window_h. Scenarios with "
        "different intervals therefore integrate over different window lengths; compare "
        "average concentration or dose-normalised exposure rather than raw AUC(tau).",
    ]
    statuses = {r["validation_status"] for r in runs}
    if len(statuses) > 1:
        notes.append(
            "Scenarios in this comparison have different validation statuses "
            f"({sorted(statuses)}). Do not read across them as if equally supported."
        )
    return {
        "label": req.label,
        "scenarios": runs,
        "exposure_table": table,
        "relative_to": baseline["label"],
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------
def run_population(req: PopulationRequest, session: Session | None = None) -> dict[str, Any]:
    patient = load_patient(session, req.patient_id) if session else None
    resolved = resolve_model(
        model_id=req.model_id,
        drug_id=req.drug_id,
        parameters=req.parameters,
        patient=patient,
        apply_covariates=req.apply_patient_covariates,
    )
    spec_names = {p.name for p in resolved.spec.parameters}
    for re_ in req.random_effects:
        if re_.parameter not in spec_names:
            raise ServiceError(
                f"Random effect targets {re_.parameter!r}, which model {req.model_id!r} "
                f"does not have. Available: {sorted(spec_names)}"
            )

    pop_spec = PopulationSpec(
        typical_values=dict(resolved.effective_parameters),
        random_effects=[
            RandomEffect(r.parameter, r.cv_percent, r.lower_bound, r.upper_bound)
            for r in req.random_effects
        ],
        correlation={(a, b): rho for a, b, rho in req.correlations},
        residual_error=ResidualError(
            req.residual_error.proportional_cv_percent, req.residual_error.additive_sd
        ),
    )

    doses = build_doses(req.regimen, req.model_id)
    grid = np.linspace(0.0, req.simulation_horizon_h, req.n_output_points)
    primary = next(
        (o.name for o in resolved.spec.observables if o.is_primary), "plasma_concentration"
    )
    multi = req.regimen.n_doses > 1
    interval = req.regimen.interval_h if multi else None
    last_dose_h = (
        req.regimen.start_h + (req.regimen.n_doses - 1) * req.regimen.interval_h if multi else None
    )

    def metric(t: np.ndarray, c: np.ndarray) -> dict[str, float]:
        if not np.all(np.isfinite(c)):
            return {}
        n = compute_nca(
            t, c, dose_mg=req.regimen.dose_mg,
            dosing_interval_h=interval, interval_start_h=last_dose_h,
        )
        return {
            "cmax": n.cmax,
            "tmax_h": n.tmax_h,
            "cmin": n.cmin,
            "auc_0_last": n.auc_0_last,
            "terminal_half_life_h": n.terminal_half_life_h or float("nan"),
        }

    def _build_replicate(p: dict[str, float]) -> BaseModel:
        """Each Monte Carlo replicate is a fresh model, so each needs the dose."""
        m = build_model(req.model_id, p)
        notify_dose(m, resolved.spec, req.regimen.dose_mg)
        return m

    t0 = time.perf_counter()
    result = run_population_simulation(
        _build_replicate,
        pop_spec,
        t_end_h=req.simulation_horizon_h,
        doses=doses,
        output_times_h=grid,
        observable=primary,
        n_subjects=req.n_subjects,
        seed=req.seed,
        percentiles=tuple(req.percentiles),
        include_residual_error=req.include_residual_error,
        summary_metric=metric,
    )
    result["wall_time_s"] = time.perf_counter() - t0

    band = None
    if req.reference_band_low is not None and req.reference_band_high is not None:
        band = (req.reference_band_low, req.reference_band_high)
    elif resolved.drug and resolved.drug.get("reference_concentration_band"):
        b = resolved.drug["reference_concentration_band"]
        band = (float(b["low"]), float(b["high"]))

    attainment = None
    if band:
        attainment = _target_attainment(result, band, req.simulation_horizon_h)

    prov = resolved.model.build_provenance(
        inputs={
            "model_id": req.model_id,
            "drug_id": req.drug_id,
            "regimen": req.regimen.model_dump(),
            "typical_parameters": resolved.effective_parameters,
            "random_effects": [r.model_dump() for r in req.random_effects],
            "correlations": req.correlations,
            "residual_error": req.residual_error.model_dump(),
            "n_subjects": req.n_subjects,
            "patient": patient.summary() if patient else None,
        },
        random_seed=req.seed,
    )
    prov.parameters = retag_parameter_origins(
        prov.parameters,
        drug=resolved.drug,
        model_id=req.model_id,
        user_supplied=req.parameters,
    )
    prov.limitations = list(prov.limitations) + [
        "Between-subject variability magnitudes come from the drug library or the operator; "
        "where they were estimated by SYNTHBODY's two-stage fit they are upper bounds on true "
        "variability, because two-stage estimation absorbs estimation error into the variance.",
        "Percentile bands describe variability between simulated individuals. They are not "
        "confidence intervals on the typical value and they carry no information about "
        "uncertainty in the structural model itself.",
    ]
    prov_dict = prov.to_dict()

    payload = {
        "simulation_id": None,
        "label": req.label,
        "model_id": req.model_id,
        "drug_id": req.drug_id,
        "result": result,
        "exposure_distribution": result.get("metric_summary", {}),
        "target_attainment": attainment,
        "provenance": prov_dict,
        "validation_status": resolved.spec.validation_status.value,
        "disclaimer": DISCLAIMER,
    }

    if session is not None and req.persist:
        row = SimulationRow(
            experiment_id=req.experiment_id,
            patient_id=req.patient_id,
            label=req.label,
            model_id=req.model_id,
            drug_id=req.drug_id,
            kind="population",
            request=req.model_dump(),
            provenance=prov_dict,
            result={
                "time_h": result["time_h"],
                "structural_percentiles": result["structural_percentiles"],
                "observation_percentiles": result.get("observation_percentiles"),
                "typical_value_profile": result["typical_value_profile"],
                "metric_summary": result.get("metric_summary", {}),
                "n_subjects_simulated": result["n_subjects_simulated"],
                "n_failures": result["n_failures"],
                "target_attainment": attainment,
            },
            input_hash=prov_dict["input_hash"],
            record_hash=prov_dict["record_hash"],
            validation_status=resolved.spec.validation_status.value,
            software_version=SOFTWARE_VERSION,
            engine_revision=ENGINE_REVISION,
            solver_success=result["n_failures"] == 0,
            solver_warning_count=result["n_failures"],
            wall_time_s=result["wall_time_s"],
        )
        session.add(row)
        session.commit()
        payload["simulation_id"] = row.id
    return payload


def _target_attainment(
    result: dict[str, Any], band: tuple[float, float], horizon_h: float
) -> dict[str, Any]:
    """Fraction of simulated subjects whose Cmax lands below / within / above the band."""
    metrics = result.get("subject_metrics") or []
    if not metrics:
        return {"band_low": band[0], "band_high": band[1], "n": 0}
    cmax = np.array([m.get("cmax", np.nan) for m in metrics], dtype=float)
    cmax = cmax[np.isfinite(cmax)]
    if cmax.size == 0:
        return {"band_low": band[0], "band_high": band[1], "n": 0}
    return {
        "band_low": band[0],
        "band_high": band[1],
        "n": int(cmax.size),
        "metric": "Cmax",
        "fraction_below_band": float(np.mean(cmax < band[0])),
        "fraction_within_band": float(np.mean((cmax >= band[0]) & (cmax <= band[1]))),
        "fraction_above_band": float(np.mean(cmax > band[1])),
        "note": (
            "Computed on peak concentration across the simulated window. This is a descriptive "
            "property of the simulated cohort, not a clinical target-attainment claim."
        ),
    }


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------
_METRIC_KEYS = {
    "auc_0_last": "auc_0_last",
    "auc_0_inf": "auc_0_inf",
    "cmax": "cmax",
    "cmin": "cmin",
    "tmax": "tmax_h",
    "t_half": "terminal_half_life_h",
}


def run_sensitivity(req: SensitivityRequest, session: Session | None = None) -> dict[str, Any]:
    resolved = resolve_model(
        model_id=req.model_id,
        drug_id=req.drug_id,
        parameters=req.parameters,
        patient=None,
        apply_covariates=False,
    )
    if not resolved.spec.supports_sensitivity:
        raise ServiceError(f"Model {req.model_id!r} does not support sensitivity analysis.")

    schema = {p.name: p for p in resolved.spec.parameters}
    specs: list[ParameterSpec] = []
    for t in req.targets:
        if t.name not in schema:
            raise ServiceError(
                f"Unknown parameter {t.name!r} for model {req.model_id!r}. "
                f"Available: {sorted(schema)}"
            )
        p = schema[t.name]
        nominal = t.nominal if t.nominal is not None else resolved.effective_parameters[t.name]
        if t.low is not None and t.high is not None:
            low, high = t.low, t.high
        else:
            r = t.relative_range or 0.5
            low, high = nominal * (1.0 - r), nominal * (1.0 + r)
        low = max(low, p.minimum)
        high = min(high, p.maximum)
        if nominal <= low or nominal >= high:
            # Keep the nominal strictly inside so central differences work.
            span = max(high - low, 1e-12)
            nominal = min(max(nominal, low + span * 1e-6), high - span * 1e-6)
        specs.append(
            ParameterSpec(
                name=t.name, nominal=nominal, low=low, high=high,
                unit=p.unit, description=p.description,
            )
        )

    doses = build_doses(req.regimen, req.model_id)
    grid = np.linspace(0.0, req.simulation_horizon_h, 601)
    primary = next(
        (o.name for o in resolved.spec.observables if o.is_primary), "plasma_concentration"
    )
    metric_key = _METRIC_KEYS[req.metric]
    multi_s = req.regimen.n_doses > 1
    interval = req.regimen.interval_h if multi_s else None
    last_dose_sens = (
        req.regimen.start_h + (req.regimen.n_doses - 1) * req.regimen.interval_h if multi_s else None
    )
    n_calls = {"n": 0}

    def objective(values: dict[str, float]) -> float:
        params = dict(resolved.effective_parameters)
        params.update(values)
        n_calls["n"] += 1
        try:
            model = build_model(req.model_id, params)
            notify_dose(model, resolved.spec, req.regimen.dose_mg)
            res = simulate(
                model,
                t_end_h=req.simulation_horizon_h,
                doses=doses,
                output_times_h=grid,
                check_tolerance_refinement=False,
            )
            nca = compute_nca(
                res.t_h, res.observable(primary),
                dose_mg=req.regimen.dose_mg, dosing_interval_h=interval,
                interval_start_h=last_dose_sens,
            )
            v = getattr(nca, metric_key)
            return float(v) if v is not None and np.isfinite(v) else float("nan")
        except Exception:
            return float("nan")

    notes: list[str] = []
    t0 = time.perf_counter()
    if req.method == "local":
        analysis = local_sensitivity(objective, specs)
    elif req.method == "morris":
        analysis = morris_screening(
            objective, specs, trajectories=req.morris_trajectories, seed=req.seed
        )
        notes.append(
            "Morris screening ranks influence. It does not quantify variance contributions; "
            "use Sobol for that."
        )
    else:
        n = 1 << int(np.ceil(np.log2(req.sobol_base_samples)))
        if n != req.sobol_base_samples:
            notes.append(f"Sobol base samples rounded up to the next power of two: {n}.")
        analysis = sobol_indices(objective, specs, base_samples=n, seed=req.seed)
    wall = time.perf_counter() - t0

    if req.metric in ("auc_0_inf", "t_half"):
        notes.append(
            f"The {req.metric} metric depends on characterising the terminal phase. If the "
            "simulation horizon is short relative to the half-life, this metric is unstable and "
            "the sensitivity indices will reflect that instability rather than real sensitivity."
        )

    return {
        "label": req.label,
        "model_id": req.model_id,
        "metric": req.metric,
        "method": req.method,
        "analysis": analysis,
        "nominal_parameters": {s.name: s.nominal for s in specs},
        "n_model_evaluations": n_calls["n"],
        "wall_time_s": wall,
        "notes": notes,
    }
