"""Regra de negócio do lote web: receber, enfileirar, acompanhar, corrigir, entregar.

Costura entre a API e o pipeline: a API não sabe ler um PDF e o
`ProcessadorDocumento` não sabe o que é um lote.

A leitura roda fora da requisição: rasterizar dezenas de páginas leva minutos e o
navegador estoura o timeout antes de ver qualquer coisa. O envio responde na hora
com o identificador e a tela pergunta o andamento.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import Executor
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from ..domain.excecoes import LeitorCbError
from ..domain.lotes import (
    DocumentoDoLote,
    EstadoLote,
    LeituraDoLote,
    Lote,
    Recorte,
    ResumoLote,
    validar_zoom,
)
from ..domain.models import ResultadoLeitura, StatusLeitura
from .armazenamento import Armazenamento, ArquivoRecebido, DocumentoGuardado
from .exportador import Exportador
from .processador import ProcessadorDocumento
from .registro import Registrador
from .repositorio import RepositorioLotes

FabricaExportador = Callable[[str], Exportador]
"""Recebe o prefixo do arquivo e devolve o exportador do relatório."""

RETENCAO_PADRAO = timedelta(hours=24)

OBSERVACAO_INTERROMPIDO = (
    "O servidor foi reiniciado durante a leitura. Envie os arquivos novamente."
)
"""Explicação que aparece na tela do lote fechado por `fechar_interrompidos`.

Diz o que fazer, não o que houve: o operador não tem como retomar de onde parou —
a fila morreu com o processo — e reenviar é a única saída.
"""

ZOOM_RELEITURA_PADRAO = 2.0
"""Ampliação da releitura de página inteira quando nenhuma é pedida.

O mesmo primeiro zoom da varredura automática. Abaixo disso a releitura enxergaria
menos que a passada que já falhou.
"""

ZOOMS_DE_ESCALADA = (3.0, 4.0)
"""Ampliações tentadas depois da escolhida, quando ela não acha nada.

Digitalização de boleto costuma resolver a partir de 3.0 — abaixo disso as barras
finas não chegam a dois pixels e nenhum recorte salva. Vai até 4.0 porque aqui é
uma página só, com o operador esperando: caro é ele tentar de novo à mão.
"""


def substitui_a_pagina(resultados: Sequence[ResultadoLeitura]) -> bool:
    """Se esta releitura pode sobrescrever o que já havia na página.

    A releitura manual é a palavra final **quando acha algo**. Se não achou, o que
    estava lá vale mais: apagar uma leitura boa por causa de uma tentativa vazia é
    perda de dado sem desfazer, e o operador nem sempre marcou a página errada —
    pode só ter marcado num zoom que não resolvia.
    """
    return any(
        resultado.status is StatusLeitura.SUCESSO for resultado in resultados
    )


def _zooms_da_releitura(escolhido: float) -> tuple[float, ...]:
    """O zoom pedido primeiro, depois os maiores da escalada."""
    return (escolhido, *(zoom for zoom in ZOOMS_DE_ESCALADA if zoom > escolhido))


def _reescalar(recorte: Recorte | None, zoom: float) -> Recorte | None:
    """Leva o retângulo para outra ampliação da mesma página.

    As coordenadas vieram em pixels do zoom em que o operador marcou; sem
    converter, a escalada recortaria um pedaço deslocado do documento.
    """
    if recorte is None or recorte.zoom == zoom:
        return recorte

    fator = zoom / recorte.zoom
    return Recorte(
        x=int(recorte.x * fator),
        y=int(recorte.y * fator),
        largura=max(1, int(recorte.largura * fator)),
        altura=max(1, int(recorte.altura * fator)),
        zoom=zoom,
    )


class LoteNaoEncontradoError(LeitorCbError):
    """Identificador que não existe — ou nunca existiu, ou o banco foi limpo."""


class RelatorioIndisponivelError(LeitorCbError):
    """O lote existe, mas não há CSV para baixar (ainda rodando, ou falhou)."""


class ArquivosIndisponiveisError(LeitorCbError):
    """Os PDFs do lote já foram descartados — não dá para reler nem exibir página."""


class ServicoLotes:
    """Coordena o ciclo de vida de um envio.

    Tudo pelo construtor: em teste entram repositório em memória e executor
    síncrono; em produção, SQLite e uma thread.
    """

    def __init__(
        self,
        repositorio: RepositorioLotes,
        armazenamento: Armazenamento,
        processador: ProcessadorDocumento,
        fabrica_exportador: FabricaExportador,
        diretorio_saida: Path,
        executor: Executor,
        registrador: Registrador,
        retencao: timedelta = RETENCAO_PADRAO,
    ) -> None:
        self._repositorio = repositorio
        self._armazenamento = armazenamento
        self._processador = processador
        self._fabrica_exportador = fabrica_exportador
        self._diretorio_saida = Path(diretorio_saida)
        self._executor = executor
        self._registrador = registrador
        self._retencao = retencao

    # ------------------------------------------------------------------ envio

    def criar(self, arquivos: Sequence[ArquivoRecebido]) -> Lote:
        """Grava os arquivos, abre o lote e o enfileira.

        Se a triagem do armazenamento barrar um arquivo, levanta
        `ArquivoRejeitadoError` e nada é aberto.
        """
        self.limpar_expirados()

        identificador = uuid.uuid4().hex
        guardados = self._armazenamento.guardar(identificador, arquivos)

        lote = Lote(
            identificador=identificador,
            criado_em=datetime.now(),
            estado=EstadoLote.PENDENTE,
            total_documentos=len(guardados),
        )

        try:
            self._repositorio.criar(lote)
            self._repositorio.registrar_documentos(
                identificador,
                [
                    DocumentoDoLote(indice=indice, nome_original=guardado.nome_original)
                    for indice, guardado in enumerate(guardados, start=1)
                ],
            )
        except Exception:
            # Sem registro no banco o lote fica invisível e os PDFs, órfãos.
            self._armazenamento.descartar(identificador)
            raise

        self._registrador.info(
            "lote recebido", lote=identificador, documentos=len(guardados)
        )
        self._executor.submit(self._processar, identificador, guardados)
        return lote

    def limpar_expirados(self) -> list[str]:
        """Apaga os PDFs de envios antigos.

        Na subida e a cada novo envio, não num agendador: o processo é local e
        passa dias desligado, e o agendador dormiria junto.
        """
        apagados = self._armazenamento.expirar(self._retencao)
        if apagados:
            self._registrador.info("arquivos expirados descartados", lotes=len(apagados))
        return apagados

    def fechar_interrompidos(self) -> list[str]:
        """Encerra os lotes que o processo anterior deixou pela metade.

        Chamado na subida, junto de `limpar_expirados`. A fila é do processo — um
        lote em andamento no banco de um servidor que acabou de subir não tem
        ninguém trabalhando nele, e ficaria "processando" até alguém mexer no
        banco à mão. Marcado como falho, ele ao menos para de rodar a barra de
        progresso e diz ao operador o que fazer.
        """
        fechados = self._repositorio.marcar_interrompidos(OBSERVACAO_INTERROMPIDO)
        if fechados:
            self._registrador.info("lotes interrompidos encerrados", lotes=len(fechados))
        return fechados

    # ----------------------------------------------------------------- worker

    def _processar(self, identificador: str, guardados: Sequence[DocumentoGuardado]) -> None:
        """Corpo do job. Roda em outra thread, então nada escapa: toda falha vira
        estado do lote, visível na tela."""
        lote = self._repositorio.obter(identificador)
        if lote is None:
            self._registrador.erro("lote sumiu antes de processar", lote=identificador)
            return

        try:
            lote = self._publicar(replace(lote, estado=EstadoLote.PROCESSANDO))

            acumulados: list[ResultadoLeitura] = []
            for indice, documento in enumerate(guardados, start=1):
                resultados = self._ler(documento)
                self._repositorio.acrescentar_resultados(identificador, indice, resultados)
                acumulados.extend(resultados)
                lote = self._publicar(replace(lote, documentos_processados=indice))

            nome_csv = self._gerar_relatorio(identificador, acumulados)
            self._publicar(replace(lote, estado=EstadoLote.CONCLUIDO, nome_csv=nome_csv))

            resumo = ResumoLote.de(acumulados)
            self._registrador.info(
                "lote concluído",
                lote=identificador,
                leituras=resumo.total,
                pendencias=resumo.pendencias,
            )
        except Exception as erro:  # noqa: BLE001 - a thread não pode morrer calada
            self._registrador.erro("lote falhou", erro, lote=identificador)
            self._publicar(
                replace(
                    lote,
                    estado=EstadoLote.FALHOU,
                    observacao=f"Falha ao processar o lote: {erro}",
                )
            )

        # Os PDFs ficam em disco até o prazo ou o descarte manual — é o que
        # permite reler à mão a página que o automático não resolveu.

    def _ler(self, documento: DocumentoGuardado) -> list[ResultadoLeitura]:
        resultados = self._processador.processar(documento.caminho)
        # O processador só conhece o nome que geramos ("001.pdf"); o relatório
        # precisa do nome que o operador enviou.
        return [replace(resultado, arquivo=documento.nome_original) for resultado in resultados]

    def _publicar(self, lote: Lote) -> Lote:
        self._repositorio.atualizar(lote)
        return lote

    # ------------------------------------------------------- leitura manual

    def total_de_paginas(self, identificador: str, documento_indice: int) -> int:
        return self._processador.total_de_paginas(
            self._documento_em_disco(identificador, documento_indice)
        )

    def imagem_da_pagina(
        self, identificador: str, documento_indice: int, pagina: int, zoom: float
    ) -> np.ndarray:
        """Rasteriza a página para a tela exibir sob o retângulo de seleção."""
        caminho = self._documento_em_disco(identificador, documento_indice)
        return self._processador.renderizar_pagina(caminho, pagina, validar_zoom(zoom))

    def reler_pagina(
        self,
        identificador: str,
        documento_indice: int,
        pagina: int,
        recorte: Recorte | None = None,
        zoom: float | None = None,
    ) -> list[ResultadoLeitura]:
        """Relê uma página, opcionalmente só na área marcada pelo operador.

        Sem recorte, `zoom` é a ampliação escolhida na tela; com recorte, o zoom
        vem dele, pois as coordenadas só valem naquela ampliação.

        O resultado substitui as linhas da página — mas só quando encontra algo,
        conforme `substitui_a_pagina`.
        """
        caminho = self._documento_em_disco(identificador, documento_indice)
        nome = self.documento(identificador, documento_indice).nome_original
        zoom = (
            recorte.zoom
            if recorte is not None
            else validar_zoom(zoom or ZOOM_RELEITURA_PADRAO)
        )

        resultados = self._ler_escalando(caminho, nome, pagina, recorte, zoom)
        substituiu = substitui_a_pagina(resultados)

        if substituiu:
            self._repositorio.substituir_pagina(
                identificador, documento_indice, pagina, resultados
            )
            self._regerar_relatorio(self.obter(identificador))

        self._registrador.info(
            "página relida manualmente",
            lote=identificador,
            documento=documento_indice,
            pagina=pagina,
            leituras=len(resultados),
            substituiu=substituiu,
        )
        return resultados

    def _ler_escalando(
        self,
        caminho: Path,
        nome: str,
        pagina: int,
        recorte: Recorte | None,
        zoom: float,
    ) -> list[ResultadoLeitura]:
        """Tenta a área marcada em ampliações crescentes até achar um código.

        O operador já disse *onde* está o código; insistir é mais barato do que
        devolver "não achei" e deixá-lo adivinhar qual botão de zoom tentar. A
        varredura automática escala pelo mesmo motivo, e sem isto a tela de
        recorte enxergaria menos que ela — foi o que aconteceu com um boleto que
        só resolve a partir de 3.0, marcado no zoom 2.0 em que a tela abre.
        """
        resultados: list[ResultadoLeitura] = []

        for tentativa in _zooms_da_releitura(zoom):
            imagem = self._processador.renderizar_pagina(caminho, pagina, tentativa)
            resultados = self._processador.ler_area(
                nome, pagina, imagem, _reescalar(recorte, tentativa)
            )
            if substitui_a_pagina(resultados):
                return resultados

        # Nada em zoom nenhum: devolve a última tentativa, que é a mais nítida.
        return resultados

    def descartar_arquivos(self, identificador: str) -> None:
        """Apaga os PDFs antes do prazo, a pedido do operador."""
        self.obter(identificador)
        self._armazenamento.descartar(identificador)
        self._registrador.info("arquivos descartados a pedido", lote=identificador)

    def arquivos_disponiveis(self, identificador: str) -> bool:
        return bool(self._armazenamento.documentos(identificador))

    # --------------------------------------------------------------- consulta

    def obter(self, identificador: str) -> Lote:
        lote = self._repositorio.obter(identificador)
        if lote is None:
            raise LoteNaoEncontradoError(f"Lote não encontrado: {identificador}")
        return lote

    def leituras(self, identificador: str) -> list[LeituraDoLote]:
        self.obter(identificador)  # 404 antes de devolver lista vazia
        return self._repositorio.leituras_de(identificador)

    def resultados(self, identificador: str) -> list[ResultadoLeitura]:
        return [leitura.resultado for leitura in self.leituras(identificador)]

    def documentos(self, identificador: str) -> list[DocumentoDoLote]:
        self.obter(identificador)
        return self._repositorio.documentos_de(identificador)

    def documento(self, identificador: str, indice: int) -> DocumentoDoLote:
        """Um documento do lote, pelo índice.

        Histórico anterior à tabela de documentos cai num nome técnico em vez de
        derrubar a tela de recorte.
        """
        for documento in self.documentos(identificador):
            if documento.indice == indice:
                return documento
        return DocumentoDoLote(indice=indice, nome_original=f"{indice:03d}.pdf")

    def resumo(self, identificador: str) -> ResumoLote:
        return self._repositorio.resumos_de([identificador]).get(identificador, ResumoLote())

    def historico(self, limite: int = 20) -> list[tuple[Lote, ResumoLote]]:
        """Lotes recentes com o resumo de cada um.

        Os resumos saem numa consulta só: lote a lote seria N+1.
        """
        lotes = self._repositorio.listar(limite)
        resumos = self._repositorio.resumos_de([lote.identificador for lote in lotes])
        return [(lote, resumos.get(lote.identificador, ResumoLote())) for lote in lotes]

    def caminho_do_relatorio(self, identificador: str) -> Path:
        """Caminho do CSV do lote, já conferido."""
        lote = self.obter(identificador)
        if not lote.nome_csv:
            raise RelatorioIndisponivelError(
                "O relatório deste lote ainda não está pronto."
            )

        destino = self._arquivo_de_saida(lote.nome_csv)
        if destino is None:
            raise RelatorioIndisponivelError("O arquivo do relatório não está mais disponível.")
        return destino

    def encerrar(self) -> None:
        """Espera o job em andamento terminar. Chamado no shutdown do servidor."""
        self._executor.shutdown(wait=True)

    # ----------------------------------------------------------------- apoio

    def _documento_em_disco(self, identificador: str, documento_indice: int) -> Path:
        self.obter(identificador)
        caminho = self._armazenamento.caminho(identificador, documento_indice)
        if caminho is None:
            raise ArquivosIndisponiveisError(
                "Os arquivos deste lote já foram descartados. "
                "Envie o PDF novamente para reler a página."
            )
        return caminho

    def _gerar_relatorio(
        self, identificador: str, resultados: Sequence[ResultadoLeitura]
    ) -> str:
        destino = self._fabrica_exportador(f"lote_{identificador[:8]}").exportar(resultados)
        return destino.name if destino is not None else ""

    def _regerar_relatorio(self, lote: Lote) -> None:
        """Reescreve o CSV depois de uma correção e remove o anterior.

        Sem remover, cada releitura deixaria mais um CSV quase igual em
        `data/output` e ninguém saberia qual é o bom.
        """
        anterior = lote.nome_csv
        nome = self._gerar_relatorio(lote.identificador, self.resultados(lote.identificador))
        self._publicar(replace(lote, nome_csv=nome))

        if anterior and anterior != nome:
            obsoleto = self._arquivo_de_saida(anterior)
            if obsoleto is not None:
                obsoleto.unlink(missing_ok=True)

    def _arquivo_de_saida(self, nome: str) -> Path | None:
        """Recompõe um nome guardado no banco dentro da pasta de saída.

        A conferência impede que um valor estragado no banco vire leitura — ou
        remoção — de arquivo fora dela.
        """
        raiz = self._diretorio_saida.resolve()
        destino = (raiz / nome).resolve()

        if not destino.is_relative_to(raiz) or not destino.is_file():
            return None
        return destino
