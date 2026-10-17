"""Store inventory and shopping quantities as package counts.

Revision ID: 0016
Revises: 0015
"""

import math
import re
from collections import defaultdict
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

PACKAGE_UNITS = {"package", "pack", "pkg", "piece", "st", "stk", "stück"}
UNIT_FACTORS = {"g": Decimal("1"), "kg": Decimal("1000"), "ml": Decimal("1"), "l": Decimal("1000")}


def _package_size(value: str | None) -> tuple[Decimal, str] | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\b", value.strip().lower())
    if not match:
        return None
    amount = Decimal(match.group(1).replace(",", "."))
    unit = match.group(2)
    return amount * UNIT_FACTORS[unit], "mass" if unit in {"g", "kg"} else "volume"


def _packages(
    quantity: object, unit: str | None, package: str | None, *, fallback_one: bool
) -> int:
    amount = Decimal(str(quantity or 0))
    if amount <= 0:
        return 0
    normalized = (unit or "").strip().lower()
    if normalized in PACKAGE_UNITS:
        return max(1, math.ceil(amount))
    size = _package_size(package)
    kind = "mass" if normalized in {"g", "kg"} else "volume" if normalized in {"ml", "l"} else None
    if size and kind == size[1]:
        return max(1, math.ceil(amount * UNIT_FACTORS[normalized] / size[0]))
    return 1 if fallback_one else max(1, math.ceil(amount))


def upgrade() -> None:
    bind = op.get_bind()
    products = {
        row.id: row.package_quantity
        for row in bind.execute(sa.text("SELECT id, package_quantity FROM products"))
    }
    batches = list(
        bind.execute(
            sa.text(
                "SELECT id, household_id, product_id, location_id, quantity, unit, "
                "best_before, opened_at, version FROM stock_batches ORDER BY id"
            )
        ).mappings()
    )
    grouped: dict[tuple[str, str], list[sa.RowMapping]] = defaultdict(list)
    converted: dict[str, int] = {}
    for batch in batches:
        grouped[(batch["household_id"], batch["product_id"])].append(batch)
        converted[batch["id"]] = _packages(
            batch["quantity"], batch["unit"], products.get(batch["product_id"]), fallback_one=True
        )

    for rows in grouped.values():
        keeper = rows[0]
        duplicate_ids = [row["id"] for row in rows[1:]]
        all_ids = [row["id"] for row in rows]
        total = sum(converted[item] for item in all_ids)
        dates = [row["best_before"] for row in rows if row["best_before"] is not None]
        opened = [row["opened_at"] for row in rows if row["opened_at"] is not None]
        maximum_version = max(int(row["version"]) for row in rows)

        counts_by_session: dict[str, list[dict[str, object]]] = defaultdict(list)
        for batch in rows:
            counts = bind.execute(
                sa.text(
                    "SELECT id, session_id, batch_id, expected_quantity, counted_quantity "
                    "FROM inventory_counts WHERE batch_id = :batch_id"
                ),
                {"batch_id": batch["id"]},
            ).mappings()
            for count in counts:
                counts_by_session[count["session_id"]].append(
                    {
                        "id": count["id"],
                        "batch_id": count["batch_id"],
                        "expected": _packages(
                            count["expected_quantity"],
                            batch["unit"],
                            products.get(batch["product_id"]),
                            fallback_one=True,
                        ),
                        "counted": _packages(
                            count["counted_quantity"],
                            batch["unit"],
                            products.get(batch["product_id"]),
                            fallback_one=True,
                        ),
                    }
                )
        for counts in counts_by_session.values():
            retained = next(
                (count for count in counts if count["batch_id"] == keeper["id"]), counts[0]
            )
            bind.execute(
                sa.text(
                    "UPDATE inventory_counts SET batch_id = :keeper, "
                    "expected_quantity = :expected, counted_quantity = :counted "
                    "WHERE id = :id"
                ),
                {
                    "keeper": keeper["id"],
                    "expected": sum(int(count["expected"]) for count in counts),
                    "counted": sum(int(count["counted"]) for count in counts),
                    "id": retained["id"],
                },
            )
            for count in counts:
                if count["id"] != retained["id"]:
                    bind.execute(
                        sa.text("DELETE FROM inventory_counts WHERE id = :id"),
                        {"id": count["id"]},
                    )

        for duplicate_id in duplicate_ids:
            bind.execute(
                sa.text(
                    "UPDATE stock_movements SET batch_id = :keeper WHERE batch_id = :duplicate"
                ),
                {"keeper": keeper["id"], "duplicate": duplicate_id},
            )
            bind.execute(sa.text("DELETE FROM stock_batches WHERE id = :id"), {"id": duplicate_id})

        bind.execute(
            sa.text(
                "UPDATE stock_batches SET quantity = :quantity, unit = 'package', "
                "best_before = :best_before, "
                "opened_at = :opened_at, version = :version WHERE id = :id"
            ),
            {
                "quantity": total,
                "best_before": min(dates) if dates else None,
                "opened_at": min(opened) if opened else None,
                "version": maximum_version + max(0, len(rows) - 1),
                "id": keeper["id"],
            },
        )

    for table, quantity_column in (
        ("min_stock_rules", "minimum_quantity"),
        ("shopping_list_items", "quantity"),
    ):
        rows = list(
            bind.execute(
                sa.text(f"SELECT id, product_id, {quantity_column} AS quantity, unit FROM {table}")
            ).mappings()
        )
        for row in rows:
            quantity = _packages(
                row["quantity"], row["unit"], products.get(row["product_id"]), fallback_one=False
            )
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET {quantity_column} = :quantity, "
                    "unit = 'package' WHERE id = :id"
                ),
                {"quantity": quantity, "id": row["id"]},
            )

    bind.execute(sa.text("UPDATE products SET default_unit = 'package'"))
    with op.batch_alter_table("stock_batches") as batch_op:
        batch_op.alter_column(
            "quantity", existing_type=sa.Numeric(14, 3), type_=sa.Integer(), existing_nullable=False
        )
        batch_op.create_unique_constraint(
            "uq_stock_batches_household_product", ["household_id", "product_id"]
        )
    with op.batch_alter_table("min_stock_rules") as batch_op:
        batch_op.alter_column(
            "minimum_quantity",
            existing_type=sa.Numeric(14, 3),
            type_=sa.Integer(),
            existing_nullable=False,
        )
    with op.batch_alter_table("shopping_list_items") as batch_op:
        batch_op.alter_column(
            "quantity", existing_type=sa.Numeric(14, 3), type_=sa.Integer(), existing_nullable=False
        )
    with op.batch_alter_table("inventory_counts") as batch_op:
        batch_op.alter_column(
            "expected_quantity",
            existing_type=sa.Numeric(14, 3),
            type_=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "counted_quantity",
            existing_type=sa.Numeric(14, 3),
            type_=sa.Integer(),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("inventory_counts") as batch_op:
        batch_op.alter_column(
            "counted_quantity",
            existing_type=sa.Integer(),
            type_=sa.Numeric(14, 3),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "expected_quantity",
            existing_type=sa.Integer(),
            type_=sa.Numeric(14, 3),
            existing_nullable=False,
        )
    with op.batch_alter_table("shopping_list_items") as batch_op:
        batch_op.alter_column(
            "quantity", existing_type=sa.Integer(), type_=sa.Numeric(14, 3), existing_nullable=False
        )
    with op.batch_alter_table("min_stock_rules") as batch_op:
        batch_op.alter_column(
            "minimum_quantity",
            existing_type=sa.Integer(),
            type_=sa.Numeric(14, 3),
            existing_nullable=False,
        )
    with op.batch_alter_table("stock_batches") as batch_op:
        batch_op.drop_constraint("uq_stock_batches_household_product", type_="unique")
        batch_op.alter_column(
            "quantity", existing_type=sa.Integer(), type_=sa.Numeric(14, 3), existing_nullable=False
        )
