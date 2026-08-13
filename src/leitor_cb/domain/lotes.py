"""O lote: um envio de documentos processado de uma vez.

Entidade da web — a CLI processa e esquece, a web precisa lembrar o que foi
enviado, em que pé está e o que saiu. Continua sendo domínio puro: nenhuma
importação de banco, disco ou HTTP.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .excecoes import RecorteInvalidoError
from .models import ResultadoLeitura, StatusLeitura

ZOOM_MAXIMO = 8.0
"""Acima disso a página vira uma imagem de dezenas de MB sem ganhar nitidez."""


class EstadoLote(StrEnum):
    PENDENTE = "pendente"
    """Documentos recebidos, ainda na fila."""

    PROCESSANDO = "processando"
    """Worker rodando; o relatório ainda não existe."""

    CONCLUIDO = "concluido"
    """Terminou. Pode ter pendências — concluído não quer dizer sem problema."""

    FALHOU = "falhou"
    """O lote inteiro morreu (disco cheio, banco fora). Casos de um arquivo
    ruim não chegam aqui: viram linha de erro no relatório."""


@dataclass(frozen=True)
class Lote:
    """Um envio. Imutável: o worker publica um novo estado via `dataclasses.replace`."""

    identificador: str
    criado_em: datetime
    estado: EstadoLote
    total_documentos: int
    documentos_processados: int = 0
    nome_csv: str = ""
    observacao: str = ""

    @property
    def terminado(self) -> bool:
        return self.estado in (EstadoLote.CONCLUIDO, EstadoLote.FALHOU)

    @property
    def percentual(self) -> int:
        """Progresso da barra, de 0 a 100.

        Terminado é 100 mesmo sem documentos: senão um envio vazio deixaria a
        barra parada em zero para sempre.
        """
        if self.terminado:
            return 100
        if self.total_documentos <= 0:
            return 0
        proporcao = self.documentos_processados / self.total_documentos
        return min(100, max(0, round(proporcao * 100)))


def validar_zoom(zoom: float) -> float:
    """Zoom aceitável para rasterizar uma página.

    Zero ou negativo quebra a renderização; alto demais gera dezenas de MB de
    imagem sem ganhar legibilidade.
    """
    if not 0 < zoom <= ZOOM_MAXIMO:
        raise RecorteInvalidoError(
            f"Zoom fora do intervalo aceito, entre 0 e {ZOOM_MAXIMO} "
            f"(recebido: {zoom})."
        )
    return zoom


@dataclass(frozen=True)
class DocumentoDoLote:
    """Um dos arquivos enviados. O índice é o que o identifica em disco
    (`001.pdf`); o nome de origem é só rótulo, e vem de fora."""

    indice: int
    nome_original: str


@dataclass(frozen=True)
class LeituraDoLote:
    """Uma leitura junto da origem dela.

    O nome do arquivo não identifica o envio — dois anexos podem repeti-lo. É o
    índice que deixa a tela reabrir a página certa para o recorte manual.
    """

    documento_indice: int
    resultado: ResultadoLeitura


@dataclass(frozen=True)
class Recorte:
    """Área marcada pelo operador na imagem da página, em pixels.

    O zoom viaja junto porque as coordenadas só valem na página rasterizada
    *naquela* ampliação. Validação no construtor, como em `CodigoBarras`: um
    retângulo degenerado recortaria imagem vazia e o erro só apareceria lá na
    frente, disfarçado de "nenhum código encontrado".
    """

    x: int
    y: int
    largura: int
    altura: int
    zoom: float

    def __post_init__(self) -> None:
        if self.largura <= 0 or self.altura <= 0:
            raise RecorteInvalidoError(
                f"A área marcada precisa ter largura e altura maiores que zero "
                f"(recebido: {self.largura}x{self.altura})."
            )
        if self.x < 0 or self.y < 0:
            raise RecorteInvalidoError(
                f"A área marcada começa fora da página ({self.x}, {self.y})."
            )
        validar_zoom(self.zoom)


@dataclass(frozen=True)
class ResumoLote:
    """Contagens do relatório, do jeito que o operador olha: quantas linhas
    saíram, quantas ele ainda precisa conferir."""

    total: int = 0
    sucessos: int = 0
    pendencias: int = 0

    @classmethod
    def de(cls, resultados: Sequence[ResultadoLeitura]) -> ResumoLote:
        return cls(
            total=len(resultados),
            sucessos=sum(1 for r in resultados if r.status is StatusLeitura.SUCESSO),
            pendencias=sum(1 for r in resultados if r.exige_atencao),
        )
