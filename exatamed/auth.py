"""Autenticação, perfis de acesso e gestão de usuários."""

import os
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from .models import TentativaLogin, Usuario, db

bp = Blueprint("auth", __name__)
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Entre com seu usuário e senha para acessar o sistema."
login_manager.login_message_category = "warning"

SENHA_MINIMA = 8
# Limite por endereço IP (complementa o bloqueio por usuário). Alto o bastante para não
# bloquear um hospital inteiro que sai para a internet por um único IP.
MAX_FALHAS_POR_IP = 30
JANELA_IP = timedelta(minutes=15)
# Hash usado quando o login não existe, para que o tempo de resposta não revele
# quais logins são válidos.
_HASH_FICTICIO = generate_password_hash("senha-ficticia-para-tempo-constante")
MAX_TENTATIVAS = 5
TEMPO_BLOQUEIO = timedelta(minutes=15)
# Endpoints acessíveis sem login.
PUBLICOS = {"auth.login", "static", "saude"}
# Endpoints liberados para quem precisa trocar a senha.
LIBERADOS_TROCA_SENHA = {"auth.minha_senha", "auth.logout", "static", "saude"}


@login_manager.user_loader
def carregar_usuario(identificador):
    """A sessão guarda "id:versão". Se a versão mudou (senha, perfil ou desativação), a sessão expira."""
    try:
        usuario_id, versao = (int(parte) for parte in identificador.split(":"))
    except ValueError:
        return None
    usuario = db.session.get(Usuario, usuario_id)
    if not usuario or not usuario.ativo or usuario.versao_sessao != versao:
        return None
    return usuario


def perfil_requerido(perfil_minimo):
    """Restringe a view a usuários com o perfil informado ou superior."""
    def decorador(view):
        @wraps(view)
        def envoltorio(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if not current_user.pode(perfil_minimo):
                abort(403)
            return view(*args, **kwargs)
        return envoltorio
    return decorador


def exigir_login():
    """`before_request` global: todo o sistema exige login, exceto as rotas públicas."""
    if request.endpoint is None or request.endpoint in PUBLICOS:
        return None
    if not current_user.is_authenticated:
        return login_manager.unauthorized()
    if current_user.deve_trocar_senha and request.endpoint not in LIBERADOS_TROCA_SENHA:
        flash("Defina uma nova senha para continuar.", "warning")
        return redirect(url_for("auth.minha_senha"))
    return None


def validar_senha(senha, confirmacao, login=None):
    if len(senha) < SENHA_MINIMA:
        return f"A senha deve ter pelo menos {SENHA_MINIMA} caracteres."
    if senha != confirmacao:
        return "A confirmação não confere com a senha."
    if login and senha.lower() == login.lower():
        return "A senha não pode ser igual ao login."
    if senha.isdigit() or senha.isalpha():
        return "Use letras e números na senha."
    return None


def _destino_seguro(destino):
    """Aceita apenas redirecionamentos para caminhos internos do sistema."""
    if not destino:
        return None
    partes = urlsplit(destino)
    # Navegadores tratam "\" como "/": "/\site.com" viraria "//site.com" (outro domínio).
    if "\\" in destino:
        return None
    if partes.scheme or partes.netloc or not destino.startswith("/") or destino.startswith("//"):
        return None
    return destino


def criar_admin_inicial():
    """Cria o primeiro administrador a partir de variáveis de ambiente, se não houver usuários.

    Usado na publicação (ex.: Render), onde não há terminal para rodar comandos.
    """
    login = os.environ.get("EXATAMED_ADMIN_LOGIN", "").strip()
    senha = os.environ.get("EXATAMED_ADMIN_SENHA", "")
    if not login or not senha or Usuario.query.first():
        return None
    if len(senha) < SENHA_MINIMA:
        raise RuntimeError(f"EXATAMED_ADMIN_SENHA deve ter pelo menos {SENHA_MINIMA} caracteres.")
    admin = Usuario(nome=os.environ.get("EXATAMED_ADMIN_NOME", "Administrador"), login=login,
                    perfil=Usuario.ADMIN)
    admin.definir_senha(senha)
    db.session.add(admin)
    db.session.commit()
    return admin


class CredencialInvalida(Exception):
    """Login ou senha recusados; ``status`` é o código HTTP sugerido para a resposta."""

    def __init__(self, mensagem, status=200):
        super().__init__(mensagem)
        self.status = status


def verificar_credenciais(login_digitado, senha):
    """Confere login e senha com as mesmas proteções do login.

    Limite de falhas por IP, bloqueio do usuário após tentativas seguidas e tempo de resposta
    constante para login inexistente. Em caso de falha, grava a tentativa e confirma a
    transação; em caso de sucesso, zera os contadores (o chamador confirma).
    """
    login_digitado = (login_digitado or "").strip().lower()
    agora = datetime.now()
    ip = (request.remote_addr or "desconhecido")[:45]
    if TentativaLogin.query.filter(TentativaLogin.ip == ip, TentativaLogin.data > agora - JANELA_IP).count() \
            >= MAX_FALHAS_POR_IP:
        raise CredencialInvalida("Muitas tentativas de acesso a partir deste endereço. Aguarde 15 minutos e "
                                 "tente novamente.", 429)
    usuario = Usuario.query.filter(db.func.lower(Usuario.login) == login_digitado).first()
    if usuario is None:
        check_password_hash(_HASH_FICTICIO, senha)
    if usuario and usuario.bloqueado_ate and usuario.bloqueado_ate > agora:
        minutos = int((usuario.bloqueado_ate - agora).total_seconds() // 60) + 1
        raise CredencialInvalida(f"Usuário bloqueado por excesso de tentativas. Tente novamente em {minutos} "
                                 "minuto(s).")
    if usuario and usuario.ativo and usuario.conferir_senha(senha):
        usuario.tentativas_falhas = 0
        usuario.bloqueado_ate = None
        return usuario
    if usuario and usuario.ativo:
        usuario.tentativas_falhas += 1
        if usuario.tentativas_falhas >= MAX_TENTATIVAS:
            usuario.bloqueado_ate = agora + TEMPO_BLOQUEIO
            usuario.tentativas_falhas = 0
    db.session.add(TentativaLogin(ip=ip, data=agora))
    TentativaLogin.query.filter(TentativaLogin.data < agora - timedelta(days=1)).delete()
    db.session.commit()
    raise CredencialInvalida("Usuário ou senha inválidos.")


def autorizar(login_digitado, senha, perfil_minimo=Usuario.FARMACEUTICO):
    """Autorização de uma operação sensível pela senha de um usuário com o perfil exigido."""
    usuario = verificar_credenciais(login_digitado, senha)
    if not usuario.pode(perfil_minimo):
        raise CredencialInvalida(f"{usuario.login} não pode autorizar esta operação: é preciso o perfil "
                                 f"{Usuario.PERFIS[perfil_minimo]} ou Administrador(a).")
    return usuario


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("principal.painel"))
    if request.method == "POST":
        try:
            usuario = verificar_credenciais(request.form.get("login", ""), request.form.get("senha", ""))
        except CredencialInvalida as erro:
            flash(str(erro), "danger")
            return render_template("auth/login.html"), erro.status
        usuario.ultimo_acesso = datetime.now()
        db.session.commit()
        session.clear()
        login_user(usuario)
        session.permanent = True
        return redirect(_destino_seguro(request.args.get("next")) or url_for("principal.painel"))
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/minha-senha", methods=["GET", "POST"])
@login_required
def minha_senha():
    if request.method == "POST":
        atual = request.form.get("senha_atual", "")
        nova = request.form.get("nova_senha", "")
        erro = None
        if not current_user.conferir_senha(atual):
            erro = "A senha atual está incorreta."
        elif atual == nova:
            erro = "A nova senha deve ser diferente da atual."
        else:
            erro = validar_senha(nova, request.form.get("confirmacao", ""), current_user.login)
        if erro:
            flash(erro, "danger")
        else:
            current_user.definir_senha(nova)
            current_user.deve_trocar_senha = False
            current_user.encerrar_sessoes()
            db.session.commit()
            login_user(current_user._get_current_object())  # renova esta sessão; as demais deixam de valer
            flash("Senha alterada com sucesso.", "success")
            return redirect(url_for("principal.painel"))
    return render_template("auth/minha_senha.html")


@bp.route("/minha-aparencia", methods=["POST"])
@login_required
def meu_tema():
    tema = request.form.get("tema")
    if tema not in Usuario.TEMAS:
        abort(400)
    current_user.tema = tema
    db.session.commit()
    return redirect(_destino_seguro(request.form.get("voltar")) or url_for("principal.painel"))


# --------------------------------------------------------------------------- usuários (admin)

@bp.route("/usuarios/")
@perfil_requerido(Usuario.ADMIN)
def usuarios():
    return render_template("auth/usuarios.html",
                           usuarios=Usuario.query.order_by(Usuario.nome).all(), agora=datetime.now())


@bp.route("/usuarios/novo", methods=["GET", "POST"])
@bp.route("/usuarios/<int:id>/editar", methods=["GET", "POST"])
@perfil_requerido(Usuario.ADMIN)
def editar_usuario(id=None):
    from .lgpd import registrar_acesso
    from .models import RegistroAcesso
    usuario = db.get_or_404(Usuario, id) if id else Usuario(ativo=True, perfil=Usuario.AUXILIAR)
    if usuario.anonimizado:
        flash("Este usuário foi anonimizado e não pode mais ser alterado.", "warning")
        return redirect(url_for(".usuarios"))
    if request.method == "POST":
        f = request.form
        erros = []
        nome = f.get("nome", "").strip()
        login_novo = f.get("login", "").strip().lower()
        perfil = f.get("perfil")
        ativo = bool(f.get("ativo"))
        senha = f.get("senha", "")
        if not nome or not login_novo:
            erros.append("Informe nome e login.")
        if len(login_novo) > 50 or not login_novo.replace(".", "").replace("_", "").replace("-", "").isalnum():
            erros.append("O login deve ter até 50 caracteres: letras, números, ponto, hífen ou sublinhado.")
        if perfil not in Usuario.PERFIS:
            erros.append("Perfil inválido.")
        duplicado = Usuario.query.filter(db.func.lower(Usuario.login) == login_novo,
                                         Usuario.id != (usuario.id or 0)).first()
        if duplicado:
            erros.append("Já existe um usuário com este login.")
        if usuario.id == current_user.id and (perfil != Usuario.ADMIN or not ativo):
            erros.append("Você não pode remover o próprio acesso de administrador.")
        if not usuario.id or senha:
            erro_senha = validar_senha(senha, f.get("confirmacao", ""), login_novo)
            if erro_senha:
                erros.append(erro_senha)
        if erros:
            for erro in erros:
                flash(erro, "danger")
        else:
            if usuario.id and (senha or perfil != usuario.perfil or not ativo):
                usuario.encerrar_sessoes()
            usuario.nome = nome
            usuario.login = login_novo
            usuario.email = f.get("email", "").strip() or None
            usuario.registro_profissional = f.get("registro_profissional", "").strip() or None
            usuario.perfil = perfil
            usuario.ativo = ativo
            if senha:
                usuario.definir_senha(senha)
                # Senha definida pelo administrador é provisória.
                usuario.deve_trocar_senha = usuario.id != current_user.id
                usuario.tentativas_falhas = 0
                usuario.bloqueado_ate = None
            db.session.add(usuario)
            db.session.commit()
            registrar_acesso(RegistroAcesso.ALTERAR if id else RegistroAcesso.INCLUIR, "usuario",
                             usuario.id, usuario.login)
            flash(f"Usuário {usuario.login} salvo.", "success")
            return redirect(url_for(".usuarios"))
    if id and request.method == "GET":
        registrar_acesso(RegistroAcesso.VISUALIZAR, "usuario", usuario.id, usuario.login)
    return render_template("auth/usuario_form.html", usuario=usuario, perfis=Usuario.PERFIS,
                           form=request.form if request.method == "POST" else None)


@bp.route("/usuarios/<int:id>/desbloquear", methods=["POST"])
@perfil_requerido(Usuario.ADMIN)
def desbloquear_usuario(id):
    usuario = db.get_or_404(Usuario, id)
    usuario.bloqueado_ate = None
    usuario.tentativas_falhas = 0
    db.session.commit()
    flash(f"Usuário {usuario.login} desbloqueado.", "success")
    return redirect(url_for(".usuarios"))
