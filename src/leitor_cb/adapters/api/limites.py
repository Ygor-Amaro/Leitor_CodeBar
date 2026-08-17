"""Tetos de envio: quantas requisições por minuto e quantos bytes por requisição.

Com um operador em localhost quase nunca disparam. Existem porque o envio é a
rota cara — cada arquivo vira rasterização, cada byte vira disco — e o servidor
fica publicado na rede do escritório sem login.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from starlette.requests import Request

from ...domain.excecoes import LeitorCbError

METODOS_COM_CORPO = frozenset({"POST", "PUT", "PATCH"})


class EnvioExcessivoError(LeitorCbError):
    """Envios demais na janela. Vira 429 no tratador de erro."""


class EnvioGrandeDemaisError(LeitorCbError):
    """Corpo da requisição acima do teto total. Vira 413 no tratador de erro."""


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


class LimiteDeCorpo:
    """Teto de bytes por requisição, cobrado antes de o corpo virar arquivo.

    O teto por arquivo do `ArmazenamentoEmDisco` chega tarde demais para servir de
    defesa: quando a rota roda, o Starlette já leu o corpo inteiro e derramou cada
    parte num arquivo temporário. Até aqui, o pior caso admitido era
    `maximo_de_arquivos` × `tamanho_maximo_mb` — 50 × 25 MB = 1,25 GB por envio —
    escrito em disco antes de qualquer recusa, e o disco é o mesmo do banco e dos
    relatórios. Com a porta aberta à rede e sem login, encher o disco não exige
    nem má intenção: basta arrastar a pasta errada.

    Middleware ASGI, e não dependência da rota, porque o FastAPI lê o corpo
    *antes* de resolver dependências — uma checagem lá chegaria depois do estrago.

    Duas defesas, porque o `Content-Length` é informação de quem envia:

    1. **Cabeçalho acima do teto**: recusa antes de ler um byte, com 413 montado
       pelo mesmo `responder` do tratador de erros — o formato continua decidido
       em `api/erros.py` (fragmento para o HTMX, JSON no `/api`).
    2. **Cabeçalho ausente ou mentindo para baixo** (envio em `chunked`): a soma
       do que realmente chegou corta a leitura no meio. Aí a exceção sobe pelo
       parser do corpo, e o FastAPI a converte em 400 — o código é menos preciso
       que o 413, mas o disco está igualmente protegido, que é o que importa.
    """

    def __init__(self, app: Any, maximo_bytes: int, responder: Callable) -> None:
        self._app = app
        self._maximo = maximo_bytes
        self._responder = responder

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http" or scope.get("method") not in METODOS_COM_CORPO:
            await self._app(scope, receive, send)
            return

        declarado = _tamanho_declarado(scope)
        if declarado is not None and declarado > self._maximo:
            resposta = self._responder(
                Request(scope, receive), EnvioGrandeDemaisError(_recado(self._maximo))
            )
            await resposta(scope, receive, send)
            return

        await self._app(scope, _CorpoContado(receive, self._maximo), send)


class _CorpoContado:
    """Envelope do `receive` que soma os bytes lidos e corta ao passar do teto."""

    def __init__(self, receive: Callable, maximo: int) -> None:
        self._receive = receive
        self._maximo = maximo
        self._total = 0

    async def __call__(self) -> dict:
        evento = await self._receive()
        if evento.get("type") != "http.request":
            return evento

        self._total += len(evento.get("body", b""))
        if self._total > self._maximo:
            raise EnvioGrandeDemaisError(_recado(self._maximo))
        return evento


def _recado(maximo: int) -> str:
    return (
        f"O envio passa do limite de {maximo / (1024 * 1024):.0f} MB no total. "
        "Divida em envios menores."
    )


def _tamanho_declarado(scope: dict) -> int | None:
    """Content-Length do pedido, quando vem e faz sentido."""
    for nome, valor in scope.get("headers", ()):
        if nome == b"content-length":
            try:
                return int(valor)
            except ValueError:
                return None
    return None


__all__ = [
    "EnvioExcessivoError",
    "EnvioGrandeDemaisError",
    "LimitadorDeTaxa",
    "LimiteDeCorpo",
]
