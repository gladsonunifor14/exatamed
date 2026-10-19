"""Migração da trilha de auditoria: da coluna de texto JSON para a tabela alteracoes_auditoria.

Até a versão 2.4, cada registro de auditoria guardava as alterações como texto JSON na coluna
``registros_auditoria.alteracoes`` ({campo: [antes, depois]}). A partir da 2.5 elas ficam na tabela
``alteracoes_auditoria``, uma linha por campo, e a coluna é removida.

A migração roda sozinha ao iniciar o sistema (``atualizar_esquema``) e também pelo comando
``flask --app exatamed migrar-auditoria``. Para cada registro ela:

1. lê o JSON antigo e grava uma linha por campo na tabela nova;
2. confere que o JSON canônico remontado das linhas novas é idêntico ao texto antigo. É sobre esse
   texto que o selo HMAC do registro foi calculado, então a igualdade garante que nenhum selo do
   histórico deixa de conferir.

Só depois que todos os registros conferem a coluna antiga é removida, na mesma transação. Se algum
registro não puder ser transferido sem perda (JSON inválido ou fora da forma canônica num registro
selado, sinal de gravação fora da aplicação), os demais são migrados, a coluna é mantida para
análise e os ids são informados. A verificação de integridade aponta esses registros.
"""

import json
import logging

from sqlalchemy import inspect, text

from .auditoria import texto_alteracoes
from .models import AlteracaoAuditoria, db

COLUNA_ANTIGA = "alteracoes"
TABELA = "registros_auditoria"
log = logging.getLogger("exatamed")


def coluna_antiga_existe(conexao):
    return COLUNA_ANTIGA in {c["name"] for c in inspect(conexao).get_columns(TABELA)}


def _alteracoes_validas(dados):
    return isinstance(dados, dict) and all(
        isinstance(campo, str) and isinstance(par, list) and len(par) == 2 and all(isinstance(v, str) for v in par)
        for campo, par in dados.items())


def migrar(conexao):
    """Transfere o histórico e remove a coluna antiga. Devolve um resumo da migração."""
    resumo = {"pendente": False, "registros": 0, "campos": 0, "ja_migrados": 0, "problemas": [],
              "coluna_removida": False}
    if TABELA not in inspect(conexao).get_table_names() or not coluna_antiga_existe(conexao):
        return resumo
    resumo["pendente"] = True
    itens = AlteracaoAuditoria.__table__
    ja_migrados = {linha[0] for linha in conexao.execute(db.select(itens.c.registro_auditoria_id).distinct())}
    linhas = conexao.execute(text(
        f"SELECT id, {COLUNA_ANTIGA}, seq_cadeia FROM {TABELA} ORDER BY id")).all()
    novos = []
    for id_, bruto, selado in linhas:
        resumo["registros"] += 1
        try:
            dados = json.loads(bruto) if bruto is not None else None
        except ValueError:
            dados = None
        if not _alteracoes_validas(dados):
            resumo["problemas"].append((id_, "conteúdo ausente ou inválido"))
            continue
        # O selo foi calculado sobre o texto antigo: a forma remontada precisa ser idêntica.
        if selado is not None and texto_alteracoes(dados) != bruto:
            resumo["problemas"].append((id_, "texto fora da forma canônica (gravado fora da aplicação?)"))
            continue
        if id_ in ja_migrados:
            resumo["ja_migrados"] += 1
            continue
        novos.extend({"registro_auditoria_id": id_, "campo": campo, "valor_anterior": antes, "valor_novo": depois}
                     for campo, (antes, depois) in dados.items())
    for inicio in range(0, len(novos), 1000):
        conexao.execute(db.insert(itens), novos[inicio:inicio + 1000])
    resumo["campos"] = len(novos)
    if resumo["problemas"]:
        log.error("Migração da trilha de auditoria: %d registro(s) não puderam ser transferidos sem perda "
                  "(ids %s). A coluna %s.%s foi mantida para análise; rode 'flask --app exatamed "
                  "verificar-integridade'.", len(resumo["problemas"]),
                  ", ".join(str(i) for i, _ in resumo["problemas"][:20]), TABELA, COLUNA_ANTIGA)
        return resumo
    conexao.execute(text(f"ALTER TABLE {TABELA} DROP COLUMN {COLUNA_ANTIGA}"))
    resumo["coluna_removida"] = True
    log.info("Trilha de auditoria migrada: %d registro(s), %d campo(s); coluna %s.%s removida.",
             resumo["registros"], resumo["campos"], TABELA, COLUNA_ANTIGA)
    return resumo


def migrar_alteracoes_auditoria():
    """Executa a migração numa transação única (tudo ou nada em caso de erro)."""
    # Uma transação aberta na sessão seguraria uma trava de leitura e o DROP COLUMN esperaria por ela.
    db.session.remove()
    with db.engine.begin() as conexao:
        return migrar(conexao)
