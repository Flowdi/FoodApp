import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..dependencies import HouseholdContext, household_context, require_writer
from ..models import (
    Product,
    Receipt,
    ReceiptLine,
    Role,
    ShoppingListItem,
    StockBatch,
    StockMovement,
    StorageLocation,
)
from ..receipt_schemas import (
    ReceiptConfigRead,
    ReceiptConfirmRequest,
    ReceiptLineRead,
    ReceiptLineUpdate,
    ReceiptRead,
    ReceiptReverseRequest,
)
from ..services.receipts import (
    compute_image_hash,
    learn_alias,
    load_receipt,
    process_receipt,
    receipt_query,
)
from ..services.shopping import create_purchase
from ..services.stock import existing_result, reverse_movement

router = APIRouter(prefix="/receipts", tags=["receipts"])
settings = get_settings()
ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/heic": ".heic",
    "image/heif": ".heic",
    "application/pdf": ".pdf",
}


def receipt_read(db: Session, receipt: Receipt) -> ReceiptRead:
    duplicate_message = None
    if receipt.duplicate_of_id:
        duplicate = db.scalar(
            receipt_query(receipt.household_id).where(Receipt.id == receipt.duplicate_of_id)
        )
        if duplicate:
            created = duplicate.confirmed_at or duplicate.created_at
            duplicate_message = (
                f"Dieser Bon wurde am {created.astimezone().strftime('%d.%m.%Y um %H:%M')} "
                f"bereits von {duplicate.uploaded_by.display_name} eingebucht"
            )
    line_total = sum(
        (
            line.total_price
            for line in receipt.lines
            if line.line_kind == "food" and line.total_price is not None
        ),
        Decimal("0"),
    )
    difference = abs(receipt.total - line_total) if receipt.total is not None else None
    return ReceiptRead(
        id=receipt.id,
        merchant=receipt.merchant,
        purchased_at=receipt.purchased_at,
        total=receipt.total,
        status=receipt.status,
        progress=receipt.progress,
        processing_error=receipt.processing_error,
        analysis_provider=receipt.analysis_provider,
        duplicate_of_id=receipt.duplicate_of_id,
        duplicate_message=duplicate_message,
        sum_difference=difference,
        image_count=len(receipt.image_paths),
        uploaded_by_name=receipt.uploaded_by.display_name,
        created_at=receipt.created_at,
        confirmed_at=receipt.confirmed_at,
        reversed_at=receipt.reversed_at,
        lines=[
            ReceiptLineRead(
                id=line.id,
                raw_text=line.raw_text,
                quantity=line.quantity,
                unit=line.unit,
                unit_price=line.unit_price,
                total_price=line.total_price,
                line_kind=line.line_kind,
                status=line.status,
                confidence=line.confidence,
                product_id=line.product_id,
                product_name=line.product.name if line.product else None,
                location_id=line.location_id,
                best_before=line.best_before,
                movement_id=line.movement_id,
                coordinates=line.coordinates,
                version=line.version,
            )
            for line in sorted(
                receipt.lines,
                key=lambda item: (item.status not in {"uncertain", "unknown"}, item.position),
            )
        ],
    )


@router.get("", response_model=list[ReceiptRead])
def list_receipts(
    context: HouseholdContext = Depends(household_context), db: Session = Depends(get_db)
) -> list[ReceiptRead]:
    receipts = db.scalars(
        receipt_query(context.membership.household_id).order_by(Receipt.created_at.desc())
    )
    return [receipt_read(db, receipt) for receipt in receipts]


@router.get("/config", response_model=ReceiptConfigRead)
def receipt_config(
    context: HouseholdContext = Depends(household_context),
) -> ReceiptConfigRead:
    del context
    mode = settings.receipt_ocr_mode.lower()
    cloud_provider = settings.llm_provider.lower() in {"openai", "anthropic"}
    cloud_processing = (
        "images"
        if mode == "vision_llm" and cloud_provider
        else "text"
        if mode in {"vision_llm", "tesseract_llm"} and cloud_provider
        else "none"
    )
    return ReceiptConfigRead(
        ocr_mode=settings.receipt_ocr_mode,
        images_sent_to_cloud=cloud_processing == "images",
        cloud_processing=cloud_processing,
        image_retention_days=settings.receipt_image_retention_days,
    )


@router.post("", response_model=ReceiptRead, status_code=status.HTTP_202_ACCEPTED)
async def upload_receipt(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(),
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> ReceiptRead:
    if not files or len(files) > 10:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Bitte 1 bis 10 Bondateien wählen"
        )
    contents: list[tuple[bytes, str]] = []
    total_size = 0
    for upload in files:
        suffix = ALLOWED_TYPES.get(upload.content_type or "")
        if suffix is None:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                {"code": "receipt_file_type", "message": "Nur JPG, PNG, HEIC und PDF sind erlaubt"},
            )
        content = await upload.read(15 * 1024 * 1024 + 1)
        if not content or len(content) > 15 * 1024 * 1024:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Bondatei ist zu groß")
        total_size += len(content)
        contents.append((content, suffix))
    if total_size > 50 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Bondateien sind zu groß")
    receipt = Receipt(
        household_id=context.membership.household_id,
        uploaded_by_id=context.user.id,
        status="processing",
        progress=5,
        image_hash=compute_image_hash([content for content, _ in contents]),
        image_paths=[],
    )
    db.add(receipt)
    db.flush()
    target = Path(settings.receipt_storage_path) / receipt.household_id / receipt.id
    target.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for index, (content, suffix) in enumerate(contents):
        path = target / f"{index + 1:02d}{suffix}"
        path.write_bytes(content)
        paths.append(str(path.resolve()))
    receipt.image_paths = paths
    db.commit()
    receipt = load_receipt(db, receipt.household_id, receipt.id)
    background_tasks.add_task(process_receipt, receipt.id)
    return receipt_read(db, receipt)


@router.get("/{receipt_id}", response_model=ReceiptRead)
def get_receipt(
    receipt_id: str,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> ReceiptRead:
    return receipt_read(db, load_receipt(db, context.membership.household_id, receipt_id))


@router.get("/{receipt_id}/images/{image_index}", response_class=FileResponse)
def get_receipt_image(
    receipt_id: str,
    image_index: int,
    context: HouseholdContext = Depends(household_context),
    db: Session = Depends(get_db),
) -> FileResponse:
    receipt = load_receipt(db, context.membership.household_id, receipt_id)
    if image_index < 0 or image_index >= len(receipt.image_paths):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bonbild nicht gefunden")
    path = Path(receipt.image_paths[image_index])
    if not path.is_file():
        raise HTTPException(status.HTTP_410_GONE, "Bonbild wurde gemäß Aufbewahrung gelöscht")
    return FileResponse(path)


@router.post(
    "/{receipt_id}/process", response_model=ReceiptRead, status_code=status.HTTP_202_ACCEPTED
)
def retry_processing(
    receipt_id: str,
    background_tasks: BackgroundTasks,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> ReceiptRead:
    receipt = load_receipt(db, context.membership.household_id, receipt_id)
    if not receipt.image_paths:
        raise HTTPException(status.HTTP_410_GONE, "Bonbilder wurden bereits gelöscht")
    receipt.status = "processing"
    receipt.progress = 5
    receipt.processing_error = None
    db.commit()
    background_tasks.add_task(process_receipt, receipt.id)
    return receipt_read(db, load_receipt(db, receipt.household_id, receipt.id))


@router.patch("/{receipt_id}/lines/{line_id}", response_model=ReceiptRead)
def update_line(
    receipt_id: str,
    line_id: str,
    payload: ReceiptLineUpdate,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> ReceiptRead:
    receipt = load_receipt(db, context.membership.household_id, receipt_id, lock=True)
    if receipt.status != "review":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "receipt_not_editable", "message": "Bon ist nicht mehr bearbeitbar"},
        )
    line = db.scalar(
        select(ReceiptLine)
        .where(
            ReceiptLine.id == line_id,
            ReceiptLine.receipt_id == receipt.id,
            ReceiptLine.household_id == receipt.household_id,
        )
        .with_for_update()
    )
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bonposition nicht gefunden")
    if line.version != payload.expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "receipt_line_conflict", "message": "Bonposition wurde geändert"},
        )
    if "product_id" in payload.model_fields_set:
        if payload.product_id is None:
            line.product_id = None
            line.status = "unknown"
        else:
            product = db.scalar(
                select(Product).where(
                    Product.id == payload.product_id,
                    Product.household_id == receipt.household_id,
                )
            )
            if product is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Produkt nicht gefunden")
            line.product_id = product.id
            line.status = "mapped"
    if payload.quantity is not None:
        line.quantity = payload.quantity
    if payload.unit is not None:
        line.unit = payload.unit
    if "location_id" in payload.model_fields_set:
        if payload.location_id is None:
            line.location_id = None
        else:
            valid_location = db.scalar(
                select(StorageLocation.id).where(
                    StorageLocation.id == payload.location_id,
                    StorageLocation.household_id == receipt.household_id,
                )
            )
            if valid_location is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Lagerort nicht gefunden")
            line.location_id = payload.location_id
    if "best_before" in payload.model_fields_set:
        line.best_before = payload.best_before
    if payload.ignored is True:
        line.status = "ignored"
    elif payload.ignored is False:
        line.status = "mapped" if line.product_id else "unknown"
    line.version += 1
    db.commit()
    return receipt_read(db, load_receipt(db, receipt.household_id, receipt.id))


@router.post("/{receipt_id}/confirm", response_model=ReceiptRead)
def confirm_receipt(
    receipt_id: str,
    payload: ReceiptConfirmRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> ReceiptRead:
    household_id = context.membership.household_id
    receipt = load_receipt(db, household_id, receipt_id, lock=True)
    if receipt.status == "confirmed":
        return receipt_read(db, receipt)
    if receipt.status != "review":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "receipt_not_ready", "message": "Bon ist noch nicht bereit"},
        )
    if receipt.duplicate_of_id and not payload.allow_duplicate:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "receipt_duplicate", "message": "Dieser Bon wurde bereits eingebucht"},
        )
    keys = [line.idempotency_key for line in payload.lines]
    replays = [existing_result(db, household_id, key) for key in keys]
    if any(replays) and not all(replays):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "receipt_partial_replay", "message": "Bon wurde teilweise gebucht"},
        )
    for requested, replay in zip(payload.lines, replays, strict=True):
        line = db.scalar(
            select(ReceiptLine)
            .where(
                ReceiptLine.id == requested.line_id,
                ReceiptLine.receipt_id == receipt.id,
                ReceiptLine.household_id == household_id,
            )
            .with_for_update()
        )
        if line is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bonposition nicht gefunden")
        if line.version != requested.expected_version:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"code": "receipt_line_conflict", "message": "Bonposition wurde geändert"},
            )
        product = db.scalar(
            select(Product).where(
                Product.id == requested.product_id, Product.household_id == household_id
            )
        )
        if product is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Produkt nicht gefunden")
        movement = replay or create_purchase(
            db,
            household_id=household_id,
            product=product,
            quantity=requested.quantity,
            unit=requested.unit,
            location_id=requested.location_id,
            best_before=requested.best_before,
            user_id=context.user.id,
            idempotency_key=requested.idempotency_key,
            client_info="receipt",
            note=f"Kassenbon {receipt.id}",
        )
        line.product_id = product.id
        line.quantity = requested.quantity
        line.unit = requested.unit
        line.location_id = movement.batch.location_id
        line.best_before = requested.best_before
        line.movement_id = movement.movement.id
        line.idempotency_key = requested.idempotency_key
        line.status = "booked"
        line.version += 1
        learn_alias(db, household_id, product.id, line.raw_text)
        shopping_items = db.scalars(
            select(ShoppingListItem)
            .where(
                ShoppingListItem.household_id == household_id,
                ShoppingListItem.product_id == product.id,
                ShoppingListItem.status == "open",
            )
            .with_for_update()
        )
        for item in shopping_items:
            item.status = "checked"
            item.checked_by_id = context.user.id
            item.checked_at = datetime.now(UTC)
            item.linked_movement_id = movement.movement.id
            item.version += 1
    receipt.status = "confirmed"
    receipt.progress = 100
    receipt.confirmed_at = datetime.now(UTC)
    db.commit()
    if settings.receipt_image_retention_days == 0:
        for path in receipt.image_paths:
            Path(path).unlink(missing_ok=True)
        receipt.image_paths = []
        db.commit()
    return receipt_read(db, load_receipt(db, household_id, receipt.id))


@router.post("/{receipt_id}/reverse", response_model=ReceiptRead)
def reverse_receipt(
    receipt_id: str,
    payload: ReceiptReverseRequest,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> ReceiptRead:
    household_id = context.membership.household_id
    receipt = load_receipt(db, household_id, receipt_id, lock=True)
    if receipt.status == "reversed":
        return receipt_read(db, receipt)
    if receipt.status != "confirmed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "receipt_not_confirmed", "message": "Bon wurde nicht eingebucht"},
        )
    if receipt.uploaded_by_id != context.user.id and context.membership.role not in {
        Role.owner,
        Role.admin,
    }:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur eigene Bons können storniert werden")
    namespace = uuid.UUID(payload.idempotency_key)
    for index, line in enumerate((line for line in receipt.lines if line.movement_id), start=1):
        movement_id = line.movement_id
        if movement_id is None:
            continue
        original = db.scalar(
            select(StockMovement).where(
                StockMovement.id == movement_id,
                StockMovement.household_id == household_id,
            )
        )
        if original is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bonbuchung nicht gefunden")
        batch = db.scalar(
            select(StockBatch).where(
                StockBatch.id == original.batch_id, StockBatch.household_id == household_id
            )
        )
        assert batch is not None
        reverse_movement(
            db,
            household_id=household_id,
            movement_id=movement_id,
            user_id=context.user.id,
            expected_version=batch.version,
            idempotency_key=str(uuid.uuid5(namespace, f"receipt-line:{index}")),
            can_reverse_any=context.membership.role in {Role.owner, Role.admin},
            commit=False,
        )
        line.status = "reversed"
        line.version += 1
    receipt.status = "reversed"
    receipt.reversed_at = datetime.now(UTC)
    db.commit()
    return receipt_read(db, load_receipt(db, household_id, receipt.id))


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(
    receipt_id: str,
    context: HouseholdContext = Depends(require_writer),
    db: Session = Depends(get_db),
) -> Response:
    receipt = load_receipt(db, context.membership.household_id, receipt_id)
    if receipt.status in {"confirmed", "reversed"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Eingebuchte Bons können nicht gelöscht werden"
        )
    for path in receipt.image_paths:
        Path(path).unlink(missing_ok=True)
    db.delete(receipt)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
