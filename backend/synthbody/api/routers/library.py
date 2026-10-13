"""Read-only endpoints: models, drugs, references, physiology, datasets."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from synthbody.engine.analysis.datasets import all_datasets, get_dataset
from synthbody.engine.physiology.reference_man import (
    PBPK_TISSUES,
    load_reference_physiology,
    physiology_provenance,
)
from synthbody.engine.registry import (
    drug_library,
    get_drug,
    get_model_spec,
    model_specs,
    reference_library,
)
from synthbody.version import ENGINE_REVISION, SOFTWARE_NAME, SOFTWARE_VERSION

router = APIRouter(tags=["library"])


@router.get("/meta")
def meta() -> dict[str, Any]:
    return {
        "software_name": SOFTWARE_NAME,
        "software_version": SOFTWARE_VERSION,
        "engine_revision": ENGINE_REVISION,
        "classification": "Research simulation software. Not a medical device.",
        "intended_use": (
            "Exploration of pharmacokinetic and pharmacodynamic model behaviour for "
            "hypothetical simulated subjects, using published models and openly licensed data."
        ),
        "not_intended_use": [
            "Diagnosis of any condition.",
            "Selection of a dose for any real person.",
            "Any decision affecting the care of an identifiable patient.",
            "Regulatory submission without independent qualification of each model.",
        ],
        "regulatory_status": {
            "fda_cleared": False,
            "ce_marked": False,
            "hipaa_compliant": False,
            "gdpr_assessed": False,
            "note": (
                "SYNTHBODY has not been reviewed or cleared by any regulator and makes no "
                "compliance claim. It is designed to be used with synthetic or published "
                "de-identified research data only."
            ),
        },
        "counts": {
            "models": len(model_specs()),
            "drugs": len(drug_library()["drugs"]),
            "references": len(reference_library()["references"]),
            "validation_datasets": len(all_datasets()),
        },
    }


@router.get("/models")
def list_models() -> dict[str, Any]:
    return {"models": [s.to_dict() for s in model_specs().values()]}


@router.get("/models/{model_id}")
def get_model(model_id: str) -> dict[str, Any]:
    try:
        return get_model_spec(model_id).to_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/drugs")
def list_drugs() -> dict[str, Any]:
    lib = drug_library()
    return {
        "curation_note": lib["curation_note"],
        "parameter_origin_legend": lib["parameter_origin_legend"],
        "drugs": lib["drugs"],
    }


@router.get("/drugs/{drug_id}")
def drug_detail(drug_id: str) -> dict[str, Any]:
    try:
        return get_drug(drug_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/references")
def list_references(
    q: str | None = Query(None, description="Free-text search across all reference fields"),
    topic: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    lib = reference_library()
    refs: list[dict[str, Any]] = lib["references"]
    if q:
        needle = q.lower()
        refs = [
            r
            for r in refs
            if needle in str(r).lower()
        ]
    if topic:
        refs = [r for r in refs if topic.lower() in [t.lower() for t in r.get("topics", [])]]
    if kind:
        refs = [r for r in refs if r.get("kind") == kind]
    return {
        "curation_note": lib["curation_note"],
        "n_total": len(lib["references"]),
        "n_matched": len(refs),
        "topics": sorted({t for r in lib["references"] for t in r.get("topics", [])}),
        "kinds": sorted({r.get("kind", "") for r in lib["references"] if r.get("kind")}),
        "references": refs,
    }


@router.get("/references/{reference_id}")
def reference_detail(reference_id: str) -> dict[str, Any]:
    for r in reference_library()["references"]:
        if r["id"] == reference_id:
            # Which models and drugs depend on this reference?
            used_by_models = [
                s.model_id for s in model_specs().values() if reference_id in s.reference_ids
            ]
            used_by_drugs = [
                d["drug_id"]
                for d in drug_library()["drugs"]
                if reference_id in str(d)
            ]
            return {**r, "used_by_models": used_by_models, "used_by_drugs": used_by_drugs}
    raise HTTPException(404, f"No reference with id {reference_id!r}.")


@router.get("/physiology")
def physiology() -> dict[str, Any]:
    phys = load_reference_physiology()
    bw = phys.reference_body_weight_kg
    vols = phys.tissue_volumes_L(bw)
    flows = phys.tissue_flows_L_per_h(bw)
    total_flow = sum(flows[t] for t in PBPK_TISSUES if t != "lung")
    return {
        "provenance": physiology_provenance(),
        "reference_body_weight_kg": bw,
        "whole_body": {
            "plasma_volume_L": phys.plasma_volume_L(bw),
            "blood_volume_L": phys.blood_volume_L(bw),
            "hematocrit": phys.hematocrit,
            "cardiac_output_L_per_h_whole_body_value": phys.cardiac_output_L_per_h(bw),
            "cardiac_output_L_per_h_sum_of_modelled_flows": total_flow,
            "cardiac_output_note": (
                "The PBPK model uses the sum of the modelled tissue flows as cardiac output so "
                "that flow balance closes exactly. The independent whole-body value from the "
                "source dataset is shown alongside for comparison."
            ),
            "gfr_L_per_h": phys.gfr_L_per_h(bw),
            "body_temperature_c": phys.body_temperature_c,
        },
        "tissues": [
            {
                "name": t,
                "volume_L": vols[t],
                "volume_fraction_of_body_weight": phys.tissues[t].vol_L_per_kg,
                "blood_flow_L_per_h": flows[t],
                "fraction_of_cardiac_output": flows[t] / total_flow if t != "lung" else 1.0,
                "f_water": phys.tissues[t].f_water,
                "f_lipid_total": phys.tissues[t].f_lipid_total,
                "f_neutral_lipid": phys.tissues[t].f_neutral_lipid,
                "f_phospholipid": phys.tissues[t].f_phospholipid,
                "f_protein": phys.tissues[t].f_protein,
                "ph": phys.tissues[t].ph,
                "composition_is_borrowed": t == "rest",
            }
            for t in PBPK_TISSUES
        ],
        "portal_drained_tissues": ["gut", "spleen"],
    }


@router.get("/datasets")
def list_datasets() -> dict[str, Any]:
    return {"datasets": [d.summary() for d in all_datasets().values()]}


@router.get("/datasets/{dataset_id}")
def dataset_detail(dataset_id: str) -> dict[str, Any]:
    try:
        ds = get_dataset(dataset_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        **ds.summary(),
        "observations": [
            {
                "subject_id": s.subject_id,
                "dose_mg": s.dose_mg,
                "weight_kg": s.weight_kg,
                "time_h": s.time_h.tolist(),
                "concentration": s.concentration_mg_per_L.tolist(),
            }
            for s in (ds.subjects[i] for i in ds.subject_ids)
        ],
    }
