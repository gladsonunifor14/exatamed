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
    con.execute("CREATE TABLE dispensacoes (id INTEGER PRIMARY KEY, data DATETIME)")
    con.executemany("INSERT INTO dispensacoes (id, data) VALUES (?, ?)", [
        (1, "2025-12-30 10:00:00"), (2, "2026-01-02 09:00:00"), (3, "2025-12-31 08:00:00"),
        (4, "2026-01-05 11:00:00")])
    con.commit()
    con.close()
    app = create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{arquivo}"})
    with app.app_context():
        for tabela in ("movimentacoes", "dispensacoes"):
            colunas = {c["name"] for c in db.inspect(db.engine).get_columns(tabela)}
            assert "usuario_id" in colunas
        # Dispensações antigas recebem numeração por ano, em ordem cronológica.
        numeros = db.session.execute(db.text("SELECT id, numero, ano FROM dispensacoes ORDER BY id")).all()
        assert [tuple(n) for n in numeros] == [(1, 1, 2025), (2, 1, 2026), (3, 2, 2025), (4, 2, 2026)]
