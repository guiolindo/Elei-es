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

PARTIDOS = [
    (10, "REP",    "Republicanos"),
    (11, "PP",     "Progressistas"),
    (12, "PDT",    "Partido Democrático Trabalhista"),
    (13, "PT",     "Partido dos Trabalhadores"),
    (14, "PTB",    "Partido Trabalhista Brasileiro"),
    (15, "MDB",    "Movimento Democrático Brasileiro"),
    (16, "PSTU",   "Partido Socialista dos Trabalhadores Unificado"),
    (17, "PSL",    "Partido Social Liberal"),
    (18, "REDE",   "Rede Sustentabilidade"),
    (19, "PODE",   "Podemos"),
    (20, "PSC",    "Partido Social Cristão"),
    (21, "PCB",    "Partido Comunista Brasileiro"),
    (22, "PL",     "Partido Liberal"),
    (23, "CIDADANIA", "Cidadania"),
    (25, "UNIÃO",  "União Brasil"),
    (27, "DC",     "Democracia Cristã"),
    (28, "AGIR",   "Agir"),
    (29, "PCO",    "Partido da Causa Operária"),
    (30, "NOVO",   "Novo"),
    (33, "PMN",    "Partido da Mobilização Nacional"),
    (35, "PMB",    "Partido da Mulher Brasileira"),
    (36, "PTC",    "Partido Trabalhista Cristão"),
    (40, "PSB",    "Partido Socialista Brasileiro"),
    (43, "PV",     "Partido Verde"),
    (44, "NOVO",   "Novo"),
    (45, "PSDB",   "Partido da Social Democracia Brasileira"),
    (50, "PSOL",   "Partido Socialismo e Liberdade"),
    (51, "PATRIOTA", "Patriota"),
    (54, "PRTB",   "Partido Renovador Trabalhista Brasileiro"),
    (55, "PSD",    "Partido Social Democrático"),
    (65, "PC do B", "Partido Comunista do Brasil"),
    (70, "AVANTE", "Avante"),
    (77, "SOLIDARIEDADE", "Solidariedade"),
    (80, "UP",     "Unidade Popular"),
    (90, "PROS",   "Partido Republicano da Ordem Social"),
]


async def main() -> None:
    async with SessionLocal() as sess:
        for cod, nome, abr in CARGOS:
            if not (await sess.execute(select(Cargo).where(Cargo.cod_cargo == cod))).scalar_one_or_none():
                sess.add(Cargo(cod_cargo=cod, nome=nome, abrangencia=abr))
        for sig, nome, ibge in UFS:
            if not (await sess.execute(select(UF).where(UF.sigla == sig))).scalar_one_or_none():
                sess.add(UF(sigla=sig, nome=nome, cod_ibge=ibge))
        for num, sig, nome in PARTIDOS:
            if not (await sess.execute(select(Partido).where(Partido.numero == num))).scalar_one_or_none():
                sess.add(Partido(numero=num, sigla=sig, nome=nome))
        await sess.commit()
    print("seed de referência concluído (cargos, UFs, partidos)")


if __name__ == "__main__":
    asyncio.run(main())
