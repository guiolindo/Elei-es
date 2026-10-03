"""adicionar coluna situacao em candidatos

Lei 9.504/97 art. 175 §3º: votos em candidato com registro cancelado após
convenção são considerados nulos. O motor exclui situacao != 'ativo' do
cálculo de 'eleito' e '2º turno'.

Revision ID: 0006_candidato_situacao
Revises: 0005_tune_autovacuum
Create Date: 2026-10-03 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_candidato_situacao"
down_revision = "0005_tune_autovacuum"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidatos",
        sa.Column(
            "situacao",
            sa.String(length=32),
            nullable=False,
            server_default="ativo",
        ),
    )
    op.create_index(
        "ix_candidatos_situacao_cargo",
        "candidatos",
        ["cod_cargo", "situacao"],
    )


def downgrade() -> None:
    op.drop_index("ix_candidatos_situacao_cargo", table_name="candidatos")
    op.drop_column("candidatos", "situacao")
