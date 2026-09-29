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
    # Código da eleição no divulgacandcontas (candidatos, fotos) — visto na URL
    # do site do TSE em 28/09/2026
    eleicao_cod_1t: int = 21270
    eleicao_cod_2t: int = 21271  # 2º turno costuma ser cod+1
    # Código da eleição no divulgacandcontas (usado para candidatos e fotos)
    eleicao_cod_divulga: int = 20322002026
    poll_interval_seconds: int = 20
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
