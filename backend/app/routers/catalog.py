from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import HouseholdContext, household_context, require_admin
from ..models import (
    AuditLog,
    MinStockRule,
    Product,
    ProductBarcode,
    StockBatch,
    StorageLocation,
)
from ..schemas import (
    BatchRead,
    BatchUpdate,
    MinStockRuleRead,
    MinStockRuleWrite,
    ProductRead,
    ProductUpdate,
)

router = APIRouter(tags=["catalog"])


def load_product(db: Session, household_id: str, product_id: str) -> Product:
    product = db.scalar(
        select(Product)
        .options(selectinload(Product.barcodes))
        .where(Product.id == product_id, Product.household_id == household_id)
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produkt nicht gefunden")
    return product


def load_batch(db: Session, household_id: str, batch_id: str) -> StockBatch:
    batch = db.scalar(
        select(StockBatch)
        .options(selectinload(StockBatch.product).selectinload(Product.barcodes))
        .where(StockBatch.id == batch_id, StockBatch.household_id == household_id)
    )
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bestandsposition nicht gefunden")
    return batch


@router.patch("/products/{product_id}", response_model=ProductRead)
def update_product(
    product_id: str,
    payload: ProductUpdate,
    context: HouseholdContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Product:
    product = load_product(db, context.membership.household_id, product_id)
    changes: dict[str, object] = {}
    values = payload.model_dump(exclude_unset=True, exclude={"barcodes"})
    if values.get("default_location_id"):
        location = db.scalar(
            select(StorageLocation).where(
                StorageLocation.id == values["default_location_id"],
                StorageLocation.household_id == context.membership.household_id,
            )
        )
        if location is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Lagerort nicht gefunden")
    for field, value in values.items():
        old_value = getattr(product, field)
        if old_value != value:
            changes[field] = {"from": old_value, "to": value}
            setattr(product, field, value)
    if payload.barcodes is not None:
        old_barcodes = sorted(item.barcode for item in product.barcodes)
        new_barcodes = sorted(set(payload.barcodes))
        if old_barcodes != new_barcodes:
            changes["barcodes"] = {"from": old_barcodes, "to": new_barcodes}
            retained = [item for item in product.barcodes if item.barcode in new_barcodes]
            retained_values = {item.barcode for item in retained}
            product.barcodes = retained + [
                ProductBarcode(barcode=value)
                for value in new_barcodes
                if value not in retained_values
            ]
    if changes:
        db.add(
            AuditLog(
                household_id=context.membership.household_id,
                user_id=context.user.id,
                entity_type="product",
                entity_id=product.id,
                action="update",
                changes=changes,
            )
        )
        db.commit()
    return load_product(db, context.membership.household_id, product_id)


@router.patch("/stock/{batch_id}", response_model=BatchRead)
def update_batch(
    batch_id: str,
    payload: BatchUpdate,
    context: HouseholdContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StockBatch:
    batch = load_batch(db, context.membership.household_id, batch_id)
    if batch.version != payload.expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "version_conflict",
                "message": "Bestand wurde zwischenzeitlich geändert",
                "current": {
                    "id": batch.id,
                    "quantity": str(batch.quantity),
                    "version": batch.version,
                },
            },
        )
    values = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    if "location_id" in values:
        location = db.scalar(
            select(StorageLocation).where(
                StorageLocation.id == values["location_id"],
                StorageLocation.household_id == context.membership.household_id,
            )
        )
        if location is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Lagerort nicht gefunden")
    changes: dict[str, object] = {}
    for field, value in values.items():
        old_value = getattr(batch, field)
        if old_value != value:
            changes[field] = {"from": str(old_value), "to": str(value)}
            setattr(batch, field, value)
    if changes:
        batch.version += 1
        db.add(
            AuditLog(
                household_id=context.membership.household_id,
                user_id=context.user.id,
                entity_type="stock_batch",
                entity_id=batch.id,
                action="update",
                changes=changes,
            )
        )
        db.commit()
    return load_batch(db, context.membership.household_id, batch_id)


@router.put("/products/{product_id}/min-stock", response_model=MinStockRuleRead)
def set_min_stock(
    product_id: str,
    payload: MinStockRuleWrite,
    context: HouseholdContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MinStockRule:
    load_product(db, context.membership.household_id, product_id)
    rule = db.scalar(
        select(MinStockRule).where(
            MinStockRule.household_id == context.membership.household_id,
            MinStockRule.product_id == product_id,
        )
    )
    if rule is None:
        rule = MinStockRule(
            household_id=context.membership.household_id,
            product_id=product_id,
            **payload.model_dump(),
        )
        db.add(rule)
    else:
        rule.minimum_quantity = payload.minimum_quantity
        rule.unit = payload.unit
        rule.active = payload.active
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/min-stock", response_model=list[MinStockRuleRead])
def min_stock_rules(
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> list[MinStockRule]:
    return list(
        db.scalars(
            select(MinStockRule)
            .where(MinStockRule.household_id == context.membership.household_id)
            .order_by(MinStockRule.product_id)
        )
    )
