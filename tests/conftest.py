import os

import pytest
from flask import g

from exatamed import create_app
from exatamed.models import Usuario, db

SENHA = "senha1234"
# Por padrão, SQLite em memória. No CI os testes rodam também no PostgreSQL:
# EXATAMED_TESTE_BANCO=postgresql+psycopg://usuario@host/banco_de_testes
BANCO_TESTES = os.environ.get("EXATAMED_TESTE_BANCO") or "sqlite:///:memory:"


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": BANCO_TESTES, "WTF_CSRF_ENABLED": False})

    # Os testes mantêm um contexto da aplicação aberto, e o Flask-Login guarda o usuário em `g`
    # (do contexto da aplicação). Sem limpar a cada requisição, um cliente de teste herdaria o
    # usuário logado de outro. Em produção cada requisição tem o próprio contexto.
    def limpar_usuario_em_cache():
        g.pop("_login_user", None)
    app.before_request_funcs.setdefault(None, []).insert(0, limpar_usuario_em_cache)
    with app.app_context():
        yield app
        db.session.remove()
        db.drop_all()


def criar_usuario(login, perfil, **extra):
    usuario = Usuario(nome=login.title(), login=login, perfil=perfil, **extra)
    usuario.definir_senha(SENHA)
    db.session.add(usuario)
    db.session.commit()
    return usuario


def entrar(client, login, senha=SENHA):
    return client.post("/login", data={"login": login, "senha": senha})


@pytest.fixture
def anonimo(app):
    """Cliente sem login."""
    return app.test_client()


@pytest.fixture
def client(app):
    """Cliente autenticado como administrador."""
    criar_usuario("admin", Usuario.ADMIN)
    cliente = app.test_client()
    entrar(cliente, "admin")
    return cliente


@pytest.fixture
def auxiliar(app):
    criar_usuario("aux", Usuario.AUXILIAR)
    cliente = app.test_client()
    entrar(cliente, "aux")
    return cliente


@pytest.fixture
def farmaceutico(app):
    criar_usuario("farma", Usuario.FARMACEUTICO)
    cliente = app.test_client()
    entrar(cliente, "farma")
    return cliente
