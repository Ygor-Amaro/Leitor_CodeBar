"""Conversão de código de barras em linha digitável e validação do código."""

import pytest

from leitor_cb.domain import (
    CodigoBarras,
    CodigoInvalidoError,
    FabricaConversor,
    Modulo10,
    Modulo11Arrecadacao,
    TipoDocumento,
)

# Boleto real: o código de 44 dígitos e a linha digitável de 47 correspondente.
BOLETO_COBRANCA = "34196152300000406291095000320351024589465000"
LINHA_COBRANCA = "34191095030032035102645894650006615230000040629"
LINHA_COBRANCA_FORMATADA = "34191.09503 00320.351026 45894.650006 6 15230000040629"


@pytest.fixture
def fabrica():
    return FabricaConversor()


class TestCodigoBarras:
    def test_rejeita_tamanho_diferente_de_44(self):
        with pytest.raises(CodigoInvalidoError, match="44 dígitos"):
            CodigoBarras("123")

    def test_rejeita_conteudo_nao_numerico(self):
        with pytest.raises(CodigoInvalidoError):
            CodigoBarras("A" + BOLETO_COBRANCA[1:])

    def test_identifica_cobranca(self):
        assert CodigoBarras(BOLETO_COBRANCA).tipo is TipoDocumento.COBRANCA

    def test_identifica_arrecadacao_pelo_primeiro_digito(self):
        codigo = CodigoBarras("8" + BOLETO_COBRANCA[1:])
        assert codigo.tipo is TipoDocumento.ARRECADACAO

    def test_dv_geral_de_boleto_real_confere(self):
        assert CodigoBarras(BOLETO_COBRANCA).dv_geral_confere() is True

    def test_dv_geral_acusa_digito_trocado(self):
        # Troca um dígito do campo livre, simulando erro de leitura óptica.
        corrompido = BOLETO_COBRANCA[:20] + "7" + BOLETO_COBRANCA[21:]
        assert CodigoBarras(corrompido).dv_geral_confere() is False


class TestConversorCobranca:
    def test_gera_linha_de_47_digitos(self, fabrica):
        linha = fabrica.converter(CodigoBarras(BOLETO_COBRANCA))
        assert linha.digitos == LINHA_COBRANCA
        assert len(linha.digitos) == 47

    def test_mascara_de_exibicao(self, fabrica):
        linha = fabrica.converter(CodigoBarras(BOLETO_COBRANCA))
        assert linha.formatada() == LINHA_COBRANCA_FORMATADA

    def test_mascara_preserva_os_digitos(self, fabrica):
        linha = fabrica.converter(CodigoBarras(BOLETO_COBRANCA))
        somente_digitos = "".join(c for c in linha.formatada() if c.isdigit())
        assert somente_digitos == linha.digitos


class TestConversorArrecadacao:
    """Guias: 4 blocos de 11 dígitos, cada um com seu DV."""

    @staticmethod
    def _codigo(identificador: str) -> str:
        # 8 = arrecadação, 2 = segmento, 3º dígito = identificação de valor.
        return ("82" + identificador + "0123456789" * 5)[:44]

    @pytest.mark.parametrize("identificador", ["6", "7", "8", "9"])
    def test_gera_linha_de_48_digitos(self, fabrica, identificador):
        linha = fabrica.converter(CodigoBarras(self._codigo(identificador)))
        assert len(linha.digitos) == 48
        assert linha.tipo is TipoDocumento.ARRECADACAO

    @pytest.mark.parametrize(
        "identificador, calculadora",
        [
            ("6", Modulo10()),
            ("7", Modulo10()),
            ("8", Modulo11Arrecadacao()),
            ("9", Modulo11Arrecadacao()),
        ],
    )
    def test_identificador_de_valor_escolhe_o_algoritmo(
        self, fabrica, identificador, calculadora
    ):
        codigo = CodigoBarras(self._codigo(identificador))
        linha = fabrica.converter(codigo)

        for indice in range(4):
            bloco_original = codigo.digitos[indice * 11 : (indice + 1) * 11]
            dv_na_linha = linha.digitos[indice * 12 + 11]
            assert dv_na_linha == calculadora.calcular(bloco_original)

    def test_mascara_separa_os_quatro_blocos(self, fabrica):
        linha = fabrica.converter(CodigoBarras(self._codigo("6")))
        grupos = linha.formatada().split(" ")

        assert len(grupos) == 4
        # 11 dígitos do bloco + hífen + DV
        assert all(len(grupo) == 13 and grupo[11] == "-" for grupo in grupos)

    def test_mascara_preserva_os_digitos(self, fabrica):
        linha = fabrica.converter(CodigoBarras(self._codigo("9")))
        somente_digitos = "".join(c for c in linha.formatada() if c.isdigit())
        assert somente_digitos == linha.digitos


class TestFabricaConversor:
    def test_roteia_por_tipo(self, fabrica):
        cobranca = fabrica.para(CodigoBarras(BOLETO_COBRANCA))
        arrecadacao = fabrica.para(CodigoBarras("8" + BOLETO_COBRANCA[1:]))
        assert type(cobranca) is not type(arrecadacao)
