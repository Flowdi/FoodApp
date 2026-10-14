"""Add receipt capture and review workflow.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "receipts" not in tables:
        _create_receipts()
    if "receipt_lines" not in tables:
        _create_receipt_lines()


def _create_receipts() -> None:
    op.create_table(
        "receipts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by_id", sa.String(length=36), nullable=False),
        sa.Column("merchant", sa.String(length=180), nullable=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="processing"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("image_hash", sa.String(length=64), nullable=False),
        sa.Column("image_paths", sa.JSON(), nullable=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("analysis_provider", sa.String(length=40), nullable=True),
        sa.Column("duplicate_of_id", sa.String(length=36), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["receipts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("household_id", "purchased_at", "status", "fingerprint", "created_at"):
        op.create_index(f"ix_receipts_{column}", "receipts", [column])


def _create_receipt_lines() -> None:
    op.create_table(
        "receipt_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("receipt_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False, server_default="1"),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default="piece"),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("line_kind", sa.String(length=30), nullable=False, server_default="food"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="unknown"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("product_id", sa.String(length=36), nullable=True),
        sa.Column("location_id", sa.String(length=36), nullable=True),
        sa.Column("best_before", sa.Date(), nullable=True),
        sa.Column("movement_id", sa.String(length=36), nullable=True),
        sa.Column("coordinates", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["storage_locations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["movement_id"], ["stock_movements.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movement_id"),
    )
    for column in ("household_id", "receipt_id", "status", "product_id"):
        op.create_index(f"ix_receipt_lines_{column}", "receipt_lines", [column])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "receipt_lines" in tables:
        op.drop_table("receipt_lines")
    if "receipts" in tables:
        op.drop_table("receipts")
