"""Correção retroativa do RJ Gov 1T após fix do parser (sub judice).

Em 04/10/2026 ~00:01 BRT o engine emitiu ELEITO_MAJORITARIO pro líder do
RJ Gov (190002542887, Douglas Ruas) com `maioria_absoluta=True` baseado
num denominador qt_votos_validos subestimado em 274.411 votos — os
votos do Garotinho (REP 10, sq=190002550196), que estava "Indeferido em
prazo recursal". A Lei 9.504 art. 16-A manda contar como válidos
enquanto roda o recurso, e o TSE declarou 2º turno confirmando. Nosso
parser foi corrigido pra usar max(TSE.vv, sum(cand.vap)), mas eventos já
emitidos no banco precisam ser corrigidos à mão.

Rodar via Railway shell:  python -m scripts.corrigir_rj_gov_sub_judice

Idempotente: se já corrigido (SEGUNDO_TURNO_DEFINIDO presente, ELEITO
removido), sai sem fazer nada.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import and_, select, delete

from app.db import SessionLocal
from app.models import Evento, Snapshot

CARGO = 3  # Governador
UF = "RJ"
# Finalistas do 2T confirmados pelo TSE: Douglas Ruas (PL, 22) × Eduardo Paes (PSD, 15)
SQ_DOUGLAS = "190002542887"
SQ_EDUARDO = "190002543380"


async def main() -> None:
    async with SessionLocal() as sess:
        # Último snapshot do RJ Gov 1T pra anexar os eventos reemitidos
        snap_stmt = select(Snapshot).where(
            and_(Snapshot.cod_cargo == CARGO, Snapshot.abrangencia == UF, Snapshot.turno == 1)
        ).order_by(Snapshot.coletado_em.desc()).limit(1)
        snap = (await sess.execute(snap_stmt)).scalar_one_or_none()
        if snap is None:
            print("[skip] nenhum snapshot RJ Gov 1T encontrado")
            return

        # Idempotência: já tem SEGUNDO_TURNO_DEFINIDO com a dupla certa?
        existe_2t = (await sess.execute(select(Evento).where(and_(
            Evento.cod_cargo == CARGO, Evento.abrangencia == UF,
            Evento.tipo == "SEGUNDO_TURNO_DEFINIDO",
        )))).scalars().all()
        tem_eleito = (await sess.execute(select(Evento).where(and_(
            Evento.cod_cargo == CARGO, Evento.abrangencia == UF,
            Evento.tipo == "ELEITO_MAJORITARIO",
        )))).scalars().all()

        if existe_2t and not tem_eleito:
            print("[skip] RJ Gov já corrigido (SEGUNDO_TURNO_DEFINIDO presente, sem ELEITO)")
            return

        # 1) Deleta ELEITO_MAJORITARIO (falso-positivo)
        n_del_eleito = (await sess.execute(delete(Evento).where(and_(
            Evento.cod_cargo == CARGO, Evento.abrangencia == UF,
            Evento.tipo == "ELEITO_MAJORITARIO",
        )))).rowcount

        # 2) Deleta MATEMATICAMENTE_ELIMINADO em cima do 2º colocado — foi
        # emitido junto com o ELEITO falso, premissa inválida.
        n_del_elim = (await sess.execute(delete(Evento).where(and_(
            Evento.cod_cargo == CARGO, Evento.abrangencia == UF,
            Evento.tipo == "MATEMATICAMENTE_ELIMINADO",
            Evento.sq_candidato_a == SQ_DOUGLAS,
        )))).rowcount
        n_del_elim += (await sess.execute(delete(Evento).where(and_(
            Evento.cod_cargo == CARGO, Evento.abrangencia == UF,
            Evento.tipo == "MATEMATICAMENTE_ELIMINADO",
            Evento.sq_candidato_a == SQ_EDUARDO,
        )))).rowcount

        # 3) Emite SEGUNDO_TURNO_DEFINIDO com a dupla correta (se não existir)
        novo = None
        if not existe_2t:
            novo = Evento(
                cod_cargo=CARGO, abrangencia=UF,
                tipo="SEGUNDO_TURNO_DEFINIDO",
                sq_candidato_a=SQ_DOUGLAS,
                sq_candidato_b=SQ_EDUARDO,
                snapshot_id=snap.id,
                ocorrido_em=datetime.now(timezone.utc),
                detalhes={"corrigido_manualmente": True,
                          "motivo": "sub judice (Garotinho) incluído no denominador por Lei 9.504 art. 16-A"},
            )
            sess.add(novo)

        await sess.commit()
        print(f"[ok] RJ Gov corrigido:")
        print(f"     ELEITO_MAJORITARIO removidos: {n_del_eleito}")
        print(f"     MATEMATICAMENTE_ELIMINADO removidos: {n_del_elim}")
        print(f"     SEGUNDO_TURNO_DEFINIDO adicionado: {bool(novo)}")


if __name__ == "__main__":
    asyncio.run(main())
