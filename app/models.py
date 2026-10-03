from datetime import datetime
from sqlalchemy import (
    BigInteger, CHAR, DateTime, ForeignKey, Integer, Numeric, SmallInteger,
    String, Text, UniqueConstraint, Index, Boolean,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Cargo(Base):
    __tablename__ = "cargos"
    cod_cargo: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(64))
    abrangencia: Mapped[str] = mapped_column(String(16))  # 'federal'|'estadual'


class UF(Base):
    __tablename__ = "ufs"
    sigla: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    nome: Mapped[str] = mapped_column(String(64))
    cod_ibge: Mapped[int] = mapped_column(Integer)


class Partido(Base):
    __tablename__ = "partidos"
    numero: Mapped[int] = mapped_column(Integer, primary_key=True)
    sigla: Mapped[str] = mapped_column(String(32))
    nome: Mapped[str] = mapped_column(String(128))


class Candidato(Base):
    __tablename__ = "candidatos"
    sq_candidato: Mapped[str] = mapped_column(String(32), primary_key=True)
    nome: Mapped[str] = mapped_column(String(128))
    nome_urna: Mapped[str] = mapped_column(String(64))
    numero: Mapped[int] = mapped_column(Integer)
    cod_cargo: Mapped[int] = mapped_column(ForeignKey("cargos.cod_cargo"))
    uf: Mapped[str | None] = mapped_column(CHAR(2), ForeignKey("ufs.sigla"), nullable=True)
    partido_numero: Mapped[int] = mapped_column(ForeignKey("partidos.numero"))
    coligacao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    foto_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    foto_local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    vice_nome: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vice_partido: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_divulga: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Situação do candidato pela Justiça Eleitoral.
    #  'ativo'                  — concorre normalmente
    #  'renunciou'              — desistiu após convenção
    #  'cancelado'              — registro cancelado
    #  'indeferido_sem_recurso' — barrado, sem recurso pendente
    #  'cassado'                — cassado durante o pleito
    # Lei 9.504/97 art. 175 §3º: votos em candidato com registro cancelado
    # após convenção são considerados nulos. Motor exclui situacao != 'ativo'
    # do cálculo de 'eleito' e '2º turno'.
    situacao: Mapped[str] = mapped_column(String(32), nullable=False, server_default="ativo")


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        Index("ix_snap_cargo_abr_col", "cod_cargo", "abrangencia", "coletado_em"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coletado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gerado_em_tse: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    turno: Mapped[int] = mapped_column(SmallInteger)
    abrangencia: Mapped[str] = mapped_column(CHAR(2))  # 'BR' or UF
    cod_cargo: Mapped[int] = mapped_column(Integer)
    hash_conteudo: Mapped[str] = mapped_column(Text, unique=True)
    raw: Mapped[dict] = mapped_column(JSONB)
    suspeito: Mapped[bool] = mapped_column(Boolean, default=False)


class SnapshotTotais(Base):
    __tablename__ = "snapshot_totais"
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), primary_key=True)
    qt_secoes_total: Mapped[int] = mapped_column(Integer)
    qt_secoes_totalizadas: Mapped[int] = mapped_column(Integer)
    qt_eleitorado_apto: Mapped[int] = mapped_column(BigInteger)
    qt_eleitorado_apto_totalizadas: Mapped[int] = mapped_column(BigInteger)
    qt_comparecimento: Mapped[int] = mapped_column(BigInteger)
    qt_abstencoes: Mapped[int] = mapped_column(BigInteger)
    qt_votos_validos: Mapped[int] = mapped_column(BigInteger)
    qt_votos_brancos: Mapped[int] = mapped_column(BigInteger)
    qt_votos_nulos: Mapped[int] = mapped_column(BigInteger)


class SnapshotCandidato(Base):
    __tablename__ = "snapshot_candidato"
    __table_args__ = (
        Index("ix_snap_cand", "sq_candidato", "snapshot_id"),
    )
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), primary_key=True)
    sq_candidato: Mapped[str] = mapped_column(ForeignKey("candidatos.sq_candidato"), primary_key=True)
    votos: Mapped[int] = mapped_column(BigInteger)
    pct_validos: Mapped[float] = mapped_column(Numeric(6, 3))
    posicao: Mapped[int] = mapped_column(SmallInteger)


class SnapshotMunicipio(Base):
    """Votos de cada candidato em cada município, extraídos do snapshot
    da UF quando o TSE inclui breakdown por município no JSON."""
    __tablename__ = "snapshot_municipio"
    __table_args__ = (
        Index("ix_snap_mun_cargo_ibge", "cod_ibge", "sq_candidato"),
    )
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), primary_key=True)
    cod_ibge: Mapped[str] = mapped_column(String(7), primary_key=True)
    sq_candidato: Mapped[str] = mapped_column(ForeignKey("candidatos.sq_candidato"), primary_key=True)
    votos: Mapped[int] = mapped_column(BigInteger)
    pct_validos: Mapped[float] = mapped_column(Numeric(6, 3))
    posicao: Mapped[int] = mapped_column(SmallInteger)


class Evento(Base):
    __tablename__ = "eventos"
    __table_args__ = (
        Index("ix_ev_cargo_abr", "cod_cargo", "abrangencia", "ocorrido_em"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ocorrido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    tipo: Mapped[str] = mapped_column(String(64))
    cod_cargo: Mapped[int] = mapped_column(Integer)
    abrangencia: Mapped[str] = mapped_column(CHAR(2))
    sq_candidato_a: Mapped[str] = mapped_column(ForeignKey("candidatos.sq_candidato"))
    sq_candidato_b: Mapped[str | None] = mapped_column(ForeignKey("candidatos.sq_candidato"), nullable=True)
    detalhes: Mapped[dict] = mapped_column(JSONB, default=dict)


class Comparacao(Base):
    __tablename__ = "comparacoes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session_id: Mapped[str] = mapped_column(String(64))
    cod_cargo: Mapped[int] = mapped_column(Integer)
    abrangencia: Mapped[str] = mapped_column(CHAR(2))
    sq_candidato_a: Mapped[str] = mapped_column(String(32))
    sq_candidato_b: Mapped[str] = mapped_column(String(32))


class TelegramChatConfig(Base):
    """Config por chat: pausa global, janela de silêncio (horários que não
    envia — respeitando fuso BRT), idioma. Uma linha por chat."""
    __tablename__ = "telegram_chat_config"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pausado_global: Mapped[bool] = mapped_column(Boolean, default=False)
    silencio_inicio: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # hora BRT (0-23)
    silencio_fim: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TelegramSubscription(Base):
    """Assinatura de um chat do Telegram: quais cargos/abrangências e quais
    tipos de evento a pessoa quer receber. Uma linha por (chat_id, cargo,
    abrangencia). tipos_evento é lista de strings ('ELEITO_1T', 'VIRADA',
    'ELEITO_MAJORITARIO', 'SEGUNDO_TURNO_DEFINIDO', 'MATEMATICAMENTE_ELIMINADO').
    """
    __tablename__ = "telegram_subs"
    __table_args__ = (
        UniqueConstraint("chat_id", "cod_cargo", "abrangencia", name="uq_tg_sub"),
        Index("ix_tg_cargo_abr", "cod_cargo", "abrangencia"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    cod_cargo: Mapped[int] = mapped_column(Integer)
    abrangencia: Mapped[str] = mapped_column(CHAR(2))
    tipos_evento: Mapped[list] = mapped_column(JSONB, default=list)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
