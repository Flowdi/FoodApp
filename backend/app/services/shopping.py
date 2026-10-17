import uuid
from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import Select

from ..models import (
    MinStockRule,
    MovementType,
    Product,
    ShoppingListItem,
    StockBatch,
    StorageLocation,
)
from ..schemas import MovementResult
from .stock import apply_delta, existing_result, load_or_create_product_stock


def item_query(household_id: str) -> Select[tuple[ShoppingListItem]]:
    return (
        select(ShoppingListItem)
        .options(selectinload(ShoppingListItem.product), selectinload(ShoppingListItem.checked_by))
        .where(ShoppingListItem.household_id == household_id)
    )


def load_item(
    db: Session, household_id: str, item_id: str, *, lock: bool = False
) -> ShoppingListItem:
    statement = item_query(household_id).where(ShoppingListItem.id == item_id)
    if lock:
        statement = statement.with_for_update()
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Einkaufslisteneintrag nicht gefunden")
    return item


def resolve_location(
    db: Session, household_id: str, product: Product, requested_id: str | None
) -> StorageLocation:
    location_id = requested_id or product.default_location_id
    location = None
    if location_id:
        location = db.scalar(
            select(StorageLocation).where(
                StorageLocation.id == location_id,
                StorageLocation.household_id == household_id,
            )
        )
    if location is None:
        location = db.scalar(
            select(StorageLocation)
            .where(StorageLocation.household_id == household_id)
            .order_by(StorageLocation.name)
        )
    if location is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kein Lagerort vorhanden")
    return location


def create_purchase(
    db: Session,
    *,
    household_id: str,
    product: Product,
    quantity: int,
    unit: str,
    location_id: str | None,
    best_before: date | None,
    user_id: str,
    idempotency_key: str,
    client_info: str | None,
    note: str = "Einkaufsliste",
) -> MovementResult:
    replay = existing_result(db, household_id, idempotency_key)
    if replay:
        return replay
    location = resolve_location(db, household_id, product, location_id)
    batch = load_or_create_product_stock(
        db,
        household_id=household_id,
        product_id=product.id,
        location_id=location.id,
        best_before=best_before,
    )
    return apply_delta(
        db,
        household_id=household_id,
        batch_id=batch.id,
        user_id=user_id,
        movement_type=MovementType.purchase,
        delta=quantity,
        expected_version=batch.version,
        idempotency_key=idempotency_key,
        note=note,
        client_info=client_info,
        commit=False,
    )


def ensure_open_version(item: ShoppingListItem, expected_version: int) -> None:
    if item.status != "open" or item.version != expected_version:
        checked = item.checked_by.display_name if item.checked_by else "einer anderen Person"
        checked_at = item.checked_at.isoformat() if item.checked_at else None
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "shopping_item_conflict",
                "message": f"Bereits abgehakt von {checked}",
                "current": {
                    "status": item.status,
                    "version": item.version,
                    "checked_by": checked,
                    "checked_at": checked_at,
                },
            },
        )


def sync_min_stock_items(db: Session, household_id: str) -> bool:
    changed = False
    rules = list(
        db.scalars(
            select(MinStockRule).where(
                MinStockRule.household_id == household_id,
                MinStockRule.active.is_(True),
            )
        )
    )
    for rule in rules:
        batches = db.scalars(
            select(StockBatch).where(
                StockBatch.household_id == household_id,
                StockBatch.product_id == rule.product_id,
                StockBatch.quantity > 0,
            )
        )
        available = sum(batch.quantity for batch in batches)
        missing = rule.minimum_quantity - available
        item = db.scalar(
            select(ShoppingListItem).where(
                ShoppingListItem.household_id == household_id,
                ShoppingListItem.product_id == rule.product_id,
                ShoppingListItem.source == "min_stock",
            )
        )
        if missing > 0:
            other_open = db.scalar(
                select(ShoppingListItem).where(
                    ShoppingListItem.household_id == household_id,
                    ShoppingListItem.product_id == rule.product_id,
                    ShoppingListItem.status == "open",
                )
            )
            if item and item.status == "open":
                if item.quantity != missing or item.unit != "package":
                    item.quantity = missing
                    item.unit = "package"
                    item.version += 1
                    changed = True
            elif item and item.status == "removed" and other_open is None:
                item.status = "open"
                item.quantity = missing
                item.unit = "package"
                item.version += 1
                changed = True
            elif item is None and other_open is None:
                db.add(
                    ShoppingListItem(
                        household_id=household_id,
                        product_id=rule.product_id,
                        quantity=missing,
                        unit="package",
                        source="min_stock",
                        create_key=str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"vorrat:min-stock:{household_id}:{rule.product_id}",
                            )
                        ),
                    )
                )
                changed = True
        elif item and item.status == "open":
            item.status = "removed"
            item.version += 1
            changed = True
    if changed:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return changed


def claim_open_item(
    db: Session,
    household_id: str,
    item_id: str,
    expected_version: int,
    user_id: str,
) -> ShoppingListItem:
    changed = db.execute(
        update(ShoppingListItem)
        .where(
            ShoppingListItem.id == item_id,
            ShoppingListItem.household_id == household_id,
            ShoppingListItem.status == "open",
            ShoppingListItem.version == expected_version,
        )
        .values(
            status="checked",
            checked_by_id=user_id,
            checked_at=datetime.now(UTC),
            version=ShoppingListItem.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(changed, "rowcount", 0) != 1:
        db.rollback()
        current = load_item(db, household_id, item_id)
        ensure_open_version(current, expected_version)
        raise AssertionError("Unreachable shopping item claim")
    return load_item(db, household_id, item_id)
