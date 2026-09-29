"""Afina autovacuum das tabelas quentes pro dia D

Snapshots, snapshot_candidato, snapshot_municipio e eventos recebem
milhares de INSERTs por hora durante a apuração. Autovacuum default
do PG (20% dead rows) demora demais em tabelas que crescem rápido —
os índices ficam bloated e os SELECTs (feed do frontend) degradam.

Baixa o threshold pra 5% dessas tabelas específicas — o autovacuum
roda com mais frequência mas mantém as tabelas enxutas.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


# Tabelas quentes com config de autovacuum agressiva
_TABELAS_QUENTES = {
    "snapshots":            5,
    "snapshot_candidato":   5,
    "snapshot_municipio":   5,
    "snapshot_totais":      5,
    "eventos":              10,
}


def upgrade() -> None:
    for tabela, pct in _TABELAS_QUENTES.items():
        # scale_factor em fração (5% → 0.05); threshold mínimo 1000 rows
        # antes de considerar o vacuum
        op.execute(
            f"ALTER TABLE {tabela} SET ("
            f"  autovacuum_vacuum_scale_factor = {pct / 100.0}, "
            f"  autovacuum_vacuum_threshold = 1000, "
            f"  autovacuum_analyze_scale_factor = {pct / 100.0}, "
            f"  autovacuum_analyze_threshold = 1000"
            f")"
        )


def downgrade() -> None:
    for tabela in _TABELAS_QUENTES:
        op.execute(
            f"ALTER TABLE {tabela} RESET ("
            f"  autovacuum_vacuum_scale_factor, "
            f"  autovacuum_vacuum_threshold, "
            f"  autovacuum_analyze_scale_factor, "
            f"  autovacuum_analyze_threshold"
            f")"
        )
