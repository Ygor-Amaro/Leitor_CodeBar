"""Persistência dos lotes. Banco em `tmp_path`, nunca em `data/`."""

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta

from conftest import leitura_boleto, leitura_sem_codigo

from leitor_cb.domain import DocumentoDoLote, EstadoLote, Lote, StatusLeitura
from leitor_cb.services import RepositorioSqlite

AGORA = datetime(2026, 8, 10, 9, 30)


def novo_lote(identificador: str = "lote1", total: int = 2) -> Lote:
    return Lote(
        identificador=identificador,
        criado_em=AGORA,
        estado=EstadoLote.PENDENTE,
        total_documentos=total,
    )


def repositorio(tmp_path) -> RepositorioSqlite:
    return RepositorioSqlite(tmp_path / "banco" / "teste.sqlite3")


def test_cria_o_banco_e_a_pasta(tmp_path):
    repo = repositorio(tmp_path)
    assert (tmp_path / "banco" / "teste.sqlite3").exists()
    assert repo.listar() == []


def test_guarda_e_recupera_o_lote(tmp_path):
    repo = repositorio(tmp_path)
    repo.criar(novo_lote())

    recuperado = repo.obter("lote1")

    assert recuperado == novo_lote()


def test_lote_inexistente_devolve_none(tmp_path):
    assert repositorio(tmp_path).obter("nao-existe") is None


def test_atualizar_publica_o_novo_estado(tmp_path):
    repo = repositorio(tmp_path)
    repo.criar(novo_lote())

    repo.atualizar(
        replace(
            novo_lote(),
            estado=EstadoLote.CONCLUIDO,
            documentos_processados=2,
            nome_csv="lote_abc.csv",
        )
    )

    recuperado = repo.obter("lote1")
    assert recuperado.estado is EstadoLote.CONCLUIDO
    assert recuperado.documentos_processados == 2
    assert recuperado.nome_csv == "lote_abc.csv"


def test_leituras_saem_ordenadas_por_documento_e_pagina(tmp_path):
    """Ordem de exibição, não de gravação: uma página corrigida à mão é
    reinserida depois e ainda assim precisa aparecer no lugar dela."""
    repo = repositorio(tmp_path)
    repo.criar(novo_lote())

    repo.acrescentar_resultados("lote1", 2, [leitura_boleto("b.pdf")])
    repo.acrescentar_resultados("lote1", 1, [leitura_sem_codigo("a.pdf", pagina=2)])
    repo.acrescentar_resultados("lote1", 1, [leitura_boleto("a.pdf")])

    leituras = repo.leituras_de("lote1")

    posicoes = [(leitura.documento_indice, leitura.resultado.pagina) for leitura in leituras]
    assert posicoes == [(1, 1), (1, 2), (2, 1)]


def test_leitura_guarda_de_qual_documento_veio(tmp_path):
    repo = repositorio(tmp_path)
    repo.criar(novo_lote())
    repo.acrescentar_resultados("lote1", 7, [leitura_boleto()])

    (leitura,) = repo.leituras_de("lote1")

    assert leitura.documento_indice == 7


def test_resultado_atravessa_o_banco_sem_perder_campo(tmp_path):
    """dv_ok é booleano-ou-nulo e tipo é enum-ou-nulo: os dois já se perderam em
    round-trip antes, e é o que esta asserção protege."""
    repo = repositorio(tmp_path)
    repo.criar(novo_lote())
    repo.acrescentar_resultados("lote1", 1, [leitura_boleto(dv_ok=False), leitura_sem_codigo()])

    boleto, sem_codigo = (leitura.resultado for leitura in repo.leituras_de("lote1"))

    assert boleto.dv_ok is False
    assert boleto.tipo is not None
    assert sem_codigo.dv_ok is None
    assert sem_codigo.tipo is None


def test_gravar_lista_vazia_nao_faz_nada(tmp_path):
    repo = repositorio(tmp_path)
    repo.criar(novo_lote())

    repo.acrescentar_resultados("lote1", 1, [])

    assert repo.leituras_de("lote1") == []


def test_resumo_conta_sucessos_e_pendencias(tmp_path):
    repo = repositorio(tmp_path)
    repo.criar(novo_lote())
    repo.acrescentar_resultados(
        "lote1",
        1,
        [
            leitura_boleto(dv_ok=True),  # sucesso, sem pendência
            leitura_boleto(dv_ok=False),  # sucesso, mas exige conferência
            leitura_sem_codigo(),  # nem sucesso nem código
        ],
    )

    resumo = repo.resumos_de(["lote1"])["lote1"]

    assert resumo.total == 3
    assert resumo.sucessos == 2
    assert resumo.pendencias == 2


def test_resumo_de_lote_sem_leitura_vem_zerado(tmp_path):
    """Lote sem linha nenhuma some do GROUP BY; quem chama não deve ter que saber."""
    repo = repositorio(tmp_path)
    repo.criar(novo_lote())

    resumos = repo.resumos_de(["lote1"])

    assert resumos["lote1"].total == 0


def test_resumos_de_varios_lotes_em_uma_chamada(tmp_path):
    repo = repositorio(tmp_path)
    repo.criar(novo_lote("um"))
    repo.criar(novo_lote("dois"))
    repo.acrescentar_resultados("um", 1, [leitura_boleto()])
    repo.acrescentar_resultados("dois", 1, [leitura_sem_codigo(), leitura_sem_codigo()])

    resumos = repo.resumos_de(["um", "dois"])

    assert resumos["um"].total == 1
    assert resumos["dois"].pendencias == 2


def test_resumos_sem_identificadores(tmp_path):
    assert repositorio(tmp_path).resumos_de([]) == {}


def test_listar_traz_o_mais_recente_primeiro(tmp_path):
    repo = repositorio(tmp_path)
    repo.criar(replace(novo_lote("antigo"), criado_em=AGORA - timedelta(hours=1)))
    repo.criar(novo_lote("recente"))

    assert [lote.identificador for lote in repo.listar()] == ["recente", "antigo"]


def test_documentos_guardam_o_nome_de_origem(tmp_path):
    repo = repositorio(tmp_path)
    repo.criar(novo_lote())

    repo.registrar_documentos(
        "lote1",
        [
            DocumentoDoLote(indice=1, nome_original="Boleto Luz.pdf"),
            DocumentoDoLote(indice=2, nome_original="Água.pdf"),
        ],
    )

    assert [d.nome_original for d in repo.documentos_de("lote1")] == [
        "Boleto Luz.pdf",
        "Água.pdf",
    ]


def test_substituir_pagina_troca_so_aquela_pagina(tmp_path):
    """O recorte manual é a palavra final sobre a página — mas só sobre ela."""
    repo = repositorio(tmp_path)
    repo.criar(novo_lote())
    repo.acrescentar_resultados(
        "lote1",
        1,
        [leitura_sem_codigo("a.pdf", pagina=1), leitura_sem_codigo("a.pdf", pagina=2)],
    )
    repo.acrescentar_resultados("lote1", 2, [leitura_sem_codigo("b.pdf", pagina=1)])

    repo.substituir_pagina("lote1", 1, 1, [leitura_boleto("a.pdf")])

    leituras = repo.leituras_de("lote1")
    documento_um = [
        leitura
        for leitura in leituras
        if leitura.documento_indice == 1 and leitura.resultado.pagina == 1
    ]
    assert len(documento_um) == 1
    assert documento_um[0].resultado.status is StatusLeitura.SUCESSO
    # A outra página do mesmo documento e o outro documento seguem intactos.
    assert len(leituras) == 3


def test_substituir_pagina_atualiza_o_resumo(tmp_path):
    repo = repositorio(tmp_path)
    repo.criar(novo_lote())
    repo.acrescentar_resultados("lote1", 1, [leitura_sem_codigo("a.pdf", pagina=1)])

    repo.substituir_pagina("lote1", 1, 1, [leitura_boleto("a.pdf")])

    assert repo.resumos_de(["lote1"])["lote1"].pendencias == 0


def test_banco_antigo_ganha_a_coluna_de_documento(tmp_path):
    """Um banco da versão sem recorte manual precisa continuar abrindo."""
    caminho = tmp_path / "antigo.sqlite3"
    with sqlite3.connect(caminho) as conexao:
        conexao.execute(
            "CREATE TABLE resultados (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "lote_id TEXT NOT NULL, arquivo TEXT NOT NULL, pagina INTEGER NOT NULL, "
            "status TEXT NOT NULL, tipo TEXT, codigo_barras TEXT NOT NULL DEFAULT '', "
            "linha_digitavel TEXT NOT NULL DEFAULT '', dv_ok INTEGER, "
            "observacao TEXT NOT NULL DEFAULT '', exige_atencao INTEGER NOT NULL DEFAULT 0)"
        )

    repo = RepositorioSqlite(caminho)
    repo.criar(novo_lote())
    repo.acrescentar_resultados("lote1", 1, [leitura_boleto()])

    assert repo.leituras_de("lote1")[0].documento_indice == 1


def test_listar_respeita_o_limite(tmp_path):
    repo = repositorio(tmp_path)
    for indice in range(5):
        repo.criar(replace(novo_lote(f"lote{indice}"), criado_em=AGORA + timedelta(minutes=indice)))

    assert len(repo.listar(limite=2)) == 2
