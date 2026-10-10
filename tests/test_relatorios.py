from datetime import date, datetime, timedelta

from exatamed import estoque, relatorios
from exatamed.models import Localizacao, Paciente, Produto, db

HOJE = date.today()


def _cenario():
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    leito1, leito2 = Localizacao(nome="Leito 1"), Localizacao(nome="Leito 2")
    p = Produto(nome_comercial="Soro", unidade_medida="FR", estoque_minimo=20, estoque_maximo=100)
    ana, bia = Paciente(nome="Ana"), Paciente(nome="Bia")
    db.session.add_all([leito1, leito2, p, ana, bia])
    db.session.flush()
    estoque.registrar_entrada(p, sus, "L1", HOJE + timedelta(days=300), 30, 2.0,
                              data=datetime.now() - timedelta(days=5))
    ontem = datetime.now() - timedelta(days=1)
    estoque.dispensar(ana, sus, leito1, [(p, 4)], data=ontem)
    estoque.dispensar(bia, sus, leito2, [(p, 6)])
    db.session.commit()
    return p


def test_consumo_diario(app):
    _cenario()
    dias, produtos = relatorios.consumo_diario(HOJE - timedelta(days=7), HOJE)
    assert len(dias.linhas) == 2
    assert dias.rodape[-1] == 20.0
    assert produtos.linhas[0][3] == 10


def test_resumo_e_consumo_por_local_e_paciente(app):
    _cenario()
    resumo, detalhe = relatorios.resumo_dispensacao(HOJE - timedelta(days=7), HOJE)
    assert resumo.rodape[1] == 2 and len(detalhe.linhas) == 2
    local = relatorios.consumo_por_local(HOJE - timedelta(days=7), HOJE)[0]
    assert {l[0]: l[4] for l in local.linhas} == {"Leito 1": 8.0, "Leito 2": 12.0}
    paciente = relatorios.consumo_por_paciente(HOJE - timedelta(days=7), HOJE)[0]
    assert {l[0]: l[6] for l in paciente.linhas} == {"Ana": 8.0, "Bia": 12.0}


def test_pedido_de_compra(app):
    _cenario()
    (dado,) = relatorios.calcular_pedido_compra(dias_historico=10)
    assert dado["saldo"] == 20
    assert dado["situacao"] == "No ponto de pedido"
    assert dado["sugestao"] == 80
    assert dado["custo_estimado"] == 160
    assert dado["cmd"] == 1.0


def test_inventario_valoriza_pelo_custo_peps(app):
    _cenario()
    resumo, detalhe = relatorios.inventario()
    assert resumo.rodape[-1] == 40.0
    assert detalhe.linhas[0][7] == 20
