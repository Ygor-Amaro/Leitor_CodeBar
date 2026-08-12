"""Rotas HTTP — API JSON e telas HTMX — sem PDF de verdade e sem thread."""

from collections.abc import Callable
from concurrent.futures import Executor, Future

import pytest
from conftest import PDF_FALSO, ProcessadorFalso, leitura_boleto, leitura_sem_codigo
from fastapi.testclient import TestClient

from leitor_cb.adapters.api.app import criar_app
from leitor_cb.config import ConfiguracaoWeb
from leitor_cb.services import (
    ArmazenamentoEmDisco,
    ExportadorCsv,
    RegistradorSilencioso,
    RepositorioSqlite,
    ServicoLotes,
)

HTMX = {"HX-Request": "true"}


class ExecutorParado(Executor):
    """Aceita o job e não roda nada — deixa o lote parado em 'na fila'.

    É como se testa a tela de progresso: com o executor imediato o lote já
    nasceria concluído e o estado intermediário nunca apareceria.
    """

    def submit(self, fn: Callable, /, *args, **kwargs) -> Future:  # type: ignore[override]
        return Future()


def montar(tmp_path, executor, processador=None, **ajustes) -> TestClient:
    config = ConfiguracaoWeb(
        dados=tmp_path / "dados", saida=tmp_path / "saida", **ajustes
    )
    servico = ServicoLotes(
        repositorio=RepositorioSqlite(config.banco),
        armazenamento=ArmazenamentoEmDisco(raiz=config.uploads),
        processador=processador or ProcessadorFalso(),
        fabrica_exportador=lambda prefixo: ExportadorCsv(config.saida, prefixo),
        diretorio_saida=config.saida,
        executor=executor,
        registrador=RegistradorSilencioso(),
    )
    app = criar_app(config, servico=servico, registrador=RegistradorSilencioso())
    return TestClient(app)


@pytest.fixture
def cliente(tmp_path, executor):
    with montar(tmp_path, executor) as cliente:
        yield cliente


def envio(nome: str = "boleto.pdf", conteudo: bytes = PDF_FALSO):
    return [("arquivos", (nome, conteudo, "application/pdf"))]


# --------------------------------------------------------------------- telas


def test_pagina_inicial_abre(cliente):
    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert "Enviar documentos" in resposta.text


def test_envio_pela_tela_devolve_o_painel_do_lote(cliente):
    resposta = cliente.post("/lotes", files=envio(), headers=HTMX)

    assert resposta.status_code == 200
    assert "Baixar CSV" in resposta.text


def test_envio_avisa_o_historico_para_recarregar(cliente):
    resposta = cliente.post("/lotes", files=envio(), headers=HTMX)

    assert resposta.headers["HX-Trigger"] == "lote-atualizado"


def test_painel_de_lote_concluido_nao_pede_mais_atualizacao(cliente):
    """O polling para porque o fragmento volta sem os atributos hx-*."""
    cliente.post("/lotes", files=envio(), headers=HTMX)
    identificador = cliente.get("/api/lotes").json()[0]["identificador"]

    resposta = cliente.get(f"/lotes/{identificador}/painel", headers=HTMX)

    assert "every 1s" not in resposta.text


def test_painel_de_lote_em_andamento_continua_pedindo(tmp_path):
    with montar(tmp_path, ExecutorParado()) as cliente:
        cliente.post("/lotes", files=envio(), headers=HTMX)
        lote = cliente.get("/api/lotes").json()[0]["identificador"]

        resposta = cliente.get(f"/lotes/{lote}/painel", headers=HTMX)

        assert 'hx-trigger="every 1s"' in resposta.text
        assert "Na fila" in resposta.text


def test_pagina_do_lote_tem_endereco_proprio(cliente):
    cliente.post("/lotes", files=envio(), headers=HTMX)
    lote = cliente.get("/api/lotes").json()[0]["identificador"]

    resposta = cliente.get(f"/lotes/{lote}")

    assert resposta.status_code == 200
    assert lote[:8] in resposta.text


def test_historico_lista_os_lotes(cliente):
    cliente.post("/lotes", files=envio(), headers=HTMX)

    resposta = cliente.get("/historico", headers=HTMX)

    assert "Concluído" in resposta.text


def test_nome_do_arquivo_aparece_escapado_na_tabela(cliente):
    """O nome vem de fora; o autoescape do Jinja é o que impede injeção de HTML.

    O payload não tem barra de propósito: com barra, `Path(...).name` já cortaria
    o trecho antes de chegar ao template, e o teste passaria sem exercitar o
    escape.
    """
    resposta = cliente.post(
        "/lotes", files=envio(nome="<img src=x onerror=alerta()>.pdf"), headers=HTMX
    )

    assert "<img src=x" not in resposta.text
    assert "&lt;img src=x" in resposta.text


# ----------------------------------------------------------------------- API


def test_api_envio_abre_o_lote(cliente):
    resposta = cliente.post("/api/lotes", files=envio())

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["estado"] == "concluido"
    assert corpo["total_documentos"] == 1


def test_api_detalhe_traz_as_leituras(tmp_path, executor):
    processador = ProcessadorFalso([leitura_boleto(), leitura_sem_codigo()])
    with montar(tmp_path, executor, processador) as cliente:
        identificador = cliente.post("/api/lotes", files=envio()).json()["identificador"]

        corpo = cliente.get(f"/api/lotes/{identificador}").json()

        assert corpo["lote"]["resumo"] == {"total": 2, "sucessos": 1, "pendencias": 1}
        assert len(corpo["resultados"]) == 2


def test_api_entrega_a_linha_crua_e_a_formatada(cliente):
    identificador = cliente.post("/api/lotes", files=envio()).json()["identificador"]

    (resultado,) = cliente.get(f"/api/lotes/{identificador}").json()["resultados"]

    assert resultado["linha_digitavel"].isdigit()
    assert "." in resultado["linha_formatada"]


def test_api_lista_os_lotes(cliente):
    cliente.post("/api/lotes", files=envio())
    cliente.post("/api/lotes", files=envio())

    assert len(cliente.get("/api/lotes").json()) == 2


def test_api_lote_inexistente_da_404(cliente):
    resposta = cliente.get("/api/lotes/nao-existe")

    assert resposta.status_code == 404
    assert "erro" in resposta.json()


# ------------------------------------------------------------------ download


def test_download_entrega_o_csv(cliente):
    identificador = cliente.post("/api/lotes", files=envio()).json()["identificador"]

    resposta = cliente.get(f"/api/lotes/{identificador}/relatorio")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/csv")
    assert "attachment" in resposta.headers["content-disposition"]


def test_download_de_lote_em_andamento_e_recusado(tmp_path):
    with montar(tmp_path, ExecutorParado()) as cliente:
        identificador = cliente.post("/api/lotes", files=envio()).json()["identificador"]

        resposta = cliente.get(f"/api/lotes/{identificador}/relatorio")

        assert resposta.status_code == 409


# --------------------------------------------------------------------- erros


def test_arquivo_invalido_na_api_volta_json(cliente):
    resposta = cliente.post("/api/lotes", files=envio(nome="planilha.xlsx"))

    assert resposta.status_code == 400
    assert "não é um PDF" in resposta.json()["erro"]


def test_arquivo_invalido_no_htmx_volta_fragmento_html(cliente):
    """Quem pergunta pelo HTMX recebe HTML: um JSON cru apareceria na tela."""
    resposta = cliente.post("/lotes", files=envio(nome="planilha.xlsx"), headers=HTMX)

    assert resposta.status_code == 400
    assert resposta.headers["content-type"].startswith("text/html")
    assert "não é um PDF" in resposta.text


# ------------------------------------------------------------ recorte manual


def primeiro_lote(cliente) -> str:
    cliente.post("/api/lotes", files=envio())
    return cliente.get("/api/lotes").json()[0]["identificador"]


def test_imagem_da_pagina_sai_em_png(cliente):
    identificador = primeiro_lote(cliente)

    resposta = cliente.get(
        f"/api/lotes/{identificador}/documentos/1/paginas/1/imagem?zoom=2"
    )

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "image/png"
    assert resposta.content.startswith(b"\x89PNG")


def test_zoom_fora_do_intervalo_e_recusado(cliente):
    identificador = primeiro_lote(cliente)

    resposta = cliente.get(
        f"/api/lotes/{identificador}/documentos/1/paginas/1/imagem?zoom=999"
    )

    assert resposta.status_code == 422


def test_tela_de_recorte_mostra_a_imagem_e_o_formulario(cliente):
    identificador = primeiro_lote(cliente)

    resposta = cliente.get(f"/lotes/{identificador}/documentos/1/paginas/1")

    assert resposta.status_code == 200
    assert "/paginas/1/imagem?zoom=" in resposta.text
    assert "Ler seleção" in resposta.text
    assert "selecao.js" in resposta.text


def test_releitura_pela_tela_devolve_o_resultado(cliente):
    identificador = primeiro_lote(cliente)

    resposta = cliente.post(
        f"/lotes/{identificador}/documentos/1/paginas/1/releitura",
        data={"zoom": "3.0", "x": "10", "y": "10", "largura": "50", "altura": "20"},
        headers=HTMX,
    )

    assert resposta.status_code == 200
    assert "Resultado da área marcada" in resposta.text
    assert resposta.headers["HX-Trigger"] == "lote-atualizado"


def test_releitura_sem_area_marcada_le_a_pagina_inteira(cliente):
    identificador = primeiro_lote(cliente)

    resposta = cliente.post(
        f"/lotes/{identificador}/documentos/1/paginas/1/releitura",
        data={"zoom": "2.0", "x": "0", "y": "0", "largura": "0", "altura": "0"},
        headers=HTMX,
    )

    assert "Resultado da página inteira" in resposta.text


def test_api_releitura_com_recorte(cliente):
    identificador = primeiro_lote(cliente)

    resposta = cliente.post(
        f"/api/lotes/{identificador}/documentos/1/paginas/1/releitura",
        json={"x": 10, "y": 10, "largura": 50, "altura": 20, "zoom": 3.0},
    )

    assert resposta.status_code == 200
    assert resposta.json()[0]["documento_indice"] == 1


def test_api_recusa_recorte_degenerado(cliente):
    identificador = primeiro_lote(cliente)

    resposta = cliente.post(
        f"/api/lotes/{identificador}/documentos/1/paginas/1/releitura",
        json={"x": 10, "y": 10, "largura": 0, "altura": 20, "zoom": 3.0},
    )

    assert resposta.status_code == 422


def test_tabela_oferece_recortar_enquanto_os_arquivos_existem(cliente):
    identificador = primeiro_lote(cliente)

    resposta = cliente.get(f"/lotes/{identificador}")

    assert "recortar" in resposta.text


def test_descarte_pela_tela_remove_a_opcao_de_recortar(cliente):
    identificador = primeiro_lote(cliente)

    resposta = cliente.post(f"/lotes/{identificador}/arquivos/descartar", headers=HTMX)

    assert resposta.status_code == 200
    assert "já foram descartados" in resposta.text
    assert "recortar" not in resposta.text


def test_releitura_apos_descarte_e_recusada(cliente):
    identificador = primeiro_lote(cliente)
    assert cliente.delete(f"/api/lotes/{identificador}/arquivos").status_code == 204

    resposta = cliente.get(
        f"/api/lotes/{identificador}/documentos/1/paginas/1/imagem"
    )

    assert resposta.status_code == 409


def test_detalhe_informa_se_os_arquivos_ainda_existem(cliente):
    identificador = primeiro_lote(cliente)
    assert cliente.get(f"/api/lotes/{identificador}").json()["arquivos_disponiveis"]

    cliente.delete(f"/api/lotes/{identificador}/arquivos")

    assert not cliente.get(f"/api/lotes/{identificador}").json()["arquivos_disponiveis"]


def test_envios_em_rajada_sao_barrados(tmp_path, executor):
    with montar(tmp_path, executor, envios_por_minuto=1) as cliente:
        assert cliente.post("/api/lotes", files=envio()).status_code == 201

        resposta = cliente.post("/api/lotes", files=envio())

        assert resposta.status_code == 429
