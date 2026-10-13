"""
Numerical verification of the simulation engine.

The central question these tests answer: does the ODE solver path produce the
same answer as the closed-form solution? If it does not, every downstream
number is suspect no matter how good the interface looks.
"""
from __future__ import annotations

import numpy as np
import pytest

from synthbody.engine.core import DoseEvent, expand_regimen, simulate
from synthbody.engine.models.compartmental import (
    OneCompartmentFirstOrderAbsorption,
    OneCompartmentMichaelisMenten,
    TwoCompartment,
)


# ===========================================================================
# One compartment, first-order absorption
# ===========================================================================
@pytest.fixture
def one_cmt():
    return OneCompartmentFirstOrderAbsorption(cl_L_per_h=2.8, v_L=34.0, ka_per_h=1.5)


def test_ode_matches_bateman_analytic(one_cmt):
    """The numerical solution must reproduce the Bateman function."""
    dose = 300.0
    grid = np.linspace(0.0, 48.0, 2001)
    res = simulate(
        one_cmt,
        t_end_h=48.0,
        doses=[DoseEvent(0.0, dose, "oral", target_state=0)],
        output_times_h=grid,
        rtol=1e-11,
        atol=1e-13,
    )
    numeric = res.observable("plasma_concentration")
    analytic = one_cmt.analytic_concentration(grid, dose)
    peak = float(np.max(analytic))
    assert peak > 0
    max_rel = float(np.max(np.abs(numeric - analytic)) / peak)
    assert max_rel < 1e-8, f"Solver deviates from analytic by {max_rel:.3e} of peak"


def test_mass_balance_closes(one_cmt):
    dose = 300.0
    res = simulate(
        one_cmt,
        t_end_h=72.0,
        doses=[DoseEvent(0.0, dose, "oral", target_state=0)],
    )
    err = res.diagnostics.mass_balance_relative_error
    assert err is not None
    assert err < 1e-10, f"Mass balance error {err:.3e}"
    assert not res.diagnostics.warnings


def test_no_negative_states(one_cmt):
    res = simulate(
        one_cmt, t_end_h=200.0, doses=[DoseEvent(0.0, 300.0, "oral", target_state=0)]
    )
    assert res.states.min() > -1e-9


def test_tolerance_refinement_reports_convergence(one_cmt):
    res = simulate(
        one_cmt,
        t_end_h=48.0,
        doses=[DoseEvent(0.0, 300.0, "oral", target_state=0)],
        rtol=1e-8,
        atol=1e-10,
        check_tolerance_refinement=True,
    )
    d = res.diagnostics.tolerance_refinement_max_rel_diff
    assert d is not None
    assert d < 1e-6, f"Not tolerance-converged: {d:.3e}"


def test_loose_tolerance_is_detected():
    """A deliberately sloppy tolerance must be flagged, not silently accepted."""
    model = OneCompartmentFirstOrderAbsorption(cl_L_per_h=2.8, v_L=34.0, ka_per_h=25.0)
    res = simulate(
        model,
        t_end_h=24.0,
        doses=[DoseEvent(0.0, 300.0, "oral", target_state=0)],
        method="RK45",
        rtol=1e-2,
        atol=1e-1,
        check_tolerance_refinement=True,
    )
    d = res.diagnostics.tolerance_refinement_max_rel_diff
    assert d is not None
    # Either it flagged a warning, or the refinement difference is measurable.
    assert d > 1e-6 or res.diagnostics.warnings


@pytest.mark.parametrize("method", ["LSODA", "BDF", "Radau", "RK45", "DOP853"])
def test_all_solvers_agree(one_cmt, method):
    dose = 300.0
    grid = np.linspace(0.0, 36.0, 361)
    res = simulate(
        one_cmt,
        t_end_h=36.0,
        doses=[DoseEvent(0.0, dose, "oral", target_state=0)],
        output_times_h=grid,
        method=method,
        rtol=1e-10,
        atol=1e-12,
        check_tolerance_refinement=False,
    )
    analytic = one_cmt.analytic_concentration(grid, dose)
    peak = float(np.max(analytic))
    assert float(np.max(np.abs(res.observable("plasma_concentration") - analytic)) / peak) < 1e-7


def test_ka_equals_ke_limiting_case():
    """ka == ke is a removable singularity in the Bateman form; it must not blow up."""
    cl, v = 2.0, 40.0
    ke = cl / v
    model = OneCompartmentFirstOrderAbsorption(cl_L_per_h=cl, v_L=v, ka_per_h=ke)
    grid = np.linspace(0.0, 100.0, 1001)
    res = simulate(
        model,
        t_end_h=100.0,
        doses=[DoseEvent(0.0, 100.0, "oral", target_state=0)],
        output_times_h=grid,
        rtol=1e-11,
        atol=1e-13,
    )
    analytic = model.analytic_concentration(grid, 100.0)
    assert np.all(np.isfinite(analytic))
    peak = float(np.max(analytic))
    assert float(np.max(np.abs(res.observable("plasma_concentration") - analytic)) / peak) < 1e-7


def test_superposition_holds_for_linear_model(one_cmt):
    """A linear model must satisfy superposition: two doses = sum of two single doses."""
    grid = np.linspace(0.0, 72.0, 721)
    kw = dict(t_end_h=72.0, output_times_h=grid, rtol=1e-11, atol=1e-13,
              check_tolerance_refinement=False)
    a = simulate(one_cmt, doses=[DoseEvent(0.0, 300.0, "oral", target_state=0)], **kw)
    b = simulate(one_cmt, doses=[DoseEvent(12.0, 300.0, "oral", target_state=0)], **kw)
    both = simulate(
        one_cmt,
        doses=[
            DoseEvent(0.0, 300.0, "oral", target_state=0),
            DoseEvent(12.0, 300.0, "oral", target_state=0),
        ],
        **kw,
    )
    summed = a.observable("plasma_concentration") + b.observable("plasma_concentration")
    peak = float(np.max(summed))
    assert float(np.max(np.abs(both.observable("plasma_concentration") - summed)) / peak) < 1e-8


def test_dose_proportionality_for_linear_model(one_cmt):
    grid = np.linspace(0.0, 48.0, 481)
    kw = dict(t_end_h=48.0, output_times_h=grid, check_tolerance_refinement=False,
              rtol=1e-11, atol=1e-13)
    low = simulate(one_cmt, doses=[DoseEvent(0.0, 100.0, "oral", target_state=0)], **kw)
    high = simulate(one_cmt, doses=[DoseEvent(0.0, 300.0, "oral", target_state=0)], **kw)
    ratio = high.observable("plasma_concentration")[1:] / low.observable("plasma_concentration")[1:]
    assert np.allclose(ratio, 3.0, rtol=1e-7)


def test_bioavailability_scales_exposure():
    full = OneCompartmentFirstOrderAbsorption(2.8, 34.0, 1.5, bioavailability=1.0)
    half = OneCompartmentFirstOrderAbsorption(2.8, 34.0, 1.5, bioavailability=0.5)
    grid = np.linspace(0.0, 48.0, 481)
    c_full = full.analytic_concentration(grid, 300.0)
    c_half = half.analytic_concentration(grid, 300.0)
    assert np.allclose(c_half[1:], 0.5 * c_full[1:], rtol=1e-12)


def test_first_pass_loss_is_accounted_in_mass_balance():
    """With F < 1 the unabsorbed fraction must still appear in the eliminated state."""
    model = OneCompartmentFirstOrderAbsorption(2.8, 34.0, 1.5, bioavailability=0.4)
    res = simulate(
        model, t_end_h=200.0, doses=[DoseEvent(0.0, 300.0, "oral", target_state=0)]
    )
    err = res.diagnostics.mass_balance_relative_error
    assert err is not None and err < 1e-9


# ===========================================================================
# Infusion
# ===========================================================================
def test_infusion_steady_state_matches_analytic():
    """Css = R0 / CL for a constant infusion."""
    cl, v = 3.0, 40.0
    model = OneCompartmentFirstOrderAbsorption(cl_L_per_h=cl, v_L=v, ka_per_h=1.0)
    rate = 10.0  # mg/h
    duration = 400.0
    res = simulate(
        model,
        t_end_h=duration,
        doses=[DoseEvent(0.0, rate * duration, "iv_infusion", duration_h=duration, target_state=1)],
        output_times_h=np.linspace(0.0, duration, 2001),
        rtol=1e-11,
        atol=1e-13,
    )
    css_expected = rate / cl
    css_actual = float(res.observable("plasma_concentration")[-1])
    assert css_actual == pytest.approx(css_expected, rel=1e-6)


def test_infusion_half_life_approach():
    """At one half-life into an infusion, concentration should be ~50% of Css."""
    cl, v = 3.0, 40.0
    model = OneCompartmentFirstOrderAbsorption(cl_L_per_h=cl, v_L=v, ka_per_h=1.0)
    t_half = model.half_life_h
    rate, duration = 10.0, t_half * 20
    res = simulate(
        model,
        t_end_h=duration,
        doses=[DoseEvent(0.0, rate * duration, "iv_infusion", duration_h=duration, target_state=1)],
        output_times_h=np.array([0.0, t_half, duration]),
        rtol=1e-11,
        atol=1e-13,
    )
    c = res.observable("plasma_concentration")
    assert c[1] / (rate / cl) == pytest.approx(0.5, abs=1e-6)


def test_infusion_mass_balance():
    """Mass balance error must track the requested solver tolerance.

    At the default rtol=1e-8 the balance closes to about 1e-8, which is the
    solver doing its job rather than a model error. Tightening the tolerance
    must tighten the balance, so the test asks for both.
    """
    model = OneCompartmentFirstOrderAbsorption(3.0, 40.0, 1.0)
    doses = [DoseEvent(2.0, 120.0, "iv_infusion", duration_h=4.0, target_state=1)]

    loose = simulate(model, t_end_h=24.0, doses=doses)
    assert loose.diagnostics.mass_balance_relative_error is not None
    assert loose.diagnostics.mass_balance_relative_error < 1e-6

    tight = simulate(model, t_end_h=24.0, doses=doses, rtol=1e-12, atol=1e-14)
    assert tight.diagnostics.mass_balance_relative_error < 1e-10
    # Tightening must actually help, not be a no-op.
    assert (
        tight.diagnostics.mass_balance_relative_error
        < loose.diagnostics.mass_balance_relative_error
    )


def test_no_drug_before_infusion_starts():
    model = OneCompartmentFirstOrderAbsorption(3.0, 40.0, 1.0)
    grid = np.linspace(0.0, 24.0, 2401)
    res = simulate(
        model,
        t_end_h=24.0,
        doses=[DoseEvent(6.0, 60.0, "iv_infusion", duration_h=2.0, target_state=1)],
        output_times_h=grid,
    )
    c = res.observable("plasma_concentration")
    assert np.all(c[grid < 6.0] == 0.0)
    assert c[grid > 7.0].max() > 0.0


# ===========================================================================
# Two compartment
# ===========================================================================
@pytest.fixture
def two_cmt():
    return TwoCompartment(cl_L_per_h=0.34, v1_L=0.34, q_L_per_h=0.23, v2_L=0.92)


def test_two_cmt_matches_biexponential(two_cmt):
    dose = 25.0
    grid = np.linspace(0.0, 24.0, 2401)
    res = simulate(
        two_cmt,
        t_end_h=24.0,
        doses=[DoseEvent(0.0, dose, "iv_bolus", target_state=1)],
        output_times_h=grid,
        rtol=1e-12,
        atol=1e-14,
    )
    analytic = two_cmt.analytic_concentration_iv_bolus(grid, dose)
    peak = float(np.max(analytic))
    max_rel = float(np.max(np.abs(res.observable("plasma_concentration") - analytic)) / peak)
    assert max_rel < 1e-8, f"Deviation {max_rel:.3e}"


def test_hybrid_rate_constants_satisfy_characteristic_polynomial(two_cmt):
    alpha, beta = two_cmt.hybrid_rate_constants
    assert alpha >= beta > 0
    assert alpha + beta == pytest.approx(two_cmt.k10 + two_cmt.k12 + two_cmt.k21, rel=1e-12)
    assert alpha * beta == pytest.approx(two_cmt.k10 * two_cmt.k21, rel=1e-12)


def test_two_cmt_initial_concentration_is_dose_over_v1(two_cmt):
    dose = 25.0
    res = simulate(
        two_cmt,
        t_end_h=8.0,
        doses=[DoseEvent(0.0, dose, "iv_bolus", target_state=1)],
        output_times_h=np.array([0.0, 1.0]),
    )
    assert res.observable("plasma_concentration")[0] == pytest.approx(dose / two_cmt.v1_L, rel=1e-12)


def test_two_cmt_mass_balance(two_cmt):
    res = simulate(
        two_cmt, t_end_h=100.0, doses=[DoseEvent(0.0, 25.0, "iv_bolus", target_state=1)]
    )
    err = res.diagnostics.mass_balance_relative_error
    assert err is not None and err < 1e-9


def test_two_cmt_collapses_to_one_cmt_when_q_tiny():
    """With negligible distribution, the observed decline must become CL/V1.

    In the Q -> 0 limit the peripheral compartment never fills, so alpha (the
    rate that actually governs the visible decline) tends to k10 = CL/V1 while
    beta tends to zero with vanishing amplitude. Checking beta would be wrong.
    """
    m = TwoCompartment(cl_L_per_h=3.0, v1_L=40.0, q_L_per_h=1e-8, v2_L=40.0)
    alpha, beta = m.hybrid_rate_constants
    assert alpha == pytest.approx(3.0 / 40.0, rel=1e-6)
    assert beta < 1e-8

    # And the observed profile must match a one-compartment IV bolus.
    grid = np.linspace(0.0, 48.0, 481)
    c2 = m.analytic_concentration_iv_bolus(grid, 100.0)
    c1 = (100.0 / 40.0) * np.exp(-(3.0 / 40.0) * grid)
    assert np.max(np.abs(c2 - c1)) / np.max(c1) < 1e-6


# ===========================================================================
# Michaelis-Menten
# ===========================================================================
def test_mm_reduces_to_first_order_far_below_km():
    """When C << Km the model must behave like first-order with CL = Vmax/Km."""
    vmax, km, v = 30.0, 5.0, 50.0
    mm = OneCompartmentMichaelisMenten(vmax_mg_per_h=vmax, km_mg_per_L=km, v_L=v)
    linear = OneCompartmentFirstOrderAbsorption(
        cl_L_per_h=vmax / km, v_L=v, ka_per_h=1.0
    )
    dose = 0.01  # tiny, so C stays far below Km
    grid = np.linspace(0.0, 48.0, 481)
    nl = simulate(
        mm,
        t_end_h=48.0,
        doses=[DoseEvent(0.0, dose, "iv_bolus", target_state=1)],
        output_times_h=grid,
        rtol=1e-12,
        atol=1e-16,
        check_tolerance_refinement=False,
    ).observable("plasma_concentration")
    # Analytic first-order IV bolus
    ke = (vmax / km) / v
    lin = (dose / v) * np.exp(-ke * grid)
    assert np.max(np.abs(nl - lin)) / np.max(lin) < 1e-4


def test_mm_saturates_above_km():
    """Doubling the dose must more than double exposure once the pathway saturates."""
    mm = OneCompartmentMichaelisMenten(vmax_mg_per_h=30.0, km_mg_per_L=5.0, v_L=50.0)
    grid = np.linspace(0.0, 240.0, 2401)

    def auc(dose: float) -> float:
        c = simulate(
            mm,
            t_end_h=240.0,
            doses=[DoseEvent(0.0, dose, "iv_bolus", target_state=1)],
            output_times_h=grid,
            check_tolerance_refinement=False,
        ).observable("plasma_concentration")
        return float(np.trapezoid(c, grid))

    a1 = auc(500.0)
    a2 = auc(1000.0)
    assert a2 / a1 > 2.05, f"Expected supra-proportional exposure, got ratio {a2 / a1:.3f}"


def test_mm_mass_balance():
    mm = OneCompartmentMichaelisMenten(vmax_mg_per_h=30.0, km_mg_per_L=5.0, v_L=50.0, ka_per_h=1.0)
    res = simulate(
        mm, t_end_h=400.0, doses=[DoseEvent(0.0, 400.0, "oral", target_state=0)]
    )
    err = res.diagnostics.mass_balance_relative_error
    assert err is not None and err < 1e-7


def test_mm_input_above_vmax_does_not_reach_steady_state():
    """Infusing faster than Vmax must produce unbounded accumulation."""
    mm = OneCompartmentMichaelisMenten(vmax_mg_per_h=10.0, km_mg_per_L=5.0, v_L=50.0)
    duration = 300.0
    rate = 15.0  # > Vmax
    res = simulate(
        mm,
        t_end_h=duration,
        doses=[DoseEvent(0.0, rate * duration, "iv_infusion", duration_h=duration, target_state=1)],
        output_times_h=np.linspace(0.0, duration, 1001),
        check_tolerance_refinement=False,
    )
    c = res.observable("plasma_concentration")
    # Still rising at the end: no plateau, in contrast to the linear case where
    # Css = R0/CL would have been reached long before 300 h.
    assert c[-1] > c[-2] > c[-3]
    # Far above Km, so elimination is saturated and cannot match the input rate.
    assert c[-1] > 5.0 * mm.km_mg_per_L
    # A linear model with CL = Vmax/Km would have plateaued at R0/CL.
    linear_css = rate / (mm.vmax_mg_per_h / mm.km_mg_per_L)
    assert c[-1] > 5.0 * linear_css


def test_mm_saturation_observable_bounds():
    mm = OneCompartmentMichaelisMenten(vmax_mg_per_h=30.0, km_mg_per_L=5.0, v_L=50.0)
    res = simulate(
        mm, t_end_h=48.0, doses=[DoseEvent(0.0, 1000.0, "iv_bolus", target_state=1)],
        check_tolerance_refinement=False,
    )
    s = res.observable("saturation_fraction")
    assert np.all((s >= 0.0) & (s <= 1.0))
    assert s.max() > 0.7  # genuinely saturated at this dose


# ===========================================================================
# Dosing machinery
# ===========================================================================
def test_repeated_dosing_produces_expected_peak_count():
    model = OneCompartmentFirstOrderAbsorption(2.8, 34.0, 1.5)
    doses = expand_regimen(300.0, "oral", n_doses=5, interval_h=12.0, target_state=0)
    assert [d.time_h for d in doses] == [0.0, 12.0, 24.0, 36.0, 48.0]
    res = simulate(model, t_end_h=84.0, doses=doses, output_times_h=np.linspace(0, 84, 8401))
    c = res.observable("plasma_concentration")
    # count interior local maxima
    peaks = int(np.sum((c[1:-1] > c[:-2]) & (c[1:-1] >= c[2:])))
    assert peaks == 5, f"Expected 5 peaks, found {peaks}"


def test_iv_bolus_trough_then_peak_both_visible():
    """A bolus at an output time must not erase the pre-dose trough."""
    model = OneCompartmentFirstOrderAbsorption(3.0, 40.0, 1.0)
    grid = np.array([0.0, 6.0, 11.999, 12.0, 18.0])
    res = simulate(
        model,
        t_end_h=24.0,
        doses=[
            DoseEvent(0.0, 100.0, "iv_bolus", target_state=1),
            DoseEvent(12.0, 100.0, "iv_bolus", target_state=1),
        ],
        output_times_h=grid,
    )
    c = res.observable("plasma_concentration")
    # At exactly 12 h the post-dose (higher) value is reported, so both the
    # trough and the peak it precedes are visible in the output.
    assert c[3] > c[2]
    # The jump equals dose/V. The 0.001 h gap between the trough sample and the
    # dose allows a small amount of real decay, hence the 1e-3 tolerance rather
    # than machine precision.
    assert (c[3] - c[2]) == pytest.approx(100.0 / 40.0, rel=1e-3)


def test_accumulation_to_steady_state_matches_theory():
    """Steady-state peak and trough must match the closed-form multiple-dose result.

        Cmax,ss = (D/V) / (1 - exp(-ke*tau))
        Cmin,ss = (D/V) * exp(-ke*tau) / (1 - exp(-ke*tau))

    This is the strongest available check on the repeated-dosing machinery,
    because it tests the breakpoint handling, the dose application and the
    resampling all at once against an exact answer.
    """
    cl, v, tau, dose = 3.0, 40.0, 8.0, 100.0
    model = OneCompartmentFirstOrderAbsorption(cl_L_per_h=cl, v_L=v, ka_per_h=50.0)
    ke = cl / v
    decay = np.exp(-ke * tau)
    cmax_ss = (dose / v) / (1.0 - decay)
    cmin_ss = (dose / v) * decay / (1.0 - decay)

    n = 40
    last_dose_t = (n - 1) * tau
    doses = expand_regimen(dose, "iv_bolus", n_doses=n, interval_h=tau, target_state=1)
    # Request a sample just before the final dose. Interpolating for the trough
    # would be wrong: the output grid cannot represent the bolus discontinuity,
    # so a point adjacent to the dose time would read the post-dose value.
    grid = np.unique(
        np.concatenate([np.linspace(0.0, n * tau, 20001), [last_dose_t - 1e-6]])
    )
    res = simulate(
        model, t_end_h=n * tau, doses=doses, output_times_h=grid,
        rtol=1e-11, atol=1e-13, check_tolerance_refinement=False,
    )
    c = res.observable("plasma_concentration")

    # Peak immediately after the final dose.
    peak = float(c[np.argmin(np.abs(grid - last_dose_t))])
    assert peak == pytest.approx(cmax_ss, rel=1e-6)

    # Trough immediately before the final dose.
    trough = float(c[np.argmin(np.abs(grid - (last_dose_t - 1e-6)))])
    assert trough == pytest.approx(cmin_ss, rel=1e-5)

    # The peak-to-trough difference must be exactly one dose worth.
    assert (peak - trough) == pytest.approx(dose / v, rel=1e-5)

    # And the first dose must be a plain single dose, with no accumulation yet.
    assert float(c[0]) == pytest.approx(dose / v, rel=1e-12)


def test_invalid_regimen_rejected():
    with pytest.raises(ValueError):
        expand_regimen(100.0, "oral", n_doses=0, interval_h=12.0)
    with pytest.raises(ValueError):
        expand_regimen(100.0, "oral", n_doses=3, interval_h=0.0)
    with pytest.raises(ValueError, match="exceed the dosing interval"):
        expand_regimen(100.0, "iv_infusion", n_doses=3, interval_h=6.0, duration_h=8.0)


def test_simulate_rejects_bad_inputs():
    model = OneCompartmentFirstOrderAbsorption(2.8, 34.0, 1.5)
    with pytest.raises(ValueError, match="must exceed"):
        simulate(model, t_end_h=0.0)
    with pytest.raises(ValueError, match="Unknown solver"):
        simulate(model, t_end_h=10.0, method="MagicSolver")
    with pytest.raises(ValueError, match="within"):
        simulate(model, t_end_h=10.0, output_times_h=np.array([0.0, 50.0]))
    with pytest.raises(ValueError, match="non-decreasing"):
        simulate(model, t_end_h=10.0, output_times_h=np.array([5.0, 1.0]))


def test_model_parameter_validation():
    with pytest.raises(ValueError):
        OneCompartmentFirstOrderAbsorption(cl_L_per_h=-1.0, v_L=34.0, ka_per_h=1.5)
    with pytest.raises(ValueError):
        OneCompartmentFirstOrderAbsorption(cl_L_per_h=2.8, v_L=0.0, ka_per_h=1.5)
    with pytest.raises(ValueError):
        OneCompartmentFirstOrderAbsorption(cl_L_per_h=2.8, v_L=34.0, ka_per_h=1.5, bioavailability=1.5)
    with pytest.raises(ValueError):
        TwoCompartment(cl_L_per_h=1.0, v1_L=1.0, q_L_per_h=-1.0, v2_L=1.0)
    with pytest.raises(ValueError):
        OneCompartmentMichaelisMenten(vmax_mg_per_h=0.0, km_mg_per_L=5.0, v_L=50.0)


def test_analytic_jacobian_matches_finite_difference():
    """A wrong Jacobian silently degrades the stiff solvers."""
    model = TwoCompartment(cl_L_per_h=0.34, v1_L=0.34, q_L_per_h=0.23, v2_L=0.92, ka_per_h=1.2)
    y = np.array([50.0, 20.0, 10.0, 5.0])
    rate = np.zeros(4)
    J = model.jacobian(0.0, y, rate)
    n = y.size
    J_fd = np.zeros((n, n))
    for j in range(n):
        h = max(abs(y[j]) * 1e-7, 1e-9)
        up, dn = y.copy(), y.copy()
        up[j] += h
        dn[j] -= h
        J_fd[:, j] = (model.rhs(0.0, up, rate) - model.rhs(0.0, dn, rate)) / (2 * h)
    assert np.allclose(J, J_fd, rtol=1e-5, atol=1e-8)


def test_mm_jacobian_matches_finite_difference():
    model = OneCompartmentMichaelisMenten(
        vmax_mg_per_h=30.0, km_mg_per_L=5.0, v_L=50.0, ka_per_h=1.0
    )
    y = np.array([100.0, 250.0, 10.0])
    rate = np.zeros(3)
    J = model.jacobian(0.0, y, rate)
    J_fd = np.zeros((3, 3))
    for j in range(3):
        h = max(abs(y[j]) * 1e-7, 1e-9)
        up, dn = y.copy(), y.copy()
        up[j] += h
        dn[j] -= h
        J_fd[:, j] = (model.rhs(0.0, up, rate) - model.rhs(0.0, dn, rate)) / (2 * h)
    assert np.allclose(J, J_fd, rtol=1e-5, atol=1e-8)


def test_solver_diagnostics_are_populated():
    model = OneCompartmentFirstOrderAbsorption(2.8, 34.0, 1.5)
    res = simulate(model, t_end_h=24.0, doses=[DoseEvent(0.0, 300.0, "oral", target_state=0)])
    d = res.diagnostics
    assert d.success
    assert d.n_rhs_evaluations > 0
    assert d.n_steps_accepted > 0
    assert d.wall_time_s >= 0.0
    assert d.method in ("LSODA", "BDF", "Radau", "RK45", "DOP853")


# ===========================================================================
# Provenance hashing contract
# ===========================================================================
def test_input_hash_ignores_evidence_metadata_but_record_hash_does_not():
    """A better citation must not invalidate a stored reproducibility hash.

    `input_hash` identifies the numbers; `record_hash` identifies the document.
    If evidence metadata leaked into `input_hash`, improving a reference would
    make every stored run look irreproducible, and the check would be ignored.
    """
    from synthbody.engine.provenance import (
        ParameterOrigin,
        ParameterRecord,
        ProvenanceRecord,
    )

    def build(origin: ParameterOrigin, description: str, refs: list[str]) -> ProvenanceRecord:
        return ProvenanceRecord(
            model_id="pk_1cmt_foa",
            model_name="One-compartment",
            model_version="1.0.0",
            parameters=[
                ParameterRecord("CL", 2.65, "L/h", origin, description, refs),
                ParameterRecord("V", 32.1, "L", origin, description, refs),
            ],
            inputs={"dose_mg": 300.0},
        )

    a = build(ParameterOrigin.USER, "", [])
    b = build(ParameterOrigin.FITTED, "Estimated from Theoph.", ["boeckmann1994"])

    assert a.input_hash == b.input_hash, "metadata must not change the input hash"
    assert a.to_dict()["record_hash"] != b.to_dict()["record_hash"], (
        "metadata must change the record hash"
    )


def test_input_hash_changes_when_a_value_changes():
    from synthbody.engine.provenance import ParameterOrigin, ParameterRecord, ProvenanceRecord

    def build(cl: float) -> ProvenanceRecord:
        return ProvenanceRecord(
            model_id="pk_1cmt_foa",
            model_name="One-compartment",
            model_version="1.0.0",
            parameters=[ParameterRecord("CL", cl, "L/h", ParameterOrigin.FITTED)],
            inputs={"dose_mg": 300.0},
        )

    assert build(2.65).input_hash != build(2.66).input_hash
    assert build(2.65).input_hash == build(2.65).input_hash


def test_input_hash_changes_when_the_engine_revision_changes():
    """A deliberate engine change must invalidate old hashes, loudly."""
    from synthbody.engine.provenance import ProvenanceRecord

    a = ProvenanceRecord(model_id="m", model_name="m", model_version="1.0.0", inputs={"d": 1})
    b = ProvenanceRecord(model_id="m", model_name="m", model_version="1.0.0", inputs={"d": 1})
    b.engine_revision = "engine-different"
    assert a.input_hash != b.input_hash


def test_input_hash_ignores_timestamp_and_platform():
    from synthbody.engine.provenance import ProvenanceRecord

    a = ProvenanceRecord(model_id="m", model_name="m", model_version="1.0.0", inputs={"d": 1})
    b = ProvenanceRecord(model_id="m", model_name="m", model_version="1.0.0", inputs={"d": 1})
    b.timestamp_utc = "1999-01-01T00:00:00+00:00"
    b.platform = "SomeOtherOS"
    b.python_version = "3.0.0"
    assert a.input_hash == b.input_hash
