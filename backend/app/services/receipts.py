import hashlib
import io
import re
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import HTTPException, status
from PIL import Image
from pillow_heif import register_heif_opener
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import Select

from ..ai import generate_image_structured, generate_structured
from ..config import Settings, get_settings
from ..database import SessionLocal
from ..models import Product, ProductAlias, Receipt, ReceiptLine, ShoppingListItem
from ..receipt_schemas import ExtractedReceipt, ExtractedReceiptLine
from .voice import normalize

IGNORED_TERMS = {
    "pfand": "deposit",
    "leergut": "return",
    "tüte": "bag",
    "tuete": "bag",
    "rabatt": "discount",
    "zwischensumme": "subtotal",
    "summe": "subtotal",
    "gesamt": "subtotal",
    "kartenzahlung": "payment",
    "barzahlung": "payment",
    "ec-karte": "payment",
}


def receipt_query(household_id: str) -> Select[tuple[Receipt]]:
    return (
        select(Receipt)
        .options(
            selectinload(Receipt.lines).selectinload(ReceiptLine.product),
            selectinload(Receipt.uploaded_by),
        )
        .where(Receipt.household_id == household_id)
    )


def load_receipt(db: Session, household_id: str, receipt_id: str, *, lock: bool = False) -> Receipt:
    statement = receipt_query(household_id).where(Receipt.id == receipt_id)
    if lock:
        statement = statement.with_for_update()
    receipt = db.scalar(statement)
    if receipt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kassenbon nicht gefunden")
    return receipt


def compute_image_hash(images: list[bytes]) -> str:
    digest = hashlib.sha256()
    for image in images:
        digest.update(hashlib.sha256(image).digest())
    return digest.hexdigest()


def compute_fingerprint(receipt: Receipt) -> str | None:
    if not receipt.merchant or not receipt.purchased_at or receipt.total is None:
        return None
    value = "|".join(
        (
            normalize(receipt.merchant),
            receipt.purchased_at.astimezone(UTC).replace(second=0, microsecond=0).isoformat(),
            f"{receipt.total:.2f}",
            receipt.image_hash,
        )
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _extract_pdf_text(content: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


def _as_jpeg(content: bytes) -> bytes:
    register_heif_opener()
    with Image.open(io.BytesIO(content)) as image:
        image.thumbnail((2000, 2000))
        rendered: Image.Image = image.convert("RGB") if image.mode != "RGB" else image
        output = io.BytesIO()
        rendered.save(output, format="JPEG", quality=86, optimize=True)
        return output.getvalue()


def _run_tesseract(path: Path) -> str:
    temporary: tempfile.TemporaryDirectory[str] | None = None
    input_path = path
    if path.suffix.lower() in {".heic", ".heif"}:
        temporary = tempfile.TemporaryDirectory(prefix="vorrat-receipt-")
        input_path = Path(temporary.name) / "receipt.jpg"
        input_path.write_bytes(_as_jpeg(path.read_bytes()))
    try:
        result = subprocess.run(
            ["tesseract", str(input_path), "stdout", "-l", "deu+eng"],
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {
                "code": "receipt_ocr_unavailable",
                "message": "Lokale Bonerkennung ist nicht verfügbar",
            },
        ) from exc
    finally:
        if temporary:
            temporary.cleanup()
    return result.stdout


def parse_receipt_text(text: str) -> ExtractedReceipt:
    rows = [" ".join(row.split()) for row in text.splitlines() if row.strip()]
    merchant = rows[0][:180] if rows else None
    purchased_at = None
    date_match = re.search(r"\b(\d{2})[.\-/](\d{2})[.\-/](\d{2,4})(?:\s+(\d{2}):(\d{2}))?", text)
    if date_match:
        day, month, year, hour, minute = date_match.groups()
        full_year = int(year) + (2000 if len(year) == 2 else 0)
        try:
            purchased_at = datetime(
                full_year, int(month), int(day), int(hour or 0), int(minute or 0), tzinfo=UTC
            )
        except ValueError:
            purchased_at = None
    lines: list[ExtractedReceiptLine] = []
    total = None
    for row in rows:
        price_match = re.search(r"(-?\d+[,.]\d{2})\s*(?:€|EUR)?$", row, re.IGNORECASE)
        if not price_match:
            continue
        price = Decimal(price_match.group(1).replace(",", "."))
        normalized = normalize(row)
        kind = next((value for term, value in IGNORED_TERMS.items() if term in normalized), "food")
        if kind == "subtotal" and any(term in normalized for term in ("summe", "gesamt")):
            total = abs(price)
            continue
        quantity = Decimal("1")
        unit = "piece"
        quantity_match = re.search(r"(\d+(?:[,.]\d+)?)\s*[xX]\b", row)
        weight_match = re.search(r"(\d+(?:[,.]\d+)?)\s*(kg|g)\b", row, re.IGNORECASE)
        if quantity_match:
            quantity = Decimal(quantity_match.group(1).replace(",", "."))
        elif weight_match:
            quantity = Decimal(weight_match.group(1).replace(",", "."))
            unit = weight_match.group(2).lower()
        lines.append(
            ExtractedReceiptLine(
                raw_text=row,
                quantity=quantity,
                unit=unit,
                total_price=price,
                line_kind=kind,
                confidence=0.55 if kind == "food" else 0.95,
            )
        )
    return ExtractedReceipt(merchant=merchant, purchased_at=purchased_at, lines=lines, total=total)


def _receipt_prompt(products: list[Product], ocr_text: str = "") -> str:
    catalog = [{"id": product.id, "name": product.name} for product in products]
    return (
        "Lies alle Seiten dieses deutschen Kassenbons. Gib Händler, Datum/Uhrzeit, Gesamtsumme "
        "und jede Position zurück. Erkenne Menge, Einheit, Einzel- und Gesamtpreis. "
        "Markiere Pfand, "
        "Leergut, Tüten, Rabatte, Zwischensummen und Zahlungsarten mit passendem line_kind. "
        "suggested_product_id darf nur eine ID aus diesem Haushaltskatalog sein; "
        "bei Unsicherheit null. "
        f"Katalog: {catalog}. OCR-Text, falls vorhanden: {ocr_text[:12000]}"
    )


def extract_receipt(
    db: Session, household_id: str, paths: list[Path], settings: Settings
) -> tuple[ExtractedReceipt, str]:
    products = list(db.scalars(select(Product).where(Product.household_id == household_id)))
    pdf_text = "\n".join(
        _extract_pdf_text(path.read_bytes()) for path in paths if path.suffix.lower() == ".pdf"
    )
    image_paths = [path for path in paths if path.suffix.lower() != ".pdf"]
    mode = settings.receipt_ocr_mode.lower()
    if mode == "vision_llm" and image_paths:
        images = [_as_jpeg(path.read_bytes()) for path in image_paths]
        return (
            generate_image_structured(
                db,
                household_id=household_id,
                feature="receipt",
                prompt=_receipt_prompt(products, pdf_text),
                images=images,
                response_model=ExtractedReceipt,
                settings=settings,
            ),
            "vision_llm",
        )
    ocr_text = pdf_text + "\n" + "\n".join(_run_tesseract(path) for path in image_paths)
    if not ocr_text.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "receipt_text_empty", "message": "Auf dem Bon wurde kein Text erkannt"},
        )
    if mode in {"vision_llm", "tesseract_llm"}:
        return (
            generate_structured(
                db,
                household_id=household_id,
                feature="receipt",
                prompt=_receipt_prompt(products, ocr_text),
                response_model=ExtractedReceipt,
                settings=settings,
            ),
            "tesseract_llm" if image_paths else "pdf_text_llm",
        )
    return parse_receipt_text(ocr_text), "tesseract_rules" if image_paths else "pdf_text_rules"


def _match_product(
    db: Session, household_id: str, line: ExtractedReceiptLine
) -> tuple[Product | None, float]:
    if line.suggested_product_id:
        suggested = db.scalar(
            select(Product).where(
                Product.id == line.suggested_product_id, Product.household_id == household_id
            )
        )
        if suggested:
            return suggested, max(line.confidence, 0.8)
    needle = normalize(line.raw_text)[:180]
    alias_match = db.execute(
        select(ProductAlias, Product)
        .join(Product, Product.id == ProductAlias.product_id)
        .where(
            ProductAlias.household_id == household_id,
            ProductAlias.normalized_alias == needle,
            Product.household_id == household_id,
        )
    ).first()
    if alias_match:
        alias, product = alias_match
        alias.usage_count += 1
        return product, 1.0
    products = list(db.scalars(select(Product).where(Product.household_id == household_id)))
    ranked = sorted(
        (
            (SequenceMatcher(None, needle, normalize(product.name)).ratio(), product)
            for product in products
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    return (ranked[0][1], ranked[0][0]) if ranked and ranked[0][0] >= 0.6 else (None, 0.0)


def _recent_shopping_quantity(
    db: Session, household_id: str, product_id: str, since: datetime
) -> Decimal:
    items = db.scalars(
        select(ShoppingListItem).where(
            ShoppingListItem.household_id == household_id,
            ShoppingListItem.product_id == product_id,
            ShoppingListItem.linked_movement_id.is_not(None),
            ShoppingListItem.checked_at >= since,
        )
    )
    return sum((item.quantity for item in items), Decimal("0"))


def apply_extraction(
    db: Session, receipt: Receipt, extracted: ExtractedReceipt, settings: Settings
) -> None:
    receipt.merchant = extracted.merchant
    receipt.purchased_at = extracted.purchased_at
    receipt.total = extracted.total
    receipt.lines.clear()
    since = datetime.now(UTC) - timedelta(hours=settings.receipt_shopping_dedup_hours)
    for position, extracted_line in enumerate(extracted.lines):
        ignored = extracted_line.line_kind != "food" or any(
            term in normalize(extracted_line.raw_text) for term in IGNORED_TERMS
        )
        product, confidence = (None, extracted_line.confidence)
        if not ignored:
            product, confidence = _match_product(db, receipt.household_id, extracted_line)
        line_status = "ignored" if ignored else "unknown"
        quantity = extracted_line.quantity
        if product:
            line_status = "mapped" if confidence >= 0.85 else "uncertain"
            recent = _recent_shopping_quantity(db, receipt.household_id, product.id, since)
            if recent >= quantity:
                line_status = "already_booked"
            elif recent > 0:
                quantity -= recent
        receipt.lines.append(
            ReceiptLine(
                household_id=receipt.household_id,
                position=position,
                raw_text=extracted_line.raw_text,
                quantity=quantity,
                unit=extracted_line.unit,
                unit_price=extracted_line.unit_price,
                total_price=extracted_line.total_price,
                line_kind=extracted_line.line_kind,
                status=line_status,
                confidence=Decimal(str(confidence)),
                product_id=product.id if product else None,
                location_id=product.default_location_id if product else None,
                coordinates=extracted_line.coordinates,
            )
        )
    receipt.fingerprint = compute_fingerprint(receipt)
    if receipt.fingerprint:
        duplicate = db.scalar(
            select(Receipt).where(
                Receipt.household_id == receipt.household_id,
                Receipt.id != receipt.id,
                Receipt.fingerprint == receipt.fingerprint,
                Receipt.status.in_(("confirmed", "reversed")),
            )
        )
        receipt.duplicate_of_id = duplicate.id if duplicate else None
    receipt.status = "review"
    receipt.progress = 100
    db.commit()


def process_receipt(receipt_id: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    with SessionLocal() as db:
        receipt = db.get(Receipt, receipt_id)
        if receipt is None:
            return
        receipt.status = "processing"
        receipt.progress = 15
        db.commit()
        try:
            paths = [Path(path) for path in receipt.image_paths]
            extracted, provider = extract_receipt(db, receipt.household_id, paths, settings)
            receipt.analysis_provider = provider
            receipt.progress = 75
            db.commit()
            apply_extraction(db, receipt, extracted, settings)
        except HTTPException as exc:
            db.rollback()
            receipt = db.get(Receipt, receipt_id)
            if receipt:
                detail = exc.detail
                receipt.status = "failed"
                receipt.processing_error = (
                    detail.get("message") if isinstance(detail, dict) else str(detail)
                )
                db.commit()
        except Exception:
            db.rollback()
            receipt = db.get(Receipt, receipt_id)
            if receipt:
                receipt.status = "failed"
                receipt.processing_error = "Bon konnte nicht verarbeitet werden"
                db.commit()


def learn_alias(db: Session, household_id: str, product_id: str, raw_text: str) -> None:
    normalized = normalize(raw_text)[:180]
    if not normalized:
        return
    alias = db.scalar(
        select(ProductAlias).where(
            ProductAlias.household_id == household_id,
            ProductAlias.normalized_alias == normalized,
        )
    )
    if alias:
        alias.product_id = product_id
        alias.alias = raw_text[:180]
        alias.source = "receipt"
        alias.usage_count += 1
    else:
        db.add(
            ProductAlias(
                household_id=household_id,
                product_id=product_id,
                alias=raw_text[:180],
                normalized_alias=normalized,
                source="receipt",
                usage_count=1,
            )
        )


def delete_expired_receipt_images(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=max(0, settings.receipt_image_retention_days))
    with SessionLocal() as db:
        receipts = db.scalars(
            select(Receipt).where(
                Receipt.confirmed_at.is_not(None),
                Receipt.confirmed_at <= cutoff,
                Receipt.image_paths != [],
            )
        )
        for receipt in receipts:
            for path in receipt.image_paths:
                Path(path).unlink(missing_ok=True)
            receipt.image_paths = []
        db.commit()
