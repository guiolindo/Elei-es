"""Snapshots por município

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "snapshot_municipio",
        sa.Column("snapshot_id", sa.Integer,
                  sa.ForeignKey("snapshots.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("cod_ibge", sa.String(7), primary_key=True),
        sa.Column("sq_candidato", sa.String(32),
                  sa.ForeignKey("candidatos.sq_candidato"),
                  primary_key=True),
        sa.Column("votos", sa.BigInteger, nullable=False),
        sa.Column("pct_validos", sa.Numeric(6, 3), nullable=False),
        sa.Column("posicao", sa.SmallInteger, nullable=False),
    )
    op.create_index(
        "ix_snap_mun_cargo_ibge",
        "snapshot_municipio",
        ["cod_ibge", "sq_candidato"],
    )


def downgrade() -> None:
    op.drop_index("ix_snap_mun_cargo_ibge", table_name="snapshot_municipio")
    op.drop_table("snapshot_municipio")
