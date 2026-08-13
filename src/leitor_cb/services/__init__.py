"""Orquestração: renderizar, decodificar, converter e exportar.

Cada classe aqui tem uma responsabilidade e depende das outras por interface
(`typing.Protocol`), nunca pela implementação concreta.
"""

from .armazenamento import (
    Armazenamento,
    ArmazenamentoEmDisco,
    ArquivoRecebido,
    ArquivoRejeitadoError,
    DocumentoGuardado,
)
from .decodificador import CodigoDetectado, Decodificador, DecodificadorZxing
from .exportador import Exportador, ExportadorConsole, ExportadorCsv
from .lotes import (
    ZOOM_RELEITURA_PADRAO,
    ArquivosIndisponiveisError,
    LoteNaoEncontradoError,
    RelatorioIndisponivelError,
    ServicoLotes,
)
from .processador import ProcessadorDocumento, SeletorRoi
from .registro import Registrador, RegistradorJson, RegistradorSilencioso
from .renderizador import DocumentoRenderizado, RenderizadorPagina, RenderizadorPdf
from .repositorio import RepositorioLotes, RepositorioSqlite

__all__ = [
    "Armazenamento",
    "ArmazenamentoEmDisco",
    "ArquivoRecebido",
    "ArquivoRejeitadoError",
    "ArquivosIndisponiveisError",
    "CodigoDetectado",
    "Decodificador",
    "DecodificadorZxing",
    "DocumentoGuardado",
    "DocumentoRenderizado",
    "Exportador",
    "ExportadorConsole",
    "ExportadorCsv",
    "LoteNaoEncontradoError",
    "ProcessadorDocumento",
    "Registrador",
    "RegistradorJson",
    "RegistradorSilencioso",
    "RelatorioIndisponivelError",
    "RenderizadorPagina",
    "RenderizadorPdf",
    "RepositorioLotes",
    "RepositorioSqlite",
    "SeletorRoi",
    "ServicoLotes",
    "ZOOM_RELEITURA_PADRAO",
]
