"""Indicadores do Dashboard de gestão.

Todos os valores são calculados pelo custo PEPS das movimentações (o custo do lote que saiu),
com decimais exatos. O consumo é líquido: dispensações menos devoluções e saídas avulsas
menos os seus estornos.
"""

import unicodedata
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import or_

from .models import Dispensacao, Lote, Movimentacao, Produto, db
from .numeros import ZERO, decimal
from .relatorios import _periodo

GRANULARIDADES = {"dia": "Dia", "mes": "Mês", "ano": "Ano"}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

# Curva ABC: classe pela participação acumulada no valor consumido (antes do item).
LIMITE_A, LIMITE_B = decimal(80), decimal(95)

# Faixas de vencimento (dias até a validade).
FAIXAS_VENCIMENTO = [(30, "Até 30 dias", "critico"), (60, "De 31 a 60 dias", "serio"),
                     (90, "De 61 a 90 dias", "alerta")]

# Saídas avulsas classificadas pelo motivo informado (texto sem acentos, em minúsculas).
CATEGORIAS_PERDA = [
    ("Avaria / quebra", ("avaria", "quebra", "danific", "violad", "contamin", "defeito")),
    ("Vencimento", ("vencid", "vencimento", "validade expirada")),
    ("Perda / extravio", ("perda", "perdid", "extravi", "furto", "roubo", "desvio")),
]
# Sugestões de motivo oferecidas na saída avulsa (ajudam a classificar).
MOTIVOS_SAIDA = ["Consumo do setor", "Avaria", "Quebra", "Vencimento", "Perda", "Extravio",
                 "Devolução ao fornecedor", "Amostra para análise"]


def _sem_acento(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def categoria_perda(motivo):
    texto = _sem_acento(motivo)
    for categoria, termos in CATEGORIAS_PERDA:
        if any(t in texto for t in termos):
            return categoria
    return None


def _percentual(parte, total):
    return decimal(parte * 100 / total) if total else ZERO


def _consumo(inicio, fim, medico_id=None, localizacao_id=None, tipo_produto=None):
    """Movimentações de consumo do período, com os filtros do dashboard."""
    ini, fim_ = _periodo(inicio, fim)
    consulta = Movimentacao.query.filter(Movimentacao.tipo.in_(Movimentacao.CONSUMO),
                                         Movimentacao.data.between(ini, fim_))
    if localizacao_id:
        # O local de dispensação (destino) ou o local de onde o item saiu.
        consulta = consulta.filter(or_(Movimentacao.destino_id == localizacao_id,
                                       Movimentacao.localizacao_id == localizacao_id))
    if medico_id:
        consulta = consulta.join(Dispensacao, Movimentacao.dispensacao_id == Dispensacao.id) \
            .filter(Dispensacao.medico_id == medico_id)
    if tipo_produto:
        consulta = consulta.join(Produto, Movimentacao.produto_id == Produto.id).filter(Produto.tipo == tipo_produto)
    return consulta.all()


# --------------------------------------------------------------------------- evolução do custo

def _chave_periodo(dia, granularidade):
    if granularidade == "ano":
        return date(dia.year, 1, 1)
    if granularidade == "mes":
        return date(dia.year, dia.month, 1)
    return dia


def _proximo(chave, granularidade):
    if granularidade == "ano":
        return date(chave.year + 1, 1, 1)
    if granularidade == "mes":
        return date(chave.year + (chave.month == 12), chave.month % 12 + 1, 1)
    return chave + timedelta(days=1)


def _rotulo_periodo(chave, granularidade):
    if granularidade == "ano":
        return str(chave.year)
    if granularidade == "mes":
        return f"{MESES[chave.month - 1]}/{chave.year % 100:02d}"
    return chave.strftime("%d/%m")


def periodo_padrao(granularidade, hoje=None):
    hoje = hoje or date.today()
    if granularidade == "ano":
        return date(hoje.year - 4, 1, 1), hoje
    if granularidade == "mes":
        return date(hoje.year - 1, hoje.month, 1), hoje
    return hoje - timedelta(days=29), hoje


def evolucao_custo(inicio, fim, granularidade="dia", medico_id=None, localizacao_id=None):
    """Custo do consumo por dia, mês ou ano, com os períodos sem consumo zerados."""
    totais = defaultdict(lambda: ZERO)
    for m in _consumo(inicio, fim, medico_id, localizacao_id):
        totais[_chave_periodo(m.data.date(), granularidade)] += m.consumo_custo
    pontos = []
    chave = _chave_periodo(inicio, granularidade)
    while chave <= fim:
        pontos.append({"chave": chave, "rotulo": _rotulo_periodo(chave, granularidade),
                       "valor": decimal(totais.get(chave, ZERO))})
        chave = _proximo(chave, granularidade)
    total = sum((p["valor"] for p in pontos), ZERO)
    com_consumo = [p for p in pontos if p["valor"]]
    return {"pontos": pontos, "total": total,
            "media": decimal(total / len(pontos)) if pontos else ZERO,
            "maior": max(com_consumo, key=lambda p: p["valor"]) if com_consumo else None}


# --------------------------------------------------------------------------- curva ABC

def curva_abc(inicio, fim, tipo_produto=None):
    """Classificação ABC dos itens pelo valor consumido no período."""
    por_produto = defaultdict(lambda: [ZERO, ZERO])
    produtos = {}
    for m in _consumo(inicio, fim, tipo_produto=tipo_produto):
        produtos[m.produto_id] = m.produto
        por_produto[m.produto_id][0] += m.consumo_quantidade
        por_produto[m.produto_id][1] += m.consumo_custo
    linhas = sorted(((produtos[pid], qtd, custo) for pid, (qtd, custo) in por_produto.items() if custo > 0),
                    key=lambda linha: -linha[2])
    total = sum((custo for _, _, custo in linhas), ZERO)
    itens, acumulado = [], ZERO
    resumo = {classe: {"itens": 0, "valor": ZERO} for classe in "ABC"}
    for posicao, (produto, qtd, custo) in enumerate(linhas, start=1):
        antes = _percentual(acumulado, total)
        classe = "A" if antes < LIMITE_A else "B" if antes < LIMITE_B else "C"
        acumulado += custo
        itens.append({"posicao": posicao, "produto": produto, "quantidade": decimal(qtd), "valor": decimal(custo),
                      "participacao": _percentual(custo, total), "acumulado": _percentual(acumulado, total),
                      "classe": classe})
        resumo[classe]["itens"] += 1
        resumo[classe]["valor"] += custo
    for dados in resumo.values():
        dados["perc_itens"] = _percentual(dados["itens"], len(itens))
        dados["perc_valor"] = _percentual(dados["valor"], total)
    return {"itens": itens, "resumo": resumo, "total": total}


# --------------------------------------------------------------------------- vencimentos

def vencimentos(hoje=None):
    """Lotes com saldo que vencem em até 30, 60 e 90 dias (e os já vencidos)."""
    hoje = hoje or date.today()
    lotes = Lote.query.join(Produto).filter(Lote.saldo > 0, Lote.validade <= hoje + timedelta(days=90)) \
        .order_by(Lote.validade, Produto.nome_comercial).all()
    faixas = [{"limite": limite, "rotulo": rotulo, "status": status, "lotes": 0, "valor": ZERO}
              for limite, rotulo, status in FAIXAS_VENCIMENTO]
    vencidos = {"lotes": 0, "valor": ZERO}
    detalhes = []
    for lote in lotes:
        dias = (lote.validade - hoje).days
        valor = decimal(lote.saldo * lote.custo_unitario)
        if dias < 0:
            vencidos["lotes"] += 1
            vencidos["valor"] += valor
            faixa = None
        else:
            faixa = next(f for f in faixas if dias <= f["limite"])
            faixa["lotes"] += 1
            faixa["valor"] += valor
        detalhes.append({"lote": lote, "dias": dias, "valor": valor, "faixa": faixa})
    return {"faixas": faixas, "vencidos": vencidos, "lotes": detalhes}


# --------------------------------------------------------------------------- ruptura e estoque de segurança

def _saldos_utilizaveis(hoje):
    return {pid: decimal(saldo) for pid, saldo in db.session.query(Lote.produto_id, db.func.sum(Lote.saldo))
            .filter(Lote.validade >= hoje, Lote.bloqueado.is_(False)).group_by(Lote.produto_id)}


def _consumo_medio_diario(hoje, dias=30):
    consumo = defaultdict(lambda: ZERO)
    for m in _consumo(hoje - timedelta(days=dias - 1), hoje):
        consumo[m.produto_id] += m.consumo_quantidade
    return {pid: decimal(qtd / dias) for pid, qtd in consumo.items()}


def ruptura(hoje=None):
    """Itens monitorados sem saldo utilizável (não vencido nem bloqueado).

    Itens monitorados: produtos ativos com estoque mínimo definido ou que já tiveram
    movimentação. Produtos recém-cadastrados, nunca comprados, ficam de fora.
    """
    hoje = hoje or date.today()
    saldos = _saldos_utilizaveis(hoje)
    movimentados = {pid for (pid,) in db.session.query(Movimentacao.produto_id).distinct()}
    saldo_total = {pid: decimal(s) for pid, s in db.session.query(Lote.produto_id, db.func.sum(Lote.saldo))
                   .group_by(Lote.produto_id)}
    cmd = _consumo_medio_diario(hoje)
    monitorados = [p for p in Produto.query.filter_by(ativo=True).order_by(Produto.nome_comercial)
                   if p.estoque_minimo > 0 or p.id in movimentados]
    em_falta = [{"produto": p, "saldo_total": saldo_total.get(p.id, ZERO), "cmd": cmd.get(p.id, ZERO)}
                for p in monitorados if saldos.get(p.id, ZERO) <= 0]
    return {"monitorados": len(monitorados), "em_falta": em_falta,
            "taxa": _percentual(len(em_falta), len(monitorados))}


NIVEIS_SEGURANCA = [("ruptura", "Em ruptura", "critico"), ("abaixo", "Abaixo do mínimo", "serio"),
                    ("adequado", "Adequado", "bom"), ("acima", "Acima do máximo", "alerta")]


def estoque_seguranca(hoje=None):
    """Saldo utilizável de cada item comparado ao estoque mínimo (estoque de segurança)."""
    hoje = hoje or date.today()
    saldos = _saldos_utilizaveis(hoje)
    cmd = _consumo_medio_diario(hoje)
    niveis = {chave: {"chave": chave, "rotulo": rotulo, "status": status, "itens": 0}
              for chave, rotulo, status in NIVEIS_SEGURANCA}
    criticos = []
    produtos = Produto.query.filter(Produto.ativo.is_(True), Produto.estoque_minimo > 0) \
        .order_by(Produto.nome_comercial).all()
    for p in produtos:
        saldo = saldos.get(p.id, ZERO)
        if saldo <= 0:
            nivel = "ruptura"
        elif saldo < p.estoque_minimo:
            nivel = "abaixo"
        elif p.estoque_maximo and saldo > p.estoque_maximo:
            nivel = "acima"
        else:
            nivel = "adequado"
        niveis[nivel]["itens"] += 1
        if nivel in ("ruptura", "abaixo"):
            consumo = cmd.get(p.id, ZERO)
            criticos.append({"produto": p, "saldo": saldo, "nivel": niveis[nivel],
                             "cobertura_minimo": _percentual(saldo, p.estoque_minimo),
                             "dias": decimal(saldo / consumo) if consumo else None})
    total = len(produtos)
    for dados in niveis.values():
        dados["percentual"] = _percentual(dados["itens"], total)
    criticos.sort(key=lambda c: c["cobertura_minimo"])
    return {"total": total, "niveis": list(niveis.values()), "criticos": criticos,
            "sem_minimo": Produto.query.filter(Produto.ativo.is_(True), Produto.estoque_minimo <= 0).count()}


# --------------------------------------------------------------------------- giro do estoque

def _valor_estoque_em(momento):
    """Valor do estoque (custo PEPS) por produto num instante, pela soma das movimentações."""
    return {pid: decimal(valor or 0) for pid, valor in
            db.session.query(Movimentacao.produto_id,
                             db.func.sum(Movimentacao.quantidade * Movimentacao.custo_unitario))
            .filter(Movimentacao.data < momento).group_by(Movimentacao.produto_id)}


def giro_estoque(inicio, fim):
    """Giro = custo do consumo no período ÷ estoque médio ((inicial + final) ÷ 2)."""
    ini, fim_ = _periodo(inicio, fim)
    dias = (fim - inicio).days + 1
    inicial, final = _valor_estoque_em(ini), _valor_estoque_em(fim_)
    consumo = defaultdict(lambda: ZERO)
    for m in _consumo(inicio, fim):
        consumo[m.produto_id] += m.consumo_custo
    produtos = {p.id: p for p in Produto.query.filter(Produto.id.in_(set(inicial) | set(final) | set(consumo)))}
    itens = []
    for pid, produto in produtos.items():
        medio = decimal((inicial.get(pid, ZERO) + final.get(pid, ZERO)) / 2)
        valor_consumo = decimal(consumo.get(pid, ZERO))
        if medio <= 0 and valor_consumo <= 0:
            continue
        giro = decimal(valor_consumo / medio) if medio > 0 else None
        itens.append({"produto": produto, "consumo": valor_consumo, "estoque_medio": medio, "giro": giro,
                      "cobertura": decimal(dias / giro) if giro else None})
    total_consumo = sum((i["consumo"] for i in itens), ZERO)
    medio_total = decimal((sum(inicial.values(), ZERO) + sum(final.values(), ZERO)) / 2)
    giro_total = decimal(total_consumo / medio_total) if medio_total > 0 else None
    com_estoque = [i for i in itens if i["giro"] is not None]
    return {
        "dias": dias, "consumo": total_consumo, "estoque_medio": medio_total, "giro": giro_total,
        "giro_anual": decimal(giro_total * 365 / dias) if giro_total is not None else None,
        "cobertura": decimal(dias / giro_total) if giro_total else None,
        "estoque_final": decimal(sum(final.values(), ZERO)),
        "menor_giro": sorted(com_estoque, key=lambda i: (i["giro"], -i["estoque_medio"]))[:5],
        "maior_giro": sorted(com_estoque, key=lambda i: -i["giro"])[:5],
    }


# --------------------------------------------------------------------------- devoluções e avarias

def devolucoes_avarias(inicio, fim):
    """Taxa de devolução das dispensações e taxa de avarias/perdas nas saídas avulsas."""
    ini, fim_ = _periodo(inicio, fim)
    movimentos = Movimentacao.query.filter(
        Movimentacao.data.between(ini, fim_),
        Movimentacao.tipo.in_((Movimentacao.DISPENSACAO, Movimentacao.ESTORNO, Movimentacao.SAIDA))).all()
    estornadas = {origem for (origem,) in db.session.query(Movimentacao.origem_id)
                  .filter(Movimentacao.tipo == Movimentacao.ESTORNO_SAIDA)}
    dispensado = devolvido = saidas = ZERO
    dispensacoes, com_devolucao = set(), set()
    categorias = {nome: {"categoria": nome, "saidas": 0, "valor": ZERO} for nome, _ in CATEGORIAS_PERDA}
    outras = {"categoria": "Outras saídas avulsas", "saidas": 0, "valor": ZERO}
    for m in movimentos:
        valor = decimal(abs(m.quantidade) * m.custo_unitario)
        if m.tipo == Movimentacao.DISPENSACAO:
            dispensado += valor
            dispensacoes.add(m.dispensacao_id)
        elif m.tipo == Movimentacao.ESTORNO:
            devolvido += valor
            com_devolucao.add(m.dispensacao_id)
        elif m.id not in estornadas:  # saída avulsa desfeita não conta
            saidas += valor
            grupo = categorias.get(categoria_perda(m.motivo)) or outras
            grupo["saidas"] += 1
            grupo["valor"] += valor
    perdas = sum((c["valor"] for c in categorias.values()), ZERO)
    consumo = dispensado - devolvido + saidas
    linhas = list(categorias.values()) + [outras]
    for linha in linhas:
        linha["percentual"] = _percentual(linha["valor"], consumo)
    return {
        "dispensado": dispensado, "devolvido": devolvido, "taxa_devolucao": _percentual(devolvido, dispensado),
        # Uma devolução no período pode ser de uma dispensação anterior: ela entra no denominador.
        "dispensacoes": len(dispensacoes | com_devolucao), "com_devolucao": len(com_devolucao),
        "taxa_dispensacoes": _percentual(len(com_devolucao), len(dispensacoes | com_devolucao)),
        "perdas": perdas, "consumo": consumo, "taxa_avarias": _percentual(perdas, consumo),
        "categorias": linhas,
    }
