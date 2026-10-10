"""Dados de demonstração (`flask --app exatamed demo`)."""

import random
from datetime import date, datetime, timedelta

from . import estoque
from .models import Localizacao, Medico, Paciente, Produto, db


def gerar_cpf(rng):
    base = [rng.randint(0, 9) for _ in range(9)]
    for tamanho in (9, 10):
        soma = sum(d * p for d, p in zip(base, range(tamanho + 1, 1, -1)))
        base.append((soma * 10) % 11 % 10)
    d = "".join(map(str, base))
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def gerar_cns(rng):
    while True:
        base = [rng.choice([7, 8, 9])] + [rng.randint(0, 9) for _ in range(13)]
        soma = sum(d * p for d, p in zip(base, range(15, 1, -1)))
        ultimo = (11 - soma % 11) % 11
        if ultimo < 10:
            return "".join(map(str, base + [ultimo]))


def popular(semente=42):
    rng = random.Random(semente)
    locais = {l.nome: l for l in Localizacao.query.all()}
    for nome in ("Leito 1", "Leito 2", "Leito 3", "Sala de parada", "Sala de recuperação", "UTI"):
        if nome not in locais:
            locais[nome] = Localizacao(nome=nome)
            db.session.add(locais[nome])

    medicos = [
        Medico(nome="Ana Beatriz Moreira", crm="12345", uf_crm="CE", especialidade="Clínica médica",
               cpf=gerar_cpf(rng), sexo="F", data_nascimento=date(1980, 5, 12), cidade="Fortaleza", uf="CE"),
        Medico(nome="Carlos Eduardo Lima", crm="54321", uf_crm="CE", especialidade="Anestesiologia",
               cpf=gerar_cpf(rng), sexo="M", data_nascimento=date(1975, 9, 3), cidade="Fortaleza", uf="CE"),
    ]
    pacientes = [
        Paciente(nome="Maria das Graças Silva", nome_mae="Francisca Silva", data_nascimento=date(1958, 3, 21),
                 sexo="F", cpf=gerar_cpf(rng), cartao_sus=gerar_cns(rng), alergias="dipirona",
                 tipo_sanguineo="O+", historico_doencas="Hipertensão, diabetes tipo 2", profissao="Aposentada",
                 cep="60000-000", cidade="Fortaleza", uf="CE"),
        Paciente(nome="João Pedro Albuquerque", nome_mae="Luciana Albuquerque", data_nascimento=date(2015, 7, 2),
                 sexo="M", cpf=gerar_cpf(rng), cartao_sus=gerar_cns(rng), alergias="penicilina, látex",
                 responsavel="Luciana Albuquerque", grau_parentesco="Mãe", tipo_sanguineo="A+",
                 plano_saude="Unimed", cidade="Fortaleza", uf="CE"),
        Paciente(nome="Francisco Holanda Neto", nome_mae="Raimunda Holanda", data_nascimento=date(1990, 11, 30),
                 sexo="M", cpf=gerar_cpf(rng), cartao_sus=gerar_cns(rng), tipo_sanguineo="B-",
                 profissao="Pedreiro", cidade="Caucaia", uf="CE"),
    ]
    sus, particular = locais["Farmácia SUS"], locais["Farmácia Particular"]
    produtos = [
        Produto(nome_comercial="Novalgina", principio_ativo="Dipirona sódica", apresentacao="500 mg/mL ampola 2 mL",
                laboratorio="Sanofi", unidade_medida="AMP", estoque_minimo=50, estoque_maximo=300,
                alertas_alergia="dipirona, pirazolonas", localizacao_padrao=sus),
        Produto(nome_comercial="Amoxil", principio_ativo="Amoxicilina", apresentacao="500 mg cápsula",
                laboratorio="GSK", unidade_medida="CAP", controle_especial="ATB", estoque_minimo=100,
                estoque_maximo=500, alertas_alergia="penicilinas, betalactâmicos", localizacao_padrao=sus),
        Produto(nome_comercial="Dimorf", principio_ativo="Sulfato de morfina", apresentacao="10 mg/mL ampola 1 mL",
                laboratorio="Cristália", unidade_medida="AMP", controle_especial="A1", estoque_minimo=20,
                estoque_maximo=80, localizacao_padrao=particular),
        Produto(nome_comercial="Soro fisiológico 0,9%", principio_ativo="Cloreto de sódio",
                apresentacao="Bolsa 500 mL", laboratorio="Baxter", unidade_medida="FR",
                estoque_minimo=100, estoque_maximo=400, localizacao_padrao=sus),
        Produto(tipo="MATERIAL", nome_comercial="Luva de procedimento M", apresentacao="Caixa com 100",
                laboratorio="Descarpack", unidade_medida="CX", estoque_minimo=10, estoque_maximo=60,
                alertas_alergia="látex", localizacao_padrao=sus),
        Produto(tipo="MATERIAL", nome_comercial="Seringa 10 mL", apresentacao="Luer lock sem agulha",
                laboratorio="BD", unidade_medida="UN", estoque_minimo=200, estoque_maximo=1000,
                localizacao_padrao=sus),
    ]
    db.session.add_all(medicos + pacientes + produtos)
    db.session.flush()

    hoje = date.today()
    inicio = datetime.combine(hoje - timedelta(days=30), datetime.min.time()).replace(hour=8)
    # Fração do estoque máximo recebida por camada; alguns itens ficam abaixo do mínimo.
    fatores = [0.2, 0.2, 0.15, 0.2, 0.1, 0.2]
    for i, produto in enumerate(produtos):
        for local in (sus, particular):
            for camada in range(2):
                estoque.registrar_entrada(
                    produto, local, f"L{produto.id:02d}{camada}{local.id}", hoje + timedelta(days=60 + 200 * camada),
                    quantidade=round(produto.estoque_maximo * fatores[i]), custo_unitario=round(rng.uniform(0.5, 15), 2)
                    * (1 + 0.1 * camada), documento=f"NF {1000 + i}", data=inicio + timedelta(days=camada * 10),
                )
    leitos = [locais[n] for n in ("Leito 1", "Leito 2", "Leito 3", "Sala de parada", "Sala de recuperação")]
    for dia in range(29, -1, -1):
        for _ in range(rng.randint(1, 3)):
            paciente = rng.choice(pacientes)
            origem = sus if not paciente.plano_saude else particular
            candidatos = [p for p in produtos if not estoque.verificar_alergias(paciente, p)]
            itens = [(p, rng.randint(1, 4)) for p in rng.sample(candidatos, 2)]
            try:
                estoque.dispensar(paciente, origem, rng.choice(leitos), itens, medico=rng.choice(medicos),
                                  prescricao=f"RX-{rng.randint(1000, 9999)}", responsavel="Farmacêutico plantonista",
                                  data=datetime.combine(hoje - timedelta(days=dia), datetime.min.time())
                                  + timedelta(hours=rng.randint(7, 20)))
            except estoque.EstoqueError:
                pass
    db.session.commit()
