from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://apuracao:apuracao@localhost:5432/apuracao"
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
    return Settings()
