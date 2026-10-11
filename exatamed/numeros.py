"""Quantidades e valores monetários com precisão decimal exata.

Custos e quantidades usam `Decimal` (colunas NUMERIC(14, 4) no banco) para que totais,
custos PEPS e saldos não acumulem erros de arredondamento de ponto flutuante.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CASAS = 4
QUANTUM = Decimal(1).scaleb(-CASAS)  # 0.0001
ZERO = Decimal(0)


def decimal(valor):
    """Converte número ou texto (aceita vírgula decimal: "1.234,5" ou "1234,5") em Decimal com 4 casas."""
    if isinstance(valor, Decimal):
        resultado = valor
    elif isinstance(valor, (int, float)):
        resultado = Decimal(str(valor))
    else:
        texto = (valor or "").strip().replace(" ", "")
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        try:
            resultado = Decimal(texto)
        except InvalidOperation:
            raise ValueError(f"Número inválido: {valor!r}") from None
    if not resultado.is_finite():
        raise ValueError(f"Número inválido: {valor!r}")
    return resultado.quantize(QUANTUM, rounding=ROUND_HALF_UP)


def formatar(valor):
    """Texto curto para mensagens: Decimal('5.0000') -> '5'; Decimal('2.5000') -> '2,5'."""
    texto = f"{decimal(valor).normalize():f}"
    return texto.replace(".", ",")
