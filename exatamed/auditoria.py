"""Auditoria: trilha de alterações e cadeia de registros à prova de adulteração.

Cadeia de auditoria
    Movimentações de estoque, registros de acesso (LGPD) e registros de auditoria são
    selados ao serem gravados: cada registro recebe um número de sequência e uma
    assinatura HMAC-SHA256 calculada sobre o seu conteúdo e a assinatura do registro
    anterior. A chave (EXATAMED_CHAVE_AUDITORIA) fica fora do banco. Assim, alterar,
    apagar ou inserir registros diretamente no banco quebra a cadeia, e a verificação
    aponta onde. O selo é atribuído sob trava da linha da cadeia, então gravações
    simultâneas recebem sequências distintas.

Trilha de auditoria
    Inclusões, alterações e exclusões de cadastros (produtos, lotes, locais, pacientes,
    médicos, usuários, dispensações) ficam registradas com os valores de antes e depois.
    Campos de dados pessoais registram apenas que foram alterados, sem o valor, para não
    duplicar dados pessoais nem contrariar a anonimização (LGPD).

Conciliação
    O saldo de cada lote deve ser igual à soma das suas movimentações.
"""

import hashlib
import hmac
import json
from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, current_app, g, has_app_context, has_request_context, render_template, request
from sqlalchemy import event
from sqlalchemy.orm import Session

from .auth import perfil_requerido
from .models import (
    AlteracaoAuditoria,
    CadeiaAuditoria,
    Dispensacao,
    Localizacao,
    Lote,
    Medico,
    Movimentacao,
    NotaFiscal,
    Paciente,
    Produto,
    ProdutoFornecedor,
    RegistroAcesso,
    RegistroAuditoria,
    Usuario,
    db,
)
from .numeros import decimal

bp = Blueprint("auditoria", __name__, url_prefix="/auditoria")

# Tabelas seladas e os campos que entram na assinatura.
CADEIAS = {
    "movimentacoes": (Movimentacao, ["id", "tipo", "data", "produto_id", "lote_id", "localizacao_id",
                                     "destino_id", "quantidade", "custo_unitario", "dispensacao_id",
                                     "origem_id", "documento", "motivo", "usuario_id"]),
    "registros_acesso": (RegistroAcesso, ["id", "data", "usuario_id", "acao", "entidade", "registro_id",
                                          "descricao", "ip"]),
    "registros_auditoria": (RegistroAuditoria, ["id", "data", "usuario_id", "acao", "entidade",
                                                "registro_id", "alteracoes", "ip"]),
}
# Campos selados que não são colunas da tabela: calculados a partir de tabelas relacionadas.
# As alterações de cada registro de auditoria ficam em alteracoes_auditoria (uma linha por campo);
# o selo cobre o JSON canônico {campo: [antes, depois]} montado a partir delas, que é exatamente o
# texto guardado na antiga coluna "alteracoes". Assim os selos do histórico continuam válidos.
CAMPOS_CALCULADOS = {"registros_auditoria": {"alteracoes"}}
NOMES_CADEIAS = {"movimentacoes": "Movimentações de estoque", "registros_acesso": "Acessos a dados pessoais",
                 "registros_auditoria": "Trilha de auditoria"}

# Cadastros auditados e campos considerados dados pessoais (registrados sem valor).
TODOS = object()
AUDITADOS = {
    Produto: ("produto", set()),
    Localizacao: ("localizacao", set()),
    Lote: ("lote", set()),
    Dispensacao: ("dispensacao", {"observacao", "responsavel"}),
    Paciente: ("paciente", TODOS),
    Medico: ("medico", TODOS),
    Usuario: ("usuario", {"nome", "login", "email", "registro_profissional"}),
    NotaFiscal: ("nota_fiscal", set()),
    ProdutoFornecedor: ("produto_fornecedor", set()),
}
ENTIDADES = {nome: modelo.__name__ for modelo, (nome, _) in AUDITADOS.items()}
IGNORADOS = {"criado_em", "atualizado_em", "ultimo_acesso", "tentativas_falhas", "ocultar_primeiros_passos",
             "seq_cadeia", "hash", "id", "xml"}
DADO_PESSOAL = "(dado pessoal)"


# --------------------------------------------------------------------------- assinatura

def _chave():
    return current_app.config["CHAVE_AUDITORIA"].encode()


def _normalizar(valor):
    if valor is None:
        return ""
    if isinstance(valor, (Decimal, float)):
        return str(decimal(valor))
    if isinstance(valor, datetime):
        return valor.isoformat(sep=" ", timespec="microseconds")
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor)


def assinatura(anterior, seq, valores, chave=None):
    conteudo = json.dumps([anterior, seq, *[_normalizar(v) for v in valores]], ensure_ascii=False)
    return hmac.new(chave or _chave(), conteudo.encode(), hashlib.sha256).hexdigest()


def texto_alteracoes(alteracoes):
    """Forma canônica das alterações de um registro: a que entra no selo."""
    return json.dumps(alteracoes, ensure_ascii=False, sort_keys=True)


def conteudo_alteracoes(executor, ids):
    """{id do registro de auditoria: JSON canônico das alterações}, lido de alteracoes_auditoria."""
    tabela = AlteracaoAuditoria.__table__
    por_registro = {id_: {} for id_ in ids}
    ids = list(ids)
    for inicio in range(0, len(ids), 500):
        consulta = db.select(tabela.c.registro_auditoria_id, tabela.c.campo, tabela.c.valor_anterior,
                             tabela.c.valor_novo).where(tabela.c.registro_auditoria_id.in_(ids[inicio:inicio + 500]))
        for registro_id, campo, antes, depois in executor.execute(consulta):
            por_registro[registro_id][campo] = [antes, depois]
    return {id_: texto_alteracoes(alteracoes) for id_, alteracoes in por_registro.items()}


def _colunas_seladas(nome):
    modelo, campos = CADEIAS[nome]
    calculados = CAMPOS_CALCULADOS.get(nome, set())
    return [modelo.__table__.c[c] for c in campos if c not in calculados]


def _valores_selados(executor, nome, linhas):
    """Valores que entram no selo, na ordem de CADEIAS, para linhas lidas com _colunas_seladas."""
    _, campos = CADEIAS[nome]
    calculados = CAMPOS_CALCULADOS.get(nome, set())
    extras = conteudo_alteracoes(executor, [linha.id for linha in linhas]) if calculados else {}
    return [[extras[linha.id] if c in calculados else getattr(linha, c) for c in campos] for linha in linhas]


def _selar(conexao, nome, ids):
    """Sela os registros indicados, em ordem, sob trava da linha da cadeia."""
    if not ids:
        return
    modelo, campos = CADEIAS[nome]
    tabela, cadeias = modelo.__table__, CadeiaAuditoria.__table__
    elo = conexao.execute(db.select(cadeias.c.ultimo_seq, cadeias.c.ultimo_hash)
                          .where(cadeias.c.nome == nome).with_for_update()).first()
    if elo is None:
        conexao.execute(db.insert(cadeias).values(nome=nome, ultimo_seq=0, ultimo_hash=""))
        seq, anterior = 0, ""
    else:
        seq, anterior = elo
    linhas = conexao.execute(db.select(*_colunas_seladas(nome)).where(tabela.c.id.in_(ids))
                             .order_by(tabela.c.id)).all()
    for linha, valores in zip(linhas, _valores_selados(conexao, nome, linhas)):
        seq += 1
        anterior = assinatura(anterior, seq, valores)
        conexao.execute(db.update(tabela).where(tabela.c.id == linha.id).values(seq_cadeia=seq, hash=anterior))
    conexao.execute(db.update(cadeias).where(cadeias.c.nome == nome)
                    .values(ultimo_seq=seq, ultimo_hash=anterior))


def preparar_cadeias():
    """Na primeira execução da versão 2.0, sela o histórico existente (cria as cadeias).

    Depois disso, registros sem selo nunca são selados automaticamente: são apontados
    pela verificação como gravados fora da aplicação.
    """
    with db.engine.begin() as conexao:
        existentes = {linha[0] for linha in conexao.execute(db.select(CadeiaAuditoria.__table__.c.nome))}
        for nome, (modelo, _) in CADEIAS.items():
            if nome in existentes:
                continue
            tabela = modelo.__table__
            ids = [linha[0] for linha in conexao.execute(
                db.select(tabela.c.id).where(tabela.c.seq_cadeia.is_(None)).order_by(tabela.c.id))]
            conexao.execute(db.insert(CadeiaAuditoria.__table__).values(nome=nome, ultimo_seq=0, ultimo_hash=""))
            _selar(conexao, nome, ids)


def reiniciar_cadeia(nome):
    """Usado apenas quando a tabela é esvaziada de propósito (cópia anonimizada do banco)."""
    db.session.execute(db.update(CadeiaAuditoria).where(CadeiaAuditoria.nome == nome)
                       .values(ultimo_seq=0, ultimo_hash=""))


# --------------------------------------------------------------------------- trilha de auditoria

def _usuario_e_ip():
    # Lê o usuário já carregado nesta requisição, sem consultar o banco durante o flush.
    usuario = g.get("_login_user") if has_request_context() else None
    usuario_id = usuario.id if usuario is not None and getattr(usuario, "is_authenticated", False) else None
    ip = (request.remote_addr or "")[:45] or None if has_request_context() else None
    return usuario_id, ip


def _alteracoes(obj, pessoais, acao):
    estado = db.inspect(obj)
    resultado = {}
    for atributo in estado.mapper.column_attrs:
        campo = atributo.key
        if campo in IGNORADOS:
            continue
        historico = estado.attrs[campo].history
        if acao == RegistroAuditoria.ALTERACAO:
            if not historico.has_changes():
                continue
            antes = historico.deleted[0] if historico.deleted else None
            depois = historico.added[0] if historico.added else None
            if _normalizar(antes) == _normalizar(depois):
                continue
        else:
            antes, depois = None, getattr(obj, campo)
            if acao == RegistroAuditoria.EXCLUSAO:
                antes, depois = depois, None
            if antes is None and depois is None:
                continue
        if campo == "senha_hash":
            resultado["senha"] = ["", "(senha definida)"]
        elif pessoais is TODOS or campo in pessoais:
            resultado[campo] = [DADO_PESSOAL, DADO_PESSOAL]
        else:
            resultado[campo] = [_normalizar(antes), _normalizar(depois)]
    return resultado


@event.listens_for(Session, "after_flush")
def _apos_gravar(session, _contexto):
    if not has_app_context() or not current_app.config.get("CHAVE_AUDITORIA"):
        return
    usuario_id, ip = _usuario_e_ip()
    registros = []
    for colecao, acao in ((session.new, RegistroAuditoria.INCLUSAO), (session.dirty, RegistroAuditoria.ALTERACAO),
                          (session.deleted, RegistroAuditoria.EXCLUSAO)):
        for obj in colecao:
            config = AUDITADOS.get(type(obj))
            if config is None or (acao == RegistroAuditoria.ALTERACAO and not session.is_modified(obj)):
                continue
            alteracoes = _alteracoes(obj, config[1], acao)
            if acao == RegistroAuditoria.ALTERACAO and not alteracoes:
                continue
            registros.append((dict(data=datetime.now(), usuario_id=usuario_id, acao=acao, entidade=config[0],
                                   registro_id=obj.id, ip=ip), alteracoes))
    conexao = session.connection()
    ids_auditoria = []
    tabela, tabela_itens = RegistroAuditoria.__table__, AlteracaoAuditoria.__table__
    for registro, alteracoes in registros:
        id_ = conexao.execute(db.insert(tabela).values(**registro).returning(tabela.c.id)).scalar()
        if alteracoes:
            conexao.execute(db.insert(tabela_itens), [
                {"registro_auditoria_id": id_, "campo": campo, "valor_anterior": antes, "valor_novo": depois}
                for campo, (antes, depois) in alteracoes.items()])
        ids_auditoria.append(id_)
    novos = {nome: [obj.id for obj in session.new if isinstance(obj, modelo)]
             for nome, (modelo, _) in CADEIAS.items()}
    novos["registros_auditoria"] += ids_auditoria
    for nome, ids in novos.items():
        _selar(conexao, nome, ids)


# --------------------------------------------------------------------------- verificação

def verificar_cadeia(nome, chave=None):
    modelo, campos = CADEIAS[nome]
    tabela = modelo.__table__
    problemas = []
    sem_selo = db.session.execute(db.select(tabela.c.id).where(tabela.c.seq_cadeia.is_(None))).scalars().all()
    if sem_selo:
        problemas.append(f"{len(sem_selo)} registro(s) gravado(s) fora da aplicação, sem selo "
                         f"(ids {', '.join(map(str, sem_selo[:10]))}{'...' if len(sem_selo) > 10 else ''}).")
    anterior, esperado, total, ultimo_seq = "", 1, 0, 0
    consulta = db.select(tabela.c.seq_cadeia, tabela.c.hash, *_colunas_seladas(nome)) \
        .where(tabela.c.seq_cadeia.isnot(None)).order_by(tabela.c.seq_cadeia)
    for linha, valores in _em_blocos(nome, db.session.execute(consulta).yield_per(1000)):
        seq, selo = linha.seq_cadeia, linha.hash
        total += 1
        if seq != esperado:
            problemas.append(f"Sequência interrompida: esperado nº {esperado}, encontrado nº {seq} "
                             f"(registro(s) removido(s) ou renumerado(s)).")
        calculado = assinatura(anterior, seq, valores, chave)
        if not hmac.compare_digest(calculado, selo or ""):
            problemas.append(f"Registro id {valores[0]} (nº {seq}): conteúdo alterado ou elo anterior removido.")
        anterior, esperado, ultimo_seq = selo or "", seq + 1, seq
        if len(problemas) >= 20:
            problemas.append("Verificação interrompida após 20 problemas.")
            break
    elo = db.session.get(CadeiaAuditoria, nome)
    if elo and len(problemas) < 20 and (elo.ultimo_seq != ultimo_seq or elo.ultimo_hash != anterior):
        problemas.append(f"O último elo registrado (nº {elo.ultimo_seq}) não confere com o último registro "
                         f"existente (nº {ultimo_seq}): registros finais removidos ou cadeia substituída.")
    return {"nome": nome, "descricao": NOMES_CADEIAS[nome], "total": total, "problemas": problemas,
            "ok": not problemas}


def _em_blocos(nome, resultado, tamanho=1000):
    """Percorre as linhas seladas com os valores do selo, buscando os campos calculados por bloco."""
    bloco = []
    for linha in resultado:
        bloco.append(linha)
        if len(bloco) == tamanho:
            yield from zip(bloco, _valores_selados(db.session, nome, bloco))
            bloco = []
    if bloco:
        yield from zip(bloco, _valores_selados(db.session, nome, bloco))


def conciliar_lotes():
    """Lotes cujo saldo difere da soma das movimentações."""
    somas = dict(db.session.query(Movimentacao.lote_id, db.func.sum(Movimentacao.quantidade))
                 .group_by(Movimentacao.lote_id).all())
    divergencias = []
    for lote in Lote.query.order_by(Lote.id):
        soma = decimal(somas.get(lote.id) or 0)
        if decimal(lote.saldo) != soma:
            divergencias.append({"lote": lote, "saldo": decimal(lote.saldo), "movimentacoes": soma})
    return divergencias


def verificar_integridade():
    cadeias = [verificar_cadeia(nome) for nome in CADEIAS]
    lotes = conciliar_lotes()
    return {"cadeias": cadeias, "lotes": lotes, "ok": all(c["ok"] for c in cadeias) and not lotes,
            "data": datetime.now()}


# --------------------------------------------------------------------------- telas (administrador)

@bp.route("/")
@perfil_requerido(Usuario.ADMIN)
def trilha():
    consulta = RegistroAuditoria.query
    filtro = request.args
    if filtro.get("entidade") in ENTIDADES:
        consulta = consulta.filter(RegistroAuditoria.entidade == filtro["entidade"])
    if filtro.get("usuario_id", type=int):
        consulta = consulta.filter(RegistroAuditoria.usuario_id == filtro.get("usuario_id", type=int))
    if filtro.get("registro_id", type=int):
        consulta = consulta.filter(RegistroAuditoria.registro_id == filtro.get("registro_id", type=int))
    pagina = consulta.order_by(RegistroAuditoria.id.desc()).paginate(
        page=filtro.get("pagina", 1, type=int), per_page=50, error_out=False)
    return render_template("auditoria/trilha.html", pagina=pagina, filtro=filtro, entidades=ENTIDADES,
                           usuarios=Usuario.query.order_by(Usuario.nome).all())


@bp.route("/integridade")
@perfil_requerido(Usuario.ADMIN)
def integridade():
    resultado = verificar_integridade() if request.args.get("verificar") else None
    return render_template("auditoria/integridade.html", resultado=resultado)
