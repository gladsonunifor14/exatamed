from exatamed.demo import popular
from exatamed.models import Dispensacao, Paciente, Produto


def test_todas_as_paginas_renderizam(client, app):
    popular()
    paginas = ["/", "/estoque/entrada", "/estoque/saida", "/estoque/transferencia", "/estoque/dispensacao",
               "/estoque/lotes", "/estoque/movimentacoes", "/estoque/inventario?localizacao_id=1",
               "/relatorios/", "/estoque/dispensacao/1"]
    for chave in ("pacientes", "medicos", "produtos", "localizacoes"):
        paginas += [f"/cadastros/{chave}/", f"/cadastros/{chave}/novo", f"/cadastros/{chave}/1/editar"]
    for chave in ("consumo_diario", "resumo_dispensacao", "consumo_local", "consumo_paciente",
                  "pedido_compra", "inventario"):
        paginas += [f"/relatorios/{chave}", f"/relatorios/{chave}?formato=csv"]
    for url in paginas:
        resposta = client.get(url)
        assert resposta.status_code == 200, url


def test_cadastro_paciente_valida_cpf(client, app):
    dados = {"nome": "Teste", "cpf": "111.111.111-11"}
    assert client.post("/cadastros/pacientes/novo", data=dados).status_code == 422
    dados["cpf"] = "52998224725"
    assert client.post("/cadastros/pacientes/novo", data=dados).status_code == 302
    assert Paciente.query.one().cpf == "529.982.247-25"


def test_paciente_menor_exige_responsavel(client, app):
    dados = {"nome": "Criança", "data_nascimento": "2020-01-01"}
    assert client.post("/cadastros/pacientes/novo", data=dados).status_code == 422
    dados.update(responsavel="Mãe", grau_parentesco="Mãe")
    assert client.post("/cadastros/pacientes/novo", data=dados).status_code == 302


def test_fluxo_entrada_e_dispensacao_pela_web(client, app):
    client.post("/cadastros/localizacoes/novo", data={"nome": "Leito 9", "ativo": "on"})
    client.post("/cadastros/produtos/novo", data={"tipo": "MEDICAMENTO", "nome_comercial": "Paracetamol",
                                                   "unidade_medida": "CP", "estoque_minimo": "5",
                                                   "estoque_maximo": "20", "ativo": "on"})
    client.post("/cadastros/pacientes/novo", data={"nome": "Paciente X"})
    produto = Produto.query.one()
    client.post("/estoque/entrada", data={"produto_id": produto.id, "localizacao_id": 1, "numero_lote": "L1",
                                          "validade": "2099-12-31", "quantidade": "10", "custo_unitario": "0,50"})
    assert produto.saldo == 10
    resposta = client.post("/estoque/dispensacao", data={
        "paciente_id": Paciente.query.one().id, "origem_id": 1, "destino_id": 3,
        "item_produto": [produto.id], "item_quantidade": ["4"]})
    assert resposta.status_code == 302
    assert Dispensacao.query.one().custo_total == 2.0
    assert Produto.query.one().saldo == 6


def test_local_principal_nao_pode_ser_excluido(client, app):
    client.post("/cadastros/localizacoes/1/excluir")
    assert client.get("/cadastros/localizacoes/").data.decode().count("Farmácia SUS") >= 1


def test_demo_nao_duplica_dados(app):
    assert popular() is True
    assert popular() is False
    assert Paciente.query.count() == 3
