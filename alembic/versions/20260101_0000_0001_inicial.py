"""Schema inicial

Revision ID: 0001
Revises:
Create Date: 2026-01-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cargos",
        sa.Column("cod_cargo", sa.Integer, primary_key=True),
        sa.Column("nome", sa.String(64), nullable=False),
        sa.Column("abrangencia", sa.String(16), nullable=False),
    )
    op.create_table(
        "ufs",
        sa.Column("sigla", sa.CHAR(2), primary_key=True),
        sa.Column("nome", sa.String(64), nullable=False),
        sa.Column("cod_ibge", sa.Integer, nullable=False),
    )
    op.create_table(
        "partidos",
        sa.Column("numero", sa.Integer, primary_key=True),
        sa.Column("sigla", sa.String(32), nullable=False),
        sa.Column("nome", sa.String(128), nullable=False),
    )
    op.create_table(
        "candidatos",
        sa.Column("sq_candidato", sa.String(32), primary_key=True),
        sa.Column("nome", sa.String(128), nullable=False),
        sa.Column("nome_urna", sa.String(64), nullable=False),
        sa.Column("numero", sa.Integer, nullable=False),
        sa.Column("cod_cargo", sa.Integer, sa.ForeignKey("cargos.cod_cargo"), nullable=False),
        sa.Column("uf", sa.CHAR(2), sa.ForeignKey("ufs.sigla"), nullable=True),
        sa.Column("partido_numero", sa.Integer, sa.ForeignKey("partidos.numero"), nullable=False),
        sa.Column("coligacao", sa.String(255)),
        sa.Column("foto_url", sa.Text),
        sa.Column("foto_local_path", sa.Text),
        sa.Column("vice_nome", sa.String(128)),
        sa.Column("vice_partido", sa.String(32)),
    )
    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("coletado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gerado_em_tse", sa.DateTime(timezone=True)),
        sa.Column("turno", sa.SmallInteger, nullable=False),
        sa.Column("abrangencia", sa.CHAR(2), nullable=False),
        sa.Column("cod_cargo", sa.Integer, nullable=False),
        sa.Column("hash_conteudo", sa.Text, nullable=False, unique=True),
        sa.Column("raw", JSONB, nullable=False),
        sa.Column("suspeito", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_snap_cargo_abr_col", "snapshots", ["cod_cargo", "abrangencia", "coletado_em"])
    op.create_table(
        "snapshot_totais",
        sa.Column("snapshot_id", sa.Integer, sa.ForeignKey("snapshots.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("qt_secoes_total", sa.Integer, nullable=False),
        sa.Column("qt_secoes_totalizadas", sa.Integer, nullable=False),
        sa.Column("qt_eleitorado_apto", sa.BigInteger, nullable=False),
        sa.Column("qt_eleitorado_apto_totalizadas", sa.BigInteger, nullable=False),
        sa.Column("qt_comparecimento", sa.BigInteger, nullable=False),
        sa.Column("qt_abstencoes", sa.BigInteger, nullable=False),
        sa.Column("qt_votos_validos", sa.BigInteger, nullable=False),
        sa.Column("qt_votos_brancos", sa.BigInteger, nullable=False),
        sa.Column("qt_votos_nulos", sa.BigInteger, nullable=False),
    )
    op.create_table(
        "snapshot_candidato",
        sa.Column("snapshot_id", sa.Integer, sa.ForeignKey("snapshots.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("sq_candidato", sa.String(32), sa.ForeignKey("candidatos.sq_candidato"), primary_key=True),
        sa.Column("votos", sa.BigInteger, nullable=False),
        sa.Column("pct_validos", sa.Numeric(6, 3), nullable=False),
        sa.Column("posicao", sa.SmallInteger, nullable=False),
    )
    op.create_index("ix_snap_cand", "snapshot_candidato", ["sq_candidato", "snapshot_id"])
    op.create_table(
        "eventos",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ocorrido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_id", sa.Integer, sa.ForeignKey("snapshots.id"), nullable=False),
        sa.Column("tipo", sa.String(64), nullable=False),
        sa.Column("cod_cargo", sa.Integer, nullable=False),
        sa.Column("abrangencia", sa.CHAR(2), nullable=False),
        sa.Column("sq_candidato_a", sa.String(32), sa.ForeignKey("candidatos.sq_candidato"), nullable=False),
        sa.Column("sq_candidato_b", sa.String(32), sa.ForeignKey("candidatos.sq_candidato")),
        sa.Column("detalhes", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_ev_cargo_abr", "eventos", ["cod_cargo", "abrangencia", "ocorrido_em"])
    op.create_table(
        "comparacoes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("cod_cargo", sa.Integer, nullable=False),
        sa.Column("abrangencia", sa.CHAR(2), nullable=False),
        sa.Column("sq_candidato_a", sa.String(32), nullable=False),
        sa.Column("sq_candidato_b", sa.String(32), nullable=False),
    )
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("endpoint", sa.Text, nullable=False, unique=True),
        sa.Column("p256dh", sa.Text, nullable=False),
        sa.Column("auth", sa.Text, nullable=False),
    )


def downgrade() -> None:
    for t in [
        "push_subscriptions", "comparacoes", "eventos",
        "snapshot_candidato", "snapshot_totais", "snapshots",
        "candidatos", "partidos", "ufs", "cargos",
    ]:
        op.drop_table(t)
