from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import MovementType, StockBatch, StockMovement
from ..schemas import MovementResult


def existing_result(db: Session, household_id: str, key: str) -> MovementResult | None:
    movement = db.scalar(
        select(StockMovement).where(
            StockMovement.household_id == household_id,
            StockMovement.idempotency_key == key,
        )
    )
    if movement is None:
        return None
    batch = db.scalar(select(StockBatch).where(StockBatch.id == movement.batch_id))
    assert batch is not None
    return MovementResult(movement=movement, batch=batch, replayed=True)


def apply_delta(
    db: Session,
    *,
    household_id: str,
    batch_id: str,
    user_id: str,
    movement_type: MovementType,
    delta: Decimal,
    expected_version: int,
    idempotency_key: str,
    note: str | None = None,
    client_info: str | None = None,
    reverses_movement_id: str | None = None,
) -> MovementResult:
    replay = existing_result(db, household_id, idempotency_key)
    if replay:
        return replay

    batch = db.scalar(
        select(StockBatch).where(
            StockBatch.id == batch_id,
            StockBatch.household_id == household_id,
        )
    )
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bestandsposition nicht gefunden")
    changed = db.execute(
        update(StockBatch)
        .where(
            StockBatch.id == batch_id,
            StockBatch.household_id == household_id,
            StockBatch.version == expected_version,
            StockBatch.quantity + delta >= 0,
        )
        .values(
            quantity=StockBatch.quantity + delta,
            version=StockBatch.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(changed, "rowcount", 0) != 1:
        db.rollback()
        current = db.scalar(
            select(StockBatch).where(
                StockBatch.id == batch_id,
                StockBatch.household_id == household_id,
            )
        )
        assert current is not None
        code = "version_conflict" if current.version != expected_version else "insufficient_stock"
        message = (
            "Bestand wurde zwischenzeitlich geändert"
            if code == "version_conflict"
            else "Nicht genügend Bestand"
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": code,
                "message": message,
                "current": {
                    "id": current.id,
                    "quantity": str(current.quantity),
                    "version": current.version,
                },
            },
        )
    db.expire(batch)
    movement = StockMovement(
        household_id=household_id,
        batch_id=batch.id,
        user_id=user_id,
        movement_type=movement_type,
        quantity_delta=delta,
        idempotency_key=idempotency_key,
        note=note,
        client_info=client_info,
        reverses_movement_id=reverses_movement_id,
    )
    db.add(movement)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = existing_result(db, household_id, idempotency_key)
        if replay:
            return replay
        raise
    db.refresh(batch)
    db.refresh(movement)
    return MovementResult(movement=movement, batch=batch)


def reverse_movement(
    db: Session,
    *,
    household_id: str,
    movement_id: str,
    user_id: str,
    expected_version: int,
    idempotency_key: str,
    can_reverse_any: bool,
) -> MovementResult:
    replay = existing_result(db, household_id, idempotency_key)
    if replay:
        return replay
    original = db.scalar(
        select(StockMovement).where(
            StockMovement.id == movement_id,
            StockMovement.household_id == household_id,
        )
    )
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Buchung nicht gefunden")
    if original.movement_type == MovementType.reversal:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ein Storno kann nicht storniert werden")
    if not can_reverse_any and original.user_id != user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Nur eigene Buchungen können storniert werden"
        )
    already_reversed = db.scalar(
        select(StockMovement).where(StockMovement.reverses_movement_id == original.id)
    )
    if already_reversed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Buchung wurde bereits storniert")
    return apply_delta(
        db,
        household_id=household_id,
        batch_id=original.batch_id,
        user_id=user_id,
        movement_type=MovementType.reversal,
        delta=-original.quantity_delta,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        note=f"Storno von {original.id}",
        reverses_movement_id=original.id,
    )
