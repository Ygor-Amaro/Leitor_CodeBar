"""Regras de negócio FEBRABAN.

Esta camada é pura: não importa PyMuPDF, OpenCV nem toca em disco. Tudo aqui
pode ser testado com strings, sem PDF e sem interface gráfica.
"""

from .conversores import (
    ConversorArrecadacao,
    ConversorCobranca,
    ConversorLinhaDigitavel,
)
from .digito_verificador import (
    CalculadoraDV,
    Modulo10,
    Modulo11Arrecadacao,
    Modulo11Cobranca,
)
from .excecoes import CodigoInvalidoError, DocumentoIlegivelError, LeitorCbError
from .fabrica import FabricaConversor
from .models import (
    CodigoBarras,
    LinhaDigitavel,
    PixPayload,
    ResultadoLeitura,
    StatusLeitura,
    TipoDocumento,
)

__all__ = [
    "CalculadoraDV",
    "CodigoBarras",
    "CodigoInvalidoError",
    "ConversorArrecadacao",
    "ConversorCobranca",
    "ConversorLinhaDigitavel",
    "DocumentoIlegivelError",
    "FabricaConversor",
    "LeitorCbError",
    "LinhaDigitavel",
    "Modulo10",
    "Modulo11Arrecadacao",
    "Modulo11Cobranca",
    "PixPayload",
    "ResultadoLeitura",
    "StatusLeitura",
    "TipoDocumento",
]
