import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import HouseholdContext, household_context, require_writer
from ..models import InventoryCount, InventorySession, MovementType, StockBatch, StorageLocation
from ..schemas import (
    InventoryConfirmRequest,
    InventoryCountRead,
    InventoryCountWrite,
    InventoryDetail,
    InventoryStartRequest,
    MovementResult,
)
from ..services.stock import apply_delta

router = APIRouter(prefix="/inventory-sessions", tags=["inventory sessions"])


def load_session(db: Session, household_id: str, session_id: str) -> InventorySession:
    inventory = db.scalar(
        select(InventorySession).where(
            InventorySession.id == session_id,
            InventorySession.household_id == household_id,
        )
    )
    if inventory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventur nicht gefunden")
    return inventory


@router.post("", response_model=InventoryDetail, status_code=status.HTTP_201_CREATED)
def start_inventory(
    payload: InventoryStartRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> InventoryDetail:
    household_id = context.membership.household_id
    if payload.location_id:
        location = db.scalar(
            select(StorageLocation).where(
                StorageLocation.id == payload.location_id,
                StorageLocation.household_id == household_id,
            )
        )
        if location is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Lagerort nicht gefunden")
    inventory = InventorySession(
        household_id=household_id,
        location_id=payload.location_id,
        created_by_id=context.user.id,
    )
    db.add(inventory)
    db.flush()
    stmt = select(StockBatch).where(
        StockBatch.household_id == household_id,
        StockBatch.quantity > 0,
    )
    if payload.location_id:
        stmt = stmt.where(StockBatch.location_id == payload.location_id)
    counts = [
        InventoryCount(
            session_id=inventory.id,
            batch_id=batch.id,
            expected_quantity=batch.quantity,
            counted_quantity=batch.quantity,
        )
        for batch in db.scalars(stmt)
    ]
    db.add_all(counts)
    db.commit()
    db.refresh(inventory)
    return InventoryDetail(session=inventory, counts=counts)


@router.get("/{session_id}", response_model=InventoryDetail)
def inventory_detail(
    session_id: str,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> InventoryDetail:
    inventory = load_session(db, context.membership.household_id, session_id)
    counts = list(
        db.scalars(
            select(InventoryCount)
            .where(InventoryCount.session_id == inventory.id)
            .order_by(InventoryCount.batch_id)
        )
    )
    return InventoryDetail(session=inventory, counts=counts)


@router.put("/{session_id}/counts", response_model=InventoryCountRead)
def record_count(
    session_id: str,
    payload: InventoryCountWrite,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> InventoryCount:
    inventory = load_session(db, context.membership.household_id, session_id)
    if inventory.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "Inventur ist bereits abgeschlossen")
    count = db.scalar(
        select(InventoryCount).where(
            InventoryCount.session_id == inventory.id,
            InventoryCount.batch_id == payload.batch_id,
        )
    )
    if count is None:
        batch = db.scalar(
            select(StockBatch).where(
                StockBatch.id == payload.batch_id,
                StockBatch.household_id == context.membership.household_id,
            )
        )
        if batch is None or (inventory.location_id and batch.location_id != inventory.location_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bestandsposition nicht gefunden")
        count = InventoryCount(
            session_id=inventory.id,
            batch_id=batch.id,
            expected_quantity=batch.quantity,
            counted_quantity=payload.counted_quantity,
        )
        db.add(count)
    else:
        count.counted_quantity = payload.counted_quantity
    db.commit()
    db.refresh(count)
    return count


@router.post("/{session_id}/confirm", response_model=list[MovementResult])
def confirm_inventory(
    session_id: str,
    payload: InventoryConfirmRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> list[MovementResult]:
    inventory = load_session(db, context.membership.household_id, session_id)
    if inventory.status == "completed":
        return []
    try:
        namespace = uuid.UUID(payload.idempotency_key)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Ungültiger Idempotency-Key"
        ) from exc
    counts = list(
        db.scalars(select(InventoryCount).where(InventoryCount.session_id == inventory.id))
    )
    results: list[MovementResult] = []
    for count in counts:
        batch = db.get(StockBatch, count.batch_id)
        if batch is None:
            continue
        delta = count.counted_quantity - batch.quantity
        if delta:
            results.append(
                apply_delta(
                    db,
                    household_id=context.membership.household_id,
                    batch_id=batch.id,
                    user_id=context.user.id,
                    movement_type=MovementType.adjust,
                    delta=delta,
                    expected_version=batch.version,
                    idempotency_key=str(uuid.uuid5(namespace, batch.id)),
                    note=f"Inventur {inventory.id}",
                )
            )
    inventory = load_session(db, context.membership.household_id, session_id)
    inventory.status = "completed"
    db.commit()
    return results
