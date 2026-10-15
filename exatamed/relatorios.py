"""Análises e relatórios gerenciais.

Cada relatório retorna uma lista de `Tabela`, renderizada de forma genérica
em HTML e exportável em CSV.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .models import Dispensacao, Lote, Movimentacao, Produto, db
from .numeros import ZERO, decimal

# Dispensações e suas devoluções (o consumo por local e por paciente é líquido).
DISPENSACAO_LIQUIDA = (Movimentacao.DISPENSACAO, Movimentacao.ESTORNO)


@dataclass
class Coluna:
    titulo: str
    formato: str = "texto"  # texto | numero | moeda | data


@dataclass
class Tabela:
    titulo: str
    colunas: list
    linhas: list = field(default_factory=list)
    rodape: list = None
    destaques: dict = field(default_factory=dict)  # índice da linha -> classe CSS


def _periodo(inicio, fim):
    return datetime.combine(inicio, time.min), datetime.combine(fim, time.max)


def _movimentos_consumo(inicio, fim, tipos=Movimentacao.CONSUMO, localizacao_id=None):
    ini, fim_ = _periodo(inicio, fim)
    consulta = Movimentacao.query.filter(
        Movimentacao.tipo.in_(tipos), Movimentacao.data.between(ini, fim_)
    )
    if localizacao_id:
        consulta = consulta.filter(Movimentacao.localizacao_id == localizacao_id)
    return consulta.order_by(Movimentacao.data).all()


def _agrupar_por_produto(movimentos):
    grupos = defaultdict(lambda: [ZERO, ZERO])
    produtos = {}
    for m in movimentos:
        produtos[m.produto_id] = m.produto
        grupos[m.produto_id][0] += m.consumo_quantidade
        grupos[m.produto_id][1] += m.consumo_custo
    linhas = [
        [str(produtos[pid]), produtos[pid].principio_ativo or "", produtos[pid].unidade_medida, qtd, custo]
        for pid, (qtd, custo) in grupos.items()
    ]
    return sorted(linhas, key=lambda l: -l[4])


COLUNAS_PRODUTO = [
    Coluna("Produto"), Coluna("Princípio ativo (DCB)"), Coluna("Unidade"),
    Coluna("Quantidade", "numero"), Coluna("Custo PEPS", "moeda"),
]


def consumo_diario(inicio, fim, localizacao_id=None):
    movimentos = _movimentos_consumo(inicio, fim, localizacao_id=localizacao_id)
    por_dia = defaultdict(lambda: {"mov": 0, "produtos": set(), "disp": ZERO, "saida": ZERO})
    for m in movimentos:
        d = por_dia[m.data.date()]
        d["mov"] += 1
        d["produtos"].add(m.produto_id)
        d["saida" if m.tipo in (Movimentacao.SAIDA, Movimentacao.ESTORNO_SAIDA) else "disp"] += m.consumo_custo
    dias = Tabela("Consumo por dia", [
        Coluna("Data", "data"), Coluna("Movimentações", "numero"), Coluna("Itens distintos", "numero"),
        Coluna("Custo dispensações", "moeda"), Coluna("Custo saídas avulsas", "moeda"),
        Coluna("Custo total", "moeda"),
    ])
    for dia in sorted(por_dia):
        d = por_dia[dia]
        dias.linhas.append([dia, d["mov"], len(d["produtos"]), d["disp"], d["saida"], d["disp"] + d["saida"]])
    total_disp = sum(l[3] for l in dias.linhas)
    total_saida = sum(l[4] for l in dias.linhas)
    dias.rodape = ["Total", sum(l[1] for l in dias.linhas), "", total_disp, total_saida, total_disp + total_saida]
    n_dias = (fim - inicio).days + 1
    produtos = Tabela(f"Consumo por produto no período (média diária sobre {n_dias} dia(s))",
                      COLUNAS_PRODUTO + [Coluna("Média diária", "numero")])
    for linha in _agrupar_por_produto(movimentos):
        produtos.linhas.append(linha + [linha[3] / n_dias])
    return [dias, produtos]


def _identificacao(paciente, anonimo):
    """Nome do paciente ou, em relatórios anonimizados, um código sem dados pessoais."""
    return paciente.pseudonimo if anonimo else paciente.nome


def resumo_dispensacao(inicio, fim, anonimo=False):
    ini, fim_ = _periodo(inicio, fim)
    dispensacoes = Dispensacao.query.filter(Dispensacao.data.between(ini, fim_)) \
        .order_by(Dispensacao.data).all()
    por_data = defaultdict(lambda: {"n": 0, "pacientes": set(), "itens": 0, "custo": ZERO})
    detalhe = Tabela("Dispensações do período", [
        Coluna("Nº"), Coluna("Data/hora"), Coluna("Paciente"), Coluna("Médico"),
        Coluna("Origem"), Coluna("Local de dispensação"), Coluna("Prescrição"),
        Coluna("Itens", "numero"), Coluna("Custo PEPS", "moeda"),
    ])
    for d in dispensacoes:
        produtos = {m.produto_id for m in d.movimentacoes}
        g = por_data[d.data.date()]
        g["n"] += 1
        g["pacientes"].add(d.paciente_id)
        g["itens"] += len(produtos)
        g["custo"] += d.custo_total
        detalhe.linhas.append([
            d.numero_formatado, d.data.strftime("%d/%m/%Y %H:%M"), _identificacao(d.paciente, anonimo),
            d.medico.nome if d.medico else "", d.origem.nome, d.destino.nome,
            d.prescricao or "", len(produtos), d.custo_total,
        ])
    resumo = Tabela("Resumo por data", [
        Coluna("Data", "data"), Coluna("Dispensações", "numero"), Coluna("Pacientes atendidos", "numero"),
        Coluna("Itens dispensados", "numero"), Coluna("Custo PEPS", "moeda"),
    ])
    for dia in sorted(por_data):
        g = por_data[dia]
        resumo.linhas.append([dia, g["n"], len(g["pacientes"]), g["itens"], g["custo"]])
    resumo.rodape = ["Total", len(dispensacoes), len({d.paciente_id for d in dispensacoes}),
                     sum(l[3] for l in resumo.linhas), sum(l[4] for l in resumo.linhas)]
    return [resumo, detalhe]


def consumo_por_local(inicio, fim, localizacao_id=None):
    movimentos = _movimentos_consumo(inicio, fim, tipos=DISPENSACAO_LIQUIDA)
    if localizacao_id:
        movimentos = [m for m in movimentos if m.destino_id == localizacao_id]
    por_local = defaultdict(list)
    for m in movimentos:
        por_local[m.destino.nome if m.destino else "(não informado)"].append(m)
    resumo = Tabela("Consumo por local de dispensação", [
        Coluna("Local"), Coluna("Dispensações", "numero"), Coluna("Pacientes", "numero"),
        Coluna("Itens distintos", "numero"), Coluna("Custo PEPS", "moeda"), Coluna("% do custo", "numero"),
    ])
    total = sum((m.consumo_custo for m in movimentos), ZERO) or 1
    tabelas = [resumo]
    for local, movs in sorted(por_local.items(), key=lambda kv: -sum((m.consumo_custo for m in kv[1]), ZERO)):
        custo = sum((m.consumo_custo for m in movs), ZERO)
        resumo.linhas.append([
            local, len({m.dispensacao_id for m in movs}),
            len({m.dispensacao.paciente_id for m in movs}),
            len({m.produto_id for m in movs}), custo, round(100 * custo / total, 2),
        ])
        tabelas.append(Tabela(f"Detalhe — {local}", COLUNAS_PRODUTO, _agrupar_por_produto(movs)))
    resumo.rodape = ["Total", sum(l[1] for l in resumo.linhas), "", "",
                     sum(l[4] for l in resumo.linhas), 100 if resumo.linhas else 0]
    return tabelas


def consumo_por_paciente(inicio, fim, paciente_id=None, anonimo=False):
    """CPF e Cartão SUS saem mascarados; com `anonimo`, o paciente vira um código (P-000123)."""
    movimentos = _movimentos_consumo(inicio, fim, tipos=DISPENSACAO_LIQUIDA)
    if paciente_id:
        movimentos = [m for m in movimentos if m.dispensacao.paciente_id == paciente_id]
    por_paciente = defaultdict(list)
    for m in movimentos:
        por_paciente[m.dispensacao.paciente].append(m)
    resumo = Tabela("Consumo por paciente", [
        Coluna("Paciente"), Coluna("CPF"), Coluna("Cartão SUS"), Coluna("Plano de saúde"),
        Coluna("Dispensações", "numero"), Coluna("Itens distintos", "numero"), Coluna("Custo PEPS", "moeda"),
    ])
    tabelas = [resumo]
    ordem = (lambda kv: kv[0].id) if anonimo else (lambda kv: kv[0].nome)
    for paciente, movs in sorted(por_paciente.items(), key=ordem):
        resumo.linhas.append([
            _identificacao(paciente, anonimo),
            "" if anonimo else paciente.cpf_mascarado,
            "" if anonimo else paciente.cartao_sus_mascarado,
            paciente.plano_saude or "SUS",
            len({m.dispensacao_id for m in movs}), len({m.produto_id for m in movs}),
            sum((m.consumo_custo for m in movs), ZERO),
        ])
        if paciente_id:
            tabelas.append(Tabela(f"Itens consumidos — {_identificacao(paciente, anonimo)}", COLUNAS_PRODUTO,
                                  _agrupar_por_produto(movs)))
    resumo.rodape = ["Total", "", "", "", sum(l[4] for l in resumo.linhas), "",
                     sum(l[6] for l in resumo.linhas)]
    return tabelas


def calcular_pedido_compra(dias_historico=30, hoje=None):
    """Compara o saldo utilizável de cada produto com seus estoques mínimo e
    máximo e sugere a quantidade de compra.

    - Saldo utilizável: soma dos lotes não vencidos e não bloqueados em todos os locais.
    - Consumo médio diário (CMD): consumo dos últimos `dias_historico` dias / dias.
    - Sugestão de compra: quando saldo <= mínimo, comprar (máximo - saldo).
    - Custo estimado: sugestão x custo unitário da entrada mais recente.
    """
    hoje = hoje or date.today()
    inicio = hoje - timedelta(days=dias_historico - 1)
    consumo = defaultdict(lambda: ZERO)
    for m in _movimentos_consumo(inicio, hoje):
        consumo[m.produto_id] += m.consumo_quantidade
    saldos = dict(
        db.session.query(Lote.produto_id, db.func.sum(Lote.saldo))
        .filter(Lote.validade >= hoje, Lote.bloqueado.is_(False)).group_by(Lote.produto_id).all()
    )
    resultado = []
    for p in Produto.query.filter_by(ativo=True).order_by(Produto.nome_comercial).all():
        saldo = saldos.get(p.id, 0) or 0
        cmd = consumo[p.id] / dias_historico
        if saldo <= p.estoque_minimo:
            situacao = "Abaixo do mínimo" if saldo < p.estoque_minimo else "No ponto de pedido"
            sugestao = max(p.estoque_maximo - saldo, 0)
        elif p.estoque_maximo and saldo > p.estoque_maximo:
            situacao, sugestao = "Acima do máximo", 0
        else:
            situacao, sugestao = "Adequado", 0
        ultima_entrada = Lote.query.filter_by(produto_id=p.id).order_by(Lote.data_entrada.desc()).first()
        custo_ref = ultima_entrada.custo_unitario if ultima_entrada else 0
        resultado.append({
            "produto": p, "saldo": saldo, "cmd": cmd,
            "cobertura": (saldo / cmd) if cmd else None,
            "situacao": situacao, "sugestao": sugestao,
            "custo_ref": custo_ref, "custo_estimado": sugestao * custo_ref,
        })
    return resultado


def pedido_compra(dias_historico=30):
    dados = calcular_pedido_compra(dias_historico)
    tabela = Tabela(f"Estoque mínimo/máximo e pedido de compra (CMD sobre {dias_historico} dias)", [
        Coluna("Produto"), Coluna("Unidade"), Coluna("Saldo utilizável", "numero"),
        Coluna("Mínimo", "numero"), Coluna("Máximo", "numero"), Coluna("Consumo médio diário", "numero"),
        Coluna("Cobertura (dias)", "numero"), Coluna("Situação"), Coluna("Sugestão de compra", "numero"),
        Coluna("Último custo", "moeda"), Coluna("Custo estimado", "moeda"),
    ])
    classes = {"Abaixo do mínimo": "table-danger", "No ponto de pedido": "table-warning",
               "Acima do máximo": "table-info"}
    for i, d in enumerate(dados):
        p = d["produto"]
        tabela.linhas.append([
            str(p), p.unidade_medida, d["saldo"], p.estoque_minimo, p.estoque_maximo, d["cmd"],
            d["cobertura"] if d["cobertura"] is not None else "—", d["situacao"], d["sugestao"],
            d["custo_ref"], d["custo_estimado"],
        ])
        if d["situacao"] in classes:
            tabela.destaques[i] = classes[d["situacao"]]
    tabela.rodape = ["Total do pedido"] + [""] * 9 + [sum(d["custo_estimado"] for d in dados)]
    return [tabela]


def inventario(localizacao_id=None, dias_alerta_validade=90):
    consulta = Lote.query.filter(Lote.saldo > 0)
    if localizacao_id:
        consulta = consulta.filter(Lote.localizacao_id == localizacao_id)
    lotes = consulta.join(Produto).order_by(Produto.nome_comercial, Lote.data_entrada).all()
    detalhe = Tabela("Inventário por lote (valorizado pelo custo PEPS de cada camada)", [
        Coluna("Produto"), Coluna("Controle especial"), Coluna("Local"), Coluna("Lote"),
        Coluna("Validade", "data"), Coluna("Entrada", "data"), Coluna("Unidade"),
        Coluna("Saldo", "numero"), Coluna("Custo unitário", "moeda"), Coluna("Valor", "moeda"),
        Coluna("Situação"),
    ])
    por_produto = defaultdict(lambda: [ZERO, ZERO])
    produtos = {}
    hoje = date.today()
    for i, l in enumerate(lotes):
        valor = l.saldo * l.custo_unitario
        detalhe.linhas.append([
            str(l.produto), l.produto.controle_especial or "", l.localizacao.nome, l.numero_lote,
            l.validade, l.data_entrada.date(), l.produto.unidade_medida, l.saldo, l.custo_unitario, valor,
            f"Bloqueado: {l.motivo_bloqueio}" if l.bloqueado else ("Vencido" if l.validade < hoje else ""),
        ])
        if l.bloqueado or l.validade < hoje:
            detalhe.destaques[i] = "table-danger"
        elif (l.validade - hoje).days <= dias_alerta_validade:
            detalhe.destaques[i] = "table-warning"
        produtos[l.produto_id] = l.produto
        por_produto[l.produto_id][0] += l.saldo
        por_produto[l.produto_id][1] += valor
    detalhe.rodape = ["Total"] + [""] * 8 + [sum(l[9] for l in detalhe.linhas), ""]
    resumo = Tabela("Resumo por produto", [
        Coluna("Produto"), Coluna("Unidade"), Coluna("Saldo", "numero"),
        Coluna("Custo médio das camadas", "moeda"), Coluna("Valor PEPS", "moeda"),
    ])
    for pid, (qtd, valor) in sorted(por_produto.items(), key=lambda kv: str(produtos[kv[0]])):
        resumo.linhas.append([str(produtos[pid]), produtos[pid].unidade_medida, qtd,
                              valor / qtd if qtd else 0, valor])
    resumo.rodape = ["Total", "", "", "", sum(l[4] for l in resumo.linhas)]
    return [resumo, detalhe]


def livro_controlados(inicio, fim, produto_id=None, lista=None):
    """Escrituração de medicamentos de controle especial (Portaria SVS/MS nº 344/1998).

    Por produto controlado: saldo no início do período, cada entrada e saída com lote,
    documento, paciente, prescritor e responsável, saldo corrente e saldo final.
    Transferências entre locais da própria instituição (e os seus estornos) não alteram
    o saldo total e não são escrituradas. ``lista`` filtra pela classificação (A1, B1...).
    """
    ini, fim_ = _periodo(inicio, fim)
    consulta = Produto.query.filter(Produto.controle_especial.isnot(None), Produto.controle_especial != "")
    if produto_id:
        consulta = consulta.filter(Produto.id == produto_id)
    if lista:
        consulta = consulta.filter(Produto.controle_especial == lista)
    tabelas = []
    escrituraveis = [t for t in Movimentacao.TIPOS if t != Movimentacao.TRANSFERENCIA]
    for produto in consulta.order_by(Produto.nome_comercial):
        saldo_inicial = db.session.query(db.func.coalesce(db.func.sum(Movimentacao.quantidade), 0)).filter(
            Movimentacao.produto_id == produto.id, Movimentacao.data < ini).scalar() or ZERO
        movimentos = Movimentacao.query.filter(
            Movimentacao.produto_id == produto.id, Movimentacao.data.between(ini, fim_),
            Movimentacao.tipo.in_(escrituraveis)).order_by(Movimentacao.data, Movimentacao.id).all()
        movimentos = [m for m in movimentos if not m.estorno_de_transferencia]
        tabela = Tabela(
            f"{produto} — lista {produto.controle_especial} — {produto.principio_ativo or ''}".rstrip(" —"), [
                Coluna("Data/hora"), Coluna("Operação"), Coluna("Lote"), Coluna("Documento"),
                Coluna("Paciente"), Coluna("Prescritor"), Coluna("Entrada", "numero"), Coluna("Saída", "numero"),
                Coluna("Saldo", "numero"), Coluna("Responsável"),
            ])
        saldo = decimal(saldo_inicial)
        tabela.linhas.append(["", "Saldo anterior", "", "", "", "", "", "", saldo, ""])
        entradas = saidas = ZERO
        for m in movimentos:
            saldo += m.quantidade
            entrada, saida = (m.quantidade, "") if m.quantidade > 0 else ("", -m.quantidade)
            entradas += m.quantidade if m.quantidade > 0 else ZERO
            saidas += -m.quantidade if m.quantidade < 0 else ZERO
            dispensacao = m.dispensacao
            medico = dispensacao.medico if dispensacao else None
            tabela.linhas.append([
                m.data.strftime("%d/%m/%Y %H:%M"), m.tipo_descricao, m.lote.numero_lote,
                m.documento or (f"Dispensação {dispensacao.numero_formatado}" if dispensacao else "") or m.motivo or "",
                dispensacao.paciente.nome if dispensacao else "",
                f"{medico.nome} ({medico.crm_formatado})" if medico else "",
                entrada, saida, saldo, m.usuario.login if m.usuario else "",
            ])
        tabela.rodape = ["", "Totais do período", "", "", "", "", entradas, saidas, saldo, ""]
        tabelas.append(tabela)
    if not tabelas:
        titulo = (f"Nenhum produto de controle especial da lista {lista} cadastrado" if lista and not produto_id
                  else "Nenhum produto de controle especial para o filtro escolhido" if lista or produto_id
                  else "Nenhum produto de controle especial cadastrado")
        tabelas.append(Tabela(titulo, [Coluna("Produto")]))
    return tabelas
