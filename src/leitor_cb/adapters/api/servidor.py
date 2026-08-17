"""Ponto de entrada do servidor local (`uv run leitor-cb-web`)."""

from __future__ import annotations

import uvicorn

from ...config import ConfiguracaoWeb
from .app import criar_app

ENDERECOS_DE_ESCUTA = {"0.0.0.0", "::", "[::]", ""}  # noqa: S104
"""Curingas: dizem em quais interfaces escutar, não um endereço que se abre."""


def _endereco_navegavel(host: str) -> str:
    """Endereço que o operador pode colar no navegador.

    Dentro do contêiner o host é `0.0.0.0` — a única forma de a porta publicada
    responder. Impresso cru, vira um link que o navegador não conecta (no Windows
    `http://0.0.0.0:8000` simplesmente falha), e o servidor parece não ter subido.
    """
    return "127.0.0.1" if host in ENDERECOS_DE_ESCUTA else host


def main() -> int:
    config = ConfiguracaoWeb.do_ambiente()

    print(f"Leitor CB em http://{_endereco_navegavel(config.host)}:{config.porta}")
    print("Encerre com Ctrl+C.\n")

    uvicorn.run(
        criar_app(config),
        host=config.host,
        port=config.porta,
        # O log da aplicação já sai estruturado, mas ele registra o processamento
        # do lote, não o acesso. Sem login, o access log do uvicorn é o único
        # registro de quem baixou qual relatório de contas a pagar — e ele exige
        # `info`, porque em `warning` uma requisição bem-sucedida não aparece.
        log_level="info",
        access_log=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
