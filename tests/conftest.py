"""Dublês compartilhados pelos testes da camada web.

Nenhum teste abre PDF de verdade nem sobe thread: o processador é falso e o
executor roda o job na hora, o que torna o fluxo do lote determinístico.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Executor, Future
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from leitor_cb.domain import Recorte, ResultadoLeitura, StatusLeitura, TipoDocumento

PDF_FALSO = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
"""Bytes suficientes para passar na triagem do armazenamento."""

BOLETO = "34196152300000406291095000320351024589465000"
LINHA_BOLETO = "34191095030032035102645894650006615230000040629"


class ExecutorImediato(Executor):
    """Executa o job na própria chamada de `submit`.

    Com ele, logo depois do envio o lote já está concluído — o teste não precisa
    esperar thread nem dormir.
    """

    def submit(self, fn: Callable, /, *args, **kwargs) -> Future:  # type: ignore[override]
        futuro: Future = Future()
        try:
            futuro.set_result(fn(*args, **kwargs))
        except BaseException as erro:  # noqa: BLE001 - espelha o ThreadPoolExecutor
            futuro.set_exception(erro)
        return futuro


class ExecutorParado(Executor):
    """Aceita o job e não roda nada — deixa o lote parado em 'na fila'.

    É como se testa a tela de progresso: com o executor imediato o lote já
    nasceria concluído e o estado intermediário nunca apareceria. Serve também
    para simular o lote que o processo anterior deixou pela metade.
    """

    def submit(self, fn: Callable, /, *args, **kwargs) -> Future:  # type: ignore[override]
        return Future()


class ProcessadorFalso:
    """Responde listas fixas de leituras, ignorando o arquivo.

    Cobre as duas entradas do pipeline: a varredura automática (`processar`) e a
    releitura de uma página (`renderizar_pagina` + `ler_area`).
    """

    def __init__(
        self,
        resultados: Sequence[ResultadoLeitura] | None = None,
        releitura: Sequence[ResultadoLeitura] | None = None,
        total_paginas: int = 1,
        zoom_minimo: float | None = None,
    ) -> None:
        self._resultados = list(resultados if resultados is not None else [leitura_boleto()])
        self._releitura = list(releitura if releitura is not None else [leitura_boleto()])
        self._total_paginas = total_paginas

        # Abaixo deste zoom a releitura não acha nada — imita o boleto cujas
        # barras finas só resolvem a partir de certa ampliação.
        self._zoom_minimo = zoom_minimo
        self._ultimo_zoom = 0.0

        self.processados: list[Path] = []
        self.renderizacoes: list[tuple[Path, int, float]] = []
        self.areas: list[Recorte | None] = []

    def processar(self, caminho: Path, ao_processar=None) -> list[ResultadoLeitura]:
        self.processados.append(Path(caminho))
        return list(self._resultados)

    def total_de_paginas(self, caminho: Path) -> int:
        return self._total_paginas

    def renderizar_pagina(self, caminho: Path, pagina: int, zoom: float) -> np.ndarray:
        self.renderizacoes.append((Path(caminho), pagina, zoom))
        self._ultimo_zoom = zoom
        return np.zeros((120, 90, 3), dtype=np.uint8)

    def ler_area(
        self,
        arquivo: str,
        pagina: int,
        imagem: np.ndarray,
        recorte: Recorte | None = None,
    ) -> list[ResultadoLeitura]:
        self.areas.append(recorte)

        if self._zoom_minimo is not None and self._ultimo_zoom < self._zoom_minimo:
            return [leitura_sem_codigo(arquivo, pagina)]

        return [
            replace(resultado, arquivo=arquivo, pagina=pagina)
            for resultado in self._releitura
        ]


class ProcessadorQuebrado:
    """Estoura no meio do lote — usado para verificar o estado `falhou`."""

    def processar(self, caminho: Path, ao_processar=None) -> list[ResultadoLeitura]:
        raise RuntimeError("PyMuPDF explodiu")


def leitura_boleto(arquivo: str = "origem.pdf", dv_ok: bool = True) -> ResultadoLeitura:
    return ResultadoLeitura(
        arquivo=arquivo,
        pagina=1,
        status=StatusLeitura.SUCESSO,
        tipo=TipoDocumento.COBRANCA,
        codigo_barras=BOLETO,
        linha_digitavel=LINHA_BOLETO,
        dv_ok=dv_ok,
        observacao="" if dv_ok else "DV geral não confere — conferir manualmente",
    )


def leitura_sem_codigo(arquivo: str = "origem.pdf", pagina: int = 2) -> ResultadoLeitura:
    return ResultadoLeitura(
        arquivo=arquivo,
        pagina=pagina,
        status=StatusLeitura.SEM_CODIGO,
        observacao="Nenhum código encontrado na página",
    )


@pytest.fixture
def executor() -> ExecutorImediato:
    return ExecutorImediato()
