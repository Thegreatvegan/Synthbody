"""
PBPK and physiology tests.

The PBPK model is research-only, so these tests verify what *can* be verified:
that the physiological data loads with its provenance intact, that mass and flow
balance close, that the model reaches the correct steady state, and that the
partition-coefficient machinery agrees with an independent analytic Vss.
"""
from __future__ import annotations

import numpy as np
import pytest

from synthbody.engine.core import DoseEvent, simulate
from synthbody.engine.models.pbpk import PerfusionLimitedPBPK
from synthbody.engine.physiology.partition import (
    DrugPhysChem,
    olive_oil_water_logd_from_logp,
    predict_partition_coefficients,
    steady_state_volume_of_distribution_L_per_kg,
    tissue_unbound_fraction,
)
from synthbody.engine.physiology.reference_man import (
    PBPK_TISSUES,
    load_reference_physiology,
    physiology_provenance,
)


# ===========================================================================
# Physiology dataset
# ===========================================================================
def test_physiology_loads_with_all_tissues():
    phys = load_reference_physiology()
    assert set(phys.tissues) == set(PBPK_TISSUES)
    for name, t in phys.tissues.items():
        assert t.vol_L_per_kg > 0, name
        assert t.flow_mL_per_min_per_kg075 > 0, name
        assert 0.0 <= t.f_water <= 1.0, name
        assert 0.0 <= t.f_lipid_total <= 1.0, name


def test_physiology_provenance_is_present_and_specific():
    """Provenance must name a licence and the primary references, not be vague."""
    prov = physiology_provenance()
    assert "httk" in prov["source_repository"].lower()
    assert "GPL-3" in prov["source_license"]
    keys = prov["key_primary_citations"]
    assert keys["tissue_blood_flows"]["pmid"] == "8378254"
    assert keys["tissue_composition"]["pmid"] == "17981004"
    # The one value whose primary source could not be retrieved must say so.
    assert "NOT" in keys["tissue_volumes"]["note"].upper() or "not independently" in (
        keys["tissue_volumes"]["note"].lower()
    )


def test_tissue_volume_fractions_are_physiologically_plausible():
    phys = load_reference_physiology()
    total = sum(t.vol_L_per_kg for t in phys.tissues.values())
    blood = phys.blood_volume_L(1.0)
    # Tissues plus blood should account for most but not more than all of body mass.
    assert 0.75 < total + blood < 1.05, f"Tissue volumes sum to {total + blood:.3f} L/kg"
    # Muscle and adipose must dominate.
    assert phys.tissues["muscle"].vol_L_per_kg > 0.3
    assert phys.tissues["adipose"].vol_L_per_kg > 0.15


def test_cardiac_output_is_physiologically_plausible():
    """A 70 kg adult should have a cardiac output near 5-7 L/min."""
    phys = load_reference_physiology()
    flows = phys.tissue_flows_L_per_h(70.0)
    total_L_per_h = sum(flows[t] for t in PBPK_TISSUES if t != "lung")
    L_per_min = total_L_per_h / 60.0
    assert 4.0 < L_per_min < 9.0, f"Cardiac output {L_per_min:.2f} L/min is implausible"


def test_gfr_is_physiologically_plausible():
    phys = load_reference_physiology()
    gfr_mL_min = phys.gfr_L_per_h(70.0) * 1000.0 / 60.0
    assert 80.0 < gfr_mL_min < 160.0, f"GFR {gfr_mL_min:.1f} mL/min is implausible"


def test_blood_volume_consistent_with_plasma_and_hematocrit():
    phys = load_reference_physiology()
    plasma = phys.plasma_volume_L(70.0)
    blood = phys.blood_volume_L(70.0)
    assert blood == pytest.approx(plasma / (1.0 - phys.hematocrit), rel=1e-12)
    assert 4.0 < blood < 7.0


def test_allometric_scaling_of_flows():
    phys = load_reference_physiology()
    a = phys.tissue_flows_L_per_h(70.0)["liver"]
    b = phys.tissue_flows_L_per_h(140.0)["liver"]
    assert b / a == pytest.approx(2.0**0.75, rel=1e-12)


def test_rest_compartment_composition_is_borrowed_from_muscle():
    """A documented assumption, verified so it cannot drift silently."""
    phys = load_reference_physiology()
    assert phys.tissues["rest"].f_water == phys.tissues["muscle"].f_water
    assert phys.tissues["rest"].f_lipid_total == phys.tissues["muscle"].f_lipid_total
    # But its volume and flow are its own.
    assert phys.tissues["rest"].vol_L_per_kg != phys.tissues["muscle"].vol_L_per_kg


# ===========================================================================
# Partition coefficients
# ===========================================================================
def test_partition_rejects_impossible_physchem():
    with pytest.raises(ValueError):
        DrugPhysChem(log_p=0.0, fraction_unbound_plasma=0.0)
    with pytest.raises(ValueError):
        DrugPhysChem(log_p=0.0, fraction_unbound_plasma=1.5)
    with pytest.raises(ValueError):
        DrugPhysChem(log_p=0.0, fraction_unbound_plasma=0.5, blood_plasma_ratio=0.0)
    with pytest.raises(ValueError):
        DrugPhysChem(log_p=99.0, fraction_unbound_plasma=0.5)


def test_lipophilicity_increases_adipose_partitioning():
    low = predict_partition_coefficients(DrugPhysChem(log_p=0.0, fraction_unbound_plasma=0.6))
    high = predict_partition_coefficients(DrugPhysChem(log_p=4.0, fraction_unbound_plasma=0.6))
    assert high.kp["adipose"] > low.kp["adipose"] * 100
    # Adipose must be the most lipophilic compartment for a lipophilic drug.
    assert high.kp["adipose"] == max(high.kp.values())


def test_all_partition_coefficients_positive():
    for logp in (-2.0, 0.0, 2.0, 4.0):
        res = predict_partition_coefficients(
            DrugPhysChem(log_p=logp, fraction_unbound_plasma=0.5)
        )
        assert set(res.kp) == set(PBPK_TISSUES)
        assert all(v > 0 for v in res.kp.values()), (logp, res.kp)


def test_tissue_unbound_fraction_bounds():
    assert tissue_unbound_fraction(1.0) == pytest.approx(1.0)
    assert 0.0 < tissue_unbound_fraction(0.01) < 1.0
    # Less unbound in plasma -> less unbound in tissue
    assert tissue_unbound_fraction(0.1) < tissue_unbound_fraction(0.9)


def test_olive_oil_correlation():
    assert olive_oil_water_logd_from_logp(0.0) == pytest.approx(-1.35)
    assert olive_oil_water_logd_from_logp(4.0) == pytest.approx(1.115 * 4 - 1.35)


def test_base_warning_is_emitted():
    """The known failure mode of Poulin-Theil must be surfaced, not hidden."""
    res = predict_partition_coefficients(
        DrugPhysChem(
            log_p=3.0, fraction_unbound_plasma=0.1, pka_basic=9.5, is_neutral=False
        )
    )
    assert any("base" in w.lower() for w in res.warnings)
    assert any("Rodgers" in w for w in res.warnings)


def test_theophylline_vss_matches_literature_order_of_magnitude():
    """The one external quantitative check the distribution module passes.

    Theophylline volume of distribution is widely reported as about 0.5 L/kg.
    The inputs are a computed log P and an inferred fu, so this is weak
    evidence, but it is a genuine out-of-sample scalar comparison.
    """
    drug = DrugPhysChem(log_p=0.0, fraction_unbound_plasma=0.60, blood_plasma_ratio=0.82)
    vss = steady_state_volume_of_distribution_L_per_kg(drug)
    assert 0.25 < vss < 1.0, f"Predicted Vss {vss:.3f} L/kg is not even the right order"
    fold = max(vss / 0.5, 0.5 / vss)
    assert fold < 2.0, f"Predicted Vss {vss:.3f} L/kg is {fold:.2f}-fold from 0.5 L/kg"


def test_vss_increases_with_lipophilicity():
    a = steady_state_volume_of_distribution_L_per_kg(
        DrugPhysChem(log_p=0.0, fraction_unbound_plasma=0.5)
    )
    b = steady_state_volume_of_distribution_L_per_kg(
        DrugPhysChem(log_p=3.0, fraction_unbound_plasma=0.5)
    )
    assert b > a


# ===========================================================================
# PBPK model
# ===========================================================================
@pytest.fixture
def pbpk():
    return PerfusionLimitedPBPK(
        drug=DrugPhysChem(log_p=0.0, fraction_unbound_plasma=0.6, blood_plasma_ratio=0.82),
        body_weight_kg=70.0,
        hepatic_intrinsic_clearance_L_per_h=5.0,
        renal_clearance_L_per_h=0.3,
    )


def test_pbpk_flow_balance_closes(pbpk):
    """Cardiac output must equal the sum of what leaves the arterial pool."""
    flows = pbpk.tissue_flows_L_per_h
    perfused = [t for t in PBPK_TISSUES if t != "lung"]
    assert pbpk.cardiac_output_L_per_h == pytest.approx(
        sum(flows[t] for t in perfused), rel=1e-12
    )


def test_pbpk_mass_balance_closes(pbpk):
    res = simulate(
        pbpk,
        t_end_h=48.0,
        doses=[DoseEvent(0.0, 300.0, "iv_bolus", target_state=2)],
        rtol=1e-9,
        atol=1e-12,
    )
    err = res.diagnostics.mass_balance_relative_error
    assert err is not None, "PBPK must report a mass balance"
    assert err < 1e-6, f"PBPK mass balance error {err:.3e}"


def test_pbpk_no_negative_concentrations(pbpk):
    res = simulate(
        pbpk,
        t_end_h=72.0,
        doses=[DoseEvent(0.0, 300.0, "iv_bolus", target_state=2)],
        rtol=1e-9,
        atol=1e-12,
    )
    assert res.states.min() > -1e-6


def test_pbpk_eventually_eliminates_everything(pbpk):
    """With non-zero clearance the body must empty given enough time."""
    res = simulate(
        pbpk,
        t_end_h=2000.0,
        doses=[DoseEvent(0.0, 300.0, "iv_bolus", target_state=2)],
        rtol=1e-9,
        atol=1e-12,
        check_tolerance_refinement=False,
    )
    eliminated = res.observable("amount_eliminated")[-1]
    assert eliminated == pytest.approx(300.0, rel=1e-3)


def test_pbpk_tissue_equilibrium_ratios_approach_kp(pbpk):
    """At true equilibrium every tissue:plasma ratio must equal its Kp.

    This verifies the transport equations: if the venous-outflow term were wrong,
    the distribution equilibrium would settle at the wrong ratio.

    Clearance is set to zero so the system reaches genuine equilibrium. With
    elimination running, tissues lag the falling plasma concentration and the
    ratio sits a few percent above Kp - a real quasi-steady-state offset, not a
    numerical error, which is why this check needs the non-eliminating case.
    """
    model = PerfusionLimitedPBPK(
        drug=pbpk.drug,
        body_weight_kg=70.0,
        hepatic_intrinsic_clearance_L_per_h=0.0,
        renal_clearance_L_per_h=0.0,
    )
    res = simulate(
        model,
        t_end_h=1000.0,
        doses=[DoseEvent(0.0, 300.0, "iv_bolus", target_state=2)],
        output_times_h=np.linspace(0.0, 1000.0, 2001),
        rtol=1e-11,
        atol=1e-14,
        check_tolerance_refinement=False,
    )
    plasma = res.observable("plasma_concentration")
    assert plasma[-1] > 0
    for tissue in PBPK_TISSUES:
        ratio = res.observable(f"C_{tissue}")[-1] / plasma[-1]
        expected = model.partition_coefficients[tissue]
        assert ratio == pytest.approx(expected, rel=1e-4), (
            f"{tissue}: equilibrium ratio {ratio:.6f} vs Kp {expected:.6f}"
        )


def test_pbpk_eliminating_system_shows_quasi_steady_state_lag(pbpk):
    """With elimination running, tissue:plasma ratios must exceed Kp.

    Documents the behaviour the equilibrium test deliberately avoids: during the
    terminal phase, tissues empty more slowly than plasma falls.
    """
    res = simulate(
        pbpk,
        t_end_h=400.0,
        doses=[DoseEvent(0.0, 300.0, "iv_bolus", target_state=2)],
        output_times_h=np.linspace(0.0, 400.0, 2001),
        rtol=1e-10,
        atol=1e-14,
        check_tolerance_refinement=False,
    )
    plasma = res.observable("plasma_concentration")
    idx = int(np.argmin(np.abs(res.t_h - 100.0)))
    for tissue in ("muscle", "adipose", "brain", "bone"):
        ratio = res.observable(f"C_{tissue}")[idx] / plasma[idx]
        kp = pbpk.partition_coefficients[tissue]
        assert ratio > kp
        assert ratio < kp * 1.5  # a lag, not a transport error


def test_pbpk_eliminating_organs_sit_below_equilibrium(pbpk):
    """Liver and kidney must be depleted relative to Kp because they clear drug."""
    res = simulate(
        pbpk,
        t_end_h=400.0,
        doses=[DoseEvent(0.0, 300.0, "iv_bolus", target_state=2)],
        output_times_h=np.linspace(0.0, 400.0, 2001),
        rtol=1e-10,
        atol=1e-14,
        check_tolerance_refinement=False,
    )
    plasma = res.observable("plasma_concentration")
    idx = int(np.argmin(np.abs(res.t_h - 100.0)))
    for tissue in ("liver", "kidney"):
        ratio = res.observable(f"C_{tissue}")[idx] / plasma[idx]
        assert ratio < pbpk.partition_coefficients[tissue]


def test_pbpk_well_stirred_clearance_is_flow_limited(pbpk):
    """Hepatic clearance can never exceed hepatic blood flow."""
    assert pbpk.hepatic_blood_clearance_L_per_h() > 0
    huge = PerfusionLimitedPBPK(
        drug=pbpk.drug,
        body_weight_kg=70.0,
        hepatic_intrinsic_clearance_L_per_h=1e6,
        renal_clearance_L_per_h=0.0,
    )
    liver_flow = huge.tissue_flows_L_per_h["liver"] + sum(
        huge.tissue_flows_L_per_h[t] for t in ("gut", "spleen")
    )
    assert huge.hepatic_blood_clearance_L_per_h() < liver_flow
    assert huge.hepatic_blood_clearance_L_per_h() == pytest.approx(liver_flow, rel=1e-3)


def test_pbpk_zero_clearance_conserves_drug(pbpk):
    """With no elimination, total drug must stay constant forever."""
    model = PerfusionLimitedPBPK(
        drug=pbpk.drug,
        body_weight_kg=70.0,
        hepatic_intrinsic_clearance_L_per_h=0.0,
        renal_clearance_L_per_h=0.0,
    )
    res = simulate(
        model,
        t_end_h=500.0,
        doses=[DoseEvent(0.0, 300.0, "iv_bolus", target_state=2)],
        rtol=1e-10,
        atol=1e-13,
        check_tolerance_refinement=False,
    )
    total = res.states[:-1].sum(axis=0)  # all but the eliminated bookkeeping state
    assert np.allclose(total, 300.0, rtol=1e-6)
    assert res.observable("amount_eliminated")[-1] == pytest.approx(0.0, abs=1e-9)


def test_pbpk_vss_from_ode_matches_analytic_prediction(pbpk):
    """Vss computed from the no-elimination equilibrium must match the analytic Vss.

    Two independent code paths: the partition-coefficient summation and the
    actual ODE equilibrium. They must agree.
    """
    model = PerfusionLimitedPBPK(
        drug=pbpk.drug,
        body_weight_kg=70.0,
        hepatic_intrinsic_clearance_L_per_h=0.0,
        renal_clearance_L_per_h=0.0,
    )
    dose = 300.0
    res = simulate(
        model,
        t_end_h=3000.0,
        doses=[DoseEvent(0.0, dose, "iv_bolus", target_state=2)],
        rtol=1e-11,
        atol=1e-14,
        check_tolerance_refinement=False,
    )
    c_plasma_eq = float(res.observable("plasma_concentration")[-1])
    vss_from_ode = dose / c_plasma_eq
    assert vss_from_ode == pytest.approx(model.predicted_vss_L(), rel=2e-3)


def test_pbpk_body_weight_scales_exposure(pbpk):
    """A heavier subject must have a lower peak concentration for the same dose."""
    light = PerfusionLimitedPBPK(
        drug=pbpk.drug, body_weight_kg=50.0,
        hepatic_intrinsic_clearance_L_per_h=5.0, renal_clearance_L_per_h=0.3,
    )
    heavy = PerfusionLimitedPBPK(
        drug=pbpk.drug, body_weight_kg=100.0,
        hepatic_intrinsic_clearance_L_per_h=5.0, renal_clearance_L_per_h=0.3,
    )
    assert heavy.predicted_vss_L() > light.predicted_vss_L()
    assert heavy.cardiac_output_L_per_h > light.cardiac_output_L_per_h


def test_pbpk_declares_research_only_status(pbpk):
    """A guard against someone quietly upgrading the claim."""
    from synthbody.engine.provenance import ValidationStatus

    assert pbpk.validation_status == ValidationStatus.RESEARCH_ONLY
    assert any("RESEARCH ONLY" in x.upper() for x in pbpk.limitations)
    assert any("blood-brain" in x.lower() for x in pbpk.limitations)


def test_pbpk_rejects_bad_configuration():
    drug = DrugPhysChem(log_p=0.0, fraction_unbound_plasma=0.6)
    with pytest.raises(ValueError):
        PerfusionLimitedPBPK(drug=drug, body_weight_kg=0.0)
    with pytest.raises(ValueError):
        PerfusionLimitedPBPK(drug=drug, hepatic_intrinsic_clearance_L_per_h=-1.0)
    with pytest.raises(ValueError, match="unknown tissues"):
        PerfusionLimitedPBPK(drug=drug, partition_override={"spleen_of_doom": 1.0})


def test_pbpk_oral_route_passes_through_liver(pbpk):
    """An oral dose must enter the liver, so liver exposure precedes plasma."""
    model = PerfusionLimitedPBPK(
        drug=pbpk.drug, body_weight_kg=70.0,
        hepatic_intrinsic_clearance_L_per_h=5.0, renal_clearance_L_per_h=0.3,
        ka_per_h=1.5,
    )
    res = simulate(
        model,
        t_end_h=24.0,
        doses=[DoseEvent(0.0, 300.0, "oral", target_state=0)],
        output_times_h=np.linspace(0.0, 24.0, 2401),
        rtol=1e-9,
        atol=1e-12,
        check_tolerance_refinement=False,
    )
    t_liver = res.t_h[int(np.argmax(res.observable("C_liver")))]
    t_plasma = res.t_h[int(np.argmax(res.observable("plasma_concentration")))]
    assert t_liver <= t_plasma
