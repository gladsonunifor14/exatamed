from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from exatamed import auditoria, estoque, relatorios
from exatamed.estoque import EstoqueError
from exatamed.models import Dispensacao, Localizacao, Lote, Medico, Paciente, Produto, db


@pytest.fixture
def base(app):
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    leito, uti = Localizacao(nome="Leito 1"), Localizacao(nome="UTI")
    soro = Produto(nome_comercial="Soro", estoque_minimo=1, estoque_maximo=100)
    morfina = Produto(nome_comercial="Dimorf", principio_ativo="Morfina", controle_especial="A1")
    paciente = Paciente(nome="Ana Souza")
    medico = Medico(nome="Dr. Rui", crm="123", uf_crm="CE")
    db.session.add_all([leito, uti, soro, morfina, paciente, medico])
    db.session.flush()
    estoque.registrar_entrada(soro, sus, "S1", date.today() + timedelta(days=300), 10, "2.00",
                              data=datetime.now() - timedelta(days=5))
    estoque.registrar_entrada(soro, sus, "S2", date.today() + timedelta(days=300), 10, "3.00",
                              data=datetime.now() - timedelta(days=4))
    estoque.registrar_entrada(morfina, sus, "M1", date.today() + timedelta(days=300), 20, "5.00",
                              data=datetime.now() - timedelta(days=10), documento="NF 77")
    db.session.commit()
    return dict(sus=sus, leito=leito, uti=uti, soro=soro, morfina=morfina, paciente=paciente, medico=medico)


def _dispensar(b, itens, **extra):
    d = estoque.dispensar(b["paciente"], b["sus"], b["leito"], itens, medico=b["medico"], prescricao="RX-9", **extra)
    db.session.commit()
    return d


# ------------------------------------------------------------------- devolução / estorno

def test_devolucao_parcial_volta_ao_mesmo_lote_com_mesmo_custo(base):
    d = _dispensar(base, [(base["soro"], 12)])  # 10 do lote S1 (R$ 2) + 2 do S2 (R$ 3)
    assert d.custo_total == Decimal("26")
    s2 = next(m for m in d.itens_dispensados if m.lote.numero_lote == "S2")
    estoque.devolver(d, {s2.id: "1"}, "Suspensão da prescrição")
    db.session.commit()
    assert db.session.get(Lote, s2.lote_id).saldo == Decimal("9")
    assert d.custo_total == Decimal("23") and d.situacao == "Devolução parcial"
    devolucao = d.devolucoes[0]
    assert devolucao.origem_id == s2.id and devolucao.custo_unitario == Decimal("3") and devolucao.quantidade == 1


def test_estorno_total_pela_web_e_consumo_liquido(farmaceutico, base):
    d = _dispensar(base, [(base["soro"], 4)])
    resposta = farmaceutico.post(f"/estoque/dispensacao/{d.id}/devolver",
                                 data={"tudo": "1", "motivo": "Erro de dispensação"})
    assert resposta.status_code == 302
    d = db.session.get(Dispensacao, d.id)
    assert d.situacao == "Devolvida integralmente" and d.custo_total == 0
    assert estoque.saldo(base["soro"].id) == 20
    hoje = date.today()
    dias, produtos = relatorios.consumo_diario(hoje - timedelta(days=1), hoje)
    assert dias.rodape[-1] == 0  # consumo líquido zerado
    assert relatorios.consumo_por_paciente(hoje, hoje)[0].rodape[-1] == 0
    pagina = farmaceutico.get(f"/estoque/dispensacao/{d.id}").get_data(as_text=True)
    assert "Devolvida integralmente" in pagina and "Erro de dispensação" in pagina
    assert auditoria.verificar_integridade()["ok"]


def test_devolucao_nao_pode_exceder_o_dispensado(base):
    d = _dispensar(base, [(base["soro"], 3)])
    item = d.itens_dispensados[0]
    estoque.devolver(d, {item.id: 2}, "parcial")
    db.session.commit()
    with pytest.raises(EstoqueError, match="só é possível devolver 1"):
        estoque.devolver(d, {item.id: 2}, "de novo")
    with pytest.raises(EstoqueError, match="motivo"):
        estoque.devolver(d, {item.id: 1}, "")


def test_devolucao_exige_farmaceutico(auxiliar, base):
    d = _dispensar(base, [(base["soro"], 1)])
    assert auxiliar.get(f"/estoque/dispensacao/{d.id}/devolver").status_code == 403
    assert auxiliar.post(f"/estoque/dispensacao/{d.id}/devolver", data={"tudo": "1", "motivo": "x"}).status_code == 403


# ------------------------------------------------------------------- bloqueio de lote

def test_lote_bloqueado_nao_e_dispensado_nem_transferido(base):
    estoque.transferir(base["soro"], base["sus"], base["uti"], 5)
    db.session.commit()
    lotes = estoque.bloquear_lote(base["soro"], "S1", "Recall do fabricante nº 12/2026")
    db.session.commit()
    assert len(lotes) == 2  # o lote S1 na farmácia e na UTI
    # Só o lote S2 (10 unidades) segue disponível na farmácia.
    with pytest.raises(EstoqueError, match="não vencido nem bloqueado"):
        _dispensar(base, [(base["soro"], 11)])
    d = _dispensar(base, [(base["soro"], 10)])
    assert {m.lote.numero_lote for m in d.itens_dispensados} == {"S2"}
    with pytest.raises(EstoqueError):
        estoque.transferir(base["soro"], base["uti"], base["leito"], 1)
    assert relatorios.calcular_pedido_compra()[1]["saldo"] == 0


def test_bloqueio_e_desbloqueio_pela_web_com_trilha(farmaceutico, auxiliar, base):
    lote = Lote.query.filter_by(numero_lote="S1").one()
    assert auxiliar.post(f"/estoque/lotes/{lote.id}/bloqueio", data={"motivo": "x"}).status_code == 403
    farmaceutico.post(f"/estoque/lotes/{lote.id}/bloqueio", data={"motivo": "Alerta ANVISA 99/2026"})
    lote = db.session.get(Lote, lote.id)
    assert lote.bloqueado and lote.motivo_bloqueio == "Alerta ANVISA 99/2026"
    assert "bloqueado" in farmaceutico.get("/estoque/lotes").get_data(as_text=True)
    farmaceutico.post(f"/estoque/lotes/{lote.id}/bloqueio", data={"motivo": "Laudo de liberação 3/2026"})
    assert not db.session.get(Lote, lote.id).bloqueado
    from exatamed.models import RegistroAuditoria
    trilha = [r.alteracoes_dict.get("bloqueado") for r in RegistroAuditoria.query.filter_by(entidade="lote",
                                                                                         acao="ALTERACAO")]
    assert ["False", "True"] in trilha and ["True", "False"] in trilha


def test_bloqueio_exige_motivo(base):
    with pytest.raises(EstoqueError, match="motivo"):
        estoque.bloquear_lote(base["soro"], "S1", " ")


# ------------------------------------------------------------------- escrituração de controlados

def test_livro_de_controlados(base):
    d = _dispensar(base, [(base["morfina"], 3)])
    estoque.devolver(d, {d.itens_dispensados[0].id: 1}, "Dose não administrada")
    estoque.transferir(base["morfina"], base["sus"], base["uti"], 5)  # interna: não escriturada
    db.session.commit()
    hoje = date.today()
    (tabela,) = relatorios.livro_controlados(hoje - timedelta(days=1), hoje)
    assert "lista A1" in tabela.titulo
    assert tabela.linhas[0][1] == "Saldo anterior" and tabela.linhas[0][8] == 20  # entrada há 10 dias
    operacoes = [linha[1] for linha in tabela.linhas[1:]]
    assert operacoes == ["Dispensação", "Devolução de dispensação"]
    dispensacao = tabela.linhas[1]
    assert dispensacao[4] == "Ana Souza" and "CRM 123/CE" in dispensacao[5] and dispensacao[7] == 3
    assert tabela.rodape[6:9] == [1, 3, 18]


def test_livro_de_controlados_restrito_e_exportacao_registrada(client, auxiliar, base):
    from exatamed.models import RegistroAcesso
    assert auxiliar.get("/relatorios/livro_controlados").status_code == 403
    assert "Escrituração" not in auxiliar.get("/relatorios/").get_data(as_text=True)
    assert client.get("/relatorios/livro_controlados?inicio=2000-01-01").status_code == 200
    client.get("/relatorios/livro_controlados?inicio=2000-01-01&formato=csv")
    assert RegistroAcesso.query.filter_by(acao="EXPORTAR").count() == 1


# ------------------------------------------------------------------- busca de pacientes

def test_busca_de_pacientes(client, base):
    p = base["paciente"]
    p.cpf, p.cartao_sus, p.alergias = "529.982.247-25", "940781618495933", "dipirona"
    db.session.add(Paciente(nome="Ana Anonimizada", anonimizado_em=datetime.now()))
    db.session.commit()
    assert client.get("/estoque/pacientes/busca?q=a").get_json() == []  # mínimo de 2 caracteres
    (achado,) = client.get("/estoque/pacientes/busca?q=souza").get_json()
    assert achado == {"id": p.id, "nome": "Ana Souza", "cpf": "***.982.247-**", "plano": "", "nascimento": "",
                      "alergias": "dipirona"}
    assert client.get("/estoque/pacientes/busca?q=52998").get_json()[0]["id"] == p.id  # por CPF
    assert client.get("/estoque/pacientes/busca?q=5933").get_json()[0]["id"] == p.id  # por Cartão SUS
    nomes = [r["nome"] for r in client.get("/estoque/pacientes/busca?q=Ana").get_json()]
    assert nomes == ["Ana Souza"]  # anonimizados não aparecem


def test_busca_exige_login(anonimo):
    assert anonimo.get("/estoque/pacientes/busca?q=ana").status_code == 302


def test_formulario_mantem_paciente_apos_erro(client, base):
    dados = {"paciente_id": base["paciente"].id, "origem_id": base["sus"].id, "destino_id": base["leito"].id}
    resposta = client.post("/estoque/dispensacao", data=dados)
    html = resposta.get_data(as_text=True)
    assert "Inclua ao menos um item" in html and 'value="Ana Souza"' in html
