"""
Compartmental gastrointestinal absorption and transit (CAT/ACAT-style).

This module answers a question the rest of SYNTHBODY previously could not: how
much of an oral dose is absorbed, and at what rate, given only the drug's
physicochemistry and the dose/formulation. Until now absorption was a single
first-order rate constant `ka` that the operator had to supply — meaning the
answer had to be known before the simulation could run.

Structure (Yu & Amidon 1999, PMID 10486429):

    stomach ──> SI_1 ──> SI_2 ──> ... ──> SI_7 ──> colon ──> excreted
       │          │        │               │         │
       │          └────────┴───────────────┴─────────┘
       │                   absorption into portal blood
       └── (no absorption from the stomach is modelled)

Each compartment carries two states: undissolved solid and dissolved drug.

Processes, and the equation used for each:

  Transit          first-order, Kt = N / T_si for the small intestine;
                   gastric emptying Kge = ln2 / t_half,gastric

  Solubility       Henderson-Hasselbalch on the neutral intrinsic solubility,
                   evaluated at each compartment's own luminal pH:
                       acid:  Cs = S0 · (1 + 10^(pH − pKa))
                       base:  Cs = S0 · (1 + 10^(pKa − pH))
                   with an optional bile-salt solubilisation term.

  Dissolution      Nernst–Brunner / Noyes–Whitney for shrinking spherical
                   particles:
                       dM/dt = −(D · A / h) · (Cs − C)
                   with A recomputed from the remaining solid mass, so the
                   surface area shrinks correctly as particles dissolve, and
                   h = min(r, 30 µm).

  Absorption       permeability-limited across a cylindrical lumen:
                       ka,i = 2 · Peff / R
                   which is the standard tube-geometry result.

  Precipitation    first-order return to solid whenever C > Cs.

WHAT THIS MODEL IS AND IS NOT. It is a mechanistic absorption model built from
published structure with physiology from an open-access source. It is NOT
validated against observed concentration-time data for poorly soluble drugs,
because the dataset that would do that (Sjögren et al. 2016, PMID 26926043) is
paywalled and could not be obtained. It is therefore RESEARCH_ONLY, and the
fraction absorbed it predicts must not be reported as a validated prediction.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np

from synthbody.config import LIBRARY_DIR
from synthbody.engine.core import BaseModel
from synthbody.engine.provenance import ParameterOrigin, ParameterRecord, ValidationStatus


# ---------------------------------------------------------------------------
# Physiology
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GITract:
    """Fasted-state human GI physiology, loaded from the shipped dataset."""

    stomach_ph: float
    stomach_volume_mL: float
    gastric_half_emptying_min: float
    n_si: int
    si_transit_total_min: float
    si_volume_mL: float
    si_length_cm: float
    si_radius_cm: float
    si_ph: tuple[float, ...]
    si_bile_salt_mM: tuple[float, ...]
    colon_ph: float
    colon_volume_mL: float
    colon_transit_min: float
    colon_perm_factor: float
    diffusion_layer_max_cm: float
    default_diffusivity_cm2_s: float
    drug_density_g_cm3: float
    raw: dict[str, Any]

    @property
    def gastric_emptying_rate_per_h(self) -> float:
        return float(np.log(2.0) / (self.gastric_half_emptying_min / 60.0))

    @property
    def si_transit_rate_per_h(self) -> float:
        """Kt = N / T_si, the CAT transit rate constant for each compartment."""
        return self.n_si / (self.si_transit_total_min / 60.0)

    @property
    def colon_transit_rate_per_h(self) -> float:
        return 1.0 / (self.colon_transit_min / 60.0)

    @property
    def si_compartment_volume_L(self) -> float:
        return self.si_volume_mL / 1000.0 / self.n_si

    @property
    def si_compartment_length_cm(self) -> float:
        return self.si_length_cm / self.n_si


@lru_cache
def load_gi_tract() -> GITract:
    doc = json.loads((LIBRARY_DIR / "gi_physiology.json").read_text(encoding="utf-8"))
    st, si, co, k = doc["stomach"], doc["small_intestine"], doc["colon"], doc["constants"]
    n = int(si["n_compartments"]["value"])
    ph = tuple(float(x) for x in si["ph_profile"]["values"])
    bs = tuple(float(x) for x in si["bile_salt_mM"]["values"])
    if len(ph) != n or len(bs) != n:
        raise ValueError(
            f"gi_physiology.json declares {n} compartments but supplies {len(ph)} pH and "
            f"{len(bs)} bile-salt values."
        )
    return GITract(
        stomach_ph=float(st["ph"]["value"]),
        stomach_volume_mL=float(st["volume_mL"]["value"]),
        gastric_half_emptying_min=float(st["half_emptying_time_min"]["value"]),
        n_si=n,
        si_transit_total_min=float(si["total_transit_time_min"]["value"]),
        si_volume_mL=float(si["total_volume_mL"]["value"]),
        si_length_cm=float(si["length_cm"]["value"]),
        si_radius_cm=float(si["radius_cm"]["value"]),
        si_ph=ph,
        si_bile_salt_mM=bs,
        colon_ph=float(co["ph"]["value"]),
        colon_volume_mL=float(co["volume_mL"]["value"]),
        colon_transit_min=float(co["transit_time_min"]["value"]),
        colon_perm_factor=float(co["relative_permeability_factor"]["value"]),
        diffusion_layer_max_cm=float(k["diffusion_layer_thickness_um"]["value"]) * 1e-4,
        default_diffusivity_cm2_s=float(k["default_diffusion_coefficient_cm2_per_s"]["value"]),
        drug_density_g_cm3=float(k["drug_density_g_per_cm3"]["value"]),
        raw=doc,
    )


def gi_provenance() -> dict[str, Any]:
    return load_gi_tract().raw["provenance"]


# ---------------------------------------------------------------------------
# Drug input
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OralDrugInput:
    """The physicochemical and formulation inputs an absorption model needs.

    These are exactly the inputs a bottom-up absorption prediction is allowed:
    nothing here is derived from the observed plasma profile.
    """

    intrinsic_solubility_mg_per_mL: float
    """Solubility of the neutral species, S0."""

    effective_permeability_cm_per_s: float
    """Human jejunal effective permeability, Peff."""

    pka_acidic: float | None = None
    pka_basic: float | None = None

    particle_radius_um: float = 25.0
    """Initial particle radius. Formulation input."""

    diffusivity_cm2_per_s: float | None = None
    density_g_per_cm3: float | None = None

    bile_salt_solubilisation_per_mM: float = 0.0
    """Fractional increase in solubility per mM bile salt. Zero disables it."""

    precipitation_rate_per_h: float = 0.0
    """First-order precipitation of supersaturated drug. Zero disables it."""

    max_solubility_ratio: float = 1e4
    """Cap on Cs/S0 from ionisation, so Henderson-Hasselbalch cannot run away."""

    is_solution: bool = False
    """If true the dose enters fully dissolved and dissolution is bypassed."""

    def __post_init__(self) -> None:
        if self.intrinsic_solubility_mg_per_mL <= 0:
            raise ValueError("intrinsic_solubility_mg_per_mL must be positive.")
        if self.effective_permeability_cm_per_s <= 0:
            raise ValueError("effective_permeability_cm_per_s must be positive.")
        if self.particle_radius_um <= 0:
            raise ValueError("particle_radius_um must be positive.")
        if self.precipitation_rate_per_h < 0:
            raise ValueError("precipitation_rate_per_h cannot be negative.")
        if self.max_solubility_ratio < 1.0:
            raise ValueError("max_solubility_ratio must be at least 1.")

    def solubility_at(self, ph: float, bile_salt_mM: float = 0.0) -> float:
        """pH-dependent solubility by Henderson-Hasselbalch, in mg/mL.

        An acid becomes more soluble as pH rises above its pKa; a base becomes
        more soluble as pH falls below its pKa. A compound with both is treated
        as the sum of the two ionised contributions.
        """
        ratio = 1.0
        if self.pka_acidic is not None:
            ratio += 10.0 ** min(ph - self.pka_acidic, 12.0)
        if self.pka_basic is not None:
            ratio += 10.0 ** min(self.pka_basic - ph, 12.0)
        ratio = min(ratio, self.max_solubility_ratio)
        cs = self.intrinsic_solubility_mg_per_mL * ratio
        if self.bile_salt_solubilisation_per_mM > 0 and bile_salt_mM > 0:
            cs *= 1.0 + self.bile_salt_solubilisation_per_mM * bile_salt_mM
        return cs


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------
@dataclass
class CompartmentalAbsorption(BaseModel):
    """GI absorption and transit producing an absorption-rate profile.

    State layout, for N small-intestinal compartments:
        0                     solid in stomach
        1                     dissolved in stomach
        2 .. 2N+1             solid/dissolved pairs for SI compartments 1..N
        2N+2, 2N+3            solid/dissolved in colon
        2N+4                  cumulative absorbed
        2N+5                  cumulative lost to faeces

    The cumulative-absorbed state is what gets convolved with a disposition
    model, which is the methodology used by the OrBiTo comparison studies.
    """

    drug: OralDrugInput
    tract: GITract | None = None
    include_colon: bool = True

    model_id: str = field(default="gi_absorption_cat", init=False)
    model_name: str = field(default="Compartmental GI absorption and transit", init=False)
    model_version: str = field(default="1.0.0", init=False)

    description = (
        "Mechanistic gastrointestinal absorption model with gastric emptying, "
        "small-intestinal transit, pH-dependent solubility, Nernst-Brunner dissolution "
        "of shrinking particles, permeability-limited uptake and optional precipitation. "
        "Predicts the fraction absorbed and the absorption-rate profile from "
        "physicochemistry alone."
    )
    validation_status = ValidationStatus.RESEARCH_ONLY
    validation_summary = (
        "Structurally verified: mass balance closes, fraction absorbed is bounded in "
        "[0,1], the model reproduces the expected limiting behaviours (complete "
        "absorption for a highly soluble and permeable compound, permeability-limited "
        "absorption at low Peff, dose-dependent fraction absorbed under solubility "
        "limitation, and faster dissolution for smaller particles). NOT validated "
        "against observed concentration-time data for poorly soluble drugs: the "
        "benchmark dataset that would do that (Sjogren et al. 2016, PMID 26926043) is "
        "paywalled and could not be obtained."
    )
    reference_ids = ["mudie2010", "yu_amidon1999", "pearce2017", "sjogren2016"]
    assumptions = [
        "Fasted state only. No food effect is modelled.",
        "No absorption from the stomach.",
        "Compartment volumes are fixed; fluid flux through the gut is not modelled.",
        "Particles are monodisperse spheres of a single initial radius.",
        "The hydrodynamic diffusion layer is min(particle radius, 30 um) rather than "
        "computed from local hydrodynamics.",
        "Effective permeability is uniform along the small intestine.",
        "Henderson-Hasselbalch solubility with no salt or common-ion effects, no "
        "solid-form changes, and no supersaturation beyond the optional precipitation term.",
        "No intestinal metabolism and no efflux transport, so the fraction absorbed is "
        "fraction entering the enterocyte, not bioavailability.",
    ]
    limitations = [
        "RESEARCH ONLY: not validated against observed oral concentration-time data.",
        "Predicts fraction ABSORBED, not bioavailability: there is no gut-wall or "
        "hepatic first-pass extraction in this model.",
        "No fed state, no formulation effects beyond particle size and a solution flag, "
        "no controlled release, no regional permeability differences.",
        "Colonic parameters are SYNTHBODY defaults and are not measurements.",
        "Precipitation is a single first-order rate rather than a nucleation-and-growth "
        "model, so supersaturating formulations will be poorly represented.",
    ]

    # ------------------------------------------------------------------ setup
    def __post_init__(self) -> None:
        self._t = self.tract or load_gi_tract()
        t = self._t
        self._n = t.n_si
        self._rho = self.drug.density_g_per_cm3 or t.drug_density_g_cm3
        self._diff = self.drug.diffusivity_cm2_per_s or t.default_diffusivity_cm2_s
        self._r0_cm = self.drug.particle_radius_um * 1e-4

        # Absorption rate constant for a cylinder: ka = 2*Peff/R.
        # Peff in cm/s -> per hour.
        self._ka_si_per_h = 2.0 * self.drug.effective_permeability_cm_per_s * 3600.0 / t.si_radius_cm
        self._ka_colon_per_h = self._ka_si_per_h * t.colon_perm_factor

        self._v_stomach_L = t.stomach_volume_mL / 1000.0
        self._v_si_L = t.si_compartment_volume_L
        self._v_colon_L = t.colon_volume_mL / 1000.0

        self._kge = t.gastric_emptying_rate_per_h
        self._kt = t.si_transit_rate_per_h
        self._kcol = t.colon_transit_rate_per_h

        # Saturated solubility per compartment, in mg/L (engine works in mg and L).
        self._cs_stomach = self.drug.solubility_at(t.stomach_ph) * 1000.0
        self._cs_si = np.array(
            [self.drug.solubility_at(t.si_ph[i], t.si_bile_salt_mM[i]) * 1000.0 for i in range(self._n)]
        )
        self._cs_colon = self.drug.solubility_at(t.colon_ph) * 1000.0

        # Index map
        self._i_abs = 2 + 2 * self._n + 2
        self._i_faeces = self._i_abs + 1
        self._dose_mg: float = 0.0

    # ------------------------------------------------------------------ states
    @property
    def state_names(self) -> list[str]:
        names = ["A_solid_stomach_mg", "A_diss_stomach_mg"]
        for i in range(1, self._n + 1):
            names += [f"A_solid_si{i}_mg", f"A_diss_si{i}_mg"]
        names += ["A_solid_colon_mg", "A_diss_colon_mg", "A_absorbed_mg", "A_faeces_mg"]
        return names

    def eliminated_state_index(self) -> int | None:
        # Absorbed and faecal drug both leave the lumen; mass balance is checked
        # explicitly in `mass_balance_error` instead, because this model has two
        # terminal sinks rather than one.
        return None

    @property
    def observable_units(self) -> dict[str, str]:
        return {
            "absorption_rate": "mg",
            "cumulative_absorbed": "mg",
            "fraction_absorbed": "fraction",
            "dissolved_total": "mg",
            "solid_total": "mg",
            "faecal_loss": "mg",
        }

    def set_dose(self, dose_mg: float) -> None:
        """Record the dose so fraction-absorbed can be reported."""
        self._dose_mg = float(dose_mg)

    # ------------------------------------------------------------ dissolution
    #
    # Two numerical decisions are worth stating explicitly, because both change
    # the equations from their textbook form:
    #
    # 1. PARTICLE RADIUS IS GLOBAL, NOT PER-COMPARTMENT. Particles are
    #    monodisperse and all experience similar conditions, so they shrink
    #    together. The radius is therefore derived once per RHS evaluation from
    #    the TOTAL solid remaining across the whole tract. Inferring a radius
    #    from the solid mass sitting in one compartment would be wrong: a
    #    compartment holding a tenth of the dose holds a tenth of the particles
    #    at full size, not all the particles at a tenth of the size.
    #
    # 2. THE DIFFUSION LAYER AND RADIUS ARE FLOORED. The textbook law with
    #    h = r gives dM/dt ∝ M^(1/3), whose derivative is infinite at M = 0.
    #    That singularity is what makes a naive implementation unintegrable:
    #    for a fine-particle soluble drug the initial rate is ~10^6 mg/h and the
    #    solver then has to resolve a non-smooth depletion tail. Flooring the
    #    radius turns the tail into a smooth first-order decay (dM/dt ∝ M)
    #    while leaving the physically meaningful part of the curve unchanged,
    #    since by then the drug has effectively all dissolved.
    _RADIUS_FLOOR_FRACTION = 1e-3   # of the initial radius
    _DIFFUSION_LAYER_FLOOR_CM = 1e-4  # 1 micrometre

    def _current_radius_cm(self, total_solid_mg: float) -> float:
        """Particle radius from the total undissolved mass remaining."""
        init = self._initial_solid_mg
        if init <= 0.0:
            return self._r0_cm
        frac = min(max(total_solid_mg / init, 0.0), 1.0)
        r = self._r0_cm * frac ** (1.0 / 3.0)
        return max(r, self._r0_cm * self._RADIUS_FLOOR_FRACTION)

    def _dissolution_rate(
        self,
        solid_mg: float,
        dissolved_mg: float,
        volume_L: float,
        cs_mg_L: float,
        r_cm: float,
    ) -> float:
        """Nernst-Brunner rate in mg/h. Returns mass leaving the solid state."""
        if solid_mg <= 0.0 or r_cm <= 0.0:
            return 0.0
        c = dissolved_mg / volume_L  # mg/L
        if c >= cs_mg_L:
            return 0.0

        # Surface area of the particles present in THIS compartment, at the
        # current global radius: A = 3M/(rho*r), exact for spheres.
        mass_g = solid_mg / 1000.0
        area_cm2 = 3.0 * mass_g / (self._rho * r_cm)

        h_cm = max(min(r_cm, self._t.diffusion_layer_max_cm), self._DIFFUSION_LAYER_FLOOR_CM)

        # D [cm2/s] * A [cm2] / h [cm] -> cm3/s -> L/h
        k_L_per_h = self._diff * area_cm2 / h_cm * 3600.0 / 1000.0
        return max(k_L_per_h * (cs_mg_L - c), 0.0)

    @property
    def _initial_solid_mg(self) -> float:
        return self._dose_mg if not self.drug.is_solution else 0.0

    # -------------------------------------------------------------------- ODE
    def rhs(self, t: float, y: np.ndarray, infusion_rate: np.ndarray) -> np.ndarray:
        d = np.zeros_like(y)
        n = self._n
        drug = self.drug

        # Particle radius is global: all monodisperse particles shrink together,
        # so it is derived once from the total solid left anywhere in the tract.
        total_solid = y[0] + y[2 + 2 * n]
        for i in range(n):
            total_solid += y[2 + 2 * i]
        r_cm = self._current_radius_cm(total_solid)

        # ---- stomach
        s_sol, s_dis = y[0], y[1]
        diss_st = self._dissolution_rate(s_sol, s_dis, self._v_stomach_L, self._cs_stomach, r_cm)
        empty_sol = self._kge * s_sol
        empty_dis = self._kge * s_dis
        d[0] = infusion_rate[0] - diss_st - empty_sol
        d[1] = infusion_rate[1] + diss_st - empty_dis

        prev_sol, prev_dis = empty_sol, empty_dis
        total_absorbed_rate = 0.0

        # ---- small intestine
        for i in range(n):
            isol, idis = 2 + 2 * i, 3 + 2 * i
            sol, dis = y[isol], y[idis]
            vol = self._v_si_L
            cs = self._cs_si[i]

            diss = self._dissolution_rate(sol, dis, vol, cs, r_cm)

            # Precipitation when supersaturated.
            precip = 0.0
            if drug.precipitation_rate_per_h > 0.0:
                c = dis / vol
                if c > cs:
                    precip = drug.precipitation_rate_per_h * (c - cs) * vol

            absorb = self._ka_si_per_h * dis
            out_sol = self._kt * sol
            out_dis = self._kt * dis

            d[isol] = prev_sol - diss + precip - out_sol
            d[idis] = prev_dis + diss - precip - absorb - out_dis

            total_absorbed_rate += absorb
            prev_sol, prev_dis = out_sol, out_dis

        # ---- colon
        icsol, icdis = 2 + 2 * n, 3 + 2 * n
        if self.include_colon:
            sol, dis = y[icsol], y[icdis]
            diss_c = self._dissolution_rate(sol, dis, self._v_colon_L, self._cs_colon, r_cm)
            absorb_c = self._ka_colon_per_h * dis
            out_sol = self._kcol * sol
            out_dis = self._kcol * dis
            d[icsol] = prev_sol - diss_c - out_sol
            d[icdis] = prev_dis + diss_c - absorb_c - out_dis
            total_absorbed_rate += absorb_c
            faeces_in = out_sol + out_dis
        else:
            d[icsol] = 0.0
            d[icdis] = 0.0
            faeces_in = prev_sol + prev_dis

        d[self._i_abs] = total_absorbed_rate
        d[self._i_faeces] = faeces_in
        return d

    def observables(self, t: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
        n = self._n
        solid = y[0] + y[2 + 2 * n]
        diss = y[1] + y[3 + 2 * n]
        for i in range(n):
            solid = solid + y[2 + 2 * i]
            diss = diss + y[3 + 2 * i]
        absorbed = y[self._i_abs]
        # Absorption rate by differentiating the cumulative curve.
        rate = np.gradient(absorbed, t) if t.size > 1 else np.zeros_like(absorbed)
        frac = absorbed / self._dose_mg if self._dose_mg > 0 else np.zeros_like(absorbed)
        return {
            "absorption_rate": rate,
            "cumulative_absorbed": absorbed,
            "fraction_absorbed": frac,
            "dissolved_total": diss,
            "solid_total": solid,
            "faecal_loss": y[self._i_faeces],
        }

    def preferred_method(self) -> str | None:
        # Dissolution of fine particles is fast relative to transit: stiff.
        return "LSODA"

    def initial_state_for_dose(self, dose_mg: float) -> np.ndarray:
        """Place the dose in the stomach as solid (or dissolved, for a solution)."""
        self.set_dose(dose_mg)
        y = np.zeros(len(self.state_names))
        if self.drug.is_solution:
            y[1] = dose_mg
        else:
            y[0] = dose_mg
        return y

    def mass_balance_error(self, y_final: np.ndarray) -> float:
        """Relative error in (dose) − (in lumen + absorbed + faeces)."""
        if self._dose_mg <= 0:
            return 0.0
        total = float(np.sum(y_final))
        return abs(self._dose_mg - total) / self._dose_mg

    # ------------------------------------------------------------- provenance
    def parameter_records(self) -> list[ParameterRecord]:
        t = self._t
        return [
            ParameterRecord(
                "S0", self.drug.intrinsic_solubility_mg_per_mL, "", ParameterOrigin.USER,
                "Intrinsic solubility of the neutral species (mg/mL).",
            ),
            ParameterRecord(
                "Peff", self.drug.effective_permeability_cm_per_s, "", ParameterOrigin.USER,
                "Human effective intestinal permeability (cm/s).",
            ),
            ParameterRecord(
                "pKa_acidic", self.drug.pka_acidic if self.drug.pka_acidic is not None else float("nan"),
                "", ParameterOrigin.USER, "Acidic pKa, if any.",
            ),
            ParameterRecord(
                "pKa_basic", self.drug.pka_basic if self.drug.pka_basic is not None else float("nan"),
                "", ParameterOrigin.USER, "Basic pKa, if any.",
            ),
            ParameterRecord(
                "particle_radius", self.drug.particle_radius_um, "", ParameterOrigin.USER,
                "Initial particle radius in micrometres (formulation input).",
            ),
            ParameterRecord(
                "ka_SI", self._ka_si_per_h, "1/h", ParameterOrigin.DERIVED,
                "Small-intestinal absorption rate constant, 2*Peff/R.",
                reference_ids=["mudie2010"],
            ),
            ParameterRecord(
                "Kge", self._kge, "1/h", ParameterOrigin.MEASURED,
                "Gastric emptying rate constant from a fasted half-emptying time of "
                f"{t.gastric_half_emptying_min:g} min.",
                reference_ids=["mudie2010"],
            ),
            ParameterRecord(
                "Kt", self._kt, "1/h", ParameterOrigin.DERIVED,
                f"Small-intestinal transit rate constant, N/T_si with N={t.n_si} and "
                f"T_si={t.si_transit_total_min:g} min.",
                reference_ids=["mudie2010", "yu_amidon1999"],
            ),
            ParameterRecord(
                "V_SI_compartment", self._v_si_L, "L", ParameterOrigin.MEASURED,
                "Fasted small-intestinal liquid volume per compartment.",
                reference_ids=["mudie2010"],
            ),
            ParameterRecord(
                "R_SI", t.si_radius_cm, "", ParameterOrigin.MEASURED,
                "Small-intestinal radius in cm.",
                reference_ids=["pearce2017"],
            ),
            ParameterRecord(
                "D", self._diff, "", ParameterOrigin.ILLUSTRATIVE,
                "Aqueous diffusion coefficient (cm2/s). A SYNTHBODY default unless supplied.",
            ),
            ParameterRecord(
                "rho", self._rho, "", ParameterOrigin.ILLUSTRATIVE,
                "Solid true density (g/cm3). A SYNTHBODY default unless supplied.",
            ),
        ]


# ---------------------------------------------------------------------------
# Absorption coupled to disposition (the OrBiTo convolution method)
# ---------------------------------------------------------------------------
@dataclass
class OralAbsorptionWithDisposition(BaseModel):
    """GI absorption feeding a linear disposition model.

    This is the structure the OrBiTo comparison studies use: a mechanistic
    absorption model supplies the rate of drug entering the systemic
    circulation, which is convolved with independently obtained disposition
    parameters. Here the convolution is done exactly rather than numerically,
    by integrating both systems together.

    `f_gut` and `f_hepatic` are applied to the absorbed flux as first-pass
    extraction, so the model reports bioavailability as well as fraction
    absorbed. Both default to 1 (no first-pass loss).
    """

    absorption: CompartmentalAbsorption
    cl_L_per_h: float
    v_central_L: float
    q_L_per_h: float | None = None
    v_peripheral_L: float | None = None
    f_gut: float = 1.0
    f_hepatic: float = 1.0

    model_id: str = field(default="oral_absorption_disposition", init=False)
    model_name: str = field(default="GI absorption coupled to disposition", init=False)
    model_version: str = field(default="1.0.0", init=False)

    description = (
        "Mechanistic GI absorption convolved with one- or two-compartment disposition, "
        "matching the methodology used in published oral-absorption software comparisons."
    )
    validation_status = ValidationStatus.RESEARCH_ONLY
    validation_summary = (
        "The disposition half uses models that are independently validated; the "
        "absorption half is research-only. The coupled model inherits the weaker of "
        "the two statuses."
    )
    reference_ids = ["mudie2010", "yu_amidon1999", "sjogren2016"]

    def __post_init__(self) -> None:
        if self.cl_L_per_h <= 0 or self.v_central_L <= 0:
            raise ValueError("CL and V must be positive.")
        if (self.q_L_per_h is None) != (self.v_peripheral_L is None):
            raise ValueError("Q and V2 must be supplied together or not at all.")
        if self.q_L_per_h is not None and (self.q_L_per_h <= 0 or self.v_peripheral_L <= 0):
            raise ValueError("Q and V2 must be positive when supplied.")
        for name, v in (("f_gut", self.f_gut), ("f_hepatic", self.f_hepatic)):
            if not 0.0 < v <= 1.0:
                raise ValueError(f"{name} must be in (0, 1].")
        self._two = self.q_L_per_h is not None
        self._n_gi = len(self.absorption.state_names)
        self.assumptions = list(self.absorption.assumptions) + [
            "Disposition is linear and independent of the absorption process.",
            "First-pass extraction is a constant fraction, not a concentration-dependent process.",
        ]
        self.limitations = list(self.absorption.limitations)

    @property
    def state_names(self) -> list[str]:
        names = list(self.absorption.state_names)
        names += ["A_central_mg"]
        if self._two:
            names += ["A_peripheral_mg"]
        names += ["A_systemically_eliminated_mg", "A_first_pass_lost_mg"]
        return names

    @property
    def observable_units(self) -> dict[str, str]:
        u = dict(self.absorption.observable_units)
        u.update(
            {
                "plasma_concentration": "mg/L",
                "amount_central": "mg",
                "bioavailable_fraction": "fraction",
            }
        )
        return u

    def rhs(self, t: float, y: np.ndarray, infusion_rate: np.ndarray) -> np.ndarray:
        n = self._n_gi
        d = np.zeros_like(y)

        # GI block: run the absorption model on its own slice.
        gi_rate = np.zeros(n)
        gi_rate[0] = infusion_rate[0] if infusion_rate.size > 0 else 0.0
        d[:n] = self.absorption.rhs(t, y[:n], gi_rate)

        # The absorbed flux is d(A_absorbed)/dt from the GI block.
        absorbed_flux = d[self.absorption._i_abs]
        f_first_pass = self.f_gut * self.f_hepatic
        to_systemic = absorbed_flux * f_first_pass
        lost = absorbed_flux * (1.0 - f_first_pass)

        i_c = n
        if self._two:
            i_p, i_e, i_l = n + 1, n + 2, n + 3
            k10 = self.cl_L_per_h / self.v_central_L
            k12 = self.q_L_per_h / self.v_central_L
            k21 = self.q_L_per_h / self.v_peripheral_L
            d[i_c] = to_systemic - (k10 + k12) * y[i_c] + k21 * y[i_p]
            d[i_p] = k12 * y[i_c] - k21 * y[i_p]
            d[i_e] = k10 * y[i_c]
            d[i_l] = lost
        else:
            i_e, i_l = n + 1, n + 2
            k10 = self.cl_L_per_h / self.v_central_L
            d[i_c] = to_systemic - k10 * y[i_c]
            d[i_e] = k10 * y[i_c]
            d[i_l] = lost
        return d

    def observables(self, t: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
        n = self._n_gi
        out = self.absorption.observables(t, y[:n])
        out["plasma_concentration"] = y[n] / self.v_central_L
        out["amount_central"] = y[n]
        dose = self.absorption._dose_mg
        if dose > 0:
            absorbed = y[self.absorption._i_abs]
            out["bioavailable_fraction"] = absorbed * self.f_gut * self.f_hepatic / dose
        return out

    def initial_state_for_dose(self, dose_mg: float) -> np.ndarray:
        y = np.zeros(len(self.state_names))
        y[: self._n_gi] = self.absorption.initial_state_for_dose(dose_mg)
        return y

    def preferred_method(self) -> str | None:
        return "LSODA"

    def parameter_records(self) -> list[ParameterRecord]:
        recs = list(self.absorption.parameter_records())
        recs += [
            ParameterRecord("CL", self.cl_L_per_h, "L/h", ParameterOrigin.USER, "Systemic clearance."),
            ParameterRecord("V", self.v_central_L, "L", ParameterOrigin.USER, "Central volume."),
            ParameterRecord(
                "F_gut", self.f_gut, "fraction", ParameterOrigin.USER, "Gut-wall availability."
            ),
            ParameterRecord(
                "F_hepatic", self.f_hepatic, "fraction", ParameterOrigin.USER,
                "Hepatic first-pass availability.",
            ),
        ]
        if self._two:
            recs += [
                ParameterRecord("Q", self.q_L_per_h, "L/h", ParameterOrigin.USER,
                                "Intercompartmental clearance."),
                ParameterRecord("V2", self.v_peripheral_L, "L", ParameterOrigin.USER,
                                "Peripheral volume."),
            ]
        return recs
