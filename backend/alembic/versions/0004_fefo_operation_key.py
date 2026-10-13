"""Add operation key for multi-batch FEFO bookings.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("stock_movements")}
    if "operation_key" not in columns:
        op.add_column("stock_movements", sa.Column("operation_key", sa.String(36), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("stock_movements")}
    if "ix_stock_movements_operation_key" not in indexes:
        op.create_index(
            "ix_stock_movements_operation_key",
            "stock_movements",
            ["operation_key"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("stock_movements")}
    if "ix_stock_movements_operation_key" in indexes:
        op.drop_index("ix_stock_movements_operation_key", table_name="stock_movements")
    columns = {column["name"] for column in inspector.get_columns("stock_movements")}
    if "operation_key" in columns:
        op.drop_column("stock_movements", "operation_key")
