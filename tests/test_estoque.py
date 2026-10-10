from datetime import date, datetime, timedelta

import pytest

from exatamed import estoque
from exatamed.estoque import EstoqueError
from exatamed.models import Localizacao, Medico, Movimentacao, Paciente, Produto, db

HOJE = date.today()


@pytest.fixture
def base(app):
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    leito = Localizacao(nome="Leito 1")
    produto = Produto(nome_comercial="Novalgina", principio_ativo="Dipirona sódica", unidade_medida="AMP",
                      alertas_alergia="pirazolonas", estoque_minimo=10, estoque_maximo=50)
    paciente = Paciente(nome="Maria", alergias="dipirona")
    outro = Paciente(nome="José")
    medico = Medico(nome="Dra. Ana", crm="123", uf_crm="CE")
    db.session.add_all([leito, produto, paciente, outro, medico])
    db.session.flush()
    return dict(sus=sus, leito=leito, produto=produto, paciente=paciente, outro=outro, medico=medico)


def _entrada(b, lote, qtd, custo, dias_atras, validade_dias=365, local=None):
    return estoque.registrar_entrada(
        b["produto"], local or b["sus"], lote, HOJE + timedelta(days=validade_dias), qtd, custo,
        data=datetime.now() - timedelta(days=dias_atras))


def test_locais_principais_criados(app):
    nomes = {l.nome for l in Localizacao.query.filter_by(principal=True)}
    assert nomes == {"Farmácia SUS", "Farmácia Particular"}


def test_baixa_peps_consome_lote_mais_antigo_primeiro(base):
    _entrada(base, "NOVO", 10, 3.0, dias_atras=1)
    _entrada(base, "ANTIGO", 5, 2.0, dias_atras=10)
    movs = estoque.registrar_saida(base["produto"], base["sus"], 8, motivo="Consumo")
    assert [(m.lote.numero_lote, -m.quantidade, m.custo_unitario) for m in movs] == [
        ("ANTIGO", 5, 2.0), ("NOVO", 3, 3.0)]
    assert sum(m.custo_total for m in movs) == pytest.approx(5 * 2.0 + 3 * 3.0)
    assert estoque.saldo(base["produto"].id) == 7


def test_saldo_insuficiente_nao_altera_estoque(base):
    _entrada(base, "A", 5, 1.0, dias_atras=1)
    with pytest.raises(EstoqueError, match="Saldo insuficiente"):
        estoque.registrar_saida(base["produto"], base["sus"], 6, motivo="x")
    assert estoque.saldo(base["produto"].id) == 5


def test_lote_vencido_nao_e_consumido(base):
    _entrada(base, "VENCIDO", 5, 1.0, dias_atras=30, validade_dias=-1)
    _entrada(base, "BOM", 5, 2.0, dias_atras=1)
    movs = estoque.registrar_saida(base["produto"], base["sus"], 5, motivo="x")
    assert [m.lote.numero_lote for m in movs] == ["BOM"]
    with pytest.raises(EstoqueError):
        estoque.registrar_saida(base["produto"], base["sus"], 1, motivo="x")


def test_transferencia_preserva_custo_e_ordem_peps(base):
    _entrada(base, "A", 5, 2.0, dias_atras=10)
    _entrada(base, "B", 5, 4.0, dias_atras=1)
    estoque.transferir(base["produto"], base["sus"], base["leito"], 7)
    assert estoque.saldo(base["produto"].id, base["sus"].id) == 3
    assert estoque.saldo(base["produto"].id, base["leito"].id) == 7
    movs = estoque.registrar_saida(base["produto"], base["leito"], 6, motivo="x")
    assert [(m.lote.numero_lote, m.custo_unitario) for m in movs] == [("A", 2.0), ("B", 4.0)]


def test_alerta_de_alergia_bloqueia_ate_confirmacao(base):
    _entrada(base, "A", 10, 1.0, dias_atras=1)
    itens = [(base["produto"], 2)]
    with pytest.raises(EstoqueError, match="ALERTA DE ALERGIA"):
        estoque.dispensar(base["paciente"], base["sus"], base["leito"], itens)
    disp = estoque.dispensar(base["paciente"], base["sus"], base["leito"], itens, confirmar_alergia=True)
    assert "alerta de alergia" in disp.observacao
    assert estoque.saldo(base["produto"].id) == 8


def test_alergia_por_classe_terapeutica(base):
    base["outro"].alergias = "Pirazolonas"
    assert estoque.verificar_alergias(base["outro"], base["produto"]) == ["pirazolonas"]
    base["outro"].alergias = "látex"
    assert estoque.verificar_alergias(base["outro"], base["produto"]) == []


def test_controle_especial_exige_medico_e_prescricao(base):
    base["produto"].controle_especial = "A1"
    _entrada(base, "A", 10, 1.0, dias_atras=1)
    with pytest.raises(EstoqueError, match="controle especial"):
        estoque.dispensar(base["outro"], base["sus"], base["leito"], [(base["produto"], 1)])
    disp = estoque.dispensar(base["outro"], base["sus"], base["leito"], [(base["produto"], 1)],
                             medico=base["medico"], prescricao="RX-1")
    assert disp.medico is base["medico"]


def test_dispensacao_valida_saldo_somando_itens_repetidos(base):
    _entrada(base, "A", 3, 1.0, dias_atras=1)
    with pytest.raises(EstoqueError, match="Saldo insuficiente"):
        estoque.dispensar(base["outro"], base["sus"], base["leito"], [(base["produto"], 2), (base["produto"], 2)])
    assert Movimentacao.query.filter_by(tipo=Movimentacao.DISPENSACAO).count() == 0


def test_ajuste_de_inventario(base):
    lote = _entrada(base, "A", 10, 1.5, dias_atras=1)
    mov = estoque.ajustar_inventario(lote, 7, "Contagem mensal")
    assert mov.quantidade == -3 and lote.saldo == 7
    assert estoque.ajustar_inventario(lote, 7, "sem diferença") is None
