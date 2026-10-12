"""Add password reset and household invitation flows.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

from backend.app import models  # noqa: F401
from backend.app.database import Base

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in ("password_reset_tokens", "household_invitations"):
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in ("household_invitations", "password_reset_tokens"):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
