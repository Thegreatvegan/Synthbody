"""Patients, experiments, stored simulations, validation and reports."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from synthbody.api.service import DISCLAIMER, ServiceError, row_to_patient, run_simulation
from synthbody.db.models import AuditLogRow, ExperimentRow, SimulationRow, VirtualPatientRow
from synthbody.db.session import get_session
from synthbody.engine.analysis.validation import build_targets, run_validation
from synthbody.engine.models.pbpk import PerfusionLimitedPBPK
from synthbody.engine.physiology.partition import DrugPhysChem
from synthbody.engine.registry import drug_library, get_model_spec, reference_library
from synthbody.schemas.api import (
    ExperimentIn,
    ExperimentOut,
    ReportRequest,
    SimulationRequest,
    SimulationSummaryOut,
    VirtualPatientIn,
    VirtualPatientOut,
)
from synthbody.version import ENGINE_REVISION, SOFTWARE_VERSION

router = APIRouter(tags=["workspace"])


def _iso(dt) -> str:
    return dt.isoformat() if dt else ""


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
def _patient_out(row: VirtualPatientRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "label": row.label,
        "is_synthetic": row.is_synthetic,
        "age_years": row.age_years,
        "weight_kg": row.weight_kg,
        "height_cm": row.height_cm,
        "sex": row.sex,
        "serum_creatinine_mg_dL": row.serum_creatinine_mg_dL,
        "albumin_g_dL": row.albumin_g_dL,
        "hepatic_function": row.hepatic_function,
        "smoking_status": row.smoking_status,
        "notes": row.notes,
        "derived": row.derived,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


@router.get("/patients", response_model=list[VirtualPatientOut])
def list_patients(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.scalars(select(VirtualPatientRow).order_by(desc(VirtualPatientRow.id))).all()
    return [_patient_out(r) for r in rows]


@router.post("/patients", response_model=VirtualPatientOut, status_code=201)
def create_patient(
    body: VirtualPatientIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    row = VirtualPatientRow(
        label=body.label,
        is_synthetic=True,
        age_years=body.age_years,
        weight_kg=body.weight_kg,
        height_cm=body.height_cm,
        sex=body.sex,
        serum_creatinine_mg_dL=body.serum_creatinine_mg_dL,
        albumin_g_dL=body.albumin_g_dL,
        hepatic_function=body.hepatic_function,
        smoking_status=body.smoking_status,
        notes=body.notes,
        derived={},
    )
    try:
        row.derived = row_to_patient(row).summary()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.add(row)
    session.add(
        AuditLogRow(
            action="patient.create",
            entity="virtual_patient",
            detail={"label": body.label},
            software_version=SOFTWARE_VERSION,
        )
    )
    session.commit()
    return _patient_out(row)


@router.put("/patients/{patient_id}", response_model=VirtualPatientOut)
def update_patient(
    patient_id: int, body: VirtualPatientIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    row = session.get(VirtualPatientRow, patient_id)
    if row is None:
        raise HTTPException(404, f"No virtual patient with id {patient_id}.")
    for field in (
        "label", "age_years", "weight_kg", "height_cm", "sex",
        "serum_creatinine_mg_dL", "albumin_g_dL", "hepatic_function",
        "smoking_status", "notes",
    ):
        setattr(row, field, getattr(body, field))
    try:
        row.derived = row_to_patient(row).summary()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return _patient_out(row)


@router.delete("/patients/{patient_id}", status_code=204, response_class=Response, response_model=None)
def delete_patient(patient_id: int, session: Session = Depends(get_session)) -> None:
    row = session.get(VirtualPatientRow, patient_id)
    if row is None:
        raise HTTPException(404, f"No virtual patient with id {patient_id}.")
    n = session.scalar(
        select(func.count()).select_from(SimulationRow).where(SimulationRow.patient_id == patient_id)
    )
    if n:
        raise HTTPException(
            409,
            f"This virtual patient is referenced by {n} stored simulation(s). Deleting it would "
            "break their reproducibility. Delete those simulations first if you really mean to.",
        )
    session.delete(row)
    session.commit()


@router.post("/patients/preview")
def preview_patient(body: VirtualPatientIn) -> dict[str, Any]:
    """Compute derived physiology without storing anything.

    Lets the Patient Builder show live BSA/eGFR/FFM as sliders move.
    """
    tmp = VirtualPatientRow(
        label=body.label, age_years=body.age_years, weight_kg=body.weight_kg,
        height_cm=body.height_cm, sex=body.sex,
        serum_creatinine_mg_dL=body.serum_creatinine_mg_dL,
        albumin_g_dL=body.albumin_g_dL, hepatic_function=body.hepatic_function,
        smoking_status=body.smoking_status, notes=body.notes, derived={},
    )
    try:
        return {
            "derived": row_to_patient(tmp).summary(),
            "equations": [
                {"name": "Body surface area", "citation": "Du Bois & Du Bois (1916)",
                 "formula": "0.007184 * height_cm^0.725 * weight_kg^0.425", "origin": "derived"},
                {"name": "Creatinine clearance", "citation": "Cockcroft & Gault (1976), PMID 1244564",
                 "formula": "((140-age)*weight)/(72*Scr), x0.85 if female", "origin": "derived",
                 "reference_id": "cockcroft1976"},
                {"name": "eGFR", "citation": "CKD-EPI 2021 (Inker et al.), PMID 34554658",
                 "formula": "142 * min(Scr/k,1)^a * max(Scr/k,1)^-1.200 * 0.9938^age * s",
                 "origin": "literature_fitted", "reference_id": "inker2021"},
                {"name": "Fat-free mass", "citation": "Janmahasatian et al. (2005)",
                 "formula": "sex-specific function of weight and BMI", "origin": "derived",
                 "note": "Displayed only; the PK models in this release scale on total body weight."},
                {"name": "Ideal body weight", "citation": "Devine (1974)",
                 "formula": "50 (male) or 45.5 (female) + 2.3 * (height_in - 60)", "origin": "derived"},
            ],
            "caveats": [
                "Cockcroft-Gault uses total body weight and overestimates clearance in obesity.",
                "The sex coefficient in these equations is binary because the published equations "
                "are. That is a limitation of the equations, not a statement about the subject.",
                "This is a hypothetical simulated subject, not a patient record.",
            ],
        }
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------
def _experiment_out(row: ExperimentRow, n: int) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "tags": row.tags,
        "n_simulations": n,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


@router.get("/experiments", response_model=list[ExperimentOut])
def list_experiments(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.scalars(select(ExperimentRow).order_by(desc(ExperimentRow.id))).all()
    counts = dict(
        session.execute(
            select(SimulationRow.experiment_id, func.count()).group_by(SimulationRow.experiment_id)
        ).all()
    )
    return [_experiment_out(r, counts.get(r.id, 0)) for r in rows]


@router.post("/experiments", response_model=ExperimentOut, status_code=201)
def create_experiment(
    body: ExperimentIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    row = ExperimentRow(name=body.name, description=body.description, tags=body.tags)
    session.add(row)
    session.commit()
    return _experiment_out(row, 0)


@router.put("/experiments/{experiment_id}", response_model=ExperimentOut)
def update_experiment(
    experiment_id: int, body: ExperimentIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    row = session.get(ExperimentRow, experiment_id)
    if row is None:
        raise HTTPException(404, f"No experiment with id {experiment_id}.")
    row.name, row.description, row.tags = body.name, body.description, body.tags
    session.commit()
    n = session.scalar(
        select(func.count()).select_from(SimulationRow).where(
            SimulationRow.experiment_id == experiment_id
        )
    )
    return _experiment_out(row, n or 0)


@router.delete("/experiments/{experiment_id}", status_code=204, response_class=Response, response_model=None)
def delete_experiment(experiment_id: int, session: Session = Depends(get_session)) -> None:
    row = session.get(ExperimentRow, experiment_id)
    if row is None:
        raise HTTPException(404, f"No experiment with id {experiment_id}.")
    session.delete(row)  # cascades to its simulations
    session.add(
        AuditLogRow(
            action="experiment.delete",
            entity="experiment",
            entity_id=str(experiment_id),
            detail={"name": row.name},
            software_version=SOFTWARE_VERSION,
        )
    )
    session.commit()


# ---------------------------------------------------------------------------
# Stored simulations
# ---------------------------------------------------------------------------
def _key_metrics(row: SimulationRow) -> dict[str, Any]:
    r = row.result or {}
    nca = r.get("nca") or {}
    if row.kind == "population":
        ms = (r.get("metric_summary") or {}).get("cmax") or {}
        return {
            "n_subjects": r.get("n_subjects_simulated"),
            "cmax_median": ms.get("median"),
            "cmax_p5": ms.get("p5"),
            "cmax_p95": ms.get("p95"),
        }
    return {
        "cmax": nca.get("cmax"),
        "tmax_h": nca.get("tmax_h"),
        "auc_0_last": nca.get("auc_0_last"),
        "terminal_half_life_h": nca.get("terminal_half_life_h"),
    }


@router.get("/simulations", response_model=list[SimulationSummaryOut])
def list_simulations(
    experiment_id: int | None = None,
    model_id: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(SimulationRow).order_by(desc(SimulationRow.id)).limit(limit)
    if experiment_id is not None:
        stmt = stmt.where(SimulationRow.experiment_id == experiment_id)
    if model_id is not None:
        stmt = stmt.where(SimulationRow.model_id == model_id)
    rows = session.scalars(stmt).all()
    return [
        {
            "id": r.id,
            "experiment_id": r.experiment_id,
            "patient_id": r.patient_id,
            "label": r.label,
            "model_id": r.model_id,
            "drug_id": r.drug_id,
            "kind": r.kind,
            "input_hash": r.input_hash,
            "record_hash": r.record_hash,
            "validation_status": r.validation_status,
            "software_version": r.software_version,
            "engine_revision": r.engine_revision,
            "solver_success": r.solver_success,
            "solver_warning_count": r.solver_warning_count,
            "wall_time_s": r.wall_time_s,
            "created_at": _iso(r.created_at),
            "key_metrics": _key_metrics(r),
        }
        for r in rows
    ]


@router.get("/simulations/{simulation_id}")
def get_simulation(simulation_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    row = session.get(SimulationRow, simulation_id)
    if row is None:
        raise HTTPException(404, f"No simulation with id {simulation_id}.")
    return {
        "id": row.id,
        "experiment_id": row.experiment_id,
        "patient_id": row.patient_id,
        "label": row.label,
        "model_id": row.model_id,
        "drug_id": row.drug_id,
        "kind": row.kind,
        "request": row.request,
        "provenance": row.provenance,
        "result": row.result,
        "input_hash": row.input_hash,
        "record_hash": row.record_hash,
        "validation_status": row.validation_status,
        "created_at": _iso(row.created_at),
        "disclaimer": DISCLAIMER,
    }


@router.post("/simulations/{simulation_id}/reproduce")
def reproduce_simulation(
    simulation_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Re-run a stored simulation from its saved request and compare the hashes.

    This is the concrete, achievable part of the white paper's deterministic
    re-execution requirement: same inputs, same engine revision, same hash.
    """
    row = session.get(SimulationRow, simulation_id)
    if row is None:
        raise HTTPException(404, f"No simulation with id {simulation_id}.")
    if row.kind != "deterministic":
        raise HTTPException(
            400, f"Reproduction is implemented for deterministic runs; this one is {row.kind!r}."
        )
    try:
        req = SimulationRequest(**{**row.request, "persist": False})
        fresh = run_simulation(req, session)
    except (ServiceError, ValueError) as exc:
        raise HTTPException(422, f"Could not reproduce: {exc}") from exc

    same_input = fresh["provenance"]["input_hash"] == row.input_hash
    same_engine = fresh["provenance"]["engine_revision"] == row.engine_revision
    orig_curve = (row.result or {}).get("primary_curve") or []
    new_curve = fresh["observables"].get(fresh["primary_observable"], [])
    max_abs_diff = None
    if orig_curve and len(orig_curve) == len(new_curve):
        max_abs_diff = max(abs(a - b) for a, b in zip(orig_curve, new_curve))

    return {
        "simulation_id": simulation_id,
        "input_hash_original": row.input_hash,
        "input_hash_reproduced": fresh["provenance"]["input_hash"],
        "input_hash_matches": same_input,
        "engine_revision_original": row.engine_revision,
        "engine_revision_now": fresh["provenance"]["engine_revision"],
        "engine_revision_matches": same_engine,
        "max_absolute_curve_difference": max_abs_diff,
        "bitwise_identical": bool(max_abs_diff == 0) if max_abs_diff is not None else None,
        "verdict": (
            "Exactly reproduced."
            if same_input and same_engine and max_abs_diff == 0
            else "Differences detected - see the fields above."
        ),
        "result": fresh,
    }


@router.post("/simulations/{simulation_id}/duplicate")
def duplicate_simulation(
    simulation_id: int,
    label: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    row = session.get(SimulationRow, simulation_id)
    if row is None:
        raise HTTPException(404, f"No simulation with id {simulation_id}.")
    req_dict = {**row.request, "label": label or f"{row.label} (copy)", "persist": True}
    try:
        return run_simulation(SimulationRequest(**req_dict), session)
    except (ServiceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/simulations/{simulation_id}", status_code=204, response_class=Response, response_model=None)
def delete_simulation(simulation_id: int, session: Session = Depends(get_session)) -> None:
    row = session.get(SimulationRow, simulation_id)
    if row is None:
        raise HTTPException(404, f"No simulation with id {simulation_id}.")
    session.delete(row)
    session.commit()


@router.get("/audit")
def audit_log(
    limit: int = Query(200, ge=1, le=2000), session: Session = Depends(get_session)
) -> dict[str, Any]:
    rows = session.scalars(
        select(AuditLogRow).order_by(desc(AuditLogRow.id)).limit(limit)
    ).all()
    return {
        "entries": [
            {
                "id": r.id,
                "at": _iso(r.at),
                "action": r.action,
                "entity": r.entity,
                "entity_id": r.entity_id,
                "detail": r.detail,
                "software_version": r.software_version,
            }
            for r in rows
        ],
        "note": (
            "An append-only record of state-changing actions. This supports reconstructing "
            "what was run; it is not a tamper-proof ledger and SYNTHBODY does not claim to be one."
        ),
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
@router.get("/validation/targets")
def validation_targets() -> dict[str, Any]:
    return {
        "targets": [
            {
                "target_id": t.target_id,
                "dataset_id": t.dataset_id,
                "model_id": t.model_id,
                "model_label": t.model_label,
                "estimated_parameters": [s.name for s in t.fit_specs],
                "notes": t.notes,
            }
            for t in build_targets().values()
        ],
        "protocol": {
            "description": (
                "Parameters are estimated from odd-numbered subjects only, then used unchanged "
                "to predict even-numbered subjects. The split is fixed in code so it cannot be "
                "chosen after seeing results."
            ),
            "why_it_matters": (
                "Calibration-set agreement only shows the software fits what it was fitted to. "
                "Only the held-out numbers say anything about the model."
            ),
        },
    }


@router.get("/validation/{target_id}")
def validation_report(target_id: str) -> dict[str, Any]:
    try:
        return run_validation(target_id).to_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/validation/pbpk/structural-check")
def pbpk_structural_check() -> dict[str, Any]:
    """The one quantitative external check the PBPK distribution module passes.

    Predicted steady-state volume of distribution for theophylline compared with
    the value widely reported in the clinical literature (~0.5 L/kg).
    """
    drug = DrugPhysChem(log_p=0.0, fraction_unbound_plasma=0.60, blood_plasma_ratio=0.82)
    model = PerfusionLimitedPBPK(
        drug=drug,
        body_weight_kg=70.0,
        hepatic_intrinsic_clearance_L_per_h=5.0,
        renal_clearance_L_per_h=0.3,
    )
    vss = model.predicted_vss_L()
    vss_per_kg = vss / 70.0
    literature = 0.5
    fold = max(vss_per_kg / literature, literature / vss_per_kg)
    return {
        "check": "Predicted steady-state volume of distribution, theophylline",
        "inputs": {
            "log_p": drug.log_p,
            "log_p_origin": "inferred (PubChem XLogP3, a computed descriptor)",
            "fraction_unbound_plasma": drug.fraction_unbound_plasma,
            "fraction_unbound_origin": "inferred (~40% protein bound, primary source not retrieved)",
            "blood_plasma_ratio": drug.blood_plasma_ratio,
            "blood_plasma_ratio_origin": "illustrative (no primary source retrieved)",
        },
        "predicted_vss_L": vss,
        "predicted_vss_L_per_kg": vss_per_kg,
        "literature_comparison_L_per_kg": literature,
        "fold_difference": fold,
        "passes_2_fold": fold <= 2.0,
        "method": "Poulin & Theil (2002) tissue-composition partitioning",
        "cardiac_output_L_per_h": model.cardiac_output_L_per_h,
        "hepatic_blood_clearance_L_per_h": model.hepatic_blood_clearance_L_per_h(),
        "partition_coefficients": model.partition_coefficients,
        "tissue_volumes_L": model.tissue_volumes_L,
        "tissue_flows_L_per_h": model.tissue_flows_L_per_h,
        "honest_scope": (
            "This checks ONE scalar prediction of the distribution module against a widely "
            "quoted literature value, using physicochemical inputs that are themselves "
            "inferred or illustrative. It is weak evidence and it is the only external check "
            "the PBPK model passes. The model has NOT been compared against any observed "
            "concentration-time profile, and its tissue concentrations are unvalidated. "
            "The comparison value of 0.5 L/kg was not extracted from a primary publication "
            "that SYNTHBODY opened."
        ),
        "validation_status": "research_only",
        "reference_ids": ["poulin2002", "rodgers2006", "pearce2017", "davies1993", "hendeles1996"],
    }


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------
@router.get("/benchmark/theophylline-apriori")
def benchmark_theophylline_apriori() -> dict[str, Any]:
    """A-priori oral absorption benchmark on the openly licensed Theoph dataset.

    Absorption is predicted from GI physiology and theophylline physicochemistry
    and is never fitted to these profiles. Runs live rather than returning a
    cached claim.
    """
    from synthbody.engine.analysis.benchmark import run_theophylline_apriori

    return run_theophylline_apriori()


@router.get("/benchmark/orbito-comparison")
def benchmark_orbito_comparison() -> dict[str, Any]:
    """Head-to-head against Simcyp / GastroPlus / GI-Sim.

    Returns `comparison_available: false` with a documented refusal unless the
    OrBiTo case library has been populated. The source study is paywalled, and
    SYNTHBODY will not build a comparison from reconstructed inputs.
    """
    from synthbody.engine.analysis.benchmark import compare_against_published

    return compare_against_published()


@router.get("/benchmark/gi-physiology")
def benchmark_gi_physiology() -> dict[str, Any]:
    """The GI physiology behind the absorption model, with its provenance."""
    from synthbody.engine.models.absorption import gi_provenance, load_gi_tract

    t = load_gi_tract()
    return {
        "provenance": gi_provenance(),
        "state": "fasted",
        "stomach": {
            "ph": t.stomach_ph,
            "volume_mL": t.stomach_volume_mL,
            "half_emptying_min": t.gastric_half_emptying_min,
            "emptying_rate_per_h": t.gastric_emptying_rate_per_h,
        },
        "small_intestine": {
            "n_compartments": t.n_si,
            "total_transit_min": t.si_transit_total_min,
            "transit_rate_per_h": t.si_transit_rate_per_h,
            "total_volume_mL": t.si_volume_mL,
            "compartment_volume_mL": t.si_compartment_volume_L * 1000.0,
            "length_cm": t.si_length_cm,
            "radius_cm": t.si_radius_cm,
            "ph_profile": list(t.si_ph),
            "bile_salt_mM": list(t.si_bile_salt_mM),
        },
        "colon": {
            "ph": t.colon_ph,
            "volume_mL": t.colon_volume_mL,
            "transit_min": t.colon_transit_min,
            "relative_permeability": t.colon_perm_factor,
        },
        "raw_entries": t.raw,
    }


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
@router.post("/reports")
def build_report(req: ReportRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    rows = [session.get(SimulationRow, sid) for sid in req.simulation_ids]
    missing = [sid for sid, r in zip(req.simulation_ids, rows) if r is None]
    if missing:
        raise HTTPException(404, f"No simulation(s) with id(s) {missing}.")
    sims: list[SimulationRow] = [r for r in rows if r is not None]

    ref_ids: set[str] = set()
    for s in sims:
        ref_ids.update((s.provenance or {}).get("reference_ids") or [])
    all_refs = {r["id"]: r for r in reference_library()["references"]}
    refs = [all_refs[i] for i in sorted(ref_ids) if i in all_refs]

    payload: dict[str, Any] = {
        "title": req.title,
        "author": req.author,
        "generated_by": f"SYNTHBODY {SOFTWARE_VERSION} ({ENGINE_REVISION})",
        "simulations": [
            {
                "id": s.id,
                "label": s.label,
                "model_id": s.model_id,
                "drug_id": s.drug_id,
                "kind": s.kind,
                "created_at": _iso(s.created_at),
                "validation_status": s.validation_status,
                "input_hash": s.input_hash,
                "record_hash": s.record_hash,
                "request": s.request,
                "provenance": s.provenance,
                "result": s.result,
            }
            for s in sims
        ],
        "references": refs if req.include_references else [],
        "disclaimer": DISCLAIMER,
    }
    if req.include_validation:
        payload["validation"] = {
            tid: run_validation(tid).to_dict() for tid in _targets_for(sims)
        }
    if req.include_limitations:
        payload["limitations"] = _collected_limitations(sims)

    if req.format == "json":
        return payload
    return {"format": "markdown", "markdown": _render_markdown(payload), "data": payload}


def _targets_for(sims: list[SimulationRow]) -> list[str]:
    model_ids = {s.model_id for s in sims}
    return [t.target_id for t in build_targets().values() if t.model_id in model_ids]


def _collected_limitations(sims: list[SimulationRow]) -> dict[str, Any]:
    model_lims: dict[str, list[str]] = {}
    for s in sims:
        try:
            spec = get_model_spec(s.model_id)
            model_lims[s.model_id] = list(spec.limitations)
        except KeyError:
            continue
    drug_lims: dict[str, list[str]] = {}
    for d in drug_library()["drugs"]:
        if d["drug_id"] in {s.drug_id for s in sims if s.drug_id}:
            drug_lims[d["drug_id"]] = d.get("limitations", [])
    return {
        "by_model": model_lims,
        "by_drug": drug_lims,
        "platform": [
            "SYNTHBODY is research software and is not a medical device.",
            "Validation covers only the designs and populations of the shipped datasets: "
            "single-dose oral theophylline and single-dose intravenous indomethacin in small "
            "numbers of adults.",
            "The PBPK model is research-only and has not been compared against observed "
            "concentration-time data.",
            "All pharmacodynamic parameters shipped are illustrative.",
            "Population variability estimated by two-stage fitting is an upper bound.",
            "No non-linear mixed-effects estimation is implemented.",
        ],
    }


def _render_markdown(p: dict[str, Any]) -> str:
    L: list[str] = []
    a = L.append
    a(f"# {p['title']}")
    a("")
    if p.get("author"):
        a(f"**Author:** {p['author']}  ")
    a(f"**Generated by:** {p['generated_by']}  ")
    a("")
    a("> " + p["disclaimer"].replace("\n", " "))
    a("")
    a("## Simulations")
    a("")
    for s in p["simulations"]:
        a(f"### {s['label']} (id {s['id']})")
        a("")
        a(f"- **Model:** `{s['model_id']}`")
        a(f"- **Drug:** `{s['drug_id'] or 'n/a'}`")
        a(f"- **Run type:** {s['kind']}")
        a(f"- **Executed:** {s['created_at']}")
        a(f"- **Validation status:** `{s['validation_status']}`")
        a(f"- **Input hash:** `{s['input_hash']}`")
        a(f"- **Record hash:** `{s['record_hash']}`")
        a("")
        reg = (s["request"] or {}).get("regimen") or {}
        if reg:
            a("**Regimen**")
            a("")
            a(f"- Route: {reg.get('route')}")
            a(f"- Dose: {reg.get('dose_mg')} mg x {reg.get('n_doses')} every {reg.get('interval_h')} h")
            a("")
        eff = (s["result"] or {}).get("effective_parameters") or {}
        if eff:
            a("**Effective parameters**")
            a("")
            a("| Parameter | Value |")
            a("| --- | --- |")
            for k, v in eff.items():
                a(f"| {k} | {v:.6g} |")
            a("")
        prov_params = (s["provenance"] or {}).get("parameters") or []
        if prov_params:
            a("**Parameter provenance**")
            a("")
            a("| Parameter | Value | Unit | Origin | Description |")
            a("| --- | --- | --- | --- | --- |")
            for pr in prov_params:
                a(
                    f"| {pr['name']} | {pr['value']:.6g} | {pr['unit'] or '-'} | "
                    f"`{pr['origin']}` | {pr.get('description', '')} |"
                )
            a("")
        nca = (s["result"] or {}).get("nca") or {}
        if nca:
            a("**Exposure metrics (non-compartmental)**")
            a("")
            a("| Metric | Value |")
            a("| --- | --- |")
            for key in (
                "cmax", "tmax_h", "cmin", "auc_0_last", "auc_0_inf",
                "auc_extrap_percent", "terminal_half_life_h", "clearance_L_per_h",
                "mean_residence_time_h",
            ):
                v = nca.get(key)
                if v is not None:
                    a(f"| {key} | {v:.6g} |")
            a("")
            for w in nca.get("warnings") or []:
                a(f"- NCA warning: {w}")
            a("")
        diag = (s["result"] or {}).get("diagnostics") or {}
        if diag:
            a("**Solver diagnostics**")
            a("")
            a(
                f"- Method `{diag.get('method')}`, rtol {diag.get('rtol'):g}, "
                f"atol {diag.get('atol'):g}"
            )
            a(f"- Success: {diag.get('success')} ({diag.get('message')})")
            a(f"- RHS evaluations: {diag.get('n_rhs_evaluations')}")
            mb = diag.get("mass_balance_relative_error")
            if mb is not None:
                a(f"- Mass balance relative error: {mb:.3e}")
            tr = diag.get("tolerance_refinement_max_rel_diff")
            if tr is not None:
                a(f"- Tolerance refinement max relative difference: {tr:.3e}")
            for w in diag.get("warnings") or []:
                a(f"- **Solver warning:** {w}")
            a("")
        prov = s["provenance"] or {}
        if prov.get("assumptions"):
            a("**Assumptions**")
            a("")
            for x in prov["assumptions"]:
                a(f"- {x}")
            a("")
        if prov.get("limitations"):
            a("**Model limitations**")
            a("")
            for x in prov["limitations"]:
                a(f"- {x}")
            a("")

    if p.get("validation"):
        a("## Independent validation")
        a("")
        for tid, v in p["validation"].items():
            hm = v["held_out_metrics"]
            cm = v["calibration_metrics"]
            a(f"### {tid}")
            a("")
            a(f"- Dataset: {v['dataset_name']}")
            a(f"- Calibration subjects: {', '.join(v['calibration_subject_ids'])}")
            a(f"- Held-out subjects: {', '.join(v['held_out_subject_ids'])}")
            a("")
            a("| Statistic | Calibration | Held-out |")
            a("| --- | --- | --- |")
            for key, label in (
                ("n", "n observations"),
                ("rmse", "RMSE"),
                ("mae", "MAE"),
                ("median_absolute_percent_error", "Median absolute % error"),
                ("average_fold_error", "Average fold error"),
                ("absolute_average_fold_error", "Absolute average fold error"),
                ("fraction_within_2_fold", "Fraction within 2-fold"),
                ("r_squared_vs_identity", "R2 vs identity"),
            ):
                cv, hv = cm.get(key), hm.get(key)
                fmt = lambda x: "n/a" if x is None else (f"{x:.4g}" if isinstance(x, float) else str(x))
                a(f"| {label} | {fmt(cv)} | {fmt(hv)} |")
            a("")
            a(f"**Interpretation.** {v['interpretation']}")
            a("")
            a(f"**Estimation method.** {v['estimation_note']}")
            a("")

    if p.get("limitations"):
        a("## Limitations")
        a("")
        lim = p["limitations"]
        a("### Platform")
        a("")
        for x in lim["platform"]:
            a(f"- {x}")
        a("")
        for mid, xs in (lim.get("by_model") or {}).items():
            a(f"### Model `{mid}`")
            a("")
            for x in xs:
                a(f"- {x}")
            a("")
        for did, xs in (lim.get("by_drug") or {}).items():
            a(f"### Drug `{did}`")
            a("")
            for x in xs:
                a(f"- {x}")
            a("")

    if p.get("references"):
        a("## References")
        a("")
        for i, r in enumerate(p["references"], 1):
            ids = []
            if r.get("pmid"):
                ids.append(f"PMID {r['pmid']}")
            if r.get("doi"):
                ids.append(f"DOI {r['doi']}")
            a(f"{i}. {r['citation']}" + (f" ({'; '.join(ids)})" if ids else ""))
            if r.get("access_note"):
                a(f"   - *Access note:* {r['access_note']}")
            if r.get("license_note"):
                a(f"   - *Licence:* {r['license_note']}")
            a("")
    return "\n".join(L)
