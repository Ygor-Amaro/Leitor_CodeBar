"""Transforma páginas de PDF em imagens para o decodificador."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Protocol

import fitz  # PyMuPDF
import numpy as np

from ..domain.excecoes import DocumentoIlegivelError


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
        matriz = fitz.Matrix(zoom, zoom)
        pix = self._documento[pagina].get_pixmap(matrix=matriz)

        imagem = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)

        if pix.n == 1:  # tons de cinza: o zxing-cpp aceita 2D direto
            convertida = imagem[:, :, 0]
        elif pix.n == 4:  # RGBA -> BGR
            convertida = imagem[:, :, 2::-1]
        else:  # RGB -> BGR
            convertida = imagem[:, :, ::-1]

        # O buffer precisa ser contíguo para atravessar a fronteira com o C++.
        return np.ascontiguousarray(convertida)


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
