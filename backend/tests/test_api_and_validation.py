"""
API integration tests and validation-pipeline regression tests.

The validation tests pin the achieved accuracy numbers. If a change to the
engine or the estimator moves them, the test fails and someone has to look at
why rather than discovering it in a demo.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

# Point the database somewhere disposable before anything imports the engine.
_TMP = Path(tempfile.mkdtemp(prefix="synthbody_test_"))
os.environ["SYNTHBODY_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402

from synthbody.api.main import app  # noqa: E402
from synthbody.engine.analysis.datasets import (  # noqa: E402
    get_dataset,
    load_indomethacin,
    load_theophylline,
)
from synthbody.engine.analysis.validation import (  # noqa: E402
    deterministic_split,
    run_validation,
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ===========================================================================
# Datasets
# ===========================================================================
def test_theoph_dataset_integrity():
    """The shipped Theoph data must be exactly as distributed: 12 x 11 = 132 rows."""
    ds = load_theophylline()
    assert len(ds.subjects) == 12
    assert ds.n_observations == 132
    for s in ds.subjects.values():
        assert s.n_observations == 11
        assert s.weight_kg is not None and 50.0 < s.weight_kg < 90.0
        assert 200.0 < s.dose_mg < 400.0
        assert np.all(np.diff(s.time_h) > 0)
        assert np.all(s.concentration_mg_per_L >= 0)


def test_theoph_first_subject_matches_distributed_values():
    """Spot-check against the published data so a corrupted file is caught."""
    s = load_theophylline().subjects["1"]
    assert s.weight_kg == pytest.approx(79.6)
    assert s.dose_mg == pytest.approx(4.02 * 79.6)
    assert s.time_h[0] == pytest.approx(0.0)
    assert s.concentration_mg_per_L[0] == pytest.approx(0.74)
    assert s.time_h[-1] == pytest.approx(24.37)
    assert s.concentration_mg_per_L[-1] == pytest.approx(3.28)


def test_indometh_dataset_integrity():
    ds = load_indomethacin()
    assert len(ds.subjects) == 6
    assert ds.n_observations == 66
    s = ds.subjects["1"]
    assert s.time_h[0] == pytest.approx(0.25)
    assert s.concentration_mg_per_L[0] == pytest.approx(1.5)
    assert s.time_h[-1] == pytest.approx(8.0)


def test_indometh_declares_the_unknown_dose_limitation():
    """The most important caveat about this dataset must be stated loudly."""
    ds = load_indomethacin()
    joined = " ".join(ds.known_limitations).upper()
    assert "DOSE IS NOT PRESENT" in joined or "ABSOLUTE VOLUMES" in joined
    assert all(s.dose_mg == 1.0 for s in ds.subjects.values())


def test_datasets_declare_licences():
    for ds in (load_theophylline(), load_indomethacin()):
        assert "GPL" in ds.license_note
        assert "programmatically" in ds.provenance


def test_unknown_dataset_raises():
    with pytest.raises(KeyError):
        get_dataset("not_a_dataset")


def test_deterministic_split_is_stable_and_disjoint():
    ds = load_theophylline()
    a1, b1 = deterministic_split(ds)
    a2, b2 = deterministic_split(ds)
    assert a1 == a2 and b1 == b2
    assert set(a1).isdisjoint(set(b1))
    assert set(a1) | set(b1) == set(ds.subject_ids)
    assert a1 == ["1", "3", "5", "7", "9", "11"]
    assert b1 == ["2", "4", "6", "8", "10", "12"]


# ===========================================================================
# Validation pipeline
# ===========================================================================
def test_theophylline_validation_held_out_accuracy():
    """Regression test pinning the achieved held-out accuracy.

    These bounds are deliberately loose enough to tolerate solver and platform
    noise but tight enough to catch a real regression. They are NOT targets the
    model was tuned to hit; they record what it achieved.
    """
    r = run_validation("theoph_1cmt_foa")
    m = r.held_out_metrics

    assert m.n == 66
    assert set(r.calibration_subject_ids).isdisjoint(set(r.held_out_subject_ids))

    assert m.absolute_average_fold_error is not None
    assert 1.15 < m.absolute_average_fold_error < 1.45, m.absolute_average_fold_error
    assert m.fraction_within_2_fold is not None
    assert m.fraction_within_2_fold > 0.80, m.fraction_within_2_fold
    assert m.median_absolute_percent_error < 30.0, m.median_absolute_percent_error
    assert m.rmse < 2.5, m.rmse
    assert m.r_squared_vs_identity > 0.5, m.r_squared_vs_identity


def test_theophylline_estimates_agree_with_published_clinical_values():
    """An external sanity check that was NOT used in the estimation.

    Adult theophylline clearance is widely reported near 0.04 L/h/kg and volume
    of distribution near 0.5 L/kg. The estimator saw only the Theoph
    concentrations, so landing in these ranges is independent corroboration.
    """
    r = run_validation("theoph_1cmt_foa")
    cl = r.typical_parameters["CL_per_kg"]
    v = r.typical_parameters["V_per_kg"]
    assert 0.02 < cl < 0.07, f"CL/F {cl:.4f} L/h/kg is outside the reported adult range"
    assert 0.3 < v < 0.75, f"V/F {v:.4f} L/kg is outside the reported adult range"


def test_indomethacin_validation_held_out_accuracy():
    r = run_validation("indometh_2cmt")
    m = r.held_out_metrics
    assert m.n == 33
    assert m.absolute_average_fold_error is not None
    assert 1.15 < m.absolute_average_fold_error < 1.60, m.absolute_average_fold_error
    assert m.fraction_within_2_fold > 0.80
    assert m.r_squared_vs_identity > 0.7


def test_validation_distinguishes_calibration_from_held_out():
    """The pipeline must report both, separately, and never conflate them."""
    r = run_validation("theoph_1cmt_foa")
    assert r.protocol["held_out_data_used_in_estimation"] is False
    assert r.protocol["split_is_deterministic"] is True
    assert r.calibration_metrics.n == 66
    assert r.held_out_metrics.n == 66
    assert "not clinical validation" in r.interpretation
    assert "NOT non-linear mixed-effects" in r.estimation_note


def test_validation_profiles_cover_every_subject():
    r = run_validation("theoph_1cmt_foa")
    assert len(r.profiles) == 12
    sets = {p["set"] for p in r.profiles}
    assert sets == {"calibration", "held_out"}
    for p in r.profiles:
        assert len(p["time_h"]) == len(p["predicted"])
        assert len(p["observed_time_h"]) == len(p["observed"]) == 11
        assert all(np.isfinite(p["predicted"]))


def test_validation_reports_poorly_estimated_subjects():
    """Subject 1 has a non-zero concentration at t=0, which the model cannot fit.

    The pipeline must surface that rather than quietly averaging it away.
    """
    r = run_validation("theoph_1cmt_foa")
    assert r.warnings, "Expected warnings about poorly estimated subjects"
    assert any("subject 1" in w for w in r.warnings)


def test_unknown_validation_target_raises():
    with pytest.raises(KeyError):
        run_validation("no_such_target")


# ===========================================================================
# API: library endpoints
# ===========================================================================
def test_health_and_meta(client):
    assert client.get("/health").status_code == 200
    m = client.get("/api/meta").json()
    assert m["regulatory_status"]["fda_cleared"] is False
    assert m["regulatory_status"]["hipaa_compliant"] is False
    assert "Not a medical device" in m["classification"]
    assert m["counts"]["models"] >= 4
    assert m["counts"]["references"] >= 20


def test_models_endpoint_exposes_schema(client):
    models = client.get("/api/models").json()["models"]
    ids = {m["model_id"] for m in models}
    assert {"pk_1cmt_foa", "pk_2cmt", "pk_1cmt_mm", "pbpk_perfusion_limited"} <= ids
    for m in models:
        assert m["parameters"], m["model_id"]
        assert m["observables"], m["model_id"]
        assert m["validation_status"] in {
            "independently_validated", "calibrated_only", "structurally_verified",
            "research_only", "not_validated",
        }
        # Every parameter must declare a range the UI can bind a control to.
        for p in m["parameters"]:
            assert p["minimum"] < p["maximum"]
            assert p["minimum"] <= p["default"] <= p["maximum"]
        assert sum(1 for o in m["observables"] if o["is_primary"]) == 1


def test_every_model_reference_resolves(client):
    """A dangling citation is worse than no citation."""
    refs = {r["id"] for r in client.get("/api/references").json()["references"]}
    for m in client.get("/api/models").json()["models"]:
        for rid in m["reference_ids"]:
            assert rid in refs, f"{m['model_id']} cites missing reference {rid}"


def test_drug_parameters_all_declare_origin(client):
    """The core research-integrity invariant of the whole platform."""
    legal = {
        "measured", "fitted", "literature_fitted", "derived",
        "inferred", "illustrative", "user",
    }
    for drug in client.get("/api/drugs").json()["drugs"]:
        for model_id, block in (drug.get("pk_parameters") or {}).items():
            for name, entry in (block.get("values") or {}).items():
                assert "origin" in entry, f"{drug['drug_id']}.{model_id}.{name}"
                assert entry["origin"] in legal, entry["origin"]
                assert "value" in entry and "unit" in entry


def test_fitted_drug_parameters_name_their_dataset(client):
    """A `fitted` claim must say what it was fitted to, or it is unverifiable."""
    for drug in client.get("/api/drugs").json()["drugs"]:
        for block in (drug.get("pk_parameters") or {}).values():
            for name, entry in (block.get("values") or {}).items():
                if entry["origin"] == "fitted":
                    assert entry.get("fitted_from_dataset"), name
                    assert entry.get("fitted_from_subjects"), name


def test_synthetic_demo_drug_is_clearly_flagged(client):
    d = client.get("/api/drugs/nonlinear_demo").json()
    assert d["is_synthetic_demonstration"] is True
    assert "NOT A REAL DRUG" in d["validation_note"].upper()
    assert d["validation_status"] == "not_validated"


def test_reference_search_and_detail(client):
    r = client.get("/api/references?q=theophylline").json()
    assert r["n_matched"] >= 1
    assert r["n_matched"] <= r["n_total"]
    d = client.get("/api/references/cockcroft1976").json()
    assert d["pmid"] == "1244564"
    assert d["doi"] == "10.1159/000180580"
    assert client.get("/api/references/does_not_exist").status_code == 404


def test_references_declare_access_honestly(client):
    """Every reference must state whether its full text was actually retrieved."""
    for r in client.get("/api/references").json()["references"]:
        assert r.get("access_note"), r["id"]
        assert r.get("license_note"), r["id"]


def test_physiology_endpoint(client):
    p = client.get("/api/physiology").json()
    assert "GPL-3" in p["provenance"]["source_license"]
    co = p["whole_body"]["cardiac_output_L_per_h_sum_of_modelled_flows"]
    assert 240.0 < co < 540.0  # 4-9 L/min
    assert len(p["tissues"]) == 12
    assert any(t["composition_is_borrowed"] for t in p["tissues"])


def test_datasets_endpoint(client):
    ds = client.get("/api/datasets").json()["datasets"]
    assert {d["dataset_id"] for d in ds} == {"theoph", "indometh"}
    detail = client.get("/api/datasets/theoph").json()
    assert len(detail["observations"]) == 12
    assert client.get("/api/datasets/nope").status_code == 404


# ===========================================================================
# API: patients
# ===========================================================================
def test_patient_lifecycle(client):
    body = {
        "label": "Test subject", "age_years": 45, "weight_kg": 80,
        "height_cm": 180, "sex": "male", "serum_creatinine_mg_dL": 1.0,
    }
    created = client.post("/api/patients", json=body)
    assert created.status_code == 201
    pid = created.json()["id"]
    assert created.json()["is_synthetic"] is True
    assert created.json()["derived"]["creatinine_clearance_cockcroft_gault_mL_min"] > 0

    updated = client.put(f"/api/patients/{pid}", json={**body, "weight_kg": 95})
    assert updated.status_code == 200
    assert updated.json()["weight_kg"] == 95

    assert client.delete(f"/api/patients/{pid}").status_code == 204
    assert client.put(f"/api/patients/{pid}", json=body).status_code == 404


def test_patient_cannot_be_marked_non_synthetic(client):
    """A hard guard: the API must refuse to store something claiming to be real."""
    r = client.post("/api/patients", json={"label": "Real person", "is_synthetic": False})
    assert r.status_code == 422


def test_patient_rejects_implausible_physiology(client):
    assert client.post("/api/patients", json={"label": "x", "age_years": 500}).status_code == 422
    assert client.post("/api/patients", json={"label": "x", "weight_kg": 0.1}).status_code == 422


def test_patient_preview_lists_its_equations(client):
    r = client.post(
        "/api/patients/preview",
        json={"label": "p", "weight_kg": 70, "height_cm": 175, "age_years": 40},
    ).json()
    names = {e["name"] for e in r["equations"]}
    assert {"Body surface area", "Creatinine clearance", "eGFR"} <= names
    assert all(e.get("citation") for e in r["equations"])
    assert any("not a patient record" in c for c in r["caveats"])


def test_patient_deletion_blocked_while_referenced(client):
    pid = client.post("/api/patients", json={"label": "Referenced", "weight_kg": 70}).json()["id"]
    sim = client.post("/api/simulate", json={
        "label": "ref run", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "patient_id": pid, "simulation_horizon_h": 24,
        "regimen": {"route": "oral", "dose_mg": 300},
    })
    assert sim.status_code == 200
    assert client.delete(f"/api/patients/{pid}").status_code == 409


# ===========================================================================
# API: simulation
# ===========================================================================
def test_simulate_theophylline_produces_plausible_exposure(client):
    r = client.post("/api/simulate", json={
        "label": "Theo 300 mg PO", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 300.0, "n_doses": 1},
        "simulation_horizon_h": 25.0, "persist": False,
    })
    assert r.status_code == 200
    j = r.json()
    nca = j["nca"]
    # Dose/V with V ~ 0.46 L/kg * 70 kg = 32 L gives Cmax of order 7-10 mg/L.
    assert 4.0 < nca["cmax"] < 12.0, nca["cmax"]
    assert 0.5 < nca["tmax_h"] < 4.0, nca["tmax_h"]
    assert 4.0 < nca["terminal_half_life_h"] < 14.0, nca["terminal_half_life_h"]
    assert j["diagnostics"]["mass_balance_relative_error"] < 1e-6
    assert j["diagnostics"]["success"] is True
    assert j["validation_status"] == "independently_validated"
    assert "not a medical device" in j["disclaimer"].lower()


def test_simulate_records_full_provenance(client):
    j = client.post("/api/simulate", json={
        "label": "prov", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 24.0,
        "persist": False,
    }).json()
    p = j["provenance"]
    for key in (
        "model_id", "model_version", "software_version", "engine_revision",
        "timestamp_utc", "parameters", "assumptions", "limitations",
        "reference_ids", "validation_status", "solver", "input_hash", "record_hash",
    ):
        assert key in p, key
    assert p["input_hash"].startswith("sha256:")
    assert p["record_hash"].startswith("sha256:")
    assert p["parameters"], "Parameter provenance must not be empty"
    for param in p["parameters"]:
        assert param["origin"] in {
            "measured", "fitted", "literature_fitted", "derived",
            "inferred", "illustrative", "user",
        }


def test_identical_requests_produce_identical_hashes(client):
    body = {
        "label": "hash", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 24.0,
        "persist": False,
    }
    a = client.post("/api/simulate", json=body).json()["provenance"]["input_hash"]
    b = client.post("/api/simulate", json=body).json()["provenance"]["input_hash"]
    c = client.post(
        "/api/simulate", json={**body, "regimen": {"route": "oral", "dose_mg": 301.0}}
    ).json()["provenance"]["input_hash"]
    assert a == b
    assert a != c


def test_simulate_rejects_unknown_model_and_parameters(client):
    assert client.post("/api/simulate", json={
        "label": "x", "model_id": "no_such_model", "simulation_horizon_h": 24,
    }).status_code in (400, 404, 422)
    r = client.post("/api/simulate", json={
        "label": "x", "model_id": "pk_1cmt_foa", "parameters": {"Nonsense": 1.0},
        "simulation_horizon_h": 24, "persist": False,
    })
    assert r.status_code == 400
    assert "Nonsense" in r.text


def test_simulate_rejects_out_of_range_parameter(client):
    r = client.post("/api/simulate", json={
        "label": "x", "model_id": "pk_1cmt_foa", "parameters": {"CL": 1e9},
        "simulation_horizon_h": 24, "persist": False,
    })
    assert r.status_code in (400, 422)


def test_simulate_rejects_unsupported_route(client):
    r = client.post("/api/simulate", json={
        "label": "x", "model_id": "pk_1cmt_foa", "simulation_horizon_h": 24,
        "regimen": {"route": "iv_infusion", "dose_mg": 100.0, "infusion_duration_h": 0.0},
        "persist": False,
    })
    assert r.status_code == 422


def test_simulate_rejects_dose_beyond_horizon(client):
    r = client.post("/api/simulate", json={
        "label": "x", "model_id": "pk_1cmt_foa", "simulation_horizon_h": 24,
        "regimen": {"route": "oral", "dose_mg": 100.0, "n_doses": 10, "interval_h": 12},
        "persist": False,
    })
    assert r.status_code == 422


def test_patient_covariates_change_the_answer(client):
    smoker = client.post("/api/patients", json={
        "label": "Smoker", "weight_kg": 70, "smoking_status": "smoker",
    }).json()["id"]
    nonsmoker = client.post("/api/patients", json={
        "label": "Non-smoker", "weight_kg": 70, "smoking_status": "non_smoker",
    }).json()["id"]
    body = {
        "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 48.0,
        "persist": False,
    }
    a = client.post("/api/simulate", json={**body, "label": "s", "patient_id": smoker}).json()
    b = client.post("/api/simulate", json={**body, "label": "n", "patient_id": nonsmoker}).json()
    # Induced clearance -> lower exposure.
    assert a["nca"]["auc_0_last"] < b["nca"]["auc_0_last"]
    assert a["effective_parameters"]["CL"] > b["effective_parameters"]["CL"]
    # And the adjustment must be labelled as inferred, not measured.
    origins = {c["origin"] for c in a["covariates_applied"]}
    assert origins <= {"derived", "inferred", "illustrative"}


def test_comparison_and_exposure_table(client):
    base = {
        "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "simulation_horizon_h": 84.0, "persist": False,
    }
    r = client.post("/api/simulate/compare", json={"label": "cmp", "scenarios": [
        {**base, "label": "200 q12h", "regimen": {"route": "oral", "dose_mg": 200, "n_doses": 6, "interval_h": 12}},
        {**base, "label": "400 q12h", "regimen": {"route": "oral", "dose_mg": 400, "n_doses": 6, "interval_h": 12}},
    ]})
    assert r.status_code == 200
    table = r.json()["exposure_table"]
    assert len(table) == 2
    # Linear model: doubling the dose must double exposure.
    assert table[1]["auc_ratio_vs_baseline"] == pytest.approx(2.0, rel=1e-3)
    assert table[1]["cmax_ratio_vs_baseline"] == pytest.approx(2.0, rel=1e-3)
    # The AUC window must be reported so the column is interpretable.
    assert table[0]["auc_window_h"] == [60.0, 72.0]
    assert table[0]["accumulation_ratio_auc"] > 1.0


def test_comparison_rejects_duplicate_labels(client):
    s = {
        "label": "same", "model_id": "pk_1cmt_foa", "simulation_horizon_h": 24.0,
        "regimen": {"route": "oral", "dose_mg": 100.0}, "persist": False,
    }
    assert client.post(
        "/api/simulate/compare", json={"label": "c", "scenarios": [s, dict(s)]}
    ).status_code == 422


def test_nonlinear_model_shows_supraproportional_exposure(client):
    base = {
        "model_id": "pk_1cmt_mm", "drug_id": "nonlinear_demo",
        "simulation_horizon_h": 120.0, "persist": False,
    }
    r = client.post("/api/simulate/compare", json={"label": "nl", "scenarios": [
        {**base, "label": "low", "regimen": {"route": "oral", "dose_mg": 200, "n_doses": 6, "interval_h": 12}},
        {**base, "label": "high", "regimen": {"route": "oral", "dose_mg": 300, "n_doses": 6, "interval_h": 12}},
    ]}).json()
    ratio = r["exposure_table"][1]["auc_ratio_vs_baseline"]
    # A 1.5x dose increase must produce more than 1.5x exposure.
    assert ratio > 1.6, ratio


def test_population_simulation(client):
    r = client.post("/api/simulate/population", json={
        "label": "pop", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 25.0,
        "n_subjects": 60, "seed": 1234,
        "random_effects": [
            {"parameter": "CL", "cv_percent": 40.0},
            {"parameter": "V", "cv_percent": 18.0},
        ],
        "persist": False,
    })
    assert r.status_code == 200
    j = r.json()
    assert j["result"]["n_subjects_simulated"] == 60
    assert j["result"]["n_failures"] == 0
    p = j["result"]["structural_percentiles"]
    assert np.all(np.array(p["p5"]) <= np.array(p["p95"]) + 1e-12)
    cm = j["exposure_distribution"]["cmax"]
    assert cm["p5"] < cm["median"] < cm["p95"]
    assert j["target_attainment"]["n"] == 60
    assert "not confidence intervals" in j["result"]["interpretation"].lower()


def test_population_requires_a_random_effect(client):
    r = client.post("/api/simulate/population", json={
        "label": "pop", "model_id": "pk_1cmt_foa", "simulation_horizon_h": 24.0,
        "random_effects": [], "persist": False,
    })
    assert r.status_code == 422


def test_population_rejects_random_effect_on_missing_parameter(client):
    r = client.post("/api/simulate/population", json={
        "label": "pop", "model_id": "pk_1cmt_foa", "simulation_horizon_h": 24.0,
        "random_effects": [{"parameter": "Vmax", "cv_percent": 30.0}], "persist": False,
    })
    assert r.status_code == 400


def test_population_is_reproducible_via_seed(client):
    body = {
        "label": "seeded", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 24.0,
        "n_subjects": 25, "seed": 777,
        "random_effects": [{"parameter": "CL", "cv_percent": 35.0}], "persist": False,
    }
    a = client.post("/api/simulate/population", json=body).json()
    b = client.post("/api/simulate/population", json=body).json()
    assert a["result"]["structural_percentiles"] == b["result"]["structural_percentiles"]


@pytest.mark.parametrize("method", ["local", "morris", "sobol"])
def test_sensitivity_identifies_clearance_as_dominant(client, method):
    """For AUC after an oral dose, clearance must dominate. If it does not, the
    sensitivity machinery is wired up wrong."""
    extra = {"morris_trajectories": 12} if method == "morris" else (
        {"sobol_base_samples": 64} if method == "sobol" else {}
    )
    r = client.post("/api/simulate/sensitivity", json={
        "label": f"sa-{method}", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 48.0,
        "method": method, "metric": "auc_0_last",
        "targets": [{"name": "CL"}, {"name": "V"}, {"name": "ka"}],
        **extra,
    })
    assert r.status_code == 200, r.text
    rows = r.json()["analysis"]["results"]
    assert rows[0]["parameter"] == "CL", [x["parameter"] for x in rows]
    assert r.json()["n_model_evaluations"] > 0


def test_local_sensitivity_sign_is_correct(client):
    """Higher clearance must lower AUC: the coefficient must be negative."""
    r = client.post("/api/simulate/sensitivity", json={
        "label": "signs", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 48.0,
        "method": "local", "metric": "auc_0_last",
        "targets": [{"name": "CL"}],
    }).json()
    assert r["analysis"]["results"][0]["normalised_sensitivity"] < 0


def test_sensitivity_rejects_unknown_parameter(client):
    r = client.post("/api/simulate/sensitivity", json={
        "label": "bad", "model_id": "pk_1cmt_foa", "simulation_horizon_h": 24.0,
        "method": "local", "targets": [{"name": "NotAParameter"}],
    })
    assert r.status_code == 400


# ===========================================================================
# API: persistence, reproduction, reports
# ===========================================================================
def test_experiment_and_simulation_persistence(client):
    eid = client.post("/api/experiments", json={
        "name": "Persistence test", "description": "d", "tags": ["t"],
    }).json()["id"]

    sid = client.post("/api/simulate", json={
        "label": "stored", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 24.0,
        "experiment_id": eid,
    }).json()["simulation_id"]
    assert sid is not None

    listed = client.get(f"/api/simulations?experiment_id={eid}").json()
    assert any(s["id"] == sid for s in listed)
    assert listed[0]["key_metrics"]["cmax"] > 0

    detail = client.get(f"/api/simulations/{sid}").json()
    assert detail["request"]["label"] == "stored"
    assert detail["provenance"]["input_hash"].startswith("sha256:")

    dup = client.post(f"/api/simulations/{sid}/duplicate?label=copy").json()
    assert dup["label"] == "copy"
    assert dup["simulation_id"] != sid

    assert client.get("/api/experiments").json()
    assert client.delete(f"/api/experiments/{eid}").status_code == 204
    # Cascade must remove the simulations too.
    assert client.get(f"/api/simulations/{sid}").status_code == 404


def test_reproduction_is_exact(client):
    sid = client.post("/api/simulate", json={
        "label": "repro", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 275.0, "n_doses": 3, "interval_h": 8},
        "simulation_horizon_h": 48.0,
    }).json()["simulation_id"]
    r = client.post(f"/api/simulations/{sid}/reproduce").json()
    assert r["input_hash_matches"] is True
    assert r["engine_revision_matches"] is True
    assert r["max_absolute_curve_difference"] == 0.0
    assert r["bitwise_identical"] is True
    assert "Exactly reproduced" in r["verdict"]


def test_report_generation_includes_provenance_and_limitations(client):
    sid = client.post("/api/simulate", json={
        "label": "report run", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 25.0,
    }).json()["simulation_id"]
    r = client.post("/api/reports", json={
        "simulation_ids": [sid], "title": "Test report", "author": "Tester",
        "format": "markdown",
    })
    assert r.status_code == 200
    md = r.json()["markdown"]
    for expected in (
        "Test report", "Parameter provenance", "Exposure metrics",
        "Solver diagnostics", "Limitations", "References",
        "not a medical device", "Independent validation",
    ):
        assert expected in md, f"Report missing {expected!r}"
    # Citations must carry identifiers.
    assert "PMID" in md


def test_report_json_format(client):
    sid = client.post("/api/simulate", json={
        "label": "json report", "model_id": "pk_1cmt_foa",
        "regimen": {"route": "oral", "dose_mg": 100.0}, "simulation_horizon_h": 24.0,
    }).json()["simulation_id"]
    j = client.post("/api/reports", json={
        "simulation_ids": [sid], "title": "J", "format": "json",
    }).json()
    assert j["simulations"][0]["id"] == sid
    assert "disclaimer" in j


def test_report_rejects_missing_simulation(client):
    assert client.post("/api/reports", json={
        "simulation_ids": [999999], "title": "x",
    }).status_code == 404


def test_audit_log_records_actions(client):
    client.post("/api/patients", json={"label": "Audited", "weight_kg": 70})
    log = client.get("/api/audit").json()
    assert log["entries"]
    assert any(e["action"] == "patient.create" for e in log["entries"])
    assert "not a tamper-proof ledger" in log["note"]


def test_validation_endpoints(client):
    t = client.get("/api/validation/targets").json()
    assert len(t["targets"]) >= 2
    assert "Only the held-out numbers" in t["protocol"]["why_it_matters"]

    v = client.get("/api/validation/theoph_1cmt_foa").json()
    assert v["held_out_metrics"]["n"] == 66

    p = client.get("/api/validation/pbpk/structural-check").json()
    assert p["validation_status"] == "research_only"
    assert p["passes_2_fold"] is True
    assert "only external check" in p["honest_scope"]
    assert 0.25 < p["predicted_vss_L_per_kg"] < 1.0

    assert client.get("/api/validation/nope").status_code == 404


# ===========================================================================
# Provenance origin accuracy
# ===========================================================================
def test_library_parameters_are_tagged_fitted_not_user(client):
    """The provenance record must say where a value really came from.

    A model instance receives plain numbers and cannot know their pedigree, so
    the service re-tags them. Without that, a fitted estimate would be reported
    as operator-supplied, understating its evidence, and a SYNTHBODY default
    would be reported the same way, hiding that it is not evidence at all.
    """
    j = client.post("/api/simulate", json={
        "label": "origins", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 25.0,
        "persist": False,
    }).json()
    by_name = {p["name"]: p for p in j["provenance"]["parameters"]}

    # CL, V and ka come from the fitted library block.
    for name in ("CL", "V", "ka"):
        assert by_name[name]["origin"] == "fitted", (name, by_name[name]["origin"])
        assert by_name[name]["reference_ids"], f"{name} must carry its citations"
    assert "theoph" in by_name["CL"]["notes"] or "0.04 L/h/kg" in by_name["CL"]["notes"]
    # The ka caveat must travel with the parameter, not just live in the UI.
    assert "121%" in by_name["ka"]["notes"]

    # Bioavailability is fixed structurally and is explicitly not evidence.
    assert by_name["F"]["origin"] == "illustrative"
    # Derived quantities keep their derived tag.
    assert by_name["ke"]["origin"] == "derived"
    assert by_name["t_half"]["origin"] == "derived"


def test_user_override_is_tagged_user(client):
    j = client.post("/api/simulate", json={
        "label": "override", "model_id": "pk_1cmt_foa", "drug_id": "theophylline",
        "parameters": {"CL": 4.0},
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 25.0,
        "persist": False,
    }).json()
    by_name = {p["name"]: p for p in j["provenance"]["parameters"]}
    assert by_name["CL"]["origin"] == "user"
    assert by_name["CL"]["value"] == pytest.approx(4.0)
    # The parameters that were not overridden keep their library pedigree.
    assert by_name["V"]["origin"] == "fitted"


def test_schema_defaults_are_tagged_illustrative(client):
    """With no compound selected, every value is a SYNTHBODY default."""
    j = client.post("/api/simulate", json={
        "label": "raw", "model_id": "pk_1cmt_foa",
        "regimen": {"route": "oral", "dose_mg": 300.0}, "simulation_horizon_h": 25.0,
        "persist": False,
    }).json()
    by_name = {p["name"]: p for p in j["provenance"]["parameters"]}
    for name in ("CL", "V", "ka", "F"):
        assert by_name[name]["origin"] == "illustrative", name
        assert "schema default" in by_name[name]["notes"]


def test_synthetic_drug_parameters_are_never_tagged_measured(client):
    """A guard against the demo compound ever appearing evidence-backed."""
    j = client.post("/api/simulate", json={
        "label": "synthetic", "model_id": "pk_1cmt_mm", "drug_id": "nonlinear_demo",
        "regimen": {"route": "oral", "dose_mg": 200.0}, "simulation_horizon_h": 48.0,
        "persist": False,
    }).json()
    origins = {p["origin"] for p in j["provenance"]["parameters"]}
    assert "measured" not in origins
    assert "fitted" not in origins
    assert "illustrative" in origins
