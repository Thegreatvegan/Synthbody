"""
Whole-body oral PBPK: mechanistic GI absorption coupled to whole-body distribution.

This module composes two models that already exist in SYNTHBODY rather than
reimplementing either of them:

* ``CompartmentalAbsorption`` -- the seven-compartment CAT/ACAT lumen model
  (gastric emptying, transit, pH-dependent solubility, Nernst-Brunner
  dissolution of shrinking particles, permeability-limited uptake).
* ``PerfusionLimitedPBPK`` -- the twelve-tissue blood-flow-limited distribution
  model with well-stirred hepatic and renal elimination.

Both are held as instances and both ``rhs`` methods are *called*, not copied.
That is deliberate: it means this model cannot drift away from the equations the
existing validated and benchmarked results were produced with. Changing a rate
law in either parent changes it here too, and the baseline regression suite will
notice.

WHAT IS GENUINELY NEW HERE: the absorbed flux is delivered into the **gut tissue
compartment**, which drains through the portal vein into the liver. In the
standalone PBPK model the oral depot empties straight into the liver, and in
``OralAbsorptionWithDisposition`` first pass is applied as two empirical scalar
factors ``f_gut`` and ``f_hepatic``. Here neither is needed:

    lumen --absorption--> gut tissue --portal--> liver --> systemic circulation

so gut-wall and hepatic first-pass extraction both *emerge* from an intrinsic
clearance and a blood flow instead of being supplied as an answer. Oral
bioavailability is an output of this model, not an input to it.

    F = f_abs  x  F_gut  x  F_hepatic

with every factor arising from the structure. Setting the gut-wall intrinsic
clearance to zero (the default) recovers F_gut = 1.

HONEST SCOPE. See ``validation_status``. The accuracy actually achieved against
observed human plasma concentrations is recorded in VALIDATION.md; read it
before using any number this model produces. Nothing here is a dose
recommendation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from synthbody.engine.core import BaseModel
from synthbody.engine.models.absorption import (
    CompartmentalAbsorption,
    GITract,
    OralDrugInput,
)
from synthbody.engine.models.pbpk import PerfusionLimitedPBPK
from synthbody.engine.physiology.partition import DrugPhysChem
from synthbody.engine.physiology.reference_man import ReferencePhysiology
from synthbody.engine.provenance import ParameterOrigin, ParameterRecord, ValidationStatus


@dataclass
class OralPBPK(BaseModel):
    """Seven-compartment GI absorption feeding a twelve-tissue PBPK model.

    State layout -- the absorption block first, then the distribution block::

        0 .. n_abs-1        the CompartmentalAbsorption states, unchanged
        n_abs ..            the PerfusionLimitedPBPK states, unchanged
        last                cumulative gut-wall extraction

    The PBPK block keeps its own first-order oral depot state, but this model
    constructs the PBPK instance with ``ka_per_h=None`` so that depot is inert
    and stays at zero: absorption is supplied by the lumen model instead. The
    state is retained rather than stripped so the delegated ``rhs`` keeps its
    exact indexing.
    """

    drug_physchem: DrugPhysChem
    oral_input: OralDrugInput
    body_weight_kg: float = 70.0
    hepatic_intrinsic_clearance_L_per_h: float = 0.0
    renal_clearance_L_per_h: float = 0.0
    gut_intrinsic_clearance_L_per_h: float = 0.0
    tract: GITract | None = None
    physiology: ReferencePhysiology | None = None
    partition_override: dict[str, float] | None = None
    include_colon: bool = True

    model_id: str = field(default="pbpk_oral_acat", init=False)
    model_name: str = field(default="Whole-body oral PBPK (ACAT + 12 tissue)", init=False)
    model_version: str = field(default="1.0.0", init=False)

    description = (
        "Mechanistic oral absorption coupled to whole-body physiologically based "
        "distribution. Dissolution, transit and permeability-limited uptake in a "
        "seven-compartment gastrointestinal tract deliver drug into the gut tissue "
        "compartment, which drains through the portal vein into the liver. Gut-wall "
        "and hepatic first-pass extraction, and therefore oral bioavailability, are "
        "emergent outputs rather than input parameters."
    )
    validation_status = ValidationStatus.RESEARCH_ONLY
    validation_summary = (
        "Structurally verified: mass balance closes across the lumen and the body, "
        "the delegated absorption and distribution right-hand sides are identical to "
        "their standalone parents, bioavailability is bounded in [0,1], and the model "
        "reduces to the standalone PBPK model when absorption is made fast. "
        "Concentration-time accuracy against observed human data is reported in "
        "VALIDATION.md; see that document for the achieved figures and the specific "
        "conditions under which they were obtained."
    )
    reference_ids = [
        "mudie2010",
        "yu_amidon1999",
        "poulin2002",
        "pearce2017",
        "ilsi1994",
        "davies1993",
        "eissing2011_osp",
    ]
    assumptions = [
        "Absorbed drug enters the gut tissue compartment and reaches the systemic "
        "circulation only through the portal vein and the liver.",
        "Gut-wall extraction follows a well-stirred model on the unbound "
        "plasma-equivalent gut tissue concentration, by analogy with the hepatic term.",
        "Every assumption of the seven-compartment absorption model applies, "
        "including fasted state only and monodisperse spherical particles.",
        "Every assumption of the perfusion-limited distribution model applies, "
        "including Poulin-Theil partitioning and instantaneous tissue equilibration.",
        "No enterohepatic recirculation and no intestinal efflux transport, so a "
        "drug that is secreted back into the lumen is not represented.",
    ]
    limitations = [
        "RESEARCH ONLY. Check VALIDATION.md for what has and has not been tested "
        "against observed data before relying on any output.",
        "Inherits the Poulin-Theil weakness for moderate-to-strong bases and the "
        "absence of a blood-brain barrier from the distribution model.",
        "Inherits fasted-state-only physiology and the absence of regional "
        "permeability differences from the absorption model.",
        "Gut-wall intrinsic clearance defaults to zero. It is a free parameter with "
        "no shipped evidence base; a non-zero value is the operator assumption.",
        "Stiff: lumen dissolution and blood-pool turnover differ by several orders "
        "of magnitude in time constant. Expect longer run times than either parent.",
    ]

    # ------------------------------------------------------------------ setup
    def __post_init__(self) -> None:
        if self.gut_intrinsic_clearance_L_per_h < 0:
            raise ValueError("gut_intrinsic_clearance_L_per_h cannot be negative.")

        self._abs = CompartmentalAbsorption(
            drug=self.oral_input, tract=self.tract, include_colon=self.include_colon
        )
        # ka_per_h=None makes the PBPK oral depot inert, so absorption is supplied
        # exclusively by the lumen model above.
        self._pbpk = PerfusionLimitedPBPK(
            drug=self.drug_physchem,
            body_weight_kg=self.body_weight_kg,
            hepatic_intrinsic_clearance_L_per_h=self.hepatic_intrinsic_clearance_L_per_h,
            renal_clearance_L_per_h=self.renal_clearance_L_per_h,
            ka_per_h=None,
            physiology=self.physiology,
            partition_override=self.partition_override,
        )

        self._n_abs = len(self._abs.state_names)
        self._n_pbpk = len(self._pbpk.state_names)
        self._abs_slice = slice(0, self._n_abs)
        self._pbpk_slice = slice(self._n_abs, self._n_abs + self._n_pbpk)

        # Indices needed inside the combined state vector.
        self._i_cum_absorbed = self._abs._i_abs
        self._gut_local = self._pbpk._idx["gut"]
        self._i_pbpk_eliminated = self._n_abs + self._pbpk._eliminated_idx
        # A separate ledger for gut-wall extraction, so F_gut is observable.
        self._i_gut_extracted = self._n_abs + self._n_pbpk

        self._v_gut = self._pbpk.tissue_volumes_L["gut"]
        self._kp_gut = self._pbpk.partition_coefficients["gut"]
        self._fu_p = self.drug_physchem.fraction_unbound_plasma
        self._dose_mg = 0.0

        self.assumptions = list(self.assumptions) + list(self._abs.assumptions)
        self.limitations = list(self.limitations) + list(self._pbpk.limitations)

    # ------------------------------------------------------------------ states
    @property
    def state_names(self) -> list[str]:
        return (
            list(self._abs.state_names)
            + list(self._pbpk.state_names)
            + ["A_gut_wall_extracted_mg"]
        )

    def eliminated_state_index(self) -> int | None:
        # Four terminal sinks (faeces, gut wall, hepatic and renal). The engine
        # single-index mass-balance check cannot express that, so this model
        # reports None and provides `mass_balance_error` instead.
        return None

    @property
    def observable_units(self) -> dict[str, str]:
        units = dict(self._pbpk.observable_units)
        units.update(
            {
                "fraction_absorbed": "fraction",
                "cumulative_absorbed": "mg",
                "absorption_rate": "mg",
                "dissolved_total": "mg",
                "solid_total": "mg",
                "faecal_loss": "mg",
                "bioavailable_fraction": "fraction",
                "gut_wall_extracted": "mg",
            }
        )
        return units

    def preferred_method(self) -> str | None:
        # Both parents ask for an implicit method; the union is stiffer than either.
        return "BDF"

    # -------------------------------------------------------------------- ODE
    def rhs(self, t: float, y: np.ndarray, infusion_rate: np.ndarray) -> np.ndarray:
        d = np.zeros_like(y)

        # ---- absorption block, delegated verbatim
        y_abs = y[self._abs_slice]
        d_abs = self._abs.rhs(t, y_abs, infusion_rate[self._abs_slice])
        d[self._abs_slice] = d_abs
        # The lumen model cumulative-absorbed derivative *is* the absorption rate.
        absorption_rate = d_abs[self._i_cum_absorbed]

        # ---- distribution block, delegated verbatim
        y_pbpk = y[self._pbpk_slice]
        d_pbpk = self._pbpk.rhs(t, y_pbpk, infusion_rate[self._pbpk_slice])

        # ---- the coupling: absorbed drug arrives in gut tissue, and gut-wall
        #      metabolism acts on it there before the portal vein carries the rest
        #      to the liver.
        gut_extraction = 0.0
        if self.gut_intrinsic_clearance_L_per_h > 0.0:
            c_gut_plasma_equiv = (y_pbpk[self._gut_local] / self._v_gut) / self._kp_gut
            gut_extraction = (
                self.gut_intrinsic_clearance_L_per_h * self._fu_p * c_gut_plasma_equiv
            )
        d_pbpk[self._gut_local] += absorption_rate - gut_extraction

        d[self._pbpk_slice] = d_pbpk
        d[self._i_gut_extracted] = gut_extraction
        return d

    def observables(self, t: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
        out = self._pbpk.observables(t, y[self._pbpk_slice])
        out.update(self._abs.observables(t, y[self._abs_slice]))
        out["gut_wall_extracted"] = y[self._i_gut_extracted]
        cumulative = y[self._i_cum_absorbed]
        if self._dose_mg > 0:
            # What got past the gut wall, as a fraction of dose. The hepatic first
            # pass is NOT subtracted here, because cumulative hepatic elimination
            # cannot be separated from systemic elimination inside a single ledger.
            # Use `oral_bioavailability_estimate()` for the F_hepatic factor.
            past_gut_wall = cumulative - y[self._i_gut_extracted]
            out["bioavailable_fraction"] = np.clip(past_gut_wall / self._dose_mg, 0.0, 1.0)
        else:
            out["bioavailable_fraction"] = np.zeros_like(cumulative)
        return out

    # ------------------------------------------------------------ dosing hooks
    def initial_state_for_dose(self, dose_mg: float) -> np.ndarray:
        """Place the dose in the stomach; the body starts drug-free."""
        self._dose_mg = dose_mg
        y = np.zeros(len(self.state_names))
        y[self._abs_slice] = self._abs.initial_state_for_dose(dose_mg)
        return y

    def set_dose(self, dose_mg: float) -> None:
        self._dose_mg = dose_mg
        self._abs.set_dose(dose_mg)

    def mass_balance_error(self, y_final: np.ndarray) -> float:
        """Relative error in dose - (lumen + faeces + body + eliminated).

        The lumen cumulative-absorbed state is excluded: it is a tracker for drug
        that has already been handed to the distribution block, so counting it
        would double-count every absorbed milligram.
        """
        if self._dose_mg <= 0:
            return 0.0
        y_abs = y_final[self._abs_slice]
        in_lumen = float(np.sum(y_abs)) - float(y_abs[self._i_cum_absorbed])
        in_body = float(np.sum(y_final[self._pbpk_slice]))
        gut_extracted = float(y_final[self._i_gut_extracted])
        total = in_lumen + in_body + gut_extracted
        return abs(self._dose_mg - total) / self._dose_mg

    # -------------------------------------------------------------- reporting
    def oral_bioavailability_estimate(self) -> dict[str, float]:
        """Predicted F and its three factors, from structure rather than fitting.

        ``F_gut`` and ``F_hepatic`` are the well-stirred extraction complements
        implied by the intrinsic clearances and the relevant blood flows -- the
        standard algebraic form, reported separately from the simulated fraction
        absorbed so that a simulated quantity and an algebraic one are not
        silently mixed.
        """
        fu_b = self._fu_p / self.drug_physchem.blood_plasma_ratio

        q_gut = self._pbpk.tissue_flows_L_per_h["gut"]
        clint_g = self.gut_intrinsic_clearance_L_per_h
        f_gut = 1.0 if clint_g <= 0 else q_gut / (q_gut + fu_b * clint_g)

        q_h = self._pbpk._q_liver_total
        clint_h = self.hepatic_intrinsic_clearance_L_per_h
        f_hep = 1.0 if clint_h <= 0 else q_h / (q_h + fu_b * clint_h)

        return {
            "f_gut": float(f_gut),
            "f_hepatic": float(f_hep),
            "f_first_pass_combined": float(f_gut * f_hep),
            "hepatic_blood_clearance_L_per_h": self._pbpk.hepatic_blood_clearance_L_per_h(),
            "total_plasma_clearance_L_per_h": self._pbpk.total_plasma_clearance_L_per_h(),
        }

    @property
    def absorption_model(self) -> CompartmentalAbsorption:
        return self._abs

    @property
    def distribution_model(self) -> PerfusionLimitedPBPK:
        return self._pbpk

    def structure_summary(self) -> dict[str, Any]:
        return {
            "absorption_states": self._n_abs,
            "distribution_states": self._n_pbpk,
            "si_compartments": self._abs._n,
            "tissues": list(self._pbpk.tissue_volumes_L),
            "absorption_target": "gut tissue compartment (portal drained)",
            "cardiac_output_L_per_h": self._pbpk.cardiac_output_L_per_h,
            "predicted_vss_L": self._pbpk.predicted_vss_L(),
        }

    # ------------------------------------------------------------- provenance
    def parameter_records(self) -> list[ParameterRecord]:
        recs: list[ParameterRecord] = []
        # Keep both parents' provenance so the Reports workspace still shows every
        # physiological constant and its citation rather than a shorter list for
        # the combined model.
        recs.extend(self._abs.parameter_records())
        recs.extend(self._pbpk.parameter_records())
        recs.append(
            ParameterRecord(
                "CLint_gut",
                self.gut_intrinsic_clearance_L_per_h,
                "L/h",
                ParameterOrigin.USER,
                "Gut-wall intrinsic clearance on unbound drug. Zero by default; no "
                "shipped evidence base.",
            )
        )
        fb = self.oral_bioavailability_estimate()
        recs.append(
            ParameterRecord(
                "F_gut_predicted", fb["f_gut"], "fraction", ParameterOrigin.DERIVED,
                "Gut-wall availability implied by CLint_gut and gut blood flow "
                "(well-stirred).",
            )
        )
        recs.append(
            ParameterRecord(
                "F_hepatic_predicted", fb["f_hepatic"], "fraction", ParameterOrigin.DERIVED,
                "Hepatic availability implied by CLint_H and liver blood flow "
                "(well-stirred).",
            )
        )
        # De-duplicate on name, keeping the first occurrence, because both parents
        # declare some of the same physiological constants.
        seen: set[str] = set()
        unique: list[ParameterRecord] = []
        for rec in recs:
            if rec.name in seen:
                continue
            seen.add(rec.name)
            unique.append(rec)
        return unique
