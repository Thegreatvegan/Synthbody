"""
Population variability and Monte Carlo uncertainty propagation.

Two sources of variability are represented and kept distinct, because conflating
them is a classic way to produce confidence bands that mean nothing:

  Between-subject variability (BSV / IIV)
      Real biological differences between individuals. Modelled as log-normal
      random effects on structural parameters:  P_i = P_typical * exp(eta_i).
      Reported as a prediction interval for an individual.

  Residual unexplained variability (RUV)
      Assay error and model misspecification at the level of a single
      measurement. Combined additive-plus-proportional. It widens what you would
      *observe*, not what the typical patient's exposure *is*.

The simulator reports the structural prediction interval by default and adds
residual error only when explicitly asked, which is the correct thing to compare
against raw observed scatter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from synthbody.engine.core import BaseModel, DoseEvent, simulate
from synthbody.engine.physiology.covariates import log_normal_sigma_from_cv


@dataclass
class RandomEffect:
    """Log-normal between-subject variability on one structural parameter."""

    parameter: str
    cv_percent: float
    lower_bound: float | None = None
    upper_bound: float | None = None

    @property
    def sigma(self) -> float:
        return log_normal_sigma_from_cv(self.cv_percent)


@dataclass
class ResidualError:
    """Combined residual error model: C_obs = C_pred*(1 + eps_prop) + eps_add."""

    proportional_cv_percent: float = 0.0
    additive_sd: float = 0.0

    @property
    def is_zero(self) -> bool:
        return self.proportional_cv_percent <= 0 and self.additive_sd <= 0


@dataclass
class PopulationSpec:
    """Everything needed to generate a virtual cohort."""

    typical_values: dict[str, float]
    random_effects: list[RandomEffect] = field(default_factory=list)
    correlation: dict[tuple[str, str], float] = field(default_factory=dict)
    residual_error: ResidualError = field(default_factory=ResidualError)

    def parameter_names(self) -> list[str]:
        return [re.parameter for re in self.random_effects]

    def validate(self) -> None:
        for re_ in self.random_effects:
            if re_.parameter not in self.typical_values:
                raise ValueError(
                    f"Random effect on {re_.parameter!r} has no typical value supplied."
                )
        names = self.parameter_names()
        for (a, b), rho in self.correlation.items():
            if a not in names or b not in names:
                raise ValueError(f"Correlation ({a}, {b}) names a parameter with no random effect.")
            if not -1.0 <= rho <= 1.0:
                raise ValueError(f"Correlation ({a}, {b}) = {rho} is outside [-1, 1].")


def _correlation_matrix(spec: PopulationSpec) -> np.ndarray:
    names = spec.parameter_names()
    k = len(names)
    R = np.eye(k)
    idx = {n: i for i, n in enumerate(names)}
    for (a, b), rho in spec.correlation.items():
        i, j = idx[a], idx[b]
        R[i, j] = R[j, i] = rho
    # A user-specified correlation matrix need not be positive semi-definite.
    # Project it onto the nearest PSD matrix rather than failing or, worse,
    # silently sampling from something that is not a distribution.
    eig, vec = np.linalg.eigh(R)
    if (eig < -1e-10).any():
        eig = np.clip(eig, 1e-10, None)
        R = vec @ np.diag(eig) @ vec.T
        d = np.sqrt(np.diag(R))
        R = R / np.outer(d, d)
    return R


def sample_population_parameters(
    spec: PopulationSpec, n_subjects: int, seed: int | None = None
) -> dict[str, np.ndarray]:
    """Draw per-subject structural parameters."""
    spec.validate()
    rng = np.random.default_rng(seed)
    names = spec.parameter_names()
    out = {k: np.full(n_subjects, v, dtype=float) for k, v in spec.typical_values.items()}
    if not names:
        return out

    sigmas = np.array([re_.sigma for re_ in spec.random_effects])
    R = _correlation_matrix(spec)
    cov = np.outer(sigmas, sigmas) * R
    etas = rng.multivariate_normal(np.zeros(len(names)), cov, size=n_subjects)

    truncated = 0
    for i, re_ in enumerate(spec.random_effects):
        vals = spec.typical_values[re_.parameter] * np.exp(etas[:, i])
        if re_.lower_bound is not None:
            truncated += int(np.sum(vals < re_.lower_bound))
            vals = np.maximum(vals, re_.lower_bound)
        if re_.upper_bound is not None:
            truncated += int(np.sum(vals > re_.upper_bound))
            vals = np.minimum(vals, re_.upper_bound)
        out[re_.parameter] = vals
    if truncated:
        out["_n_truncated"] = np.array([truncated], dtype=float)
    return out


def run_population_simulation(
    model_factory: Callable[[dict[str, float]], BaseModel],
    spec: PopulationSpec,
    *,
    t_end_h: float,
    doses: Sequence[DoseEvent],
    output_times_h: np.ndarray,
    observable: str = "plasma_concentration",
    n_subjects: int = 200,
    seed: int = 20261012,
    percentiles: Sequence[float] = (5.0, 25.0, 50.0, 75.0, 95.0),
    include_residual_error: bool = False,
    rtol: float = 1e-8,
    atol: float = 1e-10,
    summary_metric: Callable[[np.ndarray, np.ndarray], dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Monte Carlo cohort simulation.

    Returns per-time percentiles of the observable, the typical-value profile,
    and per-subject summary metrics if `summary_metric` is supplied.
    """
    if n_subjects < 1:
        raise ValueError("n_subjects must be at least 1.")
    params = sample_population_parameters(spec, n_subjects, seed)
    n_truncated = int(params.pop("_n_truncated", np.array([0.0]))[0])
    out_t = np.asarray(output_times_h, float)

    curves = np.full((n_subjects, out_t.size), np.nan)
    per_subject_params: list[dict[str, float]] = []
    metrics: list[dict[str, float]] = []
    failures: list[dict[str, Any]] = []

    for i in range(n_subjects):
        subject = {k: float(v[i]) for k, v in params.items()}
        per_subject_params.append(subject)
        try:
            model = model_factory(subject)
            res = simulate(
                model,
                t_end_h=t_end_h,
                doses=doses,
                output_times_h=out_t,
                rtol=rtol,
                atol=atol,
                check_tolerance_refinement=False,
            )
            curves[i] = res.observable(observable)
            if summary_metric is not None:
                metrics.append(summary_metric(out_t, curves[i]))
        except Exception as exc:  # a single bad draw must not kill the cohort
            failures.append({"subject": i, "parameters": subject, "error": f"{type(exc).__name__}: {exc}"})

    n_ok = int(np.sum(~np.isnan(curves).all(axis=1)))
    if n_ok == 0:
        raise RuntimeError(
            "Every subject in the cohort failed to simulate. First error: "
            + (failures[0]["error"] if failures else "unknown")
        )

    structural = curves.copy()
    observed_like = None
    if include_residual_error and not spec.residual_error.is_zero:
        rng = np.random.default_rng(seed + 1)
        prop_cv = spec.residual_error.proportional_cv_percent / 100.0
        eps_p = rng.normal(0.0, prop_cv, size=curves.shape) if prop_cv > 0 else 0.0
        eps_a = (
            rng.normal(0.0, spec.residual_error.additive_sd, size=curves.shape)
            if spec.residual_error.additive_sd > 0
            else 0.0
        )
        observed_like = np.clip(curves * (1.0 + eps_p) + eps_a, 0.0, None)

    def pct(arr: np.ndarray) -> dict[str, list[float]]:
        return {
            f"p{p:g}": np.nanpercentile(arr, p, axis=0).tolist() for p in percentiles
        }

    typical_model = model_factory(dict(spec.typical_values))
    typical = simulate(
        typical_model,
        t_end_h=t_end_h,
        doses=doses,
        output_times_h=out_t,
        rtol=rtol,
        atol=atol,
        check_tolerance_refinement=False,
    ).observable(observable)

    result: dict[str, Any] = {
        "n_subjects_requested": n_subjects,
        "n_subjects_simulated": n_ok,
        "n_failures": len(failures),
        "failures": failures[:10],
        "n_parameter_draws_truncated": n_truncated,
        "seed": seed,
        "observable": observable,
        "time_h": out_t.tolist(),
        "typical_value_profile": typical.tolist(),
        "mean": np.nanmean(structural, axis=0).tolist(),
        "structural_percentiles": pct(structural),
        "percentile_levels": list(percentiles),
        "residual_error_included": observed_like is not None,
        "random_effects": [
            {"parameter": re_.parameter, "cv_percent": re_.cv_percent, "sigma": re_.sigma}
            for re_ in spec.random_effects
        ],
        "interpretation": (
            "The structural percentiles describe variability in the underlying exposure of "
            "different individuals. They are NOT confidence intervals on the typical value, "
            "and they do not include measurement error unless residual error was requested."
        ),
    }
    if observed_like is not None:
        result["observation_percentiles"] = pct(observed_like)
        result["residual_error"] = {
            "proportional_cv_percent": spec.residual_error.proportional_cv_percent,
            "additive_sd": spec.residual_error.additive_sd,
        }
    if metrics:
        result["subject_metrics"] = metrics
        result["metric_summary"] = _summarise_metrics(metrics)
    result["subject_parameters"] = per_subject_params[:500]
    return result


def _summarise_metrics(metrics: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    keys = sorted({k for m in metrics for k in m})
    out: dict[str, dict[str, float]] = {}
    for k in keys:
        vals = np.array([m[k] for m in metrics if m.get(k) is not None and np.isfinite(m.get(k, np.nan))])
        if vals.size == 0:
            continue
        out[k] = {
            "n": int(vals.size),
            "mean": float(np.mean(vals)),
            "sd": float(np.std(vals, ddof=1)) if vals.size > 1 else 0.0,
            "cv_percent": float(100.0 * np.std(vals, ddof=1) / np.mean(vals))
            if vals.size > 1 and np.mean(vals) != 0
            else 0.0,
            "median": float(np.median(vals)),
            "p5": float(np.percentile(vals, 5)),
            "p95": float(np.percentile(vals, 95)),
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
            "geometric_mean": float(np.exp(np.mean(np.log(vals)))) if np.all(vals > 0) else float("nan"),
        }
    return out
