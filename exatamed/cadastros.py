"""Cadastros (CRUD) genéricos guiados por especificação de campos."""

from dataclasses import dataclass, field
from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from . import validacao
from .models import Dispensacao, Localizacao, Lote, Medico, Movimentacao, Paciente, Produto, Usuario, db

bp = Blueprint("cadastros", __name__, url_prefix="/cadastros")

UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB",
       "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]
SEXOS = [("F", "Feminino"), ("M", "Masculino"), ("O", "Outro / não informado")]
TIPOS_SANGUINEOS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
# Listas da Portaria SVS/MS nº 344/1998.
LISTAS_CONTROLE = [
    ("", "Não controlado"),
    ("A1", "A1 - Entorpecentes"), ("A2", "A2 - Entorpecentes (uso permitido em concentrações)"),
    ("A3", "A3 - Psicotrópicos"), ("B1", "B1 - Psicotrópicos"), ("B2", "B2 - Psicotrópicos anorexígenos"),
    ("C1", "C1 - Outras substâncias sujeitas a controle especial"), ("C2", "C2 - Retinoides"),
    ("C3", "C3 - Imunossupressores"), ("C4", "C4 - Antirretrovirais"), ("C5", "C5 - Anabolizantes"),
    ("D1", "D1 - Precursores"), ("ATB", "Antimicrobiano (RDC 471/2021)"),
]
UNIDADES = ["UN", "AMP", "FR", "CP", "CPR", "CAP", "ML", "L", "G", "MG", "BISN", "ENV", "CX", "PCT",
            "PAR", "ROLO", "KIT", "SACHE", "SER", "TB"]


@dataclass
class Campo:
    nome: str
    rotulo: str
    tipo: str = "text"  # text | textarea | date | number | select | checkbox
    obrigatorio: bool = False
    opcoes: list = None  # lista de valores ou de pares (valor, rótulo); pode ser callable
    largura: int = 4  # colunas do grid (de 12)
    ajuda: str = ""
    secao: str = None  # inicia uma nova seção do formulário

    def lista_opcoes(self):
        opcoes = self.opcoes() if callable(self.opcoes) else (self.opcoes or [])
        return [o if isinstance(o, tuple) else (o, o) for o in opcoes]


def _campos_endereco():
    return [
        Campo("cep", "CEP", largura=2, ajuda="Digite o CEP para preencher o endereço.", secao="Endereço"),
        Campo("logradouro", "Logradouro", largura=6),
        Campo("numero", "Número", largura=2),
        Campo("complemento", "Complemento", largura=2),
        Campo("bairro", "Bairro", largura=4),
        Campo("cidade", "Cidade", largura=4),
        Campo("uf", "UF", "select", opcoes=[""] + UFS, largura=2),
    ]


def _opcoes_localizacao():
    return [("", "—")] + [(str(l.id), l.nome) for l in
                          Localizacao.query.filter_by(ativo=True).order_by(Localizacao.nome)]


@dataclass
class Cadastro:
    chave: str
    modelo: type
    titulo: str
    titulo_singular: str
    campos: list
    colunas: list  # (atributo, rótulo)
    busca: list  # atributos usados na pesquisa textual
    ordem: str = "nome"
    validar: callable = None
    pode_excluir: callable = None
    links: list = field(default_factory=list)  # (rótulo, endpoint, nome do parâmetro)
    perfil_edicao: str = Usuario.AUXILIAR  # perfil mínimo para incluir/alterar

    def limite(self, atributo):
        return tamanho_maximo(self.modelo, atributo)


def _validar_documentos(obj, erros):
    if getattr(obj, "cpf", None):
        if not validacao.cpf_valido(obj.cpf):
            erros.append("CPF inválido.")
        else:
            obj.cpf = validacao.formatar_cpf(obj.cpf)
            duplicado = type(obj).query.filter(type(obj).cpf == obj.cpf, type(obj).id != obj.id).first()
            if duplicado:
                erros.append(f"CPF já cadastrado para {duplicado.nome}.")
    if getattr(obj, "cep", None):
        if not validacao.cep_valido(obj.cep):
            erros.append("CEP inválido: informe 8 dígitos.")
        else:
            obj.cep = validacao.formatar_cep(obj.cep)
    if getattr(obj, "data_nascimento", None) and obj.data_nascimento > date.today():
        erros.append("A data de nascimento não pode ser futura.")


def validar_paciente(obj, erros):
    _validar_documentos(obj, erros)
    if obj.cartao_sus:
        if not validacao.cns_valido(obj.cartao_sus):
            erros.append("Cartão Nacional de Saúde (CNS) inválido.")
        else:
            obj.cartao_sus = validacao.somente_digitos(obj.cartao_sus)
            duplicado = Paciente.query.filter(Paciente.cartao_sus == obj.cartao_sus,
                                              Paciente.id != obj.id).first()
            if duplicado:
                erros.append(f"Cartão SUS já cadastrado para {duplicado.nome}.")
    if obj.idade is not None and obj.idade < 18 and not obj.responsavel:
        erros.append("Paciente menor de idade: informe o responsável.")
    if obj.responsavel and not obj.grau_parentesco:
        erros.append("Informe o grau de parentesco do responsável.")


def validar_medico(obj, erros):
    _validar_documentos(obj, erros)
    obj.crm = validacao.somente_digitos(obj.crm) or obj.crm
    duplicado = Medico.query.filter(Medico.crm == obj.crm, Medico.uf_crm == obj.uf_crm,
                                    Medico.id != obj.id).first()
    if duplicado:
        erros.append(f"CRM {obj.crm}/{obj.uf_crm} já cadastrado para {duplicado.nome}.")


def validar_produto(obj, erros):
    if obj.estoque_minimo < 0 or obj.estoque_maximo < 0:
        erros.append("Estoques mínimo e máximo não podem ser negativos.")
    if obj.estoque_maximo and obj.estoque_maximo < obj.estoque_minimo:
        erros.append("O estoque máximo deve ser maior ou igual ao mínimo.")


def validar_localizacao(obj, erros):
    duplicado = Localizacao.query.filter(db.func.lower(Localizacao.nome) == obj.nome.lower(),
                                         Localizacao.id != obj.id).first()
    if duplicado:
        erros.append("Já existe uma localização com este nome.")
    if obj.principal and not obj.ativo:
        erros.append("Os locais principais não podem ser desativados.")


def _bloqueio_paciente(obj):
    return "possui dispensações registradas" if obj.dispensacoes else None


def _bloqueio_medico(obj):
    return "possui dispensações registradas" if obj.dispensacoes else None


def _bloqueio_produto(obj):
    return "possui lotes/movimentações — desative-o em vez de excluir" if obj.lotes else None


def _bloqueio_localizacao(obj):
    if obj.principal:
        return "é um local principal do sistema"
    em_uso = (Lote.query.filter_by(localizacao_id=obj.id).first()
              or Dispensacao.query.filter_by(destino_id=obj.id).first()
              or Movimentacao.query.filter_by(destino_id=obj.id).first())
    return "possui estoque ou movimentações — desative-a em vez de excluir" if em_uso else None


CADASTROS = {
    "pacientes": Cadastro(
        "pacientes", Paciente, "Pacientes", "Paciente",
        campos=[
            Campo("nome", "Nome completo", obrigatorio=True, largura=6, secao="Identificação"),
            Campo("nome_mae", "Nome da mãe", largura=6),
            Campo("data_nascimento", "Data de nascimento", "date", largura=3,
                  ajuda="A idade é calculada automaticamente."),
            Campo("sexo", "Sexo", "select", opcoes=[("", "—")] + SEXOS, largura=3),
            Campo("cpf", "CPF", largura=3, ajuda="000.000.000-00"),
            Campo("rg", "Documento de identidade (RG)", largura=3),
            Campo("cartao_sus", "Cartão Nacional do SUS (CNS)", largura=4),
            Campo("plano_saude", "Plano de saúde", largura=4, ajuda="Deixe vazio para SUS."),
            Campo("profissao", "Profissão", largura=4),
            *_campos_endereco(),
            Campo("telefone", "Telefone", largura=4, secao="Contato e responsável"),
            Campo("responsavel", "Nome do responsável", largura=5),
            Campo("grau_parentesco", "Grau de parentesco", largura=3),
            Campo("tipo_sanguineo", "Tipo sanguíneo", "select", opcoes=[""] + TIPOS_SANGUINEOS,
                  largura=3, secao="Informações clínicas"),
            Campo("alergias", "Alergias conhecidas", "textarea", largura=9,
                  ajuda="Separe por vírgula (ex.: dipirona, penicilina, látex). "
                        "São verificadas a cada dispensação."),
            Campo("historico_doencas", "Histórico de doenças graves", "textarea", largura=12),
        ],
        colunas=[("nome", "Nome"), ("idade", "Idade"), ("cpf", "CPF"), ("cartao_sus", "Cartão SUS"),
                 ("plano_saude", "Plano"), ("alergias", "Alergias")],
        busca=["nome", "cpf", "cartao_sus", "nome_mae"],
        validar=validar_paciente,
        pode_excluir=_bloqueio_paciente,
        links=[("Consumo", "relatorios.consumo_paciente", "paciente_id")],
    ),
    "medicos": Cadastro(
        "medicos", Medico, "Médicos", "Médico",
        campos=[
            Campo("nome", "Nome completo", obrigatorio=True, largura=6, secao="Identificação"),
            Campo("data_nascimento", "Data de nascimento", "date", largura=3),
            Campo("sexo", "Sexo", "select", opcoes=[("", "—")] + SEXOS, largura=3),
            Campo("cpf", "CPF", largura=3),
            Campo("rg", "Documento de identidade (RG)", largura=3),
            Campo("crm", "CRM", obrigatorio=True, largura=2),
            Campo("uf_crm", "UF do CRM", "select", obrigatorio=True, opcoes=[""] + UFS, largura=2),
            Campo("especialidade", "Especialidade", largura=2),
            *_campos_endereco(),
            Campo("telefone", "Telefone", largura=4, secao="Contato"),
        ],
        colunas=[("nome", "Nome"), ("crm_formatado", "CRM"), ("especialidade", "Especialidade"),
                 ("idade", "Idade"), ("telefone", "Telefone")],
        busca=["nome", "crm", "cpf", "especialidade"],
        validar=validar_medico,
        pode_excluir=_bloqueio_medico,
    ),
    "produtos": Cadastro(
        "produtos", Produto, "Medicamentos e materiais", "Medicamento / material",
        campos=[
            Campo("tipo", "Tipo", "select", obrigatorio=True, opcoes=list(Produto.TIPOS.items()),
                  largura=3, secao="Identificação"),
            Campo("nome_comercial", "Nome comercial (marca)", obrigatorio=True, largura=5),
            Campo("principio_ativo", "Princípio ativo (DCB)", largura=4),
            Campo("apresentacao", "Apresentação", largura=4, ajuda="Ex.: 500 mg comprimido, 1 g/2 mL ampola"),
            Campo("laboratorio", "Laboratório fabricante", largura=4),
            Campo("unidade_medida", "Unidade de medida", "select", obrigatorio=True, opcoes=UNIDADES, largura=2),
            Campo("controle_especial", "Controle especial", "select", opcoes=LISTAS_CONTROLE, largura=2,
                  ajuda="Portaria 344/98"),
            Campo("localizacao_padrao_id", "Localização padrão", "select", opcoes=_opcoes_localizacao,
                  largura=4, secao="Estoque",
                  ajuda="Lote, validade, local e custo são informados em cada entrada de estoque."),
            Campo("estoque_minimo", "Estoque mínimo", "number", largura=2),
            Campo("estoque_maximo", "Estoque máximo", "number", largura=2),
            Campo("ativo", "Ativo", "checkbox", largura=2),
            Campo("alertas_alergia", "Alertas de alergia", "textarea", largura=12, secao="Segurança",
                  ajuda="Substâncias/classes que disparam alerta (ex.: penicilinas, betalactâmicos, látex)."),
        ],
        colunas=[("nome_comercial", "Nome comercial"), ("principio_ativo", "DCB"),
                 ("apresentacao", "Apresentação"), ("controle_especial", "Controle"),
                 ("unidade_medida", "Unid."), ("saldo", "Saldo"),
                 ("estoque_minimo", "Mín."), ("estoque_maximo", "Máx.")],
        busca=["nome_comercial", "principio_ativo", "laboratorio"],
        ordem="nome_comercial",
        validar=validar_produto,
        pode_excluir=_bloqueio_produto,
        perfil_edicao=Usuario.FARMACEUTICO,
        links=[("Lotes", "estoque.lotes", "produto_id")],
    ),
    "localizacoes": Cadastro(
        "localizacoes", Localizacao, "Localizações", "Localização",
        campos=[
            Campo("nome", "Nome", obrigatorio=True, largura=5, ajuda="Ex.: Leito 1, Sala de parada"),
            Campo("descricao", "Descrição", largura=5),
            Campo("ativo", "Ativa", "checkbox", largura=2),
        ],
        colunas=[("nome", "Nome"), ("descricao", "Descrição"), ("principal", "Principal"), ("ativo", "Ativa")],
        busca=["nome", "descricao"],
        validar=validar_localizacao,
        pode_excluir=_bloqueio_localizacao,
        perfil_edicao=Usuario.FARMACEUTICO,
    ),
}


def _cadastro(chave):
    cadastro = CADASTROS.get(chave)
    if not cadastro:
        abort(404)
    return cadastro


def _converter(campo, bruto):
    bruto = (bruto or "").strip()
    if campo.tipo == "checkbox":
        return bruto in ("on", "1", "true")
    if not bruto:
        return 0.0 if campo.tipo == "number" else None
    if campo.tipo == "date":
        return datetime.strptime(bruto, "%Y-%m-%d").date()
    if campo.tipo == "number":
        return float(bruto.replace(",", "."))
    if campo.nome.endswith("_id"):
        return int(bruto)
    return bruto


def tamanho_maximo(modelo, atributo):
    """Tamanho máximo da coluna de texto (o PostgreSQL rejeita valores maiores)."""
    coluna = modelo.__table__.columns.get(atributo)
    return getattr(coluna.type, "length", None) if coluna is not None else None


def preencher(cadastro, obj, form):
    erros = []
    for campo in cadastro.campos:
        try:
            valor = _converter(campo, form.get(campo.nome))
        except ValueError:
            erros.append(f"Valor inválido em '{campo.rotulo}'.")
            continue
        if campo.obrigatorio and valor in (None, ""):
            erros.append(f"O campo '{campo.rotulo}' é obrigatório.")
        limite = tamanho_maximo(cadastro.modelo, campo.nome)
        if isinstance(valor, str) and limite and len(valor) > limite:
            erros.append(f"O campo '{campo.rotulo}' aceita no máximo {limite} caracteres.")
        setattr(obj, campo.nome, valor)
    if not erros and cadastro.validar:
        cadastro.validar(obj, erros)
    return erros


@bp.route("/<chave>/")
def listar(chave):
    cadastro = _cadastro(chave)
    modelo = cadastro.modelo
    termo = request.args.get("q", "").strip()
    consulta = modelo.query
    if termo:
        consulta = consulta.filter(or_(*[getattr(modelo, a).ilike(f"%{termo}%") for a in cadastro.busca]))
    pagina = consulta.order_by(getattr(modelo, cadastro.ordem)).paginate(
        page=request.args.get("pagina", 1, type=int), per_page=25, error_out=False)
    return render_template("cadastros/lista.html", cadastro=cadastro, pagina=pagina, termo=termo)


@bp.route("/<chave>/novo", methods=["GET", "POST"])
@bp.route("/<chave>/<int:id>/editar", methods=["GET", "POST"])
def editar(chave, id=None):
    cadastro = _cadastro(chave)
    if not current_user.pode(cadastro.perfil_edicao):
        abort(403)
    if id:
        obj = db.get_or_404(cadastro.modelo, id)
    else:
        obj = cadastro.modelo()
        for campo in cadastro.campos:
            if campo.tipo == "checkbox":
                setattr(obj, campo.nome, True)
    if request.method == "POST":
        with db.session.no_autoflush:
            erros = preencher(cadastro, obj, request.form)
        if erros:
            db.session.rollback()
            for erro in erros:
                flash(erro, "danger")
            return render_template("cadastros/form.html", cadastro=cadastro, obj=obj, valores=request.form), 422
        db.session.add(obj)
        db.session.commit()
        flash(f"{cadastro.titulo_singular} salvo(a) com sucesso.", "success")
        return redirect(url_for(".listar", chave=chave))
    return render_template("cadastros/form.html", cadastro=cadastro, obj=obj, valores=None)


@bp.route("/<chave>/<int:id>/excluir", methods=["POST"])
def excluir(chave, id):
    cadastro = _cadastro(chave)
    if not current_user.pode(Usuario.FARMACEUTICO):
        abort(403)
    obj = db.get_or_404(cadastro.modelo, id)
    motivo = cadastro.pode_excluir(obj) if cadastro.pode_excluir else None
    if motivo:
        flash(f"Não é possível excluir: o registro {motivo}.", "warning")
    else:
        db.session.delete(obj)
        db.session.commit()
        flash(f"{cadastro.titulo_singular} excluído(a).", "success")
    return redirect(url_for(".listar", chave=chave))
