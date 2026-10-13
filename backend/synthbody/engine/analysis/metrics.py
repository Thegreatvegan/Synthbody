"""
Predicted-versus-observed agreement statistics.

Deliberately includes the metrics that are hard to game alongside the flattering
ones. Average fold error (AFE) measures bias and absolute average fold error
(AAFE) measures precision; a model can have AFE = 1.00 (apparently unbiased)
while being wildly imprecise, so both are always reported together.

The "within 2-fold" proportion is the criterion conventionally applied to PBPK
predictions. It is a weak criterion. It is reported because reviewers expect it,
alongside the stricter numbers.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass
class AgreementMetrics:
    n: int
    n_excluded_nonpositive: int
    rmse: float
    nrmse_percent: float
    mae: float
    mean_error: float
    mean_percent_error: float
    mean_absolute_percent_error: float
    median_absolute_percent_error: float
    average_fold_error: float | None
    absolute_average_fold_error: float | None
    fraction_within_1_25_fold: float | None
    fraction_within_1_5_fold: float | None
    fraction_within_2_fold: float | None
    pearson_r: float | None
    r_squared_vs_identity: float
    concordance_correlation: float | None
    observed_mean: float
    predicted_mean: float
    units: str
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_agreement(
    observed: np.ndarray,
    predicted: np.ndarray,
    *,
    units: str = "mg/L",
    exclude_nonpositive_for_fold: bool = True,
) -> AgreementMetrics:
    obs = np.asarray(observed, float).ravel()
    pred = np.asarray(predicted, float).ravel()
    if obs.shape != pred.shape:
        raise ValueError(f"Shape mismatch: observed {obs.shape} vs predicted {pred.shape}.")

    finite = np.isfinite(obs) & np.isfinite(pred)
    notes: list[str] = []
    if not finite.all():
        notes.append(f"{int((~finite).sum())} non-finite pair(s) were excluded.")
    obs, pred = obs[finite], pred[finite]
    if obs.size == 0:
        raise ValueError("No usable observed/predicted pairs.")

    err = pred - obs
    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    obs_mean = float(np.mean(obs))
    pred_mean = float(np.mean(pred))
    obs_range = float(np.max(obs) - np.min(obs))
    nrmse = 100.0 * rmse / obs_range if obs_range > 0 else float("nan")

    # Percent errors need a non-zero denominator.
    nz = obs != 0
    if nz.sum() < obs.size:
        notes.append(
            f"{int((~nz).sum())} observation(s) equal to zero were excluded from percent-error "
            "statistics (percent error is undefined there)."
        )
    pe = 100.0 * err[nz] / obs[nz] if nz.any() else np.array([np.nan])
    mpe = float(np.mean(pe))
    mape = float(np.mean(np.abs(pe)))
    medape = float(np.median(np.abs(pe)))

    # Fold errors require strictly positive values on both sides.
    afe = aafe = None
    f125 = f15 = f2 = None
    n_excl = 0
    if exclude_nonpositive_for_fold:
        pos = (obs > 0) & (pred > 0)
        n_excl = int((~pos).sum())
        if n_excl:
            notes.append(
                f"{n_excl} pair(s) with a non-positive observed or predicted value were "
                "excluded from fold-error statistics."
            )
        if pos.sum() >= 1:
            ratio = pred[pos] / obs[pos]
            log_ratio = np.log10(ratio)
            afe = float(10.0 ** np.mean(log_ratio))
            aafe = float(10.0 ** np.mean(np.abs(log_ratio)))
            fold = np.maximum(ratio, 1.0 / ratio)
            f125 = float(np.mean(fold <= 1.25))
            f15 = float(np.mean(fold <= 1.5))
            f2 = float(np.mean(fold <= 2.0))

    # Pearson r needs variance on both sides.
    r = None
    if obs.size >= 3 and np.std(obs) > 0 and np.std(pred) > 0:
        r = float(np.corrcoef(obs, pred)[0, 1])

    # R^2 against the line of identity, NOT against a fitted regression line.
    # This is the honest version: it can go negative, and should.
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((obs - obs_mean) ** 2))
    r2_identity = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    # Lin's concordance correlation coefficient.
    ccc = None
    if obs.size >= 3:
        vo, vp = float(np.var(obs)), float(np.var(pred))
        cov = float(np.mean((obs - obs_mean) * (pred - pred_mean)))
        denom = vo + vp + (pred_mean - obs_mean) ** 2
        if denom > 0:
            ccc = 2.0 * cov / denom

    return AgreementMetrics(
        n=int(obs.size),
        n_excluded_nonpositive=n_excl,
        rmse=rmse,
        nrmse_percent=nrmse,
        mae=mae,
        mean_error=float(np.mean(err)),
        mean_percent_error=mpe,
        mean_absolute_percent_error=mape,
        median_absolute_percent_error=medape,
        average_fold_error=afe,
        absolute_average_fold_error=aafe,
        fraction_within_1_25_fold=f125,
        fraction_within_1_5_fold=f15,
        fraction_within_2_fold=f2,
        pearson_r=r,
        r_squared_vs_identity=r2_identity,
        concordance_correlation=ccc,
        observed_mean=obs_mean,
        predicted_mean=pred_mean,
        units=units,
        notes=notes,
    )


def residual_diagnostics(
    observed: np.ndarray,
    predicted: np.ndarray,
    *,
    independent_variable: np.ndarray | None = None,
) -> dict[str, Any]:
    """Residuals and a simple test for systematic structure in them.

    Returns raw and weighted residuals plus the Spearman correlation between
    |residual| and the predicted value. A strong positive correlation there says
    the error model should be proportional rather than additive.
    """
    obs = np.asarray(observed, float).ravel()
    pred = np.asarray(predicted, float).ravel()
    finite = np.isfinite(obs) & np.isfinite(pred)
    obs, pred = obs[finite], pred[finite]
    res = obs - pred

    sd = float(np.std(res, ddof=1)) if res.size > 1 else 0.0
    wres = res / sd if sd > 0 else np.zeros_like(res)

    # Proportional residuals, guarding against division by ~0 predictions.
    safe = pred > (np.max(np.abs(pred)) * 1e-9 if pred.size else 1.0)
    prop = np.full_like(res, np.nan)
    prop[safe] = res[safe] / pred[safe]

    spearman = None
    if res.size >= 4:
        spearman = _spearman(np.abs(res), pred)

    out: dict[str, Any] = {
        "residuals": res.tolist(),
        "weighted_residuals": wres.tolist(),
        "proportional_residuals": [None if np.isnan(v) else float(v) for v in prop],
        "predicted": pred.tolist(),
        "observed": obs.tolist(),
        "residual_sd": sd,
        "residual_mean": float(np.mean(res)) if res.size else 0.0,
        "spearman_abs_residual_vs_predicted": spearman,
        "interpretation": (
            "A positive Spearman correlation between |residual| and prediction indicates "
            "heteroscedasticity, i.e. a proportional rather than additive error model."
        ),
    }
    if independent_variable is not None:
        iv = np.asarray(independent_variable, float).ravel()[finite]
        out["independent_variable"] = iv.tolist()
    return out


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def prediction_interval_coverage(
    observed: np.ndarray, simulated_replicates: np.ndarray, level: float = 0.90
) -> dict[str, Any]:
    """Fraction of observations falling inside a simulation-based prediction interval.

    `simulated_replicates` has shape (n_replicates, n_observations).

    This is a coverage check, not a normalised prediction distribution error
    (NPDE) statistic. If the model and its variability model are both adequate,
    coverage should be close to `level`. Substantially higher coverage means the
    variability model is too wide, not that the model is good.
    """
    obs = np.asarray(observed, float).ravel()
    sims = np.asarray(simulated_replicates, float)
    if sims.ndim != 2 or sims.shape[1] != obs.size:
        raise ValueError(
            f"simulated_replicates must have shape (n_replicates, {obs.size}), got {sims.shape}."
        )
    alpha = (1.0 - level) / 2.0
    lo = np.nanpercentile(sims, 100.0 * alpha, axis=0)
    hi = np.nanpercentile(sims, 100.0 * (1.0 - alpha), axis=0)
    inside = (obs >= lo) & (obs <= hi)
    return {
        "level": level,
        "n": int(obs.size),
        "n_inside": int(inside.sum()),
        "coverage": float(np.mean(inside)),
        "expected_coverage": level,
        "lower": lo.tolist(),
        "upper": hi.tolist(),
        "median": np.nanmedian(sims, axis=0).tolist(),
        "note": (
            "Simulation-based prediction-interval coverage. Not an NPDE statistic. "
            "Coverage far above the nominal level indicates an over-wide variability model."
        ),
    }
