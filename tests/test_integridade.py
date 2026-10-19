from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from exatamed import estoque
from exatamed.estoque import EstoqueError
from exatamed.models import AlteracaoAuditoria, Dispensacao, Localizacao, Lote, Paciente, Produto, db


@pytest.fixture
def base(app):
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    leito = Localizacao(nome="Leito 1")
    produto = Produto(nome_comercial="Soro")
    paciente = Paciente(nome="Ana")
    db.session.add_all([leito, produto, paciente])
    db.session.commit()
    return dict(sus=sus, leito=leito, produto=produto, paciente=paciente)


def _entrada(b, qtd, custo, dias=1):
    lote = estoque.registrar_entrada(b["produto"], b["sus"], f"L{dias}", date.today() + timedelta(days=300),
                                     qtd, custo, data=datetime.now() - timedelta(days=dias))
    db.session.commit()
    return lote


# ------------------------------------------------------------------- valores decimais exatos

def test_custos_e_quantidades_sao_decimais_exatos(base):
    _entrada(base, "0,3", "0.10", dias=2)
    _entrada(base, "0.3", "0,20", dias=1)
    movs = estoque.registrar_saida(base["produto"], base["sus"], "0,6", motivo="teste")
    db.session.commit()
    custo = sum(m.custo_total for m in movs)
    assert isinstance(custo, Decimal) and custo == Decimal("0.09")  # 0,3 x 0,10 + 0,3 x 0,20
    assert estoque.saldo(base["produto"].id) == 0


def test_quantidade_invalida_e_recusada(base):
    with pytest.raises(EstoqueError, match="inválida"):
        estoque.registrar_entrada(base["produto"], base["sus"], "L", date.today(), "dez", "1")


# ------------------------------------------------------------------- concorrência

def test_baixa_recusa_se_o_saldo_mudou_durante_a_operacao(base):
    lote = _entrada(base, 10, 1)
    # Simula outra transação que consumiu 8 unidades depois que este processo leu o lote.
    lotes_lidos = estoque.lotes_peps(base["produto"].id, base["sus"].id)
    db.session.execute(db.text("UPDATE lotes SET saldo = 2 WHERE id = :id"), {"id": lote.id})
    with pytest.raises(EstoqueError, match="mudou durante a operação"):
        estoque._debitar_lote(lotes_lidos[0], Decimal(5))
    db.session.rollback()


def test_baixas_em_sequencia_nunca_deixam_saldo_negativo(base):
    _entrada(base, 3, 1)
    for _ in range(3):
        estoque.dispensar(base["paciente"], base["sus"], base["leito"], [(base["produto"], 1)])
        db.session.commit()
    with pytest.raises(EstoqueError, match="Saldo insuficiente"):
        estoque.dispensar(base["paciente"], base["sus"], base["leito"], [(base["produto"], 1)])
    assert estoque.saldo(base["produto"].id) == 0


def test_banco_recusa_saldo_negativo(base):
    lote = _entrada(base, 1, 1)
    with pytest.raises(IntegrityError):
        db.session.execute(db.text("UPDATE lotes SET saldo = -1 WHERE id = :id"), {"id": lote.id})
        db.session.commit()
    db.session.rollback()
    assert db.session.get(Lote, lote.id).saldo == 1


# ------------------------------------------------------------------- cadeia de auditoria

from exatamed import auditoria  # noqa: E402
from exatamed.models import Movimentacao, RegistroAcesso, RegistroAuditoria, Usuario  # noqa: E402


def _problemas(nome):
    return auditoria.verificar_cadeia(nome)["problemas"]


def test_movimentacoes_sao_seladas_em_sequencia(base):
    _entrada(base, 10, 1, dias=2)
    estoque.dispensar(base["paciente"], base["sus"], base["leito"], [(base["produto"], 3)])
    db.session.commit()
    movs = Movimentacao.query.order_by(Movimentacao.seq_cadeia).all()
    assert [m.seq_cadeia for m in movs] == [1, 2] and all(len(m.hash) == 64 for m in movs)
    resultado = auditoria.verificar_integridade()
    assert resultado["ok"], resultado


@pytest.mark.parametrize("adulteracao, trecho", [
    ("UPDATE movimentacoes SET quantidade = 99 WHERE id = 1", "conteúdo alterado"),
    ("DELETE FROM movimentacoes WHERE id = 2", "Sequência interrompida"),
    ("DELETE FROM movimentacoes WHERE id = 3", "último elo"),
    ("UPDATE movimentacoes SET hash = 'x' WHERE id = 2", "conteúdo alterado"),
])
def test_adulteracao_direta_no_banco_e_detectada(base, adulteracao, trecho):
    for dias in (3, 2, 1):
        _entrada(base, 5, 1, dias=dias)
    assert not _problemas("movimentacoes")
    db.session.execute(db.text(adulteracao))
    db.session.commit()
    assert any(trecho in p for p in _problemas("movimentacoes")), _problemas("movimentacoes")


def test_registro_inserido_fora_da_aplicacao_e_detectado(base):
    db.session.execute(db.text("INSERT INTO registros_acesso (data, acao, entidade) "
                               "VALUES ('2026-01-01 00:00:00', 'VISUALIZAR', 'paciente')"))
    db.session.commit()
    assert any("fora da aplicação" in p for p in _problemas("registros_acesso"))


def test_verificacao_com_outra_chave_falha(base):
    _entrada(base, 5, 1)
    assert auditoria.verificar_cadeia("movimentacoes", chave=b"outra-chave")["problemas"]


def test_saldo_de_lote_divergente_e_apontado(base):
    lote = _entrada(base, 5, 1)
    db.session.execute(db.text("UPDATE lotes SET saldo = 4 WHERE id = :id"), {"id": lote.id})
    db.session.commit()
    (divergencia,) = auditoria.conciliar_lotes()
    assert divergencia["saldo"] == 4 and divergencia["movimentacoes"] == 5


# ------------------------------------------------------------------- trilha de auditoria

def _trilha(entidade):
    return RegistroAuditoria.query.filter_by(entidade=entidade).order_by(RegistroAuditoria.id).all()


def test_trilha_registra_antes_e_depois_de_cadastros(client, base):
    produto = base["produto"]
    client.post(f"/cadastros/produtos/{produto.id}/editar",
                data={"tipo": "MEDICAMENTO", "nome_comercial": "Soro", "unidade_medida": "FR",
                      "estoque_minimo": "10", "estoque_maximo": "50", "ativo": "on"})
    alteracao = _trilha("produto")[-1]
    assert alteracao.acao == "ALTERACAO"
    assert alteracao.alteracoes_dict["estoque_minimo"] == ["0.0000", "10.0000"]
    admin = Usuario.query.filter_by(login="admin").one()
    assert alteracao.usuario_id == admin.id and alteracao.seq_cadeia


def test_trilha_registra_o_antes_de_objeto_expirado(app):
    # Alterar um objeto logo depois do commit, sem recarregá-lo: o "antes" precisa ser o valor real.
    produto = Produto(nome_comercial="A", unidade_medida="UN")
    db.session.add(produto)
    db.session.commit()
    produto.estoque_minimo, produto.nome_comercial = 5, "B"
    db.session.commit()
    alteracao = _trilha("produto")[-1]
    assert alteracao.acao == "ALTERACAO"
    assert alteracao.alteracoes_dict == {"estoque_minimo": ["0.0000", "5"], "nome_comercial": ["A", "B"]}
    assert auditoria.verificar_integridade()["ok"]


def test_mesmo_valor_em_objeto_expirado_nao_gera_alteracao(app):
    produto = Produto(nome_comercial="A", unidade_medida="UN")
    db.session.add(produto)
    db.session.commit()
    produto.nome_comercial = "A"  # igual ao gravado: não é alteração
    db.session.commit()
    assert [r.acao for r in _trilha("produto")] == ["INCLUSAO"]


def test_objeto_expirado_com_dado_pessoal(app, base):
    paciente, nome = base["paciente"], base["paciente"].nome
    db.session.commit()
    paciente.nome = nome  # mesmo nome, objeto expirado: nada a registrar
    db.session.commit()
    assert [r.acao for r in _trilha("paciente")].count("ALTERACAO") == 0
    paciente.nome = "Outro Nome"
    db.session.commit()
    assert _trilha("paciente")[-1].alteracoes_dict == {"nome": ["(dado pessoal)", "(dado pessoal)"]}


def test_trilha_nao_guarda_valores_de_dados_pessoais(client, base):
    paciente = base["paciente"]
    client.post(f"/cadastros/pacientes/{paciente.id}/editar", data={"nome": "Ana Maria", "cpf": "529.982.247-25"})
    alteracao = _trilha("paciente")[-1]
    assert alteracao.alteracoes_dict["nome"] == ["(dado pessoal)", "(dado pessoal)"]
    gravado = " ".join(i.valor_anterior + i.valor_novo for i in AlteracaoAuditoria.query)
    assert "Ana Maria" not in gravado and "529" not in gravado


def test_trilha_registra_mudanca_de_perfil_e_senha_sem_o_hash(client, base):
    from conftest import criar_usuario
    joao = criar_usuario("joao", Usuario.AUXILIAR)
    client.post(f"/usuarios/{joao.id}/editar", data={"nome": "Joao", "login": "joao", "perfil": "FARMACEUTICO",
                                                     "ativo": "on", "senha": "novaSenha1", "confirmacao": "novaSenha1"})
    alteracao = _trilha("usuario")[-1].alteracoes_dict
    assert alteracao["perfil"] == ["AUXILIAR", "FARMACEUTICO"]
    assert alteracao["senha"] == ["", "(senha definida)"] and "senha_hash" not in alteracao


def test_login_nao_polui_a_trilha(anonimo, base):
    from conftest import criar_usuario, entrar
    criar_usuario("maria", Usuario.AUXILIAR)
    antes = RegistroAuditoria.query.count()
    entrar(anonimo, "maria")
    assert RegistroAuditoria.query.count() == antes


def test_telas_de_auditoria_so_para_administrador(client, auxiliar, farmaceutico, base):
    _entrada(base, 5, 1)
    assert client.get("/auditoria/").status_code == 200
    pagina = client.get("/auditoria/integridade?verificar=1").get_data(as_text=True)
    assert "Nenhum problema encontrado" in pagina
    for cliente in (auxiliar, farmaceutico):
        assert cliente.get("/auditoria/").status_code == 403
        assert cliente.get("/auditoria/integridade").status_code == 403


def test_comando_verificar_integridade(app, base):
    _entrada(base, 5, 1)
    runner = app.test_cli_runner()
    resultado = runner.invoke(args=["verificar-integridade"])
    assert resultado.exit_code == 0 and "[OK] Movimentações de estoque" in resultado.output
    db.session.execute(db.text("UPDATE movimentacoes SET quantidade = 1 WHERE id = 1"))
    db.session.commit()
    resultado = runner.invoke(args=["verificar-integridade"])
    assert resultado.exit_code == 1 and "[FALHA]" in resultado.output


def test_acessos_lgpd_tambem_sao_selados(client, base):
    client.get(f"/cadastros/pacientes/{base['paciente'].id}/editar")
    registro = RegistroAcesso.query.one()
    assert registro.seq_cadeia == 1 and not _problemas("registros_acesso")


def test_atualizacao_sela_o_historico_existente(tmp_path):
    from exatamed import create_app
    arquivo = tmp_path / "v1.db"
    config = {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{arquivo}"}
    app = create_app(config)
    with app.app_context():
        sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
        produto = Produto(nome_comercial="Soro")
        db.session.add(produto)
        db.session.flush()
        for i in range(3):
            estoque.registrar_entrada(produto, sus, f"L{i}", date.today() + timedelta(days=90), 5, 1)
        db.session.commit()
        # Simula um banco da versão 1: sem selos e sem cadeias.
        for tabela in ("movimentacoes", "registros_acesso", "registros_auditoria"):
            db.session.execute(db.text(f"UPDATE {tabela} SET seq_cadeia = NULL, hash = NULL"))
        db.session.execute(db.text("DELETE FROM cadeias_auditoria"))
        db.session.commit()
        db.session.remove()
    app = create_app(config)
    with app.app_context():
        assert [m.seq_cadeia for m in Movimentacao.query.order_by(Movimentacao.id)] == [1, 2, 3]
        assert auditoria.verificar_integridade()["ok"]
        db.session.remove()


@pytest.mark.skipif(not __import__("conftest").BANCO_TESTES.startswith("postgresql"),
                    reason="concorrência real exige PostgreSQL (EXATAMED_TESTE_BANCO)")
def test_dispensacoes_simultaneas_nao_vendem_alem_do_estoque(app, base):
    import threading
    _entrada(base, 5, 1)
    ids = {chave: base[chave].id for chave in ("paciente", "sus", "leito", "produto")}
    resultados = []
    barreira = threading.Barrier(10)

    def dispensar_uma():
        with app.app_context():
            sessao = db.session
            try:
                barreira.wait()
                estoque.dispensar(sessao.get(Paciente, ids["paciente"]), sessao.get(Localizacao, ids["sus"]),
                                  sessao.get(Localizacao, ids["leito"]), [(sessao.get(Produto, ids["produto"]), 1)])
                sessao.commit()
                resultados.append("ok")
            except EstoqueError:
                sessao.rollback()
                resultados.append("recusada")
            finally:
                db.session.remove()

    threads = [threading.Thread(target=dispensar_uma) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    db.session.expire_all()
    assert resultados.count("ok") == 5 and resultados.count("recusada") == 5
    assert estoque.saldo(base["produto"].id) == 0
    numeros = sorted(d.numero for d in Dispensacao.query)
    assert numeros == [1, 2, 3, 4, 5]
    assert auditoria.verificar_integridade()["ok"]
