"""
Pharmacodynamic models.

Three structures, all standard and all cited:

  * Direct (sigmoid) Emax               - Holford & Sheiner 1981, PMID 7032803
  * Effect-compartment (link) model     - Sheiner et al. 1979, PMID 761446
  * Indirect response (turnover) models - Dayneka, Garg & Jusko 1993, PMID 8133465

These are applied on top of a PK model: the PK model supplies the driving
concentration, the PD model converts it into an effect. Parameters for PD
models are generally NOT identifiable from concentration data alone, so unless
the operator supplies measured values they are tagged ILLUSTRATIVE and the UI
labels any resulting effect curve as a structural illustration rather than a
prediction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from synthbody.engine.core import BaseModel
from synthbody.engine.provenance import ParameterOrigin, ParameterRecord, ValidationStatus


# ===========================================================================
# Direct effect
# ===========================================================================
@dataclass(frozen=True)
class SigmoidEmax:
    """Direct concentration-effect relationship (no ODE needed).

        E(C) = E0 + Emax * C^gamma / (EC50^gamma + C^gamma)

    gamma = 1 recovers the ordinary hyperbolic Emax model. A negative Emax
    represents an inhibitory effect.
    """

    e0: float = 0.0
    emax: float = 1.0
    ec50: float = 1.0
    hill_gamma: float = 1.0

    def __post_init__(self) -> None:
        if self.ec50 <= 0:
            raise ValueError("EC50 must be positive.")
        if self.hill_gamma <= 0:
            raise ValueError("Hill coefficient must be positive.")

    def effect(self, concentration: np.ndarray) -> np.ndarray:
        c = np.clip(np.asarray(concentration, float), 0.0, None)
        cg = c**self.hill_gamma
        return self.e0 + self.emax * cg / (self.ec50**self.hill_gamma + cg)

    def concentration_for_effect(self, target_effect: float) -> float:
        """Invert the Emax relationship. Returns NaN if the target is unreachable."""
        frac = (target_effect - self.e0) / self.emax if self.emax != 0 else np.nan
        if not np.isfinite(frac) or not 0.0 <= frac < 1.0:
            return float("nan")
        return float(self.ec50 * (frac / (1.0 - frac)) ** (1.0 / self.hill_gamma))

    def parameter_records(self) -> list[ParameterRecord]:
        return [
            ParameterRecord("E0", self.e0, "", ParameterOrigin.USER, "Baseline effect."),
            ParameterRecord("Emax", self.emax, "", ParameterOrigin.USER, "Maximum effect change."),
            ParameterRecord(
                "EC50", self.ec50, "mg/L", ParameterOrigin.USER,
                "Concentration producing half the maximum effect.",
            ),
            ParameterRecord(
                "gamma", self.hill_gamma, "", ParameterOrigin.USER,
                "Hill coefficient (steepness). 1 = hyperbolic Emax.",
            ),
        ]


# ===========================================================================
# Indirect response
# ===========================================================================
class IndirectResponseType(str, Enum):
    """The four structures of Dayneka, Garg & Jusko (1993).

    Response turnover is dR/dt = kin - kout*R. A drug acts on exactly one of
    those two rate constants, either inhibiting or stimulating it.
    """

    INHIBITION_OF_KIN = "inhibition_of_kin"
    INHIBITION_OF_KOUT = "inhibition_of_kout"
    STIMULATION_OF_KIN = "stimulation_of_kin"
    STIMULATION_OF_KOUT = "stimulation_of_kout"


@dataclass
class IndirectResponse(BaseModel):
    """Turnover model driven by an externally supplied concentration function.

    State: [R]

        inhibition:   factor = 1 - Imax*C/(IC50 + C)
        stimulation:  factor = 1 + Smax*C/(SC50 + C)

    applied to kin or kout as selected. Baseline R0 = kin/kout.
    """

    response_type: IndirectResponseType
    kin: float
    kout: float
    ic50_or_sc50: float
    imax_or_smax: float
    concentration_fn: "object"  # Callable[[float], float]
    hill_gamma: float = 1.0

    model_id: str = field(default="pd_indirect_response", init=False)
    model_name: str = field(default="Indirect response (turnover) PD model", init=False)
    model_version: str = field(default="1.0.0", init=False)

    description = (
        "Physiological turnover model in which drug concentration modulates either "
        "the production or the loss rate of a measured response variable."
    )
    validation_status = ValidationStatus.RESEARCH_ONLY
    validation_summary = (
        "Structure implemented from the cited publication and numerically verified "
        "(baseline is stationary at R0 = kin/kout; the model returns to baseline "
        "after drug washout). No pharmacodynamic dataset is shipped, so no "
        "quantitative validation has been performed."
    )
    reference_ids = ["dayneka1993"]
    assumptions = [
        "Response turnover is zero-order production and first-order loss.",
        "The drug modulates exactly one of the two rate constants.",
        "The system is at baseline steady state when dosing begins.",
    ]
    limitations = [
        "No observed pharmacodynamic data validation.",
        "kin, kout and the potency term are not identifiable from PK data; they must "
        "be supplied, and SYNTHBODY defaults for them are illustrative only.",
        "Tolerance, rebound and circadian baseline variation are not represented.",
    ]

    def __post_init__(self) -> None:
        if self.kin <= 0 or self.kout <= 0:
            raise ValueError("kin and kout must be positive.")
        if self.ic50_or_sc50 <= 0:
            raise ValueError("IC50/SC50 must be positive.")
        if self.response_type in (
            IndirectResponseType.INHIBITION_OF_KIN,
            IndirectResponseType.INHIBITION_OF_KOUT,
        ) and not 0.0 <= self.imax_or_smax <= 1.0:
            raise ValueError("Imax must be in [0, 1] for an inhibitory model.")
        if self.imax_or_smax < 0:
            raise ValueError("Smax cannot be negative.")
        if self.hill_gamma <= 0:
            raise ValueError("Hill coefficient must be positive.")

    @property
    def baseline(self) -> float:
        return self.kin / self.kout

    @property
    def state_names(self) -> list[str]:
        return ["response"]

    def initial_state(self) -> np.ndarray:
        return np.array([self.baseline], dtype=float)

    @property
    def observable_units(self) -> dict[str, str]:
        return {
            "response": "",
            "response_pct_baseline": "",
            "driving_concentration": "mg/L",
        }

    def _factor(self, c: float) -> float:
        cg = max(c, 0.0) ** self.hill_gamma
        frac = cg / (self.ic50_or_sc50**self.hill_gamma + cg)
        if self.response_type in (
            IndirectResponseType.INHIBITION_OF_KIN,
            IndirectResponseType.INHIBITION_OF_KOUT,
        ):
            return 1.0 - self.imax_or_smax * frac
        return 1.0 + self.imax_or_smax * frac

    def rhs(self, t: float, y: np.ndarray, infusion_rate: np.ndarray) -> np.ndarray:
        c = float(self.concentration_fn(t))  # type: ignore[operator]
        factor = self._factor(c)
        kin, kout = self.kin, self.kout
        if self.response_type in (
            IndirectResponseType.INHIBITION_OF_KIN,
            IndirectResponseType.STIMULATION_OF_KIN,
        ):
            kin = kin * factor
        else:
            kout = kout * factor
        return np.array([kin - kout * y[0]])

    def observables(self, t: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
        conc = np.array([float(self.concentration_fn(float(tt))) for tt in t])  # type: ignore[operator]
        return {
            "response": y[0],
            "response_pct_baseline": 100.0 * y[0] / self.baseline,
            "driving_concentration": conc,
        }

    def preferred_method(self) -> str | None:
        return "LSODA"

    def parameter_records(self) -> list[ParameterRecord]:
        potency = "IC50" if "inhibition" in self.response_type.value else "SC50"
        effect = "Imax" if "inhibition" in self.response_type.value else "Smax"
        return [
            ParameterRecord(
                "kin", self.kin, "", ParameterOrigin.ILLUSTRATIVE,
                "Zero-order production rate of the response variable.",
                reference_ids=["dayneka1993"],
            ),
            ParameterRecord(
                "kout", self.kout, "1/h", ParameterOrigin.ILLUSTRATIVE,
                "First-order loss rate constant of the response variable.",
                reference_ids=["dayneka1993"],
            ),
            ParameterRecord(
                potency, self.ic50_or_sc50, "mg/L", ParameterOrigin.ILLUSTRATIVE,
                "Concentration producing half the maximal modulation.",
            ),
            ParameterRecord(
                effect, self.imax_or_smax, "", ParameterOrigin.ILLUSTRATIVE,
                "Maximal fractional modulation of the affected rate constant.",
            ),
            ParameterRecord(
                "R0", self.baseline, "", ParameterOrigin.DERIVED, "Baseline response, kin/kout."
            ),
        ]


# ===========================================================================
# Effect compartment
# ===========================================================================
@dataclass
class EffectCompartment(BaseModel):
    """Hypothetical effect compartment linking plasma concentration to effect.

    State: [Ce]

        dCe/dt = ke0 * (Cp(t) - Ce)

    The effect compartment has negligible volume, so it does not perturb the PK.
    Its purpose is to reproduce the hysteresis seen when the effect lags plasma
    concentration. Effect is then an Emax function of Ce rather than of Cp.
    """

    ke0_per_h: float
    concentration_fn: "object"  # Callable[[float], float]
    emax_model: SigmoidEmax | None = None

    model_id: str = field(default="pd_effect_compartment", init=False)
    model_name: str = field(default="Effect-compartment (link) PD model", init=False)
    model_version: str = field(default="1.0.0", init=False)

    description = (
        "Effect-site compartment that delays the concentration driving the "
        "pharmacodynamic response, reproducing concentration-effect hysteresis."
    )
    validation_status = ValidationStatus.RESEARCH_ONLY
    validation_summary = (
        "Structure implemented from the cited publication and numerically verified "
        "(effect-site concentration converges to plasma concentration at steady "
        "state; t1/2,ke0 = ln2/ke0 governs the lag). No observed PD data validation."
    )
    reference_ids = ["sheiner1979", "holford1981"]
    assumptions = [
        "The effect site equilibrates with plasma by a single first-order process.",
        "The effect compartment is kinetically negligible and does not alter the PK.",
    ]
    limitations = [
        "No observed pharmacodynamic data validation.",
        "ke0 is identifiable only from paired concentration and effect measurements, "
        "which SYNTHBODY does not ship.",
    ]

    def __post_init__(self) -> None:
        if self.ke0_per_h <= 0:
            raise ValueError("ke0 must be positive.")

    @property
    def state_names(self) -> list[str]:
        return ["Ce_mg_per_L"]

    @property
    def equilibration_half_life_h(self) -> float:
        return float(np.log(2.0) / self.ke0_per_h)

    @property
    def observable_units(self) -> dict[str, str]:
        return {
            "effect_site_concentration": "mg/L",
            "plasma_concentration": "mg/L",
            "effect": "",
        }

    def rhs(self, t: float, y: np.ndarray, infusion_rate: np.ndarray) -> np.ndarray:
        cp = float(self.concentration_fn(t))  # type: ignore[operator]
        return np.array([self.ke0_per_h * (cp - y[0])])

    def observables(self, t: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
        cp = np.array([float(self.concentration_fn(float(tt))) for tt in t])  # type: ignore[operator]
        out = {"effect_site_concentration": y[0], "plasma_concentration": cp}
        if self.emax_model is not None:
            out["effect"] = self.emax_model.effect(y[0])
        return out

    def preferred_method(self) -> str | None:
        return "LSODA"

    def parameter_records(self) -> list[ParameterRecord]:
        recs = [
            ParameterRecord(
                "ke0", self.ke0_per_h, "1/h", ParameterOrigin.ILLUSTRATIVE,
                "Effect-site equilibration rate constant.",
                reference_ids=["sheiner1979"],
            ),
            ParameterRecord(
                "t_half_ke0", self.equilibration_half_life_h, "h", ParameterOrigin.DERIVED,
                "Effect-site equilibration half-life, ln(2)/ke0.",
            ),
        ]
        if self.emax_model is not None:
            recs.extend(self.emax_model.parameter_records())
        return recs
