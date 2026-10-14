from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import HouseholdContext, household_context, require_writer
from ..models import Household, Product, Role, ShoppingListItem
from ..schemas import (
    MovementResult,
    ShoppingCheckRequest,
    ShoppingCheckResult,
    ShoppingFinishRequest,
    ShoppingItemCreate,
    ShoppingItemRead,
    ShoppingRemoveRequest,
    ShoppingUndoRequest,
)
from ..services.shopping import (
    claim_open_item,
    create_purchase,
    item_query,
    load_item,
    sync_min_stock_items,
)
from ..services.stock import existing_result, reverse_movement

router = APIRouter(prefix="/shopping-list", tags=["shopping list"])


def item_read(item: ShoppingListItem) -> ShoppingItemRead:
    return ShoppingItemRead(
        id=item.id,
        product_id=item.product_id,
        product_name=item.product.name if item.product else item.free_text or "Freitext",
        category=item.product.category if item.product else None,
        free_text=item.free_text,
        quantity=item.quantity,
        unit=item.unit,
        note=item.note,
        source=item.source,
        status=item.status,
        checked_by_name=item.checked_by.display_name if item.checked_by else None,
        checked_at=item.checked_at,
        linked_movement_id=item.linked_movement_id,
        version=item.version,
        created_at=item.created_at,
    )


def scoped_product(db: Session, household_id: str, product_id: str | None) -> Product | None:
    if product_id is None:
        return None
    product = db.scalar(
        select(Product).where(Product.id == product_id, Product.household_id == household_id)
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produkt nicht gefunden")
    return product


@router.get("", response_model=list[ShoppingItemRead])
def list_items(
    context: HouseholdContext = Depends(household_context), db: Session = Depends(get_db)
) -> list[ShoppingItemRead]:
    household_id = context.membership.household_id
    sync_min_stock_items(db, household_id)
    items = db.scalars(
        item_query(household_id)
        .where(ShoppingListItem.status != "removed")
        .order_by(ShoppingListItem.status, ShoppingListItem.created_at)
    )
    return [item_read(item) for item in items]


@router.post("", response_model=ShoppingItemRead, status_code=status.HTTP_201_CREATED)
def create_item(
    payload: ShoppingItemCreate,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> ShoppingItemRead:
    household_id = context.membership.household_id
    existing = db.scalar(
        select(ShoppingListItem).where(
            ShoppingListItem.household_id == household_id,
            ShoppingListItem.create_key == payload.idempotency_key,
        )
    )
    if existing:
        return item_read(load_item(db, household_id, existing.id))
    product = scoped_product(db, household_id, payload.product_id)
    item = ShoppingListItem(
        household_id=household_id,
        product_id=product.id if product else None,
        free_text=payload.free_text.strip() if payload.free_text else None,
        quantity=payload.quantity,
        unit=payload.unit,
        note=payload.note,
        source=payload.source,
        created_by_id=context.user.id,
        create_key=payload.idempotency_key,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = db.scalar(
            select(ShoppingListItem).where(
                ShoppingListItem.household_id == household_id,
                ShoppingListItem.create_key == payload.idempotency_key,
            )
        )
        if replay:
            return item_read(load_item(db, household_id, replay.id))
        raise
    return item_read(load_item(db, household_id, item.id))


@router.post("/{item_id}/check", response_model=ShoppingCheckResult)
def check_item(
    item_id: str,
    payload: ShoppingCheckRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> ShoppingCheckResult:
    household_id = context.membership.household_id
    replay = existing_result(db, household_id, payload.idempotency_key)
    if replay:
        return ShoppingCheckResult(
            item=item_read(load_item(db, household_id, item_id)), movement=replay
        )
    try:
        item = claim_open_item(db, household_id, item_id, payload.expected_version, context.user.id)
    except HTTPException:
        replay = existing_result(db, household_id, payload.idempotency_key)
        if replay:
            return ShoppingCheckResult(
                item=item_read(load_item(db, household_id, item_id)), movement=replay
            )
        raise
    product = scoped_product(db, household_id, payload.product_id or item.product_id)
    if product is not None and item.product_id != product.id:
        item.product = product
        item.free_text = None
    movement = None
    household = db.get(Household, household_id)
    should_book = bool(household and household.shopping_check_mode == "instant" and product)
    if should_book:
        assert product is not None
        movement = create_purchase(
            db,
            household_id=household_id,
            product=product,
            quantity=item.quantity,
            unit=item.unit,
            location_id=payload.location_id,
            best_before=payload.best_before,
            user_id=context.user.id,
            idempotency_key=payload.idempotency_key,
            client_info=payload.client_info,
        )
    item.linked_movement_id = movement.movement.id if movement else None
    db.commit()
    return ShoppingCheckResult(
        item=item_read(load_item(db, household_id, item.id)), movement=movement
    )


@router.post("/{item_id}/undo", response_model=ShoppingCheckResult)
def undo_check(
    item_id: str,
    payload: ShoppingUndoRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> ShoppingCheckResult:
    household_id = context.membership.household_id
    replay = existing_result(db, household_id, payload.idempotency_key)
    item = load_item(db, household_id, item_id, lock=True)
    if replay:
        return ShoppingCheckResult(item=item_read(item), movement=replay)
    if item.status != "checked" or item.version != payload.expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "shopping_item_conflict",
                "message": "Eintrag wurde zwischenzeitlich geändert",
            },
        )
    if not item.linked_movement_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "shopping_no_movement", "message": "Eintrag besitzt keine Buchung"},
        )
    reversal = reverse_movement(
        db,
        household_id=household_id,
        movement_id=item.linked_movement_id,
        user_id=context.user.id,
        expected_version=payload.expected_batch_version,
        idempotency_key=payload.idempotency_key,
        can_reverse_any=context.membership.role in {Role.owner, Role.admin},
        commit=False,
    )
    item.status = "open"
    item.checked_by_id = None
    item.checked_at = None
    item.linked_movement_id = None
    item.version += 1
    db.commit()
    return ShoppingCheckResult(
        item=item_read(load_item(db, household_id, item.id)), movement=reversal
    )


@router.post("/finish", response_model=list[ShoppingCheckResult])
def finish_trip(
    payload: ShoppingFinishRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> list[ShoppingCheckResult]:
    household_id = context.membership.household_id
    replays = [existing_result(db, household_id, line.idempotency_key) for line in payload.lines]
    if all(replays):
        return [
            ShoppingCheckResult(
                item=item_read(load_item(db, household_id, line.item_id)), movement=replay
            )
            for line, replay in zip(payload.lines, replays, strict=True)
        ]
    if any(replays):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "shopping_partial_replay", "message": "Einkauf wurde teilweise gebucht"},
        )
    results: list[tuple[ShoppingListItem, MovementResult]] = []
    for line in payload.lines:
        item = load_item(db, household_id, line.item_id, lock=True)
        invalid_state = item.status != "checked" or item.linked_movement_id
        if invalid_state or item.version != line.expected_version:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"code": "shopping_item_conflict", "message": "Eintrag wurde geändert"},
            )
        product = scoped_product(db, household_id, item.product_id)
        if product is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                {"code": "shopping_product_required", "message": "Bitte Produkt zuordnen"},
            )
        movement = create_purchase(
            db,
            household_id=household_id,
            product=product,
            quantity=item.quantity,
            unit=item.unit,
            location_id=line.location_id,
            best_before=line.best_before,
            user_id=context.user.id,
            idempotency_key=line.idempotency_key,
            client_info="shopping-finish-trip",
        )
        item.linked_movement_id = movement.movement.id
        item.version += 1
        results.append((item, movement))
    db.commit()
    return [
        ShoppingCheckResult(item=item_read(load_item(db, household_id, item.id)), movement=movement)
        for item, movement in results
    ]


@router.post("/{item_id}/remove", response_model=ShoppingItemRead)
def remove_item(
    item_id: str,
    payload: ShoppingRemoveRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> ShoppingItemRead:
    item = load_item(db, context.membership.household_id, item_id, lock=True)
    if item.version != payload.expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "shopping_item_conflict", "message": "Eintrag wurde geändert"},
        )
    item.status = "removed"
    item.version += 1
    db.commit()
    return item_read(load_item(db, context.membership.household_id, item.id))


@router.post("/clear-checked", status_code=status.HTTP_204_NO_CONTENT)
def clear_checked(
    context: HouseholdContext = Depends(require_writer), db: Session = Depends(get_db)
) -> Response:
    items = db.scalars(
        select(ShoppingListItem).where(
            ShoppingListItem.household_id == context.membership.household_id,
            ShoppingListItem.status == "checked",
        )
    )
    for item in items:
        item.status = "removed"
        item.version += 1
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/export.txt", response_class=Response)
def export_text(
    context: HouseholdContext = Depends(household_context), db: Session = Depends(get_db)
) -> Response:
    items = db.scalars(
        item_query(context.membership.household_id)
        .where(ShoppingListItem.status == "open")
        .order_by(ShoppingListItem.created_at)
    )
    lines = [
        f"- {item.quantity:g} {item.unit} {item.product.name if item.product else item.free_text}"
        for item in items
    ]
    return Response("Einkaufsliste\n" + "\n".join(lines), media_type="text/plain; charset=utf-8")
