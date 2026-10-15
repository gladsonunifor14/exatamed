from datetime import date, datetime, timedelta

import pytest
from conftest import SENHA, criar_usuario

from exatamed import auditoria, estoque, relatorios
from exatamed.models import Localizacao, Lote, Medico, Movimentacao, Paciente, Produto, Usuario, db

VALIDADE = date.today() + timedelta(days=300)


@pytest.fixture
def base(app):
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    uti = Localizacao(nome="UTI")
    soro = Produto(nome_comercial="Soro", unidade_medida="FR")
    morfina = Produto(nome_comercial="Dimorf", principio_ativo="Morfina", controle_especial="A1", unidade_medida="AMP")
    midazolam = Produto(nome_comercial="Dormonid", principio_ativo="Midazolam", controle_especial="B1",
                        unidade_medida="AMP")
    paciente, medico = Paciente(nome="Ana Souza"), Medico(nome="Dr. Rui", crm="123", uf_crm="CE")
    db.session.add_all([uti, soro, morfina, midazolam, paciente, medico])
    db.session.flush()
    estoque.registrar_entrada(soro, sus, "S1", VALIDADE, 10, "2.00", data=datetime.now() - timedelta(days=2))
    estoque.registrar_entrada(morfina, sus, "M1", VALIDADE, 20, "5.00", data=datetime.now() - timedelta(days=2))
    estoque.registrar_entrada(midazolam, sus, "D1", VALIDADE, 5, "3.00", data=datetime.now() - timedelta(days=2))
    db.session.commit()
    return dict(sus=sus, uti=uti, soro=soro, morfina=morfina, midazolam=midazolam, paciente=paciente, medico=medico)


def _mov(tipo, produto, **filtro):
    return Movimentacao.query.filter_by(tipo=tipo, produto_id=produto.id, **filtro).order_by(Movimentacao.id).first()


def _estornar(cliente, mov, autorizador="admin", senha=SENHA, motivo="Lançada em duplicidade", **extra):
    return cliente.post(f"/estoque/movimentacoes/{mov.id}/estornar", follow_redirects=True,
                        data=dict(motivo=motivo, autorizador=autorizador, senha=senha, **extra))


def _lote(numero, local):
    return Lote.query.filter_by(numero_lote=numero, localizacao_id=local.id).one()


def test_estorno_de_entrada(client, base):
    entrada = _mov("ENTRADA", base["soro"])
    resposta = _estornar(client, entrada)
    assert "1 lançamento(s) inverso(s) registrado(s), autorizado(s) por admin" in resposta.get_data(as_text=True)
    assert _lote("S1", base["sus"]).saldo == 0
    estorno = _mov("ESTORNO_MOV", base["soro"])
    assert estorno.origem == entrada and estorno.quantidade == -10 and estorno.custo_unitario == 2
    assert estorno.tipo_descricao == "Estorno de entrada"
    assert estorno.motivo == "Estorno autorizado por admin (Administrador(a)): Lançada em duplicidade"
    assert auditoria.verificar_integridade()["ok"]
    pagina = client.get(f"/estoque/movimentacoes?produto_id={base['soro'].id}").get_data(as_text=True)
    assert "Estornada" in pagina and "Estorno de entrada" in pagina
    # Não estorna duas vezes nem estorna o estorno.
    assert "já foi estornada" in client.get(f"/estoque/movimentacoes/{entrada.id}/estornar").get_data(as_text=True)
    _estornar(client, entrada)
    assert "já é um estorno" in client.get(f"/estoque/movimentacoes/{estorno.id}/estornar").get_data(as_text=True)
    _estornar(client, estorno)
    assert Movimentacao.query.filter_by(tipo="ESTORNO_MOV").count() == 1 and _lote("S1", base["sus"]).saldo == 0


def test_entrada_ja_consumida_nao_e_estornada(client, base):
    estoque.registrar_saida(base["soro"], base["sus"], 3, "Consumo do setor")
    db.session.commit()
    resposta = _estornar(client, _mov("ENTRADA", base["soro"]))
    assert "já foi movimentado (saldo atual 7 FR, estorno de 10)" in resposta.get_data(as_text=True)
    assert _lote("S1", base["sus"]).saldo == 7 and _mov("ESTORNO_MOV", base["soro"]) is None


def test_estorno_de_saida_abate_o_consumo(client, base):
    estoque.registrar_saida(base["soro"], base["sus"], 4, "Consumo do setor")
    db.session.commit()
    _estornar(client, _mov("SAIDA", base["soro"]))
    assert _lote("S1", base["sus"]).saldo == 10
    estorno = _mov("ESTORNO_SAIDA", base["soro"])
    assert estorno.quantidade == 4 and estorno.tipo_descricao == "Estorno de saída"
    consumo = sum(m.consumo_quantidade for m in Movimentacao.query.filter(
        Movimentacao.tipo.in_(Movimentacao.CONSUMO)))
    assert consumo == 0
    (dias, _) = relatorios.consumo_diario(date.today(), date.today())
    assert dias.rodape[4] == 0  # custo das saídas avulsas


@pytest.mark.parametrize("pela_chegada", [False, True])
def test_estorno_de_transferencia_desfaz_as_duas_partes(client, base, pela_chegada):
    estoque.transferir(base["morfina"], base["sus"], base["uti"], 6)
    db.session.commit()
    saida = _mov("TRANSFERENCIA", base["morfina"], localizacao_id=base["sus"].id)
    chegada = _mov("TRANSFERENCIA", base["morfina"], localizacao_id=base["uti"].id)
    assert chegada.origem == saida
    _estornar(client, chegada if pela_chegada else saida)
    assert _lote("M1", base["sus"]).saldo == 20 and _lote("M1", base["uti"]).saldo == 0
    assert {m.origem_id for m in Movimentacao.query.filter_by(tipo="ESTORNO_MOV")} == {saida.id, chegada.id}
    assert auditoria.verificar_integridade()["ok"]
    # Transferência e estorno são internos: não entram na escrituração de controlados.
    (livro,) = relatorios.livro_controlados(date.today() - timedelta(days=5), date.today(), base["morfina"].id)
    assert [l[1] for l in livro.linhas] == ["Saldo anterior", "Entrada"]


def test_transferencia_antiga_sem_ligacao_tambem_e_estornada(client, base):
    estoque.transferir(base["soro"], base["sus"], base["uti"], 2)
    db.session.commit()
    chegada = _mov("TRANSFERENCIA", base["soro"], localizacao_id=base["uti"].id)
    db.session.execute(db.update(Movimentacao).where(Movimentacao.id == chegada.id).values(origem_id=None))
    db.session.commit()
    _estornar(client, _mov("TRANSFERENCIA", base["soro"], localizacao_id=base["sus"].id))
    assert _lote("S1", base["sus"]).saldo == 10 and _lote("S1", base["uti"]).saldo == 0


def test_estorno_de_ajuste_e_de_dispensacao(client, base):
    estoque.ajustar_inventario(_lote("S1", base["sus"]), 8, "Contagem")
    db.session.commit()
    _estornar(client, _mov("AJUSTE", base["soro"]))
    assert _lote("S1", base["sus"]).saldo == 10
    d = estoque.dispensar(base["paciente"], base["sus"], base["uti"], [(base["morfina"], 3)],
                          medico=base["medico"], prescricao="RX-1")
    db.session.commit()
    resposta = _estornar(client, _mov("DISPENSACAO", base["morfina"]))
    assert "registrado(s)" in resposta.get_data(as_text=True)
    devolucao = _mov("ESTORNO", base["morfina"])
    assert devolucao.quantidade == 3 and devolucao.dispensacao == d and "autorizado por admin" in devolucao.motivo
    assert _lote("M1", base["sus"]).saldo == 20
    assert "Devolvida" in client.get("/estoque/movimentacoes").get_data(as_text=True)


def test_estorno_exige_senha_de_farmaceutico_ou_admin(client, auxiliar, base):
    criar_usuario("farma", Usuario.FARMACEUTICO)
    entrada = _mov("ENTRADA", base["soro"])
    resposta = _estornar(auxiliar, entrada, autorizador="farma", senha="errada")
    assert resposta.status_code == 422 and "Usuário ou senha inválidos" in resposta.get_data(as_text=True)
    assert Usuario.query.filter_by(login="farma").one().tentativas_falhas == 1
    resposta = _estornar(auxiliar, entrada, autorizador="aux")
    assert "aux não pode autorizar esta operação" in resposta.get_data(as_text=True)
    resposta = _estornar(auxiliar, entrada, motivo="")
    assert "Informe o motivo do estorno" in resposta.get_data(as_text=True)
    assert _mov("ESTORNO_MOV", base["soro"]) is None
    # O auxiliar pede, o farmacêutico autoriza com a própria senha.
    _estornar(auxiliar, entrada, autorizador="farma")
    estorno = _mov("ESTORNO_MOV", base["soro"])
    assert estorno.usuario.login == "aux" and "autorizado por farma" in estorno.motivo
    assert Usuario.query.filter_by(login="farma").one().tentativas_falhas == 0


def test_senha_errada_repetida_bloqueia_quem_autoriza(client, base):
    entrada = _mov("ENTRADA", base["soro"])
    for _ in range(5):
        _estornar(client, entrada, senha="errada")
    resposta = _estornar(client, entrada)
    assert "Usuário bloqueado por excesso de tentativas" in resposta.get_data(as_text=True)
    assert _mov("ESTORNO_MOV", base["soro"]) is None


def test_tela_de_estorno(client, base):
    entrada = _mov("ENTRADA", base["morfina"])
    pagina = client.get(f"/estoque/movimentacoes/{entrada.id}/estornar").get_data(as_text=True)
    assert "Autorização do farmacêutico ou administrador" in pagina and 'value="admin"' in pagina
    assert 'type="password"' in pagina
    lista = client.get("/estoque/movimentacoes").get_data(as_text=True)
    assert f"/estoque/movimentacoes/{entrada.id}/estornar" in lista


# ------------------------------------------------------------------- filtro do livro de controlados

def test_livro_de_controlados_filtra_por_classificacao(client, base):
    assert {t.titulo.split(" — ")[0] for t in relatorios.livro_controlados(date.today(), date.today(), lista="B1")} \
        == {str(base["midazolam"])}
    assert len(relatorios.livro_controlados(date.today(), date.today())) == 2
    (vazio,) = relatorios.livro_controlados(date.today(), date.today(), lista="C1")
    assert vazio.titulo == "Nenhum produto de controle especial da lista C1 cadastrado"
    pagina = client.get("/relatorios/livro_controlados?lista=A1").get_data(as_text=True)
    assert "Todas as classificações" in pagina and "Todos os controlados" in pagina
    assert '<option value="A1" selected>' in pagina
    assert "Dimorf" in pagina and "lista B1" not in pagina
    csv = client.get("/relatorios/livro_controlados?lista=B1&formato=csv").get_data(as_text=True)
    assert "Dormonid" in csv and "Dimorf" not in csv
