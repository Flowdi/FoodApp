"""Add per-member recipe preferences.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("memberships")}
    if "recipe_preferences" not in columns:
        op.add_column(
            "memberships",
            sa.Column(
                "recipe_preferences",
                sa.JSON(),
                nullable=False,
                server_default='{"preferred_tags": [], "excluded_tags": []}',
            ),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("memberships")}
    if "recipe_preferences" in columns:
        op.drop_column("memberships", "recipe_preferences")
