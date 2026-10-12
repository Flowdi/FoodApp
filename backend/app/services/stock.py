import uuid
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


def transfer_stock(
    db: Session,
    *,
    household_id: str,
    batch_id: str,
    target_location_id: str,
    quantity: Decimal,
    expected_version: int,
    idempotency_key: str,
    user_id: str,
    note: str | None,
    client_info: str | None,
) -> list[MovementResult]:
    try:
        namespace = uuid.UUID(idempotency_key)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Ungültiger Idempotency-Key"
        ) from exc
    source_key = str(uuid.uuid5(namespace, "source"))
    target_key = str(uuid.uuid5(namespace, "target"))
    replay = existing_result(db, household_id, source_key)
    if replay:
        target_replay = existing_result(db, household_id, target_key)
        assert target_replay is not None
        return [replay, target_replay]
    source = db.scalar(
        select(StockBatch)
        .where(StockBatch.id == batch_id, StockBatch.household_id == household_id)
        .with_for_update()
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bestandsposition nicht gefunden")
    if source.location_id == target_location_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Quell- und Ziellagerort sind identisch")
    if source.version != expected_version:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bestand wurde zwischenzeitlich geändert")
    if source.quantity < quantity:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nicht genügend Bestand")
    target = db.scalar(
        select(StockBatch)
        .where(
            StockBatch.household_id == household_id,
            StockBatch.product_id == source.product_id,
            StockBatch.location_id == target_location_id,
            StockBatch.unit == source.unit,
            StockBatch.best_before == source.best_before,
            StockBatch.opened_at == source.opened_at,
        )
        .with_for_update()
    )
    if target is None:
        target = StockBatch(
            household_id=household_id,
            product_id=source.product_id,
            location_id=target_location_id,
            quantity=Decimal("0"),
            unit=source.unit,
            best_before=source.best_before,
            opened_at=source.opened_at,
        )
        db.add(target)
        db.flush()
    source.quantity -= quantity
    source.version += 1
    target.quantity += quantity
    target.version += 1
    source_movement = StockMovement(
        household_id=household_id,
        batch_id=source.id,
        user_id=user_id,
        movement_type=MovementType.transfer,
        quantity_delta=-quantity,
        idempotency_key=source_key,
        note=note,
        client_info=client_info,
    )
    target_movement = StockMovement(
        household_id=household_id,
        batch_id=target.id,
        user_id=user_id,
        movement_type=MovementType.transfer,
        quantity_delta=quantity,
        idempotency_key=target_key,
        note=note,
        client_info=client_info,
    )
    db.add_all([source_movement, target_movement])
    db.commit()
    for item in (source, target, source_movement, target_movement):
        db.refresh(item)
    return [
        MovementResult(movement=source_movement, batch=source),
        MovementResult(movement=target_movement, batch=target),
    ]
