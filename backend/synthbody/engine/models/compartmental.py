"""
Compartmental pharmacokinetic models.

Each model provides:
  * the ODE right-hand side used by the solver,
  * an analytic closed-form solution where one exists, used by the test suite
    to verify the numerical path rather than to serve results, and
  * an analytic Jacobian, which makes the stiff solvers both faster and better
    behaved.

Mass is tracked in mg, time in hours, volume in L, concentration in mg/L
(equivalently ug/mL). An explicit cumulative-eliminated state is carried in
every model so the engine can run a true mass-balance check.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from synthbody.engine.core import BaseModel
from synthbody.engine.provenance import ParameterOrigin, ParameterRecord, ValidationStatus


# ===========================================================================
# One compartment, first-order absorption (the theophylline workhorse)
# ===========================================================================
@dataclass
class OneCompartmentFirstOrderAbsorption(BaseModel):
    """One-compartment model with a first-order absorption depot.

    States: [A_depot, A_central, A_eliminated]

        dA_depot/dt     = -ka * A_depot
        dA_central/dt   =  F * ka * A_depot - (CL/V) * A_central
        dA_eliminated/dt= (CL/V) * A_central

    Bioavailability F multiplies the flux leaving the depot, so the depot is the
    administered amount and only the fraction F ever reaches the circulation.
    The balance is routed to the eliminated state as first-pass loss, which
    keeps the mass-balance check meaningful.
    """

    cl_L_per_h: float
    v_L: float
    ka_per_h: float
    bioavailability: float = 1.0
    lag_time_h: float = 0.0

    model_id: str = field(default="pk_1cmt_foa", init=False)
    model_name: str = field(default="One-compartment PK, first-order absorption", init=False)
    model_version: str = field(default="1.0.0", init=False)

    def __post_init__(self) -> None:
        if self.cl_L_per_h <= 0:
            raise ValueError("CL must be positive.")
        if self.v_L <= 0:
            raise ValueError("V must be positive.")
        if self.ka_per_h <= 0:
            raise ValueError("ka must be positive.")
        if not 0.0 < self.bioavailability <= 1.0:
            raise ValueError("bioavailability must be in (0, 1].")
        if self.lag_time_h < 0:
            raise ValueError("lag_time_h cannot be negative.")

    description = (
        "Linear one-compartment disposition with a first-order absorption depot. "
        "The standard structural model for orally administered theophylline."
    )
    validation_status = ValidationStatus.INDEPENDENTLY_VALIDATED
    validation_summary = (
        "Parameters estimated from a calibration subset of the Theoph dataset and "
        "evaluated on held-out subjects. See the Validation workspace for the "
        "numbers actually achieved."
    )
    reference_ids = ["boeckmann1994", "upton1980", "hendeles1996"]
    assumptions = [
        "Absorption is a single first-order process from one depot.",
        "Disposition is linear: clearance and volume do not depend on concentration.",
        "Instantaneous and complete distribution within the central compartment.",
        "Bioavailability is constant across doses and does not saturate.",
    ]
    limitations = [
        "Cannot represent a distribution phase; an IV profile with a visible "
        "biexponential decline needs the two-compartment model.",
        "No enterohepatic recirculation, no transit-compartment absorption delay "
        "beyond a simple lag, no capacity-limited metabolism.",
        "Fitted to healthy-adult single-dose oral data; extrapolation to children, "
        "hepatic impairment or chronic dosing is unvalidated.",
    ]

    # ------------------------------------------------------------------ states
    @property
    def state_names(self) -> list[str]:
        return ["A_depot_mg", "A_central_mg", "A_eliminated_mg"]

    def eliminated_state_index(self) -> int | None:
        return 2

    @property
    def observable_units(self) -> dict[str, str]:
        return {
            "plasma_concentration": "mg/L",
            "amount_central": "mg",
            "amount_depot": "mg",
            "amount_eliminated": "mg",
        }

    # ------------------------------------------------------------- derivatives
    @property
    def ke_per_h(self) -> float:
        return self.cl_L_per_h / self.v_L

    @property
    def half_life_h(self) -> float:
        return float(np.log(2.0) / self.ke_per_h)

    def rhs(self, t: float, y: np.ndarray, infusion_rate: np.ndarray) -> np.ndarray:
        a_depot, a_central, _ = y
        ka, ke, f = self.ka_per_h, self.ke_per_h, self.bioavailability
        out_of_depot = ka * a_depot
        return np.array(
            [
                infusion_rate[0] - out_of_depot,
                infusion_rate[1] + f * out_of_depot - ke * a_central,
                # systemic elimination plus the first-pass fraction that never arrived
                ke * a_central + (1.0 - f) * out_of_depot,
            ]
        )

    def jacobian(self, t: float, y: np.ndarray, infusion_rate: np.ndarray):
        ka, ke, f = self.ka_per_h, self.ke_per_h, self.bioavailability
        return np.array(
            [
                [-ka, 0.0, 0.0],
                [f * ka, -ke, 0.0],
                [(1.0 - f) * ka, ke, 0.0],
            ]
        )

    def observables(self, t: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
        return {
            "plasma_concentration": y[1] / self.v_L,
            "amount_depot": y[0],
            "amount_central": y[1],
            "amount_eliminated": y[2],
        }

    def preferred_method(self) -> str | None:
        return "LSODA"

    # ---------------------------------------------------------------- analytic
    def analytic_concentration(self, t: np.ndarray, dose_mg: float, t_dose_h: float = 0.0):
        """Bateman function for a single oral dose. Used to verify the solver.

            C(t) = F*D*ka / (V*(ka-ke)) * (exp(-ke*tau) - exp(-ka*tau))

        with the ka == ke limiting form handled separately.
        """
        tau = np.asarray(t, float) - t_dose_h - self.lag_time_h
        ka, ke, v, f = self.ka_per_h, self.ke_per_h, self.v_L, self.bioavailability
        c = np.zeros_like(tau)
        m = tau > 0
        if abs(ka - ke) < 1e-12:
            c[m] = (f * dose_mg / v) * ka * tau[m] * np.exp(-ka * tau[m])
        else:
            c[m] = (f * dose_mg * ka) / (v * (ka - ke)) * (
                np.exp(-ke * tau[m]) - np.exp(-ka * tau[m])
            )
        return c

    def parameter_records(self) -> list[ParameterRecord]:
        return [
            ParameterRecord(
                "CL", self.cl_L_per_h, "L/h", ParameterOrigin.USER,
                "Apparent total clearance (CL/F for oral data).",
            ),
            ParameterRecord(
                "V", self.v_L, "L", ParameterOrigin.USER,
                "Apparent central volume of distribution (V/F for oral data).",
            ),
            ParameterRecord(
                "ka", self.ka_per_h, "1/h", ParameterOrigin.USER,
                "First-order absorption rate constant.",
            ),
            ParameterRecord(
                "F", self.bioavailability, "", ParameterOrigin.USER,
                "Bioavailable fraction. Not identifiable from oral data alone; when "
                "fitting oral-only data this is fixed and CL/V are apparent values.",
            ),
            ParameterRecord(
                "t_lag", self.lag_time_h, "h", ParameterOrigin.USER, "Absorption lag time."
            ),
            ParameterRecord(
                "ke", self.ke_per_h, "1/h", ParameterOrigin.DERIVED, "CL/V.",
            ),
            ParameterRecord(
                "t_half", self.half_life_h, "h", ParameterOrigin.DERIVED, "ln(2)/ke.",
            ),
        ]


# ===========================================================================
# Two compartment (the indomethacin workhorse)
# ===========================================================================
@dataclass
class TwoCompartment(BaseModel):
    """Two-compartment linear disposition with an optional absorption depot.

    States: [A_depot, A_central, A_peripheral, A_eliminated]

        dA_depot/dt      = -ka*A_depot
        dA_central/dt    =  F*ka*A_depot - (CL/V1 + Q/V1)*A_central + (Q/V2)*A_periph
        dA_peripheral/dt =  (Q/V1)*A_central - (Q/V2)*A_periph
        dA_eliminated/dt =  (CL/V1)*A_central

    Setting ka to None makes the model IV-only; the depot state remains for a
    uniform state layout but is never dosed.
    """

    cl_L_per_h: float
    v1_L: float
    q_L_per_h: float
    v2_L: float
    ka_per_h: float | None = None
    bioavailability: float = 1.0

    model_id: str = field(default="pk_2cmt", init=False)
    model_name: str = field(default="Two-compartment PK", init=False)
    model_version: str = field(default="1.0.0", init=False)

    def __post_init__(self) -> None:
        for name, v in (
            ("CL", self.cl_L_per_h),
            ("V1", self.v1_L),
            ("Q", self.q_L_per_h),
            ("V2", self.v2_L),
        ):
            if v <= 0:
                raise ValueError(f"{name} must be positive, got {v}.")
        if self.ka_per_h is not None and self.ka_per_h <= 0:
            raise ValueError("ka must be positive when provided.")
        if not 0.0 < self.bioavailability <= 1.0:
            raise ValueError("bioavailability must be in (0, 1].")

    description = (
        "Linear two-compartment disposition, the standard structure for drugs "
        "showing a distinct distribution phase after intravenous administration."
    )
    validation_status = ValidationStatus.INDEPENDENTLY_VALIDATED
    validation_summary = (
        "Parameters estimated from a calibration subset of the Indometh dataset and "
        "evaluated on held-out subjects."
    )
    reference_ids = ["kwan1976"]
    assumptions = [
        "Two kinetically distinct, well-mixed distribution spaces.",
        "Linear, first-order intercompartmental transfer and elimination.",
        "Elimination occurs only from the central compartment.",
    ]
    limitations = [
        "Does not represent enterohepatic recirculation, which the source "
        "indomethacin study explicitly reports. Secondary concentration peaks "
        "will not be reproduced and will appear as fit error.",
        "V2 and Q are only identifiable when the sampling schedule resolves the "
        "distribution phase.",
    ]

    @property
    def state_names(self) -> list[str]:
        return ["A_depot_mg", "A_central_mg", "A_peripheral_mg", "A_eliminated_mg"]

    def eliminated_state_index(self) -> int | None:
        return 3

    @property
    def observable_units(self) -> dict[str, str]:
        return {
            "plasma_concentration": "mg/L",
            "peripheral_concentration": "mg/L",
            "amount_central": "mg",
            "amount_peripheral": "mg",
            "amount_eliminated": "mg",
        }

    # ------------------------------------------------------------ micro-rates
    @property
    def k10(self) -> float:
        return self.cl_L_per_h / self.v1_L

    @property
    def k12(self) -> float:
        return self.q_L_per_h / self.v1_L

    @property
    def k21(self) -> float:
        return self.q_L_per_h / self.v2_L

    @property
    def hybrid_rate_constants(self) -> tuple[float, float]:
        """(alpha, beta) with alpha >= beta, from the characteristic polynomial."""
        s = self.k10 + self.k12 + self.k21
        p = self.k10 * self.k21
        disc = max(s * s - 4.0 * p, 0.0)
        root = float(np.sqrt(disc))
        return (s + root) / 2.0, (s - root) / 2.0

    @property
    def terminal_half_life_h(self) -> float:
        _, beta = self.hybrid_rate_constants
        return float(np.log(2.0) / beta)

    @property
    def vss_L(self) -> float:
        return self.v1_L + self.v2_L

    def rhs(self, t: float, y: np.ndarray, infusion_rate: np.ndarray) -> np.ndarray:
        a_dep, a1, a2, _ = y
        ka = self.ka_per_h or 0.0
        f = self.bioavailability
        out_depot = ka * a_dep
        k10, k12, k21 = self.k10, self.k12, self.k21
        return np.array(
            [
                infusion_rate[0] - out_depot,
                infusion_rate[1] + f * out_depot - (k10 + k12) * a1 + k21 * a2,
                infusion_rate[2] + k12 * a1 - k21 * a2,
                k10 * a1 + (1.0 - f) * out_depot,
            ]
        )

    def jacobian(self, t: float, y: np.ndarray, infusion_rate: np.ndarray):
        ka = self.ka_per_h or 0.0
        f = self.bioavailability
        k10, k12, k21 = self.k10, self.k12, self.k21
        return np.array(
            [
                [-ka, 0.0, 0.0, 0.0],
                [f * ka, -(k10 + k12), k21, 0.0],
                [0.0, k12, -k21, 0.0],
                [(1.0 - f) * ka, k10, 0.0, 0.0],
            ]
        )

    def observables(self, t: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
        return {
            "plasma_concentration": y[1] / self.v1_L,
            "peripheral_concentration": y[2] / self.v2_L,
            "amount_central": y[1],
            "amount_peripheral": y[2],
            "amount_eliminated": y[3],
        }

    def preferred_method(self) -> str | None:
        return "LSODA"

    # ---------------------------------------------------------------- analytic
    def analytic_concentration_iv_bolus(
        self, t: np.ndarray, dose_mg: float, t_dose_h: float = 0.0
    ) -> np.ndarray:
        """Biexponential solution for an IV bolus. Used to verify the solver.

            C(t) = A*exp(-alpha*tau) + B*exp(-beta*tau)
            A = (D/V1)*(alpha - k21)/(alpha - beta)
            B = (D/V1)*(k21 - beta)/(alpha - beta)
        """
        tau = np.asarray(t, float) - t_dose_h
        alpha, beta = self.hybrid_rate_constants
        k21 = self.k21
        c = np.zeros_like(tau)
        m = tau >= 0
        if abs(alpha - beta) < 1e-14:  # pragma: no cover - degenerate
            c[m] = (dose_mg / self.v1_L) * np.exp(-alpha * tau[m])
            return c
        a_coef = (dose_mg / self.v1_L) * (alpha - k21) / (alpha - beta)
        b_coef = (dose_mg / self.v1_L) * (k21 - beta) / (alpha - beta)
        c[m] = a_coef * np.exp(-alpha * tau[m]) + b_coef * np.exp(-beta * tau[m])
        return c

    def parameter_records(self) -> list[ParameterRecord]:
        alpha, beta = self.hybrid_rate_constants
        recs = [
            ParameterRecord("CL", self.cl_L_per_h, "L/h", ParameterOrigin.USER, "Total clearance."),
            ParameterRecord("V1", self.v1_L, "L", ParameterOrigin.USER, "Central volume."),
            ParameterRecord(
                "Q", self.q_L_per_h, "L/h", ParameterOrigin.USER, "Intercompartmental clearance."
            ),
            ParameterRecord("V2", self.v2_L, "L", ParameterOrigin.USER, "Peripheral volume."),
            ParameterRecord("alpha", alpha, "1/h", ParameterOrigin.DERIVED, "Distribution rate."),
            ParameterRecord("beta", beta, "1/h", ParameterOrigin.DERIVED, "Terminal rate."),
            ParameterRecord("Vss", self.vss_L, "L", ParameterOrigin.DERIVED, "V1 + V2."),
            ParameterRecord(
                "t_half_terminal", self.terminal_half_life_h, "h",
                ParameterOrigin.DERIVED, "ln(2)/beta.",
            ),
        ]
        if self.ka_per_h is not None:
            recs.insert(
                4,
                ParameterRecord(
                    "ka", self.ka_per_h, "1/h", ParameterOrigin.USER, "Absorption rate constant."
                ),
            )
        return recs


# ===========================================================================
# Capacity-limited (Michaelis-Menten) elimination
# ===========================================================================
@dataclass
class OneCompartmentMichaelisMenten(BaseModel):
    """One-compartment model with saturable (Michaelis-Menten) elimination.

    States: [A_depot, A_central, A_eliminated]

        elimination rate = Vmax * C / (Km + C),  C = A_central / V

    This is the structure that makes phenytoin dosing dangerous: once C
    approaches Km the relationship between dose and steady-state exposure stops
    being proportional. It has no closed-form solution, which is exactly why the
    numerical path and its diagnostics matter.
    """

    vmax_mg_per_h: float
    km_mg_per_L: float
    v_L: float
    ka_per_h: float | None = None
    bioavailability: float = 1.0

    model_id: str = field(default="pk_1cmt_mm", init=False)
    model_name: str = field(default="One-compartment PK, Michaelis-Menten elimination", init=False)
    model_version: str = field(default="1.0.0", init=False)

    def __post_init__(self) -> None:
        if self.vmax_mg_per_h <= 0:
            raise ValueError("Vmax must be positive.")
        if self.km_mg_per_L <= 0:
            raise ValueError("Km must be positive.")
        if self.v_L <= 0:
            raise ValueError("V must be positive.")
        if self.ka_per_h is not None and self.ka_per_h <= 0:
            raise ValueError("ka must be positive when provided.")

    description = (
        "Saturable elimination following Michaelis-Menten kinetics, the classical "
        "non-linear pharmacokinetic structure."
    )
    validation_status = ValidationStatus.STRUCTURALLY_VERIFIED
    validation_summary = (
        "Numerics verified against the linear limit (C << Km reproduces first-order "
        "kinetics with CL = Vmax/Km) and by mass balance. NOT compared against any "
        "observed concentration data in this release: SYNTHBODY ships no licensed "
        "non-linear PK dataset. Treat quantitative output as research-only."
    )
    reference_ids = []
    assumptions = [
        "A single saturable elimination pathway with no parallel first-order route.",
        "Vmax and Km are time-invariant (no autoinduction or inhibition).",
    ]
    limitations = [
        "No observed-data validation has been performed for this structure here.",
        "Vmax and Km are poorly identifiable from concentrations that all sit well "
        "below or well above Km.",
        "The parameters shipped with any example using this model are illustrative "
        "defaults, not measured values for a specific drug.",
    ]

    @property
    def state_names(self) -> list[str]:
        return ["A_depot_mg", "A_central_mg", "A_eliminated_mg"]

    def eliminated_state_index(self) -> int | None:
        return 2

    @property
    def observable_units(self) -> dict[str, str]:
        return {
            "plasma_concentration": "mg/L",
            "instantaneous_clearance": "L/h",
            "saturation_fraction": "",
            "amount_eliminated": "mg",
        }

    def _elimination_rate(self, a_central: float) -> float:
        c = a_central / self.v_L
        return self.vmax_mg_per_h * c / (self.km_mg_per_L + c)

    def rhs(self, t: float, y: np.ndarray, infusion_rate: np.ndarray) -> np.ndarray:
        a_dep, a1, _ = y
        ka = self.ka_per_h or 0.0
        f = self.bioavailability
        out_depot = ka * a_dep
        elim = self._elimination_rate(a1)
        return np.array(
            [
                infusion_rate[0] - out_depot,
                infusion_rate[1] + f * out_depot - elim,
                elim + (1.0 - f) * out_depot,
            ]
        )

    def jacobian(self, t: float, y: np.ndarray, infusion_rate: np.ndarray):
        ka = self.ka_per_h or 0.0
        f = self.bioavailability
        c = y[1] / self.v_L
        # d(elim)/dA1 = Vmax*Km / (V*(Km+C)^2)
        d_elim = self.vmax_mg_per_h * self.km_mg_per_L / (self.v_L * (self.km_mg_per_L + c) ** 2)
        return np.array(
            [
                [-ka, 0.0, 0.0],
                [f * ka, -d_elim, 0.0],
                [(1.0 - f) * ka, d_elim, 0.0],
            ]
        )

    def observables(self, t: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
        c = y[1] / self.v_L
        return {
            "plasma_concentration": c,
            # Vmax/(Km+C): the clearance an observer would infer at this concentration
            "instantaneous_clearance": self.vmax_mg_per_h / (self.km_mg_per_L + c),
            "saturation_fraction": c / (self.km_mg_per_L + c),
            "amount_eliminated": y[2],
        }

    def preferred_method(self) -> str | None:
        # Saturable elimination makes the system stiff at high concentration.
        return "LSODA"

    @property
    def linear_limit_clearance_L_per_h(self) -> float:
        """Vmax/Km: the clearance this model converges to when C << Km."""
        return self.vmax_mg_per_h / self.km_mg_per_L

    def maximum_sustainable_input_mg_per_h(self) -> float:
        """Input above Vmax cannot reach steady state; concentration grows without bound."""
        return self.vmax_mg_per_h

    def parameter_records(self) -> list[ParameterRecord]:
        return [
            ParameterRecord(
                "Vmax", self.vmax_mg_per_h, "mg", ParameterOrigin.USER,
                "Maximum elimination rate (mg per hour).",
                notes="Declared in mg; the per-hour sense is implied by the rate context.",
            ),
            ParameterRecord(
                "Km", self.km_mg_per_L, "mg/L", ParameterOrigin.USER,
                "Concentration at half-maximal elimination rate.",
            ),
            ParameterRecord("V", self.v_L, "L", ParameterOrigin.USER, "Volume of distribution."),
            ParameterRecord(
                "CL_linear_limit", self.linear_limit_clearance_L_per_h, "L/h",
                ParameterOrigin.DERIVED, "Vmax/Km, the clearance approached when C << Km.",
            ),
        ]
