"""
Tests for the GI absorption model and the benchmark harness.

The absorption model cannot be validated against observed data for poorly
soluble drugs (the dataset that would do that is paywalled), so these tests
verify the next best thing: that it reproduces every limiting behaviour an
absorption model must have, and that its numerics are sound.

The benchmark tests exist mainly to protect the integrity guard — the property
that SYNTHBODY refuses to emit a head-to-head comparison it cannot support.
"""
from __future__ import annotations

import numpy as np
import pytest

from synthbody.engine.analysis.benchmark import (
    PUBLISHED_RESULTS,
    aafe,
    afe,
    compare_against_published,
    fold_error_summary,
    fold_errors,
    load_orbito_cases,
    run_theophylline_apriori,
)
from synthbody.engine.core import simulate
from synthbody.engine.models.absorption import (
    CompartmentalAbsorption,
    OralAbsorptionWithDisposition,
    OralDrugInput,
    load_gi_tract,
)
from synthbody.engine.provenance import ValidationStatus


# ===========================================================================
# Physiology
# ===========================================================================
def test_gi_physiology_loads_and_is_plausible():
    t = load_gi_tract()
    assert t.n_si == 7
    # Gastric half-emptying of ~16 min fasted -> Kge around 2.6 /h
    assert 2.0 < t.gastric_emptying_rate_per_h < 4.0
    # 192 min across 7 compartments -> Kt around 2.2 /h
    assert 1.5 < t.si_transit_rate_per_h < 3.0
    assert len(t.si_ph) == 7 and len(t.si_bile_salt_mM) == 7
    # pH must rise monotonically from duodenum to ileum
    assert all(t.si_ph[i] <= t.si_ph[i + 1] for i in range(6))
    assert 1.0 <= t.stomach_ph <= 3.0
    assert 6.0 <= t.si_ph[0] <= 7.0
    assert 6.5 <= t.si_ph[-1] <= 8.0


def test_gi_physiology_declares_its_provenance():
    from synthbody.engine.models.absorption import gi_provenance

    p = gi_provenance()
    assert p["primary_source"]["pmid"] == "20822152"
    assert p["primary_source"]["open_access"] is True
    assert "PMC3025274" in p["primary_source"]["pmc"]
    # The fed state must be declared absent, not silently approximated.
    assert "fed state is NOT implemented" in p["honest_caveat"]


def test_small_intestinal_transit_corroborated_by_independent_source():
    """Mudie (192 min) and httk (199.2 min) agree to within ~4%."""
    from synthbody.engine.physiology.reference_man import load_reference_physiology

    t = load_gi_tract()
    httk = load_reference_physiology().raw["whole_body"]["Small Intestine Mean Residence Time"]["human"]
    assert abs(t.si_transit_total_min - httk) / httk < 0.10


# ===========================================================================
# Solubility
# ===========================================================================
def test_henderson_hasselbalch_acid_and_base():
    acid = OralDrugInput(intrinsic_solubility_mg_per_mL=0.01, effective_permeability_cm_per_s=3e-4,
                         pka_acidic=4.5)
    base = OralDrugInput(intrinsic_solubility_mg_per_mL=0.01, effective_permeability_cm_per_s=3e-4,
                         pka_basic=8.0)
    # An acid is more soluble as pH rises; a base is more soluble as pH falls.
    assert acid.solubility_at(6.8) > acid.solubility_at(1.7)
    assert base.solubility_at(1.7) > base.solubility_at(6.8)
    # At pH == pKa solubility is exactly twice intrinsic.
    assert acid.solubility_at(4.5) == pytest.approx(0.02, rel=1e-9)
    assert base.solubility_at(8.0) == pytest.approx(0.02, rel=1e-9)


def test_solubility_ratio_is_capped():
    """Henderson-Hasselbalch must not run away many decades from the pKa."""
    acid = OralDrugInput(intrinsic_solubility_mg_per_mL=0.01, effective_permeability_cm_per_s=3e-4,
                         pka_acidic=2.0, max_solubility_ratio=1e3)
    assert acid.solubility_at(12.0) == pytest.approx(0.01 * 1e3, rel=1e-9)


def test_neutral_compound_solubility_is_ph_independent():
    d = OralDrugInput(intrinsic_solubility_mg_per_mL=0.05, effective_permeability_cm_per_s=3e-4)
    assert d.solubility_at(1.7) == pytest.approx(d.solubility_at(7.2))


def test_absorption_input_validation():
    with pytest.raises(ValueError):
        OralDrugInput(intrinsic_solubility_mg_per_mL=0.0, effective_permeability_cm_per_s=3e-4)
    with pytest.raises(ValueError):
        OralDrugInput(intrinsic_solubility_mg_per_mL=1.0, effective_permeability_cm_per_s=0.0)
    with pytest.raises(ValueError):
        OralDrugInput(intrinsic_solubility_mg_per_mL=1.0, effective_permeability_cm_per_s=3e-4,
                      particle_radius_um=0.0)


# ===========================================================================
# The absorption model
# ===========================================================================
def _fabs(drug: OralDrugInput, dose: float, hours: float = 30.0, npts: int = 301):
    m = CompartmentalAbsorption(drug=drug)
    y0 = m.initial_state_for_dose(dose)
    res = simulate(m, t_end_h=hours, output_times_h=np.linspace(0, hours, npts),
                   initial_state=y0, rtol=1e-8, atol=1e-11, check_tolerance_refinement=False)
    return float(res.observable("fraction_absorbed")[-1]), m.mass_balance_error(res.states[:, -1])


def test_mass_balance_closes_across_a_wide_sweep():
    worst = 0.0
    for s in (1e-4, 1e-2, 1.0, 50.0):
        for peff in (1e-6, 1e-4, 5e-4):
            for dose in (10.0, 500.0):
                _, mb = _fabs(
                    OralDrugInput(intrinsic_solubility_mg_per_mL=s,
                                  effective_permeability_cm_per_s=peff,
                                  particle_radius_um=25.0),
                    dose, hours=30.0, npts=121,
                )
                worst = max(worst, mb)
    assert worst < 1e-9, f"worst GI mass-balance error {worst:.3e}"


def test_fraction_absorbed_is_bounded():
    for s in (1e-4, 1.0, 50.0):
        for peff in (1e-6, 5e-4):
            f, _ = _fabs(OralDrugInput(intrinsic_solubility_mg_per_mL=s,
                                       effective_permeability_cm_per_s=peff), 100.0, npts=121)
            assert -1e-9 <= f <= 1.0 + 1e-9


def test_highly_soluble_and_permeable_drug_is_essentially_fully_absorbed():
    f, _ = _fabs(OralDrugInput(intrinsic_solubility_mg_per_mL=50.0,
                               effective_permeability_cm_per_s=5e-4,
                               particle_radius_um=5.0), 100.0)
    assert f > 0.95, f"BCS class I compound should be near-completely absorbed, got {f:.4f}"


def test_fraction_absorbed_falls_monotonically_with_permeability():
    prev = None
    for peff in (5e-4, 1e-4, 3e-5, 1e-5, 3e-6):
        f, _ = _fabs(OralDrugInput(intrinsic_solubility_mg_per_mL=50.0,
                                   effective_permeability_cm_per_s=peff,
                                   particle_radius_um=5.0), 100.0)
        if prev is not None:
            assert f <= prev + 1e-9, "fabs must not rise as permeability falls"
        prev = f
    assert prev < 0.2, "a very low-permeability drug should be poorly absorbed"


def test_solubility_limited_drug_shows_dose_dependent_fraction_absorbed():
    """The defining signature of solubility limitation: fabs falls as dose rises."""
    prev = None
    for dose in (1.0, 10.0, 50.0, 200.0, 800.0):
        f, _ = _fabs(OralDrugInput(intrinsic_solubility_mg_per_mL=0.005,
                                   effective_permeability_cm_per_s=3e-4,
                                   particle_radius_um=25.0), dose)
        if prev is not None:
            assert f <= prev + 1e-6, "fabs must fall with dose under solubility limitation"
        prev = f


def test_high_solubility_drug_shows_dose_proportional_absorption():
    """Contrast case: a freely soluble drug must NOT show dose-dependent fabs."""
    f_low, _ = _fabs(OralDrugInput(intrinsic_solubility_mg_per_mL=50.0,
                                   effective_permeability_cm_per_s=3e-4,
                                   particle_radius_um=10.0), 10.0)
    f_high, _ = _fabs(OralDrugInput(intrinsic_solubility_mg_per_mL=50.0,
                                    effective_permeability_cm_per_s=3e-4,
                                    particle_radius_um=10.0), 500.0)
    assert abs(f_low - f_high) < 0.02


def test_smaller_particles_increase_absorption():
    prev = None
    for r_um in (100.0, 50.0, 25.0, 10.0, 2.0):
        f, _ = _fabs(OralDrugInput(intrinsic_solubility_mg_per_mL=0.01,
                                   effective_permeability_cm_per_s=3e-4,
                                   particle_radius_um=r_um), 200.0)
        if prev is not None:
            assert f >= prev - 1e-6, "smaller particles must not absorb less"
        prev = f


def test_solution_dose_absorbs_at_least_as_well_as_solid():
    kw = dict(intrinsic_solubility_mg_per_mL=0.01, effective_permeability_cm_per_s=3e-4,
              particle_radius_um=25.0)
    f_sol, _ = _fabs(OralDrugInput(is_solution=True, **kw), 100.0)
    f_solid, _ = _fabs(OralDrugInput(**kw), 100.0)
    assert f_sol >= f_solid - 1e-9
    assert f_sol > f_solid, "a solution should beat a poorly soluble solid"


def test_particle_radius_is_global_not_per_compartment():
    """Radius must come from total solid in the tract, not one compartment's mass.

    If radius were inferred per compartment, a compartment holding a tenth of
    the dose would be treated as holding particles at a tenth of the volume,
    which would wrongly accelerate dissolution downstream.
    """
    m = CompartmentalAbsorption(
        drug=OralDrugInput(intrinsic_solubility_mg_per_mL=0.01,
                           effective_permeability_cm_per_s=3e-4, particle_radius_um=25.0)
    )
    m.set_dose(100.0)
    r_full = m._current_radius_cm(100.0)
    r_half = m._current_radius_cm(50.0)
    assert r_full == pytest.approx(25.0e-4, rel=1e-9)
    assert r_half == pytest.approx(25.0e-4 * 0.5 ** (1 / 3), rel=1e-6)


def test_dissolution_rate_is_zero_when_saturated():
    m = CompartmentalAbsorption(
        drug=OralDrugInput(intrinsic_solubility_mg_per_mL=0.01,
                           effective_permeability_cm_per_s=3e-4)
    )
    m.set_dose(100.0)
    r = m._current_radius_cm(100.0)
    # dissolved concentration already at saturation -> no further dissolution
    cs = 10.0  # mg/L
    assert m._dissolution_rate(50.0, cs * 0.015, 0.015, cs, r) == 0.0


def test_absorption_model_declares_research_only():
    """Guard against someone quietly upgrading this claim."""
    m = CompartmentalAbsorption(
        drug=OralDrugInput(intrinsic_solubility_mg_per_mL=1.0, effective_permeability_cm_per_s=3e-4)
    )
    assert m.validation_status is ValidationStatus.RESEARCH_ONLY
    assert any("RESEARCH ONLY" in x.upper() for x in m.limitations)
    assert any("fraction ABSORBED, not bioavailability" in x for x in m.limitations)
    assert "26926043" in m.validation_summary or "paywalled" in m.validation_summary


# ===========================================================================
# Absorption coupled to disposition
# ===========================================================================
def test_coupled_model_conserves_and_produces_a_profile():
    drug = OralDrugInput(intrinsic_solubility_mg_per_mL=7.36,
                         effective_permeability_cm_per_s=3e-4, pka_acidic=8.81)
    model = OralAbsorptionWithDisposition(
        absorption=CompartmentalAbsorption(drug=drug), cl_L_per_h=2.65, v_central_L=32.1
    )
    y0 = model.initial_state_for_dose(300.0)
    res = simulate(model, t_end_h=25.0, output_times_h=np.linspace(0, 25, 251),
                   initial_state=y0, rtol=1e-8, atol=1e-11, check_tolerance_refinement=False)
    c = res.observable("plasma_concentration")
    assert np.all(c >= -1e-9)
    assert c.max() > 0
    assert c[0] == pytest.approx(0.0, abs=1e-12), "oral dose must start at zero concentration"
    # Peak must be interior, not at either end.
    assert 0 < int(np.argmax(c)) < len(c) - 1


def test_first_pass_reduces_exposure_without_changing_fraction_absorbed():
    drug = OralDrugInput(intrinsic_solubility_mg_per_mL=7.36,
                         effective_permeability_cm_per_s=3e-4)

    def peak_and_fabs(fh: float):
        m = OralAbsorptionWithDisposition(
            absorption=CompartmentalAbsorption(drug=drug),
            cl_L_per_h=2.65, v_central_L=32.1, f_hepatic=fh,
        )
        y0 = m.initial_state_for_dose(300.0)
        r = simulate(m, t_end_h=25.0, output_times_h=np.linspace(0, 25, 251),
                     initial_state=y0, rtol=1e-8, atol=1e-11,
                     check_tolerance_refinement=False)
        return float(r.observable("plasma_concentration").max()), float(
            r.observable("fraction_absorbed")[-1]
        )

    c_full, f_full = peak_and_fabs(1.0)
    c_half, f_half = peak_and_fabs(0.5)
    assert c_half == pytest.approx(c_full * 0.5, rel=1e-3)
    # First-pass extraction must NOT change how much was absorbed from the gut.
    assert f_half == pytest.approx(f_full, rel=1e-6)


def test_coupled_model_rejects_inconsistent_two_compartment_spec():
    drug = OralDrugInput(intrinsic_solubility_mg_per_mL=1.0, effective_permeability_cm_per_s=3e-4)
    with pytest.raises(ValueError, match="together"):
        OralAbsorptionWithDisposition(
            absorption=CompartmentalAbsorption(drug=drug),
            cl_L_per_h=2.0, v_central_L=30.0, q_L_per_h=5.0,
        )


# ===========================================================================
# Benchmark metric definitions
# ===========================================================================
def test_aafe_and_afe_definitions():
    obs = np.array([10.0, 10.0, 10.0, 10.0])
    # Alternating 2x over and 2x under: unbiased (AFE 1) but imprecise (AAFE 2).
    pred = np.array([20.0, 5.0, 20.0, 5.0])
    assert afe(pred, obs) == pytest.approx(1.0, rel=1e-9)
    assert aafe(pred, obs) == pytest.approx(2.0, rel=1e-9)
    # Perfect prediction
    assert aafe(obs, obs) == pytest.approx(1.0)
    assert afe(obs, obs) == pytest.approx(1.0)
    # Systematic 2-fold over-prediction: both equal 2
    assert aafe(obs * 2, obs) == pytest.approx(2.0, rel=1e-9)
    assert afe(obs * 2, obs) == pytest.approx(2.0, rel=1e-9)


def test_fold_errors_exclude_nonpositive_pairs():
    r = fold_errors(np.array([1.0, 2.0, 0.0]), np.array([1.0, 1.0, 1.0]))
    assert r.size == 2


def test_fold_errors_rejects_all_invalid():
    with pytest.raises(ValueError):
        fold_errors(np.array([0.0, -1.0]), np.array([1.0, 1.0]))


def test_fold_error_summary_is_symmetric():
    s = fold_error_summary(np.array([20.0, 5.0]), np.array([10.0, 10.0]))
    assert s["median_fold_error"] == pytest.approx(2.0)
    assert s["max_fold_error"] == pytest.approx(2.0)
    assert s["fraction_within_2_fold"] == pytest.approx(1.0)
    assert s["fraction_over_2_fold_error"] == pytest.approx(0.0)


# ===========================================================================
# The integrity guard
# ===========================================================================
def test_orbito_case_library_ships_empty():
    cases, meta = load_orbito_cases()
    assert cases == []
    assert meta["status"] == "empty"


def test_head_to_head_comparison_is_refused_without_data():
    """The central integrity property of this module.

    With no obtainable inputs or observations there must be NO code path that
    produces a comparison table. A fabricated benchmark is the single worst
    thing this product could emit.
    """
    c = compare_against_published()
    assert c["comparison_available"] is False
    assert "refusal_reason" in c
    assert "paywalled" in c["refusal_reason"]
    assert "synthbody_results" not in c
    assert c["what_would_be_needed"]
    # The published figures must still be recorded, clearly as recorded values.
    assert c["published_results"] == PUBLISHED_RESULTS
    assert "does not use these numbers in any computation" in c["published_results_provenance"]


def test_access_record_documents_why_data_is_unavailable():
    c = compare_against_published()
    rec = c["access_record"]
    assert rec["pmid"] == "26926043"
    assert "closed" in rec["unpaywall"]
    assert "403" in rec["acs_supporting_information"]


def test_published_competitor_numbers_are_recorded_not_computed():
    assert PUBLISHED_RESULTS["GI-Sim 4.1"]["auc"] == 1.3
    assert PUBLISHED_RESULTS["Simcyp 13.1"]["cmax"] == 2.2
    assert PUBLISHED_RESULTS["GastroPlus 8.0"]["tmax"] == 1.5


# ===========================================================================
# The executable benchmark
# ===========================================================================
@pytest.fixture(scope="module")
def theoph_benchmark():
    return run_theophylline_apriori(peff_sweep=(2.0e-4, 3.0e-4, 5.0e-4))


def test_theophylline_benchmark_runs_on_held_out_subjects(theoph_benchmark):
    r = theoph_benchmark
    assert r["held_out_subject_ids"] == ["2", "4", "6", "8", "10", "12"]
    assert set(r["held_out_subject_ids"]).isdisjoint(set(r["calibration_subject_ids"]))
    assert r["headline_result"] is not None


def test_theophylline_predicted_as_essentially_completely_absorbed(theoph_benchmark):
    """Theophylline is a BCS Class I drug and is completely absorbed in vivo.

    The absorption model is given only solubility, pKa and permeability — never
    the observed profiles — so recovering fabs near 1 is a genuine a-priori result.
    """
    h = theoph_benchmark["headline_result"]
    assert h["mean_predicted_fabs"] > 0.90, h["mean_predicted_fabs"]


def test_theophylline_benchmark_accuracy_is_pinned(theoph_benchmark):
    """Regression bounds on the achieved a-priori accuracy.

    Deliberately loose enough to tolerate solver noise, tight enough to catch a
    real regression. These record what was achieved; they are not targets.
    """
    m = theoph_benchmark["headline_result"]["evaluation"]["metrics"]
    assert m["cmax"]["n"] == 6
    assert m["cmax"]["aafe"] < 1.30, m["cmax"]["aafe"]
    assert m["auc"]["aafe"] < 1.40, m["auc"]["aafe"]
    # tmax is the weak metric: population-mean gastric emptying cannot capture
    # between-subject variability in how fast the stomach empties.
    assert m["tmax"]["aafe"] < 2.20, m["tmax"]["aafe"]


def test_headline_uses_prespecified_permeability_not_the_best(theoph_benchmark):
    """Selecting the best sweep point would be selection on the outcome."""
    r = theoph_benchmark
    assert r["headline_result"]["peff_cm_per_s"] == pytest.approx(r["prespecified_peff_cm_per_s"])
    assert "post-hoc" in r["headline_note"]


def test_benchmark_declares_it_is_not_comparable_to_the_published_study(theoph_benchmark):
    scope = theoph_benchmark["honest_scope"]
    assert "NOT comparable" in scope
    assert "INCOMPLETE absorption" in scope


def test_permeability_sweep_is_reported_because_peff_is_inferred(theoph_benchmark):
    """An inferred input must have its sensitivity shown, not hidden."""
    r = theoph_benchmark
    assert len(r["peff_sweep"]) >= 3
    assert r["physchem"]["effective_permeability_cm_per_s"]["origin"] == "inferred"
    fabs = [s["mean_predicted_fabs"] for s in r["peff_sweep"]]
    assert fabs == sorted(fabs), "fabs must rise with permeability across the sweep"
