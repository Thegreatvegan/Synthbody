"""
Whole-body perfusion-limited (blood-flow-limited) PBPK model.

Structure: an arterial blood pool, a venous blood pool, lung, and ten tissue
compartments. Gut and spleen drain into the liver through the portal vein;
everything else drains into the venous pool.

For a non-eliminating tissue t:

    V_t * dC_t/dt = Q_t * ( C_art - C_t * BP / Kp_t )

where C_t is the total tissue concentration, C_art the arterial *blood*
concentration, Kp_t the tissue:plasma partition coefficient and BP the
blood:plasma ratio. The emergent venous blood concentration leaving the tissue
is C_t * BP / Kp_t.

Hepatic elimination uses the well-stirred assumption acting on the unbound
plasma-equivalent concentration in the liver:

    rate = CL_int_H * fu_p * C_liver / Kp_liver

Renal elimination acts on the kidney compartment in the same way.

HONEST SCOPE. This module is RESEARCH_ONLY. It implements published equations
with physiological constants of documented provenance, and the engine verifies
its mass balance and its steady-state behaviour. What it has NOT done is
reproduce an observed human concentration-time profile. The one quantitative
external check that is performed is on predicted steady-state volume of
distribution; see the Validation workspace. Do not read tissue concentrations
out of this model and treat them as predictions of a real exposure.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from synthbody.engine.core import BaseModel
from synthbody.engine.physiology.partition import (
    DrugPhysChem,
    PartitionResult,
    predict_partition_coefficients,
    steady_state_volume_of_distribution_L_per_kg,
)
from synthbody.engine.physiology.reference_man import (
    PBPK_TISSUES,
    PORTAL_TISSUES,
    ReferencePhysiology,
    load_reference_physiology,
)
from synthbody.engine.provenance import ParameterOrigin, ParameterRecord, ValidationStatus

# State layout: depot, arterial, venous, then one per tissue, then eliminated.
_DEPOT = 0
_ARTERIAL = 1
_VENOUS = 2
_TISSUE_OFFSET = 3


@dataclass
class PerfusionLimitedPBPK(BaseModel):
    """Twelve-tissue perfusion-limited PBPK model for a small molecule."""

    drug: DrugPhysChem
    body_weight_kg: float = 70.0
    hepatic_intrinsic_clearance_L_per_h: float = 0.0
    renal_clearance_L_per_h: float = 0.0
    ka_per_h: float | None = None
    bioavailability: float = 1.0
    physiology: ReferencePhysiology | None = None
    partition_override: dict[str, float] | None = None

    model_id: str = field(default="pbpk_perfusion_limited", init=False)
    model_name: str = field(default="Whole-body perfusion-limited PBPK", init=False)
    model_version: str = field(default="1.0.0", init=False)

    description = (
        "Twelve-compartment blood-flow-limited physiologically based pharmacokinetic "
        "model with hepatic and renal elimination. Tissue partition coefficients are "
        "predicted from drug physicochemistry and tissue composition."
    )
    validation_status = ValidationStatus.RESEARCH_ONLY
    validation_summary = (
        "Numerically verified (mass balance closes; the model reduces to the correct "
        "steady state and its predicted Vss agrees with the independent analytic "
        "Vss calculation). NOT validated against observed human concentration-time "
        "data. Tissue concentrations are model output, not exposure predictions."
    )
    reference_ids = [
        "poulin2002",
        "rodgers2006",
        "davies1993",
        "ilsi1994",
        "schmitt2008",
        "pearce2017",
        "eissing2011_osp",
    ]
    assumptions = [
        "Perfusion-limited (blood-flow-limited) distribution: no permeability barrier, "
        "instantaneous equilibration between tissue and the blood perfusing it.",
        "Tissue:plasma partition coefficients predicted by the Poulin-Theil "
        "tissue-composition method from log P and fraction unbound.",
        "Hepatic elimination follows the well-stirred model on the unbound "
        "plasma-equivalent liver concentration.",
        "The lumped `rest` compartment is assigned muscle tissue composition; its "
        "volume and perfusion come from the source dataset but its composition does not.",
        "Cardiac output is set to the sum of the modelled tissue flows so that flow "
        "balance closes exactly, rather than to the independent whole-body value.",
        "No active transport, no biliary excretion, no enterohepatic recirculation, "
        "no metabolite tracking.",
    ]
    limitations = [
        "RESEARCH ONLY. No observed concentration-time validation has been performed.",
        "The Poulin-Theil partitioning method is known to predict poorly for "
        "moderate-to-strong bases; Rodgers-Rowland is not implemented.",
        "Blood-brain barrier is not represented: brain is an ordinary "
        "perfusion-limited compartment and brain concentrations will be overestimated "
        "for compounds that are actively excluded from the CNS.",
        "Organ volume fractions trace to a 1994 ILSI monograph that SYNTHBODY could "
        "not independently retrieve; they are used as redistributed by US EPA httk.",
        "A single reference adult physiology; no paediatric, geriatric, pregnancy or "
        "disease physiology is implemented.",
    ]

    # ------------------------------------------------------------------ setup
    def __post_init__(self) -> None:
        if self.body_weight_kg <= 0:
            raise ValueError("body_weight_kg must be positive.")
        if self.hepatic_intrinsic_clearance_L_per_h < 0 or self.renal_clearance_L_per_h < 0:
            raise ValueError("Clearances cannot be negative.")
        if self.ka_per_h is not None and self.ka_per_h <= 0:
            raise ValueError("ka must be positive when provided.")

        self._phys = self.physiology or load_reference_physiology()
        self._tissues = list(PBPK_TISSUES)
        self._vol = self._phys.tissue_volumes_L(self.body_weight_kg)
        self._flow = self._phys.tissue_flows_L_per_h(self.body_weight_kg)

        self._partition: PartitionResult = predict_partition_coefficients(self.drug, self._phys)
        self._kp = dict(self._partition.kp)
        if self.partition_override:
            unknown = set(self.partition_override) - set(self._kp)
            if unknown:
                raise ValueError(f"partition_override names unknown tissues: {sorted(unknown)}")
            self._kp.update(self.partition_override)

        # Flow bookkeeping. Non-lung tissues are perfused from the arterial pool.
        # Cardiac output is defined as the sum of those flows so that what leaves
        # the arterial pool exactly equals what returns, and mass balance closes.
        self._perfused = [t for t in self._tissues if t != "lung"]
        self._portal = [t for t in self._perfused if t in PORTAL_TISSUES]
        self._systemic = [t for t in self._perfused if t not in PORTAL_TISSUES and t != "liver"]
        self._cardiac_output_L_per_h = float(sum(self._flow[t] for t in self._perfused))

        # Liver receives hepatic-artery flow plus all portal flow.
        self._q_hepatic_artery = self._flow["liver"]
        self._q_portal = float(sum(self._flow[t] for t in self._portal))
        self._q_liver_total = self._q_hepatic_artery + self._q_portal

        self._v_plasma = self._phys.plasma_volume_L(self.body_weight_kg)
        self._v_blood = self._phys.blood_volume_L(self.body_weight_kg)
        # Split blood between an arterial and a venous pool. The 1:2 split is a
        # conventional approximation, declared as an assumption.
        self._v_art = self._v_blood / 3.0
        self._v_ven = self._v_blood * 2.0 / 3.0

        self._idx = {t: _TISSUE_OFFSET + i for i, t in enumerate(self._tissues)}
        self._eliminated_idx = _TISSUE_OFFSET + len(self._tissues)
        self._bp = self.drug.blood_plasma_ratio
        self._fu_p = self.drug.fraction_unbound_plasma

        self.assumptions = list(self.assumptions) + [
            "Blood volume is split 1:2 between arterial and venous pools."
        ]
        self.limitations = list(self.limitations) + list(self._partition.warnings)

    # ------------------------------------------------------------------ states
    @property
    def state_names(self) -> list[str]:
        names = ["A_depot_mg", "A_arterial_blood_mg", "A_venous_blood_mg"]
        names += [f"A_{t.replace(' ', '_')}_mg" for t in self._tissues]
        names.append("A_eliminated_mg")
        return names

    def eliminated_state_index(self) -> int | None:
        return self._eliminated_idx

    @property
    def observable_units(self) -> dict[str, str]:
        u = {
            "plasma_concentration": "mg/L",
            "arterial_blood_concentration": "mg/L",
            "venous_blood_concentration": "mg/L",
            "amount_eliminated": "mg",
        }
        for t in self._tissues:
            u[f"C_{t.replace(' ', '_')}"] = "mg/L"
        return u

    # ------------------------------------------------------------ derivatives
    def _venous_out(self, tissue: str, amount_mg: float) -> float:
        """Blood concentration leaving a tissue: C_t * BP / Kp_t."""
        c_t = amount_mg / self._vol[tissue]
        return c_t * self._bp / self._kp[tissue]

    def rhs(self, t: float, y: np.ndarray, infusion_rate: np.ndarray) -> np.ndarray:
        d = np.zeros_like(y)
        ka = self.ka_per_h or 0.0
        f = self.bioavailability

        # ---- absorption depot -> liver (first pass through the portal vein)
        out_depot = ka * y[_DEPOT]
        d[_DEPOT] = infusion_rate[_DEPOT] - out_depot
        absorbed = f * out_depot

        c_art = y[_ARTERIAL] / self._v_art
        c_ven = y[_VENOUS] / self._v_ven

        # ---- lung sits between the venous pool and the arterial pool
        qc = self._cardiac_output_L_per_h
        c_lung_out = self._venous_out("lung", y[self._idx["lung"]])
        d[self._idx["lung"]] = qc * (c_ven - c_lung_out)

        # ---- arterial pool: fed by the lung, drained by every perfused tissue
        art_drain = 0.0
        for tissue in self._perfused:
            art_drain += self._flow[tissue]
        d[_ARTERIAL] = qc * c_lung_out - art_drain * c_art

        # ---- ordinary systemic tissues
        venous_return = 0.0
        for tissue in self._systemic:
            q = self._flow[tissue]
            c_out = self._venous_out(tissue, y[self._idx[tissue]])
            d[self._idx[tissue]] = q * (c_art - c_out)
            venous_return += q * c_out

        # ---- portal tissues drain into the liver, not the vena cava
        portal_in = 0.0
        for tissue in self._portal:
            q = self._flow[tissue]
            c_out = self._venous_out(tissue, y[self._idx[tissue]])
            d[self._idx[tissue]] = q * (c_art - c_out)
            portal_in += q * c_out

        # ---- liver: hepatic artery + portal inflow + oral absorption, minus
        #      outflow and hepatic metabolism
        li = self._idx["liver"]
        c_li_out = self._venous_out("liver", y[li])
        c_li_plasma_equiv = (y[li] / self._vol["liver"]) / self._kp["liver"]
        hepatic_elim = self.hepatic_intrinsic_clearance_L_per_h * self._fu_p * c_li_plasma_equiv
        d[li] = (
            self._q_hepatic_artery * c_art
            + portal_in
            + absorbed
            - self._q_liver_total * c_li_out
            - hepatic_elim
        )
        venous_return += self._q_liver_total * c_li_out

        # ---- kidney elimination, applied on top of its perfusion balance
        ki = self._idx["kidney"]
        c_ki_plasma_equiv = (y[ki] / self._vol["kidney"]) / self._kp["kidney"]
        renal_elim = self.renal_clearance_L_per_h * c_ki_plasma_equiv
        d[ki] -= renal_elim

        # ---- venous pool
        d[_VENOUS] = infusion_rate[_VENOUS] + venous_return - qc * c_ven

        # ---- bookkeeping: everything that left the system
        d[self._eliminated_idx] = hepatic_elim + renal_elim + (1.0 - f) * out_depot
        return d

    def observables(self, t: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
        c_ven_blood = y[_VENOUS] / self._v_ven
        out: dict[str, np.ndarray] = {
            # What a venous blood draw would report, converted to plasma.
            "plasma_concentration": c_ven_blood / self._bp,
            "arterial_blood_concentration": y[_ARTERIAL] / self._v_art,
            "venous_blood_concentration": c_ven_blood,
            "amount_eliminated": y[self._eliminated_idx],
        }
        for tissue in self._tissues:
            out[f"C_{tissue.replace(' ', '_')}"] = y[self._idx[tissue]] / self._vol[tissue]
        return out

    def preferred_method(self) -> str | None:
        # Blood pools turn over in seconds while adipose takes hours: stiff.
        return "BDF"

    # -------------------------------------------------------------- reporting
    @property
    def cardiac_output_L_per_h(self) -> float:
        return self._cardiac_output_L_per_h

    @property
    def partition_coefficients(self) -> dict[str, float]:
        return dict(self._kp)

    @property
    def tissue_volumes_L(self) -> dict[str, float]:
        return dict(self._vol)

    @property
    def tissue_flows_L_per_h(self) -> dict[str, float]:
        return dict(self._flow)

    def predicted_vss_L(self) -> float:
        """Analytic Vss from partition coefficients, independent of the ODE run."""
        return (
            steady_state_volume_of_distribution_L_per_kg(self.drug, self._partition, self._phys)
            * self.body_weight_kg
        )

    def hepatic_blood_clearance_L_per_h(self) -> float:
        """Well-stirred hepatic blood clearance implied by CLint.

            CL_H = Q_H * fu_b * CLint / (Q_H + fu_b * CLint),  fu_b = fu_p / BP
        """
        clint = self.hepatic_intrinsic_clearance_L_per_h
        if clint <= 0:
            return 0.0
        qh = self._q_liver_total
        fu_b = self._fu_p / self._bp
        return qh * fu_b * clint / (qh + fu_b * clint)

    def total_plasma_clearance_L_per_h(self) -> float:
        return self.hepatic_blood_clearance_L_per_h() * self._bp + self.renal_clearance_L_per_h

    def parameter_records(self) -> list[ParameterRecord]:
        recs = [
            ParameterRecord(
                "BW", self.body_weight_kg, "", ParameterOrigin.USER, "Body weight in kg."
            ),
            ParameterRecord(
                "logP", self.drug.log_p, "", ParameterOrigin.USER,
                "Octanol:water partition coefficient of the neutral species (log10).",
            ),
            ParameterRecord(
                "fu_p", self.drug.fraction_unbound_plasma, "fraction", ParameterOrigin.USER,
                "Fraction unbound in plasma.",
            ),
            ParameterRecord(
                "BP", self.drug.blood_plasma_ratio, "ratio", ParameterOrigin.USER,
                "Blood:plasma concentration ratio.",
            ),
            ParameterRecord(
                "CLint_H", self.hepatic_intrinsic_clearance_L_per_h, "L/h", ParameterOrigin.USER,
                "Hepatic intrinsic clearance on unbound drug.",
            ),
            ParameterRecord(
                "CL_R", self.renal_clearance_L_per_h, "L/h", ParameterOrigin.USER,
                "Renal plasma clearance.",
            ),
            ParameterRecord(
                "Q_cardiac", self._cardiac_output_L_per_h, "L/h", ParameterOrigin.DERIVED,
                "Sum of modelled tissue perfusion, used as cardiac output so flow balances.",
                reference_ids=["davies1993", "pearce2017"],
            ),
            ParameterRecord(
                "V_blood", self._v_blood, "L", ParameterOrigin.DERIVED,
                "Plasma volume divided by (1 - haematocrit).",
                reference_ids=["pearce2017"],
            ),
            ParameterRecord(
                "CL_H_blood", self.hepatic_blood_clearance_L_per_h(), "L/h",
                ParameterOrigin.DERIVED, "Well-stirred hepatic blood clearance implied by CLint.",
            ),
            ParameterRecord(
                "Vss_predicted", self.predicted_vss_L(), "L", ParameterOrigin.DERIVED,
                "Steady-state volume of distribution from predicted partition coefficients.",
                reference_ids=["poulin2002"],
            ),
            ParameterRecord(
                "fu_tissue", self._partition.fu_tissue_non_adipose, "fraction",
                ParameterOrigin.DERIVED,
                "Poulin-Theil non-adipose tissue unbound fraction approximation.",
                reference_ids=["poulin2002"],
            ),
        ]
        for tissue in self._tissues:
            recs.append(
                ParameterRecord(
                    f"Kp_{tissue.replace(' ', '_')}", self._kp[tissue], "ratio",
                    ParameterOrigin.DERIVED,
                    f"Predicted {tissue} to plasma partition coefficient.",
                    reference_ids=["poulin2002", "schmitt2008"],
                )
            )
            recs.append(
                ParameterRecord(
                    f"V_{tissue.replace(' ', '_')}", self._vol[tissue], "L",
                    ParameterOrigin.MEASURED,
                    f"{tissue} volume from the reference physiology dataset.",
                    reference_ids=["ilsi1994", "pearce2017"],
                )
            )
            recs.append(
                ParameterRecord(
                    f"Q_{tissue.replace(' ', '_')}", self._flow[tissue], "L/h",
                    ParameterOrigin.MEASURED,
                    f"{tissue} perfusion from the reference physiology dataset.",
                    reference_ids=["davies1993", "pearce2017"],
                )
            )
        return recs
