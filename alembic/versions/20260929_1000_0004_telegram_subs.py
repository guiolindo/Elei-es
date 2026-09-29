"""Assinaturas do bot do Telegram

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_subs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("cod_cargo", sa.Integer(), nullable=False),
        sa.Column("abrangencia", sa.CHAR(2), nullable=False),
        sa.Column("tipos_evento", JSONB, nullable=False, server_default="[]"),
        sa.UniqueConstraint("chat_id", "cod_cargo", "abrangencia", name="uq_tg_sub"),
    )
    op.create_index("ix_tg_cargo_abr", "telegram_subs", ["cod_cargo", "abrangencia"])
    op.create_table(
        "telegram_chat_config",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("pausado_global", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("silencio_inicio", sa.SmallInteger(), nullable=True),
        sa.Column("silencio_fim", sa.SmallInteger(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("telegram_chat_config")
    op.drop_index("ix_tg_cargo_abr", "telegram_subs")
    op.drop_table("telegram_subs")
