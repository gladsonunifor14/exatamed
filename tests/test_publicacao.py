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


def test_banco_da_versao_anterior_ganha_colunas_de_auditoria(tmp_path):
    import sqlite3

    from exatamed import create_app
    from exatamed.models import db

    arquivo = tmp_path / "antigo.db"
    con = sqlite3.connect(arquivo)
    con.execute("CREATE TABLE movimentacoes (id INTEGER PRIMARY KEY, tipo VARCHAR(20))")
    con.execute("CREATE TABLE dispensacoes (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    app = create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{arquivo}"})
    with app.app_context():
        for tabela in ("movimentacoes", "dispensacoes"):
            colunas = {c["name"] for c in db.inspect(db.engine).get_columns(tabela)}
            assert "usuario_id" in colunas
