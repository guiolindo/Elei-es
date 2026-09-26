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

CANDIDATOS = [
    # sq, nome, urna, numero, cargo, uf, partido
    ("PR2026_01", "Fulano da Silva", "FULANO", 13, 1, None, 13),
    ("PR2026_02", "Ciclano de Souza", "CICLANO", 22, 1, None, 22),
    ("PR2026_03", "Beltrano Rocha", "BELTRANO", 12, 1, None, 12),
    ("PR2026_04", "Sicrano Almeida", "SICRANO", 45, 1, None, 45),
    ("GO2026_SP_01", "Ana Paulista", "ANA", 13, 3, "SP", 13),
    ("GO2026_SP_02", "Bruno Bandeira", "BRUNO", 22, 3, "SP", 22),
    ("GO2026_SP_03", "Carla Ipiranga", "CARLA", 10, 3, "SP", 10),
]


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
        # candidatos
        for sq, nome, urna, numero, cargo, uf, partido in CANDIDATOS:
            if not (await sess.execute(select(Candidato).where(Candidato.sq_candidato == sq))).scalar_one_or_none():
                sess.add(Candidato(
                    sq_candidato=sq, nome=nome, nome_urna=urna, numero=numero,
                    cod_cargo=cargo, uf=uf, partido_numero=partido,
                ))
        await sess.commit()
    print("seed concluído")


if __name__ == "__main__":
    asyncio.run(main())
