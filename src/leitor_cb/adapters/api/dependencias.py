"""Ligações que as rotas pedem por injeção.

As rotas não constroem nada: pedem `Servico` e recebem o que a composition root
(`app.py`) pendurou no estado do app — é o que deixa o teste montar o mesmo app
com um repositório em memória.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends, Request, UploadFile

from ...config import ConfiguracaoWeb
from ...services.armazenamento import ArquivoRecebido
from ...services.lotes import ServicoLotes
from .limites import EnvioExcessivoError, LimitadorDeTaxa


def _servico(request: Request) -> ServicoLotes:
    return request.app.state.servico


def _configuracao(request: Request) -> ConfiguracaoWeb:
    return request.app.state.configuracao


def _limitador(request: Request) -> LimitadorDeTaxa:
    return request.app.state.limitador


Servico = Annotated[ServicoLotes, Depends(_servico)]
Config = Annotated[ConfiguracaoWeb, Depends(_configuracao)]


def conferir_limite(
    request: Request,
    limitador: Annotated[LimitadorDeTaxa, Depends(_limitador)],
) -> None:
    """Barra envios em rajada. Aplicada só nas rotas de upload."""
    origem = request.client.host if request.client else "desconhecido"
    if not limitador.permitir(origem):
        raise EnvioExcessivoError(
            "Envios demais em pouco tempo. Espere um minuto e tente de novo."
        )


LimiteDeEnvio = Depends(conferir_limite)


def como_recebidos(arquivos: Sequence[UploadFile]) -> list[ArquivoRecebido]:
    """Adapta o upload do Starlette ao contrato do armazenamento.

    Passa o `file`, não um `await read()`: o armazenamento grava em pedaços, e
    ler tudo antes deixaria o lote inteiro na memória.
    """
    return [
        ArquivoRecebido(nome=arquivo.filename or "", fluxo=arquivo.file)
        for arquivo in arquivos
    ]
