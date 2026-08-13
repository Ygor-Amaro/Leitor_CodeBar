"""Conversão da página rasterizada para um formato que o navegador exibe.

No adaptador, não no serviço: `ServicoLotes` devolve matriz, e só quem responde
HTTP precisa saber que vira PNG. Servir JPEG ou WebP não tocaria na regra.
"""

from __future__ import annotations

import cv2
import numpy as np

from ...domain.excecoes import DocumentoIlegivelError


def para_png(imagem: np.ndarray) -> bytes:
    """Codifica a matriz BGR (ou em tons de cinza) que veio do renderizador.

    PNG e não JPEG: é sobre esta imagem que o operador mira o código, e artefato
    de compressão em barra fina atrapalha exatamente a mira.
    """
    sucesso, buffer = cv2.imencode(".png", imagem)
    if not sucesso:
        raise DocumentoIlegivelError("Não foi possível gerar a imagem desta página.")
    return buffer.tobytes()
