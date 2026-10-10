"""ExataMed — gerenciamento de estoque de farmácia hospitalar."""

import os
from datetime import date, datetime, timedelta

import click
from flask import Flask, render_template
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from .models import Localizacao, Usuario, db

__version__ = "1.1.0"

CHAVE_PADRAO = "dev-troque-esta-chave"
LOCAIS_PRINCIPAIS = [
    ("Farmácia SUS", "Estoque destinado a pacientes do Sistema Único de Saúde"),
    ("Farmácia Particular", "Estoque destinado a pacientes particulares e de convênios"),
]

csrf = CSRFProtect()


def garantir_locais_principais():
    for nome, descricao in LOCAIS_PRINCIPAIS:
        if not Localizacao.query.filter_by(nome=nome).first():
            db.session.add(Localizacao(nome=nome, descricao=descricao, principal=True))
    db.session.commit()


# Colunas incluídas depois da primeira versão: (tabela, coluna, definição SQL).
COLUNAS_NOVAS = [
    ("movimentacoes", "usuario_id", "INTEGER REFERENCES usuarios(id)"),
    ("dispensacoes", "usuario_id", "INTEGER REFERENCES usuarios(id)"),
]


def atualizar_esquema():
    """Acrescenta em bancos já existentes as colunas criadas em versões novas.

    O `create_all` cria tabelas que faltam, mas não altera tabelas existentes.
    """
    inspetor = db.inspect(db.engine)
    tabelas = set(inspetor.get_table_names())
    for tabela, coluna, definicao in COLUNAS_NOVAS:
        if tabela in tabelas and coluna not in {c["name"] for c in inspetor.get_columns(tabela)}:
            with db.engine.begin() as conexao:
                conexao.execute(db.text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}"))


def url_banco(instance_path):
    """URL do banco a partir do ambiente, normalizada para o driver psycopg 3.

    Serviços como Render, Railway e Heroku fornecem `postgres://...`, que o
    SQLAlchemy não aceita.
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
    producao = os.environ.get("EXATAMED_ENV", "").lower() in ("production", "producao", "produção")
    app.config.update(
        PRODUCAO=producao,
        SECRET_KEY=os.environ.get("EXATAMED_SECRET_KEY", CHAVE_PADRAO),
        SQLALCHEMY_DATABASE_URI=url_banco(app.instance_path),
        # Reabre conexões que o PostgreSQL gerenciado encerrou por inatividade.
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=producao,
        REMEMBER_COOKIE_SECURE=producao,
        WTF_CSRF_TIME_LIMIT=None,
    )
    if config:
        app.config.update(config)
    if producao and app.config["SECRET_KEY"] == CHAVE_PADRAO:
        raise RuntimeError("Defina a variável EXATAMED_SECRET_KEY antes de publicar o sistema.")
    if producao:
        # Atrás do proxy HTTPS do serviço de hospedagem.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)

    from . import auth, cadastros, views
    auth.login_manager.init_app(app)
    app.before_request(auth.exigir_login)
    app.register_blueprint(auth.bp)
    app.register_blueprint(views.principal)
    app.register_blueprint(views.bp_estoque)
    app.register_blueprint(views.bp_relatorios)
    app.register_blueprint(cadastros.bp)

    @app.route("/saude")
    def saude():
        """Verificação de funcionamento usada pelo serviço de hospedagem."""
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok", "versao": __version__}

    @app.after_request
    def cabecalhos_seguranca(resposta):
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "DENY")
        resposta.headers.setdefault("Referrer-Policy", "same-origin")
        if producao:
            resposta.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resposta

    @app.errorhandler(403)
    def proibido(_erro):
        return render_template("erro.html", titulo="Acesso negado",
                               mensagem="Seu perfil não tem permissão para esta operação."), 403

    @app.errorhandler(404)
    def nao_encontrado(_erro):
        return render_template("erro.html", titulo="Página não encontrada",
                               mensagem="O endereço acessado não existe."), 404

    @app.errorhandler(CSRFError)
    def erro_csrf(_erro):
        return render_template("erro.html", titulo="Sessão expirada",
                               mensagem="O formulário expirou. Volte, recarregue a página e tente novamente."), 400

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
        return {"versao": __version__, "Usuario": Usuario}

    with app.app_context():
        db.create_all()
        atualizar_esquema()
        garantir_locais_principais()
        auth.criar_admin_inicial()
        if not Usuario.query.first() and not app.config.get("TESTING"):
            app.logger.warning(
                "Nenhum usuário cadastrado. Crie o administrador com 'flask --app exatamed criar-admin' "
                "ou defina EXATAMED_ADMIN_LOGIN e EXATAMED_ADMIN_SENHA.")
        if os.environ.get("EXATAMED_CARREGAR_DEMO") == "1":
            from .demo import popular
            popular()
        # Fecha as conexões antes de o gunicorn (--preload) criar os processos.
        if db.engine.dialect.name != "sqlite":
            db.engine.dispose()

    @app.cli.command("demo")
    def demo():
        """Popula o banco com dados e usuários de demonstração."""
        from .demo import criar_usuarios_demo, popular
        if popular():
            click.echo("Dados de demonstração criados.")
        else:
            click.echo("O banco já possui cadastros; dados de demonstração não foram criados.")
        criados = criar_usuarios_demo()
        if criados:
            click.echo("Usuários de demonstração (troque as senhas antes de usar dados reais):")
            for login, senha, perfil in criados:
                click.echo(f"  {login:<14} senha: {senha:<14} perfil: {perfil}")

    @app.cli.command("criar-admin")
    @click.option("--login", prompt="Login")
    @click.option("--nome", prompt="Nome completo")
    @click.password_option("--senha", prompt="Senha", confirmation_prompt="Confirme a senha")
    def criar_admin(login, nome, senha):
        """Cria um usuário administrador."""
        from .auth import validar_senha
        login = login.strip().lower()
        erro = validar_senha(senha, senha, login)
        if erro:
            raise click.ClickException(erro)
        if Usuario.query.filter(db.func.lower(Usuario.login) == login).first():
            raise click.ClickException("Já existe um usuário com este login.")
        admin = Usuario(nome=nome, login=login, perfil=Usuario.ADMIN)
        admin.definir_senha(senha)
        db.session.add(admin)
        db.session.commit()
        click.echo(f"Administrador '{login}' criado.")

    return app
