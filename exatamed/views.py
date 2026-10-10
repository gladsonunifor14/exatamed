"""Telas de estoque, dispensação e relatórios."""

import csv
import io
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from . import estoque, relatorios
from .ajuda import primeiros_passos
from .lgpd import registrar_acesso
from .auth import perfil_requerido
from .estoque import EstoqueError
from .models import (Dispensacao, Localizacao, Lote, Medico, Movimentacao, Paciente, Produto, RegistroAcesso,
                     Usuario, db)

principal = Blueprint("principal", __name__)
bp_estoque = Blueprint("estoque", __name__, url_prefix="/estoque")
bp_relatorios = Blueprint("relatorios", __name__, url_prefix="/relatorios")


def _data(nome, padrao=None):
    valor = request.values.get(nome)
    if not valor:
        return padrao
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        raise EstoqueError(f"Data inválida: {valor}")


def _numero(nome):
    try:
        return float((request.form.get(nome) or "").replace(",", "."))
    except ValueError:
        raise EstoqueError("Informe uma quantidade numérica válida.")


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
        # Cadastros anonimizados não recebem novas dispensações.
        "pacientes": Paciente.query.filter(Paciente.anonimizado_em.is_(None)).order_by(Paciente.nome).all(),
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
    consumo_hoje = sum(m.custo_total for m in Movimentacao.query.filter(
        Movimentacao.tipo.in_(Movimentacao.CONSUMO), Movimentacao.data >= inicio))
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
                     "estoque/saida.html")


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
            quantidade = float(qtd.replace(",", "."))
        except ValueError:
            raise EstoqueError(f"Quantidade inválida para {produto}.")
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
    )


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
                        raise EstoqueError("Não foi possível numerar a dispensação. Tente novamente.")
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
    return render_template("estoque/dispensacao.html", alerta=alerta, form=request.form, **contexto)


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
            "saldos": {str(l.id): estoque.saldo(produto.id, l.id) for l in Localizacao.query.all()}}


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
    return render_template("estoque/movimentacoes.html", pagina=pagina, filtro=request.args,
                           tipos=Movimentacao.TIPOS, **_contexto_formularios())


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
                    contado = float(bruto.replace(",", "."))
                except ValueError:
                    raise EstoqueError(f"Contagem inválida no lote {lote.numero_lote}.")
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
}


# Relatórios que identificam pacientes: podem ser gerados anonimizados e têm a exportação registrada.
RELATORIOS_COM_PACIENTES = ("resumo_dispensacao", "consumo_paciente")


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
                (f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",") if isinstance(v, float)
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
    return render_template("relatorios/relatorio.html", chave=chave, titulo=titulo, filtros=filtros,
                           tabelas=tabelas, args=request.args,
                           inicio_padrao=hoje.replace(day=1), fim_padrao=hoje,
                           **_contexto_formularios())


# Atalhos com nomes estáveis (usados por links dos cadastros).
@bp_relatorios.route("/paciente")
def consumo_paciente():
    args = request.args.to_dict()
    args.setdefault("inicio", (date.today() - timedelta(days=365)).isoformat())
    return redirect(url_for(".exibir", chave="consumo_paciente", **args))
