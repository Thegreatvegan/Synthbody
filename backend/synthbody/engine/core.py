"""
Model contract + ODE integration core.

Design rules:
  * Model definitions never import anything from the API or the database.
  * Dosing is handled by splitting the integration at event times rather than
    by adding smooth approximations of a bolus. An IV bolus is a true state
    discontinuity; smoothing it is how you get quietly wrong Cmax.
  * Every run is accompanied by diagnostics the engine computed itself
    (mass balance, negative states, a tolerance-refinement check), not just
    whatever the solver reported about itself.
"""
from __future__ import annotations

import time
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np
from scipy.integrate import solve_ivp

from synthbody.engine.provenance import (
    ParameterRecord,
    ProvenanceRecord,
    SolverDiagnostics,
    ValidationStatus,
)

STIFF_METHODS = {"LSODA", "BDF", "Radau"}
ALL_METHODS = {"LSODA", "BDF", "Radau", "RK45", "DOP853"}

ROUTE_IV_BOLUS = "iv_bolus"
ROUTE_IV_INFUSION = "iv_infusion"
ROUTE_ORAL = "oral"
INSTANTANEOUS_ROUTES = (ROUTE_IV_BOLUS, ROUTE_ORAL)


# ---------------------------------------------------------------------------
# Dosing
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DoseEvent:
    """A single administration.

    time_h
        When the administration starts.
    amount_mg
        Total amount delivered by this event.
    route
        One of iv_bolus, iv_infusion, oral.
    duration_h
        Infusion duration. Ignored for bolus and oral routes.
    target_state
        Index of the state that receives the drug (depot for oral, central for IV).
    """

    time_h: float
    amount_mg: float
    route: str
    duration_h: float = 0.0
    target_state: int = 0

    @property
    def is_instantaneous(self) -> bool:
        return self.route in INSTANTANEOUS_ROUTES or self.duration_h <= 0

    @property
    def end_h(self) -> float:
        return self.time_h if self.is_instantaneous else self.time_h + self.duration_h

    @property
    def rate_mg_per_h(self) -> float:
        if self.is_instantaneous:
            return 0.0
        return self.amount_mg / self.duration_h


def expand_regimen(
    amount_mg: float,
    route: str,
    n_doses: int,
    interval_h: float,
    start_h: float = 0.0,
    duration_h: float = 0.0,
    target_state: int = 0,
) -> list[DoseEvent]:
    """Build a multiple-dose regimen. n_doses=1 gives a single dose."""
    if n_doses < 1:
        raise ValueError("n_doses must be >= 1")
    if n_doses > 1 and interval_h <= 0:
        raise ValueError("interval_h must be positive for multiple dosing")
    if n_doses > 1 and duration_h > interval_h:
        raise ValueError("Infusion duration cannot exceed the dosing interval.")
    return [
        DoseEvent(start_h + i * interval_h, amount_mg, route, duration_h, target_state)
        for i in range(n_doses)
    ]


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@dataclass
class SimulationResult:
    t_h: np.ndarray
    states: np.ndarray  # shape (n_states, n_times)
    state_names: list[str]
    observables: dict[str, np.ndarray]
    observable_units: dict[str, str]
    diagnostics: SolverDiagnostics
    provenance: ProvenanceRecord | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def observable(self, name: str) -> np.ndarray:
        if name not in self.observables:
            raise KeyError(f"No observable {name!r}. Available: {sorted(self.observables)}")
        return self.observables[name]


# ---------------------------------------------------------------------------
# Model contract
# ---------------------------------------------------------------------------
class BaseModel(ABC):
    """A SYNTHBODY simulation model.

    Subclasses declare their identity, their parameters (with provenance), the
    ODE right-hand side, and how to turn states into observable quantities.
    """

    model_id: str = "abstract"
    model_name: str = "Abstract model"
    model_version: str = "0.0.0"
    description: str = ""
    validation_status: ValidationStatus = ValidationStatus.NOT_VALIDATED
    validation_summary: str = ""
    reference_ids: list[str] = []
    assumptions: list[str] = []
    limitations: list[str] = []
    parameter_dimensions: dict[str, str] = {}

    # -------------------------------------------------------------- required
    @property
    @abstractmethod
    def state_names(self) -> list[str]:
        """Names of the ODE states, in order. Drug amounts are in mg."""

    @abstractmethod
    def rhs(self, t: float, y: np.ndarray, infusion_rate: np.ndarray) -> np.ndarray:
        """d(state)/dt in mg/h. infusion_rate is the mg/h entering each state."""

    @abstractmethod
    def observables(self, t: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
        """Derived quantities (concentrations, effects) from the state trajectory."""

    # -------------------------------------------------------------- optional
    @property
    def observable_units(self) -> dict[str, str]:
        return {}

    def parameter_records(self) -> list[ParameterRecord]:
        return []

    def initial_state(self) -> np.ndarray:
        return np.zeros(len(self.state_names), dtype=float)

    def jacobian(self, t: float, y: np.ndarray, infusion_rate: np.ndarray):
        """Analytic Jacobian, if available. A stability and speed win for stiff systems."""
        return None

    def eliminated_state_index(self) -> int | None:
        """Index of a cumulative-eliminated-amount state, if the model tracks one.

        Models that provide this get a real mass-balance check: amount dosed in
        must equal amount still in the body plus amount eliminated.
        """
        return None

    def preferred_method(self) -> str | None:
        return None

    # ------------------------------------------------------------ provenance
    def build_provenance(
        self, inputs: dict[str, Any], *, random_seed: int | None = None
    ) -> ProvenanceRecord:
        return ProvenanceRecord(
            model_id=self.model_id,
            model_name=self.model_name,
            model_version=self.model_version,
            parameters=self.parameter_records(),
            inputs=inputs,
            assumptions=list(self.assumptions),
            limitations=list(self.limitations),
            reference_ids=list(self.reference_ids),
            validation_status=self.validation_status,
            validation_summary=self.validation_summary,
            random_seed=random_seed,
        )


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------
def _build_infusion_schedule(
    doses: Sequence[DoseEvent], n_states: int
) -> Callable[[float], np.ndarray]:
    """Piecewise-constant infusion rate vector as a function of time."""
    infusions = [d for d in doses if not d.is_instantaneous]

    def rate(t: float) -> np.ndarray:
        r = np.zeros(n_states)
        for d in infusions:
            # Half-open interval so back-to-back infusions do not double count.
            if d.time_h <= t < d.end_h:
                r[d.target_state] += d.rate_mg_per_h
        return r

    return rate


def _breakpoints(doses: Sequence[DoseEvent], t0: float, t_end: float) -> list[float]:
    """Times at which the RHS is non-smooth and integration must restart."""
    pts = {t0, t_end}
    for d in doses:
        for t in (d.time_h, d.end_h):
            if t0 < t < t_end:
                pts.add(t)
    return sorted(pts)


def simulate(
    model: BaseModel,
    *,
    t_end_h: float,
    doses: Sequence[DoseEvent] = (),
    output_times_h: np.ndarray | None = None,
    t0_h: float = 0.0,
    method: str | None = None,
    rtol: float = 1e-8,
    atol: float = 1e-10,
    max_step_h: float | None = None,
    initial_state: np.ndarray | None = None,
    check_tolerance_refinement: bool = True,
    _refinement_pass: bool = False,
) -> SimulationResult:
    """Integrate a model over [t0_h, t_end_h] applying the given doses.

    Instantaneous doses are added to the state vector at breakpoints; infusions
    enter through the RHS as a piecewise-constant rate. Integration restarts at
    every breakpoint so the solver never steps across a discontinuity.
    """
    if t_end_h <= t0_h:
        raise ValueError(f"t_end_h ({t_end_h}) must exceed t0_h ({t0_h}).")

    method = method or model.preferred_method() or "LSODA"
    if method not in ALL_METHODS:
        raise ValueError(f"Unknown solver method {method!r}. Known: {sorted(ALL_METHODS)}")

    names = model.state_names
    n = len(names)
    y = (model.initial_state() if initial_state is None else np.asarray(initial_state, float)).copy()
    if y.shape != (n,):
        raise ValueError(f"Initial state has shape {y.shape}, expected ({n},).")

    if output_times_h is None:
        output_times_h = np.linspace(t0_h, t_end_h, 601)
    out_t = np.asarray(output_times_h, dtype=float)
    if np.any(np.diff(out_t) < 0):
        raise ValueError("output_times_h must be non-decreasing.")
    if out_t.size == 0:
        raise ValueError("output_times_h must contain at least one time point.")
    if out_t[0] < t0_h - 1e-12 or out_t[-1] > t_end_h + 1e-12:
        raise ValueError("output_times_h must lie within [t0_h, t_end_h].")

    rate_fn = _build_infusion_schedule(doses, n)
    bolus_by_time: dict[float, np.ndarray] = {}
    for d in doses:
        if d.is_instantaneous and t0_h <= d.time_h <= t_end_h:
            vec = bolus_by_time.setdefault(round(d.time_h, 12), np.zeros(n))
            vec[d.target_state] += d.amount_mg

    bps = _breakpoints(doses, t0_h, t_end_h)
    jac_probe = model.jacobian(t0_h, y, rate_fn(t0_h))
    use_jac = jac_probe is not None and method in STIFF_METHODS

    def f(t: float, yy: np.ndarray) -> np.ndarray:
        return model.rhs(t, yy, rate_fn(t))

    def jac(t: float, yy: np.ndarray):
        return model.jacobian(t, yy, rate_fn(t))

    traj_t: list[float] = []
    traj_y: list[np.ndarray] = []
    nfev = njev = nlu = nsteps = 0
    messages: list[str] = []
    success = True
    warns: list[str] = []

    wall0 = time.perf_counter()

    # Apply any dose landing exactly at t0 before the first segment.
    if round(t0_h, 12) in bolus_by_time:
        y = y + bolus_by_time.pop(round(t0_h, 12))
    traj_t.append(t0_h)
    traj_y.append(y.copy())

    for seg_start, seg_end in zip(bps[:-1], bps[1:]):
        seg_out = out_t[(out_t > seg_start) & (out_t <= seg_end)]
        t_eval = np.unique(np.concatenate([seg_out, [seg_end]]))
        kwargs: dict[str, Any] = dict(
            fun=f,
            t_span=(seg_start, seg_end),
            y0=y,
            method=method,
            rtol=rtol,
            atol=atol,
            t_eval=t_eval,
            dense_output=False,
        )
        if use_jac:
            kwargs["jac"] = jac
        if max_step_h is not None:
            kwargs["max_step"] = max_step_h

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sol = solve_ivp(**kwargs)

        nfev += int(sol.nfev)
        njev += int(getattr(sol, "njev", 0) or 0)
        nlu += int(getattr(sol, "nlu", 0) or 0)
        nsteps += int(len(sol.t))
        if not sol.success:
            success = False
            messages.append(f"[{seg_start:g}->{seg_end:g}h] {sol.message}")

        if sol.y.shape[1]:
            traj_t.extend(sol.t.tolist())
            traj_y.extend(sol.y.T.tolist())
            y = sol.y[:, -1].copy()

        # Apply a bolus landing exactly at this breakpoint after recording the
        # pre-dose value, so a trough and the peak that follows are both visible.
        key = round(seg_end, 12)
        if key in bolus_by_time:
            y = y + bolus_by_time.pop(key)
            traj_t.append(seg_end)
            traj_y.append(y.copy())

    wall = time.perf_counter() - wall0

    T = np.asarray(traj_t, float)
    Y = np.asarray(traj_y, float).T  # (n_states, n_points)

    # Resample onto the requested grid. Where a discontinuity produced two
    # values at one time, take the later (post-dose) one.
    Y_out = np.empty((n, out_t.size))
    for i in range(n):
        Y_out[i] = _resample_last(T, Y[i], out_t)

    # --------------------------------------------------------- diagnostics
    min_state = float(Y.min()) if Y.size else 0.0
    max_negative = float(-min_state) if min_state < 0 else 0.0
    # Scale the negativity warning against the largest amount actually present,
    # so 1e-18 mg of round-off on a 300 mg dose does not raise an alarm.
    scale = max(float(np.abs(Y).max()), 1e-30) if Y.size else 1.0
    if max_negative > 1e-6 * scale:
        warns.append(
            f"State went negative by {max_negative:.3g} mg "
            f"({max_negative / scale:.2%} of peak amount) - tighten tolerances or check the model."
        )

    mass_err = _mass_balance_error(model, Y, doses, T)
    if mass_err is not None and mass_err > 1e-4:
        warns.append(f"Mass balance off by {mass_err:.3%} - results are not trustworthy.")

    refine_diff = None
    if check_tolerance_refinement and not _refinement_pass:
        refine_diff = _refinement_check(
            model, t_end_h, doses, out_t, t0_h, method, rtol, atol, max_step_h, initial_state, Y_out
        )
        if refine_diff is not None and refine_diff > 1e-3:
            warns.append(
                f"Tightening tolerances 100x changed the solution by {refine_diff:.3%}; "
                "the reported trajectory is not tolerance-converged."
            )

    diag = SolverDiagnostics(
        method=method,
        rtol=rtol,
        atol=atol,
        success=success,
        message="; ".join(messages) if messages else "ok",
        n_rhs_evaluations=nfev,
        n_jacobian_evaluations=njev,
        n_lu_decompositions=nlu,
        n_steps_accepted=nsteps,
        wall_time_s=wall,
        mass_balance_relative_error=mass_err,
        max_negative_state=max_negative,
        tolerance_refinement_max_rel_diff=refine_diff,
        warnings=warns,
    )

    obs = model.observables(out_t, Y_out)
    return SimulationResult(
        t_h=out_t,
        states=Y_out,
        state_names=list(names),
        observables=obs,
        observable_units=dict(model.observable_units),
        diagnostics=diag,
    )


def _resample_last(T: np.ndarray, y: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Interpolate, but at an exact duplicated time pick the last (post-dose) value."""
    out = np.empty(targets.size)
    for k, tt in enumerate(targets):
        exact = np.flatnonzero(np.isclose(T, tt, rtol=0, atol=1e-10))
        if exact.size:
            out[k] = y[exact[-1]]
        else:
            out[k] = np.interp(tt, T, y)
    return out


def _mass_balance_error(
    model: BaseModel,
    Y: np.ndarray,
    doses: Sequence[DoseEvent],
    T: np.ndarray,
) -> float | None:
    """Relative error in (dosed in) - (in body + eliminated) at the final time."""
    idx = model.eliminated_state_index()
    if idx is None or Y.size == 0:
        return None
    t_last = T[-1]
    delivered = 0.0
    for d in doses:
        if d.time_h > t_last:
            continue
        if d.is_instantaneous:
            delivered += d.amount_mg
        else:
            delivered += d.rate_mg_per_h * (min(d.end_h, t_last) - d.time_h)
    if delivered <= 0:
        return None
    final = Y[:, -1]
    # Everything except the cumulative-eliminated bookkeeping state is "in body".
    in_body = float(final.sum() - final[idx])
    eliminated = float(final[idx])
    return abs(delivered - (in_body + eliminated)) / delivered


def _refinement_check(
    model, t_end_h, doses, out_t, t0_h, method, rtol, atol, max_step_h, initial_state, Y_ref
) -> float | None:
    """Re-solve with 100x tighter tolerances and report the worst relative difference.

    This is the engine checking its own numerics rather than trusting the
    solver's self-report. The cost is one extra solve, which is cheap here.
    """
    try:
        tight = simulate(
            model,
            t_end_h=t_end_h,
            doses=doses,
            output_times_h=out_t,
            t0_h=t0_h,
            method=method,
            rtol=max(rtol * 1e-2, 1e-13),
            atol=max(atol * 1e-2, 1e-16),
            max_step_h=max_step_h,
            initial_state=initial_state,
            check_tolerance_refinement=False,
            _refinement_pass=True,
        )
    except Exception:  # pragma: no cover - refinement is advisory only
        return None
    a, b = np.abs(Y_ref), np.abs(tight.states)
    scale = max(float(np.max(b)), 1e-30)
    # Compare against the global peak rather than pointwise, so the deep tail
    # (where absolute error is irrelevant) does not dominate the metric.
    return float(np.max(np.abs(a - b)) / scale)
