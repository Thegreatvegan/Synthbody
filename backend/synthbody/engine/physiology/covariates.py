"""
Virtual patient descriptors and the covariate equations that turn them into
model parameters.

Scope discipline: this module implements only relationships that have a named
published equation or a widely accepted theory-based form. Where SYNTHBODY
applies a multiplier that was *not* read out of a specific paper (for example
the magnitude of the smoking effect on theophylline clearance), the multiplier
is returned tagged ILLUSTRATIVE or INFERRED and the UI shows it as such.

Nothing here is a clinical dosing tool.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from synthbody.engine.provenance import ParameterOrigin

# Theory-based allometric exponents (Anderson & Holford 2008, PMID 17914927).
ALLOMETRIC_EXPONENT_CLEARANCE = 0.75
ALLOMETRIC_EXPONENT_VOLUME = 1.0
REFERENCE_WEIGHT_KG = 70.0


class Sex(str, Enum):
    """Sex recorded for the purpose of physiological equations only.

    Used because the equations SYNTHBODY implements (Cockcroft-Gault,
    CKD-EPI 2021, fat-free mass) were published with a binary sex coefficient.
    This is a limitation of those equations, documented in the limitations
    report; it is not a statement about the people a model might represent.
    """

    FEMALE = "female"
    MALE = "male"


class SmokingStatus(str, Enum):
    NON_SMOKER = "non_smoker"
    SMOKER = "smoker"


class HepaticFunction(str, Enum):
    NORMAL = "normal"
    MILD_IMPAIRMENT = "mild_impairment"
    MODERATE_IMPAIRMENT = "moderate_impairment"
    SEVERE_IMPAIRMENT = "severe_impairment"


@dataclass
class VirtualPatient:
    """A hypothetical simulated subject. Never a real person's record.

    `label` is free text for the operator. `is_synthetic` exists so that every
    downstream artefact (report, export, figure) can state plainly that the
    subject is not a patient.
    """

    label: str = "Virtual subject"
    age_years: float = 35.0
    weight_kg: float = 70.0
    height_cm: float = 175.0
    sex: Sex = Sex.MALE
    serum_creatinine_mg_dL: float = 0.9
    albumin_g_dL: float = 4.3
    hepatic_function: HepaticFunction = HepaticFunction.NORMAL
    smoking_status: SmokingStatus = SmokingStatus.NON_SMOKER
    notes: str = ""
    is_synthetic: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    # ------------------------------------------------------------- validation
    def validate(self) -> None:
        problems: list[str] = []
        if not 0.0 < self.age_years <= 120.0:
            problems.append(f"age_years={self.age_years} outside (0, 120]")
        if not 1.0 <= self.weight_kg <= 400.0:
            problems.append(f"weight_kg={self.weight_kg} outside [1, 400]")
        if not 30.0 <= self.height_cm <= 260.0:
            problems.append(f"height_cm={self.height_cm} outside [30, 260]")
        if not 0.1 <= self.serum_creatinine_mg_dL <= 25.0:
            problems.append(f"serum_creatinine_mg_dL={self.serum_creatinine_mg_dL} outside [0.1, 25]")
        if not 1.0 <= self.albumin_g_dL <= 7.0:
            problems.append(f"albumin_g_dL={self.albumin_g_dL} outside [1, 7]")
        if problems:
            raise ValueError("Implausible virtual patient: " + "; ".join(problems))

    # -------------------------------------------------------------- body size
    @property
    def bmi(self) -> float:
        h = self.height_cm / 100.0
        return self.weight_kg / (h * h)

    @property
    def bsa_m2(self) -> float:
        """Du Bois & Du Bois (1916) body surface area.

        BSA = 0.007184 * height_cm^0.725 * weight_kg^0.425
        """
        return 0.007184 * self.height_cm**0.725 * self.weight_kg**0.425

    @property
    def fat_free_mass_kg(self) -> float:
        """Janmahasatian et al. (2005) fat-free mass.

        Reported here as a descriptive body-composition summary for the patient
        builder. The PK models in this release scale on total body weight, so
        FFM is displayed but not used to drive clearance.
        """
        bmi = self.bmi
        if self.sex is Sex.MALE:
            return (9.27e3 * self.weight_kg) / (6.68e3 + 216.0 * bmi)
        return (9.27e3 * self.weight_kg) / (8.78e3 + 244.0 * bmi)

    @property
    def ideal_body_weight_kg(self) -> float:
        """Devine (1974) ideal body weight, in kg, from height in inches."""
        inches = self.height_cm / 2.54
        base = 50.0 if self.sex is Sex.MALE else 45.5
        return base + 2.3 * max(inches - 60.0, 0.0)

    # ----------------------------------------------------------- renal function
    def creatinine_clearance_cockcroft_gault_mL_min(self) -> float:
        """Cockcroft & Gault (1976), PMID 1244564.

        CrCl = ((140 - age) * weight) / (72 * Scr) , x0.85 if female.

        Uses total body weight, as in the original publication. Note that this
        overestimates clearance in obesity; the builder displays ideal body
        weight alongside so the operator can see the discrepancy.
        """
        crcl = ((140.0 - self.age_years) * self.weight_kg) / (72.0 * self.serum_creatinine_mg_dL)
        if self.sex is Sex.FEMALE:
            crcl *= 0.85
        return max(crcl, 0.0)

    def egfr_ckd_epi_2021_mL_min_1_73m2(self) -> float:
        """CKD-EPI 2021 creatinine equation (Inker et al. 2021, PMID 34554658).

        eGFR = 142 * min(Scr/k, 1)^a * max(Scr/k, 1)^-1.200 * 0.9938^age * s
          k = 0.7 (female) / 0.9 (male)
          a = -0.241 (female) / -0.302 (male)
          s = 1.012 (female) / 1.000 (male)

        The coefficients are the published values for the race-free equation.
        They are labelled LITERATURE_FITTED: SYNTHBODY did not re-derive them and
        could not open the primary paper to re-check them, so anyone relying on
        this for anything beyond simulation should verify against the source.
        """
        if self.sex is Sex.FEMALE:
            k, a, s = 0.7, -0.241, 1.012
        else:
            k, a, s = 0.9, -0.302, 1.000
        ratio = self.serum_creatinine_mg_dL / k
        return 142.0 * min(ratio, 1.0) ** a * max(ratio, 1.0) ** -1.200 * 0.9938**self.age_years * s

    def egfr_absolute_mL_min(self) -> float:
        """De-normalise eGFR from /1.73 m2 to the individual's BSA."""
        return self.egfr_ckd_epi_2021_mL_min_1_73m2() * self.bsa_m2 / 1.73

    # ------------------------------------------------------------- descriptors
    def summary(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "is_synthetic": self.is_synthetic,
            "age_years": self.age_years,
            "weight_kg": self.weight_kg,
            "height_cm": self.height_cm,
            "sex": self.sex.value,
            "bmi_kg_m2": round(self.bmi, 2),
            "bsa_m2_du_bois": round(self.bsa_m2, 3),
            "fat_free_mass_kg_janmahasatian": round(self.fat_free_mass_kg, 2),
            "ideal_body_weight_kg_devine": round(self.ideal_body_weight_kg, 2),
            "serum_creatinine_mg_dL": self.serum_creatinine_mg_dL,
            "albumin_g_dL": self.albumin_g_dL,
            "creatinine_clearance_cockcroft_gault_mL_min": round(
                self.creatinine_clearance_cockcroft_gault_mL_min(), 1
            ),
            "egfr_ckd_epi_2021_mL_min_1_73m2": round(self.egfr_ckd_epi_2021_mL_min_1_73m2(), 1),
            "egfr_absolute_mL_min": round(self.egfr_absolute_mL_min(), 1),
            "hepatic_function": self.hepatic_function.value,
            "smoking_status": self.smoking_status.value,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Covariate effects
# ---------------------------------------------------------------------------
@dataclass
class CovariateEffect:
    """One multiplicative adjustment applied to a typical parameter value."""

    parameter: str
    multiplier: float
    basis: str
    origin: ParameterOrigin
    reference_ids: list[str] = field(default_factory=list)


def allometric_clearance_factor(weight_kg: float) -> CovariateEffect:
    return CovariateEffect(
        parameter="CL",
        multiplier=(weight_kg / REFERENCE_WEIGHT_KG) ** ALLOMETRIC_EXPONENT_CLEARANCE,
        basis=(
            f"Allometric scaling of clearance: (WT/{REFERENCE_WEIGHT_KG:g})^"
            f"{ALLOMETRIC_EXPONENT_CLEARANCE}"
        ),
        origin=ParameterOrigin.DERIVED,
        reference_ids=["anderson2008"],
    )


def allometric_volume_factor(weight_kg: float) -> CovariateEffect:
    return CovariateEffect(
        parameter="V",
        multiplier=(weight_kg / REFERENCE_WEIGHT_KG) ** ALLOMETRIC_EXPONENT_VOLUME,
        basis=(
            f"Allometric scaling of volume: (WT/{REFERENCE_WEIGHT_KG:g})^"
            f"{ALLOMETRIC_EXPONENT_VOLUME}"
        ),
        origin=ParameterOrigin.DERIVED,
        reference_ids=["anderson2008"],
    )


# Multipliers below are NOT extracted from the cited papers. They encode the
# direction and a plausible magnitude of an effect those papers establish
# qualitatively. They are tagged so no reviewer can mistake them for measurements.
_HEPATIC_MULTIPLIER: dict[HepaticFunction, float] = {
    HepaticFunction.NORMAL: 1.00,
    HepaticFunction.MILD_IMPAIRMENT: 0.80,
    HepaticFunction.MODERATE_IMPAIRMENT: 0.60,
    HepaticFunction.SEVERE_IMPAIRMENT: 0.40,
}

_SMOKING_MULTIPLIER_CYP1A2 = 1.60


def hepatic_clearance_factor(status: HepaticFunction) -> CovariateEffect:
    return CovariateEffect(
        parameter="CL",
        multiplier=_HEPATIC_MULTIPLIER[status],
        basis=(
            "Illustrative multiplier on hepatic clearance by impairment category. "
            "Direction is supported by the cited studies; the magnitude is a "
            "SYNTHBODY default and was not read from any publication."
        ),
        origin=ParameterOrigin.ILLUSTRATIVE,
        reference_ids=["fukuchi2020_cirrhosis"],
    )


def smoking_cyp1a2_clearance_factor(status: SmokingStatus) -> CovariateEffect:
    mult = _SMOKING_MULTIPLIER_CYP1A2 if status is SmokingStatus.SMOKER else 1.0
    return CovariateEffect(
        parameter="CL",
        multiplier=mult,
        basis=(
            "Cigarette smoking induces CYP1A2 and increases the clearance of "
            "CYP1A2 substrates. The 1.6x factor is a commonly quoted order of "
            "magnitude, inferred rather than extracted from the cited review."
        ),
        origin=ParameterOrigin.INFERRED,
        reference_ids=["zevin1999_smoking"],
    )


def renal_clearance_factor(
    patient: VirtualPatient, reference_crcl_mL_min: float = 120.0
) -> CovariateEffect:
    """Scale the renally excreted fraction of clearance by relative renal function."""
    crcl = patient.creatinine_clearance_cockcroft_gault_mL_min()
    return CovariateEffect(
        parameter="CL_renal",
        multiplier=crcl / reference_crcl_mL_min,
        basis=(
            f"Renal clearance scaled by Cockcroft-Gault CrCl ({crcl:.1f} mL/min) "
            f"relative to a reference of {reference_crcl_mL_min:g} mL/min."
        ),
        origin=ParameterOrigin.DERIVED,
        reference_ids=["cockcroft1976"],
    )


def combine(effects: list[CovariateEffect], parameter: str) -> float:
    """Product of all multipliers targeting one parameter."""
    out = 1.0
    for e in effects:
        if e.parameter == parameter:
            out *= e.multiplier
    return out


def log_normal_sigma_from_cv(cv_percent: float) -> float:
    """Convert a coefficient of variation (%) into a log-normal sigma.

    For X = theta * exp(eta), eta ~ N(0, sigma^2):
        CV = sqrt(exp(sigma^2) - 1)
    """
    if cv_percent < 0:
        raise ValueError("CV% cannot be negative.")
    cv = cv_percent / 100.0
    return math.sqrt(math.log(1.0 + cv * cv))
