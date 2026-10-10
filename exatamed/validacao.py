"""Validações e normalizações de documentos brasileiros."""

import re


def somente_digitos(valor):
    return re.sub(r"\D", "", valor or "")


def cpf_valido(cpf):
    digitos = somente_digitos(cpf)
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d) * peso for d, peso in zip(digitos[:tamanho], range(tamanho + 1, 1, -1)))
        verificador = (soma * 10) % 11 % 10
        if verificador != int(digitos[tamanho]):
            return False
    return True


def formatar_cpf(cpf):
    d = somente_digitos(cpf)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else cpf


def cep_valido(cep):
    return len(somente_digitos(cep)) == 8


def formatar_cep(cep):
    d = somente_digitos(cep)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else cep


def cns_valido(cns):
    """Valida o Cartão Nacional de Saúde (CNS) — 15 dígitos, algoritmo do DATASUS."""
    d = somente_digitos(cns)
    if len(d) != 15 or d[0] not in "126789":
        return False
    return sum(int(c) * peso for c, peso in zip(d, range(15, 0, -1))) % 11 == 0
