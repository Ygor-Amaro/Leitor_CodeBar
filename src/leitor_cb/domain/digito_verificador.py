"""Algoritmos de dígito verificador do padrão FEBRABAN.

Cada algoritmo é uma classe com o mesmo contrato (`CalculadoraDV`), o que permite
aos conversores escolherem a estratégia em tempo de execução sem `if` espalhado
no meio da conversão.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class CalculadoraDV(Protocol):
    """Contrato de qualquer algoritmo de dígito verificador."""

    def calcular(self, bloco: str) -> str:
        """Devolve o dígito verificador do bloco numérico, como string."""
        ...


class Modulo10:
    """Módulo 10 — usado nos campos da linha digitável de cobrança e nas
    arrecadações cujo identificador de valor é 6 ou 7.

    Multiplicador alterna 2 e 1 da direita para a esquerda; produtos maiores que
    9 têm seus algarismos somados (ex.: 18 -> 1 + 8 = 9).
    """

    def calcular(self, bloco: str) -> str:
        soma = 0
        multiplicador = 2

        for digito in reversed(bloco):
            produto = int(digito) * multiplicador
            if produto > 9:
                produto = (produto // 10) + (produto % 10)
            soma += produto
            multiplicador = 1 if multiplicador == 2 else 2

        resto = soma % 10
        return str(0 if resto == 0 else 10 - resto)


class Modulo11Arrecadacao:
    """Módulo 11 na variante de arrecadação (identificador de valor 8 ou 9).

    Multiplicador cresce de 2 a 9 da direita para a esquerda e reinicia. Um DV
    calculado como 10 ou 11 vira 0.
    """

    def calcular(self, bloco: str) -> str:
        dv = 11 - (_soma_ponderada_2_a_9(bloco) % 11)
        if dv in (10, 11):
            dv = 0
        return str(dv)


class Modulo11Cobranca:
    """Módulo 11 na variante de cobrança, usado apenas para conferir o dígito
    verificador geral do código de barras (5ª posição).

    Difere do de arrecadação na exceção: aqui um DV calculado como 0, 10 ou 11
    vira 1.
    """

    def calcular(self, bloco: str) -> str:
        dv = 11 - (_soma_ponderada_2_a_9(bloco) % 11)
        if dv in (0, 10, 11):
            dv = 1
        return str(dv)


def _soma_ponderada_2_a_9(bloco: str) -> int:
    """Soma os dígitos ponderados por 2, 3, ..., 9, 2, 3, ... da direita para a
    esquerda — base comum às duas variantes de Módulo 11."""
    soma = 0
    multiplicador = 2

    for digito in reversed(bloco):
        soma += int(digito) * multiplicador
        multiplicador += 1
        if multiplicador > 9:
            multiplicador = 2

    return soma


# Instâncias reutilizáveis — os algoritmos não guardam estado.
MODULO_10 = Modulo10()
MODULO_11_ARRECADACAO = Modulo11Arrecadacao()
MODULO_11_COBRANCA = Modulo11Cobranca()
