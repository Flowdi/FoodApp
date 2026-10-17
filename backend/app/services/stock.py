import uuid
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import MovementType, StockBatch, StockMovement, uuid_str
from ..schemas import MovementResult


def load_or_create_product_stock(
    db: Session,
    *,
    household_id: str,
    product_id: str,
    location_id: str,
    best_before: date | None,
) -> StockBatch:
    values = {
        "id": uuid_str(),
        "household_id": household_id,
        "product_id": product_id,
        "location_id": location_id,
        "quantity": 0,
        "unit": "package",
        "best_before": best_before,
        "version": 1,
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        pg_statement = postgresql_insert(StockBatch).values(**values)
        pg_statement = pg_statement.on_conflict_do_nothing(
            index_elements=["household_id", "product_id"]
        )
        db.execute(pg_statement)
    elif dialect == "sqlite":
        sqlite_statement = sqlite_insert(StockBatch).values(**values)
        sqlite_statement = sqlite_statement.on_conflict_do_nothing(
            index_elements=["household_id", "product_id"]
        )
        db.execute(sqlite_statement)
    else:
        existing = db.scalar(
            select(StockBatch).where(
                StockBatch.household_id == household_id,
                StockBatch.product_id == product_id,
            )
        )
        if existing is None:
            db.add(StockBatch(**values))
            db.flush()
    batch = db.scalar(
        select(StockBatch)
        .where(
            StockBatch.household_id == household_id,
            StockBatch.product_id == product_id,
        )
        .with_for_update()
    )
    assert batch is not None
    batch.location_id = location_id
    if best_before and (batch.best_before is None or best_before < batch.best_before):
        batch.best_before = best_before
    return batch


def existing_result(db: Session, household_id: str, key: str) -> MovementResult | None:
    movement = db.scalar(
        select(StockMovement).where(
            StockMovement.household_id == household_id,
            StockMovement.idempotency_key == key,
        )
    )
    if movement is None:
        return None
    batch = db.scalar(
        select(StockBatch).where(
            StockBatch.id == movement.batch_id,
            StockBatch.household_id == household_id,
        )
    )
    assert batch is not None
    return MovementResult(movement=movement, batch=batch, replayed=True)


def existing_operation(db: Session, household_id: str, key: str) -> list[MovementResult]:
    movements = list(
        db.scalars(
            select(StockMovement)
            .where(
                StockMovement.household_id == household_id,
                StockMovement.operation_key == key,
            )
            .order_by(StockMovement.created_at, StockMovement.id)
        )
    )
    if movements:
        namespace = uuid.UUID(key)
        order = {key: 0}
        order.update(
            {
                str(uuid.uuid5(namespace, f"fefo:{index}")): index
                for index in range(1, len(movements))
            }
        )
        movements.sort(key=lambda movement: order.get(movement.idempotency_key, len(movements)))
    results: list[MovementResult] = []
    for movement in movements:
        batch = db.scalar(
            select(StockBatch).where(
                StockBatch.id == movement.batch_id,
                StockBatch.household_id == household_id,
            )
        )
        assert batch is not None
        results.append(MovementResult(movement=movement, batch=batch, replayed=True))
    return results


def consume_fefo(
    db: Session,
    *,
    household_id: str,
    product_id: str,
    quantity: int,
    unit: str,
    expected_versions: dict[str, int],
    idempotency_key: str,
    user_id: str,
    note: str | None,
    client_info: str | None,
    movement_type: MovementType = MovementType.consume,
) -> list[MovementResult]:
    replay = existing_operation(db, household_id, idempotency_key)
    if replay:
        return replay
    collision = db.scalar(
        select(StockMovement).where(
            StockMovement.household_id == household_id,
            StockMovement.idempotency_key == idempotency_key,
        )
    )
    if collision:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "idempotency_conflict", "message": "Idempotency-Key ist bereits belegt"},
        )
    try:
        namespace = uuid.UUID(idempotency_key)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Ungültiger Idempotency-Key"
        ) from exc

    batches = list(
        db.scalars(
            select(StockBatch)
            .where(
                StockBatch.household_id == household_id,
                StockBatch.product_id == product_id,
                StockBatch.quantity > 0,
            )
            .order_by(StockBatch.best_before.asc().nullslast(), StockBatch.id)
            .with_for_update()
        )
    )
    replay = existing_operation(db, household_id, idempotency_key)
    if replay:
        return replay
    available = sum(batch.quantity for batch in batches)
    if available < quantity:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "insufficient_stock",
                "message": "Nicht genügend Bestand",
                "current": {"quantity": str(available), "unit": unit},
            },
        )

    remaining = quantity
    movements: list[tuple[StockMovement, StockBatch]] = []
    for index, batch in enumerate(batches):
        if remaining <= 0:
            break
        expected_version = expected_versions.get(batch.id)
        if expected_version != batch.version:
            db.rollback()
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
        amount = min(batch.quantity, remaining)
        batch.quantity -= amount
        batch.version += 1
        movement = StockMovement(
            household_id=household_id,
            batch_id=batch.id,
            user_id=user_id,
            movement_type=movement_type,
            quantity_delta=-amount,
            idempotency_key=(
                idempotency_key if index == 0 else str(uuid.uuid5(namespace, f"fefo:{index}"))
            ),
            operation_key=idempotency_key,
            note=note,
            client_info=client_info,
        )
        db.add(movement)
        movements.append((movement, batch))
        remaining -= amount
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = existing_operation(db, household_id, idempotency_key)
        if replay:
            return replay
        raise
    results: list[MovementResult] = []
    for movement, batch in movements:
        db.refresh(movement)
        db.refresh(batch)
        results.append(MovementResult(movement=movement, batch=batch))
    return results


def apply_delta(
    db: Session,
    *,
    household_id: str,
    batch_id: str,
    user_id: str,
    movement_type: MovementType,
    delta: int | Decimal,
    expected_version: int,
    idempotency_key: str,
    note: str | None = None,
    client_info: str | None = None,
    reverses_movement_id: str | None = None,
    commit: bool = True,
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
    if not commit:
        db.flush()
        db.refresh(batch)
        return MovementResult(movement=movement, batch=batch)
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
    commit: bool = True,
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
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "reversal_not_reversible",
                "message": "Ein Storno kann nicht storniert werden",
            },
        )
    if not can_reverse_any and original.user_id != user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Nur eigene Buchungen können storniert werden"
        )
    already_reversed = db.scalar(
        select(StockMovement).where(StockMovement.reverses_movement_id == original.id)
    )
    if already_reversed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "already_reversed", "message": "Buchung wurde bereits storniert"},
        )
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
        commit=commit,
    )


def transfer_stock(
    db: Session,
    *,
    household_id: str,
    batch_id: str,
    target_location_id: str,
    quantity: int,
    expected_version: int,
    idempotency_key: str,
    user_id: str,
    note: str | None,
    client_info: str | None,
) -> list[MovementResult]:
    replay = existing_result(db, household_id, idempotency_key)
    if replay:
        return [replay]
    source = db.scalar(
        select(StockBatch)
        .where(StockBatch.id == batch_id, StockBatch.household_id == household_id)
        .with_for_update()
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bestandsposition nicht gefunden")
    if source.location_id == target_location_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "same_location", "message": "Quell- und Ziellagerort sind identisch"},
        )
    if source.version != expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "version_conflict",
                "message": "Bestand wurde zwischenzeitlich geändert",
                "current": {
                    "id": source.id,
                    "quantity": str(source.quantity),
                    "version": source.version,
                },
            },
        )
    if source.quantity != quantity:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {
                "code": "complete_transfer_required",
                "message": "Eine Bestandsposition kann nur vollständig umgelagert werden",
                "current": {
                    "id": source.id,
                    "quantity": str(source.quantity),
                    "version": source.version,
                },
            },
        )
    source.location_id = target_location_id
    source.version += 1
    movement = StockMovement(
        household_id=household_id,
        batch_id=source.id,
        user_id=user_id,
        movement_type=MovementType.transfer,
        quantity_delta=0,
        idempotency_key=idempotency_key,
        note=note,
        client_info=client_info,
    )
    db.add(movement)
    db.commit()
    for item in (source, movement):
        db.refresh(item)
    return [MovementResult(movement=movement, batch=source)]
