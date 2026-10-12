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


# ---------------------------------------------------------------- mascaramento (LGPD)
# Exibem só parte do documento, o suficiente para conferência, em listas, relatórios
# e exportações. O dado completo fica visível apenas na ficha do cadastro.

def mascarar_cpf(cpf):
    """529.982.247-25 -> ***.982.247-**"""
    d = somente_digitos(cpf)
    if len(d) != 11:
        return mascarar_generico(cpf)
    return f"***.{d[3:6]}.{d[6:9]}-**"


def mascarar_cns(cns):
    """Cartão SUS: mostra só os 4 últimos dígitos."""
    d = somente_digitos(cns)
    return "*" * (len(d) - 4) + d[-4:] if len(d) > 4 else mascarar_generico(cns)


def mascarar_telefone(telefone):
    """(85) 99999-1234 -> (**) *****-1234"""
    if not telefone:
        return ""
    total = len(somente_digitos(telefone))
    resultado, vistos = [], 0
    for caractere in telefone:
        if caractere.isdigit():
            vistos += 1
            resultado.append(caractere if vistos > total - 4 else "*")
        else:
            resultado.append(caractere)
    return "".join(resultado)


def mascarar_email(email):
    if not email or "@" not in email:
        return mascarar_generico(email)
    usuario, dominio = email.split("@", 1)
    return f"{usuario[:1]}***@{dominio}"


def mascarar_generico(valor):
    """Qualquer outro documento: mantém só os 3 últimos caracteres."""
    if not valor:
        return ""
    return "*" * max(len(valor) - 3, 3) + valor[-3:] if len(valor) > 3 else "***"
