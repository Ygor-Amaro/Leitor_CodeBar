"""Ponto de entrada da linha de comando.

Este módulo é a *composition root*: é o único lugar que sabe quais
implementações concretas entram em cada porta do pipeline.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ..config import Configuracao, ModoLeitura
from ..domain.models import ResultadoLeitura
from ..services.decodificador import DecodificadorZxing
from ..services.exportador import ExportadorConsole, ExportadorCsv
from ..services.processador import ProcessadorDocumento
from ..services.renderizador import RenderizadorPdf

CODIGO_SUCESSO = 0
CODIGO_PENDENCIAS = 1
CODIGO_ERRO_USO = 2


def zoom_positivo(valor: str) -> float:
    """Valida `--zoom` no parse: argparse já sai com o código de erro de uso."""
    try:
        zoom = float(valor)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{valor}' não é um número.") from None

    if zoom <= 0:
        raise argparse.ArgumentTypeError(f"o zoom deve ser maior que zero (recebido: {zoom}).")

    return zoom


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="leitor-cb",
        description=(
            "Lê códigos de barras (FEBRABAN) e QR Codes PIX em PDFs de pagamento "
            "e gera as linhas digitáveis em CSV."
        ),
    )
    parser.add_argument(
        "--entrada",
        type=Path,
        help="Arquivo PDF ou pasta com PDFs (padrão: data/input).",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        help="Pasta onde o CSV será gravado (padrão: data/output).",
    )
    parser.add_argument(
        "--zoom",
        type=zoom_positivo,
        nargs="+",
        metavar="Z",
        help="Zooms de renderização tentados em ordem (padrão: 2.0 3.0).",
    )

    modo = parser.add_mutually_exclusive_group()
    modo.add_argument(
        "--sem-gui",
        action="store_true",
        help="Não abre janelas; páginas não lidas viram pendência no relatório.",
    )
    modo.add_argument(
        "--sempre-manual",
        action="store_true",
        help="Pede recorte manual em toda página (comportamento do script antigo).",
    )

    parser.add_argument(
        "--sem-csv",
        action="store_true",
        help="Só imprime no terminal, sem gerar arquivo.",
    )
    return parser


def configuracao_de(args: argparse.Namespace) -> Configuracao:
    """Aplica os argumentos da CLI por cima do que veio do .env."""
    base = Configuracao.do_ambiente()

    if args.sem_gui:
        modo = ModoLeitura.SEM_GUI
    elif args.sempre_manual:
        modo = ModoLeitura.SEMPRE_MANUAL
    else:
        modo = ModoLeitura.AUTOMATICO

    return Configuracao(
        entrada=args.entrada or base.entrada,
        saida=args.saida or base.saida,
        zooms=tuple(args.zoom) if args.zoom else base.zooms,
        formatos=base.formatos,
        modo=modo,
        gerar_csv=not args.sem_csv,
    )


def montar_processador(config: Configuracao) -> ProcessadorDocumento:
    """Liga as implementações concretas às portas do pipeline."""
    seletor = None
    if config.usa_gui:
        # Importado aqui para que o modo headless não exija GUI disponível.
        from .seletor_roi import SeletorRoiOpenCv

        seletor = SeletorRoiOpenCv()

    return ProcessadorDocumento(
        renderizador=RenderizadorPdf(),
        decodificador=DecodificadorZxing(config.formatos),
        seletor=seletor,
        zooms=config.zooms,
        sempre_manual=config.sempre_manual,
    )


def _proteger_console() -> None:
    """Impede que um acento derrube o lote em consoles Windows não-UTF-8.

    Mantém a codificação nativa do terminal e só troca o tratamento de erro,
    para não introduzir mojibake onde hoje a exibição está correta.
    """
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(errors="replace")


def localizar_pdfs(entrada: Path) -> list[Path]:
    if entrada.is_file():
        return [entrada]
    if entrada.is_dir():
        return sorted(
            caminho
            for caminho in entrada.iterdir()
            if caminho.is_file() and caminho.suffix.casefold() == ".pdf"
        )
    return []


def main(argv: Sequence[str] | None = None) -> int:
    _proteger_console()

    args = construir_parser().parse_args(argv)
    config = configuracao_de(args)

    if not config.entrada.exists():
        print(f"Entrada não encontrada: {config.entrada}", file=sys.stderr)
        return CODIGO_ERRO_USO

    documentos = localizar_pdfs(config.entrada)
    if not documentos:
        print(f"Nenhum PDF encontrado em: {config.entrada}", file=sys.stderr)
        return CODIGO_ERRO_USO

    processador = montar_processador(config)
    console = ExportadorConsole()

    print(f"{len(documentos)} documento(s) a processar. Modo: {config.modo.value}\n")

    resultados: list[ResultadoLeitura] = []
    for documento in documentos:
        resultados.extend(processador.processar(documento, ao_processar=console.imprimir))

    console.exportar(resultados)

    if config.gerar_csv:
        destino = ExportadorCsv(config.saida).exportar(resultados)
        print(f"\nRelatório gravado em: {destino}")

    return CODIGO_PENDENCIAS if any(r.exige_atencao for r in resultados) else CODIGO_SUCESSO


if __name__ == "__main__":
    raise SystemExit(main())
