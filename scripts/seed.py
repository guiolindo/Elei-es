"""Popula tabelas de referência (cargos, UFs, partidos).

Candidatos vêm do TSE via scripts/importar_termux.py — este arquivo
não gera mais candidatos fictícios.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Cargo, UF, Partido


CARGOS = [
    (1, "Presidente", "federal"),
    (3, "Governador", "estadual"),
    (5, "Senador", "estadual"),
    (6, "Deputado Federal", "estadual"),
    (7, "Deputado Estadual", "estadual"),
]

UFS = [
    ("AC", "Acre", 12), ("AL", "Alagoas", 27), ("AP", "Amapá", 16),
    ("AM", "Amazonas", 13), ("BA", "Bahia", 29), ("CE", "Ceará", 23),
    ("DF", "Distrito Federal", 53), ("ES", "Espírito Santo", 32),
    ("GO", "Goiás", 52), ("MA", "Maranhão", 21), ("MT", "Mato Grosso", 51),
    ("MS", "Mato Grosso do Sul", 50), ("MG", "Minas Gerais", 31),
    ("PA", "Pará", 15), ("PB", "Paraíba", 25), ("PR", "Paraná", 41),
    ("PE", "Pernambuco", 26), ("PI", "Piauí", 22),
    ("RJ", "Rio de Janeiro", 33), ("RN", "Rio Grande do Norte", 24),
    ("RS", "Rio Grande do Sul", 43), ("RO", "Rondônia", 11),
    ("RR", "Roraima", 14), ("SC", "Santa Catarina", 42),
    ("SP", "São Paulo", 35), ("SE", "Sergipe", 28), ("TO", "Tocantins", 17),
]

# Partidos registrados no TSE para 2026. Sincronizado com static/partidos.js
# em 03/10/2026 — mudanças desde 2022:
#   14 PTB → MISSÃO (fundido em nov/2025)
#   20 PSC → PODE (fusão em 2024)
#   25 UNIÃO → PRD (União migrou pra 44)
#   33 PMN → MOBILIZA
#   35 PMB → O DEMOCRATA
#   44 (novo) UNIÃO BRASIL
#   Extintos: 17 PSL, 19, 51 PATRIOTA, 90 PROS (mantidos pra dados históricos)
PARTIDOS = [
    (10, "REPUBLICANOS", "Republicanos"),
    (11, "PP",     "Progressistas"),
    (12, "PDT",    "Partido Democrático Trabalhista"),
    (13, "PT",     "Partido dos Trabalhadores"),
    (14, "MISSÃO", "Missão"),
    (15, "MDB",    "Movimento Democrático Brasileiro"),
    (16, "PSTU",   "Partido Socialista dos Trabalhadores Unificado"),
    (18, "REDE",   "Rede Sustentabilidade"),
    (20, "PODE",   "Podemos"),
    (21, "PCB",    "Partido Comunista Brasileiro"),
    (22, "PL",     "Partido Liberal"),
    (23, "CIDADANIA", "Cidadania"),
    (25, "PRD",    "Partido Renovação Democrática"),
    (27, "DC",     "Democracia Cristã"),
    (28, "PRTB",   "Partido Renovador Trabalhista Brasileiro"),
    (29, "PCO",    "Partido da Causa Operária"),
    (30, "NOVO",   "Novo"),
    (33, "MOBILIZA", "Mobiliza"),
    (35, "O DEMOCRATA", "O Democrata"),
    (36, "AGIR",   "Agir"),
    (40, "PSB",    "Partido Socialista Brasileiro"),
    (43, "PV",     "Partido Verde"),
    (44, "UNIÃO",  "União Brasil"),
    (45, "PSDB",   "Partido da Social Democracia Brasileira"),
    (50, "PSOL",   "Partido Socialismo e Liberdade"),
    (55, "PSD",    "Partido Social Democrático"),
    (65, "PCdoB",  "Partido Comunista do Brasil"),
    (70, "AVANTE", "Avante"),
    (77, "SOLIDARIEDADE", "Solidariedade"),
    (80, "UP",     "Unidade Popular"),
    # Extintos — mantidos pra dados históricos
    (17, "PSL",      "Partido Social Liberal"),
    (51, "PATRIOTA", "Patriota"),
    (90, "PROS",     "Partido Republicano da Ordem Social"),
]


async def main() -> None:
    async with SessionLocal() as sess:
        for cod, nome, abr in CARGOS:
            if not (await sess.execute(select(Cargo).where(Cargo.cod_cargo == cod))).scalar_one_or_none():
                sess.add(Cargo(cod_cargo=cod, nome=nome, abrangencia=abr))
        for sig, nome, ibge in UFS:
            if not (await sess.execute(select(UF).where(UF.sigla == sig))).scalar_one_or_none():
                sess.add(UF(sigla=sig, nome=nome, cod_ibge=ibge))
        # Partidos: UPSERT para atualizar sigla/nome quando o TSE renumera
        # (ex.: 25 era União Brasil em 2022, virou PRD em 2026).
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        for num, sig, nome in PARTIDOS:
            stmt = pg_insert(Partido).values(numero=num, sigla=sig, nome=nome)
            stmt = stmt.on_conflict_do_update(
                index_elements=["numero"],
                set_={"sigla": sig, "nome": nome},
            )
            await sess.execute(stmt)
        await sess.commit()
    print("seed de referência concluído (cargos, UFs, partidos)")


if __name__ == "__main__":
    asyncio.run(main())
