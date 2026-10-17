"""Repair missing membership preference columns.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PREFERENCE_COLUMNS = (
    (
        "notification_channels",
        sa.JSON(),
        sa.text('\'["in_app", "email", "push"]\''),
    ),
    (
        "recipe_preferences",
        sa.JSON(),
        sa.text('\'{"preferred_tags": [], "excluded_tags": []}\''),
    ),
    (
        "voice_preferences",
        sa.JSON(),
        sa.text(
            '\'{"auto_confirm_shopping": false, "speech_output": false, '
            '"start_listening_on_launch": null}\''
        ),
    ),
)


def upgrade() -> None:
    """Bring databases with incomplete historic migrations back to the model schema."""
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("memberships")}
    for name, column_type, default in PREFERENCE_COLUMNS:
        if name not in columns:
            op.add_column(
                "memberships",
                sa.Column(name, column_type, nullable=False, server_default=default),
            )


def downgrade() -> None:
    # This is intentionally non-destructive: the migration repairs columns that may have
    # originated in older revisions, so removing them would lose valid user preferences.
    pass
