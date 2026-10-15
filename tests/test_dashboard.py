from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from conftest import criar_usuario

from exatamed import dashboard, estoque, graficos
from exatamed.models import Localizacao, Medico, Movimentacao, Paciente, Produto, Usuario, db

HOJE = date.today()


def _dias(n):
    return datetime.combine(HOJE - timedelta(days=n), datetime.min.time()) + timedelta(hours=10)


@pytest.fixture
def cenario(app):
    """Cenário com valores conhecidos (custos em R$):

    entradas: A1 100 x 2 (vence em 20 d), A2 20 x 3 (80 d), B 50 x 1 (45 d), B0 5 x 1 (vencido),
              D 4 x 10, F 4 x 1
    consumo:  dispensação A 30 (60, Dr. Um, UTI), devolução A 5 (10), dispensação D 4 (40, Dra. Dois, UTI),
              saída B 10 por avaria (10), saída B 5 consumo do setor (5)  -> consumo líquido 105
    """
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    uti = Localizacao(nome="UTI")
    a = Produto(nome_comercial="Alfa", unidade_medida="AMP", estoque_minimo=10, estoque_maximo=50)
    b = Produto(nome_comercial="Beta", tipo="MATERIAL", unidade_medida="UN", estoque_minimo=5)
    c = Produto(nome_comercial="Gama", unidade_medida="UN")  # sem mínimo e sem movimentação
    d = Produto(nome_comercial="Delta", unidade_medida="AMP", estoque_minimo=2)
    e = Produto(nome_comercial="Épsilon", unidade_medida="UN", estoque_minimo=3)  # nunca comprado
    f = Produto(nome_comercial="Fi", unidade_medida="UN", estoque_minimo=10)
    um, dois = Medico(nome="Dr. Um", crm="1", uf_crm="CE"), Medico(nome="Dra. Dois", crm="2", uf_crm="CE")
    paciente = Paciente(nome="Ana")
    db.session.add_all([uti, a, b, c, d, e, f, um, dois, paciente])
    db.session.flush()
    estoque.registrar_entrada(a, sus, "A1", HOJE + timedelta(days=20), 100, "2", data=_dias(40))
    estoque.registrar_entrada(a, sus, "A2", HOJE + timedelta(days=80), 20, "3", data=_dias(35))
    estoque.registrar_entrada(b, sus, "B0", HOJE - timedelta(days=5), 5, "1", data=_dias(100))
    estoque.registrar_entrada(b, sus, "B1", HOJE + timedelta(days=45), 50, "1", data=_dias(40))
    estoque.registrar_entrada(d, sus, "D1", HOJE + timedelta(days=300), 4, "10", data=_dias(40))
    estoque.registrar_entrada(f, sus, "F1", HOJE + timedelta(days=300), 4, "1", data=_dias(40))
    d1 = estoque.dispensar(paciente, sus, uti, [(a, 30)], medico=um, prescricao="RX1", data=_dias(10))
    db.session.flush()
    estoque.devolver(d1, {d1.itens_dispensados[0].id: 5}, "Sobra", data=_dias(8))
    estoque.dispensar(paciente, sus, uti, [(d, 4)], medico=dois, prescricao="RX2", data=_dias(5))
    estoque.registrar_saida(b, sus, 10, "Avaria na embalagem", data=_dias(3))
    estoque.registrar_saida(b, sus, 5, "Consumo do setor", data=_dias(2))
    db.session.commit()
    return dict(sus=sus, uti=uti, a=a, b=b, c=c, d=d, e=e, f=f, um=um, dois=dois)


INICIO = HOJE - timedelta(days=29)


def test_evolucao_do_custo_com_filtros(cenario):
    por_dia = dashboard.evolucao_custo(INICIO, HOJE, "dia")
    assert len(por_dia["pontos"]) == 30 and por_dia["total"] == 105
    valores = {p["chave"]: p["valor"] for p in por_dia["pontos"]}
    assert valores[HOJE - timedelta(days=10)] == 60 and valores[HOJE - timedelta(days=8)] == -10
    assert por_dia["maior"]["valor"] == 60
    assert dashboard.evolucao_custo(INICIO, HOJE, "dia", medico_id=cenario["um"].id)["total"] == 50
    assert dashboard.evolucao_custo(INICIO, HOJE, "dia", medico_id=cenario["dois"].id)["total"] == 40
    assert dashboard.evolucao_custo(INICIO, HOJE, "dia", localizacao_id=cenario["uti"].id)["total"] == 90
    assert dashboard.evolucao_custo(INICIO, HOJE, "dia", localizacao_id=cenario["sus"].id)["total"] == 105
    por_mes = dashboard.evolucao_custo(date(HOJE.year - 1, HOJE.month, 1), HOJE, "mes")
    assert len(por_mes["pontos"]) == 13 and por_mes["total"] == 105
    por_ano = dashboard.evolucao_custo(date(HOJE.year - 4, 1, 1), HOJE, "ano")
    assert [p["rotulo"] for p in por_ano["pontos"]] == [str(HOJE.year - i) for i in range(4, -1, -1)]


def test_curva_abc(cenario):
    abc = dashboard.curva_abc(INICIO, HOJE)
    assert abc["total"] == 105
    assert [(i["produto"].nome_comercial, i["valor"], i["classe"]) for i in abc["itens"]] == [
        ("Alfa", 50, "A"), ("Delta", 40, "A"), ("Beta", 15, "B")]
    assert abc["itens"][-1]["acumulado"] == 100
    assert abc["resumo"]["A"]["itens"] == 2 and abc["resumo"]["B"]["itens"] == 1 and abc["resumo"]["C"]["itens"] == 0
    materiais = dashboard.curva_abc(INICIO, HOJE, "MATERIAL")
    assert [(i["produto"].nome_comercial, i["classe"]) for i in materiais["itens"]] == [("Beta", "A")]
    assert [i["produto"].nome_comercial for i in dashboard.curva_abc(INICIO, HOJE, "MEDICAMENTO")["itens"]] == [
        "Alfa", "Delta"]


def test_vencimentos(cenario):
    v = dashboard.vencimentos(HOJE)
    assert [(f["lotes"], f["valor"]) for f in v["faixas"]] == [(1, 150), (1, 35), (1, 60)]
    assert v["vencidos"] == {"lotes": 1, "valor": 5}
    assert [d["lote"].numero_lote for d in v["lotes"]] == ["B0", "A1", "B1", "A2"]


def test_ruptura_e_estoque_de_seguranca(cenario):
    r = dashboard.ruptura(HOJE)
    assert r["monitorados"] == 5 and r["taxa"] == 40  # Alfa, Beta, Delta, Épsilon, Fi
    assert {x["produto"].nome_comercial for x in r["em_falta"]} == {"Delta", "Épsilon"}
    s = dashboard.estoque_seguranca(HOJE)
    assert {n["chave"]: n["itens"] for n in s["niveis"]} == {"ruptura": 2, "abaixo": 1, "adequado": 1, "acima": 1}
    assert s["total"] == 5 and s["sem_minimo"] == 1
    assert [(c["produto"].nome_comercial, c["cobertura_minimo"]) for c in s["criticos"]][-1] == ("Fi", 40)


def test_giro_do_estoque(cenario):
    g = dashboard.giro_estoque(INICIO, HOJE)
    # Estoque no início 359 (todas as entradas), no fim 254 (359 - 105): médio 306,5.
    assert g["consumo"] == 105 and g["estoque_medio"] == Decimal("306.5") and g["estoque_final"] == 254
    assert round(g["giro"], 4) == Decimal("0.3426") and round(g["cobertura"]) == 88
    assert g["maior_giro"][0]["produto"].nome_comercial == "Delta"  # consumiu todo o estoque


def test_devolucoes_e_avarias(cenario):
    d = dashboard.devolucoes_avarias(INICIO, HOJE)
    assert d["dispensado"] == 100 and d["devolvido"] == 10 and d["taxa_devolucao"] == 10
    assert d["dispensacoes"] == 2 and d["com_devolucao"] == 1 and d["taxa_dispensacoes"] == 50
    assert d["consumo"] == 105 and d["perdas"] == 10 and round(d["taxa_avarias"], 2) == Decimal("9.52")
    categorias = {c["categoria"]: (c["saidas"], c["valor"]) for c in d["categorias"]}
    assert categorias["Avaria / quebra"] == (1, 10) and categorias["Outras saídas avulsas"] == (1, 5)
    # Saída estornada não conta.
    admin = criar_usuario("adm", Usuario.ADMIN)
    saida = Movimentacao.query.filter_by(tipo="SAIDA", motivo="Consumo do setor").one()
    estoque.estornar(saida, "Lançada por engano", admin)
    db.session.commit()
    d = dashboard.devolucoes_avarias(INICIO, HOJE)
    assert d["consumo"] == 100 and d["taxa_avarias"] == 10


@pytest.mark.parametrize("motivo, categoria", [
    ("Avaria na embalagem", "Avaria / quebra"), ("QUEBRA", "Avaria / quebra"), ("Ampola quebrada", "Avaria / quebra"),
    ("Lote vencido", "Vencimento"), ("Perda", "Perda / extravio"), ("Extraviado no transporte", "Perda / extravio"),
    ("Consumo do setor", None), ("Devolução ao fornecedor", None), (None, None),
])
def test_categoria_das_saidas(motivo, categoria):
    assert dashboard.categoria_perda(motivo) == categoria


def test_graficos():
    pontos = [{"rotulo": "01/10", "valor": Decimal("0")}, {"rotulo": "02/10", "valor": Decimal("1234.5")}]
    g = graficos.barras(pontos)
    assert g["marcas"][0]["caminho"] is None and g["marcas"][1]["caminho"].startswith("M")
    assert g["marcas"][1]["dica"] == "02/10: R$ 1.234,50"
    assert [linha["rotulo"] for linha in g["linhas"]] == ["R$ 0", "R$ 500", "R$ 1 mil", "R$ 1,5 mil"]
    vazio = graficos.barras([{"rotulo": "x", "valor": Decimal("0")}])
    assert vazio["marcas"][0]["caminho"] is None


def test_pagina_do_dashboard(client, cenario):
    assert 'href="/dashboard/"' in client.get("/").get_data(as_text=True)
    pagina = client.get("/dashboard/?granularidade=dia").get_data(as_text=True)
    for trecho in ["Evolução do custo por dia", "Curva ABC", "Itens próximos ao vencimento",
                   "Taxa de ruptura do estoque", "Nível do estoque de segurança", "Giro do estoque",
                   "Devoluções de medicamentos e avarias",
                   "R$ 105,00", "40,0%", "dashboard.js"]:
        assert trecho in pagina, trecho
    assert pagina.count('class="viz-barra"') == 4  # 4 dias com custo positivo (o da devolução é negativo)
    filtrada = client.get(f"/dashboard/?granularidade=dia&medico_id={cenario['um'].id}").get_data(as_text=True)
    assert "Médico: <strong>Dr. Um</strong>" in filtrada and "R$ 50,00" in filtrada
    materiais = client.get("/dashboard/?tipo=MATERIAL").get_data(as_text=True)
    assert "Curva ABC · materiais" in materiais
    longo = client.get("/dashboard/?granularidade=dia&inicio=2020-01-01").get_data(as_text=True)
    assert "período de até um ano" in longo
    assert "A data inicial deve ser anterior" in client.get(
        f"/dashboard/?inicio={HOJE.isoformat()}&fim={(HOJE - timedelta(days=3)).isoformat()}").get_data(as_text=True)


def test_dashboard_sem_dados_e_login(client, anonimo):
    pagina = client.get("/dashboard/").get_data(as_text=True)
    assert "Nenhum consumo no período" in pagina and "Nenhum item com estoque mínimo definido" in pagina
    assert anonimo.get("/dashboard/").status_code == 302
