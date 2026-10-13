"""Add persistent shopping list workflow.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    household_columns = {column["name"] for column in inspector.get_columns("households")}
    if "shopping_check_mode" not in household_columns:
        op.add_column(
            "households",
            sa.Column(
                "shopping_check_mode",
                sa.String(length=20),
                nullable=False,
                server_default="instant",
            ),
        )
    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "default_location_id" not in product_columns:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("products") as batch_op:
                batch_op.add_column(sa.Column("default_location_id", sa.String(length=36)))
                batch_op.create_foreign_key(
                    "fk_products_default_location_id",
                    "storage_locations",
                    ["default_location_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        else:
            op.add_column(
                "products",
                sa.Column(
                    "default_location_id",
                    sa.String(length=36),
                    sa.ForeignKey("storage_locations.id", ondelete="SET NULL"),
                ),
            )
    if "shopping_list_items" in inspector.get_table_names():
        return
    op.create_table(
        "shopping_list_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36)),
        sa.Column("free_text", sa.String(length=240)),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("created_by_id", sa.String(length=36)),
        sa.Column("checked_by_id", sa.String(length=36)),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("linked_movement_id", sa.String(length=36)),
        sa.Column("recipe_id", sa.String(length=36)),
        sa.Column("create_key", sa.String(length=36)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["checked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["linked_movement_id"], ["stock_movements.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("household_id", "create_key"),
    )
    op.create_index("ix_shopping_list_items_household_id", "shopping_list_items", ["household_id"])
    op.create_index("ix_shopping_list_items_product_id", "shopping_list_items", ["product_id"])
    op.create_index("ix_shopping_list_items_status", "shopping_list_items", ["status"])
    op.create_index("ix_shopping_list_items_recipe_id", "shopping_list_items", ["recipe_id"])
    op.execute(
        "INSERT INTO shopping_list_items "
        "(id, household_id, product_id, quantity, unit, source, status, recipe_id, version) "
        "SELECT id, household_id, product_id, quantity, unit, 'recipe', 'open', recipe_id, 1 "
        "FROM shopping_list_entries"
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "shopping_list_items" in inspector.get_table_names():
        op.drop_table("shopping_list_items")
    if "default_location_id" in {column["name"] for column in inspector.get_columns("products")}:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("products") as batch_op:
                batch_op.drop_column("default_location_id")
        else:
            op.drop_column("products", "default_location_id")
    if "shopping_check_mode" in {column["name"] for column in inspector.get_columns("households")}:
        op.drop_column("households", "shopping_check_mode")
