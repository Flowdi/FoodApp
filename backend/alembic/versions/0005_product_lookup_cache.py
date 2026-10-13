"""Add household-scoped product lookup cache.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

from backend.app import models  # noqa: F401
from backend.app.database import Base

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["product_lookup_cache"].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["product_lookup_cache"].drop(bind=op.get_bind(), checkfirst=True)
