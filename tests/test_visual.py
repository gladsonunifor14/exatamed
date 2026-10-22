"""Melhorias visuais: selos de situação, navegação, indicadores clicáveis, acessibilidade e cartões no celular."""

import re
from datetime import date, timedelta

import pytest

from exatamed import estoque
from exatamed.models import Localizacao, Lote, Produto, db


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
    for url in ("/estoque/movimentacoes", "/estoque/notas"):
        assert 'class="d-md-none lista-cartoes"' in client.get(url).get_data(as_text=True), url
