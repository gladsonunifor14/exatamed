"""Modelos de dados do ExataMed."""

from datetime import date, datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

from . import validacao

db = SQLAlchemy()

# Quantidades e custos: decimal exato com 4 casas (ver numeros.py).
QTD = db.Numeric(14, 4)


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


class SeladoMixin:
    """Registro selado na cadeia de auditoria (ver auditoria.py): número de sequência e
    assinatura HMAC que encadeia o registro ao anterior. Alterar, remover ou inserir
    registros fora da aplicação quebra a cadeia, o que é detectado na verificação."""

    seq_cadeia = db.Column(db.Integer, index=True)
    hash = db.Column(db.String(64))


class DadosPessoaisMixin:
    """Campos e versões mascaradas (LGPD) comuns a pessoas cadastradas."""

    # Preenchido quando o cadastro é anonimizado (irreversível).
    anonimizado_em = db.Column(db.DateTime)

    @property
    def anonimizado(self):
        return self.anonimizado_em is not None

    @property
    def cpf_mascarado(self):
        return validacao.mascarar_cpf(self.cpf) if self.cpf else ""

    @property
    def rg_mascarado(self):
        return validacao.mascarar_generico(self.rg) if self.rg else ""

    @property
    def telefone_mascarado(self):
        return validacao.mascarar_telefone(self.telefone)


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
    anonimizado_em = db.Column(db.DateTime)
    # Incrementada ao trocar a senha, o perfil ou desativar o usuário: invalida as sessões abertas.
    versao_sessao = db.Column(db.Integer, default=1, nullable=False)

    def get_id(self):
        return f"{self.id}:{self.versao_sessao}"

    def encerrar_sessoes(self):
        self.versao_sessao = (self.versao_sessao or 1) + 1

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
    def anonimizado(self):
        return self.anonimizado_em is not None

    @property
    def email_mascarado(self):
        return validacao.mascarar_email(self.email) if self.email else ""

    @property
    def perfil_descricao(self):
        return self.PERFIS.get(self.perfil, self.perfil)

    def __str__(self):
        return self.nome


class Paciente(DadosPessoaisMixin, TimestampMixin, EnderecoMixin, db.Model):
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

    @property
    def cartao_sus_mascarado(self):
        return validacao.mascarar_cns(self.cartao_sus) if self.cartao_sus else ""

    @property
    def pseudonimo(self):
        """Identificador sem dados pessoais, usado em relatórios anonimizados."""
        return f"P-{self.id:06d}"

    def __str__(self):
        return self.nome


class Medico(DadosPessoaisMixin, TimestampMixin, EnderecoMixin, db.Model):
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
    __table_args__ = (
        db.CheckConstraint("estoque_minimo >= 0 AND estoque_maximo >= 0", name="ck_produto_limites"),
    )

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
    estoque_minimo = db.Column(QTD, nullable=False, default=0)
    estoque_maximo = db.Column(QTD, nullable=False, default=0)
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
    # O banco recusa saldo negativo mesmo que uma falha de aplicação tente gravá-lo.
    __table_args__ = (
        db.CheckConstraint("saldo >= 0", name="ck_lote_saldo_nao_negativo"),
        db.CheckConstraint("quantidade_inicial > 0", name="ck_lote_quantidade_inicial"),
        db.CheckConstraint("custo_unitario >= 0", name="ck_lote_custo"),
    )

    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey("produtos.id"), nullable=False, index=True)
    localizacao_id = db.Column(db.Integer, db.ForeignKey("localizacoes.id"), nullable=False, index=True)
    numero_lote = db.Column(db.String(50), nullable=False)
    validade = db.Column(db.Date, nullable=False)
    data_entrada = db.Column(db.DateTime, nullable=False, default=datetime.now)
    custo_unitario = db.Column(QTD, nullable=False, default=0)
    quantidade_inicial = db.Column(QTD, nullable=False)
    saldo = db.Column(QTD, nullable=False)
    # Bloqueio (recall do fabricante, interdição sanitária, quarentena): não é dispensado nem transferido.
    bloqueado = db.Column(db.Boolean, nullable=False, default=False)
    motivo_bloqueio = db.Column(db.String(200))
    bloqueado_em = db.Column(db.DateTime)

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
        """Custo PEPS líquido: itens dispensados menos itens devolvidos."""
        return sum((m.consumo_custo for m in self.movimentacoes), 0)

    @property
    def itens_dispensados(self):
        return [m for m in self.movimentacoes if m.tipo == Movimentacao.DISPENSACAO]

    @property
    def devolucoes(self):
        return [m for m in self.movimentacoes if m.tipo == Movimentacao.ESTORNO]

    @property
    def situacao(self):
        dispensado = sum((-m.quantidade for m in self.itens_dispensados), 0)
        devolvido = sum((m.quantidade for m in self.devolucoes), 0)
        if not devolvido:
            return "Dispensada"
        return "Devolvida integralmente" if devolvido >= dispensado else "Devolução parcial"

    @property
    def numero_formatado(self):
        if self.numero is None:
            return str(self.id)
        return f"{self.numero:05d}/{self.ano}"

    @staticmethod
    def proximo_numero(ano):
        """Próximo número do ano, tirado de um contador travado no banco (SELECT ... FOR UPDATE).

        Dispensações simultâneas esperam a vez no contador em vez de calcular o mesmo
        número. A trava vale até o fim da transação.
        """
        from sqlalchemy.exc import IntegrityError
        nome = f"dispensacao:{ano}"

        def travar():
            return Sequencia.query.filter_by(nome=nome).with_for_update().populate_existing().first()

        contador = travar()
        if contador is None:
            # Primeiro número do ano (ou primeira execução após a atualização): parte do maior já usado.
            maior = db.session.query(db.func.max(Dispensacao.numero)).filter(Dispensacao.ano == ano).scalar() or 0
            try:
                with db.session.begin_nested():
                    db.session.add(Sequencia(nome=nome, ultimo=maior))
            except IntegrityError:
                pass  # outra transação criou o contador ao mesmo tempo
            contador = travar()
        contador.ultimo += 1
        return contador.ultimo


class Movimentacao(SeladoMixin, db.Model):
    """Registro imutável de cada movimento de estoque, sempre ligado a um lote."""

    __tablename__ = "movimentacoes"
    __table_args__ = (db.CheckConstraint("quantidade <> 0", name="ck_movimentacao_quantidade"),)

    ENTRADA = "ENTRADA"
    SAIDA = "SAIDA"
    DISPENSACAO = "DISPENSACAO"
    TRANSFERENCIA = "TRANSFERENCIA"
    AJUSTE = "AJUSTE"
    ESTORNO = "ESTORNO"
    TIPOS = {
        ENTRADA: "Entrada",
        SAIDA: "Saída",
        DISPENSACAO: "Dispensação",
        TRANSFERENCIA: "Transferência",
        AJUSTE: "Ajuste de inventário",
        ESTORNO: "Devolução de dispensação",
    }
    # Tipos que entram no cálculo de consumo. A devolução (ESTORNO, quantidade positiva)
    # abate o consumo da dispensação de origem: consumo líquido = dispensado - devolvido.
    CONSUMO = (SAIDA, DISPENSACAO, ESTORNO)

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False, index=True)
    data = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    produto_id = db.Column(db.Integer, db.ForeignKey("produtos.id"), nullable=False, index=True)
    lote_id = db.Column(db.Integer, db.ForeignKey("lotes.id"), nullable=False)
    localizacao_id = db.Column(db.Integer, db.ForeignKey("localizacoes.id"), nullable=False)
    destino_id = db.Column(db.Integer, db.ForeignKey("localizacoes.id"))
    # Positiva para entradas/ajustes a maior, negativa para baixas.
    quantidade = db.Column(QTD, nullable=False)
    custo_unitario = db.Column(QTD, nullable=False, default=0)
    dispensacao_id = db.Column(db.Integer, db.ForeignKey("dispensacoes.id"), index=True)
    # Devolução: aponta a movimentação de dispensação que está sendo devolvida.
    origem_id = db.Column(db.Integer, db.ForeignKey("movimentacoes.id"), index=True)
    documento = db.Column(db.String(100))
    motivo = db.Column(db.String(200))
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))

    usuario = db.relationship("Usuario")
    produto = db.relationship("Produto")
    lote = db.relationship("Lote")
    localizacao = db.relationship("Localizacao", foreign_keys=[localizacao_id])
    destino = db.relationship("Localizacao", foreign_keys=[destino_id])
    dispensacao = db.relationship("Dispensacao", back_populates="movimentacoes")
    origem = db.relationship("Movimentacao", remote_side="Movimentacao.id", backref="devolucoes")

    @property
    def custo_total(self):
        """Valor absoluto da movimentação (quantidade x custo do lote)."""
        return abs(self.quantidade) * self.custo_unitario

    @property
    def quantidade_devolvida(self):
        return sum((d.quantidade for d in self.devolucoes), 0)

    @property
    def quantidade_a_devolver(self):
        """Quanto desta dispensação ainda pode ser devolvido."""
        return -self.quantidade - self.quantidade_devolvida

    @property
    def consumo_quantidade(self):
        """Quantidade consumida: positiva nas baixas, negativa nas devoluções."""
        return -self.quantidade

    @property
    def consumo_custo(self):
        return self.consumo_quantidade * self.custo_unitario

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


class RegistroAcesso(SeladoMixin, db.Model):
    """Trilha de acesso a dados pessoais (LGPD, art. 37): quem viu, alterou, exportou
    ou anonimizou dados pessoais, e quando."""

    __tablename__ = "registros_acesso"

    VISUALIZAR = "VISUALIZAR"
    INCLUIR = "INCLUIR"
    ALTERAR = "ALTERAR"
    EXPORTAR = "EXPORTAR"
    ANONIMIZAR = "ANONIMIZAR"
    ACOES = {VISUALIZAR: "Visualizou", INCLUIR: "Incluiu", ALTERAR: "Alterou", EXPORTAR: "Exportou",
             ANONIMIZAR: "Anonimizou"}
    ENTIDADES = {"paciente": "Paciente", "medico": "Médico", "usuario": "Usuário",
                 "dispensacao": "Dispensação", "relatorio": "Relatório"}

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), index=True)
    acao = db.Column(db.String(20), nullable=False)
    entidade = db.Column(db.String(20), nullable=False, index=True)
    registro_id = db.Column(db.Integer)
    descricao = db.Column(db.String(200))
    ip = db.Column(db.String(45))

    usuario = db.relationship("Usuario")

    @property
    def acao_descricao(self):
        return self.ACOES.get(self.acao, self.acao)

    @property
    def entidade_descricao(self):
        return self.ENTIDADES.get(self.entidade, self.entidade)


class RegistroAuditoria(SeladoMixin, db.Model):
    """Trilha de auditoria geral: inclusões, alterações e exclusões de cadastros, com
    valores de antes e depois. Campos de dados pessoais registram só que foram alterados."""

    __tablename__ = "registros_auditoria"

    INCLUSAO = "INCLUSAO"
    ALTERACAO = "ALTERACAO"
    EXCLUSAO = "EXCLUSAO"
    ACOES = {INCLUSAO: "Inclusão", ALTERACAO: "Alteração", EXCLUSAO: "Exclusão"}

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), index=True)
    acao = db.Column(db.String(20), nullable=False)
    entidade = db.Column(db.String(40), nullable=False, index=True)
    registro_id = db.Column(db.Integer, index=True)
    alteracoes = db.Column(db.Text)  # JSON: {campo: [antes, depois]}
    ip = db.Column(db.String(45))

    usuario = db.relationship("Usuario")

    @property
    def acao_descricao(self):
        return self.ACOES.get(self.acao, self.acao)

    @property
    def alteracoes_dict(self):
        import json
        return json.loads(self.alteracoes) if self.alteracoes else {}


class CadeiaAuditoria(db.Model):
    """Último elo de cada cadeia de registros selados (uma linha por tabela)."""

    __tablename__ = "cadeias_auditoria"

    nome = db.Column(db.String(40), primary_key=True)
    ultimo_seq = db.Column(db.Integer, nullable=False, default=0)
    ultimo_hash = db.Column(db.String(64), nullable=False, default="")


class TentativaLogin(db.Model):
    """Falhas de login por endereço IP, para limitar tentativas em massa."""

    __tablename__ = "tentativas_login"

    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(45), nullable=False, index=True)
    data = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)


class Sequencia(db.Model):
    """Contadores numerados (ex.: número da dispensação por ano), sempre lidos com trava."""

    __tablename__ = "sequencias"

    nome = db.Column(db.String(40), primary_key=True)
    ultimo = db.Column(db.Integer, nullable=False, default=0)
