"""Modelos de dados do ExataMed."""

from datetime import date, datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def calcular_idade(nascimento, referencia=None):
    if not nascimento:
        return None
    referencia = referencia or date.today()
    anos = referencia.year - nascimento.year
    if (referencia.month, referencia.day) < (nascimento.month, nascimento.day):
        anos -= 1
    return anos


class TimestampMixin:
    criado_em = db.Column(db.DateTime, default=datetime.now, nullable=False)
    atualizado_em = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)


class EnderecoMixin:
    cep = db.Column(db.String(9))
    logradouro = db.Column(db.String(200))
    numero = db.Column(db.String(20))
    complemento = db.Column(db.String(100))
    bairro = db.Column(db.String(100))
    cidade = db.Column(db.String(100))
    uf = db.Column(db.String(2))

    @property
    def endereco_completo(self):
        partes = [
            ", ".join(p for p in (self.logradouro, self.numero) if p),
            self.complemento,
            self.bairro,
            " - ".join(p for p in (self.cidade, self.uf) if p),
            f"CEP {self.cep}" if self.cep else None,
        ]
        return ", ".join(p for p in partes if p)


class Usuario(UserMixin, TimestampMixin, db.Model):
    """Usuário do sistema. Os perfis são hierárquicos: auxiliar < farmacêutico < administrador."""

    __tablename__ = "usuarios"

    AUXILIAR = "AUXILIAR"
    FARMACEUTICO = "FARMACEUTICO"
    ADMIN = "ADMIN"
    PERFIS = {AUXILIAR: "Auxiliar de farmácia", FARMACEUTICO: "Farmacêutico(a)", ADMIN: "Administrador(a)"}
    NIVEIS = {AUXILIAR: 1, FARMACEUTICO: 2, ADMIN: 3}

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    login = db.Column(db.String(50), nullable=False, unique=True, index=True)
    email = db.Column(db.String(200))
    registro_profissional = db.Column(db.String(30))  # CRF, quando farmacêutico
    perfil = db.Column(db.String(20), nullable=False, default=AUXILIAR)
    senha_hash = db.Column(db.String(255), nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    deve_trocar_senha = db.Column(db.Boolean, default=False, nullable=False)
    tentativas_falhas = db.Column(db.Integer, default=0, nullable=False)
    bloqueado_ate = db.Column(db.DateTime)
    ultimo_acesso = db.Column(db.DateTime)
    ocultar_primeiros_passos = db.Column(db.Boolean, default=False, nullable=False)

    def definir_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def conferir_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

    def pode(self, perfil_minimo):
        return self.ativo and self.NIVEIS.get(self.perfil, 0) >= self.NIVEIS[perfil_minimo]

    @property
    def is_active(self):
        return self.ativo

    @property
    def perfil_descricao(self):
        return self.PERFIS.get(self.perfil, self.perfil)

    def __str__(self):
        return self.nome


class Paciente(TimestampMixin, EnderecoMixin, db.Model):
    __tablename__ = "pacientes"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False, index=True)
    nome_mae = db.Column(db.String(200))
    data_nascimento = db.Column(db.Date)
    sexo = db.Column(db.String(1))
    cpf = db.Column(db.String(14), unique=True)
    rg = db.Column(db.String(30))
    cartao_sus = db.Column(db.String(20), unique=True)
    telefone = db.Column(db.String(20))
    responsavel = db.Column(db.String(200))
    grau_parentesco = db.Column(db.String(50))
    plano_saude = db.Column(db.String(100))
    alergias = db.Column(db.Text)
    tipo_sanguineo = db.Column(db.String(3))
    historico_doencas = db.Column(db.Text)
    profissao = db.Column(db.String(100))

    dispensacoes = db.relationship("Dispensacao", back_populates="paciente")

    @property
    def idade(self):
        return calcular_idade(self.data_nascimento)

    def __str__(self):
        return self.nome


class Medico(TimestampMixin, EnderecoMixin, db.Model):
    __tablename__ = "medicos"
    __table_args__ = (db.UniqueConstraint("crm", "uf_crm", name="uq_medico_crm_uf"),)

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False, index=True)
    data_nascimento = db.Column(db.Date)
    sexo = db.Column(db.String(1))
    cpf = db.Column(db.String(14), unique=True)
    crm = db.Column(db.String(20), nullable=False)
    uf_crm = db.Column(db.String(2), nullable=False)
    especialidade = db.Column(db.String(100))
    rg = db.Column(db.String(30))
    telefone = db.Column(db.String(20))

    dispensacoes = db.relationship("Dispensacao", back_populates="medico")

    @property
    def idade(self):
        return calcular_idade(self.data_nascimento)

    @property
    def crm_formatado(self):
        return f"CRM {self.crm}/{self.uf_crm}"

    def __str__(self):
        return f"{self.nome} ({self.crm_formatado})"


class Localizacao(TimestampMixin, db.Model):
    """Local físico de armazenamento ou de dispensação (farmácia, leito, sala...)."""

    __tablename__ = "localizacoes"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    descricao = db.Column(db.String(200))
    # Locais principais (Farmácia SUS / Farmácia Particular) não podem ser excluídos.
    principal = db.Column(db.Boolean, default=False, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    def __str__(self):
        return self.nome


class Produto(TimestampMixin, db.Model):
    """Medicamento ou material médico-hospitalar."""

    __tablename__ = "produtos"

    TIPOS = {"MEDICAMENTO": "Medicamento", "MATERIAL": "Material médico-hospitalar"}

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False, default="MEDICAMENTO")
    nome_comercial = db.Column(db.String(200), nullable=False, index=True)
    principio_ativo = db.Column(db.String(200), index=True)
    apresentacao = db.Column(db.String(200))
    laboratorio = db.Column(db.String(200))
    # Lista da Portaria SVS/MS 344/98 (A1, B1, C1...) ou vazio quando não controlado.
    controle_especial = db.Column(db.String(10))
    unidade_medida = db.Column(db.String(30), nullable=False, default="UN")
    localizacao_padrao_id = db.Column(db.Integer, db.ForeignKey("localizacoes.id"))
    alertas_alergia = db.Column(db.Text)
    estoque_minimo = db.Column(db.Float, nullable=False, default=0)
    estoque_maximo = db.Column(db.Float, nullable=False, default=0)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    localizacao_padrao = db.relationship("Localizacao")
    lotes = db.relationship("Lote", back_populates="produto", order_by="Lote.data_entrada")

    @property
    def controlado(self):
        return bool(self.controle_especial)

    @property
    def saldo(self):
        return sum(l.saldo for l in self.lotes)

    @property
    def valor_estoque(self):
        return sum(l.saldo * l.custo_unitario for l in self.lotes)

    def __str__(self):
        desc = self.nome_comercial
        if self.apresentacao:
            desc += f" - {self.apresentacao}"
        return desc


class Lote(db.Model):
    """Camada de estoque PEPS: um lote recebido em uma data, a um custo, em um local.

    Uma transferência entre locais cria uma nova camada no destino preservando
    a data de entrada e o custo originais, de modo que a ordem PEPS se mantém.
    """

    __tablename__ = "lotes"

    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey("produtos.id"), nullable=False, index=True)
    localizacao_id = db.Column(db.Integer, db.ForeignKey("localizacoes.id"), nullable=False, index=True)
    numero_lote = db.Column(db.String(50), nullable=False)
    validade = db.Column(db.Date, nullable=False)
    data_entrada = db.Column(db.DateTime, nullable=False, default=datetime.now)
    custo_unitario = db.Column(db.Float, nullable=False, default=0)
    quantidade_inicial = db.Column(db.Float, nullable=False)
    saldo = db.Column(db.Float, nullable=False)

    produto = db.relationship("Produto", back_populates="lotes")
    localizacao = db.relationship("Localizacao")

    @property
    def valor(self):
        return self.saldo * self.custo_unitario

    @property
    def vencido(self):
        return self.validade < date.today()

    @property
    def dias_para_vencer(self):
        return (self.validade - date.today()).days


class Dispensacao(TimestampMixin, db.Model):
    __tablename__ = "dispensacoes"
    # Numeração sequencial reiniciada a cada ano: 00001/2026, 00002/2026...
    __table_args__ = (db.Index("uq_dispensacao_numero_ano", "ano", "numero", unique=True),)

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.Integer)
    ano = db.Column(db.Integer)
    data = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False, index=True)
    medico_id = db.Column(db.Integer, db.ForeignKey("medicos.id"))
    # Farmácia de onde o estoque sai.
    origem_id = db.Column(db.Integer, db.ForeignKey("localizacoes.id"), nullable=False)
    # Local para onde foi dispensado (leito, sala de parada...).
    destino_id = db.Column(db.Integer, db.ForeignKey("localizacoes.id"), nullable=False, index=True)
    prescricao = db.Column(db.String(50))
    observacao = db.Column(db.Text)
    responsavel = db.Column(db.String(100))
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))

    usuario = db.relationship("Usuario")
    paciente = db.relationship("Paciente", back_populates="dispensacoes")
    medico = db.relationship("Medico", back_populates="dispensacoes")
    origem = db.relationship("Localizacao", foreign_keys=[origem_id])
    destino = db.relationship("Localizacao", foreign_keys=[destino_id])
    movimentacoes = db.relationship("Movimentacao", back_populates="dispensacao")

    @property
    def custo_total(self):
        return sum(m.custo_total for m in self.movimentacoes)

    @property
    def numero_formatado(self):
        if self.numero is None:
            return str(self.id)
        return f"{self.numero:05d}/{self.ano}"

    @staticmethod
    def proximo_numero(ano):
        ultimo = db.session.query(db.func.max(Dispensacao.numero)).filter(Dispensacao.ano == ano).scalar()
        return (ultimo or 0) + 1


class Movimentacao(db.Model):
    """Registro imutável de cada movimento de estoque, sempre ligado a um lote."""

    __tablename__ = "movimentacoes"

    ENTRADA = "ENTRADA"
    SAIDA = "SAIDA"
    DISPENSACAO = "DISPENSACAO"
    TRANSFERENCIA = "TRANSFERENCIA"
    AJUSTE = "AJUSTE"
    TIPOS = {
        ENTRADA: "Entrada",
        SAIDA: "Saída",
        DISPENSACAO: "Dispensação",
        TRANSFERENCIA: "Transferência",
        AJUSTE: "Ajuste de inventário",
    }
    # Tipos que representam consumo (baixa definitiva) para os relatórios.
    CONSUMO = (SAIDA, DISPENSACAO)

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False, index=True)
    data = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    produto_id = db.Column(db.Integer, db.ForeignKey("produtos.id"), nullable=False, index=True)
    lote_id = db.Column(db.Integer, db.ForeignKey("lotes.id"), nullable=False)
    localizacao_id = db.Column(db.Integer, db.ForeignKey("localizacoes.id"), nullable=False)
    destino_id = db.Column(db.Integer, db.ForeignKey("localizacoes.id"))
    # Positiva para entradas/ajustes a maior, negativa para baixas.
    quantidade = db.Column(db.Float, nullable=False)
    custo_unitario = db.Column(db.Float, nullable=False, default=0)
    dispensacao_id = db.Column(db.Integer, db.ForeignKey("dispensacoes.id"), index=True)
    documento = db.Column(db.String(100))
    motivo = db.Column(db.String(200))
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))

    usuario = db.relationship("Usuario")
    produto = db.relationship("Produto")
    lote = db.relationship("Lote")
    localizacao = db.relationship("Localizacao", foreign_keys=[localizacao_id])
    destino = db.relationship("Localizacao", foreign_keys=[destino_id])
    dispensacao = db.relationship("Dispensacao", back_populates="movimentacoes")

    @property
    def custo_total(self):
        return abs(self.quantidade) * self.custo_unitario

    @property
    def tipo_descricao(self):
        return self.TIPOS.get(self.tipo, self.tipo)


@db.event.listens_for(Movimentacao, "before_insert")
@db.event.listens_for(Dispensacao, "before_insert")
def _registrar_usuario(mapper, connection, alvo):
    """Grava automaticamente o usuário logado em toda movimentação (trilha de auditoria)."""
    if alvo.usuario_id is None:
        from flask import has_request_context
        from flask_login import current_user
        if has_request_context() and current_user.is_authenticated:
            alvo.usuario_id = current_user.id
