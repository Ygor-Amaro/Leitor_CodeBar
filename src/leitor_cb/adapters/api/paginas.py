"""Rotas de tela: páginas inteiras e os fragmentos que o HTMX troca.

A interatividade sai de atributos no HTML — o fragmento de progresso pede a si
mesmo a cada segundo e volta sem o atributo de repetição quando o lote termina,
que é como o polling para sozinho.

O JavaScript entra só onde o navegador é insubstituível: arrastar o retângulo do
recorte (`selecao.js`) e copiar/filtrar o relatório (`relatorio.js`).
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse

from ...domain.lotes import Lote, Recorte, validar_zoom
from ...services.lotes import substitui_a_pagina
from .dependencias import Config, LimiteDeEnvio, Servico, como_recebidos
from .rotas import relatorio_do_lote
from .visao import templates

roteador = APIRouter(include_in_schema=False)

EVENTO_HISTORICO = "lote-atualizado"
"""Disparado no cabeçalho `HX-Trigger`; a lista de lotes escuta e se recarrega."""


@roteador.get("/")
def inicio(request: Request, servico: Servico, config: Config) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "config": config,
            "historico": servico.historico(config.lotes_no_historico),
        },
    )


@roteador.post("/lotes", dependencies=[LimiteDeEnvio])
def enviar(request: Request, servico: Servico, arquivos: list[UploadFile]) -> Response:
    criado = servico.criar(como_recebidos(arquivos))
    # Relê antes de desenhar: um PDF pequeno pode ter terminado enquanto a
    # resposta era montada, e o painel mostraria progresso de trabalho acabado.
    lote = servico.obter(criado.identificador)
    # Avisa o histórico já na criação, para o lote aparecer na lista enquanto roda.
    return _painel(request, servico, lote, avisar_historico=True)


@roteador.get("/lotes/{identificador}/painel")
def painel(request: Request, servico: Servico, identificador: str) -> Response:
    lote = servico.obter(identificador)
    return _painel(request, servico, lote, avisar_historico=lote.terminado)


@roteador.get("/lotes/{identificador}/relatorio")
def baixar(servico: Servico, identificador: str) -> FileResponse:
    return relatorio_do_lote(servico, identificador)


@roteador.post("/lotes/{identificador}/arquivos/descartar")
def descartar_arquivos(request: Request, servico: Servico, identificador: str) -> Response:
    servico.descartar_arquivos(identificador)
    return _painel(request, servico, servico.obter(identificador), avisar_historico=False)


@roteador.get("/lotes/{identificador}")
def pagina_do_lote(request: Request, servico: Servico, identificador: str) -> Response:
    """Endereço fixo de um lote — serve para reabrir um relatório depois."""
    lote = servico.obter(identificador)
    return templates.TemplateResponse(
        request=request,
        name="lote.html",
        context=_contexto(servico, lote),
    )


# --------------------------------------------------------------- recorte manual


@roteador.get("/lotes/{identificador}/documentos/{documento}/paginas/{pagina}")
def tela_de_recorte(
    request: Request,
    servico: Servico,
    config: Config,
    identificador: str,
    documento: int,
    pagina: int,
    zoom: float | None = None,
) -> Response:
    """Mostra a página rasterizada para o operador marcar onde está o código."""
    lote = servico.obter(identificador)
    # Conferido aqui, não só na rota da imagem: o zoom da URL vai para o `<img>`,
    # e um valor fora da faixa desenharia a tela com a imagem quebrada e sem dizer
    # por quê.
    escolhido = validar_zoom(zoom) if zoom else config.zoom_selecao_padrao

    return templates.TemplateResponse(
        request=request,
        name="pagina.html",
        context={
            "lote": lote,
            "documento": servico.documento(identificador, documento),
            "pagina": pagina,
            "total_paginas": servico.total_de_paginas(identificador, documento),
            "zoom": escolhido,
            "zooms": config.zooms_selecao,
            "leituras": [
                leitura
                for leitura in servico.leituras(identificador)
                if leitura.documento_indice == documento
                and leitura.resultado.pagina == pagina
            ],
        },
    )


@roteador.post("/lotes/{identificador}/documentos/{documento}/paginas/{pagina}/releitura")
def reler(
    request: Request,
    servico: Servico,
    identificador: str,
    documento: int,
    pagina: int,
    zoom: float = Form(default=2.0),
    x: int = Form(default=0),
    y: int = Form(default=0),
    largura: int = Form(default=0),
    altura: int = Form(default=0),
) -> Response:
    """Relê a página, com a área marcada ou inteira.

    Largura ou altura zeradas são o combinado para "não marquei nada" — é o botão
    ao lado. O zoom vale nos dois casos: é o que está na tela.
    """
    recorte = (
        Recorte(x=x, y=y, largura=largura, altura=altura, zoom=zoom)
        if largura > 0 and altura > 0
        else None
    )
    resultados = servico.reler_pagina(identificador, documento, pagina, recorte, zoom)
    atualizou = substitui_a_pagina(resultados)

    return templates.TemplateResponse(
        request=request,
        name="_leitura.html",
        context={
            "identificador": identificador,
            "resultados": resultados,
            "recortado": recorte is not None,
            "atualizou": atualizou,
        },
        # Sem leitura nova não há o que recarregar no histórico.
        headers={"HX-Trigger": EVENTO_HISTORICO} if atualizou else None,
    )


@roteador.get("/historico")
def historico(request: Request, servico: Servico, config: Config) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="_historico.html",
        context={"historico": servico.historico(config.lotes_no_historico)},
    )


# ------------------------------------------------------------------------ apoio


def _painel(
    request: Request, servico: Servico, lote: Lote, avisar_historico: bool
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="_painel.html",
        context=_contexto(servico, lote),
        headers={"HX-Trigger": EVENTO_HISTORICO} if avisar_historico else None,
    )


def _contexto(servico: Servico, lote: Lote) -> dict[str, object]:
    """As leituras só são buscadas quando o lote acabou: enquanto roda a tela
    mostra progresso, e a tabela parcial custaria uma varredura por segundo."""
    return {
        "lote": lote,
        "resumo": servico.resumo(lote.identificador),
        "leituras": servico.leituras(lote.identificador) if lote.terminado else [],
        "arquivos_disponiveis": (
            servico.arquivos_disponiveis(lote.identificador) if lote.terminado else False
        ),
    }
