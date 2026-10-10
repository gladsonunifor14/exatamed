from datetime import date, datetime, timedelta

import pytest

from exatamed import estoque
from exatamed.estoque import EstoqueError
from exatamed.models import Dispensacao, Localizacao, Paciente, Produto, db


@pytest.fixture
def base(app):
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    leito, uti = Localizacao(nome="Leito 1"), Localizacao(nome="UTI")
    produto = Produto(nome_comercial="Soro")
    paciente = Paciente(nome="Ana")
    db.session.add_all([leito, uti, produto, paciente])
    db.session.flush()
    estoque.registrar_entrada(produto, sus, "L1", date.today() + timedelta(days=400), 100, 1.0,
                              data=datetime(2025, 1, 1))
    db.session.commit()
    return dict(sus=sus, leito=leito, uti=uti, produto=produto, paciente=paciente)


def _dispensar(b, data=None, origem=None):
    return estoque.dispensar(b["paciente"], origem or b["sus"], b["leito"], [(b["produto"], 1)], data=data)


# ----------------------------------------------------------------- numeração n/ano

def test_numeracao_sequencial_no_formato_numero_ano(base):
    d1, d2 = _dispensar(base, datetime(2026, 3, 1)), _dispensar(base, datetime(2026, 3, 2))
    assert (d1.numero_formatado, d2.numero_formatado) == ("00001/2026", "00002/2026")


def test_numeracao_reinicia_a_cada_ano(base):
    _dispensar(base, datetime(2025, 12, 31))
    _dispensar(base, datetime(2025, 12, 31))
    assert _dispensar(base, datetime(2026, 1, 1)).numero_formatado == "00001/2026"
    assert _dispensar(base, datetime(2025, 12, 31, 23)).numero_formatado == "00003/2025"


def test_banco_impede_numero_repetido_no_mesmo_ano(base):
    _dispensar(base, datetime(2026, 5, 1))
    db.session.commit()
    repetida = Dispensacao(numero=1, ano=2026, paciente=base["paciente"], origem=base["sus"],
                           destino=base["leito"])
    db.session.add(repetida)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_dispensacao_pela_web_mostra_o_numero(client, base, monkeypatch):
    dados = {"paciente_id": base["paciente"].id, "origem_id": base["sus"].id, "destino_id": base["leito"].id,
             "item_produto": [base["produto"].id], "item_quantidade": ["1"]}
    resposta = client.post("/estoque/dispensacao", data=dados, follow_redirects=True)
    ano = date.today().year
    assert f"Dispensação nº 00001/{ano}" in resposta.get_data(as_text=True)
    # Simula outra dispensação gravada ao mesmo tempo, que "pegou" o número antes:
    # a primeira tentativa colide no índice único e o sistema tenta de novo.
    original = Dispensacao.proximo_numero
    chamadas = []

    def concorrente(ano_):
        chamadas.append(ano_)
        return 1 if len(chamadas) == 1 else original(ano_)
    monkeypatch.setattr(Dispensacao, "proximo_numero", staticmethod(concorrente))
    resposta = client.post("/estoque/dispensacao", data=dados, follow_redirects=True)
    assert f"Dispensação nº 00002/{ano}" in resposta.get_data(as_text=True)
    assert len(chamadas) == 2
    assert client.get("/").get_data(as_text=True).count(f"/{ano}</a>") == 2


# ----------------------------------------------------------------- farmácia de origem

def test_dispensacao_so_sai_das_farmacias_principais(base):
    estoque.transferir(base["produto"], base["sus"], base["uti"], 10)
    with pytest.raises(EstoqueError, match="Farmácia SUS ou da Farmácia Particular"):
        _dispensar(base, origem=base["uti"])
    assert _dispensar(base).origem.principal


def test_formulario_lista_apenas_farmacias_principais_como_origem(client, base):
    html = client.get("/estoque/dispensacao").get_data(as_text=True)
    origem = html.split('name="origem_id"')[1].split("</select>")[0]
    destino = html.split('name="destino_id"')[1].split("</select>")[0]
    assert "Farmácia SUS" in origem and "Farmácia Particular" in origem
    assert "Leito 1" not in origem and "UTI" not in origem
    assert "Leito 1" in destino and "UTI" in destino


# ----------------------------------------------------------------- permissões de Localização

def test_auxiliar_so_consulta_localizacoes(auxiliar, base):
    leito_id = base["leito"].id
    assert auxiliar.get("/cadastros/localizacoes/").status_code == 200
    assert "Novo" not in auxiliar.get("/cadastros/localizacoes/").get_data(as_text=True).split("<table")[0]
    assert auxiliar.get("/cadastros/localizacoes/novo").status_code == 403
    assert auxiliar.post("/cadastros/localizacoes/novo", data={"nome": "Leito 9", "ativo": "on"}).status_code == 403
    assert auxiliar.get(f"/cadastros/localizacoes/{leito_id}/editar").status_code == 403
    assert auxiliar.post(f"/cadastros/localizacoes/{leito_id}/editar", data={"nome": "X"}).status_code == 403
    assert auxiliar.post(f"/cadastros/localizacoes/{leito_id}/excluir").status_code == 403
    assert Localizacao.query.filter_by(nome="Leito 9").count() == 0
    assert db.session.get(Localizacao, leito_id).nome == "Leito 1"


@pytest.mark.parametrize("perfil", ["client", "farmaceutico"])
def test_farmaceutico_e_admin_gerenciam_localizacoes(perfil, request, base):
    cliente = request.getfixturevalue(perfil)
    assert cliente.post("/cadastros/localizacoes/novo", data={"nome": "Leito 9", "ativo": "on"}).status_code == 302
    novo = Localizacao.query.filter_by(nome="Leito 9").one()
    assert cliente.post(f"/cadastros/localizacoes/{novo.id}/editar",
                        data={"nome": "Leito 10", "ativo": "on"}).status_code == 302
    assert cliente.post(f"/cadastros/localizacoes/{novo.id}/excluir").status_code == 302
    assert Localizacao.query.filter(Localizacao.nome.in_(["Leito 9", "Leito 10"])).count() == 0


# ----------------------------------------------------------------- CEP

def test_busca_de_cep_nos_cadastros_com_endereco(client):
    for chave in ("pacientes", "medicos"):
        assert "js/cep.js" in client.get(f"/cadastros/{chave}/novo").get_data(as_text=True)
    assert "js/cep.js" not in client.get("/cadastros/produtos/novo").get_data(as_text=True)
    assert client.get("/static/js/cep.js").status_code == 200
