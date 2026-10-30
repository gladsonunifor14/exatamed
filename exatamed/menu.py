"""Menu lateral: grupos, itens, permissões e o item da página atual.

Cada item aponta para um endpoint; `ativo_em` lista as outras páginas que pertencem a ele (por
exemplo, a conferência de uma NF-e acende "Notas fiscais"). Um padrão "blueprint.*" vale para todas
as páginas do blueprint. Os argumentos do item (como a chave do cadastro) também precisam bater.
"""

from dataclasses import dataclass, field

from .models import Usuario


@dataclass(frozen=True)
class Item:
    rotulo: str
    icone: str
    endpoint: str
    args: dict = field(default_factory=dict)
    perfil: str = None  # perfil mínimo para ver o item
    ativo_em: tuple = ()

    def corresponde(self, endpoint, view_args):
        if not any(endpoint == padrao or (padrao.endswith(".*") and endpoint.startswith(padrao[:-1]))
                   for padrao in (self.endpoint, *self.ativo_em)):
            return False
        return all((view_args or {}).get(chave) == valor for chave, valor in self.args.items())


def _cadastro(rotulo, icone, chave):
    return Item(rotulo, icone, "cadastros.listar", {"chave": chave}, ativo_em=("cadastros.editar",))


GRUPOS = [
    ("visao_geral", "Visão geral", [
        Item("Dashboard", "speedometer2", "dashboard.indice"),
        Item("Relatórios", "graph-up", "relatorios.indice", ativo_em=("relatorios.*",)),
    ]),
    ("operacoes", "Operações", [
        Item("Dispensações", "prescription2", "estoque.dispensacao",
             ativo_em=("estoque.ver_dispensacao", "estoque.devolver_dispensacao")),
        Item("Entradas de estoque", "box-arrow-in-down", "estoque.entrada"),
        Item("Saídas avulsas", "box-arrow-up", "estoque.saida", perfil=Usuario.FARMACEUTICO),
        Item("Transferências", "arrow-left-right", "estoque.transferencia"),
        Item("Inventário", "clipboard-check", "estoque.contagem", perfil=Usuario.FARMACEUTICO),
    ]),
    ("estoque", "Estoque", [
        Item("Posição de estoque", "boxes", "estoque.posicao"),
        Item("Lotes e validades", "stack", "estoque.lotes", ativo_em=("estoque.bloqueio_lote",)),
        Item("Movimentações", "list-ul", "estoque.movimentacoes", ativo_em=("estoque.estornar_movimentacao",)),
        Item("Notas fiscais", "receipt", "estoque.notas_fiscais", ativo_em=("estoque.conferir_nfe",)),
    ]),
    ("cadastros", "Cadastros", [
        _cadastro("Pacientes", "person", "pacientes"),
        _cadastro("Médicos", "person-badge", "medicos"),
        _cadastro("Medicamentos e materiais", "capsule", "produtos"),
        _cadastro("Locais de consumo", "geo-alt", "localizacoes"),
    ]),
    ("administracao", "Administração", [
        Item("Usuários e permissões", "people", "auth.usuarios", perfil=Usuario.ADMIN,
             ativo_em=("auth.editar_usuario",)),
        Item("Registros de auditoria", "journal-check", "auditoria.trilha", perfil=Usuario.ADMIN,
             ativo_em=("auditoria.*", "lgpd.acessos")),
        Item("Ajuda", "question-circle", "ajuda.guia", ativo_em=("ajuda.*",)),
    ]),
    ("configuracoes", "Configurações", [
        Item("Configurações", "gear", "auth.configuracoes", ativo_em=("auth.minha_senha",)),
    ]),
]


def menu_do_usuario(usuario, endpoint, view_args):
    """Grupos com os itens que o usuário pode ver, marcando o da página atual.

    Devolve (grupos, secao): secao é o grupo da página atual (para o caminho de navegação), ou None.
    """
    grupos, secao = [], None
    for chave, rotulo, itens in GRUPOS:
        visiveis = []
        for item in itens:
            if item.perfil and not usuario.pode(item.perfil):
                continue
            ativo = bool(endpoint) and item.corresponde(endpoint, view_args)
            visiveis.append({"item": item, "ativo": ativo})
            if ativo and secao is None:
                secao = {"chave": chave, "rotulo": rotulo, "item": item.rotulo}
        if visiveis:
            unico = len(visiveis) == 1 and visiveis[0]["item"].rotulo == rotulo
            grupos.append({"chave": chave, "rotulo": rotulo, "itens": visiveis, "unico": unico})
    return grupos, secao
