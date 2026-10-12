from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import MovementType, Role

Quantity = Annotated[Decimal, Field(gt=0, decimal_places=3)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    household_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserRead(ORMModel):
    id: str
    email: EmailStr
    display_name: str


class MembershipRead(ORMModel):
    household_id: str
    role: Role


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    brand: str | None = None
    category: str | None = None
    default_unit: str = "piece"
    image_url: str | None = None
    notes: str | None = None
    barcodes: list[str] = []


class ProductRead(ORMModel):
    id: str
    household_id: str
    name: str
    brand: str | None
    category: str | None
    default_unit: str
    image_url: str | None
    barcodes: list["BarcodeRead"]


class BarcodeRead(ORMModel):
    barcode: str


class BatchRead(ORMModel):
    id: str
    product_id: str
    location_id: str
    quantity: Decimal
    unit: str
    best_before: date | None
    version: int
    product: ProductRead


class PurchaseRequest(BaseModel):
    product_id: str
    location_id: str
    quantity: Quantity
    unit: str
    best_before: date | None = None
    idempotency_key: str
    client_info: str | None = None


class ChangeStockRequest(BaseModel):
    quantity: Quantity
    expected_version: int = Field(ge=1)
    idempotency_key: str
    note: str | None = None
    client_info: str | None = None


class ReversalRequest(BaseModel):
    idempotency_key: str
    expected_version: int = Field(ge=1)


class MovementRead(ORMModel):
    id: str
    household_id: str
    batch_id: str
    user_id: str
    movement_type: MovementType
    quantity_delta: Decimal
    idempotency_key: str
    reverses_movement_id: str | None
    created_at: datetime


class MovementResult(BaseModel):
    movement: MovementRead
    batch: BatchRead
    replayed: bool = False


class LocationRead(ORMModel):
    id: str
    name: str


class LookupResult(BaseModel):
    barcode: str
    name: str | None = None
    brand: str | None = None
    quantity: str | None = None
    image_url: str | None = None
    found: bool


class ErrorDetail(BaseModel):
    code: str
    message: str
    current: BatchRead | None = None
