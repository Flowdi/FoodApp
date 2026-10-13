from decimal import Decimal

import pytest

from backend.app.units import convert_quantity, sum_converted


def test_metric_conversions():
    assert convert_quantity(Decimal("1500"), "g", "kg") == Decimal("1.500")
    assert convert_quantity(Decimal("2"), "l", "ml") == Decimal("2000")


def test_incompatible_units():
    with pytest.raises(ValueError):
        convert_quantity(Decimal("1"), "piece", "g")


def test_sum_converts_compatible_units():
    assert sum_converted([(Decimal("500"), "ml"), (Decimal("1"), "l")], "l") == Decimal("1.500")
