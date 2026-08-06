"""Relatório CSV e saída de console."""

import csv

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

        assert "DV GERAL NAO CONFERE" in capsys.readouterr().out
