"""tabela visitas (analytics minimalista, IP hash SHA-256)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-12 13:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visitas",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ocorreu_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("path", sa.String(length=256), nullable=False),
        sa.Column("ip_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("referrer", sa.String(length=256), nullable=True),
        sa.Column("ua_familia", sa.String(length=32), nullable=True),
        sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vis_ocorreu_em", "visitas", ["ocorreu_em"])
    op.create_index("ix_vis_path_ocorreu", "visitas", ["path", "ocorreu_em"])


def downgrade() -> None:
    op.drop_index("ix_vis_path_ocorreu", table_name="visitas")
    op.drop_index("ix_vis_ocorreu_em", table_name="visitas")
    op.drop_table("visitas")
