import pytest

from exatamed import create_app
from exatamed.models import Usuario, db

SENHA = "senha1234"


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False})
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
