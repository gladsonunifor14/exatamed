"""Adequação à LGPD: registro de acessos a dados pessoais e anonimização.

- Mascaramento: CPF, Cartão SUS, RG e telefone aparecem parcialmente ocultos em listas,
  relatórios e exportações (ver `validacao.mascarar_*`); completos só na ficha do cadastro.
- Registro de acessos (art. 37): quem visualizou, alterou, exportou ou anonimizou dados pessoais.
- Anonimização (arts. 12, 16 e 18): substitui de forma irreversível os dados que identificam a
  pessoa, preservando o histórico de estoque e de custos. Respeita o prazo de guarda da
  escrituração de medicamentos de controle especial.
"""

import secrets
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, has_request_context, redirect, render_template, request, url_for
from flask_login import current_user

from .auth import perfil_requerido
from .models import Dispensacao, Medico, Movimentacao, Paciente, Produto, RegistroAcesso, Usuario, db

bp = Blueprint("lgpd", __name__, url_prefix="/lgpd")

# Prazo mínimo de guarda dos registros de medicamentos de controle especial
# (escrituração prevista na Portaria SVS/MS nº 344/1998). Ajuste conforme a orientação
# do encarregado de dados (DPO) e do farmacêutico responsável técnico.
PRAZO_GUARDA_CONTROLADOS_ANOS = 2
CONFIRMACAO = "ANONIMIZAR"
CAMPOS_ENDERECO = ("cep", "logradouro", "numero", "complemento", "bairro", "cidade")


class LGPDError(ValueError):
    """Operação recusada pelas regras de proteção de dados."""


# --------------------------------------------------------------------------- registro de acessos

def registrar_acesso(acao, entidade, registro_id=None, descricao=None):
    """Grava quem acessou dados pessoais. Faz commit próprio para valer também em consultas."""
    usuario_id = current_user.id if current_user and current_user.is_authenticated else None
    db.session.add(RegistroAcesso(
        acao=acao, entidade=entidade, registro_id=registro_id, usuario_id=usuario_id,
        descricao=(descricao or "")[:RegistroAcesso.descricao.type.length] or None,
        ip=(request.remote_addr or "")[:45] or None if has_request_context() else None,
    ))
    db.session.commit()


# --------------------------------------------------------------------------- anonimização

def _limite_guarda(hoje=None):
    hoje = hoje or date.today()
    return datetime.combine(hoje - timedelta(days=round(365.25 * PRAZO_GUARDA_CONTROLADOS_ANOS)),
                            datetime.min.time())


def _ultimo_controlado(filtro):
    """Data da dispensação de controlado mais recente que atende ao filtro, dentro do prazo de guarda."""
    return db.session.query(db.func.max(Dispensacao.data)) \
        .join(Movimentacao, Movimentacao.dispensacao_id == Dispensacao.id) \
        .join(Produto, Produto.id == Movimentacao.produto_id) \
        .filter(Produto.controle_especial.isnot(None), Produto.controle_especial != "",
                Dispensacao.data >= _limite_guarda(), filtro).scalar()


def impedimento(registro):
    """Motivo pelo qual o registro ainda não pode ser anonimizado, ou None."""
    if registro.anonimizado:
        return "Este cadastro já foi anonimizado."
    if isinstance(registro, Paciente):
        filtro, papel = Dispensacao.paciente_id == registro.id, "recebeu"
    elif isinstance(registro, Medico):
        filtro, papel = Dispensacao.medico_id == registro.id, "prescreveu"
    else:
        if registro.id == current_user.id:
            return "Você não pode anonimizar o seu próprio usuário."
        if registro.perfil == Usuario.ADMIN and registro.ativo and Usuario.query.filter(
                Usuario.perfil == Usuario.ADMIN, Usuario.ativo.is_(True), Usuario.id != registro.id).count() == 0:
            return "Este é o único administrador ativo do sistema."
        filtro, papel = Dispensacao.usuario_id == registro.id, "dispensou"
    ultimo = _ultimo_controlado(filtro)
    if ultimo:
        liberacao = ultimo + timedelta(days=round(365.25 * PRAZO_GUARDA_CONTROLADOS_ANOS))
        return (f"Este cadastro {papel} medicamento de controle especial em {ultimo:%d/%m/%Y}. A "
                f"escrituração de controlados deve ser guardada por {PRAZO_GUARDA_CONTROLADOS_ANOS} anos; "
                f"a anonimização será possível a partir de {liberacao:%d/%m/%Y}.")
    return None


def _anonimizar_pessoa(pessoa, rotulo):
    pessoa.nome = rotulo
    pessoa.cpf = pessoa.rg = pessoa.telefone = None
    for campo in CAMPOS_ENDERECO:
        setattr(pessoa, campo, None)
    # Generalização: mantém só o ano de nascimento (faixa etária para estatísticas).
    if pessoa.data_nascimento:
        pessoa.data_nascimento = date(pessoa.data_nascimento.year, 1, 1)
    pessoa.anonimizado_em = datetime.now()


def aplicar_anonimizacao_paciente(paciente):
    _anonimizar_pessoa(paciente, f"Paciente anonimizado {paciente.pseudonimo}")
    for campo in ("nome_mae", "cartao_sus", "responsavel", "grau_parentesco", "profissao", "alergias",
                  "tipo_sanguineo", "historico_doencas"):
        setattr(paciente, campo, None)


def aplicar_anonimizacao_medico(medico):
    _anonimizar_pessoa(medico, f"Médico anonimizado M-{medico.id:06d}")
    medico.crm, medico.uf_crm = f"ANON{medico.id}", "XX"


def aplicar_anonimizacao_usuario(usuario):
    rotulo = f"Usuário anonimizado U-{usuario.id:06d}"
    usuario.nome = rotulo
    usuario.login = f"anonimo-{usuario.id}"
    usuario.email = usuario.registro_profissional = None
    usuario.ativo = False
    usuario.encerrar_sessoes()
    usuario.definir_senha(secrets.token_urlsafe(32))
    usuario.anonimizado_em = datetime.now()
    # O nome também fica gravado como "responsável" nas dispensações que ele registrou.
    Dispensacao.query.filter_by(usuario_id=usuario.id).update({"responsavel": rotulo},
                                                              synchronize_session=False)


APLICAR = {"paciente": aplicar_anonimizacao_paciente, "medico": aplicar_anonimizacao_medico,
           "usuario": aplicar_anonimizacao_usuario}
MODELOS = {"paciente": Paciente, "medico": Medico, "usuario": Usuario}


def anonimizar(entidade, registro, motivo):
    """Anonimiza um cadastro de forma irreversível e registra a operação."""
    if not motivo or not motivo.strip():
        raise LGPDError("Informe o motivo da anonimização (ex.: pedido do titular, protocolo nº ...).")
    motivo_impedimento = impedimento(registro)
    if motivo_impedimento:
        raise LGPDError(motivo_impedimento)
    APLICAR[entidade](registro)
    db.session.commit()
    registrar_acesso(RegistroAcesso.ANONIMIZAR, entidade, registro.id, motivo.strip())


def anonimizar_banco():
    """Anonimiza TODOS os dados pessoais de uma cópia do banco (treinamento, testes, homologação).

    Não aplica o prazo de guarda, pois deve ser usado apenas em cópias. Mantém login e senha dos
    usuários para que a cópia continue utilizável.
    """
    totais = {"pacientes": 0, "medicos": 0, "usuarios": 0}
    for paciente in Paciente.query.filter(Paciente.anonimizado_em.is_(None)):
        aplicar_anonimizacao_paciente(paciente)
        totais["pacientes"] += 1
    for medico in Medico.query.filter(Medico.anonimizado_em.is_(None)):
        aplicar_anonimizacao_medico(medico)
        totais["medicos"] += 1
    for usuario in Usuario.query:
        usuario.nome = f"Usuário {usuario.id}"
        usuario.email = usuario.registro_profissional = None
        Dispensacao.query.filter_by(usuario_id=usuario.id).update({"responsavel": usuario.nome},
                                                                  synchronize_session=False)
        totais["usuarios"] += 1
    # Responsáveis em texto livre sem usuário vinculado e observações podem conter nomes.
    Dispensacao.query.filter(Dispensacao.usuario_id.is_(None)).update({"responsavel": None},
                                                                      synchronize_session=False)
    Dispensacao.query.update({"observacao": None}, synchronize_session=False)
    # O registro de acessos identifica pessoas e o comportamento delas no sistema.
    RegistroAcesso.query.delete()
    from .auditoria import reiniciar_cadeia
    reiniciar_cadeia("registros_acesso")
    db.session.commit()
    return totais


# --------------------------------------------------------------------------- telas (administrador)

@bp.route("/")
@perfil_requerido(Usuario.ADMIN)
def acessos():
    consulta = RegistroAcesso.query
    filtro = request.args
    if filtro.get("usuario_id", type=int):
        consulta = consulta.filter(RegistroAcesso.usuario_id == filtro.get("usuario_id", type=int))
    if filtro.get("entidade") in RegistroAcesso.ENTIDADES:
        consulta = consulta.filter(RegistroAcesso.entidade == filtro["entidade"])
    if filtro.get("acao") in RegistroAcesso.ACOES:
        consulta = consulta.filter(RegistroAcesso.acao == filtro["acao"])
    pagina = consulta.order_by(RegistroAcesso.data.desc(), RegistroAcesso.id.desc()).paginate(
        page=filtro.get("pagina", 1, type=int), per_page=50, error_out=False)
    return render_template(
        "lgpd/acessos.html", pagina=pagina, filtro=filtro,
        usuarios=Usuario.query.order_by(Usuario.nome).all(),
        totais={"pacientes": Paciente.query.filter(Paciente.anonimizado_em.isnot(None)).count(),
                "medicos": Medico.query.filter(Medico.anonimizado_em.isnot(None)).count(),
                "usuarios": Usuario.query.filter(Usuario.anonimizado_em.isnot(None)).count()},
        prazo=PRAZO_GUARDA_CONTROLADOS_ANOS, entidades=RegistroAcesso.ENTIDADES, acoes=RegistroAcesso.ACOES)


@bp.route("/anonimizar/<entidade>/<int:id>", methods=["GET", "POST"])
@perfil_requerido(Usuario.ADMIN)
def anonimizar_cadastro(entidade, id):
    if entidade not in MODELOS:
        abort(404)
    registro = db.get_or_404(MODELOS[entidade], id)
    voltar = url_for("auth.usuarios") if entidade == "usuario" else \
        url_for("cadastros.listar", chave=entidade + "s")
    if request.method == "POST":
        if request.form.get("confirmacao", "").strip().upper() != CONFIRMACAO:
            flash(f"Para confirmar, digite {CONFIRMACAO}.", "danger")
        else:
            try:
                anonimizar(entidade, registro, request.form.get("motivo", ""))
                flash("Cadastro anonimizado. Os dados pessoais foram removidos de forma definitiva; "
                      "o histórico de estoque foi preservado.", "success")
                return redirect(voltar)
            except LGPDError as erro:
                db.session.rollback()
                flash(str(erro), "danger")
    return render_template("lgpd/anonimizar.html", entidade=entidade, registro=registro,
                           impedimento=impedimento(registro), voltar=voltar, confirmacao=CONFIRMACAO,
                           rotulo=RegistroAcesso.ENTIDADES[entidade])
