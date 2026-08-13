"""O que o zxing procura na página."""

import zxingcpp

from leitor_cb.services.decodificador import FORMATOS_PADRAO, DecodificadorZxing


def test_formatos_padrao_sao_aceitos_pelo_zxing():
    """Nome de formato errado só apareceria na subida do servidor, como exceção."""
    assert DecodificadorZxing(FORMATOS_PADRAO) is not None


def test_procura_code128_alem_de_itf_e_qrcode():
    """A ficha de compensação manda ITF, mas emissor que imprime os mesmos 44
    dígitos em Code 128 existe — visto num boleto Itaú de 08/2026, que sem este
    formato na lista saía como "nenhum código encontrado".
    """
    formatos = str(zxingcpp.barcode_formats_from_str(FORMATOS_PADRAO))

    assert "ITF" in formatos
    assert "Code 128" in formatos
    assert "QR Code" in formatos
