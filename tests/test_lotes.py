"""Ciclo de vida do lote, com dublês em todas as portas."""

import io
import os
import time
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import (
    PDF_FALSO,
    ExecutorParado,
    ProcessadorFalso,
    ProcessadorQuebrado,
    leitura_boleto,
    leitura_sem_codigo,
)

from leitor_cb.domain import EstadoLote, Recorte, RecorteInvalidoError, StatusLeitura
from leitor_cb.services import (
    ZOOM_RELEITURA_PADRAO,
    ArmazenamentoEmDisco,
    ArquivoRecebido,
    ArquivosIndisponiveisError,
    ExportadorCsv,
    LoteNaoEncontradoError,
    RegistradorSilencioso,
    RelatorioIndisponivelError,
    RepositorioSqlite,
    ServicoLotes,
)


def recebido(nome: str) -> ArquivoRecebido:
    return ArquivoRecebido(nome=nome, fluxo=io.BytesIO(PDF_FALSO))


def montar(tmp_path, executor, processador=None, retencao=timedelta(hours=24)) -> ServicoLotes:
    saida = tmp_path / "saida"
    return ServicoLotes(
        repositorio=RepositorioSqlite(tmp_path / "banco.sqlite3"),
        armazenamento=ArmazenamentoEmDisco(raiz=tmp_path / "uploads"),
        processador=processador or ProcessadorFalso(),
        fabrica_exportador=lambda prefixo: ExportadorCsv(saida, prefixo),
        diretorio_saida=saida,
        executor=executor,
        registrador=RegistradorSilencioso(),
        retencao=retencao,
    )


def test_lote_percorre_ate_concluir(tmp_path, executor):
    servico = montar(tmp_path, executor)

    lote = servico.criar([recebido("a.pdf"), recebido("b.pdf")])

    concluido = servico.obter(lote.identificador)
    assert concluido.estado is EstadoLote.CONCLUIDO
    assert concluido.documentos_processados == 2
    assert concluido.percentual == 100


def test_relatorio_e_gravado_na_pasta_de_saida(tmp_path, executor):
    servico = montar(tmp_path, executor)

    lote = servico.criar([recebido("a.pdf")])

    caminho = servico.caminho_do_relatorio(lote.identificador)
    cabecalho = caminho.read_text(encoding="utf-8-sig").splitlines()[0]
    assert caminho.parent == (tmp_path / "saida").resolve()
    # QUOTE_ALL: o cabeçalho sai com aspas, como o resto do arquivo.
    assert cabecalho.startswith('"arquivo";"pagina"')


def test_resultado_mostra_o_nome_que_o_operador_enviou(tmp_path, executor):
    """Em disco o arquivo virou 001.pdf; o relatório precisa dizer 'Boleto.pdf'."""
    servico = montar(tmp_path, executor)

    lote = servico.criar([recebido("Boleto Luz.pdf")])

    (resultado,) = servico.resultados(lote.identificador)
    assert resultado.arquivo == "Boleto Luz.pdf"


def test_resumo_reflete_as_leituras(tmp_path, executor):
    processador = ProcessadorFalso([leitura_boleto(), leitura_sem_codigo()])
    servico = montar(tmp_path, executor, processador)

    lote = servico.criar([recebido("a.pdf")])

    resumo = servico.resumo(lote.identificador)
    assert resumo.total == 2
    assert resumo.sucessos == 1
    assert resumo.pendencias == 1


def test_pdfs_ficam_disponiveis_para_releitura(tmp_path, executor):
    """Apagar no fim do lote impediria o recorte manual, que só existe justamente
    quando o automático não resolveu."""
    servico = montar(tmp_path, executor)

    lote = servico.criar([recebido("a.pdf")])

    assert servico.arquivos_disponiveis(lote.identificador)


def test_falha_no_processamento_marca_o_lote_e_nao_derruba_o_servidor(tmp_path, executor):
    servico = montar(tmp_path, executor, ProcessadorQuebrado())

    lote = servico.criar([recebido("a.pdf")])

    falhado = servico.obter(lote.identificador)
    assert falhado.estado is EstadoLote.FALHOU
    assert "PyMuPDF explodiu" in falhado.observacao


def test_lote_que_falhou_nao_oferece_relatorio(tmp_path, executor):
    servico = montar(tmp_path, executor, ProcessadorQuebrado())
    lote = servico.criar([recebido("a.pdf")])

    with pytest.raises(RelatorioIndisponivelError):
        servico.caminho_do_relatorio(lote.identificador)


def test_falha_mantem_os_pdfs_para_nova_tentativa(tmp_path, executor):
    servico = montar(tmp_path, executor, ProcessadorQuebrado())

    lote = servico.criar([recebido("a.pdf")])

    assert servico.arquivos_disponiveis(lote.identificador)


def test_lote_inexistente_levanta(tmp_path, executor):
    with pytest.raises(LoteNaoEncontradoError):
        montar(tmp_path, executor).obter("nao-existe")


def test_relatorio_apagado_do_disco_nao_vira_leitura_de_outro_arquivo(tmp_path, executor):
    servico = montar(tmp_path, executor)
    lote = servico.criar([recebido("a.pdf")])
    servico.caminho_do_relatorio(lote.identificador).unlink()

    with pytest.raises(RelatorioIndisponivelError):
        servico.caminho_do_relatorio(lote.identificador)


def test_historico_traz_lote_e_resumo(tmp_path, executor):
    servico = montar(tmp_path, executor)
    servico.criar([recebido("a.pdf")])
    servico.criar([recebido("b.pdf")])

    historico = servico.historico()

    assert len(historico) == 2
    assert all(resumo.total == 1 for _, resumo in historico)


# ------------------------------------------------------------ recorte manual


def montar_com_pendencia(tmp_path, executor) -> tuple[ServicoLotes, str, ProcessadorFalso]:
    """Lote que saiu com pendência — o caso em que o recorte manual serve."""
    processador = ProcessadorFalso(
        resultados=[leitura_sem_codigo("Boleto.pdf", pagina=1)],
        releitura=[leitura_boleto("Boleto.pdf")],
    )
    servico = montar(tmp_path, executor, processador)
    lote = servico.criar([recebido("Boleto.pdf")])
    return servico, lote.identificador, processador


def test_recorte_substitui_a_pendencia_da_pagina(tmp_path, executor):
    servico, identificador, _ = montar_com_pendencia(tmp_path, executor)
    assert servico.resumo(identificador).pendencias == 1

    servico.reler_pagina(
        identificador, 1, 1, Recorte(x=10, y=20, largura=40, altura=15, zoom=3.0)
    )

    (resultado,) = servico.resultados(identificador)
    assert resultado.status is StatusLeitura.SUCESSO
    assert servico.resumo(identificador).pendencias == 0


def test_recorte_chega_ao_processador_com_o_zoom_pedido(tmp_path, executor):
    servico, identificador, processador = montar_com_pendencia(tmp_path, executor)
    recorte = Recorte(x=10, y=20, largura=40, altura=15, zoom=3.0)

    servico.reler_pagina(identificador, 1, 1, recorte)

    assert processador.areas == [recorte]
    # A página tem de ser rasterizada no mesmo zoom em que o operador marcou.
    assert processador.renderizacoes[-1][1:] == (1, 3.0)


def test_releitura_sem_recorte_le_a_pagina_inteira(tmp_path, executor):
    servico, identificador, processador = montar_com_pendencia(tmp_path, executor)

    servico.reler_pagina(identificador, 1, 1, None)

    assert processador.areas == [None]


def test_releitura_de_pagina_inteira_usa_o_zoom_escolhido(tmp_path, executor):
    """Sem retângulo, quem manda no zoom é o que o operador ampliou na tela."""
    servico, identificador, processador = montar_com_pendencia(tmp_path, executor)

    servico.reler_pagina(identificador, 1, 1, None, zoom=4.0)

    assert processador.renderizacoes[-1][1:] == (1, 4.0)


def test_releitura_de_pagina_inteira_sem_zoom_cai_no_padrao(tmp_path, executor):
    """O padrão acompanha o primeiro zoom da varredura automática.

    Abaixo dele a releitura enxergaria menos do que a passada que já falhou — e,
    como ela substitui a página, trocaria uma leitura boa por "nenhum código
    encontrado".
    """
    servico, identificador, processador = montar_com_pendencia(tmp_path, executor)

    servico.reler_pagina(identificador, 1, 1, None)

    assert processador.renderizacoes[-1][1:] == (1, ZOOM_RELEITURA_PADRAO)


def test_releitura_recusa_zoom_fora_da_faixa(tmp_path, executor):
    servico, identificador, _ = montar_com_pendencia(tmp_path, executor)

    with pytest.raises(RecorteInvalidoError):
        servico.reler_pagina(identificador, 1, 1, None, zoom=99.0)


def test_releitura_escala_o_zoom_ate_achar_o_codigo(tmp_path, executor):
    """Barra fina não resolve em zoom baixo, e a tela de recorte abre em 2.0.

    Sem a escalada, o operador marcava o código no lugar certo e recebia "nenhum
    código encontrado" — enxergando menos que a varredura automática, que já
    tenta 3.0.
    """
    processador = ProcessadorFalso(
        resultados=[leitura_sem_codigo("Boleto.pdf", pagina=1)],
        releitura=[leitura_boleto("Boleto.pdf")],
        zoom_minimo=3.0,
    )
    servico = montar(tmp_path, executor, processador)
    identificador = servico.criar([recebido("Boleto.pdf")]).identificador

    (resultado,) = servico.reler_pagina(
        identificador, 1, 1, Recorte(x=10, y=20, largura=40, altura=15, zoom=2.0)
    )

    assert resultado.status is StatusLeitura.SUCESSO
    assert [zoom for _, _, zoom in processador.renderizacoes] == [2.0, 3.0]


def test_escalada_reposiciona_o_recorte_no_novo_zoom(tmp_path, executor):
    """O retângulo veio em pixels do zoom marcado; sem converter, a segunda
    tentativa recortaria outro pedaço da página."""
    processador = ProcessadorFalso(
        releitura=[leitura_boleto("Boleto.pdf")], zoom_minimo=4.0
    )
    servico = montar(tmp_path, executor, processador)
    identificador = servico.criar([recebido("Boleto.pdf")]).identificador

    servico.reler_pagina(
        identificador, 1, 1, Recorte(x=10, y=20, largura=40, altura=15, zoom=2.0)
    )

    assert processador.areas == [
        Recorte(x=10, y=20, largura=40, altura=15, zoom=2.0),
        Recorte(x=15, y=30, largura=60, altura=22, zoom=3.0),
        Recorte(x=20, y=40, largura=80, altura=30, zoom=4.0),
    ]


def test_releitura_vazia_nao_apaga_a_leitura_que_existia(tmp_path, executor):
    """Apagar uma leitura boa por causa de uma tentativa vazia é perda de dado
    sem desfazer — e a tentativa pode ter falhado só pelo zoom."""
    processador = ProcessadorFalso(
        resultados=[leitura_boleto("Boleto.pdf")],
        releitura=[leitura_sem_codigo("Boleto.pdf", pagina=1)],
    )
    servico = montar(tmp_path, executor, processador)
    identificador = servico.criar([recebido("Boleto.pdf")]).identificador
    csv_antes = servico.obter(identificador).nome_csv

    (resultado,) = servico.reler_pagina(identificador, 1, 1, None)

    assert resultado.status is StatusLeitura.SEM_CODIGO
    (guardado,) = servico.resultados(identificador)
    assert guardado.status is StatusLeitura.SUCESSO
    assert servico.obter(identificador).nome_csv == csv_antes


def test_releitura_usa_o_nome_que_o_operador_enviou(tmp_path, executor):
    servico, identificador, _ = montar_com_pendencia(tmp_path, executor)

    (resultado,) = servico.reler_pagina(identificador, 1, 1, None)

    assert resultado.arquivo == "Boleto.pdf"


def test_releitura_regenera_o_csv_e_remove_o_anterior(tmp_path, executor):
    """O CSV baixado não pode continuar mostrando a pendência já resolvida."""
    servico, identificador, _ = montar_com_pendencia(tmp_path, executor)
    anterior = servico.caminho_do_relatorio(identificador)

    servico.reler_pagina(identificador, 1, 1, None)

    atual = servico.caminho_do_relatorio(identificador)
    assert "sucesso" in atual.read_text(encoding="utf-8-sig")
    assert not anterior.exists() or anterior == atual
    assert len(list((tmp_path / "saida").glob("*.csv"))) == 1


def test_imagem_da_pagina_e_rasterizada_no_zoom_pedido(tmp_path, executor):
    servico, identificador, processador = montar_com_pendencia(tmp_path, executor)

    imagem = servico.imagem_da_pagina(identificador, 1, 1, 4.0)

    assert imagem.shape == (120, 90, 3)
    assert processador.renderizacoes[-1][1:] == (1, 4.0)


def test_descartar_arquivos_impede_a_releitura(tmp_path, executor):
    servico, identificador, _ = montar_com_pendencia(tmp_path, executor)

    servico.descartar_arquivos(identificador)

    assert not servico.arquivos_disponiveis(identificador)
    with pytest.raises(ArquivosIndisponiveisError):
        servico.reler_pagina(identificador, 1, 1, None)


def test_envio_expirado_e_apagado(tmp_path, executor):
    servico = montar(tmp_path, executor, retencao=timedelta(hours=1))
    lote = servico.criar([recebido("a.pdf")])
    pasta = tmp_path / "uploads" / lote.identificador

    # Envelhece a pasta em duas horas, além do prazo de retenção.
    antigo = time.time() - 2 * 3600
    os.utime(pasta, (antigo, antigo))

    assert servico.limpar_expirados() == [lote.identificador]
    assert not servico.arquivos_disponiveis(lote.identificador)


def test_envio_dentro_do_prazo_sobrevive_a_limpeza(tmp_path, executor):
    servico = montar(tmp_path, executor, retencao=timedelta(hours=1))
    lote = servico.criar([recebido("a.pdf")])

    servico.limpar_expirados()

    assert servico.arquivos_disponiveis(lote.identificador)


def test_documentos_do_lote_ficam_registrados(tmp_path, executor):
    servico = montar(tmp_path, executor)

    lote = servico.criar([recebido("Luz.pdf"), recebido("Água.pdf")])

    documentos = servico.documentos(lote.identificador)
    assert [(d.indice, d.nome_original) for d in documentos] == [
        (1, "Luz.pdf"),
        (2, "Água.pdf"),
    ]


def test_processador_recebe_o_caminho_gravado(tmp_path, executor):
    processador = ProcessadorFalso()
    servico = montar(tmp_path, executor, processador)

    servico.criar([recebido("a.pdf")])

    assert [Path(caminho).name for caminho in processador.processados] == ["001.pdf"]


# ------------------------------------------------- lotes deixados pela metade


def test_fechar_interrompidos_encerra_o_lote_que_ficou_na_fila(tmp_path):
    """O que sobra de um servidor derrubado no meio da leitura.

    A fila mora na memória do processo: ninguém vai retomar esse lote, e sem
    fechá-lo a tela pediria o andamento a cada segundo, para sempre.
    """
    servico = montar(tmp_path, ExecutorParado())
    lote = servico.criar([recebido("boleto.pdf")])
    assert servico.obter(lote.identificador).estado is EstadoLote.PENDENTE

    fechados = servico.fechar_interrompidos()

    assert fechados == [lote.identificador]
    encerrado = servico.obter(lote.identificador)
    assert encerrado.estado is EstadoLote.FALHOU
    assert encerrado.terminado
    assert "novamente" in encerrado.observacao


def test_fechar_interrompidos_deixa_o_lote_concluido_em_paz(tmp_path, executor):
    servico = montar(tmp_path, executor)
    lote = servico.criar([recebido("boleto.pdf")])
    csv_gerado = servico.obter(lote.identificador).nome_csv

    assert servico.fechar_interrompidos() == []

    intacto = servico.obter(lote.identificador)
    assert intacto.estado is EstadoLote.CONCLUIDO
    assert intacto.nome_csv == csv_gerado
