from datetime import date, datetime, timedelta

import pytest

from exatamed import estoque
from exatamed.estoque import EstoqueError
from exatamed.models import Dispensacao, Localizacao, Lote, Movimentacao, Paciente, Produto, db

AGORA = datetime.now().replace(second=0, microsecond=0)
FORMATO = "%Y-%m-%dT%H:%M"


def _antes(dias, horas=0):
    return AGORA - timedelta(days=dias, hours=horas)


@pytest.fixture
def base(app):
    """Soro: lote S0 (entrou há 30 dias, venceu há 2), S1 (entrou há 10 dias), S2 (entrou há 2 dias)."""
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    leito = Localizacao(nome="Leito 1")
    soro = Produto(nome_comercial="Soro", unidade_medida="FR")
    paciente = Paciente(nome="Ana Souza")
    db.session.add_all([leito, soro, paciente])
    db.session.flush()
    estoque.registrar_entrada(soro, sus, "S0", date.today() - timedelta(days=2), 3, "1", data=_antes(30))
    estoque.registrar_entrada(soro, sus, "S1", date.today() + timedelta(days=300), 5, "2", data=_antes(10))
    estoque.registrar_entrada(soro, sus, "S2", date.today() + timedelta(days=300), 10, "3", data=_antes(2))
    db.session.commit()
    return dict(sus=sus, leito=leito, soro=soro, paciente=paciente)


def _formulario(b, quantidade, data=None, sugerida=None, **extra):
    dados = {"paciente_id": b["paciente"].id, "origem_id": b["sus"].id, "destino_id": b["leito"].id,
             "item_produto": b["soro"].id, "item_quantidade": quantidade,
             "data_sugerida": sugerida or AGORA.strftime(FORMATO)}
    if data is not None:
        dados["data_dispensacao"] = data if isinstance(data, str) else data.strftime(FORMATO)
    dados.update(extra)
    return dados


def _consumo_por_lote(d):
    return {m.lote.numero_lote: -m.quantidade for m in d.itens_dispensados}


def test_dispensacao_retroativa_pela_tela(client, base):
    quando = _antes(3, horas=4)
    resposta = client.post("/estoque/dispensacao", data=_formulario(base, 4, quando), follow_redirects=True)
    pagina = resposta.get_data(as_text=True)
    d = Dispensacao.query.one()
    assert d.data == quando and d.retroativa and d.numero_formatado == f"00001/{quando.year}"
    assert {m.data for m in d.movimentacoes} == {quando}
    assert "Lançamento retroativo, registrado em" in pagina and quando.strftime("%d/%m/%Y %H:%M") in pagina
    # Há 3 dias S0 ainda estava válido (venceu há 2) e S2 não tinha entrado: PEPS daquele dia.
    assert _consumo_por_lote(d) == {"S0": 3, "S1": 1}


def test_data_futura_e_recusada(client, base):
    amanha = AGORA + timedelta(days=1)
    resposta = client.post("/estoque/dispensacao", data=_formulario(base, 1, amanha))
    assert "A data da dispensação não pode ser futura" in resposta.get_data(as_text=True)
    daqui_a_pouco = AGORA + timedelta(hours=2)
    resposta = client.post("/estoque/dispensacao", data=_formulario(base, 1, daqui_a_pouco))
    assert "não pode ser futura" in resposta.get_data(as_text=True)
    assert Dispensacao.query.count() == 0 and Movimentacao.query.filter_by(tipo="DISPENSACAO").count() == 0
    with pytest.raises(EstoqueError, match="não pode ser futura"):
        estoque.dispensar(base["paciente"], base["sus"], base["leito"], [(base["soro"], 1)],
                          data=datetime.now() + timedelta(minutes=5))


def test_campo_sem_alteracao_registra_agora(client, base):
    sugerida = (AGORA - timedelta(minutes=3)).strftime(FORMATO)  # hora em que a tela foi aberta
    client.post("/estoque/dispensacao", data=_formulario(base, 2, sugerida, sugerida=sugerida))
    d = Dispensacao.query.one()
    assert not d.retroativa and abs(d.data - datetime.now()) < timedelta(minutes=1)
    assert _consumo_por_lote(d) == {"S1": 2}  # PEPS de hoje: S0 vencido não sai


def test_lote_que_entrou_depois_nao_e_usado(base):
    # Há 5 dias havia S0 (3) e S1 (5): S2 (10) só entrou há 2 dias.
    with pytest.raises(EstoqueError, match=r"disponível 8 FR \(lotes que já estavam em estoque"):
        estoque.dispensar(base["paciente"], base["sus"], base["leito"], [(base["soro"], 9)], data=_antes(5))
    db.session.rollback()
    hoje = estoque.dispensar(base["paciente"], base["sus"], base["leito"], [(base["soro"], 9)])
    assert _consumo_por_lote(hoje) == {"S1": 5, "S2": 4}  # hoje S0 está vencido


def test_lote_valido_na_data_retroativa_pode_sair(base):
    # S0 venceu há 2 dias, mas estava válido há 5 dias: a dispensação retroativa pode usá-lo.
    d = estoque.dispensar(base["paciente"], base["sus"], base["leito"], [(base["soro"], 4)], data=_antes(5))
    db.session.commit()
    assert _consumo_por_lote(d) == {"S0": 3, "S1": 1}
    assert Lote.query.filter_by(numero_lote="S0").one().saldo == 0


def test_retroativa_no_ano_anterior_usa_a_numeracao_daquele_ano(base):
    virada = datetime(AGORA.year - 1, 12, 30, 14, 0)
    estoque.registrar_entrada(base["soro"], base["sus"], "V1", date.today() + timedelta(days=300), 5, "1",
                              data=virada - timedelta(days=5))
    d = estoque.dispensar(base["paciente"], base["sus"], base["leito"], [(base["soro"], 1)], data=virada)
    db.session.commit()
    assert d.numero_formatado == f"00001/{AGORA.year - 1}"
    atual = estoque.dispensar(base["paciente"], base["sus"], base["leito"], [(base["soro"], 1)])
    db.session.commit()
    assert atual.numero_formatado == f"00001/{AGORA.year}"


def test_data_invalida(client, base):
    resposta = client.post("/estoque/dispensacao", data=_formulario(base, 1, "17/10/2026 10:00"))
    assert "Data e hora da dispensação inválidas" in resposta.get_data(as_text=True)
    assert Dispensacao.query.count() == 0


def test_formulario_tem_o_campo_com_limite(client, base):
    pagina = client.get("/estoque/dispensacao").get_data(as_text=True)
    assert 'type="datetime-local"' in pagina and 'name="data_dispensacao"' in pagina and 'max="' in pagina
