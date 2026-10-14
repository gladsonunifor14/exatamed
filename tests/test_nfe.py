import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from nfe_exemplo import chave, gerar_xml

from exatamed import auditoria
from exatamed.models import Localizacao, Lote, Movimentacao, NotaFiscal, Produto, ProdutoFornecedor, db
from exatamed.nfe import NFeError, chave_valida, ler_nfe

ITEM_COM_IMPOSTOS = [{"codigo": "X1", "descricao": "PRODUTO X", "gtin": "SEM GTIN", "anvisa": "", "unidade": "UN",
                      "quantidade": "10", "unitario": "10.00", "frete": "0", "desconto": "0", "lotes": []}]


# ------------------------------------------------------------------- leitura do XML

def test_le_nfe_autorizada_com_rastro():
    nota = ler_nfe(gerar_xml())
    assert nota["autorizada"] and nota["numero"] == "1234" and nota["emitente_cnpj"] == "12345678000195"
    dipirona, seringa = nota["itens"]
    assert dipirona["custo_unitario"] == Decimal("25.5")  # (75 + 3 frete - 1,50 desconto) / 3 CX
    assert dipirona["gtin"] == "7891234567895" and dipirona["registro_anvisa"] == "1023500010015"
    assert [(l["lote"], l["quantidade"], l["validade"]) for l in dipirona["lotes"]] == [
        ("DP2501", 2, date(2028, 1, 31)), ("DP2502", 1, date(2028, 2, 29))]
    assert seringa["gtin"] == "" and seringa["lotes"] == [{"lote": "", "quantidade": 100, "fabricacao": None,
                                                           "validade": None}]


def test_custo_inclui_ipi_e_icms_st():
    xml = gerar_xml(itens=ITEM_COM_IMPOSTOS).decode()
    xml = xml.replace("<ICMS><ICMS00><orig>0</orig><CST>00</CST></ICMS00></ICMS>",
                      "<ICMS><ICMS10><orig>0</orig><CST>10</CST><vICMSST>5.00</vICMSST></ICMS10></ICMS>"
                      "<IPI><cEnq>999</cEnq><IPITrib><CST>50</CST><vIPI>15.00</vIPI></IPITrib></IPI>")
    (item,) = ler_nfe(xml.encode())["itens"]
    assert item["custo_unitario"] == Decimal("12")  # (100 + 15 IPI + 5 ST) / 10


def test_leiaute_310_com_lote_no_grupo_med():
    xml = gerar_xml(itens=ITEM_COM_IMPOSTOS).decode().replace(
        "<indTot>1</indTot>", "<indTot>1</indTot><med><nLote>ANT1</nLote><qLote>10</qLote><dFab>2026-01-01</dFab>"
                              "<dVal>2027-12-31</dVal><vPMC>1</vPMC></med>")
    (item,) = ler_nfe(xml.encode())["itens"]
    assert item["lotes"][0]["lote"] == "ANT1" and item["lotes"][0]["validade"] == date(2027, 12, 31)


def test_chave_de_acesso():
    assert chave_valida(chave())
    assert not chave_valida(chave()[:-1] + str((int(chave()[-1]) + 1) % 10))
    xml = gerar_xml().decode().replace(f"NFe{chave()}", f"NFe{chave()[:-1]}0" if chave()[-1] != "0" else "NFe1")
    with pytest.raises(NFeError, match="Chave de acesso"):
        ler_nfe(xml.encode())


@pytest.mark.parametrize("conteudo, trecho", [
    (b"", "vazio"),
    (b"isto nao e xml", "não é um XML válido"),
    (b"<pedido><item/></pedido>", "não é uma NF-e"),
    (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>', "não permitidas"),
    (b'<?xml version="1.0"?><!DOCTYPE b [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;">]><b>&b;</b>',
     "não permitidas"),
    (b"<x>" + b"a" * (5 * 1024 * 1024) + b"</x>", "maior que 5 MB"),
])
def test_xml_invalido_ou_malicioso_e_recusado(conteudo, trecho):
    with pytest.raises(NFeError, match=trecho):
        ler_nfe(conteudo)


# ------------------------------------------------------------------- fluxo pela tela

@pytest.fixture
def base(app):
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    dipirona = Produto(nome_comercial="Novalgina", principio_ativo="Dipirona", unidade_medida="AMP",
                       gtin="7891234567895")
    seringa = Produto(tipo="MATERIAL", nome_comercial="Seringa 10 mL", unidade_medida="UN")
    db.session.add_all([dipirona, seringa])
    db.session.commit()
    return dict(sus=sus, dipirona=dipirona, seringa=seringa)


def _enviar(cliente, xml):
    return cliente.post("/estoque/entrada/nfe", data={"xml": (io.BytesIO(xml), "nota.xml")},
                        content_type="multipart/form-data")


def _confirmacao(b, **extra):
    validade = (date.today() + timedelta(days=400)).isoformat()
    dados = {"localizacao_id": b["sus"].id,
             "item_1_importar": "1", "item_1_produto": b["dipirona"].id, "item_1_fator": "10",
             "item_1_lote_0": "DP2501", "item_1_validade_0": "2028-01-31",
             "item_1_lote_1": "DP2502", "item_1_validade_1": "2028-02-29",
             "item_2_importar": "1", "item_2_produto": b["seringa"].id, "item_2_fator": "1",
             "item_2_lote_0": "SR77", "item_2_validade_0": validade}
    dados.update(extra)
    return {k: v for k, v in dados.items() if v is not None}


def test_importacao_completa(auxiliar, base):
    resposta = _enviar(auxiliar, gerar_xml())
    nota = NotaFiscal.query.one()
    assert resposta.status_code == 302 and f"/estoque/nfe/{nota.id}" in resposta.location
    assert nota.situacao == "PENDENTE" and "<nfeProc" in nota.xml
    pagina = auxiliar.get(f"/estoque/nfe/{nota.id}").get_data(as_text=True)
    assert "Sugerido pelo código de barras (GTIN)" in pagina and "não reconhecido" in pagina
    resposta = auxiliar.post(f"/estoque/nfe/{nota.id}", data=_confirmacao(base), follow_redirects=True)
    assert "3 lote(s) deram entrada" in resposta.get_data(as_text=True)
    nota = db.session.get(NotaFiscal, nota.id)
    assert nota.situacao == "IMPORTADA" and nota.usuario.login == "aux" and nota.localizacao == base["sus"]
    lotes = {l.numero_lote: l for l in Lote.query.filter_by(nota_fiscal_id=nota.id)}
    assert lotes["DP2501"].saldo == 20 and lotes["DP2502"].saldo == 10  # 2 CX e 1 CX × 10 AMP
    assert lotes["DP2501"].custo_unitario == Decimal("2.55")  # R$ 25,50 por CX ÷ 10
    assert lotes["SR77"].saldo == 100 and lotes["SR77"].custo_unitario == Decimal("0.45")
    assert {m.documento for m in Movimentacao.query} == {"NF-e 1234/1"}
    de_para = ProdutoFornecedor.query.filter_by(codigo="DIP500").one()
    assert de_para.produto == base["dipirona"] and de_para.fator == 10
    assert auditoria.verificar_integridade()["ok"]


def test_nota_nao_pode_ser_importada_duas_vezes(client, base):
    _enviar(client, gerar_xml())
    nota = NotaFiscal.query.one()
    client.post(f"/estoque/nfe/{nota.id}", data=_confirmacao(base))
    resposta = _enviar(client, gerar_xml())
    assert resposta.status_code == 302
    assert "já foi importada" in client.get("/estoque/entrada").get_data(as_text=True)
    # Reenvio do formulário de confirmação também não duplica.
    client.post(f"/estoque/nfe/{nota.id}", data=_confirmacao(base))
    assert Lote.query.count() == 3


def test_proxima_nota_do_fornecedor_e_reconhecida_pelo_de_para(client, base):
    _enviar(client, gerar_xml(numero=1))
    client.post(f"/estoque/nfe/{NotaFiscal.query.one().id}", data=_confirmacao(base))
    base["dipirona"].gtin = None  # sem GTIN, só o de-para reconhece
    db.session.commit()
    _enviar(client, gerar_xml(numero=2))
    segunda = NotaFiscal.query.filter_by(numero="2").one()
    pagina = client.get(f"/estoque/nfe/{segunda.id}").get_data(as_text=True)
    assert "Sugerido pelo código do fornecedor" in pagina and 'value="10"' in pagina


@pytest.mark.parametrize("ajuste, trecho", [
    ({"item_1_produto": None}, "selecione o produto"),
    ({"item_2_lote_0": ""}, "informe o número do lote"),
    ({"item_2_validade_0": ""}, "informe a validade"),
    ({"item_2_validade_0": "2020-01-01"}, "vencido"),
    ({"item_1_fator": "0"}, "maior que zero"),
    ({"localizacao_id": None}, "local de entrada"),
])
def test_validacoes_da_conferencia_sao_atomicas(client, base, ajuste, trecho):
    _enviar(client, gerar_xml())
    nota = NotaFiscal.query.one()
    resposta = client.post(f"/estoque/nfe/{nota.id}", data=_confirmacao(base, **ajuste))
    assert trecho in resposta.get_data(as_text=True)
    assert Lote.query.count() == 0 and db.session.get(NotaFiscal, nota.id).situacao == "PENDENTE"


def test_item_desmarcado_nao_entra(client, base):
    _enviar(client, gerar_xml())
    dados = _confirmacao(base)
    del dados["item_2_importar"]
    client.post(f"/estoque/nfe/{NotaFiscal.query.one().id}", data=dados)
    assert {l.numero_lote for l in Lote.query} == {"DP2501", "DP2502"}


@pytest.mark.parametrize("xml, trecho", [
    (gerar_xml(situacao="110"), "não está autorizada"),
    (gerar_xml(com_protocolo=False), "protocolo de autorização"),
])
def test_nota_sem_autorizacao_e_recusada(client, base, xml, trecho):
    _enviar(client, xml)
    assert trecho in client.get("/estoque/entrada").get_data(as_text=True)
    assert NotaFiscal.query.count() == 0


def test_descartar_e_reenviar(client, base):
    _enviar(client, gerar_xml())
    nota = NotaFiscal.query.one()
    client.post(f"/estoque/nfe/{nota.id}/descartar")
    assert db.session.get(NotaFiscal, nota.id).situacao == "DESCARTADA"
    assert "Descartada" in client.get("/estoque/notas").get_data(as_text=True)
    _enviar(client, gerar_xml())
    assert NotaFiscal.query.one().situacao == "PENDENTE"


def test_importacao_exige_login(anonimo):
    assert _enviar(anonimo, gerar_xml()).status_code == 302
    assert NotaFiscal.query.count() == 0


def test_arquivo_grande_demais(client):
    resposta = _enviar(client, b"0" * (7 * 1024 * 1024))
    assert resposta.status_code == 413


def test_gtin_validado_no_cadastro(client, base):
    dados = {"tipo": "MEDICAMENTO", "nome_comercial": "Outro", "unidade_medida": "UN", "ativo": "on"}
    resposta = client.post("/cadastros/produtos/novo", data=dict(dados, gtin="7891234567890"))
    assert "GTIN) inválido" in resposta.get_data(as_text=True)
    resposta = client.post("/cadastros/produtos/novo", data=dict(dados, gtin="7891234567895"))
    assert "Já existe um produto com este código" in resposta.get_data(as_text=True)
