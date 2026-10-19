"""Exportação dos dados do banco em SQL (scripts INSERT), para migrar dados entre instalações.

O arquivo gerado recria o conteúdo de todas as tabelas num banco com o esquema do ExataMed já
criado (o sistema cria as tabelas ao iniciar). As tabelas são percorridas na ordem das chaves
estrangeiras e as linhas na ordem da chave primária, com os mesmos ids, de modo que os vínculos
e os selos da cadeia de auditoria são preservados.

Os selos (HMAC) dependem da EXATAMED_CHAVE_AUDITORIA: o banco de destino precisa usar a mesma
chave do banco de origem para que a verificação de integridade continue passando.
"""

import re
from datetime import datetime

from sqlalchemy import Integer, select, text
from sqlalchemy.dialects import postgresql, sqlite

from .models import Medico, Paciente, db

# Estilo de parâmetro nomeado: com o padrão do psycopg (pyformat), o compilador dobraria o "%"
# dos textos ("0,9%" viraria "0,9%%"), e o arquivo é executado sem parâmetros.
DIALETOS = {"postgresql": postgresql.dialect(paramstyle="named"), "sqlite": sqlite.dialect(paramstyle="named")}
# Falhas de login por IP: dado operacional e passageiro, não faz parte da migração.
TABELAS_IGNORADAS = {"tentativas_login"}
LINHAS_POR_INSERT = 200
AVISO_ANONIMIZADO = "Dados pessoais ANONIMIZADOS."
AVISO_DADOS_PESSOAIS = "ATENÇÃO: contém dados pessoais (LGPD). Guarde em local seguro e não publique."


# --------------------------------------------------------------------------- anonimização (opcional)

def _anonimizar_paciente(linha):
    from .lgpd import aplicar_anonimizacao_paciente
    if linha.get("anonimizado_em"):
        return linha
    paciente = Paciente(**linha)  # objeto transitório: não entra na sessão nem no banco
    aplicar_anonimizacao_paciente(paciente)
    return {coluna: getattr(paciente, coluna) for coluna in linha}


def _anonimizar_medico(linha):
    from .lgpd import aplicar_anonimizacao_medico
    if linha.get("anonimizado_em"):
        return linha
    medico = Medico(**linha)
    aplicar_anonimizacao_medico(medico)
    return {coluna: getattr(medico, coluna) for coluna in linha}


def _anonimizar_usuario(linha):
    # Como no comando anonimizar-banco: login e senha ficam, para a cópia continuar utilizável.
    return dict(linha, nome=f"Usuário {linha['id']}", email=None, registro_profissional=None)


def _anonimizar_dispensacao(linha):
    responsavel = f"Usuário {linha['usuario_id']}" if linha.get("usuario_id") else None
    return dict(linha, responsavel=responsavel, observacao=None)


def _anonimizar_cadeia(linha):
    # O registro de acessos não é exportado: a cadeia dele recomeça vazia.
    if linha["nome"] == "registros_acesso":
        return dict(linha, ultimo_seq=0, ultimo_hash="")
    return linha


ANONIMIZACAO = {
    "pacientes": _anonimizar_paciente,
    "medicos": _anonimizar_medico,
    "usuarios": _anonimizar_usuario,
    "dispensacoes": _anonimizar_dispensacao,
    "cadeias_auditoria": _anonimizar_cadeia,
}
IGNORADAS_AO_ANONIMIZAR = {"registros_acesso"}


# --------------------------------------------------------------------------- geração do SQL

def tabelas_exportadas(anonimizar=False):
    ignoradas = TABELAS_IGNORADAS | (IGNORADAS_AO_ANONIMIZAR if anonimizar else set())
    return [t for t in db.metadata.sorted_tables if t.name not in ignoradas]


def _insert(tabela, linhas, dialeto):
    comando = tabela.insert().values(linhas)
    return str(comando.compile(dialect=dialeto, compile_kwargs={"literal_binds": True})) + ";"


def _tem_id_sequencial(tabela):
    coluna = tabela.columns.get("id")
    return coluna is not None and coluna.primary_key and isinstance(coluna.type, Integer)


def exportar_sql(saida, dialeto=None, anonimizar=False, limpar=True, versao=""):
    """Escreve em `saida` (arquivo de texto aberto) os comandos SQL e devolve a contagem por tabela."""
    nome_dialeto = dialeto or db.engine.dialect.name
    if nome_dialeto not in DIALETOS:
        raise ValueError(f"Dialeto não suportado: {nome_dialeto}. Use postgresql ou sqlite.")
    compilador = DIALETOS[nome_dialeto]
    tabelas = tabelas_exportadas(anonimizar)
    saida.write(
        f"-- ExataMed {versao}: dados exportados em {datetime.now():%d/%m/%Y %H:%M} para {nome_dialeto}.\n"
        "-- Gerado por: flask --app exatamed exportar-sql\n"
        f"-- {AVISO_ANONIMIZADO if anonimizar else AVISO_DADOS_PESSOAIS}\n"
        "--\n"
        "-- Como usar: num banco novo, inicie o ExataMed uma vez (o sistema cria as tabelas) e rode este arquivo:\n"
        "--   PostgreSQL: psql \"$DATABASE_URL\" -f arquivo.sql   |   SQLite: sqlite3 exatamed.db < arquivo.sql\n"
        "--   ou: flask --app exatamed importar-sql arquivo.sql --confirmar\n"
        "-- Os selos da cadeia de auditoria exigem a mesma EXATAMED_CHAVE_AUDITORIA do banco de origem.\n\n"
    )
    saida.write("BEGIN;\n\n")
    if limpar:
        saida.write("-- Apaga os dados existentes (o banco de destino deve ser novo).\n")
        for tabela in reversed(tabelas):
            saida.write(f"DELETE FROM {tabela.name};\n")
        if anonimizar and "registros_acesso" in db.metadata.tables:
            saida.write("DELETE FROM registros_acesso;\n")
        saida.write("\n")
    contagem = {}
    for tabela in tabelas:
        consulta = select(tabela).order_by(*tabela.primary_key.columns)
        transformar = ANONIMIZACAO.get(tabela.name) if anonimizar else None
        total, bloco = 0, []
        saida.write(f"-- {tabela.name}\n")
        for linha in db.session.execute(consulta.execution_options(yield_per=500)).mappings():
            linha = dict(linha)
            bloco.append(transformar(linha) if transformar else linha)
            if len(bloco) == LINHAS_POR_INSERT:
                saida.write(_insert(tabela, bloco, compilador) + "\n")
                total, bloco = total + len(bloco), []
        if bloco:
            saida.write(_insert(tabela, bloco, compilador) + "\n")
            total += len(bloco)
        contagem[tabela.name] = total
        saida.write("\n")
    if nome_dialeto == "postgresql":
        saida.write("-- Ajusta as sequências dos ids para continuar depois dos registros importados.\n")
        for tabela in tabelas:
            if _tem_id_sequencial(tabela):
                saida.write(f"SELECT setval(pg_get_serial_sequence('{tabela.name}', 'id'), "
                            f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {tabela.name};\n")
        saida.write("\n")
    saida.write("COMMIT;\n")
    return contagem


# Arquivos exportados até a versão 2.4 trazem as alterações da trilha na coluna de texto "alteracoes".
FORMATO_ANTIGO = re.compile(r"INSERT INTO registros_auditoria \([^)]*\balteracoes\b")


def _executar_script(conteudo):
    conexao = db.engine.raw_connection()
    try:
        cursor = conexao.cursor()
        if db.engine.dialect.name == "sqlite":
            # O arquivo já traz BEGIN/COMMIT; executescript respeita a transação do script.
            conexao.driver_connection.executescript(conteudo)
        else:
            cursor.execute(conteudo)
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()


def importar_sql(conteudo):
    """Executa um arquivo gerado por `exportar_sql` no banco configurado, numa transação.

    Um arquivo da versão 2.4 ou anterior (alterações da trilha em texto JSON) é carregado com a
    coluna antiga recriada temporariamente e, em seguida, migrado para a tabela alteracoes_auditoria.
    Devolve o resumo dessa migração, ou None para arquivos no formato atual.
    """
    from .migracao_auditoria import COLUNA_ANTIGA, TABELA, coluna_antiga_existe, migrar_alteracoes_auditoria
    db.session.remove()  # libera as travas da sessão antes dos DELETE do script
    antigo = bool(FORMATO_ANTIGO.search(conteudo))
    coluna_criada = False
    if antigo:
        with db.engine.begin() as conexao:
            if "\nDELETE FROM registros_auditoria;" in conteudo:
                # O arquivo antigo não conhece a tabela nova: esvazia-a antes dos DELETE dele.
                conexao.execute(text("DELETE FROM alteracoes_auditoria"))
            if not coluna_antiga_existe(conexao):
                conexao.execute(text(f"ALTER TABLE {TABELA} ADD COLUMN {COLUNA_ANTIGA} TEXT"))
                coluna_criada = True
    try:
        _executar_script(conteudo)
    except Exception:
        if coluna_criada:
            with db.engine.begin() as conexao:
                conexao.execute(text(f"ALTER TABLE {TABELA} DROP COLUMN {COLUNA_ANTIGA}"))
        raise
    db.session.expire_all()
    return migrar_alteracoes_auditoria() if antigo else None


def contar_linhas():
    return {t.name: db.session.execute(text(f"SELECT COUNT(*) FROM {t.name}")).scalar()
            for t in db.metadata.sorted_tables}
