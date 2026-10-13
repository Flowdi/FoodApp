"""Add recipe shopping-list entries.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "shopping_list_entries" not in inspector.get_table_names():
        op.create_table(
            "shopping_list_entries",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("household_id", sa.String(length=36), nullable=False),
            sa.Column("product_id", sa.String(length=36), nullable=False),
            sa.Column("recipe_id", sa.String(length=36), nullable=True),
            sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
            sa.Column("unit", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("household_id", "product_id", "recipe_id"),
        )
        op.create_index(
            "ix_shopping_list_entries_household_id", "shopping_list_entries", ["household_id"]
        )
        op.create_index(
            "ix_shopping_list_entries_product_id", "shopping_list_entries", ["product_id"]
        )
        op.create_index(
            "ix_shopping_list_entries_recipe_id", "shopping_list_entries", ["recipe_id"]
        )


def downgrade() -> None:
    if "shopping_list_entries" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("shopping_list_entries")
