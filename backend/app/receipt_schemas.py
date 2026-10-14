from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .schemas import IdempotencyKey, Quantity


class ExtractedReceiptLine(BaseModel):
    raw_text: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(default=Decimal("1"), gt=0, decimal_places=3)
    unit: str = Field(default="piece", min_length=1, max_length=20)
    unit_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    total_price: Decimal | None = Field(default=None, decimal_places=2)
    line_kind: Literal[
        "food", "deposit", "return", "bag", "discount", "subtotal", "payment", "other"
    ] = "food"
    suggested_product_id: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    coordinates: dict[str, object] | None = None


class ExtractedReceipt(BaseModel):
    merchant: str | None = Field(default=None, max_length=180)
    purchased_at: datetime | None = None
    lines: list[ExtractedReceiptLine] = []
    total: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class ReceiptLineRead(BaseModel):
    id: str
    raw_text: str
    quantity: Decimal
    unit: str
    unit_price: Decimal | None
    total_price: Decimal | None
    line_kind: str
    status: str
    confidence: Decimal
    product_id: str | None
    product_name: str | None
    location_id: str | None
    best_before: date | None
    movement_id: str | None
    coordinates: dict[str, object] | None
    version: int


class ReceiptRead(BaseModel):
    id: str
    merchant: str | None
    purchased_at: datetime | None
    total: Decimal | None
    status: str
    progress: int
    processing_error: str | None
    analysis_provider: str | None
    duplicate_of_id: str | None
    duplicate_message: str | None = None
    sum_difference: Decimal | None = None
    image_count: int
    uploaded_by_name: str
    created_at: datetime
    confirmed_at: datetime | None
    reversed_at: datetime | None
    lines: list[ReceiptLineRead]


class ReceiptConfigRead(BaseModel):
    ocr_mode: str
    images_sent_to_cloud: bool
    cloud_processing: Literal["images", "text", "none"]
    image_retention_days: int


class ReceiptLineUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    product_id: str | None = None
    quantity: Quantity | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    location_id: str | None = None
    best_before: date | None = None
    ignored: bool | None = None


class ReceiptConfirmLine(BaseModel):
    line_id: str
    expected_version: int = Field(ge=1)
    product_id: str
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=20)
    location_id: str | None = None
    best_before: date | None = None
    idempotency_key: IdempotencyKey


class ReceiptConfirmRequest(BaseModel):
    lines: list[ReceiptConfirmLine] = Field(min_length=1)
    allow_duplicate: bool = False


class ReceiptReverseRequest(BaseModel):
    idempotency_key: IdempotencyKey
