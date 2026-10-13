from collections.abc import Iterable
from decimal import Decimal

CONVERSIONS: dict[tuple[str, str], Decimal] = {
    ("g", "kg"): Decimal("0.001"),
    ("kg", "g"): Decimal("1000"),
    ("ml", "l"): Decimal("0.001"),
    ("l", "ml"): Decimal("1000"),
}


def convert_quantity(value: Decimal, source: str, target: str) -> Decimal:
    if source == target:
        return value
    try:
        return value * CONVERSIONS[(source, target)]
    except KeyError as exc:
        raise ValueError(f"Cannot convert {source} to {target}") from exc


def sum_converted(values: Iterable[tuple[Decimal, str]], target: str) -> Decimal:
    total = Decimal("0")
    for value, source in values:
        try:
            total += convert_quantity(value, source, target)
        except ValueError:
            continue
    return total.quantize(Decimal("0.001"))
