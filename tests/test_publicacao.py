import pytest

from exatamed import url_banco


@pytest.mark.parametrize("entrada, esperado", [
    ("postgres://u:s@host:5432/db", "postgresql+psycopg://u:s@host:5432/db"),
    ("postgresql://u:s@host/db", "postgresql+psycopg://u:s@host/db"),
    ("postgresql+psycopg://u:s@host/db", "postgresql+psycopg://u:s@host/db"),
    ("sqlite:////tmp/x.db", "sqlite:////tmp/x.db"),
])
def test_url_do_banco_normalizada(monkeypatch, entrada, esperado):
    monkeypatch.setenv("EXATAMED_DATABASE_URL", entrada)
    assert url_banco("/inst") == esperado


def test_url_padrao_sqlite_e_fallback_database_url(monkeypatch):
    monkeypatch.delenv("EXATAMED_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert url_banco("/inst") == "sqlite:////inst/exatamed.db"
    monkeypatch.setenv("DATABASE_URL", "postgres://u@h/db")
    assert url_banco("/inst") == "postgresql+psycopg://u@h/db"


def test_verificacao_de_saude(client):
    assert client.get("/saude").get_json()["status"] == "ok"
