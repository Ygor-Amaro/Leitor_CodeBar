"""Tratamento de erro em um lugar só.

Toda falha esperada é subclasse de `LeitorCbError` e é aqui que ela vira código
HTTP. Rota nenhuma escreve `status_code` de erro à mão: quem recusa algo levanta
a exceção do domínio.

O formato segue quem perguntou: fragmento de HTML para o HTMX (`HX-Request`),
página inteira para o navegador navegando — o link antigo de um lote apagado
precisa de caminho de volta, não de um `{"erro": ...}` — e JSON no resto.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from ...domain.excecoes import (
    DocumentoIlegivelError,
    LeitorCbError,
    PaginaInexistenteError,
    RecorteInvalidoError,
)
from ...services.armazenamento import ArquivoRejeitadoError
from ...services.lotes import (
    ArquivosIndisponiveisError,
    LoteNaoEncontradoError,
    RelatorioIndisponivelError,
)
from ...services.registro import Registrador
from .limites import EnvioExcessivoError

SITUACOES: tuple[tuple[type[LeitorCbError], int], ...] = (
    (ArquivoRejeitadoError, status.HTTP_400_BAD_REQUEST),
    (RecorteInvalidoError, status.HTTP_400_BAD_REQUEST),
    (DocumentoIlegivelError, status.HTTP_400_BAD_REQUEST),
    (LoteNaoEncontradoError, status.HTTP_404_NOT_FOUND),
    (PaginaInexistenteError, status.HTTP_404_NOT_FOUND),
    (RelatorioIndisponivelError, status.HTTP_409_CONFLICT),
    (ArquivosIndisponiveisError, status.HTTP_409_CONFLICT),
    (EnvioExcessivoError, status.HTTP_429_TOO_MANY_REQUESTS),
)

GENERICO = "Erro interno. Veja o log do servidor."


def codigo_de(erro: BaseException) -> int:
    for tipo, codigo in SITUACOES:
        if isinstance(erro, tipo):
            return codigo
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def registrar_tratadores(
    app: FastAPI, templates: Jinja2Templates, registrador: Registrador
) -> None:
    @app.exception_handler(LeitorCbError)
    async def _esperado(request: Request, erro: Exception) -> Response:
        codigo = codigo_de(erro)
        if codigo >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            registrador.erro("falha no processamento", erro, caminho=request.url.path)
        return _responder(request, templates, codigo, str(erro))

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, erro: Exception) -> Response:
        registrador.erro("erro não tratado", erro, caminho=request.url.path)
        # Genérica de propósito: a original carrega caminho de disco e detalhe de
        # biblioteca, inúteis para quem está na tela.
        return _responder(
            request, templates, status.HTTP_500_INTERNAL_SERVER_ERROR, GENERICO
        )


def _responder(
    request: Request, templates: Jinja2Templates, codigo: int, mensagem: str
) -> Response:
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="_alerta.html",
            context={"mensagem": mensagem},
            status_code=codigo,
        )

    if _navegando(request):
        return templates.TemplateResponse(
            request=request,
            name="erro.html",
            context={"mensagem": mensagem, "codigo": codigo},
            status_code=codigo,
        )

    return JSONResponse({"erro": mensagem}, status_code=codigo)


def _navegando(request: Request) -> bool:
    """Se quem pediu foi a barra de endereços, e não um programa.

    `/api` é contrato e responde JSON sempre; fora dali, quem aceita HTML navega.
    """
    if request.url.path.startswith("/api"):
        return False
    return "text/html" in request.headers.get("accept", "")
