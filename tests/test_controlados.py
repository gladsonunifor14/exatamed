import pytest

from exatamed.controlados import PRIORIDADE, SUBSTANCIAS, classificar
from exatamed.models import Produto


@pytest.mark.parametrize("texto, lista, substancia", [
    ("Sulfato de morfina", "A1", "morfina"),
    ("Citrato de FENTANILA", "A1", "fentanila"),
    ("Cloridrato de petidina", "A1", "petidina"),
    ("Cloridrato de tramadol", "A2", "tramadol"),
    ("Paracetamol + fosfato de codeína", "A2", "codeina"),
    ("Metilfenidato", "A3", "metilfenidato"),
    ("Midazolam", "B1", "midazolam"),
    ("Hemitartarato de zolpidem", "B1", "zolpidem"),
    ("Cloridrato de sibutramina", "B2", "sibutramina"),
    ("Haloperidol decanoato", "C1", "haloperidol"),
    ("Ácido valproico", "C1", "valproico"),
    ("Carbonato de lítio", "C1", "litio"),
    ("Isotretinoína", "C2", "isotretinoina"),
    ("Talidomida", "C3", "talidomida"),
    ("Cipionato de testosterona", "C5", "testosterona"),
    ("Sulfato de efedrina", "D1", "efedrina"),
    ("Amoxicilina + clavulanato de potássio", "ATB", "amoxicilina"),
    ("Piperacilina sódica + tazobactam", "ATB", "piperacilina"),
    ("Semaglutida", "GLP1", "semaglutida"),
])
def test_classifica_pelo_principio_ativo(texto, lista, substancia):
    assert classificar(texto) == (lista, substancia)


@pytest.mark.parametrize("texto", ["Dipirona sódica", "Paracetamol", "Soro fisiológico 0,9%", "Nalbufina-x", "", None])
def test_nao_controlado_ou_sem_correspondencia_exata(texto):
    # "Nalbufina-x" não é a palavra "nalbufina": evita falso positivo dentro de outro nome.
    assert classificar(texto) == (None, None)


def test_palavra_inteira_e_lista_mais_restritiva():
    assert classificar("Etilmorfina") == ("A2", "etilmorfina")  # não confunde com morfina (A1)
    assert classificar("Benzilpenicilina benzatina") == ("ATB", "benzilpenicilina")
    assert classificar("Diazepam + amitriptilina") == ("B1", "diazepam")  # B1 prevalece sobre C1
    assert classificar("", "TRAMADOL 50MG/ML AMP") == ("A2", "tramadol")  # nome usado na falta do princípio


def test_tabela_consistente():
    assert set(SUBSTANCIAS) == set(PRIORIDADE)
    todas = [s for lista in SUBSTANCIAS.values() for s in lista]
    assert len(todas) == len(set(todas)), "substância em mais de uma lista"


PRODUTO = {"tipo": "MEDICAMENTO", "unidade_medida": "AMP", "ativo": "on"}


def test_cadastro_preenche_controle_especial(client):
    resposta = client.post("/cadastros/produtos/novo", follow_redirects=True,
                           data=dict(PRODUTO, nome_comercial="Dimorf", principio_ativo="Sulfato de morfina"))
    assert "classificado automaticamente: morfina — A1 - Entorpecentes (Portaria 344/98)" in resposta.get_data(
        as_text=True)
    assert Produto.query.filter_by(nome_comercial="Dimorf").one().controle_especial == "A1"


def test_escolha_diferente_da_tabela_e_mantida_com_aviso(client):
    resposta = client.post("/cadastros/produtos/novo", follow_redirects=True,
                           data=dict(PRODUTO, nome_comercial="Tylex", principio_ativo="Paracetamol + codeína",
                                     controle_especial="C1"))
    assert "classifica codeina como A2" in resposta.get_data(as_text=True)
    assert Produto.query.filter_by(nome_comercial="Tylex").one().controle_especial == "C1"


def test_produto_nao_controlado_continua_sem_controle(client):
    client.post("/cadastros/produtos/novo", data=dict(PRODUTO, nome_comercial="Novalgina", principio_ativo="Dipirona"))
    assert Produto.query.filter_by(nome_comercial="Novalgina").one().controle_especial is None


def test_consulta_da_classificacao_para_a_tela(client, anonimo):
    dados = client.get("/cadastros/produtos/controle-especial?principio_ativo=Midazolam").get_json()
    assert dados == {"lista": "B1", "substancia": "midazolam", "rotulo": "B1 - Psicotrópicos",
                     "referencia": "Portaria 344/98"}
    dados = client.get("/cadastros/produtos/controle-especial?principio_ativo=Ceftriaxona").get_json()
    assert dados["referencia"] == "RDC 471/2021"
    assert client.get("/cadastros/produtos/controle-especial?principio_ativo=Dipirona").get_json() == {"lista": ""}
    assert anonimo.get("/cadastros/produtos/controle-especial?principio_ativo=Midazolam").status_code == 302


def test_formulario_de_produto_carrega_o_preenchimento_automatico(client):
    pagina = client.get("/cadastros/produtos/novo").get_data(as_text=True)
    assert 'data-classificar="principio_ativo,nome_comercial"' in pagina and "controle_especial.js" in pagina
    assert "Agonista GLP-1" in pagina
