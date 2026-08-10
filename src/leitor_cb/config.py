"""Configuração da aplicação, com valores vindos do .env e sobrepostos na CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv

from .services.decodificador import FORMATOS_PADRAO
from .services.processador import ZOOMS_PADRAO


class ModoLeitura(StrEnum):
    """Como o operador interage com a leitura."""

    AUTOMATICO = "automatico"
    """Varre a página inteira; só abre a janela de recorte se nada for achado."""

    SEM_GUI = "sem_gui"
    """Nunca abre janela — páginas não lidas entram no relatório de pendências."""

    SEMPRE_MANUAL = "sempre_manual"
    """Comportamento do script antigo: recorte manual em toda página."""


@dataclass(frozen=True)
class Configuracao:
    entrada: Path = Path("data/input")
    saida: Path = Path("data/output")
    zooms: tuple[float, ...] = field(default=ZOOMS_PADRAO)
    formatos: str = FORMATOS_PADRAO
    modo: ModoLeitura = ModoLeitura.AUTOMATICO
    gerar_csv: bool = True

    @classmethod
    def do_ambiente(cls) -> Configuracao:
        """Lê o .env, caindo nos padrões quando a variável não existe."""
        load_dotenv()
        return cls(
            entrada=Path(os.getenv("LEITOR_CB_ENTRADA", "data/input")),
            saida=Path(os.getenv("LEITOR_CB_SAIDA", "data/output")),
            zooms=_zooms_do_ambiente(),
            formatos=os.getenv("LEITOR_CB_FORMATOS", FORMATOS_PADRAO),
        )

    @property
    def usa_gui(self) -> bool:
        return self.modo is not ModoLeitura.SEM_GUI

    @property
    def sempre_manual(self) -> bool:
        return self.modo is ModoLeitura.SEMPRE_MANUAL


def _zooms_do_ambiente() -> tuple[float, ...]:
    bruto = os.getenv("LEITOR_CB_ZOOMS", "")
    if not bruto.strip():
        return ZOOMS_PADRAO

    try:
        zooms = tuple(float(parte) for parte in bruto.split(",") if parte.strip())
    except ValueError:
        return ZOOMS_PADRAO

    # Zoom <= 0 quebraria a renderização de toda página, transformando erro de
    # configuração em lote inteiro de pendências.
    return tuple(zoom for zoom in zooms if zoom > 0) or ZOOMS_PADRAO
