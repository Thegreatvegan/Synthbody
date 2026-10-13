"""
Run the full validation suite and print a human-readable report.

This is the script that decides what SYNTHBODY is allowed to claim. Run it
after any change to the engine:

    python scripts/run_validation.py
    python scripts/run_validation.py --json validation_results.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from synthbody.engine.analysis.validation import run_all_validations  # noqa: E402
from synthbody.engine.models.pbpk import PerfusionLimitedPBPK  # noqa: E402
from synthbody.engine.physiology.partition import DrugPhysChem  # noqa: E402


def fmt(v, nd=4):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        if not np.isfinite(v):
            return "n/a"
        return f"{v:.{nd}g}"
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=str, default=None, help="write full results as JSON")
    args = ap.parse_args()

    reports = run_all_validations()
    payload = {}

    for tid, r in reports.items():
        print("=" * 100)
        print(f"TARGET   {tid}")
        print(f"MODEL    {r.model_label}  [{r.model_id}]")
        print(f"DATASET  {r.dataset_name}  [{r.dataset_id}]")
        print(f"SPLIT    calibration={r.calibration_subject_ids}  held_out={r.held_out_subject_ids}")
        print("-" * 100)
        print("TYPICAL PARAMETERS (geometric mean of calibration-subject estimates)")
        for k, v in r.typical_parameters.items():
            cv = r.between_subject_cv_percent.get(k)
            print(f"   {k:12s} = {fmt(v):>12s}    between-subject CV = {fmt(cv, 3):>8s} %")
        print("-" * 100)
        for label, m in (("CALIBRATION", r.calibration_metrics), ("HELD-OUT", r.held_out_metrics)):
            print(f"{label} AGREEMENT  (n = {m.n})")
            print(f"   RMSE                        {fmt(m.rmse)} {m.units}")
            print(f"   MAE                         {fmt(m.mae)} {m.units}")
            print(f"   Mean percent error          {fmt(m.mean_percent_error, 3)} %")
            print(f"   Median abs percent error    {fmt(m.median_absolute_percent_error, 3)} %")
            print(f"   Average fold error (AFE)    {fmt(m.average_fold_error)}")
            print(f"   Abs avg fold error (AAFE)   {fmt(m.absolute_average_fold_error)}")
            print(f"   Within 1.25-fold            {fmt(m.fraction_within_1_25_fold, 3)}")
            print(f"   Within 1.5-fold             {fmt(m.fraction_within_1_5_fold, 3)}")
            print(f"   Within 2-fold               {fmt(m.fraction_within_2_fold, 3)}")
            print(f"   R2 vs line of identity      {fmt(m.r_squared_vs_identity)}")
            print(f"   Lin concordance             {fmt(m.concordance_correlation)}")
            for n in m.notes:
                print(f"   note: {n}")
            print()
        print("INTERPRETATION")
        print("   " + r.interpretation.replace(". ", ".\n   "))
        if r.warnings:
            print("WARNINGS")
            for w in r.warnings:
                print(f"   - {w}")
        print()
        payload[tid] = r.to_dict()

    # ---- PBPK structural check: predicted Vss for theophylline
    print("=" * 100)
    print("PBPK DISTRIBUTION MODULE - STRUCTURAL CHECK")
    print("-" * 100)
    # Theophylline physicochemistry. logP and fu are commonly reported values;
    # they are INPUTS to this check, declared in drugs.json with their origin.
    theo = DrugPhysChem(log_p=-0.02, fraction_unbound_plasma=0.60, blood_plasma_ratio=0.82)
    pbpk = PerfusionLimitedPBPK(
        drug=theo,
        body_weight_kg=70.0,
        hepatic_intrinsic_clearance_L_per_h=5.0,
        renal_clearance_L_per_h=0.3,
    )
    vss = pbpk.predicted_vss_L()
    print(f"   Predicted Vss (theophylline physchem) = {vss:.2f} L = {vss / 70.0:.3f} L/kg")
    print("   Literature comparison: theophylline volume of distribution is widely")
    print("   reported as approximately 0.5 L/kg in adults.")
    print(f"   Fold difference vs 0.5 L/kg: {max(vss / 70.0 / 0.5, 0.5 / (vss / 70.0)):.2f}")
    print(f"   Cardiac output (sum of modelled flows) = {pbpk.cardiac_output_L_per_h:.1f} L/h")
    print(f"   Well-stirred CL_H (blood) = {pbpk.hepatic_blood_clearance_L_per_h():.3f} L/h")
    print("   Predicted Kp values:")
    for k, v in sorted(pbpk.partition_coefficients.items()):
        print(f"      Kp_{k:<10s} = {v:.3f}")
    payload["pbpk_structural_check"] = {
        "predicted_vss_L": vss,
        "predicted_vss_L_per_kg": vss / 70.0,
        "cardiac_output_L_per_h": pbpk.cardiac_output_L_per_h,
        "hepatic_blood_clearance_L_per_h": pbpk.hepatic_blood_clearance_L_per_h(),
        "partition_coefficients": pbpk.partition_coefficients,
        "drug_inputs": {
            "log_p": theo.log_p,
            "fraction_unbound_plasma": theo.fraction_unbound_plasma,
            "blood_plasma_ratio": theo.blood_plasma_ratio,
        },
    }

    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
