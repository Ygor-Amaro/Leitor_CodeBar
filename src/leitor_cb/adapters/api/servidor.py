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
        log_level="warning",  # o log da aplicação já sai estruturado
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
