"""
Tissue:plasma partition coefficient prediction from drug physicochemistry and
tissue composition.

Implements the tissue-composition approach of Poulin & Theil (2002)
(PMID 11977112, DOI 10.1002/jps.10128):

    Kp_t = [ Po:w * (Fnl_t + 0.3*Fph_t) + (Fw_t + 0.7*Fph_t) ]
           -----------------------------------------------------  *  fu_p / fu_t
           [ Po:w * (Fnl_p + 0.3*Fph_p) + (Fw_p + 0.7*Fph_p) ]

with the non-adipose tissue unbound fraction approximated as

    fu_t = 1 / (1 + ((1 - fu_p)/fu_p) * 0.5)

and the adipose compartment using the olive-oil:water distribution coefficient
in place of Po:w.

IMPORTANT, and surfaced in the UI: this method is known to predict poorly for
moderate-to-strong bases, where Rodgers & Rowland (2005/2006) performs better
by accounting for binding to acidic phospholipids. SYNTHBODY does not implement
Rodgers & Rowland in this release. The PBPK model that consumes these
coefficients is therefore marked RESEARCH_ONLY except for the one quantitative
check it does pass (steady-state volume of distribution for theophylline, a
neutral, low-logP compound where the method is better behaved).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from synthbody.engine.physiology.reference_man import (
    PBPK_TISSUES,
    ReferencePhysiology,
    load_reference_physiology,
)


@dataclass(frozen=True)
class DrugPhysChem:
    """The physicochemical inputs the partitioning method needs."""

    log_p: float
    """Octanol:water partition coefficient of the neutral species, log10."""

    fraction_unbound_plasma: float
    """fu,p - fraction unbound in plasma (0, 1]."""

    blood_plasma_ratio: float = 1.0
    """B:P - whole blood to plasma concentration ratio."""

    pka_acidic: float | None = None
    pka_basic: float | None = None
    is_neutral: bool = True

    def __post_init__(self) -> None:
        if not 0.0 < self.fraction_unbound_plasma <= 1.0:
            raise ValueError(
                f"fraction_unbound_plasma must be in (0, 1], got {self.fraction_unbound_plasma}"
            )
        if self.blood_plasma_ratio <= 0:
            raise ValueError("blood_plasma_ratio must be positive.")
        if not -5.0 <= self.log_p <= 10.0:
            raise ValueError(f"log_p={self.log_p} is outside a physically sensible range.")


def olive_oil_water_logd_from_logp(log_p: float) -> float:
    """Olive-oil:water distribution coefficient from log Po:w.

    Poulin & Theil use the Leo correlation
        log Dvo:w = 1.115 * log Po:w - 1.35
    for the adipose compartment. Tagged DERIVED wherever it is reported.
    """
    return 1.115 * log_p - 1.35


def tissue_unbound_fraction(fraction_unbound_plasma: float) -> float:
    """Poulin & Theil approximation of fu in non-adipose tissue.

    Assumes the binding-protein concentration in tissue interstitium is about
    half that of plasma. Adipose is assigned fu_t = 1.
    """
    fu_p = fraction_unbound_plasma
    return 1.0 / (1.0 + ((1.0 - fu_p) / fu_p) * 0.5)


@dataclass(frozen=True)
class PartitionResult:
    kp: dict[str, float]
    fu_tissue_non_adipose: float
    method: str
    log_d_olive_oil_water: float
    warnings: tuple[str, ...]


def predict_partition_coefficients(
    drug: DrugPhysChem, physiology: ReferencePhysiology | None = None
) -> PartitionResult:
    """Predict Kp (tissue:plasma, total concentrations) for every PBPK tissue."""
    phys = physiology or load_reference_physiology()
    p_ow = 10.0**drug.log_p
    log_dvow = olive_oil_water_logd_from_logp(drug.log_p)
    d_vow = 10.0**log_dvow
    fu_p = drug.fraction_unbound_plasma
    fu_t = tissue_unbound_fraction(fu_p)

    # Plasma composition. The httk dataset gives an effective neutral-lipid
    # volume fraction for plasma; the remainder of plasma is treated as water.
    f_nl_p = phys.plasma_f_neutral_lipid
    f_ph_p = 0.0  # plasma phospholipid is negligible in this parameterisation
    f_w_p = 1.0 - f_nl_p - phys.plasma_f_protein_volume

    # The plasma denominator must use the SAME lipid descriptor as the numerator.
    # Poulin & Theil substitute the olive-oil:water coefficient for adipose, and
    # that substitution applies on both sides of the ratio. Using the octanol
    # denominator for the adipose numerator systematically under-predicts fat
    # partitioning and can make adipose rank below skin for a lipophilic drug,
    # which is physiologically wrong.
    denom_octanol = p_ow * (f_nl_p + 0.3 * f_ph_p) + (f_w_p + 0.7 * f_ph_p)
    denom_olive = d_vow * (f_nl_p + 0.3 * f_ph_p) + (f_w_p + 0.7 * f_ph_p)
    if denom_octanol <= 0 or denom_olive <= 0:
        raise ValueError("Non-physical plasma composition produced a non-positive denominator.")

    warnings: list[str] = []
    if not drug.is_neutral and drug.pka_basic is not None and drug.pka_basic > 7.0:
        warnings.append(
            "Compound is a moderate-to-strong base. The Poulin-Theil method is known to "
            "under-predict tissue distribution for such compounds; Rodgers-Rowland is "
            "the appropriate method and is not implemented in this release."
        )
    if drug.log_p > 5.0:
        warnings.append(
            f"log P = {drug.log_p:g} is high; tissue-composition partitioning is poorly "
            "constrained for very lipophilic compounds."
        )

    kp: dict[str, float] = {}
    for name in PBPK_TISSUES:
        t = phys.tissues[name]
        f_nl, f_ph, f_w = t.f_neutral_lipid, t.f_phospholipid, t.f_water
        if name == "adipose":
            numer = d_vow * (f_nl + 0.3 * f_ph) + (f_w + 0.7 * f_ph)
            # Poulin & Theil assign fu = 1 in adipose.
            kp[name] = (numer / denom_olive) * fu_p
        else:
            numer = p_ow * (f_nl + 0.3 * f_ph) + (f_w + 0.7 * f_ph)
            kp[name] = (numer / denom_octanol) * (fu_p / fu_t)

    return PartitionResult(
        kp=kp,
        fu_tissue_non_adipose=fu_t,
        method="Poulin & Theil (2002) tissue-composition method",
        log_d_olive_oil_water=log_dvow,
        warnings=tuple(warnings),
    )


def steady_state_volume_of_distribution_L_per_kg(
    drug: DrugPhysChem,
    partition: PartitionResult | None = None,
    physiology: ReferencePhysiology | None = None,
) -> float:
    """Predicted Vss per kg body weight.

        Vss = Vplasma + Verythrocytes*E:P + sum_t ( V_t * Kp_t )

    Erythrocyte contribution is folded in through the blood:plasma ratio:
        V_e * (B:P - (1 - Hct)) / Hct   in plasma-equivalent terms.

    This is the single quantitative prediction from the PBPK distribution module
    that SYNTHBODY checks against an observed human value.
    """
    phys = physiology or load_reference_physiology()
    part = partition or predict_partition_coefficients(drug, phys)

    v_plasma = phys.plasma_volume_mL_per_kg / 1000.0  # L/kg
    hct = phys.hematocrit
    v_blood = v_plasma / (1.0 - hct)
    v_rbc = v_blood - v_plasma

    # Erythrocyte:plasma concentration ratio implied by B:P and haematocrit.
    e_p = (drug.blood_plasma_ratio - (1.0 - hct)) / hct

    vss = v_plasma + v_rbc * max(e_p, 0.0)
    for name in PBPK_TISSUES:
        vss += phys.tissues[name].vol_L_per_kg * part.kp[name]
    return vss


def ionised_fraction_fractions(ph: float, pka_acidic: float | None, pka_basic: float | None) -> float:
    """Fraction of drug in the neutral form at a given pH (Henderson-Hasselbalch).

    Provided for display and for future Rodgers-Rowland work. The Poulin-Theil
    implementation above operates on the neutral-species log P and does not call
    this, which is one of its documented approximations.
    """
    ratio = 1.0
    if pka_acidic is not None:
        ratio += 10.0 ** (ph - pka_acidic)
    if pka_basic is not None:
        ratio += 10.0 ** (pka_basic - ph)
    return 1.0 / ratio


def log_safe(x: float) -> float:  # pragma: no cover - small numeric helper
    return math.log(max(x, 1e-300))
