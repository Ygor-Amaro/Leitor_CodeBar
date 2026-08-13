"""Formato JSON da API.

Tradução: o domínio não ganha decorador de serialização nem campo que só existe
por causa de HTTP. Quem muda o contrato mexe aqui, não em `domain/`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from ...domain.lotes import LeituraDoLote, Lote, ResumoLote
from ...domain.models import ResultadoLeitura


class ResumoResposta(BaseModel):
    total: int = 0
    sucessos: int = 0
    pendencias: int = 0

    @classmethod
    def de(cls, resumo: ResumoLote) -> ResumoResposta:
        return cls(
            total=resumo.total, sucessos=resumo.sucessos, pendencias=resumo.pendencias
        )


class LoteResposta(BaseModel):
    identificador: str
    criado_em: datetime
    estado: str
    total_documentos: int
    documentos_processados: int
    percentual: int
    terminado: bool
    observacao: str = ""
    resumo: ResumoResposta = Field(default_factory=ResumoResposta)

    @classmethod
    def de(cls, lote: Lote, resumo: ResumoLote | None = None) -> LoteResposta:
        return cls(
            identificador=lote.identificador,
            criado_em=lote.criado_em,
            estado=lote.estado.value,
            total_documentos=lote.total_documentos,
            documentos_processados=lote.documentos_processados,
            percentual=lote.percentual,
            terminado=lote.terminado,
            observacao=lote.observacao,
            resumo=ResumoResposta.de(resumo or ResumoLote()),
        )


class RecortePedido(BaseModel):
    """Área marcada na tela, em pixels da página renderizada naquele zoom."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    largura: int = Field(gt=0)
    altura: int = Field(gt=0)
    zoom: float = Field(gt=0, le=8)


class ResultadoResposta(BaseModel):
    documento_indice: int = 1
    arquivo: str
    pagina: int
    status: str
    tipo: str | None = None
    codigo_barras: str = ""
    linha_digitavel: str = ""

    linha_formatada: str = ""
    """Com a máscara, para ler na tela. A crua é `linha_digitavel`, que é a que
    se cola no internet banking."""

    dv_ok: bool | None = None
    observacao: str = ""
    exige_atencao: bool = False

    @classmethod
    def de_leitura(cls, leitura: LeituraDoLote) -> ResultadoResposta:
        return cls.de(leitura.resultado, leitura.documento_indice)

    @classmethod
    def de(cls, resultado: ResultadoLeitura, documento_indice: int = 1) -> ResultadoResposta:
        return cls(
            documento_indice=documento_indice,
            arquivo=resultado.arquivo,
            pagina=resultado.pagina,
            status=resultado.status.value,
            tipo=resultado.tipo.value if resultado.tipo else None,
            codigo_barras=resultado.codigo_barras,
            linha_digitavel=resultado.linha_digitavel,
            linha_formatada=resultado.linha_formatada,
            dv_ok=resultado.dv_ok,
            observacao=resultado.observacao,
            exige_atencao=resultado.exige_atencao,
        )


class LoteDetalhado(BaseModel):
    lote: LoteResposta
    resultados: list[ResultadoResposta] = Field(default_factory=list)

    arquivos_disponiveis: bool = False
    """Se os PDFs ainda estão em disco — sem eles não há releitura manual."""

    @classmethod
    def de(
        cls,
        lote: Lote,
        resumo: ResumoLote,
        leituras: Sequence[LeituraDoLote],
        arquivos_disponiveis: bool = False,
    ) -> LoteDetalhado:
        return cls(
            lote=LoteResposta.de(lote, resumo),
            resultados=[ResultadoResposta.de_leitura(leitura) for leitura in leituras],
            arquivos_disponiveis=arquivos_disponiveis,
        )


class ErroResposta(BaseModel):
    erro: str
    detalhe: str = ""
