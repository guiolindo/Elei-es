"""Adicionar raw_divulga em candidatos

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("candidatos", sa.Column("raw_divulga", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("candidatos", "raw_divulga")
