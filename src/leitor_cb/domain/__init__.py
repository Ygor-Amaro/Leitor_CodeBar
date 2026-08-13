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
from .excecoes import (
    CodigoInvalidoError,
    DocumentoIlegivelError,
    LeitorCbError,
    PaginaInexistenteError,
    RecorteInvalidoError,
)
from .fabrica import FabricaConversor
from .lotes import (
    DocumentoDoLote,
    EstadoLote,
    LeituraDoLote,
    Lote,
    Recorte,
    ResumoLote,
    validar_zoom,
)
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
    "DocumentoDoLote",
    "DocumentoIlegivelError",
    "EstadoLote",
    "FabricaConversor",
    "LeituraDoLote",
    "LeitorCbError",
    "LinhaDigitavel",
    "Lote",
    "Modulo10",
    "Modulo11Arrecadacao",
    "Modulo11Cobranca",
    "PaginaInexistenteError",
    "PixPayload",
    "Recorte",
    "RecorteInvalidoError",
    "ResultadoLeitura",
    "ResumoLote",
    "StatusLeitura",
    "TipoDocumento",
    "validar_zoom",
]
