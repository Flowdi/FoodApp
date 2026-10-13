"""Add inventory confirmation idempotency key.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("inventory_sessions")
    }
    if "confirmation_key" not in columns:
        op.add_column("inventory_sessions", sa.Column("confirmation_key", sa.String(length=36)))


def downgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("inventory_sessions")
    }
    if "confirmation_key" in columns:
        op.drop_column("inventory_sessions", "confirmation_key")
