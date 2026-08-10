"""Pipeline de leitura de um documento."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

from ..domain.excecoes import CodigoInvalidoError, DocumentoIlegivelError
from ..domain.fabrica import FabricaConversor
from ..domain.models import CodigoBarras, PixPayload, ResultadoLeitura
from .decodificador import CodigoDetectado, Decodificador
from .renderizador import RenderizadorPagina

ZOOMS_PADRAO: tuple[float, ...] = (2.0, 3.0)

ObservadorResultado = Callable[[ResultadoLeitura], None]


class SeletorRoi(Protocol):
    """Porta do recorte manual — implementada na camada de adaptadores porque
    depende de interface gráfica."""

    def selecionar(self, imagem: np.ndarray, titulo: str) -> np.ndarray | None:
        """Devolve o recorte escolhido pelo operador, ou None se ele pular."""
        ...


class ProcessadorDocumento:
    """Encadeia renderização, decodificação e conversão, página a página.

    Recebe todas as dependências pelo construtor: em teste, entram dublês; em
    produção, PyMuPDF e zxing-cpp. É o que torna o pipeline verificável sem PDF
    e sem janela gráfica.
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
        """Lê um documento inteiro e devolve uma linha de resultado por código.

        Falha de um arquivo não interrompe o lote: vira um resultado com status
        de erro.
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
        """Tenta a leitura automática em zooms crescentes; cai para o recorte
        manual só se nenhum zoom trouxer algo aproveitável.

        A escalada para quando aparece um código *útil*, não quando aparece um
        código qualquer: uma nota fiscal costuma ter ITF de rastreio legível já
        no zoom baixo, e parar nele esconderia o boleto que só sai no zoom alto.
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

        # Sem nada aproveitável: devolve o que houver para virar pendência
        # explícita no relatório, em vez de sumir como "sem código".
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
        """Descarta ruído quando a página também trouxe um código utilizável.

        Uma nota fiscal pode ter outros códigos ITF impressos; se algum for um
        boleto válido ou um QR, só esses interessam.
        """
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
    """Um QR (PIX) ou um código de barras no formato FEBRABAN — o resto é ruído.

    Mesmo critério usado para decidir se vale escalar o zoom e para filtrar a
    página; manter os dois juntos evita que divirjam.
    """
    return detectado.eh_qrcode or _eh_codigo_barras_valido(detectado.texto)


def _eh_codigo_barras_valido(texto: str) -> bool:
    try:
        CodigoBarras(texto)
    except CodigoInvalidoError:
        return False
    return True
