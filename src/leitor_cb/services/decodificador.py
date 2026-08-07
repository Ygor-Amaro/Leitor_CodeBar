"""Leitura óptica dos códigos presentes numa imagem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import zxingcpp

# Boletos e guias usam ITF (2 de 5 intercalado); o PIX usa QR Code. Restringir
# os formatos reduz leitura de ruído e acelera a varredura da página inteira.
FORMATOS_PADRAO = "ITF,QRCode"


@dataclass(frozen=True)
class CodigoDetectado:
    """Resultado bruto da leitura óptica, ainda sem significado de negócio."""

    texto: str
    formato: str

    @property
    def eh_qrcode(self) -> bool:
        return self.formato.replace(" ", "").casefold() == "qrcode"


class Decodificador(Protocol):
    """Porta de leitura óptica."""

    def decodificar(self, imagem: np.ndarray) -> list[CodigoDetectado]: ...


class DecodificadorZxing:
    """Implementação com zxing-cpp.

    Usa `read_barcodes` (plural), que varre a imagem inteira e devolve todos os
    códigos — é o que permite dispensar a seleção manual de área.
    """

    def __init__(self, formatos: str = FORMATOS_PADRAO) -> None:
        self._formatos = zxingcpp.barcode_formats_from_str(formatos)

    def decodificar(self, imagem: np.ndarray) -> list[CodigoDetectado]:
        resultados = zxingcpp.read_barcodes(imagem, formats=self._formatos)
        return [
            CodigoDetectado(texto=resultado.text, formato=str(resultado.format))
            for resultado in resultados
            if resultado.text
        ]
