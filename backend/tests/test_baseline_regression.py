"""Backward-compatibility guard for the pre-expansion scientific baseline.

Every number in ``tests/baseline/reference_outputs.json`` was produced by the
engine at commit 3d0d122, before any capability-expansion work started. These
tests replay them.

The point is not to test the models -- the other suites do that. The point is
that adding a whole-body oral PBPK model, a DDI module or a new drug entry must
not move a concentration curve, a fitted parameter or a published validation
figure that was already standing. If one of these fails, the fix is to revert
the change or to document deliberately why the result moved -- never to
regenerate the fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from synthbody.engine.analysis.benchmark import run_theophylline_apriori
from synthbody.engine.analysis.validation import run_validation
from synthbody.engine.core import DoseEvent, expand_regimen, simulate
from synthbody.engine.models.compartmental import (
    OneCompartmentFirstOrderAbsorption,
    OneCompartmentMichaelisMenten,
    TwoCompartment,
)
from synthbody.engine.models.pbpk import PerfusionLimitedPBPK
from synthbody.engine.physiology.partition import DrugPhysChem

BASELINE_PATH = Path(__file__).parent / "baseline" / "reference_outputs.json"
BASELINE = json.loads(BASELINE_PATH.read_text())

# Curve agreement is required to 1e-9 relative. The models are deterministic and
# the solver tolerances are fixed, so anything looser would let a real change
# hide inside the slack.
CURVE_RTOL = 1e-9


def _replay(name: str, model, t_end: float, doses):
    expected = BASELINE["curves"][name]
    grid = np.linspace(0.0, expected["t_end_h"], expected["n"])
    result = simulate(
        model, t_end_h=t_end, doses=doses, output_times_h=grid,
        check_tolerance_refinement=False,
    )
    got = result.observable("plasma_concentration")
    np.testing.assert_allclose(got, np.array(expected["c"]), rtol=CURVE_RTOL, atol=1e-12)
    return result


def test_one_compartment_oral_curve_unchanged():
    _replay(
        "pk_1cmt_foa_300mg_oral",
        OneCompartmentFirstOrderAbsorption(2.6537, 32.116, 2.133),
        25.0,
        [DoseEvent(0.0, 300.0, "oral", target_state=0)],
    )


def test_two_compartment_iv_curve_unchanged():
    _replay(
        "pk_2cmt_iv_25",
        TwoCompartment(0.3413, 0.3432, 0.2318, 0.9244),
        8.0,
        [DoseEvent(0.0, 25.0, "iv_bolus", target_state=1)],
    )


def test_michaelis_menten_multiple_dose_curve_unchanged():
    """The non-linear model under accumulation -- the most fragile of the three."""
    _replay(
        "pk_1cmt_mm_multi",
        OneCompartmentMichaelisMenten(30.0, 5.0, 50.0, ka_per_h=1.0),
        96.0,
        expand_regimen(200.0, "oral", 6, 12.0, target_state=0),
    )


def _baseline_pbpk() -> PerfusionLimitedPBPK:
    return PerfusionLimitedPBPK(
        drug=DrugPhysChem(log_p=0.0, fraction_unbound_plasma=0.60, blood_plasma_ratio=0.82),
        body_weight_kg=70.0,
        hepatic_intrinsic_clearance_L_per_h=5.0,
        renal_clearance_L_per_h=0.3,
    )


def test_pbpk_iv_curve_unchanged():
    _replay("pbpk_iv_300", _baseline_pbpk(), 24.0,
            [DoseEvent(0.0, 300.0, "iv_bolus", target_state=2)])


def test_pbpk_scalars_unchanged():
    """Vss, cardiac output and every tissue partition coefficient.

    The partition coefficients are included because a Poulin-Theil bug was
    found and fixed once already; this pins the corrected values.
    """
    pbpk = _baseline_pbpk()
    assert pbpk.predicted_vss_L() == pytest.approx(
        BASELINE["scalars"]["pbpk_predicted_vss_L"], rel=1e-12)
    assert pbpk.cardiac_output_L_per_h == pytest.approx(
        BASELINE["scalars"]["pbpk_cardiac_output_L_per_h"], rel=1e-12)
    expected = BASELINE["scalars"]["pbpk_partition"]
    assert set(pbpk.partition_coefficients) == set(expected)
    for tissue, value in expected.items():
        assert pbpk.partition_coefficients[tissue] == pytest.approx(value, rel=1e-12), tissue


@pytest.mark.parametrize("target_id", ["theoph_1cmt_foa", "indometh_2cmt"])
def test_published_validation_results_unchanged(target_id):
    """The two headline accuracy figures quoted in README.md and VALIDATION.md.

    These are published claims about the software. They are allowed to change
    only with a documented reason.
    """
    expected = BASELINE["scalars"][f"validation_{target_id}"]
    result = run_validation(target_id)
    metrics = result.held_out_metrics
    assert metrics.absolute_average_fold_error == pytest.approx(
        expected["held_out_aafe"], rel=1e-9)
    assert metrics.average_fold_error == pytest.approx(expected["held_out_afe"], rel=1e-9)
    assert metrics.rmse == pytest.approx(expected["held_out_rmse"], rel=1e-9)
    assert metrics.fraction_within_2_fold == pytest.approx(
        expected["held_out_fraction_within_2_fold"], rel=1e-12)
    for name, value in expected["typical_parameters"].items():
        assert result.typical_parameters[name] == pytest.approx(value, rel=1e-9), name


def test_theophylline_apriori_benchmark_unchanged():
    """The competitive-benchmark numbers quoted in BENCHMARK.md.

    Pinned at the pre-specified permeability, not the post-hoc best one, so the
    test also keeps the headline honest.
    """
    expected = BASELINE["scalars"]["benchmark_theoph_apriori"]
    report = run_theophylline_apriori(peff_sweep=(expected["prespecified_peff_cm_per_s"],))
    headline = report["headline_result"]
    metrics = headline["evaluation"]["metrics"]
    assert headline["mean_predicted_fabs"] == pytest.approx(
        expected["mean_predicted_fabs"], rel=1e-9)
    for metric in ("auc", "cmax", "tmax"):
        assert metrics[metric]["aafe"] == pytest.approx(
            expected[f"{metric}_aafe"], rel=1e-9), f"{metric} AAFE"
        assert metrics[metric]["afe"] == pytest.approx(
            expected[f"{metric}_afe"], rel=1e-9), f"{metric} AFE"


def test_baseline_fixture_is_not_silently_empty():
    """Guards against the fixture being truncated or regenerated to nothing."""
    assert len(BASELINE["curves"]) == 4
    assert BASELINE["engine_revision"] == "engine-2026.10.12b"
    for curve in BASELINE["curves"].values():
        assert len(curve["c"]) == curve["n"] > 100
        assert max(curve["c"]) > 0.0
