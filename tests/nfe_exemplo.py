"""Gera XMLs de NF-e realistas (leiaute 4.00, com protocolo) para os testes."""


def dv_chave(chave43):
    soma = sum(int(d) * p for d, p in zip(reversed(chave43), [2, 3, 4, 5, 6, 7, 8, 9] * 6))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def chave(numero=1234, cnpj="12345678000195"):
    base = f"23{2610}{cnpj}55001{numero:09d}1{numero:08d}"
    return base + dv_chave(base)


ITENS_PADRAO = [
    # Medicamento com dois lotes (grupo rastro) e registro ANVISA: caixa com 10 ampolas.
    {"codigo": "DIP500", "descricao": "DIPIRONA SODICA 500MG/ML AMP 2ML CX C/10", "gtin": "7891234567895",
     "anvisa": "1023500010015", "unidade": "CX", "quantidade": "3", "unitario": "25.00", "frete": "3.00",
     "desconto": "1.50",
     "lotes": [("DP2501", "2", "2026-01-10", "2099-01-31"), ("DP2502", "1", "2026-02-10", "2099-02-28")]},
    # Material sem rastreabilidade (lote e validade informados na conferência).
    {"codigo": "SER10", "descricao": "SERINGA 10ML LUER LOCK", "gtin": "SEM GTIN", "anvisa": "", "unidade": "UN",
     "quantidade": "100", "unitario": "0.45", "frete": "0", "desconto": "0", "lotes": []},
]


def gerar_xml(numero=1234, cnpj="12345678000195", itens=None, situacao="100", com_protocolo=True,
              nome="DISTRIBUIDORA HOSPITALAR LTDA"):
    itens = ITENS_PADRAO if itens is None else itens
    ch = chave(numero, cnpj)
    dets, total = [], 0
    for i, item in enumerate(itens, start=1):
        rastros = "".join(
            f"<rastro><nLote>{lote}</nLote><qLote>{qtd}</qLote><dFab>{fab}</dFab><dVal>{val}</dVal></rastro>"
            for lote, qtd, fab, val in item["lotes"])
        med = (f"<med><cProdANVISA>{item['anvisa']}</cProdANVISA><vPMC>40.00</vPMC></med>" if item["anvisa"] else "")
        vprod = float(item["quantidade"]) * float(item["unitario"])
        total += vprod
        dets.append(
            f'<det nItem="{i}"><prod><cProd>{item["codigo"]}</cProd><cEAN>{item["gtin"]}</cEAN>'
            f'<xProd>{item["descricao"]}</xProd><NCM>30049099</NCM><CFOP>5102</CFOP><uCom>{item["unidade"]}</uCom>'
            f'<qCom>{item["quantidade"]}</qCom><vUnCom>{item["unitario"]}</vUnCom><vProd>{vprod:.2f}</vProd>'
            f'<cEANTrib>{item["gtin"]}</cEANTrib><uTrib>{item["unidade"]}</uTrib><qTrib>{item["quantidade"]}</qTrib>'
            f'<vUnTrib>{item["unitario"]}</vUnTrib>'
            + (f'<vFrete>{item["frete"]}</vFrete>' if item["frete"] != "0" else "")
            + (f'<vDesc>{item["desconto"]}</vDesc>' if item["desconto"] != "0" else "")
            + f"<indTot>1</indTot>{rastros}{med}</prod>"
            f"<imposto><ICMS><ICMS00><orig>0</orig><CST>00</CST></ICMS00></ICMS></imposto></det>")
    protocolo = (f'<protNFe versao="4.00"><infProt><tpAmb>1</tpAmb><chNFe>{ch}</chNFe>'
                 f"<dhRecbto>2026-10-10T08:31:00-03:00</dhRecbto><nProt>123260000012345</nProt>"
                 f"<cStat>{situacao}</cStat><xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe>"
                 if com_protocolo else "")
    nfe = (f'<NFe xmlns="http://www.portalfiscal.inf.br/nfe"><infNFe versao="4.00" Id="NFe{ch}">'
           f"<ide><cUF>23</cUF><natOp>VENDA</natOp><mod>55</mod><serie>1</serie><nNF>{numero}</nNF>"
           f"<dhEmi>2026-10-10T08:30:00-03:00</dhEmi><tpNF>1</tpNF></ide>"
           f"<emit><CNPJ>{cnpj}</CNPJ><xNome>{nome}</xNome></emit>"
           f"<dest><CNPJ>98765432000198</CNPJ><xNome>HOSPITAL EXEMPLO</xNome></dest>"
           + "".join(dets)
           + f"<total><ICMSTot><vNF>{total:.2f}</vNF></ICMSTot></total></infNFe></NFe>")
    if not com_protocolo:
        return f'<?xml version="1.0" encoding="UTF-8"?>{nfe}'.encode()
    return (f'<?xml version="1.0" encoding="UTF-8"?><nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" '
            f'versao="4.00">{nfe}{protocolo}</nfeProc>').encode()
