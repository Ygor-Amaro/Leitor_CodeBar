"""Pipeline completo com dublês — sem PDF, sem janela gráfica."""

from contextlib import contextmanager

import numpy as np
import pytest

from leitor_cb.domain import DocumentoIlegivelError, StatusLeitura, TipoDocumento
from leitor_cb.services import CodigoDetectado, ProcessadorDocumento

BOLETO = "34196152300000406291095000320351024589465000"
LINHA_BOLETO = "34191095030032035102645894650006615230000040629"
PIX = "00020126580014BR.GOV.BCB.PIX0136chave-exemplo5204000053039865802BR"


class DocumentoFalso:
    def __init__(self, total_paginas: int = 1) -> None:
        self.total_paginas = total_paginas
        self.renderizacoes: list[tuple[int, float]] = []

    def renderizar(self, pagina: int, zoom: float) -> np.ndarray:
        self.renderizacoes.append((pagina, zoom))
        return np.zeros((10, 10, 3), dtype=np.uint8)


class RenderizadorFalso:
    def __init__(self, documento: DocumentoFalso) -> None:
        self.documento = documento

    @contextmanager
    def abrir(self, caminho):
        yield self.documento


class RenderizadorQuebrado:
    @contextmanager
    def abrir(self, caminho):
        raise DocumentoIlegivelError("arquivo corrompido")
        yield  # pragma: no cover


class DecodificadorFalso:
    """Devolve uma resposta diferente a cada chamada."""

    def __init__(self, *respostas: list[CodigoDetectado]) -> None:
        self.respostas = list(respostas)
        self.chamadas = 0

    def decodificar(self, imagem):
        self.chamadas += 1
        if not self.respostas:
            return []
        return self.respostas.pop(0)


class SeletorFalso:
    def __init__(self, recorte: np.ndarray | None) -> None:
        self._recorte = recorte
        self.chamadas = 0

    def selecionar(self, imagem, titulo):
        self.chamadas += 1
        return self._recorte


def itf(texto: str) -> CodigoDetectado:
    return CodigoDetectado(texto=texto, formato="ITF")


def qrcode(texto: str) -> CodigoDetectado:
    return CodigoDetectado(texto=texto, formato="QR Code")


def montar(decodificador, seletor=None, **kwargs) -> ProcessadorDocumento:
    return ProcessadorDocumento(
        renderizador=RenderizadorFalso(DocumentoFalso()),
        decodificador=decodificador,
        seletor=seletor,
        **kwargs,
    )


class TestLeituraAutomatica:
    def test_boleto_vira_linha_digitavel(self):
        processador = montar(DecodificadorFalso([itf(BOLETO)]))

        (resultado,) = processador.processar("lote.pdf")

        assert resultado.status is StatusLeitura.SUCESSO
        assert resultado.tipo is TipoDocumento.COBRANCA
        assert resultado.linha_digitavel == LINHA_BOLETO
        assert resultado.dv_ok is True
        assert resultado.pagina == 1
        assert resultado.arquivo == "lote.pdf"

    def test_qrcode_vira_payload_pix(self):
        processador = montar(DecodificadorFalso([qrcode(PIX)]))

        (resultado,) = processador.processar("lote.pdf")

        assert resultado.tipo is TipoDocumento.PIX
        assert resultado.linha_digitavel == PIX
        assert resultado.codigo_barras == ""

    def test_dv_geral_errado_e_sinalizado_mas_nao_descartado(self):
        corrompido = BOLETO[:20] + "7" + BOLETO[21:]
        processador = montar(DecodificadorFalso([itf(corrompido)]))

        (resultado,) = processador.processar("lote.pdf")

        assert resultado.status is StatusLeitura.SUCESSO
        assert resultado.dv_ok is False
        assert resultado.exige_atencao
        assert resultado.linha_digitavel  # a linha continua disponível

    def test_codigo_fora_do_padrao_nao_levanta_excecao(self):
        processador = montar(DecodificadorFalso([itf("123456")]))

        (resultado,) = processador.processar("lote.pdf")

        assert resultado.status is StatusLeitura.CODIGO_INVALIDO
        assert resultado.codigo_barras == "123456"
        assert resultado.linha_digitavel == ""

    def test_ruido_e_descartado_quando_ha_boleto_na_pagina(self):
        processador = montar(DecodificadorFalso([itf("99887766"), itf(BOLETO)]))

        resultados = processador.processar("lote.pdf")

        assert len(resultados) == 1
        assert resultados[0].codigo_barras == BOLETO

    def test_varios_boletos_na_mesma_pagina_geram_varias_linhas(self):
        outro = "8" + BOLETO[1:]
        processador = montar(DecodificadorFalso([itf(BOLETO), itf(outro)]))

        resultados = processador.processar("lote.pdf")

        assert [r.tipo for r in resultados] == [
            TipoDocumento.COBRANCA,
            TipoDocumento.ARRECADACAO,
        ]


class TestZoomProgressivo:
    def test_ruido_no_primeiro_zoom_nao_interrompe_a_escalada(self):
        """Ler um ITF qualquer não é ter achado o boleto.

        Nota fiscal costuma trazer código de rastreio legível no zoom baixo; se
        a escalada parasse nele, o boleto que só sai no zoom alto se perderia.
        """
        renderizador = RenderizadorFalso(DocumentoFalso())
        processador = ProcessadorDocumento(
            renderizador=renderizador,
            decodificador=DecodificadorFalso([itf("99887766")], [itf(BOLETO)]),
            zooms=(2.0, 3.0),
        )

        (resultado,) = processador.processar("lote.pdf")

        assert renderizador.documento.renderizacoes == [(0, 2.0), (0, 3.0)]
        assert resultado.status is StatusLeitura.SUCESSO
        assert resultado.codigo_barras == BOLETO

    def test_ruido_em_todos_os_zooms_aciona_o_recorte_manual(self):
        seletor = SeletorFalso(np.zeros((5, 5, 3), dtype=np.uint8))
        processador = montar(
            DecodificadorFalso([itf("99887766")], [itf("99887766")], [itf(BOLETO)]),
            seletor=seletor,
            zooms=(2.0, 3.0),
        )

        (resultado,) = processador.processar("lote.pdf")

        assert seletor.chamadas == 1
        assert resultado.codigo_barras == BOLETO

    def test_ruido_vira_pendencia_quando_nada_mais_aparece(self):
        """O ruído não some do relatório: vira linha sinalizada, não silêncio."""
        processador = montar(DecodificadorFalso([itf("99887766")]), zooms=(2.0, 3.0))

        (resultado,) = processador.processar("lote.pdf")

        assert resultado.status is StatusLeitura.CODIGO_INVALIDO
        assert resultado.codigo_barras == "99887766"
        assert resultado.exige_atencao

    def test_para_no_primeiro_zoom_que_decodifica(self):
        renderizador = RenderizadorFalso(DocumentoFalso())
        processador = ProcessadorDocumento(
            renderizador=renderizador,
            decodificador=DecodificadorFalso([itf(BOLETO)]),
            zooms=(2.0, 3.0),
        )

        processador.processar("lote.pdf")

        assert renderizador.documento.renderizacoes == [(0, 2.0)]

    def test_tenta_zoom_maior_quando_nada_e_encontrado(self):
        renderizador = RenderizadorFalso(DocumentoFalso())
        processador = ProcessadorDocumento(
            renderizador=renderizador,
            decodificador=DecodificadorFalso([], [itf(BOLETO)]),
            zooms=(2.0, 3.0),
        )

        (resultado,) = processador.processar("lote.pdf")

        assert renderizador.documento.renderizacoes == [(0, 2.0), (0, 3.0)]
        assert resultado.status is StatusLeitura.SUCESSO


class TestRecorteManual:
    def test_sem_seletor_a_pagina_vira_pendencia(self):
        processador = montar(DecodificadorFalso())

        (resultado,) = processador.processar("lote.pdf")

        assert resultado.status is StatusLeitura.SEM_CODIGO
        assert resultado.exige_atencao

    def test_seletor_e_acionado_so_apos_falha_automatica(self):
        seletor = SeletorFalso(np.zeros((5, 5, 3), dtype=np.uint8))
        processador = montar(
            DecodificadorFalso([], [], [itf(BOLETO)]), seletor=seletor
        )

        (resultado,) = processador.processar("lote.pdf")

        assert seletor.chamadas == 1
        assert resultado.status is StatusLeitura.SUCESSO

    def test_operador_pode_pular_a_pagina(self):
        seletor = SeletorFalso(None)
        processador = montar(DecodificadorFalso(), seletor=seletor)

        (resultado,) = processador.processar("lote.pdf")

        assert resultado.status is StatusLeitura.SEM_CODIGO

    def test_modo_sempre_manual_nao_tenta_automatico(self):
        seletor = SeletorFalso(np.zeros((5, 5, 3), dtype=np.uint8))
        decodificador = DecodificadorFalso([itf(BOLETO)])
        processador = montar(decodificador, seletor=seletor, sempre_manual=True)

        processador.processar("lote.pdf")

        assert seletor.chamadas == 1
        assert decodificador.chamadas == 1  # só a leitura do recorte


class TestFalhas:
    def test_arquivo_ilegivel_vira_resultado_de_erro(self):
        processador = ProcessadorDocumento(
            renderizador=RenderizadorQuebrado(),
            decodificador=DecodificadorFalso(),
        )

        (resultado,) = processador.processar("quebrado.pdf")

        assert resultado.status is StatusLeitura.ERRO
        assert "corrompido" in resultado.observacao

    def test_pagina_com_falha_nao_interrompe_o_documento(self):
        class DecodificadorInstavel:
            def __init__(self):
                self.chamadas = 0

            def decodificar(self, imagem):
                self.chamadas += 1
                if self.chamadas == 1:
                    raise RuntimeError("falha na leitura óptica")
                return [itf(BOLETO)]

        processador = ProcessadorDocumento(
            renderizador=RenderizadorFalso(DocumentoFalso(total_paginas=2)),
            decodificador=DecodificadorInstavel(),
            zooms=(2.0,),
        )

        primeiro, segundo = processador.processar("lote.pdf")

        assert primeiro.status is StatusLeitura.ERRO
        assert segundo.status is StatusLeitura.SUCESSO


class TestObservador:
    def test_resultados_sao_notificados_ao_vivo(self):
        vistos = []
        processador = ProcessadorDocumento(
            renderizador=RenderizadorFalso(DocumentoFalso(total_paginas=2)),
            decodificador=DecodificadorFalso([itf(BOLETO)], [qrcode(PIX)]),
            zooms=(2.0,),
        )

        resultados = processador.processar("lote.pdf", ao_processar=vistos.append)

        assert vistos == resultados
        assert len(vistos) == 2


@pytest.mark.parametrize(
    "formato, esperado",
    [("QR Code", True), ("QRCode", True), ("qrcode", True), ("ITF", False)],
)
def test_deteccao_de_qrcode_ignora_espacos_e_caixa(formato, esperado):
    assert CodigoDetectado(texto="x", formato=formato).eh_qrcode is esperado
