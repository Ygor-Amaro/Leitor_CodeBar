"""Saída dos resultados: console durante o processamento e CSV ao final."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ..domain.models import LinhaDigitavel, ResultadoLeitura, StatusLeitura, TipoDocumento

COLUNAS = (
    "arquivo",
    "pagina",
    "tipo",
    "codigo_barras",
    "linha_digitavel",
    "dv_ok",
    "status",
    "observacao",
)


class Exportador(Protocol):
    """Porta de saída. Acrescentar JSON ou banco de dados é implementar isto."""

    def exportar(self, resultados: Sequence[ResultadoLeitura]) -> Path | None: ...


class ExportadorConsole:
    """Imprime no terminal, no formato que o operador já conhece."""

    def imprimir(self, resultado: ResultadoLeitura) -> None:
        """Feedback ao vivo, chamado a cada página processada."""
        prefixo = f"[{resultado.arquivo} p.{resultado.pagina}]"

        if resultado.status is not StatusLeitura.SUCESSO:
            print(f"{prefixo} {resultado.observacao}")
            return

        if resultado.tipo is TipoDocumento.PIX:
            print(f"{prefixo} QR Code (PIX):\n{resultado.linha_digitavel}")
            return

        linha = LinhaDigitavel(resultado.linha_digitavel, resultado.tipo)
        alerta = "" if resultado.dv_ok else "  <-- DV GERAL NAO CONFERE"
        print(f"{prefixo} Linha digitável: {linha.formatada()}{alerta}")

    def exportar(self, resultados: Sequence[ResultadoLeitura]) -> None:
        """Resumo final do lote."""
        total = len(resultados)
        sucessos = sum(1 for r in resultados if r.status is StatusLeitura.SUCESSO)
        atencao = [r for r in resultados if r.exige_atencao]

        print(f"\n{'-' * 60}")
        print(f"Páginas com resultado: {total} | leituras bem-sucedidas: {sucessos}")

        if atencao:
            print(f"Exigem conferência manual: {len(atencao)}")
            for resultado in atencao:
                print(
                    f"  - {resultado.arquivo} p.{resultado.pagina}: "
                    f"{resultado.observacao or resultado.status.value}"
                )
        else:
            print("Nenhuma pendência.")


class ExportadorCsv:
    """Grava o relatório em CSV.

    Separador `;` e encoding `utf-8-sig` para que o Excel em português abra o
    arquivo com duplo clique, sem assistente de importação e sem quebrar acento.
    """

    def __init__(self, diretorio: Path, prefixo: str = "leitura") -> None:
        self._diretorio = Path(diretorio)
        self._prefixo = prefixo

    def exportar(self, resultados: Sequence[ResultadoLeitura]) -> Path:
        self._diretorio.mkdir(parents=True, exist_ok=True)
        destino = self._diretorio / (
            f"{self._prefixo}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        )

        with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(
                arquivo, fieldnames=COLUNAS, delimiter=";", quoting=csv.QUOTE_MINIMAL
            )
            escritor.writeheader()
            for resultado in resultados:
                escritor.writerow(self._linha(resultado))

        return destino

    @staticmethod
    def _linha(resultado: ResultadoLeitura) -> dict[str, str]:
        return {
            "arquivo": resultado.arquivo,
            "pagina": str(resultado.pagina),
            "tipo": resultado.tipo.value if resultado.tipo else "",
            # Prefixo de tabulação impede o Excel de converter o número em
            # notação científica e perder dígitos do código.
            "codigo_barras": _texto_seguro(resultado.codigo_barras),
            "linha_digitavel": _texto_seguro(resultado.linha_digitavel),
            "dv_ok": "" if resultado.dv_ok is None else ("sim" if resultado.dv_ok else "nao"),
            "status": resultado.status.value,
            "observacao": resultado.observacao,
        }


def _texto_seguro(valor: str) -> str:
    """Mantém sequências longas de dígitos como texto ao abrir no Excel."""
    if valor.isdigit():
        return f"\t{valor}"
    return valor
