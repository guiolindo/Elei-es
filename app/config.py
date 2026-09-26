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
    tse_cdn_base: str = "https://resultados.tse.jus.br/oficial/ele2026"
    tse_fotos_base: str = "https://divulgacandcontas.tse.jus.br/divulga/rest/v1/candidato/foto"
    eleicao_ano: int = 2026
    eleicao_cod_1t: int = 619
    eleicao_cod_2t: int = 620
    poll_interval_seconds: int = 20
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
