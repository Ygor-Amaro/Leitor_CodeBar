"""Triagem e gravação dos PDFs enviados pelo navegador.

O envio é a única porta por onde entra arquivo de fora, e é o que estes testes
cercam: nome hostil, conteúdo que não é PDF, tamanho e quantidade.
"""

import io

import pytest
from conftest import PDF_FALSO

from leitor_cb.services import ArmazenamentoEmDisco, ArquivoRecebido, ArquivoRejeitadoError


def recebido(nome: str, conteudo: bytes = PDF_FALSO) -> ArquivoRecebido:
    return ArquivoRecebido(nome=nome, fluxo=io.BytesIO(conteudo))


def armazenamento(tmp_path, **ajustes) -> ArmazenamentoEmDisco:
    return ArmazenamentoEmDisco(raiz=tmp_path / "uploads", **ajustes)


def test_grava_com_nome_sequencial_proprio(tmp_path):
    guardados = armazenamento(tmp_path).guardar("lote1", [recebido("a.pdf"), recebido("b.pdf")])

    assert [guardado.caminho.name for guardado in guardados] == ["001.pdf", "002.pdf"]
    assert all(guardado.caminho.read_bytes() == PDF_FALSO for guardado in guardados)


def test_preserva_o_nome_de_origem_como_metadado(tmp_path):
    (guardado,) = armazenamento(tmp_path).guardar("lote1", [recebido("Boleto Água.pdf")])

    assert guardado.nome_original == "Boleto Água.pdf"


def test_nome_com_travessia_nao_escapa_da_pasta(tmp_path):
    """O nome do navegador nunca vira caminho — vira só rótulo."""
    raiz = tmp_path / "uploads"
    (guardado,) = armazenamento(tmp_path).guardar("lote1", [recebido("../../../fora.pdf")])

    assert guardado.caminho.parent == raiz / "lote1"
    assert guardado.caminho.name == "001.pdf"
    assert not (tmp_path.parent / "fora.pdf").exists()


def test_recusa_extensao_que_nao_e_pdf(tmp_path):
    with pytest.raises(ArquivoRejeitadoError, match="não é um PDF"):
        armazenamento(tmp_path).guardar("lote1", [recebido("planilha.xlsx")])


def test_recusa_conteudo_que_nao_e_pdf(tmp_path):
    """Extensão certa não basta: o conteúdo precisa começar com %PDF-."""
    with pytest.raises(ArquivoRejeitadoError, match="conteúdo de PDF"):
        armazenamento(tmp_path).guardar("lote1", [recebido("falso.pdf", b"MZ\x90executavel")])


def test_recusa_arquivo_vazio(tmp_path):
    with pytest.raises(ArquivoRejeitadoError, match="vazio"):
        armazenamento(tmp_path).guardar("lote1", [recebido("nada.pdf", b"")])


def test_recusa_acima_do_tamanho_maximo(tmp_path):
    grande = PDF_FALSO + b"x" * 5000
    guarda = armazenamento(tmp_path, tamanho_maximo=1000)

    with pytest.raises(ArquivoRejeitadoError, match="limite"):
        guarda.guardar("lote1", [recebido("grande.pdf", grande)])


def test_recusa_arquivos_demais(tmp_path):
    guarda = armazenamento(tmp_path, maximo_de_arquivos=2)

    with pytest.raises(ArquivoRejeitadoError, match="no máximo"):
        guarda.guardar("lote1", [recebido(f"{i}.pdf") for i in range(3)])


def test_recusa_envio_sem_arquivo(tmp_path):
    with pytest.raises(ArquivoRejeitadoError, match="Nenhum arquivo"):
        armazenamento(tmp_path).guardar("lote1", [])


def test_um_arquivo_ruim_descarta_o_envio_inteiro(tmp_path):
    """Meio lote em disco viraria relatório incompleto sem ninguém perceber."""
    guarda = armazenamento(tmp_path)

    with pytest.raises(ArquivoRejeitadoError):
        guarda.guardar("lote1", [recebido("bom.pdf"), recebido("ruim.txt")])

    assert not (tmp_path / "uploads" / "lote1").exists()


def test_descartar_remove_a_pasta(tmp_path):
    guarda = armazenamento(tmp_path)
    guarda.guardar("lote1", [recebido("a.pdf")])

    guarda.descartar("lote1")

    assert not (tmp_path / "uploads" / "lote1").exists()


def test_descartar_lote_inexistente_nao_falha(tmp_path):
    armazenamento(tmp_path).descartar("nuncaexistiu1")


def test_identificador_fora_do_padrao_e_recusado(tmp_path):
    """Hoje o identificador vem de uuid4(); a checagem é o que mantém isso seguro
    se um dia ele passar a vir da URL."""
    with pytest.raises(ArquivoRejeitadoError, match="Identificador"):
        armazenamento(tmp_path).guardar("../fora", [recebido("a.pdf")])
