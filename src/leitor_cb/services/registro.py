"""Log estruturado: uma linha JSON por evento.

O servidor roda desatendido, e quando um lote dá errado o terminal é a única
testemunha. JSON, e não texto livre, para dar para filtrar por `identificador`.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any, Protocol


class Registrador(Protocol):
    """Porta de log. Trocar por arquivo, syslog ou nada é implementar isto."""

    def info(self, mensagem: str, **contexto: Any) -> None: ...

    def aviso(self, mensagem: str, **contexto: Any) -> None: ...

    def erro(
        self, mensagem: str, excecao: BaseException | None = None, **contexto: Any
    ) -> None: ...


class RegistradorJson:
    """Escreve uma linha JSON por evento na saída escolhida."""

    def __init__(self, destino: Any = None) -> None:
        self._destino = destino if destino is not None else sys.stderr

    def info(self, mensagem: str, **contexto: Any) -> None:
        self._escrever("info", mensagem, contexto)

    def aviso(self, mensagem: str, **contexto: Any) -> None:
        self._escrever("aviso", mensagem, contexto)

    def erro(self, mensagem: str, excecao: BaseException | None = None, **contexto: Any) -> None:
        if excecao is not None:
            contexto = {**contexto, "excecao": f"{type(excecao).__name__}: {excecao}"}
        self._escrever("erro", mensagem, contexto)

    def _escrever(self, nivel: str, mensagem: str, contexto: dict[str, Any]) -> None:
        evento = {
            "momento": datetime.now().isoformat(timespec="seconds"),
            "nivel": nivel,
            "mensagem": mensagem,
            **contexto,
        }
        # `default=str` porque contexto costuma trazer Path e datetime; um log
        # não pode derrubar a requisição que ele estava só descrevendo.
        print(json.dumps(evento, ensure_ascii=False, default=str), file=self._destino, flush=True)


class RegistradorSilencioso:
    """Descarta tudo. É o que os testes injetam para não sujar a saída."""

    def info(self, mensagem: str, **contexto: Any) -> None: ...

    def aviso(self, mensagem: str, **contexto: Any) -> None: ...

    def erro(
        self, mensagem: str, excecao: BaseException | None = None, **contexto: Any
    ) -> None: ...
