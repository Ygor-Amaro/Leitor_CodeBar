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

# O Excel trata como fórmula toda célula iniciada por estes caracteres. TAB e CR
# entram porque o Excel os ignora antes de decidir, servindo de disfarce.
INICIADORES_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r")


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
        # O motivo vem pronto do domínio: DV divergente e identificador de valor
        # fora do padrão são alertas diferentes e o operador precisa saber qual.
        alerta = "" if resultado.dv_ok else f"  <-- {resultado.observacao}"
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
        destino = self._caminho_livre()

        with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
            # QUOTE_ALL para que o prefixo de tabulação chegue íntegro ao Excel:
            # sem aspas, o TAB fica solto no arquivo e a proteção não é confiável.
            escritor = csv.DictWriter(
                arquivo, fieldnames=COLUNAS, delimiter=";", quoting=csv.QUOTE_ALL
            )
            escritor.writeheader()
            for resultado in resultados:
                escritor.writerow(self._linha(resultado))

        return destino

    def _caminho_livre(self) -> Path:
        """Nome ainda não usado. O carimbo tem resolução de segundos, então dois
        lotes seguidos colidiriam e o primeiro relatório se perderia calado."""
        carimbo = f"{datetime.now():%Y%m%d_%H%M%S}"
        destino = self._diretorio / f"{self._prefixo}_{carimbo}.csv"

        contador = 2
        while destino.exists():
            destino = self._diretorio / f"{self._prefixo}_{carimbo}_{contador}.csv"
            contador += 1

        return destino

    @staticmethod
    def _linha(resultado: ResultadoLeitura) -> dict[str, str]:
        return {
            "arquivo": _texto_seguro(resultado.arquivo),
            "pagina": str(resultado.pagina),
            "tipo": resultado.tipo.value if resultado.tipo else "",
            "codigo_barras": _texto_seguro(resultado.codigo_barras),
            "linha_digitavel": _texto_seguro(resultado.linha_digitavel),
            "dv_ok": "" if resultado.dv_ok is None else ("sim" if resultado.dv_ok else "nao"),
            "status": resultado.status.value,
            "observacao": _texto_seguro(resultado.observacao),
        }


def _texto_seguro(valor: str) -> str:
    """Deixa o valor inofensivo para o Excel.

    Dois riscos, porque o CSV é feito para ser aberto com duplo clique: número
    longo virar notação científica (some dígito do código) e texto virar fórmula
    viva. O conteúdo vem de dentro do PDF — payload de PIX, nome de arquivo,
    leitura falha — e portanto não é confiável.
    """
    if valor.isdigit():
        return f"\t{valor}"
    if valor.startswith(INICIADORES_DE_FORMULA):
        # Apóstrofo é a neutralização que o Excel entende; fica visível na
        # célula, o que também serve de aviso de que o conteúdo era estranho.
        return f"'{valor}"
    return valor
