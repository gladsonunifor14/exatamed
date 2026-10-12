import re

from conftest import SENHA, criar_usuario, entrar

from exatamed.auth import MAX_FALHAS_POR_IP
from exatamed.demo import popular
from exatamed.models import Usuario, db

PAGINAS = ["/", "/estoque/entrada", "/estoque/dispensacao", "/estoque/lotes", "/estoque/movimentacoes",
           "/cadastros/pacientes/", "/cadastros/pacientes/novo", "/relatorios/", "/relatorios/consumo_diario",
           "/ajuda/", "/lgpd/", "/auditoria/", "/auditoria/integridade", "/usuarios/", "/estoque/dispensacao/1"]


def test_csp_estrita_e_sem_javascript_inline(client, anonimo):
    popular()
    for cliente, url in [(anonimo, "/login")] + [(client, u) for u in PAGINAS]:
        resposta = cliente.get(url)
        assert resposta.status_code == 200, url
        csp = resposta.headers["Content-Security-Policy"]
        assert "script-src 'self';" in csp and "frame-ancestors 'none'" in csp and "unsafe-eval" not in csp
        html = resposta.get_data(as_text=True)
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), f"script inline em {url}"
        assert not re.search(r"\son[a-z]+=", html), f"handler inline em {url}"
        corpo = re.sub(r'https://viacep[^"]*', "", html.split("<body")[1])
        assert "cdn.jsdelivr" not in html and "https://" not in corpo


def test_assets_servidos_localmente(client):
    for caminho in ("vendor/bootstrap/bootstrap.min.css", "vendor/bootstrap/bootstrap.min.js",
                    "vendor/bootstrap/popper.min.js", "vendor/bootstrap-icons/bootstrap-icons.min.css",
                    "vendor/bootstrap-icons/fonts/bootstrap-icons.woff2", "js/app.js", "js/dispensacao.js"):
        assert client.get(f"/static/{caminho}").status_code == 200, caminho


def test_paginas_autenticadas_nao_ficam_em_cache(client, anonimo):
    assert client.get("/cadastros/pacientes/").headers["Cache-Control"] == "no-store"
    assert "no-store" not in anonimo.get("/login").headers.get("Cache-Control", "")


def test_dados_do_cadastro_sao_escapados_no_html(client):
    from exatamed.models import Paciente
    db.session.add(Paciente(nome="<script>alert(1)</script>", alergias='<img src=x onerror="alert(2)">'))
    db.session.commit()
    html = client.get("/cadastros/pacientes/").get_data(as_text=True)
    assert "<script>alert(1)" not in html and "&lt;script&gt;alert(1)" in html
    assert '<img src=x' not in html


def test_troca_de_senha_pelo_admin_encerra_sessoes_do_usuario(client, app):
    joao = criar_usuario("joao", Usuario.AUXILIAR)
    sessao_joao = app.test_client()
    entrar(sessao_joao, "joao")
    assert sessao_joao.get("/").status_code == 200
    client.post(f"/usuarios/{joao.id}/editar", data={"nome": "Joao", "login": "joao", "perfil": "AUXILIAR",
                                                     "ativo": "on", "senha": "novaSenha1", "confirmacao": "novaSenha1"})
    resposta = sessao_joao.get("/")
    assert resposta.status_code == 302 and "/login" in resposta.location


def test_mudanca_de_perfil_ou_desativacao_encerram_sessoes(client, app):
    maria = criar_usuario("maria", Usuario.FARMACEUTICO)
    sessao = app.test_client()
    entrar(sessao, "maria")
    client.post(f"/usuarios/{maria.id}/editar", data={"nome": "Maria", "login": "maria", "perfil": "AUXILIAR",
                                                      "ativo": "on"})
    assert sessao.get("/").status_code == 302


def test_troca_da_propria_senha_mantem_a_sessao_atual_e_encerra_as_outras(app):
    criar_usuario("ana", Usuario.AUXILIAR)
    atual, outra = app.test_client(), app.test_client()
    entrar(atual, "ana")
    entrar(outra, "ana")
    atual.post("/minha-senha", data={"senha_atual": SENHA, "nova_senha": "outraSenha9", "confirmacao": "outraSenha9"})
    assert atual.get("/").status_code == 200
    assert outra.get("/").status_code == 302


def test_sessao_de_versao_anterior_nao_e_aceita(app):
    """Cookies de sessão da v1 guardavam só o id do usuário."""
    from exatamed.auth import carregar_usuario
    usuario = criar_usuario("velho", Usuario.ADMIN)
    assert carregar_usuario(str(usuario.id)) is None
    assert carregar_usuario(f"{usuario.id}:{usuario.versao_sessao}") == usuario


def test_limite_de_tentativas_por_ip(anonimo, app):
    criar_usuario("ana", Usuario.AUXILIAR)
    for i in range(MAX_FALHAS_POR_IP):
        entrar(anonimo, f"inexistente{i}", "errada")
    resposta = entrar(anonimo, "ana")  # até a senha certa é barrada durante a janela
    assert resposta.status_code == 429 and "Muitas tentativas" in resposta.get_data(as_text=True)
