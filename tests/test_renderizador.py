"""Rasterização de página — o teto de pixels que protege a memória do servidor.

Os PDFs são criados aqui mesmo, em `tmp_path`: nenhum arquivo de exemplo entra no
repositório, e o que se quer exercitar é a *medida* da página, não o conteúdo.
"""

import fitz
import pytest

from leitor_cb.domain.excecoes import DocumentoIlegivelError
from leitor_cb.services.processador import ProcessadorDocumento
from leitor_cb.services.renderizador import PIXELS_MAXIMOS, RenderizadorPdf

A4 = (595, 842)
GIGANTE = (14400, 14400)
"""Maior página que o formato PDF admite — 200 polegadas de lado."""


def pdf(tmp_path, largura: int, altura: int, nome: str = "pagina.pdf"):
    documento = fitz.open()
    documento.new_page(width=largura, height=altura)
    caminho = tmp_path / nome
    documento.save(caminho)
    documento.close()
    return caminho


class DecodificadorMudo:
    """Nunca acha nada: aqui só interessa se a renderização acontece."""

    def decodificar(self, imagem):
        return []


def test_pagina_a4_passa_em_todos_os_zooms(tmp_path):
    """O teto não pode atrapalhar o uso real — A4 no zoom 8 é o pior caso da tela
    de recorte."""
    caminho = pdf(tmp_path, *A4)

    with RenderizadorPdf().abrir(caminho) as documento:
        for zoom in (2.0, 3.0, 4.0, 8.0):
            assert documento.renderizar(0, zoom).size > 0


def test_pagina_gigante_e_barrada_antes_de_alocar(tmp_path):
    """522 bytes de PDF pediriam 2,3 GB no zoom padrão e 37 GB no zoom 8.

    Com o teto de 2 GB do contêiner, sem esta barreira o envio derruba o servidor
    por falta de memória — sem login, de qualquer máquina da rede.
    """
    caminho = pdf(tmp_path, *GIGANTE)
    assert caminho.stat().st_size < 10_000  # o arquivo em si é minúsculo

    with (
        RenderizadorPdf().abrir(caminho) as documento,
        pytest.raises(DocumentoIlegivelError) as erro,
    ):
        documento.renderizar(0, 2.0)

    assert "pixels" in str(erro.value)


def test_pagina_gigante_barrada_tambem_no_zoom_minimo_da_tela(tmp_path):
    caminho = pdf(tmp_path, *GIGANTE)

    with RenderizadorPdf().abrir(caminho) as documento, pytest.raises(DocumentoIlegivelError):
        documento.renderizar(0, 1.5)


def test_o_teto_vale_pela_area_e_nao_pelo_zoom(tmp_path):
    """Zoom baixo numa página enorme estoura; zoom alto numa pequena, não.

    É o que o `validar_zoom` sozinho não pegava: ele limita o multiplicador, e o
    que consome memória é o produto pela medida da página.
    """
    lado = int((PIXELS_MAXIMOS**0.5) * 2)
    caminho = pdf(tmp_path, lado, lado, "larga.pdf")

    with RenderizadorPdf().abrir(caminho) as documento, pytest.raises(DocumentoIlegivelError):
        documento.renderizar(0, 1.0)


def test_pagina_gigante_vira_pendencia_e_nao_derruba_o_lote(tmp_path):
    """O caminho do envio real: a falha precisa virar linha do relatório."""
    caminho = pdf(tmp_path, *GIGANTE)
    processador = ProcessadorDocumento(
        renderizador=RenderizadorPdf(),
        decodificador=DecodificadorMudo(),
        seletor=None,
    )

    (resultado,) = processador.processar(caminho)

    assert resultado.exige_atencao
    assert "pixels" in resultado.observacao
