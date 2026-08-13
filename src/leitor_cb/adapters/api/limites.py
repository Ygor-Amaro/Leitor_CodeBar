"""Limite de envios por janela de tempo.

Com um operador em localhost quase nunca dispara. Existe porque o envio é a rota
cara — cada arquivo vira rasterização — e um duplo clique impaciente enfileira
trabalho que ninguém vai olhar.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from ...domain.excecoes import LeitorCbError


class EnvioExcessivoError(LeitorCbError):
    """Envios demais na janela. Vira 429 no tratador de erro."""


class LimitadorDeTaxa:
    """Janela deslizante em memória.

    O estado morre com o processo, que é o escopo de um servidor local. Com mais
    de um processo, isto vira Redis sem mudar quem chama.
    """

    def __init__(self, maximo: int, janela_segundos: float = 60.0) -> None:
        self._maximo = maximo
        self._janela = janela_segundos
        self._marcas: dict[str, list[float]] = defaultdict(list)
        self._trava = threading.Lock()

    def permitir(self, identificacao: str, agora: float | None = None) -> bool:
        """Registra a tentativa e diz se ela cabe no limite."""
        instante = time.monotonic() if agora is None else agora

        with self._trava:
            recentes = [
                marca for marca in self._marcas[identificacao] if instante - marca < self._janela
            ]

            if len(recentes) >= self._maximo:
                # Guarda a lista podada mesmo ao recusar: senão as marcas velhas
                # ficam para sempre e o cliente nunca se recupera.
                self._marcas[identificacao] = recentes
                return False

            recentes.append(instante)
            self._marcas[identificacao] = recentes
            return True
