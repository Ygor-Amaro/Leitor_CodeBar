"""Casos de mesa dos algoritmos de dígito verificador."""

import pytest

from leitor_cb.domain.digito_verificador import (
    Modulo10,
    Modulo11Arrecadacao,
    Modulo11Cobranca,
)

# Blocos extraídos de um boleto real (Itaú) cuja linha digitável é conhecida:
# 34191.09503 00320.351026 45894.650006 6 15230000040629
CASOS_MODULO_10 = [
    ("341910950", "3"),
    ("0032035102", "6"),
    ("4589465000", "6"),
]


class TestModulo10:
    @pytest.mark.parametrize("bloco, esperado", CASOS_MODULO_10)
    def test_blocos_de_boleto_real(self, bloco, esperado):
        assert Modulo10().calcular(bloco) == esperado

    def test_resto_zero_gera_dv_zero(self):
        assert Modulo10().calcular("0000000000") == "0"

    def test_produto_maior_que_nove_tem_algarismos_somados(self):
        # 9 * 2 = 18 -> 1 + 8 = 9 -> resto 9 -> DV 1
        assert Modulo10().calcular("9") == "1"


class TestModulo11Arrecadacao:
    def test_dv_onze_vira_zero(self):
        # soma 0 -> resto 0 -> DV 11 -> 0
        assert Modulo11Arrecadacao().calcular("00000000000") == "0"

    def test_dv_dez_vira_zero(self):
        # 6 * 2 = 12 -> resto 1 -> DV 10 -> 0
        assert Modulo11Arrecadacao().calcular("00000000006") == "0"

    def test_dv_normal(self):
        # 1 * 2 = 2 -> resto 2 -> DV 9
        assert Modulo11Arrecadacao().calcular("00000000001") == "9"


class TestModulo11Cobranca:
    """Difere do de arrecadação apenas na exceção: 0, 10 e 11 viram 1."""

    def test_dv_onze_vira_um(self):
        assert Modulo11Cobranca().calcular("00000000000") == "1"

    def test_dv_dez_vira_um(self):
        assert Modulo11Cobranca().calcular("00000000006") == "1"

    def test_dv_normal_coincide_com_arrecadacao(self):
        assert Modulo11Cobranca().calcular("00000000001") == "9"
