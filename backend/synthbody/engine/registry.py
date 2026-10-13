"""
The model and drug registry.

Everything the UI can run is declared here: the model structures, their
parameter schemas, which observables they emit, and what validation status each
one carries. The frontend reads this registry rather than hard-coding model
knowledge, so adding a model is a backend-only change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable

from synthbody.config import LIBRARY_DIR
from synthbody.engine.core import BaseModel
from synthbody.engine.models.compartmental import (
    OneCompartmentFirstOrderAbsorption,
    OneCompartmentMichaelisMenten,
    TwoCompartment,
)
from synthbody.engine.models.absorption import CompartmentalAbsorption, OralDrugInput
from synthbody.engine.models.oral_pbpk import OralPBPK
from synthbody.engine.models.pbpk import PerfusionLimitedPBPK
from synthbody.engine.physiology.partition import DrugPhysChem
from synthbody.engine.provenance import ValidationStatus


@dataclass(frozen=True)
class ParameterSchema:
    name: str
    label: str
    unit: str
    default: float
    minimum: float
    maximum: float
    description: str
    scales_with_weight: bool = False
    allometric_exponent: float | None = None
    step: float | None = None
    group: str = "Disposition"


@dataclass(frozen=True)
class ObservableSchema:
    name: str
    label: str
    unit: str
    description: str
    is_primary: bool = False


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    name: str
    short_name: str
    description: str
    category: str
    routes: tuple[str, ...]
    parameters: tuple[ParameterSchema, ...]
    observables: tuple[ObservableSchema, ...]
    validation_status: ValidationStatus
    validation_summary: str
    reference_ids: tuple[str, ...]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    builder: Callable[..., BaseModel]
    dose_target_state: dict[str, int]
    supports_population: bool = True
    supports_sensitivity: bool = True
    has_analytic_solution: bool = False
    supports_multiple_dosing: bool = True
    """False for models whose dose enters as a solid particle population.

    The absorption models derive a shared particle radius from the total
    undissolved mass against the mass initially dosed. A second dose arriving
    while the first is still dissolving would make that radius meaningless --
    the two populations are at different stages of dissolution and the model
    represents only one. Rather than return a quietly wrong number, those
    models decline multiple dosing. Removing this restriction needs a
    polydisperse particle representation, which is tracked in PROGRESS.md.
    """
    requires_dose_notification: bool = False
    """True for models exposing ``set_dose``, which need the dose before running.

    ``fraction_absorbed`` and the particle radius are both expressed relative to
    the administered amount, so these models have to be told what it is.
    """

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "short_name": self.short_name,
            "description": self.description,
            "category": self.category,
            "routes": list(self.routes),
            "parameters": [
                {
                    "name": p.name,
                    "label": p.label,
                    "unit": p.unit,
                    "default": p.default,
                    "minimum": p.minimum,
                    "maximum": p.maximum,
                    "description": p.description,
                    "scales_with_weight": p.scales_with_weight,
                    "allometric_exponent": p.allometric_exponent,
                    "step": p.step,
                    "group": p.group,
                }
                for p in self.parameters
            ],
            "observables": [
                {
                    "name": o.name,
                    "label": o.label,
                    "unit": o.unit,
                    "description": o.description,
                    "is_primary": o.is_primary,
                }
                for o in self.observables
            ],
            "validation_status": self.validation_status.value,
            "validation_summary": self.validation_summary,
            "reference_ids": list(self.reference_ids),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "dose_target_state": self.dose_target_state,
            "supports_population": self.supports_population,
            "supports_sensitivity": self.supports_sensitivity,
            "has_analytic_solution": self.has_analytic_solution,
            "supports_multiple_dosing": self.supports_multiple_dosing,
            "requires_dose_notification": self.requires_dose_notification,
        }


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def _build_1cmt_foa(params: dict[str, float], **_: Any) -> BaseModel:
    return OneCompartmentFirstOrderAbsorption(
        cl_L_per_h=params["CL"],
        v_L=params["V"],
        ka_per_h=params["ka"],
        bioavailability=params.get("F", 1.0),
        lag_time_h=params.get("t_lag", 0.0),
    )


def _build_2cmt(params: dict[str, float], **_: Any) -> BaseModel:
    ka = params.get("ka")
    return TwoCompartment(
        cl_L_per_h=params["CL"],
        v1_L=params["V1"],
        q_L_per_h=params["Q"],
        v2_L=params["V2"],
        ka_per_h=ka if ka and ka > 0 else None,
        bioavailability=params.get("F", 1.0),
    )


def _build_mm(params: dict[str, float], **_: Any) -> BaseModel:
    ka = params.get("ka")
    return OneCompartmentMichaelisMenten(
        vmax_mg_per_h=params["Vmax"],
        km_mg_per_L=params["Km"],
        v_L=params["V"],
        ka_per_h=ka if ka and ka > 0 else None,
        bioavailability=params.get("F", 1.0),
    )


def _build_pbpk(params: dict[str, float], **_: Any) -> BaseModel:
    drug = DrugPhysChem(
        log_p=params["logP"],
        fraction_unbound_plasma=params["fu_p"],
        blood_plasma_ratio=params.get("BP", 1.0),
    )
    ka = params.get("ka")
    return PerfusionLimitedPBPK(
        drug=drug,
        body_weight_kg=params.get("BW", 70.0),
        hepatic_intrinsic_clearance_L_per_h=params.get("CLint_H", 0.0),
        renal_clearance_L_per_h=params.get("CL_R", 0.0),
        ka_per_h=ka if ka and ka > 0 else None,
        bioavailability=params.get("F", 1.0),
    )


def _oral_drug_input(params: dict[str, float]) -> OralDrugInput:
    """Shared physicochemical inputs for the two absorption-bearing models."""
    pka = params.get("pKa_acidic", 0.0)
    return OralDrugInput(
        intrinsic_solubility_mg_per_mL=params.get("S0", 1.0),
        effective_permeability_cm_per_s=params.get("Peff", 3.0e-4),
        # 0 is the schema's "no ionisable group" sentinel: a pKa of exactly zero
        # is not a meaningful input for an orally administered small molecule.
        pka_acidic=pka if pka and pka > 0 else None,
        particle_radius_um=params.get("r_particle", 25.0),
        precipitation_rate_per_h=params.get("k_precip", 0.0),
    )


def _build_absorption(params: dict[str, float], **_: Any) -> BaseModel:
    return CompartmentalAbsorption(drug=_oral_drug_input(params))


def _build_oral_pbpk(params: dict[str, float], **_: Any) -> BaseModel:
    drug = DrugPhysChem(
        log_p=params["logP"],
        fraction_unbound_plasma=params["fu_p"],
        blood_plasma_ratio=params.get("BP", 1.0),
    )
    return OralPBPK(
        drug_physchem=drug,
        oral_input=_oral_drug_input(params),
        body_weight_kg=params.get("BW", 70.0),
        hepatic_intrinsic_clearance_L_per_h=params.get("CLint_H", 0.0),
        renal_clearance_L_per_h=params.get("CL_R", 0.0),
        gut_intrinsic_clearance_L_per_h=params.get("CLint_gut", 0.0),
    )


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------
_P = ParameterSchema
_O = ObservableSchema

# Shared between the absorption model and the oral PBPK model so the two cannot
# drift apart in their physicochemical input schema.
_ABSORPTION_PARAMS = (
    _P("S0", "Intrinsic solubility", "mg/mL", 1.0, 1e-6, 1000.0,
       "Solubility of the neutral species. pH-dependent solubility is computed "
       "from this and the pKa by Henderson-Hasselbalch.",
       group="Physicochemistry", step=0.1),
    _P("Peff", "Effective permeability", "cm/s", 3.0e-4, 1e-7, 1e-2,
       "Human jejunal effective permeability. Above roughly 2-4e-4 cm/s is "
       "conventionally considered high permeability.",
       group="Physicochemistry", step=1e-5),
    _P("pKa_acidic", "Acidic pKa", "", 0.0, 0.0, 14.0,
       "Acidic dissociation constant. Leave at 0 for a non-ionisable compound.",
       group="Physicochemistry", step=0.1),
    _P("r_particle", "Particle radius", "um", 25.0, 0.01, 500.0,
       "Initial radius of the monodisperse particle population. A formulation "
       "input, not a property of the drug.",
       group="Formulation", step=1.0),
    _P("k_precip", "Precipitation rate", "1/h", 0.0, 0.0, 100.0,
       "First-order precipitation of supersaturated drug. 0 disables it.",
       group="Formulation", step=0.1),
)

_ABSORPTION_OBSERVABLES = (
    _O("fraction_absorbed", "Fraction absorbed", "fraction",
       "Cumulative fraction of the dose that has crossed the gut wall. This is "
       "fraction ABSORBED, not bioavailability: no first-pass extraction is "
       "applied in the standalone absorption model."),
    _O("cumulative_absorbed", "Cumulative absorbed", "mg",
       "Absorbed mass; this is the quantity convolved with a disposition model."),
    _O("absorption_rate", "Absorption rate", "mg",
       "Numerical derivative of the cumulative absorbed curve."),
    _O("dissolved_total", "Dissolved in lumen", "mg",
       "Total dissolved drug across stomach, small intestine and colon."),
    _O("solid_total", "Undissolved in lumen", "mg",
       "Total solid drug remaining anywhere in the tract."),
    _O("faecal_loss", "Lost to faeces", "mg",
       "Drug that transited past the absorptive region without being absorbed."),
)


@lru_cache
def model_specs() -> dict[str, ModelSpec]:
    one_cmt = OneCompartmentFirstOrderAbsorption(cl_L_per_h=2.8, v_L=34.0, ka_per_h=1.5)
    two_cmt = TwoCompartment(cl_L_per_h=10.0, v1_L=10.0, q_L_per_h=10.0, v2_L=10.0)
    mm = OneCompartmentMichaelisMenten(vmax_mg_per_h=30.0, km_mg_per_L=5.0, v_L=50.0)
    # Probe instances, built only to read their self-declared description,
    # assumptions, limitations and validation status, so the registry and the
    # model classes cannot disagree about what a model claims.
    absorption = CompartmentalAbsorption(
        drug=OralDrugInput(
            intrinsic_solubility_mg_per_mL=1.0, effective_permeability_cm_per_s=3.0e-4
        )
    )
    oral_pbpk = OralPBPK(
        drug_physchem=DrugPhysChem(
            log_p=-0.02, fraction_unbound_plasma=0.6, blood_plasma_ratio=0.82
        ),
        oral_input=OralDrugInput(
            intrinsic_solubility_mg_per_mL=1.0, effective_permeability_cm_per_s=3.0e-4
        ),
    )

    specs: list[ModelSpec] = [
        ModelSpec(
            model_id="pk_1cmt_foa",
            name=one_cmt.model_name,
            short_name="1-CMT oral",
            description=one_cmt.description,
            category="Compartmental PK",
            routes=("oral", "iv_bolus", "iv_infusion"),
            parameters=(
                _P("CL", "Clearance", "L/h", 2.8, 0.001, 500.0,
                    "Apparent total clearance (CL/F for oral data).", True, 0.75, 0.05),
                _P("V", "Volume of distribution", "L", 34.0, 0.1, 2000.0,
                   "Apparent volume of distribution (V/F for oral data).", True, 1.0, 0.5),
                _P("ka", "Absorption rate constant", "1/h", 1.5, 0.001, 50.0,
                   "First-order absorption rate constant.", group="Absorption", step=0.05),
                _P("F", "Bioavailability", "fraction", 1.0, 0.01, 1.0,
                   "Bioavailable fraction. Not identifiable from oral data alone.",
                   group="Absorption", step=0.01),
                _P("t_lag", "Absorption lag", "h", 0.0, 0.0, 12.0,
                   "Delay before absorption begins.", group="Absorption", step=0.05),
            ),
            observables=(
                _O("plasma_concentration", "Plasma concentration", "mg/L",
                   "Concentration in the central compartment.", True),
                _O("amount_depot", "Amount in depot", "mg", "Drug awaiting absorption."),
                _O("amount_central", "Amount in central compartment", "mg", "Systemic drug amount."),
                _O("amount_eliminated", "Cumulative eliminated", "mg",
                   "Total drug removed, used for the mass-balance check."),
            ),
            validation_status=one_cmt.validation_status,
            validation_summary=one_cmt.validation_summary,
            reference_ids=tuple(one_cmt.reference_ids),
            assumptions=tuple(one_cmt.assumptions),
            limitations=tuple(one_cmt.limitations),
            builder=_build_1cmt_foa,
            dose_target_state={"oral": 0, "iv_bolus": 1, "iv_infusion": 1},
            has_analytic_solution=True,
        ),
        ModelSpec(
            model_id="pk_2cmt",
            name=two_cmt.model_name,
            short_name="2-CMT",
            description=two_cmt.description,
            category="Compartmental PK",
            routes=("iv_bolus", "iv_infusion", "oral"),
            parameters=(
                _P("CL", "Clearance", "L/h", 10.0, 0.001, 1000.0, "Total clearance.", True, 0.75, 0.1),
                _P("V1", "Central volume", "L", 10.0, 0.1, 2000.0, "Central compartment volume.",
                   True, 1.0, 0.1),
                _P("Q", "Intercompartmental clearance", "L/h", 10.0, 0.001, 1000.0,
                   "Distribution clearance between compartments.", True, 0.75, 0.1),
                _P("V2", "Peripheral volume", "L", 10.0, 0.1, 5000.0, "Peripheral compartment volume.",
                   True, 1.0, 0.1),
                _P("ka", "Absorption rate constant", "1/h", 0.0, 0.0, 50.0,
                   "Set to 0 for intravenous-only use.", group="Absorption", step=0.05),
                _P("F", "Bioavailability", "fraction", 1.0, 0.01, 1.0, "Bioavailable fraction.",
                   group="Absorption", step=0.01),
            ),
            observables=(
                _O("plasma_concentration", "Plasma concentration", "mg/L",
                   "Central compartment concentration.", True),
                _O("peripheral_concentration", "Peripheral concentration", "mg/L",
                   "Peripheral compartment concentration."),
                _O("amount_central", "Amount central", "mg", "Central compartment amount."),
                _O("amount_peripheral", "Amount peripheral", "mg", "Peripheral compartment amount."),
                _O("amount_eliminated", "Cumulative eliminated", "mg", "Mass-balance bookkeeping."),
            ),
            validation_status=two_cmt.validation_status,
            validation_summary=two_cmt.validation_summary,
            reference_ids=tuple(two_cmt.reference_ids),
            assumptions=tuple(two_cmt.assumptions),
            limitations=tuple(two_cmt.limitations),
            builder=_build_2cmt,
            dose_target_state={"oral": 0, "iv_bolus": 1, "iv_infusion": 1},
            has_analytic_solution=True,
        ),
        ModelSpec(
            model_id="pk_1cmt_mm",
            name=mm.model_name,
            short_name="1-CMT Michaelis-Menten",
            description=mm.description,
            category="Non-linear PK",
            routes=("oral", "iv_bolus", "iv_infusion"),
            parameters=(
                _P("Vmax", "Maximum elimination rate", "mg", 30.0, 0.001, 10000.0,
                   "Maximum elimination rate in mg per hour.", True, 0.75, 0.5),
                _P("Km", "Michaelis constant", "mg/L", 5.0, 0.001, 1000.0,
                   "Concentration at half-maximal elimination rate.", step=0.1),
                _P("V", "Volume of distribution", "L", 50.0, 0.1, 2000.0,
                   "Volume of distribution.", True, 1.0, 0.5),
                _P("ka", "Absorption rate constant", "1/h", 1.0, 0.0, 50.0,
                   "Set to 0 for intravenous-only use.", group="Absorption", step=0.05),
                _P("F", "Bioavailability", "fraction", 1.0, 0.01, 1.0, "Bioavailable fraction.",
                   group="Absorption", step=0.01),
            ),
            observables=(
                _O("plasma_concentration", "Plasma concentration", "mg/L",
                   "Central compartment concentration.", True),
                _O("instantaneous_clearance", "Apparent clearance", "L/h",
                   "Vmax/(Km+C): the clearance an observer would infer at this concentration."),
                _O("saturation_fraction", "Pathway saturation", "fraction",
                   "C/(Km+C): fraction of maximal elimination capacity in use."),
                _O("amount_eliminated", "Cumulative eliminated", "mg", "Mass-balance bookkeeping."),
            ),
            validation_status=mm.validation_status,
            validation_summary=mm.validation_summary,
            reference_ids=tuple(mm.reference_ids),
            assumptions=tuple(mm.assumptions),
            limitations=tuple(mm.limitations),
            builder=_build_mm,
            dose_target_state={"oral": 0, "iv_bolus": 1, "iv_infusion": 1},
            has_analytic_solution=False,
        ),
        ModelSpec(
            model_id="pbpk_perfusion_limited",
            name="Whole-body perfusion-limited PBPK",
            short_name="PBPK (12 tissue)",
            description=(
                "Twelve-compartment blood-flow-limited PBPK model with predicted tissue "
                "partition coefficients, hepatic well-stirred metabolism and renal clearance."
            ),
            category="Physiologically based PK",
            routes=("iv_bolus", "iv_infusion", "oral"),
            parameters=(
                _P("logP", "log P (octanol:water)", "", 0.0, -3.0, 7.0,
                   "Partition coefficient of the neutral species, log10.",
                   group="Physicochemistry", step=0.1),
                _P("fu_p", "Fraction unbound in plasma", "fraction", 0.6, 0.001, 1.0,
                   "Unbound fraction in plasma.", group="Physicochemistry", step=0.01),
                _P("BP", "Blood:plasma ratio", "ratio", 1.0, 0.1, 5.0,
                   "Whole blood to plasma concentration ratio.", group="Physicochemistry", step=0.05),
                _P("CLint_H", "Hepatic intrinsic clearance", "L/h", 10.0, 0.0, 10000.0,
                   "Intrinsic clearance acting on unbound drug in the liver.",
                   True, 0.75, 0.5, group="Elimination"),
                _P("CL_R", "Renal clearance", "L/h", 0.3, 0.0, 100.0,
                   "Renal plasma clearance.", True, 0.75, 0.05, group="Elimination"),
                _P("BW", "Body weight", "", 70.0, 1.0, 300.0,
                   "Body weight in kg; scales all organ volumes and flows.",
                   group="Physiology", step=1.0),
                _P("ka", "Absorption rate constant", "1/h", 0.0, 0.0, 50.0,
                   "Set to 0 for intravenous-only use. Oral absorption enters the liver.",
                   group="Absorption", step=0.05),
                _P("F", "Fraction absorbed", "fraction", 1.0, 0.01, 1.0,
                   "Fraction of the oral dose reaching the portal vein.",
                   group="Absorption", step=0.01),
            ),
            observables=(
                _O("plasma_concentration", "Plasma concentration (venous)", "mg/L",
                   "What a peripheral venous blood draw would report.", True),
                _O("arterial_blood_concentration", "Arterial blood concentration", "mg/L",
                   "Arterial pool concentration."),
                _O("venous_blood_concentration", "Venous blood concentration", "mg/L",
                   "Venous pool concentration."),
                _O("C_liver", "Liver concentration", "mg/L", "Total liver tissue concentration."),
                _O("C_kidney", "Kidney concentration", "mg/L", "Total kidney tissue concentration."),
                _O("C_brain", "Brain concentration", "mg/L",
                   "Total brain tissue concentration. No blood-brain barrier is modelled, so "
                   "this will overestimate CNS exposure for actively excluded compounds."),
                _O("C_adipose", "Adipose concentration", "mg/L", "Total adipose tissue concentration."),
                _O("C_muscle", "Muscle concentration", "mg/L", "Total muscle tissue concentration."),
                _O("C_heart", "Heart concentration", "mg/L", "Total heart tissue concentration."),
                _O("C_lung", "Lung concentration", "mg/L", "Total lung tissue concentration."),
                _O("C_gut", "Gut concentration", "mg/L", "Total gut tissue concentration."),
                _O("C_spleen", "Spleen concentration", "mg/L", "Total spleen tissue concentration."),
                _O("C_bone", "Bone concentration", "mg/L", "Total bone tissue concentration."),
                _O("C_skin", "Skin concentration", "mg/L", "Total skin tissue concentration."),
                _O("C_rest", "Remainder concentration", "mg/L", "Lumped remainder compartment."),
                _O("amount_eliminated", "Cumulative eliminated", "mg", "Mass-balance bookkeeping."),
            ),
            validation_status=ValidationStatus.RESEARCH_ONLY,
            validation_summary=(
                "Numerically verified (mass balance closes; predicted Vss matches the "
                "independent analytic calculation). NOT validated against observed human "
                "concentration-time data. Tissue concentrations are model output, not "
                "exposure predictions."
            ),
            reference_ids=(
                "poulin2002", "rodgers2006", "davies1993", "ilsi1994",
                "schmitt2008", "pearce2017", "eissing2011_osp",
            ),
            assumptions=(
                "Perfusion-limited distribution with no permeability barrier.",
                "Partition coefficients predicted by the Poulin-Theil method.",
                "Well-stirred hepatic elimination; no active transport or biliary excretion.",
                "A single reference adult physiology scaled only by body weight.",
            ),
            limitations=(
                "RESEARCH ONLY: no observed concentration-time validation.",
                "Poulin-Theil partitioning is unreliable for moderate-to-strong bases.",
                "No blood-brain barrier, no metabolite tracking, no enterohepatic recirculation.",
            ),
            builder=_build_pbpk,
            dose_target_state={"oral": 0, "iv_bolus": 2, "iv_infusion": 2},
            has_analytic_solution=False,
        ),
        ModelSpec(
            model_id="gi_absorption_cat",
            name=absorption.model_name,
            short_name="GI absorption (7-cmt)",
            description=(
                "Seven-compartment compartmental absorption and transit model: gastric "
                "emptying, small-intestinal transit, pH-dependent solubility, "
                "Nernst-Brunner dissolution of shrinking particles and "
                "permeability-limited uptake. Predicts the fraction absorbed and the "
                "absorption-rate profile from physicochemistry alone, with no "
                "disposition model attached."
            ),
            category="Absorption",
            routes=("oral",),
            parameters=_ABSORPTION_PARAMS,
            observables=(
                _O("fraction_absorbed", "Fraction absorbed", "fraction",
                   "Cumulative fraction of the dose across the gut wall. Fraction "
                   "ABSORBED, not bioavailability.", True),
            ) + _ABSORPTION_OBSERVABLES[1:],
            validation_status=absorption.validation_status,
            validation_summary=absorption.validation_summary,
            reference_ids=tuple(absorption.reference_ids),
            assumptions=tuple(absorption.assumptions),
            limitations=tuple(absorption.limitations),
            builder=_build_absorption,
            dose_target_state={"oral": 0},
            # No plasma concentration exists in this model, so the population and
            # sensitivity workspaces -- which are built around exposure metrics
            # derived from a concentration-time curve -- have nothing to report.
            supports_population=False,
            supports_sensitivity=True,
            has_analytic_solution=False,
            supports_multiple_dosing=False,
            requires_dose_notification=True,
        ),
        ModelSpec(
            model_id="pbpk_oral_acat",
            name=oral_pbpk.model_name,
            short_name="Oral PBPK (ACAT + 12 tissue)",
            description=oral_pbpk.description,
            category="Physiologically based PK",
            routes=("oral",),
            parameters=(
                _P("logP", "log P (octanol:water)", "", -0.02, -3.0, 7.0,
                   "Partition coefficient of the neutral species, log10.",
                   group="Physicochemistry", step=0.1),
                _P("fu_p", "Fraction unbound in plasma", "fraction", 0.6, 0.001, 1.0,
                   "Unbound fraction in plasma.", group="Physicochemistry", step=0.01),
                _P("BP", "Blood:plasma ratio", "ratio", 0.82, 0.1, 5.0,
                   "Whole blood to plasma concentration ratio.",
                   group="Physicochemistry", step=0.05),
            ) + _ABSORPTION_PARAMS + (
                _P("CLint_H", "Hepatic intrinsic clearance", "L/h", 4.5, 0.0, 10000.0,
                   "Intrinsic clearance on unbound drug in the liver. Hepatic "
                   "first-pass extraction emerges from this and liver blood flow.",
                   True, 0.75, 0.5, group="Elimination"),
                _P("CLint_gut", "Gut-wall intrinsic clearance", "L/h", 0.0, 0.0, 10000.0,
                   "Intrinsic clearance on unbound drug in the gut wall. Zero by "
                   "default: SYNTHBODY ships no evidence base for this parameter, so "
                   "any non-zero value is the operator's assumption.",
                   True, 0.75, 0.5, group="Elimination"),
                _P("CL_R", "Renal clearance", "L/h", 0.0, 0.0, 100.0,
                   "Renal plasma clearance.", True, 0.75, 0.05, group="Elimination"),
                _P("BW", "Body weight", "", 70.0, 1.0, 300.0,
                   "Body weight in kg; scales all organ volumes and flows.",
                   group="Physiology", step=1.0),
            ),
            observables=(
                _O("plasma_concentration", "Plasma concentration (venous)", "mg/L",
                   "What a peripheral venous blood draw would report. This is the "
                   "observable that has been tested against observed human data.", True),
                _O("bioavailable_fraction", "Fraction past the gut wall", "fraction",
                   "Absorbed dose less cumulative gut-wall extraction. The hepatic "
                   "first-pass factor is reported separately as F_hepatic_predicted, "
                   "because cumulative hepatic and systemic elimination share one ledger."),
                _O("gut_wall_extracted", "Gut-wall extraction", "mg",
                   "Cumulative drug removed by gut-wall metabolism. Zero unless "
                   "CLint_gut is set."),
                _O("C_liver", "Liver concentration", "mg/L",
                   "Total liver tissue concentration. UNVALIDATED: no observed human "
                   "tissue data ships with SYNTHBODY."),
                _O("C_gut", "Gut concentration", "mg/L",
                   "Total gut tissue concentration, the compartment absorbed drug "
                   "enters. UNVALIDATED."),
                _O("C_kidney", "Kidney concentration", "mg/L", "UNVALIDATED."),
                _O("C_brain", "Brain concentration", "mg/L",
                   "UNVALIDATED, and no blood-brain barrier is modelled, so this "
                   "overestimates CNS exposure for actively excluded compounds."),
                _O("C_adipose", "Adipose concentration", "mg/L", "UNVALIDATED."),
                _O("C_muscle", "Muscle concentration", "mg/L", "UNVALIDATED."),
                _O("C_heart", "Heart concentration", "mg/L", "UNVALIDATED."),
                _O("C_lung", "Lung concentration", "mg/L", "UNVALIDATED."),
                _O("C_spleen", "Spleen concentration", "mg/L", "UNVALIDATED."),
                _O("C_bone", "Bone concentration", "mg/L", "UNVALIDATED."),
                _O("C_skin", "Skin concentration", "mg/L", "UNVALIDATED."),
                _O("C_rest", "Remainder concentration", "mg/L", "UNVALIDATED."),
                _O("arterial_blood_concentration", "Arterial blood concentration", "mg/L",
                   "Arterial pool concentration."),
                _O("venous_blood_concentration", "Venous blood concentration", "mg/L",
                   "Venous pool concentration."),
                _O("amount_eliminated", "Cumulative eliminated", "mg",
                   "Hepatic plus renal elimination. Mass-balance bookkeeping."),
            ) + _ABSORPTION_OBSERVABLES,
            validation_status=oral_pbpk.validation_status,
            validation_summary=oral_pbpk.validation_summary,
            reference_ids=tuple(oral_pbpk.reference_ids),
            assumptions=tuple(oral_pbpk.assumptions),
            limitations=tuple(oral_pbpk.limitations),
            builder=_build_oral_pbpk,
            dose_target_state={"oral": 0},
            supports_population=True,
            supports_sensitivity=True,
            has_analytic_solution=False,
            supports_multiple_dosing=False,
            requires_dose_notification=True,
        ),
    ]
    return {s.model_id: s for s in specs}


def get_model_spec(model_id: str) -> ModelSpec:
    specs = model_specs()
    if model_id not in specs:
        raise KeyError(f"Unknown model {model_id!r}. Available: {sorted(specs)}")
    return specs[model_id]


def build_model(model_id: str, parameters: dict[str, float]) -> BaseModel:
    """Instantiate a model, validating the supplied parameters against its schema."""
    spec = get_model_spec(model_id)
    merged = {p.name: p.default for p in spec.parameters}
    unknown = set(parameters) - set(merged)
    if unknown:
        raise ValueError(
            f"Model {model_id!r} has no parameter(s) {sorted(unknown)}. "
            f"Expected: {sorted(merged)}"
        )
    for p in spec.parameters:
        if p.name in parameters:
            v = float(parameters[p.name])
            if not p.minimum <= v <= p.maximum:
                raise ValueError(
                    f"{model_id}.{p.name} = {v} {p.unit} is outside the allowed range "
                    f"[{p.minimum}, {p.maximum}]."
                )
            merged[p.name] = v
    return spec.builder(merged)


# ---------------------------------------------------------------------------
# Drug library
# ---------------------------------------------------------------------------
@lru_cache
def drug_library() -> dict[str, Any]:
    return json.loads((LIBRARY_DIR / "drugs.json").read_text(encoding="utf-8"))


@lru_cache
def reference_library() -> dict[str, Any]:
    return json.loads((LIBRARY_DIR / "references.json").read_text(encoding="utf-8"))


def get_reference(ref_id: str) -> dict[str, Any] | None:
    for r in reference_library()["references"]:
        if r["id"] == ref_id:
            return r
    return None


def get_drug(drug_id: str) -> dict[str, Any]:
    for d in drug_library()["drugs"]:
        if d["drug_id"] == drug_id:
            return d
    raise KeyError(
        f"Unknown drug {drug_id!r}. Available: {[d['drug_id'] for d in drug_library()['drugs']]}"
    )
