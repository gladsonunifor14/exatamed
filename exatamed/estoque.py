"""Regras de negócio de estoque: entradas, baixas PEPS, transferências,
dispensação e ajustes de inventário."""

import re
import unicodedata
from datetime import date, datetime

from .models import Dispensacao, Lote, Movimentacao, db
from .numeros import ZERO, decimal, formatar


class EstoqueError(ValueError):
    """Operação de estoque inválida (saldo insuficiente, dados inconsistentes...)."""


def _quantidade(valor, rotulo="A quantidade"):
    try:
        return decimal(valor)
    except ValueError:
        raise EstoqueError(f"{rotulo} é inválida.") from None


def _debitar_lote(lote, quantidade):
    """Debita o saldo no próprio banco, de forma atômica.

    O UPDATE só acontece se o saldo ainda cobrir a quantidade: se outra operação
    consumiu o lote no meio do caminho, nada é gravado e a operação é recusada,
    em vez de deixar o estoque negativo.
    """
    resultado = db.session.execute(
        db.update(Lote).where(Lote.id == lote.id, Lote.saldo >= quantidade)
        .values(saldo=Lote.saldo - quantidade).execution_options(synchronize_session=False))
    if resultado.rowcount != 1:
        raise EstoqueError(f"O saldo do lote {lote.numero_lote} mudou durante a operação "
                           "(outra movimentação simultânea). Confira e tente novamente.")
    db.session.expire(lote, ["saldo"])


def _creditar_lote(lote, quantidade):
    db.session.execute(
        db.update(Lote).where(Lote.id == lote.id).values(saldo=Lote.saldo + quantidade)
        .execution_options(synchronize_session=False))
    db.session.expire(lote, ["saldo"])


def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def _termos(texto):
    return {t.strip() for t in re.split(r"[,;\n/]+", _normalizar(texto)) if len(t.strip()) >= 3}


def verificar_alergias(paciente, produto):
    """Retorna os termos de alergia do paciente que conflitam com o produto."""
    alergias = _termos(paciente.alergias)
    if not alergias:
        return []
    texto_produto = _normalizar(" ".join(
        filter(None, (produto.nome_comercial, produto.principio_ativo, produto.alertas_alergia))
    ))
    alertas_produto = _termos(produto.alertas_alergia)
    conflitos = set()
    for alergia in alergias:
        if alergia in texto_produto or any(alerta in alergia for alerta in alertas_produto):
            conflitos.add(alergia)
    return sorted(conflitos)


def saldo(produto_id, localizacao_id=None):
    consulta = db.session.query(db.func.coalesce(db.func.sum(Lote.saldo), 0)).filter(
        Lote.produto_id == produto_id
    )
    if localizacao_id:
        consulta = consulta.filter(Lote.localizacao_id == localizacao_id)
    return consulta.scalar()


def lotes_peps(produto_id, localizacao_id, incluir_vencidos=False, travar=False):
    """Lotes com saldo na ordem PEPS (primeiro que entra, primeiro que sai).

    Com `travar`, as linhas ficam bloqueadas (SELECT ... FOR UPDATE no PostgreSQL)
    até o fim da transação, serializando baixas simultâneas do mesmo produto.
    """
    consulta = Lote.query.filter(
        Lote.produto_id == produto_id,
        Lote.localizacao_id == localizacao_id,
        Lote.saldo > 0,
        Lote.bloqueado.is_(False),
    )
    if not incluir_vencidos:
        consulta = consulta.filter(Lote.validade >= date.today())
    if travar:
        consulta = consulta.with_for_update()
    return consulta.order_by(Lote.data_entrada, Lote.id).all()


def registrar_entrada(produto, localizacao, numero_lote, validade, quantidade, custo_unitario,
                      documento=None, data=None):
    quantidade = _quantidade(quantidade)
    custo_unitario = _quantidade(custo_unitario, "O custo unitário")
    if quantidade <= 0:
        raise EstoqueError("A quantidade de entrada deve ser maior que zero.")
    if custo_unitario < 0:
        raise EstoqueError("O custo unitário não pode ser negativo.")
    if not numero_lote:
        raise EstoqueError("Informe o número do lote.")
    data = data or datetime.now()
    lote = Lote(
        produto=produto,
        localizacao=localizacao,
        numero_lote=numero_lote.strip(),
        validade=validade,
        data_entrada=data,
        custo_unitario=custo_unitario,
        quantidade_inicial=quantidade,
        saldo=quantidade,
    )
    db.session.add(lote)
    db.session.add(Movimentacao(
        tipo=Movimentacao.ENTRADA,
        data=data,
        produto=produto,
        lote=lote,
        localizacao=localizacao,
        quantidade=quantidade,
        custo_unitario=custo_unitario,
        documento=documento,
    ))
    return lote


def baixar_peps(produto, localizacao, quantidade, tipo, data=None, destino=None,
                dispensacao=None, documento=None, motivo=None):
    """Baixa `quantidade` do estoque consumindo os lotes mais antigos primeiro.

    Lotes vencidos nunca são consumidos. Retorna as movimentações geradas
    (uma por lote consumido), cada uma com o custo do seu lote.
    """
    quantidade = _quantidade(quantidade)
    if quantidade <= 0:
        raise EstoqueError("A quantidade deve ser maior que zero.")
    lotes = lotes_peps(produto.id, localizacao.id, travar=True)
    disponivel = sum((l.saldo for l in lotes), ZERO)
    if disponivel < quantidade:
        raise EstoqueError(
            f"Saldo insuficiente de '{produto}' em {localizacao}: "
            f"disponível {formatar(disponivel)} {produto.unidade_medida} (não vencido nem bloqueado), "
            f"solicitado {formatar(quantidade)}."
        )
    data = data or datetime.now()
    restante = quantidade
    movimentacoes = []
    for lote in lotes:
        if restante <= 0:
            break
        consumo = min(lote.saldo, restante)
        _debitar_lote(lote, consumo)
        restante -= consumo
        mov = Movimentacao(
            tipo=tipo,
            data=data,
            produto=produto,
            lote=lote,
            localizacao=localizacao,
            destino=destino,
            quantidade=-consumo,
            custo_unitario=lote.custo_unitario,
            dispensacao=dispensacao,
            documento=documento,
            motivo=motivo,
        )
        db.session.add(mov)
        movimentacoes.append(mov)
    return movimentacoes


def registrar_saida(produto, localizacao, quantidade, motivo, documento=None, data=None):
    """Saída avulsa (consumo de setor, perda, avaria, devolução ao fornecedor...)."""
    if not motivo:
        raise EstoqueError("Informe o motivo da saída.")
    return baixar_peps(produto, localizacao, quantidade, Movimentacao.SAIDA, data=data,
                       documento=documento, motivo=motivo)


def transferir(produto, origem, destino, quantidade, documento=None, data=None):
    """Move estoque entre locais preservando lote, validade, custo e ordem PEPS."""
    if origem.id == destino.id:
        raise EstoqueError("Origem e destino devem ser diferentes.")
    data = data or datetime.now()
    movimentacoes = baixar_peps(produto, origem, quantidade, Movimentacao.TRANSFERENCIA,
                                data=data, destino=destino, documento=documento)
    for mov in movimentacoes:
        origem_lote = mov.lote
        novo = Lote(
            produto=produto,
            localizacao=destino,
            numero_lote=origem_lote.numero_lote,
            validade=origem_lote.validade,
            data_entrada=origem_lote.data_entrada,
            custo_unitario=origem_lote.custo_unitario,
            quantidade_inicial=-mov.quantidade,
            saldo=-mov.quantidade,
        )
        db.session.add(novo)
        db.session.add(Movimentacao(
            tipo=Movimentacao.TRANSFERENCIA,
            data=data,
            produto=produto,
            lote=novo,
            localizacao=destino,
            quantidade=-mov.quantidade,
            custo_unitario=origem_lote.custo_unitario,
            documento=documento,
            motivo=f"Recebido de {origem}",
        ))
    return movimentacoes


def dispensar(paciente, origem, destino, itens, medico=None, prescricao=None,
              observacao=None, responsavel=None, confirmar_alergia=False, data=None):
    """Dispensa itens [(produto, quantidade), ...] para um paciente.

    - Produtos de controle especial exigem médico prescritor e nº de prescrição.
    - Conflitos com alergias do paciente bloqueiam a operação, a menos que
      `confirmar_alergia` seja verdadeiro (ciência do farmacêutico).
    """
    if not itens:
        raise EstoqueError("Inclua ao menos um item na dispensação.")
    if not origem.principal:
        raise EstoqueError("A dispensação só pode sair da Farmácia SUS ou da Farmácia Particular.")
    if origem.id == destino.id:
        raise EstoqueError("O local de dispensação deve ser diferente da farmácia de origem.")
    conflitos = {}
    for produto, _ in itens:
        if produto.controlado and (not medico or not prescricao):
            raise EstoqueError(
                f"'{produto}' é de controle especial (lista {produto.controle_especial}): "
                "informe o médico prescritor e o número da prescrição."
            )
        achados = verificar_alergias(paciente, produto)
        if achados:
            conflitos[str(produto)] = achados
    itens = [(produto, _quantidade(quantidade, f"A quantidade de '{produto}'")) for produto, quantidade in itens]
    necessidade = {}
    for produto, quantidade in itens:
        if quantidade <= 0:
            raise EstoqueError(f"A quantidade de '{produto}' deve ser maior que zero.")
        necessidade[produto] = necessidade.get(produto, ZERO) + quantidade
    for produto, quantidade in necessidade.items():
        disponivel = sum((l.saldo for l in lotes_peps(produto.id, origem.id)), ZERO)
        if disponivel < quantidade:
            raise EstoqueError(
                f"Saldo insuficiente de '{produto}' em {origem}: disponível {formatar(disponivel)} "
                f"{produto.unidade_medida} (não vencido nem bloqueado), solicitado {formatar(quantidade)}."
            )
    if conflitos and not confirmar_alergia:
        detalhes = "; ".join(f"{p}: {', '.join(a)}" for p, a in conflitos.items())
        raise EstoqueError(f"ALERTA DE ALERGIA para {paciente.nome} — {detalhes}. "
                           "Confirme a ciência do alerta para prosseguir.")

    data = data or datetime.now()
    alerta = ""
    if conflitos:
        alerta = "Dispensado ciente de alerta de alergia. "
    dispensacao = Dispensacao(
        ano=data.year,
        numero=Dispensacao.proximo_numero(data.year),
        data=data,
        paciente=paciente,
        medico=medico,
        origem=origem,
        destino=destino,
        prescricao=prescricao,
        observacao=(alerta + (observacao or "")).strip() or None,
        responsavel=responsavel,
    )
    db.session.add(dispensacao)
    for produto, quantidade in itens:
        baixar_peps(produto, origem, quantidade, Movimentacao.DISPENSACAO, data=data,
                    destino=destino, dispensacao=dispensacao, documento=prescricao)
    return dispensacao


def ajustar_inventario(lote, quantidade_contada, motivo, data=None):
    """Ajusta o saldo de um lote para a quantidade contada fisicamente."""
    quantidade_contada = _quantidade(quantidade_contada, "A quantidade contada")
    if quantidade_contada < 0:
        raise EstoqueError("A quantidade contada não pode ser negativa.")
    # Trava o lote e relê o saldo atual antes de calcular a diferença.
    db.session.flush()
    lote = Lote.query.filter_by(id=lote.id).with_for_update().populate_existing().one()
    diferenca = quantidade_contada - lote.saldo
    if diferenca == 0:
        return None
    if diferenca < 0:
        _debitar_lote(lote, -diferenca)
    else:
        _creditar_lote(lote, diferenca)
    mov = Movimentacao(
        tipo=Movimentacao.AJUSTE,
        data=data or datetime.now(),
        produto=lote.produto,
        lote=lote,
        localizacao=lote.localizacao,
        quantidade=diferenca,
        custo_unitario=lote.custo_unitario,
        motivo=motivo or "Ajuste de inventário",
    )
    db.session.add(mov)
    return mov


def devolver(dispensacao, quantidades, motivo, data=None):
    """Registra a devolução (estorno) de itens de uma dispensação.

    `quantidades` mapeia o id da movimentação de dispensação para a quantidade devolvida.
    Nada é apagado: cada devolução é uma movimentação nova (ESTORNO), positiva, que
    volta ao mesmo lote e com o mesmo custo da saída original.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise EstoqueError("Informe o motivo da devolução.")
    itens = {m.id: m for m in dispensacao.itens_dispensados}
    devolucoes = []
    data = data or datetime.now()
    for mov_id, quantidade in quantidades.items():
        original = itens.get(mov_id)
        if original is None:
            raise EstoqueError("Item não pertence a esta dispensação.")
        quantidade = _quantidade(quantidade, f"A quantidade devolvida de '{original.produto}'")
        if quantidade == 0:
            continue
        if quantidade < 0:
            raise EstoqueError("A quantidade devolvida não pode ser negativa.")
        if quantidade > original.quantidade_a_devolver:
            raise EstoqueError(
                f"'{original.produto}', lote {original.lote.numero_lote}: só é possível devolver "
                f"{formatar(original.quantidade_a_devolver)} {original.produto.unidade_medida}.")
        _creditar_lote(original.lote, quantidade)
        devolucao = Movimentacao(
            tipo=Movimentacao.ESTORNO, data=data, produto=original.produto, lote=original.lote,
            localizacao=original.localizacao, destino=dispensacao.destino, quantidade=quantidade,
            custo_unitario=original.custo_unitario, dispensacao=dispensacao, origem=original,
            documento=f"Dispensação {dispensacao.numero_formatado}", motivo=motivo[:200],
        )
        db.session.add(devolucao)
        devolucoes.append(devolucao)
    if not devolucoes:
        raise EstoqueError("Informe a quantidade devolvida de ao menos um item.")
    return devolucoes


def bloquear_lote(produto, numero_lote, motivo):
    """Bloqueia o lote em todos os locais (recall, interdição, quarentena)."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise EstoqueError("Informe o motivo do bloqueio (ex.: recall do fabricante, alerta ANVISA nº ...).")
    lotes = Lote.query.filter_by(produto_id=produto.id, numero_lote=numero_lote, bloqueado=False).all()
    if not lotes:
        raise EstoqueError("Lote não encontrado ou já bloqueado.")
    agora = datetime.now()
    for lote in lotes:
        lote.bloqueado, lote.motivo_bloqueio, lote.bloqueado_em = True, motivo[:200], agora
    return lotes


def desbloquear_lote(produto, numero_lote, motivo):
    motivo = (motivo or "").strip()
    if not motivo:
        raise EstoqueError("Informe o motivo do desbloqueio (ex.: laudo de liberação nº ...).")
    lotes = Lote.query.filter_by(produto_id=produto.id, numero_lote=numero_lote, bloqueado=True).all()
    if not lotes:
        raise EstoqueError("Lote não encontrado ou não está bloqueado.")
    for lote in lotes:
        lote.bloqueado, lote.bloqueado_em = False, None
        lote.motivo_bloqueio = f"Desbloqueado: {motivo}"[:200]
    return lotes
