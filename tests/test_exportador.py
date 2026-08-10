"""Relatório CSV e saída de console."""

import csv

import pytest

from leitor_cb.domain import CodigoBarras, FabricaConversor, PixPayload, ResultadoLeitura
from leitor_cb.services import ExportadorConsole, ExportadorCsv
from leitor_cb.services.exportador import COLUNAS

BOLETO = "34196152300000406291095000320351024589465000"


def resultados_de_exemplo() -> list[ResultadoLeitura]:
    codigo = CodigoBarras(BOLETO)
    linha = FabricaConversor().converter(codigo)
    return [
        ResultadoLeitura.de_boleto("lote.pdf", 1, codigo, linha),
        ResultadoLeitura.de_pix("lote.pdf", 2, PixPayload("00020126580014BR.GOV.BCB.PIX")),
        ResultadoLeitura.sem_codigo("lote.pdf", 3),
        ResultadoLeitura.invalido("lote.pdf", 4, "123", "tamanho inválido"),
    ]


def ler_csv(caminho):
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        return list(csv.DictReader(arquivo, delimiter=";"))


class TestExportadorCsv:
    def test_cria_o_diretorio_de_saida(self, tmp_path):
        destino = tmp_path / "relatorios" / "2026"
        arquivo = ExportadorCsv(destino).exportar(resultados_de_exemplo())

        assert arquivo.exists()
        assert arquivo.parent == destino

    def test_cabecalho_e_quantidade_de_linhas(self, tmp_path):
        arquivo = ExportadorCsv(tmp_path).exportar(resultados_de_exemplo())
        linhas = ler_csv(arquivo)

        assert list(linhas[0].keys()) == list(COLUNAS)
        assert len(linhas) == 4

    def test_conteudo_do_boleto(self, tmp_path):
        arquivo = ExportadorCsv(tmp_path).exportar(resultados_de_exemplo())
        boleto = ler_csv(arquivo)[0]

        assert boleto["tipo"] == "cobranca"
        assert boleto["status"] == "sucesso"
        assert boleto["dv_ok"] == "sim"
        # O prefixo de tabulação impede o Excel de virar notação científica.
        assert boleto["codigo_barras"].lstrip("\t") == BOLETO
        assert len(boleto["linha_digitavel"].lstrip("\t")) == 47

    def test_dv_ok_fica_vazio_quando_nao_se_aplica(self, tmp_path):
        arquivo = ExportadorCsv(tmp_path).exportar(resultados_de_exemplo())
        pix, sem_codigo = ler_csv(arquivo)[1], ler_csv(arquivo)[2]

        assert pix["dv_ok"] == ""
        assert sem_codigo["dv_ok"] == ""
        assert sem_codigo["status"] == "sem_codigo"

    def test_acentuacao_sobrevive_ao_round_trip(self, tmp_path):
        arquivo = ExportadorCsv(tmp_path).exportar(resultados_de_exemplo())
        invalido = ler_csv(arquivo)[3]

        assert invalido["observacao"] == "tamanho inválido"

    def test_arquivos_diferentes_nao_se_sobrescrevem(self, tmp_path):
        exportador = ExportadorCsv(tmp_path, prefixo="lote")
        primeiro = exportador.exportar(resultados_de_exemplo())

        assert primeiro.name.startswith("lote_")
        assert primeiro.suffix == ".csv"

    def test_dois_lotes_no_mesmo_segundo_convivem(self, tmp_path):
        """O carimbo tem resolução de segundos; sem sufixo, o 1º relatório sumiria."""
        exportador = ExportadorCsv(tmp_path, prefixo="lote")
        primeiro = exportador.exportar(resultados_de_exemplo())
        segundo = exportador.exportar(resultados_de_exemplo())

        assert primeiro != segundo
        assert primeiro.exists() and segundo.exists()
        assert len(list(tmp_path.glob("lote_*.csv"))) == 2


class TestInjecaoDeFormula:
    """O CSV é feito para abrir no Excel e o conteúdo vem de dentro do PDF."""

    @pytest.mark.parametrize(
        "payload",
        [
            "=cmd|'/c calc'!A1",
            "+1+1",
            "-1+1",
            "@SUM(1+1)",
            "\t=1+1",
            "\r=1+1",
        ],
    )
    def test_payload_pix_perigoso_e_neutralizado(self, tmp_path, payload):
        arquivo = ExportadorCsv(tmp_path).exportar(
            [ResultadoLeitura.de_pix("nota.pdf", 1, PixPayload(payload))]
        )
        linha = ler_csv(arquivo)[0]

        assert linha["linha_digitavel"] == f"'{payload}"
        assert not linha["linha_digitavel"].startswith(("=", "+", "-", "@", "\t", "\r"))

    def test_nome_de_arquivo_perigoso_e_neutralizado(self, tmp_path):
        malicioso = '=HYPERLINK("http://evil","clique")'
        arquivo = ExportadorCsv(tmp_path).exportar(
            [ResultadoLeitura.sem_codigo(f"{malicioso}.pdf", 1)]
        )

        assert ler_csv(arquivo)[0]["arquivo"] == f"'{malicioso}.pdf"

    def test_codigo_de_barras_ilegivel_e_neutralizado(self, tmp_path):
        arquivo = ExportadorCsv(tmp_path).exportar(
            [ResultadoLeitura.invalido("nota.pdf", 1, "=1+1", "tamanho inválido")]
        )

        assert ler_csv(arquivo)[0]["codigo_barras"] == "'=1+1"

    def test_conteudo_legitimo_nao_e_alterado(self, tmp_path):
        arquivo = ExportadorCsv(tmp_path).exportar(resultados_de_exemplo())
        boleto, pix = ler_csv(arquivo)[0], ler_csv(arquivo)[1]

        assert boleto["codigo_barras"] == f"\t{BOLETO}"  # só o prefixo numérico
        assert pix["linha_digitavel"] == "00020126580014BR.GOV.BCB.PIX"

    def test_prefixo_de_tabulacao_sai_entre_aspas(self, tmp_path):
        """Sem aspas o TAB fica solto no arquivo e a proteção não é confiável."""
        arquivo = ExportadorCsv(tmp_path).exportar(resultados_de_exemplo())
        primeira_linha = arquivo.read_text(encoding="utf-8-sig").splitlines()[1]

        assert f'"\t{BOLETO}"' in primeira_linha


class TestExportadorConsole:
    def test_imprime_cada_status_sem_quebrar(self, capsys):
        console = ExportadorConsole()
        for resultado in resultados_de_exemplo():
            console.imprimir(resultado)

        saida = capsys.readouterr().out
        assert "34191.09503" in saida  # linha formatada
        assert "QR Code (PIX)" in saida

    def test_resumo_lista_pendencias(self, capsys):
        ExportadorConsole().exportar(resultados_de_exemplo())

        saida = capsys.readouterr().out
        assert "Exigem conferência manual: 2" in saida

    def test_resumo_sem_pendencias(self, capsys):
        codigo = CodigoBarras(BOLETO)
        linha = FabricaConversor().converter(codigo)
        ExportadorConsole().exportar([ResultadoLeitura.de_boleto("a.pdf", 1, codigo, linha)])

        assert "Nenhuma pendência." in capsys.readouterr().out

    def test_dv_divergente_ganha_alerta_visivel(self, capsys):
        corrompido = CodigoBarras(BOLETO[:20] + "7" + BOLETO[21:])
        linha = FabricaConversor().converter(corrompido)
        ExportadorConsole().imprimir(
            ResultadoLeitura.de_boleto("a.pdf", 1, corrompido, linha)
        )

        assert "DV geral não confere" in capsys.readouterr().out

    def test_identificador_invalido_ganha_alerta_proprio(self, capsys):
        """O operador precisa saber qual conferência falhou, não só que falhou."""
        codigo = CodigoBarras("8117" + "0" * 40)
        linha = FabricaConversor().converter(codigo)
        ExportadorConsole().imprimir(ResultadoLeitura.de_boleto("a.pdf", 1, codigo, linha))

        saida = capsys.readouterr().out
        assert "Identificador de valor" in saida
        assert "DV geral" not in saida
