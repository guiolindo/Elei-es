"""Popula tabelas de referência (cargos, UFs, partidos) e alguns candidatos
sintéticos de 2022 para desenvolver sem esperar o dia da eleição."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Cargo, UF, Partido, Candidato


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
    (13, "PT", "Partido dos Trabalhadores"),
    (22, "PL", "Partido Liberal"),
    (12, "PDT", "Partido Democrático Trabalhista"),
    (45, "PSDB", "Partido da Social Democracia Brasileira"),
    (10, "REP", "Republicanos"),
    (25, "UNIÃO", "União Brasil"),
    (44, "NOVO", "Novo"),
    (50, "PSOL", "Partido Socialismo e Liberdade"),
]

def _construir_candidatos():
    """Gera dataset de exemplo para desenvolvimento: candidatos presidenciais
    nacionais + 3 candidatos a governador, 2 a senador, 2 a deputado federal
    e 2 a deputado estadual em cada uma das 27 UFs.
    """
    cands = [
        # Presidente (nacional)
        ("PR2026_01", "Fulano da Silva",   "FULANO",   13, 1, None, 13),
        ("PR2026_02", "Ciclano de Souza",  "CICLANO",  22, 1, None, 22),
        ("PR2026_03", "Beltrano Rocha",    "BELTRANO", 12, 1, None, 12),
        ("PR2026_04", "Sicrano Almeida",   "SICRANO",  45, 1, None, 45),
    ]
    # Nomes-base para variar por UF sem duplicar
    base_gov = [("Ana", 13, 13), ("Bruno", 22, 22), ("Carla", 45, 45)]
    base_sen = [("Helena", 130, 13), ("Igor", 220, 22)]
    base_dfe = [("João", 1300, 13), ("Kátia", 2200, 22)]
    base_dea = [("Nuno", 13001, 13), ("Olga", 22002, 22)]

    for uf in [s for s, _n, _i in UFS]:
        for i, (nome, num, part) in enumerate(base_gov, start=1):
            cands.append((f"GO2026_{uf}_{i:02d}", f"{nome} de {uf}", nome.upper(), num, 3, uf, part))
        for i, (nome, num, part) in enumerate(base_sen, start=1):
            cands.append((f"SE2026_{uf}_{i:02d}", f"{nome} de {uf}", nome.upper(), num, 5, uf, part))
        for i, (nome, num, part) in enumerate(base_dfe, start=1):
            cands.append((f"DF2026_{uf}_{i:02d}", f"{nome} de {uf}", nome.upper(), num, 6, uf, part))
        for i, (nome, num, part) in enumerate(base_dea, start=1):
            cands.append((f"DE2026_{uf}_{i:02d}", f"{nome} de {uf}", nome.upper(), num, 7, uf, part))
    return cands


CANDIDATOS = _construir_candidatos()


async def main() -> None:
    async with SessionLocal() as sess:
        # cargos
        for cod, nome, abr in CARGOS:
            if not (await sess.execute(select(Cargo).where(Cargo.cod_cargo == cod))).scalar_one_or_none():
                sess.add(Cargo(cod_cargo=cod, nome=nome, abrangencia=abr))
        # ufs
        for sig, nome, ibge in UFS:
            if not (await sess.execute(select(UF).where(UF.sigla == sig))).scalar_one_or_none():
                sess.add(UF(sigla=sig, nome=nome, cod_ibge=ibge))
        # partidos
        for num, sig, nome in PARTIDOS:
            if not (await sess.execute(select(Partido).where(Partido.numero == num))).scalar_one_or_none():
                sess.add(Partido(numero=num, sigla=sig, nome=nome))
        # candidatos — só insere fictícios se não houver NENHUM candidato ainda.
        # Depois que os reais do TSE entrarem, o seed nunca mais reinsere.
        r = await sess.execute(select(Candidato).limit(1))
        if r.scalar_one_or_none() is not None:
            print("já existem candidatos — pulando seed de fictícios")
        else:
            for sq, nome, urna, numero, cargo, uf, partido in CANDIDATOS:
                sess.add(Candidato(
                    sq_candidato=sq, nome=nome, nome_urna=urna, numero=numero,
                    cod_cargo=cargo, uf=uf, partido_numero=partido,
                ))
        await sess.commit()
    print("seed concluído")


if __name__ == "__main__":
    asyncio.run(main())
