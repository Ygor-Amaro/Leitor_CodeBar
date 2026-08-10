"""Montagem da configuração e descoberta de arquivos na CLI."""

from pathlib import Path

import pytest

from leitor_cb.adapters.cli import (
    CODIGO_ERRO_USO,
    configuracao_de,
    construir_parser,
    localizar_pdfs,
    main,
)
from leitor_cb.config import ModoLeitura


def configurar(*argv: str):
    return configuracao_de(construir_parser().parse_args(list(argv)))


class TestConfiguracao:
    def test_modo_padrao_e_automatico(self):
        assert configurar().modo is ModoLeitura.AUTOMATICO

    def test_sem_gui_desliga_a_janela(self):
        config = configurar("--sem-gui")
        assert config.modo is ModoLeitura.SEM_GUI
        assert config.usa_gui is False
        assert config.sempre_manual is False

    def test_sempre_manual(self):
        config = configurar("--sempre-manual")
        assert config.sempre_manual is True
        assert config.usa_gui is True

    def test_zoom_sobrepoe_o_padrao(self):
        assert configurar("--zoom", "1.5", "4").zooms == (1.5, 4.0)

    @pytest.mark.parametrize("invalido", ["0", "-2", "abc"])
    def test_zoom_invalido_e_erro_de_uso(self, invalido, capsys):
        """Zoom <= 0 quebraria toda página: melhor recusar no parse."""
        with pytest.raises(SystemExit) as saida:
            configurar("--zoom", invalido)

        assert saida.value.code == CODIGO_ERRO_USO

    def test_caminhos_sobrepoem_o_padrao(self):
        config = configurar("--entrada", "x/y", "--saida", "z")
        assert config.entrada == Path("x/y")
        assert config.saida == Path("z")

    def test_sem_csv(self):
        assert configurar("--sem-csv").gerar_csv is False


class TestLocalizarPdfs:
    def test_arquivo_unico(self, tmp_path):
        pdf = tmp_path / "boleto.pdf"
        pdf.touch()
        assert localizar_pdfs(pdf) == [pdf]

    def test_pasta_filtra_e_ordena(self, tmp_path):
        (tmp_path / "b.pdf").touch()
        (tmp_path / "a.PDF").touch()
        (tmp_path / "planilha.xlsx").touch()
        (tmp_path / "subpasta").mkdir()

        encontrados = [caminho.name for caminho in localizar_pdfs(tmp_path)]

        assert encontrados == ["a.PDF", "b.pdf"]

    def test_caminho_inexistente(self, tmp_path):
        assert localizar_pdfs(tmp_path / "nao-existe") == []


class TestMain:
    def test_entrada_inexistente(self, tmp_path, capsys):
        codigo = main(["--entrada", str(tmp_path / "nada"), "--sem-gui"])

        assert codigo == CODIGO_ERRO_USO
        assert "não encontrada" in capsys.readouterr().err

    def test_pasta_sem_pdfs(self, tmp_path, capsys):
        codigo = main(["--entrada", str(tmp_path), "--sem-gui"])

        assert codigo == CODIGO_ERRO_USO
        assert "Nenhum PDF" in capsys.readouterr().err
