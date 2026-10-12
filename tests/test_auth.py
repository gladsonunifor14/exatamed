from datetime import date, timedelta

import pytest
from conftest import SENHA, criar_usuario, entrar

from exatamed import create_app, estoque
from exatamed.models import Dispensacao, Localizacao, Medico, Movimentacao, Paciente, Produto, Usuario, db


def test_todas_as_paginas_exigem_login(anonimo):
    for url in ("/", "/estoque/dispensacao", "/cadastros/pacientes/", "/relatorios/inventario",
                "/relatorios/inventario?formato=csv", "/usuarios/"):
        resposta = anonimo.get(url)
        assert resposta.status_code == 302 and "/login" in resposta.location, url
    assert anonimo.get("/saude").status_code == 200
    assert anonimo.get("/login").status_code == 200


def test_login_e_logout(anonimo, app):
    criar_usuario("maria", Usuario.AUXILIAR)
    assert "inválidos" in entrar(anonimo, "maria", "errada").get_data(as_text=True)
    assert anonimo.get("/").status_code == 302
    resposta = entrar(anonimo, "MARIA")  # login não diferencia maiúsculas
    assert resposta.status_code == 302
    assert anonimo.get("/").status_code == 200
    assert Usuario.query.filter_by(login="maria").one().ultimo_acesso is not None
    anonimo.post("/logout")
    assert anonimo.get("/").status_code == 302


def test_redirecionamento_apos_login_so_para_o_proprio_sistema(anonimo, app):
    criar_usuario("maria", Usuario.AUXILIAR)
    for destino in ("https://site-malicioso.com", "//site-malicioso.com", "/\\site-malicioso.com"):
        resposta = anonimo.post("/login", query_string={"next": destino}, data={"login": "maria", "senha": SENHA})
        assert resposta.location == "/", destino
        anonimo.post("/logout")
    anonimo.post("/logout")
    resposta = anonimo.post("/login?next=/estoque/lotes", data={"login": "maria", "senha": SENHA})
    assert resposta.location == "/estoque/lotes"


def test_bloqueio_apos_tentativas_erradas(anonimo, app):
    criar_usuario("maria", Usuario.AUXILIAR)
    for _ in range(5):
        entrar(anonimo, "maria", "errada")
    usuario = Usuario.query.filter_by(login="maria").one()
    assert usuario.bloqueado_ate is not None
    resposta = entrar(anonimo, "maria")  # nem a senha correta entra durante o bloqueio
    assert resposta.status_code == 200 and "bloqueado" in resposta.get_data(as_text=True)


def test_usuario_inativo_nao_entra(anonimo, app):
    criar_usuario("maria", Usuario.AUXILIAR, ativo=False)
    assert entrar(anonimo, "maria").status_code == 200
    assert anonimo.get("/").status_code == 302


def test_senha_provisoria_obriga_troca(anonimo, app):
    criar_usuario("maria", Usuario.AUXILIAR, deve_trocar_senha=True)
    entrar(anonimo, "maria")
    resposta = anonimo.get("/estoque/lotes")
    assert resposta.status_code == 302 and "/minha-senha" in resposta.location
    resposta = anonimo.post("/minha-senha", data={"senha_atual": SENHA, "nova_senha": "curta",
                                                  "confirmacao": "curta"})
    assert "pelo menos 8" in resposta.get_data(as_text=True)
    anonimo.post("/minha-senha", data={"senha_atual": SENHA, "nova_senha": "novaSenha99",
                                       "confirmacao": "novaSenha99"})
    assert anonimo.get("/estoque/lotes").status_code == 200
    assert Usuario.query.filter_by(login="maria").one().conferir_senha("novaSenha99")


def test_admin_gerencia_usuarios(client, app):
    resposta = client.post("/usuarios/novo", data={"nome": "José", "login": "jose", "perfil": "AUXILIAR",
                                                   "ativo": "on", "senha": "inicial123", "confirmacao": "inicial123"})
    assert resposta.status_code == 302
    jose = Usuario.query.filter_by(login="jose").one()
    assert jose.deve_trocar_senha and jose.conferir_senha("inicial123")
    # Login duplicado e senha fraca são recusados.
    resposta = client.post("/usuarios/novo", data={"nome": "Outro", "login": "jose", "perfil": "AUXILIAR",
                                                   "senha": "12345678", "confirmacao": "12345678"})
    texto = resposta.get_data(as_text=True)
    assert "Já existe" in texto and "letras e números" in texto
    # O administrador não pode remover o próprio acesso.
    admin = Usuario.query.filter_by(login="admin").one()
    client.post(f"/usuarios/{admin.id}/editar", data={"nome": "Admin", "login": "admin", "perfil": "AUXILIAR",
                                                      "ativo": "on"})
    assert db.session.get(Usuario, admin.id).perfil == Usuario.ADMIN


def test_permissoes_do_auxiliar(auxiliar):
    assert auxiliar.get("/estoque/dispensacao").status_code == 200
    assert auxiliar.get("/estoque/entrada").status_code == 200
    assert auxiliar.get("/cadastros/pacientes/novo").status_code == 200
    for url in ("/estoque/saida", "/estoque/inventario", "/cadastros/produtos/novo",
                "/cadastros/localizacoes/novo", "/usuarios/"):
        assert auxiliar.get(url).status_code == 403, url
    assert auxiliar.post("/cadastros/localizacoes/1/excluir").status_code == 403


def test_farmaceutico_nao_gerencia_usuarios(farmaceutico):
    assert farmaceutico.get("/estoque/saida").status_code == 200
    assert farmaceutico.get("/cadastros/produtos/novo").status_code == 200
    assert farmaceutico.get("/usuarios/").status_code == 403


@pytest.fixture
def cenario(app):
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    leito = Localizacao(nome="Leito 1")
    morfina = Produto(nome_comercial="Dimorf", principio_ativo="Morfina", controle_especial="A1")
    dipirona = Produto(nome_comercial="Novalgina", principio_ativo="Dipirona")
    paciente = Paciente(nome="Ana", alergias="dipirona")
    medico = Medico(nome="Dr. Rui", crm="1", uf_crm="CE")
    db.session.add_all([leito, morfina, dipirona, paciente, medico])
    db.session.flush()
    for p in (morfina, dipirona):
        estoque.registrar_entrada(p, sus, "L1", date.today() + timedelta(days=100), 10, 1.0)
    db.session.commit()
    return {"origem_id": sus.id, "destino_id": leito.id, "paciente_id": paciente.id, "medico_id": medico.id,
            "prescricao": "RX-1", "morfina": morfina.id, "dipirona": dipirona.id}


def _dispensar(cliente, c, produto, **extra):
    dados = {k: c[k] for k in ("origem_id", "destino_id", "paciente_id", "medico_id", "prescricao")}
    dados.update(item_produto=[c[produto]], item_quantidade=["1"], **extra)
    return cliente.post("/estoque/dispensacao", data=dados)


def test_auxiliar_nao_dispensa_controlado_nem_libera_alergia(auxiliar, cenario):
    resposta = _dispensar(auxiliar, cenario, "morfina")
    assert "só podem ser dispensados por farmacêutico" in resposta.get_data(as_text=True)
    resposta = _dispensar(auxiliar, cenario, "dipirona", confirmar_alergia="on")
    assert "Somente um farmacêutico pode liberar" in resposta.get_data(as_text=True)
    assert Dispensacao.query.count() == 0


def test_farmaceutico_dispensa_e_fica_registrado(farmaceutico, cenario):
    assert _dispensar(farmaceutico, cenario, "morfina").status_code == 302
    assert _dispensar(farmaceutico, cenario, "dipirona", confirmar_alergia="on").status_code == 302
    farma = Usuario.query.filter_by(login="farma").one()
    for disp in Dispensacao.query.all():
        assert disp.usuario_id == farma.id and disp.responsavel == farma.nome
    baixas = Movimentacao.query.filter_by(tipo=Movimentacao.DISPENSACAO).all()
    assert baixas and all(m.usuario_id == farma.id for m in baixas)


def test_formularios_exigem_token_csrf(app):
    app.config["WTF_CSRF_ENABLED"] = True
    criar_usuario("maria", Usuario.ADMIN)
    cliente = app.test_client()
    assert entrar(cliente, "maria").status_code == 400  # sem token
    pagina = cliente.get("/login").get_data(as_text=True)
    token = pagina.split('name="csrf_token" value="')[1].split('"')[0]
    resposta = cliente.post("/login", data={"login": "maria", "senha": SENHA, "csrf_token": token})
    assert resposta.status_code == 302


def test_admin_inicial_por_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("EXATAMED_ADMIN_LOGIN", "chefe")
    monkeypatch.setenv("EXATAMED_ADMIN_SENHA", "senhaForte1")
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        chefe = Usuario.query.one()
        assert chefe.login == "chefe" and chefe.perfil == Usuario.ADMIN and chefe.conferir_senha("senhaForte1")
        db.drop_all()


def test_producao_exige_chave_secreta(monkeypatch):
    monkeypatch.setenv("EXATAMED_ENV", "production")
    monkeypatch.delenv("EXATAMED_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="EXATAMED_SECRET_KEY"):
        create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
