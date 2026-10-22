"""Melhorias visuais: selos de situação, navegação, indicadores clicáveis, acessibilidade e cartões no celular."""

import re
from datetime import date, timedelta

import pytest

from exatamed import estoque
from exatamed.models import Localizacao, Lote, Produto, RegistroAuditoria, Usuario, db


@pytest.fixture
def produtos(app):
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    abaixo = Produto(nome_comercial="Abaixo", unidade_medida="UN", estoque_minimo=10)
    falta = Produto(nome_comercial="Falta", unidade_medida="UN", estoque_minimo=5)
    ok = Produto(nome_comercial="Ok", unidade_medida="UN", estoque_minimo=1)
    novo = Produto(nome_comercial="Novo", unidade_medida="UN")
    db.session.add_all([abaixo, falta, ok, novo])
    db.session.flush()
    estoque.registrar_entrada(abaixo, sus, "A1", date.today() + timedelta(days=20), 3, "1")
    estoque.registrar_entrada(ok, sus, "O1", date.today() + timedelta(days=400), 3, "1")
    db.session.commit()
    return dict(abaixo=abaixo, falta=falta, ok=ok, novo=novo)


def test_situacao_do_estoque(produtos):
    assert produtos["abaixo"].situacao_estoque == ("serio", "Abaixo do mínimo")
    assert produtos["falta"].situacao_estoque == ("critico", "Em falta")
    assert produtos["ok"].situacao_estoque is None and produtos["novo"].situacao_estoque is None


@pytest.mark.parametrize("dias, esperado", [
    (-1, ("critico", "Vencido")), (0, ("critico", "Vence hoje")), (1, ("critico", "Vence em 1 dia")),
    (30, ("critico", "Vence em 30 dias")), (45, ("serio", "Vence em 45 dias")), (90, ("alerta", "Vence em 90 dias")),
    (91, None),
])
def test_selo_de_validade(dias, esperado):
    assert Lote(validade=date.today() + timedelta(days=dias)).selo_validade == esperado


def test_lista_de_produtos(client, produtos):
    pagina = client.get("/cadastros/produtos/").get_data(as_text=True)
    assert "selo selo-serio" in pagina and "Abaixo do mínimo" in pagina and "Em falta" in pagina
    assert 'class="d-md-none lista-cartoes"' in pagina and 'class="card d-none d-md-block"' in pagina
    assert 'aria-label="Editar"' in pagina and 'aria-label="Excluir"' in pagina and 'aria-label="Pesquisar"' in pagina
    assert "4 registro(s)" in pagina


def test_caminho_e_menu_ativo(client, produtos):
    pagina = client.get("/cadastros/produtos/").get_data(as_text=True)
    assert re.search(r'<nav aria-label="Caminho".*Início.*Cadastros.*Medicamentos e materiais', pagina, re.S)
    assert re.search(r'nav-link dropdown-toggle active"[^>]*aria-current="page"[^>]*>Cadastros', pagina)
    relatorio = client.get("/relatorios/saidas_avulsas").get_data(as_text=True)
    assert 'href="/relatorios/">Relatórios</a>' in relatorio and "Saídas avulsas</li>" in relatorio
    devolucao = client.get("/estoque/dispensacao").get_data(as_text=True)
    assert re.search(r'nav-link active"[^>]*href="/estoque/dispensacao"', devolucao)
    painel = client.get("/").get_data(as_text=True)
    assert 'aria-label="Caminho"' not in painel and 'aria-current="page"' not in painel


def test_painel(client, produtos):
    pagina = client.get("/").get_data(as_text=True)
    for destino in ('href="/cadastros/produtos/"', 'href="/cadastros/pacientes/"', "chave=resumo_dispensacao",
                    "/relatorios/consumo_diario", "/relatorios/inventario"):
        assert destino in pagina.replace("&amp;", "&") or destino.replace("chave=", "") in pagina, destino
    assert "Vence em 20 dias" in pagina and "Abaixo do mínimo" in pagina and "Em falta" in pagina
    assert "table-warning" not in pagina


def test_lotes_e_notas_no_celular(client, produtos):
    lotes = client.get("/estoque/lotes").get_data(as_text=True)
    assert "Vence em 20 dias" in lotes and 'class="d-md-none lista-cartoes"' in lotes
    assert 'aria-label="Bloquear lote (recall, quarentena)"' in lotes
    assert 'class="d-md-none lista-cartoes"' in client.get("/estoque/movimentacoes").get_data(as_text=True)
    notas = client.get("/estoque/notas").get_data(as_text=True)
    assert "lista-cartoes" not in notas and "Nenhuma nota fiscal importada ainda." in notas


# ------------------------------------------------------------------- 2.8: confirmações, avisos, telas vazias, tema

def test_confirmacao_diz_o_que_sera_afetado(client, produtos):
    pagina = client.get("/cadastros/produtos/").get_data(as_text=True)
    assert 'data-confirmar="Excluir medicamento / material “Abaixo”?' in pagina
    assert 'data-confirmar-titulo="Excluir medicamento / material"' in pagina and "data-confirmar-perigo" in pagina
    assert "window.confirm" in client.get("/static/js/app.js").get_data(as_text=True)  # só como reserva


def test_sucesso_vira_aviso_e_erro_fica_fixo(client, anonimo):
    dados = {"nome": "Ala Norte", "tipo": "SETOR"}
    pagina = client.post("/cadastros/localizacoes/novo", data=dados, follow_redirects=True).get_data(as_text=True)
    aviso = pagina.split('class="toast-container', 1)[1]
    assert 'role="status"' in aviso and "salvo(a) com sucesso" in aviso
    assert 'class="alert' not in pagina
    erro = anonimo.post("/login", data={"login": "x", "senha": "errada"}).get_data(as_text=True)
    assert 'class="alert alert-danger' in erro and 'role="alert"' in erro and "toast-container" not in erro


def test_telas_sem_dados(client, app):
    lotes = client.get("/estoque/lotes").get_data(as_text=True)
    assert "Nenhum lote com saldo em estoque." in lotes and 'href="/estoque/entrada"' in lotes
    produtos = client.get("/cadastros/produtos/").get_data(as_text=True)
    assert "nenhum cadastro ainda" in produtos and "Cadastrar medicamento / material" in produtos
    busca = client.get("/cadastros/pacientes/?q=zzz").get_data(as_text=True)
    assert "Nada encontrado para “zzz”." in busca and "Limpar pesquisa" in busca
    filtrado = client.get("/estoque/movimentacoes?tipo=ENTRADA").get_data(as_text=True)
    assert "Nenhuma movimentação para os filtros escolhidos." in filtrado and "Limpar filtros" in filtrado
    assert "Nenhuma dispensação registrada ainda." in client.get("/").get_data(as_text=True)


def test_dispensacao_em_etapas_com_barra_no_celular(client):
    pagina = client.get("/estoque/dispensacao").get_data(as_text=True)
    for etapa in ("1</span> Paciente", "2</span> Prescrição e locais", "3</span> Itens"):
        assert etapa in pagina
    barra = pagina.split('class="barra-acao', 1)[1].split("</div>\n<div", 1)[0]
    assert 'form="form-dispensacao"' in barra and 'id="resumo-itens"' in barra
    assert 'aria-label="Medicamento ou material"' in pagina


def test_tema_por_usuario(client, app):
    pagina = client.get("/").get_data(as_text=True)
    assert 'data-tema="sistema"' in pagina and "/static/js/tema.js" in pagina.split("</head>")[0]
    auditoria = RegistroAuditoria.query.count()
    resposta = client.post("/minha-aparencia", data={"tema": "escuro", "voltar": "/estoque/lotes?x=1"})
    assert resposta.status_code == 302 and resposta.location.endswith("/estoque/lotes?x=1")
    assert Usuario.query.filter_by(login="admin").one().tema == "escuro"
    assert RegistroAuditoria.query.count() == auditoria  # preferência de tela não entra na trilha
    pagina = client.get("/").get_data(as_text=True)
    assert 'data-tema="escuro"' in pagina and 'value="escuro"\n                  aria-pressed="true"' in pagina
    assert client.post("/minha-aparencia", data={"tema": "roxo"}).status_code == 400
    externo = client.post("/minha-aparencia", data={"tema": "claro", "voltar": "//site.com/"})
    assert externo.location.endswith("/") and "site.com" not in externo.location


def test_tema_exige_login(anonimo):
    assert anonimo.post("/minha-aparencia", data={"tema": "escuro"}).status_code == 302
    assert 'data-tema="sistema"' in anonimo.get("/login").get_data(as_text=True)
