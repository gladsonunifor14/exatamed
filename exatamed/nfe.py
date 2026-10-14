"""Leitura do XML da NF-e (modelo 55, leiautes 3.10 e 4.00).

Aceita o arquivo "nfeProc" (NF-e com protocolo de autorização, o XML que o fornecedor
envia) ou só o elemento "NFe". O XML é lido com defusedxml, que recusa entidades externas
e expansões maliciosas ("bomba de entidades").

Para cada item, devolve código, descrição, GTIN, registro ANVISA, unidade, quantidade,
custo unitário efetivo e os lotes com validade (grupo "rastro" no leiaute 4.00 ou "med"
no 3.10). O custo unitário efetivo inclui frete, seguro, outras despesas, IPI e ICMS-ST e
desconta o desconto do item, que é como o custo de aquisição entra no estoque.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .numeros import decimal

NS = "{http://www.portalfiscal.inf.br/nfe}"
# 100 = autorizada; 150 = autorizada fora do prazo.
SITUACOES_AUTORIZADAS = {"100", "150"}
TAMANHO_MAXIMO = 5 * 1024 * 1024  # 5 MB


class NFeError(ValueError):
    """Arquivo que não é uma NF-e válida ou que não pode ser importada."""


def _filho(elemento, caminho):
    """Busca por caminho ignorando o namespace (alguns emissores omitem o padrão)."""
    if elemento is None:
        return None
    achado = elemento.find("/".join(NS + parte for parte in caminho.split("/")))
    if achado is None:
        achado = elemento.find(caminho)
    return achado


def _texto(elemento, caminho, padrao=""):
    achado = _filho(elemento, caminho)
    return (achado.text or "").strip() if achado is not None and achado.text else padrao


def _filhos(elemento, nome):
    if elemento is None:
        return []
    return elemento.findall(NS + nome) or elemento.findall(nome)


def _numero(texto, padrao="0"):
    try:
        return Decimal((texto or padrao).strip())
    except InvalidOperation:
        raise NFeError(f"Valor numérico inválido no XML: {texto!r}") from None


def _data(texto):
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        raise NFeError(f"Data inválida no XML: {texto!r}") from None


def _data_hora(texto):
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        # Mantém a hora local de emissão (o fuso, ex. -03:00, é descartado).
        return datetime.fromisoformat(texto).replace(tzinfo=None)
    except ValueError:
        raise NFeError(f"Data de emissão inválida no XML: {texto!r}") from None


def chave_valida(chave):
    """Confere o dígito verificador (módulo 11) da chave de acesso de 44 dígitos."""
    if len(chave) != 44 or not chave.isdigit():
        return False
    soma = sum(int(d) * peso for d, peso in zip(reversed(chave[:43]), [2, 3, 4, 5, 6, 7, 8, 9] * 6))
    resto = soma % 11
    dv = 0 if resto < 2 else 11 - resto
    return dv == int(chave[43])


def _custo_unitario(det, prod, quantidade):
    """Custo de aquisição por unidade comercial (uCom)."""
    if quantidade <= 0:
        raise NFeError("Item com quantidade zero ou negativa no XML.")
    total = _numero(_texto(prod, "vProd"))
    for campo in ("vFrete", "vSeg", "vOutro"):
        total += _numero(_texto(prod, campo) or "0")
    total -= _numero(_texto(prod, "vDesc") or "0")
    imposto = _filho(det, "imposto")
    total += _numero(_texto(imposto, "IPI/IPITrib/vIPI") or "0")
    icms = _filho(imposto, "ICMS")
    if icms is not None:
        for grupo in icms:
            total += _numero(_texto(grupo, "vICMSST") or "0")
    return decimal(total / quantidade)


def _lotes(prod, quantidade):
    """Lotes do item: grupo "rastro" (leiaute 4.00) ou "med" com lote (leiaute 3.10)."""
    lotes = []
    for rastro in _filhos(prod, "rastro"):
        lotes.append({"lote": _texto(rastro, "nLote"), "quantidade": decimal(_numero(_texto(rastro, "qLote"))),
                      "fabricacao": _data(_texto(rastro, "dFab")), "validade": _data(_texto(rastro, "dVal"))})
    if not lotes:
        for med in _filhos(prod, "med"):
            if _texto(med, "nLote"):
                lotes.append({"lote": _texto(med, "nLote"), "quantidade": decimal(_numero(_texto(med, "qLote"))),
                              "fabricacao": _data(_texto(med, "dFab")), "validade": _data(_texto(med, "dVal"))})
    if not lotes:
        # Material sem rastreabilidade na nota: lote e validade serão informados na conferência.
        lotes.append({"lote": "", "quantidade": quantidade, "fabricacao": None, "validade": None})
    return lotes


def ler_nfe(conteudo):
    """Lê o XML (bytes) e devolve um dicionário com cabeçalho, situação e itens."""
    if not conteudo:
        raise NFeError("Arquivo vazio.")
    if len(conteudo) > TAMANHO_MAXIMO:
        raise NFeError("Arquivo maior que 5 MB: não parece ser um XML de NF-e.")
    try:
        raiz = ElementTree.fromstring(conteudo, forbid_dtd=True)
    except DefusedXmlException:
        raise NFeError("O XML contém construções não permitidas (DTD ou entidades) e foi recusado.") from None
    except ElementTree.ParseError:
        raise NFeError("O arquivo não é um XML válido.") from None

    nfe = raiz if raiz.tag.endswith("NFe") and not raiz.tag.endswith("nfeProc") else _filho(raiz, "NFe")
    inf = _filho(nfe, "infNFe")
    if inf is None:
        raise NFeError("O arquivo não é uma NF-e: elemento infNFe não encontrado.")
    chave = (inf.get("Id") or "").removeprefix("NFe")
    if not chave_valida(chave):
        raise NFeError("Chave de acesso ausente ou inválida (dígito verificador não confere).")
    ide = _filho(inf, "ide")
    if _texto(ide, "mod") not in ("", "55"):
        raise NFeError("Apenas NF-e modelo 55 pode ser importada.")
    emit, dest = _filho(inf, "emit"), _filho(inf, "dest")
    prot = _filho(raiz, "protNFe/infProt")

    itens = []
    for det in _filhos(inf, "det"):
        prod = _filho(det, "prod")
        quantidade = decimal(_numero(_texto(prod, "qCom")))
        med = _filho(prod, "med")
        gtin = _texto(prod, "cEAN")
        itens.append({
            "numero": int(det.get("nItem") or len(itens) + 1),
            "codigo": _texto(prod, "cProd"),
            "descricao": _texto(prod, "xProd"),
            "gtin": gtin if gtin.isdigit() else "",
            "registro_anvisa": _texto(med, "cProdANVISA") if med is not None else "",
            "ncm": _texto(prod, "NCM"),
            "unidade": _texto(prod, "uCom"),
            "quantidade": quantidade,
            "valor_total": decimal(_numero(_texto(prod, "vProd"))),
            "custo_unitario": _custo_unitario(det, prod, quantidade),
            "lotes": _lotes(prod, quantidade),
        })
    if not itens:
        raise NFeError("A NF-e não tem itens.")

    return {
        "chave": chave,
        "numero": _texto(ide, "nNF"),
        "serie": _texto(ide, "serie"),
        "emissao": _data_hora(_texto(ide, "dhEmi") or _texto(ide, "dEmi")),
        "emitente_cnpj": _texto(emit, "CNPJ") or _texto(emit, "CPF"),
        "emitente_nome": _texto(emit, "xNome"),
        "destinatario_cnpj": _texto(dest, "CNPJ") or _texto(dest, "CPF"),
        "destinatario_nome": _texto(dest, "xNome"),
        "valor_total": decimal(_numero(_texto(inf, "total/ICMSTot/vNF"))),
        "protocolo": _texto(prot, "nProt"),
        "situacao_sefaz": _texto(prot, "cStat"),
        "motivo_sefaz": _texto(prot, "xMotivo"),
        "autorizada": _texto(prot, "cStat") in SITUACOES_AUTORIZADAS,
        "itens": itens,
    }
