import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, model_validator

from .models import MovementType, Role

Quantity = Annotated[Decimal, Field(gt=0, decimal_places=3)]
PackageQuantity = Annotated[int, Field(gt=0)]
RecipeTag = Annotated[str, Field(min_length=1, max_length=50)]


def canonical_uuid(value: str) -> str:
    return str(uuid.UUID(value))


IdempotencyKey = Annotated[str, AfterValidator(canonical_uuid)]


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


class HouseholdRead(ORMModel):
    id: str
    name: str
    timezone: str
    expiry_warning_days: int
    shopping_check_mode: str


class HouseholdUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    expiry_warning_days: int | None = Field(default=None, ge=0, le=365)
    shopping_check_mode: str | None = Field(default=None, pattern="^(instant|finish_trip)$")


class MemberRead(BaseModel):
    user_id: str
    email: EmailStr
    display_name: str
    role: Role


class MemberRoleUpdate(BaseModel):
    role: Role


class NotificationPreferences(BaseModel):
    channels: list[str]


class RecipePreferences(BaseModel):
    preferred_tags: list[RecipeTag] = Field(default=[], max_length=20)
    excluded_tags: list[RecipeTag] = Field(default=[], max_length=20)


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
    default_unit: str = "package"
    default_location_id: str | None = None
    image_url: str | None = None
    package_quantity: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    barcodes: list[str] = []


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    brand: str | None = None
    category: str | None = None
    default_unit: str | None = None
    default_location_id: str | None = None
    image_url: str | None = None
    package_quantity: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    barcodes: list[str] | None = None


class ProductRead(ORMModel):
    id: str
    household_id: str
    name: str
    brand: str | None
    category: str | None
    default_unit: str
    default_location_id: str | None
    image_url: str | None
    package_quantity: str | None
    notes: str | None
    barcodes: list["BarcodeRead"]


class BarcodeRead(ORMModel):
    barcode: str


class BatchRead(ORMModel):
    id: str
    product_id: str
    location_id: str
    quantity: int
    unit: str
    best_before: date | None
    opened_at: date | None
    version: int
    product: ProductRead


class PurchaseRequest(BaseModel):
    product_id: str
    location_id: str
    quantity: PackageQuantity = 1
    unit: str = "package"
    best_before: date | None = None
    idempotency_key: IdempotencyKey
    client_info: str | None = None


class ChangeStockRequest(BaseModel):
    quantity: PackageQuantity
    expected_version: int = Field(ge=1)
    idempotency_key: IdempotencyKey
    note: str | None = None
    client_info: str | None = None


class FefoConsumeRequest(BaseModel):
    product_id: str
    quantity: PackageQuantity
    unit: str = "package"
    expected_versions: dict[str, int]
    idempotency_key: IdempotencyKey
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
    quantity: PackageQuantity
    expected_version: int = Field(ge=1)
    idempotency_key: IdempotencyKey
    note: str | None = None
    client_info: str | None = None


class MinStockRuleWrite(BaseModel):
    minimum_quantity: PackageQuantity
    unit: str = "package"
    active: bool = True


class MinStockRuleRead(ORMModel):
    id: str
    product_id: str
    minimum_quantity: int
    unit: str
    active: bool


class ShoppingItemCreate(BaseModel):
    product_id: str | None = None
    free_text: str | None = Field(default=None, min_length=1, max_length=240)
    quantity: PackageQuantity
    unit: str = "package"
    note: str | None = None
    source: str = Field(default="manual", pattern="^(manual|voice|receipt|recipe)$")
    idempotency_key: IdempotencyKey

    @model_validator(mode="after")
    def require_product_or_text(self) -> "ShoppingItemCreate":
        if not self.product_id and not self.free_text:
            raise ValueError("Produkt oder Freitext ist erforderlich")
        return self


class ShoppingItemRead(ORMModel):
    id: str
    product_id: str | None
    product_name: str
    category: str | None
    free_text: str | None
    quantity: int
    unit: str
    note: str | None
    source: str
    status: str
    checked_by_name: str | None
    checked_at: datetime | None
    linked_movement_id: str | None
    version: int
    created_at: datetime


class ShoppingCheckRequest(BaseModel):
    expected_version: int = Field(ge=1)
    idempotency_key: IdempotencyKey
    product_id: str | None = None
    location_id: str | None = None
    best_before: date | None = None
    book_to_stock: bool = True
    client_info: str | None = None


class ShoppingUndoRequest(BaseModel):
    expected_version: int = Field(ge=1)
    expected_batch_version: int | None = Field(default=None, ge=1)
    idempotency_key: IdempotencyKey


class ShoppingTripLine(BaseModel):
    item_id: str
    expected_version: int = Field(ge=1)
    location_id: str | None = None
    best_before: date | None = None
    idempotency_key: IdempotencyKey


class ShoppingFinishRequest(BaseModel):
    lines: list[ShoppingTripLine] = Field(min_length=1)


class ShoppingRemoveRequest(BaseModel):
    expected_version: int = Field(ge=1)


class RecipeIngredientWrite(BaseModel):
    product_id: str
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=20)


class RecipeIngredientRead(ORMModel):
    id: str
    product_id: str
    quantity: Decimal
    unit: str
    product_name: str


class RecipeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    servings: int = Field(default=2, ge=1, le=100)
    instructions: str | None = None
    tags: list[str] = []
    ingredients: list[RecipeIngredientWrite] = Field(min_length=1)


class RecipeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    servings: int | None = Field(default=None, ge=1, le=100)
    instructions: str | None = None
    tags: list[str] | None = None
    ingredients: list[RecipeIngredientWrite] | None = Field(default=None, min_length=1)


class RecipeRead(ORMModel):
    id: str
    name: str
    servings: int
    instructions: str | None
    tags: list[str]
    ingredients: list[RecipeIngredientRead]


class MissingIngredient(BaseModel):
    product_id: str
    product_name: str
    required_quantity: Decimal
    available_quantity: Decimal
    missing_quantity: Decimal
    unit: str


class RecipeRecommendation(BaseModel):
    recipe: RecipeRead
    score: float
    availability_score: float
    expiry_score: float
    preference_score: float
    missing_ingredients: list[MissingIngredient]
    explanation: str
    ranking_source: str = "deterministic"


class InventoryStartRequest(BaseModel):
    location_id: str | None = None


class InventorySessionRead(ORMModel):
    id: str
    location_id: str | None
    status: str
    created_at: datetime


class InventoryCountWrite(BaseModel):
    batch_id: str
    counted_quantity: int = Field(ge=0)


class InventoryCountRead(ORMModel):
    batch_id: str
    expected_quantity: int
    expected_version: int
    counted_quantity: int


class InventoryConfirmRequest(BaseModel):
    idempotency_key: IdempotencyKey


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
    idempotency_key: IdempotencyKey
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
    product_id: str | None = None
    product_name: str | None = None
    user_name: str | None = None


class MovementResult(BaseModel):
    movement: MovementRead
    batch: BatchRead
    replayed: bool = False


class ShoppingCheckResult(BaseModel):
    item: ShoppingItemRead
    movement: MovementResult | None = None


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
