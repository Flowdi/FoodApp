"""Add inventory count batch versions.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("inventory_counts")
    }
    if "expected_version" not in columns:
        op.add_column(
            "inventory_counts",
            sa.Column("expected_version", sa.Integer(), nullable=False, server_default="1"),
        )
        op.execute(
            "UPDATE inventory_counts SET expected_version = COALESCE("
            "(SELECT version FROM stock_batches "
            "WHERE stock_batches.id = inventory_counts.batch_id), 1)"
        )


def downgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("inventory_counts")
    }
    if "expected_version" in columns:
        op.drop_column("inventory_counts", "expected_version")
