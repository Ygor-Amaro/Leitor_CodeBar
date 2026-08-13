"""Configuração da aplicação, com valores vindos do .env e sobrepostos na CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta
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


@dataclass(frozen=True)
class ConfiguracaoWeb:
    """Ajustes do servidor local.

    A leitura pela web é sempre headless: o `cv2.selectROI` abriria a janela na
    máquina do *servidor*. O que não resolve no automático vira pendência.
    """

    host: str = "127.0.0.1"
    """Só a própria máquina. Trocar para 0.0.0.0 expõe boletos na rede local."""

    porta: int = 8000
    dados: Path = Path("data")
    saida: Path = Path("data/output")
    zooms: tuple[float, ...] = field(default=ZOOMS_PADRAO)
    formatos: str = FORMATOS_PADRAO
    tamanho_maximo_mb: int = 25
    maximo_de_arquivos: int = 50
    envios_por_minuto: int = 20
    lotes_no_historico: int = 20

    retencao_horas: int = 24
    """Por quanto tempo os PDFs enviados ficam em disco.

    Não é zero porque a releitura manual precisa do arquivo original. Passado o
    prazo, `ServicoLotes.limpar_expirados` apaga.
    """

    zooms_selecao: tuple[float, ...] = (1.5, 2.0, 3.0, 4.0)
    """Ampliações oferecidas na tela de recorte, da menor para a maior."""

    @property
    def zoom_selecao_padrao(self) -> float:
        return self.zooms_selecao[1] if len(self.zooms_selecao) > 1 else self.zooms_selecao[0]

    @classmethod
    def do_ambiente(cls) -> ConfiguracaoWeb:
        load_dotenv()
        base = Configuracao.do_ambiente()
        return cls(
            host=os.getenv("LEITOR_CB_HOST", "127.0.0.1"),
            porta=_inteiro("LEITOR_CB_PORTA", 8000),
            dados=Path(os.getenv("LEITOR_CB_DADOS", "data")),
            saida=base.saida,
            zooms=base.zooms,
            formatos=base.formatos,
            tamanho_maximo_mb=_inteiro("LEITOR_CB_TAMANHO_MAXIMO_MB", 25),
            maximo_de_arquivos=_inteiro("LEITOR_CB_MAXIMO_ARQUIVOS", 50),
            retencao_horas=_inteiro("LEITOR_CB_RETENCAO_HORAS", 24),
        )

    @property
    def retencao(self) -> timedelta:
        return timedelta(hours=self.retencao_horas)

    @property
    def banco(self) -> Path:
        return self.dados / "leitor_cb.sqlite3"

    @property
    def uploads(self) -> Path:
        return self.dados / "uploads"

    @property
    def tamanho_maximo_bytes(self) -> int:
        return self.tamanho_maximo_mb * 1024 * 1024


def _inteiro(chave: str, padrao: int) -> int:
    """Valor inteiro positivo do ambiente; volta ao padrão se vier lixo.

    Porta zero ou limite negativo derrubariam o boot, e configuração errada não
    deve virar servidor que não sobe.
    """
    try:
        valor = int(os.getenv(chave, ""))
    except ValueError:
        return padrao
    return valor if valor > 0 else padrao


def _zooms_do_ambiente() -> tuple[float, ...]:
    bruto = os.getenv("LEITOR_CB_ZOOMS", "")
    if not bruto.strip():
        return ZOOMS_PADRAO

    try:
        zooms = tuple(float(parte) for parte in bruto.split(",") if parte.strip())
    except ValueError:
        return ZOOMS_PADRAO

    # Zoom <= 0 quebra a renderização de toda página: erro de configuração viraria
    # lote inteiro de pendências.
    return tuple(zoom for zoom in zooms if zoom > 0) or ZOOMS_PADRAO
