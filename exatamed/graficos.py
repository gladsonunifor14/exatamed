"""Geometria dos gráficos do Dashboard, desenhados em SVG no servidor.

Sem biblioteca de gráficos no navegador: o SVG respeita a política de segurança de conteúdo
(sem JavaScript inline) e funciona na impressão. O JavaScript do dashboard só acrescenta a
dica (tooltip) ao passar o mouse ou focar uma marca.
"""

import math
from decimal import Decimal


def moeda(valor):
    return "R$ " + f"{valor or 0:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def moeda_curta(valor):
    """Rótulo de eixo: R$ 1,2 mil, R$ 3,4 mi."""
    valor = float(valor or 0)
    for limite, sufixo in ((1e6, " mi"), (1e3, " mil")):
        if abs(valor) >= limite:
            texto = f"{valor / limite:.1f}".rstrip("0").rstrip(".").replace(".", ",")
            return f"R$ {texto}{sufixo}"
    return f"R$ {valor:.0f}"


def _passo_redondo(maximo, divisoes=4):
    bruto = maximo / divisoes
    magnitude = 10 ** math.floor(math.log10(bruto))
    for fator in (1, 2, 2.5, 5, 10):
        if bruto <= fator * magnitude:
            return fator * magnitude
    return 10 * magnitude


def _barra_arredondada(x, y, largura, base, raio=4):
    """Barra com as pontas de cima arredondadas e a base reta, apoiada no eixo."""
    raio = min(raio, largura / 2, max(base - y, 0))
    if raio <= 0:
        return f"M{x:.1f},{base:.1f}H{x + largura:.1f}V{y:.1f}H{x:.1f}Z"
    return (f"M{x:.1f},{base:.1f}V{y + raio:.1f}Q{x:.1f},{y:.1f} {x + raio:.1f},{y:.1f}"
            f"H{x + largura - raio:.1f}Q{x + largura:.1f},{y:.1f} {x + largura:.1f},{y + raio:.1f}"
            f"V{base:.1f}Z")


def barras(pontos, largura=1100, altura=280):
    """Colunas verticais de uma série (rótulo, valor) com eixo de valores em reais."""
    margem = {"esq": 64, "dir": 8, "topo": 12, "base": 28}
    area_l = largura - margem["esq"] - margem["dir"]
    area_a = altura - margem["topo"] - margem["base"]
    maior = max((float(p["valor"]) for p in pontos), default=0)
    passo = _passo_redondo(maior) if maior > 0 else 1
    teto = passo * max(math.ceil(maior / passo), 1)
    base = margem["topo"] + area_a
    escala = area_a / teto
    linhas = [{"y": base - v * escala, "rotulo": moeda_curta(v)}
              for v in (passo * i for i in range(int(round(teto / passo)) + 1))]
    fatia = area_l / max(len(pontos), 1)
    largura_barra = max(min(fatia - 2, fatia * 0.72, 48), 1)
    # Rótulos do eixo X espaçados para não se sobreporem (~56 px por rótulo).
    salto = max(1, math.ceil(len(pontos) * 56 / area_l))
    marcas = []
    for i, p in enumerate(pontos):
        valor = float(p["valor"])
        x = margem["esq"] + i * fatia + (fatia - largura_barra) / 2
        y = base - valor * escala
        marcas.append({
            "caminho": _barra_arredondada(x, y, largura_barra, base) if valor > 0 else None,
            "alvo_x": margem["esq"] + i * fatia, "alvo_l": fatia,
            "centro": x + largura_barra / 2, "rotulo": p["rotulo"],
            "mostrar_rotulo": i % salto == 0, "dica": f"{p['rotulo']}: {moeda(p['valor'])}",
        })
    return {"largura": largura, "altura": altura, "margem": margem, "base": base, "linhas": linhas,
            "marcas": marcas, "topo": margem["topo"], "fim_x": largura - margem["dir"]}


def curva_abc(itens, largura=620, altura=280):
    """Curva ABC: % acumulado do valor (eixo Y) pela % dos itens (eixo X), em trechos por classe."""
    margem = {"esq": 44, "dir": 12, "topo": 12, "base": 28}
    area_l = largura - margem["esq"] - margem["dir"]
    area_a = altura - margem["topo"] - margem["base"]
    base = margem["topo"] + area_a

    def ponto(perc_itens, perc_valor):
        return margem["esq"] + float(perc_itens) / 100 * area_l, base - float(perc_valor) / 100 * area_a

    total = len(itens)
    trechos, anterior = {}, ponto(0, 0)
    marcadores = []
    for item in itens:
        atual = ponto(Decimal(item["posicao"] * 100) / total, item["acumulado"])
        trechos.setdefault(item["classe"], []).append((anterior, atual))
        marcadores.append({"x": atual[0], "y": atual[1], "classe": item["classe"],
                           "dica": f"{item['posicao']}º {item['produto']} · classe {item['classe']} · "
                                   f"{moeda(item['valor'])} · acumulado "
                                   f"{str(round(item['acumulado'], 1)).replace('.', ',')}%"})
        anterior = atual
    caminhos = []
    for classe, segmentos in trechos.items():
        d = "".join(f"M{a[0]:.1f},{a[1]:.1f}L{b[0]:.1f},{b[1]:.1f}" for a, b in segmentos)
        caminhos.append({"classe": classe, "d": d})
    linhas = [{"y": base - v / 100 * area_a, "rotulo": f"{v}%"} for v in (0, 25, 50, 75, 100)]
    referencias = [{"y": base - v / 100 * area_a, "rotulo": f"{v}%"} for v in (80, 95)]
    eixo_x = [{"x": margem["esq"] + v / 100 * area_l, "rotulo": f"{v}%"} for v in (0, 20, 40, 60, 80, 100)]
    return {"largura": largura, "altura": altura, "margem": margem, "base": base, "linhas": linhas,
            "referencias": referencias, "eixo_x": eixo_x, "caminhos": caminhos,
            "marcadores": marcadores if total <= 150 else [], "fim_x": largura - margem["dir"]}
