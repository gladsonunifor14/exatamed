from datetime import date, datetime, timedelta

import pytest
from conftest import SENHA, criar_usuario, entrar

from exatamed import estoque, validacao
from exatamed.lgpd import LGPDError, anonimizar
from exatamed.models import (
    Dispensacao,
    Localizacao,
    Medico,
    Movimentacao,
    Paciente,
    Produto,
    RegistroAcesso,
    Usuario,
    db,
)

CPF = "529.982.247-25"
CNS = "940781618495933"


@pytest.fixture
def base(app):
    sus = Localizacao.query.filter_by(nome="Farmácia SUS").one()
    leito = Localizacao(nome="Leito 1")
    soro = Produto(nome_comercial="Soro")
    morfina = Produto(nome_comercial="Dimorf", controle_especial="A1")
    paciente = Paciente(nome="Maria das Dores", nome_mae="Ana", cpf=CPF, cartao_sus=CNS, telefone="(85) 99999-1234",
                        data_nascimento=date(1970, 6, 15), alergias="dipirona", cidade="Fortaleza", uf="CE",
                        sexo="F", plano_saude="Unimed")
    medico = Medico(nome="Dr. Rui Barbosa", crm="1234", uf_crm="CE", cpf="111.444.777-35")
    db.session.add_all([leito, soro, morfina, paciente, medico])
    db.session.flush()
    for produto in (soro, morfina):
        estoque.registrar_entrada(produto, sus, "L1", date.today() + timedelta(days=400), 100, 2.0,
                                  data=datetime.now() - timedelta(days=4 * 365))
    db.session.commit()
    return dict(sus=sus, leito=leito, soro=soro, morfina=morfina, paciente=paciente, medico=medico)


def _dispensar(b, produto="soro", data=None, usuario_id=None):
    d = estoque.dispensar(b["paciente"], b["sus"], b["leito"], [(b[produto], 1)], medico=b["medico"],
                          prescricao="RX-1", data=data)
    if usuario_id:
        d.usuario_id = usuario_id
    db.session.commit()
    return d


def _acessos(acao=None):
    consulta = RegistroAcesso.query
    return consulta.filter_by(acao=acao).all() if acao else consulta.all()


# ------------------------------------------------------------------- mascaramento

def test_mascaras():
    assert validacao.mascarar_cpf(CPF) == "***.982.247-**"
    assert validacao.mascarar_cns(CNS) == "***********5933"
    assert validacao.mascarar_telefone("(85) 99999-1234") == "(**) *****-1234"
    assert validacao.mascarar_email("maria@hospital.org") == "m***@hospital.org"
    assert validacao.mascarar_generico("2005009123") == "*******123"
    assert validacao.mascarar_cpf(None) == "" and validacao.mascarar_telefone("") == ""


def test_listas_e_relatorios_mostram_documentos_mascarados(client, base):
    _dispensar(base)
    lista = client.get("/cadastros/pacientes/").get_data(as_text=True)
    assert "***.982.247-**" in lista and CPF not in lista and CNS not in lista
    assert "(**) *****" not in lista  # telefone não aparece na lista de pacientes
    medicos = client.get("/cadastros/medicos/").get_data(as_text=True)
    assert "111.444.777-35" not in medicos
    busca = client.get("/estoque/pacientes/busca?q=Maria").get_data(as_text=True)
    assert "***.982.247-**" in busca and CPF not in busca
    for formato in ("", "&formato=csv"):
        texto = client.get(f"/relatorios/consumo_paciente?inicio=2000-01-01{formato}").get_data(as_text=True)
        assert "***.982.247-**" in texto and CPF not in texto and CNS not in texto and "5933" in texto


def test_busca_por_cpf_continua_funcionando(client, base):
    assert "Maria das Dores" in client.get("/cadastros/pacientes/?q=529.982").get_data(as_text=True)


def test_relatorios_anonimizados(client, base):
    _dispensar(base)
    p = base["paciente"]
    for chave in ("consumo_paciente", "resumo_dispensacao"):
        for formato in ("", "&formato=csv"):
            texto = client.get(f"/relatorios/{chave}?inicio=2000-01-01&anonimo=1{formato}").get_data(as_text=True)
            if not formato:  # na página, confere só as tabelas (o filtro de pacientes não é impresso)
                texto = texto.rsplit("</form>", 1)[-1]
            assert p.pseudonimo in texto and "Maria" not in texto and "982.247" not in texto, chave
    assert not _acessos(RegistroAcesso.EXPORTAR)  # relatório anônimo não registra exportação


# ------------------------------------------------------------------- registro de acessos

def test_acessos_a_dados_pessoais_sao_registrados(client, base):
    p, d = base["paciente"], _dispensar(base)
    client.get(f"/cadastros/pacientes/{p.id}/editar")
    client.post(f"/cadastros/pacientes/{p.id}/editar", data={"nome": p.nome, "cpf": CPF})
    client.post("/cadastros/pacientes/novo", data={"nome": "Novo Paciente"})
    client.get(f"/estoque/dispensacao/{d.id}")
    client.get("/relatorios/consumo_paciente?formato=csv&inicio=2000-01-01")
    client.get("/cadastros/pacientes/")  # lista mascarada: não registra
    registros = [(r.acao, r.entidade) for r in RegistroAcesso.query.order_by(RegistroAcesso.id)]
    assert registros == [("VISUALIZAR", "paciente"), ("ALTERAR", "paciente"), ("INCLUIR", "paciente"),
                         ("VISUALIZAR", "dispensacao"), ("EXPORTAR", "relatorio")]
    admin = Usuario.query.filter_by(login="admin").one()
    assert all(r.usuario_id == admin.id for r in RegistroAcesso.query)
    pagina = client.get("/lgpd/").get_data(as_text=True)
    assert "Visualizou" in pagina and "Exportou" in pagina
    assert "Exportou" not in client.get("/lgpd/?acao=VISUALIZAR").get_data(as_text=True).split("<tbody>")[1]


def test_registro_de_acessos_so_para_administrador(auxiliar, farmaceutico):
    for cliente in (auxiliar, farmaceutico):
        assert cliente.get("/lgpd/").status_code == 403


# ------------------------------------------------------------------- anonimização de paciente

def test_anonimizar_paciente_preserva_historico(client, base):
    p = base["paciente"]
    d = _dispensar(base)
    custo = d.custo_total
    resposta = client.post(f"/lgpd/anonimizar/paciente/{p.id}",
                           data={"motivo": "Pedido do titular, protocolo 12/2026", "confirmacao": "anonimizar"})
    assert resposta.status_code == 302
    p = db.session.get(Paciente, p.id)
    assert p.anonimizado and p.nome == f"Paciente anonimizado {p.pseudonimo}"
    for campo in ("nome_mae", "cpf", "cartao_sus", "telefone", "alergias", "cidade"):
        assert getattr(p, campo) is None, campo
    assert p.data_nascimento == date(1970, 1, 1) and p.sexo == "F" and p.uf == "CE"
    d = db.session.get(Dispensacao, d.id)
    assert d.paciente_id == p.id and d.custo_total == custo  # histórico preservado
    registro = RegistroAcesso.query.filter_by(acao="ANONIMIZAR").one()
    assert registro.descricao == "Pedido do titular, protocolo 12/2026"
    # Não pode ser editado nem receber novas dispensações.
    assert client.get(f"/cadastros/pacientes/{p.id}/editar").status_code == 302
    assert p.pseudonimo not in client.get("/estoque/dispensacao").get_data(as_text=True)
    assert "Anonimizado" in client.get("/cadastros/pacientes/").get_data(as_text=True)


def test_anonimizacao_exige_motivo_e_confirmacao(client, base):
    pid = base["paciente"].id
    client.post(f"/lgpd/anonimizar/paciente/{pid}", data={"motivo": "x", "confirmacao": "sim"})
    client.post(f"/lgpd/anonimizar/paciente/{pid}", data={"motivo": "", "confirmacao": "ANONIMIZAR"})
    assert not db.session.get(Paciente, pid).anonimizado


def test_anonimizacao_so_para_administrador(auxiliar, farmaceutico, base):
    for cliente in (auxiliar, farmaceutico):
        resposta = cliente.post(f"/lgpd/anonimizar/paciente/{base['paciente'].id}",
                                data={"motivo": "x", "confirmacao": "ANONIMIZAR"})
        assert resposta.status_code == 403
    assert not db.session.get(Paciente, base["paciente"].id).anonimizado


def test_prazo_de_guarda_de_controlados(client, base):
    p = base["paciente"]
    _dispensar(base, "morfina", data=datetime.now() - timedelta(days=200))
    pagina = client.get(f"/lgpd/anonimizar/paciente/{p.id}").get_data(as_text=True)
    assert "Não é possível anonimizar agora" in pagina
    client.post(f"/lgpd/anonimizar/paciente/{p.id}", data={"motivo": "pedido", "confirmacao": "ANONIMIZAR"})
    assert not db.session.get(Paciente, p.id).anonimizado
    # O médico prescritor também fica retido pelo mesmo prazo.
    with pytest.raises(LGPDError, match="controle especial"):
        anonimizar("medico", base["medico"], "pedido")


def test_controlado_fora_do_prazo_de_guarda_permite_anonimizar(client, base):
    _dispensar(base, "morfina", data=datetime.now() - timedelta(days=3 * 365))
    client.post(f"/lgpd/anonimizar/paciente/{base['paciente'].id}",
                data={"motivo": "pedido", "confirmacao": "ANONIMIZAR"})
    assert db.session.get(Paciente, base["paciente"].id).anonimizado


# ------------------------------------------------------------------- médico e usuário

def test_anonimizar_medicos(client, base):
    outro = Medico(nome="Dra. Lia", crm="999", uf_crm="CE")
    db.session.add(outro)
    db.session.commit()
    for medico in (base["medico"], outro):
        client.post(f"/lgpd/anonimizar/medico/{medico.id}",
                    data={"motivo": "desligamento", "confirmacao": "ANONIMIZAR"})
    for medico in Medico.query.all():
        assert medico.anonimizado and medico.cpf is None and medico.crm == f"ANON{medico.id}"


def test_anonimizar_usuario(client, base):
    joao = criar_usuario("joao", Usuario.FARMACEUTICO, email="joao@hospital.org", registro_profissional="CRF 1")
    d = _dispensar(base, usuario_id=joao.id)
    d.responsavel = "Joao"
    db.session.commit()
    client.post(f"/lgpd/anonimizar/usuario/{joao.id}", data={"motivo": "desligamento", "confirmacao": "ANONIMIZAR"})
    joao = db.session.get(Usuario, joao.id)
    assert joao.anonimizado and not joao.ativo and joao.login == f"anonimo-{joao.id}"
    assert joao.email is None and joao.registro_profissional is None
    assert db.session.get(Dispensacao, d.id).responsavel == joao.nome
    assert client.get(f"/usuarios/{joao.id}/editar").status_code == 302
    novo_cliente = client.application.test_client()
    assert entrar(novo_cliente, "joao").status_code == 200  # não entra mais


def test_nao_anonimiza_a_si_mesmo_nem_o_ultimo_administrador(client, app):
    admin = Usuario.query.filter_by(login="admin").one()
    client.post(f"/lgpd/anonimizar/usuario/{admin.id}", data={"motivo": "x", "confirmacao": "ANONIMIZAR"})
    assert not db.session.get(Usuario, admin.id).anonimizado
    outro_admin = criar_usuario("chefe", Usuario.ADMIN)
    cliente = app.test_client()
    entrar(cliente, "chefe")
    admin_inativo = db.session.get(Usuario, admin.id)
    # Com dois administradores ativos, um pode anonimizar o outro.
    cliente.post(f"/lgpd/anonimizar/usuario/{admin_inativo.id}", data={"motivo": "x", "confirmacao": "ANONIMIZAR"})
    assert db.session.get(Usuario, admin.id).anonimizado
    assert not db.session.get(Usuario, outro_admin.id).anonimizado


# ------------------------------------------------------------------- cópia do banco

def test_anonimizar_banco_inteiro(app, base):
    criar_usuario("maria.farma", Usuario.FARMACEUTICO, email="m@h.org")
    _dispensar(base)
    runner = app.test_cli_runner()
    resultado = runner.invoke(args=["anonimizar-banco"])
    assert resultado.exit_code != 0 and "--confirmar" in resultado.output
    resultado = runner.invoke(args=["anonimizar-banco", "--confirmar"])
    assert resultado.exit_code == 0, resultado.output
    assert all(p.anonimizado and p.cpf is None for p in Paciente.query)
    assert all(m.anonimizado for m in Medico.query)
    usuario = Usuario.query.filter_by(login="maria.farma").one()
    assert usuario.nome.startswith("Usuário ") and usuario.email is None and usuario.conferir_senha(SENHA)
    assert RegistroAcesso.query.count() == 0
    assert Movimentacao.query.count() > 0  # estoque intacto


def test_anonimizar_banco_bloqueado_em_producao(app):
    app.config["PRODUCAO"] = True
    resultado = app.test_cli_runner().invoke(args=["anonimizar-banco", "--confirmar"])
    assert resultado.exit_code != 0 and "produção" in resultado.output
