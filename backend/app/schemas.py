from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from .models import MovementType, Role

Quantity = Annotated[Decimal, Field(gt=0, decimal_places=3)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    household_name: str | None = Field(default=None, min_length=1, max_length=120)
    invitation_token: str | None = None

    @model_validator(mode="after")
    def require_household_or_invitation(self) -> "RegisterRequest":
        if not self.household_name and not self.invitation_token:
            raise ValueError("Haushaltsname oder Einladung ist erforderlich")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=128)


class InvitationCreate(BaseModel):
    email: EmailStr | None = None
    role: Role = Role.member


class InvitationRead(BaseModel):
    token: str
    invitation_url: str
    expires_at: datetime


class InvitationAccept(BaseModel):
    token: str


class InvitationAccepted(BaseModel):
    household_id: str
    role: Role


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


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    brand: str | None = None
    category: str | None = None
    default_unit: str | None = None
    image_url: str | None = None
    notes: str | None = None
    barcodes: list[str] | None = None


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


class BatchUpdate(BaseModel):
    location_id: str | None = None
    best_before: date | None = None
    opened_at: date | None = None
    unit: str | None = None
    expected_version: int = Field(ge=1)


class TransferRequest(BaseModel):
    batch_id: str
    target_location_id: str
    quantity: Quantity
    expected_version: int = Field(ge=1)
    idempotency_key: str
    note: str | None = None
    client_info: str | None = None


class MinStockRuleWrite(BaseModel):
    minimum_quantity: Quantity
    unit: str
    active: bool = True


class MinStockRuleRead(ORMModel):
    id: str
    product_id: str
    minimum_quantity: Decimal
    unit: str
    active: bool


class ShoppingListItem(BaseModel):
    product_id: str
    product_name: str
    current_quantity: Decimal
    minimum_quantity: Decimal
    missing_quantity: Decimal
    unit: str


class InventoryStartRequest(BaseModel):
    location_id: str | None = None


class InventorySessionRead(ORMModel):
    id: str
    location_id: str | None
    status: str
    created_at: datetime


class InventoryCountWrite(BaseModel):
    batch_id: str
    counted_quantity: Decimal = Field(ge=0, decimal_places=3)


class InventoryCountRead(ORMModel):
    batch_id: str
    expected_quantity: Decimal
    counted_quantity: Decimal


class InventoryConfirmRequest(BaseModel):
    idempotency_key: str


class InventoryDetail(BaseModel):
    session: InventorySessionRead
    counts: list[InventoryCountRead]


class NotificationRead(ORMModel):
    id: str
    kind: str
    message: str
    sent_channels: list[str]
    read_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime


class PushSubscriptionWrite(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


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
    note: str | None
    client_info: str | None
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
