"""Add product package quantity.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("products")}
    if "package_quantity" not in columns:
        op.add_column("products", sa.Column("package_quantity", sa.String(length=80)))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("products")}
    if "package_quantity" in columns:
        op.drop_column("products", "package_quantity")
