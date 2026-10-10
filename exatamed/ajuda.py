"""Onboarding: página de ajuda (guia do usuário) e checklist de primeiros passos."""

from pathlib import Path

import markdown
from flask import Blueprint, abort, current_app, redirect, render_template, send_from_directory, url_for
from flask_login import current_user
from markdown.extensions.toc import slugify_unicode

from .auth import perfil_requerido
from .models import Dispensacao, Localizacao, Lote, Medico, Paciente, Produto, Usuario, db

bp = Blueprint("ajuda", __name__, url_prefix="/ajuda")

_cache = {}


def pasta_docs():
    return Path(current_app.root_path).parent / "docs"


def carregar_guia():
    """Converte docs/GUIA_DO_USUARIO.md em HTML. É o mesmo arquivo exibido no GitHub,
    então o guia tem uma única versão. O resultado fica em cache até o arquivo mudar."""
    arquivo = pasta_docs() / "GUIA_DO_USUARIO.md"
    if not arquivo.exists():
        return None, None
    versao = arquivo.stat().st_mtime
    if _cache.get("versao") != versao:
        md = markdown.Markdown(
            extensions=["tables", "toc", "fenced_code", "sane_lists"],
            # Âncoras no mesmo formato do GitHub, para os links internos funcionarem nos dois lugares.
            extension_configs={"toc": {"slugify": slugify_unicode, "toc_depth": "2"}},
        )
        html = md.convert(arquivo.read_text(encoding="utf-8"))
        html = html.replace("<table>", '<table class="table table-sm table-bordered">')
        _cache.update(versao=versao, html=html, sumario=md.toc_tokens)
    return _cache["html"], _cache["sumario"]


@bp.route("/")
def guia():
    html, sumario = carregar_guia()
    return render_template("ajuda/guia.html", conteudo=html, sumario=sumario or [])


# As imagens do guia (docs/img) são referenciadas como "img/arquivo.png", caminho que funciona
# tanto no GitHub quanto aqui, pois a página de ajuda fica em /ajuda/.
@bp.route("/img/<path:nome>")
def imagem(nome):
    pasta = pasta_docs() / "img"
    if not (pasta / nome).is_file():
        abort(404)
    return send_from_directory(pasta, nome)


@bp.route("/primeiros-passos/<acao>", methods=["POST"])
@perfil_requerido(Usuario.ADMIN)
def alternar_primeiros_passos(acao):
    if acao not in ("ocultar", "mostrar"):
        abort(404)
    current_user.ocultar_primeiros_passos = acao == "ocultar"
    db.session.commit()
    return redirect(url_for("principal.painel"))


def primeiros_passos():
    """Etapas da implantação do sistema, marcadas automaticamente conforme os dados existem."""
    produtos_ativos = Produto.query.filter_by(ativo=True)
    sem_limites = produtos_ativos.filter(Produto.estoque_maximo <= 0).count()
    total_produtos = produtos_ativos.count()
    etapas = [
        ("Criar o administrador do sistema", "Feito na instalação.", True, None, "primeiro-acesso"),
        ("Cadastrar os usuários da equipe",
         "Um usuário para cada pessoa, com o perfil adequado (auxiliar, farmacêutico ou administrador).",
         Usuario.query.count() > 1, url_for("auth.editar_usuario"), "gestão-de-usuários-administrador"),
        ("Cadastrar os locais de dispensação",
         "Leitos, salas e setores para onde os itens são dispensados (Leito 1, Sala de parada...).",
         Localizacao.query.filter_by(principal=False).count() > 0,
         url_for("cadastros.editar", chave="localizacoes"), "2-locais-de-dispensação"),
        ("Cadastrar medicamentos e materiais",
         "Nome comercial, princípio ativo, apresentação, controle especial e alertas de alergia.",
         total_produtos > 0, url_for("cadastros.editar", chave="produtos"), "3-medicamentos-e-materiais"),
        ("Definir estoque mínimo e máximo",
         f"{sem_limites} item(ns) ainda sem estoque máximo." if sem_limites else
         "Usados no cálculo do pedido de compra.",
         total_produtos > 0 and sem_limites == 0, url_for("cadastros.listar", chave="produtos"),
         "3-medicamentos-e-materiais"),
        ("Cadastrar médicos e pacientes", "Necessários para registrar as dispensações.",
         Medico.query.count() > 0 and Paciente.query.count() > 0,
         url_for("cadastros.listar", chave="pacientes"), "4-médicos-e-pacientes"),
        ("Registrar a primeira entrada de estoque", "Informe lote, validade, local e custo de cada item recebido.",
         Lote.query.count() > 0, url_for("estoque.entrada"), "5-entrada-de-estoque"),
        ("Fazer a primeira dispensação", "Baixa pelo método PEPS, com verificação de alergias.",
         Dispensacao.query.count() > 0, url_for("estoque.dispensacao"), "6-primeira-dispensação"),
    ]
    return [dict(titulo=t, descricao=d, feito=f, url=u, ancora=a) for t, d, f, u, a in etapas]
