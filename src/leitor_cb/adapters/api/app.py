"""Composition root da web.

O que `cli.py` é para o terminal: o único lugar que nomeia implementação concreta.
As rotas conhecem só `ServicoLotes`; que por baixo haja SQLite, PyMuPDF e
zxing-cpp é decisão daqui.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ...config import ConfiguracaoWeb
from ...services.armazenamento import ArmazenamentoEmDisco
from ...services.decodificador import DecodificadorZxing
from ...services.exportador import ExportadorCsv
from ...services.lotes import ServicoLotes
from ...services.processador import ProcessadorDocumento
from ...services.registro import Registrador, RegistradorJson
from ...services.renderizador import RenderizadorPdf
from ...services.repositorio import RepositorioSqlite
from . import erros, paginas, rotas
from .limites import LimitadorDeTaxa, LimiteDeCorpo
from .visao import DIRETORIO_ESTATICOS, templates


def _versao() -> str:
    """Versão do pacote instalado.

    Lida do metadado em vez de repetida aqui: a etiqueta da imagem, o
    `pyproject.toml` e esta linha já divergiram uma vez, e é justo na hora de
    voltar atrás numa atualização que a versão exibida precisa ser verdade.
    """
    try:
        return version("leitor-cb")
    except PackageNotFoundError:  # rodando do fonte, sem instalar
        return "0.0.0"


def _conferir_estaticos() -> None:
    """Derruba a subida se o pacote veio sem os arquivos estáticos.

    O `mount` aceita uma pasta vazia sem reclamar: as telas carregariam, mas sem
    htmx não haveria barra de progresso, sem `relatorio.js` não haveria botão de
    copiar e a tela de recorte não desenharia o retângulo. Uma falha muda dessas
    é bem pior de diagnosticar às pressas do que um servidor que não sobe.
    """
    if not (DIRETORIO_ESTATICOS / "htmx.min.js").is_file():
        raise RuntimeError(
            f"Arquivos estáticos não encontrados em {DIRETORIO_ESTATICOS}. "
            "O pacote foi instalado sem 'adapters/web/static'."
        )


def montar_servico(
    config: ConfiguracaoWeb,
    registrador: Registrador,
    executor: Executor | None = None,
) -> ServicoLotes:
    """Liga as implementações concretas às portas do serviço de lotes."""
    return ServicoLotes(
        repositorio=RepositorioSqlite(config.banco),
        armazenamento=ArmazenamentoEmDisco(
            raiz=config.uploads,
            tamanho_maximo=config.tamanho_maximo_bytes,
            maximo_de_arquivos=config.maximo_de_arquivos,
        ),
        processador=ProcessadorDocumento(
            renderizador=RenderizadorPdf(),
            decodificador=DecodificadorZxing(config.formatos),
            # Sem seletor: a janela do OpenCV abriria na máquina do servidor, não
            # na de quem está no navegador. O que o automático não resolve vira
            # pendência, como no `--sem-gui`.
            seletor=None,
            zooms=config.zooms,
        ),
        fabrica_exportador=lambda prefixo: ExportadorCsv(config.saida, prefixo),
        diretorio_saida=config.saida,
        # Uma thread só: rasterizar é caro em memória, e dois lotes simultâneos
        # disputam CPU sem entregar nenhum mais cedo.
        executor=executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="lote"),
        registrador=registrador,
        retencao=config.retencao,
    )


def criar_app(
    config: ConfiguracaoWeb | None = None,
    servico: ServicoLotes | None = None,
    registrador: Registrador | None = None,
) -> FastAPI:
    """Monta a aplicação.

    `servico` e `registrador` são parâmetros para o teste montar o mesmo app com
    dublês; sem eles, testar uma rota exigiria PDF de verdade em disco.
    """
    config = config or ConfiguracaoWeb.do_ambiente()
    registrador = registrador or RegistradorJson()
    servico = servico or montar_servico(config, registrador)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
        # O processo passa dias desligado; a varredura na subida é o que faz o
        # prazo de retenção valer mesmo assim.
        servico.limpar_expirados()
        # A fila vive na memória deste processo: lote em andamento no banco de um
        # servidor que acabou de subir é resto de queda, e sem fechar aqui ele
        # ficaria "processando" para sempre, com a tela pedindo o andamento a
        # cada segundo.
        servico.fechar_interrompidos()
        yield
        # Espera o lote em andamento: matar a thread no meio o deixaria
        # eternamente "processando" no banco.
        servico.encerrar()

    app = FastAPI(
        title="Leitor CB",
        description="Leitura de códigos de barras FEBRABAN e QR Codes PIX em PDFs.",
        version=_versao(),
        lifespan=ciclo_de_vida,
        # A porta está aberta à rede do escritório e não há login: o Swagger seria
        # um mapa clicável de todos os endpoints, inclusive o DELETE que descarta
        # os PDFs de outra pessoa. A tabela de endpoints do README documenta a API.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.state.configuracao = config
    app.state.servico = servico
    app.state.registrador = registrador
    app.state.limitador = LimitadorDeTaxa(maximo=config.envios_por_minuto)

    # Antes de tudo: corta o envio grande demais enquanto ele ainda é corpo de
    # requisição, não arquivo em disco. O `responder` é injetado para o middleware
    # não precisar importar `erros` — que importa `limites` — e para o formato da
    # recusa continuar saindo do mesmo lugar que o dos outros erros.
    app.add_middleware(
        LimiteDeCorpo,
        maximo_bytes=config.tamanho_maximo_envio_bytes,
        responder=lambda request, erro: erros.resposta_de_erro(request, templates, erro),
    )

    _conferir_estaticos()
    app.mount("/estaticos", StaticFiles(directory=DIRETORIO_ESTATICOS), name="estaticos")

    erros.registrar_tratadores(app, templates, registrador)
    app.include_router(rotas.roteador)
    app.include_router(paginas.roteador)

    return app
