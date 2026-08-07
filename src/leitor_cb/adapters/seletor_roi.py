"""Recorte manual de área, usado quando a leitura automática falha."""

from __future__ import annotations

import cv2
import numpy as np


class SeletorRoiOpenCv:
    """Abre uma janela e devolve o pedaço da imagem marcado pelo operador.

    Implementa a porta `services.processador.SeletorRoi`. É a única classe do
    projeto que bloqueia esperando interação humana — por isso fica isolada
    aqui e é injetada como opcional.
    """

    def __init__(self, largura: int = 700, altura: int = 900) -> None:
        self._largura = largura
        self._altura = altura

    def selecionar(self, imagem: np.ndarray, titulo: str) -> np.ndarray | None:
        cv2.namedWindow(titulo, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        cv2.resizeWindow(titulo, self._largura, self._altura)

        try:
            x, y, largura, altura = cv2.selectROI(
                titulo, imagem, showCrosshair=True, fromCenter=False
            )
        finally:
            cv2.destroyWindow(titulo)

        if largura <= 0 or altura <= 0:  # operador apertou ESC ou não arrastou
            return None

        return imagem[y : y + altura, x : x + largura]
