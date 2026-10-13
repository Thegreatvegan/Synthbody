"""
Concentration-time validation of the whole-body oral PBPK model.

This is the test the PBPK module has been missing. Until now the only external
check on it was a comparison of its predicted steady-state volume of
distribution against a literature value -- a single scalar. That is not enough
to call a distribution model validated, and SYNTHBODY has said so in
``SCIENTIFIC_LIMITATIONS.md`` since the first release.

WHAT IS PREDICTED A PRIORI AND WHAT IS NOT. This matters more than the result,
because a validation that quietly fits the thing it is measuring is worthless:

  * **Distribution -- fully a priori.** All twelve tissue:plasma partition
    coefficients, and therefore the volume of distribution, are computed by the
    Poulin-Theil method from log P, fraction unbound and blood:plasma ratio.
    Nothing about the observed profiles enters. The volume of distribution is
    never fitted in this protocol, which is the single biggest difference from
    the empirical one-compartment validation, where V/F was estimated from the
    data.
  * **Absorption -- fully a priori.** Gastric emptying, transit, dissolution
    and permeability-limited uptake come from the shipped GI physiology and
    theophylline physicochemistry at the *pre-specified* effective
    permeability, not a value chosen after seeing the fit. There is no absorption
    rate constant to estimate: ``ka`` is an emergent property of the lumen model.
  * **Elimination -- calibrated, on disjoint subjects.** One number, total
    plasma clearance per kg, is taken from the calibration subjects and inverted
    through the well-stirred equation to a hepatic intrinsic clearance. The
    subjects it was estimated from are not the subjects it is evaluated on.

So of the three processes that shape an oral profile, two are predicted from
physicochemistry and one is calibrated out-of-sample. Clearance largely sets
AUC, so AUC remains the weak metric here, exactly as in the absorption
benchmark. The informative outputs are the shape of the curve, Cmax and tmax,
and the point-by-point agreement across the whole profile.

The protocol is fixed in code -- the same deterministic odd/even subject split
used everywhere else in SYNTHBODY -- so it cannot be adjusted after seeing an
unfavourable answer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from synthbody.engine.analysis.datasets import load_theophylline
from synthbody.engine.analysis.metrics import compute_agreement
from synthbody.engine.analysis.nca import compute_nca
from synthbody.engine.core import simulate
from synthbody.engine.models.absorption import OralDrugInput
from synthbody.engine.models.oral_pbpk import OralPBPK
from synthbody.engine.physiology.partition import DrugPhysChem

# --------------------------------------------------------------------------
# Inputs, with the provenance of every one of them stated.
#
# These are the SAME values already used by the shipped PBPK structural check
# in scripts/run_validation.py, deliberately unchanged, so that this test
# cannot be accused of having re-picked its inputs to improve the answer.
# --------------------------------------------------------------------------
THEOPHYLLINE_PBPK_INPUTS: dict[str, dict[str, Any]] = {
    "log_p": {
        "value": -0.02,
        "origin": "measured",
        "source": "PubChem CID 2153, computed XLogP3. Public domain. Already used "
                  "unchanged by the shipped PBPK structural check.",
    },
    "fraction_unbound_plasma": {
        "value": 0.60,
        "origin": "inferred",
        "source": "Theophylline is approximately 40% bound to plasma protein, a "
                  "widely quoted figure whose primary source SYNTHBODY did not "
                  "retrieve. Carried over unchanged from the existing Vss check.",
    },
    "blood_plasma_ratio": {
        "value": 0.82,
        "origin": "inferred",
        "source": "Widely quoted value; primary source not retrieved. Carried over "
                  "unchanged from the existing Vss check.",
    },
    "renal_fraction_of_clearance": {
        "value": 0.0,
        "origin": "illustrative",
        "source": "ALL systemic clearance is assigned to the hepatic route in this "
                  "protocol. Theophylline is in fact roughly 10% renally excreted "
                  "unchanged, but SYNTHBODY did not retrieve a primary source for "
                  "that split, and because theophylline is a low-extraction drug the "
                  "choice moves predicted hepatic availability by well under 1%. "
                  "`renal_fraction_of_clearance` is exposed as an argument so the "
                  "sensitivity can be checked rather than assumed.",
    },
}

# Pre-specified. Identical to the value the absorption benchmark declared as its
# headline, chosen before any PBPK profile was computed.
PRESPECIFIED_PEFF_CM_PER_S = 3.0e-4
PRESPECIFIED_PARTICLE_RADIUS_UM = 25.0

CALIBRATION_SUBJECT_IDS: tuple[str, ...] = ("1", "3", "5", "7", "9", "11")


def hepatic_clint_from_plasma_clearance(
    *,
    total_plasma_clearance_L_per_h: float,
    liver_blood_flow_L_per_h: float,
    fraction_unbound_plasma: float,
    blood_plasma_ratio: float,
    renal_fraction: float = 0.0,
) -> float:
    """Invert the well-stirred model to get CLint from an observed plasma CL.

    Forward direction, as implemented in ``PerfusionLimitedPBPK``::

        CL_H,blood = Q_H * fu_b * CLint / (Q_H + fu_b * CLint)
        CL_plasma  = CL_H,blood * BP + CL_renal

    Inverting::

        CL_H,blood  = (CL_plasma - CL_renal) / BP
        fu_b * CLint = Q_H * CL_H,blood / (Q_H - CL_H,blood)

    Raises if the implied hepatic blood clearance exceeds liver blood flow,
    which would mean the well-stirred model cannot produce the observed
    clearance at all -- a real physiological impossibility that should surface
    loudly rather than be clipped into range.
    """
    if total_plasma_clearance_L_per_h <= 0:
        raise ValueError("total_plasma_clearance_L_per_h must be positive.")
    if not 0.0 <= renal_fraction < 1.0:
        raise ValueError("renal_fraction must be in [0, 1).")

    cl_renal = total_plasma_clearance_L_per_h * renal_fraction
    cl_hepatic_plasma = total_plasma_clearance_L_per_h - cl_renal
    cl_hepatic_blood = cl_hepatic_plasma / blood_plasma_ratio

    if cl_hepatic_blood >= liver_blood_flow_L_per_h:
        raise ValueError(
            f"Implied hepatic blood clearance {cl_hepatic_blood:.2f} L/h is not less "
            f"than liver blood flow {liver_blood_flow_L_per_h:.2f} L/h. The "
            "well-stirred model cannot reproduce this clearance; the inputs are "
            "physiologically inconsistent."
        )

    fu_b = fraction_unbound_plasma / blood_plasma_ratio
    clint = (
        liver_blood_flow_L_per_h
        * cl_hepatic_blood
        / ((liver_blood_flow_L_per_h - cl_hepatic_blood) * fu_b)
    )
    return float(clint)


@dataclass
class SubjectPrediction:
    """One held-out subject: predicted versus observed, with no tuning between."""

    subject_id: str
    weight_kg: float
    dose_mg: float
    time_h: list[float]
    observed_mg_per_L: list[float]
    predicted_mg_per_L: list[float]
    predicted_fabs: float
    predicted_f_hepatic: float
    hepatic_clint_L_per_h: float
    predicted_vss_L_per_kg: float
    observed_cmax: float
    predicted_cmax: float
    observed_tmax_h: float
    predicted_tmax_h: float
    observed_auc: float
    predicted_auc: float
    mass_balance_relative_error: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PBPKValidationResult:
    """The complete, self-describing outcome of the protocol."""

    model_id: str
    protocol: str
    inputs: dict[str, Any]
    calibration_subject_ids: list[str]
    held_out_subject_ids: list[str]
    calibrated_clearance_L_per_h_per_kg: float
    predictions: list[SubjectPrediction] = field(default_factory=list)
    pointwise_metrics: dict[str, float] = field(default_factory=dict)
    metric_summary: dict[str, dict[str, float]] = field(default_factory=dict)
    comparison_to_empirical_model: dict[str, Any] = field(default_factory=dict)
    interpretation: str = ""
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["predictions"] = [p.to_dict() for p in self.predictions]
        return d


def _fold_summary(predicted: np.ndarray, observed: np.ndarray) -> dict[str, float]:
    """AAFE / AFE / fraction within 2-fold for a set of paired scalars."""
    mask = (observed > 0) & (predicted > 0)
    if not np.any(mask):
        return {"aafe": float("nan"), "afe": float("nan"),
                "fraction_within_2_fold": float("nan"), "n": 0}
    ratio = predicted[mask] / observed[mask]
    log_ratio = np.log10(ratio)
    return {
        "aafe": float(10.0 ** np.mean(np.abs(log_ratio))),
        "afe": float(10.0 ** np.mean(log_ratio)),
        "fraction_within_2_fold": float(np.mean((ratio >= 0.5) & (ratio <= 2.0))),
        "n": int(np.sum(mask)),
    }


def run_oral_pbpk_validation(
    *,
    peff_cm_per_s: float = PRESPECIFIED_PEFF_CM_PER_S,
    particle_radius_um: float = PRESPECIFIED_PARTICLE_RADIUS_UM,
    renal_fraction_of_clearance: float = 0.0,
    calibration_subject_ids: tuple[str, ...] = CALIBRATION_SUBJECT_IDS,
) -> PBPKValidationResult:
    """Predict held-out Theoph profiles with the whole-body oral PBPK model.

    Returns the full result whatever it says. There is no pass/fail threshold
    and no retry: the numbers are reported as computed.
    """
    # Imported here to keep the engine's analysis layer free of import cycles.
    from synthbody.engine.analysis.validation import run_validation

    dataset = load_theophylline()
    calibration = set(calibration_subject_ids)
    held_out = [s for s in dataset.subject_ids if s not in calibration]
    if not held_out:
        raise ValueError("No held-out subjects remain; the split is degenerate.")

    # The ONE calibrated number, estimated on the calibration subjects only.
    empirical = run_validation("theoph_1cmt_foa")
    cl_per_kg = empirical.typical_parameters["CL_per_kg"]

    physchem = DrugPhysChem(
        log_p=THEOPHYLLINE_PBPK_INPUTS["log_p"]["value"],
        fraction_unbound_plasma=THEOPHYLLINE_PBPK_INPUTS["fraction_unbound_plasma"]["value"],
        blood_plasma_ratio=THEOPHYLLINE_PBPK_INPUTS["blood_plasma_ratio"]["value"],
    )
    oral_input = OralDrugInput(
        intrinsic_solubility_mg_per_mL=7.36,
        effective_permeability_cm_per_s=peff_cm_per_s,
        pka_acidic=8.81,
        particle_radius_um=particle_radius_um,
    )

    predictions: list[SubjectPrediction] = []
    all_observed: list[float] = []
    all_predicted: list[float] = []

    for sid in held_out:
        subject = dataset.subjects[sid]
        weight = subject.weight_kg or 70.0

        # Build the model at this subject's weight. Physiology scales with weight
        # through the reference-physiology module; nothing is fitted per subject.
        probe = OralPBPK(
            drug_physchem=physchem, oral_input=oral_input, body_weight_kg=weight
        )
        liver_flow = probe.distribution_model._q_liver_total
        clint = hepatic_clint_from_plasma_clearance(
            total_plasma_clearance_L_per_h=cl_per_kg * weight,
            liver_blood_flow_L_per_h=liver_flow,
            fraction_unbound_plasma=physchem.fraction_unbound_plasma,
            blood_plasma_ratio=physchem.blood_plasma_ratio,
            renal_fraction=renal_fraction_of_clearance,
        )
        model = OralPBPK(
            drug_physchem=physchem,
            oral_input=oral_input,
            body_weight_kg=weight,
            hepatic_intrinsic_clearance_L_per_h=clint,
            renal_clearance_L_per_h=cl_per_kg * weight * renal_fraction_of_clearance,
        )

        observed_times = np.asarray(subject.time_h, dtype=float)
        horizon = float(observed_times[-1])
        # A dense grid for Cmax/tmax/AUC, with the observation times included so
        # the point-by-point comparison needs no interpolation of the prediction
        # onto a coarser mesh than it was computed on.
        dense = np.unique(
            np.concatenate([np.linspace(0.0, horizon, 481), observed_times])
        )
        y0 = model.initial_state_for_dose(subject.dose_mg)
        result = simulate(
            model,
            t_end_h=horizon,
            output_times_h=dense,
            initial_state=y0,
            check_tolerance_refinement=False,
        )
        curve = result.observable("plasma_concentration")

        at_observed = np.array(
            [curve[int(np.argmin(np.abs(dense - t)))] for t in observed_times]
        )
        observed_conc = np.asarray(subject.concentration_mg_per_L, dtype=float)

        obs_nca = compute_nca(observed_times, observed_conc, dose_mg=subject.dose_mg)
        pred_nca = compute_nca(dense, curve, dose_mg=subject.dose_mg)
        fb = model.oral_bioavailability_estimate()

        predictions.append(
            SubjectPrediction(
                subject_id=sid,
                weight_kg=weight,
                dose_mg=subject.dose_mg,
                time_h=[float(t) for t in observed_times],
                observed_mg_per_L=[float(c) for c in observed_conc],
                predicted_mg_per_L=[float(c) for c in at_observed],
                predicted_fabs=float(result.observable("fraction_absorbed")[-1]),
                predicted_f_hepatic=fb["f_hepatic"],
                hepatic_clint_L_per_h=clint,
                predicted_vss_L_per_kg=float(
                    model.distribution_model.predicted_vss_L() / weight
                ),
                observed_cmax=float(obs_nca.cmax),
                predicted_cmax=float(pred_nca.cmax),
                observed_tmax_h=float(obs_nca.tmax_h),
                predicted_tmax_h=float(pred_nca.tmax_h),
                observed_auc=float(obs_nca.auc_0_inf or obs_nca.auc_0_last),
                predicted_auc=float(pred_nca.auc_0_inf or pred_nca.auc_0_last),
                mass_balance_relative_error=float(
                    model.mass_balance_error(result.states[:, -1])
                ),
            )
        )
        all_observed.extend(float(c) for c in observed_conc)
        all_predicted.extend(float(c) for c in at_observed)

    observed_array = np.asarray(all_observed)
    predicted_array = np.asarray(all_predicted)
    pointwise = compute_agreement(observed_array, predicted_array, units="mg/L")

    summary = {
        "cmax": _fold_summary(
            np.array([p.predicted_cmax for p in predictions]),
            np.array([p.observed_cmax for p in predictions]),
        ),
        "tmax": _fold_summary(
            np.array([p.predicted_tmax_h for p in predictions]),
            np.array([p.observed_tmax_h for p in predictions]),
        ),
        "auc": _fold_summary(
            np.array([p.predicted_auc for p in predictions]),
            np.array([p.observed_auc for p in predictions]),
        ),
    }

    # The comparison that actually matters for interpretation: the empirical
    # one-compartment model fitted THREE parameters to this drug, including the
    # volume of distribution. The PBPK model calibrated ONE and predicted the
    # volume from physicochemistry. A PBPK AAFE close to the empirical one
    # therefore represents a stronger result than the same number would from the
    # empirical model, because it was obtained with two fewer degrees of freedom.
    comparison = {
        "empirical_model_id": "pk_1cmt_foa",
        "empirical_held_out_aafe": empirical.held_out_metrics.absolute_average_fold_error,
        "empirical_held_out_fraction_within_2_fold": (
            empirical.held_out_metrics.fraction_within_2_fold
        ),
        "empirical_fitted_parameter_count": 3,
        "empirical_fitted_parameters": ["CL_per_kg", "V_per_kg", "ka"],
        "pbpk_held_out_aafe": pointwise.absolute_average_fold_error,
        "pbpk_held_out_fraction_within_2_fold": pointwise.fraction_within_2_fold,
        "pbpk_calibrated_parameter_count": 1,
        "pbpk_calibrated_parameters": ["CL_per_kg (inverted to CLint_H)"],
        "note": (
            "Not a like-for-like contest. The empirical model fitted clearance, "
            "volume and an absorption rate constant to theophylline; the PBPK model "
            "calibrated clearance alone and predicted volume and the entire "
            "absorption profile from physicochemistry. Equal accuracy at fewer "
            "degrees of freedom is the meaningful comparison, not a lower AAFE."
        ),
    }

    mean_vss = float(np.mean([p.predicted_vss_L_per_kg for p in predictions]))
    fitted_v_per_kg = empirical.typical_parameters["V_per_kg"]

    interpretation = (
        f"Across {len(predictions)} held-out subjects and "
        f"{pointwise.n} observed plasma concentrations, the whole-body "
        f"oral PBPK model predicts with AAFE {pointwise.absolute_average_fold_error:.3f} "
        f"and AFE {pointwise.average_fold_error:.3f}, with "
        f"{pointwise.fraction_within_2_fold * 100:.0f}% of points within 2-fold. "
        f"Cmax AAFE is {summary['cmax']['aafe']:.3f} and tmax AAFE is "
        f"{summary['tmax']['aafe']:.3f}. The volume of distribution was never "
        f"fitted: it is predicted as {mean_vss:.3f} L/kg from physicochemistry, "
        f"against {fitted_v_per_kg:.3f} L/kg estimated by the empirical model from "
        f"the calibration data, a "
        f"{max(mean_vss / fitted_v_per_kg, fitted_v_per_kg / mean_vss):.2f}-fold "
        "difference."
    )

    caveats = [
        "ONE DRUG, ONE STUDY, ONE POPULATION. Twelve healthy adults given a single "
        "oral theophylline dose. Theophylline is a freely soluble, highly permeable, "
        "low-extraction, minimally bound neutral compound -- close to the easiest "
        "case a PBPK model can be given. Nothing here supports extrapolation to "
        "poorly soluble, highly bound, high-extraction or basic drugs.",
        "AUC is the weak metric: clearance was calibrated, and AUC is approximately "
        "dose times bioavailability divided by clearance, so AUC agreement is partly "
        "a restatement of the calibration. Judge this result on curve shape, Cmax "
        "and tmax.",
        "Clearance was calibrated on six subjects from the same study as the six "
        "evaluated. Out-of-sample across subjects is not out-of-sample across "
        "studies, laboratories or populations.",
        "tmax carries no between-subject variability in gastric emptying, so every "
        "subject receives the same predicted absorption profile shape. This is a "
        "known structural limitation, already documented for the absorption model.",
        "Tissue concentrations remain entirely unvalidated. This protocol tests the "
        "plasma prediction only. No observed human tissue concentration data ships "
        "with SYNTHBODY, and agreement in plasma does not establish that any "
        "individual organ compartment is right.",
    ]

    return PBPKValidationResult(
        model_id="pbpk_oral_acat",
        protocol=(
            "Deterministic odd/even subject split on R datasets::Theoph. Hepatic "
            "intrinsic clearance inverted from the calibration-subject plasma "
            "clearance through the well-stirred model; all twelve tissue partition "
            "coefficients and the entire GI absorption profile predicted a priori "
            "from physicochemistry at the pre-specified effective permeability. "
            "Held-out subjects evaluated point by point at the observed sampling "
            "times, with no per-subject adjustment."
        ),
        inputs={
            "physchem": THEOPHYLLINE_PBPK_INPUTS,
            "peff_cm_per_s": peff_cm_per_s,
            "particle_radius_um": particle_radius_um,
            "renal_fraction_of_clearance": renal_fraction_of_clearance,
            "prespecified": peff_cm_per_s == PRESPECIFIED_PEFF_CM_PER_S,
        },
        calibration_subject_ids=list(calibration_subject_ids),
        held_out_subject_ids=held_out,
        calibrated_clearance_L_per_h_per_kg=float(cl_per_kg),
        predictions=predictions,
        pointwise_metrics={
            "aafe": pointwise.absolute_average_fold_error,
            "afe": pointwise.average_fold_error,
            "rmse": pointwise.rmse,
            "fraction_within_2_fold": pointwise.fraction_within_2_fold,
            "fraction_within_1_5_fold": pointwise.fraction_within_1_5_fold,
            "median_absolute_percent_error": pointwise.median_absolute_percent_error,
            "n_observations": float(pointwise.n),
            "r_squared_identity": pointwise.r_squared_vs_identity,
            "concordance_correlation": pointwise.concordance_correlation,
        },
        metric_summary=summary,
        comparison_to_empirical_model=comparison,
        interpretation=interpretation,
        caveats=caveats,
    )
