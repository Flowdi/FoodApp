"""Add notification resolution state.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("notifications")}
    if "resolved_at" not in columns:
        op.add_column("notifications", sa.Column("resolved_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("notifications")}
    if "resolved_at" in columns:
        op.drop_column("notifications", "resolved_at")
