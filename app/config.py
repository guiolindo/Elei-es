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
    # Aponta para o Cloudflare Worker (que roda em SP e passa pelo Akamai
    # do TSE como IP BR). Ver cloudflare-worker/ para o código do worker.
    # No dia da eleição, se preferir, mova para variável de ambiente.
    tse_cdn_base: str = "https://apuracao-2026.gui342386.workers.dev/oficial/ele2026"
    tse_fotos_base: str = "https://apuracao-2026.gui342386.workers.dev/fotos"
    eleicao_ano: int = 2026
    eleicao_cod_1t: int = 619
    eleicao_cod_2t: int = 620
    poll_interval_seconds: int = 20
    # Base do endpoint de listagem de candidatos (divulga do TSE).
    # Formato: {base}/{ano}/{uf}/{cod_eleicao}/{cargo}/candidatos
    tse_divulga_base: str = "https://apuracao-2026.gui342386.workers.dev/divulga/rest/v1/candidatura/listar"
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


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Normaliza a DATABASE_URL depois do carregamento para lidar com o
    # formato que o Railway injeta automaticamente.
    object.__setattr__(s, "database_url", _normalizar_database_url(s.database_url))
    return s
