"""Guarda em disco os PDFs que chegam pelo navegador.

Tudo aqui parte de que o arquivo é hostil: nome escolhido por quem enviou. O nome
original é metadado e nunca vira caminho — quem nomeia o arquivo em disco somos
nós.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO, Protocol

from ..domain.excecoes import LeitorCbError

ASSINATURA_PDF = b"%PDF-"
PEDACO = 1024 * 1024


class ArquivoRejeitadoError(LeitorCbError):
    """O envio não passou na triagem — extensão, tamanho ou conteúdo."""


@dataclass(frozen=True)
class ArquivoRecebido:
    """Um upload ainda não gravado. `fluxo` é lido em pedaços: um lote de boletos
    digitalizados passa fácil de centenas de MB."""

    nome: str
    fluxo: BinaryIO


@dataclass(frozen=True)
class DocumentoGuardado:
    """O arquivo já em disco, com o nome de origem preservado à parte."""

    nome_original: str
    caminho: Path


class Armazenamento(Protocol):
    """Porta de armazenamento temporário dos envios."""

    def guardar(
        self, identificador: str, arquivos: Sequence[ArquivoRecebido]
    ) -> list[DocumentoGuardado]: ...

    def documentos(self, identificador: str) -> list[Path]: ...

    def caminho(self, identificador: str, indice: int) -> Path | None: ...

    def descartar(self, identificador: str) -> None: ...

    def expirar(self, idade_maxima: timedelta) -> list[str]: ...


class ArmazenamentoEmDisco:
    """Uma pasta por lote, mantida por um prazo e então apagada.

    Guardar para sempre criaria uma segunda cópia de documento financeiro de
    terceiro sem dono; apagar ao fim do lote impediria a releitura manual, que é
    justamente quando o arquivo ainda faz falta. O prazo é o meio-termo, e o
    operador pode descartar antes pela tela.
    """

    def __init__(
        self,
        raiz: Path,
        tamanho_maximo: int = 25 * 1024 * 1024,
        maximo_de_arquivos: int = 50,
    ) -> None:
        self._raiz = Path(raiz)
        self._tamanho_maximo = tamanho_maximo
        self._maximo_de_arquivos = maximo_de_arquivos

    def guardar(
        self, identificador: str, arquivos: Sequence[ArquivoRecebido]
    ) -> list[DocumentoGuardado]:
        if not arquivos:
            raise ArquivoRejeitadoError("Nenhum arquivo foi enviado.")

        if len(arquivos) > self._maximo_de_arquivos:
            raise ArquivoRejeitadoError(
                f"São no máximo {self._maximo_de_arquivos} arquivos por envio "
                f"(recebidos: {len(arquivos)})."
            )

        pasta = self._pasta(identificador)
        pasta.mkdir(parents=True, exist_ok=True)

        guardados: list[DocumentoGuardado] = []
        try:
            for indice, arquivo in enumerate(arquivos, start=1):
                guardados.append(self._gravar(pasta, indice, arquivo))
        except Exception:
            # Tudo ou nada: meio lote em disco vira relatório incompleto e calado.
            self.descartar(identificador)
            raise

        return guardados

    def documentos(self, identificador: str) -> list[Path]:
        pasta = self._pasta(identificador)
        if not pasta.is_dir():
            return []
        return sorted(caminho for caminho in pasta.iterdir() if caminho.is_file())

    def caminho(self, identificador: str, indice: int) -> Path | None:
        """Arquivo de um documento do lote, ou None se já foi descartado.

        O nome vem do índice, nunca de fora: a leitura fica presa à pasta do lote.
        """
        destino = self._pasta(identificador) / f"{indice:03d}.pdf"
        return destino if destino.is_file() else None

    def descartar(self, identificador: str) -> None:
        shutil.rmtree(self._pasta(identificador), ignore_errors=True)

    def expirar(self, idade_maxima: timedelta) -> list[str]:
        """Apaga os envios mais antigos que o prazo; devolve o que apagou."""
        if not self._raiz.is_dir():
            return []

        limite = time.time() - idade_maxima.total_seconds()
        apagados: list[str] = []

        for pasta in self._raiz.iterdir():
            try:
                if pasta.is_dir() and pasta.stat().st_mtime < limite:
                    shutil.rmtree(pasta, ignore_errors=True)
                    apagados.append(pasta.name)
            except OSError:
                # Pasta que some no meio da varredura não aborta as outras.
                continue

        return apagados

    def _pasta(self, identificador: str) -> Path:
        """Só o identificador que nós geramos entra no caminho.

        Hoje vem de `uuid4()`; a checagem é o que segura o dia em que ele passar
        a vir da URL.
        """
        if not identificador.isalnum():
            raise ArquivoRejeitadoError(f"Identificador de lote inválido: {identificador!r}")
        return self._raiz / identificador

    def _gravar(self, pasta: Path, indice: int, arquivo: ArquivoRecebido) -> DocumentoGuardado:
        nome_original = Path(arquivo.nome or "").name or "sem-nome.pdf"

        if not nome_original.casefold().endswith(".pdf"):
            raise ArquivoRejeitadoError(f"'{nome_original}' não é um PDF.")

        # Nome sequencial, nosso: nada vindo do navegador — '..', barra,
        # dois-pontos, nome reservado do Windows — toca o sistema de arquivos.
        destino = pasta / f"{indice:03d}.pdf"
        primeiro = True

        with destino.open("wb") as saida:
            total = 0
            for pedaco in _pedacos(arquivo.fluxo):
                if primeiro:
                    if not pedaco.startswith(ASSINATURA_PDF):
                        raise ArquivoRejeitadoError(
                            f"'{nome_original}' não tem conteúdo de PDF."
                        )
                    primeiro = False

                total += len(pedaco)
                if total > self._tamanho_maximo:
                    limite_mb = self._tamanho_maximo / (1024 * 1024)
                    raise ArquivoRejeitadoError(
                        f"'{nome_original}' passa do limite de {limite_mb:.0f} MB."
                    )
                saida.write(pedaco)

        if primeiro:  # nenhum pedaço: arquivo vazio
            raise ArquivoRejeitadoError(f"'{nome_original}' está vazio.")

        return DocumentoGuardado(nome_original=nome_original, caminho=destino)


def _pedacos(fluxo: BinaryIO) -> Iterator[bytes]:
    while pedaco := fluxo.read(PEDACO):
        yield pedaco
