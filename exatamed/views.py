"""Telas de estoque, dispensação e relatórios."""

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from . import dashboard, entrada_nfe, estoque, graficos, relatorios
from .ajuda import primeiros_passos
from .auth import CredencialInvalida, autorizar, perfil_requerido
from .cadastros import CADASTROS, LISTAS_CONTROLE, UNIDADES, preencher
from .estoque import EstoqueError
from .lgpd import registrar_acesso
from .models import (
    Dispensacao,
    Localizacao,
    Lote,
    Medico,
    Movimentacao,
    NotaFiscal,
    Paciente,
    Produto,
    RegistroAcesso,
    Usuario,
    db,
)
from .nfe import TAMANHO_MAXIMO as TAMANHO_MAXIMO_NFE
from .nfe import NFeError
from .numeros import ZERO, decimal, formatar

principal = Blueprint("principal", __name__)
bp_estoque = Blueprint("estoque", __name__, url_prefix="/estoque")
bp_relatorios = Blueprint("relatorios", __name__, url_prefix="/relatorios")
bp_dashboard = Blueprint("dashboard", __name__, url_prefix="/dashboard")


def _data(nome, padrao=None):
    valor = request.values.get(nome)
    if not valor:
        return padrao
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        raise EstoqueError(f"Data inválida: {valor}") from None


def _numero(nome):
    try:
        return decimal(request.form.get(nome) or "")
    except ValueError:
        raise EstoqueError("Informe uma quantidade numérica válida.") from None


def _texto(nome, coluna, rotulo):
    """Texto opcional do formulário, respeitando o tamanho da coluna no banco."""
    valor = (request.form.get(nome) or "").strip()
    limite = coluna.type.length
    if limite and len(valor) > limite:
        raise EstoqueError(f"O campo '{rotulo}' aceita no máximo {limite} caracteres.")
    return valor or None


def _obter(modelo, nome, obrigatorio=True, rotulo=None):
    valor = request.values.get(nome, type=int)
    obj = db.session.get(modelo, valor) if valor else None
    if obrigatorio and obj is None:
        raise EstoqueError(f"Selecione {rotulo or nome}.")
    return obj


def _contexto_formularios():
    return {
        "produtos": Produto.query.filter_by(ativo=True).order_by(Produto.nome_comercial).all(),
        "locais": Localizacao.query.filter_by(ativo=True).order_by(Localizacao.principal.desc(),
                                                                   Localizacao.nome).all(),
        # Cadastros anonimizados não recebem novas dispensações. Os pacientes não são
        # carregados aqui (podem ser milhares): a dispensação usa busca incremental.
        "medicos": Medico.query.filter(Medico.anonimizado_em.is_(None)).order_by(Medico.nome).all(),
        "hoje": date.today(),
    }


@principal.route("/")
def painel():
    hoje = date.today()
    pedido = relatorios.calcular_pedido_compra()
    a_vencer = Lote.query.filter(Lote.saldo > 0, Lote.validade <= hoje + timedelta(days=90)) \
        .order_by(Lote.validade).limit(15).all()
    inicio = datetime.combine(hoje, datetime.min.time())
    consumo_hoje = sum((m.consumo_custo for m in Movimentacao.query.filter(
        Movimentacao.tipo.in_(Movimentacao.CONSUMO), Movimentacao.data >= inicio)), ZERO)
    return render_template(
        "painel.html",
        total_produtos=Produto.query.filter_by(ativo=True).count(),
        total_pacientes=Paciente.query.count(),
        dispensacoes_hoje=Dispensacao.query.filter(Dispensacao.data >= inicio).count(),
        consumo_hoje=consumo_hoje,
        valor_estoque=sum(l.saldo * l.custo_unitario for l in Lote.query.filter(Lote.saldo > 0)),
        repor=[p for p in pedido if p["sugestao"] > 0],
        a_vencer=a_vencer,
        hoje=hoje,
        ultimas=Dispensacao.query.order_by(Dispensacao.data.desc()).limit(8).all(),
        passos=_passos_do_painel(),
    )


def _passos_do_painel():
    """Checklist de implantação: só para o administrador, até tudo estar feito ou ele ocultar."""
    if not current_user.pode(Usuario.ADMIN) or current_user.ocultar_primeiros_passos:
        return None
    passos = primeiros_passos()
    return None if all(p["feito"] for p in passos) else passos


# --------------------------------------------------------------------------- estoque

def _executar(operacao, sucesso, template, **extra):
    """Executa uma operação de estoque com commit/rollback e mensagens."""
    if request.method == "POST":
        try:
            resultado = operacao()
            db.session.commit()
            flash(sucesso(resultado) if callable(sucesso) else sucesso, "success")
            return redirect(request.url)
        except EstoqueError as erro:
            db.session.rollback()
            flash(str(erro), "danger")
    return render_template(template, **_contexto_formularios(), **extra)


@bp_estoque.route("/entrada", methods=["GET", "POST"])
def entrada():
    def operacao():
        produto = _obter(Produto, "produto_id", rotulo="o produto")
        local = _obter(Localizacao, "localizacao_id", rotulo="a localização")
        validade = _data("validade")
        if not validade:
            raise EstoqueError("Informe a validade do lote.")
        if validade < date.today():
            raise EstoqueError("Não é permitido dar entrada em lote vencido.")
        return estoque.registrar_entrada(
            produto, local, _texto("numero_lote", Lote.numero_lote, "Lote") or "", validade,
            _numero("quantidade"), _numero("custo_unitario"),
            documento=_texto("documento", Movimentacao.documento, "Documento"),
        )
    return _executar(operacao, lambda l: f"Entrada registrada: lote {l.numero_lote} de {l.produto}.",
                     "estoque/entrada.html")


# --------------------------------------------------------------------------- entrada por XML da NF-e

@bp_estoque.route("/entrada/nfe", methods=["POST"])
def receber_nfe():
    arquivo = request.files.get("xml")
    if not arquivo or not arquivo.filename:
        flash("Selecione o arquivo XML da NF-e.", "danger")
        return redirect(url_for(".entrada"))
    try:
        nota = entrada_nfe.receber_xml(arquivo.read(TAMANHO_MAXIMO_NFE + 1))
        db.session.commit()
    except NFeError as erro:
        db.session.rollback()
        flash(str(erro), "danger")
        return redirect(url_for(".entrada"))
    return redirect(url_for(".conferir_nfe", id=nota.id))


def _escolhas_do_formulario(dados):
    escolhas = {}
    for item in dados["itens"]:
        n = item["numero"]
        produto_id = request.form.get(f"item_{n}_produto", type=int)
        lotes = []
        for k in range(len(item["lotes"])):
            texto_validade = request.form.get(f"item_{n}_validade_{k}") or ""
            try:
                validade = datetime.strptime(texto_validade, "%Y-%m-%d").date() if texto_validade else None
            except ValueError:
                raise EstoqueError(f"Item {n}: validade inválida.") from None
            lotes.append({"lote": request.form.get(f"item_{n}_lote_{k}", ""), "validade": validade})
        escolhas[n] = {"importar": bool(request.form.get(f"item_{n}_importar")),
                       "produto": db.session.get(Produto, produto_id) if produto_id else None,
                       "fator": request.form.get(f"item_{n}_fator") or "1", "lotes": lotes}
    return escolhas


@bp_estoque.route("/nfe/<int:id>", methods=["GET", "POST"])
def conferir_nfe(id):
    nota = db.get_or_404(NotaFiscal, id)
    dados = entrada_nfe.dados_da_nota(nota)
    if request.method == "POST" and nota.situacao == NotaFiscal.PENDENTE:
        try:
            entradas = entrada_nfe.confirmar(nota, _obter(Localizacao, "localizacao_id", obrigatorio=False),
                                             _escolhas_do_formulario(dados))
            nota.usuario_id = current_user.id
            db.session.commit()
            flash(f"{nota.documento} importada: {entradas} lote(s) deram entrada no estoque.", "success")
            return redirect(url_for(".conferir_nfe", id=nota.id))
        except EstoqueError as erro:
            db.session.rollback()
            nota = db.session.get(NotaFiscal, id)
            flash(str(erro), "danger")
    sugestoes = {}
    for item in dados["itens"]:
        produto, fator, origem = entrada_nfe.sugerir_produto(nota.emitente_cnpj, item)
        sugestoes[item["numero"]] = {"produto": produto, "fator": fator, "origem": origem,
                                     "ultimo_custo": entrada_nfe.ultimo_custo(produto.id) if produto else None}
    formulario = request.form if request.method == "POST" else None
    return render_template("estoque/nfe_conferencia.html", nota=nota, dados=dados, sugestoes=sugestoes,
                           origens=entrada_nfe.ORIGENS_SUGESTAO, form=formulario, listas_controle=LISTAS_CONTROLE,
                           unidades=UNIDADES, tipos=Produto.TIPOS, **_contexto_formularios())


@bp_estoque.route("/nfe/<int:id>/descartar", methods=["POST"])
def descartar_nfe(id):
    nota = db.get_or_404(NotaFiscal, id)
    try:
        entrada_nfe.descartar(nota)
        db.session.commit()
        flash(f"{nota.documento} descartada. Ela pode ser enviada de novo quando necessário.", "info")
    except EstoqueError as erro:
        flash(str(erro), "danger")
    return redirect(url_for(".notas_fiscais"))


@bp_estoque.route("/nfe/<int:id>/excluir", methods=["POST"])
@perfil_requerido(Usuario.FARMACEUTICO)
def excluir_nfe(id):
    nota = db.get_or_404(NotaFiscal, id)
    documento = nota.documento
    try:
        entrada_nfe.excluir(nota)
        db.session.commit()
        flash(f"{documento} excluída.", "success")
    except EstoqueError as erro:
        db.session.rollback()
        flash(str(erro), "danger")
    return redirect(url_for(".notas_fiscais"))


@bp_estoque.route("/nfe/<int:id>/produto", methods=["POST"])
@perfil_requerido(Usuario.FARMACEUTICO)
def cadastrar_produto_nfe(id):
    """Cadastra, sem sair da conferência, o produto de um item da nota que não está no sistema."""
    nota = db.get_or_404(NotaFiscal, id)
    if nota.situacao != NotaFiscal.PENDENTE:
        return jsonify(erros=["Esta nota não está mais em conferência."]), 409
    cadastro = CADASTROS["produtos"]
    dados = request.form.to_dict()
    dados["ativo"] = "on"
    produto = Produto()
    with db.session.no_autoflush:
        erros = preencher(cadastro, produto, dados)
    if erros:
        db.session.rollback()
        return jsonify(erros=erros), 422
    db.session.add(produto)
    db.session.commit()
    texto = str(produto) + (f" [{produto.principio_ativo}]" if produto.principio_ativo else "")
    return jsonify(id=produto.id, texto=texto,
                   unidade=produto.unidade_medida, controle=produto.controle_especial or "",
                   aviso=getattr(produto, "aviso_cadastro", None)), 201


@bp_estoque.route("/notas")
def notas_fiscais():
    pagina = NotaFiscal.query.order_by(NotaFiscal.criado_em.desc()).paginate(
        page=request.args.get("pagina", 1, type=int), per_page=30, error_out=False)
    return render_template("estoque/notas.html", pagina=pagina)


@bp_estoque.route("/saida", methods=["GET", "POST"])
@perfil_requerido(Usuario.FARMACEUTICO)
def saida():
    def operacao():
        produto = _obter(Produto, "produto_id", rotulo="o produto")
        local = _obter(Localizacao, "localizacao_id", rotulo="a localização")
        movs = estoque.registrar_saida(produto, local, _numero("quantidade"),
                                       _texto("motivo", Movimentacao.motivo, "Motivo"),
                                       documento=_texto("documento", Movimentacao.documento, "Documento"))
        return sum(m.custo_total for m in movs)
    return _executar(operacao, lambda custo: f"Saída registrada. Custo PEPS: R$ {custo:,.2f}.",
                     "estoque/saida.html", motivos_saida=dashboard.MOTIVOS_SAIDA)


@bp_estoque.route("/transferencia", methods=["GET", "POST"])
def transferencia():
    def operacao():
        produto = _obter(Produto, "produto_id", rotulo="o produto")
        origem = _obter(Localizacao, "origem_id", rotulo="a origem")
        destino = _obter(Localizacao, "destino_id", rotulo="o destino")
        return estoque.transferir(produto, origem, destino, _numero("quantidade"),
                                  documento=_texto("documento", Movimentacao.documento, "Documento"))
    return _executar(operacao, "Transferência registrada.", "estoque/transferencia.html")


def _registrar_dispensacao():
    paciente = _obter(Paciente, "paciente_id", rotulo="o paciente")
    itens = []
    for pid, qtd in zip(request.form.getlist("item_produto"), request.form.getlist("item_quantidade")):
        if not pid and not qtd:
            continue
        produto = db.session.get(Produto, int(pid)) if pid else None
        if not produto:
            raise EstoqueError("Selecione o produto de cada item.")
        try:
            quantidade = decimal(qtd)
        except ValueError:
            raise EstoqueError(f"Quantidade inválida para {produto}.") from None
        itens.append((produto, quantidade))
    farmaceutico = current_user.pode(Usuario.FARMACEUTICO)
    controlados = [str(p) for p, _ in itens if p.controlado]
    if controlados and not farmaceutico:
        raise EstoqueError("Itens de controle especial só podem ser dispensados por farmacêutico: "
                           + ", ".join(controlados) + ".")
    return estoque.dispensar(
        paciente,
        _obter(Localizacao, "origem_id", rotulo="a farmácia de origem"),
        _obter(Localizacao, "destino_id", rotulo="o local de dispensação"),
        itens,
        medico=_obter(Medico, "medico_id", obrigatorio=False),
        prescricao=_texto("prescricao", Dispensacao.prescricao, "Nº da prescrição"),
        observacao=request.form.get("observacao") or None,
        responsavel=current_user.nome[:Dispensacao.responsavel.type.length],
        # Só o farmacêutico pode liberar uma dispensação com alerta de alergia.
        confirmar_alergia=farmaceutico and bool(request.form.get("confirmar_alergia")),
        data=_data_dispensacao(),
    )


FORMATO_DATA_HORA = "%Y-%m-%dT%H:%M"


def _data_dispensacao():
    """Data e hora informadas na dispensação (None = agora).

    O campo vem preenchido com a hora em que a tela foi aberta; se não foi alterado, vale o
    momento do registro. Data futura é recusada em `estoque.dispensar`.
    """
    texto = (request.form.get("data_dispensacao") or "").strip()
    if not texto or texto == request.form.get("data_sugerida"):
        return None
    try:
        return datetime.strptime(texto, FORMATO_DATA_HORA)
    except ValueError:
        raise EstoqueError("Data e hora da dispensação inválidas.") from None


@bp_estoque.route("/dispensacao", methods=["GET", "POST"])
def dispensacao():
    alerta = None
    if request.method == "POST":
        try:
            # Duas dispensações gravadas ao mesmo tempo podem disputar o mesmo número
            # (o índice único do banco impede a duplicidade); nesse caso, tenta de novo.
            for tentativa in range(3):
                try:
                    disp = _registrar_dispensacao()
                    db.session.commit()
                    break
                except IntegrityError:
                    db.session.rollback()
                    if tentativa == 2:
                        raise EstoqueError("Não foi possível numerar a dispensação. Tente novamente.") from None
            flash(f"Dispensação nº {disp.numero_formatado} registrada para {disp.paciente.nome}. "
                  f"Custo PEPS: R$ {disp.custo_total:,.2f}.", "success")
            return redirect(url_for(".ver_dispensacao", id=disp.id))
        except EstoqueError as erro:
            db.session.rollback()
            if str(erro).startswith("ALERTA DE ALERGIA"):
                alerta = str(erro)
            else:
                flash(str(erro), "danger")
    contexto = _contexto_formularios()
    # Só as farmácias principais (Farmácia SUS e Farmácia Particular) podem ser origem.
    contexto["origens"] = [l for l in contexto["locais"] if l.principal]
    paciente_id = request.form.get("paciente_id", type=int)
    contexto["paciente_selecionado"] = db.session.get(Paciente, paciente_id) if paciente_id else None
    contexto["agora_campo"] = datetime.now().strftime(FORMATO_DATA_HORA)
    return render_template("estoque/dispensacao.html", alerta=alerta, form=request.form, **contexto)


@bp_estoque.route("/pacientes/busca")
def buscar_pacientes():
    """Busca incremental de pacientes para a dispensação (nome, CPF ou Cartão SUS).

    Devolve no máximo 15 resultados, com CPF mascarado. Cadastros anonimizados não aparecem.
    """
    termo = (request.args.get("q") or "").strip()
    if len(termo) < 2:
        return []
    filtros = [Paciente.nome.ilike(f"%{termo}%")]
    digitos = "".join(c for c in termo if c.isdigit())
    if len(digitos) >= 3:
        filtros += [Paciente.cpf.ilike(f"%{digitos[:3]}%{digitos[3:]}%"), Paciente.cartao_sus.ilike(f"%{digitos}%")]
    pacientes = Paciente.query.filter(Paciente.anonimizado_em.is_(None), db.or_(*filtros)) \
        .order_by(Paciente.nome).limit(15).all()
    return [{"id": p.id, "nome": p.nome, "cpf": p.cpf_mascarado, "plano": p.plano_saude or "",
             "nascimento": p.data_nascimento.strftime("%d/%m/%Y") if p.data_nascimento else "",
             "alergias": p.alergias or ""} for p in pacientes]


@bp_estoque.route("/dispensacao/<int:id>")
def ver_dispensacao(id):
    dispensacao = db.get_or_404(Dispensacao, id)
    # O comprovante mostra o Cartão SUS completo (necessário para faturamento): acesso registrado.
    registrar_acesso(RegistroAcesso.VISUALIZAR, "dispensacao", dispensacao.id,
                     f"Comprovante {dispensacao.numero_formatado}")
    return render_template("estoque/dispensacao_ver.html", d=dispensacao)


@bp_estoque.route("/alergias")
def checar_alergias():
    """Endpoint JSON usado pela tela de dispensação para alertar em tempo real."""
    paciente = db.session.get(Paciente, request.args.get("paciente_id", type=int) or 0)
    produto = db.session.get(Produto, request.args.get("produto_id", type=int) or 0)
    if not paciente or not produto:
        return {"conflitos": []}
    return {"conflitos": estoque.verificar_alergias(paciente, produto),
            "controlado": produto.controle_especial or "",
            "saldos": {str(l.id): formatar(estoque.saldo(produto.id, l.id)) for l in Localizacao.query.all()}}


@bp_estoque.route("/dispensacao/<int:id>/devolver", methods=["GET", "POST"])
@perfil_requerido(Usuario.FARMACEUTICO)
def devolver_dispensacao(id):
    dispensacao = db.get_or_404(Dispensacao, id)
    if request.method == "POST":
        try:
            if request.form.get("tudo"):
                quantidades = {m.id: m.quantidade_a_devolver for m in dispensacao.itens_dispensados
                               if m.quantidade_a_devolver > 0}
            else:
                quantidades = {m.id: request.form.get(f"devolver_{m.id}") or "0"
                               for m in dispensacao.itens_dispensados}
            devolucoes = estoque.devolver(dispensacao, quantidades, request.form.get("motivo"))
            db.session.commit()
            flash(f"Devolução registrada: {len(devolucoes)} item(ns) retornaram ao estoque.", "success")
            return redirect(url_for(".ver_dispensacao", id=dispensacao.id))
        except EstoqueError as erro:
            db.session.rollback()
            flash(str(erro), "danger")
    return render_template("estoque/dispensacao_devolver.html", d=dispensacao)


@bp_estoque.route("/lotes/<int:id>/bloqueio", methods=["GET", "POST"])
@perfil_requerido(Usuario.FARMACEUTICO)
def bloqueio_lote(id):
    lote = db.get_or_404(Lote, id)
    mesmos = Lote.query.filter_by(produto_id=lote.produto_id, numero_lote=lote.numero_lote) \
        .order_by(Lote.localizacao_id).all()
    if request.method == "POST":
        try:
            if lote.bloqueado:
                estoque.desbloquear_lote(lote.produto, lote.numero_lote, request.form.get("motivo"))
                mensagem = f"Lote {lote.numero_lote} desbloqueado."
            else:
                estoque.bloquear_lote(lote.produto, lote.numero_lote, request.form.get("motivo"))
                mensagem = f"Lote {lote.numero_lote} bloqueado em todos os locais."
            db.session.commit()
            flash(mensagem, "success")
            return redirect(url_for(".lotes", produto_id=lote.produto_id))
        except EstoqueError as erro:
            db.session.rollback()
            flash(str(erro), "danger")
    return render_template("estoque/lote_bloqueio.html", lote=lote, mesmos=mesmos)


@bp_estoque.route("/lotes")
def lotes():
    consulta = Lote.query.join(Produto)
    produto_id = request.args.get("produto_id", type=int)
    localizacao_id = request.args.get("localizacao_id", type=int)
    if produto_id:
        consulta = consulta.filter(Lote.produto_id == produto_id)
    if localizacao_id:
        consulta = consulta.filter(Lote.localizacao_id == localizacao_id)
    if not request.args.get("zerados"):
        consulta = consulta.filter(Lote.saldo > 0)
    return render_template("estoque/lotes.html",
                           lotes=consulta.order_by(Produto.nome_comercial, Lote.data_entrada).all(),
                           filtro=request.args, **_contexto_formularios())


@bp_estoque.route("/movimentacoes")
def movimentacoes():
    consulta = Movimentacao.query
    for campo in ("produto_id", "localizacao_id"):
        valor = request.args.get(campo, type=int)
        if valor:
            consulta = consulta.filter(getattr(Movimentacao, campo) == valor)
    tipo = request.args.get("tipo")
    if tipo:
        consulta = consulta.filter(Movimentacao.tipo == tipo)
    pagina = consulta.order_by(Movimentacao.data.desc(), Movimentacao.id.desc()).paginate(
        page=request.args.get("pagina", 1, type=int), per_page=50, error_out=False)
    ids = [m.id for m in pagina.items]
    estornadas = {origem for (origem,) in db.session.query(Movimentacao.origem_id).filter(
        Movimentacao.origem_id.in_(ids), Movimentacao.tipo.in_(Movimentacao.ESTORNOS))} if ids else set()
    return render_template("estoque/movimentacoes.html", pagina=pagina, filtro=request.args,
                           tipos=Movimentacao.TIPOS, estornadas=estornadas, estornaveis=Movimentacao.ESTORNAVEIS,
                           **_contexto_formularios())


@bp_estoque.route("/movimentacoes/<int:id>/estornar", methods=["GET", "POST"])
def estornar_movimentacao(id):
    """Desfaz uma movimentação, com a senha de um farmacêutico ou administrador."""
    mov = db.get_or_404(Movimentacao, id)
    impedimento = estoque.verificar_estorno(mov)
    partes = [mov]
    if not impedimento and mov.tipo == Movimentacao.TRANSFERENCIA:
        try:
            partes = sorted([mov, estoque.contraparte_transferencia(mov)], key=lambda m: m.quantidade)
        except EstoqueError as erro:
            impedimento = str(erro).rstrip(".").lower()
    if request.method == "POST" and not impedimento:
        try:
            autorizador = autorizar(request.form.get("autorizador", ""), request.form.get("senha", ""))
        except CredencialInvalida as erro:
            flash(f"Estorno não autorizado: {erro}", "danger")
            return render_template("estoque/estorno.html", mov=mov, partes=partes, impedimento=None,
                                   form=request.form), erro.status if erro.status != 200 else 422
        try:
            lancamentos = estoque.estornar(mov, request.form.get("motivo"), autorizador)
            db.session.commit()
            flash(f"Movimentação estornada: {len(lancamentos)} lançamento(s) inverso(s) registrado(s), "
                  f"autorizado(s) por {autorizador.login}.", "success")
            return redirect(url_for(".movimentacoes", produto_id=mov.produto_id))
        except EstoqueError as erro:
            db.session.rollback()
            flash(str(erro), "danger")
            mov = db.session.get(Movimentacao, id)
            partes = [db.session.get(Movimentacao, p.id) for p in partes]
    return render_template("estoque/estorno.html", mov=mov, partes=partes, impedimento=impedimento,
                           form=request.form if request.method == "POST" else None)


@bp_estoque.route("/inventario", methods=["GET", "POST"])
@perfil_requerido(Usuario.FARMACEUTICO)
def contagem():
    """Contagem física: ajusta os saldos dos lotes de um local."""
    localizacao = _obter(Localizacao, "localizacao_id", obrigatorio=False)
    if request.method == "POST" and localizacao:
        motivo = (request.form.get("motivo") or "Ajuste de inventário").strip()[:Movimentacao.motivo.type.length]
        ajustes = 0
        try:
            for lote in Lote.query.filter_by(localizacao_id=localizacao.id).filter(Lote.saldo > 0):
                bruto = request.form.get(f"contagem_{lote.id}", "").strip()
                if bruto == "":
                    continue
                try:
                    contado = decimal(bruto)
                except ValueError:
                    raise EstoqueError(f"Contagem inválida no lote {lote.numero_lote}.") from None
                if estoque.ajustar_inventario(lote, contado, motivo):
                    ajustes += 1
            db.session.commit()
            flash(f"Inventário de {localizacao} concluído: {ajustes} lote(s) ajustado(s).", "success")
            return redirect(url_for(".contagem", localizacao_id=localizacao.id))
        except EstoqueError as erro:
            db.session.rollback()
            flash(str(erro), "danger")
    lotes_local = []
    if localizacao:
        lotes_local = Lote.query.join(Produto).filter(Lote.localizacao_id == localizacao.id, Lote.saldo > 0) \
            .order_by(Produto.nome_comercial, Lote.data_entrada).all()
    return render_template("estoque/contagem.html", localizacao=localizacao, lotes=lotes_local,
                           **_contexto_formularios())


# --------------------------------------------------------------------------- relatórios

RELATORIOS = {
    "consumo_diario": ("Consumo diário", "periodo_local"),
    "resumo_dispensacao": ("Resumo de dispensação por data", "periodo"),
    "consumo_local": ("Consumo por local de dispensação", "periodo_local"),
    "consumo_paciente": ("Consumo por paciente", "periodo_paciente"),
    "pedido_compra": ("Estoque mínimo/máximo e pedido de compra", "historico"),
    "inventario": ("Inventário", "local"),
    "livro_controlados": ("Escrituração de controlados", "periodo_produto"),
}
# Relatórios restritos ao farmacêutico (contêm a escrituração regulatória de controlados).
RELATORIOS_FARMACEUTICO = ("livro_controlados",)


# Relatórios que identificam pacientes: podem ser gerados anonimizados e têm a exportação registrada.
RELATORIOS_COM_PACIENTES = ("resumo_dispensacao", "consumo_paciente", "livro_controlados")


def _anonimo():
    return request.args.get("anonimo") == "1"


def _gerar(chave):
    hoje = date.today()
    inicio = _data("inicio", hoje.replace(day=1))
    fim = _data("fim", hoje)
    if inicio > fim:
        raise EstoqueError("A data inicial deve ser anterior à final.")
    localizacao_id = request.args.get("localizacao_id", type=int)
    if chave == "consumo_diario":
        return relatorios.consumo_diario(inicio, fim, localizacao_id)
    if chave == "resumo_dispensacao":
        return relatorios.resumo_dispensacao(inicio, fim, anonimo=_anonimo())
    if chave == "consumo_local":
        return relatorios.consumo_por_local(inicio, fim, localizacao_id)
    if chave == "consumo_paciente":
        return relatorios.consumo_por_paciente(inicio, fim, request.args.get("paciente_id", type=int),
                                               anonimo=_anonimo())
    if chave == "livro_controlados":
        return relatorios.livro_controlados(inicio, fim, request.args.get("produto_id", type=int),
                                            request.args.get("lista") or None)
    if chave == "pedido_compra":
        dias = max(request.args.get("dias", 30, type=int), 1)
        return relatorios.pedido_compra(dias)
    return relatorios.inventario(localizacao_id)


def _csv(titulo, tabelas):
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow([f"ExataMed — {titulo}", f"Gerado em {datetime.now():%d/%m/%Y %H:%M}"])
    for tabela in tabelas:
        escritor.writerow([])
        escritor.writerow([tabela.titulo])
        escritor.writerow([c.titulo for c in tabela.colunas])
        for linha in tabela.linhas + ([tabela.rodape] if tabela.rodape else []):
            escritor.writerow([
                (formatar(v) if isinstance(v, (float, Decimal))
                 else v.strftime("%d/%m/%Y") if isinstance(v, date) else v)
                for v in linha
            ])
    nome = titulo.lower().replace(" ", "_").replace("/", "-")
    # BOM para o Excel reconhecer UTF-8.
    return Response("﻿" + saida.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=exatamed_{nome}.csv"})


@bp_relatorios.route("/")
def indice():
    return render_template("relatorios/indice.html", relatorios=RELATORIOS)


@bp_relatorios.route("/<chave>")
def exibir(chave):
    if chave not in RELATORIOS:
        return redirect(url_for(".indice"))
    titulo, filtros = RELATORIOS[chave]
    if chave in RELATORIOS_FARMACEUTICO and not current_user.pode(Usuario.FARMACEUTICO):
        abort(403)
    try:
        tabelas = _gerar(chave)
    except EstoqueError as erro:
        flash(str(erro), "danger")
        tabelas = []
    if request.args.get("formato") == "csv":
        if chave in RELATORIOS_COM_PACIENTES and not _anonimo():
            registrar_acesso(RegistroAcesso.EXPORTAR, "relatorio", None,
                             f"{titulo} ({request.args.get('inicio', '')} a {request.args.get('fim', '')})")
        return _csv(titulo, tabelas)
    hoje = date.today()
    contexto = _contexto_formularios()
    if filtros == "periodo_paciente":
        contexto["pacientes"] = Paciente.query.filter(Paciente.anonimizado_em.is_(None)).order_by(Paciente.nome).all()
    return render_template("relatorios/relatorio.html", chave=chave, titulo=titulo, filtros=filtros,
                           tabelas=tabelas, args=request.args, listas_controle=LISTAS_CONTROLE[1:],
                           inicio_padrao=hoje.replace(day=1), fim_padrao=hoje, **contexto)


# Atalhos com nomes estáveis (usados por links dos cadastros).
@bp_relatorios.route("/paciente")
def consumo_paciente():
    args = request.args.to_dict()
    args.setdefault("inicio", (date.today() - timedelta(days=365)).isoformat())
    return redirect(url_for(".exibir", chave="consumo_paciente", **args))


# --------------------------------------------------------------------------- dashboard de gestão

@bp_dashboard.route("/", endpoint="indice")
def painel_de_gestao():
    hoje = date.today()
    granularidade = request.args.get("granularidade", "mes")
    if granularidade not in dashboard.GRANULARIDADES:
        granularidade = "mes"
    padrao_inicio, padrao_fim = dashboard.periodo_padrao(granularidade, hoje)
    try:
        inicio, fim = _data("inicio", padrao_inicio), _data("fim", padrao_fim)
        if inicio > fim:
            raise EstoqueError("A data inicial deve ser anterior à final.")
        if granularidade == "dia" and (fim - inicio).days > 366:
            raise EstoqueError("Para ver por dia, escolha um período de até um ano (ou agrupe por mês).")
    except EstoqueError as erro:
        flash(str(erro), "warning")
        inicio, fim = padrao_inicio, padrao_fim
    medico_id = request.args.get("medico_id", type=int)
    localizacao_id = request.args.get("localizacao_id", type=int)
    tipo = request.args.get("tipo") if request.args.get("tipo") in Produto.TIPOS else None
    custo = dashboard.evolucao_custo(inicio, fim, granularidade, medico_id, localizacao_id)
    abc = dashboard.curva_abc(inicio, fim, tipo)
    contexto = _contexto_formularios()
    contexto["medicos"] = Medico.query.order_by(Medico.nome).all()
    return render_template(
        "dashboard/indice.html", filtro=request.args, granularidade=granularidade, inicio=inicio, fim=fim,
        granularidades=dashboard.GRANULARIDADES, tipos=Produto.TIPOS, tipo=tipo,
        medico=db.session.get(Medico, medico_id) if medico_id else None,
        local=db.session.get(Localizacao, localizacao_id) if localizacao_id else None,
        custo=custo, grafico_custo=graficos.barras(custo["pontos"]),
        abc=abc, grafico_abc=graficos.curva_abc(abc["itens"]) if abc["itens"] else None,
        vencimentos=dashboard.vencimentos(hoje), ruptura=dashboard.ruptura(hoje),
        seguranca=dashboard.estoque_seguranca(hoje), giro=dashboard.giro_estoque(inicio, fim),
        devolucoes=dashboard.devolucoes_avarias(inicio, fim), **contexto)
