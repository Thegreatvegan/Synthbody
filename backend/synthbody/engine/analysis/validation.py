"""
The validation pipeline.

This is the module that decides whether SYNTHBODY is allowed to claim anything.

Protocol, fixed in advance and applied identically every run:

  1. Split the dataset into a CALIBRATION set and a HELD-OUT set by subject id.
     The split is deterministic (odd-numbered subjects calibrate, even-numbered
     validate) so it cannot be tuned after seeing the result.
  2. Estimate typical parameters from the CALIBRATION subjects only, by
     two-stage fitting, and take the geometric mean of the individual estimates.
  3. Predict the HELD-OUT subjects using those typical parameters, adjusted only
     by each subject's recorded covariates (dose, and weight where available).
     No held-out observation ever touches the estimation.
  4. Report agreement statistics separately for calibration and held-out data.

Step 4 is the point. Calibration-set agreement is a software-correctness check.
Only the held-out numbers are evidence about the model, and only within the
population and design the dataset actually covers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from synthbody.engine.analysis.datasets import ObservedDataset, Subject, get_dataset
from synthbody.engine.analysis.estimation import FitSpec, fit_two_stage
from synthbody.engine.analysis.metrics import AgreementMetrics, compute_agreement, residual_diagnostics
from synthbody.engine.core import DoseEvent, simulate
from synthbody.engine.models.compartmental import (
    OneCompartmentFirstOrderAbsorption,
    TwoCompartment,
)
from synthbody.version import ENGINE_REVISION, SOFTWARE_VERSION


def deterministic_split(dataset: ObservedDataset) -> tuple[list[str], list[str]]:
    """Odd subject ids calibrate, even subject ids validate.

    Deterministic and declared up front so the split cannot be chosen to
    flatter the result.
    """
    calib, held = [], []
    for sid in dataset.subject_ids:
        try:
            is_odd = int(sid) % 2 == 1
        except ValueError:  # pragma: no cover - ids are numeric in shipped data
            is_odd = len(calib) <= len(held)
        (calib if is_odd else held).append(sid)
    return calib, held


# ---------------------------------------------------------------------------
# Model-specific adapters
# ---------------------------------------------------------------------------
@dataclass
class ValidationTarget:
    """How to fit and predict one dataset with one model structure."""

    target_id: str
    dataset_id: str
    model_id: str
    model_label: str
    fit_specs: list[FitSpec]
    build_predict: Callable[[Subject], Callable[[dict[str, float], np.ndarray], np.ndarray]]
    scale_by_weight: list[str] = field(default_factory=list)
    reference_weight_kg: float = 70.0
    allometric_exponents: dict[str, float] = field(default_factory=dict)
    notes: str = ""


def _theoph_predict(subject: Subject):
    """Prediction function for one Theoph subject.

    Parameters are per-kilogram (CL/F per kg, V/F per kg) so that a typical
    value estimated across subjects of different weights is meaningful. The
    absolute dose and weight come from the subject's own record.
    """

    def predict(params: dict[str, float], t: np.ndarray) -> np.ndarray:
        wt = subject.weight_kg or 70.0
        model = OneCompartmentFirstOrderAbsorption(
            cl_L_per_h=params["CL_per_kg"] * wt,
            v_L=params["V_per_kg"] * wt,
            ka_per_h=params["ka"],
            bioavailability=1.0,  # not identifiable from oral data; fixed at 1
        )
        return model.analytic_concentration(np.asarray(t, float), subject.dose_mg)

    return predict


def _indometh_predict(subject: Subject):
    """Prediction function for one Indometh subject.

    The dose is unknown, so V1 and V2 are apparent volumes per unit dose.
    """

    def predict(params: dict[str, float], t: np.ndarray) -> np.ndarray:
        model = TwoCompartment(
            cl_L_per_h=params["CL"],
            v1_L=params["V1"],
            q_L_per_h=params["Q"],
            v2_L=params["V2"],
            ka_per_h=None,
        )
        return model.analytic_concentration_iv_bolus(np.asarray(t, float), subject.dose_mg)

    return predict


def build_targets() -> dict[str, ValidationTarget]:
    return {
        "theoph_1cmt_foa": ValidationTarget(
            target_id="theoph_1cmt_foa",
            dataset_id="theoph",
            model_id="pk_1cmt_foa",
            model_label="One-compartment PK, first-order absorption",
            fit_specs=[
                FitSpec("CL_per_kg", initial=0.04, lower=1e-4, upper=1.0, unit="L/h/kg"),
                FitSpec("V_per_kg", initial=0.5, lower=1e-3, upper=5.0, unit="L/kg"),
                FitSpec("ka", initial=1.5, lower=1e-3, upper=50.0, unit="1/h"),
            ],
            build_predict=_theoph_predict,
            notes=(
                "Parameters are apparent (CL/F, V/F) because bioavailability is not "
                "identifiable from oral-only data and was fixed at 1. Clearance and volume "
                "are estimated per kilogram using each subject's recorded weight."
            ),
        ),
        "indometh_2cmt": ValidationTarget(
            target_id="indometh_2cmt",
            dataset_id="indometh",
            model_id="pk_2cmt",
            model_label="Two-compartment PK",
            fit_specs=[
                FitSpec("CL", initial=10.0, lower=1e-3, upper=1e4, unit="L/h per unit dose"),
                FitSpec("V1", initial=10.0, lower=1e-3, upper=1e4, unit="L per unit dose"),
                FitSpec("Q", initial=10.0, lower=1e-3, upper=1e4, unit="L/h per unit dose"),
                FitSpec("V2", initial=10.0, lower=1e-3, upper=1e4, unit="L per unit dose"),
            ],
            build_predict=_indometh_predict,
            notes=(
                "The administered dose is absent from the distributed dataset, so a nominal "
                "dose of 1 unit is used and all volumes and clearances are apparent values "
                "per unit dose. Ratios and rate constants derived from them are still valid."
            ),
        ),
    }


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
@dataclass
class ValidationReport:
    target_id: str
    dataset_id: str
    dataset_name: str
    model_id: str
    model_label: str
    protocol: dict[str, Any]
    calibration_subject_ids: list[str]
    held_out_subject_ids: list[str]
    typical_parameters: dict[str, float]
    between_subject_cv_percent: dict[str, float]
    individual_estimates: dict[str, dict[str, float]]
    individual_rse_percent: dict[str, dict[str, float | None]]
    calibration_metrics: AgreementMetrics
    held_out_metrics: AgreementMetrics
    held_out_residuals: dict[str, Any]
    per_subject_held_out: list[dict[str, Any]]
    observed_vs_predicted: dict[str, list[float]]
    profiles: list[dict[str, Any]]
    estimation_note: str
    interpretation: str
    software_version: str
    engine_revision: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "model_id": self.model_id,
            "model_label": self.model_label,
            "protocol": self.protocol,
            "calibration_subject_ids": self.calibration_subject_ids,
            "held_out_subject_ids": self.held_out_subject_ids,
            "typical_parameters": self.typical_parameters,
            "between_subject_cv_percent": self.between_subject_cv_percent,
            "individual_estimates": self.individual_estimates,
            "individual_rse_percent": self.individual_rse_percent,
            "calibration_metrics": self.calibration_metrics.to_dict(),
            "held_out_metrics": self.held_out_metrics.to_dict(),
            "held_out_residuals": self.held_out_residuals,
            "per_subject_held_out": self.per_subject_held_out,
            "observed_vs_predicted": self.observed_vs_predicted,
            "profiles": self.profiles,
            "estimation_note": self.estimation_note,
            "interpretation": self.interpretation,
            "software_version": self.software_version,
            "engine_revision": self.engine_revision,
            "warnings": self.warnings,
        }


def run_validation(target_id: str, *, profile_points: int = 240) -> ValidationReport:
    targets = build_targets()
    if target_id not in targets:
        raise KeyError(f"Unknown validation target {target_id!r}. Available: {sorted(targets)}")
    target = targets[target_id]
    dataset = get_dataset(target.dataset_id)
    calib_ids, held_ids = deterministic_split(dataset)
    if not calib_ids or not held_ids:
        raise RuntimeError("The deterministic split produced an empty set; cannot validate.")

    # ---- stage 1: fit calibration subjects only
    calib_data = {
        sid: (dataset.subjects[sid].time_h, dataset.subjects[sid].concentration_mg_per_L)
        for sid in calib_ids
    }
    two_stage = fit_two_stage(
        lambda sid: target.build_predict(dataset.subjects[sid]),
        calib_data,
        target.fit_specs,
        weighting="proportional",
    )
    typical = dict(two_stage.typical_values_geometric_mean)

    warnings: list[str] = []
    if two_stage.n_subjects_failed:
        warnings.append(
            f"{two_stage.n_subjects_failed} calibration subject(s) failed to fit: "
            + "; ".join(f"{k}: {v}" for k, v in two_stage.failures.items())
        )
    for name, fit in two_stage.individual_fits.items():
        for w in fit.warnings:
            warnings.append(f"calibration subject {name}: {w}")

    # ---- stage 2: predict both sets with the single typical parameter vector
    def gather(ids: list[str]) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
        obs_all, pred_all, per_subject = [], [], []
        for sid in ids:
            s = dataset.subjects[sid]
            pred = np.asarray(target.build_predict(s)(typical, s.time_h), float)
            obs = s.concentration_mg_per_L
            obs_all.append(obs)
            pred_all.append(pred)
            m = compute_agreement(obs, pred, units=dataset.concentration_unit)
            per_subject.append(
                {
                    "subject_id": sid,
                    "dose_mg": s.dose_mg,
                    "weight_kg": s.weight_kg,
                    "n_observations": s.n_observations,
                    "rmse": m.rmse,
                    "mean_absolute_percent_error": m.mean_absolute_percent_error,
                    "average_fold_error": m.average_fold_error,
                    "absolute_average_fold_error": m.absolute_average_fold_error,
                    "fraction_within_2_fold": m.fraction_within_2_fold,
                    "observed_cmax": float(np.max(obs)),
                    "predicted_cmax": float(np.max(pred)),
                }
            )
        return np.concatenate(obs_all), np.concatenate(pred_all), per_subject

    c_obs, c_pred, _ = gather(calib_ids)
    h_obs, h_pred, h_per_subject = gather(held_ids)

    calib_metrics = compute_agreement(c_obs, c_pred, units=dataset.concentration_unit)
    held_metrics = compute_agreement(h_obs, h_pred, units=dataset.concentration_unit)
    held_resid = residual_diagnostics(h_obs, h_pred)

    # ---- dense profiles for plotting, from the ODE engine not the analytic form,
    #      so what the UI draws is what the simulator produces
    profiles: list[dict[str, Any]] = []
    for sid in dataset.subject_ids:
        s = dataset.subjects[sid]
        t_end = float(s.time_h[-1]) * 1.05
        grid = np.linspace(0.0, t_end, profile_points)
        model, doses = _build_engine_model(target, s, typical)
        res = simulate(
            model,
            t_end_h=t_end,
            doses=doses,
            output_times_h=grid,
            check_tolerance_refinement=False,
        )
        profiles.append(
            {
                "subject_id": sid,
                "set": "calibration" if sid in set(calib_ids) else "held_out",
                "time_h": grid.tolist(),
                "predicted": res.observable("plasma_concentration").tolist(),
                "observed_time_h": s.time_h.tolist(),
                "observed": s.concentration_mg_per_L.tolist(),
                "dose_mg": s.dose_mg,
                "weight_kg": s.weight_kg,
            }
        )

    interpretation = _interpret(held_metrics, dataset)
    return ValidationReport(
        target_id=target_id,
        dataset_id=dataset.dataset_id,
        dataset_name=dataset.name,
        model_id=target.model_id,
        model_label=target.model_label,
        protocol={
            "split_rule": "Odd-numbered subject ids calibrate; even-numbered subject ids are held out.",
            "split_is_deterministic": True,
            "estimation": "Two-stage: per-subject weighted non-linear least squares, then geometric mean.",
            "weighting": "proportional (1/prediction)",
            "held_out_data_used_in_estimation": False,
            "covariates_applied_to_held_out": "Each held-out subject's own recorded dose and body weight only.",
            "notes": target.notes,
        },
        calibration_subject_ids=calib_ids,
        held_out_subject_ids=held_ids,
        typical_parameters=typical,
        between_subject_cv_percent=two_stage.between_subject_cv_percent,
        individual_estimates={k: v.parameters for k, v in two_stage.individual_fits.items()},
        individual_rse_percent={
            k: v.relative_standard_errors_percent for k, v in two_stage.individual_fits.items()
        },
        calibration_metrics=calib_metrics,
        held_out_metrics=held_metrics,
        held_out_residuals=held_resid,
        per_subject_held_out=h_per_subject,
        observed_vs_predicted={
            "calibration_observed": c_obs.tolist(),
            "calibration_predicted": c_pred.tolist(),
            "held_out_observed": h_obs.tolist(),
            "held_out_predicted": h_pred.tolist(),
        },
        profiles=profiles,
        estimation_note=two_stage.method_note,
        interpretation=interpretation,
        software_version=SOFTWARE_VERSION,
        engine_revision=ENGINE_REVISION,
        warnings=warnings,
    )


def _build_engine_model(target: ValidationTarget, subject: Subject, typical: dict[str, float]):
    """Construct the ODE model and dose events for a subject, for plotting."""
    if target.model_id == "pk_1cmt_foa":
        wt = subject.weight_kg or 70.0
        model = OneCompartmentFirstOrderAbsorption(
            cl_L_per_h=typical["CL_per_kg"] * wt,
            v_L=typical["V_per_kg"] * wt,
            ka_per_h=typical["ka"],
            bioavailability=1.0,
        )
        doses = [DoseEvent(0.0, subject.dose_mg, "oral", target_state=0)]
        return model, doses
    if target.model_id == "pk_2cmt":
        model = TwoCompartment(
            cl_L_per_h=typical["CL"],
            v1_L=typical["V1"],
            q_L_per_h=typical["Q"],
            v2_L=typical["V2"],
            ka_per_h=None,
        )
        doses = [DoseEvent(0.0, subject.dose_mg, "iv_bolus", target_state=1)]
        return model, doses
    raise ValueError(f"No engine adapter for model {target.model_id!r}.")


def _interpret(m: AgreementMetrics, dataset: ObservedDataset) -> str:
    bits: list[str] = []
    if m.absolute_average_fold_error is not None:
        bits.append(
            f"On held-out subjects the model's absolute average fold error is "
            f"{m.absolute_average_fold_error:.3f} and its average fold error is "
            f"{m.average_fold_error:.3f}, so typical precision is about "
            f"{(m.absolute_average_fold_error - 1) * 100:.0f}% with "
            f"{'over' if m.average_fold_error > 1 else 'under'}-prediction bias of "
            f"{abs(m.average_fold_error - 1) * 100:.0f}%."
        )
    if m.fraction_within_2_fold is not None:
        bits.append(
            f"{m.fraction_within_2_fold * 100:.0f}% of held-out observations fall within "
            "2-fold of prediction."
        )
    bits.append(
        f"Median absolute percent error is {m.median_absolute_percent_error:.0f}% "
        f"(RMSE {m.rmse:.3f} {m.units})."
    )
    bits.append(
        "This is evidence only for the population and study design this dataset covers: "
        + dataset.description.split(".")[0].lower()
        + ". It is not evidence of accuracy in any other population, route, dose range or "
        "disease state, and it is not clinical validation."
    )
    return " ".join(bits)


def run_all_validations() -> dict[str, ValidationReport]:
    return {tid: run_validation(tid) for tid in build_targets()}
