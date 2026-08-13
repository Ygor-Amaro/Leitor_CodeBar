"""Pipeline de leitura de um documento."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

from ..domain.excecoes import (
    CodigoInvalidoError,
    DocumentoIlegivelError,
    PaginaInexistenteError,
    RecorteInvalidoError,
)
from ..domain.fabrica import FabricaConversor
from ..domain.lotes import Recorte
from ..domain.models import CodigoBarras, PixPayload, ResultadoLeitura, StatusLeitura
from .decodificador import CodigoDetectado, Decodificador
from .renderizador import RenderizadorPagina

ZOOMS_PADRAO: tuple[float, ...] = (2.0, 3.0)

ObservadorResultado = Callable[[ResultadoLeitura], None]


class SeletorRoi(Protocol):
    """Porta do recorte manual. Fica nos adaptadores por depender de GUI."""

    def selecionar(self, imagem: np.ndarray, titulo: str) -> np.ndarray | None:
        """Devolve o recorte escolhido pelo operador, ou None se ele pular."""
        ...


class ProcessadorDocumento:
    """Encadeia renderização, decodificação e conversão, página a página.

    Dependências pelo construtor: dublês em teste, PyMuPDF e zxing-cpp em
    produção. É o que torna o pipeline verificável sem PDF e sem janela.
    """

    def __init__(
        self,
        renderizador: RenderizadorPagina,
        decodificador: Decodificador,
        fabrica: FabricaConversor | None = None,
        seletor: SeletorRoi | None = None,
        zooms: Sequence[float] = ZOOMS_PADRAO,
        sempre_manual: bool = False,
    ) -> None:
        self._renderizador = renderizador
        self._decodificador = decodificador
        self._fabrica = fabrica or FabricaConversor()
        self._seletor = seletor
        self._zooms = tuple(zooms) or ZOOMS_PADRAO
        self._sempre_manual = sempre_manual

    def processar(
        self,
        caminho: Path,
        ao_processar: ObservadorResultado | None = None,
    ) -> list[ResultadoLeitura]:
        """Lê o documento inteiro, uma linha de resultado por código.

        Falha de arquivo não interrompe o lote: vira resultado com status de erro.
        """
        arquivo = Path(caminho).name
        resultados: list[ResultadoLeitura] = []

        def registrar(resultado: ResultadoLeitura) -> None:
            resultados.append(resultado)
            if ao_processar is not None:
                ao_processar(resultado)

        try:
            with self._renderizador.abrir(Path(caminho)) as documento:
                for numero in range(documento.total_paginas):
                    for resultado in self._processar_pagina(documento, arquivo, numero):
                        registrar(resultado)
        except DocumentoIlegivelError as erro:
            registrar(ResultadoLeitura.erro(arquivo, 0, str(erro)))

        return resultados

    def total_de_paginas(self, caminho: Path) -> int:
        """Quantas páginas o documento tem — a tela de recorte navega por elas."""
        with self._renderizador.abrir(Path(caminho)) as documento:
            return documento.total_paginas

    def renderizar_pagina(self, caminho: Path, pagina: int, zoom: float) -> np.ndarray:
        """Rasteriza uma página avulsa, para a tela de recorte da web.

        `pagina` é base 1, como em `ResultadoLeitura`: quem chama é a interface,
        não o laço interno.
        """
        with self._renderizador.abrir(Path(caminho)) as documento:
            if not 1 <= pagina <= documento.total_paginas:
                raise PaginaInexistenteError(
                    f"O documento tem {documento.total_paginas} página(s); "
                    f"pediram a {pagina}."
                )
            return documento.renderizar(pagina - 1, zoom)

    def ler_area(
        self,
        arquivo: str,
        pagina: int,
        imagem: np.ndarray,
        recorte: Recorte | None = None,
    ) -> list[ResultadoLeitura]:
        """Decodifica uma imagem já renderizada, opcionalmente só num pedaço.

        Reaproveita `_priorizar` e `_interpretar` de propósito: o recorte manual
        passa pelas mesmas regras FEBRABAN em vez de virar um segundo pipeline.
        """
        trecho = _recortar(imagem, recorte) if recorte is not None else imagem
        detectados = self._decodificador.decodificar(trecho)

        if not detectados:
            if recorte is None:
                return [ResultadoLeitura.sem_codigo(arquivo, pagina)]
            return [
                ResultadoLeitura(
                    arquivo=arquivo,
                    pagina=pagina,
                    status=StatusLeitura.SEM_CODIGO,
                    observacao="Nenhum código encontrado na área marcada",
                )
            ]

        return [
            self._interpretar(arquivo, pagina, detectado)
            for detectado in self._priorizar(detectados)
        ]

    def _processar_pagina(
        self, documento, arquivo: str, numero: int
    ) -> list[ResultadoLeitura]:
        pagina = numero + 1

        try:
            detectados = self._detectar(documento, arquivo, numero)
        except Exception as erro:  # noqa: BLE001 - uma página ruim não derruba o lote
            return [ResultadoLeitura.erro(arquivo, pagina, f"Falha ao ler a página: {erro}")]

        if not detectados:
            return [ResultadoLeitura.sem_codigo(arquivo, pagina)]

        return [
            self._interpretar(arquivo, pagina, detectado)
            for detectado in self._priorizar(detectados)
        ]

    def _detectar(self, documento, arquivo: str, numero: int) -> list[CodigoDetectado]:
        """Zooms crescentes; recorte manual só se nenhum trouxer nada aproveitável.

        A escalada para no primeiro código *útil*, não no primeiro código: nota
        fiscal costuma ter ITF de rastreio legível no zoom baixo, e parar nele
        esconderia o boleto que só sai no alto.
        """
        if self._sempre_manual and self._seletor is not None:
            imagem = documento.renderizar(numero, self._zooms[0])
            return self._detectar_manual(imagem, arquivo, numero)

        imagem = None
        ruido: list[CodigoDetectado] = []
        for zoom in self._zooms:
            imagem = documento.renderizar(numero, zoom)
            detectados = self._decodificador.decodificar(imagem)
            if any(_eh_util(detectado) for detectado in detectados):
                return detectados
            ruido = detectados or ruido

        if self._seletor is not None and imagem is not None:
            recorte = self._detectar_manual(imagem, arquivo, numero)
            if recorte:
                return recorte

        # Nada aproveitável: devolve o ruído para virar pendência explícita, em
        # vez de sumir como "sem código".
        return ruido

    def _detectar_manual(
        self, imagem: np.ndarray, arquivo: str, numero: int
    ) -> list[CodigoDetectado]:
        titulo = f"{arquivo} - pagina {numero + 1} - selecione o codigo com o mouse"
        recorte = self._seletor.selecionar(imagem, titulo)  # type: ignore[union-attr]
        if recorte is None or recorte.size == 0:
            return []
        return self._decodificador.decodificar(recorte)

    @staticmethod
    def _priorizar(detectados: Sequence[CodigoDetectado]) -> list[CodigoDetectado]:
        """Descarta o ruído quando a página também trouxe um código utilizável —
        nota fiscal costuma ter outros ITF impressos."""
        uteis = [detectado for detectado in detectados if _eh_util(detectado)]
        return uteis or list(detectados)

    def _interpretar(
        self, arquivo: str, pagina: int, detectado: CodigoDetectado
    ) -> ResultadoLeitura:
        if detectado.eh_qrcode:
            return ResultadoLeitura.de_pix(arquivo, pagina, PixPayload(detectado.texto))

        try:
            codigo = CodigoBarras(detectado.texto)
        except CodigoInvalidoError as erro:
            return ResultadoLeitura.invalido(arquivo, pagina, detectado.texto, str(erro))

        linha = self._fabrica.converter(codigo)
        return ResultadoLeitura.de_boleto(arquivo, pagina, codigo, linha)


def _eh_util(detectado: CodigoDetectado) -> bool:
    """Um QR (PIX) ou um código FEBRABAN — o resto é ruído.

    Um critério só para escalar o zoom e para filtrar a página, senão divergem.
    """
    return detectado.eh_qrcode or _eh_codigo_barras_valido(detectado.texto)


def _recortar(imagem: np.ndarray, recorte: Recorte) -> np.ndarray:
    """Fatia a área marcada, presa aos limites da imagem.

    Arrastar o mouse para fora da página é gesto natural; sem prender, a fatia
    sairia vazia e o erro apareceria disfarçado de "nenhum código encontrado".
    """
    altura_total, largura_total = imagem.shape[:2]

    inicio_x = min(recorte.x, largura_total)
    inicio_y = min(recorte.y, altura_total)
    fim_x = min(inicio_x + recorte.largura, largura_total)
    fim_y = min(inicio_y + recorte.altura, altura_total)

    if fim_x <= inicio_x or fim_y <= inicio_y:
        raise RecorteInvalidoError("A área marcada está fora da página.")

    return imagem[inicio_y:fim_y, inicio_x:fim_x]


def _eh_codigo_barras_valido(texto: str) -> bool:
    try:
        CodigoBarras(texto)
    except CodigoInvalidoError:
        return False
    return True
