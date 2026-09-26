from app.config import _normalizar_database_url


def test_normalizar_postgres_curto():
    assert _normalizar_database_url("postgres://u:p@h:5432/db") \
        == "postgresql+asyncpg://u:p@h:5432/db"


def test_normalizar_postgresql_padrao():
    assert _normalizar_database_url("postgresql://u:p@h:5432/db") \
        == "postgresql+asyncpg://u:p@h:5432/db"


def test_normalizar_ja_asyncpg_intacto():
    url = "postgresql+asyncpg://u:p@h:5432/db"
    assert _normalizar_database_url(url) == url


def test_normalizar_vazio():
    assert _normalizar_database_url("") == ""
