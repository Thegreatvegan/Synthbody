"""
Explicit physical units for every quantity that crosses a model boundary.

Rationale: the single most common source of silent error in PK/PD code is a
unit mismatch (mg vs mg/kg, h vs min, L vs L/kg). Rather than depend on a
heavyweight units library, SYNTHBODY uses a small closed vocabulary of
canonical units plus declared conversions, and *refuses* to convert between
dimensions. Every model parameter declares its unit; the engine validates the
declared unit against the unit the model expects before integrating.
"""
from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# Canonical internal units. The ODE right-hand sides are written exclusively
# in these; conversion happens once, at the boundary.
# --------------------------------------------------------------------------
CANONICAL = {
    "time": "h",
    "mass": "mg",
    "volume": "L",
    "concentration": "mg/L",
    "flow": "L/h",
    "clearance": "L/h",
    "rate_constant": "1/h",
    "dimensionless": "",
}

# factor maps "unit" -> multiplier to reach the canonical unit of its dimension
_CONVERSIONS: dict[str, tuple[str, float]] = {
    # time
    "h": ("time", 1.0),
    "hr": ("time", 1.0),
    "min": ("time", 1.0 / 60.0),
    "s": ("time", 1.0 / 3600.0),
    "day": ("time", 24.0),
    "d": ("time", 24.0),
    # mass
    "mg": ("mass", 1.0),
    "g": ("mass", 1000.0),
    "ug": ("mass", 1e-3),
    "mcg": ("mass", 1e-3),
    "ng": ("mass", 1e-6),
    # volume
    "L": ("volume", 1.0),
    "mL": ("volume", 1e-3),
    "dL": ("volume", 0.1),
    # concentration
    "mg/L": ("concentration", 1.0),
    "ug/mL": ("concentration", 1.0),  # identical by definition
    "mcg/mL": ("concentration", 1.0),
    "ug/L": ("concentration", 1e-3),
    "ng/mL": ("concentration", 1e-3),
    "g/L": ("concentration", 1000.0),
    # flow / clearance
    "L/h": ("clearance", 1.0),
    "mL/min": ("clearance", 60.0 * 1e-3),
    "L/min": ("clearance", 60.0),
    "mL/h": ("clearance", 1e-3),
    # rate constants
    "1/h": ("rate_constant", 1.0),
    "1/min": ("rate_constant", 60.0),
    "1/day": ("rate_constant", 1.0 / 24.0),
    "h-1": ("rate_constant", 1.0),
    # dimensionless
    "": ("dimensionless", 1.0),
    "-": ("dimensionless", 1.0),
    "fraction": ("dimensionless", 1.0),
    "ratio": ("dimensionless", 1.0),
}

# Units that are "per kilogram" variants. These are dimensionally distinct and
# must be resolved against a body weight before entering the ODE.
_PER_KG = {
    "mg/kg": "mass",
    "L/kg": "volume",
    "L/h/kg": "clearance",
    "mL/min/kg": "clearance",
}


class UnitError(ValueError):
    """Raised when a declared unit is unknown or dimensionally incompatible."""


@dataclass(frozen=True)
class Quantity:
    """A number that knows what it is. Immutable."""

    value: float
    unit: str

    def dimension(self) -> str:
        return dimension_of(self.unit)

    def to_canonical(self, body_weight_kg: float | None = None) -> float:
        return to_canonical(self.value, self.unit, body_weight_kg)

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.value:g} {self.unit}".strip()


def dimension_of(unit: str) -> str:
    unit = (unit or "").strip()
    if unit in _PER_KG:
        return _PER_KG[unit]
    if unit in _CONVERSIONS:
        return _CONVERSIONS[unit][0]
    raise UnitError(f"Unknown unit {unit!r}. Known: {sorted(set(_CONVERSIONS) | set(_PER_KG))}")


def to_canonical(value: float, unit: str, body_weight_kg: float | None = None) -> float:
    """Convert `value` expressed in `unit` into the canonical unit of its dimension.

    Per-kilogram units require a body weight; omitting it is an error rather
    than a silent assumption of 70 kg.
    """
    unit = (unit or "").strip()
    if unit in _PER_KG:
        if body_weight_kg is None:
            raise UnitError(f"Unit {unit!r} is per-kilogram; a body weight is required to resolve it.")
        if body_weight_kg <= 0:
            raise UnitError(f"Body weight must be positive, got {body_weight_kg}.")
        base = unit.rsplit("/kg", 1)[0]
        return to_canonical(value, base) * body_weight_kg
    if unit not in _CONVERSIONS:
        raise UnitError(f"Unknown unit {unit!r}.")
    return value * _CONVERSIONS[unit][1]


def convert(value: float, from_unit: str, to_unit: str, body_weight_kg: float | None = None) -> float:
    """Convert between two units of the *same* dimension. Refuses cross-dimension."""
    d_from, d_to = dimension_of(from_unit), dimension_of(to_unit)
    if d_from != d_to:
        raise UnitError(
            f"Refusing to convert {from_unit!r} ({d_from}) to {to_unit!r} ({d_to}): different dimensions."
        )
    canonical = to_canonical(value, from_unit, body_weight_kg)
    if to_unit in _PER_KG:
        if body_weight_kg is None:
            raise UnitError(f"Target unit {to_unit!r} is per-kilogram; body weight required.")
        base = to_unit.rsplit("/kg", 1)[0]
        return canonical / _CONVERSIONS[base][1] / body_weight_kg
    return canonical / _CONVERSIONS[to_unit][1]


def require_dimension(unit: str, expected: str, *, what: str = "parameter") -> None:
    actual = dimension_of(unit)
    if actual != expected:
        raise UnitError(f"{what} declared in {unit!r} ({actual}) but {expected!r} was expected.")
