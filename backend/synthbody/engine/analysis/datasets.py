"""
Observed clinical datasets shipped with SYNTHBODY.

Only datasets whose redistribution licence is clear are included. Both of the
datasets below ship in the R `datasets` package under GPL-2 | GPL-3 and were
obtained programmatically, unmodified.

NOTHING in this module is synthetic. If a number appears here it was measured
in a human subject and published. Synthetic demonstration inputs live elsewhere
and are labelled as such.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from synthbody.config import DATASET_DIR


@dataclass(frozen=True)
class Subject:
    subject_id: str
    time_h: np.ndarray
    concentration_mg_per_L: np.ndarray
    dose_mg: float
    weight_kg: float | None
    route: str

    @property
    def n_observations(self) -> int:
        return int(self.time_h.size)


@dataclass(frozen=True)
class ObservedDataset:
    dataset_id: str
    name: str
    drug: str
    route: str
    subjects: dict[str, Subject]
    concentration_unit: str
    reference_ids: list[str]
    license_note: str
    provenance: str
    description: str
    known_limitations: list[str]

    @property
    def subject_ids(self) -> list[str]:
        return sorted(self.subjects, key=lambda s: (len(s), s))

    @property
    def n_observations(self) -> int:
        return sum(s.n_observations for s in self.subjects.values())

    def split(self, calibration_ids: list[str]) -> tuple[list[str], list[str]]:
        """Partition into calibration and held-out validation subjects."""
        unknown = set(calibration_ids) - set(self.subjects)
        if unknown:
            raise ValueError(f"Unknown subject ids: {sorted(unknown)}")
        held_out = [s for s in self.subject_ids if s not in set(calibration_ids)]
        return list(calibration_ids), held_out

    def pooled(self, subject_ids: list[str] | None = None) -> tuple[np.ndarray, np.ndarray]:
        ids = subject_ids or self.subject_ids
        t = np.concatenate([self.subjects[i].time_h for i in ids])
        c = np.concatenate([self.subjects[i].concentration_mg_per_L for i in ids])
        return t, c

    def summary(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "drug": self.drug,
            "route": self.route,
            "n_subjects": len(self.subjects),
            "n_observations": self.n_observations,
            "concentration_unit": self.concentration_unit,
            "reference_ids": self.reference_ids,
            "license_note": self.license_note,
            "provenance": self.provenance,
            "description": self.description,
            "known_limitations": self.known_limitations,
            "subjects": [
                {
                    "subject_id": s.subject_id,
                    "n_observations": s.n_observations,
                    "dose_mg": s.dose_mg,
                    "weight_kg": s.weight_kg,
                    "t_last_h": float(s.time_h[-1]),
                    "cmax_observed": float(np.max(s.concentration_mg_per_L)),
                }
                for s in (self.subjects[i] for i in self.subject_ids)
            ],
        }


@lru_cache
def load_theophylline() -> ObservedDataset:
    """R datasets::Theoph - oral theophylline in 12 subjects.

    Columns as distributed: Subject, Wt (kg), Dose (mg/kg), Time (h), conc (mg/L).
    Dose is per kilogram, so the absolute dose is Dose * Wt.
    """
    rows: list[dict[str, str]] = []
    with (DATASET_DIR / "theoph.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    by_subject: dict[str, list[tuple[float, float]]] = {}
    meta: dict[str, tuple[float, float]] = {}
    for r in rows:
        sid = str(int(float(r["Subject"])))
        wt = float(r["Wt"])
        dose_per_kg = float(r["Dose"])
        by_subject.setdefault(sid, []).append((float(r["Time"]), float(r["conc"])))
        meta[sid] = (wt, dose_per_kg * wt)

    subjects: dict[str, Subject] = {}
    for sid, pairs in by_subject.items():
        pairs.sort(key=lambda p: p[0])
        wt, dose_mg = meta[sid]
        subjects[sid] = Subject(
            subject_id=sid,
            time_h=np.array([p[0] for p in pairs], float),
            concentration_mg_per_L=np.array([p[1] for p in pairs], float),
            dose_mg=dose_mg,
            weight_kg=wt,
            route="oral",
        )

    return ObservedDataset(
        dataset_id="theoph",
        name="Theophylline oral pharmacokinetics (Theoph)",
        drug="theophylline",
        route="oral",
        subjects=subjects,
        concentration_unit="mg/L",
        reference_ids=["boeckmann1994", "upton1980"],
        license_note=(
            "Distributed in the R `datasets` package under GPL-2 | GPL-3. Redistributed "
            "unmodified by SYNTHBODY under those terms."
        ),
        provenance=(
            "Obtained programmatically from the Rdatasets CSV mirror of R datasets::Theoph "
            "on 2026-10-12. 132 rows, 12 subjects, 11 observations each. No values were "
            "transcribed by hand and none were altered."
        ),
        description=(
            "Twelve subjects each given a single oral dose of theophylline, with plasma "
            "concentrations measured at 11 time points over roughly 25 hours. The canonical "
            "teaching and benchmarking dataset for one-compartment first-order-absorption "
            "population pharmacokinetics."
        ),
        known_limitations=[
            "Single dose only: provides no information about accumulation or time-varying clearance.",
            "Healthy adults; the dataset carries no information about hepatic impairment, "
            "age extremes or drug interactions.",
            "Only body weight is recorded as a covariate. Smoking status, which strongly "
            "affects theophylline clearance via CYP1A2, is not available.",
            "Two subjects have a non-zero concentration recorded at nominal time zero, which "
            "a model with an absorption depot starting empty cannot reproduce.",
            "Bioavailability is not identifiable from oral-only data, so clearance and volume "
            "estimated from it are apparent values (CL/F and V/F).",
        ],
    )


@lru_cache
def load_indomethacin() -> ObservedDataset:
    """R datasets::Indometh - intravenous indomethacin in 6 subjects.

    Columns as distributed: Subject, time (h), conc (mcg/mL).

    The dose is NOT in the distributed data frame. R's documentation describes
    the study as repeated intravenous administration; the per-subject dose is
    therefore unknown to SYNTHBODY. Rather than invent one, dose_mg is recorded
    as 1.0 and every volume/clearance estimate from this dataset is explicitly
    an apparent value per unit dose (V/D, CL/D). This is stated in the
    limitations and surfaced in the UI.
    """
    with (DATASET_DIR / "indometh.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    by_subject: dict[str, list[tuple[float, float]]] = {}
    for r in rows:
        sid = str(int(float(r["Subject"])))
        by_subject.setdefault(sid, []).append((float(r["time"]), float(r["conc"])))

    subjects: dict[str, Subject] = {}
    for sid, pairs in by_subject.items():
        pairs.sort(key=lambda p: p[0])
        subjects[sid] = Subject(
            subject_id=sid,
            time_h=np.array([p[0] for p in pairs], float),
            concentration_mg_per_L=np.array([p[1] for p in pairs], float),
            dose_mg=1.0,
            weight_kg=None,
            route="iv_bolus",
        )

    return ObservedDataset(
        dataset_id="indometh",
        name="Indomethacin intravenous pharmacokinetics (Indometh)",
        drug="indomethacin",
        route="iv_bolus",
        subjects=subjects,
        concentration_unit="mg/L",
        reference_ids=["kwan1976"],
        license_note=(
            "Distributed in the R `datasets` package under GPL-2 | GPL-3. Redistributed "
            "unmodified by SYNTHBODY under those terms."
        ),
        provenance=(
            "Obtained programmatically from the Rdatasets CSV mirror of R datasets::Indometh "
            "on 2026-10-12. 66 rows, 6 subjects, 11 observations each. Concentrations are "
            "reported in mcg/mL, which is numerically identical to mg/L."
        ),
        description=(
            "Six subjects given intravenous indomethacin, with plasma concentrations measured "
            "at 11 time points over 8 hours. Shows a clear biexponential decline and is the "
            "standard small benchmark for two-compartment disposition."
        ),
        known_limitations=[
            "THE ADMINISTERED DOSE IS NOT PRESENT IN THE DISTRIBUTED DATASET. SYNTHBODY uses "
            "a nominal dose of 1 unit, so every estimated volume and clearance from this "
            "dataset is an apparent value per unit dose, not an absolute L or L/h.",
            "The source study reports enterohepatic recirculation. A plain two-compartment "
            "model cannot reproduce secondary peaks and that misfit will show up in residuals.",
            "Eight hours of sampling is short relative to the terminal phase, so the terminal "
            "rate constant and anything derived from it are weakly determined.",
            "No covariates at all are recorded: no weight, age or sex.",
        ],
    )


@lru_cache
def all_datasets() -> dict[str, ObservedDataset]:
    return {
        "theoph": load_theophylline(),
        "indometh": load_indomethacin(),
    }


def get_dataset(dataset_id: str) -> ObservedDataset:
    ds = all_datasets().get(dataset_id)
    if ds is None:
        raise KeyError(f"Unknown dataset {dataset_id!r}. Available: {sorted(all_datasets())}")
    return ds
