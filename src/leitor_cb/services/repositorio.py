"""Persistência dos lotes e das leituras.

A CLI processava e esquecia; a web precisa responder "o que eu enviei ontem?".

`RepositorioLotes` é a porta — quem chama nunca sabe que existe SQLite. Trocar por
Postgres é escrever outra implementação do mesmo contrato.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ..domain.lotes import DocumentoDoLote, EstadoLote, LeituraDoLote, Lote, ResumoLote
from ..domain.models import ResultadoLeitura, StatusLeitura, TipoDocumento

ESQUEMA = """
CREATE TABLE IF NOT EXISTS lotes (
    id                     TEXT    PRIMARY KEY,
    criado_em              TEXT    NOT NULL,
    estado                 TEXT    NOT NULL,
    total_documentos       INTEGER NOT NULL,
    documentos_processados INTEGER NOT NULL DEFAULT 0,
    nome_csv               TEXT    NOT NULL DEFAULT '',
    observacao             TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS documentos (
    lote_id       TEXT    NOT NULL REFERENCES lotes(id) ON DELETE CASCADE,
    indice        INTEGER NOT NULL,
    nome_original TEXT    NOT NULL,
    PRIMARY KEY (lote_id, indice)
);

CREATE TABLE IF NOT EXISTS resultados (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lote_id         TEXT    NOT NULL REFERENCES lotes(id) ON DELETE CASCADE,
    -- Qual dos arquivos gerou a linha: é por ele que a tela reabre a página para
    -- o recorte manual. O nome não serve, pode repetir.
    documento_indice INTEGER NOT NULL DEFAULT 1,
    arquivo         TEXT    NOT NULL,
    pagina          INTEGER NOT NULL,
    status          TEXT    NOT NULL,
    tipo            TEXT,
    codigo_barras   TEXT    NOT NULL DEFAULT '',
    linha_digitavel TEXT    NOT NULL DEFAULT '',
    dv_ok           INTEGER,
    observacao      TEXT    NOT NULL DEFAULT '',
    -- Gravado a partir de `ResultadoLeitura.exige_atencao`. Reescrever a regra em
    -- SQL faria a contagem da tela divergir do relatório quando ela mudasse.
    exige_atencao   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_resultados_lote ON resultados(lote_id, id);
"""


class RepositorioLotes(Protocol):
    """Porta de persistência dos lotes."""

    def criar(self, lote: Lote) -> None: ...

    def atualizar(self, lote: Lote) -> None: ...

    def obter(self, identificador: str) -> Lote | None: ...

    def listar(self, limite: int = 50) -> list[Lote]: ...

    def registrar_documentos(
        self, identificador: str, documentos: Sequence[DocumentoDoLote]
    ) -> None: ...

    def documentos_de(self, identificador: str) -> list[DocumentoDoLote]: ...

    def acrescentar_resultados(
        self,
        identificador: str,
        documento_indice: int,
        resultados: Sequence[ResultadoLeitura],
    ) -> None: ...

    def substituir_pagina(
        self,
        identificador: str,
        documento_indice: int,
        pagina: int,
        resultados: Sequence[ResultadoLeitura],
    ) -> None: ...

    def leituras_de(self, identificador: str) -> list[LeituraDoLote]: ...

    def resumos_de(self, identificadores: Sequence[str]) -> dict[str, ResumoLote]: ...


class RepositorioSqlite:
    """Implementação em SQLite, um arquivo em `data/`.

    Uma conexão por operação: o worker roda em outra thread e conexão de SQLite
    não atravessa thread com segurança. WAL para a tela ler enquanto ele grava.
    """

    def __init__(self, caminho: Path) -> None:
        self._caminho = Path(caminho)
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._conectar() as conexao:
            conexao.executescript(ESQUEMA)
            _migrar(conexao)

    @contextmanager
    def _conectar(self) -> Iterator[sqlite3.Connection]:
        conexao = sqlite3.connect(self._caminho, timeout=15.0)
        conexao.row_factory = sqlite3.Row
        try:
            conexao.execute("PRAGMA journal_mode=WAL")
            conexao.execute("PRAGMA foreign_keys=ON")
            with conexao:  # commit no sucesso, rollback na exceção
                yield conexao
        finally:
            conexao.close()

    def criar(self, lote: Lote) -> None:
        with self._conectar() as conexao:
            conexao.execute(
                "INSERT INTO lotes (id, criado_em, estado, total_documentos, "
                "documentos_processados, nome_csv, observacao) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    lote.identificador,
                    lote.criado_em.isoformat(),
                    lote.estado.value,
                    lote.total_documentos,
                    lote.documentos_processados,
                    lote.nome_csv,
                    lote.observacao,
                ),
            )

    def atualizar(self, lote: Lote) -> None:
        with self._conectar() as conexao:
            conexao.execute(
                "UPDATE lotes SET estado = ?, total_documentos = ?, "
                "documentos_processados = ?, nome_csv = ?, observacao = ? WHERE id = ?",
                (
                    lote.estado.value,
                    lote.total_documentos,
                    lote.documentos_processados,
                    lote.nome_csv,
                    lote.observacao,
                    lote.identificador,
                ),
            )

    def obter(self, identificador: str) -> Lote | None:
        with self._conectar() as conexao:
            linha = conexao.execute(
                "SELECT * FROM lotes WHERE id = ?", (identificador,)
            ).fetchone()
        return _para_lote(linha) if linha is not None else None

    def listar(self, limite: int = 50) -> list[Lote]:
        with self._conectar() as conexao:
            linhas = conexao.execute(
                "SELECT * FROM lotes ORDER BY criado_em DESC, id DESC LIMIT ?",
                (max(1, limite),),
            ).fetchall()
        return [_para_lote(linha) for linha in linhas]

    def registrar_documentos(
        self, identificador: str, documentos: Sequence[DocumentoDoLote]
    ) -> None:
        if not documentos:
            return

        with self._conectar() as conexao:
            conexao.executemany(
                "INSERT OR REPLACE INTO documentos (lote_id, indice, nome_original) "
                "VALUES (?, ?, ?)",
                [
                    (identificador, documento.indice, documento.nome_original)
                    for documento in documentos
                ],
            )

    def documentos_de(self, identificador: str) -> list[DocumentoDoLote]:
        with self._conectar() as conexao:
            linhas = conexao.execute(
                "SELECT indice, nome_original FROM documentos WHERE lote_id = ? "
                "ORDER BY indice",
                (identificador,),
            ).fetchall()
        return [
            DocumentoDoLote(indice=linha["indice"], nome_original=linha["nome_original"])
            for linha in linhas
        ]

    def acrescentar_resultados(
        self,
        identificador: str,
        documento_indice: int,
        resultados: Sequence[ResultadoLeitura],
    ) -> None:
        """Grava em bloco, um documento por vez: uma transação por linha faria o
        disco ditar o ritmo do lote."""
        if not resultados:
            return

        with self._conectar() as conexao:
            self._inserir(conexao, identificador, documento_indice, resultados)

    def substituir_pagina(
        self,
        identificador: str,
        documento_indice: int,
        pagina: int,
        resultados: Sequence[ResultadoLeitura],
    ) -> None:
        """Troca todas as linhas de uma página pelas novas.

        O recorte manual é a palavra final sobre a página: sem apagar antes, a
        pendência antiga ficaria ao lado da leitura corrigida. Na mesma transação
        para que uma falha no meio não deixe a página sem linha nenhuma.
        """
        with self._conectar() as conexao:
            conexao.execute(
                "DELETE FROM resultados WHERE lote_id = ? AND documento_indice = ? "
                "AND pagina = ?",
                (identificador, documento_indice, pagina),
            )
            self._inserir(conexao, identificador, documento_indice, resultados)

    @staticmethod
    def _inserir(
        conexao: sqlite3.Connection,
        identificador: str,
        documento_indice: int,
        resultados: Sequence[ResultadoLeitura],
    ) -> None:
        conexao.executemany(
            "INSERT INTO resultados (lote_id, documento_indice, arquivo, pagina, "
            "status, tipo, codigo_barras, linha_digitavel, dv_ok, observacao, "
            "exige_atencao) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    identificador,
                    documento_indice,
                    resultado.arquivo,
                    resultado.pagina,
                    resultado.status.value,
                    resultado.tipo.value if resultado.tipo else None,
                    resultado.codigo_barras,
                    resultado.linha_digitavel,
                    None if resultado.dv_ok is None else int(resultado.dv_ok),
                    resultado.observacao,
                    int(resultado.exige_atencao),
                )
                for resultado in resultados
            ],
        )

    def leituras_de(self, identificador: str) -> list[LeituraDoLote]:
        with self._conectar() as conexao:
            linhas = conexao.execute(
                "SELECT * FROM resultados WHERE lote_id = ? "
                "ORDER BY documento_indice, pagina, id",
                (identificador,),
            ).fetchall()
        return [
            LeituraDoLote(
                documento_indice=linha["documento_indice"],
                resultado=_para_resultado(linha),
            )
            for linha in linhas
        ]

    def resumos_de(self, identificadores: Sequence[str]) -> dict[str, ResumoLote]:
        """Contagens de vários lotes em uma consulta só — um SELECT por lote seria
        o N+1 clássico: 50 idas ao banco para desenhar 50 linhas."""
        if not identificadores:
            return {}

        marcadores = ",".join("?" for _ in identificadores)
        with self._conectar() as conexao:
            linhas = conexao.execute(
                f"SELECT lote_id, COUNT(*) AS total, "  # noqa: S608 - marcadores são '?'
                f"SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS sucessos, "
                f"SUM(exige_atencao) AS pendencias "
                f"FROM resultados WHERE lote_id IN ({marcadores}) GROUP BY lote_id",
                (StatusLeitura.SUCESSO.value, *identificadores),
            ).fetchall()

        resumos = {
            linha["lote_id"]: ResumoLote(
                total=linha["total"] or 0,
                sucessos=linha["sucessos"] or 0,
                pendencias=linha["pendencias"] or 0,
            )
            for linha in linhas
        }
        # Lote sem linha nenhuma não aparece no GROUP BY; o resumo zerado poupa a
        # tela de saber disso.
        return {
            identificador: resumos.get(identificador, ResumoLote())
            for identificador in identificadores
        }


def _migrar(conexao: sqlite3.Connection) -> None:
    """Acerta bancos criados por versões anteriores.

    `CREATE TABLE IF NOT EXISTS` não acrescenta coluna a tabela existente: um
    banco anterior ao recorte manual subiria sem `documento_indice` e quebraria
    na primeira consulta. O default 1 serve ao histórico antigo, que não o usava.
    """
    colunas = {
        linha["name"] for linha in conexao.execute("PRAGMA table_info(resultados)")
    }
    if "documento_indice" not in colunas:
        conexao.execute(
            "ALTER TABLE resultados ADD COLUMN documento_indice INTEGER NOT NULL DEFAULT 1"
        )


def _para_lote(linha: sqlite3.Row) -> Lote:
    return Lote(
        identificador=linha["id"],
        criado_em=datetime.fromisoformat(linha["criado_em"]),
        estado=EstadoLote(linha["estado"]),
        total_documentos=linha["total_documentos"],
        documentos_processados=linha["documentos_processados"],
        nome_csv=linha["nome_csv"],
        observacao=linha["observacao"],
    )


def _para_resultado(linha: sqlite3.Row) -> ResultadoLeitura:
    return ResultadoLeitura(
        arquivo=linha["arquivo"],
        pagina=linha["pagina"],
        status=StatusLeitura(linha["status"]),
        tipo=TipoDocumento(linha["tipo"]) if linha["tipo"] else None,
        codigo_barras=linha["codigo_barras"],
        linha_digitavel=linha["linha_digitavel"],
        dv_ok=None if linha["dv_ok"] is None else bool(linha["dv_ok"]),
        observacao=linha["observacao"],
    )
