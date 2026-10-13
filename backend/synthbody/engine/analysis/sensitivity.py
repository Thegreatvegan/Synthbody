"""
Parameter sensitivity analysis.

Three methods, chosen because they answer different questions:

  local     Normalised sensitivity coefficients by central finite differences.
            S_ij = (dY_i / dP_j) * (P_j / Y_i) -- the percent change in output
            per percent change in a parameter, evaluated at one point. Cheap,
            exact at the nominal parameter set, blind to interactions.

  morris    Elementary-effects screening. Ranks parameters by influence across
            the whole input space at O(k) cost per trajectory. Use it to decide
            which parameters are worth a Sobol run.

  sobol     Variance decomposition. Reports what fraction of output variance
            each parameter explains on its own (S1) and including all its
            interactions (ST). ST - S1 is the interaction strength.

Finite differences carry a real risk: too small a step and the answer is
round-off noise, too large and it is not a derivative. The local routine
therefore reports the step actually used and performs a step-halving
consistency check.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

import numpy as np

try:  # SALib is optional; Morris/Sobol degrade gracefully without it.
    from SALib.analyze import morris as morris_analyze
    from SALib.analyze import sobol as sobol_analyze
    from SALib.sample import morris as morris_sample
    from SALib.sample import sobol as sobol_sample

    SALIB_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when SALib is absent
    SALIB_AVAILABLE = False


ScalarObjective = Callable[[dict[str, float]], float]


@dataclass
class ParameterSpec:
    name: str
    nominal: float
    low: float
    high: float
    unit: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if self.low >= self.high:
            raise ValueError(f"{self.name}: low ({self.low}) must be < high ({self.high}).")
        if not self.low <= self.nominal <= self.high:
            raise ValueError(
                f"{self.name}: nominal ({self.nominal}) must lie within [{self.low}, {self.high}]."
            )


# ---------------------------------------------------------------------------
# Local
# ---------------------------------------------------------------------------
def local_sensitivity(
    objective: ScalarObjective,
    specs: Sequence[ParameterSpec],
    *,
    relative_step: float = 1e-3,
    verify_step_halving: bool = True,
) -> dict[str, Any]:
    """Normalised local sensitivity coefficients at the nominal parameter set."""
    nominal = {s.name: s.nominal for s in specs}
    y0 = float(objective(nominal))
    if not np.isfinite(y0):
        raise ValueError("Objective is not finite at the nominal parameter set.")

    rows: list[dict[str, Any]] = []
    for s in specs:
        coef, used_step, note = _central_difference(objective, nominal, s, relative_step, y0)
        check = None
        if verify_step_halving:
            coef_half, _, _ = _central_difference(objective, nominal, s, relative_step / 2.0, y0)
            if coef is not None and coef_half is not None:
                denom = max(abs(coef), 1e-12)
                check = abs(coef - coef_half) / denom
                if check > 0.05:
                    note = (
                        (note + " ") if note else ""
                    ) + (
                        f"Halving the step changed the coefficient by {check:.1%}; the finite "
                        "difference is not well converged for this parameter."
                    )
        rows.append(
            {
                "parameter": s.name,
                "unit": s.unit,
                "nominal": s.nominal,
                "normalised_sensitivity": coef,
                "step_used_relative": used_step,
                "step_halving_relative_change": check,
                "description": s.description,
                "note": note or "",
            }
        )

    ranked = sorted(
        rows,
        key=lambda r: abs(r["normalised_sensitivity"]) if r["normalised_sensitivity"] is not None else -1.0,
        reverse=True,
    )
    return {
        "method": "local_normalised_finite_difference",
        "baseline_objective": y0,
        "results": ranked,
        "interpretation": (
            "A normalised sensitivity of 1.0 means a 1% increase in the parameter produces a "
            "1% increase in the output. Values are valid only at the nominal parameter set and "
            "do not capture interactions."
        ),
    }


def _central_difference(
    objective: ScalarObjective,
    nominal: dict[str, float],
    spec: ParameterSpec,
    relative_step: float,
    y0: float,
) -> tuple[float | None, float, str]:
    p0 = spec.nominal
    if p0 == 0:
        # Fall back to an absolute step scaled to the allowed range.
        h = relative_step * max(abs(spec.high - spec.low), 1.0)
    else:
        h = relative_step * abs(p0)

    # Keep the perturbation inside the declared plausible range.
    note = ""
    hi, lo = p0 + h, p0 - h
    if hi > spec.high or lo < spec.low:
        h = min(spec.high - p0, p0 - spec.low)
        if h <= 0:
            return None, 0.0, "Nominal value sits on a range boundary; no central difference possible."
        note = "Step was shrunk to stay inside the declared parameter range."
        hi, lo = p0 + h, p0 - h

    up, dn = dict(nominal), dict(nominal)
    up[spec.name], dn[spec.name] = hi, lo
    y_up, y_dn = float(objective(up)), float(objective(dn))
    if not (np.isfinite(y_up) and np.isfinite(y_dn)):
        return None, h / abs(p0) if p0 else h, "Objective was non-finite at a perturbed point."

    deriv = (y_up - y_dn) / (2.0 * h)
    if y0 == 0:
        return None, h / abs(p0) if p0 else h, "Baseline output is zero; normalisation is undefined."
    coef = deriv * p0 / y0
    return float(coef), (h / abs(p0) if p0 else h), note


# ---------------------------------------------------------------------------
# Global
# ---------------------------------------------------------------------------
def _problem(specs: Sequence[ParameterSpec]) -> dict[str, Any]:
    return {
        "num_vars": len(specs),
        "names": [s.name for s in specs],
        "bounds": [[s.low, s.high] for s in specs],
    }


def morris_screening(
    objective: ScalarObjective,
    specs: Sequence[ParameterSpec],
    *,
    trajectories: int = 64,
    levels: int = 8,
    seed: int = 20261012,
) -> dict[str, Any]:
    """Morris elementary-effects screening."""
    if not SALIB_AVAILABLE:
        raise RuntimeError("SALib is not installed; Morris screening is unavailable.")
    problem = _problem(specs)
    X = morris_sample.sample(problem, N=trajectories, num_levels=levels, seed=seed)
    Y = _evaluate(objective, problem["names"], X)
    res = morris_analyze.analyze(problem, X, Y, num_levels=levels, seed=seed)

    rows = [
        {
            "parameter": name,
            "mu_star": float(res["mu_star"][i]),
            "mu": float(res["mu"][i]),
            "sigma": float(res["sigma"][i]),
            "mu_star_conf": float(res["mu_star_conf"][i]),
            "unit": specs[i].unit,
        }
        for i, name in enumerate(problem["names"])
    ]
    rows.sort(key=lambda r: r["mu_star"], reverse=True)
    return {
        "method": "morris_elementary_effects",
        "n_model_evaluations": int(X.shape[0]),
        "trajectories": trajectories,
        "levels": levels,
        "seed": seed,
        "results": rows,
        "interpretation": (
            "mu_star ranks overall influence. A large sigma relative to mu_star indicates the "
            "parameter's effect depends on the values of the others (interaction or non-linearity)."
        ),
    }


def sobol_indices(
    objective: ScalarObjective,
    specs: Sequence[ParameterSpec],
    *,
    base_samples: int = 512,
    calc_second_order: bool = False,
    seed: int = 20261012,
) -> dict[str, Any]:
    """Sobol variance-based sensitivity indices."""
    if not SALIB_AVAILABLE:
        raise RuntimeError("SALib is not installed; Sobol analysis is unavailable.")
    if base_samples & (base_samples - 1) != 0:
        raise ValueError("base_samples should be a power of two for the Sobol sequence.")
    problem = _problem(specs)
    X = sobol_sample.sample(problem, N=base_samples, calc_second_order=calc_second_order, seed=seed)
    Y = _evaluate(objective, problem["names"], X)
    res = sobol_analyze.analyze(problem, Y, calc_second_order=calc_second_order, seed=seed)

    rows = [
        {
            "parameter": name,
            "S1": float(res["S1"][i]),
            "S1_conf": float(res["S1_conf"][i]),
            "ST": float(res["ST"][i]),
            "ST_conf": float(res["ST_conf"][i]),
            "interaction_strength": float(res["ST"][i] - res["S1"][i]),
            "unit": specs[i].unit,
        }
        for i, name in enumerate(problem["names"])
    ]
    rows.sort(key=lambda r: r["ST"], reverse=True)
    sum_s1 = float(sum(r["S1"] for r in rows))
    return {
        "method": "sobol_variance_decomposition",
        "n_model_evaluations": int(X.shape[0]),
        "base_samples": base_samples,
        "seed": seed,
        "results": rows,
        "sum_first_order": sum_s1,
        "output_variance": float(np.var(Y)),
        "interpretation": (
            "S1 is the variance fraction explained by a parameter alone; ST includes all its "
            f"interactions. The first-order indices here sum to {sum_s1:.3f}; a value well "
            "below 1 means interactions dominate. Confidence intervals are bootstrap estimates "
            "and widen sharply at small sample sizes."
        ),
    }


def _evaluate(objective: ScalarObjective, names: list[str], X: np.ndarray) -> np.ndarray:
    out = np.empty(X.shape[0])
    for i, row in enumerate(X):
        val = objective(dict(zip(names, row.tolist())))
        out[i] = float(val) if np.isfinite(val) else np.nan
    if np.isnan(out).any():
        n_bad = int(np.isnan(out).sum())
        # Imputing the mean keeps the index machinery usable but biases it toward
        # the centre, so this is surfaced rather than hidden.
        out[np.isnan(out)] = np.nanmean(out)
        raise_note = (
            f"{n_bad} of {out.size} evaluations were non-finite and were replaced by the mean; "
            "sensitivity indices from this run are unreliable."
        )
        import warnings as _w

        _w.warn(raise_note, RuntimeWarning, stacklevel=2)
    return out
