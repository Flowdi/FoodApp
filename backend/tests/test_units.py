from decimal import Decimal

import pytest

from backend.app.units import convert_quantity


def test_metric_conversions():
    assert convert_quantity(Decimal("1500"), "g", "kg") == Decimal("1.500")
    assert convert_quantity(Decimal("2"), "l", "ml") == Decimal("2000")


def test_incompatible_units():
    with pytest.raises(ValueError):
        convert_quantity(Decimal("1"), "piece", "g")
