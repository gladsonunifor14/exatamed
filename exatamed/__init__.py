"""ExataMed — gerenciamento de estoque de farmácia hospitalar."""

import os
from datetime import date, datetime

import click
from flask import Flask

from .models import Localizacao, db

__version__ = "1.0.0"

LOCAIS_PRINCIPAIS = [
    ("Farmácia SUS", "Estoque destinado a pacientes do Sistema Único de Saúde"),
    ("Farmácia Particular", "Estoque destinado a pacientes particulares e de convênios"),
]


def garantir_locais_principais():
    for nome, descricao in LOCAIS_PRINCIPAIS:
        if not Localizacao.query.filter_by(nome=nome).first():
            db.session.add(Localizacao(nome=nome, descricao=descricao, principal=True))
    db.session.commit()


def url_banco(instance_path):
    """URL do banco a partir do ambiente, normalizada para o driver psycopg 3.

    Render, Railway e Heroku fornecem a URL no formato `postgres://...`, que o
    SQLAlchemy não aceita. Sem variável definida, usa SQLite na pasta `instance/`.
    """
    url = os.environ.get("EXATAMED_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        return f"sqlite:///{os.path.join(instance_path, 'exatamed.db')}"
    for prefixo in ("postgres://", "postgresql://"):
        if url.startswith(prefixo):
            return "postgresql+psycopg://" + url[len(prefixo):]
    return url


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.environ.get("EXATAMED_SECRET_KEY", "dev-troque-esta-chave"),
        SQLALCHEMY_DATABASE_URI=url_banco(app.instance_path),
        # Reabre conexões que o PostgreSQL gerenciado encerrou por inatividade.
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    )
    if config:
        app.config.update(config)

    db.init_app(app)

    from . import cadastros, views
    app.register_blueprint(views.principal)
    app.register_blueprint(views.bp_estoque)
    app.register_blueprint(views.bp_relatorios)
    app.register_blueprint(cadastros.bp)

    @app.route("/saude")
    def saude():
        """Verificação de funcionamento usada pelo serviço de hospedagem."""
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok", "versao": __version__}

    @app.template_filter("moeda")
    def moeda(valor):
        valor = valor or 0
        return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @app.template_filter("numero")
    def numero(valor, casas=2):
        if valor is None or valor == "":
            return ""
        if isinstance(valor, str):
            return valor
        texto = f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if "," in texto:
            texto = texto.rstrip("0").rstrip(",")
        return texto

    @app.template_filter("data")
    def data(valor, formato="%d/%m/%Y"):
        if isinstance(valor, (date, datetime)):
            return valor.strftime(formato)
        return valor or ""

    @app.context_processor
    def globais():
        return {"versao": __version__}

    with app.app_context():
        db.create_all()
        garantir_locais_principais()
        # Fecha as conexões antes de o gunicorn (--preload) criar os processos.
        if db.engine.dialect.name != "sqlite":
            db.engine.dispose()

    @app.cli.command("demo")
    def demo():
        """Popula o banco com dados de demonstração."""
        from .demo import popular
        if popular():
            click.echo("Dados de demonstração criados.")
        else:
            click.echo("O banco já possui cadastros; dados de demonstração não foram criados.")

    return app
