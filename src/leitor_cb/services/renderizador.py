"""Transforma páginas de PDF em imagens para o decodificador."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Protocol

import fitz  # PyMuPDF
import numpy as np

from ..domain.excecoes import DocumentoIlegivelError

PIXELS_MAXIMOS = 80_000_000
"""Teto da imagem rasterizada, em pixels.

O zoom sozinho não limita nada: o tamanho de saída é o da página *vezes* o zoom, e
o formato PDF admite página de 14400 pontos. Um arquivo de 522 bytes com essa
medida pede 2,3 GB no zoom 2.0 da varredura automática e 37 GB no zoom 8 — e o
`ascontiguousarray` abaixo faz uma segunda cópia, dobrando o pico. Sem este teto,
meio quilobyte enviado por qualquer um da rede derruba o servidor por falta de
memória, antes mesmo de alguém pedir a imagem.

80 Mpx cabe A3 inteiro no zoom 8 (o maior da tela de recorte), que é bem mais do
que um boleto precisa. Acima disso o documento vira pendência explícita, no mesmo
caminho de qualquer outra página que não deu para ler.
"""


class DocumentoRenderizado(Protocol):
    """Documento aberto, capaz de rasterizar uma página sob demanda."""

    @property
    def total_paginas(self) -> int: ...

    def renderizar(self, pagina: int, zoom: float) -> np.ndarray:
        """Devolve a página (base 0) como imagem BGR ou tons de cinza."""
        ...


class RenderizadorPagina(Protocol):
    """Porta de entrada de documentos. Trocar PyMuPDF por outra biblioteca é
    escrever outra implementação deste contrato."""

    def abrir(self, caminho: Path) -> AbstractContextManager[DocumentoRenderizado]: ...


class DocumentoPdf:
    """Adaptador em torno de um `fitz.Document` aberto."""

    def __init__(self, documento: fitz.Document) -> None:
        self._documento = documento

    @property
    def total_paginas(self) -> int:
        return len(self._documento)

    def renderizar(self, pagina: int, zoom: float) -> np.ndarray:
        """Rasteriza a página no zoom pedido.

        O zoom é o que decide se um código mal digitalizado será legível — daí
        ele ser parâmetro, e não constante como no script antigo.
        """
        alvo = self._documento[pagina]
        # Conferido antes do `get_pixmap`: depois já seria a alocação que se quer
        # evitar. A conta é a do PyMuPDF — medida da página vezes o zoom.
        _conferir_tamanho(alvo.rect.width * zoom, alvo.rect.height * zoom, pagina)

        matriz = fitz.Matrix(zoom, zoom)
        pix = alvo.get_pixmap(matrix=matriz)

        imagem = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)

        if pix.n == 1:  # tons de cinza: o zxing-cpp aceita 2D direto
            convertida = imagem[:, :, 0]
        elif pix.n == 4:  # RGBA -> BGR
            convertida = imagem[:, :, 2::-1]
        else:  # RGB -> BGR
            convertida = imagem[:, :, ::-1]

        # O buffer precisa ser contíguo para atravessar a fronteira com o C++.
        return np.ascontiguousarray(convertida)


def _conferir_tamanho(largura: float, altura: float, pagina: int) -> None:
    """Barra a página que, no zoom pedido, viraria uma imagem grande demais."""
    pixels = int(largura) * int(altura)
    if pixels > PIXELS_MAXIMOS:
        raise DocumentoIlegivelError(
            f"A página {pagina + 1} ficaria com {pixels / 1_000_000:.0f} milhões de "
            f"pixels neste zoom, acima do limite de {PIXELS_MAXIMOS // 1_000_000} "
            "milhões. Reduza o zoom ou envie a página num formato menor."
        )


class RenderizadorPdf:
    """Implementação de `RenderizadorPagina` baseada em PyMuPDF."""

    @contextmanager
    def abrir(self, caminho: Path) -> Iterator[DocumentoPdf]:
        try:
            documento = fitz.open(caminho)
        except Exception as erro:  # noqa: BLE001 - a origem varia com o arquivo
            raise DocumentoIlegivelError(
                f"Não foi possível abrir '{caminho}': {erro}"
            ) from erro

        try:
            yield DocumentoPdf(documento)
        finally:
            documento.close()
