import re
from datetime import date, timedelta
from pathlib import Path

from conftest import criar_usuario
from exatamed import estoque
from exatamed.ajuda import carregar_guia, primeiros_passos
from exatamed.demo import popular
from exatamed.models import Localizacao, Medico, Paciente, Produto, Usuario, db

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _ids_do_guia():
    html, _ = carregar_guia()
    return set(re.findall(r'id="([^"]+)"', html))


def test_links_internos_do_guia_apontam_para_secoes_existentes(app):
    ids = _ids_do_guia()
    texto = (DOCS / "GUIA_DO_USUARIO.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\(#([^)]+)\)", texto)
    assert links
    for ancora in links:
        assert ancora in ids, ancora


def test_imagens_do_guia_existem():
    texto = (DOCS / "GUIA_DO_USUARIO.md").read_text(encoding="utf-8")
    imagens = re.findall(r"\]\((img/[^)]+)\)", texto)
    assert imagens
    for imagem in imagens:
        assert (DOCS / imagem).is_file(), imagem


def test_checklist_aponta_para_secoes_do_guia(client):
    ids = _ids_do_guia()
    with client.application.test_request_context():
        for passo in primeiros_passos():
            assert passo["ancora"] in ids, passo["ancora"]
    assert "roteiro-de-implantação-administrador" in ids


def test_pagina_de_ajuda_para_todos_os_perfis(client, auxiliar):
    for cliente in (client, auxiliar):
        resposta = cliente.get("/ajuda/")
        texto = resposta.get_data(as_text=True)
        assert resposta.status_code == 200
        assert "Guia do usuário" in texto and 'src="img/login.png"' in texto
    assert client.get("/ajuda/img/login.png").status_code == 200
    assert client.get("/ajuda/img/nao-existe.png").status_code == 404
    assert client.get("/ajuda/img/../GUIA_DO_USUARIO.md").status_code == 404


def test_ajuda_exige_login(anonimo):
    assert anonimo.get("/ajuda/").status_code == 302
    assert anonimo.get("/ajuda/img/login.png").status_code == 302


def test_checklist_marca_etapas_conforme_os_dados(client):
    texto = client.get("/").get_data(as_text=True)
    assert "Primeiros passos" in texto and "1 de 8 etapas" in texto
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    produto = Produto(nome_comercial="Soro", estoque_minimo=1, estoque_maximo=10)
    db.session.add_all([Localizacao(nome="Leito 1"), produto, Medico(nome="Dr", crm="1", uf_crm="CE"),
                        Paciente(nome="Ana")])
    db.session.flush()
    estoque.registrar_entrada(produto, sus, "L1", date.today() + timedelta(days=90), 5, 1.0)
    db.session.commit()
    assert "6 de 8 etapas" in client.get("/").get_data(as_text=True)


def test_checklist_some_quando_tudo_esta_feito(client):
    popular()
    criar_usuario("aux", Usuario.AUXILIAR)
    assert "Primeiros passos" not in client.get("/").get_data(as_text=True)


def test_checklist_pode_ser_ocultado_e_reexibido(client):
    assert "Primeiros passos" in client.get("/").get_data(as_text=True)
    client.post("/ajuda/primeiros-passos/ocultar")
    assert "Primeiros passos" not in client.get("/").get_data(as_text=True)
    assert "Mostrar primeiros passos" in client.get("/ajuda/").get_data(as_text=True)
    client.post("/ajuda/primeiros-passos/mostrar")
    assert "Primeiros passos" in client.get("/").get_data(as_text=True)


def test_checklist_so_para_administrador(auxiliar, farmaceutico):
    for cliente in (auxiliar, farmaceutico):
        assert "Primeiros passos" not in cliente.get("/").get_data(as_text=True)
        assert cliente.post("/ajuda/primeiros-passos/ocultar").status_code == 403
