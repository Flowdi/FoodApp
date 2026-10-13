"""Add per-membership notification preferences.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("memberships")}
    if "notification_channels" not in columns:
        op.add_column(
            "memberships",
            sa.Column(
                "notification_channels",
                sa.JSON(),
                nullable=False,
                server_default='["in_app", "email", "push"]',
            ),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("memberships")}
    if "notification_channels" in columns:
        op.drop_column("memberships", "notification_channels")
