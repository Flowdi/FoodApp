import csv
import io
from datetime import datetime
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import Select

from ..config import get_settings
from ..database import get_db
from ..dependencies import HouseholdContext, household_context, require_writer
from ..models import (
    MovementType,
    Product,
    ProductBarcode,
    ProductLookupCache,
    Role,
    StockBatch,
    StockMovement,
    StorageLocation,
    User,
)
from ..schemas import (
    BatchRead,
    ChangeStockRequest,
    FefoConsumeRequest,
    LocationRead,
    LookupResult,
    MovementRead,
    MovementResult,
    ProductCreate,
    ProductRead,
    PurchaseRequest,
    ReversalRequest,
    TransferRequest,
)
from ..services.stock import (
    apply_delta,
    consume_fefo,
    existing_result,
    reverse_movement,
    transfer_stock,
)

router = APIRouter(tags=["inventory"])


@router.get("/locations", response_model=list[LocationRead])
def locations(
    context: HouseholdContext = Depends(household_context), db: Session = Depends(get_db)
) -> list[StorageLocation]:
    return list(
        db.scalars(
            select(StorageLocation)
            .where(StorageLocation.household_id == context.membership.household_id)
            .order_by(StorageLocation.name)
        )
    )


@router.get("/products", response_model=list[ProductRead])
def products(
    q: str | None = None,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> list[Product]:
    stmt = (
        select(Product)
        .options(selectinload(Product.barcodes))
        .where(Product.household_id == context.membership.household_id)
    )
    if q:
        stmt = stmt.where(or_(Product.name.ilike(f"%{q}%"), Product.brand.ilike(f"%{q}%")))
    return list(db.scalars(stmt.order_by(Product.name)))


@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> Product:
    product = Product(
        household_id=context.membership.household_id, **payload.model_dump(exclude={"barcodes"})
    )
    product.barcodes = [ProductBarcode(barcode=value) for value in payload.barcodes]
    db.add(product)
    db.commit()
    return db.scalar(
        select(Product).options(selectinload(Product.barcodes)).where(Product.id == product.id)
    )  # type: ignore[return-value]


@router.get("/products/barcode/{barcode}", response_model=ProductRead)
def by_barcode(
    barcode: str,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> Product:
    product = db.scalar(
        select(Product)
        .join(ProductBarcode)
        .options(selectinload(Product.barcodes))
        .where(
            Product.household_id == context.membership.household_id,
            ProductBarcode.barcode == barcode,
        )
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produkt nicht gefunden")
    return product


@router.get("/lookup/{barcode}", response_model=LookupResult)
def lookup(
    barcode: str,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> LookupResult:
    cached = db.scalar(
        select(ProductLookupCache).where(
            ProductLookupCache.household_id == context.membership.household_id,
            ProductLookupCache.barcode == barcode,
        )
    )
    if cached:
        return LookupResult.model_validate(cached.payload)
    settings = get_settings()
    response = httpx.get(
        f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json",
        headers={"User-Agent": settings.open_food_facts_user_agent},
        timeout=8,
    )
    if response.status_code != 200 or response.json().get("status") != 1:
        result = LookupResult(barcode=barcode, found=False)
    else:
        item = response.json().get("product", {})
        result = LookupResult(
            barcode=barcode,
            name=item.get("product_name_de") or item.get("product_name"),
            brand=item.get("brands"),
            quantity=item.get("quantity"),
            image_url=item.get("image_front_small_url"),
            found=True,
        )
    db.add(
        ProductLookupCache(
            household_id=context.membership.household_id,
            barcode=barcode,
            payload=result.model_dump(mode="json"),
        )
    )
    db.commit()
    return result


@router.get("/stock", response_model=list[BatchRead])
def stock(
    location_id: str | None = None,
    q: str | None = None,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> list[StockBatch]:
    stmt = (
        select(StockBatch)
        .join(Product)
        .options(selectinload(StockBatch.product).selectinload(Product.barcodes))
        .where(StockBatch.household_id == context.membership.household_id, StockBatch.quantity > 0)
    )
    if location_id:
        stmt = stmt.where(StockBatch.location_id == location_id)
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q}%"))
    return list(db.scalars(stmt.order_by(StockBatch.best_before.asc().nullslast(), Product.name)))


@router.post("/stock/purchase", response_model=MovementResult, status_code=status.HTTP_201_CREATED)
def purchase(
    payload: PurchaseRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> MovementResult:
    replay = existing_result(db, context.membership.household_id, payload.idempotency_key)
    if replay:
        return replay
    product = db.scalar(
        select(Product).where(
            Product.id == payload.product_id,
            Product.household_id == context.membership.household_id,
        )
    )
    location = db.scalar(
        select(StorageLocation).where(
            StorageLocation.id == payload.location_id,
            StorageLocation.household_id == context.membership.household_id,
        )
    )
    if not product or not location:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produkt oder Lagerort nicht gefunden")
    batch = StockBatch(
        household_id=context.membership.household_id,
        product_id=product.id,
        location_id=location.id,
        quantity=Decimal("0"),
        unit=payload.unit,
        best_before=payload.best_before,
    )
    db.add(batch)
    db.flush()
    return apply_delta(
        db,
        household_id=context.membership.household_id,
        batch_id=batch.id,
        user_id=context.user.id,
        movement_type=MovementType.purchase,
        delta=payload.quantity,
        expected_version=1,
        idempotency_key=payload.idempotency_key,
        client_info=payload.client_info,
    )


@router.post("/stock/transfer", response_model=list[MovementResult])
def transfer(
    payload: TransferRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> list[MovementResult]:
    location = db.scalar(
        select(StorageLocation).where(
            StorageLocation.id == payload.target_location_id,
            StorageLocation.household_id == context.membership.household_id,
        )
    )
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ziellagerort nicht gefunden")
    return transfer_stock(
        db,
        household_id=context.membership.household_id,
        batch_id=payload.batch_id,
        target_location_id=payload.target_location_id,
        quantity=payload.quantity,
        expected_version=payload.expected_version,
        idempotency_key=payload.idempotency_key,
        user_id=context.user.id,
        note=payload.note,
        client_info=payload.client_info,
    )


@router.post("/stock/consume-fefo", response_model=list[MovementResult])
def consume_product_fefo(
    payload: FefoConsumeRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> list[MovementResult]:
    product = db.scalar(
        select(Product).where(
            Product.id == payload.product_id,
            Product.household_id == context.membership.household_id,
        )
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produkt nicht gefunden")
    return consume_fefo(
        db,
        household_id=context.membership.household_id,
        product_id=payload.product_id,
        quantity=payload.quantity,
        unit=payload.unit,
        expected_versions=payload.expected_versions,
        idempotency_key=payload.idempotency_key,
        user_id=context.user.id,
        note=payload.note,
        client_info=payload.client_info,
    )


@router.post("/stock/discard-fefo", response_model=list[MovementResult])
def discard_product_fefo(
    payload: FefoConsumeRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> list[MovementResult]:
    product = db.scalar(
        select(Product).where(
            Product.id == payload.product_id,
            Product.household_id == context.membership.household_id,
        )
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produkt nicht gefunden")
    return consume_fefo(
        db,
        household_id=context.membership.household_id,
        product_id=payload.product_id,
        quantity=payload.quantity,
        unit=payload.unit,
        expected_versions=payload.expected_versions,
        idempotency_key=payload.idempotency_key,
        user_id=context.user.id,
        note=payload.note,
        client_info=payload.client_info,
        movement_type=MovementType.discard,
    )


@router.post("/stock/{batch_id}/{action}", response_model=MovementResult)
def change_stock(
    batch_id: str,
    action: str,
    payload: ChangeStockRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> MovementResult:
    try:
        movement_type = MovementType(action)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Unbekannter Buchungstyp"
        ) from exc
    if movement_type not in {MovementType.consume, MovementType.discard}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Nur consume oder discard erlaubt"
        )
    return apply_delta(
        db,
        household_id=context.membership.household_id,
        batch_id=batch_id,
        user_id=context.user.id,
        movement_type=movement_type,
        delta=-payload.quantity,
        expected_version=payload.expected_version,
        idempotency_key=payload.idempotency_key,
        note=payload.note,
        client_info=payload.client_info,
    )


def movement_query(
    household_id: str,
    user_id: str | None,
    product_id: str | None,
    movement_type: MovementType | None,
    start: datetime | None,
    end: datetime | None,
) -> Select[tuple[StockMovement]]:
    stmt = select(StockMovement).where(StockMovement.household_id == household_id)
    if product_id:
        stmt = stmt.where(
            StockMovement.batch_id.in_(
                select(StockBatch.id).where(StockBatch.product_id == product_id)
            )
        )
    if user_id:
        stmt = stmt.where(StockMovement.user_id == user_id)
    if movement_type:
        stmt = stmt.where(StockMovement.movement_type == movement_type)
    if start:
        stmt = stmt.where(StockMovement.created_at >= start)
    if end:
        stmt = stmt.where(StockMovement.created_at <= end)
    return stmt


@router.get("/movements/export.csv")
def export_movements(
    user_id: str | None = None,
    product_id: str | None = None,
    movement_type: MovementType | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    stmt = (
        movement_query(
            context.membership.household_id,
            user_id,
            product_id,
            movement_type,
            start,
            end,
        )
        .join(StockBatch, StockBatch.id == StockMovement.batch_id)
        .join(Product, Product.id == StockBatch.product_id)
        .join(User, User.id == StockMovement.user_id)
        .with_only_columns(StockMovement, Product.name, User.display_name)
        .order_by(StockMovement.created_at.desc())
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Zeitpunkt", "Nutzer", "Produkt", "Typ", "Menge", "Notiz", "Gerät"])
    for movement, product_name, display_name in db.execute(stmt):
        writer.writerow(
            [
                movement.created_at.isoformat(),
                display_name,
                product_name,
                movement.movement_type.value,
                movement.quantity_delta,
                movement.note or "",
                movement.client_info or "",
            ]
        )
    payload = output.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="vorrat-buchungen.csv"'},
    )


@router.post("/movements/{movement_id}/reverse", response_model=MovementResult)
def reverse(
    movement_id: str,
    payload: ReversalRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> MovementResult:
    return reverse_movement(
        db,
        household_id=context.membership.household_id,
        movement_id=movement_id,
        user_id=context.user.id,
        expected_version=payload.expected_version,
        idempotency_key=payload.idempotency_key,
        can_reverse_any=context.membership.role in {Role.owner, Role.admin},
    )


@router.get("/movements", response_model=list[MovementRead])
def movements(
    limit: int = Query(100, ge=1, le=500),
    user_id: str | None = None,
    product_id: str | None = None,
    movement_type: MovementType | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> list[MovementRead]:
    stmt = (
        movement_query(
            context.membership.household_id,
            user_id,
            product_id,
            movement_type,
            start,
            end,
        )
        .join(StockBatch, StockBatch.id == StockMovement.batch_id)
        .join(Product, Product.id == StockBatch.product_id)
        .join(User, User.id == StockMovement.user_id)
        .with_only_columns(StockMovement, Product.id, Product.name, User.display_name)
        .order_by(StockMovement.created_at.desc())
        .limit(limit)
    )
    return [
        MovementRead.model_validate(movement).model_copy(
            update={
                "product_id": product_id_value,
                "product_name": product_name,
                "user_name": user_name,
            }
        )
        for movement, product_id_value, product_name, user_name in db.execute(stmt)
    ]
