from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalizar_database_url(url: str) -> str:
    """Railway (e outras PaaS) entrega DATABASE_URL como `postgres://` ou
    `postgresql://` — o SQLAlchemy async precisa do dialeto `+asyncpg`.
    Também tolera `postgresql+psycopg` caso alguém copie de outro lugar.
    """
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://apuracao:apuracao@localhost:5432/apuracao"
    port: int = 8000
    # Endpoints oficiais do TSE.
    # - resultados.tse.jus.br NÃO tem Akamai — Railway acessa direto (IP SP).
    # - divulgacandcontas.tse.jus.br tem Akamai — coleta via Termux
    #   (scripts/importar_termux.py) alimenta o banco via /api/admin/*.
    # Não usar Cloudflare Worker: Free tier 100k req/dia é apertado
    # e Akamai bloqueia workers Cloudflare mesmo.
    tse_cdn_base: str = "https://resultados.tse.jus.br/oficial/ele2026"
    tse_fotos_base: str = "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img"
    eleicao_ano: int = 2026
    # Códigos de eleição no TSE 2026 — DOIS códigos separados:
    #  - PRESIDENCIAL (cargo 1): 6257 (1T), presume 6258 (2T)
    #  - ESTADUAL (cargos 3, 5, 6, 7): 6259 (1T), presume 6260 (2T)
    # Confirmado em 30/09/2026 testando os endpoints do S3 diretamente.
    # 2T ainda não foi publicado — próximos códigos naturais na sequência.
    # descoberta.py ajusta automaticamente se o TSE usar outro número.
    eleicao_cod_1t: int = 6257           # Presidente 1T
    eleicao_cod_2t: int = 6258           # Presidente 2T
    eleicao_cod_1t_estadual: int = 6259  # Governador/Senador/Deputados 1T
    eleicao_cod_2t_estadual: int = 6260  # Governador 2T
    # Código da eleição no divulgacandcontas (usado para candidatos e fotos)
    eleicao_cod_divulga: int = 20322002026
    poll_interval_seconds: int = 20
    # Quais turnos o poller coleta. Opções: "all" (default), "1", "2".
    # Entre 1T e 2T não há ganho em polar 1T (já 100% apurado), então
    # define POLL_TURNO=2 nas env vars reduz ~70% dos requests (137
    # alvos 1T removidos) + bate menos no S3/CloudFront do TSE.
    # Volta pra "all" se precisar reconsultar algo específico.
    poll_turno: str = "all"
    # Intervalo do cleanup de snapshots (segundos). No dia D vale baixar
    # pra 900 (15 min) pra não acumular; dias normais 3600 (1h) basta.
    cleanup_interval_seconds: int = 3600
    # Retenção máxima de snapshots por chave (cargo × abrangência × turno).
    # 200 × ~1min = ~3h de curva fina — suficiente pro gráfico do dia D.
    snapshots_retention_per_key: int = 200
    # Base do endpoint de listagem de candidatos (divulga do TSE).
    # Formato: {base}/{ano}/{uf}/{cod_eleicao}/{cargo}/candidatos
    tse_divulga_base: str = "https://divulgacandcontas.tse.jus.br/divulga/rest/v1/candidatura/listar"
    # Proxy para acessar TSE (o TSE bloqueia IPs fora do Brasil via Akamai).
    # Formato: http://usuario:senha@host:porta ou http://host:porta.
    # Se vazio, tenta acessar direto (funciona só se o app estiver hospedado no BR).
    tse_proxy: str = ""
    # Lista de proxies para rotação automática, separados por vírgula:
    #   http://ip1:porta1,http://ip2:porta2,...
    # O código testa cada um contra o TSE e cacheia o que funciona.
    # Preferir este em vez de tse_proxy porque tolera proxies caindo.
    tse_proxy_list: str = ""
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_claim_email: str = "admin@example.com"
    session_secret: str = "change-me"
    cors_origins: str = "http://localhost:8080"
    # Token exigido nos endpoints /api/admin/*. Se vazio, admin fica aberto
    # (útil só em dev). Em produção sempre setar via env var.
    admin_token: str = ""
    # Bot do Telegram — se preenchido, sobe long-polling e envia alertas.
    # Deixe vazio pra desligar. Username sem @ (ex.: "avisoeleicao_bot").
    telegram_bot_token: str = ""
    telegram_bot_username: str = "avisoeleicao_bot"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Normaliza a DATABASE_URL depois do carregamento para lidar com o
    # formato que o Railway injeta automaticamente.
    object.__setattr__(s, "database_url", _normalizar_database_url(s.database_url))
    return s
