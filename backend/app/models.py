import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


class Role(enum.StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class MovementType(enum.StrEnum):
    purchase = "purchase"
    consume = "consume"
    discard = "discard"
    adjust = "adjust"
    transfer = "transfer"
    reversal = "reversal"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Household(Base):
    __tablename__ = "households"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Berlin")
    expiry_warning_days: Mapped[int] = mapped_column(default=3)
    notification_settings: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "household_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.member)


class StorageLocation(Base):
    __tablename__ = "storage_locations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))


class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(180), index=True)
    brand: Mapped[str | None] = mapped_column(String(180))
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    default_unit: Mapped[str] = mapped_column(String(20), default="piece")
    image_url: Mapped[str | None] = mapped_column(String(1000))
    notes: Mapped[str | None] = mapped_column(Text)
    barcodes: Mapped[list["ProductBarcode"]] = relationship(cascade="all, delete-orphan")


class ProductBarcode(Base):
    __tablename__ = "product_barcodes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    barcode: Mapped[str] = mapped_column(String(32), unique=True, index=True)


class StockBatch(Base):
    __tablename__ = "stock_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    location_id: Mapped[str] = mapped_column(
        ForeignKey("storage_locations.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    unit: Mapped[str] = mapped_column(String(20))
    best_before: Mapped[date | None] = mapped_column(Date)
    opened_at: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    product: Mapped[Product] = relationship()
    location: Mapped[StorageLocation] = relationship()


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (UniqueConstraint("household_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("stock_batches.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    movement_type: Mapped[MovementType] = mapped_column(Enum(MovementType))
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    note: Mapped[str | None] = mapped_column(Text)
    client_info: Mapped[str | None] = mapped_column(String(255))
    reverses_movement_id: Mapped[str | None] = mapped_column(
        ForeignKey("stock_movements.id"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class MinStockRule(Base):
    __tablename__ = "min_stock_rules"
    __table_args__ = (UniqueConstraint("household_id", "product_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    minimum_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(60))
    changes: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventorySession(Base):
    __tablename__ = "inventory_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[str | None] = mapped_column(ForeignKey("storage_locations.id"))
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryCount(Base):
    __tablename__ = "inventory_counts"
    __table_args__ = (UniqueConstraint("session_id", "batch_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    session_id: Mapped[str] = mapped_column(ForeignKey("inventory_sessions.id", ondelete="CASCADE"))
    batch_id: Mapped[str] = mapped_column(ForeignKey("stock_batches.id"))
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    counted_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True)
    message: Mapped[str] = mapped_column(Text)
    sent_channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)


class Recipe(Base):
    __tablename__ = "recipes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(180))
    servings: Mapped[int] = mapped_column(default=2)
    instructions: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(20))
