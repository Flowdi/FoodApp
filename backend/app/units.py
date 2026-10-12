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
