"""API REST dos lotes.

Existe por si: automatiza o envio por script sem passar pela tela, e é o que um
front em outra tecnologia consumiria.

As rotas são `def`, não `async def`, de propósito: gravar upload e consultar
SQLite bloqueiam, e assim o FastAPI as joga numa thread do pool em vez de travar
o laço de eventos — e com ele o polling de progresso de todo mundo.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from ...domain.lotes import Recorte
from ...services.lotes import ZOOM_RELEITURA_PADRAO
from .dependencias import Config, LimiteDeEnvio, Servico, como_recebidos
from .esquemas import (
    ErroResposta,
    LoteDetalhado,
    LoteResposta,
    RecortePedido,
    ResultadoResposta,
)
from .imagens import para_png

roteador = APIRouter(
    prefix="/api",
    tags=["lotes"],
    responses={404: {"model": ErroResposta}, 500: {"model": ErroResposta}},
)


@roteador.get("/saude", summary="Responde se o processo está de pé")
def saude() -> dict[str, str]:
    """Alvo do HEALTHCHECK do contêiner.

    Não toca no banco de propósito: a checagem roda a cada 30 s para sempre, e
    apontá-la para `/api/lotes` faria cada rodada abrir duas conexões SQLite e
    marcar o contêiner como doente numa disputa de trava passageira. Aqui, o que
    se pergunta é só se o processo aceita requisição.
    """
    return {"status": "ok"}


@roteador.post(
    "/lotes",
    response_model=LoteResposta,
    status_code=status.HTTP_201_CREATED,
    dependencies=[LimiteDeEnvio],
    summary="Envia PDFs e abre um lote",
)
def criar_lote(servico: Servico, arquivos: list[UploadFile]) -> LoteResposta:
    """Responde assim que os arquivos estão em disco; a leitura segue em segundo
    plano. Acompanhe por `GET /api/lotes/{identificador}`.

    O estado é relido do repositório: um lote curto pode já ter terminado, e
    anunciar "pendente" faria o cliente perguntar de novo à toa.
    """
    criado = servico.criar(como_recebidos(arquivos))
    identificador = criado.identificador
    return LoteResposta.de(servico.obter(identificador), servico.resumo(identificador))


@roteador.get("/lotes", response_model=list[LoteResposta], summary="Lotes recentes")
def listar_lotes(
    servico: Servico,
    config: Config,
    limite: int = Query(default=0, ge=0, le=200),
) -> list[LoteResposta]:
    quantos = limite or config.lotes_no_historico
    return [LoteResposta.de(lote, resumo) for lote, resumo in servico.historico(quantos)]


@roteador.get(
    "/lotes/{identificador}",
    response_model=LoteDetalhado,
    summary="Estado do lote e as leituras já extraídas",
)
def obter_lote(servico: Servico, identificador: str) -> LoteDetalhado:
    return LoteDetalhado.de(
        servico.obter(identificador),
        servico.resumo(identificador),
        servico.leituras(identificador),
        servico.arquivos_disponiveis(identificador),
    )


@roteador.get(
    "/lotes/{identificador}/documentos/{documento}/paginas/{pagina}/imagem",
    summary="Página do PDF rasterizada em PNG",
    response_class=Response,
)
def imagem_da_pagina(
    servico: Servico,
    identificador: str,
    documento: int,
    pagina: int,
    zoom: float = Query(default=2.0, gt=0, le=8),
) -> Response:
    """A imagem da tela de recorte. Só existe enquanto os PDFs não foram
    descartados."""
    imagem = servico.imagem_da_pagina(identificador, documento, pagina, zoom)
    return Response(
        content=para_png(imagem),
        media_type="image/png",
        # O PDF não muda; sem cache, cada troca de zoom rerasterizaria o que já
        # foi visto.
        headers={"Cache-Control": "private, max-age=300"},
    )


@roteador.post(
    "/lotes/{identificador}/documentos/{documento}/paginas/{pagina}/releitura",
    response_model=list[ResultadoResposta],
    summary="Relê uma página, opcionalmente só na área marcada",
)
def reler_pagina(
    servico: Servico,
    identificador: str,
    documento: int,
    pagina: int,
    recorte: RecortePedido | None = None,
    zoom: float = Query(default=ZOOM_RELEITURA_PADRAO, gt=0, le=8),
) -> list[ResultadoResposta]:
    """Relê a página e, se achar algo, substitui as linhas dela e regenera o CSV.

    Sem corpo, relê a página inteira no `zoom` pedido; com corpo, só o retângulo,
    e aí vale o zoom de dentro dele — as coordenadas dependem dele. Em ambos os
    casos o zoom é o ponto de partida: não achando nada, a leitura tenta
    ampliações maiores antes de desistir.

    Leitura vazia não apaga o que já estava na página; a resposta vem com o
    status `sem_codigo` e o relatório fica intacto.
    """
    area = (
        Recorte(
            x=recorte.x,
            y=recorte.y,
            largura=recorte.largura,
            altura=recorte.altura,
            zoom=recorte.zoom,
        )
        if recorte is not None
        else None
    )
    resultados = servico.reler_pagina(identificador, documento, pagina, area, zoom)
    return [ResultadoResposta.de(resultado, documento) for resultado in resultados]


@roteador.delete(
    "/lotes/{identificador}/arquivos",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Descarta os PDFs do lote antes do prazo",
)
def descartar_arquivos(servico: Servico, identificador: str) -> Response:
    servico.descartar_arquivos(identificador)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@roteador.get("/lotes/{identificador}/relatorio", summary="Baixa o CSV do lote")
def baixar_relatorio(servico: Servico, identificador: str) -> FileResponse:
    return relatorio_do_lote(servico, identificador)


def relatorio_do_lote(servico: Servico, identificador: str) -> FileResponse:
    """Compartilhado com a rota de tela — o download é o mesmo arquivo."""
    caminho = servico.caminho_do_relatorio(identificador)
    return FileResponse(caminho, media_type="text/csv", filename=caminho.name)
