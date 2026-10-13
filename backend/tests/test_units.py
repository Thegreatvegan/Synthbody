"""Unit-safety tests. A unit bug is the most likely way this engine produces a
confidently wrong answer, so these are the strictest tests in the suite."""
from __future__ import annotations

import math

import pytest

from synthbody.engine.units import (
    Quantity,
    UnitError,
    convert,
    dimension_of,
    require_dimension,
    to_canonical,
)


def test_canonical_identities():
    assert to_canonical(1.0, "h") == 1.0
    assert to_canonical(1.0, "mg") == 1.0
    assert to_canonical(1.0, "L") == 1.0
    assert to_canonical(1.0, "mg/L") == 1.0


def test_time_conversions():
    assert to_canonical(60.0, "min") == pytest.approx(1.0)
    assert to_canonical(3600.0, "s") == pytest.approx(1.0)
    assert to_canonical(1.0, "day") == pytest.approx(24.0)


def test_mass_conversions():
    assert to_canonical(1.0, "g") == pytest.approx(1000.0)
    assert to_canonical(1000.0, "ug") == pytest.approx(1.0)


def test_ug_per_ml_equals_mg_per_l():
    """ug/mL and mg/L are the same number. Treating them as different is a classic bug."""
    assert to_canonical(7.5, "ug/mL") == pytest.approx(to_canonical(7.5, "mg/L"))


def test_clearance_conversions():
    # 1 L/min = 60 L/h
    assert to_canonical(1.0, "L/min") == pytest.approx(60.0)
    # 100 mL/min = 6 L/h
    assert to_canonical(100.0, "mL/min") == pytest.approx(6.0)


def test_rate_constant_conversions():
    assert to_canonical(1.0, "1/min") == pytest.approx(60.0)
    assert to_canonical(1.0, "1/day") == pytest.approx(1.0 / 24.0)


def test_per_kg_requires_weight():
    with pytest.raises(UnitError, match="per-kilogram"):
        to_canonical(0.5, "L/kg")
    assert to_canonical(0.5, "L/kg", body_weight_kg=70.0) == pytest.approx(35.0)
    assert to_canonical(4.0, "mg/kg", body_weight_kg=79.6) == pytest.approx(318.4)


def test_per_kg_rejects_nonpositive_weight():
    with pytest.raises(UnitError):
        to_canonical(0.5, "L/kg", body_weight_kg=0.0)
    with pytest.raises(UnitError):
        to_canonical(0.5, "L/kg", body_weight_kg=-70.0)


def test_cross_dimension_conversion_is_refused():
    """This is the whole point: refuse, do not guess."""
    with pytest.raises(UnitError, match="different dimensions"):
        convert(1.0, "mg", "L")
    with pytest.raises(UnitError, match="different dimensions"):
        convert(1.0, "h", "mg/L")
    with pytest.raises(UnitError, match="different dimensions"):
        convert(1.0, "L/h", "1/h")


def test_round_trip_conversions():
    for value, a, b in [
        (7.0, "mg/L", "ng/mL"),
        (2.5, "h", "min"),
        (300.0, "mg", "g"),
        (5.0, "L/h", "mL/min"),
    ]:
        back = convert(convert(value, a, b), b, a)
        assert back == pytest.approx(value, rel=1e-12)


def test_per_kg_round_trip():
    v = convert(0.0379, "L/h/kg", "L/h", body_weight_kg=80.0)
    assert v == pytest.approx(3.032)
    back = convert(v, "L/h", "L/h/kg", body_weight_kg=80.0)
    assert back == pytest.approx(0.0379)


def test_unknown_unit_raises():
    with pytest.raises(UnitError, match="Unknown unit"):
        dimension_of("furlongs/fortnight")


def test_require_dimension():
    require_dimension("L/h", "clearance")
    with pytest.raises(UnitError, match="clearance"):
        require_dimension("mg", "clearance", what="CL")


def test_quantity_is_immutable_and_knows_itself():
    q = Quantity(0.5, "L/kg")
    assert q.dimension() == "volume"
    assert q.to_canonical(body_weight_kg=70.0) == pytest.approx(35.0)
    with pytest.raises(Exception):
        q.value = 1.0  # type: ignore[misc]


def test_dimensionless_variants():
    for u in ("", "-", "fraction", "ratio"):
        assert dimension_of(u) == "dimensionless"
        assert to_canonical(0.6, u) == pytest.approx(0.6)


def test_no_silent_nan():
    assert math.isfinite(to_canonical(1.0, "mg/L"))
