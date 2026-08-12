"""Regras puras do lote e do recorte — strings e números, sem banco nem imagem."""

from datetime import datetime

import pytest
from conftest import leitura_boleto, leitura_sem_codigo

from leitor_cb.domain import EstadoLote, Lote, Recorte, RecorteInvalidoError, ResumoLote

AGORA = datetime(2026, 8, 10, 9, 30)


def lote(estado: EstadoLote, total: int = 4, processados: int = 0) -> Lote:
    return Lote(
        identificador="abc",
        criado_em=AGORA,
        estado=estado,
        total_documentos=total,
        documentos_processados=processados,
    )


def test_percentual_acompanha_o_processamento():
    assert lote(EstadoLote.PROCESSANDO, total=4, processados=1).percentual == 25


def test_lote_terminado_marca_cem_por_cento():
    assert lote(EstadoLote.CONCLUIDO, total=4, processados=2).percentual == 100


def test_lote_vazio_terminado_nao_trava_a_barra_em_zero():
    """Sem isto, um envio sem documentos deixaria a barra parada para sempre."""
    assert lote(EstadoLote.CONCLUIDO, total=0).percentual == 100


def test_lote_vazio_em_andamento_fica_em_zero():
    assert lote(EstadoLote.PENDENTE, total=0).percentual == 0


@pytest.mark.parametrize(
    "estado, terminado",
    [
        (EstadoLote.PENDENTE, False),
        (EstadoLote.PROCESSANDO, False),
        (EstadoLote.CONCLUIDO, True),
        (EstadoLote.FALHOU, True),
    ],
)
def test_estados_terminais(estado, terminado):
    assert lote(estado).terminado is terminado


def test_resumo_separa_sucesso_de_pendencia():
    resumo = ResumoLote.de(
        [leitura_boleto(), leitura_boleto(dv_ok=False), leitura_sem_codigo()]
    )

    assert (resumo.total, resumo.sucessos, resumo.pendencias) == (3, 2, 2)


def test_recorte_valido_guarda_as_medidas():
    recorte = Recorte(x=10, y=20, largura=100, altura=40, zoom=2.0)

    assert (recorte.x, recorte.largura, recorte.zoom) == (10, 100, 2.0)


@pytest.mark.parametrize(
    "campos",
    [
        {"largura": 0},
        {"altura": 0},
        {"largura": -5},
        {"x": -1},
        {"y": -1},
        {"zoom": 0},
        {"zoom": -2.0},
        {"zoom": 99.0},
    ],
)
def test_recorte_degenerado_e_recusado_no_construtor(campos):
    """Recortar com retângulo inválido devolveria imagem vazia, e o erro
    apareceria disfarçado de 'nenhum código encontrado'."""
    base = {"x": 5, "y": 5, "largura": 50, "altura": 20, "zoom": 2.0}

    with pytest.raises(RecorteInvalidoError):
        Recorte(**{**base, **campos})
