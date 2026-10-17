import io
from datetime import date

import pytest
from sqlalchemy import select

from exatamed import auditoria
from exatamed.demo import criar_usuarios_demo, popular
from exatamed.exportacao import exportar_sql, importar_sql, tabelas_exportadas
from exatamed.models import Localizacao, NotaFiscal, Paciente, Produto, RegistroAcesso, TentativaLogin, Usuario, db

TEXTO_DIFICIL = "O'Brien 0,9% \\ teste; DELETE FROM x;\nsegunda linha – ação"


def _foto():
    """Conteúdo de todas as tabelas exportadas, linha a linha."""
    foto = {t.name: [tuple(linha) for linha in db.session.execute(select(t).order_by(*t.primary_key.columns))]
            for t in tabelas_exportadas()}
    db.session.commit()
    return foto


def _exportar(**opcoes):
    saida = io.StringIO()
    contagem = exportar_sql(saida, versao="teste", **opcoes)
    return saida.getvalue(), contagem


@pytest.fixture
def dados(app):
    popular()
    criar_usuarios_demo()
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    db.session.add(Produto(nome_comercial=TEXTO_DIFICIL, unidade_medida="UN"))
    db.session.add(NotaFiscal(chave="1" * 44, numero="1", serie="1", emitente_cnpj="1", emitente_nome="Fornecedor",
                              situacao="DESCARTADA", xml="<a>x; y 'z' 10%</a>", localizacao=sus))
    db.session.add(TentativaLogin(ip="10.0.0.1"))
    db.session.commit()
    return sus


def test_exporta_e_importa_os_mesmos_dados(dados):
    antes = _foto()
    sql, contagem = _exportar()
    assert contagem["movimentacoes"] == len(antes["movimentacoes"]) > 0
    assert "tentativas_login" not in contagem and "INSERT INTO tentativas_login" not in sql
    assert sql.startswith("-- ExataMed teste") and "BEGIN;" in sql and sql.rstrip().endswith("COMMIT;")
    # O banco muda depois da exportação...
    Produto.query.filter_by(nome_comercial=TEXTO_DIFICIL).one().nome_comercial = "alterado"
    db.session.add(Produto(nome_comercial="Novo", unidade_medida="UN"))
    db.session.commit()
    # ...e a importação devolve exatamente o conteúdo exportado, com a integridade preservada.
    importar_sql(sql)
    assert _foto() == antes
    assert Produto.query.filter_by(nome_comercial=TEXTO_DIFICIL).count() == 1
    assert NotaFiscal.query.one().xml == "<a>x; y 'z' 10%</a>"
    assert auditoria.verificar_integridade()["ok"]


def test_ids_continuam_depois_da_importacao(dados):
    sql, _ = _exportar()
    importar_sql(sql)
    maior = db.session.query(db.func.max(Produto.id)).scalar()
    novo = Produto(nome_comercial="Depois da migração", unidade_medida="UN")
    db.session.add(novo)
    db.session.commit()
    assert novo.id == maior + 1


def test_postgresql_ajusta_sequencias(dados):
    sql, _ = _exportar(dialeto="postgresql")
    assert "SELECT setval(pg_get_serial_sequence('produtos', 'id')" in sql
    assert "0,9%%" not in sql and "0,9%" in sql  # o "%" não é escapado: o arquivo roda sem parâmetros
    assert "setval" not in _exportar(dialeto="sqlite")[0]


def test_sem_limpar_nao_apaga(dados):
    assert "\nDELETE FROM pacientes;" in _exportar()[0]
    assert "\nDELETE FROM" not in _exportar(limpar=False)[0]


def test_exportacao_anonimizada(dados):
    nomes = [p.nome for p in Paciente.query]
    usuario = Usuario.query.filter_by(login="admin").one()
    hash_senha = usuario.senha_hash
    sql, contagem = _exportar(anonimizar=True)
    assert all(nome not in sql for nome in nomes) and "Paciente anonimizado P-" in sql
    assert "registros_acesso" not in contagem and "INSERT INTO registros_acesso" not in sql
    assert "Dados pessoais ANONIMIZADOS" in sql
    assert Paciente.query.filter(Paciente.anonimizado_em.isnot(None)).count() == 0  # o banco não muda
    importar_sql(sql)
    assert {p.nome for p in Paciente.query} == {f"Paciente anonimizado {p.pseudonimo}" for p in Paciente.query}
    admin = Usuario.query.filter_by(login="admin").one()
    assert admin.senha_hash == hash_senha and admin.nome == f"Usuário {admin.id}"
    assert RegistroAcesso.query.count() == 0
    assert auditoria.verificar_integridade()["ok"]


def test_comandos(app, dados, tmp_path):
    executor = app.test_cli_runner()
    arquivo = tmp_path / "dados.sql"
    resultado = executor.invoke(args=["exportar-sql", "--saida", str(arquivo)])
    assert resultado.exit_code == 0 and "Arquivo gerado" in resultado.output and "LGPD" in resultado.output
    assert "INSERT INTO pacientes" in arquivo.read_text(encoding="utf-8")
    resultado = executor.invoke(args=["importar-sql", str(arquivo)])
    assert resultado.exit_code != 0 and "--confirmar" in resultado.output
    resultado = executor.invoke(args=["importar-sql", str(arquivo), "--confirmar"])
    assert resultado.exit_code == 0 and "Importação concluída" in resultado.output
    assert Paciente.query.count() == 3 and date.today()
