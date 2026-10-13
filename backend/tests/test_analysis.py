"""
Tests for NCA, agreement metrics, sensitivity, population simulation and
parameter estimation.

Most of these check an answer that is known analytically, because "the number
looks plausible" is not verification.
"""
from __future__ import annotations

import numpy as np
import pytest

from synthbody.engine.analysis.estimation import FitSpec, fit_individual
from synthbody.engine.analysis.metrics import (
    compute_agreement,
    prediction_interval_coverage,
    residual_diagnostics,
)
from synthbody.engine.analysis.nca import (
    accumulation_metrics,
    compute_nca,
    time_within_range,
)
from synthbody.engine.analysis.population import (
    PopulationSpec,
    RandomEffect,
    ResidualError,
    run_population_simulation,
    sample_population_parameters,
)
from synthbody.engine.analysis.sensitivity import (
    ParameterSpec,
    local_sensitivity,
    morris_screening,
    sobol_indices,
)
from synthbody.engine.core import DoseEvent, expand_regimen
from synthbody.engine.models.compartmental import OneCompartmentFirstOrderAbsorption
from synthbody.engine.physiology.covariates import (
    HepaticFunction,
    Sex,
    SmokingStatus,
    VirtualPatient,
    log_normal_sigma_from_cv,
)


# ===========================================================================
# NCA
# ===========================================================================
def test_nca_on_monoexponential_recovers_known_values():
    """For C = C0*exp(-k t): AUC(0-inf) = C0/k and t1/2 = ln2/k, exactly."""
    c0, k = 10.0, 0.1
    t = np.linspace(0.0, 200.0, 20001)
    c = c0 * np.exp(-k * t)
    r = compute_nca(t, c, dose_mg=100.0)
    assert r.cmax == pytest.approx(c0, rel=1e-9)
    assert r.tmax_h == pytest.approx(0.0)
    assert r.terminal_rate_constant_per_h == pytest.approx(k, rel=1e-6)
    assert r.terminal_half_life_h == pytest.approx(np.log(2) / k, rel=1e-6)
    assert r.auc_0_inf == pytest.approx(c0 / k, rel=1e-5)
    # CL = dose/AUCinf = 100 / 100 = 1.0
    assert r.clearance_L_per_h == pytest.approx(100.0 / (c0 / k), rel=1e-5)
    assert r.terminal_fit_r_squared == pytest.approx(1.0, abs=1e-9)


def test_nca_log_down_beats_linear_on_declining_curve():
    """Linear trapezoids overestimate AUC on log-linear decline. Verify we do better."""
    c0, k = 10.0, 0.3
    t = np.linspace(0.0, 24.0, 25)  # coarse grid exaggerates the difference
    c = c0 * np.exp(-k * t)
    r = compute_nca(t, c)
    true_auc = (c0 / k) * (1 - np.exp(-k * 24.0))
    linear = float(np.trapezoid(c, t))
    assert abs(r.auc_0_last - true_auc) < abs(linear - true_auc)


def test_nca_warns_on_excessive_extrapolation():
    c0, k = 10.0, 0.01  # very long half-life
    t = np.linspace(0.0, 5.0, 101)  # far too short a window
    r = compute_nca(t, c0 * np.exp(-k * t), dose_mg=100.0)
    assert r.auc_extrap_percent is not None and r.auc_extrap_percent > 20.0
    assert any("extrapolated" in w for w in r.warnings)


def test_nca_clips_negatives_and_says_so():
    t = np.linspace(0.0, 10.0, 11)
    c = np.array([1.0, 2.0, 3.0, 2.0, 1.0, -0.001, 0.5, 0.4, 0.3, 0.2, 0.1])
    r = compute_nca(t, c)
    assert any("Negative" in w for w in r.warnings)
    assert r.cmin >= 0.0


def test_nca_interval_anchoring_picks_the_right_window():
    """AUC(tau) must come from the interval after the last dose, not the last
    interval of the simulation window."""
    model = OneCompartmentFirstOrderAbsorption(3.0, 40.0, 2.0)
    from synthbody.engine.core import simulate

    tau, n = 12.0, 3
    doses = expand_regimen(300.0, "oral", n_doses=n, interval_h=tau, target_state=0)
    grid = np.linspace(0.0, 96.0, 9601)
    res = simulate(model, t_end_h=96.0, doses=doses, output_times_h=grid,
                   check_tolerance_refinement=False)
    c = res.observable("plasma_concentration")
    last_dose = (n - 1) * tau  # 24 h

    anchored = compute_nca(grid, c, dosing_interval_h=tau, interval_start_h=last_dose)
    assert anchored.auc_window_h == (24.0, 36.0)
    assert anchored.cmax > 0

    # Unanchored falls back to the final window 84-96 h, long after dosing ended.
    unanchored = compute_nca(grid, c, dosing_interval_h=tau)
    assert unanchored.auc_window_h == (84.0, 96.0)
    assert unanchored.auc_0_last < anchored.auc_0_last


def test_nca_warns_when_horizon_truncates_the_interval():
    t = np.linspace(0.0, 30.0, 301)
    c = 5.0 * np.exp(-0.1 * t)
    r = compute_nca(t, c, dosing_interval_h=12.0, interval_start_h=24.0)
    assert any("UNDERSTATES" in w for w in r.warnings)


def test_nca_requires_enough_points():
    with pytest.raises(ValueError):
        compute_nca(np.array([0.0]), np.array([1.0]))
    with pytest.raises(ValueError):
        compute_nca(np.array([0.0, 1.0]), np.array([1.0]))


def test_accumulation_ratio_matches_linear_theory():
    """R_ac = 1/(1-exp(-ke*tau)) for a linear one-compartment model."""
    from synthbody.engine.core import simulate

    cl, v, tau = 3.0, 40.0, 8.0
    ke = cl / v
    model = OneCompartmentFirstOrderAbsorption(cl, v, ka_per_h=50.0)
    n = 30
    doses = expand_regimen(100.0, "iv_bolus", n_doses=n, interval_h=tau, target_state=1)
    grid = np.linspace(0.0, n * tau, 24001)
    c = simulate(model, t_end_h=n * tau, doses=doses, output_times_h=grid,
                 rtol=1e-11, atol=1e-13, check_tolerance_refinement=False
                 ).observable("plasma_concentration")
    m = accumulation_metrics(grid, c, tau, n_doses=n, first_dose_h=0.0)
    expected = 1.0 / (1.0 - np.exp(-ke * tau))
    assert m["accumulation_ratio_auc"] == pytest.approx(expected, rel=5e-3)
    assert m["n_complete_intervals"] == n
    assert m["cmax_ss"] > m["cmin_ss"] > 0


def test_time_within_range_on_a_known_square_wave():
    """Half the time above the band, half below: the fractions must be exact."""
    t = np.linspace(0.0, 100.0, 100001)
    c = np.where(t < 50.0, 30.0, 1.0)
    r = time_within_range(t, c, low=10.0, high=20.0)
    assert r["fraction_above"] == pytest.approx(0.5, abs=1e-3)
    assert r["fraction_below"] == pytest.approx(0.5, abs=1e-3)
    assert r["fraction_within"] == pytest.approx(0.0, abs=1e-3)
    assert r["fraction_below"] + r["fraction_within"] + r["fraction_above"] == pytest.approx(1.0)


def test_time_within_range_is_grid_independent():
    """The answer must not depend on how finely the caller sampled."""
    k = 0.2
    results = []
    for n in (201, 2001, 20001):
        t = np.linspace(0.0, 60.0, n)
        results.append(time_within_range(t, 25.0 * np.exp(-k * t), 5.0, 15.0)["fraction_within"])
    assert max(results) - min(results) < 5e-3


def test_time_within_range_rejects_inverted_band():
    t = np.linspace(0, 10, 11)
    with pytest.raises(ValueError):
        time_within_range(t, np.ones(11), low=20.0, high=10.0)


# ===========================================================================
# Agreement metrics
# ===========================================================================
def test_perfect_prediction_gives_perfect_metrics():
    obs = np.array([1.0, 5.0, 10.0, 2.0])
    m = compute_agreement(obs, obs.copy())
    assert m.rmse == pytest.approx(0.0)
    assert m.average_fold_error == pytest.approx(1.0)
    assert m.absolute_average_fold_error == pytest.approx(1.0)
    assert m.fraction_within_2_fold == pytest.approx(1.0)
    assert m.r_squared_vs_identity == pytest.approx(1.0)


def test_afe_detects_bias_and_aafe_detects_imprecision():
    """The key distinction: AFE can be 1.0 while the model is badly imprecise."""
    obs = np.array([10.0, 10.0, 10.0, 10.0])
    # Alternating 2x over and 2x under: unbiased on the log scale, very imprecise.
    pred = np.array([20.0, 5.0, 20.0, 5.0])
    m = compute_agreement(obs, pred)
    assert m.average_fold_error == pytest.approx(1.0, rel=1e-9)
    assert m.absolute_average_fold_error == pytest.approx(2.0, rel=1e-9)
    assert m.fraction_within_1_5_fold == pytest.approx(0.0)


def test_systematic_two_fold_overprediction():
    obs = np.array([1.0, 2.0, 4.0, 8.0])
    m = compute_agreement(obs, obs * 2.0)
    assert m.average_fold_error == pytest.approx(2.0, rel=1e-9)
    assert m.absolute_average_fold_error == pytest.approx(2.0, rel=1e-9)
    assert m.mean_percent_error == pytest.approx(100.0, rel=1e-9)


def test_r_squared_vs_identity_can_be_negative():
    """An honest R^2: a model worse than the mean must score below zero."""
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    pred = np.array([10.0, 10.0, 10.0, 10.0])
    m = compute_agreement(obs, pred)
    assert m.r_squared_vs_identity < 0.0


def test_zero_observations_are_excluded_and_reported():
    obs = np.array([0.0, 1.0, 2.0])
    pred = np.array([0.5, 1.0, 2.0])
    m = compute_agreement(obs, pred)
    assert m.n_excluded_nonpositive == 1
    assert any("non-positive" in n for n in m.notes)


def test_shape_mismatch_rejected():
    with pytest.raises(ValueError, match="Shape mismatch"):
        compute_agreement(np.array([1.0, 2.0]), np.array([1.0]))


def test_residual_diagnostics_detect_heteroscedasticity():
    rng = np.random.default_rng(42)
    pred = np.linspace(1.0, 100.0, 300)
    # Error proportional to prediction -> strong positive Spearman.
    obs = pred * (1.0 + rng.normal(0.0, 0.2, pred.size))
    d = residual_diagnostics(obs, pred)
    assert d["spearman_abs_residual_vs_predicted"] > 0.4


def test_prediction_interval_coverage_is_calibrated():
    """Drawing observations from the same distribution must give ~nominal coverage."""
    rng = np.random.default_rng(7)
    n_obs, n_rep = 400, 600
    truth = np.full(n_obs, 10.0)
    sims = rng.normal(10.0, 2.0, size=(n_rep, n_obs))
    obs = rng.normal(10.0, 2.0, size=n_obs)
    r = prediction_interval_coverage(obs, sims, level=0.90)
    assert abs(r["coverage"] - 0.90) < 0.05
    assert r["n"] == n_obs


def test_prediction_interval_coverage_rejects_bad_shape():
    with pytest.raises(ValueError):
        prediction_interval_coverage(np.ones(5), np.ones((10, 4)))


# ===========================================================================
# Sensitivity
# ===========================================================================
def test_local_sensitivity_recovers_analytic_derivative():
    """For AUC = D/CL, the normalised sensitivity to CL is exactly -1."""
    def objective(p):
        return 300.0 / p["CL"]

    res = local_sensitivity(objective, [ParameterSpec("CL", 3.0, 1.0, 10.0)])
    s = res["results"][0]["normalised_sensitivity"]
    assert s == pytest.approx(-1.0, rel=1e-5)


def test_local_sensitivity_on_power_law():
    """For Y = P^2 the normalised sensitivity is exactly 2."""
    res = local_sensitivity(
        lambda p: p["x"] ** 2, [ParameterSpec("x", 4.0, 1.0, 10.0)]
    )
    assert res["results"][0]["normalised_sensitivity"] == pytest.approx(2.0, rel=1e-5)


def test_local_sensitivity_ranks_by_magnitude():
    def objective(p):
        return 5.0 * p["a"] + 0.01 * p["b"]

    res = local_sensitivity(
        objective,
        [ParameterSpec("b", 1.0, 0.5, 2.0), ParameterSpec("a", 1.0, 0.5, 2.0)],
    )
    assert res["results"][0]["parameter"] == "a"


def test_local_sensitivity_reports_step_convergence():
    res = local_sensitivity(
        lambda p: 300.0 / p["CL"], [ParameterSpec("CL", 3.0, 1.0, 10.0)]
    )
    row = res["results"][0]
    assert row["step_halving_relative_change"] is not None
    assert row["step_halving_relative_change"] < 1e-3


def test_parameter_spec_validates_bounds():
    with pytest.raises(ValueError):
        ParameterSpec("x", nominal=5.0, low=10.0, high=1.0)
    with pytest.raises(ValueError):
        ParameterSpec("x", nominal=50.0, low=1.0, high=10.0)


def test_morris_ranks_the_dominant_parameter_first():
    specs = [
        ParameterSpec("a", 1.0, 0.5, 1.5),
        ParameterSpec("b", 1.0, 0.5, 1.5),
    ]
    res = morris_screening(
        lambda p: 100.0 * p["a"] + 0.1 * p["b"], specs, trajectories=20, levels=4
    )
    assert res["results"][0]["parameter"] == "a"
    assert res["results"][0]["mu_star"] > res["results"][1]["mu_star"] * 10


def test_sobol_additive_model_has_no_interaction():
    """For Y = a + b the first-order indices must sum to ~1 and ST ~ S1."""
    specs = [ParameterSpec("a", 1.0, 0.0, 2.0), ParameterSpec("b", 1.0, 0.0, 2.0)]
    res = sobol_indices(lambda p: p["a"] + p["b"], specs, base_samples=512)
    assert res["sum_first_order"] == pytest.approx(1.0, abs=0.08)
    for row in res["results"]:
        assert abs(row["ST"] - row["S1"]) < 0.08


def test_sobol_detects_pure_interaction():
    """For Y = a*b on symmetric ranges, ST must exceed S1 appreciably."""
    specs = [ParameterSpec("a", 1.0, -1.0, 1.0), ParameterSpec("b", 1.0, -1.0, 1.0)]
    # nominal must be inside the range
    specs = [ParameterSpec("a", 0.0, -1.0, 1.0), ParameterSpec("b", 0.0, -1.0, 1.0)]
    res = sobol_indices(lambda p: p["a"] * p["b"], specs, base_samples=1024)
    assert res["sum_first_order"] < 0.3
    for row in res["results"]:
        assert row["interaction_strength"] > 0.5


def test_sobol_rejects_non_power_of_two():
    with pytest.raises(ValueError):
        sobol_indices(lambda p: p["a"], [ParameterSpec("a", 1.0, 0.0, 2.0)], base_samples=500)


# ===========================================================================
# Population
# ===========================================================================
def test_cv_to_sigma_conversion_is_exact():
    for cv in (10.0, 30.0, 50.0, 100.0):
        sigma = log_normal_sigma_from_cv(cv)
        recovered = 100.0 * np.sqrt(np.exp(sigma**2) - 1.0)
        assert recovered == pytest.approx(cv, rel=1e-12)


def test_sampled_population_recovers_requested_cv():
    spec = PopulationSpec(
        typical_values={"CL": 3.0, "V": 40.0},
        random_effects=[RandomEffect("CL", 30.0), RandomEffect("V", 20.0)],
    )
    p = sample_population_parameters(spec, 20000, seed=1)
    for name, cv in (("CL", 30.0), ("V", 20.0)):
        vals = p[name]
        observed = 100.0 * np.std(vals, ddof=1) / np.mean(vals)
        assert observed == pytest.approx(cv, rel=0.05), f"{name}: {observed:.1f}% vs {cv}%"


def test_sampled_population_is_log_normal_with_right_median():
    spec = PopulationSpec(
        typical_values={"CL": 3.0}, random_effects=[RandomEffect("CL", 40.0)]
    )
    vals = sample_population_parameters(spec, 50000, seed=2)["CL"]
    assert np.all(vals > 0)
    # Median of a log-normal equals the typical value.
    assert float(np.median(vals)) == pytest.approx(3.0, rel=0.02)


def test_correlated_random_effects_produce_requested_correlation():
    spec = PopulationSpec(
        typical_values={"CL": 3.0, "V": 40.0},
        random_effects=[RandomEffect("CL", 30.0), RandomEffect("V", 30.0)],
        correlation={("CL", "V"): 0.8},
    )
    p = sample_population_parameters(spec, 20000, seed=3)
    r = float(np.corrcoef(np.log(p["CL"]), np.log(p["V"]))[0, 1])
    assert r == pytest.approx(0.8, abs=0.03)


def test_non_psd_correlation_matrix_is_projected_not_crashed():
    """A user can easily specify an impossible correlation structure."""
    spec = PopulationSpec(
        typical_values={"A": 1.0, "B": 1.0, "C": 1.0},
        random_effects=[RandomEffect("A", 30.0), RandomEffect("B", 30.0), RandomEffect("C", 30.0)],
        correlation={("A", "B"): 0.99, ("B", "C"): 0.99, ("A", "C"): -0.99},
    )
    p = sample_population_parameters(spec, 1000, seed=4)
    for k in ("A", "B", "C"):
        assert np.all(np.isfinite(p[k]))
        assert np.all(p[k] > 0)


def test_population_spec_rejects_unknown_parameters():
    spec = PopulationSpec(
        typical_values={"CL": 3.0}, random_effects=[RandomEffect("Vmax", 30.0)]
    )
    with pytest.raises(ValueError, match="no typical value"):
        spec.validate()
    spec2 = PopulationSpec(
        typical_values={"CL": 3.0},
        random_effects=[RandomEffect("CL", 30.0)],
        correlation={("CL", "Nope"): 0.5},
    )
    with pytest.raises(ValueError, match="no random effect"):
        spec2.validate()


def test_population_simulation_percentiles_are_ordered_and_bracket_typical():
    spec = PopulationSpec(
        typical_values={"CL": 3.0, "V": 40.0, "ka": 1.5, "F": 1.0, "t_lag": 0.0},
        random_effects=[RandomEffect("CL", 35.0), RandomEffect("V", 20.0)],
        residual_error=ResidualError(15.0, 0.1),
    )
    grid = np.linspace(0.0, 48.0, 97)
    res = run_population_simulation(
        lambda p: OneCompartmentFirstOrderAbsorption(
            p["CL"], p["V"], p["ka"], p.get("F", 1.0), p.get("t_lag", 0.0)
        ),
        spec,
        t_end_h=48.0,
        doses=[DoseEvent(0.0, 300.0, "oral", target_state=0)],
        output_times_h=grid,
        n_subjects=300,
        seed=11,
    )
    assert res["n_subjects_simulated"] == 300
    assert res["n_failures"] == 0
    p = res["structural_percentiles"]
    lo, mid, hi = np.array(p["p5"]), np.array(p["p50"]), np.array(p["p95"])
    assert np.all(lo <= mid + 1e-12)
    assert np.all(mid <= hi + 1e-12)
    typical = np.array(res["typical_value_profile"])
    # The typical-value profile should sit inside the cohort spread after t=0.
    inside = (typical[1:] >= lo[1:] - 1e-9) & (typical[1:] <= hi[1:] + 1e-9)
    assert inside.mean() > 0.95


def test_residual_error_widens_the_bands_only_when_requested():
    spec = PopulationSpec(
        typical_values={"CL": 3.0, "V": 40.0, "ka": 1.5},
        random_effects=[RandomEffect("CL", 30.0)],
        residual_error=ResidualError(30.0, 0.2),
    )
    grid = np.linspace(0.0, 24.0, 49)
    kw = dict(
        t_end_h=24.0,
        doses=[DoseEvent(0.0, 300.0, "oral", target_state=0)],
        output_times_h=grid,
        n_subjects=400,
        seed=13,
    )
    factory = lambda p: OneCompartmentFirstOrderAbsorption(p["CL"], p["V"], p["ka"])
    without = run_population_simulation(factory, spec, include_residual_error=False, **kw)
    with_ = run_population_simulation(factory, spec, include_residual_error=True, **kw)
    assert "observation_percentiles" not in without
    assert "observation_percentiles" in with_
    s_width = np.array(with_["structural_percentiles"]["p95"]) - np.array(
        with_["structural_percentiles"]["p5"]
    )
    o_width = np.array(with_["observation_percentiles"]["p95"]) - np.array(
        with_["observation_percentiles"]["p5"]
    )
    assert np.mean(o_width) > np.mean(s_width)


def test_population_is_reproducible_by_seed():
    spec = PopulationSpec(
        typical_values={"CL": 3.0, "V": 40.0, "ka": 1.5},
        random_effects=[RandomEffect("CL", 30.0)],
    )
    a = sample_population_parameters(spec, 100, seed=99)["CL"]
    b = sample_population_parameters(spec, 100, seed=99)["CL"]
    c = sample_population_parameters(spec, 100, seed=100)["CL"]
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


# ===========================================================================
# Estimation
# ===========================================================================
def test_fit_recovers_known_parameters_from_noise_free_data():
    """The acid test for an estimator: give it data generated by known truth."""
    truth = OneCompartmentFirstOrderAbsorption(cl_L_per_h=2.8, v_L=34.0, ka_per_h=1.5)
    t = np.array([0.25, 0.5, 1.0, 2.0, 3.5, 5.0, 7.0, 9.0, 12.0, 24.0])
    c = truth.analytic_concentration(t, 320.0)

    def predict(p, tt):
        return OneCompartmentFirstOrderAbsorption(p["CL"], p["V"], p["ka"]).analytic_concentration(
            tt, 320.0
        )

    res = fit_individual(
        predict,
        t,
        c,
        [
            FitSpec("CL", 1.0, 0.01, 100.0),
            FitSpec("V", 20.0, 1.0, 500.0),
            FitSpec("ka", 0.5, 0.01, 50.0),
        ],
    )
    assert res.converged
    assert res.parameters["CL"] == pytest.approx(2.8, rel=1e-3)
    assert res.parameters["V"] == pytest.approx(34.0, rel=1e-3)
    assert res.parameters["ka"] == pytest.approx(1.5, rel=1e-3)


def test_fit_reports_standard_errors_and_correlations():
    truth = OneCompartmentFirstOrderAbsorption(2.8, 34.0, 1.5)
    rng = np.random.default_rng(5)
    t = np.array([0.25, 0.5, 1.0, 2.0, 3.5, 5.0, 7.0, 9.0, 12.0, 24.0])
    c = truth.analytic_concentration(t, 320.0) * (1 + rng.normal(0, 0.08, t.size))

    def predict(p, tt):
        return OneCompartmentFirstOrderAbsorption(p["CL"], p["V"], p["ka"]).analytic_concentration(
            tt, 320.0
        )

    res = fit_individual(
        predict, t, c,
        [FitSpec("CL", 2.0, 0.01, 100.0), FitSpec("V", 30.0, 1.0, 500.0),
         FitSpec("ka", 1.0, 0.01, 50.0)],
    )
    assert all(res.standard_errors[k] is not None for k in ("CL", "V", "ka"))
    assert res.correlation_matrix is not None
    assert len(res.correlation_matrix) == 3
    # Diagonal of a correlation matrix must be 1.
    for i in range(3):
        assert res.correlation_matrix[i][i] == pytest.approx(1.0, abs=1e-9)
    assert res.condition_number is not None and res.condition_number > 0


def test_fit_refuses_more_parameters_than_data():
    def predict(p, tt):
        return np.full_like(tt, p["a"])

    with pytest.raises(ValueError, match="cannot support"):
        fit_individual(
            predict,
            np.array([1.0, 2.0]),
            np.array([1.0, 1.0]),
            [FitSpec("a", 1.0), FitSpec("b", 1.0), FitSpec("c", 1.0)],
        )


def test_fit_requires_positive_initial_values():
    with pytest.raises(ValueError, match="log scale"):
        FitSpec("CL", initial=0.0)
    with pytest.raises(ValueError, match="log scale"):
        FitSpec("CL", initial=-1.0)


def test_fit_rejects_unknown_weighting():
    def predict(p, tt):
        return np.full_like(tt, p["a"])

    with pytest.raises(ValueError, match="weighting"):
        fit_individual(
            predict, np.linspace(1, 10, 10), np.ones(10), [FitSpec("a", 1.0)],
            weighting="magic",
        )


def test_fit_flags_unidentifiable_parameters():
    """Two parameters that only appear as a product cannot be separated."""
    def predict(p, tt):
        return np.full_like(tt, p["a"] * p["b"])

    t = np.linspace(1, 10, 10)
    res = fit_individual(
        predict, t, np.full(10, 6.0), [FitSpec("a", 1.0), FitSpec("b", 1.0)]
    )
    assert any(
        "identifiable" in w or "standard error" in w.lower() for w in res.warnings
    ), res.warnings


# ===========================================================================
# Covariates
# ===========================================================================
def test_patient_validation_rejects_implausible_values():
    with pytest.raises(ValueError, match="Implausible"):
        VirtualPatient(age_years=200.0)
    with pytest.raises(ValueError, match="Implausible"):
        VirtualPatient(weight_kg=0.5)
    with pytest.raises(ValueError, match="Implausible"):
        VirtualPatient(serum_creatinine_mg_dL=0.0)


def test_cockcroft_gault_known_case():
    """A 40-year-old 70 kg male with Scr 1.0 has CrCl = (140-40)*70/(72*1.0) = 97.2."""
    p = VirtualPatient(age_years=40, weight_kg=70, height_cm=175, sex=Sex.MALE,
                       serum_creatinine_mg_dL=1.0)
    assert p.creatinine_clearance_cockcroft_gault_mL_min() == pytest.approx(97.222, rel=1e-4)


def test_cockcroft_gault_female_factor():
    kw = dict(age_years=40, weight_kg=70, height_cm=175, serum_creatinine_mg_dL=1.0)
    male = VirtualPatient(sex=Sex.MALE, **kw).creatinine_clearance_cockcroft_gault_mL_min()
    female = VirtualPatient(sex=Sex.FEMALE, **kw).creatinine_clearance_cockcroft_gault_mL_min()
    assert female / male == pytest.approx(0.85, rel=1e-9)


def test_du_bois_bsa_known_case():
    """A 70 kg, 175 cm adult has a Du Bois BSA close to 1.85 m2."""
    p = VirtualPatient(weight_kg=70, height_cm=175)
    assert p.bsa_m2 == pytest.approx(1.846, abs=0.01)


def test_ckd_epi_declines_with_age_and_creatinine():
    base = VirtualPatient(age_years=30, serum_creatinine_mg_dL=0.9)
    older = VirtualPatient(age_years=80, serum_creatinine_mg_dL=0.9)
    worse = VirtualPatient(age_years=30, serum_creatinine_mg_dL=2.5)
    assert older.egfr_ckd_epi_2021_mL_min_1_73m2() < base.egfr_ckd_epi_2021_mL_min_1_73m2()
    assert worse.egfr_ckd_epi_2021_mL_min_1_73m2() < base.egfr_ckd_epi_2021_mL_min_1_73m2()


def test_allometric_factors_are_exact():
    from synthbody.engine.physiology.covariates import (
        allometric_clearance_factor,
        allometric_volume_factor,
    )

    assert allometric_clearance_factor(70.0).multiplier == pytest.approx(1.0)
    assert allometric_volume_factor(70.0).multiplier == pytest.approx(1.0)
    assert allometric_clearance_factor(140.0).multiplier == pytest.approx(2.0**0.75)
    assert allometric_volume_factor(140.0).multiplier == pytest.approx(2.0)


def test_illustrative_covariates_are_labelled_as_such():
    """A guard: these multipliers must never be presented as measurements."""
    from synthbody.engine.physiology.covariates import (
        hepatic_clearance_factor,
        smoking_cyp1a2_clearance_factor,
    )
    from synthbody.engine.provenance import ParameterOrigin

    hep = hepatic_clearance_factor(HepaticFunction.SEVERE_IMPAIRMENT)
    assert hep.origin == ParameterOrigin.ILLUSTRATIVE
    assert hep.multiplier < 1.0

    smoke = smoking_cyp1a2_clearance_factor(SmokingStatus.SMOKER)
    assert smoke.origin == ParameterOrigin.INFERRED
    assert smoke.multiplier > 1.0

    assert smoking_cyp1a2_clearance_factor(SmokingStatus.NON_SMOKER).multiplier == 1.0
