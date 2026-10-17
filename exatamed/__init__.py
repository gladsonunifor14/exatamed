"""ExataMed — gerenciamento de estoque de farmácia hospitalar."""

import logging
import os
import time
from datetime import date, datetime, timedelta

import click
from flask import Flask, g, render_template, request
from flask_login import current_user
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from .models import Localizacao, Usuario, db

__version__ = "2.4.0"

CHAVE_PADRAO = "dev-troque-esta-chave"
LOCAIS_PRINCIPAIS = [
    ("Farmácia SUS", "Estoque destinado a pacientes do Sistema Único de Saúde"),
    ("Farmácia Particular", "Estoque destinado a pacientes particulares e de convênios"),
]

csrf = CSRFProtect()

# Política de segurança de conteúdo: só scripts, estilos e fontes do próprio sistema.
# A única conexão externa é a consulta de CEP (ViaCEP), feita pelo navegador.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self' https://viacep.com.br; form-action 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")


def garantir_locais_principais():
    for nome, descricao in LOCAIS_PRINCIPAIS:
        if not Localizacao.query.filter_by(nome=nome).first():
            db.session.add(Localizacao(nome=nome, descricao=descricao, principal=True))
    db.session.commit()


# Colunas incluídas depois da primeira versão: (tabela, coluna, definição SQL).
COLUNAS_NOVAS = [
    ("movimentacoes", "usuario_id", "INTEGER REFERENCES usuarios(id)"),
    ("dispensacoes", "usuario_id", "INTEGER REFERENCES usuarios(id)"),
    ("usuarios", "ocultar_primeiros_passos", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("dispensacoes", "numero", "INTEGER"),
    ("dispensacoes", "ano", "INTEGER"),
    ("pacientes", "anonimizado_em", "TIMESTAMP"),
    ("medicos", "anonimizado_em", "TIMESTAMP"),
    ("usuarios", "anonimizado_em", "TIMESTAMP"),
    ("movimentacoes", "seq_cadeia", "INTEGER"),
    ("movimentacoes", "hash", "VARCHAR(64)"),
    ("registros_acesso", "seq_cadeia", "INTEGER"),
    ("registros_acesso", "hash", "VARCHAR(64)"),
    ("movimentacoes", "origem_id", "INTEGER REFERENCES movimentacoes(id)"),
    ("lotes", "bloqueado", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("lotes", "motivo_bloqueio", "VARCHAR(200)"),
    ("lotes", "bloqueado_em", "TIMESTAMP"),
    ("usuarios", "versao_sessao", "INTEGER NOT NULL DEFAULT 1"),
    ("produtos", "gtin", "VARCHAR(14)"),
    ("produtos", "registro_anvisa", "VARCHAR(20)"),
    ("lotes", "nota_fiscal_id", "INTEGER REFERENCES notas_fiscais(id)"),
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
    numerar_dispensacoes_antigas()
    if db.engine.dialect.name == "postgresql":
        converter_para_decimal()
        criar_restricoes_postgresql()


# Colunas que eram FLOAT (ponto flutuante) até a versão 1.x.
COLUNAS_DECIMAIS = [("produtos", "estoque_minimo"), ("produtos", "estoque_maximo"),
                    ("lotes", "custo_unitario"), ("lotes", "quantidade_inicial"), ("lotes", "saldo"),
                    ("movimentacoes", "quantidade"), ("movimentacoes", "custo_unitario")]

# Restrições criadas pelo create_all em bancos novos; em bancos antigos do PostgreSQL, criadas aqui.
RESTRICOES = [("produtos", "ck_produto_limites", "estoque_minimo >= 0 AND estoque_maximo >= 0"),
              ("lotes", "ck_lote_saldo_nao_negativo", "saldo >= 0"),
              ("lotes", "ck_lote_quantidade_inicial", "quantidade_inicial > 0"),
              ("lotes", "ck_lote_custo", "custo_unitario >= 0"),
              ("movimentacoes", "ck_movimentacao_quantidade", "quantidade <> 0")]


def converter_para_decimal():
    """PostgreSQL: converte quantidades e custos de double precision para numeric(14,4)."""
    with db.engine.begin() as conexao:
        for tabela, coluna in COLUNAS_DECIMAIS:
            tipo = conexao.execute(db.text(
                "SELECT data_type FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
                {"t": tabela, "c": coluna}).scalar()
            if tipo == "double precision":
                conexao.execute(db.text(
                    f"ALTER TABLE {tabela} ALTER COLUMN {coluna} TYPE numeric(14,4) "
                    f"USING round({coluna}::numeric, 4)"))


def criar_restricoes_postgresql():
    existentes = {linha[0] for linha in db.session.execute(db.text("SELECT conname FROM pg_constraint"))}
    db.session.rollback()
    for tabela, nome, regra in RESTRICOES:
        if nome in existentes:
            continue
        try:
            with db.engine.begin() as conexao:
                conexao.execute(db.text(f"ALTER TABLE {tabela} ADD CONSTRAINT {nome} CHECK ({regra})"))
        except Exception as erro:  # dados antigos que violam a regra: o sistema sobe e avisa
            logging.getLogger("exatamed").error(
                "Não foi possível criar a restrição %s (%s): %s. Rode 'flask --app exatamed "
                "verificar-integridade' e corrija os dados.", nome, regra, erro)


def numerar_dispensacoes_antigas():
    """Dá número no formato 00001/ano às dispensações registradas antes da numeração existir."""
    with db.engine.begin() as conexao:
        pendentes = conexao.execute(db.text(
            "SELECT id, data FROM dispensacoes WHERE numero IS NULL ORDER BY data, id")).all()
        proximos = {}
        for id_, data in pendentes:
            # O SQLite devolve a data como texto; o PostgreSQL, como datetime.
            ano = data.year if hasattr(data, "year") else int(str(data)[:4])
            if ano not in proximos:
                ultimo = conexao.execute(db.text("SELECT MAX(numero) FROM dispensacoes WHERE ano = :ano"),
                                         {"ano": ano}).scalar()
                proximos[ano] = (ultimo or 0) + 1
            conexao.execute(db.text("UPDATE dispensacoes SET ano = :ano, numero = :numero WHERE id = :id"),
                            {"ano": ano, "numero": proximos[ano], "id": id_})
            proximos[ano] += 1
    # Em bancos novos o create_all já criou o índice; em bancos antigos, cria agora.
    with db.engine.begin() as conexao:
        conexao.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_dispensacao_numero_ano ON dispensacoes (ano, numero)"))


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
        # Prefixo __Host-: o navegador só aceita o cookie via HTTPS, sem domínio, no caminho "/".
        SESSION_COOKIE_NAME="__Host-exatamed" if producao else "exatamed",
        REMEMBER_COOKIE_SECURE=producao,
        WTF_CSRF_TIME_LIMIT=None,
        # Limite de upload (XML de NF-e tem poucos KB; recusa arquivos grandes demais).
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        # Chave da cadeia de auditoria. Use uma chave própria e NUNCA a troque: as
        # assinaturas já gravadas deixariam de conferir.
        LOG_FORMATO=os.environ.get("EXATAMED_LOG_FORMATO"),  # "json" ou "texto"
        LOG_NIVEL=os.environ.get("EXATAMED_LOG_NIVEL", "INFO"),
        CHAVE_AUDITORIA=os.environ.get("EXATAMED_CHAVE_AUDITORIA")
        or os.environ.get("EXATAMED_SECRET_KEY", CHAVE_PADRAO),
    )
    if config:
        app.config.update(config)
    if producao and app.config["SECRET_KEY"] == CHAVE_PADRAO:
        raise RuntimeError("Defina a variável EXATAMED_SECRET_KEY antes de publicar o sistema.")
    if producao:
        # Atrás do proxy HTTPS do serviço de hospedagem.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    from .observabilidade import configurar_logs
    configurar_logs(app)
    if producao and not os.environ.get("EXATAMED_CHAVE_AUDITORIA"):
        app.logger.warning("EXATAMED_CHAVE_AUDITORIA não definida: a cadeia de auditoria usa a chave secreta. "
                           "Defina uma chave própria e nunca a altere.")

    db.init_app(app)
    csrf.init_app(app)

    from . import ajuda, auditoria, auth, cadastros, lgpd, views
    auth.login_manager.init_app(app)
    app.before_request(auth.exigir_login)
    app.register_blueprint(auth.bp)
    app.register_blueprint(views.principal)
    app.register_blueprint(views.bp_estoque)
    app.register_blueprint(views.bp_relatorios)
    app.register_blueprint(views.bp_dashboard)
    app.register_blueprint(cadastros.bp)
    app.register_blueprint(ajuda.bp)
    app.register_blueprint(lgpd.bp)
    app.register_blueprint(auditoria.bp)

    @app.route("/saude")
    def saude():
        """Verificação de funcionamento (hospedagem, balanceador, monitoramento).

        200 com a latência do banco quando tudo responde; 503 se o banco estiver fora.
        """
        inicio = time.perf_counter()
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception:
            db.session.rollback()
            app.logger.exception("Verificação de saúde: banco de dados indisponível")
            return {"status": "erro", "banco": "indisponivel", "versao": __version__}, 503
        return {"status": "ok", "banco": "ok", "latencia_banco_ms": round((time.perf_counter() - inicio) * 1000, 1),
                "versao": __version__}

    @app.after_request
    def cabecalhos_seguranca(resposta):
        resposta.headers.setdefault("Content-Security-Policy", CSP)
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "DENY")
        resposta.headers.setdefault("Referrer-Policy", "same-origin")
        resposta.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        if current_user.is_authenticated and request.endpoint != "static":
            # Páginas com dados de pacientes não ficam no cache do navegador (computadores compartilhados).
            resposta.headers["Cache-Control"] = "no-store"
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

    @app.errorhandler(413)
    def arquivo_grande(_erro):
        return render_template("erro.html", titulo="Arquivo muito grande",
                               mensagem="O arquivo enviado passa do limite de 5 MB. Confira se é o XML da NF-e."), 413

    @app.errorhandler(500)
    def erro_interno(_erro):
        return render_template("erro.html", titulo="Erro inesperado",
                               mensagem="Ocorreu um erro inesperado e ele foi registrado. Se o problema "
                                        "persistir, informe ao suporte o código abaixo.",
                               codigo=g.get("request_id")), 500

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

    @app.template_filter("percentual")
    def percentual(valor, casas=1):
        if valor is None:
            return "—"
        return f"{valor:.{casas}f}".replace(".", ",") + "%"

    @app.template_filter("numero_campo")
    def numero_campo(valor):
        """Valor para campos de formulário: decimal exato, sem separador de milhar (1234.5)."""
        from .numeros import decimal
        return f"{decimal(valor).normalize():f}"

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
        # Antes de qualquer gravação: sela o histórico existente na primeira execução da v2.
        auditoria.preparar_cadeias()
        garantir_locais_principais()
        auth.criar_admin_inicial()
        # Avisa ao iniciar o servidor; nos comandos (demo, criar-admin) o usuário está sendo criado.
        contexto = click.get_current_context(silent=True)
        em_comando = contexto is not None and contexto.command.name != "run"
        if not Usuario.query.first() and not app.config.get("TESTING") and not em_comando:
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

    @app.cli.command("verificar-integridade")
    def verificar_integridade_cmd():
        """Confere as cadeias de auditoria e os saldos dos lotes (código de saída 1 se houver problema)."""
        resultado = auditoria.verificar_integridade()
        for cadeia in resultado["cadeias"]:
            situacao = "OK" if cadeia["ok"] else "FALHA"
            click.echo(f"[{situacao}] {cadeia['descricao']}: {cadeia['total']} registro(s) selado(s)")
            for problema in cadeia["problemas"]:
                click.echo(f"    - {problema}")
        if resultado["lotes"]:
            click.echo(f"[FALHA] Saldos de lotes: {len(resultado['lotes'])} divergência(s)")
            for item in resultado["lotes"][:20]:
                click.echo(f"    - Lote {item['lote'].numero_lote} (id {item['lote'].id}): saldo {item['saldo']}, "
                           f"soma das movimentações {item['movimentacoes']}")
        else:
            click.echo("[OK] Saldos de lotes conferem com as movimentações")
        if not resultado["ok"]:
            raise SystemExit(1)

    @app.cli.command("anonimizar-banco")
    @click.option("--confirmar", is_flag=True, help="Confirma que este banco é uma CÓPIA.")
    def anonimizar_banco_cmd(confirmar):
        """Anonimiza todos os dados pessoais de uma CÓPIA do banco (treinamento e testes)."""
        from .lgpd import anonimizar_banco
        if app.config["PRODUCAO"]:
            raise click.ClickException("Comando bloqueado em produção (EXATAMED_ENV=production). "
                                       "Rode-o numa cópia do banco.")
        if not confirmar:
            raise click.ClickException("Operação irreversível. Use numa CÓPIA do banco e repita com --confirmar.")
        totais = anonimizar_banco()
        click.echo(f"Banco anonimizado: {totais['pacientes']} paciente(s), {totais['medicos']} médico(s) e "
                   f"{totais['usuarios']} usuário(s). Logins e senhas foram mantidos.")

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
