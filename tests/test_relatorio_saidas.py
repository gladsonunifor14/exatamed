from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from conftest import criar_usuario

from exatamed import estoque, relatorios
from exatamed.models import Localizacao, Movimentacao, Produto, Usuario, db

HOJE = date.today()


def _dias(n, hora=10):
    return datetime.combine(HOJE - timedelta(days=n), datetime.min.time()) + timedelta(hours=hora)


@pytest.fixture
def saidas(app):
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    particular = Localizacao.query.filter_by(nome="Farmácia Particular").one()
    soro = Produto(nome_comercial="Soro", unidade_medida="FR")
    luva = Produto(nome_comercial="Luva", tipo="MATERIAL", unidade_medida="CX")
    db.session.add_all([soro, luva])
    db.session.flush()
    validade = HOJE + timedelta(days=300)
    estoque.registrar_entrada(soro, sus, "S1", validade, 5, "2.00", data=_dias(60))
    estoque.registrar_entrada(soro, sus, "S2", validade, 20, "3.00", data=_dias(59))
    estoque.registrar_entrada(luva, particular, "L1", validade, 10, "10.00", data=_dias(60))
    estoque.registrar_saida(soro, sus, 1, "Consumo do setor", data=_dias(40))  # fora do período (sai de S1)
    estoque.registrar_saida(soro, sus, 8, "Avaria na embalagem", documento="OC-1", data=_dias(5))  # S1 4 + S2 4
    estoque.registrar_saida(soro, sus, 2, "Consumo do setor", data=_dias(4))
    estoque.registrar_saida(luva, particular, 1, "Consumo do setor", data=_dias(3))
    estoque.registrar_saida(soro, sus, 1, "Vencimento", data=_dias(2))
    db.session.commit()
    vencimento = Movimentacao.query.filter_by(tipo="SAIDA", motivo="Vencimento").one()
    estoque.estornar(vencimento, "Lançada por engano", criar_usuario("farma", Usuario.FARMACEUTICO))
    db.session.commit()
    return dict(sus=sus, particular=particular)


INICIO = HOJE - timedelta(days=29)


def test_detalhe_resumos_e_estornada(saidas):
    motivos, produtos, detalhe = relatorios.saidas_avulsas(INICIO, HOJE)
    linhas = [(l[1], l[2], l[5], l[8], l[9], l[12]) for l in detalhe.linhas]
    assert linhas == [
        ("Soro", "S1", 4, Decimal("8"), "Avaria na embalagem", ""),
        ("Soro", "S2", 4, Decimal("12"), "Avaria na embalagem", ""),
        ("Soro", "S2", 2, Decimal("6"), "Consumo do setor", ""),
        ("Luva", "L1", 1, Decimal("10"), "Consumo do setor", ""),
        ("Soro", "S2", 1, Decimal("3"), "Vencimento", f"Estornada em {HOJE:%d/%m/%Y}"),
    ]
    assert detalhe.destaques == {4: "text-muted text-decoration-line-through"}
    assert detalhe.rodape[8] == 36  # a estornada fica fora do total
    assert [(l[0], l[1], l[2], l[3]) for l in motivos.linhas] == [
        ("Avaria na embalagem", "Avaria / quebra", 2, 20), ("Consumo do setor", "Outras saídas", 2, 16)]
    assert motivos.rodape[3] == 36
    assert [(l[0], l[2], l[3]) for l in produtos.linhas] == [("Soro", 10, 26), ("Luva", 1, 10)]


def test_filtro_de_local_e_de_data(saidas):
    _, _, sus = relatorios.saidas_avulsas(INICIO, HOJE, saidas["sus"].id)
    assert {l[4] for l in sus.linhas} == {"Farmácia SUS"} and sus.rodape[8] == 26
    _, _, particular = relatorios.saidas_avulsas(INICIO, HOJE, saidas["particular"].id)
    assert [l[1] for l in particular.linhas] == ["Luva"]
    _, _, um_dia = relatorios.saidas_avulsas(HOJE - timedelta(days=4), HOJE - timedelta(days=4))
    assert [l[9] for l in um_dia.linhas] == ["Consumo do setor"]
    motivos, produtos, vazio = relatorios.saidas_avulsas(HOJE, HOJE)
    assert vazio.linhas == [] and motivos.linhas == [] and vazio.rodape[8] == 0


def test_tela_e_exportacao(client, auxiliar, saidas):
    indice = client.get("/relatorios/").get_data(as_text=True)
    assert "/relatorios/saidas_avulsas" in indice and "Saídas avulsas" in indice
    url = f"/relatorios/saidas_avulsas?inicio={INICIO.isoformat()}&fim={HOJE.isoformat()}"
    pagina = client.get(url + f"&localizacao_id={saidas['sus'].id}").get_data(as_text=True)
    assert "Resumo por motivo" in pagina and "Avaria na embalagem" in pagina and "Luva" not in pagina
    assert 'name="localizacao_id"' in pagina and 'name="inicio"' in pagina and 'name="fim"' in pagina
    csv = client.get(url + "&formato=csv").get_data(as_text=True)
    assert "Saídas avulsas do período" in csv and "Estornada em" in csv
    assert auxiliar.get(url).status_code == 200  # consulta, como os demais relatórios
