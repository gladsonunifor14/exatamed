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


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.environ.get("EXATAMED_SECRET_KEY", "dev-troque-esta-chave"),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "EXATAMED_DATABASE_URL", f"sqlite:///{os.path.join(app.instance_path, 'exatamed.db')}"
        ),
    )
    if config:
        app.config.update(config)

    db.init_app(app)

    from . import cadastros, views
    app.register_blueprint(views.principal)
    app.register_blueprint(views.bp_estoque)
    app.register_blueprint(views.bp_relatorios)
    app.register_blueprint(cadastros.bp)

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

    @app.cli.command("demo")
    def demo():
        """Popula o banco com dados de demonstração."""
        from .demo import popular
        popular()
        click.echo("Dados de demonstração criados.")

    return app
