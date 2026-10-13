"""Add voice preferences, product aliases and AI usage logs.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    membership_columns = {column["name"] for column in inspector.get_columns("memberships")}
    if "voice_preferences" not in membership_columns:
        op.add_column(
            "memberships",
            sa.Column(
                "voice_preferences",
                sa.JSON(),
                nullable=False,
                server_default=sa.text(
                    '\'{"auto_confirm_shopping": false, "speech_output": false}\''
                ),
            ),
        )
    tables = set(inspector.get_table_names())
    if "product_aliases" not in tables:
        _create_product_aliases()
    if "ai_usage_logs" not in tables:
        _create_ai_usage_logs()
    if "voice_executions" not in tables:
        _create_voice_executions()


def _create_product_aliases() -> None:
    op.create_table(
        "product_aliases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("alias", sa.String(length=180), nullable=False),
        sa.Column("normalized_alias", sa.String(length=180), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "normalized_alias"),
    )
    op.create_index("ix_product_aliases_household_id", "product_aliases", ["household_id"])
    op.create_index("ix_product_aliases_product_id", "product_aliases", ["product_id"])
    op.create_index("ix_product_aliases_normalized_alias", "product_aliases", ["normalized_alias"])


def _create_ai_usage_logs() -> None:
    op.create_table(
        "ai_usage_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("feature", sa.String(length=40), nullable=False),
        sa.Column("input_units", sa.Integer(), nullable=True),
        sa.Column("output_units", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_usage_logs_household_id", "ai_usage_logs", ["household_id"])
    op.create_index("ix_ai_usage_logs_feature", "ai_usage_logs", ["feature"])
    op.create_index("ix_ai_usage_logs_created_at", "ai_usage_logs", ["created_at"])


def _create_voice_executions() -> None:
    op.create_table(
        "voice_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "idempotency_key"),
    )
    op.create_index("ix_voice_executions_household_id", "voice_executions", ["household_id"])


def downgrade() -> None:
    op.drop_table("voice_executions")
    op.drop_table("ai_usage_logs")
    op.drop_table("product_aliases")
    op.drop_column("memberships", "voice_preferences")
