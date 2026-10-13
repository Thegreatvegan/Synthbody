"""
Parameter estimation.

Two estimators, both honest about what they are:

  fit_individual
      Weighted non-linear least squares for one subject's profile, via
      scipy.optimize.least_squares on log-transformed parameters (which keeps
      every parameter positive without bound-hitting pathologies). Returns
      asymptotic standard errors from the Jacobian, the correlation matrix, and
      a condition number so you can see when parameters are not separately
      identifiable.

  fit_two_stage
      The standard two-stage approach: fit each subject independently, then
      summarise the individual estimates. This is NOT a non-linear mixed-effects
      (NONMEM/FOCE) estimation. Two-stage is known to overestimate
      between-subject variance, particularly with sparse data. SYNTHBODY reports
      the estimates it produces and states this bias rather than implying it has
      done population modelling it has not.

Proportional weighting is the default because concentration assay error is
predominantly proportional; the choice is recorded in the result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np
from scipy.optimize import least_squares


@dataclass
class FitSpec:
    """One parameter to estimate."""

    name: str
    initial: float
    lower: float = 1e-12
    upper: float = np.inf
    fixed: bool = False
    unit: str = ""

    def __post_init__(self) -> None:
        if self.initial <= 0:
            raise ValueError(f"{self.name}: estimation is on the log scale, so the initial value must be > 0.")
        if not self.lower < self.upper:
            raise ValueError(f"{self.name}: lower must be < upper.")
        if not self.lower <= self.initial <= self.upper:
            raise ValueError(f"{self.name}: initial value outside [lower, upper].")


@dataclass
class FitResult:
    parameters: dict[str, float]
    standard_errors: dict[str, float | None]
    relative_standard_errors_percent: dict[str, float | None]
    correlation_matrix: list[list[float]] | None
    parameter_order: list[str]
    objective_value: float
    residual_sd: float
    n_observations: int
    n_parameters: int
    converged: bool
    termination_message: str
    n_function_evaluations: int
    weighting: str
    condition_number: float | None
    aic: float | None
    bic: float | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameters": self.parameters,
            "standard_errors": self.standard_errors,
            "relative_standard_errors_percent": self.relative_standard_errors_percent,
            "correlation_matrix": self.correlation_matrix,
            "parameter_order": self.parameter_order,
            "objective_value": self.objective_value,
            "residual_sd": self.residual_sd,
            "n_observations": self.n_observations,
            "n_parameters": self.n_parameters,
            "converged": self.converged,
            "termination_message": self.termination_message,
            "n_function_evaluations": self.n_function_evaluations,
            "weighting": self.weighting,
            "condition_number": self.condition_number,
            "aic": self.aic,
            "bic": self.bic,
            "warnings": self.warnings,
        }


PredictFn = Callable[[dict[str, float], np.ndarray], np.ndarray]


def fit_individual(
    predict: PredictFn,
    t_obs: np.ndarray,
    c_obs: np.ndarray,
    specs: Sequence[FitSpec],
    *,
    weighting: str = "proportional",
    max_nfev: int = 4000,
    x_scale_jac: bool = True,
) -> FitResult:
    """Weighted non-linear least squares on log-transformed parameters."""
    t = np.asarray(t_obs, float).ravel()
    c = np.asarray(c_obs, float).ravel()
    if t.shape != c.shape:
        raise ValueError("t_obs and c_obs must have the same shape.")
    keep = np.isfinite(t) & np.isfinite(c)
    t, c = t[keep], c[keep]
    if t.size == 0:
        raise ValueError("No usable observations.")

    free = [s for s in specs if not s.fixed]
    fixed = {s.name: s.initial for s in specs if s.fixed}
    if not free:
        raise ValueError("At least one parameter must be free.")
    if t.size <= len(free):
        raise ValueError(
            f"{t.size} observations cannot support {len(free)} free parameters."
        )

    names = [s.name for s in free]
    x0 = np.log(np.array([s.initial for s in free]))
    lo = np.log(np.array([max(s.lower, 1e-300) for s in free]))
    hi = np.array([np.log(s.upper) if np.isfinite(s.upper) else np.inf for s in free])

    if weighting not in ("none", "proportional", "sqrt"):
        raise ValueError("weighting must be one of: none, proportional, sqrt")

    def weights(pred: np.ndarray) -> np.ndarray:
        if weighting == "none":
            return np.ones_like(pred)
        # Guard against a near-zero prediction producing an infinite weight.
        floor = max(float(np.max(np.abs(c))) * 1e-3, 1e-12)
        safe = np.maximum(np.abs(pred), floor)
        return 1.0 / safe if weighting == "proportional" else 1.0 / np.sqrt(safe)

    def residuals(x: np.ndarray) -> np.ndarray:
        params = dict(fixed)
        params.update(dict(zip(names, np.exp(x).tolist())))
        pred = np.asarray(predict(params, t), float)
        if pred.shape != c.shape:
            raise ValueError(f"predict returned shape {pred.shape}, expected {c.shape}.")
        if not np.all(np.isfinite(pred)):
            # Steer the optimiser away rather than crashing it.
            return np.full_like(c, 1e6)
        return (pred - c) * weights(pred)

    sol = least_squares(
        residuals,
        x0,
        bounds=(lo, hi),
        max_nfev=max_nfev,
        x_scale="jac" if x_scale_jac else 1.0,
        method="trf",
    )

    est_log = sol.x
    est = dict(fixed)
    est.update(dict(zip(names, np.exp(est_log).tolist())))

    n, p = int(t.size), len(free)
    dof = max(n - p, 1)
    ssr = float(2.0 * sol.cost)
    sigma2 = ssr / dof
    resid_sd = float(np.sqrt(sigma2))

    warnings: list[str] = []
    se: dict[str, float | None] = {k: None for k in names}
    rse: dict[str, float | None] = {k: None for k in names}
    corr: list[list[float]] | None = None
    cond: float | None = None

    try:
        J = sol.jac
        JTJ = J.T @ J
        cond = float(np.linalg.cond(JTJ))
        if cond > 1e10:
            warnings.append(
                f"The Jacobian is near-singular (condition number {cond:.2e}); the parameters "
                "are not separately identifiable from these data and the standard errors below "
                "should not be trusted."
            )
        cov_log = np.linalg.inv(JTJ) * sigma2
        sd_log = np.sqrt(np.clip(np.diag(cov_log), 0.0, None))
        for i, k in enumerate(names):
            # delta method: SE(theta) = theta * SE(log theta)
            se[k] = float(est[k] * sd_log[i])
            rse[k] = float(100.0 * sd_log[i])
        d = np.where(sd_log > 0, sd_log, 1.0)
        corr = (cov_log / np.outer(d, d)).tolist()
    except np.linalg.LinAlgError:
        warnings.append("The covariance matrix could not be computed; no standard errors available.")

    for k in names:
        if rse[k] is not None and rse[k] > 50.0:
            warnings.append(f"{k} has a relative standard error of {rse[k]:.0f}% - poorly estimated.")

    # Gaussian log-likelihood for the weighted residuals, for IC comparison only.
    aic = bic = None
    if ssr > 0:
        ll = -0.5 * n * (np.log(2.0 * np.pi * sigma2) + 1.0)
        aic = float(2.0 * p - 2.0 * ll)
        bic = float(p * np.log(n) - 2.0 * ll)

    if not sol.success:
        warnings.append(f"The optimiser did not converge cleanly: {sol.message}")

    return FitResult(
        parameters=est,
        standard_errors=se,
        relative_standard_errors_percent=rse,
        correlation_matrix=corr,
        parameter_order=names,
        objective_value=ssr,
        residual_sd=resid_sd,
        n_observations=n,
        n_parameters=p,
        converged=bool(sol.success),
        termination_message=str(sol.message),
        n_function_evaluations=int(sol.nfev),
        weighting=weighting,
        condition_number=cond,
        aic=aic,
        bic=bic,
        warnings=warnings,
    )


@dataclass
class TwoStageResult:
    individual_fits: dict[str, FitResult]
    typical_values_geometric_mean: dict[str, float]
    typical_values_arithmetic_mean: dict[str, float]
    between_subject_cv_percent: dict[str, float]
    n_subjects_fitted: int
    n_subjects_failed: int
    failures: dict[str, str]
    method_note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "individual_fits": {k: v.to_dict() for k, v in self.individual_fits.items()},
            "typical_values_geometric_mean": self.typical_values_geometric_mean,
            "typical_values_arithmetic_mean": self.typical_values_arithmetic_mean,
            "between_subject_cv_percent": self.between_subject_cv_percent,
            "n_subjects_fitted": self.n_subjects_fitted,
            "n_subjects_failed": self.n_subjects_failed,
            "failures": self.failures,
            "method_note": self.method_note,
        }


def fit_two_stage(
    predict_for_subject: Callable[[str], PredictFn],
    subject_data: dict[str, tuple[np.ndarray, np.ndarray]],
    specs: Sequence[FitSpec],
    *,
    weighting: str = "proportional",
) -> TwoStageResult:
    """Fit every subject independently, then summarise.

    `predict_for_subject(subject_id)` returns a prediction function closed over
    that subject's dose and covariates.
    """
    fits: dict[str, FitResult] = {}
    failures: dict[str, str] = {}
    for sid, (t, c) in subject_data.items():
        try:
            fits[sid] = fit_individual(
                predict_for_subject(sid), t, c, specs, weighting=weighting
            )
        except Exception as exc:
            failures[sid] = f"{type(exc).__name__}: {exc}"

    if not fits:
        raise RuntimeError(
            "No subject could be fitted. First failure: "
            + (next(iter(failures.values())) if failures else "unknown")
        )

    names = [s.name for s in specs]
    geo: dict[str, float] = {}
    arith: dict[str, float] = {}
    cv: dict[str, float] = {}
    for name in names:
        vals = np.array(
            [f.parameters[name] for f in fits.values() if name in f.parameters], dtype=float
        )
        vals = vals[np.isfinite(vals) & (vals > 0)]
        if vals.size == 0:
            continue
        logv = np.log(vals)
        geo[name] = float(np.exp(np.mean(logv)))
        arith[name] = float(np.mean(vals))
        # CV% from the log-scale SD, matching the log-normal BSV model used in simulation.
        sd_log = float(np.std(logv, ddof=1)) if vals.size > 1 else 0.0
        cv[name] = float(100.0 * np.sqrt(max(np.exp(sd_log**2) - 1.0, 0.0)))

    return TwoStageResult(
        individual_fits=fits,
        typical_values_geometric_mean=geo,
        typical_values_arithmetic_mean=arith,
        between_subject_cv_percent=cv,
        n_subjects_fitted=len(fits),
        n_subjects_failed=len(failures),
        failures=failures,
        method_note=(
            "Standard two-stage estimation: each subject fitted independently, then the "
            "individual estimates summarised. This is NOT non-linear mixed-effects "
            "estimation. Two-stage is known to overestimate between-subject variability, "
            "especially with sparse sampling, because each individual estimate carries its "
            "own estimation error into the variance calculation. The reported CV% is "
            "therefore an upper bound on true between-subject variability."
        ),
    )
