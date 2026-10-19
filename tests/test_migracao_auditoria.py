"""Migração da trilha de auditoria: coluna JSON "alteracoes" -> tabela alteracoes_auditoria."""

import pytest
from sqlalchemy import inspect, text

from exatamed import auditoria
from exatamed.auditoria import conteudo_alteracoes, texto_alteracoes
from exatamed.migracao_auditoria import migrar_alteracoes_auditoria
from exatamed.models import AlteracaoAuditoria, Localizacao, Paciente, Produto, RegistroAuditoria, db

ATUALIZAR = text("UPDATE registros_auditoria SET alteracoes = :t WHERE id = :i")


def _colunas():
    return {c["name"] for c in inspect(db.engine).get_columns("registros_auditoria")}


@pytest.fixture
def legado(app):
    """Banco no formato da versão 2.4: alterações em texto JSON na coluna, sem a tabela nova preenchida.

    Os registros são gravados pela aplicação (selados); depois o conteúdo volta para a coluna antiga,
    exatamente como a 2.4 guardava, e as linhas da tabela nova são apagadas.
    """
    produto = Produto(nome_comercial='Soro "fisiológico" 0,9%', unidade_medida="FR")
    db.session.add_all([produto, Paciente(nome="Ana Souza", cpf="529.982.247-25"), Localizacao(nome="UTI")])
    db.session.commit()
    produto.estoque_minimo, produto.nome_comercial = 5, "Soro – ação"
    db.session.commit()
    db.session.delete(Localizacao.query.filter_by(nome="UTI").one())
    db.session.commit()
    ids = [r.id for r in RegistroAuditoria.query.order_by(RegistroAuditoria.id)]
    textos = conteudo_alteracoes(db.session, ids)
    db.session.remove()
    with db.engine.begin() as conexao:
        conexao.execute(text("ALTER TABLE registros_auditoria ADD COLUMN alteracoes TEXT"))
        for id_, texto in textos.items():
            conexao.execute(ATUALIZAR, {"t": texto, "i": id_})
        conexao.execute(text("DELETE FROM alteracoes_auditoria"))
    return textos


def test_migra_o_historico_e_remove_a_coluna(legado):
    assert "alteracoes" in _colunas() and AlteracaoAuditoria.query.count() == 0
    resumo = migrar_alteracoes_auditoria()
    assert resumo["coluna_removida"] and not resumo["problemas"]
    assert resumo["registros"] == len(legado) and resumo["campos"] == AlteracaoAuditoria.query.count() > 0
    assert "alteracoes" not in _colunas()
    # Cada registro tem exatamente o conteúdo antigo, campo a campo, e os selos continuam válidos.
    for registro in RegistroAuditoria.query:
        assert texto_alteracoes(registro.alteracoes_dict) == legado[registro.id]
    alteracao = RegistroAuditoria.query.filter_by(entidade="produto", acao="ALTERACAO").one()
    assert alteracao.alteracoes_dict["nome_comercial"] == ['Soro "fisiológico" 0,9%', "Soro – ação"]
    assert alteracao.alteracoes_dict["estoque_minimo"] == ["0.0000", "5"]
    assert RegistroAuditoria.query.filter_by(entidade="paciente").one().alteracoes_dict["nome"] == [
        "(dado pessoal)", "(dado pessoal)"]
    assert auditoria.verificar_integridade()["ok"]


def test_migracao_e_idempotente(legado):
    migrar_alteracoes_auditoria()
    total = AlteracaoAuditoria.query.count()
    db.session.remove()
    segunda = migrar_alteracoes_auditoria()
    assert not segunda["pendente"] and AlteracaoAuditoria.query.count() == total


def test_registro_adulterado_mantem_a_coluna_e_e_apontado(legado):
    alvo, intacto = sorted(legado)[0], sorted(legado)[1]
    # Mesmo conteúdo, mas fora da forma canônica: o selo não foi calculado sobre este texto.
    adulterado = legado[alvo].replace('", "', '",  "', 1)
    invalido = sorted(legado)[2]
    with db.engine.begin() as conexao:
        conexao.execute(ATUALIZAR, {"t": adulterado, "i": alvo})
        conexao.execute(ATUALIZAR, {"t": "{não é json", "i": invalido})
    resumo = migrar_alteracoes_auditoria()
    assert {i for i, _ in resumo["problemas"]} == {alvo, invalido} and not resumo["coluna_removida"]
    assert "alteracoes" in _colunas()  # nada se perde: a coluna fica para análise
    assert AlteracaoAuditoria.query.filter_by(registro_auditoria_id=intacto).count() > 0
    db.session.remove()
    falhas = auditoria.verificar_cadeia("registros_auditoria")["problemas"]
    assert any(f"Registro id {alvo} " in p for p in falhas)
    # Corrigido o texto (restaurado o original), a migração conclui na execução seguinte.
    with db.engine.begin() as conexao:
        for id_ in (alvo, invalido):
            conexao.execute(ATUALIZAR, {"t": legado[id_], "i": id_})
    resumo = migrar_alteracoes_auditoria()
    assert resumo["coluna_removida"] and resumo["ja_migrados"] == len(legado) - 2
    assert auditoria.verificar_integridade()["ok"]


def test_comando_de_migracao(app, legado):
    executor = app.test_cli_runner()
    resultado = executor.invoke(args=["migrar-auditoria"])
    assert resultado.exit_code == 0 and "removida" in resultado.output
    resultado = executor.invoke(args=["migrar-auditoria"])
    assert "Nada a migrar" in resultado.output


def test_novos_registros_gravam_uma_linha_por_campo(app):
    produto = Produto(nome_comercial="Dipirona", unidade_medida="AMP")
    db.session.add(produto)
    db.session.commit()
    registro = RegistroAuditoria.query.filter_by(entidade="produto").one()
    campos = {i.campo: (i.valor_anterior, i.valor_novo) for i in registro.itens}
    assert campos["nome_comercial"] == ("", "Dipirona") and campos["unidade_medida"] == ("", "AMP")
    assert [i.campo for i in registro.itens] == sorted(campos)
    # Alterar uma linha de alteração diretamente no banco quebra o selo do registro.
    with db.engine.begin() as conexao:
        conexao.execute(text("UPDATE alteracoes_auditoria SET valor_novo = 'Outro' WHERE campo = 'nome_comercial'"))
    db.session.remove()
    assert not auditoria.verificar_cadeia("registros_auditoria")["ok"]
