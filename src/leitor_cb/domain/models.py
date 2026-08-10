"""Entidades e objetos de valor do domínio."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .digito_verificador import (
    MODULO_10,
    MODULO_11_ARRECADACAO,
    MODULO_11_COBRANCA,
    CalculadoraDV,
)
from .excecoes import CodigoInvalidoError

TAMANHO_CODIGO_BARRAS = 44
TAMANHO_LINHA_COBRANCA = 47
TAMANHO_LINHA_ARRECADACAO = 48

# 3º dígito do código de arrecadação: identificação de valor efetivo ou
# referência. 6 e 7 usam Módulo 10; 8 e 9 usam Módulo 11.
IDENTIFICADORES_MODULO_10 = frozenset({"6", "7"})
IDENTIFICADORES_MODULO_11 = frozenset({"8", "9"})
IDENTIFICADORES_VALIDOS = IDENTIFICADORES_MODULO_10 | IDENTIFICADORES_MODULO_11


class TipoDocumento(StrEnum):
    COBRANCA = "cobranca"
    ARRECADACAO = "arrecadacao"
    PIX = "pix"


class StatusLeitura(StrEnum):
    SUCESSO = "sucesso"
    SEM_CODIGO = "sem_codigo"
    CODIGO_INVALIDO = "codigo_invalido"
    ERRO = "erro"


@dataclass(frozen=True)
class CodigoBarras:
    """Os 44 dígitos lidos do código de barras, já validados quanto ao formato."""

    digitos: str

    def __post_init__(self) -> None:
        if len(self.digitos) != TAMANHO_CODIGO_BARRAS or not self.digitos.isdigit():
            raise CodigoInvalidoError(
                f"O código de barras deve ter {TAMANHO_CODIGO_BARRAS} dígitos numéricos "
                f"(lido: {self.digitos!r}, {len(self.digitos)} caracteres)."
            )

    @property
    def tipo(self) -> TipoDocumento:
        """Guias e contas de consumo começam com 8; o resto é boleto bancário."""
        if self.digitos.startswith("8"):
            return TipoDocumento.ARRECADACAO
        return TipoDocumento.COBRANCA

    @property
    def identificador_valor(self) -> str:
        """3º dígito — só tem significado em arrecadação."""
        return self.digitos[2]

    @property
    def identificador_valor_valido(self) -> bool:
        """Só restringe arrecadação — em cobrança o 3º dígito não tem esse papel.

        Fora de 6/7/8/9 não dá para saber qual Módulo o emissor usou: a
        `calculadora_arrecadacao` chuta o de 11, e o DV geral passa a ser
        conferido pelo mesmo chute — logo, não detecta o próprio erro. Daí a
        checagem precisar ser explícita.
        """
        return (
            self.tipo is not TipoDocumento.ARRECADACAO
            or self.identificador_valor in IDENTIFICADORES_VALIDOS
        )

    @property
    def calculadora_arrecadacao(self) -> CalculadoraDV:
        if self.identificador_valor in IDENTIFICADORES_MODULO_10:
            return MODULO_10
        return MODULO_11_ARRECADACAO

    @property
    def dv_geral(self) -> str:
        """DV geral do código: 4ª posição em arrecadação, 5ª em cobrança."""
        if self.tipo is TipoDocumento.ARRECADACAO:
            return self.digitos[3]
        return self.digitos[4]

    def dv_geral_confere(self) -> bool:
        """Recalcula o DV geral sobre os outros 43 dígitos e compara com o lido.

        Serve de rede de proteção contra leitura óptica errada — um dígito
        trocado quase sempre quebra essa conferência.
        """
        if self.tipo is TipoDocumento.ARRECADACAO:
            base = self.digitos[:3] + self.digitos[4:]
            calculadora = self.calculadora_arrecadacao
        else:
            base = self.digitos[:4] + self.digitos[5:]
            calculadora = MODULO_11_COBRANCA

        return calculadora.calcular(base) == self.dv_geral

    def motivo_de_desconfianca(self) -> str | None:
        """Por que esta leitura não merece confiança, ou None se estiver coerente.

        Consultivo, como o `dv_geral_confere`: quem chama sinaliza a linha para
        conferência manual, nunca a descarta.
        """
        if not self.identificador_valor_valido:
            return (
                f"Identificador de valor '{self.identificador_valor}' fora do "
                "padrão (esperado 6, 7, 8 ou 9)"
            )
        if not self.dv_geral_confere():
            return "DV geral não confere"
        return None

    def __str__(self) -> str:
        return self.digitos


@dataclass(frozen=True)
class LinhaDigitavel:
    """Linha digitável pronta: 47 dígitos em cobrança, 48 em arrecadação.

    Guarda sempre os dígitos crus — é essa forma que se cola no internet
    banking. A máscara com pontos e espaços é só apresentação.
    """

    digitos: str
    tipo: TipoDocumento

    def formatada(self) -> str:
        """Aplica a máscara de exibição do respectivo padrão."""
        if self.tipo is TipoDocumento.ARRECADACAO:
            blocos = [self.digitos[i : i + 12] for i in range(0, len(self.digitos), 12)]
            return " ".join(f"{bloco[:11]}-{bloco[11:]}" for bloco in blocos)

        d = self.digitos
        return (
            f"{d[0:5]}.{d[5:10]} "
            f"{d[10:15]}.{d[15:21]} "
            f"{d[21:26]}.{d[26:32]} "
            f"{d[32]} "
            f"{d[33:47]}"
        )

    def __str__(self) -> str:
        return self.digitos


@dataclass(frozen=True)
class PixPayload:
    """Conteúdo copia-e-cola de um QR Code PIX, repassado sem interpretação."""

    texto: str

    def __str__(self) -> str:
        return self.texto


@dataclass(frozen=True)
class ResultadoLeitura:
    """O que foi extraído de uma página. É a linha do relatório final."""

    arquivo: str
    pagina: int
    status: StatusLeitura
    tipo: TipoDocumento | None = None
    codigo_barras: str = ""
    linha_digitavel: str = ""
    dv_ok: bool | None = None
    observacao: str = ""

    @classmethod
    def de_boleto(
        cls,
        arquivo: str,
        pagina: int,
        codigo: CodigoBarras,
        linha: LinhaDigitavel,
    ) -> ResultadoLeitura:
        motivo = codigo.motivo_de_desconfianca()
        return cls(
            arquivo=arquivo,
            pagina=pagina,
            status=StatusLeitura.SUCESSO,
            tipo=codigo.tipo,
            codigo_barras=codigo.digitos,
            linha_digitavel=linha.digitos,
            dv_ok=motivo is None,
            observacao="" if motivo is None else f"{motivo} — conferir manualmente",
        )

    @classmethod
    def de_pix(cls, arquivo: str, pagina: int, payload: PixPayload) -> ResultadoLeitura:
        return cls(
            arquivo=arquivo,
            pagina=pagina,
            status=StatusLeitura.SUCESSO,
            tipo=TipoDocumento.PIX,
            linha_digitavel=payload.texto,
        )

    @classmethod
    def sem_codigo(cls, arquivo: str, pagina: int) -> ResultadoLeitura:
        return cls(
            arquivo=arquivo,
            pagina=pagina,
            status=StatusLeitura.SEM_CODIGO,
            observacao="Nenhum código encontrado na página",
        )

    @classmethod
    def invalido(
        cls, arquivo: str, pagina: int, texto_lido: str, motivo: str
    ) -> ResultadoLeitura:
        return cls(
            arquivo=arquivo,
            pagina=pagina,
            status=StatusLeitura.CODIGO_INVALIDO,
            codigo_barras=texto_lido,
            observacao=motivo,
        )

    @classmethod
    def erro(cls, arquivo: str, pagina: int, motivo: str) -> ResultadoLeitura:
        return cls(
            arquivo=arquivo,
            pagina=pagina,
            status=StatusLeitura.ERRO,
            observacao=motivo,
        )

    @property
    def exige_atencao(self) -> bool:
        """Linhas que o operador precisa olhar antes de pagar."""
        return self.status is not StatusLeitura.SUCESSO or self.dv_ok is False
