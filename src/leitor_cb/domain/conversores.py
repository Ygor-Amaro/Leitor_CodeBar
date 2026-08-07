"""Conversão do código de barras (44 dígitos) para a linha digitável."""

from abc import ABC, abstractmethod

from .digito_verificador import MODULO_10, CalculadoraDV
from .models import CodigoBarras, LinhaDigitavel, TipoDocumento


class ConversorLinhaDigitavel(ABC):
    """Contrato comum às duas famílias de documento."""

    @abstractmethod
    def converter(self, codigo: CodigoBarras) -> LinhaDigitavel:
        """Devolve a linha digitável correspondente ao código de barras."""


class ConversorCobranca(ConversorLinhaDigitavel):
    """Boleto bancário: 44 dígitos viram 47.

    A linha reordena o código original em cinco campos. Os três primeiros
    recebem um DV de Módulo 10 cada; o quarto é o DV geral e o quinto traz
    fator de vencimento e valor.
    """

    def __init__(self, calculadora: CalculadoraDV | None = None) -> None:
        self._dv = calculadora or MODULO_10

    def converter(self, codigo: CodigoBarras) -> LinhaDigitavel:
        d = codigo.digitos

        campo1 = d[0:4] + d[19:24]  # banco + moeda + início do campo livre
        campo2 = d[24:34]
        campo3 = d[34:44]
        campo4 = d[4:5]  # DV geral
        campo5 = d[5:19]  # fator de vencimento + valor

        digitos = (
            f"{campo1}{self._dv.calcular(campo1)}"
            f"{campo2}{self._dv.calcular(campo2)}"
            f"{campo3}{self._dv.calcular(campo3)}"
            f"{campo4}{campo5}"
        )
        return LinhaDigitavel(digitos, TipoDocumento.COBRANCA)


class ConversorArrecadacao(ConversorLinhaDigitavel):
    """Guias e contas de consumo: 44 dígitos viram 48.

    O código é fatiado em quatro blocos de 11 dígitos e cada bloco ganha seu
    próprio DV. Qual algoritmo usar é decidido pelo identificador de valor do
    próprio código (`CodigoBarras.calculadora_arrecadacao`).
    """

    def __init__(self, calculadora: CalculadoraDV | None = None) -> None:
        # Permite fixar o algoritmo em teste; em produção, fica a cargo do código.
        self._dv_fixa = calculadora

    def converter(self, codigo: CodigoBarras) -> LinhaDigitavel:
        dv = self._dv_fixa or codigo.calculadora_arrecadacao
        blocos = [codigo.digitos[i : i + 11] for i in range(0, 44, 11)]

        digitos = "".join(f"{bloco}{dv.calcular(bloco)}" for bloco in blocos)
        return LinhaDigitavel(digitos, TipoDocumento.ARRECADACAO)
