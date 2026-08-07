"""Orquestração: renderizar, decodificar, converter e exportar.

Cada classe aqui tem uma responsabilidade e depende das outras por interface
(`typing.Protocol`), nunca pela implementação concreta.
"""

from .decodificador import CodigoDetectado, Decodificador, DecodificadorZxing
from .exportador import Exportador, ExportadorConsole, ExportadorCsv
from .processador import ProcessadorDocumento, SeletorRoi
from .renderizador import DocumentoRenderizado, RenderizadorPagina, RenderizadorPdf

__all__ = [
    "CodigoDetectado",
    "Decodificador",
    "DecodificadorZxing",
    "DocumentoRenderizado",
    "Exportador",
    "ExportadorConsole",
    "ExportadorCsv",
    "ProcessadorDocumento",
    "RenderizadorPagina",
    "RenderizadorPdf",
    "SeletorRoi",
]
