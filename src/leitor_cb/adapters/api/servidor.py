"""Ponto de entrada do servidor local (`uv run leitor-cb-web`)."""

from __future__ import annotations

import uvicorn

from ...config import ConfiguracaoWeb
from .app import criar_app


def main() -> int:
    config = ConfiguracaoWeb.do_ambiente()

    print(f"Leitor CB em http://{config.host}:{config.porta}")
    print("Encerre com Ctrl+C.\n")

    uvicorn.run(
        criar_app(config),
        host=config.host,
        port=config.porta,
        # "info" liga o log de acesso do uvicorn. Sem login no servidor, ele é o
        # único registro de quem baixou qual relatório de contas a pagar — o
        # `RegistradorJson` conta o que a aplicação fez, não quem pediu.
        log_level="info",
        access_log=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
