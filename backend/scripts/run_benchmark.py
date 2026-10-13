"""
Run the SYNTHBODY benchmark suite and print a human-readable report.

    python scripts/run_benchmark.py
    python scripts/run_benchmark.py --json ../docs/benchmark_results.json

Two things happen:

  1. The theophylline a-priori absorption benchmark RUNS, on openly licensed
     data, with absorption predicted from physicochemistry and GI physiology
     rather than fitted.

  2. The head-to-head comparison against Simcyp / GastroPlus / GI-Sim is
     attempted and will REFUSE unless the OrBiTo case library has been
     populated, because the source study is paywalled.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synthbody.engine.analysis.benchmark import (  # noqa: E402
    PUBLISHED_RESULTS,
    PUBLISHED_RESULTS_PROVENANCE,
    compare_against_published,
    run_theophylline_apriori,
)


def rule(ch: str = "=", n: int = 96) -> None:
    print(ch * n)


def fmt(v, nd=3):
    return "n/a" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=str, default=None)
    args = ap.parse_args()

    payload = {}

    # ---------------------------------------------------------------- part 1
    rule()
    print("BENCHMARK 1 — THEOPHYLLINE A-PRIORI ABSORPTION  (executed)")
    rule()
    r = run_theophylline_apriori()
    payload["theophylline_apriori"] = r

    print("Question: with absorption rate derived ONLY from GI physiology and")
    print("theophylline physicochemistry — never fitted to these profiles — how well")
    print("does SYNTHBODY predict observed plasma concentrations?")
    print()
    print(f"  Dataset            : {r['dataset']['name']}")
    print(f"  Calibration subject: {', '.join(r['calibration_subject_ids'])}  (disposition only)")
    print(f"  Held-out subjects  : {', '.join(r['held_out_subject_ids'])}  (the test)")
    print(f"  CL/F = {r['disposition_source']['cl_per_kg_L_per_h']:.5f} L/h/kg, "
          f"V/F = {r['disposition_source']['v_per_kg_L']:.4f} L/kg")
    print(f"  Absorption ka      : NOT fitted. Derived from gastric emptying, transit and Peff.")
    print(f"  (A fitted ka of {r['fitted_ka_for_reference_per_h']:.3f} /h exists elsewhere in "
          "SYNTHBODY and is shown only for contrast.)")
    print()

    print("Physicochemical inputs and where they came from:")
    for k, v in r["physchem"].items():
        print(f"  {k:38s} {v['value']:<10g} [{v['origin']}]")
    print()

    print("Sensitivity to the inferred permeability (full sweep):")
    print(f"  {'Peff (cm/s)':>12} {'mean fabs':>10} | {'AUC AAFE':>9} {'Cmax AAFE':>10} {'tmax AAFE':>10}")
    print("  " + "-" * 60)
    for s in r["peff_sweep"]:
        m = s["evaluation"]["metrics"]
        g = lambda k: m[k]["aafe"] if m[k].get("available") else float("nan")
        mark = " <- pre-specified" if abs(s["peff_cm_per_s"] - r["prespecified_peff_cm_per_s"]) < 1e-12 else ""
        print(f"  {s['peff_cm_per_s']:12.1e} {s['mean_predicted_fabs']:10.4f} | "
              f"{g('auc'):9.3f} {g('cmax'):10.3f} {g('tmax'):10.3f}{mark}")
    print()

    h = r["headline_result"]
    hm = h["evaluation"]["metrics"]
    print(f"HEADLINE (pre-specified Peff = {h['peff_cm_per_s']:.1e} cm/s, "
          f"mean predicted fabs = {h['mean_predicted_fabs']:.4f}):")
    print(f"  {'metric':6s} {'n':>3} {'AAFE':>7} {'AFE':>7} {'median FE':>10} {'within 2x':>10} {'max FE':>8}")
    for k in ("auc", "cmax", "tmax"):
        x = hm[k]
        if not x.get("available"):
            print(f"  {k.upper():6s} unavailable: {x.get('reason')}")
            continue
        print(f"  {k.upper():6s} {x['n']:3d} {x['aafe']:7.3f} {x['afe']:7.3f} "
              f"{x['median_fold_error']:10.3f} {x['fraction_within_2_fold']*100:9.0f}% "
              f"{x['max_fold_error']:8.2f}")
    print()
    print(f"  {r['headline_note']}")
    print()
    print("Per-subject predictions (held out):")
    print(f"  {'subject':>10} {'dose mg':>8} {'fabs':>7} | {'AUC pred':>9} {'AUC obs':>9} | "
          f"{'Cmax p':>7} {'Cmax o':>7} | {'tmax p':>7} {'tmax o':>7}")
    for cr in h["case_results"]:
        sid = cr["case_id"].split("-")[1]
        print(f"  {sid:>10} {cr['dose_mg']:8.1f} {cr['predicted_fabs']:7.4f} | "
              f"{cr['predicted_auc']:9.2f} {cr['observed_auc']:9.2f} | "
              f"{cr['predicted_cmax']:7.2f} {cr['observed_cmax']:7.2f} | "
              f"{cr['predicted_tmax_h']:7.2f} {cr['observed_tmax_h']:7.2f}")
    mb = max(c["mass_balance_error"] for c in h["case_results"])
    print(f"\n  max GI mass-balance error: {mb:.2e}")
    print()
    print("  SCOPE: " + r["honest_scope"])
    print()

    # ---------------------------------------------------------------- part 2
    rule()
    print("BENCHMARK 2 — HEAD-TO-HEAD vs SIMCYP / GASTROPLUS / GI-SIM")
    rule()
    c = compare_against_published()
    payload["orbito_comparison"] = c

    print("Published results (recorded, never computed by SYNTHBODY):")
    print(f"  {'Software':<18} {'AUC':>6} {'Cmax':>6} {'tmax':>6}")
    for name, m in PUBLISHED_RESULTS.items():
        print(f"  {name:<18} {m['auc']:6.1f} {m['cmax']:6.1f} {m['tmax']:6.1f}")
    print()
    print("  " + PUBLISHED_RESULTS_PROVENANCE.replace(". ", ".\n  "))
    print()

    if not c["comparison_available"]:
        print("STATUS: COMPARISON REFUSED")
        print()
        print("  " + c["refusal_reason"].replace(". ", ".\n  "))
        print()
        print("  Access record:")
        for k, v in c["access_record"].items():
            if k == "consequence":
                continue
            print(f"    {k:28s} {v}")
        print()
        print("  What would be needed:")
        for item in c["what_would_be_needed"]:
            print(f"    - {item}")
        print()
        print(f"  {c['how_to_supply']}")
    else:
        print(f"STATUS: {c['n_administrations']} administrations executed")
        print(f"  SYNTHBODY AAFE: {c['synthbody_results']}")
        print(f"  {c['comparability_caveat']}")

    print()
    rule()
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
