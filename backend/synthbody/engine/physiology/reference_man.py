"""
Human reference physiology, loaded from the openly licensed dataset shipped
in data/library/reference_physiology.json.

Provenance summary (full detail lives in the JSON file):
  * organ volume fractions  -> ILSI Risk Science Institute (1994), via US EPA httk
  * organ blood flows       -> Davies & Morris (1993) Pharm Res 10:1093-5, via httk
  * tissue composition      -> Schmitt (2008) Toxicol In Vitro 22:457-67, via httk
  * whole-body constants    -> httk physiology.data

Every value was read programmatically out of httk's binary Tables.RData; none
was transcribed by hand. See references.json entries `pearce2017`, `davies1993`,
`ilsi1994`, `schmitt2008`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from synthbody.config import LIBRARY_DIR

# Tissues the PBPK model represents, in a fixed order. `rest` lumps everything
# not explicitly modelled so that volumes and flows still close.
PBPK_TISSUES: tuple[str, ...] = (
    "lung",
    "adipose",
    "bone",
    "brain",
    "heart",
    "kidney",
    "muscle",
    "skin",
    "gut",
    "spleen",
    "liver",
    "rest",
)

# Tissues whose venous outflow drains into the liver via the portal vein rather
# than directly into the vena cava.
PORTAL_TISSUES: tuple[str, ...] = ("gut", "spleen")


@dataclass(frozen=True)
class TissueProperties:
    name: str
    vol_L_per_kg: float
    flow_mL_per_min_per_kg075: float
    f_water: float
    f_lipid_total: float
    f_protein: float
    f_neutral_lipid_of_lipid: float
    f_neutral_phospholipid_of_lipid: float
    f_acidic_phospholipid_of_lipid: float
    ph: float

    @property
    def f_neutral_lipid(self) -> float:
        """Absolute volume fraction of neutral lipid in the tissue."""
        return self.f_lipid_total * self.f_neutral_lipid_of_lipid

    @property
    def f_phospholipid(self) -> float:
        """Absolute volume fraction of phospholipid (neutral + acidic)."""
        return self.f_lipid_total * (
            self.f_neutral_phospholipid_of_lipid + self.f_acidic_phospholipid_of_lipid
        )


@dataclass(frozen=True)
class ReferencePhysiology:
    tissues: dict[str, TissueProperties]
    plasma_volume_mL_per_kg: float
    hematocrit: float
    gfr_mL_per_min_per_kg075: float
    cardiac_output_mL_per_min_per_kg075: float
    plasma_f_neutral_lipid: float
    plasma_f_protein_volume: float
    body_temperature_c: float
    reference_body_weight_kg: float
    raw: dict[str, Any]

    # ------------------------------------------------------------------ sizing
    def tissue_volumes_L(self, body_weight_kg: float) -> dict[str, float]:
        return {n: t.vol_L_per_kg * body_weight_kg for n, t in self.tissues.items()}

    def tissue_flows_L_per_h(self, body_weight_kg: float) -> dict[str, float]:
        """Allometrically scaled perfusion: Q = q * BW^0.75, converted to L/h."""
        scale = body_weight_kg**0.75
        return {
            n: t.flow_mL_per_min_per_kg075 * scale * 60.0 / 1000.0 for n, t in self.tissues.items()
        }

    def cardiac_output_L_per_h(self, body_weight_kg: float) -> float:
        return self.cardiac_output_mL_per_min_per_kg075 * body_weight_kg**0.75 * 60.0 / 1000.0

    def gfr_L_per_h(self, body_weight_kg: float) -> float:
        return self.gfr_mL_per_min_per_kg075 * body_weight_kg**0.75 * 60.0 / 1000.0

    def blood_volume_L(self, body_weight_kg: float) -> float:
        """Blood = plasma / (1 - haematocrit)."""
        plasma_L = self.plasma_volume_mL_per_kg * body_weight_kg / 1000.0
        return plasma_L / (1.0 - self.hematocrit)

    def plasma_volume_L(self, body_weight_kg: float) -> float:
        return self.plasma_volume_mL_per_kg * body_weight_kg / 1000.0


@lru_cache
def load_reference_physiology() -> ReferencePhysiology:
    path = LIBRARY_DIR / "reference_physiology.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    raw_t = doc["tissues"]

    def val(tissue: str, key: str, fallback_tissue: str | None = None) -> float:
        v = raw_t.get(tissue, {}).get(key)
        if v is None and fallback_tissue is not None:
            v = raw_t.get(fallback_tissue, {}).get(key)
        if v is None:
            raise KeyError(f"reference_physiology.json: no {key!r} for tissue {tissue!r}")
        return float(v)

    tissues: dict[str, TissueProperties] = {}
    for name in PBPK_TISSUES:
        # `rest` carries volume and flow but no composition in the source data.
        # Giving it muscle composition is an explicit modelling assumption and is
        # declared in the model's `assumptions` list, not hidden here.
        comp_src = "muscle" if name == "rest" else name
        tissues[name] = TissueProperties(
            name=name,
            vol_L_per_kg=val(name, "vol_L_per_kg"),
            flow_mL_per_min_per_kg075=val(name, "flow_mL_per_min_per_kg075"),
            f_water=val(comp_src, "f_water"),
            f_lipid_total=val(comp_src, "f_lipid_total"),
            f_protein=val(comp_src, "f_protein"),
            f_neutral_lipid_of_lipid=val(comp_src, "f_neutral_lipid_of_lipid"),
            f_neutral_phospholipid_of_lipid=val(comp_src, "f_neutral_phospholipid_of_lipid"),
            f_acidic_phospholipid_of_lipid=val(comp_src, "f_acidic_phospholipid_of_lipid"),
            ph=val(comp_src, "ph"),
        )

    wb = doc["whole_body"]

    def wbv(key: str) -> float:
        entry = wb.get(key)
        if entry is None or entry.get("human") is None:
            raise KeyError(f"reference_physiology.json: missing whole-body value {key!r}")
        return float(entry["human"])

    return ReferencePhysiology(
        tissues=tissues,
        plasma_volume_mL_per_kg=wbv("Plasma Volume"),
        hematocrit=wbv("Hematocrit"),
        gfr_mL_per_min_per_kg075=wbv("GFR"),
        cardiac_output_mL_per_min_per_kg075=wbv("Cardiac Output"),
        plasma_f_neutral_lipid=wbv("Plasma Effective Neutral Lipid Volume Fraction"),
        plasma_f_protein_volume=wbv("Plasma Protein Volume Fraction"),
        body_temperature_c=wbv("Average Body Temperature"),
        reference_body_weight_kg=wbv("Average BW"),
        raw=doc,
    )


def physiology_provenance() -> dict[str, Any]:
    """The provenance block from the physiology dataset, for API exposure."""
    return load_reference_physiology().raw["provenance"]
