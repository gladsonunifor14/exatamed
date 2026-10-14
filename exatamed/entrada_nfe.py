"""Entrada de estoque a partir do XML da NF-e.

Fluxo em duas etapas, com conferência humana:

1. ``receber_xml``: lê o XML, recusa nota sem autorização da SEFAZ ou já importada e guarda
   a nota como PENDENTE, com o XML original (obrigação de guarda fiscal).
2. ``confirmar``: com o produto, o fator de conversão, os lotes e as validades conferidos,
   registra todas as entradas numa única transação, liga cada lote à nota e memoriza o
   de-para "código do fornecedor -> produto" para as próximas importações.
"""

from datetime import date, datetime

from . import estoque
from .estoque import EstoqueError
from .models import Lote, NotaFiscal, Produto, ProdutoFornecedor, db
from .nfe import NFeError, ler_nfe
from .numeros import decimal

ORIGENS_SUGESTAO = {
    "fornecedor": "código do fornecedor (importação anterior)",
    "gtin": "código de barras (GTIN)",
    "anvisa": "registro ANVISA",
}


def receber_xml(conteudo):
    """Valida o XML e devolve a NotaFiscal pendente (nova ou já existente)."""
    dados = ler_nfe(conteudo)
    if dados["situacao_sefaz"] and not dados["autorizada"]:
        raise NFeError(f"A NF-e não está autorizada pela SEFAZ (situação {dados['situacao_sefaz']}: "
                       f"{dados['motivo_sefaz']}).")
    if not dados["protocolo"]:
        raise NFeError("O XML não tem o protocolo de autorização da SEFAZ. Peça ao fornecedor o arquivo "
                       "completo da NF-e autorizada (nfeProc).")
    try:
        xml = conteudo.decode("utf-8")
    except UnicodeDecodeError:
        xml = conteudo.decode("latin-1")
    nota = NotaFiscal.query.filter_by(chave=dados["chave"]).first()
    if nota and nota.situacao == NotaFiscal.IMPORTADA:
        quem = f" por {nota.usuario.login}" if nota.usuario else ""
        raise NFeError(f"A {nota.documento} de {nota.emitente_nome} já foi importada em "
                       f"{nota.importada_em:%d/%m/%Y %H:%M}{quem}.")
    if nota is None:
        nota = NotaFiscal(chave=dados["chave"])
        db.session.add(nota)
    nota.situacao = NotaFiscal.PENDENTE
    nota.numero, nota.serie, nota.emissao = dados["numero"], dados["serie"], dados["emissao"]
    nota.emitente_cnpj, nota.emitente_nome = dados["emitente_cnpj"], dados["emitente_nome"][:200]
    nota.valor_total, nota.protocolo, nota.xml = dados["valor_total"], dados["protocolo"], xml
    return nota


def dados_da_nota(nota):
    return ler_nfe(nota.xml.encode("utf-8"))


def sugerir_produto(cnpj, item):
    """Produto e fator sugeridos para um item da nota, e de onde veio a sugestão."""
    de_para = ProdutoFornecedor.query.filter_by(cnpj=cnpj, codigo=item["codigo"]).first()
    if de_para and de_para.produto.ativo:
        return de_para.produto, de_para.fator, "fornecedor"
    if item["gtin"]:
        produto = Produto.query.filter_by(gtin=item["gtin"], ativo=True).first()
        if produto:
            return produto, decimal(1), "gtin"
    if item["registro_anvisa"]:
        produto = Produto.query.filter_by(registro_anvisa=item["registro_anvisa"], ativo=True).first()
        if produto:
            return produto, decimal(1), "anvisa"
    return None, decimal(1), None


def ultimo_custo(produto_id):
    lote = Lote.query.filter_by(produto_id=produto_id).order_by(Lote.data_entrada.desc(), Lote.id.desc()).first()
    return lote.custo_unitario if lote else None


def confirmar(nota, localizacao, escolhas):
    """Registra as entradas conferidas.

    ``escolhas`` mapeia o número do item para ``{"importar", "produto", "fator", "lotes":
    [{"lote", "validade"}, ...]}``, na mesma ordem dos lotes lidos do XML.
    """
    nota = NotaFiscal.query.filter_by(id=nota.id).with_for_update().populate_existing().one()
    if nota.situacao != NotaFiscal.PENDENTE:
        raise EstoqueError(f"Esta nota está com a situação '{nota.situacao_descricao}' e não pode ser importada.")
    if localizacao is None:
        raise EstoqueError("Selecione o local de entrada do estoque.")
    dados = dados_da_nota(nota)
    hoje = date.today()
    agora = datetime.now()
    entradas = 0
    for item in dados["itens"]:
        escolha = escolhas.get(item["numero"]) or {}
        if not escolha.get("importar"):
            continue
        rotulo = f"Item {item['numero']} ({item['descricao']})"
        produto = escolha.get("produto")
        if produto is None:
            raise EstoqueError(f"{rotulo}: selecione o produto correspondente.")
        try:
            fator = decimal(escolha.get("fator") or "1")
        except ValueError:
            raise EstoqueError(f"{rotulo}: fator de conversão inválido.") from None
        if fator <= 0:
            raise EstoqueError(f"{rotulo}: o fator de conversão deve ser maior que zero.")
        conferidos = escolha.get("lotes") or []
        for indice, lote_nf in enumerate(item["lotes"]):
            conferido = conferidos[indice] if indice < len(conferidos) else {}
            numero_lote = (conferido.get("lote") or lote_nf["lote"] or "").strip()
            validade = conferido.get("validade") or lote_nf["validade"]
            if not numero_lote:
                raise EstoqueError(f"{rotulo}: informe o número do lote.")
            if not validade:
                raise EstoqueError(f"{rotulo}, lote {numero_lote}: informe a validade.")
            if validade < hoje:
                raise EstoqueError(f"{rotulo}, lote {numero_lote}: lote vencido em {validade:%d/%m/%Y}.")
            quantidade = decimal(lote_nf["quantidade"] * fator)
            custo = decimal(item["custo_unitario"] / fator)
            lote = estoque.registrar_entrada(produto, localizacao, numero_lote, validade, quantidade, custo,
                                             documento=nota.documento, data=agora)
            lote.nota_fiscal = nota
            entradas += 1
        _memorizar_de_para(nota.emitente_cnpj, item, produto, fator)
    if not entradas:
        raise EstoqueError("Selecione ao menos um item para importar.")
    nota.situacao, nota.localizacao, nota.importada_em = NotaFiscal.IMPORTADA, localizacao, agora
    return entradas


def _memorizar_de_para(cnpj, item, produto, fator):
    de_para = ProdutoFornecedor.query.filter_by(cnpj=cnpj, codigo=item["codigo"]).first()
    if de_para is None:
        de_para = ProdutoFornecedor(cnpj=cnpj, codigo=item["codigo"][:60])
        db.session.add(de_para)
    de_para.descricao, de_para.produto, de_para.fator = item["descricao"][:200], produto, fator


def descartar(nota):
    if nota.situacao != NotaFiscal.PENDENTE:
        raise EstoqueError("Só notas aguardando conferência podem ser descartadas.")
    nota.situacao = NotaFiscal.DESCARTADA

