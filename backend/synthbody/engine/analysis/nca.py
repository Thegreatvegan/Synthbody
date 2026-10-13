"""
Non-compartmental analysis of a simulated (or observed) concentration-time profile.

These are the exposure metrics a pharmacometrician actually reads off a curve:
Cmax, Tmax, AUC, terminal half-life, clearance, mean residence time, and the
accumulation and fluctuation of a multiple-dose profile.

AUC uses the linear-up / log-down trapezoidal rule, which is the convention in
regulatory NCA because plain linear trapezoids overestimate AUC on a declining
log-linear phase.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass
class NCAResult:
    cmax: float
    tmax_h: float
    cmin: float
    tlast_h: float
    clast: float
    auc_0_last: float
    auc_window_h: tuple[float, float] | None
    auc_0_inf: float | None
    auc_extrap_percent: float | None
    terminal_rate_constant_per_h: float | None
    terminal_half_life_h: float | None
    terminal_fit_r_squared: float | None
    terminal_fit_n_points: int
    clearance_L_per_h: float | None
    volume_terminal_L: float | None
    mean_residence_time_h: float | None
    aumc_0_last: float
    dose_mg: float | None
    units: dict[str, str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _auc_linear_up_log_down(t: np.ndarray, c: np.ndarray) -> float:
    """Linear-up / log-down trapezoidal AUC."""
    total = 0.0
    for i in range(len(t) - 1):
        dt = t[i + 1] - t[i]
        if dt <= 0:
            continue
        c0, c1 = c[i], c[i + 1]
        if c1 > 0 and c0 > 0 and c1 < c0:
            # declining and strictly positive -> log-down
            total += dt * (c0 - c1) / np.log(c0 / c1)
        else:
            total += dt * (c0 + c1) / 2.0
    return float(total)


def _aumc(t: np.ndarray, c: np.ndarray) -> float:
    """First moment curve, linear trapezoid (convention for MRT)."""
    m = t * c
    return float(np.trapezoid(m, t)) if hasattr(np, "trapezoid") else float(np.trapz(m, t))


def _terminal_slope(
    t: np.ndarray, c: np.ndarray, min_points: int = 3
) -> tuple[float | None, float | None, int]:
    """Estimate lambda_z by log-linear regression, choosing the window by adjusted R^2.

    Walks backwards from the last point, adding earlier points while the
    adjusted R-squared improves. This mirrors the automatic lambda_z selection
    used by standard NCA software rather than fixing an arbitrary window.
    """
    pos = c > 0
    tt, cc = t[pos], c[pos]
    if tt.size < min_points:
        return None, None, 0
    peak = int(np.argmax(cc))
    # Only use points after the peak.
    tt, cc = tt[peak:], cc[peak:]
    if tt.size < min_points:
        return None, None, 0

    y = np.log(cc)
    best = (None, None, 0)
    best_adj = -np.inf
    for n in range(min_points, tt.size + 1):
        xs, ys = tt[-n:], y[-n:]
        slope, intercept = np.polyfit(xs, ys, 1)
        pred = slope * xs + intercept
        ss_res = float(np.sum((ys - pred) ** 2))
        ss_tot = float(np.sum((ys - ys.mean()) ** 2))
        if ss_tot <= 0:
            continue
        r2 = 1.0 - ss_res / ss_tot
        adj = 1.0 - (1.0 - r2) * (n - 1) / max(n - 2, 1)
        if adj > best_adj + 1e-12:
            best_adj = adj
            best = (-float(slope), r2, n)
    return best


def compute_nca(
    t_h: np.ndarray,
    concentration: np.ndarray,
    *,
    dose_mg: float | None = None,
    concentration_unit: str = "mg/L",
    dosing_interval_h: float | None = None,
    interval_start_h: float | None = None,
) -> NCAResult:
    """Non-compartmental summary of one profile.

    If `dosing_interval_h` is given, AUC and the peak/trough statistics are
    reported over one dosing interval rather than over the whole profile, which
    is what you want for a multiple-dose regimen.

    `interval_start_h` selects which interval. Callers should pass the time of
    the LAST dose, so the reported AUC(tau) is the interval that actually
    follows a dose. Omitting it falls back to the last complete interval inside
    the simulated window, which is only equivalent when dosing continues to the
    end of the simulation.
    """
    t = np.asarray(t_h, float)
    c = np.asarray(concentration, float)
    if t.shape != c.shape:
        raise ValueError("Time and concentration arrays must have the same shape.")
    if t.size < 2:
        raise ValueError("Need at least two points for NCA.")
    order = np.argsort(t, kind="stable")
    t, c = t[order], c[order]

    warnings: list[str] = []
    if np.any(c < 0):
        warnings.append("Negative concentrations were present and were clipped to zero for NCA.")
        c = np.clip(c, 0.0, None)

    window_t, window_c = t, c
    auc_window: tuple[float, float] | None = None
    if dosing_interval_h and dosing_interval_h > 0:
        if interval_start_h is not None:
            lo = float(interval_start_h)
            hi = lo + dosing_interval_h
            if hi > t[-1] + 1e-12:
                warnings.append(
                    f"The simulation ends at {t[-1]:.3g} h but one dosing interval after the "
                    f"last dose would run to {hi:.3g} h. AUC(tau) is reported over the truncated "
                    f"window {lo:.3g}-{t[-1]:.3g} h and UNDERSTATES the true interval exposure. "
                    "Extend the simulation horizon by at least one interval past the last dose."
                )
                hi = float(t[-1])
        else:
            n_complete = int(np.floor(t[-1] / dosing_interval_h))
            if n_complete < 1:
                warnings.append(
                    "The simulation does not span one complete dosing interval; "
                    "interval AUC was not computed."
                )
                lo = hi = None  # type: ignore[assignment]
            else:
                lo = (n_complete - 1) * dosing_interval_h
                hi = n_complete * dosing_interval_h
        if lo is not None:
            m = (t >= lo - 1e-12) & (t <= hi + 1e-12)
            if m.sum() >= 2:
                window_t, window_c = t[m], c[m]
                auc_window = (float(lo), float(hi))
            else:
                warnings.append(
                    f"Fewer than two output points fall inside the dosing interval "
                    f"{lo:.3g}-{hi:.3g} h; AUC was computed over the whole profile instead. "
                    "Increase n_output_points."
                )

    imax = int(np.argmax(window_c))
    cmax = float(window_c[imax])
    tmax = float(window_t[imax])
    auc_last = _auc_linear_up_log_down(window_t, window_c)
    aumc_last = _aumc(window_t, window_c)

    lam_z, r2, n_pts = _terminal_slope(t, c)
    thalf = float(np.log(2.0) / lam_z) if lam_z and lam_z > 0 else None

    clast = float(c[-1])
    auc_inf: float | None = None
    extrap: float | None = None
    if lam_z and lam_z > 0 and clast > 0:
        auc_inf = auc_last + clast / lam_z
        extrap = 100.0 * (clast / lam_z) / auc_inf if auc_inf > 0 else None
        if extrap is not None and extrap > 20.0:
            warnings.append(
                f"{extrap:.1f}% of AUC(0-inf) is extrapolated beyond the last time point; "
                "AUC(0-inf) and anything derived from it are unreliable. Simulate longer."
            )
    elif clast > 0:
        warnings.append(
            "The terminal phase could not be characterised, so AUC(0-inf) was not computed."
        )

    cl = None
    vz = None
    mrt = None
    if dose_mg is not None and dose_mg > 0:
        basis = auc_inf if auc_inf else None
        if basis and basis > 0:
            cl = dose_mg / basis
            if lam_z and lam_z > 0:
                vz = cl / lam_z
    if auc_last > 0:
        mrt = aumc_last / auc_last

    return NCAResult(
        cmax=cmax,
        tmax_h=tmax,
        cmin=float(np.min(window_c)),
        tlast_h=float(t[-1]),
        clast=clast,
        auc_0_last=auc_last,
        auc_window_h=auc_window,
        auc_0_inf=auc_inf,
        auc_extrap_percent=extrap,
        terminal_rate_constant_per_h=lam_z,
        terminal_half_life_h=thalf,
        terminal_fit_r_squared=r2,
        terminal_fit_n_points=n_pts,
        clearance_L_per_h=cl,
        volume_terminal_L=vz,
        mean_residence_time_h=mrt,
        aumc_0_last=aumc_last,
        dose_mg=dose_mg,
        units={
            "concentration": concentration_unit,
            "time": "h",
            "auc": f"{concentration_unit}*h",
            "clearance": "L/h",
            "volume": "L",
        },
        warnings=warnings,
    )


def accumulation_metrics(
    t_h: np.ndarray,
    concentration: np.ndarray,
    dosing_interval_h: float,
    *,
    n_doses: int | None = None,
    first_dose_h: float = 0.0,
) -> dict[str, float | None]:
    """Peak-to-trough fluctuation and accumulation across a multiple-dose profile.

    When `n_doses` is supplied, intervals are counted from the first dose and
    capped at the number of doses actually given, so the "last interval" is the
    one following the final dose rather than an empty window after dosing stopped.
    """
    t = np.asarray(t_h, float)
    c = np.asarray(concentration, float)
    if dosing_interval_h <= 0:
        raise ValueError("dosing_interval_h must be positive.")
    span = max(t[-1] - first_dose_h, 0.0)
    n_complete = int(np.floor(span / dosing_interval_h))
    if n_doses is not None:
        n_complete = min(n_complete, n_doses)
    if n_complete < 1:
        return {
            "n_complete_intervals": 0,
            "first_interval_auc": None,
            "last_interval_auc": None,
            "accumulation_ratio_auc": None,
            "cmax_ss": None,
            "cmin_ss": None,
            "peak_trough_fluctuation_percent": None,
            "average_concentration_ss": None,
        }

    def interval(i: int) -> tuple[np.ndarray, np.ndarray]:
        lo = first_dose_h + i * dosing_interval_h
        hi = min(lo + dosing_interval_h, float(t[-1]))
        m = (t >= lo - 1e-12) & (t <= hi + 1e-12)
        return t[m], c[m]

    t0, c0 = interval(0)
    tl, cl = interval(n_complete - 1)
    auc_first = _auc_linear_up_log_down(t0, c0) if t0.size >= 2 else None
    auc_last = _auc_linear_up_log_down(tl, cl) if tl.size >= 2 else None
    cmax_ss = float(np.max(cl)) if cl.size else None
    cmin_ss = float(np.min(cl)) if cl.size else None
    cavg = (auc_last / dosing_interval_h) if auc_last else None
    fluct = None
    if cmax_ss is not None and cmin_ss is not None and cavg and cavg > 0:
        fluct = 100.0 * (cmax_ss - cmin_ss) / cavg
    return {
        "n_complete_intervals": n_complete,
        "first_interval_auc": auc_first,
        "last_interval_auc": auc_last,
        "accumulation_ratio_auc": (auc_last / auc_first) if (auc_first and auc_last) else None,
        "cmax_ss": cmax_ss,
        "cmin_ss": cmin_ss,
        "peak_trough_fluctuation_percent": fluct,
        "average_concentration_ss": cavg,
    }


def time_within_range(
    t_h: np.ndarray, concentration: np.ndarray, low: float, high: float
) -> dict[str, float]:
    """Fraction of simulated time spent below / within / above a reference band.

    Implemented by linear interpolation of band crossings so the answer does not
    depend on the output grid spacing.
    """
    if high <= low:
        raise ValueError("high must exceed low.")
    t = np.asarray(t_h, float)
    c = np.asarray(concentration, float)
    total = float(t[-1] - t[0])
    if total <= 0:
        raise ValueError("Profile has zero duration.")

    # Dense resample is sufficient and much simpler than exact crossing algebra;
    # resolution is chosen fine enough that the discretisation error is below
    # the reporting precision.
    n = max(20_000, t.size * 10)
    tt = np.linspace(t[0], t[-1], n)
    cc = np.interp(tt, t, c)
    dt = (t[-1] - t[0]) / (n - 1)
    below = float(np.sum(cc < low) * dt)
    within = float(np.sum((cc >= low) & (cc <= high)) * dt)
    above = float(np.sum(cc > high) * dt)
    return {
        "hours_below": below,
        "hours_within": within,
        "hours_above": above,
        "fraction_below": below / total,
        "fraction_within": within / total,
        "fraction_above": above / total,
        "total_hours": total,
        "band_low": low,
        "band_high": high,
    }
